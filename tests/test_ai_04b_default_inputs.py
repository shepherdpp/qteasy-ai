# coding=utf-8
# ======================================
# File: test_ai_04b_default_inputs.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-17
# Desc:
# 第四B步：放行所依据的缺省必须写进步骤 inputs，再质检。
# 元素切分已经取出的槽在第一次质检前点到。
# ======================================

import inspect
import json
import tempfile
import unittest
from typing import Any, Dict, List, Optional

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.session_gate import new_task_patches
from qteasy_ai.slot_graph import (
    _apply_judged,
    _judge_slots,
    _slot_default_value,
    kernel_window,
)


_SCREEN = "筛股 银行业 跌幅超过 10%"
_SCREEN_BAD = "筛股 回看 abc 跌 10% 银行业"
_HOLD = "600519 和 000858 做一条等权组合，看过去一段时间的持仓收益率，并跟沪深300做一个对比"
_OPEN = "取一支股票的日线，算收益，再出一页图"


def _planner(replies: Optional[List[str]] = None) -> Planner:
    """无模型，或按队列喂假模型。"""

    provider = FakeLLMProvider(replies=list(replies)) if replies is not None else None
    return Planner(build_default_registry(), provider=provider, env_facts={})


def _pending(plan: Any) -> List[Dict[str, Any]]:
    """澄清卡上的题。"""

    blob = (plan.assumptions or {}).get("clarification") or {}
    return [item for item in (blob.get("pending") or []) if isinstance(item, dict)]


def _names(plan: Any) -> List[str]:
    """待答题名。"""

    return [str(item.get("name") or "") for item in _pending(plan)]


def _confirmable(plan: Any) -> bool:
    """可见步骤里没有澄清回退。"""

    return "qt.ai.system.fallback" not in [step.skill_name for step in plan.steps]


def _snap(plan: Any, skill: str) -> Dict[str, Any]:
    """快照或可见步骤上的 inputs。"""

    for step in (plan.assumptions or {}).get("accepted_steps") or []:
        if str(step.get("skill_name") or "") == skill:
            return dict(step.get("inputs") or {})
    for step in plan.steps:
        if step.skill_name == skill:
            return dict(step.inputs or {})
    return {}


def _raw_plan(result: Dict[str, Any]) -> Dict[str, Any]:
    """助手 raw 结果里的计划。"""

    plan = result.get("plan") or {}
    return plan if isinstance(plan, dict) else {}


def _raw_inputs(plan: Dict[str, Any], skill: str) -> Dict[str, Any]:
    """raw 计划里某个技能的 inputs。"""

    for step in list(plan.get("steps") or []) + list((plan.get("assumptions") or {}).get("accepted_steps") or []):
        if isinstance(step, dict) and step.get("skill_name") == skill:
            return dict(step.get("inputs") or {})
    return {}


