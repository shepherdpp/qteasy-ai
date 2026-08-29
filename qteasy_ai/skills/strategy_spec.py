# coding=utf-8
# ======================================
# File: strategy_spec.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-29
# Desc:
# qteasy AI 阶段 D：NL → StrategySpec。
# ======================================

"""从自然语言生成机器可读 StrategySpec（规则金句优先）。"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..contracts import (
    SkillError,
    SkillMetadata,
    SkillResult,
    SkillSideEffects,
    StrategySpec,
    new_run_id,
)

SMA_CROSS_TEMPLATE_ID = "rule_iterator.sma_cross"
DEFAULT_RISK_DECL: Dict[str, str] = {
    "cost": "declare_only",
    "moq": "declare_only",
    "delivery": "declare_only",
    "short_sell": "declare_only",
}

_SMA_HINTS = (
    "金叉",
    "死叉",
    "均线交叉",
    "双均线",
    "均线",
    "sma",
    "ma cross",
    "dual ma",
    "moving average",
)
_PT_HINTS = ("目标仓位", "position target", " pt ", "满仓权重")
_VS_HINTS = (" vs ", "股数", "手数", "volume signal", "固定数量")


def _normalize_query(query: str) -> str:
    """去掉首尾空白。"""

    return str(query or "").strip()


def _has_any(text: str, hints: Tuple[str, ...]) -> bool:
    """大小写不敏感的子串命中。"""

    blob = f" {text.lower()} "
    raw = text
    for hint in hints:
        if hint.isascii():
            if hint.lower() in blob:
                return True
        elif hint in raw:
            return True
    return False


def _extract_ma_periods(query: str) -> Optional[Tuple[int, int]]:
    """从 NL 抽取快/慢均线周期；未命中返回 None。"""

    patterns = [
        r"(\d+)\s*[/／、,]\s*(\d+)\s*日?\s*均线",
        r"(\d+)\s*日[^0-9]{0,12}(\d+)\s*日",
        r"fast\s*[=:]?\s*(\d+)\D{0,24}slow\s*[=:]?\s*(\d+)",
        r"(\d+)\s*(?:and|&|/)\s*(\d+)\s*(?:day|日).{0,12}(?:ma|sma|均线)",
    ]
    for pattern in patterns:
        match = re.search(pattern, query, flags=re.IGNORECASE)
        if not match:
            continue
        fast = int(match.group(1))
        slow = int(match.group(2))
        if fast <= 0 or slow <= 0:
            continue
        if fast > slow:
            fast, slow = slow, fast
        return fast, slow
    return None


def _extract_asset_pool(query: str) -> str:
    """抽取标的；未命中返回空串，禁止编造默认池。"""

    alias_map = {
        "沪深300": "000300.SH",
        "csi300": "000300.SH",
        "csi 300": "000300.SH",
    }
    q_lower = query.lower()
    for alias, code in alias_map.items():
        if alias.lower() in q_lower or alias in query:
            return code
    symbol_match = re.search(r"(\d{6}\.(?:SH|SZ|BJ))", query, flags=re.IGNORECASE)
    if symbol_match:
        return symbol_match.group(1).upper()
    return ""


def _extract_invest_dates(query: str) -> Tuple[str, str]:
    """抽取回测起止日期；未命中返回空串。"""

    year_range = re.search(
        r"(20\d{2})\s*年?\s*(?:[~\-–—]|至|到|to)\s*(20\d{2})\s*年?",
        query,
        flags=re.IGNORECASE,
    )
    if year_range:
        y1 = int(year_range.group(1))
        y2 = int(year_range.group(2))
        if y1 <= y2:
            return f"{y1:04d}0101", f"{y2:04d}1231"
    date_match = re.findall(r"(20\d{2}[-/]?\d{2}[-/]?\d{2})", query)
    if len(date_match) >= 2:
        start = date_match[0].replace("-", "").replace("/", "")
        end = date_match[1].replace("-", "").replace("/", "")
        return start, end
    return "", ""


def _extract_run_freq(query: str) -> str:
    """抽取运行频率，默认日频。"""

    q_lower = query.lower()
    if any(item in query or item in q_lower for item in ("周线", "周频", "weekly", "freq=w")):
        return "w"
    if any(item in query or item in q_lower for item in ("月线", "月频", "monthly")):
        return "m"
    return "d"


def _signal_type_conflict(query: str) -> bool:
    """同时声明 PT 与 VS 视为矛盾。"""

    padded = f" {query} "
    has_pt = _has_any(padded, _PT_HINTS) or bool(re.search(r"\bPT\b", query, flags=re.IGNORECASE))
    has_vs = _has_any(padded, _VS_HINTS) or bool(re.search(r"\bVS\b", query, flags=re.IGNORECASE))
    return has_pt and has_vs


def parse_strategy_spec_from_nl(query: str) -> Tuple[Optional[StrategySpec], Dict[str, Any]]:
    """规则解析 NL；成功返回 Spec，否则返回澄清载荷。

    Parameters
    ----------
    query : str
        用户自然语言。

    Returns
    -------
    tuple
        ``(spec, clarify_payload)``；成功时 payload 为空字典。
    """

    text = _normalize_query(query)
    if _signal_type_conflict(text):
        return None, {
            "clarify_required": True,
            "missing_info": "signal_type",
            "reason": "signal_type_conflict",
            "hint": "PT (position target) and VS (share/volume) cannot be selected together. Pick one signal type.",
            "assumptions": [],
        }
    periods = _extract_ma_periods(text)
    is_sma = _has_any(text, _SMA_HINTS) or periods is not None
    if not is_sma:
        return None, {
            "clarify_required": True,
            "missing_info": "template_id|fast|slow",
            "reason": "template_not_supported_or_incomplete",
            "hint": "This stage only supports RuleIterator dual-MA cross (fast/slow periods). Provide e.g. 20/60 SMA golden/death cross.",
            "assumptions": [],
        }
    if periods is None:
        return None, {
            "clarify_required": True,
            "missing_info": "fast|slow",
            "reason": "ma_periods_missing",
            "hint": "Dual-MA cross requires explicit fast/slow windows, e.g. 20/60.",
            "assumptions": [],
        }
    fast, slow = periods
    asset_pool = _extract_asset_pool(text)
    invest_start, invest_end = _extract_invest_dates(text)
    run_freq = _extract_run_freq(text)
    window_length = int(slow) + 5
    assumptions: List[str] = [
        "template_id=rule_iterator.sma_cross",
        "signal_type=PS (cross signal, aligned with Example01CrossSMA)",
        "risk_decl is declaration-only; kernel cost/MOQ/T+1 unchanged",
    ]
    if not asset_pool:
        assumptions.append("asset_pool not provided; not invented")
    spec = StrategySpec(
        signal_type="PS",
        run_freq=run_freq,
        run_timing="close",
        asset_pool=asset_pool,
        htypes=["close"],
        window_length=window_length,
        use_latest_data_cycle=False,
        parameters=[
            {
                "name": "fast",
                "default": fast,
                "range": [5, max(80, fast)],
                "par_type": "int",
                "opt_tag": 1,
            },
            {
                "name": "slow",
                "default": slow,
                "range": [20, max(200, slow)],
                "par_type": "int",
                "opt_tag": 1,
            },
        ],
        risk_decl=dict(DEFAULT_RISK_DECL),
        template_id=SMA_CROSS_TEMPLATE_ID,
        assumptions=assumptions,
        source_query=text,
        invest_start=invest_start,
        invest_end=invest_end,
        class_name="GeneratedSmaCross",
    )
    return spec, {}


def resolve_spec_from_inputs(
    spec: Any = None,
    upstream_payload: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """从 handler 入参或上游 payload 取出 StrategySpec 字典。"""

    if isinstance(spec, StrategySpec):
        return spec.to_dict()
    if isinstance(spec, dict) and spec:
        return dict(spec)
    payload = upstream_payload if isinstance(upstream_payload, dict) else {}
    nested = payload.get("spec")
    if isinstance(nested, dict) and nested:
        return dict(nested)
    raw_kwargs = kwargs.get("spec")
    if isinstance(raw_kwargs, dict) and raw_kwargs:
        return dict(raw_kwargs)
    return {}


def build_strategy_spec_from_nl_skill(
    llm_func: Callable[..., str] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.strategy.spec_from_nl``。

    Parameters
    ----------
    llm_func : callable, optional
        预留 LLM 填槽；本阶段规则金句优先，unittest 可不注入。
        传入时仅在规则路径无法解析时调用（当前未启用）。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。
    """

    metadata = SkillMetadata(
        name="qt.ai.strategy.spec_from_nl",
        version="0.1.0",
        summary="Turn a natural-language strategy description into a machine-readable StrategySpec.",
        inputs_schema={
            "query": {"type": "string", "required": True},
        },
        outputs_schema={"spec": "dict", "assumptions": "list"},
        side_effects=SkillSideEffects(description="readonly NL to StrategySpec"),
        required_capabilities=[],
        qteasy_entrypoints=[],
        skill_kind="api",
    )
    _reserved_llm = llm_func  # 阶段 D 规则金句优先；保留注入点供后续切片

    def handler(
        query: str = "",
        upstream_payload: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> dict:
        run_id = new_run_id()
        text = _normalize_query(query) or _normalize_query(str(kwargs.get("user_query") or ""))
        inputs_echo = {"query": text, **kwargs}
        spec, clarify = parse_strategy_spec_from_nl(text)
        if spec is None:
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                payload=dict(clarify),
                error=SkillError(
                    code="CLARIFY_REQUIRED",
                    message=str(clarify.get("hint") or "Strategy description is incomplete or conflicting."),
                    details={
                        "missing_info": clarify.get("missing_info"),
                        "reason": clarify.get("reason"),
                    },
                ),
            )
            return result.to_dict()
        result = SkillResult(
            ok=True,
            skill_name=metadata.name,
            run_id=run_id,
            inputs_echo=inputs_echo,
            payload={"spec": spec.to_dict(), "clarify_required": False},
            metrics={
                "fast": spec.parameters[0]["default"],
                "slow": spec.parameters[1]["default"],
            },
            data_summary={
                "template_id": spec.template_id,
                "signal_type": spec.signal_type,
                "asset_pool": spec.asset_pool,
            },
        )
        return result.to_dict()

    return metadata, handler
