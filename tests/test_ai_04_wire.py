# coding=utf-8
# ======================================
# File: test_ai_04_wire.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-07
# Desc:
# 步骤图的线格式：形状开关、选择卡、闭合菜谱错误。
# ======================================

import json
import tempfile
import unittest

import numpy as np
import pandas as pd

from qteasy.history import HistoryPanel
from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.human_card import clarification_needs_answer, project_human_cards
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.skills.hp_volatility import build_hp_volatility_skill
from qteasy_ai.slot_graph import apply_slot_layer
from qteasy_ai.wire import align_steps


def _job(payload) -> str:
    """分类罐头。"""

    if isinstance(payload, str):
        payload = {"job": payload}
    return json.dumps(payload, ensure_ascii=False)


def _pending(plan):
    """澄清卡 pending。"""

    blob = (plan.assumptions or {}).get("clarification") or {}
    return [item for item in (blob.get("pending") or []) if isinstance(item, dict)]


def _names(plan):
    """pending 槽名。"""

    return [str(item.get("name") or "") for item in _pending(plan)]


def _accepted(plan):
    """澄清卡上的步骤快照。没有快照时用计划步骤。"""

    rows = (plan.assumptions or {}).get("accepted_steps")
    if isinstance(rows, list) and rows:
        return rows
    blob = (plan.assumptions or {}).get("clarification") or {}
    rows = blob.get("accepted_steps")
    if isinstance(rows, list) and rows:
        return rows
    return [
        {
            "step_id": step.step_id,
            "skill_name": step.skill_name,
            "inputs": dict(step.inputs or {}),
            "depends_on": list(step.depends_on or []),
        }
        for step in plan.steps
        if step.skill_name != "qt.ai.system.fallback"
    ]


