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

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .ask_engine import AskEngine, AskResponse
from .config import DEFAULT_PROVIDER_TIMEOUT, ConfigCenter
from .contracts import ToolPlan, new_plan_id
from .executor import PlanExecutor
from .human_card import infer_effective_kind, project_human_cards
from .knowledge_base import KnowledgeBase
from .memory_store import MemoryStore, merge_env_facts
from .output import AssistantOutput
from .plan_markdown import tool_plan_to_markdown
from .planner import Planner
from .provider import BaseLLMProvider
from .renderer import OutputRenderer
from .registry import SkillRegistry
from .run_policy import RunStorePolicy
from .session import ConversationState, SessionStore
from .session_gate import SessionGate, extract_patches, merge_facts
from .open_workflow import (
    apply_spec_patches,
    is_design_loop,
    maybe_mark_builder_open_loop,
    pending_kb_write_from_spec,
    search_user_kb,
    write_confirmed_note,
)
from .skills import (
    build_backtest_run_skill,
    build_check_tushare_skill,
    build_data_read_skill,
    build_data_refill_skill,
    build_data_summary_skill,
    build_factor_ic_summary_skill,
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
    build_visual_export_skill,
)


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
        build_data_summary_skill,
        build_data_read_skill,
        build_visual_export_skill,
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
        self._last_run_id = ""

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
        session_context = ""
        session = None
        sid = str(session_id or "").strip()
        if sid:
            session = self.session_store.load(sid)
            session_context = self._slot_summary(session)
            session.turns.append({"query": query, "kind": "ask"})
            self.session_store.save(session)
        result: AskResponse = self.ask_engine.ask(
            query,
            explanation_depth=explanation_depth,
            session_context=session_context,
        )
        payload = result.to_dict()
        if session is not None:
            payload["session"] = {"session_id": session.session_id, "slots_summary": session_context}
        self._attach_human_cards(
            payload,
            query=query,
            requested_mode=str(requested_mode or "ask"),
            session=session,
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
    ) -> Dict[str, Any] | AssistantOutput:
        """Plan 模式：生成 dry_run 计划。

        与 `ask()` 的区别在于：
        - ask：KnowledgeBase 问答，无 skill / 无 Executor；
        - plan / preview：生成可审阅 ToolPlan steps，不执行。
        """

        plan, session = self._assemble_plan(
            query,
            session_id=session_id,
            agent_auto=agent_auto,
        )
        if str((plan.planner_trace or {}).get("intent_job") or "") == "route_to_ask":
            return self.ask(
                query,
                response_style=response_style,
                persist=persist,
                keep=keep,
                explanation_depth=explanation_depth,
                session_id=session_id,
                requested_mode="plan",
            )
        return self._execute_and_format(
            plan=plan,
            confirm=False,
            response_style=response_style,
            persist=persist,
            keep=keep,
            explanation_depth=explanation_depth,
            session=session,
            query=query,
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
    ) -> Dict[str, Any] | AssistantOutput:
        """Plan + 确认执行。

        一次性 ``run(query)`` 保持 B：人敲了 run = 本轮确认，不读 ``allow_*``。
        仅当 session 内 ``agent_auto=True`` 时，``allow_*`` 门控高副作用步。
        live 步永不 auto。
        """

        plan, session = self._assemble_plan(
            query,
            session_id=session_id,
            agent_auto=agent_auto,
        )
        if str((plan.planner_trace or {}).get("intent_job") or "") == "route_to_ask":
            return self.ask(
                query,
                response_style=response_style,
                persist=persist,
                keep=keep,
                explanation_depth=explanation_depth,
                session_id=session_id,
                requested_mode="run",
            )
        confirm = True
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
            query=query,
            requested_mode="run",
        )

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
    ) -> Dict[str, Any] | AssistantOutput:
        """从 ``runs/`` 加载已审阅 ToolPlan 并执行，禁止重新 Hybrid。

        Parameters
        ----------
        plan_id : str
            已落盘计划的 ``plan_id``。
        session_id : str, optional
            若提供则回写 ``task_complete`` / 清除 ``awaiting_abandon``。
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
            query=str(getattr(plan, "user_query", "") or ""),
            requested_mode="run",
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
        query: str = "",
        requested_mode: str = "plan",
    ) -> Dict[str, Any] | AssistantOutput:
        """执行并按策略处理落盘与渲染。"""

        persist_mode = persist or self.run_policy.persist_mode
        persist_run = persist_mode in {"bounded", "audit"}
        payload = self.executor.execute(plan, confirm=confirm, persist_run=False, on_step=on_step)
        plan_md = tool_plan_to_markdown(payload.get("plan") or plan)
        if confirm:
            payload["plan_md"] = ""
        else:
            payload["plan_md"] = plan_md

        if confirm:
            self._merge_env_facts_from_execution(payload)
            if session is not None and str((payload.get("execution") or {}).get("status") or "") == "success":
                if session.active_design:
                    session.current_trial_plan_id = ""
                    updated = []
                    for item in session.trial_queue:
                        row = dict(item)
                        if str(row.get("status") or "") == "active":
                            row["status"] = "done"
                        updated.append(row)
                    session.trial_queue = updated
                else:
                    session.task_complete = True
                    session.awaiting_abandon = False
                    session.pending_clarification = None
                    session.missing = []
                self.session_store.save(session)

        self._attach_session_payload(payload, plan, session)
        if persist_run:
            run_id = str(payload.get("run_id", "")).strip()
            if run_id:
                run_file = self.memory_store.save_run(run_id, payload)
                payload["run_file"] = run_file
                if confirm:
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
        self._attach_human_cards(
            payload,
            query=asked,
            requested_mode=requested_mode,
            session=session,
        )

        if response_style == "raw":
            return payload

        rendered = self.renderer.render(
            payload,
            style="user_friendly",
            context={"persist_mode": persist_mode},
            explanation_depth=explanation_depth,
        )
        if (not confirm) and plan_md:
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

    def _assemble_plan(
        self,
        query: str,
        *,
        session_id: str | None,
        agent_auto: Optional[bool],
    ) -> Tuple[Any, Optional[ConversationState]]:
        """load → gate →（跳过或调用）classify → persist。"""

        self._refresh_planner_env_facts()
        profile = self.memory_store.load_profile()
        sid = str(session_id or "").strip()
        if not sid:
            return self.planner.build_plan(query, mode="plan", profile=profile), None

        state = self.session_store.load(sid)
        if agent_auto is not None:
            state.agent_auto = bool(agent_auto)
        gate = self.session_gate.classify(state, query)

        if (
            gate.kind == "new_intent"
            and gate.needs_abandon
            and not gate.abandon_confirmed
            and state.active_design
        ):
            peek = self.planner.intent_engine.classify(query)
            peek = maybe_mark_builder_open_loop(peek, query)
            parent_job = str((state.active_design or {}).get("job") or "")
            if is_design_loop(self.planner.intent_engine.catalog, peek) and peek.job != parent_job:
                state.turns.append({"query": query, "kind": "open_nested_open"})
                self.session_store.save(state)
                return self._nested_open_clarify_plan(query), state

        if gate.kind == "new_intent" and gate.needs_abandon and not gate.abandon_confirmed:
            state.awaiting_abandon = True
            state.turns.append({"query": query, "kind": "new_intent", "needs_abandon": True})
            self.session_store.save(state)
            return self._abandon_clarify_plan(query), state

        skip_classify = False
        if gate.kind == "open_idle":
            return self._open_idle_plan(query, str(gate.rationale or "")), state
        if gate.kind == "abandon_trial":
            return self._abandon_trial_state(state, query), state
        if gate.kind == "lock_spec":
            return self._lock_spec_plan(state, query), state
        if gate.abandon_confirmed and str(gate.rationale or "") == "abandon_open":
            self._reset_task(state, keep_turns=True)
            state.turns.append({"query": query, "kind": "abandon_open"})
            self.session_store.save(state)
            return self._open_cleared_plan(query), state
        if gate.abandon_confirmed:
            self._reset_task(state, keep_turns=True)
            state.original_query = query
        elif gate.kind == "propose_trial":
            if state.current_trial_plan_id:
                self._queue_trial(state, query)
                self.session_store.save(state)
                return self._design_status_plan(state, query, queued=True), state
            state.open_action = "propose_trial"
            skip_classify = True
        elif gate.kind in {"fill_slot", "change_slot"}:
            # 双保险：完成态不应走到补槽（classify 已拦截；防旧调用方）。
            if state.task_complete:
                self._reset_task(state, keep_turns=True)
                state.original_query = query
                merge_facts(state, extract_patches(query), source="extracted", confirmed=True)
                skip_classify = False
            else:
                merge_facts(state, gate.patches, source="user", confirmed=True)
                if state.active_design:
                    spec = dict((state.active_design or {}).get("spec_draft") or {})
                    state.active_design["spec_draft"] = apply_spec_patches(spec, gate.patches)
                    skip_classify = True
                    state.open_action = ""
                else:
                    skip_classify = bool(state.active_intent)
        elif gate.kind == "confirm":
            for slot in state.slots.values():
                slot.confirmed = True
            skip_classify = bool(state.active_intent)
        elif gate.kind == "clarify":
            skip_classify = bool(state.active_intent)
        else:
            if state.active_intent and state.task_complete:
                self._reset_task(state, keep_turns=True)
            if not state.original_query:
                state.original_query = query
            merge_facts(state, extract_patches(query), source="extracted", confirmed=True)

        plan = self.planner.build_plan(
            query,
            mode="plan",
            session=state,
            skip_classify=skip_classify,
            profile=profile,
        )
        self._sync_session_from_plan(state, plan, query=query, skip_classify=skip_classify)
        state.open_action = ""
        state.turns.append(
            {
                "query": query,
                "kind": gate.kind,
                "plan_id": plan.plan_id,
                "skip_classify": skip_classify,
            }
        )
        self.session_store.save(state)
        return plan, state

    @staticmethod
    def _reset_task(state: ConversationState, *, keep_turns: bool) -> None:
        """放弃当前闭合或开放任务，保留 session_id / turns。"""

        state.active_intent = None
        state.slots = {}
        state.missing = []
        state.pending_clarification = None
        state.current_plan_id = ""
        state.clarify_round = 0
        state.awaiting_abandon = False
        state.original_query = ""
        state.task_complete = False
        state.active_design = None
        state.current_trial_plan_id = ""
        state.trial_queue = []
        state.open_action = ""
        if not keep_turns:
            state.turns = []

    def _queue_trial(self, state: ConversationState, query: str) -> None:
        """当前已有 active 试错时，新建议只进队列。"""

        spec = dict((state.active_design or {}).get("spec_draft") or {})
        state.trial_queue.append(
            {
                "job": str(spec.get("suggested_job") or "research.factor_ic"),
                "reason": query,
                "status": "queued",
            }
        )

    def _design_status_plan(
        self,
        state: ConversationState,
        query: str,
        *,
        queued: bool = False,
        locked: bool = False,
    ) -> Any:
        """用当前设计草稿合成空步 ToolPlan。"""

        design = dict(state.active_design or {})
        spec = dict(design.get("spec_draft") or {})
        assumptions = {
            "planner": "hybrid_intent_h_prime",
            "design_loop": True,
            "spec_draft": spec,
            "kb_hits": list(design.get("kb_hits") or []),
            "open_job": str(design.get("job") or ""),
            "intent_job": str(design.get("job") or ""),
            "intent_source": "session",
            "intent_rationale": "design_status",
            "trial_queued": bool(queued),
        }
        if locked and design.get("pending_kb_write"):
            assumptions["pending_kb_write"] = dict(design.get("pending_kb_write") or {})
        return ToolPlan(
            plan_id=new_plan_id(),
            user_query=query,
            steps=[],
            assumptions=assumptions,
            execution_mode="dry_run",
            mode="plan",
            planner_trace={
                "intent_job": str(design.get("job") or ""),
                "source": "session",
                "rationale": "design_status",
            },
        )

    def _abandon_trial_state(self, state: ConversationState, query: str) -> Any:
        """放弃当前试错，Spec 草稿保留。"""

        state.current_trial_plan_id = ""
        state.trial_queue = [
            item for item in state.trial_queue if str(item.get("status") or "") != "active"
        ]
        state.open_action = ""
        state.turns.append({"query": query, "kind": "abandon_trial"})
        self.session_store.save(state)
        return self._design_status_plan(state, query)

    def _lock_spec_plan(self, state: ConversationState, query: str) -> Any:
        """锁定 Spec 并生成待确认的 KB 写入草案。"""

        design = dict(state.active_design or {})
        spec = dict(design.get("spec_draft") or {})
        draft = pending_kb_write_from_spec(job=str(design.get("job") or ""), spec=spec)
        design["pending_kb_write"] = draft
        state.active_design = design
        state.turns.append({"query": query, "kind": "lock_spec"})
        self.session_store.save(state)
        return self._design_status_plan(state, query, locked=True)

    def _open_cleared_plan(self, query: str) -> Any:
        """开放 Job 已放弃后的空计划。"""

        return ToolPlan(
            plan_id=new_plan_id(),
            user_query=query,
            steps=[],
            assumptions={
                "intent_job": "clarify",
                "open_job_cleared": True,
            },
            execution_mode="dry_run",
            mode="plan",
            planner_trace={"intent_job": "clarify", "source": "session", "rationale": "abandon_open"},
        )

    def _open_idle_plan(self, query: str, reason: str) -> Any:
        """设计环未激活时的试错/锁定/回退。"""

        return ToolPlan(
            plan_id=new_plan_id(),
            user_query=query,
            steps=[],
            assumptions={
                "intent_job": "clarify",
                "open_idle": True,
                "open_idle_reason": str(reason or ""),
            },
            execution_mode="dry_run",
            mode="plan",
            planner_trace={"intent_job": "clarify", "source": "session", "rationale": "open_idle"},
        )

    def _nested_open_clarify_plan(self, query: str) -> Any:
        """禁止 open 套 open。"""

        step = self.planner._make_step(
            step_id="step_1",
            skill_name="qt.ai.system.fallback",
            inputs=self.planner._fallback_step_inputs(
                query=query,
                action="clarify_required",
                reason="open_nested_open_not_allowed",
                hint="An open design loop cannot nest another open job. Finish or abandon the current exploration first.",
                missing_info="abandon_open_or_continue",
                next_step="Abandon the current open job, or keep refining the current FactorSpec.",
            ),
        )
        return ToolPlan(
            plan_id=new_plan_id(),
            user_query=query,
            steps=[step],
            assumptions={
                "clarification": {
                    "restatement": f"You asked: {query}",
                    "pending": [{"name": "open_nest", "hint": "Open jobs cannot nest open jobs."}],
                    "confirm_prompt": "Abandon the current open job or continue the current design loop.",
                }
            },
            execution_mode="dry_run",
            mode="plan",
        )

    def abandon_trial(
        self,
        session_id: str,
        *,
        response_style: str = "user_friendly",
    ) -> Dict[str, Any] | AssistantOutput:
        """放弃当前试错（CLI/HTTP 一等操作）。"""

        state = self.session_store.load(str(session_id or "").strip() or "default")
        plan = self._abandon_trial_state(state, "abandon trial")
        return self._execute_and_format(
            plan=plan,
            confirm=False,
            response_style=response_style,
            persist=None,
            keep=False,
            session=state,
        )

    def abandon_open(
        self,
        session_id: str,
        *,
        response_style: str = "user_friendly",
    ) -> Dict[str, Any] | AssistantOutput:
        """放弃整个开放 Job，保留 session_id。"""

        state = self.session_store.load(str(session_id or "").strip() or "default")
        self._reset_task(state, keep_turns=True)
        state.turns.append({"query": "abandon open", "kind": "abandon_open"})
        self.session_store.save(state)
        plan = self._open_cleared_plan("abandon open")
        return self._execute_and_format(
            plan=plan,
            confirm=False,
            response_style=response_style,
            persist=None,
            keep=False,
            session=state,
        )

    def confirm_kb_write(
        self,
        session_id: str,
        *,
        confirm: bool = True,
        response_style: str = "user_friendly",
    ) -> Dict[str, Any] | AssistantOutput:
        """确认后写入 user_kb/raw 并 compile。"""

        sid = str(session_id or "").strip() or "default"
        state = self.session_store.load(sid)
        design = dict(state.active_design or {})
        draft = dict(design.get("pending_kb_write") or {})
        if not confirm:
            raise ValueError("KB write requires explicit confirmation.")
        if not draft:
            raise ValueError("No pending user-KB write to confirm.")
        path = write_confirmed_note(self.memory_store, draft)
        design["pending_kb_write"] = None
        design["last_kb_write"] = path
        design["kb_hits"] = search_user_kb(self.memory_store, str((design.get("spec_draft") or {}).get("name") or ""))
        state.active_design = design
        self.session_store.save(state)
        plan = self._design_status_plan(state, "confirm kb write", locked=True)
        plan.assumptions["kb_write_path"] = path
        return self._execute_and_format(
            plan=plan,
            confirm=False,
            response_style=response_style,
            persist=None,
            keep=False,
            session=state,
        )

    def _sync_session_from_plan(
        self,
        state: ConversationState,
        plan: Any,
        *,
        query: str,
        skip_classify: bool,
    ) -> None:
        """把本轮 Job / 缺失槽 / 澄清回写会话。"""

        job = str((plan.planner_trace or {}).get("intent_job") or "")
        flags = {}
        if isinstance(state.active_intent, dict):
            flags = dict(state.active_intent.get("flags") or {})
        assumptions = getattr(plan, "assumptions", None) or {}
        if assumptions.get("design_loop"):
            hits = search_user_kb(self.memory_store, query)
            spec = dict(assumptions.get("spec_draft") or {})
            prev = dict(state.active_design or {})
            design_blob = {
                "job": job or str(assumptions.get("open_job") or prev.get("job") or ""),
                "spec_draft": spec,
                "kb_hits": hits,
                "assumptions": list(spec.get("assumptions") or prev.get("assumptions") or []),
            }
            if prev.get("pending_kb_write"):
                design_blob["pending_kb_write"] = dict(prev.get("pending_kb_write") or {})
            if prev.get("last_kb_write"):
                design_blob["last_kb_write"] = prev.get("last_kb_write")
            state.active_design = design_blob
            if hasattr(plan, "assumptions"):
                plan.assumptions = dict(plan.assumptions or {})
                plan.assumptions["kb_hits"] = hits
            flags = dict(flags)
            if assumptions.get("open_job") == "strategy.builder" or (
                job == "strategy.builder" and (assumptions.get("spec_draft") or {})
            ):
                flags["open_loop"] = True
            if job and job not in {"clarify", "route_to_ask", "unsafe", "open"}:
                state.active_intent = {"job": job, "flags": flags}
            if assumptions.get("trial_job") and plan.steps:
                if state.current_trial_plan_id and state.current_trial_plan_id != plan.plan_id:
                    self._queue_trial(state, query)
                else:
                    state.current_trial_plan_id = str(plan.plan_id)
                    state.trial_queue = [
                        item
                        for item in state.trial_queue
                        if str(item.get("status") or "") != "active"
                    ]
                    state.trial_queue.insert(
                        0,
                        {
                            "job": str(assumptions.get("trial_job") or ""),
                            "reason": query,
                            "status": "active",
                            "plan_id": plan.plan_id,
                        },
                    )
        elif job and job not in {"clarify", "route_to_ask", "unsafe", "open"}:
            if not skip_classify or not state.active_intent:
                state.active_intent = {"job": job, "flags": flags}
        if not state.original_query:
            state.original_query = query
        missing = list((plan.assumptions or {}).get("session_missing") or [])
        clarification = (plan.assumptions or {}).get("clarification")
        if missing:
            if state.clarify_round < 3:
                state.clarify_round += 1
            state.missing = missing
            if isinstance(clarification, dict):
                state.pending_clarification = clarification
        else:
            state.missing = []
            if isinstance(clarification, dict):
                state.pending_clarification = clarification
            else:
                state.pending_clarification = None
        state.current_plan_id = str(getattr(plan, "plan_id", "") or "")

    def _abandon_clarify_plan(self, query: str) -> Any:
        """未完成任务遇到新意图时，先确认是否放弃。"""

        step = self.planner._make_step(
            step_id="step_1",
            skill_name="qt.ai.system.fallback",
            inputs=self.planner._fallback_step_inputs(
                query=query,
                action="clarify_required",
                reason="confirm_abandon_current_task",
                hint="Current task is incomplete. Confirm abandon before starting a new job. Session is kept.",
                missing_info="abandon_confirm",
                next_step="Reply abandon to drop the current task, or continue filling slots.",
            ),
        )
        return ToolPlan(
            plan_id=new_plan_id(),
            user_query=query,
            steps=[step],
            assumptions={
                "clarification": {
                    "restatement": f"You asked: {query}",
                    "pending": [{"name": "abandon", "hint": "Confirm abandon of the current incomplete task."}],
                    "confirm_prompt": "Reply abandon to drop the current task. Session id and turns stay.",
                    "options": [
                        {"id": "abandon", "label": "Abandon the current task"},
                        {"id": "continue", "label": "Keep filling slots"},
                    ],
                }
            },
            execution_mode="dry_run",
            mode="plan",
        )

    @staticmethod
    def _slot_summary(state: ConversationState) -> str:
        """已确认槽的短摘要（截断）。"""

        parts = []
        for key, slot in (state.slots or {}).items():
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
    ) -> None:
        """投影人读卡写入 payload 与 session messages[]。"""

        payload["requested_mode"] = str(requested_mode or "")
        payload["effective_kind"] = infer_effective_kind(payload)
        cards = project_human_cards(
            payload,
            requested_mode=requested_mode,
            query=query,
            registry=self.registry,
        )
        payload["human_cards"] = cards
        if session is not None:
            session.append_messages(cards)
            self.session_store.save(session)

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
            blob = {
                "session_id": session.session_id,
                "clarify_round": session.clarify_round,
                "current_plan_id": session.current_plan_id,
                "missing": list(session.missing),
                "agent_auto": session.agent_auto,
            }
            if session.active_design:
                blob["active_design"] = dict(session.active_design)
                blob["current_trial_plan_id"] = session.current_trial_plan_id
                blob["trial_queue"] = list(session.trial_queue)
            payload["session"] = blob
            payload["kb_hits"] = list((session.active_design or {}).get("kb_hits") or [])

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
