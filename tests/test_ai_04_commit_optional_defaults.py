# coding=utf-8
# ======================================
# File: test_ai_04_commit_optional_defaults.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-12
# Desc:
# 选填缺省：没提到就留缺省、不出卡；提到了却没有合法值才出题，缺省是选项。
# ======================================

import datetime
import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai import slot_graph
from qteasy_ai.slot_graph import _pending_after_fill, apply_ordered_answers

_GOLD = "600519 和 000858 做一条等权组合"
_WINDOW_DIGIT = "600519 和 000858 做一条等权组合，看过去3年的持仓收益率，并跟沪深300做一个对比"
_WINDOW_CN = "600519 和 000858 做一条等权组合，看过去三年的持仓收益率，并跟沪深300做一个对比"
_HISTORY = "get_history_data close for 000300.SH"
_HISTORY_WINDOW = "get_history_data close for 000300.SH，过去三年"
_SPAN = "600519 和 000858 做一条等权组合，看过去一段时间的持仓收益率，并跟沪深300做一个对比"
_SCREEN = "筛股 银行业 跌幅超过 10%"
_SCREEN_BAD = "筛股 回看 abc 跌 10% 银行业"
_DATE = re.compile(r"(?<!\d)20\d{6}(?!\d)")
_WINDOW_HINT = "Provide at least one of start or end. rows alone does not select a history window."


def _planner(replies: List[str] = None) -> Planner:
    """假模型或无模型的规划器。"""

    provider = FakeLLMProvider(replies=list(replies or [])) if replies is not None else None
    return Planner(build_default_registry(), provider=provider, env_facts={})


def _kernel_ends() -> Tuple[str, str]:
    """测试自己算的内核窗口：今天，以及今天减 365 天。不调用实现。"""

    today = datetime.date.today()
    end = today.strftime("%Y%m%d")
    start = (today - datetime.timedelta(days=365)).strftime("%Y%m%d")
    return start, end


def _three_year_ends() -> Tuple[str, str]:
    """今天减三年的两种写法，用来证明缺省标签不是这句话折出来的。"""

    today = datetime.date.today()
    try:
        calendar = today.replace(year=today.year - 3)
    except ValueError:
        calendar = today.replace(year=today.year - 3, day=28)
    by_days = today - datetime.timedelta(days=365 * 3)
    return calendar.strftime("%Y%m%d"), by_days.strftime("%Y%m%d")


def _confirmable(plan: Any) -> bool:
    """可见步骤里没有澄清回退。"""

    return "qt.ai.system.fallback" not in [step.skill_name for step in plan.steps]


def _pending(plan: Any) -> List[Dict[str, Any]]:
    """澄清卡上的题。"""

    blob = (plan.assumptions or {}).get("clarification") or {}
    return [item for item in (blob.get("pending") or []) if isinstance(item, dict)]


def _names(plan: Any) -> List[str]:
    """待答题名。"""

    return [str(item.get("name") or "") for item in _pending(plan)]


def _snap(plan: Any, skill: str) -> Dict[str, Any]:
    """快照或可见步骤上的 inputs。"""

    accepted = (plan.assumptions or {}).get("accepted_steps") or []
    for step in accepted:
        if str(step.get("skill_name") or "") == skill:
            return dict(step.get("inputs") or {})
    for step in plan.steps:
        if step.skill_name == skill:
            return dict(step.inputs or {})
    return {}


def _blob(plan: Any) -> str:
    """快照和可见步骤里的输入原文，用来找不该出现的日期。"""

    chunks = [json.dumps((plan.assumptions or {}).get("accepted_steps") or [], ensure_ascii=False)]
    chunks.append(
        json.dumps(
            [{"skill": step.skill_name, "inputs": dict(step.inputs or {})} for step in plan.steps],
            ensure_ascii=False,
        )
    )
    return "\n".join(chunks)


def _option(row: Dict[str, Any], option_id: str) -> Dict[str, Any]:
    """按 id 取一个选项。没有则空 dict。"""

    for item in row.get("options") or []:
        if str(item.get("id") or "") == option_id:
            return item
    return {}


