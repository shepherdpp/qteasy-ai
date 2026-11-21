# coding=utf-8
# ======================================
# File: test_ai_04_b2_diagnosis.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-08
# Desc:
# 0.4 B2：摘要与导出共用一张体检表。
# 问句省略步骤，可选槽有默认但不追问。
# ======================================

import tempfile
import unittest
from datetime import date

import numpy as np
import pandas as pd

from qteasy_ai.contracts import ToolPlan, ToolStep
from qteasy_ai.executor import PlanExecutor
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.planner import Planner
from qteasy_ai.registry import SkillRegistry
from qteasy_ai.session import ConversationState
from qteasy_ai.skills.data_kline import build_data_kline_skill
from qteasy_ai.skills.hp_describe import build_hp_describe_skill
from qteasy_ai.skills.hp_plot import build_hp_plot_skill
from qteasy_ai.skills.hp_transform import build_hp_returns_skill
from qteasy_ai.skills.hp_volatility import build_hp_volatility_skill
from qteasy_ai.app import build_default_registry
from qteasy_ai.intents.recipes import _diagnosis_steps
from qteasy_ai.slot_graph import _project

_FULL = [
    "qt.ai.data.kline",
    "qt.ai.hp.describe",
    "qt.ai.hp.volatility",
    "qt.ai.hp.plot",
]
_BANNED = (
    "backtest",
    "refill",
    "codegen",
    "live",
    "cum_return",
    "research_preset",
    "summary_kline",
    "export_kline",
)


def _names(steps) -> list:
    """步骤技能名。"""

    return [step.skill_name for step in steps]


def _accepted(plan, skill_name: str) -> dict:
    """快照里这个技能的输入。"""

    for row in (plan.assumptions or {}).get("accepted_steps") or []:
        if row.get("skill_name") == skill_name:
            return dict(row.get("inputs") or {})
    return {}


def _filled_pair(skill_name: str, inputs: dict) -> ToolPlan:
    """已经填好代码的取数加一步统计，交给执行器。"""

    return ToolPlan(
        plan_id="plan_filled_stat",
        user_query="filled statistic",
        execution_mode="execute",
        steps=[
            ToolStep(step_id="step_1", skill_name="qt.ai.data.kline", inputs={"shares": "000300.SH"}),
            ToolStep(step_id="step_2", skill_name=skill_name, inputs=dict(inputs), depends_on=["step_1"]),
        ],
    )


def _ohlcv(closes) -> pd.DataFrame:
    """单标的日频 OHLCV。收盘价就是夹具。"""

    close = np.asarray(closes, dtype=float)
    index = pd.date_range("2024-01-01", periods=len(close), freq="D")
    index.name = "date"
    return pd.DataFrame(
        {
            "open": close - 0.4,
            "high": close + 0.6,
            "low": close - 0.8,
            "close": close,
            "vol": np.full(len(close), 10.0),
        },
        index=index,
    )


def _hand_vol(closes, window: int) -> float:
    """简单收益的滚动样本标准差，再乘 sqrt(252)。窗口长于样本时用全部收益。"""

    prices = np.asarray(closes, dtype=float)
    returns = prices[1:] / prices[:-1] - 1.0
    sample = returns[-int(window):]
    return float(sample.std(ddof=1) * np.sqrt(252.0))


def _hand_returns(closes, periods: int, method: str) -> np.ndarray:
    """简单收益是 p_t / p_{t-n} - 1，对数收益是对数差。前 n 根为空。"""

    prices = np.asarray(closes, dtype=float)
    out = np.full(len(prices), np.nan)
    if method == "log":
        out[periods:] = np.log(prices[periods:]) - np.log(prices[:-periods])
    else:
        out[periods:] = prices[periods:] / prices[:-periods] - 1.0
    return out