class TestAi04bDefaultInputs(unittest.TestCase):
    """进入计划前，缺省写进步骤输入；切得出的槽先被点到。"""

    def test_open_kline_window_is_kernel_default(self) -> None:
        """代码确认后不出日期卡。历史窗口等于当时的内核缺省，且不是用户已确认。"""

        print("\n[TestAi04bDefaultInputs] 开放图内核窗口")
        window = kernel_window()
        compose = {
            "steps": [
                {
                    "skill_name": "qt.ai.data.kline",
                    "inputs": {"shares": "600519.SH", "asset_type": "E"},
                    "depends_on": [],
                },
                {"skill_name": "qt.ai.hp.returns", "inputs": {}, "depends_on": ["step_1"]},
                {"skill_name": "qt.ai.hp.plot", "inputs": {}, "depends_on": ["step_2"]},
            ]
        }
        job = json.dumps({"job": "open"})
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                provider=FakeLLMProvider(
                    replies=[
                        json.dumps({"task": _OPEN, "question": ""}, ensure_ascii=False),
                        job,
                        job,
                        json.dumps(compose, ensure_ascii=False),
                        json.dumps({"freq": "d"}, ensure_ascii=False),
                        json.dumps({
                            "questions": [
                                {
                                    "name": "shares",
                                    "explanation": "请给出证券代码",
                                    "options": [],
                                    "open": {"label": "其它"},
                                }
                            ]
                        }, ensure_ascii=False),
                    ]
                ),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            assistant.plan(_OPEN, response_style="raw", session_id="open-kernel")
            first = _raw_plan(
                assistant.plan(
                    "",
                    response_style="raw",
                    session_id="open-kernel",
                    patches={"intent": "confirm_open_intent"},
                )
            )
            rows = ((first.get("assumptions") or {}).get("clarification") or {}).get("pending") or []
            print(" entry pending:", [item.get("name") for item in rows])
            self.assertEqual([item.get("name") for item in rows], ["shares"])
            assistant.apply_provider(
                FakeLLMProvider(replies=[json.dumps({"shares": "600519"}, ensure_ascii=False)])
            )
            second = _raw_plan(
                assistant.plan("", response_style="raw", session_id="open-kernel", answers=["600519"])
            )
            steps = list(second.get("steps") or [])
            pending = [
                str(item.get("name") or "")
                for item in (((second.get("assumptions") or {}).get("clarification") or {}).get("pending") or [])
                if isinstance(item, dict)
            ]
            kline = _raw_inputs(second, "qt.ai.data.kline")
            defaults = (second.get("assumptions") or {}).get("slot_defaults") or {}
            loaded = assistant.session_store.load("open-kernel")
            slots = loaded.task.slots if loaded is not None and loaded.task is not None else {}
            start_slot = slots.get("start")
            end_slot = slots.get("end")
            shares_slot = slots.get("shares")
            print(" skills:", [step.get("skill_name") for step in steps])
            print(" pending:", pending, "confirmable:", "qt.ai.system.fallback" not in [step.get("skill_name") for step in steps])
            print(" window:", kline.get("start"), kline.get("end"), "kernel:", window)
            print(" defaults:", defaults)
            print(
                " confirmed:",
                "start", getattr(start_slot, "confirmed", None),
                "end", getattr(end_slot, "confirmed", None),
                "shares", getattr(shares_slot, "confirmed", None),
            )
            self.assertNotIn("start", pending)
            self.assertNotIn("end", pending)
            self.assertNotIn("qt.ai.system.fallback", [step.get("skill_name") for step in steps])
            self.assertEqual(kline.get("start"), window["start"])
            self.assertEqual(kline.get("end"), window["end"])
            self.assertEqual(defaults.get("start"), "default")
            self.assertEqual(defaults.get("end"), "default")
            self.assertTrue(start_slot is None or not start_slot.confirmed)
            self.assertTrue(end_slot is None or not end_slot.confirmed)
            self.assertIsNotNone(shares_slot)
            self.assertTrue(shares_slot.confirmed)
            self.assertNotIn("asset_type", kline)
            self.assertNotIn("asset_type", pending)

    def test_one_written_end_keeps_the_other_kernel_bound(self) -> None:
        """用户只写下其中一端时，只补空着的那一端，且补上的一端不是用户已确认。"""

        print("\n[TestAi04bDefaultInputs] 只补空着的一端")
        window = kernel_window()
        start_only = _planner().build_plan("读取历史 close 000300.SH 20240315", mode="plan")
        history = _snap(start_only, "qt.ai.data.history")
        defaults = (start_only.assumptions or {}).get("slot_defaults") or {}
        print(" start only:", history.get("start"), history.get("end"), "defaults:", defaults)
        self.assertEqual(history.get("start"), window["start"])
        self.assertEqual(history.get("end"), window["end"])
        self.assertNotEqual(history.get("start"), "20240315")
        self.assertNotIn("20240315", json.dumps(history, ensure_ascii=False))

        end_only = _planner().build_plan("读取历史 close 000300.SH 到 2023 年", mode="plan")
        ended = _snap(end_only, "qt.ai.data.history")
        ended_defaults = (end_only.assumptions or {}).get("slot_defaults") or {}
        patches = new_task_patches("读取历史 close 000300.SH 到 2023 年")
        print(" end only:", ended.get("start"), ended.get("end"), "defaults:", ended_defaults)
        print(" patches:", patches)
        self.assertEqual(ended.get("end"), window["end"])
        self.assertEqual(ended.get("start"), window["start"])
        self.assertNotEqual(ended.get("end"), "20231231")
        self.assertNotIn("20231231", json.dumps(ended, ensure_ascii=False))
        self.assertNotIn("start", patches)
        self.assertNotIn("end", patches)

    def test_example_default_survives_reinspect(self) -> None:
        """等于卡片例子的字面缺省，再质检时对照已经写下的值，仍然留下。"""

        print("\n[TestAi04bDefaultInputs] 等于例子的缺省")
        planner = _planner()
        step = planner._make_step(step_id="step_1", skill_name="qt.ai.data.kline", inputs={})
        slot = {
            "name": "start",
            "type": "string",
            "required": False,
            "format": "YYYYMMDD",
            "example": "20250101",
            "default": "20250101",
        }
        result = _judge_slots([slot], [step], {}, set(), "", [])
        _apply_judged(planner, [step], [slot], result, {})
        print(" kept:", step.inputs.get("start"), "accepted:", result.get("accepted"), "rejected:", result.get("rejected"))
        self.assertEqual(step.inputs.get("start"), "20250101")
        self.assertNotIn("start", result.get("rejected") or {})
        self.assertEqual((result.get("accepted") or {}).get("start", {}).get("source"), "default")

    def test_illegal_default_returns_to_gaps(self) -> None:
        """非法缺省再质检后清掉。未知 default_kind 不写值，同样回到空缺。"""

        print("\n[TestAi04bDefaultInputs] 非法缺省回到空缺")
        planner = _planner()
        illegal_step = planner._make_step(step_id="step_1", skill_name="qt.ai.data.kline", inputs={})
        illegal = {
            "name": "start",
            "type": "string",
            "required": False,
            "format": "YYYYMMDD",
            "example": "20250101",
            "default": "20251340",
        }
        rejected = _judge_slots([illegal], [illegal_step], {}, set(), "", [])
        _apply_judged(planner, [illegal_step], [illegal], rejected, {})
        print(" illegal:", illegal_step.inputs.get("start"), "rejected:", rejected.get("rejected"))
        self.assertIn(illegal_step.inputs.get("start"), (None, ""))
        self.assertIn("start", rejected.get("rejected") or {})

        unknown_step = planner._make_step(step_id="step_1", skill_name="qt.ai.data.kline", inputs={})
        unknown = {
            "name": "start",
            "type": "string",
            "required": False,
            "format": "YYYYMMDD",
            "example": "20250101",
            "default_kind": "missing_kind",
        }
        missed = _judge_slots([unknown], [unknown_step], {}, set(), "", [])
        _apply_judged(planner, [unknown_step], [unknown], missed, {})
        print(" unknown:", unknown_step.inputs.get("start"), "rejected:", missed.get("rejected"))
        self.assertIn(unknown_step.inputs.get("start"), (None, ""))
        self.assertIn("start", missed.get("rejected") or {})
        self.assertIsNone(_slot_default_value(unknown))

    def test_lookback_uses_declared_default_not_skill_name(self) -> None:
        """没提回看时写入声明缺省，不按技能名。写了但不是整数时只出回看卡，不写 126。"""

        print("\n[TestAi04bDefaultInputs] 回看声明缺省")
        registry = build_default_registry()
        quiet = _planner().build_plan(_SCREEN, mode="plan")
        defaults = (quiet.assumptions or {}).get("slot_defaults") or {}
        predicate = _snap(quiet, "qt.ai.research.price_predicate")
        print(" quiet pending:", _names(quiet), "defaults:", defaults, "lookback:", predicate.get("lookback_days"))
        self.assertNotIn("lookback_days", _names(quiet))
        self.assertEqual(predicate.get("lookback_days"), 126)

        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            assistant.plan(_SCREEN, response_style="raw", session_id="lookback-default")
            loaded = assistant.session_store.load("lookback-default")
            slots = loaded.task.slots if loaded is not None and loaded.task is not None else {}
            lookback = slots.get("lookback_days")
            print(" session lookback:", getattr(lookback, "confirmed", None), getattr(lookback, "value", None))
            self.assertTrue(lookback is None or not lookback.confirmed)

        asked = _planner().build_plan(_SCREEN_BAD, mode="plan")
        predicate = _snap(asked, "qt.ai.research.price_predicate")
        print(" asked pending:", _names(asked), "lookback:", predicate.get("lookback_days"))
        self.assertNotIn("lookback_days", _names(asked))
        self.assertEqual(predicate.get("lookback_days"), 126)

        materialize_source = inspect.getsource(_judge_slots)
        dispatch_source = inspect.getsource(_slot_default_value)
        fill_source = inspect.getsource(
            __import__("qteasy_ai.slot_graph", fromlist=["_fill_graph"])._fill_graph
        )
        print(
            " skill name in writer:",
            "qt.ai.research.price_predicate" in materialize_source,
            "qt.ai.research.price_predicate" in dispatch_source,
            "qt.ai.research.price_predicate" in fill_source,
        )
        self.assertNotIn("qt.ai.research.price_predicate", materialize_source)
        self.assertNotIn("qt.ai.research.price_predicate", dispatch_source)
        self.assertNotIn("qt.ai.research.price_predicate", fill_source)
        self.assertNotIn("_apply_lookback_default", fill_source)
        self.assertNotIn("126", materialize_source)
        self.assertNotIn("126", dispatch_source)

    def test_window_phrase_keeps_date_card_and_benchmark(self) -> None:
        """窗口说法仍出日期卡。元素切分取出的基准已在步骤上，且不在持有里。"""

        print("\n[TestAi04bDefaultInputs] 日期卡与基准")
        plan = _planner().build_plan(_HOLD, mode="plan")
        portfolio = _snap(plan, "qt.ai.hp.portfolio")
        kline = _snap(plan, "qt.ai.data.kline")
        holdings = list(portfolio.get("holdings") or [])
        benchmark = portfolio.get("benchmark") or {}
        print(" pending:", _names(plan), "confirmable:", _confirmable(plan))
        print(" kline:", kline.get("start"), kline.get("end"), "asset:", kline.get("asset_type"))
        print(" benchmark:", benchmark, "holdings:", [item.get("code") for item in holdings])
        self.assertNotEqual(_names(plan), ["start", "end"])
        self.assertFalse(_confirmable(plan))
        self.assertNotIn("start", _names(plan))
        self.assertNotIn("end", _names(plan))
        self.assertNotEqual((benchmark or {}).get("code"), "000300.SH")
        self.assertFalse(holdings)
        self.assertNotIn("asset_type", _names(plan))
        self.assertNotIn("asset_type", kline)


if __name__ == "__main__":
    unittest.main()
