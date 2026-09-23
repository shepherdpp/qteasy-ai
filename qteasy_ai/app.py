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
from .session import ConversationState, SessionStore, clear_live_running, register_live_running
from .session_gate import (
    SessionGate,
    extract_patches,
    extract_plan_id,
    is_discuss_only,
    is_execute_plan_utterance,
    is_skip_clarify,
    merge_facts,
)
from .side_effects import plan_has_high_side_effect
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
            last = session.messages[-1] if session.messages else {}
            already = (
                str(last.get("kind") or "") == "user_text"
                and str(last.get("text") or "").strip() == str(query or "").strip()
            )
            if not already:
                session.append_user_text(query)
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
        patches: Optional[Dict[str, Any]] = None,
        skip: bool = False,
    ) -> Dict[str, Any] | AssistantOutput:
        """Plan 模式：生成 dry_run 计划。

        与 `ask()` 的区别在于：
        - ask：KnowledgeBase 问答，无 skill / 无 Executor；
        - plan / preview：生成可审阅 ToolPlan steps，不执行。

        非空 ``patches`` 为同一 Job 改槽回执：``query`` 可空，不跑跟进句分类。
        ``skip=True`` 为控件跳过澄清，不写 ``user_text``。
        """

        structured = _normalize_patches(patches)
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
        if not structured:
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
        )
        if hatched is not None:
            return hatched
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
        query: str = "",
        requested_mode: str = "plan",
        hatch: str = "",
        hatch_plan_id: str = "",
    ) -> Dict[str, Any] | AssistantOutput:
        """执行并按策略处理落盘与渲染。"""

        persist_mode = persist or self.run_policy.persist_mode
        persist_run = persist_mode in {"bounded", "audit"}
        execute_requested = bool(confirm)
        clarify_plan = self._plan_is_clarify(plan)
        if clarify_plan:
            confirm = False
        live_sid = ""
        if confirm and session is not None and session.task is not None:
            session.task.status = "running"
            session.task.high_side_effect = plan_has_high_side_effect(plan)
            self.session_store.save(session)
            live_sid = str(session.session_id or "")
            register_live_running(live_sid)
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
        try:
            payload = self.executor.execute(
                plan,
                confirm=confirm,
                persist_run=False,
                on_step=on_step,
                run_id=reuse_run_id,
            )
        except Exception:
            if live_sid:
                clear_live_running(live_sid)
            raise
        try:
            return self._persist_after_execute(
                payload,
                plan=plan,
                confirm=confirm,
                execute_requested=execute_requested,
                clarify_plan=clarify_plan,
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
            )
        finally:
            if live_sid:
                clear_live_running(live_sid)

    def _persist_after_execute(
        self,
        payload: Dict[str, Any],
        *,
        plan: Any,
        confirm: bool,
        execute_requested: bool,
        clarify_plan: bool,
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
    ) -> Dict[str, Any] | AssistantOutput:
        """execute 成功后落盘 / 标 done；调用方在 finally 里 clear_live。"""

        write_plan_md = (not confirm) and (not execute_requested) and (not clarify_plan)
        if write_plan_md:
            plan_md = tool_plan_to_markdown(
                payload.get("plan") or plan,
                provider=getattr(self.planner, "provider", None),
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
        elif confirm:
            self._merge_env_facts_from_execution(payload)
            if session is not None and session.task is not None:
                status = str((payload.get("execution") or {}).get("status") or "")
                session.task.mark_done()
                session.task.run_id = str(payload.get("run_id") or "")
                if status == "success":
                    session.task.set_pending(None)
                    session.task.set_missing([])
                self.session_store.save(session)
        elif session is not None and session.task is not None:
            pending = session.task.pending_clarification
            if clarify_plan or pending or session.task.missing:
                session.task.status = "clarifying"
            else:
                session.task.mark_ready()
                session.task.high_side_effect = plan_has_high_side_effect(plan)
            self.session_store.save(session)

        self._attach_session_payload(payload, plan, session)
        write_plan_md = (not confirm) and (not execute_requested) and (not clarify_plan)
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
            payload["revision"] = int(assumptions.get("revision") or 0)
        if assumptions.get("block_running"):
            payload["block_running"] = True
        self._attach_human_cards(
            payload,
            query=asked,
            requested_mode=requested_mode,
            session=session,
            include_user_text=include_user,
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
    ) -> Optional[Dict[str, Any] | AssistantOutput]:
        """两条模式缺口与 skip 澄清：不走 Hybrid。"""

        del agent_auto
        if is_discuss_only(query):
            return self.ask(
                query,
                response_style=response_style,
                persist=persist,
                keep=keep,
                explanation_depth=explanation_depth,
                session_id=session_id,
                requested_mode=requested_mode,
            )
        sid = str(session_id or "").strip()
        session = self.session_store.load(sid) if sid else None
        if is_skip_clarify(query) and session is not None and session.task is not None and (
            session.task.pending_clarification or session.task.missing
        ):
            session.append_user_text(query)
            self.session_store.save(session)
            return self._skip_clarification_result(
                session,
                query=query,
                requested_mode=requested_mode,
                response_style=response_style,
                include_user_text=False,
            )
        run_hatch = is_execute_plan_utterance(query) or (
            requested_mode == "run" and bool(extract_plan_id(query))
        )
        if not run_hatch:
            return None
        if session is not None:
            session.append_user_text(query)
            self.session_store.save(session)
        plan_id = extract_plan_id(query) or (
            str(session.task.plan_id or "") if session is not None and session.task is not None else ""
        )
        if not plan_id:
            return self._closed_error_result(
                query=query,
                requested_mode=requested_mode,
                response_style=response_style,
                session=session,
                code="PLAN_ID_MISSING",
                message="No current plan to run. Create a plan first, or name plan_id in the sentence.",
                next_action="Run plan() first, or include plan_xxxxxxxx in the sentence.",
            )
        hatch = "plan_mode_execute" if requested_mode == "plan" else "run_plan_id"
        try:
            return self.run_plan(
                plan_id,
                response_style=response_style,
                persist=persist,
                keep=keep,
                explanation_depth=explanation_depth,
                session_id=sid or None,
                on_step=on_step,
                requested_mode=requested_mode,
                hatch=hatch,
            )
        except ValueError as exc:
            return self._closed_error_result(
                query=query,
                requested_mode=requested_mode,
                response_style=response_style,
                session=session,
                code="PLAN_ID_NOT_FOUND",
                message=str(exc),
                next_action="Create or select a plan in this session, then Confirm.",
            )

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
            code="CLARIFICATION_SKIPPED",
            message="Clarification skipped. This request ended.",
            next_action="Start a new question, or provide the missing field next time.",
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
    def _plan_is_clarify(plan: Any) -> bool:
        """单步 fallback clarify_required，本轮不得 execute。"""

        steps = list(getattr(plan, "steps", None) or [])
        if len(steps) != 1:
            assumptions = getattr(plan, "assumptions", None) or {}
            return isinstance(assumptions.get("clarification"), dict) and bool(assumptions.get("clarification"))
        step = steps[0]
        if str(getattr(step, "skill_name", "") or "") != "qt.ai.system.fallback":
            return False
        return str((getattr(step, "inputs", None) or {}).get("fallback_action") or "") == "clarify_required"

    def _assemble_plan(
        self,
        query: str,
        *,
        session_id: str | None,
        agent_auto: Optional[bool],
        patches: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Any, Optional[ConversationState]]:
        """Composer 先记 user_text，再按 Task 转移表路由。"""

        self._refresh_planner_env_facts()
        profile = self.memory_store.load_profile()
        sid = str(session_id or "").strip()
        if not sid:
            return self.planner.build_plan(query, mode="plan", profile=profile), None

        state = self.session_store.load(sid)
        if agent_auto is not None:
            state.agent_auto = bool(agent_auto)
        structured = _normalize_patches(patches)
        inbound = "control" if structured else "composer"
        asked = str(query or "").strip()
        skip_classify = False
        topic_skipped = False
        keep_plan_id = ""
        slot_revision: Optional[Dict[str, Any]] = None

        if inbound == "composer" and asked:
            state.append_user_text(asked)
            self.session_store.save(state)

        if inbound == "control":
            merge_facts(state, structured, source="user", confirmed=True)
            answer = next((str(value) for value in structured.values() if value not in (None, "")), "")
            if state.task is not None and (state.task.pending_clarification or state.task.missing):
                state.close_open_card(answer, status="answered")
            skip_classify = bool(state.task and state.task.job)
            keep_plan_id = str(state.task.plan_id or "") if state.task is not None else ""
            slot_revision = dict(structured)
            if state.task is not None:
                state.task.revision = int(state.task.revision or 0) + 1
                if state.task.status in {"done", "cancelled", ""}:
                    state.task.mark_ready()
        else:
            gate = self.session_gate.classify(state, asked)
            if gate.kind == "block_running":
                self.session_store.save(state)
                return self._block_running_plan(asked), state
            if gate.kind == "fill_slot":
                merge_facts(state, gate.patches, source="user", confirmed=True)
                state.close_open_card(asked, status="answered")
                skip_classify = bool(state.task and state.task.job)
            elif gate.kind == "new_intent":
                peek = self.planner.intent_engine.classify(asked)
                if str(getattr(peek, "job", "") or "") == "route_to_ask":
                    dummy = ToolPlan(
                        plan_id="",
                        user_query=asked,
                        steps=[],
                        assumptions={"intent_job": "route_to_ask"},
                        execution_mode="dry_run",
                        mode="plan",
                        planner_trace={"intent_job": "route_to_ask", "source": "session", "rationale": "ask_not_task"},
                    )
                    self.session_store.save(state)
                    return dummy, state
                topic_skipped = bool(state.task and state.task.status in {"clarifying", "ready", "running"})
                if topic_skipped:
                    state.cancel_task()
                state.start_task(query=asked)
                merge_facts(state, extract_patches(asked), source="extracted", confirmed=True)
                skip_classify = False
            else:
                if state.task is None:
                    state.start_task(query=asked)
                merge_facts(state, extract_patches(asked), source="extracted", confirmed=True)

        plan = self.planner.build_plan(
            asked or query,
            mode="plan",
            session=state,
            skip_classify=skip_classify,
            profile=profile,
        )
        if keep_plan_id and inbound == "control":
            plan.plan_id = keep_plan_id
        if topic_skipped:
            plan.assumptions = dict(plan.assumptions or {})
            plan.assumptions["topic_skipped"] = True
        if slot_revision:
            plan.assumptions = dict(plan.assumptions or {})
            plan.assumptions["slot_revision"] = dict(slot_revision)
            plan.assumptions["revision"] = int(getattr(state.task, "revision", 0) or 0) if state.task else 0
        self._sync_session_from_plan(state, plan, query=asked or query, skip_classify=skip_classify)
        self.session_store.save(state)
        return plan, state

    def _block_running_plan(self, query: str) -> Any:
        """高副作用 running 时拒绝换题。"""

        return ToolPlan(
            plan_id=new_plan_id(),
            user_query=query,
            steps=[],
            assumptions={
                "intent_job": "clarify",
                "block_running": True,
            },
            execution_mode="dry_run",
            mode="plan",
            planner_trace={"intent_job": "clarify", "source": "session", "rationale": "block_running"},
        )

    def confirm_kb_write(
        self,
        session_id: str,
        *,
        confirm: bool = True,
        response_style: str = "user_friendly",
    ) -> Dict[str, Any] | AssistantOutput:
        """确认后写入 user_kb/raw 并 compile。不再绑 active_design。"""

        del session_id
        if not confirm:
            raise ValueError("KB write requires explicit confirmation.")
        raise ValueError("No pending user-KB write to confirm.")

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
            return
        if missing:
            if state.task.clarify_round < 3:
                state.task.clarify_round += 1
            state.task.set_missing(missing)
            if isinstance(clarification, dict):
                state.task.set_pending(clarification)
        else:
            state.task.set_missing([])
            if isinstance(clarification, dict):
                state.task.set_pending(clarification)
            else:
                state.task.set_pending(None)
        state.task.plan_id = str(getattr(plan, "plan_id", "") or "")

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