class TestAi04B2Diagnosis(unittest.TestCase):
    """摘要和导出走同一张表，省略和填槽按问句。"""

    def setUp(self) -> None:
        self.planner = Planner(build_default_registry(), env_facts={})

    def test_one_table_omits_different_steps(self) -> None:
        """两个旧 id 都由 _diagnosis_steps 产生，省略后的技能名单不同。"""

        print("\n[TestAi04B2] 同一张表，两句省略不同")
        summary_query = "kline summary of 000300.SH"
        export_query = "export kline of 000300.SH to png"
        both = "kline summary of 000300.SH export png"
        summary_steps = _diagnosis_steps(self.planner, summary_query, "data.summary")
        export_steps = _diagnosis_steps(self.planner, export_query, "data.export")
        full_summary = _diagnosis_steps(self.planner, both, "data.summary")
        full_export = _diagnosis_steps(self.planner, both, "data.export")
        summary_names = _names(summary_steps)
        export_names = _names(export_steps)
        print(" summary:", summary_names)
        print(" export:", export_names)
        print(" both summary:", _names(full_summary))
        print(" both export:", _names(full_export))
        self.assertEqual(summary_names, _FULL[:3])
        self.assertEqual(export_names, ["qt.ai.data.kline", "qt.ai.hp.plot"])
        self.assertEqual(_names(full_summary), _FULL)
        self.assertEqual(_names(full_export), _FULL)
        self.assertNotEqual(summary_names, export_names)

    def test_returns_swap_keeps_job_and_shape(self) -> None:
        """波动和收益都进 data.summary，只换统计技能。没写视图时仍是 shape。"""

        print("\n[TestAi04B2] 波动与收益换技能")
        vol = self.planner.build_plan("沪深300今年波动率和交易天数 000300.SH", mode="plan")
        ret = self.planner.build_plan("沪深300今年收益和交易天数 000300.SH", mode="plan")
        vol_names = _names(vol.steps)
        ret_names = _names(ret.steps)
        print(" vol job:", vol.planner_trace.get("intent_job"), vol_names)
        print(" ret job:", ret.planner_trace.get("intent_job"), ret_names)
        print(" vol view:", _accepted(vol, "qt.ai.hp.describe").get("view"))
        print(" ret view:", _accepted(ret, "qt.ai.hp.describe").get("view"))
        vol_acc = [row.get("skill_name") for row in (vol.assumptions or {}).get("accepted_steps") or []]
        ret_acc = [row.get("skill_name") for row in (ret.assumptions or {}).get("accepted_steps") or []]
        print(" vol accepted:", vol_acc, _accepted(vol, "qt.ai.data.kline"))
        print(" ret accepted:", ret_acc, _accepted(ret, "qt.ai.data.kline"))
        self.assertEqual(vol.planner_trace.get("intent_job"), "data.summary")
        self.assertEqual(ret.planner_trace.get("intent_job"), "data.summary")
        self.assertEqual(vol_names, ["qt.ai.system.fallback"])
        self.assertEqual(ret_names, ["qt.ai.system.fallback"])
        self.assertIn("qt.ai.hp.volatility", vol_acc)
        self.assertNotIn("qt.ai.hp.returns", vol_acc)
        self.assertIn("qt.ai.hp.returns", ret_acc)
        self.assertNotIn("qt.ai.hp.volatility", ret_acc)
        self.assertNotIn("000300.SH", str(_accepted(vol, "qt.ai.data.kline")))
        self.assertNotIn("000300.SH", str(_accepted(ret, "qt.ai.data.kline")))

    def test_window_sixty_and_return_slots(self) -> None:
        """60 日波动写入窗口 60。对数收益和 5 日收益进摘要并写对应槽。"""

        print("\n[TestAi04B2] 窗口、对数和 5 日收益")
        closes = [10.0 + (i % 5) * 0.7 + i * 0.15 for i in range(30)]
        window_plan = self.planner.build_plan("000300.SH 60日波动率", mode="plan")
        log_plan = self.planner.build_plan("000300.SH 的对数收益", mode="plan")
        period_plan = self.planner.build_plan("000300.SH 的5日收益", mode="plan")
        print(" window job:", window_plan.planner_trace.get("intent_job"), "window:", _accepted(window_plan, "qt.ai.hp.volatility"))
        print(" log job:", log_plan.planner_trace.get("intent_job"), "method:", _accepted(log_plan, "qt.ai.hp.returns"))
        print(" period job:", period_plan.planner_trace.get("intent_job"), "periods:", _accepted(period_plan, "qt.ai.hp.returns"))
        self.assertEqual(window_plan.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(window_plan.steps[0].inputs.get("reason"), "missing_required_slots")
        self.assertNotEqual(_accepted(window_plan, "qt.ai.hp.volatility").get("window"), 60)
        self.assertNotIn("000300.SH", str(_accepted(window_plan, "qt.ai.data.kline")))
        self.assertEqual(log_plan.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertNotEqual(_accepted(log_plan, "qt.ai.hp.returns").get("method"), "log")
        self.assertEqual(period_plan.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertNotEqual(_accepted(period_plan, "qt.ai.hp.returns").get("periods"), 5)

        expected_60 = _hand_vol(closes, 60)
        expected_20 = _hand_vol(closes, 20)
        print(" hand vol 60:", expected_60, "hand vol 20:", expected_20)
        self.assertNotAlmostEqual(expected_60, expected_20, places=6)
        vol_last = self._execute(_filled_pair("qt.ai.hp.volatility", {"window": 60}), closes, "qt.ai.hp.volatility")["metrics"]["last"]
        print(" skill vol last:", vol_last)
        self.assertAlmostEqual(float(vol_last), expected_60, places=8)

        log_frame = self._execute(_filled_pair("qt.ai.hp.returns", {"method": "log"}), closes, "qt.ai.hp.returns")["payload"]["frame"]
        period_frame = self._execute(_filled_pair("qt.ai.hp.returns", {"periods": 5}), closes, "qt.ai.hp.returns")["payload"]["frame"]
        log_values = np.asarray(log_frame, dtype=float).ravel()
        period_values = np.asarray(period_frame, dtype=float).ravel()
        log_expected = _hand_returns(closes, 1, "log")
        period_expected = _hand_returns(closes, 5, "simple")
        print(" log tail:", log_values[-3:], "expected:", log_expected[-3:])
        print(" period tail:", period_values[-3:], "expected:", period_expected[-3:])
        self.assertTrue(np.allclose(log_values, log_expected, equal_nan=True))
        self.assertTrue(np.allclose(period_values, period_expected, equal_nan=True))

    def test_this_year_and_two_codes(self) -> None:
        """今年是当年 1 月 1 日到 12 月 31 日。体检收齐两个代码，持有对比金句仍收三个。"""

        print("\n[TestAi04B2] 今年与多代码")
        plan = self.planner.build_plan("000300.SH 今年波动率", mode="plan")
        today = date.today()
        start = f"{today.year:04d}0101"
        end = f"{today.year:04d}1231"
        from qteasy_ai.slot_graph import kernel_window

        window = kernel_window()
        kline = _accepted(plan, "qt.ai.data.kline")
        print(" start:", kline.get("start"), "calendar:", start, "kernel:", window)
        print(" end:", kline.get("end"), "calendar:", end)
        print(" reason:", plan.steps[0].inputs.get("reason"))
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(plan.steps[0].inputs.get("reason"), "missing_required_slots")
        self.assertEqual(kline.get("start"), window["start"])
        self.assertEqual(kline.get("end"), window["end"])
        self.assertNotEqual(kline.get("start"), start)
        self.assertNotIn("000300.SH", str(kline))

        recent = self.planner.build_plan("000300.SH 近一年波动率", mode="plan")
        recent_kline = _accepted(recent, "qt.ai.data.kline")
        print(" recent skills:", [step.skill_name for step in recent.steps])
        print(" recent:", recent_kline.get("start"), recent_kline.get("end"))
        print(" reason:", recent.steps[0].inputs.get("reason"))
        self.assertEqual(recent.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(recent.steps[0].inputs.get("reason"), "missing_required_slots")
        self.assertEqual(recent_kline.get("start"), window["start"])
        self.assertEqual(recent_kline.get("end"), window["end"])
        self.assertNotIn("000300.SH", str(recent_kline))

        two = self.planner.build_plan("000001.SZ 和 000002.SZ 的波动率", mode="plan")
        two_kline = _accepted(two, "qt.ai.data.kline")
        print(" diagnosis shares:", two_kline.get("shares"), "job:", two.planner_trace.get("intent_job"))
        self.assertEqual(two.planner_trace.get("intent_job"), "data.summary")
        self.assertEqual(two.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertNotIn("000001.SZ", str(two_kline))
        self.assertNotIn("000002.SZ", str(two_kline))

        hold = self.planner.build_plan("000001.SZ 和 000002.SZ 做一条等权组合，相对沪深300", mode="plan")
        hold_codes = str(hold.steps[0].inputs.get("shares") or "")
        print(" hold shares:", hold_codes, "job:", hold.planner_trace.get("intent_job"))
        self.assertEqual(hold.planner_trace.get("intent_job"), "research.hold_compare")
        for code in ("000001.SZ", "000002.SZ", "000300.SH"):
            self.assertIn(code, hold_codes)

    def test_four_steps_fan_out_and_slots_stay_empty_in_catalog(self) -> None:
        """四步都挂在取数上。目录槽仍空，因子 IC 槽名不变，投影不带黑名单键。"""

        print("\n[TestAi04B2] 扇出与投影")
        query = "kline summary of 000300.SH export png"
        plan = self.planner.build_plan(query, mode="plan")
        names = _names(plan.steps)
        print(" job:", plan.planner_trace.get("intent_job"))
        print(" skills:", names)
        print(" depends:", [step.depends_on for step in plan.steps])
        print(" reason:", plan.steps[0].inputs.get("reason"))
        accepted_names = [row.get("skill_name") for row in (plan.assumptions or {}).get("accepted_steps") or []]
        print(" accepted:", accepted_names, _accepted(plan, "qt.ai.data.kline"))
        self.assertEqual(plan.planner_trace.get("intent_job"), "data.summary")
        self.assertEqual(names, ["qt.ai.system.fallback"])
        self.assertEqual(plan.steps[0].inputs.get("reason"), "missing_required_slots")
        self.assertEqual(accepted_names, _FULL)
        self.assertNotIn("000300.SH", str(_accepted(plan, "qt.ai.data.kline")))
        self.assertNotIn("as_panel", _accepted(plan, "qt.ai.hp.volatility"))
        self.assertIn(_accepted(plan, "qt.ai.hp.plot").get("shares"), (None, ""))
        self.assertEqual(self.planner.intent_engine.catalog.legal_max_steps(), 3)
        catalog = self.planner.intent_engine.catalog
        summary_slots = [item.get("name") for item in catalog.job_slots("data.summary")]
        export_slots = [item.get("name") for item in catalog.job_slots("data.export")]
        factor_slots = [item.get("name") for item in catalog.job_slots("research.factor_ic")]
        print(" summary slots:", summary_slots)
        print(" export slots:", export_slots)
        print(" factor slots:", factor_slots)
        self.assertEqual(summary_slots, [])
        self.assertEqual(export_slots, [])
        self.assertEqual(factor_slots, ["shares", "start", "end", "factor_htype", "return_htype"])
        recipe = _diagnosis_steps(self.planner, query, "data.summary")
        projected = [row["name"] for row in _project(self.planner, recipe, set(), "data.summary")]
        print(" projected:", projected)
        self.assertIn("window", projected)
        self.assertIn("view", projected)
        for blocked in ("as_panel", "interactive", "rows", "upstream_payload", "upstream_payloads"):
            self.assertNotIn(blocked, projected)
        for name in accepted_names:
            for banned in _BANNED:
                self.assertNotIn(banned, name)

    def test_default_window_stays_off_the_step_until_confirmed(self) -> None:
        """没说窗口时侧栏是 default、未确认，步骤里没有 window。确认 60 后才写入。"""

        print("\n[TestAi04B2] 侧栏默认窗口")
        state = ConversationState.empty("b2-window")
        state.start_task(query="000300.SH 波动率", job="data.summary")
        plan = self.planner.build_plan("000300.SH 波动率", mode="plan", session=state)
        slot = state.task.slots.get("window")
        vol = _accepted(plan, "qt.ai.hp.volatility")
        print(" slot:", None if slot is None else (slot.value, slot.source, slot.confirmed))
        print(" step window:", vol.get("window"), "visible:", _names(plan.steps))
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertNotIn("000300.SH", str(_accepted(plan, "qt.ai.data.kline")))
        self.assertIsNotNone(slot)
        self.assertEqual(slot.value, 20)
        self.assertEqual(slot.source, "default")
        self.assertFalse(slot.confirmed)
        self.assertNotIn("window", vol)
        state.set_slot("window", 60, source="user", confirmed=True)
        changed = self.planner.build_plan(
            "000300.SH 波动率",
            mode="plan",
            session=state,
            skip_classify=True,
        )
        changed_vol = _accepted(changed, "qt.ai.hp.volatility")
        print(" confirmed window:", changed_vol.get("window"), "visible:", _names(changed.steps))
        self.assertEqual(changed.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(changed_vol.get("window"), 60)

    def test_followup_switches_statistic_and_drops_foreign_inputs(self) -> None:
        """跟进一句「收益」只换统计技能。波动专有的 window 不留到收益步。"""

        print("\n[TestAi04B2] 跟进切换收益")
        state = ConversationState.empty("b2-switch")
        asked = "kline summary of 000300.SH"
        state.start_task(query=asked, job="data.summary")
        first = self.planner.build_plan(asked, mode="plan", session=state)
        state.set_slot("window", 60, source="user", confirmed=True)
        state.set_slot("price_htype", "close", source="user", confirmed=True)
        second = self.planner.build_plan("收益", mode="plan", session=state, skip_classify=True)
        print(" first:", _names(first.steps), "job:", first.planner_trace.get("intent_job"))
        print(" second:", _names(second.steps), "job:", second.planner_trace.get("intent_job"))
        stat = _accepted(second, "qt.ai.hp.returns")
        accepted_names = [row.get("skill_name") for row in (second.assumptions or {}).get("accepted_steps") or []]
        print(" returns inputs:", stat, "accepted:", accepted_names)
        self.assertEqual(second.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(second.planner_trace.get("intent_job"), "data.summary")
        self.assertIn("qt.ai.hp.describe", accepted_names)
        self.assertNotIn("qt.ai.hp.volatility", accepted_names)
        self.assertNotIn("window", stat)
        self.assertEqual(stat.get("price_htype"), "close")
        self.assertNotIn("000300.SH", str(_accepted(second, "qt.ai.data.kline")))

    def test_execute_once_default_vol_and_one_png(self) -> None:
        """四步只取一次数。默认波动对照窗口 20，出图一张且 interactive 为 false。"""

        print("\n[TestAi04B2] 执行一次取数")
        closes = [10.0, 10.4, 10.1, 11.2, 10.8, 11.5, 11.1, 12.0]
        calls = {"n": 0}

        def _fake(**kwargs):
            calls["n"] += 1
            print(" get_kline kwargs:", kwargs)
            return _ohlcv(closes)

        registry = SkillRegistry()
        for meta, handler in (
            build_data_kline_skill(get_kline_func=_fake),
            build_hp_describe_skill(),
            build_hp_volatility_skill(),
            build_hp_plot_skill(),
        ):
            registry.register(meta, handler)
        plan = ToolPlan(
            plan_id="plan_summary_png",
            user_query="filled summary and plot",
            execution_mode="execute",
            steps=[
                ToolStep(step_id="step_1", skill_name="qt.ai.data.kline", inputs={"shares": "000300.SH"}),
                ToolStep(
                    step_id="step_2",
                    skill_name="qt.ai.hp.describe",
                    inputs={"view": "shape"},
                    depends_on=["step_1"],
                ),
                ToolStep(
                    step_id="step_3",
                    skill_name="qt.ai.hp.volatility",
                    inputs={"window": 20},
                    depends_on=["step_1"],
                ),
                ToolStep(
                    step_id="step_4",
                    skill_name="qt.ai.hp.plot",
                    inputs={"interactive": False},
                    depends_on=["step_1"],
                ),
            ],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = PlanExecutor(registry, memory_store=MemoryStore(base_dir=temp_dir)).execute(
                plan,
                confirm=True,
            )
        rows = payload["execution"]["steps"]
        by_name = {row["skill_name"]: row["result"] for row in rows}
        print(" calls:", calls["n"])
        print(" skills:", list(by_name))
        print(" describe:", by_name["qt.ai.hp.describe"]["metrics"])
        print(" vol:", by_name["qt.ai.hp.volatility"]["metrics"])
        print(" plot echo:", by_name["qt.ai.hp.plot"]["inputs_echo"])
        print(" artifacts:", by_name["qt.ai.hp.plot"].get("artifacts"))
        expected = _hand_vol(closes, 20)
        print(" hand vol 20:", expected)
        self.assertTrue(all(row["result"].get("ok") for row in rows))
        self.assertEqual(calls["n"], 1)
        self.assertEqual(by_name["qt.ai.hp.describe"]["metrics"]["n_rows"], len(closes))
        self.assertAlmostEqual(float(by_name["qt.ai.hp.volatility"]["metrics"]["last"]), expected, places=8)
        self.assertEqual(len(by_name["qt.ai.hp.plot"]["artifacts"]), 1)
        self.assertFalse(by_name["qt.ai.hp.plot"]["inputs_echo"]["interactive"])
        for name in by_name:
            for banned in _BANNED:
                self.assertNotIn(banned, name)

    def _execute(self, plan, closes, skill_name: str) -> dict:
        """用假行情执行，返回指定技能的结果。"""

        def _fake(**kwargs):
            return _ohlcv(closes)

        registry = SkillRegistry()
        for meta, handler in (
            build_data_kline_skill(get_kline_func=_fake),
            build_hp_volatility_skill(),
            build_hp_returns_skill(),
            build_hp_describe_skill(),
        ):
            registry.register(meta, handler)
        plan.execution_mode = "execute"
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = PlanExecutor(registry, memory_store=MemoryStore(base_dir=temp_dir)).execute(
                plan,
                confirm=True,
            )
        print(" execute ok:", payload["execution"].get("ok"), "status:", payload["execution"].get("status"))
        row = next(item for item in payload["execution"]["steps"] if item["skill_name"] == skill_name)
        if not row["result"].get("ok", False):
            print(" error:", row["result"].get("error"))
        return row["result"]
