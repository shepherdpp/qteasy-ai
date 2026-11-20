# coding=utf-8
# ======================================
# File: test_ai_04_touched_without_value.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-20
# Desc:
# 有模型的修改句只信协议：补出的日期不写入，null 出日期卡，
# 持有多一项且没有代码时只问这项。
# ======================================

import inspect
import json
import tempfile
import unittest
from typing import Any, Dict, List

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.slot_graph import _read_model_revision, accept_yyyymmdd, kernel_window

_READY = "600519 和 000858 做一条等权组合"
_PAST = "起止时间改为过去两年"
_BANK = "增加一只股票：兴业银行"


def _assistant(temp_dir: str) -> QteasyAssistant:
    """无模型助手，计划落在临时目录。"""

    return QteasyAssistant(
        registry=build_default_registry(),
        memory_store=MemoryStore(base_dir=temp_dir),
    )


def _plan(result: Dict[str, Any]) -> Dict[str, Any]:
    """raw 结果里的计划。"""

    plan = result.get("plan") or {}
    return plan if isinstance(plan, dict) else {}


def _pending(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """澄清卡上的题。"""

    card = (plan.get("assumptions") or {}).get("clarification") or {}
    return [item for item in (card.get("pending") or []) if isinstance(item, dict)]


def _inputs(plan: Dict[str, Any], skill: str) -> Dict[str, Any]:
    """快照或可见步骤上的 inputs。"""

    accepted = (plan.get("assumptions") or {}).get("accepted_steps") or []
    for step in accepted:
        if str(step.get("skill_name") or "") == skill:
            return dict(step.get("inputs") or {})
    for step in plan.get("steps") or []:
        if str(step.get("skill_name") or "") == skill:
            return dict(step.get("inputs") or {})
    return {}


def _confirmable(plan: Dict[str, Any]) -> bool:
    """有真实步骤，且没有澄清回退、也没有待答题。"""

    skills = [str(step.get("skill_name") or "") for step in (plan.get("steps") or [])]
    if not skills:
        return False
    return "qt.ai.system.fallback" not in skills and not _pending(plan)


def _fill_prompt(provider: FakeLLMProvider) -> str:
    """这一轮里的填槽协议。润色卡不是它。"""

    for prompt in provider.prompts:
        if prompt.startswith("Slot protocol."):
            return prompt
    return ""


def _replies(sentence: str, payload: Dict[str, Any]) -> List[str]:
    """拆句、分类、填槽三则固定协议。"""

    return [
        json.dumps({"task": sentence, "question": ""}, ensure_ascii=False),
        json.dumps({"job": "research.hold_compare"}),
        json.dumps(payload, ensure_ascii=False),
    ]


class TestAi04TouchedWithoutValue(unittest.TestCase):
    """点到了却没有合法值。只走固定协议。"""

    def test_source_must_name_the_date(self) -> None:
        """原文收不成的八位不写入。已写下的八位、年月日和到某年仍收下。"""

        print("\n[TestAi04TouchedWithoutValue] 日期质检")
        invented = accept_yyyymmdd("20240507", "20250101", _PAST)
        written = accept_yyyymmdd("20250405", "20250101", "2025年4月5日")
        dashed = accept_yyyymmdd("20261110", "20251231", "2026-11-10")
        example_day = accept_yyyymmdd("20250101", "20250101", "2025年1月1日")
        end_only = accept_yyyymmdd("20231231", "20251231", "到 2023 年")
        not_start = accept_yyyymmdd("20230101", "20250101", "到 2023 年")
        already = accept_yyyymmdd("20250101", "20250101", "20250101")
        print(" invented:", invented, "written:", written, "dashed:", dashed)
        print(" example day:", example_day, "end only:", end_only, "not start:", not_start)
        print(" already written:", already)
        self.assertIsNone(invented)
        self.assertEqual(written, "20250405")
        self.assertEqual(dashed, "20261110")
        self.assertEqual(example_day, "20250101")
        self.assertEqual(end_only, "20231231")
        self.assertIsNone(not_start)
        self.assertEqual(already, "20250101")

    def test_invented_dates_are_not_written(self) -> None:
        """协议补出的起止不落在步骤上，也不写回内核窗口。"""

        print("\n[TestAi04TouchedWithoutValue] 补出的日期")
        sentence = _PAST
        payload = {"start": "20240507", "end": "20260507"}
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir)
            first = assistant.plan(_READY, response_style="raw", session_id="s-invented")
            opened = _plan(first)
            portfolio = _inputs(opened, "qt.ai.hp.portfolio")
            kline = _inputs(opened, "qt.ai.data.kline")
            window = kernel_window()
            holdings = list(portfolio.get("holdings") or [])
            print(" before holdings:", holdings)
            print(" before dates:", kline.get("start"), kline.get("end"), "kernel:", window)
            print(" before confirmable:", _confirmable(opened), "pending:", _pending(opened))
            self.assertTrue(_confirmable(opened))
            self.assertEqual([item.get("code") for item in holdings], ["600519.SH", "000858.SZ"])
            self.assertEqual(kline.get("start"), window["start"])
            self.assertEqual(kline.get("end"), window["end"])
            provider = FakeLLMProvider(replies=_replies(sentence, payload))
            assistant.apply_provider(provider)
            second = assistant.plan(sentence, response_style="raw", session_id="s-invented")
            plan = _plan(second)
            revised = _inputs(plan, "qt.ai.data.kline")
            pending = _pending(plan)
            fill = _fill_prompt(provider)
            print(" prompts:", len(provider.prompts))
            print(" fill:", fill)
            print(" dates:", revised.get("start"), revised.get("end"))
            print(" confirmable:", _confirmable(plan))
            print(" pending:", [(item.get("name"), item.get("prompt")) for item in pending])
            self.assertIn(sentence, fill)
            self.assertNotIn(_READY, fill)
            self.assertNotIn(revised.get("start"), ("20240507", window["start"]))
            self.assertNotIn(revised.get("end"), ("20260507", window["end"]))
            self.assertIn(revised.get("start"), (None, ""))
            self.assertIn(revised.get("end"), (None, ""))
            self.assertFalse(_confirmable(plan))
            self.assertEqual([item.get("name") for item in pending], ["start", "end"])

    def test_null_dates_ask_and_keep_kernel_off_the_steps(self) -> None:
        """协议对起止交回 null：出日期卡，缺省是选项，内核窗口不写回。"""

        print("\n[TestAi04TouchedWithoutValue] 日期 null")
        sentence = _PAST
        payload = {"start": None, "end": None}
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir)
            assistant.plan(_READY, response_style="raw", session_id="s-null")
            provider = FakeLLMProvider(replies=_replies(sentence, payload))
            assistant.apply_provider(provider)
            second = assistant.plan(sentence, response_style="raw", session_id="s-null")
            plan = _plan(second)
            kline = _inputs(plan, "qt.ai.data.kline")
            pending = _pending(plan)
            window = kernel_window()
            fill = _fill_prompt(provider)
            print(" dates:", kline.get("start"), kline.get("end"), "kernel:", window)
            print(" fill:", fill)
            print(" confirmable:", _confirmable(plan))
            print(
                " pending:",
                [
                    (item.get("name"), item.get("prompt"), item.get("options"), item.get("default_value"))
                    for item in pending
                ],
            )
            self.assertIn(sentence, fill)
            self.assertNotIn(_READY, fill)
            self.assertIn(kline.get("start"), (None, ""))
            self.assertIn(kline.get("end"), (None, ""))
            self.assertNotEqual(kline.get("start"), window["start"])
            self.assertNotEqual(kline.get("end"), window["end"])
            self.assertFalse(_confirmable(plan))
            self.assertEqual([item.get("name") for item in pending], ["start", "end"])
            for item in pending:
                options = item.get("options") or []
                print(" options:", item.get("name"), options)
                self.assertTrue(any(str(option.get("id")) == "default" for option in options))

    def test_extra_holding_without_code_is_the_only_question(self) -> None:
        """原来两项仍已确认。多出来的没有代码的一项单独出卡。"""

        print("\n[TestAi04TouchedWithoutValue] 持有多一项")
        sentence = _BANK
        payload = {
            "holdings": [
                {"mention": "600519", "code": "600519.SH", "status": "confirmed"},
                {"mention": "000858", "code": "000858.SZ", "status": "confirmed"},
                {"mention": "兴业银行"},
            ]
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir)
            assistant.plan(_READY, response_style="raw", session_id="s-bank")
            provider = FakeLLMProvider(replies=_replies(sentence, payload))
            assistant.apply_provider(provider)
            second = assistant.plan(sentence, response_style="raw", session_id="s-bank")
            plan = _plan(second)
            holdings = list(_inputs(plan, "qt.ai.hp.portfolio").get("holdings") or [])
            pending = _pending(plan)
            fill = _fill_prompt(provider)
            print(" holdings:", holdings)
            print(" fill:", fill)
            print(" confirmable:", _confirmable(plan))
            print(
                " pending:",
                [
                    (item.get("name"), item.get("index"), item.get("mention"), item.get("prompt"))
                    for item in pending
                ],
            )
            self.assertIn(sentence, fill)
            self.assertNotIn(_READY, fill)
            self.assertEqual([item.get("code") for item in holdings[:2]], ["600519.SH", "000858.SZ"])
            self.assertTrue(all(item.get("status") == "confirmed" for item in holdings[:2]))
            self.assertEqual(holdings[2].get("mention"), "兴业银行")
            self.assertIn(holdings[2].get("code"), (None, ""))
            self.assertNotEqual(holdings[2].get("status"), "confirmed")
            self.assertFalse(_confirmable(plan))
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].get("index"), 2)
            self.assertEqual(pending[0].get("mention"), "兴业银行")
            self.assertNotIn("600519", str(pending[0].get("prompt") or ""))
            self.assertNotIn("000858", str(pending[0].get("prompt") or ""))

    def test_revision_entry_keeps_literals_in_the_checkers(self) -> None:
        """修改句入口不复制日期格式、后缀和公司名。"""

        print("\n[TestAi04TouchedWithoutValue] 源码守卫")
        body = inspect.getsource(_read_model_revision)
        banned = (
            "YYYYMMDD",
            "%Y%m%d",
            ".SH",
            "过去两年",
            "兴业银行",
            "贵州茅台",
            "_apply_sentence_values",
            "window_phrase",
            "_enumerate_pieces",
        )
        for token in banned:
            print(" guard:", token, token in body)
            self.assertNotIn(token, body)


if __name__ == "__main__":
    unittest.main()
