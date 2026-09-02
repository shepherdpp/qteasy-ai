# coding=utf-8
# ======================================
# File: intent_engine.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-02
# Desc:
# 方案 H 意图门：规则锁 → 冲突表 →
# LLM 只出 Job ID。
# ======================================

"""Hybrid Planner 意图分类引擎。

分类只输出 Job id 与 flags，不选择扁平 skill 菜单、不产出 steps。
宪法级约束写死在本模块，Catalog 不能覆盖。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set

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
    "You classify a qteasy-ai user query into exactly one Job id. "
    "Reply with JSON only: {\"job\": \"<id>\"}. "
    "Use only Job ids listed in the prompt. Do not output skill names or steps."
)


def normalize_query_text(query: str) -> str:
    """归一查询文本（空白、破折号），供 gold 精确匹配。"""

    text = (query or "").strip()
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    return text


class IntentEngine:
    """方案 H 三步分类器。"""

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

        if self._is_unsafe(raw, q_lower):
            return IntentDecision(
                job="unsafe",
                source="rule",
                rationale="constitution_unsafe",
            )
        unsupported = self._match_unsupported(raw, q_lower)
        if unsupported:
            return IntentDecision(
                job="not_supported",
                source="rule",
                rationale=str(unsupported),
            )

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

        if not hits:
            return self._llm_or_clarify(raw, allowed_llm, rationale="zero_trigger_hit")

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

        winner, conflict_reason = self._apply_conflicts(hits)
        if winner:
            return IntentDecision(
                job=winner,
                flags=self._flags_for(winner, raw, q_lower),
                source="tiebreak",
                rationale=conflict_reason or "conflict_table",
            )
        return self._llm_or_clarify(raw, allowed_llm, rationale="uncovered_conflict")

    def _llm_or_clarify(
        self,
        query: str,
        allowed: Set[str],
        *,
        rationale: str,
    ) -> IntentDecision:
        """0 命中或冲突表未覆盖：有 Provider 则只出 Job ID。"""

        if self.provider is None:
            return IntentDecision(
                job="clarify",
                source="rule",
                rationale=f"{rationale}:no_provider",
            )
        job, parse_ok = self._ask_llm_job(query, allowed)
        if not parse_ok:
            return IntentDecision(
                job="clarify",
                source="rule",
                rationale=f"{rationale}:illegal_llm_job",
                llm_called=True,
            )
        return IntentDecision(
            job=job,
            flags=self._flags_for(job, query, query.lower()),
            source="llm",
            rationale=rationale,
            llm_called=True,
        )

    def _ask_llm_job(self, query: str, allowed: Set[str]) -> tuple:
        """调用 Provider，只解析 Job id。"""

        lines = "\n".join(self.catalog.job_summaries())
        prompt = (
            "Official and system Job ids:\n"
            f"{lines}\n\n"
            f"User query:\n{query}\n"
        )
        try:
            raw = self.provider.chat(prompt, system_prompt=_LLM_JOB_SYSTEM)
        except Exception:
            return "", False
        parsed = _parse_job_json(raw)
        if parsed is None or parsed not in allowed:
            return "", False
        return parsed, True

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
        """冲突表消歧；唯一赢家则返回。"""

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


def _parse_job_json(text: str) -> Optional[str]:
    """解析分类 LLM 输出；steps 菜单视为非法。"""

    blob = (text or "").strip()
    if not blob:
        return None
    if blob.startswith("```"):
        blob = re.sub(r"^```(?:json)?", "", blob).strip()
        blob = re.sub(r"```$", "", blob).strip()
    try:
        payload = json.loads(blob)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if "steps" in payload:
        return None
    job = payload.get("job") or payload.get("job_id")
    if not isinstance(job, str):
        return None
    return job.strip()