class TestAi04Wire(unittest.TestCase):
    """线格式质检、形状开关和接不上时的选择卡。"""

    def setUp(self) -> None:
        self.registry = build_default_registry()

    def test_returns_into_plot_sets_as_panel(self) -> None:
        """取数、收益、绘图：收益步写成面板，日期卡快照里仍在。"""

        print("\n[TestAi04Wire] 收益接到绘图时补 as_panel")
        steps = [
            {
                "skill_name": "qt.ai.data.history",
                "inputs": {
                    "shares": "000300.SH",
                    "htype_names": "close",
                    "asset_type": "IDX",
                    "freq": "d",
                },
            },
            {"skill_name": "qt.ai.hp.returns", "inputs": {}, "depends_on": ["step_1"]},
            {"skill_name": "qt.ai.hp.plot", "inputs": {"page": 1}, "depends_on": ["step_2"]},
        ]
        fake = FakeLLMProvider(replies=[json.dumps({"steps": steps}), "not-a-second-graph"])
        plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(
            "取 000300.SH 日线，算收益，再出一页图",
            mode="plan",
            forced_job="open",
        )
        accepted = _accepted(plan)
        returns = next(row for row in accepted if row["skill_name"] == "qt.ai.hp.returns")
        open_prompts = [text for text in fake.prompts if text.startswith("Allowed skills:")]
        print(" pending:", _names(plan))
        print(" returns inputs:", returns["inputs"])
        print(" open prompts:", len(open_prompts), "all prompts:", len(fake.prompts))
        self.assertTrue(returns["inputs"].get("as_panel"))
        self.assertEqual(len(open_prompts), 1)
        self.assertNotIn("wire_choice", _names(plan))
        self.assertIn("start", _names(plan))

    def test_returns_alone_keeps_library_default(self) -> None:
        """收益没有后继时不写 as_panel。"""

        print("\n[TestAi04Wire] 收益没有后继时保持库默认")
        steps = [
            {
                "skill_name": "qt.ai.data.history",
                "inputs": {
                    "shares": "000300.SH",
                    "htype_names": "close",
                    "start": "20240101",
                    "end": "20240630",
                    "freq": "d",
                    "asset_type": "IDX",
                },
            },
            {"skill_name": "qt.ai.hp.returns", "inputs": {}, "depends_on": ["step_1"]},
        ]
        fake = FakeLLMProvider(replies=[json.dumps({"steps": steps})])
        plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(
            "取 000300.SH 从 20240101 到 20240630 的收盘并算收益",
            mode="plan",
            forced_job="open",
        )
        print(" skills:", [step.skill_name for step in plan.steps])
        print(" returns:", plan.steps[1].inputs)
        self.assertEqual([step.skill_name for step in plan.steps], ["qt.ai.data.history", "qt.ai.hp.returns"])
        self.assertNotIn("as_panel", plan.steps[1].inputs)

    def test_summary_export_screen_and_alpha(self) -> None:
        """体检不改波动率默认；导出和筛股不被拒绝；阿尔法没基准时要上游表。"""

        print("\n[TestAi04Wire] 体检、导出、筛股和阿尔法")
        planner = Planner(self.registry, env_facts={})
        summary = planner.build_plan("000300.SH volatility", mode="plan")
        accepted = _accepted(summary)
        print(" summary skills:", [row["skill_name"] for row in accepted])
        print(" summary reason:", summary.steps[0].inputs.get("reason"))
        volatility = next(row for row in accepted if row["skill_name"] == "qt.ai.hp.volatility")
        print(" volatility inputs:", volatility["inputs"])
        print(" volatility depends:", volatility["depends_on"])
        self.assertEqual([row["skill_name"] for row in accepted], ["qt.ai.data.kline", "qt.ai.hp.volatility"])
        self.assertNotEqual(summary.steps[0].inputs.get("reason"), "wire_product_mismatch")
        self.assertNotIn("as_panel", volatility["inputs"])
        self.assertEqual(volatility["depends_on"], ["step_1"])
        self.assertFalse(any(row["skill_name"] == "qt.ai.hp.describe" for row in accepted))

        exported = planner.build_plan("export png 000300.SH", mode="plan")
        export_names = [row["skill_name"] for row in _accepted(exported)]
        print(" export skills:", export_names, exported.steps[0].inputs.get("reason"))
        self.assertEqual(export_names, ["qt.ai.data.kline", "qt.ai.hp.plot"])
        self.assertNotEqual(exported.steps[0].inputs.get("reason"), "wire_product_mismatch")

        screened = planner.build_plan("筛股 20d 跌 10%", mode="plan")
        screen_names = [row["skill_name"] for row in _accepted(screened)]
        print(" screen skills:", screen_names, screened.steps[0].inputs.get("reason"))
        self.assertIn("qt.ai.research.universe_filter", screen_names)
        self.assertIn("qt.ai.research.project_universe", screen_names)
        self.assertNotEqual(screened.steps[0].inputs.get("reason"), "wire_product_mismatch")

        bare = [
            planner._make_step(step_id="step_1", skill_name="qt.ai.data.history", inputs={"shares": "000300.SH"}),
            planner._make_step(
                step_id="step_2",
                skill_name="qt.ai.hp.alpha_beta",
                inputs={},
                depends_on=["step_1"],
            ),
        ]
        missing = align_steps(planner, bare)
        print(" alpha without frame:", missing)
        self.assertIsNotNone(missing)
        self.assertIn("frame", str(missing))

        linked = [
            planner._make_step(step_id="step_1", skill_name="qt.ai.data.history", inputs={"shares": "000300.SH"}),
            planner._make_step(
                step_id="step_2",
                skill_name="qt.ai.hp.returns",
                inputs={},
                depends_on=["step_1"],
            ),
            planner._make_step(
                step_id="step_3",
                skill_name="qt.ai.hp.alpha_beta",
                inputs={},
                depends_on=["step_1", "step_2"],
            ),
        ]
        fitted = align_steps(planner, linked)
        print(" alpha with frame:", fitted, linked[1].inputs)
        self.assertIsNone(fitted)
        self.assertNotIn("as_panel", linked[1].inputs)

        quoted = [
            planner._make_step(step_id="step_1", skill_name="qt.ai.data.history", inputs={"shares": "000300.SH"}),
            planner._make_step(
                step_id="step_2",
                skill_name="qt.ai.hp.alpha_beta",
                inputs={"benchmark": "000300.SH"},
                depends_on=["step_1"],
            ),
        ]
        quoted_fit = align_steps(planner, quoted)
        print(" alpha with benchmark:", quoted_fit)
        self.assertIsNone(quoted_fit)

    def test_open_prompt_states_wires(self) -> None:
        """组图提示写明消费、默认产出、另一种产出，并要求不要填形状开关。"""

        print("\n[TestAi04Wire] 组图提示里的线格式")
        steps = [{"skill_name": "qt.ai.hp.returns", "inputs": {}}]
        fake = FakeLLMProvider(replies=[json.dumps({"steps": steps})])
        Planner(self.registry, provider=fake, env_facts={}).build_plan(
            "算收益",
            mode="plan",
            forced_job="open",
        )
        prompt = next(text for text in fake.prompts if text.startswith("Allowed skills:"))
        system = fake.system_prompts[0]
        print(" has consumes:", "consumes " in prompt)
        print(" has produces:", "produces " in prompt)
        print(" has alt:", "alt " in prompt)
        print(" system leaves switches unset:", "Do not set as_panel" in system)
        self.assertIn("consumes ", prompt)
        self.assertIn("produces ", prompt)
        self.assertIn("alt ", prompt)
        self.assertIn("as_panel=true->panel:qteasy.history.HistoryPanel", prompt)
        self.assertIn("Do not set as_panel", system)
        self.assertIn("declared alternate", system)

    def test_agg_plot_choice_and_resume(self) -> None:
        """汇总接不上绘图时出中文选择卡。点保留或改画都不再组图。"""

        print("\n[TestAi04Wire] 汇总接绘图的选择卡")
        steps = [
            {"skill_name": "qt.ai.data.history", "inputs": {"shares": "000300.SH", "htype_names": "close"}},
            {"skill_name": "qt.ai.hp.agg", "inputs": {"stat": "mean"}, "depends_on": ["step_1"]},
            {"skill_name": "qt.ai.hp.plot", "inputs": {"page": 1}, "depends_on": ["step_2"]},
        ]
        query = "取 000300.SH 日线，做汇总，再出一页图"
        fake = FakeLLMProvider(
            replies=[
                _job("open"),
                _job("open"),
                json.dumps({"steps": steps}, ensure_ascii=False),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                provider=fake,
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "wire-agg"
            first = asst.plan(query, response_style="raw", session_id=sid)
            plan = first.get("plan") or {}
            blob = (plan.get("assumptions") or {}).get("clarification") or {}
            row = (blob.get("pending") or [{}])[0]
            option_ids = [str(item.get("id") or "") for item in (row.get("options") or [])]
            text = json.dumps(blob, ensure_ascii=False)
            print(" options:", option_ids)
            print(" prompt:", blob.get("confirm_prompt"))
            print(" allowed:", len([item for item in fake.prompts if item.startswith("Allowed skills:")]), "left:", fake.replies)
            self.assertEqual(option_ids, ["drop_consumer", "use_panel", "rewrite"])
            self.assertEqual(row.get("name"), "wire_choice")
            self.assertIn("汇总表", str(blob.get("confirm_prompt")))
            self.assertIn("不画图", row["options"][0]["label"])
            self.assertEqual(row["options"][1]["label"], "改画前面的行情")
            self.assertNotIn("DataFrame", text)
            self.assertNotIn("HistoryPanel", text)
            self.assertNotIn("supported_skill", text)
            self.assertEqual(len([item for item in fake.prompts if item.startswith("Allowed skills:")]), 1)
            self.assertEqual(fake.replies, [])

            dropped = asst.plan("", response_style="raw", session_id=sid, patches={"wire_choice": "drop_consumer"})
            dropped_plan = dropped.get("plan") or {}
            dropped_rows = (dropped_plan.get("assumptions") or {}).get("accepted_steps") or []
            if not dropped_rows:
                dropped_rows = [
                    step
                    for step in (dropped_plan.get("steps") or [])
                    if step.get("skill_name") != "qt.ai.system.fallback"
                ]
            names = [str(row.get("skill_name") or "") for row in dropped_rows]
            print(" dropped skills:", names)
            print(" prompts after drop:", len(fake.prompts), "left:", fake.replies)
            self.assertIn("qt.ai.hp.agg", names)
            self.assertNotIn("qt.ai.hp.plot", names)
            self.assertEqual(len([item for item in fake.prompts if item.startswith("Allowed skills:")]), 1)

        fake_plot = FakeLLMProvider(
            replies=[
                _job("open"),
                _job("open"),
                json.dumps({"steps": steps}, ensure_ascii=False),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                provider=fake_plot,
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "wire-plot"
            asst.plan(query, response_style="raw", session_id=sid)
            plotted = asst.plan("", response_style="raw", session_id=sid, patches={"wire_choice": "use_panel"})
            plotted_plan = plotted.get("plan") or {}
            rows = (plotted_plan.get("assumptions") or {}).get("accepted_steps") or []
            print(" use_panel rows:", rows)
            print(" prompts after plot:", len([item for item in fake_plot.prompts if item.startswith("Allowed skills:")]))
            plot = next(row for row in rows if row.get("skill_name") == "qt.ai.hp.plot")
            self.assertEqual(plot.get("depends_on"), ["step_1"])
            self.assertNotIn("qt.ai.hp.agg", [row.get("skill_name") for row in rows])
            self.assertEqual(len([item for item in fake_plot.prompts if item.startswith("Allowed skills:")]), 1)

    def test_no_earlier_panel_omits_use_panel(self) -> None:
        """前面没有面板时不出「改画前面的行情」。"""

        print("\n[TestAi04Wire] 没有更早的面板")
        steps = [
            {"skill_name": "qt.ai.hp.agg", "inputs": {"stat": "mean"}},
            {"skill_name": "qt.ai.hp.plot", "inputs": {"page": 1}, "depends_on": ["step_1"]},
        ]
        fake = FakeLLMProvider(replies=[json.dumps({"steps": steps})])
        plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(
            "汇总之后出一页图",
            mode="plan",
            forced_job="open",
        )
        row = _pending(plan)[0]
        option_ids = [str(item.get("id") or "") for item in (row.get("options") or [])]
        print(" options:", option_ids, row.get("label"))
        self.assertEqual(row.get("name"), "wire_choice")
        self.assertIn("drop_consumer", option_ids)
        self.assertNotIn("use_panel", option_ids)
        self.assertIn("rewrite", option_ids)

    def test_rewrite_reclassifies(self) -> None:
        """换一种说法用新句子重新分类，不沿用接不上的图。"""

        print("\n[TestAi04Wire] 换一种说法")
        steps = [
            {"skill_name": "qt.ai.hp.agg", "inputs": {"stat": "mean"}},
            {"skill_name": "qt.ai.hp.plot", "inputs": {"page": 1}, "depends_on": ["step_1"]},
        ]
        fake = FakeLLMProvider(
            replies=[
                _job("open"),
                _job("open"),
                json.dumps({"steps": steps}),
                _job("strategy.meta"),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                provider=fake,
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "wire-rewrite"
            asst.plan("汇总之后出一页图", response_style="raw", session_id=sid)
            before = len(fake.prompts)
            second = asst.plan(
                "",
                response_style="raw",
                session_id=sid,
                patches={"wire_choice": "列出内置策略"},
            )
            plan = second.get("plan") or {}
            skills = [step.get("skill_name") for step in (plan.get("steps") or [])]
            catalogs = [text for text in fake.prompts[before:] if "列出内置策略" in text]
            print(" skills:", skills)
            print(" new prompts mention rewrite:", len(catalogs), "intent:", (plan.get("planner_trace") or {}).get("intent_job"))
            self.assertTrue(catalogs)
            self.assertEqual(skills, ["qt.ai.strategy_meta.list"])
            self.assertNotIn("qt.ai.hp.plot", skills)

    def test_one_switch_cannot_feed_two_types(self) -> None:
        """同一步不能既交表又交面板。出选择卡，不再组图。"""

        print("\n[TestAi04Wire] 一个开关喂不了两种类型")
        steps = [
            {"skill_name": "qt.ai.data.history", "inputs": {"shares": "000300.SH"}},
            {"skill_name": "qt.ai.hp.returns", "inputs": {}, "depends_on": ["step_1"]},
            {"skill_name": "qt.ai.hp.alpha_beta", "inputs": {}, "depends_on": ["step_2"]},
        ]
        fake = FakeLLMProvider(replies=[json.dumps({"steps": steps}), "must-not-compose-again"])
        plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(
            "取数、算收益、再算阿尔法",
            mode="plan",
            forced_job="open",
        )
        row = _pending(plan)[0]
        option_ids = [str(item.get("id") or "") for item in (row.get("options") or [])]
        print(" options:", option_ids)
        print(" left:", fake.replies)
        self.assertEqual(row.get("name"), "wire_choice")
        self.assertIn("drop_consumer", option_ids)
        self.assertIn("rewrite", option_ids)
        self.assertNotIn("use_panel", option_ids)
        self.assertEqual(len([text for text in fake.prompts if text.startswith("Allowed skills:")]), 1)
        self.assertEqual(fake.replies, ["must-not-compose-again"])

    def test_closed_recipe_mismatch_is_not_a_choice(self) -> None:
        """闭合菜谱接不上是菜谱错误，不出选择卡。"""

        print("\n[TestAi04Wire] 闭合菜谱线接不上")
        planner = Planner(self.registry, env_facts={})
        steps = [
            planner._make_step(step_id="step_1", skill_name="qt.ai.data.history", inputs={"shares": "000300.SH"}),
            planner._make_step(
                step_id="step_2",
                skill_name="qt.ai.hp.performance",
                inputs={},
                depends_on=["step_1"],
            ),
            planner._make_step(
                step_id="step_3",
                skill_name="qt.ai.hp.plot",
                inputs={},
                depends_on=["step_2"],
            ),
        ]
        out, extras = apply_slot_layer(planner, steps, "画绩效", "data.summary", None)
        blob = extras.get("clarification") or {}
        pending = blob.get("pending") or []
        print(" reason:", out[0].inputs.get("reason"))
        print(" pending:", pending)
        print(" hint:", out[0].inputs.get("hint"))
        self.assertEqual(out[0].inputs.get("reason"), "wire_product_mismatch")
        self.assertEqual(pending, [])
        self.assertFalse(clarification_needs_answer(blob))
        self.assertNotIn("wire_choice", json.dumps(blob, ensure_ascii=False))
        self.assertNotIn("drop_consumer", json.dumps(blob, ensure_ascii=False))
        cards = project_human_cards(
            {
                "plan": {
                    "user_query": "画绩效",
                    "assumptions": {"clarification": blob},
                    "steps": [],
                },
                "execution": {"status": "dry_run", "steps": []},
            },
            requested_mode="plan",
            query="画绩效",
            include_user_text=False,
        )
        kinds = [item.get("kind") for item in cards]
        print(" cards:", kinds)
        self.assertIn("error", kinds)
        self.assertNotIn("clarify", kinds)

    def test_model_false_is_overwritten(self) -> None:
        """模型把 as_panel 写成假、后面仍是绘图时，检查器改回真。"""

        print("\n[TestAi04Wire] 模型写反的形状开关")
        steps = [
            {
                "skill_name": "qt.ai.data.history",
                "inputs": {
                    "shares": "000300.SH",
                    "htype_names": "close",
                    "start": "20240101",
                    "end": "20240630",
                    "freq": "d",
                    "asset_type": "IDX",
                },
            },
            {
                "skill_name": "qt.ai.hp.returns",
                "inputs": {"as_panel": False},
                "depends_on": ["step_1"],
            },
            {"skill_name": "qt.ai.hp.plot", "inputs": {"page": 1}, "depends_on": ["step_2"]},
        ]
        fake = FakeLLMProvider(replies=[json.dumps({"steps": steps})])
        plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(
            "取 000300.SH 从 20240101 到 20240630 的收盘，算收益，再出一页图",
            mode="plan",
            forced_job="open",
        )
        print(" skills:", [step.skill_name for step in plan.steps])
        print(" returns:", plan.steps[1].inputs if len(plan.steps) > 1 else plan.steps[0].inputs)
        self.assertEqual(plan.steps[1].skill_name, "qt.ai.hp.returns")
        self.assertTrue(plan.steps[1].inputs.get("as_panel"))

    def test_volatility_stores_frame(self) -> None:
        """波动率的表要放在 frame，声明才和运行时一致。"""

        print("\n[TestAi04Wire] 波动率交出 frame")
        panel = HistoryPanel(
            values=np.asarray([[[1.0], [2.0], [3.0], [4.0]]], dtype=float),
            levels=["000300.SH"],
            rows=pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
            columns=["close"],
        )
        handler = build_hp_volatility_skill()[1]
        result = handler(window=2, annualize=False, as_panel=False, upstream_payload={"panel": panel})
        frame = (result.get("payload") or {}).get("frame")
        print(" ok:", result.get("ok"), "frame type:", type(frame).__name__)
        self.assertTrue(result.get("ok"))
        self.assertIsInstance(frame, pd.DataFrame)
        self.assertGreater(len(frame.index), 0)


if __name__ == "__main__":
    unittest.main()
