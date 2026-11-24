# coding=utf-8
# ======================================
# File: app.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-04-15
# Desc:
# qteasy AI 外壳应用层入口，统一编排
# Notebook / CLI 调用链路。
# ======================================

"""阶段A统一入口（Notebook/CLI 共用）。

这个模块定位为“装配层（assembly layer）”，负责把分散模块按固定拓扑连接：

1. `SkillRegistry`：技能注册中心；
2. `Planner`：自然语言到 ToolPlan；
3. `PlanExecutor`：计划执行与 run 落盘；
4. `MemoryStore`：profile/env_facts/runs 存储。

设计目标
--------
- 对 Notebook 用户暴露简单 API（ask/plan/run）；
- 对 CLI 和未来 Web/TUI 保持一致的应用层语义；
- 避免前端直接感知技能细节与执行细节。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from .ask_engine import AskEngine, AskResponse, build_ask_history_index
from .config import DEFAULT_PROVIDER_TIMEOUT, ConfigCenter
from .contracts import ToolPlan, new_plan_id
from .executor import PlanExecutor
from .human_card import (
    clarification_needs_answer,
    infer_effective_kind,
    option_answer_label,
    polish_human_cards,
    project_human_cards,
    question_answer_rows,
)
from .identity import (
    parse_identity_utterance,
    remove_identity_file,
    write_identity_file,
)
from .knowledge_base import KnowledgeBase
from .memory_store import MemoryStore, merge_env_facts
from .output import AssistantOutput
from .plan_markdown import tool_plan_to_markdown
from .planner import Planner
from .provider import BaseLLMProvider
from .renderer import OutputRenderer
from .registry import SkillRegistry
from .result_reading import attach_result_reading
from .run_policy import RunStorePolicy
from .progress_bridge import bind_progress_callback, install_qteasy_tqdm_bridge, reset_progress_callback
from .session import (
    ConversationState,
    DEFERRED_REPLACED_NOTICE,
    DEFERRED_RUN_NOTICE,
    SessionStore,
    _LIVE_LOCK,
    clear_live_running,
    is_live_backgrounded,
    is_live_running,
    live_cancel_event,
    mark_live_progress,
    mark_live_step_end,
    mark_live_step_start,
    pop_deferred_run,
    register_live_running,
    set_deferred_run,
    task_was_cancelled,
)
from .parse_turn import BLOCK_HINT, CONFIRM_OPEN_ID, constitution_package, format_card_replies
from .session_gate import (
    SessionGate,
    merge_facts,
    new_task_patches,
)
from .side_effects import plan_has_high_side_effect

_CJK_STAGE = re.compile(r"[\u4e00-\u9fff]")
_STAGE_OPEN_ZH = "正在创建开放计划"
_STAGE_OPEN_EN = "Creating an open plan."
from .skills import (
    build_backtest_run_skill,
    build_data_history_skill,
    build_data_reference_skill,
    build_data_statement_skill,
    build_data_static_skill,
    build_dtype_find_skill,
    build_table_info_skill,
    build_table_overview_skill,
    build_check_tushare_skill,
    build_data_kline_skill,
    build_data_read_skill,
    build_data_refill_skill,
    build_factor_ic_summary_skill,
    build_hp_describe_skill,
    build_hp_slice_skill,
    build_hp_drop_skill,
    build_hp_rename_skill,
    build_hp_fill_skill,
    build_hp_dropna_skill,
    build_hp_resample_skill,
    build_hp_assign_skill,
    build_hp_align_skill,
    build_hp_join_skill,
    build_hp_returns_skill,
    build_hp_shift_skill,
    build_hp_diff_skill,
    build_hp_pct_change_skill,
    build_hp_rank_skill,
    build_hp_zscore_skill,
    build_hp_rolling_skill,
    build_hp_agg_skill,
    build_hp_corr_skill,
    build_hp_compare_skill,
    build_hp_combine_mask_skill,
    build_hp_where_skill,
    build_hp_expr_skill,
    build_hp_indicator_skill,
    build_hp_candle_pattern_skill,
    build_hp_research_preset_skill,
    build_hp_portfolio_skill,
    build_hp_cum_return_skill,
    build_hp_normalize_skill,
    build_hp_alpha_beta_skill,
    build_hp_performance_skill,
    build_hp_plot_skill,
    build_hp_volatility_skill,
    build_insight_backtest_skill,
    build_live_trade_plan_only_skill,
    build_optimize_run_skill,
    build_operator_from_spec_skill,
    build_overview_tables_skill,
    build_price_predicate_skill,
    build_project_universe_skill,
    build_research_screen_skill,
    build_strategy_codegen_hybrid_skill,
    build_strategy_meta_get_skill,
    build_strategy_meta_list_skill,
    build_strategy_sanity_check_skill,
    build_strategy_spec_from_nl_skill,
    build_system_fallback_skill,
    build_universe_filter_skill,
)


_LAST_CHANCE_PROMPT = (
    "Last chance: please provide valid values for the remaining fields."
)
_CLARIFICATION_FAILED_MESSAGE = (
    "Clarification failed: too many invalid answers. This request ended."
)


def _provider_for_narrative(provider: Any, assumptions: Any, query: str) -> Any:
    """计划说明使用当前模型。询问不再单独关掉它。"""

    del assumptions, query
    return provider


def _normalize_patches(patches: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """去掉空键空值的结构化槽补丁。

    Parameters
    ----------
    patches : dict, optional
        槽名到值。

    Returns
    -------
    dict
        仅含非空键值的补丁。
    """

    out: Dict[str, Any] = {}
    for key, value in (patches or {}).items():
        name = str(key or "").strip()
        if not name or value in (None, ""):
            continue
        out[name] = value
    return out


def _take_card_payload(
    pending: Any,
    patches: Dict[str, Any],
) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """取出这张卡上每一个非空折叠值。字符串进原文，项列表单独交解释者。

    Parameters
    ----------
    pending : dict
        当前澄清卡。
    patches : dict
        折叠后的槽补丁。被取出的键会从补丁里弹出。

    Returns
    -------
    tuple
        ``(card_text, card_items)``。
    """

    from .slot_graph import is_bound_item_list

    found: Dict[str, str] = {}
    items: Dict[str, Any] = {}
    for name in list(patches):
        value = patches.get(name)
        if value in (None, ""):
            continue
        if is_bound_item_list(value):
            items[name] = patches.pop(name)
            continue
        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            items[name] = patches.pop(name)
            continue
        found[name] = str(patches.pop(name))
    return found, items


def _append_clarify_history(
    task: Any,
    pending: Any,
    card_text: Dict[str, str],
    card_items: Dict[str, Any],
) -> None:
    """把这一次已经回答的格子追加进历次澄清。新出的卡先不写进去。"""

    rows = pending.get("pending") if isinstance(pending, dict) else None
    by_name: Dict[str, Dict[str, Any]] = {}
    for row in rows or []:
        if isinstance(row, dict) and str(row.get("name") or ""):
            by_name.setdefault(str(row.get("name")), row)
    slots: List[Dict[str, Any]] = []
    answers: Dict[str, Any] = {}
    answers.update(card_text or {})
    answers.update(card_items or {})
    for name, answer in answers.items():
        key = str(name or "")
        if not key or answer in (None, "", []):
            continue
        row = by_name.get(key) or {}
        slots.append(
            {
                "name": key,
                "prompt": str(row.get("prompt") or ""),
                "options": [dict(item) for item in (row.get("options") or []) if isinstance(item, dict)],
                "answer": answer,
                "error": str(row.get("error") or ""),
            }
        )
    if not slots:
        return
    history = [dict(item) for item in (getattr(task, "clarify_history", None) or []) if isinstance(item, dict)]
    history.append({"slots": slots})
    task.clarify_history = history


def _merge_fill_slots(state: Any, plan: Any) -> None:
    """这一圈收下的槽写进当前任务。缺省不确认，没收完的列表也不确认。"""

    record_slots = ((getattr(plan, "assumptions", None) or {}).get("fill_record") or {}).get("slots")
    if not isinstance(record_slots, list):
        return
    for item in record_slots:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if not name:
            continue
        value = item.get("value")
        source = str(item.get("source") or "")
        if source == "default":
            state.set_slot(name, value, source="default", confirmed=False)
        elif source == "user" and _holding_still_open(value):
            state.set_slot(name, value, source="user", confirmed=False)
        elif source == "user":
            merge_facts(state, {name: value}, source="user", confirmed=True)


def _holding_still_open(value: Any) -> bool:
    """项列表里还有未确认项。普通标量不是这种列表。"""

    if not isinstance(value, list) or not value:
        return False
    if not all(isinstance(item, dict) for item in value):
        return False
    if not any("status" in item or "code" in item for item in value):
        return False
    return any(str(item.get("status") or "") != "confirmed" for item in value)


def _submission_changes(
    pending: Dict[str, Any],
    card_text: Dict[str, str],
    card_items: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """这张卡上每一格先记成 accepted，随后再按下一张卡的 error 改判。"""

    rows = [item for item in ((pending or {}).get("pending") or []) if isinstance(item, dict)]
    labels = {
        str(item.get("name") or ""): str(item.get("label") or item.get("name") or "")
        for item in rows
    }
    changes: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for name, value in list((card_text or {}).items()) + list((card_items or {}).items()):
        key = str(name or "")
        if not key or key in seen or value in (None, ""):
            continue
        seen.add(key)
        changes.append({
            "name": key,
            "label": labels.get(key) or key,
            "value": value,
            "origin": "accepted",
        })
    return changes


def _mark_rejected_slot_changes(
    changes: List[Dict[str, Any]],
    assumptions: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """澄清卡 ``pending.error`` 非空的提交键改为 rejected。

    Parameters
    ----------
    changes : list of dict
        本轮写入键。``origin`` 为 ``accepted`` 或 ``filled``。
    assumptions : dict, optional
        计划假设。``clarification.pending`` 与用户看见的卡一致。

    Returns
    -------
    list of dict
        被拒绝的提交键 ``origin`` 为 ``rejected``。系统填入且不在名单里的键仍是 ``filled``。
    """

    clarification = (assumptions or {}).get("clarification") if isinstance(assumptions, dict) else None
    pending = clarification.get("pending") if isinstance(clarification, dict) else None
    rejected = {
        str(item.get("name") or "").strip()
        for item in (pending or [])
        if isinstance(item, dict) and str(item.get("error") or "").strip() and str(item.get("name") or "").strip()
    }
    if not rejected:
        return [dict(item) for item in changes]
    rows: List[Dict[str, Any]] = []
    for item in changes:
        row = dict(item)
        if str(row.get("name") or "") in rejected and str(row.get("origin") or "accepted") == "accepted":
            row["origin"] = "rejected"
        rows.append(row)
    return rows


def build_default_registry() -> SkillRegistry:
    """构建默认 Registry（阶段 A～D 已注册技能）。

    Returns
    -------
    SkillRegistry
        已注册只读、引导与 L1/L2/L3 技能的注册中心实例。
    """

    registry = SkillRegistry()
    for builder in [
        build_strategy_meta_list_skill,
        build_strategy_meta_get_skill,
        build_data_kline_skill,
        build_data_history_skill,
        build_data_reference_skill,
        build_data_static_skill,
        build_data_statement_skill,
        build_dtype_find_skill,
        build_table_info_skill,
        build_table_overview_skill,
        build_hp_volatility_skill,
        build_hp_describe_skill,
        build_hp_slice_skill,
        build_hp_drop_skill,
        build_hp_rename_skill,
        build_hp_fill_skill,
        build_hp_dropna_skill,
        build_hp_resample_skill,
        build_hp_assign_skill,
        build_hp_align_skill,
        build_hp_join_skill,
        build_hp_returns_skill,
        build_hp_shift_skill,
        build_hp_diff_skill,
        build_hp_pct_change_skill,
        build_hp_rank_skill,
        build_hp_zscore_skill,
        build_hp_rolling_skill,
        build_hp_agg_skill,
        build_hp_corr_skill,
        build_hp_compare_skill,
        build_hp_combine_mask_skill,
        build_hp_where_skill,
        build_hp_expr_skill,
        build_hp_indicator_skill,
        build_hp_candle_pattern_skill,
        build_hp_research_preset_skill,
        build_hp_portfolio_skill,
        build_hp_cum_return_skill,
        build_hp_normalize_skill,
        build_hp_alpha_beta_skill,
        build_hp_performance_skill,
        build_hp_plot_skill,
        build_data_read_skill,
        build_system_fallback_skill,
        build_check_tushare_skill,
        build_overview_tables_skill,
        build_factor_ic_summary_skill,
        build_data_refill_skill,
        build_backtest_run_skill,
        build_optimize_run_skill,
        build_research_screen_skill,
        build_universe_filter_skill,
        build_price_predicate_skill,
        build_project_universe_skill,
        build_insight_backtest_skill,
        build_strategy_spec_from_nl_skill,
        build_strategy_codegen_hybrid_skill,
        build_strategy_sanity_check_skill,
        build_operator_from_spec_skill,
        build_live_trade_plan_only_skill,
    ]:
        metadata, handler = builder()
        registry.register(metadata, handler)
    return registry


@dataclass
class AssistantResponse:
    """统一返回对象（预留类型）。

    Notes
    -----
    当前阶段A主要以 `dict` 返回，保留该 dataclass 是为了后续在
    类型系统中逐步收敛响应对象结构。
    """

    plan: Dict[str, Any]
    execution: Dict[str, Any]
    run_id: str
    run_file: str


def _identity_spec(row: Dict[str, Any]) -> Dict[str, Any]:
    """取出消息上的身份写入草案。没有时为空字典。"""

    payload = row.get("payload") if isinstance(row, dict) else None
    if not isinstance(payload, dict):
        return {}
    spec = payload.get("identity_write")
    if not isinstance(spec, dict):
        return {}
    return spec


def _pending_identity_index(session: Optional[ConversationState]) -> int:
    """最近一条仍待确认的身份卡下标。没有时为 -1。"""

    if session is None:
        return -1
    for index in range(len(session.messages) - 1, -1, -1):
        spec = _identity_spec(session.messages[index])
        if spec.get("pending"):
            return index
    return -1


def _mark_identity_pending(session: ConversationState, index: int, *, pending: bool) -> None:
    """改身份卡的 pending 标记。文件是否写入由调用方决定。"""

    row = dict(session.messages[index])
    payload = dict(row.get("payload") or {})
    spec = dict(payload.get("identity_write") or {})
    spec["pending"] = bool(pending)
    payload["identity_write"] = spec
    row["payload"] = payload
    session.messages[index] = row


class QteasyAssistant:
    """Notebook/CLI 共用助手对象。

    这是用户最直接接触的 AI 外壳对象，面向“用户意图”而不是“内部模块”。
    用户只需要选择调用模式：

    - `ask()`：Ask 目标态问答（LLM + KnowledgeBase，不执行 skill）；
    - `preview()` / `plan()`：生成 dry-run 计划；
    - `run()`：确认执行计划。
    """

    def __init__(
        self,
        *,
        provider: Optional[BaseLLMProvider] = None,
        memory_store: Optional[MemoryStore] = None,
        registry: Optional[SkillRegistry] = None,
        run_policy: Optional[RunStorePolicy] = None,
    ) -> None:
        # MemoryStore：负责持久化执行记录与轻量记忆。
        self.memory_store = memory_store or MemoryStore()
        # Registry：聚合本阶段可用技能及其元数据。
        self.registry = registry or build_default_registry()
        # Planner：根据用户请求生成计划对象（注入 env_facts 供门禁）。
        self.planner = Planner(
            self.registry,
            provider=provider,
            env_facts=self.memory_store.load_env_facts(),
        )
        self.planner.memory_store = self.memory_store
        # Executor：负责按计划执行。
        self.executor = PlanExecutor(self.registry, self.memory_store)
        self.renderer = OutputRenderer()
        self.run_policy = run_policy or RunStorePolicy()
        self.ask_engine = AskEngine(
            knowledge_base=KnowledgeBase(),
            provider=provider,
        )
        self.session_store = SessionStore(self.memory_store)
        self.session_gate = SessionGate(provider=provider)
        self.on_stage = None
        self._last_run_id = ""
        identity_dir = self.memory_store.user_kb_dir
        self.ask_engine.identity_dir = identity_dir
        self.planner.identity_dir = identity_dir
        self.planner.intent_engine.identity_dir = identity_dir

    def apply_provider(self, provider: Optional[BaseLLMProvider]) -> None:
        """热替换 Ask / Planner / SessionGate 的 LLM Provider。"""

        self.planner.provider = provider
        if getattr(self.planner, "intent_engine", None) is not None:
            self.planner.intent_engine.provider = provider
        self.ask_engine.provider = provider
        self.session_gate.provider = provider

    _ALLOW_FLAGS = {
        "qt.ai.data.refill_basic_equity_and_index": "allow_refill",
        "qt.ai.backtest.run_builtin": "allow_backtest",
        "qt.ai.optimize.run_builtin": "allow_optimize",
    }
    _LIVE_SKILLS = frozenset({"qt.ai.pipeline.live_trade_plan_only"})

    def _refresh_planner_env_facts(self) -> None:
        """从 MemoryStore 刷新 Planner 的 env_facts。"""

        self.planner.env_facts = self.memory_store.load_env_facts()

    def _build_plan(self, query: str, *, mode: str) -> Any:
        """加载最新 env_facts 后生成 ToolPlan（无会话）。"""

        self._refresh_planner_env_facts()
        profile = self.memory_store.load_profile()
        return self.planner.build_plan(query, mode=mode, profile=profile)

    def ask(
        self,
        query: str,
        *,
        response_style: str = "user_friendly",
        persist: str | None = None,
        keep: bool = False,
        explanation_depth: str = "standard",
        session_id: str | None = None,
        requested_mode: str | None = None,
    ) -> Dict[str, Any] | AssistantOutput:
        """Ask 目标态：LLMClient + KnowledgeBase 问答，不执行 skill。

        不调用 PlanExecutor，不写入 ``runs/``。``persist`` / ``keep`` 被忽略。
        有 ``session_id`` 时从 ``messages[]`` 现算成功 Ask 的一句话索引并传给引擎。
        引擎不读 session。成功后仍把 ``ask_focus`` 写在 Ask 卡上供查看。不建 Task。
        若仍需审阅可执行步骤，请使用 ``preview()`` 或 ``plan()``。

        Parameters
        ----------
        query : str
            用户自然语言问题。
        response_style : {'user_friendly', 'raw'}, default 'user_friendly'
            raw 返回 Ask 字典；user_friendly 返回 AssistantOutput。
        persist : str, optional
            忽略（Ask 不落盘 run）。
        keep : bool, default False
            忽略。
        explanation_depth : {'brief', 'standard', 'deep'}, default 'standard'
            解释层深度。

        Returns
        -------
        dict or AssistantOutput
            ``mode='ask'`` 的问答结果，不含可执行 steps。
        """

        del persist, keep
        identity = self._identity_response(
            query,
            session_id=session_id,
            requested_mode=str(requested_mode or "ask"),
            response_style=response_style,
        )
        if identity is not None:
            return identity
        session_context = ""
        session = None
        sid = str(session_id or "").strip()
        if sid:
            session = self.session_store.load(sid)
            session_context = self._slot_summary(session)
            last = session.messages[-1] if session.messages else {}
            already = (
                str(last.get("kind") or "") == "user_text"
                and str(last.get("text") or "").strip() == str(query or "").strip()
            )
            if not already:
                session.append_user_text(query)
            self.session_store.save(session)
        ask_history = (
            build_ask_history_index(session.messages, self.ask_engine.knowledge_base)
            if session is not None else None
        )
        latched_plain = bool(session.ask_plain_language) if session is not None else False
        result: AskResponse = self.ask_engine.ask(
            query,
            explanation_depth=explanation_depth,
            session_context=session_context,
            ask_history=ask_history,
            plain_language=latched_plain,
        )
        payload = result.to_dict()
        if session is not None:
            turn_plain = bool((payload.get("raw") or {}).get("ask_plain_language"))
            if turn_plain and not session.ask_plain_language:
                session.ask_plain_language = True
                self.session_store.save(session)
            payload["session"] = {"session_id": session.session_id, "slots_summary": session_context}
        self._attach_human_cards(
            payload,
            query=query,
            requested_mode=str(requested_mode or "ask"),
            session=session,
            include_user_text=session is None,
        )
        if response_style == "raw":
            return payload
        return AssistantOutput(
            narrative=result.narrative,
            python_code=result.python_code,
            result_preview=result.result_preview,
            raw=payload,
        )

    def preview(
        self,
        query: str,
        *,
        response_style: str = "user_friendly",
        persist: str | None = None,
        keep: bool = False,
        explanation_depth: str = "standard",
        session_id: str | None = None,
        agent_auto: Optional[bool] = None,
        debug: bool = False,
    ) -> Dict[str, Any] | AssistantOutput:
        """Plan 预览别名：dry-run ToolPlan，不执行 skill。

        对应阶段 A 误用 ``ask()`` 作为「只看 plan」的迁移入口。
        语义与 ``plan()`` 相同。
        """

        return self.plan(
            query,
            response_style=response_style,
            persist=persist,
            keep=keep,
            explanation_depth=explanation_depth,
            session_id=session_id,
            agent_auto=agent_auto,
            debug=debug,
        )

    def plan(
        self,
        query: str,
        *,
        response_style: str = "user_friendly",
        persist: str | None = None,
        keep: bool = False,
        explanation_depth: str = "standard",
        session_id: str | None = None,
        agent_auto: Optional[bool] = None,
        patches: Optional[Dict[str, Any]] = None,
        answers: Optional[List[Any]] = None,
        skip: bool = False,
        allow_composer_slot_fill: bool = True,
        debug: bool = False,
    ) -> Dict[str, Any] | AssistantOutput:
        """Plan 模式：生成 dry_run 计划。

        与 `ask()` 的区别在于：
        - ask：KnowledgeBase 问答，无 skill / 无 Executor；
        - plan / preview：生成可审阅 ToolPlan steps，不执行。

        非空 ``patches`` 为同一 Job 改槽回执：``query`` 可空，不跑跟进句分类。
        ``answers`` 是澄清卡按题序交回的列表，先折成槽补丁再走上面的回执。
        ``skip=True`` 为控件跳过澄清，不写 ``user_text``。
        ``allow_composer_slot_fill=False``（Web）：clarifying 下打字升级同一份计划；整句「跳过」仍换题。
        """

        structured = _normalize_patches(patches)
        clarify_answers = None
        if skip:
            sid = str(session_id or "").strip()
            session = self.session_store.load(sid) if sid else None
            if session is None:
                return self._closed_error_result(
                    query=query,
                    requested_mode="plan",
                    response_style=response_style,
                    session=None,
                    code="SESSION_ID_REQUIRED",
                    message="Provide a session_id to skip clarification.",
                    next_action="Open a session, then skip from the clarify card.",
                )
            return self._skip_clarification_result(
                session,
                query=query,
                requested_mode="plan",
                response_style=response_style,
                include_user_text=False,
            )
        if answers is not None:
            folded = self._fold_clarify_answers(session_id, answers)
            if folded is None:
                sid = str(session_id or "").strip()
                session = self.session_store.load(sid) if sid else None
                return self._closed_error_result(
                    query=query,
                    requested_mode="plan",
                    response_style=response_style,
                    session=session,
                    code="CLARIFICATION_ANSWERS",
                    message="Clarification answers do not match the open questions.",
                    next_action="Answer each question, then submit again.",
                    include_user_text=False,
                )
            structured = _normalize_patches(folded)
            clarify_answers = list(answers)
        action = self._unresolved_action(session_id, structured, answers=clarify_answers)
        wire_choice = self._wire_choice_value(session_id, structured, answers=clarify_answers)
        if wire_choice in {"drop_consumer", "use_panel"}:
            plan, session = self._assemble_wire_resume(
                session_id,
                agent_auto=agent_auto,
                choice=wire_choice,
                debug=debug,
            )
            asked = ""
        elif wire_choice:
            text = str(query or "").strip() if wire_choice == "rewrite" else wire_choice
            plan, session = self._assemble_plan(
                text,
                session_id=session_id,
                agent_auto=agent_auto,
                patches=None,
                allow_composer_slot_fill=False,
                replace_query=text,
                debug=debug,
            )
            asked = text
        elif action == "abandon":
            sid = str(session_id or "").strip()
            session = self.session_store.load(sid) if sid else None
            if session is None or session.task is None:
                return self._closed_error_result(
                    query=query,
                    requested_mode="plan",
                    response_style=response_style,
                    session=session,
                    code="SESSION_ID_REQUIRED",
                    message="Provide a session_id to abandon this request.",
                    next_action="Open a session, then choose Abandon on the clarify card.",
                )
            return self._close_clarification_result(
                session,
                query=query,
                requested_mode="plan",
                response_style=response_style,
                include_user_text=False,
                code="CLARIFICATION_ABANDONED",
                message="Request abandoned.",
                next_action="Start a new question when you are ready.",
            )
        elif action == "compose_open":
            plan, session = self._assemble_plan(
                "",
                session_id=session_id,
                agent_auto=agent_auto,
                patches=None,
                allow_composer_slot_fill=allow_composer_slot_fill,
                forced_job="open",
                debug=debug,
            )
            asked = ""
        elif action:
            plan, session = self._assemble_plan(
                action,
                session_id=session_id,
                agent_auto=agent_auto,
                patches=None,
                allow_composer_slot_fill=False,
                replace_query=action,
                debug=debug,
            )
            asked = action
        else:
            asked = query
            if not structured:
                identity = self._identity_response(
                    query,
                    session_id=session_id,
                    requested_mode="plan",
                    response_style=response_style,
                )
                if identity is not None:
                    return identity
                # Web clarifying：不把「跳过」当成控件跳过，交给 assemble 换题。
                skip_hatch = False
                if not allow_composer_slot_fill:
                    sid = str(session_id or "").strip()
                    if sid:
                        peek = self.session_store.load(sid)
                        skip_hatch = peek.task_status() == "clarifying"
                if not skip_hatch:
                    hatched = self._maybe_hatch_mode_gap(
                        query,
                        session_id=session_id,
                        requested_mode="plan",
                        response_style=response_style,
                        persist=persist,
                        keep=keep,
                        explanation_depth=explanation_depth,
                        agent_auto=agent_auto,
                    )
                    if hatched is not None:
                        return hatched
            plan, session = self._assemble_plan(
                query,
                session_id=session_id,
                agent_auto=agent_auto,
                patches=structured or None,
                allow_composer_slot_fill=allow_composer_slot_fill,
                clarify_answers=clarify_answers,
                debug=debug,
            )
        failed = self._clarification_failed_result(
            plan,
            session,
            query=asked,
            requested_mode="plan",
            response_style=response_style,
        )
        if failed is not None:
            return failed
        return self._execute_and_format(
            plan=plan,
            confirm=False,
            response_style=response_style,
            persist=persist,
            keep=keep,
            explanation_depth=explanation_depth,
            session=session,
            query=asked,
            requested_mode="plan",
        )

    def run(
        self,
        query: str,
        *,
        response_style: str = "user_friendly",
        persist: str | None = None,
        keep: bool = False,
        explanation_depth: str = "standard",
        session_id: str | None = None,
        agent_auto: Optional[bool] = None,
        on_step: Any = None,
        on_step_start: Any = None,
        on_progress: Any = None,
    ) -> Dict[str, Any] | AssistantOutput:
        """Plan + 确认执行。

        一次性 ``run(query)`` 保持 B：人敲了 run = 本轮确认，不读 ``allow_*``。
        仅当 session 内 ``agent_auto=True`` 时，``allow_*`` 门控高副作用步。
        live 步永不 auto。
        """

        identity = self._identity_response(
            query,
            session_id=session_id,
            requested_mode="run",
            response_style=response_style,
        )
        if identity is not None:
            return identity
        hatched = self._maybe_hatch_mode_gap(
            query,
            session_id=session_id,
            requested_mode="run",
            response_style=response_style,
            persist=persist,
            keep=keep,
            explanation_depth=explanation_depth,
            agent_auto=agent_auto,
            on_step=on_step,
            on_step_start=on_step_start,
            on_progress=on_progress,
        )
        if hatched is not None:
            return hatched
        plan, session = self._assemble_plan(
            query,
            session_id=session_id,
            agent_auto=agent_auto,
        )
        failed = self._clarification_failed_result(
            plan,
            session,
            query=query,
            requested_mode="run",
            response_style=response_style,
        )
        if failed is not None:
            return failed
        hold = bool((getattr(plan, "assumptions", None) or {}).get("hold_execution"))
        confirm = not hold
        if not hold:
            plan.execution_mode = "execute"
        if session is not None and session.agent_auto:
            plan, confirm = self._apply_agent_auto_gate(plan)
        return self._execute_and_format(
            plan=plan,
            confirm=confirm,
            response_style=response_style,
            persist=persist,
            keep=keep,
            explanation_depth=explanation_depth,
            session=session,
            on_step=on_step,
            on_step_start=on_step_start,
            on_progress=on_progress,
            query=query,
            requested_mode="run",
        )

    def cancel_unexecuted_plan(self, session_id: str) -> None:
        """取消尚未执行的计划。已开始执行的不在这里取消。

        Parameters
        ----------
        session_id : str
            会话 id。没有任务，或状态不是 clarifying / ready 时不改。
        """

        sid = str(session_id or "").strip()
        if not sid:
            return
        state = self.session_store.load(sid)
        if state.task is None or state.task.status not in {"clarifying", "ready"}:
            return
        state.cancel_task()
        self.session_store.save(state)

    def _kept_plan_steps(self, state: ConversationState) -> List[Dict[str, Any]]:
        """澄清卡上的步骤；没有时读这份计划已经保存的图。"""

        task = state.task
        pending = task.pending_clarification if task is not None and isinstance(task.pending_clarification, dict) else {}
        snapshot = pending.get("accepted_steps")
        if isinstance(snapshot, list) and any(isinstance(row, dict) and row.get("skill_name") for row in snapshot):
            return [row for row in snapshot if isinstance(row, dict)]
        plan_id = str(task.plan_id or "") if task is not None else ""
        if not plan_id:
            return []
        payload = self.memory_store.find_run_by_plan_id(plan_id)
        plan = payload.get("plan") if isinstance(payload, dict) else None
        if not isinstance(plan, dict):
            return []
        assumptions = plan.get("assumptions") if isinstance(plan.get("assumptions"), dict) else {}
        accepted = assumptions.get("accepted_steps")
        if isinstance(accepted, list) and accepted:
            return [row for row in accepted if isinstance(row, dict)]
        steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
        return [
            row
            for row in steps
            if isinstance(row, dict)
            and row.get("skill_name")
            and row.get("skill_name") != "qt.ai.system.fallback"
        ]

    def run_plan(
        self,
        plan_id: str,
        *,
        response_style: str = "user_friendly",
        persist: str | None = None,
        keep: bool = False,
        explanation_depth: str = "standard",
        session_id: str | None = None,
        on_step: Any = None,
        on_step_start: Any = None,
        on_progress: Any = None,
        requested_mode: str = "run",
        hatch: str = "",
    ) -> Dict[str, Any] | AssistantOutput:
        """从 ``runs/`` 加载已审阅 ToolPlan 并执行，禁止重新 Hybrid。

        Parameters
        ----------
        plan_id : str
            已落盘计划的 ``plan_id``。
        session_id : str, optional
            若提供则回写当前 ``task.status`` / ``task.plan_id``。
        requested_mode : str, default 'run'
            用户入口；Plan 模式口头执行时为 ``plan``。
        hatch : str, optional
            模式缺口标记，写入人读 ``mode_notice``。
        """

        from .contracts import ToolPlan

        payload = self.memory_store.find_run_by_plan_id(plan_id)
        plan_raw = payload.get("plan") if isinstance(payload, dict) else None
        if not isinstance(plan_raw, dict) or not plan_raw:
            raise ValueError(
                f"Reviewed plan not found in runs/: plan_id={plan_id!r}. "
                "Use plan() first, then run --plan-id with that plan_id."
            )
        plan = ToolPlan.from_dict(plan_raw)
        plan.execution_mode = "execute"
        session = None
        sid = str(session_id or "").strip()
        if sid and is_live_running(sid) and is_live_backgrounded(sid):
            return self._deferred_execute_notice(sid, str(plan_id or ""))
        if sid:
            session = self.session_store.load(sid)
        return self._execute_and_format(
            plan=plan,
            confirm=True,
            response_style=response_style,
            persist=persist,
            keep=keep,
            explanation_depth=explanation_depth,
            session=session,
            on_step=on_step,
            on_step_start=on_step_start,
            on_progress=on_progress,
            query=str(getattr(plan, "user_query", "") or ""),
            requested_mode=str(requested_mode or "run"),
            hatch=str(hatch or ""),
            hatch_plan_id=str(plan_id or ""),
        )

    def _execute_and_format(
        self,
        *,
        plan: Any,
        confirm: bool,
        response_style: str,
        persist: str | None,
        keep: bool,
        explanation_depth: str = "standard",
        session: Optional[ConversationState] = None,
        on_step: Optional[Any] = None,
        on_step_start: Optional[Any] = None,
        on_progress: Optional[Any] = None,
        query: str = "",
        requested_mode: str = "plan",
        hatch: str = "",
        hatch_plan_id: str = "",
    ) -> Dict[str, Any] | AssistantOutput:
        """执行并按策略处理落盘与渲染。"""

        persist_mode = persist or self.run_policy.persist_mode
        persist_run = persist_mode in {"bounded", "audit"}
        execute_requested = bool(confirm)
        closed_note = self._plan_is_closed_note(plan)
        clarify_plan = self._plan_is_clarify(plan)
        if clarify_plan or closed_note:
            confirm = False
        live_sid = ""
        live_generation = ""
        executing_task_id = ""
        append_only = False
        if confirm and session is not None and session.task is not None:
            plan_key = str(getattr(plan, "plan_id", "") or "")
            owns_task = (not plan_key) or str(session.task.plan_id or "") == plan_key
            if owns_task:
                executing_task_id = str(session.task.id or "")
                session.task.status = "running"
                session.task.high_side_effect = plan_has_high_side_effect(plan)
                self.session_store.save(session)
            else:
                executing_task_id = "detached-" + plan_key
                append_only = True
            live_sid = str(session.session_id or "")
            live_generation = register_live_running(
                live_sid,
                steps=list(getattr(plan, "steps", None) or []),
                task_id=executing_task_id,
            )
        reuse_run_id = ""
        assumptions = getattr(plan, "assumptions", None) or {}
        if (
            not confirm
            and session is not None
            and isinstance(assumptions.get("slot_revision"), dict)
            and assumptions.get("slot_revision")
        ):
            existing = self.memory_store.find_run_by_plan_id(str(getattr(plan, "plan_id", "") or ""))
            status = str(((existing.get("execution") or {}) if isinstance(existing, dict) else {}).get("status") or "")
            if status == "dry_run":
                reuse_run_id = str(existing.get("run_id") or "")

        def _on_step_start(step_id: str, skill_name: str, index: int, total: int) -> None:
            if live_sid:
                mark_live_step_start(
                    live_sid,
                    step_id=step_id,
                    skill_name=skill_name,
                    index=index,
                    total=total,
                )
            if on_step_start is not None:
                on_step_start(step_id, skill_name, index, total)

        def _on_step(record: Any) -> None:
            if live_sid:
                result = getattr(record, "result", None) or {}
                if result.get("skipped"):
                    status = "skipped"
                elif result.get("ok"):
                    status = "done"
                else:
                    status = "error"
                mark_live_step_end(
                    live_sid,
                    step_id=str(getattr(record, "step_id", "") or ""),
                    status=status,
                    ok=result.get("ok"),
                )
            if on_step is not None:
                on_step(record)

        def _on_progress(done: int, total: int, label: str = "") -> None:
            if live_sid:
                mark_live_progress(live_sid, done=done, total=total, label=label)
            if on_progress is not None:
                on_progress(done, total, label)

        progress_token = None
        cancel_token = None
        if live_sid:
            install_qteasy_tqdm_bridge()
            progress_token = bind_progress_callback(_on_progress)
            event = live_cancel_event(live_sid)
            if event is not None:
                try:
                    from qteasy.cancel_check import bind_cancel_check
                except ImportError:
                    bind_cancel_check = None
                if bind_cancel_check is not None:
                    cancel_token = bind_cancel_check(event.is_set)
        try:
            try:
                payload = self.executor.execute(
                    plan,
                    confirm=confirm,
                    persist_run=False,
                    on_step=_on_step,
                    on_step_start=_on_step_start if (live_sid or on_step_start is not None) else None,
                    run_id=reuse_run_id,
                )
            except Exception as exc:
                try:
                    from qteasy.cancel_check import RunCancelled
                except ImportError:
                    is_cancelled = False
                else:
                    is_cancelled = isinstance(exc, RunCancelled)
                if is_cancelled:
                    payload = {
                        "execution": {"status": "cancelled", "steps": []},
                        "run_id": "",
                        "plan": plan.to_dict() if hasattr(plan, "to_dict") else {},
                    }
                else:
                    if live_sid:
                        clear_live_running(live_sid, generation=live_generation)
                    raise
        finally:
            if progress_token is not None:
                reset_progress_callback(progress_token)
            if cancel_token is not None:
                try:
                    from qteasy.cancel_check import reset_cancel_check
                except ImportError:
                    reset_cancel_check = None
                if reset_cancel_check is not None:
                    reset_cancel_check(cancel_token)
        start_deferred = False
        try:
            result = self._persist_after_execute(
                payload,
                plan=plan,
                confirm=confirm,
                execute_requested=execute_requested,
                clarify_plan=clarify_plan,
                closed_note=closed_note,
                persist_run=persist_run,
                persist_mode=persist_mode,
                keep=keep,
                session=session,
                query=query,
                requested_mode=requested_mode,
                hatch=hatch,
                hatch_plan_id=hatch_plan_id,
                response_style=response_style,
                explanation_depth=explanation_depth,
                assumptions=assumptions,
                executing_task_id=executing_task_id,
                append_only=append_only,
            )
            start_deferred = bool(live_sid) and not task_was_cancelled(executing_task_id)
            return result
        finally:
            if live_sid:
                clear_live_running(live_sid, generation=live_generation)
            if start_deferred:
                nxt = pop_deferred_run(live_sid)
                if nxt:
                    try:
                        self.run_plan(nxt, session_id=live_sid, response_style="raw")
                    except Exception:
                        pass

    def _persist_after_execute(
        self,
        payload: Dict[str, Any],
        *,
        plan: Any,
        confirm: bool,
        execute_requested: bool,
        clarify_plan: bool,
        closed_note: bool = False,
        persist_run: bool,
        persist_mode: str,
        keep: bool,
        session: Optional[ConversationState],
        query: str,
        requested_mode: str,
        hatch: str,
        hatch_plan_id: str,
        response_style: str,
        explanation_depth: str,
        assumptions: Dict[str, Any],
        executing_task_id: str = "",
        append_only: bool = False,
    ) -> Dict[str, Any] | AssistantOutput:
        """execute 成功后落盘 / 标 done；调用方在 finally 里 clear_live。"""

        write_plan_md = (not confirm) and (not execute_requested) and (not clarify_plan) and (not closed_note)
        if write_plan_md:
            plan_md = tool_plan_to_markdown(
                payload.get("plan") or plan,
                provider=_provider_for_narrative(
                    getattr(self.planner, "provider", None),
                    assumptions,
                    query,
                ),
                registry=self.registry,
            )
            payload["plan_md"] = plan_md
        else:
            plan_md = ""
            payload["plan_md"] = ""
        if hatch:
            payload["hatch"] = hatch
            payload["hatch_plan_id"] = str(hatch_plan_id or "")
        if assumptions.get("topic_skipped"):
            payload["topic_skipped"] = True

        if assumptions.get("block_running"):
            payload["block_running"] = True
        elif assumptions.get("abandoned"):
            if session is not None and session.task is not None:
                session.task.cancel()
            if session is not None:
                self.session_store.save(session)
        elif confirm:
            self._merge_env_facts_from_execution(payload)
        elif session is not None and session.task is not None:
            pending = session.task.pending_clarification
            if closed_note:
                session.task.set_pending(None)
                session.task.set_missing([])
                session.task.mark_done()
            elif clarify_plan or pending or session.task.missing:
                session.task.status = "clarifying"
            else:
                session.task.mark_ready()
                session.task.high_side_effect = plan_has_high_side_effect(plan)
            self.session_store.save(session)

        self._attach_session_payload(payload, plan, session)
        write_plan_md = (not confirm) and (not execute_requested) and (not clarify_plan) and (not closed_note)
        if persist_run:
            run_id = str(payload.get("run_id", "")).strip()
            if run_id:
                run_file = self.memory_store.save_run(run_id, payload)
                payload["run_file"] = run_file
                if confirm or not write_plan_md:
                    payload["plan_md_file"] = ""
                else:
                    md_file = self.memory_store.save_plan_md(run_id, plan_md)
                    payload["plan_md_file"] = md_file
                self._last_run_id = run_id
                if persist_mode == "bounded":
                    cleanup_report = self.memory_store.cleanup_runs(
                        max_age_days=self.run_policy.max_age_days,
                        max_count=self.run_policy.max_count,
                        max_total_mb=self.run_policy.max_total_mb,
                    )
                else:
                    cleanup_report = {"deleted_count": 0, "deleted_files": [], "remaining_count": len(self.memory_store.list_runs())}
                payload["cleanup"] = cleanup_report
                if keep:
                    payload["pinned_file"] = self.memory_store.pin_run(run_id, tag="keep")
        else:
            payload["run_file"] = ""
            payload["plan_md_file"] = ""
            payload["cleanup"] = {"deleted_count": 0, "deleted_files": [], "remaining_count": len(self.memory_store.list_runs())}

        asked = str(query or getattr(plan, "user_query", "") or "")
        include_user = session is None and bool(asked) and not confirm and not hatch
        if session is not None:
            include_user = False
        if isinstance(assumptions.get("slot_revision"), dict) and assumptions.get("slot_revision"):
            payload["slot_revision"] = dict(assumptions.get("slot_revision") or {})
            payload["slot_changes"] = list(assumptions.get("slot_changes") or [])
            payload["revision"] = int(assumptions.get("revision") or 0)
        if assumptions.get("block_running"):
            payload["block_running"] = True
        self._attach_human_cards(
            payload,
            query=asked,
            requested_mode=requested_mode,
            session=session,
            include_user_text=include_user,
            executing_task_id=executing_task_id if confirm else "",
            append_only=append_only if confirm else False,
            run_status=str((payload.get("execution") or {}).get("status") or "") if confirm else "",
        )

        if response_style == "raw":
            return payload

        rendered = self.renderer.render(
            payload,
            style="user_friendly",
            context={"persist_mode": persist_mode},
            explanation_depth=explanation_depth,
        )
        if write_plan_md and plan_md:
            first_lines = "\n".join(plan_md.strip().splitlines()[:6])
            rendered.narrative = rendered.narrative + f"\n\nPlan (markdown preview):\n{first_lines}"
        if self.run_policy.show_save_hint:
            run_file = payload.get("run_file", "")
            hint = f"\nRun file: {run_file}" if run_file else "\nRun file: not persisted."
            plan_md_file = payload.get("plan_md_file", "")
            if plan_md_file:
                hint = hint + f"\nPlan md file: {plan_md_file}"
            rendered.narrative = rendered.narrative + hint
        return rendered

    def _merge_env_facts_from_execution(self, payload: Dict[str, Any]) -> None:
        """将 guide skill 成功探针 merge 进 env_facts（仅 execute 路径）。"""

        steps = (payload.get("execution") or {}).get("steps") or []
        probe: Dict[str, Any] = {}
        for step in steps:
            result = step.get("result") or {}
            if not result.get("ok"):
                continue
            env_probe = (result.get("payload") or {}).get("env_probe")
            if not isinstance(env_probe, dict):
                continue
            for key, value in env_probe.items():
                if key == "tables" and isinstance(value, dict):
                    tables = dict(probe.get("tables") or {})
                    tables.update(value)
                    probe["tables"] = tables
                else:
                    probe[key] = value
        if not probe:
            return
        old = self.memory_store.load_env_facts()
        merged = merge_env_facts(old, probe)
        self.memory_store.save_env_facts(merged)
        self.planner.env_facts = merged

    def _maybe_hatch_mode_gap(
        self,
        query: str,
        *,
        session_id: str | None,
        requested_mode: str,
        response_style: str,
        persist: str | None,
        keep: bool,
        explanation_depth: str,
        agent_auto: Optional[bool] = None,
        on_step: Any = None,
        on_step_start: Any = None,
        on_progress: Any = None,
    ) -> Optional[Dict[str, Any] | AssistantOutput]:
        """讨论、口头执行和整句跳过都不再从这里截走。"""

        del query, session_id, requested_mode, response_style, persist, keep
        del explanation_depth, agent_auto, on_step, on_step_start, on_progress
        return None

    def _skip_clarification_result(
        self,
        session: ConversationState,
        *,
        query: str,
        requested_mode: str,
        response_style: str,
        include_user_text: bool = True,
    ) -> Dict[str, Any] | AssistantOutput:
        """skip 澄清：本句失败结束。"""

        return self._close_clarification_result(
            session,
            query=query,
            requested_mode=requested_mode,
            response_style=response_style,
            include_user_text=include_user_text,
            code="CLARIFICATION_SKIPPED",
            message="Clarification skipped. This request ended.",
            next_action="Start a new question, or provide the missing field next time.",
        )

    def _clarification_failed_result(
        self,
        plan: Any,
        session: Optional[ConversationState],
        *,
        query: str,
        requested_mode: str,
        response_style: str,
    ) -> Dict[str, Any] | AssistantOutput | None:
        """答错耗尽时短路为 G.9 失败收口；否则返回 None。"""

        if session is None or not bool((getattr(plan, "assumptions", None) or {}).get("clarification_failed")):
            return None
        return self._close_clarification_result(
            session,
            query=query,
            requested_mode=requested_mode,
            response_style=response_style,
            include_user_text=False,
            code="CLARIFICATION_FAILED",
            message=_CLARIFICATION_FAILED_MESSAGE,
            next_action="Start a new question with clearer values for the required fields.",
        )

    def _close_clarification_result(
        self,
        session: ConversationState,
        *,
        query: str,
        requested_mode: str,
        response_style: str,
        code: str,
        message: str,
        next_action: str,
        include_user_text: bool = True,
    ) -> Dict[str, Any] | AssistantOutput:
        """澄清失败收口（End skip 与答错耗尽共用骨架）。"""

        session.close_open_card(query, status="skipped")
        if session.task is not None:
            session.task.set_pending(None)
            session.task.set_missing([])
            session.task.mark_done()
        self.session_store.save(session)
        return self._closed_error_result(
            query=query,
            requested_mode=requested_mode,
            response_style=response_style,
            session=session,
            code=code,
            message=message,
            next_action=next_action,
            include_user_text=include_user_text,
        )

    def _closed_error_result(
        self,
        *,
        query: str,
        requested_mode: str,
        response_style: str,
        session: Optional[ConversationState],
        code: str,
        message: str,
        next_action: str,
        include_user_text: bool = True,
    ) -> Dict[str, Any] | AssistantOutput:
        """闭合 Job 的英文 error 卡（不走 Executor）。"""

        payload: Dict[str, Any] = {
            "error": {
                "code": str(code),
                "message": str(message),
                "next_action": str(next_action),
            },
            "execution": {"status": "failed", "steps": []},
        }
        if session is not None:
            self.session_store.save(session)
        dummy = ToolPlan(
            plan_id="",
            user_query=query,
            steps=[],
            assumptions={},
            execution_mode="dry_run",
            mode="plan",
        )
        self._attach_session_payload(payload, dummy, session)
        write_user = include_user_text and (session is None)
        self._attach_human_cards(
            payload,
            query=query,
            requested_mode=requested_mode,
            session=session,
            include_user_text=write_user,
        )
        if response_style == "raw":
            return payload
        return self.renderer.render(payload, style="user_friendly", context={}, explanation_depth="standard")

    @staticmethod
    def _plan_is_closed_note(plan: Any) -> bool:
        """有说明、但没有可答项。不是澄清中断。"""

        assumptions = getattr(plan, "assumptions", None) or {}
        clar = assumptions.get("clarification")
        return isinstance(clar, dict) and bool(clar) and not clarification_needs_answer(clar)

    @staticmethod
    def _plan_is_clarify(plan: Any) -> bool:
        """单步 fallback clarify_required，且还有可答项。本轮不得 execute。"""

        if QteasyAssistant._plan_is_closed_note(plan):
            return False
        steps = list(getattr(plan, "steps", None) or [])
        if len(steps) != 1:
            assumptions = getattr(plan, "assumptions", None) or {}
            clar = assumptions.get("clarification")
            return isinstance(clar, dict) and clarification_needs_answer(clar)
        step = steps[0]
        if str(getattr(step, "skill_name", "") or "") != "qt.ai.system.fallback":
            return False
        return str((getattr(step, "inputs", None) or {}).get("fallback_action") or "") == "clarify_required"

    def _card_submitted_value(
        self,
        session_id: str | None,
        name: str,
        patches: Dict[str, Any],
        answers: Optional[List[Any]] = None,
    ) -> str:
        """按题号读这一题的原文。没有 ``answers`` 时读旧的槽名补丁。"""

        sid = str(session_id or "").strip()
        if not sid:
            return ""
        session = self.session_store.load(sid)
        task = session.task if session is not None else None
        pending = task.pending_clarification if task is not None and isinstance(task.pending_clarification, dict) else {}
        rows = [item for item in (pending.get("pending") or []) if isinstance(item, dict)]
        if not any(str(item.get("name") or "") == name for item in rows):
            return ""
        if answers is not None:
            for index, item in enumerate(rows):
                if str(item.get("name") or "") != name:
                    continue
                if index >= len(answers):
                    return ""
                raw = answers[index]
                return str(raw if raw is not None else "").strip()
            return ""
        if name not in (patches or {}):
            return ""
        return str((patches or {}).get(name) or "").strip()

    def _wire_choice_value(
        self,
        session_id: str | None,
        patches: Dict[str, Any],
        answers: Optional[List[Any]] = None,
    ) -> str:
        """当前卡在问 ``wire_choice`` 时返回这一题的原文，否则空串。"""

        return self._card_submitted_value(session_id, "wire_choice", patches, answers)

    def _fold_clarify_answers(
        self,
        session_id: str | None,
        answers: List[Any],
    ) -> Optional[Dict[str, Any]]:
        """把澄清卡的有序答案折成槽补丁。题数对不上时返回 ``None``。"""

        sid = str(session_id or "").strip()
        session = self.session_store.load(sid) if sid else None
        task = session.task if session is not None else None
        pending = task.pending_clarification if task is not None and isinstance(task.pending_clarification, dict) else {}
        rows = [item for item in (pending.get("pending") or []) if isinstance(item, dict)]
        from .slot_graph import apply_ordered_answers

        return apply_ordered_answers(rows, answers)

    def _seal_clarify(
        self,
        state: ConversationState,
        answer: str,
        label: str,
        answers: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """关闭澄清并立刻落盘，再进入可能很慢的规划。"""

        if state.task is None:
            return
        if not (state.task.pending_clarification or state.task.missing):
            return
        shown = str(label or answer or "").strip()
        state.close_open_card(
            str(answer or ""),
            status="answered",
            answer_label=shown,
            answers=answers,
        )
        state.task.set_pending(None)
        state.task.set_missing([])
        self.session_store.save(state)

    def _commit_stage(self, state: ConversationState, stage_id: str, text: str) -> None:
        """阶段收口写一条人话。本轮回调只被调用这一次。"""

        sentence = str(text or "").strip()
        if state is None or not sentence:
            return
        state.append_messages(
            [
                {
                    "kind": "mode_notice",
                    "text": sentence,
                    "payload": {"stage_id": str(stage_id or "")},
                }
            ]
        )
        self.session_store.save(state)
        hook = getattr(self, "on_stage", None)
        if callable(hook):
            hook(str(stage_id or ""), sentence)

    def _assemble_wire_resume(
        self,
        session_id: str | None,
        *,
        agent_auto: Optional[bool],
        choice: str,
        debug: bool = False,
    ) -> Tuple[Any, Optional[ConversationState]]:
        """按选择卡上已经验证过的步骤快照恢复，不再组图。"""

        self._refresh_planner_env_facts()
        profile = self.memory_store.load_profile()
        sid = str(session_id or "").strip()
        state = self.session_store.load(sid) if sid else None
        if state is None or state.task is None:
            return self.planner.build_plan("", mode="plan", profile=profile, debug=debug), state
        if agent_auto is not None:
            state.agent_auto = bool(agent_auto)
        pending = state.task.pending_clarification if isinstance(state.task.pending_clarification, dict) else {}
        snapshots = pending.get("wire_snapshots") if isinstance(pending.get("wire_snapshots"), dict) else {}
        rows = snapshots.get(choice) if isinstance(snapshots, dict) else None
        snapshot = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        asked = str(state.task.user_query or "").strip()
        if state.task.pending_clarification or state.task.missing:
            self._seal_clarify(state, choice, option_answer_label(pending, choice))
        held = self.planner.provider
        self.planner.provider = None
        self.planner._wire_resume = True
        try:
            plan = self.planner.build_plan(
                asked,
                mode="plan",
                session=state,
                profile=profile,
                resume_steps=snapshot or None,
                debug=debug,
            )
        finally:
            self.planner.provider = held
            self.planner._wire_resume = False
        self._sync_session_from_plan(state, plan, query=asked, skip_classify=True)
        self.session_store.save(state)
        return plan, state

    def _unresolved_action(
        self,
        session_id: str | None,
        patches: Dict[str, Any],
        answers: Optional[List[Any]] = None,
    ) -> str:
        """当前卡在问 ``unresolved_intent`` 时返回这一题的原文，否则空串。"""

        return self._card_submitted_value(session_id, "unresolved_intent", patches, answers)

    def _composer_parse(
        self,
        state: ConversationState,
        asked: str,
        prior_messages: List[Dict[str, Any]],
        profile: Dict[str, Any],
        debug: bool,
    ) -> Tuple[Any, ConversationState]:
        """宪法一次，然后提纲和解析。点名只再解析一次。"""

        engine = self.planner.intent_engine
        engine.provider = self.planner.provider
        blocked = engine._constitution(asked, asked.lower())
        if blocked is not None:
            package = constitution_package(asked, blocked)
            if not debug:
                package.pop("debug_entries", None)
        else:
            outline, cards = self.planner.outline_from(prior_messages)
            package = self.planner.parse_fetched(asked, outline, cards, state, debug=debug)
        return self._build_parsed(state, package, asked, profile, debug)

    def _answer_parse_card(
        self,
        state: ConversationState,
        pending: Dict[str, Any],
        structured: Dict[str, Any],
        asked: str,
        profile: Dict[str, Any],
        debug: bool,
    ) -> Tuple[Any, ConversationState]:
        """意图卡沿用当时的 relation。恢复卡先改成 new。空白框回到同一次解析。"""

        rows = [item for item in (pending.get("pending") or []) if isinstance(item, dict)]
        row = rows[0] if rows else {}
        name = str(row.get("name") or "")
        answer = str(structured.get(name) or asked or "").strip()
        package = dict(pending.get("parse_package") or {})
        matched = ""
        for item in row.get("options") or []:
            if not isinstance(item, dict):
                continue
            ident = str(item.get("id") or "")
            if ident == CONFIRM_OPEN_ID:
                continue
            if answer and answer in {ident, str(item.get("label") or "")}:
                matched = ident
                break
        recover = bool(pending.get("recover_authored"))
        utterance = str(package.get("utterance") or asked)
        if recover and matched:
            package["relation"] = "new"
            package["original_relation"] = "new"
            package["job"] = matched
            package["confirmed"] = "recovery"
            package["choice"] = matched
            package["card"] = "recover"
            package["open_intent"] = ""
            return self._build_parsed(state, package, utterance, profile, debug)
        if not recover and answer == CONFIRM_OPEN_ID:
            package["job"] = "open"
            package["confirmed"] = "open_intent"
            package["choice"] = CONFIRM_OPEN_ID
            package["card"] = "intent"
            return self._build_parsed(state, package, utterance, profile, debug)
        if not recover and matched:
            package["job"] = matched
            package["confirmed"] = "candidate"
            package["choice"] = matched
            package["card"] = "intent"
            package["open_intent"] = ""
            return self._build_parsed(state, package, utterance, profile, debug)
        if recover:
            if state.task is not None:
                state.task.intent_card_replies = []
                state.task.intent_fetched = ""
            prior = [dict(item) for item in (state.messages or []) if isinstance(item, dict)]
            if answer:
                state.append_user_text(answer)
                self.session_store.save(state)
            return self._composer_parse(state, answer, prior, profile, debug)
        return self._reparse_card_reply(state, pending, row, package, answer, profile, debug)

    def _reparse_card_reply(
        self,
        state: ConversationState,
        pending: Dict[str, Any],
        row: Dict[str, Any],
        package: Dict[str, Any],
        answer: str,
        profile: Dict[str, Any],
        debug: bool,
    ) -> Tuple[Any, ConversationState]:
        """空白框是这张卡的回复。拦住则留在原卡，通过则用原句再解析。

        Parameters
        ----------
        state : ConversationState
            当前会话。
        pending : dict
            提交前的意图卡。
        row : dict
            卡上的那一题。
        package : dict
            发出这张卡时的解析整包。
        answer : str
            空白框里的回复。
        profile : dict
            用户配置。
        debug : bool
            是否写入解析调试记录。

        Returns
        -------
        tuple
            计划与会话。
        """

        utterance = str(package.get("utterance") or "")
        if not answer:
            return self._same_intent_plan(state, pending, utterance), state
        engine = self.planner.intent_engine
        engine.provider = self.planner.provider
        blocked = engine._constitution(answer, answer.lower())
        if blocked is not None:
            hint = self.planner.hint_for_constitution(answer, blocked)
            if hint:
                state.append_messages(
                    [
                        {
                            "kind": "mode_notice",
                            "text": hint,
                            "payload": {"reason": "constitution_reply"},
                        }
                    ]
                )
                self.session_store.save(state)
            return self._same_intent_plan(state, pending, utterance), state
        official = []
        for item in row.get("options") or []:
            if not isinstance(item, dict):
                continue
            ident = str(item.get("id") or "")
            if not ident or ident == CONFIRM_OPEN_ID:
                continue
            official.append({"id": ident, "label": str(item.get("label") or ident)})
        reply_row = {
            "prompt": str(row.get("prompt") or ""),
            "options": official,
            "open_intent": str(package.get("open_intent") or ""),
            "reply": answer,
        }
        task = state.task
        history = [dict(item) for item in (getattr(task, "intent_card_replies", None) or []) if isinstance(item, dict)]
        history.append(reply_row)
        if task is not None:
            task.intent_card_replies = history
        prior: List[Dict[str, Any]] = []
        for item in state.messages or []:
            if not isinstance(item, dict):
                continue
            if item.get("kind") == "user_text" and str(item.get("text") or "") == utterance:
                break
            prior.append(dict(item))
        outline, cards = self.planner.outline_from(prior)
        fetched = str(getattr(task, "intent_fetched", "") or "") if task is not None else ""
        parsed = self.planner.parse_fetched(
            utterance,
            outline,
            cards,
            state,
            debug=debug,
            prior_fetched=fetched,
            card_replies=format_card_replies(history),
        )
        return self._build_parsed(state, parsed, utterance, profile, debug)

    def _same_intent_plan(
        self,
        state: ConversationState,
        pending: Dict[str, Any],
        utterance: str,
    ) -> ToolPlan:
        """原意图卡继续可答。不重新投影一条相同的澄清。

        Parameters
        ----------
        state : ConversationState
            当前会话。
        pending : dict
            提交前的意图卡。
        utterance : str
            发出这张卡的原句。

        Returns
        -------
        ToolPlan
            仍带这张澄清卡的计划。
        """

        task = state.task
        plan_id = str(getattr(task, "plan_id", "") or "") or new_plan_id()
        record = getattr(task, "parse_record", None) if task is not None else None
        return ToolPlan(
            plan_id=plan_id,
            user_query=utterance or str(getattr(task, "user_query", "") or ""),
            steps=[],
            assumptions={
                "clarification": dict(pending) if isinstance(pending, dict) else {},
                "parse_record": dict(record) if isinstance(record, dict) else {},
            },
        )

    def _build_parsed(
        self,
        state: ConversationState,
        package: Dict[str, Any],
        query: str,
        profile: Dict[str, Any],
        debug: bool,
    ) -> Tuple[Any, ConversationState]:
        """用已经解析的整包出计划。点选不再解析。"""

        kept = self._kept_plan_steps(state)
        plan = self.planner.build_plan(
            query,
            mode="plan",
            session=state,
            profile=profile,
            kept_steps=kept,
            parsed=package,
            debug=debug,
        )
        _merge_fill_slots(state, plan)
        self._sync_session_from_plan(state, plan, query=query, skip_classify=False)
        self._remember_intent(state, plan)
        self.session_store.save(state)
        return plan, state

    @staticmethod
    def _remember_intent(state: ConversationState, plan: Any) -> None:
        """卡片和选择记在意图历史上，不并进填槽历史。"""

        task = state.task
        if task is None:
            return
        record = (getattr(plan, "assumptions", None) or {}).get("parse_record")
        if not isinstance(record, dict):
            return
        card = str(record.get("card") or "")
        choice = str(record.get("choice") or "")
        if not card and not choice:
            return
        history = [dict(item) for item in (task.intent_history or []) if isinstance(item, dict)]
        history.append(
            {
                "card": card,
                "choice": choice,
                "relation": str(record.get("relation") or ""),
                "job": str(record.get("job") or ""),
            }
        )
        task.intent_history = history

    def _assemble_plan(
        self,
        query: str,
        *,
        session_id: str | None,
        agent_auto: Optional[bool],
        patches: Optional[Dict[str, Any]] = None,
        allow_composer_slot_fill: bool = True,
        forced_job: str = "",
        replace_query: str = "",
        clarify_answers: Optional[List[Any]] = None,
        debug: bool = False,
    ) -> Tuple[Any, Optional[ConversationState]]:
        """Composer 先记 user_text，再按 Task 转移表路由。"""

        self._refresh_planner_env_facts()
        profile = self.memory_store.load_profile()
        sid = str(session_id or "").strip()
        if not sid:
            return self.planner.build_plan(
                query,
                mode="plan",
                profile=profile,
                forced_job=forced_job,
                debug=debug,
            ), None

        state = self.session_store.load(sid)
        if agent_auto is not None:
            state.agent_auto = bool(agent_auto)
        if str(forced_job or "") == "open" or str(replace_query or "").strip():
            return self._assemble_recovery(
                state,
                profile=profile,
                forced_job=forced_job,
                replace_query=replace_query,
                debug=debug,
            )
        structured = _normalize_patches(patches)
        inbound = "control" if structured or clarify_answers is not None else "composer"
        asked = str(query or "").strip()
        skip_classify = False
        topic_skipped = False
        user_answered = False
        keep_plan_id = ""
        resume_steps = None
        slot_revision: Optional[Dict[str, Any]] = None
        slot_changes: List[Dict[str, Any]] = []
        card_text: Dict[str, str] = {}
        card_items: Dict[str, Any] = {}
        revision_query = ""
        kept_steps: Optional[List[Dict[str, Any]]] = None
        clause_split = None
        revising = False

        prior_messages = [dict(item) for item in (state.messages or []) if isinstance(item, dict)]
        if inbound == "composer" and asked:
            if state.task is not None:
                state.task.intent_card_replies = []
                state.task.intent_fetched = ""
            state.append_user_text(asked)
            self.session_store.save(state)

        if inbound == "control":
            pending = (
                state.task.pending_clarification
                if state.task is not None and isinstance(state.task.pending_clarification, dict)
                else {}
            )
            if pending.get("intent_authored") or pending.get("recover_authored"):
                return self._answer_parse_card(
                    state,
                    pending,
                    structured,
                    asked,
                    profile,
                    debug,
                )
            card_text, card_items = _take_card_payload(pending, structured)
            slot_revision = dict(card_text)
            kept_steps = self._kept_plan_steps(state)
            answer = next((str(value) for value in structured.values() if value not in (None, "")), "")
            skip_classify = bool(state.task and state.task.job)
            keep_plan_id = str(state.task.plan_id or "") if state.task is not None else ""
            snapshot = pending.get("accepted_steps")
            if state.task is not None and (pending or state.task.missing):
                if clarify_answers is not None:
                    self._seal_clarify(
                        state,
                        "",
                        "",
                        answers=question_answer_rows(pending, clarify_answers),
                    )
                else:
                    self._seal_clarify(state, answer, option_answer_label(pending, answer))
                user_answered = True
            if (
                str(pending.get("resume_job") or "") == "open"
                and isinstance(snapshot, list)
                and snapshot
            ):
                resume_steps = [row for row in snapshot if isinstance(row, dict)]
                asked = str(state.task.user_query or asked).strip()
            if state.task is not None:
                state.task.revision = int(state.task.revision or 0) + 1
                if state.task.status in {"done", "cancelled", ""}:
                    state.task.mark_ready()
        elif asked:
            gate = self.session_gate.classify(state, asked)
            if gate.kind == "block_running":
                plan = self._block_running_plan(asked, debug=debug)
                if state.task is not None and state.task.plan_id:
                    plan.plan_id = str(state.task.plan_id)
                self._sync_session_from_plan(state, plan, query=asked, skip_classify=False)
                self.session_store.save(state)
                return plan, state
            return self._composer_parse(state, asked, prior_messages, profile, debug)

        if inbound == "control" and state.task is not None:
            _append_clarify_history(state.task, pending, card_text, card_items)
        plan = self.planner.build_plan(
            asked or query,
            mode="plan",
            session=state,
            skip_classify=skip_classify,
            profile=profile,
            resume_steps=resume_steps,
            card_text=card_text or None,
            card_items=card_items or None,
            revision_query=revision_query,
            kept_steps=kept_steps,
            clause_split=clause_split,
            debug=debug,
        )
        _merge_fill_slots(state, plan)
        if keep_plan_id and (inbound == "control" or revising):
            plan.plan_id = keep_plan_id
        if topic_skipped:
            plan.assumptions = dict(plan.assumptions or {})
            plan.assumptions["topic_skipped"] = True
        if slot_revision:
            slot_changes = _submission_changes(pending, card_text, card_items)
            slot_changes = _mark_rejected_slot_changes(slot_changes, getattr(plan, "assumptions", None))
            plan.assumptions = dict(plan.assumptions or {})
            plan.assumptions["slot_revision"] = dict(slot_revision)
            plan.assumptions["slot_changes"] = list(slot_changes)
            plan.assumptions["revision"] = int(getattr(state.task, "revision", 0) or 0) if state.task else 0
        self._sync_session_from_plan(state, plan, query=asked or query, skip_classify=skip_classify)
        if revising and state.task is not None:
            new_job = str((plan.assumptions or {}).get("intent_job") or "")
            if new_job and new_job not in {"clarify", "route_to_ask", "unsafe", "open", "not_supported"}:
                state.task.job = new_job
            if keep_plan_id:
                state.task.plan_id = keep_plan_id
        self._apply_clarify_answer_streak(state, plan, user_answered=user_answered)
        self.session_store.save(state)
        return plan, state

    def _assemble_recovery(
        self,
        state: ConversationState,
        *,
        profile: Dict[str, Any],
        forced_job: str,
        replace_query: str,
        debug: bool = False,
    ) -> Tuple[Any, ConversationState]:
        """恢复卡的两个规划动作：强制 open，或用新句子重新分类。"""

        if str(forced_job or "") == "open":
            if state.task is None:
                state.start_task(query="")
            asked = str(state.task.user_query or "").strip()
            pending_card = (
                state.task.pending_clarification
                if isinstance(state.task.pending_clarification, dict)
                else {}
            )
            if state.task.pending_clarification or state.task.missing:
                self._seal_clarify(state, "compose_open", option_answer_label(pending_card, "compose_open"))
            chinese = bool(_CJK_STAGE.search(asked))
            self._commit_stage(state, "compose_open", _STAGE_OPEN_ZH if chinese else _STAGE_OPEN_EN)
            plan = self.planner.build_plan(
                asked,
                mode="plan",
                session=state,
                skip_classify=False,
                profile=profile,
                forced_job="open",
                debug=debug,
            )
            self._sync_session_from_plan(state, plan, query=asked, skip_classify=False)
            clar = (plan.assumptions or {}).get("clarification")
            if state.task is not None and isinstance(clar, dict) and clar and not clarification_needs_answer(clar):
                state.task.set_pending(None)
                state.task.set_missing([])
                state.task.mark_done()
            elif state.task is not None and not isinstance(clar, dict):
                if state.task.status == "clarifying":
                    state.task.mark_ready()
            self.session_store.save(state)
            return plan, state

        text = str(replace_query or "").strip()
        backgrounded = is_live_backgrounded(state.session_id)
        cancelled = bool(
            state.task and state.task.status in {"clarifying", "ready", "running"}
        ) and not backgrounded
        if text:
            state.append_user_text(text)
        if cancelled:
            state.cancel_task()
        state.start_task(query=text)
        merge_facts(state, new_task_patches(text), source="extracted", confirmed=True)
        plan = self.planner.build_plan(text, mode="plan", session=state, profile=profile, debug=debug)
        if cancelled:
            plan.assumptions = dict(plan.assumptions or {})
            plan.assumptions["topic_skipped"] = True
        self._sync_session_from_plan(state, plan, query=text, skip_classify=False)
        self.session_store.save(state)
        return plan, state

    def _block_running_plan(self, query: str, *, debug: bool = False) -> Any:
        """高副作用 running 时拒绝换题。请用户等待，或放弃当前计划。"""

        record = {
            "utterance": str(query or ""),
            "intent_text": "",
            "clarification_text": "",
            "open_intent": "",
            "job": "",
            "task": "",
            "questions": [],
            "relation": "",
            "plan_id": "",
            "candidates": [],
            "confirmed_by": "",
            "card": "",
            "choice": "",
            "constitution_hint": "",
            "block_hint": BLOCK_HINT,
            "open_note": "",
            "executable": False,
        }
        trace: Dict[str, Any] = {
            "intent_job": "clarify",
            "source": "session",
            "rationale": "block_running",
        }
        if debug:
            trace["parse_debug"] = [
                {
                    "outline": "",
                    "fetched": "",
                    "protocol": "",
                    "gold_id": "",
                    "rationale": "block_running",
                }
            ]
        return ToolPlan(
            plan_id=new_plan_id(),
            user_query=query,
            steps=[
                self.planner._make_step(
                    step_id="step_1",
                    skill_name="qt.ai.system.fallback",
                    inputs=self.planner._fallback_step_inputs(
                        query=query,
                        action="clarify_required",
                        reason="block_running",
                        hint=BLOCK_HINT,
                        missing_info="none",
                        next_step="Wait for the running plan to finish, or abandon it.",
                    ),
                )
            ],
            assumptions={
                "intent_job": "clarify",
                "block_running": True,
                "parse_record": record,
                "hold_execution": True,
            },
            execution_mode="dry_run",
            mode="plan",
            planner_trace=trace,
        )

    def confirm_kb_write(
        self,
        session_id: str,
        *,
        confirm: bool = True,
        response_style: str = "user_friendly",
    ) -> Dict[str, Any] | AssistantOutput:
        """确认后写入用户身份文件。没有待确认的身份变更时保持原失败。

        Parameters
        ----------
        session_id : str
            会话 id。
        confirm : bool, default True
            True 写入；False 且存在待确认身份卡时只取消。
        response_style : {'user_friendly', 'raw'}, default 'user_friendly'
            raw 返回字典。

        Returns
        -------
        dict or AssistantOutput
            确认或取消后的人读结果。

        Raises
        ------
        ValueError
            未确认，或没有待写入的身份变更。
        """

        sid = str(session_id or "").strip()
        session = self.session_store.load(sid) if sid else None
        index = _pending_identity_index(session)
        if not confirm:
            if index < 0:
                raise ValueError("KB write requires explicit confirmation.")
            _mark_identity_pending(session, index, pending=False)
            self.session_store.save(session)
            return self._identity_notice_payload(
                session,
                text=str(session.messages[index].get("text") or ""),
                response_style=response_style,
            )
        if index < 0:
            raise ValueError("No pending user-KB write to confirm.")
        spec = _identity_spec(session.messages[index])
        if str(spec.get("action") or "") == "restore":
            remove_identity_file(self.memory_store.user_kb_dir)
        else:
            write_identity_file(
                self.memory_store.user_kb_dir,
                name=str(spec.get("name") or ""),
                voice=str(spec.get("voice") or ""),
            )
        self.memory_store.compile_user_kb()
        _mark_identity_pending(session, index, pending=False)
        self.session_store.save(session)
        return self._identity_notice_payload(
            session,
            text=str(session.messages[index].get("text") or ""),
            response_style=response_style,
        )

    def _identity_response(
        self,
        query: str,
        *,
        session_id: str | None,
        requested_mode: str,
        response_style: str,
    ) -> Dict[str, Any] | AssistantOutput | None:
        """身份变更先出确认卡，不写文件。不是身份句时返回 None。"""

        utterance = parse_identity_utterance(query)
        if utterance is None:
            return None
        if utterance.action == "refuse":
            text = utterance.refusal
            spec: Dict[str, Any] = {}
        else:
            text = utterance.confirm_text
            spec = {
                "identity_write": {
                    "pending": True,
                    "action": utterance.action,
                    "name": utterance.name,
                    "voice": utterance.voice,
                }
            }
        sid = str(session_id or "").strip()
        session = self.session_store.load(sid) if sid else None
        card = {"kind": "mode_notice", "text": text, "payload": spec}
        if session is not None:
            last = session.messages[-1] if session.messages else {}
            already = (
                str(last.get("kind") or "") == "user_text"
                and str(last.get("text") or "").strip() == str(query or "").strip()
            )
            if not already:
                session.append_user_text(query)
            session.append_messages([card])
            self.session_store.save(session)
        cards = [
            {"kind": "user_text", "text": str(query or ""), "payload": {}},
            card,
        ]
        return self._identity_notice_payload(
            session,
            text=text,
            response_style=response_style,
            cards=cards,
            requested_mode=requested_mode,
        )

    def _identity_notice_payload(
        self,
        session: Optional[ConversationState],
        *,
        text: str,
        response_style: str,
        cards: Optional[List[Dict[str, Any]]] = None,
        requested_mode: str = "ask",
    ) -> Dict[str, Any] | AssistantOutput:
        """身份确认卡的 raw / user_friendly 返回。"""

        sid = session.session_id if session is not None else ""
        payload: Dict[str, Any] = {
            "mode": "ask",
            "requested_mode": requested_mode,
            "narrative": text,
            "answer": text,
            "sources": [],
            "human_cards": list(cards or []),
        }
        if sid:
            payload["session"] = {"session_id": sid}
        if response_style == "raw":
            return payload
        return AssistantOutput(
            narrative=text,
            python_code="",
            result_preview="",
            raw=payload,
        )

    def _sync_session_from_plan(
        self,
        state: ConversationState,
        plan: Any,
        *,
        query: str,
        skip_classify: bool,
    ) -> None:
        """把本轮 Job / 缺失槽 / 澄清回写当前 Task。"""

        job = str((plan.planner_trace or {}).get("intent_job") or "")
        flags = dict(state.task.flags or {}) if state.task is not None else {}
        incoming = (getattr(plan, "assumptions", None) or {}).get("intent_flags")
        if isinstance(incoming, dict):
            flags.update(incoming)
        if job and job not in {"clarify", "route_to_ask", "unsafe", "open"}:
            if state.task is None:
                state.start_task(query=query, job=job, flags=flags)
            elif not skip_classify or not state.task.job:
                state.task.job = job
                state.task.flags = flags
        if state.task is not None and not state.task.user_query:
            state.task.user_query = query
        missing = list((plan.assumptions or {}).get("session_missing") or [])
        clarification = (plan.assumptions or {}).get("clarification")
        if state.task is None:
            parsed_now = (plan.assumptions or {}).get("parse_record")
            if not isinstance(parsed_now, dict):
                return
            state.start_task(query=query)
        answerable = isinstance(clarification, dict) and clarification_needs_answer(clarification)
        closed_note = isinstance(clarification, dict) and bool(clarification) and not answerable
        if closed_note:
            state.task.set_pending(None)
            state.task.set_missing([])
            state.task.mark_done()
        elif answerable:
            state.task.set_pending(clarification)
            state.task.set_missing(missing)
        elif missing:
            state.task.set_missing(missing)
            state.task.set_pending(None)
        else:
            state.task.set_missing([])
            state.task.set_pending(None)
        state.task.plan_id = str(getattr(plan, "plan_id", "") or "")
        record = (plan.assumptions or {}).get("fill_record")
        if isinstance(record, dict):
            state.task.fill_record = dict(record)
        parsed = (plan.assumptions or {}).get("parse_record")
        if isinstance(parsed, dict):
            state.task.parse_record = dict(parsed)
        debug_rows = (plan.planner_trace or {}).get("parse_debug")
        if isinstance(debug_rows, list) and debug_rows:
            state.task.parse_debug = [dict(item) for item in debug_rows if isinstance(item, dict)]

    @staticmethod
    def _apply_clarify_answer_streak(
        state: ConversationState,
        plan: Any,
        *,
        user_answered: bool,
    ) -> None:
        """用户提交后仍缺才升 clarify_round；3=last chance；到 4 就停，卡片留下。"""

        if not user_answered or state.task is None:
            return
        if not state.task.missing:
            return
        if int(state.task.clarify_round or 0) >= 4:
            return
        state.task.clarify_round = int(state.task.clarify_round or 0) + 1
        assumptions = dict(getattr(plan, "assumptions", None) or {})
        if state.task.clarify_round == 3:
            clar = assumptions.get("clarification")
            if isinstance(clar, dict):
                clar = dict(clar)
                prompt = str(clar.get("confirm_prompt") or "").strip()
                if _LAST_CHANCE_PROMPT not in prompt:
                    clar["confirm_prompt"] = (
                        f"{prompt} {_LAST_CHANCE_PROMPT}".strip()
                        if prompt
                        else _LAST_CHANCE_PROMPT
                    )
                assumptions["clarification"] = clar
                plan.assumptions = assumptions
                state.task.set_pending(clar)

    @staticmethod
    def _slot_summary(state: ConversationState) -> str:
        """已确认槽的短摘要（截断）。"""

        parts = []
        slots = state.task.slots if state.task is not None else {}
        for key, slot in (slots or {}).items():
            if not slot.confirmed or slot.value in (None, ""):
                continue
            parts.append(f"{key}={slot.value}")
        text = "; ".join(parts)
        return text[:400]

    def _attach_human_cards(
        self,
        payload: Dict[str, Any],
        *,
        query: str,
        requested_mode: str,
        session: Optional[ConversationState],
        include_user_text: bool = True,
        executing_task_id: str = "",
        append_only: bool = False,
        run_status: str = "",
    ) -> None:
        """投影人读卡写入 payload 与 session messages[]。"""

        payload["requested_mode"] = str(requested_mode or "")
        payload["effective_kind"] = infer_effective_kind(payload)
        cards = project_human_cards(
            payload,
            requested_mode=requested_mode,
            query=query,
            registry=self.registry,
            include_user_text=include_user_text,
        )
        plan_blob = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
        plan_assumptions = plan_blob.get("assumptions") if isinstance(plan_blob, dict) else {}
        cards = polish_human_cards(
            cards,
            provider=_provider_for_narrative(
                getattr(self.planner, "provider", None),
                plan_assumptions,
                query,
            ),
            query=query,
            identity_dir=self.memory_store.user_kb_dir,
        )
        execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
        cards = attach_result_reading(
            cards,
            plan_blob if isinstance(plan_blob, dict) else {},
            execution,
            provider=getattr(self.planner, "provider", None),
            identity_dir=self.memory_store.user_kb_dir,
        )
        from .run_view import stamp_result_cards
        from .workbench.mapper import step_artifact_index

        run_id = str(payload.get("run_id") or "")
        exec_steps = [item for item in (execution.get("steps") or []) if isinstance(item, dict)]
        cards = stamp_result_cards(cards, payload, step_artifact_index(run_id, exec_steps))
        payload["human_cards"] = cards
        if session is None:
            return
        if not executing_task_id:
            session.append_messages(cards)
            self.session_store.save(session)
            return
        self._commit_execute_cards(
            session,
            cards,
            executing_task_id=executing_task_id,
            append_only=append_only,
            run_status=run_status,
            run_id=str(payload.get("run_id") or ""),
        )

    def _commit_execute_cards(
        self,
        session: ConversationState,
        cards: list,
        *,
        executing_task_id: str,
        append_only: bool,
        run_status: str,
        run_id: str,
    ) -> None:
        """锁内重载后再写 Task / 结果卡，避免旧对象盖掉 Stop 或新 Task。"""

        with _LIVE_LOCK:
            if task_was_cancelled(executing_task_id):
                return
            fresh = self.session_store.load(session.session_id)
            task = fresh.task
            same = task is not None and str(task.id or "") == str(executing_task_id)
            if same and str(task.status or "") == "running" and not append_only:
                task.mark_done()
                task.run_id = str(run_id or "")
                if run_status == "success":
                    task.set_pending(None)
                    task.set_missing([])
            elif not same and not append_only and not is_live_backgrounded(session.session_id):
                return
            fresh.append_messages(cards)
            self.session_store.save(fresh)

    def _deferred_execute_notice(self, session_id: str, plan_id: str) -> Dict[str, Any]:
        """后台仍在跑时，把新的 execute 排成一条等待。"""

        replaced = set_deferred_run(session_id, plan_id)
        text = DEFERRED_REPLACED_NOTICE if replaced else DEFERRED_RUN_NOTICE
        state = self.session_store.load(session_id)
        state.append_messages(
            [
                {
                    "kind": "mode_notice",
                    "text": text,
                    "payload": {"reason": "deferred_run", "plan_id": str(plan_id or "")},
                }
            ]
        )
        self.session_store.save(state)
        return {
            "mode": "plan",
            "plan": {"plan_id": str(plan_id or ""), "steps": [], "assumptions": {"deferred_run": True}},
            "execution": {"status": "", "steps": []},
            "assumptions": {"deferred_run": True},
            "deferred_run": True,
        }

    def _attach_session_payload(
        self,
        payload: Dict[str, Any],
        plan: Any,
        session: Optional[ConversationState],
    ) -> None:
        """把 clarification / session 挂到响应。"""

        clarification = (getattr(plan, "assumptions", None) or {}).get("clarification")
        if isinstance(clarification, dict):
            payload["clarification"] = clarification
        if session is not None:
            task = session.task
            payload["session"] = {
                "session_id": session.session_id,
                "clarify_round": int(task.clarify_round) if task is not None else 0,
                "current_plan_id": str(task.plan_id or "") if task is not None else "",
                "missing": list(task.missing) if task is not None else [],
                "agent_auto": session.agent_auto,
            }

    def _apply_agent_auto_gate(self, plan: Any) -> Tuple[Any, bool]:
        """agent_auto 下按 allow_* 拦截高副作用；live 永不执行。"""

        profile = self.memory_store.load_profile()
        agent = profile.get("agent") if isinstance(profile.get("agent"), dict) else {}
        blocked: list[str] = []
        for step in plan.steps:
            name = step.skill_name
            if name in self._LIVE_SKILLS:
                blocked.append(name)
                continue
            flag = self._ALLOW_FLAGS.get(name)
            if flag and not bool(agent.get(flag)):
                blocked.append(name)
        if blocked:
            plan.execution_mode = "dry_run"
            plan.assumptions = dict(plan.assumptions or {})
            plan.assumptions["allow_gate_blocked"] = blocked
            return plan, False
        return plan, True

    def debug_config(self) -> Dict[str, Any]:
        """返回当前 AI 配置诊断信息（不泄露密钥）。"""

        config_center = ConfigCenter()
        provider_cfg = config_center.resolve_provider_config()
        trace = config_center.get_trace()
        api_key = str(provider_cfg.get("api_key", "")).strip()
        return {
            "provider_enabled": self.planner.provider is not None,
            "model": str(provider_cfg.get("model", "")).strip(),
            "base_url": str(provider_cfg.get("base_url", "")).strip(),
            "timeout": int(provider_cfg.get("timeout", DEFAULT_PROVIDER_TIMEOUT)),
            "api_key_present": bool(api_key),
            "config_sources": {key: item.get("source", "") for key, item in trace.items()},
        }

    def pin_last_run(self, tag: str = "") -> str:
        """将最近一次 run 记录钉住保存。"""

        if not self._last_run_id:
            raise ValueError("No run has been persisted yet.")
        return self.memory_store.pin_run(self._last_run_id, tag=tag)
