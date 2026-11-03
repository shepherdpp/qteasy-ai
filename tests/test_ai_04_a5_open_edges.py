# coding=utf-8
# ======================================
# File: test_ai_04_a5_open_edges.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-03
# Desc:
# 0.4 A5：只读原子进入系统 open 合法边。
# max_steps 仍为 3；回测、refill、写码、实盘、优化仍拒绝。
# ======================================

import json
import unittest

from qteasy_ai.app import build_default_registry
from qteasy_ai.intents import load_default_catalog
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.side_effects import step_needs_confirm

_QUERY = "xyzzy unmatched formula 12345"

_KEPT = [
    "qt.ai.strategy_meta.list",
    "qt.ai.strategy_meta.get",
    "qt.ai.data.kline",
    "qt.ai.hp.describe",
    "qt.ai.hp.volatility",
    "qt.ai.data.read",
    "qt.ai.env.check_tushare",
    "qt.ai.env.overview_tables",
    "qt.ai.research.factor_ic_summary",
    "qt.ai.research.universe_filter",
    "qt.ai.research.project_universe",
    "qt.ai.insight.summarize_backtest",
]

_NEW = [
    "qt.ai.data.history",
    "qt.ai.data.reference",
    "qt.ai.data.static",
    "qt.ai.data.statement",
    "qt.ai.dtype.find",
    "qt.ai.datasource.table_info",
    "qt.ai.datasource.table_overview",
    "qt.ai.hp.slice",
    "qt.ai.hp.drop",
    "qt.ai.hp.rename",
    "qt.ai.hp.fill",
    "qt.ai.hp.dropna",
    "qt.ai.hp.resample",
    "qt.ai.hp.assign",
    "qt.ai.hp.align",
    "qt.ai.hp.join",
    "qt.ai.hp.returns",
    "qt.ai.hp.shift",
    "qt.ai.hp.diff",
    "qt.ai.hp.pct_change",
    "qt.ai.hp.rank",
    "qt.ai.hp.zscore",
    "qt.ai.hp.rolling",
    "qt.ai.hp.agg",
    "qt.ai.hp.corr",
    "qt.ai.hp.compare",
    "qt.ai.hp.combine_mask",
    "qt.ai.hp.where",
    "qt.ai.hp.expr",
    "qt.ai.hp.indicator",
    "qt.ai.hp.candle_pattern",
    "qt.ai.hp.research_preset",
    "qt.ai.hp.portfolio",
    "qt.ai.hp.cum_return",
    "qt.ai.hp.normalize",
    "qt.ai.hp.alpha_beta",
    "qt.ai.hp.performance",
    "qt.ai.hp.plot",
]

_FORBIDDEN = [
    "qt.ai.data.refill_basic_equity_and_index",
    "qt.ai.backtest.run_builtin",
    "qt.ai.optimize.run_builtin",
    "qt.ai.strategy.codegen_hybrid",
    "qt.ai.pipeline.live_trade_plan_only",
    "qt.ai.visual.export_kline",
]

_OFF_EDGE = [
    "qt.ai.strategy.spec_from_nl",
    "qt.ai.research.screen_stocks",
]


def _open_plan(registry, steps):
    """用两段罐头回复走出系统 open。"""

    fake = FakeLLMProvider(
        replies=[
            json.dumps({"job": "open"}),
            json.dumps({"steps": steps}),
        ]
    )
    plan = Planner(registry, provider=fake, env_facts={}).build_plan(_QUERY, mode="plan")
    return plan, fake


