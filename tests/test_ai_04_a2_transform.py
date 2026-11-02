# coding=utf-8
# ======================================
# File: test_ai_04_a2_transform.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-02
# Desc:
# 0.4 A2：收益率、位移、排名、滚动、汇总、相关、
# 比较、掩码与列表达式。成功看手算数值，失败看英文。
# ======================================

import math
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
from qteasy_ai.skills.hp_transform import (
    build_hp_agg_skill,
    build_hp_combine_mask_skill,
    build_hp_compare_skill,
    build_hp_corr_skill,
    build_hp_diff_skill,
    build_hp_expr_skill,
    build_hp_pct_change_skill,
    build_hp_rank_skill,
    build_hp_returns_skill,
    build_hp_rolling_skill,
    build_hp_shift_skill,
    build_hp_where_skill,
    build_hp_zscore_skill,
)

_TRANSFORM_SKILLS = [
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
]

_DATES3 = ["2024-01-01", "2024-01-02", "2024-01-03"]
_SQRT_HALF = math.sqrt(0.5)
_INV_SQRT2 = 1.0 / math.sqrt(2.0)


def _panel(values, shares, dates, columns) -> HistoryPanel:
    """用已知数字做一块面板。values 形状是 (标的, 日期, 列)。"""

    return HistoryPanel(
        values=np.asarray(values, dtype=float),
        levels=list(shares),
        rows=pd.to_datetime(list(dates)),
        columns=list(columns),
    )


def _flat(panel: HistoryPanel) -> list:
    """按标的、日期展开。NaN 记成 None。"""

    out = []
    for item in np.asarray(panel.values, dtype=float).reshape(-1):
        out.append(None if not np.isfinite(item) else float(item))
    return out


def _bools(mask) -> list:
    """掩码按 C 顺序展开成 Python bool。"""

    return [bool(item) for item in np.asarray(mask, dtype=bool).reshape(-1)]


def _close_or_none(left, right) -> bool:
    """两边同为 None，或都是有限数且足够接近。"""

    if left is None or right is None:
        return left is None and right is None
    return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-9)


