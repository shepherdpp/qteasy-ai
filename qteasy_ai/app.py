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
from typing import Any, Dict, Optional

from .ask_engine import AskEngine, AskResponse
from .config import DEFAULT_PROVIDER_TIMEOUT, ConfigCenter
from .executor import PlanExecutor
from .knowledge_base import KnowledgeBase
from .memory_store import MemoryStore, merge_env_facts
from .output import AssistantOutput
from .plan_markdown import tool_plan_to_markdown
from .planner import Planner
from .provider import BaseLLMProvider
from .renderer import OutputRenderer
from .registry import SkillRegistry
from .run_policy import RunStorePolicy
from .skills import (
    build_backtest_run_skill,
    build_check_tushare_skill,
    build_data_refill_skill,
    build_data_summary_skill,
    build_factor_ic_summary_skill,
    build_insight_backtest_skill,
    build_live_trade_plan_only_skill,
    build_optimize_run_skill,
    build_operator_from_spec_skill,
    build_overview_tables_skill,
    build_research_screen_skill,
    build_strategy_codegen_hybrid_skill,
    build_strategy_meta_get_skill,
    build_strategy_meta_list_skill,
    build_strategy_sanity_check_skill,
    build_strategy_spec_from_nl_skill,
    build_system_fallback_skill,
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
        build_visual_export_skill,
        build_system_fallback_skill,
        build_check_tushare_skill,
        build_overview_tables_skill,
        build_factor_ic_summary_skill,
        build_data_refill_skill,
        build_backtest_run_skill,
        build_optimize_run_skill,
        build_research_screen_skill,
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
        self._last_run_id = ""

    def _refresh_planner_env_facts(self) -> None:
        """从 MemoryStore 刷新 Planner 的 env_facts。"""

        self.planner.env_facts = self.memory_store.load_env_facts()

    def _build_plan(self, query: str, *, mode: str) -> Any:
        """加载最新 env_facts 后生成 ToolPlan。"""

        self._refresh_planner_env_facts()
        return self.planner.build_plan(query, mode=mode)

    def ask(
        self,
        query: str,
        *,
        response_style: str = "user_friendly",
        persist: str | None = None,
        keep: bool = False,
        explanation_depth: str = "standard",
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
        result: AskResponse = self.ask_engine.ask(query, explanation_depth=explanation_depth)
        if response_style == "raw":
            return result.to_dict()
        return AssistantOutput(
            narrative=result.narrative,
            python_code=result.python_code,
            result_preview=result.result_preview,
            raw=result.to_dict(),
        )

    def preview(
        self,
        query: str,
        *,
        response_style: str = "user_friendly",
        persist: str | None = None,
        keep: bool = False,
        explanation_depth: str = "standard",
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
        )

    def plan(
        self,
        query: str,
        *,
        response_style: str = "user_friendly",
        persist: str | None = None,
        keep: bool = False,
        explanation_depth: str = "standard",
    ) -> Dict[str, Any] | AssistantOutput:
        """Plan 模式：生成 dry_run 计划。

        与 `ask()` 的区别在于：
        - ask：KnowledgeBase 问答，无 skill / 无 Executor；
        - plan / preview：生成可审阅 ToolPlan steps，不执行。
        """

        plan = self._build_plan(query, mode="plan")
        return self._execute_and_format(
            plan=plan,
            confirm=False,
            response_style=response_style,
            persist=persist,
            keep=keep,
            explanation_depth=explanation_depth,
        )

    def run(
        self,
        query: str,
        *,
        response_style: str = "user_friendly",
        persist: str | None = None,
        keep: bool = False,
        explanation_depth: str = "standard",
    ) -> Dict[str, Any] | AssistantOutput:
        """Plan + 确认执行。

        CLI ``run`` 视为人在回路的一次确认：生成计划后 ``confirm=True`` 执行。
        ``profile.agent.allow_*`` 本阶段不读取、不门控。
        """

        plan = self._build_plan(query, mode="plan")
        plan.execution_mode = "execute"
        return self._execute_and_format(
            plan=plan,
            confirm=True,
            response_style=response_style,
            persist=persist,
            keep=keep,
            explanation_depth=explanation_depth,
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
    ) -> Dict[str, Any] | AssistantOutput:
        """执行并按策略处理落盘与渲染。"""

        persist_mode = persist or self.run_policy.persist_mode
        persist_run = persist_mode in {"bounded", "audit"}
        payload = self.executor.execute(plan, confirm=confirm, persist_run=False)
        plan_md = tool_plan_to_markdown(payload.get("plan") or plan)
        payload["plan_md"] = plan_md

        if confirm:
            self._merge_env_facts_from_execution(payload)

        if persist_run:
            run_id = str(payload.get("run_id", "")).strip()
            if run_id:
                run_file = self.memory_store.save_run(run_id, payload)
                payload["run_file"] = run_file
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

        if response_style == "raw":
            return payload

        rendered = self.renderer.render(
            payload,
            style="user_friendly",
            context={"persist_mode": persist_mode},
            explanation_depth=explanation_depth,
        )
        if plan_md:
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
