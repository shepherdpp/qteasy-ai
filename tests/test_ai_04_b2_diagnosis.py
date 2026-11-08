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
from datetime import date, timedelta

import numpy as np
import pandas as pd

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
        print(" vol view:", vol.steps[1].inputs.get("view"))
        print(" ret view:", ret.steps[1].inputs.get("view"))
        self.assertEqual(vol.planner_trace.get("intent_job"), "data.summary")
        self.assertEqual(ret.planner_trace.get("intent_job"), "data.summary")
        self.assertIn("qt.ai.hp.volatility", vol_names)
        self.assertNotIn("qt.ai.hp.returns", vol_names)
        self.assertIn("qt.ai.hp.returns", ret_names)
        self.assertNotIn("qt.ai.hp.volatility", ret_names)
        self.assertEqual(vol.steps[1].inputs.get("view"), "shape")
        self.assertEqual(ret.steps[1].inputs.get("view"), "shape")

    def test_window_sixty_and_return_slots(self) -> None:
        """60 日波动写入窗口 60。对数收益和 5 日收益进摘要并写对应槽。"""

        print("\n[TestAi04B2] 窗口、对数和 5 日收益")
        closes = [10.0 + (i % 5) * 0.7 + i * 0.15 for i in range(30)]
        window_plan = self.planner.build_plan("000300.SH 60日波动率", mode="plan")
        log_plan = self.planner.build_plan("000300.SH 的对数收益", mode="plan")
        period_plan = self.planner.build_plan("000300.SH 的5日收益", mode="plan")
        vol_step = next(step for step in window_plan.steps if step.skill_name == "qt.ai.hp.volatility")
        log_step = next(step for step in log_plan.steps if step.skill_name == "qt.ai.hp.returns")
        period_step = next(step for step in period_plan.steps if step.skill_name == "qt.ai.hp.returns")
        print(" window job:", window_plan.planner_trace.get("intent_job"), "window:", vol_step.inputs.get("window"))
        print(" log job:", log_plan.planner_trace.get("intent_job"), "method:", log_step.inputs.get("method"))
        print(" period job:", period_plan.planner_trace.get("intent_job"), "periods:", period_step.inputs.get("periods"))
        self.assertEqual(window_plan.planner_trace.get("intent_job"), "data.summary")
        self.assertEqual(vol_step.inputs.get("window"), 60)
        self.assertEqual(log_plan.planner_trace.get("intent_job"), "data.summary")
        self.assertEqual(log_step.inputs.get("method"), "log")
        self.assertEqual(period_plan.planner_trace.get("intent_job"), "data.summary")
        self.assertEqual(period_step.inputs.get("periods"), 5)

        expected_60 = _hand_vol(closes, 60)
        expected_20 = _hand_vol(closes, 20)
        print(" hand vol 60:", expected_60, "hand vol 20:", expected_20)
        self.assertNotAlmostEqual(expected_60, expected_20, places=6)
        vol_last = self._execute(window_plan, closes, "qt.ai.hp.volatility")["metrics"]["last"]
        print(" skill vol last:", vol_last)
        self.assertAlmostEqual(float(vol_last), expected_60, places=8)

        log_frame = self._execute(log_plan, closes, "qt.ai.hp.returns")["payload"]["frame"]
        period_frame = self._execute(period_plan, closes, "qt.ai.hp.returns")["payload"]["frame"]
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
        print(" start:", plan.steps[0].inputs.get("start"), "calendar:", start)
        print(" end:", plan.steps[0].inputs.get("end"), "calendar:", end)
        self.assertEqual(plan.steps[0].inputs.get("start"), start)
        self.assertEqual(plan.steps[0].inputs.get("end"), end)

        recent = self.planner.build_plan("000300.SH 近一年波动率", mode="plan")
        recent_start = (today - timedelta(days=365)).strftime("%Y%m%d")
        recent_end = today.strftime("%Y%m%d")
        print(" recent:", recent.steps[0].inputs.get("start"), recent.steps[0].inputs.get("end"))
        print(" calendar:", recent_start, recent_end)
        self.assertEqual(recent.steps[0].inputs.get("start"), recent_start)
        self.assertEqual(recent.steps[0].inputs.get("end"), recent_end)

        two = self.planner.build_plan("000001.SZ 和 000002.SZ 的波动率", mode="plan")
        codes = str(two.steps[0].inputs.get("shares") or "")
        print(" diagnosis shares:", codes, "job:", two.planner_trace.get("intent_job"))
        self.assertEqual(two.planner_trace.get("intent_job"), "data.summary")
        self.assertEqual(codes, "000001.SZ,000002.SZ")

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
        self.assertEqual(plan.planner_trace.get("intent_job"), "data.summary")
        self.assertEqual(names, _FULL)
        self.assertNotEqual(plan.steps[0].inputs.get("reason"), "wire_product_mismatch")
        for step in plan.steps[1:]:
            self.assertEqual(step.depends_on, ["step_1"])
        stat = next(step for step in plan.steps if step.skill_name == "qt.ai.hp.volatility")
        plot = next(step for step in plan.steps if step.skill_name == "qt.ai.hp.plot")
        print(" as_panel:", stat.inputs.get("as_panel"), "plot shares:", plot.inputs.get("shares"))
        self.assertNotIn("as_panel", stat.inputs)
        self.assertIn(plot.inputs.get("shares"), (None, ""))
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
        projected = [row["name"] for row in _project(self.planner, plan.steps, set(), "data.summary")]
        print(" projected:", projected)
        self.assertIn("window", projected)
        self.assertIn("view", projected)
        for blocked in ("as_panel", "interactive", "rows", "upstream_payload", "upstream_payloads"):
            self.assertNotIn(blocked, projected)
        for name in names:
            for banned in _BANNED:
                self.assertNotIn(banned, name)

    def test_default_window_stays_off_the_step_until_confirmed(self) -> None:
        """没说窗口时侧栏是 default、未确认，步骤里没有 window。确认 60 后才写入。"""

        print("\n[TestAi04B2] 侧栏默认窗口")
        state = ConversationState.empty("b2-window")
        state.start_task(query="000300.SH 波动率", job="data.summary")
        plan = self.planner.build_plan("000300.SH 波动率", mode="plan", session=state)
        slot = state.task.slots.get("window")
        vol = next(step for step in plan.steps if step.skill_name == "qt.ai.hp.volatility")
        print(" slot:", None if slot is None else (slot.value, slot.source, slot.confirmed))
        print(" step window:", vol.inputs.get("window"))
        self.assertIsNotNone(slot)
        self.assertEqual(slot.value, 20)
        self.assertEqual(slot.source, "default")
        self.assertFalse(slot.confirmed)
        self.assertNotIn("window", vol.inputs)
        state.set_slot("window", 60, source="user", confirmed=True)
        changed = self.planner.build_plan(
            "000300.SH 波动率",
            mode="plan",
            session=state,
            skip_classify=True,
        )
        changed_vol = next(step for step in changed.steps if step.skill_name == "qt.ai.hp.volatility")
        print(" confirmed window:", changed_vol.inputs.get("window"))
        self.assertEqual(changed_vol.inputs.get("window"), 60)

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
        stat = next(step for step in second.steps if step.skill_name == "qt.ai.hp.returns")
        print(" returns inputs:", stat.inputs)
        self.assertEqual(second.planner_trace.get("intent_job"), "data.summary")
        self.assertIn("qt.ai.hp.describe", _names(second.steps))
        self.assertNotIn("qt.ai.hp.volatility", _names(second.steps))
        self.assertNotIn("window", stat.inputs)
        self.assertEqual(stat.inputs.get("price_htype"), "close")

    def test_execute_once_default_vol_and_one_png(self) -> None:
        """四步只取一次数。默认波动对照窗口 20，出图一张且 interactive 为 false。"""

        print("\n[TestAi04B2] 执行一次取数")
        closes = [10.0, 10.4, 10.1, 11.2, 10.8, 11.5, 11.1, 12.0]
        plan = self.planner.build_plan("kline summary of 000300.SH export png", mode="plan")
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
        plan.execution_mode = "execute"
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
