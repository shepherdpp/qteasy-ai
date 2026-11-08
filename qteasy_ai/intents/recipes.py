# coding=utf-8
# ======================================
# File: recipes.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-02
# Desc:
# 已知 Job → 固定 DAG（Python，不是 JSON 工作流）。
# ======================================

"""按 Job + flags 组装规则菜谱 R。"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, TYPE_CHECKING

from ..intent_engine import IntentDecision
from ..skills.env_guide import DEFAULT_CORE_TABLES

if TYPE_CHECKING:
    from ..planner import Planner
    from ..contracts import ToolStep


def compose_recipe(planner: "Planner", decision: IntentDecision, query: str) -> List["ToolStep"]:
    """根据已分类 Job 生成 steps。

    Parameters
    ----------
    planner : Planner
        用于 ``_make_step`` 与抽槽。
    decision : IntentDecision
        分类结果。
    query : str
        原始问句。

    Returns
    -------
    list of ToolStep
        可执行或 fallback 步骤。
    """

    job = decision.job
    flags = decision.flags or {}
    q_lower = query.lower()
    if job == "unsafe":
        bypass = any(
            item in q_lower for item in ["跳过确认", "skip confirmation", "write files directly"]
        )
        if bypass:
            return [
                planner._make_step(
                    step_id="step_1",
                    skill_name="qt.ai.system.fallback",
                    inputs=planner._fallback_step_inputs(
                        query=query,
                        action="not_supported_yet",
                        reason="bypass_confirmation_not_allowed",
                        hint="High side-effect operations require explicit confirmation.",
                        missing_info="confirmation",
                        next_step="Please use plan mode first, then execute with explicit confirmation.",
                    ),
                )
            ]
        return [
            planner._make_step(
                step_id="step_1",
                skill_name="qt.ai.system.fallback",
                inputs=planner._fallback_step_inputs(
                    query=query,
                    action="clarify_required",
                    reason="unsafe_command_request",
                    hint="Shell command execution is not supported by qteasy AI skills.",
                    missing_info="none",
                    next_step="Please describe the qteasy task directly instead of raw shell commands.",
                ),
            )
        ]
    if job == "not_supported":
        return [
            planner._make_step(
                step_id="step_1",
                skill_name="qt.ai.system.fallback",
                inputs=planner._fallback_step_inputs(
                    query=query,
                    action="not_supported_yet",
                    reason=decision.rationale or "not_supported",
                    hint="This request is out of qteasy-ai 1.0 scope.",
                    missing_info="supported_skill",
                    next_step="Use refill, builtin backtest/optimize, stock screen, kline summary, or strategy meta.",
                ),
            )
        ]
    if job == "clarify":
        if decision.rationale == "multi_high_risk_intent":
            return [
                planner._make_step(
                    step_id="step_1",
                    skill_name="qt.ai.system.fallback",
                    inputs=planner._fallback_step_inputs(
                        query=query,
                        action="clarify_required",
                        reason="multi_intent_not_supported_in_single_step_planner",
                        hint="Please split request into smaller steps: download/backtest/optimize/live.",
                        missing_info="single_intent_query",
                        next_step="Split your request into one intent per query.",
                    ),
                )
            ]
        return [
            planner._make_step(
                step_id="step_1",
                skill_name="qt.ai.system.fallback",
                inputs=planner._fallback_step_inputs(
                    query=query,
                    action="clarify_required",
                    reason=decision.rationale or "clarify_required",
                    hint="Please refine the request so it matches one supported qteasy-ai job.",
                    missing_info="supported_skill",
                    next_step="Try refill, builtin backtest/optimize, stock screen, kline summary, or strategy meta.",
                ),
            )
        ]
    if job == "route_to_ask":
        return [
            planner._make_step(
                step_id="step_1",
                skill_name="qt.ai.system.fallback",
                inputs=planner._fallback_step_inputs(
                    query=query,
                    action="route_to_ask",
                    reason="conceptual_question",
                    hint="This looks like a conceptual question. Use Ask mode (qteasy-ai ask).",
                    missing_info="none",
                    next_step="Call ask() for Q&A without executable steps.",
                ),
            )
        ]
    if job == "env.ready":
        return env_ready_steps(planner)
    if job == "data.summary":
        return _summary_steps(planner, query)
    if job == "data.export":
        return _export_steps(planner, query)
    if job == "data.refill":
        steps = planner._infer_refill_steps(query=query, q_lower=q_lower, skip_query_guard=True)
        return steps if steps is not None else _not_supported(planner, query)
    if job == "data.read":
        return _compose_data_read(planner, query, flags)
    if job == "research.factor_ic":
        return planner._factor_ic_steps(query)
    if job == "research.factor_explore":
        return []
    if job == "research.screen":
        return _compose_screen(planner, query, q_lower)
    if job == "research.hold_compare":
        return _hold_compare_steps(planner, query)
    if job == "strategy.meta":
        return _compose_strategy_meta(planner, query, q_lower)
    if job == "backtest.builtin":
        steps = planner._infer_backtest_steps(query=query, q_lower=q_lower, skip_query_guard=True)
        if steps is not None:
            return steps
        return _not_supported(planner, query)
    if job == "optimize.builtin":
        steps = planner._infer_optimize_steps(query=query, q_lower=q_lower, skip_query_guard=True)
        return steps if steps is not None else _not_supported(planner, query)
    if job == "strategy.builder":
        steps = planner._infer_strategy_builder_steps(query=query, q_lower=q_lower)
        if steps is not None:
            return steps
        return [
            planner._make_step(
                step_id="step_1",
                skill_name="qt.ai.system.fallback",
                inputs=planner._fallback_step_inputs(
                    query=query,
                    action="clarify_required",
                    reason="strategy_spec_incomplete",
                    hint="Please provide a complete dual-MA cross description.",
                    missing_info="fast|slow",
                    next_step="Provide fast/slow windows (e.g. 20/60) and a single signal type.",
                ),
            )
        ]
    if job == "insight.last_backtest":
        return [
            planner._make_step(
                step_id="step_1",
                skill_name="qt.ai.insight.summarize_backtest",
                inputs={},
            )
        ]
    if job == "live.plan_only":
        return [
            planner._make_step(
                step_id="step_1",
                skill_name="qt.ai.pipeline.live_trade_plan_only",
                inputs={"query": query},
            )
        ]
    if job == "open":
        return []
    return _not_supported(planner, query)


def _not_supported(planner: "Planner", query: str) -> List["ToolStep"]:
    """默认 not_supported fallback。"""

    return [
        planner._make_step(
            step_id="step_1",
            skill_name="qt.ai.system.fallback",
            inputs=planner._fallback_step_inputs(
                query=query,
                action="not_supported_yet",
                reason="no_matching_skill",
                hint="No matching qteasy-ai skill for this query.",
                missing_info="supported_skill",
                next_step="Try refill, builtin backtest/optimize, stock screen, kline summary, or strategy meta.",
            ),
        )
    ]


def _compose_strategy_meta(planner: "Planner", query: str, q_lower: str) -> List["ToolStep"]:
    """列出或读取内置策略。"""

    is_parameter_query = planner._is_strategy_parameter_query(q_lower)
    match_id = planner._extract_strategy_id(query)
    if is_parameter_query and not match_id:
        return [
            planner._make_step(
                step_id="step_1",
                skill_name="qt.ai.system.fallback",
                inputs={
                    "query": query,
                    "fallback_action": "clarify_required",
                    "reason": "strategy_id_missing_for_parameter_query",
                    "hint": "Cannot determine strategy id for parameter query.",
                    "missing_info": "strategy_id",
                    "next_step": "Please provide exact strategy id, e.g. 'List all tunable parameters of MACD strategy'.",
                },
            )
        ]
    if match_id:
        return [
            planner._make_step(
                step_id="step_1",
                skill_name="qt.ai.strategy_meta.get",
                inputs={"strategy_id": match_id},
            )
        ]
    return [planner._make_step(step_id="step_1", skill_name="qt.ai.strategy_meta.list", inputs={})]


_API_TO_CHANNEL = {
    "get_history_data": "history",
    "get_reference_data": "reference",
    "get_static_data": "static",
}
_CHANNEL_SKILL = {
    "history": "qt.ai.data.history",
    "reference": "qt.ai.data.reference",
    "static": "qt.ai.data.static",
}


def env_ready_steps(planner: "Planner") -> List["ToolStep"]:
    """token 检查，再对四张核心表各查一次 table_info。

    Parameters
    ----------
    planner : Planner
        用来生成步骤。

    Returns
    -------
    list of ToolStep
        第一步是 ``qt.ai.env.check_tushare``。
    """

    steps = [planner._make_step(step_id="step_1", skill_name="qt.ai.env.check_tushare", inputs={})]
    for offset, table_name in enumerate(DEFAULT_CORE_TABLES, start=2):
        steps.append(
            planner._make_step(
                step_id=f"step_{offset}",
                skill_name="qt.ai.datasource.table_info",
                inputs={"table_name": table_name},
            )
        )
    return steps


@lru_cache(maxsize=64)
def _recommended_channel(dtype_name: str) -> str:
    """按 DataType 推荐入口给出 history / reference / static。

    Parameters
    ----------
    dtype_name : str
        宽名，如 ``cn_gdp`` / ``industry`` / ``close``。

    Returns
    -------
    str
        三入口之一；查不到或多种入口并存时返回空串。
    """

    name = str(dtype_name or "").strip()
    if not name:
        return ""
    try:
        import qteasy as qt

        frame = qt.find_history_data(name, as_data_frame=True)
    except Exception:
        return ""
    if frame is None or getattr(frame, "empty", True) or "name" not in getattr(frame, "columns", []):
        return ""
    exact = frame.loc[frame["name"].astype(str) == name]
    if exact.empty or "recommended_api" not in exact.columns:
        return ""
    apis = {str(item).strip() for item in exact["recommended_api"].tolist() if str(item).strip()}
    if len(apis) != 1:
        return ""
    return _API_TO_CHANNEL.get(next(iter(apis)), "")


def _compose_data_read(planner: "Planner", query: str, flags: Dict[str, Any]) -> List["ToolStep"]:
    """三入口只读取数。字面非 history 的 channel 保持不动；否则跟数据类型候选。

    数据类型的值留给填槽。图上只先写下行情里已经抽到的标的和日期。
    """

    from ..slot_graph import dtype_tokens, peek_channel

    market = planner._market_inputs(query)
    channel = str(flags.get("channel") or "history").strip().lower() or "history"
    tokens = dtype_tokens(query)
    if channel == "history":
        peeked = peek_channel(tokens)
        if peeked:
            channel = peeked
    skill_name = _CHANNEL_SKILL.get(channel, "qt.ai.data.history")
    inputs: Dict[str, Any] = {}
    if channel == "history" and not tokens:
        inputs["htype_names"] = "close"
    if channel != "reference" and market.get("shares"):
        inputs["shares"] = market["shares"]
    if channel != "static":
        if market.get("start"):
            inputs["start"] = market["start"]
        if market.get("end"):
            inputs["end"] = market["end"]
        if market.get("freq"):
            inputs["freq"] = market["freq"]
    return [
        planner._make_step(
            step_id="step_1",
            skill_name=skill_name,
            inputs=inputs,
        )
    ]


def _extract_dtype_names(query: str) -> str:
    """从问句抽取宽名（close/industry/cn_gdp 等）。"""

    lower = query.lower()
    for name in ("cn_gdp", "north_money", "industry", "list_date", "close", "pe"):
        if name in lower:
            return name
    return ""


def _hold_compare_steps(planner: "Planner", query: str) -> List["ToolStep"]:
    """持有对比：一条组合。没说超额时对齐到 1，说了累计收益就改成简单累计。"""

    from ..slot_graph import hold_share_codes, mentions_cumret, mentions_excess

    market = dict(planner._market_inputs(query) or {})
    codes = hold_share_codes(query)
    if codes:
        market["shares"] = ",".join(codes)
    excess = mentions_excess(query)
    cumret = mentions_cumret(query)
    steps = [
        planner._make_step(
            step_id="step_1",
            skill_name="qt.ai.data.kline",
            inputs=market,
        ),
        planner._make_step(
            step_id="step_2",
            skill_name="qt.ai.hp.portfolio",
            inputs={},
            depends_on=["step_1"],
        ),
    ]
    if excess and not cumret:
        steps.append(
            planner._make_step(
                step_id="step_3",
                skill_name="qt.ai.hp.plot",
                inputs={},
                depends_on=["step_2"],
            )
        )
        return steps
    if cumret:
        transform: Dict[str, Any] = {"method": "simple"}
        if excess:
            transform["htypes"] = "excess_close"
        steps.append(
            planner._make_step(
                step_id="step_3",
                skill_name="qt.ai.hp.cum_return",
                inputs=transform,
                depends_on=["step_2"],
            )
        )
        steps.append(
            planner._make_step(
                step_id="step_4",
                skill_name="qt.ai.hp.plot",
                inputs={},
                depends_on=["step_3"],
            )
        )
        return steps
    steps.append(
        planner._make_step(
            step_id="step_3",
            skill_name="qt.ai.hp.normalize",
            inputs={},
            depends_on=["step_2"],
        )
    )
    steps.append(
        planner._make_step(
            step_id="step_4",
            skill_name="qt.ai.hp.plot",
            inputs={},
            depends_on=["step_3"],
        )
    )
    return steps


def _summary_steps(planner: "Planner", query: str) -> List["ToolStep"]:
    """K 线摘要：取面板、滚动波动率、结构行数。"""

    market = planner._market_inputs(query)
    return [
        planner._make_step(
            step_id="step_1",
            skill_name="qt.ai.data.kline",
            inputs=market,
        ),
        planner._make_step(
            step_id="step_2",
            skill_name="qt.ai.hp.volatility",
            inputs={},
            depends_on=["step_1"],
        ),
        planner._make_step(
            step_id="step_3",
            skill_name="qt.ai.hp.describe",
            inputs={"view": "shape"},
            depends_on=["step_1"],
        ),
    ]


def _export_steps(planner: "Planner", query: str) -> List["ToolStep"]:
    """K 线导出：取面板后画一页静态图。不传 plot_type。"""

    market = planner._market_inputs(query)
    return [
        planner._make_step(
            step_id="step_1",
            skill_name="qt.ai.data.kline",
            inputs=market,
        ),
        planner._make_step(
            step_id="step_2",
            skill_name="qt.ai.hp.plot",
            inputs={},
            depends_on=["step_1"],
        ),
    ]


def _compose_screen(planner: "Planner", query: str, q_lower: str) -> List["ToolStep"]:
    """选股 Job：Universe + 可选谓词 + 投影。用户槽留给填槽。"""

    from ..slot_graph import mentions_return

    extra = []
    for token in ("市盈率", "市值", "成交量", "换手", "申万", " pe", "pe/", "pb"):
        if token in q_lower:
            extra.append(token.strip())
    if extra:
        return [
            planner._make_step(
                step_id="step_1",
                skill_name="qt.ai.system.fallback",
                inputs=planner._fallback_step_inputs(
                    query=query,
                    action="clarify_required",
                    reason="screen_extra_conditions_not_supported",
                    hint="PE/market-cap/volume/formula filters are not supported in this stage.",
                    missing_info="supported_screen_conditions",
                    next_step="Use lookback + drawdown/gain threshold + one exact Tushare industry name.",
                    details={"unsupported": extra},
                ),
            )
        ]
    steps = [
        planner._make_step(
            step_id="step_1",
            skill_name="qt.ai.research.universe_filter",
            inputs={},
        )
    ]
    last_id = "step_1"
    if mentions_return(query):
        steps.append(
            planner._make_step(
                step_id="step_2",
                skill_name="qt.ai.research.price_predicate",
                inputs={},
                depends_on=[last_id],
            )
        )
        last_id = "step_2"
    project_id = "step_3" if last_id == "step_2" else "step_2"
    steps.append(
        planner._make_step(
            step_id=project_id,
            skill_name="qt.ai.research.project_universe",
            inputs={"max_hits": 50},
            depends_on=[last_id],
        )
    )
    return steps
