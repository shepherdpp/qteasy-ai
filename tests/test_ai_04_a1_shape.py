# coding=utf-8
# ======================================
# File: test_ai_04_a1_shape.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-02
# Desc:
# 0.4 A1：面板切片、删改、填补、重采样、赋值，
# 以及经执行器传入的两块面板对齐与合并。
# ======================================

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
from qteasy_ai.skills.hp_shape import (
    build_hp_align_skill,
    build_hp_assign_skill,
    build_hp_drop_skill,
    build_hp_dropna_skill,
    build_hp_fill_skill,
    build_hp_join_skill,
    build_hp_rename_skill,
    build_hp_resample_skill,
    build_hp_slice_skill,
)

_SHAPE_SKILLS = [
    "qt.ai.hp.slice",
    "qt.ai.hp.drop",
    "qt.ai.hp.rename",
    "qt.ai.hp.fill",
    "qt.ai.hp.dropna",
    "qt.ai.hp.resample",
    "qt.ai.hp.assign",
    "qt.ai.hp.align",
    "qt.ai.hp.join",
]


def _panel(values, shares, dates, columns) -> HistoryPanel:
    """用已知数字做一块面板。values 形状是 (标的, 日期, 列)。"""

    return HistoryPanel(
        values=np.asarray(values, dtype=float),
        levels=list(shares),
        rows=pd.to_datetime(list(dates)),
        columns=list(columns),
    )


def _flat(panel: HistoryPanel) -> list:
    """单列展开成 Python 数。NaN 记成 None，方便打印。"""

    out = []
    for item in np.asarray(panel.values, dtype=float).reshape(-1):
        out.append(None if not np.isfinite(item) else float(item))
    return out


def _dates(panel: HistoryPanel) -> list:
    """日期收成 YYYYMMDD。"""

    return [item.strftime("%Y%m%d") for item in panel.hdates]


