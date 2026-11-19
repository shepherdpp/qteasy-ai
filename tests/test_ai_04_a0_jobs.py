# coding=utf-8
# ======================================
# File: test_ai_04_a0_jobs.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-01
# Desc:
# 0.4 A0：data.summary / data.export / research.screen
# 的叶子改为原子步骤表。
# ======================================

import json
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from qteasy.history import HistoryPanel
from qteasy_ai.app import build_default_registry
from qteasy_ai.executor import PlanExecutor
from qteasy_ai.memory_store import MemoryStore, _json_safe
from qteasy_ai.planner import Planner
from qteasy_ai.registry import SkillRegistry
from qteasy_ai.skills.data_kline import build_data_kline_skill
from qteasy_ai.skills.hp_describe import build_hp_describe_skill
from qteasy_ai.skills.hp_plot import build_hp_plot_skill
from qteasy_ai.skills.hp_volatility import build_hp_volatility_skill

_SUMMARY = [
    "qt.ai.data.kline",
    "qt.ai.hp.describe",
    "qt.ai.hp.volatility",
]
_EXPORT = ["qt.ai.data.kline", "qt.ai.hp.plot"]
_SCREEN = [
    "qt.ai.research.universe_filter",
    "qt.ai.research.price_predicate",
    "qt.ai.research.project_universe",
]
_SCREEN_ENUM = [
    "qt.ai.research.universe_filter",
    "qt.ai.research.project_universe",
]


def _names(steps) -> list:
    """步骤技能名。"""

    return [step.skill_name for step in steps]


def _ohlcv_frame(closes) -> pd.DataFrame:
    """单标的 OHLCV。收盘价上涨，便于蜡烛图出现红色实体。"""

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


def _ohlcv_panel(closes_by_share: dict) -> HistoryPanel:
    """多标的 OHLCV 面板。values 形状为 (share, time, htype)。"""

    shares = list(closes_by_share)
    n_time = len(next(iter(closes_by_share.values())))
    values = np.zeros((len(shares), n_time, 5), dtype=float)
    for i, share in enumerate(shares):
        close = np.asarray(closes_by_share[share], dtype=float)
        values[i, :, 0] = close - 0.4
        values[i, :, 1] = close + 0.6
        values[i, :, 2] = close - 0.8
        values[i, :, 3] = close
        values[i, :, 4] = 1000.0 + i
    dates = list(pd.date_range("2024-01-01", periods=n_time, freq="D"))
    return HistoryPanel(
        values,
        levels=shares,
        rows=dates,
        columns=["open", "high", "low", "close", "vol"],
    )


def _rolling_annual_vol(closes, window: int) -> float:
    """手算：简单收益的滚动样本标准差，再乘 sqrt(252)。"""

    prices = np.asarray(closes, dtype=float)
    returns = prices[1:] / prices[:-1] - 1.0
    sample = returns[-window:]
    return float(sample.std(ddof=1) * np.sqrt(252.0))


