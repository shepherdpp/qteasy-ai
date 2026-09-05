# coding=utf-8
# ======================================
# File: intent_engine.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-02
# Desc:
# 方案 H′ 意图门：宪法先跑；Mode-R
# 仅 1 命中；Mode-D 只信 LLM 协议。
# ======================================

"""Hybrid Planner 意图分类引擎。

分类只输出 Job id 与 flags，不选择扁平 skill 菜单、不产出 steps。
宪法级约束写死在本模块，Catalog 不能覆盖。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, NamedTuple, Optional, Set

from .intents import IntentCatalog, IntentDecision, load_default_catalog
from .provider import BaseLLMProvider

HIGH_RISK_JOBS = frozenset(
    {"data.refill", "backtest.builtin", "optimize.builtin", "live.plan_only"}
)
INSIGHT_FLAG_HINTS = (
    "年化",
    "最大回撤",
    "解读",
    "归因",
    "summarize",
    "annual",
    "mdd",
)
READ_CHANNEL_HINTS = (
    ("static", ("get_static_data", "静态数据", "static data")),
    ("reference", ("get_reference_data", "参考数据", "reference data", "宏观")),
    ("history", ("get_history_data", "读取历史", "history data")),
)

_LLM_JOB_SYSTEM = (
    "You classify a qteasy-ai user query into Job id(s). "
    "Reply with JSON only. Legal shapes: "
    '{"job": "<id>", "uncertain": false}, '
    '{"job": "<id>", "uncertain": true}, '
    '{"jobs": ["<id>"]}, '
    '{"jobs": ["<id_a>", "<id_b>"]}. '
    "Omit uncertain only when you are certain. "
    "If the query mixes two tasks, return jobs with more than one id "
    "instead of guessing one. "
    "Use only Job ids listed in the prompt. Do not output skill names or steps."
)

_MULTI_JOB_HINT = "Please focus on one task or split into two queries."


class _LlmParse(NamedTuple):
    """分类 LLM 协议解析结果。"""

    kind: str
    job: str


def normalize_query_text(query: str) -> str:
    """归一查询文本（空白、破折号），供 gold 精确匹配。"""

    text = (query or "").strip()
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    return text


class IntentEngine:
    """方案 H′ 分类器：宪法 → Mode-R 规则 / Mode-D LLM。"""

    def __init__(
        self,
        catalog: Optional[IntentCatalog] = None,
        provider: Optional[BaseLLMProvider] = None,
    ) -> None:
        self.catalog = catalog or load_default_catalog()
        self.provider = provider
        self._gold_index = {
            normalize_query_text(str(item.get("query") or "")): item
            for item in self.catalog.gold_cases()
            if item.get("query")
        }

    def classify(self, query: str) -> IntentDecision:
        """将单句 query 分类为 Job。

        Parameters
        ----------
        query : str
            用户自然语言。

        Returns
        -------
        IntentDecision
            job / flags / source / rationale。
        """

        raw = (query or "").strip()
        q_lower = raw.lower()
        official = set(self.catalog.official_ids)
        allowed_llm = set(self.catalog.official_ids) | {"open", "clarify", "route_to_ask"}

        constitution = self._constitution(raw, q_lower)
        if constitution is not None:
            return constitution

        if self.provider is not None:
            return self._llm_classify(raw, allowed_llm)

        gold = self._gold_index.get(normalize_query_text(raw))
        if gold and gold.get("lock"):
            flags = dict(gold.get("flags") or {})
            flags.update(self._flags_for(str(gold.get("job")), raw, q_lower))
            return IntentDecision(
                job=str(gold.get("job")),
                flags=flags,
                source="rule",
                rationale=f"gold_lock:{gold.get('id')}",
                llm_called=False,
            )

        hits = self._trigger_hits(raw, q_lower)
        hits.discard("unsafe")
        if len(hits) == 1:
            job = next(iter(hits))
            if job not in official and job not in {"route_to_ask"}:
                job = "clarify"
            return IntentDecision(
                job=job,
                flags=self._flags_for(job, raw, q_lower),
                source="rule",
                rationale="single_trigger",
            )
        rationale = "zero_trigger_hit" if not hits else "multi_trigger_hit"
        return IntentDecision(
            job="clarify",
            source="rule",
            rationale=f"{rationale}:no_provider",
        )

    def _constitution(self, query: str, q_lower: str) -> Optional[IntentDecision]:
        """宪法：unsafe / 显式不支持 / 多高风险 / 实盘永不 auto。"""

        if self._is_unsafe(query, q_lower):
            return IntentDecision(
                job="unsafe",
                source="rule",
                rationale="constitution_unsafe",
            )
        unsupported = self._match_unsupported(query, q_lower)
        if unsupported:
            return IntentDecision(
                job="not_supported",
                source="rule",
                rationale=str(unsupported),
            )

        hits = self._trigger_hits(query, q_lower)
        hits.discard("unsafe")
        high_risk = set(hits) & set(HIGH_RISK_JOBS)
        if "strategy.builder" in hits:
            high_risk.discard("backtest.builtin")
        if len(high_risk) >= 2:
            return IntentDecision(
                job="clarify",
                source="rule",
                rationale="multi_high_risk_intent",
            )
        if "live.plan_only" in hits:
            return IntentDecision(
                job="live.plan_only",
                source="rule",
                rationale="live_never_auto",
            )
        return None

    def _llm_classify(self, query: str, allowed: Set[str]) -> IntentDecision:
        """Mode-D：只信 LLM 协议；唯一合法且确定才接受。"""

        parsed = self._ask_llm_job(query, allowed)
        if parsed.kind == "accept":
            return IntentDecision(
                job=parsed.job,
                flags=self._flags_for(parsed.job, query, query.lower()),
                source="llm",
                rationale="llm_certain",
                llm_called=True,
            )
        if parsed.kind == "uncertain":
            return IntentDecision(
                job="clarify",
                source="rule",
                rationale="llm_uncertain",
                llm_called=True,
            )
        if parsed.kind == "multi":
            return IntentDecision(
                job="clarify",
                source="rule",
                rationale=f"llm_multi_job:{_MULTI_JOB_HINT}",
                llm_called=True,
            )
        return IntentDecision(
            job="clarify",
            source="rule",
            rationale="illegal_llm_job",
            llm_called=True,
        )

    def _ask_llm_job(self, query: str, allowed: Set[str]) -> _LlmParse:
        """调用 Provider，按 H′ 协议解析 Job / uncertain / jobs。"""

        lines = "\n".join(self.catalog.job_summaries())
        prompt = (
            "Official and system Job ids:\n"
            f"{lines}\n\n"
            f"User query:\n{query}\n"
        )
        try:
            raw = self.provider.chat(prompt, system_prompt=_LLM_JOB_SYSTEM)
        except Exception:
            return _LlmParse("illegal", "")
        return _parse_llm_job_payload(raw, allowed)

    def _is_unsafe(self, query: str, q_lower: str) -> bool:
        """宪法：shell / 跳过确认。"""

        for trigger in self.catalog.triggers_doc.get("triggers") or []:
            if str(trigger.get("job")) != "unsafe":
                continue
            if _trigger_match(query, q_lower, trigger):
                return True
        return False

    def _match_unsupported(self, query: str, q_lower: str) -> str:
        """显式不支持模式。"""

        for pattern in self.catalog.unsupported_doc.get("patterns") or []:
            fake = {
                "any": pattern.get("any") or [],
                "all": pattern.get("all") or [],
                "regex": pattern.get("regex") or "",
            }
            if _trigger_match(query, q_lower, fake):
                return str(pattern.get("reason") or "not_supported")
        return ""

    def _trigger_hits(self, query: str, q_lower: str) -> Set[str]:
        """返回命中的 Job id 集合。"""

        hits: Set[str] = set()
        for trigger in self.catalog.triggers_doc.get("triggers") or []:
            job = str(trigger.get("job") or "")
            if not job or job == "unsafe":
                continue
            if _trigger_match(query, q_lower, trigger):
                hits.add(job)
        return hits

    def _apply_conflicts(self, hits: Set[str]) -> tuple:
        """冲突表消歧（H′ 停用；conflicts.json 仍由 Catalog 加载）。"""

        remaining = set(hits)
        rationale = ""
        for pair in self.catalog.conflicts_doc.get("pairs") or []:
            jobs = set(pair.get("jobs") or [])
            winner = str(pair.get("winner") or "")
            if len(jobs) < 2 or not winner:
                continue
            if jobs <= remaining:
                remaining = (remaining - jobs) | {winner}
                rationale = str(pair.get("rationale") or "tiebreak")
        if len(remaining) == 1:
            return next(iter(remaining)), rationale
        return "", ""

    @staticmethod
    def _flags_for(job: str, query: str, q_lower: str) -> Dict[str, Any]:
        """规则填 flags，分类 LLM 不出 DAG。"""

        flags: Dict[str, Any] = {}
        if job == "backtest.builtin" and any(item in q_lower for item in INSIGHT_FLAG_HINTS):
            flags["with_insight"] = True
        if job == "strategy.builder" and any(item in q_lower for item in ["回测", "backtest"]):
            flags["with_backtest"] = True
        if job == "data.read":
            flags["channel"] = "history"
            for channel, hints in READ_CHANNEL_HINTS:
                if any(hint in q_lower for hint in hints):
                    flags["channel"] = channel
                    break
        return flags


def _token_in(query: str, q_lower: str, token: str) -> bool:
    """子串命中（中英混合）。"""

    if not token:
        return False
    return token.lower() in q_lower or token in query


def _trigger_match(query: str, q_lower: str, trigger: Dict[str, Any]) -> bool:
    """any / all / regex / exclude_any。"""

    exclude = trigger.get("exclude_any") or []
    if any(_token_in(query, q_lower, str(item)) for item in exclude):
        return False
    regex = str(trigger.get("regex") or "").strip()
    if regex and re.search(regex, q_lower):
        return True
    any_tokens = [str(item) for item in (trigger.get("any") or [])]
    all_tokens = [str(item) for item in (trigger.get("all") or [])]
    if any_tokens and any(_token_in(query, q_lower, item) for item in any_tokens):
        return True
    if all_tokens and all(_token_in(query, q_lower, item) for item in all_tokens):
        return True
    return False


def _parse_llm_job_payload(text: str, allowed: Set[str]) -> _LlmParse:
    """解析 H′ 分类协议；steps / 非 dict / 未知 id / 空响应为非法。"""

    blob = (text or "").strip()
    if not blob:
        return _LlmParse("illegal", "")
    if blob.startswith("```"):
        blob = re.sub(r"^```(?:json)?", "", blob).strip()
        blob = re.sub(r"```$", "", blob).strip()
    try:
        payload = json.loads(blob)
    except json.JSONDecodeError:
        return _LlmParse("illegal", "")
    if not isinstance(payload, dict):
        return _LlmParse("illegal", "")
    if "steps" in payload:
        return _LlmParse("illegal", "")

    job = ""
    if "jobs" in payload:
        jobs = payload.get("jobs")
        if not isinstance(jobs, list) or any(not isinstance(item, str) for item in jobs):
            return _LlmParse("illegal", "")
        stripped = [item.strip() for item in jobs if item.strip()]
        if len(stripped) != 1:
            return _LlmParse("multi", "")
        job = stripped[0]
    else:
        raw_job = payload.get("job") or payload.get("job_id")
        if not isinstance(raw_job, str) or not raw_job.strip():
            return _LlmParse("illegal", "")
        job = raw_job.strip()

    if job not in allowed:
        return _LlmParse("illegal", "")
    if payload.get("uncertain") is True:
        return _LlmParse("uncertain", job)
    return _LlmParse("accept", job)