class TestA2Transform(unittest.TestCase):
    """变换与比较原子的金标准。数值都是手工算的。"""

    def test_returns_simple_log_and_missing_column(self) -> None:
        """[1, 2, 4] 的简单收益是 [nan, 1, 1]；对数收益第二根是 log(2)。缺列用英文拒绝。"""

        panel = _panel([[[1.0], [2.0], [4.0]]], ["s1"], _DATES3, ["close"])
        before = np.array(panel.values, copy=True)
        handler = build_hp_returns_skill()[1]
        simple = handler(upstream_payload={"panel": panel})
        as_panel = handler(as_panel=True, upstream_payload={"panel": panel})
        logged = handler(method="log", upstream_payload={"panel": panel})
        rejected = handler(price_htype="missing", upstream_payload={"panel": panel})
        simple_col = [None if not np.isfinite(item) else float(item) for item in simple["payload"]["frame"]["s1"]]
        log_col = [None if not np.isfinite(item) else float(item) for item in logged["payload"]["frame"]["s1"]]
        panel_out = as_panel["payload"]["panel"]
        print("\n[A2 returns] simple:", simple_col)
        print(" as_panel:", list(panel_out.htypes), _flat(panel_out.subpanel(htypes="ret_close")))
        print(" log:", log_col)
        print(" missing:", rejected["error"]["code"], rejected["error"]["message"])
        self.assertTrue(simple["ok"])
        self.assertNotIn("panel", simple["payload"])
        self.assertEqual(simple_col, [None, 1.0, 1.0])
        self.assertTrue(as_panel["ok"])
        self.assertEqual(list(panel_out.htypes), ["ret_close"])
        self.assertEqual(_flat(panel_out), [None, 1.0, 1.0])
        self.assertTrue(np.allclose(panel.values, before))
        self.assertTrue(_close_or_none(log_col[0], None))
        self.assertTrue(math.isclose(log_col[1], math.log(2.0)))
        self.assertTrue(math.isclose(log_col[2], math.log(2.0)))
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["error"]["code"], "HP_TRANSFORM_FAILED")
        self.assertIn("missing", rejected["error"]["message"])
        self.assertNotIn("Traceback", rejected["error"]["message"])

    def test_shift_diff_and_pct_change(self) -> None:
        """位移 [nan, 1, 2]；填 0 变成 [0, 1, 2]。差分 [nan, 2, 3]。涨跌幅 [nan, 1, 1]。"""

        prices = _panel([[[1.0], [2.0], [4.0]]], ["s1"], _DATES3, ["close"])
        steps = _panel([[[1.0], [3.0], [6.0]]], ["s1"], _DATES3, ["close"])
        shifted = build_hp_shift_skill()[1](upstream_payload={"panel": prices})
        filled = build_hp_shift_skill()[1](fill_value=0, upstream_payload={"panel": prices})
        zero = build_hp_shift_skill()[1](periods=0, upstream_payload={"panel": prices})
        diffed = build_hp_diff_skill()[1](upstream_payload={"panel": steps})
        changed = build_hp_pct_change_skill()[1](upstream_payload={"panel": prices})
        unknown = build_hp_pct_change_skill()[1](htypes="nope", upstream_payload={"panel": prices})
        print("\n[A2 shift] default:", _flat(shifted["payload"]["panel"]))
        print(" fill 0:", _flat(filled["payload"]["panel"]))
        print(" periods 0:", zero["error"]["message"])
        print(" diff:", _flat(diffed["payload"]["panel"]))
        print(" pct:", _flat(changed["payload"]["panel"]))
        print(" unknown:", unknown["error"]["message"])
        self.assertEqual(_flat(shifted["payload"]["panel"]), [None, 1.0, 2.0])
        self.assertEqual(_flat(filled["payload"]["panel"]), [0.0, 1.0, 2.0])
        self.assertEqual(_flat(prices), [1.0, 2.0, 4.0])
        self.assertFalse(zero["ok"])
        self.assertEqual(zero["error"]["code"], "HP_TRANSFORM_FAILED")
        self.assertIn("non-zero", zero["error"]["message"])
        self.assertNotIn("Traceback", zero["error"]["message"])
        self.assertEqual(_flat(diffed["payload"]["panel"]), [None, 2.0, 3.0])
        self.assertEqual(_flat(changed["payload"]["panel"]), [None, 1.0, 1.0])
        self.assertFalse(unknown["ok"])
        self.assertIn("nope", unknown["error"]["message"])
        self.assertNotIn("Traceback", unknown["error"]["message"])

    def test_rank_average_and_bad_axis(self) -> None:
        """两日排名 s1 是 [1, 2]，s2 是 [2, 1]。axis 不是 share 时英文失败。"""

        panel = _panel(
            [[[1.0], [2.0]], [[2.0], [1.0]]],
            ["s1", "s2"],
            ["2024-01-01", "2024-01-02"],
            ["close"],
        )
        ranked = build_hp_rank_skill()[1](by="close", upstream_payload={"panel": panel})
        rejected = build_hp_rank_skill()[1](by="close", axis="time", upstream_payload={"panel": panel})
        column = ranked["payload"]["panel"].subpanel(htypes="rank_close")
        print("\n[A2 rank] rank_close:", _flat(column))
        print(" bad axis:", rejected["error"]["message"])
        self.assertTrue(ranked["ok"])
        self.assertEqual(_flat(column), [1.0, 2.0, 2.0, 1.0])
        self.assertEqual(_flat(panel), [1.0, 2.0, 2.0, 1.0])
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["error"]["code"], "HP_TRANSFORM_FAILED")
        self.assertIn("share", rejected["error"]["message"])
        self.assertNotIn("Traceback", rejected["error"]["message"])

    def test_zscore_cs_and_ts(self) -> None:
        """截面 1 与 3 的 z 是 ∓1/sqrt(2)。cs 不能带 window。时序第二根是 (2-1.5)/sqrt(0.5)。"""

        cross = _panel([[[1.0]], [[3.0]]], ["s1", "s2"], ["2024-01-01"], ["close"])
        series = _panel([[[1.0], [2.0], [3.0]]], ["s1"], _DATES3, ["close"])
        cs = build_hp_zscore_skill()[1](by="close", upstream_payload={"panel": cross})
        bad_window = build_hp_zscore_skill()[1](by="close", method="cs", window=2, upstream_payload={"panel": cross})
        ts = build_hp_zscore_skill()[1](by="close", method="ts", window=2, upstream_payload={"panel": series})
        cs_col = _flat(cs["payload"]["panel"].subpanel(htypes="cs_z_close"))
        ts_col = _flat(ts["payload"]["panel"].subpanel(htypes="ts_z_close_2"))
        print("\n[A2 zscore] cs:", cs_col)
        print(" cs with window:", bad_window["error"]["message"])
        print(" ts:", ts_col)
        self.assertTrue(cs["ok"])
        self.assertTrue(math.isclose(cs_col[0], -_INV_SQRT2))
        self.assertTrue(math.isclose(cs_col[1], _INV_SQRT2))
        self.assertFalse(bad_window["ok"])
        self.assertEqual(bad_window["error"]["code"], "HP_TRANSFORM_FAILED")
        self.assertIn("window", bad_window["error"]["message"])
        self.assertNotIn("Traceback", bad_window["error"]["message"])
        self.assertTrue(ts["ok"])
        self.assertIsNone(ts_col[0])
        self.assertTrue(math.isclose(ts_col[1], (2.0 - 1.5) / _SQRT_HALF))
        self.assertTrue(math.isclose(ts_col[2], (3.0 - 2.5) / _SQRT_HALF))

    def test_rolling_mean_std_and_reject_var(self) -> None:
        """窗口 2 的均值是 [nan, 1.5, 2.5]，标准差第二根是 sqrt(0.5)。var 不在白名单。"""

        panel = _panel([[[1.0], [2.0], [3.0]]], ["s1"], _DATES3, ["close"])
        handler = build_hp_rolling_skill()[1]
        mean = handler(window=2, stat="mean", upstream_payload={"panel": panel})
        std = handler(window=2, stat="std", upstream_payload={"panel": panel})
        rejected = handler(window=2, stat="var", upstream_payload={"panel": panel})
        print("\n[A2 rolling] mean:", _flat(mean["payload"]["panel"]))
        print(" std:", _flat(std["payload"]["panel"]))
        print(" var:", rejected["error"]["message"])
        self.assertEqual(_flat(mean["payload"]["panel"]), [None, 1.5, 2.5])
        std_col = _flat(std["payload"]["panel"])
        self.assertIsNone(std_col[0])
        self.assertTrue(math.isclose(std_col[1], _SQRT_HALF))
        self.assertTrue(math.isclose(std_col[2], _SQRT_HALF))
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["error"]["code"], "HP_TRANSFORM_FAILED")
        self.assertNotIn("AttributeError", rejected["error"]["message"])
        self.assertNotIn("Traceback", rejected["error"]["message"])

    def test_agg_mean_std_quantile(self) -> None:
        """[1, 2, 3] 的均值 2、标准差 1、中位数 2。按列汇总时索引是列名。q=1.5 英文失败。"""

        panel = _panel([[[1.0], [2.0], [3.0]]], ["s1"], _DATES3, ["close"])
        handler = build_hp_agg_skill()[1]
        mean = handler(stat="mean", upstream_payload={"panel": panel})
        std = handler(stat="std", upstream_payload={"panel": panel})
        quantile = handler(stat="quantile", q=0.5, upstream_payload={"panel": panel})
        by_htype = handler(stat="mean", by="htype", upstream_payload={"panel": panel})
        rejected = handler(stat="quantile", q=1.5, upstream_payload={"panel": panel})
        print("\n[A2 agg] mean:", float(mean["payload"]["frame"].loc["s1", "close"]))
        print(" std:", float(std["payload"]["frame"].loc["s1", "close"]))
        print(" q:", float(quantile["payload"]["frame"].loc["s1", "close"]))
        print(" by htype index:", list(by_htype["payload"]["frame"].index))
        print(" q=1.5:", rejected["error"]["message"])
        self.assertTrue(math.isclose(float(mean["payload"]["frame"].loc["s1", "close"]), 2.0))
        self.assertTrue(math.isclose(float(std["payload"]["frame"].loc["s1", "close"]), 1.0))
        self.assertTrue(math.isclose(float(quantile["payload"]["frame"].loc["s1", "close"]), 2.0))
        self.assertEqual(list(by_htype["payload"]["frame"].index), ["close"])
        self.assertTrue(math.isclose(float(by_htype["payload"]["frame"].loc["close", "s1"]), 2.0))
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["error"]["code"], "HP_TRANSFORM_FAILED")
        self.assertIn("1.5", rejected["error"]["message"])
        self.assertNotIn("Traceback", rejected["error"]["message"])

    def test_corr_pearson_spearman_and_bad_method(self) -> None:
        """a=[1,2,3]、b=[2,4,6] 的 Pearson 与 Spearman 都是 1。kendall 英文失败。"""

        panel = _panel(
            [[[1.0], [2.0], [3.0]], [[2.0], [4.0], [6.0]]],
            ["a", "b"],
            _DATES3,
            ["close"],
        )
        handler = build_hp_corr_skill()[1]
        pearson = handler(htype="close", upstream_payload={"panel": panel})
        spearman = handler(htype="close", method="spearman", upstream_payload={"panel": panel})
        rejected = handler(htype="close", method="kendall", upstream_payload={"panel": panel})
        print("\n[A2 corr] pearson a,b:", float(pearson["payload"]["frame"].loc["a", "b"]))
        print(" spearman a,b:", float(spearman["payload"]["frame"].loc["a", "b"]))
        print(" kendall:", rejected["error"]["message"])
        self.assertTrue(math.isclose(float(pearson["payload"]["frame"].loc["a", "b"]), 1.0))
        self.assertTrue(math.isclose(float(spearman["payload"]["frame"].loc["a", "b"]), 1.0))
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["error"]["code"], "HP_TRANSFORM_FAILED")
        self.assertIn("kendall", rejected["error"]["message"])
        self.assertNotIn("Traceback", rejected["error"]["message"])

    def test_compare_scalar_column_and_both(self) -> None:
        """close > 3 是 [假, 真, 假]。close > open 是 [假, 真]。两个右端同时给则英文失败。"""

        scalar_panel = _panel([[[1.0], [5.0], [3.0]]], ["s1"], _DATES3, ["close"])
        pair = _panel([[[1.0, 2.0], [5.0, 4.0]]], ["s1"], ["2024-01-01", "2024-01-02"], ["close", "open"])
        handler = build_hp_compare_skill()[1]
        scalar = handler(htype="close", op="gt", value=3, upstream_payload={"panel": scalar_panel})
        columns = handler(htype="close", op="gt", other_htype="open", upstream_payload={"panel": pair})
        both = handler(
            htype="close",
            op="gt",
            value=3,
            other_htype="open",
            upstream_payload={"panel": pair},
        )
        print("\n[A2 compare] scalar:", _bools(scalar["payload"]["mask"]))
        print(" columns:", _bools(columns["payload"]["mask"]))
        print(" both:", both["error"]["code"], both["error"]["message"])
        self.assertEqual(_bools(scalar["payload"]["mask"]), [False, True, False])
        self.assertEqual(list(scalar["payload"]["panel"].htypes), ["close"])
        self.assertEqual(_bools(columns["payload"]["mask"]), [False, True])
        self.assertFalse(both["ok"])
        self.assertEqual(both["error"]["code"], "HP_COMPARE_FAILED")
        self.assertNotIn("Traceback", both["error"]["message"])
        self.assertTrue(both["error"]["message"].isascii())

    def test_where_broadcasts_and_rejects_text(self) -> None:
        """(1, 3) 掩码广播到两列，只有中间那天为真。字符串掩码英文拒绝，不调用库。"""

        panel = _panel(
            [[[1.0, 8.0], [2.0, 9.0], [3.0, 10.0]]],
            ["s1"],
            _DATES3,
            ["close", "open"],
        )
        mask = np.array([[False, True, False]])
        result = self._execute(
            [{"panel": panel}, {"mask": mask}],
            build_hp_where_skill,
            {},
        )
        out = result["payload"]["mask"]
        text = build_hp_where_skill()[1](upstream_payload={"panel": panel, "mask": "close > 1"})
        function = build_hp_where_skill()[1](upstream_payload={"panel": panel, "mask": lambda item: item})
        print("\n[A2 where] shape:", out.shape, "values:", _bools(out))
        print(" text:", text["error"]["code"], text["error"]["message"])
        print(" function:", function["error"]["code"], function["error"]["message"])
        self.assertTrue(result["ok"])
        self.assertEqual(out.shape, panel.shape)
        self.assertEqual(_bools(out), [False, False, True, True, False, False])
        self.assertEqual(_flat(panel), [1.0, 8.0, 2.0, 9.0, 3.0, 10.0])
        self.assertFalse(text["ok"])
        self.assertEqual(text["error"]["code"], "HP_WHERE_REJECTED")
        self.assertNotIn("Traceback", text["error"]["message"])
        self.assertTrue(text["error"]["message"].isascii())
        self.assertFalse(function["ok"])
        self.assertEqual(function["error"]["code"], "HP_WHERE_REJECTED")

    def test_combine_mask_and_or_not(self) -> None:
        """与是 [真, 假]，或是 [真, 真]，非是 [假, 真]。xor 与形状不同都英文失败。"""

        left = np.array([True, False])
        right = np.array([True, True])
        both = self._execute([{"mask": left}, {"mask": right}], build_hp_combine_mask_skill, {"op": "and"})
        either = self._execute([{"mask": left}, {"mask": right}], build_hp_combine_mask_skill, {"op": "or"})
        flipped = self._execute([{"mask": left}], build_hp_combine_mask_skill, {"op": "not"})
        xor = build_hp_combine_mask_skill()[1](
            op="xor",
            upstream_payloads=[{"mask": left}, {"mask": right}],
        )
        mismatch = build_hp_combine_mask_skill()[1](
            op="and",
            upstream_payloads=[{"mask": left}, {"mask": np.array([True, True, False])}],
        )
        print("\n[A2 combine] and:", _bools(both["payload"]["mask"]))
        print(" or:", _bools(either["payload"]["mask"]))
        print(" not:", _bools(flipped["payload"]["mask"]))
        print(" xor:", xor["error"]["message"])
        print(" shape:", mismatch["error"]["message"])
        self.assertEqual(_bools(both["payload"]["mask"]), [True, False])
        self.assertEqual(_bools(either["payload"]["mask"]), [True, True])
        self.assertEqual(_bools(flipped["payload"]["mask"]), [False, True])
        self.assertFalse(xor["ok"])
        self.assertEqual(xor["error"]["code"], "HP_MASK_REQUIRED")
        self.assertNotIn("Traceback", xor["error"]["message"])
        self.assertFalse(mismatch["ok"])
        self.assertEqual(mismatch["error"]["code"], "HP_MASK_REQUIRED")
        self.assertNotIn("Traceback", mismatch["error"]["message"])

    def test_expr_arithmetic_and_english_failures(self) -> None:
        """(high+low)/2 写入 hl2=[3, 5]。缺 volume、比较语法都是英文技能错误。"""

        panel = _panel([[[4.0, 2.0], [6.0, 4.0]]], ["s1"], ["2024-01-01", "2024-01-02"], ["high", "low"])
        before = np.array(panel.values, copy=True)
        handler = build_hp_expr_skill()[1]
        added = handler(new_htype="hl2", expression="(high + low) / 2", upstream_payload={"panel": panel})
        missing = handler(new_htype="hl2", expression="high + volume", upstream_payload={"panel": panel})
        compared = handler(new_htype="hl2", expression="high > low", upstream_payload={"panel": panel})
        column = added["payload"]["panel"].subpanel(htypes="hl2")
        print("\n[A2 expr] htypes:", list(added["payload"]["panel"].htypes), "hl2:", _flat(column))
        print(" missing:", missing["error"]["code"], missing["error"]["message"])
        print(" compare:", compared["error"]["message"])
        self.assertEqual(list(added["payload"]["panel"].htypes), ["high", "low", "hl2"])
        self.assertEqual(_flat(column), [3.0, 5.0])
        self.assertTrue(np.allclose(panel.values, before))
        self.assertEqual(list(panel.htypes), ["high", "low"])
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error"]["code"], "HP_EXPR_FAILED")
        self.assertIn("volume", missing["error"]["message"])
        self.assertNotIn("Traceback", missing["error"]["message"])
        self.assertFalse(compared["ok"])
        self.assertEqual(compared["error"]["code"], "HP_EXPR_FAILED")
        self.assertIn("unsupported", compared["error"]["message"])
        self.assertNotIn("Traceback", compared["error"]["message"])

    def test_missing_panel_message(self) -> None:
        """没有上游面板时，错误码和英文句子固定。"""

        handler = build_hp_returns_skill()[1]
        result = handler()
        print("\n[A2 missing panel]", result["error"]["code"], result["error"]["message"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "HP_PANEL_MISSING")
        self.assertEqual(result["error"]["message"], "A HistoryPanel from the previous step is required.")

    def test_transform_skills_are_registered(self) -> None:
        """十三个变换技能都在默认注册表里。"""

        names = {item.name for item in build_default_registry().list_skills()}
        print("\n[A2 transform registry]", sorted(name for name in names if name.startswith("qt.ai.hp.")))
        for name in _TRANSFORM_SKILLS:
            self.assertIn(name, names)

    def _execute(self, payloads: list, builder, extra_inputs: dict) -> dict:
        """若干步发出 payload，最后一步依赖它们。"""

        registry = SkillRegistry()
        steps = []
        depends = []
        for index, payload in enumerate(payloads):
            name = f"qt.ai.test.emit_{index}"
            step_id = f"step_{index}"
            registry.register(*_emitter(name, payload))
            steps.append(ToolStep(step_id=step_id, skill_name=name, inputs={}))
            depends.append(step_id)
        registry.register(*builder())
        steps.append(
            ToolStep(
                step_id="op",
                skill_name=builder()[0].name,
                inputs=dict(extra_inputs),
                depends_on=depends,
            )
        )
        plan = ToolPlan(
            plan_id="plan_transform",
            user_query="transform panels",
            execution_mode="execute",
            steps=steps,
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