class TestA1Shape(unittest.TestCase):
    """整形原子的金标准。数值都是手工算的。"""

    def test_slice_keeps_the_requested_close(self) -> None:
        """日期闭区间与行号都切到第二天的 2。"""

        panel = _panel([[[1.0], [2.0], [3.0]]], ["000001.SZ"], ["2024-01-01", "2024-01-02", "2024-01-03"], ["close"])
        handler = build_hp_slice_skill()[1]
        by_date = handler(start="20240102", end="20240102", upstream_payload={"panel": panel})
        by_index = handler(index=1, upstream_payload={"panel": panel})
        print("\n[A1 slice] 闭区间第二天:", _flat(by_date["payload"]["panel"]), _dates(by_date["payload"]["panel"]))
        print(" 行号 1:", _flat(by_index["payload"]["panel"]), _dates(by_index["payload"]["panel"]))
        self.assertTrue(by_date["ok"])
        self.assertEqual(_flat(by_date["payload"]["panel"]), [2.0])
        self.assertEqual(_dates(by_date["payload"]["panel"]), ["20240102"])
        self.assertEqual(_flat(by_index["payload"]["panel"]), [2.0])

    def test_drop_and_rename_labels(self) -> None:
        """丢掉 open 后只剩 close=4；改名后轴标签换成新名字。"""

        panel = _panel(
            [[[4.0, 9.0]]],
            ["000001.SZ"],
            ["2024-01-02"],
            ["close", "open"],
        )
        dropped = build_hp_drop_skill()[1](htypes="open", upstream_payload={"panel": panel})
        renamed = build_hp_rename_skill()[1](
            htypes={"close": "adj_close"},
            shares={"000001.SZ": "AAA"},
            upstream_payload={"panel": panel},
        )
        print("\n[A1 drop/rename] dropped htypes:", dropped["payload"]["panel"].htypes, "values:", _flat(dropped["payload"]["panel"]))
        print(" renamed shares/htypes:", renamed["payload"]["panel"].shares, renamed["payload"]["panel"].htypes)
        self.assertEqual(list(dropped["payload"]["panel"].htypes), ["close"])
        self.assertEqual(_flat(dropped["payload"]["panel"]), [4.0])
        self.assertEqual(list(renamed["payload"]["panel"].shares), ["AAA"])
        self.assertEqual(list(renamed["payload"]["panel"].htypes), ["adj_close", "open"])

    def test_fill_writes_new_panel_and_leaves_source(self) -> None:
        """[nan, 2, nan] 前向变成 [nan, 2, 2]，原面板不变。"""

        panel = _panel([[[np.nan], [2.0], [np.nan]]], ["000001.SZ"], ["2024-01-01", "2024-01-02", "2024-01-03"], ["close"])
        before = np.array(panel.values, copy=True)
        filled = build_hp_fill_skill()[1](method="ffill", upstream_payload={"panel": panel})
        backward = build_hp_fill_skill()[1](method="bfill", upstream_payload={"panel": panel})
        constant = build_hp_fill_skill()[1](method="fillna", value=0, upstream_payload={"panel": panel})
        print("\n[A1 fill] source:", _flat(panel))
        print(" ffill:", _flat(filled["payload"]["panel"]))
        print(" bfill:", _flat(backward["payload"]["panel"]))
        print(" fillna 0:", _flat(constant["payload"]["panel"]))
        self.assertTrue(np.allclose(panel.values, before, equal_nan=True))
        self.assertEqual(_flat(filled["payload"]["panel"]), [None, 2.0, 2.0])
        self.assertEqual(_flat(backward["payload"]["panel"]), [2.0, 2.0, None])
        self.assertEqual(_flat(constant["payload"]["panel"]), [0.0, 2.0, 0.0])

    def test_dropna_removes_the_empty_row(self) -> None:
        """how=any 丢掉中间的 NaN 行，留下 1 和 3。"""

        panel = _panel([[[1.0], [np.nan], [3.0]]], ["000001.SZ"], ["2024-01-01", "2024-01-02", "2024-01-03"], ["close"])
        result = build_hp_dropna_skill()[1](upstream_payload={"panel": panel})
        kept = result["payload"]["panel"]
        print("\n[A1 dropna] kept dates:", _dates(kept), "values:", _flat(kept))
        self.assertEqual(_dates(kept), ["20240101", "20240103"])
        self.assertEqual(_flat(kept), [1.0, 3.0])

    def test_resample_week_and_month_last(self) -> None:
        """周线最后一根是周五 5 与下一周 7；一月最后一天是 31。"""

        days = pd.date_range("2024-01-01", periods=7, freq="D")
        week_panel = _panel(np.arange(1, 8, dtype=float).reshape(1, 7, 1), ["000001.SZ"], days, ["close"])
        month_days = pd.date_range("2024-01-01", periods=31, freq="D")
        month_panel = _panel(np.arange(1, 32, dtype=float).reshape(1, 31, 1), ["000001.SZ"], month_days, ["close"])
        week = build_hp_resample_skill()[1](rule="w", agg={"close": "last"}, upstream_payload={"panel": week_panel})
        month = build_hp_resample_skill()[1](rule="m", agg={"close": "last"}, upstream_payload={"panel": month_panel})
        week_out = week["payload"]["panel"]
        month_out = month["payload"]["panel"]
        print("\n[A1 resample] week dates:", _dates(week_out), "values:", _flat(week_out))
        print(" month dates:", _dates(month_out), "values:", _flat(month_out))
        self.assertEqual(list(zip(_dates(week_out), _flat(week_out))), [("20240105", 5.0), ("20240112", 7.0)])
        self.assertEqual(list(zip(_dates(month_out), _flat(month_out))), [("20240131", 31.0)])

    def test_assign_scalar_and_array_and_reject_text(self) -> None:
        """标量 9 与数组 [4,5,6] 写入新列。字符串被英文拒绝。"""

        panel = _panel([[[1.0], [2.0], [3.0]]], ["000001.SZ"], ["2024-01-01", "2024-01-02", "2024-01-03"], ["close"])
        handler = build_hp_assign_skill()[1]
        scalar = handler(column="signal", value=9, upstream_payload={"panel": panel})
        array = handler(column="extra", value=[4.0, 5.0, 6.0], upstream_payload={"panel": panel})
        rejected = handler(column="bad", value="not-a-number", upstream_payload={"panel": panel})
        scalar_panel = scalar["payload"]["panel"]
        array_panel = array["payload"]["panel"]
        print("\n[A1 assign] scalar signal:", _flat(scalar_panel.subpanel(htypes="signal")))
        print(" array extra:", _flat(array_panel.subpanel(htypes="extra")))
        print(" rejected:", rejected["error"]["message"])
        self.assertEqual(_flat(scalar_panel.subpanel(htypes="signal")), [9.0, 9.0, 9.0])
        self.assertEqual(_flat(scalar_panel.subpanel(htypes="close")), [1.0, 2.0, 3.0])
        self.assertEqual(_flat(array_panel.subpanel(htypes="extra")), [4.0, 5.0, 6.0])
        self.assertFalse(rejected["ok"])
        self.assertIn("numeric array", rejected["error"]["message"])
        self.assertNotIn("Traceback", rejected["error"]["message"])

    def test_align_and_join_receive_the_second_panel(self) -> None:
        """执行器把第二块面板送进来。交集日左表是 2、右表是 20；并集里 000002.SZ 在 1 月 2 日是 5。"""

        left = _panel([[[1.0], [2.0]]], ["000001.SZ"], ["2024-01-01", "2024-01-02"], ["close"])
        right_align = _panel([[[20.0], [30.0]]], ["000001.SZ"], ["2024-01-02", "2024-01-03"], ["close"])
        right_join = _panel([[[5.0]]], ["000002.SZ"], ["2024-01-02"], ["close"])
        aligned = self._execute_pair(left, right_align, build_hp_align_skill, {"join": "inner"})
        joined = self._execute_pair(left, right_join, build_hp_join_skill, {})
        align_result = aligned["execution"]["steps"][2]["result"]
        join_result = joined["execution"]["steps"][2]["result"]
        print("\n[A1 align] ok:", align_result["ok"], "error:", align_result.get("error"))
        if align_result["ok"]:
            print(" left:", _dates(align_result["payload"]["panel"]), _flat(align_result["payload"]["panel"]))
            print(" right:", _dates(align_result["payload"]["other"]), _flat(align_result["payload"]["other"]))
        print("[A1 join] ok:", join_result["ok"], "error:", join_result.get("error"))
        if join_result["ok"]:
            print(" shares:", list(join_result["payload"]["panel"].shares), "values:", _flat(join_result["payload"]["panel"]))
        self.assertTrue(align_result["ok"])
        self.assertEqual(_dates(align_result["payload"]["panel"]), ["20240102"])
        self.assertEqual(_flat(align_result["payload"]["panel"]), [2.0])
        self.assertEqual(_flat(align_result["payload"]["other"]), [20.0])
        self.assertTrue(join_result["ok"])
        self.assertEqual(list(join_result["payload"]["panel"].shares), ["000001.SZ", "000002.SZ"])
        self.assertEqual(_dates(join_result["payload"]["panel"]), ["20240101", "20240102"])
        self.assertEqual(_flat(join_result["payload"]["panel"]), [1.0, 2.0, None, 5.0])

    def test_shape_skills_are_registered(self) -> None:
        """九个整形技能都在默认注册表里。"""

        names = {item.name for item in build_default_registry().list_skills()}
        print("\n[A1 shape registry]", sorted(name for name in names if name.startswith("qt.ai.hp.")))
        for name in _SHAPE_SKILLS:
            self.assertIn(name, names)

    def _execute_pair(self, left: HistoryPanel, right: HistoryPanel, builder, extra_inputs: dict) -> dict:
        """两步发出面板，第三步依赖它们。"""

        registry = SkillRegistry()
        registry.register(*_emitter("qt.ai.test.emit_left", left))
        registry.register(*_emitter("qt.ai.test.emit_right", right))
        registry.register(*builder())
        plan = ToolPlan(
            plan_id="plan_shape",
            user_query="shape two panels",
            execution_mode="execute",
            steps=[
                ToolStep(step_id="left", skill_name="qt.ai.test.emit_left", inputs={}),
                ToolStep(step_id="right", skill_name="qt.ai.test.emit_right", inputs={}),
                ToolStep(
                    step_id="combine",
                    skill_name=builder()[0].name,
                    inputs=dict(extra_inputs),
                    depends_on=["left", "right"],
                ),
            ],
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            executor = PlanExecutor(registry=registry, memory_store=MemoryStore(base_dir=temp_dir))
            return executor.execute(plan, confirm=True)


def _emitter(name: str, panel: HistoryPanel):
    """测试用的面板出口。闭包持有已知面板。"""

    metadata = SkillMetadata(
        name=name,
        version="0.1.0",
        summary="Emit one known panel.",
        inputs_schema={},
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly"),
    )

    def handler(**kwargs) -> dict:
        return {"ok": True, "skill_name": name, "payload": {"panel": panel}, "warnings": []}

    return metadata, handler


if __name__ == "__main__":
    unittest.main()
