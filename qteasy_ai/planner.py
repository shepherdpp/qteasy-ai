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

"""自然语言到 ToolPlan 的 Hybrid 最小实现。

A0 目标是打通 Planner 三段式链路：

1. `build_candidate_plan()`：候选计划生成（当前以规则为主，Provider 可选）；
2. `validate_plan()`：规则校验、字段归一与风险门控；
3. `finalize_plan()`：生成可执行计划并附加 `planner_trace`。
"""

from __future__ import annotations

import datetime
import re
import unicodedata
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from .contracts import SkillSideEffects, ToolPlan, ToolStep, new_plan_id
from .provider import BaseLLMProvider
from .registry import SkillRegistry


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
        steps = self._infer_steps(query=query, q_lower=q_lower)
        assumptions = {
            "planner": "hybrid_candidate_stage_b0",
            "provider_enabled": self.provider is not None,
            "env_facts_used": bool(self.env_facts),
        }
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
        }
        return final_plan

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
        return ToolStep(
            step_id=step_id,
            skill_name=skill_name,
            inputs=inputs,
            side_effects=meta.side_effects,
            estimated_cost="low",
            depends_on=list(depends_on or []),
            run_if="",
            on_fail="stop",
            retry_limit=0,
        )

    def _infer_steps(self, *, query: str, q_lower: str) -> List[ToolStep]:
        """根据 query 推断一步或多步技能调用（B0 规则路径）。"""

        fallback_inputs = self._infer_fallback_inputs(query=query, q_lower=q_lower)
        if fallback_inputs is not None:
            return [
                self._make_step(
                    step_id="step_1",
                    skill_name="qt.ai.system.fallback",
                    inputs=fallback_inputs,
                )
            ]

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
            steps = [self._make_step(step_id="step_1", skill_name=skill_name, inputs=inputs)]
            return steps

        if self._is_factor_ic_query(q_lower):
            primary = self._make_step(
                step_id="step_1",
                skill_name="qt.ai.research.factor_ic_summary",
                inputs=self._extract_market_inputs(query),
            )
            return self._maybe_prepend_table_gate([primary], data_intent=True)

        # summary / 摘要 / 波动率 优先于 kline 导出（修实弹误路由）
        if self._is_summary_query(q_lower):
            primary = self._make_step(
                step_id="step_1",
                skill_name="qt.ai.data.summary_kline",
                inputs=self._extract_market_inputs(query),
            )
            return self._maybe_prepend_table_gate([primary], data_intent=True)

        if any(word in q_lower for word in ["kline", "candle", "k线", "绘图", "导出", "png", "export"]):
            primary = self._make_step(
                step_id="step_1",
                skill_name="qt.ai.visual.export_kline",
                inputs=self._extract_market_inputs(query),
            )
            return self._maybe_prepend_table_gate([primary], data_intent=True)

        primary = self._make_step(
            step_id="step_1",
            skill_name="qt.ai.data.summary_kline",
            inputs=self._extract_market_inputs(query),
        )
        return self._maybe_prepend_table_gate([primary], data_intent=True)

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

        high_risk_intents = [contains_live, contains_download, contains_backtest, contains_optimize, contains_codegen]
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

        if contains_download or contains_backtest or contains_optimize or contains_codegen:
            return {
                "query": query,
                "fallback_action": "not_supported_yet",
                "reason": "feature_not_implemented_in_stage_a",
                "hint": "This capability is planned for later stages. Use available read-only skills for now.",
                "missing_info": "supported_stage_a_skill",
                "next_step": "Try read-only tasks such as strategy list/get, kline summary, and kline export.",
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
        symbol_match = re.search(r"(\d{6}\.(?:SH|SZ|BJ))", query, flags=re.IGNORECASE)
        if symbol_match:
            result["shares"] = symbol_match.group(1).upper()
        else:
            short_symbol = re.search(r"\b(\d{6})\b", query)
            if short_symbol:
                # 阶段A的简化假设：纯6位代码优先按 SH 处理。
                result["shares"] = short_symbol.group(1) + ".SH"
        date_match = re.findall(r"(20\d{2}[-/]?\d{2}[-/]?\d{2})", query)
        if date_match:
            result["start"] = date_match[0].replace("-", "").replace("/", "")
            if len(date_match) > 1:
                result["end"] = date_match[1].replace("-", "").replace("/", "")
        freq_match = re.search(r"\b(1min|5min|15min|30min|60min|d|w|m)\b", query, flags=re.IGNORECASE)
        if freq_match:
            result["freq"] = freq_match.group(1)
        return result