class TestAi04A5OpenEdges(unittest.TestCase):
    """系统 open 收进 A1–A4 只读原子，三步上限和确认门不动。"""

    def setUp(self) -> None:
        self.catalog = load_default_catalog()
        self.registry = build_default_registry()

    def test_readonly_atoms_enter_legal_edges(self) -> None:
        """新只读原子在白名单且已注册；禁止名单仍是那六条；步数上限为 3。"""

        print("\n[TestAi04A5OpenEdges] 只读原子进入合法边")
        allowed = self.catalog.legal_allowed_skills()
        forbidden = self.catalog.legal_forbidden_skills()
        registered = {item.name for item in self.registry.list_skills()}
        print(" max_steps:", self.catalog.legal_max_steps())
        print(" allowed count:", len(allowed))
        print(" forbidden:", forbidden)
        print(" hp.plot allowed:", "qt.ai.hp.plot" in allowed)
        print(" missing new:", sorted(set(_NEW) - set(allowed)))
        self.assertEqual(self.catalog.legal_max_steps(), 3)
        self.assertEqual(set(allowed), set(_KEPT) | set(_NEW))
        self.assertEqual(set(forbidden), set(_FORBIDDEN))
        self.assertFalse(set(allowed) & set(forbidden))
        self.assertTrue(set(allowed) <= registered)
        self.assertNotIn("qt.ai.hp.plot", forbidden)
        for name in _OFF_EDGE:
            self.assertNotIn(name, allowed)
            self.assertNotIn(name, forbidden)

    def test_three_step_fetch_returns_plot_stays_dry_run(self) -> None:
        """取面板、算收益、出图三步放行，仍是 dry_run，出图仍要确认。"""

        print("\n[TestAi04A5OpenEdges] 三步取数收益出图")
        steps = [
            {
                "skill_name": "qt.ai.data.kline",
                "inputs": {"shares": "000300.SH"},
            },
            {
                "skill_name": "qt.ai.hp.returns",
                "inputs": {},
                "depends_on": ["step_1"],
            },
            {
                "skill_name": "qt.ai.hp.plot",
                "inputs": {"page": 1},
                "depends_on": ["step_2"],
            },
        ]
        plan, fake = _open_plan(self.registry, steps)
        names = [step.skill_name for step in plan.steps]
        depends = [list(step.depends_on) for step in plan.steps]
        print(" intent_job:", plan.planner_trace.get("intent_job"))
        print(" skills:", names)
        print(" depends_on:", depends)
        print(" execution_mode:", plan.execution_mode)
        print(" rationale:", plan.planner_trace.get("rationale"))
        self.assertEqual(plan.planner_trace.get("intent_job"), "open")
        self.assertEqual(plan.execution_mode, "dry_run")
        self.assertEqual(
            names,
            ["qt.ai.data.kline", "qt.ai.hp.returns", "qt.ai.hp.plot"],
        )
        self.assertEqual(depends, [[], ["step_1"], ["step_2"]])
        self.assertEqual(plan.steps[0].inputs.get("shares"), "000300.SH")
        plot = plan.steps[2]
        effects = {
            "filesystem_write": bool(plot.side_effects.filesystem_write),
            "network": bool(plot.side_effects.network),
            "local_state_change": bool(plot.side_effects.local_state_change),
            "heavy_compute": bool(plot.side_effects.heavy_compute),
        }
        print(" plot filesystem_write:", effects["filesystem_write"])
        print(" plot needs_confirm:", step_needs_confirm(plot.skill_name, effects))
        self.assertTrue(plot.side_effects.filesystem_write)
        self.assertTrue(step_needs_confirm(plot.skill_name, effects))
        open_prompts = [text for text in fake.prompts if text.startswith("Allowed skills:")]
        print(" open prompts:", len(open_prompts))
        self.assertEqual(len(open_prompts), 1)
        allowed_section = open_prompts[0].split("User query:", 1)[0]
        print(" returns in allowed section:", "qt.ai.hp.returns" in allowed_section)
        print(" backtest in allowed section:", "qt.ai.backtest.run_builtin" in allowed_section)
        self.assertIn("qt.ai.hp.returns", allowed_section)
        self.assertNotIn("qt.ai.backtest.run_builtin", allowed_section)

    def test_four_steps_are_rejected(self) -> None:
        """四步超过上限，整单澄清，不留下那四只技能。"""

        print("\n[TestAi04A5OpenEdges] 四步拒绝")
        four = [
            "qt.ai.data.kline",
            "qt.ai.hp.returns",
            "qt.ai.hp.volatility",
            "qt.ai.hp.plot",
        ]
        steps = [
            {"skill_name": name, "inputs": {"shares": "000300.SH"} if idx == 0 else {}}
            for idx, name in enumerate(four)
        ]
        plan, _fake = _open_plan(self.registry, steps)
        names = [step.skill_name for step in plan.steps]
        reason = plan.steps[0].inputs.get("reason") if plan.steps else ""
        print(" intent_job:", plan.planner_trace.get("intent_job"))
        print(" skills:", names)
        print(" reason:", reason)
        print(" execution_mode:", plan.execution_mode)
        self.assertEqual(plan.planner_trace.get("intent_job"), "clarify")
        self.assertEqual(names, ["qt.ai.system.fallback"])
        self.assertEqual(reason, "open_too_many_steps")
        for name in four:
            self.assertNotIn(name, names)

    def test_forbidden_skills_are_rejected(self) -> None:
        """回测、refill、优化、写码、实盘和旧导出技能各被拒绝。"""

        print("\n[TestAi04A5OpenEdges] 禁止技能拒绝")
        for name in _FORBIDDEN:
            plan, _fake = _open_plan(
                self.registry,
                [{"skill_name": name, "inputs": {}}],
            )
            names = [step.skill_name for step in plan.steps]
            reason = plan.steps[0].inputs.get("reason") if plan.steps else ""
            print(" skill:", name)
            print(" intent_job:", plan.planner_trace.get("intent_job"))
            print(" skills:", names)
            print(" reason:", reason)
            print(" execution_mode:", plan.execution_mode)
            self.assertEqual(plan.planner_trace.get("intent_job"), "clarify")
            self.assertEqual(names, ["qt.ai.system.fallback"])
            self.assertEqual(reason, "open_forbidden_skill")
            self.assertNotIn(name, names)

    def test_skills_off_the_edge_are_rejected(self) -> None:
        """写策略和筛股大技能不在合法边上，理由不是新的禁止项。"""

        print("\n[TestAi04A5OpenEdges] 边外技能拒绝")
        for name in _OFF_EDGE:
            plan, _fake = _open_plan(
                self.registry,
                [{"skill_name": name, "inputs": {}}],
            )
            names = [step.skill_name for step in plan.steps]
            reason = plan.steps[0].inputs.get("reason") if plan.steps else ""
            print(" skill:", name)
            print(" intent_job:", plan.planner_trace.get("intent_job"))
            print(" skills:", names)
            print(" reason:", reason)
            print(" execution_mode:", plan.execution_mode)
            self.assertEqual(plan.planner_trace.get("intent_job"), "clarify")
            self.assertEqual(names, ["qt.ai.system.fallback"])
            self.assertEqual(reason, "open_skill_not_on_legal_edge")
            self.assertNotIn(name, names)


if __name__ == "__main__":
    unittest.main()
