# coding=utf-8
# ======================================
# File: test_ai_04_a4_portfolio.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-02
# Desc:
# 0.4 A4：组合、累计收益、归一化、alpha/beta、
# 绩效摘要，以及绘图对上游布尔掩码的一页 PNG。
# ======================================

import math
import os
import tempfile
import unittest

import numpy as np
import pandas as pd

from qteasy.history import HistoryPanel
from qteasy_ai.app import build_default_registry
from qteasy_ai.contracts import SkillMetadata, SkillSideEffects, ToolPlan, ToolStep
from qteasy_ai.executor import PlanExecutor
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.registry import SkillRegistry
from qteasy_ai.skills.hp_plot import build_hp_plot_skill
from qteasy_ai.skills.hp_study import (
    build_hp_alpha_beta_skill,
    build_hp_cum_return_skill,
    build_hp_normalize_skill,
    build_hp_performance_skill,
    build_hp_portfolio_skill,
)
from qteasy_ai.skills.hp_volatility import build_hp_volatility_skill

_NEW_SKILLS = [
    "qt.ai.hp.portfolio",
    "qt.ai.hp.cum_return",
    "qt.ai.hp.normalize",
    "qt.ai.hp.alpha_beta",
    "qt.ai.hp.performance",
]
_DATES3 = ["2024-01-02", "2024-01-03", "2024-01-04"]


def _panel(values, shares, dates, columns) -> HistoryPanel:
    """用已知数字做一块面板。values 形状是 (标的, 日期, 列)。"""

    return HistoryPanel(
        values=np.asarray(values, dtype=float),
        levels=list(shares),
        rows=pd.to_datetime(list(dates)),
        columns=list(columns),
    )


def _flat(panel: HistoryPanel) -> list:
    """按标的、日期、列展开。NaN 记成 None。"""

    out = []
    for item in np.asarray(panel.values, dtype=float).reshape(-1):
        out.append(None if not np.isfinite(item) else float(item))
    return out


def _close(left, right) -> bool:
    """两边都是有限数且足够接近。"""

    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-8)


def _rolling_annual_vol(closes, window: int) -> float:
    """手算：简单收益最后一窗的样本标准差，再乘 sqrt(252)。"""

    prices = np.asarray(closes, dtype=float)
    returns = prices[1:] / prices[:-1] - 1.0
    sample = returns[-window:]
    return float(sample.std(ddof=1) * np.sqrt(252.0))


def _hand_alpha_beta() -> tuple:
    """股票 [10, 11, 12, 13] 对基准 [10, 10, 12, 12] 的回归。

    简单收益去掉第一根空值后，beta 是协方差比方差，alpha 再乘 252。
    """

    x_values = np.array([0.0, 0.2, 0.0])
    y_values = np.array([0.1, 1.0 / 11.0, 1.0 / 12.0])
    x_dev = x_values - x_values.mean()
    y_dev = y_values - y_values.mean()
    beta = float(np.sum(x_dev * y_dev) / np.sum(x_dev ** 2))
    alpha = float((y_values.mean() - beta * x_values.mean()) * 252.0)
    return beta, alpha


