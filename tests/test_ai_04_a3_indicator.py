# coding=utf-8
# ======================================
# File: test_ai_04_a3_indicator.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-02
# Desc:
# 0.4 A3：指标、蜡烛形态与研究预设。
# 成功看手算数值，失败看英文，换名字仍是同一个技能。
# ======================================

import math
import tempfile
import unittest

import numpy as np
import pandas as pd

from qteasy.history import HistoryPanel
from qteasy.tafuncs import TA_LIB_AVAILABLE
from qteasy_ai.app import build_default_registry
from qteasy_ai.contracts import SkillMetadata, SkillSideEffects, ToolPlan, ToolStep
from qteasy_ai.executor import PlanExecutor
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.registry import SkillRegistry
from qteasy_ai.skills.hp_indicator import (
    build_hp_candle_pattern_skill,
    build_hp_indicator_skill,
    build_hp_research_preset_skill,
)

_INDICATOR_SKILLS = [
    "qt.ai.hp.indicator",
    "qt.ai.hp.candle_pattern",
    "qt.ai.hp.research_preset",
]
_DATES3 = ["2024-01-02", "2024-01-03", "2024-01-04"]
_MACD_COLUMNS = ("macd_12_26_9", "macd_signal_12_26_9", "macd_hist_12_26_9")
_PRESET_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "vol",
    "macd_12_26_9",
    "macd_signal_12_26_9",
    "macd_hist_12_26_9",
    "sma_20",
)


def _panel(values, shares, dates, columns) -> HistoryPanel:
    """用已知数字做一块面板。values 形状是 (标的, 日期, 列)。"""

    return HistoryPanel(
        values=np.asarray(values, dtype=float),
        levels=list(shares),
        rows=pd.to_datetime(list(dates)),
        columns=list(columns),
    )


def _constant(rows: int, columns: list) -> HistoryPanel:
    """每一列、每一根都是 10。"""

    values = np.full((1, rows, len(columns)), 10.0, dtype=float)
    dates = pd.date_range("2024-01-01", periods=rows, freq="D")
    return _panel(values, ["s1"], dates, columns)


def _flat(panel: HistoryPanel) -> list:
    """按标的、日期展开。NaN 记成 None。"""

    out = []
    for item in np.asarray(panel.values, dtype=float).reshape(-1):
        out.append(None if not np.isfinite(item) else float(item))
    return out


def _last(panel: HistoryPanel, htype: str):
    """某一列最后一根。NaN 记成 None。"""

    column = panel.subpanel(htypes=htype)
    item = float(np.asarray(column.values, dtype=float).reshape(-1)[-1])
    if not np.isfinite(item):
        return None
    return item


def _close_or_none(left, right) -> bool:
    """两边同为 None，或都是有限数且足够接近。"""

    if left is None or right is None:
        return left is None and right is None
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-8)