class TestAi04A0Recipes(unittest.TestCase):
    """三个 Job id 不变，叶子是原子步骤表。"""

    def setUp(self) -> None:
        self.planner = Planner(build_default_registry(), env_facts={})

    def test_summary_job_is_kline_vol_describe(self) -> None:
        """波动率金句仍进 data.summary，叶子是取数、结构摘要和波动。"""

        print("\n[TestAi04A0Recipes] summary chain")
        query = "kline summary of 000300.SH"
        plan = self.planner.build_plan(query, mode="plan")
        legacy = self.planner._infer_steps(query=query, q_lower=query.lower())
        names = _names(plan.steps)
        print(" job:", plan.planner_trace.get("intent_job"))
        print(" skills:", names)
        print(" legacy:", _names(legacy))
        print(" depends:", [step.depends_on for step in plan.steps])
        shares = plan.steps[0].inputs.get("shares")
        print(" describe inputs:", plan.steps[1].inputs)
        print(" shares:", shares)
        self.assertEqual(plan.planner_trace.get("intent_job"), "data.summary")
        self.assertEqual(names, _SUMMARY)
        self.assertEqual(_names(legacy), _SUMMARY)
        self.assertEqual(
            shares,
            [{"mention": "000300.SH", "code": "000300.SH", "status": "confirmed"}],
        )
        self.assertEqual(plan.steps[1].depends_on, ["step_1"])
        self.assertEqual(plan.steps[2].depends_on, ["step_1"])
        self.assertEqual(plan.steps[1].inputs.get("view"), "shape")
        self.assertNotIn("qt.ai.data.summary_kline", names)
        self.assertNotIn("plot_type", plan.steps[0].inputs)

    def test_export_job_is_kline_then_plot(self) -> None:
        """导出金句仍进 data.export。收盘曲线也不再传 plot_type。"""

        print("\n[TestAi04A0Recipes] export chain")
        candle = "export kline of 000300.SH to png"
        curve = "export close curve of 000300.SH"
        candle_plan = self.planner.build_plan(candle, mode="plan")
        curve_plan = self.planner.build_plan(curve, mode="plan")
        legacy = self.planner._infer_steps(query="导出 000300.SH 折线", q_lower="导出 000300.SH 折线")
        print(" candle:", _names(candle_plan.steps), candle_plan.steps[0].inputs)
        print(" curve job:", curve_plan.planner_trace.get("intent_job"), _names(curve_plan.steps))
        print(" legacy:", _names(legacy), [step.inputs for step in legacy])
        self.assertEqual(candle_plan.planner_trace.get("intent_job"), "data.export")
        self.assertEqual(_names(candle_plan.steps), _EXPORT)
        self.assertEqual(candle_plan.steps[1].depends_on, ["step_1"])
        self.assertNotIn("plot_type", candle_plan.steps[0].inputs)
        self.assertNotIn("plot_type", candle_plan.steps[1].inputs)
        self.assertEqual(curve_plan.planner_trace.get("intent_job"), "data.export")
        self.assertEqual(_names(curve_plan.steps), _EXPORT)
        self.assertTrue(all("plot_type" not in step.inputs for step in curve_plan.steps))
        self.assertEqual(_names(legacy), _EXPORT)
        self.assertTrue(all("plot_type" not in step.inputs for step in legacy))
        self.assertNotIn("qt.ai.visual.export_kline", _names(candle_plan.steps))

    def test_screen_recipe_stays_three_atoms(self) -> None:
        """筛股金句仍是三原子。遗留推断路径不得再发出 screen_stocks。"""

        print("\n[TestAi04A0Recipes] screen three atoms")
        query = "请搜索过去半年内所有跌幅>20%，且行业属于制造业的股票。"
        plan = self.planner.build_plan(query, mode="plan")
        legacy = self.planner._infer_steps(query=query, q_lower=query.lower())
        bare = "请搜索过去半年行业属于银行的股票"
        bare_plan = self.planner.build_plan(bare, mode="plan")
        bare_legacy = self.planner._infer_steps(query=bare, q_lower=bare.lower())
        print(" skills:", _names(plan.steps))
        print(" legacy:", _names(legacy))
        print(" bare:", _names(bare_plan.steps), _names(bare_legacy))
        self.assertEqual(plan.planner_trace.get("intent_job"), "research.screen")
        self.assertEqual(_names(plan.steps), _SCREEN)
        self.assertEqual(_names(legacy), _SCREEN)
        self.assertNotIn("qt.ai.research.screen_stocks", _names(plan.steps) + _names(legacy))
        self.assertEqual(_names(bare_plan.steps), _SCREEN_ENUM)
        self.assertEqual(_names(bare_legacy), _SCREEN_ENUM)
        self.assertNotIn("qt.ai.research.price_predicate", _names(bare_plan.steps))

    def test_summary_chain_fetches_once_and_drops_panel_on_save(self) -> None:
        """三步执行只取一次数。落盘文件里没有整块面板的文本转储。"""

        print("\n[TestAi04A0Recipes] fetch once and omit panel")
        closes = [10.0, 11.0, 12.0, 13.0, 9.876543]
        calls = {"n": 0}

        def _fake_kline(**kwargs):
            calls["n"] += 1
            print(" get_kline kwargs:", kwargs)
            return _ohlcv_frame(closes)

        registry = SkillRegistry()
        for meta, handler in (
            build_data_kline_skill(get_kline_func=_fake_kline),
            build_hp_volatility_skill(),
            build_hp_describe_skill(),
        ):
            registry.register(meta, handler)
        planner = Planner(registry, env_facts={})
        plan = planner.build_plan("kline summary of 000300.SH", mode="plan")
        plan.execution_mode = "execute"
        with tempfile.TemporaryDirectory() as temp_dir:
            executor = PlanExecutor(registry, memory_store=MemoryStore(base_dir=temp_dir))
            payload = executor.execute(plan, confirm=True)
            text = Path(payload["run_file"]).read_text(encoding="utf-8")
            saved = json.loads(text)
        describe = next(
            row["result"]
            for row in payload["execution"]["steps"]
            if row.get("skill_name") == "qt.ai.hp.describe"
        )
        kline_payload = saved["execution"]["steps"][0]["result"]["payload"]
        print(" calls:", calls["n"])
        print(" describe metrics:", describe.get("metrics"))
        print(" saved panel:", kline_payload.get("panel"))
        self.assertEqual(calls["n"], 1)
        self.assertEqual(describe["metrics"]["n_rows"], 5)
        self.assertEqual(kline_payload.get("panel"), {"omitted": "history_panel"})
        self.assertNotIn("share 0, label", text)


