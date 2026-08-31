# coding=utf-8
# ======================================
# File: planner.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-04-15
# Desc:
# qteasy AI 外壳规划层，负责将用户
# 请求转换为结构化 ToolPlan。
# ======================================

"""自然语言到 ToolPlan 的 Hybrid 实现。

三段式链路：

1. `build_candidate_plan()`：规则推断，或（有 Provider 时）LLM 候选 JSON；
2. `validate_plan()`：规则校验、字段归一；env_facts / 日期门禁在候选之后共用；
3. `finalize_plan()`：生成可执行计划并附加 `planner_trace`（含 candidate_source）。
"""

from __future__ import annotations

import datetime
import json
import re
import unicodedata
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from .contracts import SkillSideEffects, ToolPlan, ToolStep, new_plan_id
from .provider import BaseLLMProvider
from .registry import SkillRegistry
from .runtime import SkillRuntime


class RuleValidator:
    """Planner 规则校验器。"""

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def validate(self, candidate_plan: ToolPlan) -> Tuple[ToolPlan, Dict[str, Any]]:
        """校验并返回修订后的计划。"""

        corrected = deepcopy(candidate_plan)
        available_skills = {item.name for item in self.registry.list_skills()}
        trace: Dict[str, Any] = {
            "validator": "rule_validator_v2",
            "corrections": [],
            "downgrade_reason": "",
        }
        corrected_steps: List[ToolStep] = []
        for step in corrected.steps:
            if step.skill_name not in available_skills:
                trace["downgrade_reason"] = f"Skill not found: {step.skill_name}"
                continue
            meta = self.registry.get_metadata(step.skill_name)
            if step.side_effects != meta.side_effects:
                step.side_effects = meta.side_effects
                trace["corrections"].append(
                    {
                        "step_id": step.step_id,
                        "field": "side_effects",
                        "reason": "sync_from_registry_metadata",
                    }
                )
            if step.on_fail not in {"stop", "continue", "retry"}:
                trace["corrections"].append(
                    {
                        "step_id": step.step_id,
                        "field": "on_fail",
                        "from": step.on_fail,
                        "to": "stop",
                    }
                )
                step.on_fail = "stop"
            if step.on_fail != "retry" and step.retry_limit > 0:
                trace["corrections"].append(
                    {
                        "step_id": step.step_id,
                        "field": "retry_limit",
                        "from": step.retry_limit,
                        "to": 0,
                    }
                )
                step.retry_limit = 0
            corrected_steps.append(step)
        if not corrected_steps and corrected.mode == "plan":
            trace["downgrade_reason"] = trace["downgrade_reason"] or "No valid step after validation."
        corrected.steps = corrected_steps
        return corrected, trace