class TestA3Indicator(unittest.TestCase):
    """指标、形态与预设的金标准。数值是手工算的。"""

    def test_sma_windows_and_rejected_ta_kwarg(self) -> None:
        """[1, 2, 4] 的 2 日均线是 [nan, 1.5, 3]；3 日均线最后一根是 7/3。timeperiod 不接受。"""

        panel = _panel([[[1.0], [2.0], [4.0]]], ["s1"], _DATES3, ["close"])
        before = np.array(panel.values, copy=True)
        handler = build_hp_indicator_skill()[1]
        short = handler(func_name="sma", kwargs={"window": 2}, upstream_payload={"panel": panel})
        long = handler(func_name="sma", kwargs={"window": 3}, upstream_payload={"panel": panel})
        rejected = handler(func_name="sma", kwargs={"timeperiod": 2}, upstream_payload={"panel": panel})
        short_col = _flat(short["payload"]["panel"].subpanel(htypes="sma_2"))
        long_col = _flat(long["payload"]["panel"].subpanel(htypes="sma_3"))
        print("\n[A3 sma] window2:", short_col)
        print(" window3:", long_col)
        print(" timeperiod:", rejected["error"]["code"], rejected["error"]["message"])
        self.assertTrue(short["ok"])
        self.assertTrue(long["ok"])
        self.assertEqual(short["skill_name"], "qt.ai.hp.indicator")
        self.assertEqual(long["skill_name"], "qt.ai.hp.indicator")
        self.assertEqual(list(short["payload"]["panel"].htypes), ["close", "sma_2"])
        self.assertEqual(short_col, [None, 1.5, 3.0])
        self.assertEqual(len(long_col), 3)
        self.assertIsNone(long_col[0])
        self.assertIsNone(long_col[1])
        self.assertTrue(_close_or_none(long_col[2], 7.0 / 3.0))
        self.assertEqual(list(panel.htypes), ["close"])
        self.assertTrue(np.allclose(panel.values, before))
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["error"]["code"], "HP_INDICATOR_FAILED")
        self.assertIn("timeperiod", rejected["error"]["message"])
        self.assertIn("not accepted", rejected["error"]["message"])
        self.assertNotIn("Traceback", rejected["error"]["message"])

    def test_macd_then_sma_on_a_constant_series(self) -> None:
        """常数 10 的 MACD 最后一根是 0，20 日均线最后一根是 10。两次调用同一个技能。"""

        panel = _constant(60, ["close"])
        before = np.array(panel.values, copy=True)
        handler = build_hp_indicator_skill()[1]
        macd = handler(func_name="macd", upstream_payload={"panel": panel})
        priced = macd["payload"]["panel"]
        sma = handler(func_name="sma", kwargs={"window": 20}, upstream_payload={"panel": priced})
        macd_last = {name: _last(priced, name) for name in _MACD_COLUMNS}
        sma_last = _last(sma["payload"]["panel"], "sma_20")
        print("\n[A3 macd+sma] htypes:", list(priced.htypes), list(sma["payload"]["panel"].htypes))
        print(" macd last:", macd_last, "sma_20 last:", sma_last)
        self.assertTrue(macd["ok"])
        self.assertTrue(sma["ok"])
        self.assertEqual(macd["skill_name"], "qt.ai.hp.indicator")
        self.assertEqual(sma["skill_name"], "qt.ai.hp.indicator")
        self.assertEqual(list(priced.htypes), ["close", *_MACD_COLUMNS])
        for name, value in macd_last.items():
            self.assertTrue(_close_or_none(value, 0.0), name)
        self.assertIn("sma_20", list(sma["payload"]["panel"].htypes))
        self.assertTrue(_close_or_none(sma_last, 10.0))
        self.assertNotIn("sma_20", list(priced.htypes))
        self.assertEqual(list(panel.htypes), ["close"])
        self.assertTrue(np.allclose(panel.values, before))

    def test_dema_uses_apply_ta_and_rejects_unknown_kwarg(self) -> None:
        """常数 10 的 DEMA 最后一根是 10，列名是 dema。非法参数是英文失败。"""

        panel = _constant(40, ["close"])
        handler = build_hp_indicator_skill()[1]
        added = handler(func_name="dema", kwargs={"period": 3}, upstream_payload={"panel": panel})
        rejected = handler(func_name="dema", kwargs={"not_a_param": 1}, upstream_payload={"panel": panel})
        column = _last(added["payload"]["panel"], "dema")
        print("\n[A3 dema] htypes:", list(added["payload"]["panel"].htypes), "last:", column)
        print(" bad kwarg:", rejected["error"]["code"], rejected["error"]["message"])
        self.assertTrue(added["ok"])
        self.assertEqual(added["skill_name"], "qt.ai.hp.indicator")
        self.assertEqual(list(added["payload"]["panel"].htypes), ["close", "dema"])
        self.assertNotIn("ema_3", list(added["payload"]["panel"].htypes))
        self.assertTrue(_close_or_none(column, 10.0))
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["error"]["code"], "HP_INDICATOR_FAILED")
        self.assertIn("not_a_param", rejected["error"]["message"])
        self.assertNotIn("Traceback", rejected["error"]["message"])

    def test_indicator_english_failures(self) -> None:
        """缺函数、蜡烛形态、缺列、缺面板，都是英文技能错误。"""

        panel = _panel([[[1.0], [2.0], [4.0]]], ["s1"], _DATES3, ["close"])
        handler = build_hp_indicator_skill()[1]
        missing = handler(func_name="not_a_function", upstream_payload={"panel": panel})
        candle = handler(func_name="cdlhammer", upstream_payload={"panel": panel})
        nope = handler(func_name="sma", htype="nope", upstream_payload={"panel": panel})
        blank = handler(func_name="", upstream_payload={"panel": panel})
        no_panel = handler(func_name="sma")
        print("\n[A3 indicator errors]")
        print(" missing:", missing["error"]["message"])
        print(" candle:", candle["error"]["message"])
        print(" htype:", nope["error"]["message"])
        print(" blank:", blank["error"]["message"])
        print(" panel:", no_panel["error"]["code"], no_panel["error"]["message"])
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error"]["code"], "HP_INDICATOR_FAILED")
        self.assertIn("not_a_function", missing["error"]["message"])
        self.assertNotIn("Traceback", missing["error"]["message"])
        self.assertFalse(candle["ok"])
        self.assertEqual(candle["error"]["code"], "HP_INDICATOR_FAILED")
        self.assertIn("cdlhammer", candle["error"]["message"])
        self.assertIn("hp.candle_pattern", candle["error"]["message"])
        self.assertNotIn("Traceback", candle["error"]["message"])
        self.assertFalse(nope["ok"])
        self.assertIn("nope", nope["error"]["message"])
        self.assertNotIn("Traceback", nope["error"]["message"])
        self.assertFalse(blank["ok"])
        self.assertIn("func_name", blank["error"]["message"])
        self.assertFalse(no_panel["ok"])
        self.assertEqual(no_panel["error"]["code"], "HP_PANEL_MISSING")
        self.assertEqual(no_panel["error"]["message"], "A HistoryPanel from the previous step is required.")

    def test_candle_patterns_share_one_skill(self) -> None:
        """锤头和吞没是同一个技能。平盘信号为 0；没有函数或缺 open 时英文失败。"""

        flat = _constant(5, ["open", "high", "low", "close"])
        before = np.array(flat.values, copy=True)
        no_open = _constant(5, ["high", "low", "close"])
        handler = build_hp_candle_pattern_skill()[1]
        hammer = handler(name="cdlhammer", upstream_payload={"panel": flat})
        engulf = handler(name="cdlengulfing", upstream_payload={"panel": flat})
        unknown = handler(name="cdlnotreal", upstream_payload={"panel": flat})
        other = handler(name="sma", upstream_payload={"panel": flat})
        missing_open = handler(name="cdlhammer", upstream_payload={"panel": no_open})
        print("\n[A3 candle] talib:", TA_LIB_AVAILABLE)
        print(" hammer ok:", hammer["ok"], "engulf ok:", engulf["ok"])
        print(" unknown:", unknown["error"]["message"])
        print(" sma:", other["error"]["message"])
        print(" missing open:", missing_open["error"]["message"])
        self.assertEqual(hammer["skill_name"], "qt.ai.hp.candle_pattern")
        self.assertEqual(engulf["skill_name"], "qt.ai.hp.candle_pattern")
        if hammer["ok"]:
            hammer_values = hammer["payload"]["frame"].to_numpy(dtype=float)
            engulf_values = engulf["payload"]["frame"].to_numpy(dtype=float)
            drawn = handler(name="cdlhammer", as_panel=True, upstream_payload={"panel": flat})
            drawn_values = np.asarray(drawn["payload"]["panel"].values, dtype=float)
            print(" hammer:", hammer_values.reshape(-1).tolist())
            print(" as_panel:", list(drawn["payload"]["panel"].htypes), drawn_values.reshape(-1).tolist())
            self.assertNotIn("panel", hammer["payload"])
            self.assertTrue(np.allclose(hammer_values, 0.0))
            self.assertTrue(engulf["ok"])
            self.assertTrue(np.allclose(engulf_values, 0.0))
            self.assertTrue(drawn["ok"])
            self.assertEqual(drawn["skill_name"], "qt.ai.hp.candle_pattern")
            self.assertEqual(list(drawn["payload"]["panel"].htypes), ["cdlhammer"])
            self.assertTrue(np.allclose(drawn_values, 0.0))
        else:
            self.assertEqual(hammer["error"]["code"], "HP_CANDLE_FAILED")
            self.assertIn("cdlhammer", hammer["error"]["message"])
            self.assertNotIn("Traceback", hammer["error"]["message"])
            self.assertFalse(engulf["ok"])
            self.assertIn("cdlengulfing", engulf["error"]["message"])
        self.assertEqual(list(flat.htypes), ["open", "high", "low", "close"])
        self.assertTrue(np.allclose(flat.values, before))
        self.assertFalse(unknown["ok"])
        self.assertEqual(unknown["error"]["code"], "HP_CANDLE_FAILED")
        self.assertIn("cdlnotreal", unknown["error"]["message"])
        self.assertNotIn("Traceback", unknown["error"]["message"])
        self.assertFalse(other["ok"])
        self.assertIn("cdl", other["error"]["message"])
        self.assertNotIn("Traceback", other["error"]["message"])
        self.assertFalse(missing_open["ok"])
        self.assertEqual(missing_open["error"]["code"], "HP_CANDLE_FAILED")
        self.assertIn("open", missing_open["error"]["message"])
        self.assertNotIn("Traceback", missing_open["error"]["message"])

    def test_research_preset_matches_indicator_columns(self) -> None:
        """常数 OHLCV 的预设带上 MACD 三列和 sma_20。最后一根分别是 0 和 10。"""

        panel = _constant(60, ["open", "high", "low", "close", "vol"])
        before = np.array(panel.values, copy=True)
        handler = build_hp_research_preset_skill()[1]
        preset = handler(name="ohlcv_macd_ma", upstream_payload={"panel": panel})
        produced = preset["payload"]["panel"]
        macd_last = {name: _last(produced, name) for name in _MACD_COLUMNS}
        sma_last = _last(produced, "sma_20")
        missing = handler(
            name="ohlcv_macd_ma",
            upstream_payload={"panel": _constant(60, ["open", "high", "low", "close"])},
        )
        unknown = handler(name="not_a_preset", upstream_payload={"panel": panel})
        print("\n[A3 preset] htypes:", list(produced.htypes))
        print(" macd last:", macd_last, "sma_20 last:", sma_last)
        print(" missing vol:", missing["error"]["message"])
        print(" unknown:", unknown["error"]["message"])
        self.assertTrue(preset["ok"])
        self.assertEqual(preset["skill_name"], "qt.ai.hp.research_preset")
        self.assertEqual(tuple(produced.htypes), _PRESET_COLUMNS)
        for name, value in macd_last.items():
            self.assertTrue(_close_or_none(value, 0.0), name)
        self.assertTrue(_close_or_none(sma_last, 10.0))
        self.assertEqual(list(panel.htypes), ["open", "high", "low", "close", "vol"])
        self.assertTrue(np.allclose(panel.values, before))
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error"]["code"], "HP_PRESET_FAILED")
        self.assertIn("vol", missing["error"]["message"])
        self.assertNotIn("Traceback", missing["error"]["message"])
        self.assertFalse(unknown["ok"])
        self.assertEqual(unknown["error"]["code"], "HP_PRESET_FAILED")
        self.assertIn("not_a_preset", unknown["error"]["message"])
        self.assertNotIn("Traceback", unknown["error"]["message"])

    def test_indicator_skills_are_registered(self) -> None:
        """三个指标技能各注册一次。"""

        names = [item.name for item in build_default_registry().list_skills()]
        print("\n[A3 indicator registry]", [name for name in names if name.startswith("qt.ai.hp.")])
        for name in _INDICATOR_SKILLS:
            self.assertEqual(names.count(name), 1)

    def test_executor_passes_the_panel_into_sma(self) -> None:
        """上一步的面板经执行器交给 SMA，2 日均线仍是 [nan, 1.5, 3]。"""

        panel = _panel([[[1.0], [2.0], [4.0]]], ["s1"], _DATES3, ["close"])
        result = self._execute(
            {"panel": panel},
            build_hp_indicator_skill,
            {"func_name": "sma", "kwargs": {"window": 2}},
        )
        column = _flat(result["payload"]["panel"].subpanel(htypes="sma_2"))
        print("\n[A3 executor sma]", column)
        self.assertTrue(result["ok"])
        self.assertEqual(result["skill_name"], "qt.ai.hp.indicator")
        self.assertEqual(column, [None, 1.5, 3.0])

    def _execute(self, payload: dict, builder, extra_inputs: dict) -> dict:
        """一步发出 payload，下一步依赖它。"""

        registry = SkillRegistry()
        registry.register(*_emitter("qt.ai.test.emit", payload))
        registry.register(*builder())
        plan = ToolPlan(
            plan_id="plan_indicator",
            user_query="append an indicator",
            execution_mode="execute",
            steps=[
                ToolStep(step_id="emit", skill_name="qt.ai.test.emit", inputs={}),
                ToolStep(
                    step_id="op",
                    skill_name=builder()[0].name,
                    inputs=dict(extra_inputs),
                    depends_on=["emit"],
                ),
            ],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            executor = PlanExecutor(registry=registry, memory_store=MemoryStore(base_dir=temp_dir))
            finished = executor.execute(plan, confirm=True)
        return finished["execution"]["steps"][-1]["result"]


def _emitter(name: str, payload: dict):
    """测试用出口。闭包持有已知 payload。"""

    metadata = SkillMetadata(
        name=name,
        version="0.1.0",
        summary="Emit one known payload.",
        inputs_schema={},
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly"),
    )

    def handler(**kwargs) -> dict:
        return {"ok": True, "skill_name": name, "payload": payload, "warnings": []}

    return metadata, handler


if __name__ == "__main__":
    unittest.main()