def _raw_plan(result: Dict[str, Any]) -> Dict[str, Any]:
    """助手 raw 结果里的计划。"""

    plan = result.get("plan") or {}
    return plan if isinstance(plan, dict) else {}


class TestAi04CommitOptionalDefaults(unittest.TestCase):
    """提到了的选填槽不能带着缺省跳过。"""

    def test_equal_weight_without_window_keeps_kernel_dates(self) -> None:
        """等权金句没提窗口：可确认，日期不进待答，也不写进计划。"""

        print("\n[TestAi04OptionalDefaults] 等权金句无窗口")
        plan = _planner().build_plan(_GOLD, mode="plan")
        kline = _snap(plan, "qt.ai.data.kline")
        print(" confirmable:", _confirmable(plan), "pending:", _names(plan))
        print(" kline start:", kline.get("start"), "end:", kline.get("end"))
        self.assertTrue(_confirmable(plan))
        self.assertNotIn("start", _names(plan))
        self.assertNotIn("end", _names(plan))
        self.assertIn(kline.get("start"), (None, ""))
        self.assertIn(kline.get("end"), (None, ""))

    def test_window_phrase_asks_both_ends(self) -> None:
        """过去3年和过去三年都只出日期题，不把说法折成日期。"""

        print("\n[TestAi04OptionalDefaults] 窗口说法出两题")
        start, end = _kernel_ends()
        not_three = _three_year_ends()
        for query in (_WINDOW_DIGIT, _WINDOW_CN):
            plan = _planner().build_plan(query, mode="plan")
            portfolio = _snap(plan, "qt.ai.hp.portfolio")
            kline = _snap(plan, "qt.ai.data.kline")
            holdings = portfolio.get("holdings") or []
            benchmark = portfolio.get("benchmark") or {}
            rows = {str(item.get("name") or ""): item for item in _pending(plan)}
            print(" query:", query)
            print(" confirmable:", _confirmable(plan), "pending:", _names(plan))
            print(" holdings:", [item.get("code") for item in holdings], "mode:", portfolio.get("mode"))
            print(" benchmark:", benchmark)
            print(" kline dates:", kline.get("start"), kline.get("end"))
            print(
                " prompts:",
                {name: (rows.get(name) or {}).get("prompt") for name in ("start", "end")},
            )
            self.assertFalse(_confirmable(plan))
            self.assertEqual([item.get("code") for item in holdings], ["600519.SH", "000858.SZ"])
            self.assertTrue(all(item.get("status") == "confirmed" for item in holdings))
            self.assertEqual((benchmark or {}).get("code"), "000300.SH")
            self.assertNotIn("000300.SH", [item.get("code") for item in holdings])
            self.assertEqual(portfolio.get("mode"), "equal")
            self.assertEqual(_names(plan), ["start", "end"])
            self.assertIsNone(_DATE.search(str(kline.get("start") or "")))
            self.assertIsNone(_DATE.search(str(kline.get("end") or "")))
            for name, label in (("start", start), ("end", end)):
                row = rows[name]
                option = _option(row, "default")
                print(" option:", name, option, "open:", row.get("open"))
                self.assertTrue(str(row.get("prompt") or "").strip())
                self.assertEqual(option.get("id"), "default")
                self.assertEqual(option.get("label"), label)
                self.assertNotIn(option.get("label"), not_three)
                self.assertEqual((row.get("open") or {}).get("label"), "其它")

    def test_default_answers_write_kernel_window(self) -> None:
        """两题都选 default，写入测试自己算出的内核窗口，计划这才可确认。"""

        print("\n[TestAi04OptionalDefaults] 两题都交缺省")
        start, end = _kernel_ends()
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            first = assistant.plan(_WINDOW_DIGIT, response_style="raw", session_id="s-default")
            rows = ((_raw_plan(first).get("assumptions") or {}).get("clarification") or {}).get("pending") or []
            print(" first prompts:", [(item.get("name"), item.get("prompt"), item.get("default_value")) for item in rows])
            self.assertEqual([item.get("name") for item in rows], ["start", "end"])
            second = assistant.plan("", response_style="raw", session_id="s-default", answers=["default", "default"])
            plan = _raw_plan(second)
            skills = [step.get("skill_name") for step in (plan.get("steps") or [])]
            kline = next(
                (step.get("inputs") or {} for step in (plan.get("steps") or []) if step.get("skill_name") == "qt.ai.data.kline"),
                {},
            )
            portfolio = next(
                (step.get("inputs") or {} for step in (plan.get("steps") or []) if step.get("skill_name") == "qt.ai.hp.portfolio"),
                {},
            )
            print(" skills:", skills)
            print(" written:", kline.get("start"), kline.get("end"))
            print(" holdings:", [item.get("code") for item in (portfolio.get("holdings") or [])])
            self.assertNotIn("qt.ai.system.fallback", skills)
            self.assertEqual(kline.get("start"), start)
            self.assertEqual(kline.get("end"), end)
            self.assertEqual(
                [item.get("code") for item in (portfolio.get("holdings") or [])],
                ["600519.SH", "000858.SZ"],
            )

    def test_open_date_keeps_typed_digits(self) -> None:
        """开放输入的 8 位日期先过校验，通过后不替换成缺省。"""

        print("\n[TestAi04OptionalDefaults] 开放输入日期")
        _start, end = _kernel_ends()
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            first = assistant.plan(_WINDOW_DIGIT, response_style="raw", session_id="s-open")
            rows = ((_raw_plan(first).get("assumptions") or {}).get("clarification") or {}).get("pending") or []
            print(" examples:", [(item.get("name"), item.get("example")) for item in rows])
            self.assertEqual([item.get("name") for item in rows], ["start", "end"])
            self.assertNotEqual("20200101", str(rows[0].get("example") or ""))
            second = assistant.plan("", response_style="raw", session_id="s-open", answers=["20200101", "default"])
            plan = _raw_plan(second)
            kline = next(
                (step.get("inputs") or {} for step in (plan.get("steps") or []) if step.get("skill_name") == "qt.ai.data.kline"),
                {},
            )
            print(" written:", kline.get("start"), kline.get("end"))
            self.assertEqual(kline.get("start"), "20200101")
            self.assertNotEqual(kline.get("start"), _start)
            self.assertEqual(kline.get("end"), end)

    def test_model_omits_dates_and_null_asks(self) -> None:
        """协议没交日期键就当没提到；交成 null 才出日期卡。"""

        print("\n[TestAi04OptionalDefaults] 协议缺键与 null")
        holdings = [
            {"mention": "600519", "code": "600519.SH"},
            {"mention": "000858", "code": "000858.SZ"},
        ]
        benchmark = {"mention": "沪深300", "code": "000300.SH"}
        omitted = _planner(
            [
                json.dumps({"job": "research.hold_compare"}),
                json.dumps({"holdings": holdings, "benchmark": benchmark, "mode": "equal"}),
            ]
        ).build_plan(_WINDOW_DIGIT, mode="plan")
        print(" omitted pending:", _names(omitted), "confirmable:", _confirmable(omitted))
        self.assertNotIn("start", _names(omitted))
        self.assertNotIn("end", _names(omitted))
        self.assertTrue(_confirmable(omitted))

        nulled = _planner(
            [
                json.dumps({"job": "research.hold_compare"}),
                json.dumps(
                    {
                        "holdings": holdings,
                        "benchmark": benchmark,
                        "mode": "equal",
                        "start": None,
                        "end": None,
                    }
                ),
            ]
        ).build_plan(_WINDOW_DIGIT, mode="plan")
        kline = _snap(nulled, "qt.ai.data.kline")
        rows = {str(item.get("name") or ""): item for item in _pending(nulled)}
        print(" null pending:", _names(nulled), "dates:", kline.get("start"), kline.get("end"))
        self.assertEqual(_names(nulled), ["start", "end"])
        self.assertFalse(_confirmable(nulled))
        self.assertIsNone(_DATE.search(_blob(nulled)))
        self.assertEqual(_option(rows["start"], "default").get("id"), "default")
        self.assertEqual(_option(rows["end"], "default").get("id"), "default")

    def test_lookback_sentinel(self) -> None:
        """没提回看就写入 126；回看 abc 只出回看题，缺省选项是 126。"""

        print("\n[TestAi04OptionalDefaults] 回看哨兵")
        quiet = _planner().build_plan(_SCREEN, mode="plan")
        predicate = _snap(quiet, "qt.ai.research.price_predicate")
        print(" quiet pending:", _names(quiet), "lookback:", predicate.get("lookback_days"))
        self.assertNotIn("lookback_days", _names(quiet))
        self.assertNotIn("start", _names(quiet))
        self.assertNotIn("end", _names(quiet))
        self.assertEqual(predicate.get("lookback_days"), 126)

        asked = _planner().build_plan(_SCREEN_BAD, mode="plan")
        rows = [item for item in _pending(asked) if item.get("name") == "lookback_days"]
        print(" asked names:", _names(asked))
        print(" lookback row:", rows[0] if rows else None)
        self.assertEqual(_names(asked), ["lookback_days"])
        self.assertTrue(str(rows[0].get("prompt") or "").strip())
        option = _option(rows[0], "default")
        self.assertEqual(option.get("id"), "default")
        self.assertEqual(str(option.get("label")), "126")
        self.assertFalse(any(_DATE.search(str(item.get("label") or "")) for item in (rows[0].get("options") or [])))
        self.assertNotEqual(rows[0].get("format"), "YYYYMMDD")
        self.assertNotIn("start", _names(asked))
        self.assertNotIn("end", _names(asked))

        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            assistant.plan(_SCREEN_BAD, response_style="raw", session_id="s-lookback")
            second = assistant.plan("", response_style="raw", session_id="s-lookback", answers=["default"])
            plan = _raw_plan(second)
            skills = [step.get("skill_name") for step in (plan.get("steps") or [])]
            written = next(
                (
                    step.get("inputs") or {}
                    for step in (plan.get("steps") or [])
                    if step.get("skill_name") == "qt.ai.research.price_predicate"
                ),
                {},
            )
            print(" after default skills:", skills, "lookback:", written.get("lookback_days"))
            self.assertNotIn("qt.ai.system.fallback", skills)
            self.assertEqual(written.get("lookback_days"), 126)

    def test_history_window_phrase(self) -> None:
        """历史取数没提窗口不出日期题；过去三年才出，且两端题面不同。"""

        print("\n[TestAi04OptionalDefaults] 历史取数窗口")
        start, end = _kernel_ends()
        not_three = _three_year_ends()
        quiet = _planner().build_plan(_HISTORY, mode="plan")
        history = _snap(quiet, "qt.ai.data.history")
        print(" quiet job:", quiet.planner_trace.get("intent_job"), "pending:", _names(quiet))
        print(" quiet dates:", history.get("start"), history.get("end"), "confirmable:", _confirmable(quiet))
        self.assertEqual(quiet.planner_trace.get("intent_job"), "data.read")
        self.assertEqual(quiet.steps[0].skill_name, "qt.ai.data.history")
        self.assertTrue(_confirmable(quiet))
        self.assertNotIn("start", _names(quiet))
        self.assertNotIn("end", _names(quiet))
        self.assertIn(history.get("start"), (None, ""))
        self.assertIn(history.get("end"), (None, ""))

        asked = _planner().build_plan(_HISTORY_WINDOW, mode="plan")
        rows = {str(item.get("name") or ""): item for item in _pending(asked)}
        fetched = _snap(asked, "qt.ai.data.history")
        print(" asked pending:", _names(asked))
        print(" fetched dates:", fetched.get("start"), fetched.get("end"))
        self.assertEqual(asked.planner_trace.get("intent_job"), "data.read")
        self.assertEqual(_names(asked), ["start", "end"])
        self.assertIsNone(_DATE.search(_blob(asked)))
        self.assertNotEqual(rows["start"].get("label"), rows["end"].get("label"))
        self.assertNotEqual(rows["start"].get("hint"), rows["end"].get("hint"))
        self.assertNotEqual(rows["start"].get("example"), rows["end"].get("example"))
        self.assertEqual(rows["start"].get("format"), "YYYYMMDD")
        self.assertEqual(rows["end"].get("format"), "YYYYMMDD")
        self.assertIn(_WINDOW_HINT, str(rows["start"].get("constraint") or ""))
        self.assertIn(_WINDOW_HINT, str(rows["end"].get("constraint") or ""))
        self.assertNotIn(_WINDOW_HINT, str(rows["start"].get("hint") or ""))
        self.assertNotIn(_WINDOW_HINT, str(rows["end"].get("hint") or ""))
        for name, label in (("start", start), ("end", end)):
            row = rows[name]
            option = _option(row, "default")
            print(" history option:", name, row.get("prompt"), option, row.get("open"))
            self.assertTrue(str(row.get("prompt") or "").strip())
            self.assertEqual(option.get("id"), "default")
            self.assertEqual(option.get("label"), label)
            self.assertNotIn(option.get("label"), not_three)
            self.assertEqual((row.get("open") or {}).get("label"), "其它")

    def test_same_ask_for_hold_compare_and_open(self) -> None:
        """同一条出题函数不按任务名区分持有对比和开放图。"""

        print("\n[TestAi04OptionalDefaults] 同一条出题函数")
        slots = [
            {
                "name": "start",
                "type": "string",
                "required": False,
                "enum": [],
                "filled": False,
                "format": "YYYYMMDD",
                "label": "Start date",
                "hint": "The first day of the range.",
                "example": "20250101",
                "default_kind": "kernel_window",
            },
            {
                "name": "end",
                "type": "string",
                "required": False,
                "enum": [],
                "filled": False,
                "format": "YYYYMMDD",
                "label": "End date",
                "hint": "The last day of the range.",
                "example": "20251231",
                "default_kind": "kernel_window",
            },
        ]
        hold = _pending_after_fill(
            slots, [], [], {}, _WINDOW_CN, set(), set(), "research.hold_compare", {"start", "end"}
        )
        opened = _pending_after_fill(
            slots, [], [], {}, _WINDOW_CN, set(), set(), "open", {"start", "end"}
        )
        print(" hold:", [(item.get("name"), _option(item, "default")) for item in hold])
        print(" open:", [(item.get("name"), _option(item, "default")) for item in opened])
        self.assertEqual(hold, opened)
        self.assertEqual([item.get("name") for item in hold], ["start", "end"])
        self.assertTrue(all(_option(item, "default").get("id") == "default" for item in hold))