class Planner:
    """规则 + env_facts 门禁的计划生成器（B0）。

    Parameters
    ----------
    registry : SkillRegistry
        技能注册中心，用于读取技能元数据（尤其是 side_effects）。
    provider : BaseLLMProvider, optional
        模型提供方抽象。B0 仅记录是否启用，不参与候选计划生成。
    env_facts : dict, optional
        本机环境事实（凭证/表状态）；用于门禁前置检查。
    """

    # 门禁关注的核心行情表：仅当 env_facts 已记录且 exists=False 时前置 overview。
    _CORE_MARKET_TABLES = ("stock_daily", "index_daily")

    def __init__(
        self,
        registry: SkillRegistry,
        provider: Optional[BaseLLMProvider] = None,
        env_facts: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.registry = registry
        self.provider = provider
        self.env_facts: Dict[str, Any] = dict(env_facts or {})
        self.validator = RuleValidator(registry)
        self._strategy_alias_map: Optional[Dict[str, str]] = None
        self._skill_runtime = SkillRuntime()

    def build_plan(self, user_query: str, *, mode: str = "plan") -> ToolPlan:
        """Hybrid 三段式入口，生成最终可执行计划。

        Returns
        -------
        ToolPlan
            已附带 `planner_trace` 的可执行计划对象。
        """

        candidate = self.build_candidate_plan(user_query, mode=mode)
        validated, trace = self.validate_plan(candidate)
        return self.finalize_plan(candidate, validated, trace)

    def build_candidate_plan(self, user_query: str, *, mode: str = "plan") -> ToolPlan:
        """生成候选计划。

        Parameters
        ----------
        user_query : str
            用户自然语言请求。
        mode : {'plan', 'ask'}
            Ask 模式下不执行技能，仅返回空步骤计划；
            Plan 模式下按规则推断技能与输入参数。

        Returns
        -------
        ToolPlan
            候选计划。
        """

        if mode == "ask":
            steps = []
            assumptions: Dict[str, Any] = {"mode": "ask", "no_skill_execution": True}
            return ToolPlan(
                plan_id=new_plan_id(),
                user_query=user_query,
                steps=steps,
                assumptions=assumptions,
                execution_mode="dry_run",
                mode="ask",
            )

        query = user_query.strip()
        q_lower = query.lower()
        candidate_source = "rule"
        downgrade_reason = ""
        steps: Optional[List[ToolStep]] = None
        if self.provider is not None:
            llm_steps, llm_reason = self._try_llm_candidate(query)
            if llm_steps is not None:
                candidate_source = "llm"
                steps = llm_steps
            else:
                downgrade_reason = llm_reason
                steps = self._infer_steps(query=query, q_lower=q_lower)
        else:
            steps = self._infer_steps(query=query, q_lower=q_lower)
        steps, gate_extras = self._apply_post_candidate_gates(
            steps, query=query, candidate_source=candidate_source
        )
        assumptions = {
            "planner": "hybrid_candidate_stage_b",
            "provider_enabled": self.provider is not None,
            "env_facts_used": bool(self.env_facts),
            "candidate_source": candidate_source,
            "downgrade_reason": downgrade_reason,
        }
        assumptions.update(gate_extras)
        for step in steps:
            if step.skill_name == "qt.ai.data.refill_basic_equity_and_index" and not step.inputs.get("symbols"):
                assumptions["refill_universe"] = "all symbols for those tables (high cost)"
            if step.skill_name == "qt.ai.optimize.run_builtin":
                assumptions["opti_method"] = step.inputs.get("opti_method", "montecarlo")
                assumptions["opti_sample_count"] = step.inputs.get("opti_sample_count", 32)
            if step.skill_name == "qt.ai.research.screen_stocks":
                assumptions["screen_end"] = "latest trading day in local datasource"
        return ToolPlan(
            plan_id=new_plan_id(),
            user_query=user_query,
            steps=steps,
            assumptions=assumptions,
            execution_mode="dry_run",
            mode="plan",
        )

    def validate_plan(self, candidate_plan: ToolPlan) -> Tuple[ToolPlan, Dict[str, Any]]:
        """校验候选计划并返回修订结果。"""

        return self.validator.validate(candidate_plan)

    @staticmethod
    def finalize_plan(candidate_plan: ToolPlan, validated_plan: ToolPlan, trace: Dict[str, Any]) -> ToolPlan:
        """合并候选与校验结果，形成最终计划。"""

        final_plan = deepcopy(validated_plan)
        final_plan.planner_trace = {
            "candidate_plan_id": candidate_plan.plan_id,
            "validator_trace": trace,
            "final_step_count": len(final_plan.steps),
            "candidate_source": candidate_plan.assumptions.get("candidate_source", "rule"),
            "downgrade_reason": candidate_plan.assumptions.get("downgrade_reason", ""),
        }
        recipe_slots_from = candidate_plan.assumptions.get("recipe_slots_from")
        if recipe_slots_from:
            final_plan.planner_trace["recipe_slots_from"] = recipe_slots_from
        llm_skill_sequence = candidate_plan.assumptions.get("llm_skill_sequence")
        if llm_skill_sequence:
            final_plan.planner_trace["llm_skill_sequence"] = list(llm_skill_sequence)
        return final_plan

    _DATA_INTENT_SKILLS = {
        "qt.ai.data.summary_kline",
        "qt.ai.research.factor_ic_summary",
        "qt.ai.visual.export_kline",
        "qt.ai.data.refill_basic_equity_and_index",
    }

    _LLM_PLAN_SYSTEM = (
        "You generate a qteasy-ai ToolPlan candidate. "
        "Reply with JSON only: {\"steps\": [{\"skill_name\": \"qt.ai...\", \"inputs\": {}}]}. "
        "Use only skill names listed in the prompt. Do not invent skills."
    )

    def _try_llm_candidate(self, query: str) -> Tuple[Optional[List[ToolStep]], str]:
        """调用 Provider 生成候选 steps；失败返回 (None, reason)。

        候选 prompt 对每个已注册 skill 注入 ``- name: summary`` 一行用途，
        降低错品类（例如回测句点成 refill）。
        """

        if self.provider is None:
            return None, "provider_missing"
        catalog_items = self.registry.list_skills()
        catalog_names = [item.name for item in catalog_items]
        catalog_lines = [
            f"- {item.name}: {item.summary}"
            for item in catalog_items
        ]
        prompt = (
            "Available skills:\n"
            + "\n".join(catalog_lines)
            + f"\n\nUser query:\n{query}\n\n"
            "Return JSON with a steps array. Each step needs skill_name and inputs."
        )
        try:
            text = self.provider.chat(prompt, system_prompt=self._LLM_PLAN_SYSTEM)
        except Exception as exc:
            return None, f"llm_chat_failed: {exc}"
        payload = self._parse_llm_plan_json(text)
        if not isinstance(payload, dict):
            return None, "llm_json_parse_failed"
        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            return None, "llm_empty_steps"
        available = set(catalog_names)
        steps: List[ToolStep] = []
        for idx, raw in enumerate(raw_steps, start=1):
            if not isinstance(raw, dict):
                return None, "llm_invalid_step"
            name = str(raw.get("skill_name", "")).strip()
            if name not in available:
                return None, f"Skill not found: {name}"
            inputs = raw.get("inputs") if isinstance(raw.get("inputs"), dict) else {}
            depends = raw.get("depends_on") if isinstance(raw.get("depends_on"), list) else []
            step = self._make_step(
                step_id=f"step_{idx}",
                skill_name=name,
                inputs=dict(inputs),
                depends_on=[str(item) for item in depends],
            )
            if raw.get("run_if"):
                step.run_if = str(raw.get("run_if"))
            steps.append(step)
        return steps, ""

    @staticmethod
    def _parse_llm_plan_json(text: str) -> Optional[Dict[str, Any]]:
        """从模型文本中解析计划 JSON。"""

        blob = (text or "").strip()
        if blob.startswith("```"):
            lines = blob.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            blob = "\n".join(lines).strip()
        try:
            payload = json.loads(blob)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass
        start = blob.find("{")
        end = blob.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(blob[start : end + 1])
        except json.JSONDecodeError:
            return None
        return payload if isinstance(payload, dict) else None

    def _apply_post_candidate_gates(
        self,
        steps: List[ToolStep],
        *,
        query: str,
        candidate_source: str = "rule",
    ) -> Tuple[List[ToolStep], Dict[str, Any]]:
        """对 LLM 与规则候选共用菜谱覆写、日期、必填槽与 env_facts 门禁。"""

        extras: Dict[str, Any] = {}
        gated = steps
        if candidate_source == "llm" and steps:
            extras["llm_skill_sequence"] = self._skill_name_sequence(steps)
        if candidate_source == "llm":
            gated, applied = self._overwrite_slots_if_recipe_match(gated, query=query)
            if applied:
                extras["recipe_slots_from"] = "rule"
        gated = self._enforce_refill_date_range(gated, query=query)
        if candidate_source == "llm":
            gated = self._enforce_required_slots(gated, query=query)
        gated = self._maybe_prepend_tushare_gate(gated)
        data_intent = any(step.skill_name in self._DATA_INTENT_SKILLS for step in gated)
        return self._maybe_prepend_table_gate(gated, data_intent=data_intent), extras

    @staticmethod
    def _skill_name_sequence(steps: List[ToolStep]) -> List[str]:
        """返回步骤 skill_name 有序列。"""

        return [step.skill_name for step in steps]

    @staticmethod
    def _is_contiguous_subsequence(needle: List[str], haystack: List[str]) -> bool:
        """判断 needle 是否为 haystack 的连续子序列（含相等）。"""

        n_len = len(needle)
        h_len = len(haystack)
        if n_len == 0 or n_len > h_len:
            return False
        for start in range(h_len - n_len + 1):
            if haystack[start : start + n_len] == needle:
                return True
        return False

    @staticmethod
    def _is_fallback_only_recipe(steps: List[ToolStep]) -> bool:
        """规则菜谱是否仅为 system.fallback。"""

        return bool(steps) and all(step.skill_name == "qt.ai.system.fallback" for step in steps)

    def _overwrite_slots_if_recipe_match(
        self, steps: List[ToolStep], *, query: str
    ) -> Tuple[List[ToolStep], bool]:
        """LLM 与规则菜谱互为连续子序列时，整表换成规则步骤。

        规则菜谱仅为 fallback 时默认不换表；本句命中 StrategyBuilder
        关键词则仍用规则澄清，避免单步 codegen 漏网。
        """

        if not steps:
            return steps, False
        q_lower = query.lower()
        rule_steps = self._infer_steps(query=query, q_lower=q_lower)
        if not rule_steps:
            return steps, False
        if self._is_fallback_only_recipe(rule_steps):
            if self._has_strategy_builder_keywords(query, q_lower):
                return deepcopy(rule_steps), True
            return steps, False
        llm_names = self._skill_name_sequence(steps)
        rule_names = self._skill_name_sequence(rule_steps)
        if self._is_contiguous_subsequence(rule_names, llm_names) or self._is_contiguous_subsequence(
            llm_names, rule_names
        ):
            return deepcopy(rule_steps), True
        return steps, False

    def _missing_required_fields(self, step: ToolStep) -> List[str]:
        """返回步骤缺少的 inputs_schema required 字段。"""

        try:
            meta = self.registry.get_metadata(step.skill_name)
        except Exception:
            return []
        return list(self._skill_runtime.precheck(meta, step.inputs))

    def _enforce_required_slots(self, steps: List[ToolStep], *, query: str) -> List[ToolStep]:
        """LLM 候选缺必填槽时用同 skill 规则填槽，否则整单 clarify。

        与 SkillRuntime.precheck 同源；禁止把空槽计划交给 Executor。
        """

        if not steps:
            return steps
        missing_by_step = [self._missing_required_fields(step) for step in steps]
        if not any(missing_by_step):
            return steps
        q_lower = query.lower()
        rule_steps = self._infer_steps(query=query, q_lower=q_lower)
        rule_by_skill: Dict[str, ToolStep] = {}
        for rule_step in rule_steps:
            rule_by_skill.setdefault(rule_step.skill_name, rule_step)
        merged = deepcopy(steps)
        still_missing: List[str] = []
        for step, missing in zip(merged, missing_by_step):
            if not missing:
                continue
            rule_peer = rule_by_skill.get(step.skill_name)
            if rule_peer is None:
                still_missing.extend(missing)
                continue
            for field_name in missing:
                if field_name in rule_peer.inputs:
                    step.inputs[field_name] = rule_peer.inputs[field_name]
            leftover = self._missing_required_fields(step)
            still_missing.extend(leftover)
        if not still_missing:
            return merged
        unique_missing = sorted(set(still_missing))
        missing_info = "|".join(unique_missing)
        return [
            self._make_step(
                step_id="step_1",
                skill_name="qt.ai.system.fallback",
                inputs=self._fallback_step_inputs(
                    query=query,
                    action="clarify_required",
                    reason="llm_missing_required_slots",
                    hint="The LLM candidate omitted required skill inputs. Provide the missing fields instead of executing an empty-slot plan.",
                    missing_info=missing_info,
                    next_step=f"Provide: {', '.join(unique_missing)}.",
                ),
            )
        ]

    def _enforce_refill_date_range(self, steps: List[ToolStep], *, query: str) -> List[ToolStep]:
        """refill 缺起止日期时整单澄清，禁止无界下载。"""

        for step in steps:
            if step.skill_name != "qt.ai.data.refill_basic_equity_and_index":
                continue
            start = str(step.inputs.get("start") or "").strip()
            end = str(step.inputs.get("end") or "").strip()
            if start and end:
                continue
            return [
                self._make_step(
                    step_id="step_1",
                    skill_name="qt.ai.system.fallback",
                    inputs=self._fallback_step_inputs(
                        query=query,
                        action="clarify_required",
                        reason="refill_date_range_required",
                        hint="Download/refill requires an explicit start and end date. Unbounded full-history download is not allowed.",
                        missing_info="date_range",
                        next_step="Provide a date range such as 20180101 to 20231231 or 2018-2023.",
                    ),
                )
            ]
        return steps

    def _maybe_prepend_tushare_gate(self, steps: List[ToolStep]) -> List[ToolStep]:
        """refill 且 env_facts 标明 token 缺失时前置 check_tushare。"""

        if not any(step.skill_name == "qt.ai.data.refill_basic_equity_and_index" for step in steps):
            return steps
        if any(step.skill_name == "qt.ai.env.check_tushare" for step in steps):
            return steps
        tushare = self.env_facts.get("tushare") if isinstance(self.env_facts.get("tushare"), dict) else {}
        if tushare.get("token_present") is not False:
            return steps
        gate = self._make_step(step_id="step_gate", skill_name="qt.ai.env.check_tushare", inputs={})
        rest: List[ToolStep] = []
        for idx, step in enumerate(steps, start=1):
            step.step_id = f"step_{idx}"
            rest.append(step)
        return [gate] + rest

    def _make_step(
        self,
        *,
        step_id: str,
        skill_name: str,
        inputs: Dict[str, Any],
        depends_on: Optional[List[str]] = None,
    ) -> ToolStep:
        """构造带 registry 元数据的 ToolStep。"""

        meta = self.registry.get_metadata(skill_name)
        side = meta.side_effects
        if side.local_state_change or side.filesystem_write:
            cost = "high"
        elif side.heavy_compute:
            cost = "high"
        else:
            cost = "low"
        return ToolStep(
            step_id=step_id,
            skill_name=skill_name,
            inputs=inputs,
            side_effects=meta.side_effects,
            estimated_cost=cost,
            depends_on=list(depends_on or []),
            run_if="",
            on_fail="stop",
            retry_limit=0,
        )

    @staticmethod
    def _has_strategy_builder_keywords(query: str, q_lower: str) -> bool:
        """是否含 StrategyBuilder 关键词（写策略 / 双均线金叉）。"""

        write_hints = (
            "生成策略",
            "strategybuilder",
            "codegen",
            "帮我写",
            "写一个",
            "写一份",
            "创建策略",
            "write a strategy",
            "generate a strategy",
        )
        sma_hints = ("金叉", "死叉", "双均线", "均线交叉", "sma cross", "dual ma")
        return any(item in query or item in q_lower for item in write_hints) or any(
            item in query or item in q_lower for item in sma_hints
        )

    def _is_strategy_builder_query(self, query: str, q_lower: str) -> bool:
        """判断是否走 StrategyBuilder DAG（排除实盘与内置策略回测）。"""

        if any(item in q_lower for item in ["实盘", "live trade"]) or bool(
            re.search(r"\blive\b", q_lower)
        ):
            return False
        if not self._has_strategy_builder_keywords(query, q_lower):
            return False
        write_hints = ("生成策略", "strategybuilder", "codegen", "帮我写", "写一个", "写一份", "创建策略")
        if self._extract_strategy_id(query) and not any(
            item in query or item in q_lower for item in write_hints
        ):
            return False
        return True

    def _infer_strategy_builder_steps(self, *, query: str, q_lower: str) -> Optional[List[ToolStep]]:
        """NL→Spec→codegen→sanity→Operator→可选回测/insight。"""

        if not self._is_strategy_builder_query(query, q_lower):
            return None
        from .skills.strategy_spec import parse_strategy_spec_from_nl

        spec, clarify = parse_strategy_spec_from_nl(query)
        if spec is None:
            return [
                self._make_step(
                    step_id="step_1",
                    skill_name="qt.ai.system.fallback",
                    inputs=self._fallback_step_inputs(
                        query=query,
                        action="clarify_required",
                        reason=str(clarify.get("reason") or "strategy_spec_incomplete"),
                        hint=str(clarify.get("hint") or "Please provide a complete dual-MA cross description."),
                        missing_info=str(clarify.get("missing_info") or "fast|slow"),
                        next_step="Provide fast/slow windows (e.g. 20/60) and a single signal type.",
                    ),
                )
            ]
        spec_inputs: Dict[str, Any] = {"query": query}
        steps = [
            self._make_step(
                step_id="step_1",
                skill_name="qt.ai.strategy.spec_from_nl",
                inputs=spec_inputs,
            ),
            self._make_step(
                step_id="step_2",
                skill_name="qt.ai.strategy.codegen_hybrid",
                inputs={},
                depends_on=["step_1"],
            ),
            self._make_step(
                step_id="step_3",
                skill_name="qt.ai.strategy.sanity_check",
                inputs={},
                depends_on=["step_2"],
            ),
            self._make_step(
                step_id="step_4",
                skill_name="qt.ai.operator.build_from_spec",
                inputs={},
                depends_on=["step_3"],
            ),
        ]
        if self._is_backtest_query(q_lower):
            market = self._extract_market_inputs(query)
            bt_inputs: Dict[str, Any] = {
                "strategy_id": spec.class_name or "GeneratedSmaCross",
                "freq": spec.run_freq or market.get("freq") or "d",
            }
            pool = spec.asset_pool or market.get("shares") or ""
            if pool:
                bt_inputs["asset_pool"] = pool
            start = spec.invest_start or market.get("start") or ""
            end = spec.invest_end or market.get("end") or ""
            if start:
                bt_inputs["invest_start"] = start
            if end:
                bt_inputs["invest_end"] = end
            steps.append(
                self._make_step(
                    step_id="step_5",
                    skill_name="qt.ai.backtest.run_builtin",
                    inputs=bt_inputs,
                    depends_on=["step_4"],
                )
            )
            if self._is_insight_commentary(q_lower):
                insight = self._make_step(
                    step_id="step_6",
                    skill_name="qt.ai.insight.summarize_backtest",
                    inputs={},
                    depends_on=["step_5"],
                )
                insight.run_if = "all_dependencies_ok"
                steps.append(insight)
        return steps

    def _infer_live_plan_only_steps(self, *, query: str, q_lower: str) -> Optional[List[ToolStep]]:
        """实盘请求只路由到 plan-only skill，永不当作可执行下单。"""

        if not (
            any(item in q_lower for item in ["实盘", "live trade"])
            or bool(re.search(r"\blive\b", q_lower))
        ):
            return None
        return [
            self._make_step(
                step_id="step_1",
                skill_name="qt.ai.pipeline.live_trade_plan_only",
                inputs={"query": query},
            )
        ]

    def _infer_steps(self, *, query: str, q_lower: str) -> List[ToolStep]:
        """根据 query 推断一步或多步技能调用（阶段 B/D 规则路径）。"""

        builder_steps = self._infer_strategy_builder_steps(query=query, q_lower=q_lower)
        if builder_steps is not None:
            return builder_steps

        live_steps = self._infer_live_plan_only_steps(query=query, q_lower=q_lower)
        if live_steps is not None:
            return live_steps

        fallback_inputs = self._infer_fallback_inputs(query=query, q_lower=q_lower)
        if fallback_inputs is not None:
            return [
                self._make_step(
                    step_id="step_1",
                    skill_name="qt.ai.system.fallback",
                    inputs=fallback_inputs,
                )
            ]

        screen_steps = self._infer_screen_steps(query=query, q_lower=q_lower)
        if screen_steps is not None:
            return screen_steps

        refill_steps = self._infer_refill_steps(query=query, q_lower=q_lower)
        if refill_steps is not None:
            return refill_steps

        optimize_steps = self._infer_optimize_steps(query=query, q_lower=q_lower)
        if optimize_steps is not None:
            return optimize_steps

        backtest_steps = self._infer_backtest_steps(query=query, q_lower=q_lower)
        if backtest_steps is not None:
            return backtest_steps

        insight_steps = self._infer_insight_only_steps(query=query, q_lower=q_lower)
        if insight_steps is not None:
            return insight_steps

        if self._is_env_query(q_lower):
            return [
                self._make_step(step_id="step_1", skill_name="qt.ai.env.check_tushare", inputs={}),
                self._make_step(step_id="step_2", skill_name="qt.ai.env.overview_tables", inputs={}),
            ]

        if any(word in q_lower for word in ["strategy", "built-in", "built in", "策略"]):
            is_parameter_query = self._is_strategy_parameter_query(q_lower)
            match_id = self._extract_strategy_id(query)
            if is_parameter_query and not match_id:
                return [
                    self._make_step(
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
                skill_name = "qt.ai.strategy_meta.get"
                inputs: Dict[str, Any] = {"strategy_id": match_id}
            else:
                skill_name = "qt.ai.strategy_meta.list"
                inputs = {}
            return [self._make_step(step_id="step_1", skill_name=skill_name, inputs=inputs)]

        if self._is_factor_ic_query(q_lower):
            primary = self._make_step(
                step_id="step_1",
                skill_name="qt.ai.research.factor_ic_summary",
                inputs=self._extract_market_inputs(query),
            )
            return [primary]

        if self._is_summary_query(q_lower):
            primary = self._make_step(
                step_id="step_1",
                skill_name="qt.ai.data.summary_kline",
                inputs=self._extract_market_inputs(query),
            )
            return [primary]

        if any(word in q_lower for word in ["kline", "candle", "k线", "绘图", "导出", "png", "export"]):
            primary = self._make_step(
                step_id="step_1",
                skill_name="qt.ai.visual.export_kline",
                inputs=self._extract_market_inputs(query),
            )
            return [primary]

        return [
            self._make_step(
                step_id="step_1",
                skill_name="qt.ai.system.fallback",
                inputs={
                    "query": query,
                    "fallback_action": "not_supported_yet",
                    "reason": "no_matching_skill",
                    "hint": "No matching qteasy-ai skill for this query. Arbitrary stats/formulas are not supported.",
                    "missing_info": "supported_skill",
                    "next_step": "Try refill, builtin backtest/optimize, stock screen, kline summary, or strategy meta.",
                },
            )
        ]

    def _maybe_prepend_table_gate(self, steps: List[ToolStep], *, data_intent: bool) -> List[ToolStep]:
        """当 env_facts 已记录核心表缺失时，前置 overview_tables。"""

        if not data_intent or not self.env_facts:
            return steps
        tables = self.env_facts.get("tables")
        if not isinstance(tables, dict) or not tables:
            return steps
        missing = False
        for name in self._CORE_MARKET_TABLES:
            entry = tables.get(name)
            if isinstance(entry, dict) and entry.get("exists") is False:
                missing = True
                break
        if not missing:
            return steps
        if any(step.skill_name == "qt.ai.env.overview_tables" for step in steps):
            return steps
        gate = self._make_step(step_id="step_gate", skill_name="qt.ai.env.overview_tables", inputs={})
        renumbered: List[ToolStep] = [gate]
        for idx, step in enumerate(steps, start=1):
            step.step_id = f"step_{idx}"
            renumbered.append(step)
        return renumbered

    @staticmethod
    def _is_env_query(q_lower: str) -> bool:
        """判断是否为环境就绪检查意图。"""

        keywords = [
            "tushare",
            "token",
            "配好",
            "缺表",
            "数据表",
            "本地表",
            "env",
            "environment",
            "check table",
            "missing table",
            "local data table",
            "overview table",
        ]
        return any(item in q_lower for item in keywords)

    @staticmethod
    def _is_summary_query(q_lower: str) -> bool:
        """判断是否为 K 线/行情摘要意图（优先于 export）。"""

        keywords = [
            "summary",
            "摘要",
            "波动率",
            "交易天数",
            "volatility",
            "trading day",
            "trading days",
            "n_rows",
        ]
        return any(item in q_lower for item in keywords)

    @staticmethod
    def _is_factor_ic_query(q_lower: str) -> bool:
        """判断是否为因子 IC 摘要意图。"""

        keywords = ["factor ic", "因子 ic", "因子ic", "ic summary", "ic 摘要", "information coefficient"]
        return any(item in q_lower for item in keywords)

    def _fallback_step_inputs(
        self,
        *,
        query: str,
        action: str,
        reason: str,
        hint: str,
        missing_info: str,
        next_step: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """构造 system.fallback 输入。"""

        payload: Dict[str, Any] = {
            "query": query,
            "fallback_action": action,
            "reason": reason,
            "hint": hint,
            "missing_info": missing_info,
            "next_step": next_step,
        }
        if details:
            payload["details"] = details
        return payload

    @staticmethod
    def _is_download_query(q_lower: str) -> bool:
        """判断是否为下载/refill 意图。"""

        return any(item in q_lower for item in ["下载", "download", "refill"])

    @staticmethod
    def _is_backtest_query(q_lower: str) -> bool:
        """判断是否为回测意图。"""

        return any(item in q_lower for item in ["回测", "backtest"])

    @staticmethod
    def _is_optimize_query(q_lower: str) -> bool:
        """判断是否为优化意图。"""

        return any(item in q_lower for item in ["优化", "optimize"])

    @staticmethod
    def _is_screen_query(q_lower: str) -> bool:
        """判断是否为筛股意图（避免落到 summary_kline）。"""

        keywords = ["筛股", "筛选股票", "搜索股票", "搜股票", "screen stock", "stock screen", "screening"]
        if any(item in q_lower for item in keywords):
            return True
        if ("搜索" in q_lower and "股票" in q_lower) or ("筛选" in q_lower and "股票" in q_lower):
            return True
        has_move = ("跌幅" in q_lower) or ("涨幅" in q_lower) or ("drawdown" in q_lower)
        has_pool = ("股票" in q_lower) or ("industry" in q_lower) or ("行业" in q_lower)
        return has_move and has_pool

    @staticmethod
    def _is_insight_commentary(q_lower: str) -> bool:
        """判断回测问法是否同时要年化/回撤解读。"""

        return any(
            item in q_lower
            for item in ["年化", "最大回撤", "解读", "归因", "summarize", "annual", "mdd"]
        )

    @staticmethod
    def _is_insight_only_query(q_lower: str) -> bool:
        """判断是否为只读总结已有回测，而非新开回测。"""

        summarize = any(item in q_lower for item in ["总结回测", "解读回测", "summarize backtest", "上次回测", "归因"])
        launching = any(item in q_lower for item in ["跑", "run ", "用 "])
        return summarize and not launching

    def _infer_screen_steps(self, *, query: str, q_lower: str) -> Optional[List[ToolStep]]:
        """筛股路由：规则抽参；缺阈值/窗口或额外条件则澄清。"""

        if not self._is_screen_query(q_lower):
            return None
        extra = []
        for token in ("市盈率", "市值", "成交量", "换手", "申万", " pe", "pe/", "pb"):
            if token in q_lower:
                extra.append(token.strip())
        if extra:
            return [
                self._make_step(
                    step_id="step_1",
                    skill_name="qt.ai.system.fallback",
                    inputs=self._fallback_step_inputs(
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
        params, missing = self._extract_screen_params(query=query, q_lower=q_lower)
        if missing:
            return [
                self._make_step(
                    step_id="step_1",
                    skill_name="qt.ai.system.fallback",
                    inputs=self._fallback_step_inputs(
                        query=query,
                        action="clarify_required",
                        reason="screen_missing_fields",
                        hint="Stock screen needs a lookback window and a return threshold.",
                        missing_info="|".join(missing),
                        next_step="Example: 过去半年跌幅>20%，行业属于银行.",
                    ),
                )
            ]
        return [
            self._make_step(
                step_id="step_1",
                skill_name="qt.ai.research.screen_stocks",
                inputs=params,
            )
        ]

    def _extract_screen_params(self, *, query: str, q_lower: str) -> Tuple[Dict[str, Any], List[str]]:
        """从筛股问法抽取 lookback / metric / threshold / industry。"""

        params: Dict[str, Any] = {}
        missing: List[str] = []
        lookback_days: Optional[int] = None
        if any(item in q_lower for item in ["半年", "6个月", "六个月", "six months"]):
            lookback_days = 126
        elif any(item in q_lower for item in ["3个月", "三个月", "一季度", "季度", "3 months"]):
            lookback_days = 63
        elif any(item in q_lower for item in ["1年", "一年", "过去一年", "one year"]):
            lookback_days = 252
        else:
            day_match = re.search(r"(\d+)\s*(?:日|天|days?)", q_lower)
            if day_match:
                lookback_days = int(day_match.group(1))
        if lookback_days is None:
            missing.append("lookback")
        else:
            params["lookback_days"] = lookback_days

        drop_match = re.search(r"(跌幅|drawdown|drop)\s*[>≥>=]{1,2}\s*(\d+(?:\.\d+)?)\s*%?", query, flags=re.IGNORECASE)
        gain_match = re.search(r"(涨幅|gain|rally)\s*[>≥>=]{1,2}\s*(\d+(?:\.\d+)?)\s*%?", query, flags=re.IGNORECASE)
        if drop_match:
            params["metric"] = "drawdown"
            params["threshold"] = float(drop_match.group(2)) / 100.0
        elif gain_match:
            params["metric"] = "gain"
            params["threshold"] = float(gain_match.group(2)) / 100.0
        else:
            missing.append("return_threshold")

        industry = ""
        industry_match = re.search(r"行业(?:属于|为|是|:|：)\s*([^\s，,的]+)", query)
        if industry_match:
            industry = industry_match.group(1).strip()
        else:
            en_match = re.search(r"industry\s*(?:is|=|:|：)\s*([A-Za-z0-9_\u4e00-\u9fff]+)", query, flags=re.IGNORECASE)
            if en_match:
                industry = en_match.group(1).strip()
        if industry:
            params["industry"] = industry
        else:
            missing.append("industry")
        return params, missing

    def _infer_refill_steps(self, *, query: str, q_lower: str) -> Optional[List[ToolStep]]:
        """下载路由：缺日期澄清；无 token 时前置 check_tushare。"""

        if not self._is_download_query(q_lower):
            return None
        market = self._extract_market_inputs(query)
        start = market.get("start")
        end = market.get("end")
        if not start or not end:
            return [
                self._make_step(
                    step_id="step_1",
                    skill_name="qt.ai.system.fallback",
                    inputs=self._fallback_step_inputs(
                        query=query,
                        action="clarify_required",
                        reason="refill_date_range_required",
                        hint="Download/refill requires an explicit start and end date. Unbounded full-history download is not allowed.",
                        missing_info="date_range",
                        next_step="Provide a date range such as 20180101 to 20231231 or 2018-2023.",
                    ),
                )
            ]
        inputs: Dict[str, Any] = {"start": start, "end": end, "tables": ["stock_daily", "index_daily"]}
        if market.get("shares"):
            inputs["symbols"] = market["shares"]
        steps = [
            self._make_step(
                step_id="step_1",
                skill_name="qt.ai.data.refill_basic_equity_and_index",
                inputs=inputs,
            )
        ]
        return steps

    def _infer_optimize_steps(self, *, query: str, q_lower: str) -> Optional[List[ToolStep]]:
        """优化路由：缺 strategy_id 则澄清。"""

        if not self._is_optimize_query(q_lower):
            return None
        strategy_id = self._extract_strategy_id(query)
        if not strategy_id:
            return [
                self._make_step(
                    step_id="step_1",
                    skill_name="qt.ai.system.fallback",
                    inputs=self._fallback_step_inputs(
                        query=query,
                        action="clarify_required",
                        reason="optimize_strategy_id_missing",
                        hint="Cannot determine built-in strategy id for optimize.",
                        missing_info="strategy_id",
                        next_step="Provide a built-in strategy id, e.g. DMA or macd.",
                    ),
                )
            ]
        market = self._extract_market_inputs(query)
        inputs: Dict[str, Any] = {
            "strategy_id": strategy_id,
            "opti_method": "montecarlo",
            "opti_sample_count": 32,
        }
        if market.get("shares"):
            inputs["asset_pool"] = market["shares"]
        if market.get("start"):
            inputs["invest_start"] = market["start"]
        if market.get("end"):
            inputs["invest_end"] = market["end"]
        return [
            self._make_step(
                step_id="step_1",
                skill_name="qt.ai.optimize.run_builtin",
                inputs=inputs,
            )
        ]

    def _infer_backtest_steps(self, *, query: str, q_lower: str) -> Optional[List[ToolStep]]:
        """回测路由；若同时要年化/回撤解读则追加 insight DAG。"""

        if not self._is_backtest_query(q_lower):
            return None
        if self._is_insight_only_query(q_lower):
            return None
        strategy_id = self._extract_strategy_id(query)
        if not strategy_id:
            return [
                self._make_step(
                    step_id="step_1",
                    skill_name="qt.ai.system.fallback",
                    inputs=self._fallback_step_inputs(
                        query=query,
                        action="clarify_required",
                        reason="backtest_strategy_id_missing",
                        hint="Cannot determine built-in strategy id for backtest.",
                        missing_info="strategy_id",
                        next_step="Provide a built-in strategy id, e.g. macd.",
                    ),
                )
            ]
        market = self._extract_market_inputs(query)
        inputs: Dict[str, Any] = {"strategy_id": strategy_id, "freq": market.get("freq") or "d"}
        if market.get("shares"):
            inputs["asset_pool"] = market["shares"]
        if market.get("start"):
            inputs["invest_start"] = market["start"]
        if market.get("end"):
            inputs["invest_end"] = market["end"]
        backtest = self._make_step(
            step_id="step_1",
            skill_name="qt.ai.backtest.run_builtin",
            inputs=inputs,
        )
        if not self._is_insight_commentary(q_lower):
            return [backtest]
        insight = self._make_step(
            step_id="step_2",
            skill_name="qt.ai.insight.summarize_backtest",
            inputs={},
            depends_on=["step_1"],
        )
        insight.run_if = "all_dependencies_ok"
        return [backtest, insight]

    def _infer_insight_only_steps(self, *, query: str, q_lower: str) -> Optional[List[ToolStep]]:
        """只读总结已有回测。"""

        if not self._is_insight_only_query(q_lower) and not (
            ("insight" in q_lower or "归因" in q_lower) and not self._is_backtest_query(q_lower)
        ):
            if not (("总结" in q_lower or "summarize" in q_lower) and self._is_backtest_query(q_lower)):
                return None
        return [
            self._make_step(
                step_id="step_1",
                skill_name="qt.ai.insight.summarize_backtest",
                inputs={},
            )
        ]

    def _infer_single_step(self, *, query: str, q_lower: str) -> ToolStep:
        """兼容旧调用：返回推断结果的第一步。"""

        steps = self._infer_steps(query=query, q_lower=q_lower)
        return steps[0]

    @staticmethod
    def _is_strategy_parameter_query(q_lower: str) -> bool:
        """判断是否为“策略参数查询”意图。"""

        keywords = [
            "参数",
            "可调参数",
            "参数列表",
            "调参",
            "parameter",
            "parameters",
            "tunable",
            "hyperparameter",
        ]
        return any(item in q_lower for item in keywords)

    @staticmethod
    def _infer_fallback_inputs(*, query: str, q_lower: str) -> Optional[Dict[str, str]]:
        """识别需要回退到统一响应的请求。"""

        contains_live = any(item in q_lower for item in ["实盘", "live trade", "live"])
        contains_download = any(item in q_lower for item in ["下载", "download", "refill"])
        contains_backtest = any(item in q_lower for item in ["回测", "backtest"])
        contains_optimize = any(item in q_lower for item in ["优化", "optimize"])
        contains_codegen = any(item in q_lower for item in ["生成策略", "strategybuilder", "codegen"])
        contains_dangerous = any(item in q_lower for item in ["rm -rf", "bash", "shell command", "cmd /c", "powershell"])
        contains_bypass_confirm = any(item in q_lower for item in ["跳过确认", "skip confirmation", "write files directly"])
        builder_query = Planner._has_strategy_builder_keywords(query, q_lower)

        if contains_dangerous:
            return {
                "query": query,
                "fallback_action": "clarify_required",
                "reason": "unsafe_command_request",
                "hint": "Shell command execution is not supported by qteasy AI skills.",
                "missing_info": "none",
                "next_step": "Please describe the qteasy task directly instead of raw shell commands.",
            }

        if contains_bypass_confirm:
            return {
                "query": query,
                "fallback_action": "not_supported_yet",
                "reason": "bypass_confirmation_not_allowed",
                "hint": "High side-effect operations require explicit confirmation.",
                "missing_info": "confirmation",
                "next_step": "Please use plan mode first, then execute with explicit confirmation.",
            }

        high_risk_intents = [contains_live, contains_download, contains_backtest, contains_optimize]
        if not builder_query:
            high_risk_intents.append(contains_codegen)
        if sum(1 for flag in high_risk_intents if flag) >= 2:
            return {
                "query": query,
                "fallback_action": "clarify_required",
                "reason": "multi_intent_not_supported_in_single_step_planner",
                "hint": "Please split request into smaller steps: download/backtest/optimize/live.",
                "missing_info": "single_intent_query",
                "next_step": "Split your request into one intent per query.",
            }

        if contains_live:
            return {
                "query": query,
                "fallback_action": "plan_only",
                "reason": "live_trade_requires_strong_confirmation",
                "hint": "Live trade is not auto-executed. Please use plan mode and confirm manually.",
                "missing_info": "explicit_execution_confirmation",
                "next_step": "Ask for a live-trade plan first, then confirm each high-risk step manually.",
            }

        if builder_query:
            return None

        if contains_codegen:
            return {
                "query": query,
                "fallback_action": "not_supported_yet",
                "reason": "strategy_builder_not_supported",
                "hint": "StrategyBuilder / strategy codegen is not available in this stage.",
                "missing_info": "supported_stage_b_skill",
                "next_step": "Use built-in strategy ids with backtest/optimize, or read-only strategy_meta.",
            }

        date_match = re.findall(r"(20\d{2}[-/]?\d{2}[-/]?\d{2})", query)
        if len(date_match) > 1:
            start = date_match[0].replace("-", "").replace("/", "")
            end = date_match[1].replace("-", "").replace("/", "")
            try:
                start_dt = datetime.datetime.strptime(start, "%Y%m%d")
                end_dt = datetime.datetime.strptime(end, "%Y%m%d")
                if start_dt > end_dt:
                    return {
                        "query": query,
                        "fallback_action": "clarify_required",
                        "reason": "invalid_date_range",
                        "hint": "Start date must be earlier than or equal to end date.",
                        "missing_info": "valid_date_range",
                        "next_step": "Provide a valid date range with start <= end.",
                    }
            except ValueError:
                return {
                    "query": query,
                    "fallback_action": "clarify_required",
                    "reason": "invalid_date_format",
                    "hint": "Date format should be YYYYMMDD or YYYY-MM-DD.",
                    "missing_info": "valid_date_format",
                    "next_step": "Use YYYYMMDD or YYYY-MM-DD format.",
                }

        if "freq=" in q_lower and not re.search(r"\b(1min|5min|15min|30min|60min|d|w|m)\b", query, flags=re.IGNORECASE):
            return {
                "query": query,
                "fallback_action": "clarify_required",
                "reason": "invalid_frequency_expression",
                "hint": "Supported freq: 1min/5min/15min/30min/60min/d/w/m.",
                "missing_info": "valid_frequency",
                "next_step": "Choose one freq in: 1min/5min/15min/30min/60min/d/w/m.",
            }
        return None

    def _extract_strategy_id(self, query: str) -> Optional[str]:
        """提取策略 ID。

        Notes
        -----
        该函数是“宽松匹配”，会忽略常见功能词，尝试抓取第一个
        可能代表策略名的 token。若无法可靠判断则返回 None。
        """

        ignored = {
            "list",
            "built",
            "builtin",
            "strategies",
            "strategy",
            "show",
            "get",
            "all",
            "in",
            "param",
            "parameter",
            "parameters",
            "optimize",
            "optimization",
            "backtest",
            "download",
            "refill",
            "run",
            "using",
            "with",
            "from",
            "please",
            "data",
            "local",
            "daily",
            "share",
            "shares",
            "stock",
            "stocks",
            "index",
            "screen",
            "search",
            "summary",
            "summarize",
        }
        normalized = unicodedata.normalize("NFKC", query)
        normalized_lower = normalized.lower()
        alias_map = self._get_strategy_alias_map()
        for alias, canonical in alias_map.items():
            if re.search(rf"(?<![a-z0-9_]){re.escape(alias)}(?![a-z0-9_])", normalized_lower):
                return canonical
        candidates = re.findall(r"\b([A-Za-z][A-Za-z0-9_]{1,})\b", normalized)
        for item in candidates:
            lower_item = item.lower()
            if lower_item not in ignored and len(lower_item) >= 3:
                return alias_map.get(lower_item, item)
        return None

    def _get_strategy_alias_map(self) -> Dict[str, str]:
        """构建内置策略别名映射。"""

        if self._strategy_alias_map is not None:
            return self._strategy_alias_map
        alias_map: Dict[str, str] = {}
        try:
            import qteasy as qt

            built_ins = qt.built_in_list()
            for strategy_id in built_ins:
                sid = str(strategy_id).strip()
                if not sid:
                    continue
                alias_map[sid.lower()] = sid
                alias_map[sid.upper().lower()] = sid
        except Exception:
            # 无法读取内置策略列表时，保持空映射并回退到宽松 token 抽取。
            alias_map = {}
        self._strategy_alias_map = alias_map
        return alias_map

    @staticmethod
    def _extract_market_inputs(query: str) -> Dict[str, Any]:
        """提取标的与时间参数。

        当前支持抽取：
        - 标的：`000001.SH/000001.SZ/000001.BJ`，或 6 位数字（默认补 `.SH`）；
        - 日期：`YYYYMMDD` / `YYYY-MM-DD` / `YYYY/MM/DD`；
        - 频率：`1min/5min/15min/30min/60min/d/w/m`。

        返回值仅包含命中的字段，未命中的字段由技能内部使用默认值。
        """

        result: Dict[str, Any] = {}
        year_range = re.search(
            r"(20\d{2})\s*年?\s*(?:[~\-–—]|至|到|to)\s*(20\d{2})\s*年?",
            query,
            flags=re.IGNORECASE,
        )
        if year_range:
            y1 = int(year_range.group(1))
            y2 = int(year_range.group(2))
            if y1 <= y2:
                result["start"] = f"{y1:04d}0101"
                result["end"] = f"{y2:04d}1231"
        alias_map = {
            "沪深300": "000300.SH",
            "csi300": "000300.SH",
            "csi 300": "000300.SH",
        }
        q_lower = query.lower()
        for alias, code in alias_map.items():
            if alias.lower() in q_lower or alias in query:
                result["shares"] = code
                break
        symbol_match = re.search(r"(\d{6}\.(?:SH|SZ|BJ))", query, flags=re.IGNORECASE)
        if symbol_match:
            result["shares"] = symbol_match.group(1).upper()
        elif "shares" not in result:
            short_symbol = re.search(r"\b(\d{6})\b", query)
            if short_symbol:
                # 阶段A的简化假设：纯6位代码优先按 SH 处理。
                result["shares"] = short_symbol.group(1) + ".SH"
        if "start" not in result:
            date_match = re.findall(r"(20\d{2}[-/]?\d{2}[-/]?\d{2})", query)
            if date_match:
                result["start"] = date_match[0].replace("-", "").replace("/", "")
                if len(date_match) > 1:
                    result["end"] = date_match[1].replace("-", "").replace("/", "")
        freq_match = re.search(r"\b(1min|5min|15min|30min|60min|d|w|m)\b", query, flags=re.IGNORECASE)
        if freq_match:
            result["freq"] = freq_match.group(1)
        return result
