# coding=utf-8
# ======================================
# File: open_workflow.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-10
# Desc:
# 开放环设计态：气质分叉、Spec 草稿、试错/回退、用户 KB。
# ======================================

"""开放环编排辅助。

系统 Job ``open``（E.0 合法边短 DAG）不是设计环。本模块只处理
Catalog ``workflow: open`` 与 ``flags.open_loop``。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .intents import IntentCatalog, IntentDecision

DESIGN_FORBIDDEN_SKILLS = frozenset(
    {
        "qt.ai.research.factor_ic_summary",
        "qt.ai.strategy.codegen_hybrid",
        "qt.ai.backtest.run_builtin",
        "qt.ai.optimize.run_builtin",
        "qt.ai.data.refill_basic_equity_and_index",
        "qt.ai.pipeline.live_trade_plan_only",
    }
)

_TRIAL_HINTS = (
    "try ic",
    "run ic",
    "factor ic",
    "试错",
    "跑一次 ic",
    "跑一下 ic",
    "试试这个",
    "propose trial",
    "try this factor",
)
_ABANDON_TRIAL_HINTS = (
    "abandon trial",
    "放弃这次试错",
    "放弃当前试错",
    "drop the trial",
)
_ABANDON_OPEN_HINTS = (
    "abandon open",
    "放弃整个开放",
    "放弃这个探索",
    "abandon this research",
    "drop the open job",
)
_LOCK_HINTS = (
    "就按这个来",
    "lock this spec",
    "save this note",
    "写入笔记",
    "write to user kb",
    "confirm kb write",
)
_BUILDER_TEMPLATE_HINTS = (
    "金叉",
    "死叉",
    "双均线",
    "均线交叉",
    "sma cross",
    "dual ma",
    "20/60",
    "20 / 60",
)


def is_system_open_job(job: str) -> bool:
    """是否 E.0 系统 Job ``open``（合法边 DAG）。"""

    return str(job or "").strip() == "open"


def is_design_loop(catalog: IntentCatalog, decision: IntentDecision) -> bool:
    """classify 之后是否进入设计环（不含系统 Job open）。"""

    if is_system_open_job(decision.job):
        return False
    if catalog.job_workflow(decision.job) == "open":
        return True
    return bool((decision.flags or {}).get("open_loop"))


def has_builder_template_anchor(query: str) -> bool:
    """策略句是否已有双均线等模板锚点。"""

    text = str(query or "")
    lower = text.lower()
    if any(hint in text or hint in lower for hint in _BUILDER_TEMPLATE_HINTS):
        return True
    try:
        from .skills.strategy_spec import parse_strategy_spec_from_nl

        spec, _clarify = parse_strategy_spec_from_nl(text)
    except Exception:
        return False
    return spec is not None


def maybe_mark_builder_open_loop(decision: IntentDecision, query: str) -> IntentDecision:
    """无模板锚点的 strategy.builder 打 open_loop。"""

    if decision.job != "strategy.builder":
        return decision
    if has_builder_template_anchor(query):
        return decision
    flags = dict(decision.flags or {})
    flags["open_loop"] = True
    decision.flags = flags
    return decision


def classify_open_utterance(text: str) -> str:
    """开放态跟进：试错 / 两种回退 / 锁规格 / 补草稿。"""

    raw = str(text or "").strip()
    lower = raw.lower()
    compact = raw.replace(" ", "").lower()
    if any(hint in lower or hint in raw for hint in _ABANDON_TRIAL_HINTS):
        return "abandon_trial"
    if any(hint in lower or hint in raw for hint in _ABANDON_OPEN_HINTS):
        return "abandon_open"
    if compact in {"abandontest", "abandontrial"}:
        return "abandon_trial"
    if any(hint in lower or hint in raw for hint in _LOCK_HINTS):
        return "lock_spec"
    if any(hint in lower or hint in raw for hint in _TRIAL_HINTS):
        return "propose_trial"
    return "fill_slot"


def draft_factor_spec(query: str, session: Any = None) -> Dict[str, Any]:
    """从问句抽出最小 FactorSpec 草稿。"""

    existing = {}
    if session is not None and isinstance(getattr(session, "active_design", None), dict):
        existing = dict((session.active_design or {}).get("spec_draft") or {})
    text = str(query or "")
    lower = text.lower()
    name = str(existing.get("name") or "")
    if "momentum" in lower or "动量" in text:
        name = name or "momentum"
    universe = str(existing.get("universe") or "")
    if "hs300" in lower or "沪深300" in text or "000300" in text:
        universe = universe or "000300.SH"
    hypothesis = str(existing.get("hypothesis") or "").strip()
    if not hypothesis:
        hypothesis = f"Look for a useful factor from: {text[:180]}"
    return {
        "name": name or "unnamed_factor",
        "hypothesis": hypothesis,
        "universe": universe,
        "suggested_job": str(existing.get("suggested_job") or "research.factor_ic"),
        "assumptions": list(existing.get("assumptions") or ["Object is not named yet; design before IC."]),
    }


def draft_strategy_spec(query: str, session: Any = None) -> Dict[str, Any]:
    """无模板策略的最小 StrategySpec 草稿。"""

    existing = {}
    if session is not None and isinstance(getattr(session, "active_design", None), dict):
        existing = dict((session.active_design or {}).get("spec_draft") or {})
    text = str(query or "")
    hypothesis = str(existing.get("hypothesis") or "").strip() or f"Strategy idea (rules TBD): {text[:180]}"
    return {
        "name": str(existing.get("name") or "untitled_strategy"),
        "hypothesis": hypothesis,
        "universe": str(existing.get("universe") or ""),
        "suggested_job": "strategy.builder",
        "signal_type": str(existing.get("signal_type") or ""),
        "assumptions": list(existing.get("assumptions") or ["Rules are not specified; do not codegen yet."]),
    }


def apply_spec_patches(spec: Dict[str, Any], patches: Dict[str, Any]) -> Dict[str, Any]:
    """把跟进补丁打进 Spec 草稿。"""

    out = dict(spec or {})
    for key, value in (patches or {}).items():
        if value in (None, ""):
            continue
        if key in {"shares", "asset_pool"}:
            out["universe"] = value
        elif key == "hypothesis":
            out["hypothesis"] = value
        elif key in {"name", "factor", "factor_name"}:
            out["name"] = value
        elif key == "suggested_job":
            out["suggested_job"] = value
        else:
            out[key] = value
    return out


def trial_query_from_spec(spec: Dict[str, Any]) -> str:
    """用草稿拼闭合 IC 抽槽句。"""

    name = str((spec or {}).get("name") or "momentum")
    universe = str((spec or {}).get("universe") or "000300.SH")
    return f"factor IC summary for {name} {universe}"


def search_user_kb(store: Any, query: str, *, limit: int = 8) -> List[Dict[str, Any]]:
    """在 compiled catalog 里做关键词命中（设计环只读）。"""

    catalog = {}
    try:
        path = Path(store.user_kb_dir) / "compiled" / "catalog.json"
        if path.is_file():
            import json

            catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        catalog = {}
    entries = list(catalog.get("entries") or []) if isinstance(catalog, dict) else []
    tokens = [item.lower() for item in re.split(r"\W+", str(query or "")) if len(item) >= 2]
    hits: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        blob = " ".join(
            [
                str(entry.get("title") or ""),
                str(entry.get("path") or ""),
                " ".join(str(item) for item in (entry.get("tags") or [])),
                str(entry.get("run_id") or ""),
            ]
        ).lower()
        if tokens and not any(token in blob for token in tokens):
            continue
        hits.append(
            {
                "path": str(entry.get("path") or ""),
                "title": str(entry.get("title") or ""),
                "tags": list(entry.get("tags") or []),
            }
        )
        if len(hits) >= int(limit):
            break
    return hits


def pending_kb_write_from_spec(
    *,
    job: str,
    spec: Dict[str, Any],
) -> Dict[str, Any]:
    """生成待确认的用户 KB 写入草案。"""

    bucket = "strategies" if str(job).startswith("strategy.") else "factors"
    slug_src = str((spec or {}).get("name") or "note")
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", slug_src).strip("-").lower() or "note"
    title = str((spec or {}).get("name") or slug)
    body = (
        f"# {title}\n\n"
        f"- hypothesis: {spec.get('hypothesis')}\n"
        f"- universe: {spec.get('universe')}\n"
        f"- suggested_job: {spec.get('suggested_job')}\n"
    )
    return {
        "bucket": bucket,
        "slug": slug,
        "title": title,
        "body": body,
        "relpath": f"raw/{bucket}/{slug}.md",
    }


def write_confirmed_note(store: Any, draft: Dict[str, Any]) -> str:
    """确认后写入 raw/ 并 compile。"""

    rel = str(draft.get("relpath") or "")
    if not rel.startswith("raw/"):
        raise ValueError("KB write path must stay under raw/.")
    path = Path(store.user_kb_dir) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(draft.get("body") or ""), encoding="utf-8")
    store.compile_user_kb()
    return str(path)


def build_design_assumptions(
    *,
    decision: IntentDecision,
    spec: Dict[str, Any],
    kb_hits: Optional[List[Dict[str, Any]]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """设计环 assumptions（零执行菜谱）。"""

    blob: Dict[str, Any] = {
        "design_loop": True,
        "spec_draft": dict(spec or {}),
        "kb_hits": list(kb_hits or []),
        "open_job": decision.job,
    }
    if extra:
        blob.update(extra)
    return blob


def design_forbidden_in_steps(skill_names: List[str]) -> bool:
    """设计态 steps 是否混入禁止 skill。"""

    return any(name in DESIGN_FORBIDDEN_SKILLS for name in skill_names)