def _raw_inputs(plan: Dict[str, Any], skill: str) -> Dict[str, Any]:
    """raw 计划里某个技能的 inputs。"""

    groups = [plan.get("steps") or []]
    groups.append((plan.get("assumptions") or {}).get("accepted_steps") or [])
    for steps in groups:
        for step in steps:
            if isinstance(step, dict) and step.get("skill_name") == skill:
                inputs = step.get("inputs") or {}
                return inputs if isinstance(inputs, dict) else {}
    return {}


def _raw_pending(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """raw 计划澄清卡上的题。"""

    blob = (plan.get("assumptions") or {}).get("clarification") or {}
    return [item for item in (blob.get("pending") or []) if isinstance(item, dict)]


def _func_body(name: str) -> str:
    """从 slot_graph 源码里切出一个顶层函数。"""

    src = Path(slot_graph.__file__).read_text(encoding="utf-8")
    start = src.index(f"\ndef {name}(")
    nxt = src.find("\ndef ", start + 1)
    return src[start:] if nxt < 0 else src[start:nxt]


class TestAi04DateCardAnswers(unittest.TestCase):
    """日期卡只绑定原文，解释者读这一题，再过同一份校验。"""

    def _open_dates(self, assistant: QteasyAssistant, sid: str) -> List[Dict[str, Any]]:
        """代码已确定的窗口句，第一张卡应是开始日和结束日。"""

        first = assistant.plan(_SPAN, response_style="raw", session_id=sid)
        rows = _raw_pending(_raw_plan(first))
        print(" first pending:", [(item.get("name"), item.get("example")) for item in rows])
        self.assertEqual([item.get("name") for item in rows], ["start", "end"])
        return rows

    def test_example_date_is_kept_when_the_user_typed_it(self) -> None:
        """用户输入的例子日期要留下，同一轮不能再用任务原句清掉。"""

        print("\n[TestAi04DateCard] 例子日期照收")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            rows = self._open_dates(assistant, "s-example")
            answers = ["20250101", "20261010"]
            folded = apply_ordered_answers(rows, answers)
            print(" answers:", answers)
            print(" folded:", folded)
            self.assertEqual((folded or {}).get("start"), "20250101")
            self.assertEqual((folded or {}).get("end"), "20261010")
            second = assistant.plan("", response_style="raw", session_id="s-example", answers=answers)
            plan = _raw_plan(second)
            kline = _raw_inputs(plan, "qt.ai.data.kline")
            portfolio = _raw_inputs(plan, "qt.ai.hp.portfolio")
            holdings = [item.get("code") for item in (portfolio.get("holdings") or [])]
            print(" confirmable:", "qt.ai.system.fallback" not in [step.get("skill_name") for step in plan.get("steps") or []])
            print(" written:", kline.get("start"), kline.get("end"))
            print(" holdings:", holdings, "benchmark:", (portfolio.get("benchmark") or {}).get("code"))
            self.assertNotIn("qt.ai.system.fallback", [step.get("skill_name") for step in plan.get("steps") or []])
            self.assertEqual(kline.get("start"), "20250101")
            self.assertEqual(kline.get("end"), "20261010")
            self.assertEqual(holdings, ["600519.SH", "000858.SZ"])
            self.assertEqual((portfolio.get("benchmark") or {}).get("code"), "000300.SH")

    def test_unparsed_chinese_date_returns_to_the_same_question(self) -> None:
        """无模型解释不出中文日期时，只问这一题并带 error。"""

        print("\n[TestAi04DateCard] 中文日期回到同一题")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            rows = self._open_dates(assistant, "s-cn")
            answers = ["2025年4月5日", "2026-11-10"]
            folded = apply_ordered_answers(rows, answers)
            print(" answers:", answers)
            print(" folded:", folded)
            self.assertEqual((folded or {}).get("start"), "2025年4月5日")
            self.assertNotIn("202545", str(folded))
            second = assistant.plan("", response_style="raw", session_id="s-cn", answers=answers)
            plan = _raw_plan(second)
            kline = _raw_inputs(plan, "qt.ai.data.kline")
            pending = _raw_pending(plan)
            print(" written:", kline.get("start"), kline.get("end"))
            print(" next:", [(item.get("name"), item.get("error")) for item in pending])
            self.assertEqual(kline.get("end"), "20261110")
            self.assertNotEqual(kline.get("start"), "20250101")
            self.assertIn(kline.get("start"), (None, ""))
            self.assertEqual([item.get("name") for item in pending], ["start"])
            self.assertIn("2025年4月5日", str(pending[0].get("error") or ""))
            loaded = assistant.session_store.load("s-cn")
            start_slot = (loaded.task.slots or {}).get("start") if loaded is not None and loaded.task is not None else None
            print(" start slot:", None if start_slot is None else (start_slot.value, start_slot.confirmed))
            self.assertTrue(start_slot is None or not start_slot.confirmed)
            self.assertNotEqual(getattr(start_slot, "value", None), "202545")

    def test_impossible_calendar_day_returns_with_error(self) -> None:
        """8 位但不是日历日的开始日不收下。"""

        print("\n[TestAi04DateCard] 非法日历")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            self._open_dates(assistant, "s-bad")
            second = assistant.plan(
                "",
                response_style="raw",
                session_id="s-bad",
                answers=["20251340", "20261010"],
            )
            plan = _raw_plan(second)
            kline = _raw_inputs(plan, "qt.ai.data.kline")
            pending = _raw_pending(plan)
            print(" written:", kline.get("start"), kline.get("end"))
            print(" next:", [(item.get("name"), item.get("error")) for item in pending])
            self.assertIn(kline.get("start"), (None, ""))
            self.assertEqual(kline.get("end"), "20261010")
            self.assertEqual([item.get("name") for item in pending], ["start"])
            self.assertIn("20251340", str(pending[0].get("error") or ""))

    def test_model_reads_the_card_text(self) -> None:
        """交卷后的第一则填槽协议只含这一题原文。"""

        print("\n[TestAi04DateCard] 有模型读卡片原文")
        provider = FakeLLMProvider(
            replies=[json.dumps({"start": "20250405", "end": "20261110"})]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            self._open_dates(assistant, "s-model")
            assistant.apply_provider(provider)
            second = assistant.plan(
                "",
                response_style="raw",
                session_id="s-model",
                answers=["2025年4月5日", "2026-11-10"],
            )
            plan = _raw_plan(second)
            kline = _raw_inputs(plan, "qt.ai.data.kline")
            portfolio = _raw_inputs(plan, "qt.ai.hp.portfolio")
            prompt = provider.prompts[0] if provider.prompts else ""
            print(" prompts:", len(provider.prompts))
            print(" prompt:", prompt)
            print(" written:", kline.get("start"), kline.get("end"))
            print(" holdings:", [item.get("code") for item in (portfolio.get("holdings") or [])])
            self.assertIn("2025年4月5日", prompt)
            self.assertNotIn("过去一段时间", prompt)
            self.assertNotIn("Parse these clarification answers", prompt)
            self.assertEqual(kline.get("start"), "20250405")
            self.assertEqual(kline.get("end"), "20261110")
            self.assertNotIn("qt.ai.system.fallback", [step.get("skill_name") for step in plan.get("steps") or []])
            self.assertEqual(
                [item.get("code") for item in (portfolio.get("holdings") or [])],
                ["600519.SH", "000858.SZ"],
            )

    def test_model_omits_one_date_and_asks_only_that_one(self) -> None:
        """协议没交的是这张卡上的日期槽，下一张卡只问它并带 error。"""

        print("\n[TestAi04DateCard] 协议只交结束日")
        provider = FakeLLMProvider(replies=[json.dumps({"end": "20261110"})])
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            self._open_dates(assistant, "s-one")
            assistant.apply_provider(provider)
            second = assistant.plan(
                "",
                response_style="raw",
                session_id="s-one",
                answers=["2025年4月5日", "2026-11-10"],
            )
            plan = _raw_plan(second)
            pending = _raw_pending(plan)
            print(" next:", [(item.get("name"), item.get("error")) for item in pending])
            print(" skills:", [step.get("skill_name") for step in plan.get("steps") or []])
            self.assertEqual([item.get("name") for item in pending], ["start"])
            self.assertIn("2025年4月5日", str(pending[0].get("error") or ""))
            self.assertIn("qt.ai.system.fallback", [step.get("skill_name") for step in plan.get("steps") or []])

    def test_sentence_review_and_card_share_one_date_checker(self) -> None:
        """原句复核和卡片交卷调用同一份日期校验，折叠里不再剥数字。"""

        print("\n[TestAi04DateCard] 唯一一份日期校验")
        legal = _func_body("_submitted_legal")
        review = _func_body("_review_submission")
        folded = _func_body("apply_ordered_answers")
        print(" legal calls:", "accept_yyyymmdd(" in legal)
        print(" review calls:", "accept_yyyymmdd(" in review)
        print(" fold strips:", 're.sub(r"\\D"' in folded)
        self.assertIn("def accept_yyyymmdd(", Path(slot_graph.__file__).read_text(encoding="utf-8"))
        self.assertIn("accept_yyyymmdd(", legal)
        self.assertIn("accept_yyyymmdd(", review)
        self.assertNotIn('re.sub(r"\\D"', folded)


if __name__ == "__main__":
    unittest.main()