class TestAi04A0Atoms(unittest.TestCase):
    """四个 L1 的数值、行数上限和单页 PNG。"""

    def test_kline_requires_shares_and_returns_ohlcv_panel(self) -> None:
        """缺 shares 是英文错误且不取数。有 shares 时面板列是 OHLCV。"""

        print("\n[TestAi04A0Atoms] kline shares and panel")
        calls = {"n": 0}
        frame = _ohlcv_frame([10.0, 11.0, 12.0])

        def _fake(**kwargs):
            calls["n"] += 1
            self._seen = dict(kwargs)
            return frame.copy()

        _, handler = build_data_kline_skill(get_kline_func=_fake)
        missing = handler()
        print(" missing:", missing["error"])
        print(" calls after missing:", calls["n"])
        self.assertFalse(missing["ok"])
        self.assertEqual(calls["n"], 0)
        self.assertTrue(missing["error"]["message"].isascii())
        self.assertIn("shares", missing["error"]["message"].lower())
        self.assertNotIn("Traceback", missing["error"]["message"])

        result = handler(shares="000300.SH")
        panel = result["payload"]["panel"]
        print(" called:", self._seen)
        print(" htypes:", list(panel.htypes))
        print(" rows:", panel.row_count)
        self.assertTrue(result["ok"])
        self.assertEqual(calls["n"], 1)
        self.assertTrue(self._seen.get("as_panel"))
        self.assertEqual(self._seen.get("freq"), "d")
        self.assertEqual(list(panel.htypes), ["open", "high", "low", "close", "vol"])
        self.assertEqual(panel.row_count, 3)
        close0 = panel["close"].values[0, 0]
        close_value = float(close0.reshape(-1)[0])
        print(" close0:", close_value)
        self.assertAlmostEqual(close_value, 10.0, places=6)

        empty = pd.DataFrame(columns=["open", "high", "low", "close", "vol"])
        _, empty_handler = build_data_kline_skill(get_kline_func=lambda **_: empty.copy())
        failed = empty_handler(shares="000300.SH")
        print(" empty:", failed["error"])
        self.assertFalse(failed["ok"])
        self.assertTrue(failed["error"]["message"].isascii())
        self.assertNotIn("Traceback", failed["error"]["message"])

    def test_volatility_last_matches_hand_calc_and_needs_panel(self) -> None:
        """末值等于手算滚动年化波动率。没有上游面板时英文报错且不取数。"""

        print("\n[TestAi04A0Atoms] volatility")
        closes = [10.0, 11.0, 12.0, 13.0, 14.0]
        expected = _rolling_annual_vol(closes, window=3)
        panel = _ohlcv_panel({"000300.SH": closes})
        calls = {"n": 0}

        def _fetch(**kwargs):
            calls["n"] += 1
            return kwargs

        _, handler = build_hp_volatility_skill()
        missing = handler(upstream_payload={}, get_kline_func=_fetch)
        print(" missing:", missing["error"], "fetch calls:", calls["n"])
        self.assertFalse(missing["ok"])
        self.assertEqual(calls["n"], 0)
        self.assertTrue(missing["error"]["message"].isascii())
        self.assertNotIn("Traceback", missing["error"]["message"])

        result = handler(window=3, upstream_payload={"panel": panel}, get_kline_func=_fetch)
        last = result["metrics"]["last"]
        print(" last:", last, "expected:", expected)
        self.assertTrue(result["ok"])
        self.assertEqual(calls["n"], 0)
        self.assertAlmostEqual(float(last), expected, places=10)
        self.assertNotIn("values", result["payload"])

    def test_describe_shape_and_head_cap(self) -> None:
        """shape 行数正确。head 默认 5 行，请求 100 行时仍不超过 20。"""

        print("\n[TestAi04A0Atoms] describe")
        closes = [float(i) for i in range(25)]
        panel = _ohlcv_panel({"000001.SZ": closes, "000002.SZ": closes})
        _, handler = build_hp_describe_skill()
        shape = handler(view="shape", upstream_payload={"panel": panel})
        head = handler(view="head", upstream_payload={"panel": panel})
        capped = handler(view="head", n=100, upstream_payload={"panel": panel})
        print(" shape:", shape["metrics"])
        print(" head n:", len(head["payload"]["preview_rows"]))
        print(" capped n:", len(capped["payload"]["preview_rows"]))
        blob = json.dumps(_json_safe(capped))
        self.assertTrue(shape["ok"])
        self.assertEqual(shape["metrics"]["n_rows"], 25)
        self.assertEqual(shape["metrics"]["n_shares"], 2)
        self.assertEqual(shape["metrics"]["n_htypes"], 5)
        self.assertEqual(len(head["payload"]["preview_rows"]), 5)
        self.assertEqual(len(capped["payload"]["preview_rows"]), 20)
        self.assertNotIn("values", shape["payload"])
        self.assertNotIn("values", head["payload"])
        self.assertNotIn("24.0", blob)
        self.assertNotIn("share 0, label", blob)

        missing = handler(view="shape", upstream_payload={})
        print(" missing:", missing["error"])
        self.assertFalse(missing["ok"])
        self.assertTrue(missing["error"]["message"].isascii())

    def test_plot_one_png_and_forces_agg(self) -> None:
        """一次一张 PNG，page_count 与页数一致。interactive=True 仍走 Agg。"""

        print("\n[TestAi04A0Atoms] plot page")
        panel = _ohlcv_panel(
            {
                "000001.SZ": [10, 11, 12, 13, 14, 15, 16, 17],
                "000002.SZ": [20, 21, 22, 23, 24, 25, 26, 27],
                "000003.SZ": [30, 31, 32, 33, 34, 35, 36, 37],
            }
        )
        _, handler = build_hp_plot_skill()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "page.png")
            result = handler(
                max_shares_per_figure=2,
                page=1,
                interactive=True,
                output_path=path,
                upstream_payload={"panel": panel},
            )
            import matplotlib

            backend = str(matplotlib.get_backend() or "")
            print(" metrics:", result["metrics"])
            print(" artifacts:", result["artifacts"])
            print(" backend:", backend, "exists:", os.path.isfile(path))
            self.assertTrue(result["ok"])
            self.assertEqual(result["metrics"]["page"], 1)
            self.assertEqual(result["metrics"]["page_count"], 2)
            self.assertEqual(len(result["artifacts"]), 1)
            self.assertTrue(str(result["artifacts"][0]["path"]).endswith(".png"))
            self.assertTrue(os.path.isfile(path))
            self.assertIn("agg", backend.lower())
            self.assertFalse(result["inputs_echo"].get("interactive"))

    def test_json_safe_omits_history_panel_values(self) -> None:
        """HistoryPanel 落盘时不转成带行情数字的字符串。"""

        print("\n[TestAi04A0Atoms] json omit panel")
        panel = _ohlcv_panel({"AAA.SH": [1.0, 3.0, 9.876543]})
        safe = _json_safe({"panel": panel, "keep": 3})
        text = json.dumps(safe)
        print(" safe:", safe)
        self.assertEqual(safe["keep"], 3)
        self.assertNotIn("9.876543", text)
        self.assertNotIn("share 0, label", text)


if __name__ == "__main__":
    unittest.main()