class TestA4Portfolio(unittest.TestCase):
    """组合与收益摘要的金标准。数值是手工算的。"""

    def test_cum_return_simple_and_bad_method(self) -> None:
        """[10, 11, 12] 的简单累计收益是 [0, 0.1, 0.2]。非法 method 是英文失败。"""

        panel = _panel([[[10.0], [11.0], [12.0]]], ["s1"], _DATES3, ["close"])
        before = np.array(panel.values, copy=True)
        handler = build_hp_cum_return_skill()[1]
        done = handler(upstream_payload={"panel": panel})
        rejected = handler(method="nope", upstream_payload={"panel": panel})
        missing = handler()
        column = _flat(done["payload"]["panel"])
        print("\n[A4 cum_return]", column, list(done["payload"]["panel"].htypes))
        print(" bad method:", rejected["error"]["code"], rejected["error"]["message"])
        print(" missing:", missing["error"]["code"], missing["error"]["message"])
        self.assertTrue(done["ok"])
        self.assertEqual(done["skill_name"], "qt.ai.hp.cum_return")
        self.assertEqual(list(done["payload"]["panel"].htypes), ["cumret_close"])
        self.assertEqual(len(column), 3)
        self.assertTrue(_close(column[0], 0.0))
        self.assertTrue(_close(column[1], 0.1))
        self.assertTrue(_close(column[2], 0.2))
        self.assertEqual(list(panel.htypes), ["close"])
        self.assertTrue(np.allclose(panel.values, before))
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["error"]["code"], "HP_CUM_RETURN_FAILED")
        self.assertIn("nope", rejected["error"]["message"])
        self.assertTrue(rejected["error"]["message"].isascii())
        self.assertNotIn("Traceback", rejected["error"]["message"])
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error"]["code"], "HP_PANEL_MISSING")

    def test_normalize_base_and_out_of_range(self) -> None:
        """[10, 20, 40] 以第一根为基准得到 [1, 2, 4]。越界下标是英文失败。"""

        panel = _panel([[[10.0], [20.0], [40.0]]], ["s1"], _DATES3, ["close"])
        before = np.array(panel.values, copy=True)
        handler = build_hp_normalize_skill()[1]
        done = handler(upstream_payload={"panel": panel})
        rejected = handler(base_index=3, upstream_payload={"panel": panel})
        column = _flat(done["payload"]["panel"])
        print("\n[A4 normalize]", column, list(done["payload"]["panel"].htypes))
        print(" base_index:", rejected["error"]["code"], rejected["error"]["message"])
        self.assertTrue(done["ok"])
        self.assertEqual(done["skill_name"], "qt.ai.hp.normalize")
        self.assertEqual(list(done["payload"]["panel"].htypes), ["norm_close"])
        self.assertEqual(len(column), 3)
        self.assertTrue(_close(column[0], 1.0))
        self.assertTrue(_close(column[1], 2.0))
        self.assertTrue(_close(column[2], 4.0))
        self.assertTrue(np.allclose(panel.values, before))
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["error"]["code"], "HP_NORMALIZE_FAILED")
        self.assertIn("base_index", rejected["error"]["message"])
        self.assertTrue(rejected["error"]["message"].isascii())
        self.assertNotIn("Traceback", rejected["error"]["message"])

    def test_portfolio_equal_weighted_and_benchmark(self) -> None:
        """等权是 [20, 15]，权重 [1, 3] 是 [25, 16.5]。基准 B 不进等权。"""

        panel = _panel(
            [[[10.0], [12.0]], [[30.0], [18.0]]],
            ["A", "B"],
            ["2024-01-02", "2024-01-03"],
            ["close"],
        )
        before = np.array(panel.values, copy=True)
        handler = build_hp_portfolio_skill()[1]
        equal = handler(upstream_payload={"panel": panel})
        weighted = handler(mode="weighted", weights=[1, 3], upstream_payload={"panel": panel})
        tagged = handler(
            benchmark="B",
            benchmark_output="tag_along",
            upstream_payload={"panel": panel},
        )
        excess = handler(
            benchmark="B",
            benchmark_output="excess_only",
            upstream_payload={"panel": panel},
        )
        print("\n[A4 portfolio] equal:", _flat(equal["payload"]["panel"]), equal["payload"]["panel"].shares)
        print(" weighted:", _flat(weighted["payload"]["panel"]))
        print(" tag:", tagged["payload"]["panel"].shares, _flat(tagged["payload"]["panel"]))
        print(" excess:", excess["payload"]["panel"].shares, excess["payload"]["panel"].htypes, _flat(excess["payload"]["panel"]))
        self.assertTrue(equal["ok"])
        self.assertEqual(equal["skill_name"], "qt.ai.hp.portfolio")
        self.assertEqual(list(equal["payload"]["panel"].shares), ["PORTFOLIO"])
        self.assertEqual(_flat(equal["payload"]["panel"]), [20.0, 15.0])
        self.assertTrue(weighted["ok"])
        self.assertEqual(_flat(weighted["payload"]["panel"]), [25.0, 16.5])
        self.assertTrue(tagged["ok"])
        self.assertEqual(list(tagged["payload"]["panel"].shares), ["PORTFOLIO", "B"])
        self.assertEqual(_flat(tagged["payload"]["panel"]), [10.0, 12.0, 30.0, 18.0])
        self.assertTrue(excess["ok"])
        self.assertEqual(list(excess["payload"]["panel"].shares), ["PORTFOLIO"])
        self.assertEqual(list(excess["payload"]["panel"].htypes), ["excess_close"])
        self.assertEqual(_flat(excess["payload"]["panel"]), [-20.0, -6.0])
        self.assertTrue(np.allclose(panel.values, before))

    def test_portfolio_mask_drops_a_member(self) -> None:
        """B 的第二根为假时，等权第二根只剩 A 的 12。"""

        panel = _panel(
            [[[10.0], [12.0]], [[30.0], [18.0]]],
            ["A", "B"],
            ["2024-01-02", "2024-01-03"],
            ["close"],
        )
        mask = np.array([[True, True], [True, False]])
        handler = build_hp_portfolio_skill()[1]
        done = handler(mask=mask, upstream_payload={"panel": panel})
        print("\n[A4 portfolio mask]", _flat(done["payload"]["panel"]))
        self.assertTrue(done["ok"])
        self.assertEqual(_flat(done["payload"]["panel"]), [20.0, 12.0])

    def test_portfolio_english_failures(self) -> None:
        """未知基准、加权缺权重、等权却给了权重、缺面板，都是英文。"""

        panel = _panel([[[10.0], [12.0]]], ["A"], ["2024-01-02", "2024-01-03"], ["close"])
        handler = build_hp_portfolio_skill()[1]
        unknown = handler(benchmark="NOPE", upstream_payload={"panel": panel})
        bare = handler(mode="weighted", upstream_payload={"panel": panel})
        extra = handler(mode="equal", weights=[1.0], upstream_payload={"panel": panel})
        missing = handler()
        print("\n[A4 portfolio errors]")
        print(" benchmark:", unknown["error"]["message"])
        print(" weights:", bare["error"]["message"])
        print(" equal+weights:", extra["error"]["message"])
        print(" panel:", missing["error"]["code"], missing["error"]["message"])
        self.assertFalse(unknown["ok"])
        self.assertEqual(unknown["error"]["code"], "HP_PORTFOLIO_FAILED")
        self.assertIn("NOPE", unknown["error"]["message"])
        self.assertNotIn("Traceback", unknown["error"]["message"])
        self.assertFalse(bare["ok"])
        self.assertIn("weighted", bare["error"]["message"])
        self.assertTrue(bare["error"]["message"].isascii())
        self.assertNotIn("Traceback", bare["error"]["message"])
        self.assertFalse(extra["ok"])
        self.assertIn("weights", extra["error"]["message"])
        self.assertNotIn("Traceback", extra["error"]["message"])
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error"]["code"], "HP_PANEL_MISSING")

    def test_alpha_beta_matches_hand_regression(self) -> None:
        """alpha 与 beta 用手写协方差公式，年化乘 252。缺基准是英文失败。"""

        dates = pd.date_range("2024-01-02", periods=4, freq="D")
        panel = _panel([[[10.0], [11.0], [12.0], [13.0]]], ["s1"], dates, ["close"])
        bench = pd.Series([10.0, 10.0, 12.0, 12.0], index=pd.DatetimeIndex(dates), name="bench")
        beta, alpha = _hand_alpha_beta()
        handler = build_hp_alpha_beta_skill()[1]
        done = handler(benchmark=bench, upstream_payload={"panel": panel})
        via_frame = handler(
            upstream_payloads=[
                {"panel": panel},
                {"frame": bench.to_frame("px")},
            ],
        )
        missing = handler(upstream_payload={"panel": panel})
        frame = done["payload"]["frame"]
        other = via_frame["payload"]["frame"]
        print("\n[A4 alpha_beta] hand beta:", beta, "alpha:", alpha)
        print(" frame:", frame.to_dict(orient="index"))
        print(" via frame beta:", float(other.loc["s1", "beta"]))
        print(" missing:", missing["error"]["code"], missing["error"]["message"])
        self.assertTrue(done["ok"])
        self.assertEqual(done["skill_name"], "qt.ai.hp.alpha_beta")
        self.assertIs(done["payload"]["panel"], panel)
        self.assertEqual(list(frame.columns), ["alpha", "beta", "r2", "n_obs"])
        self.assertEqual(int(frame.loc["s1", "n_obs"]), 3)
        self.assertTrue(_close(frame.loc["s1", "beta"], beta))
        self.assertTrue(_close(frame.loc["s1", "alpha"], alpha))
        self.assertTrue(via_frame["ok"])
        self.assertTrue(_close(other.loc["s1", "beta"], beta))
        self.assertTrue(_close(other.loc["s1", "alpha"], alpha))
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error"]["code"], "HP_ALPHA_BETA_FAILED")
        self.assertIn("benchmark", missing["error"]["message"])
        self.assertTrue(missing["error"]["message"].isascii())
        self.assertNotIn("Traceback", missing["error"]["message"])

    def test_performance_cagr_from_cumret(self) -> None:
        """累计收益 [0, 0.1, 0.21] 的末值是 0.21，CAGR 用 2 期和 252。"""

        panel = _panel([[[0.0], [0.1], [0.21]]], ["s1"], _DATES3, ["cumret_close"])
        expected = (1.21 ** (252.0 / 2.0)) - 1.0
        handler = build_hp_performance_skill()[1]
        done = handler(upstream_payload={"panel": panel})
        frame = done["payload"]["frame"]
        print("\n[A4 performance]", frame.to_dict(orient="index"))
        print(" expected cagr:", expected)
        self.assertTrue(done["ok"])
        self.assertEqual(done["skill_name"], "qt.ai.hp.performance")
        self.assertIs(done["payload"]["panel"], panel)
        self.assertEqual(list(frame.columns), ["cum_return_end", "cagr", "n_periods"])
        self.assertTrue(_close(frame.loc["s1", "cum_return_end"], 0.21))
        self.assertEqual(int(frame.loc["s1", "n_periods"]), 2)
        self.assertTrue(math.isclose(float(frame.loc["s1", "cagr"]), expected, rel_tol=1e-12, abs_tol=0.0))

    def test_performance_english_failures(self) -> None:
        """多列不指明、期数非正、不足两个点、累计收益不高于 -1，都是英文。"""

        two = _panel([[[0.0, 1.0], [0.1, 1.1]]], ["s1"], ["2024-01-02", "2024-01-03"], ["cumret_close", "other"])
        short = _panel([[[0.1]]], ["s1"], ["2024-01-02"], ["cumret_close"])
        wiped = _panel([[[-0.2], [-1.0]]], ["s1"], ["2024-01-02", "2024-01-03"], ["cumret_close"])
        handler = build_hp_performance_skill()[1]
        ambiguous = handler(upstream_payload={"panel": two})
        bad_periods = handler(periods_per_year=0, upstream_payload={"panel": short})
        too_short = handler(upstream_payload={"panel": short})
        ruined = handler(upstream_payload={"panel": wiped})
        print("\n[A4 performance errors]")
        print(" htype:", ambiguous["error"]["message"])
        print(" periods:", bad_periods["error"]["message"])
        print(" short:", too_short["error"]["message"])
        print(" end:", ruined["error"]["message"])
        self.assertFalse(ambiguous["ok"])
        self.assertEqual(ambiguous["error"]["code"], "HP_PERFORMANCE_FAILED")
        self.assertIn("htype", ambiguous["error"]["message"])
        self.assertNotIn("Traceback", ambiguous["error"]["message"])
        self.assertFalse(bad_periods["ok"])
        self.assertIn("periods_per_year", bad_periods["error"]["message"])
        self.assertFalse(too_short["ok"])
        self.assertIn("two finite", too_short["error"]["message"])
        self.assertFalse(ruined["ok"])
        self.assertIn("-1", ruined["error"]["message"])
        self.assertTrue(ruined["error"]["message"].isascii())

    def test_volatility_last_still_matches_hand_calc(self) -> None:
        """已有波动率原子的末值仍等于手算，注册名不变。"""

        closes = [10.0, 11.0, 12.0, 13.0, 14.0]
        expected = _rolling_annual_vol(closes, window=3)
        dates = pd.date_range("2024-01-01", periods=len(closes), freq="D")
        panel = _panel([[[item] for item in closes]], ["s1"], dates, ["close"])
        metadata, handler = build_hp_volatility_skill()
        done = handler(window=3, upstream_payload={"panel": panel})
        print("\n[A4 volatility] last:", done["metrics"]["last"], "expected:", expected)
        self.assertEqual(metadata.name, "qt.ai.hp.volatility")
        self.assertTrue(done["ok"])
        self.assertEqual(done["skill_name"], "qt.ai.hp.volatility")
        self.assertTrue(_close(done["metrics"]["last"], expected))

    def test_plot_highlight_max_and_upstream_mask(self) -> None:
        """max 优先于掩码。末维为 1 的三维掩码能画一张图；末维不是 1 则英文失败。"""

        closes = [10.0, 11.0, 12.0, 13.0]
        dates = pd.date_range("2024-01-01", periods=len(closes), freq="D")
        values = np.zeros((1, len(closes), 5), dtype=float)
        close = np.asarray(closes, dtype=float)
        values[0, :, 0] = close - 0.4
        values[0, :, 1] = close + 0.6
        values[0, :, 2] = close - 0.8
        values[0, :, 3] = close
        values[0, :, 4] = 10.0
        panel = _panel(values, ["s1"], dates, ["open", "high", "low", "close", "vol"])
        good = np.zeros((1, len(closes), 1), dtype=bool)
        good[0, 2, 0] = True
        bad = np.zeros((1, len(closes), 2), dtype=bool)
        handler = build_hp_plot_skill()[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            max_path = os.path.join(temp_dir, "max.png")
            mask_path = os.path.join(temp_dir, "mask.png")
            bad_path = os.path.join(temp_dir, "bad.png")
            page_path = os.path.join(temp_dir, "page.png")
            highlighted = handler(
                highlight="max",
                interactive=True,
                output_path=max_path,
                upstream_payload={"panel": panel, "mask": bad},
            )
            masked = handler(
                output_path=mask_path,
                upstream_payload={"panel": panel, "mask": good},
            )
            rejected = handler(
                output_path=bad_path,
                upstream_payload={"panel": panel, "mask": bad},
            )
            overflow = handler(
                page=2,
                output_path=page_path,
                upstream_payload={"panel": panel},
            )
            print("\n[A4 plot] max echo:", highlighted["inputs_echo"]["highlight"], highlighted["inputs_echo"]["interactive"])
            print(" mask ok:", masked["ok"], "artifacts:", masked.get("artifacts"))
            print(" bad:", rejected["error"]["code"], rejected["error"]["message"])
            print(" page:", overflow["error"]["code"], overflow["error"]["message"])
            self.assertTrue(highlighted["ok"])
            self.assertEqual(highlighted["inputs_echo"]["highlight"], "max")
            self.assertFalse(highlighted["inputs_echo"]["interactive"])
            self.assertEqual(len(highlighted["artifacts"]), 1)
            self.assertTrue(os.path.isfile(max_path))
            self.assertTrue(masked["ok"])
            self.assertEqual(masked["inputs_echo"]["highlight"], "upstream_mask")
            self.assertEqual(masked["metrics"]["page_count"], 1)
            self.assertEqual(len(masked["artifacts"]), 1)
            self.assertTrue(os.path.isfile(mask_path))
            self.assertFalse(rejected["ok"])
            self.assertEqual(rejected["error"]["code"], "HP_PLOT_FAILED")
            self.assertTrue(rejected["error"]["message"].isascii())
            self.assertNotIn("Traceback", rejected["error"]["message"])
            self.assertFalse(os.path.isfile(bad_path))
            self.assertFalse(overflow["ok"])
            self.assertEqual(overflow["error"]["code"], "HP_PLOT_FAILED")
            self.assertIn("page", overflow["error"]["message"])
            self.assertNotIn("Traceback", overflow["error"]["message"])
            self.assertFalse(os.path.isfile(page_path))

    def test_new_skills_are_registered_once(self) -> None:
        """五个新原子各注册一次。波动率仍在。"""

        names = [item.name for item in build_default_registry().list_skills()]
        print("\n[A4 registry]", [name for name in names if name.startswith("qt.ai.hp.")])
        for name in _NEW_SKILLS:
            self.assertEqual(names.count(name), 1)
        self.assertEqual(names.count("qt.ai.hp.volatility"), 1)

    def test_executor_passes_mask_into_portfolio(self) -> None:
        """执行器把上游掩码交给组合。B 的第二根被排除后，第二根仍是 12。"""

        panel = _panel(
            [[[10.0], [12.0]], [[30.0], [18.0]]],
            ["A", "B"],
            ["2024-01-02", "2024-01-03"],
            ["close"],
        )
        mask = np.array([[True, True], [True, False]])
        result = self._execute({"panel": panel, "mask": mask}, build_hp_portfolio_skill, {})
        print("\n[A4 executor portfolio]", _flat(result["payload"]["panel"]))
        self.assertTrue(result["ok"])
        self.assertEqual(result["skill_name"], "qt.ai.hp.portfolio")
        self.assertEqual(_flat(result["payload"]["panel"]), [20.0, 12.0])

    def _execute(self, payload: dict, builder, extra_inputs: dict) -> dict:
        """一步发出 payload，下一步依赖它。"""

        registry = SkillRegistry()
        registry.register(*_emitter("qt.ai.test.emit", payload))
        registry.register(*builder())
        plan = ToolPlan(
            plan_id="plan_portfolio",
            user_query="build a portfolio",
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
