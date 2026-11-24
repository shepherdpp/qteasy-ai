# coding=utf-8
# ======================================
# File: test_ai_04_match_notice.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-19
# Desc:
# 第十步：匹配说明只投影计划记录里的任务、来源和理由。
# 不重新分类。确认开放图的语言看计划上的原句。
# ======================================

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.human_card import project_human_cards
from qteasy_ai.match_notice import render_match_notice
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.provider import FakeLLMProvider

_HOLD = "600519 和 000858 做一条等权组合"
_WEATHER = "请帮我看看天气"
_OPEN_ZH = "取 000300.SH 日线，算收益，再出一页图，请生成一个简短的开放计划"
_STEPS = [
    {"skill_name": "qt.ai.data.kline", "inputs": {"shares": "000300.SH"}},
    {"skill_name": "qt.ai.hp.returns", "inputs": {}, "depends_on": ["step_1"]},
    {"skill_name": "qt.ai.hp.plot", "inputs": {"page": 1}, "depends_on": ["step_2"]},
]
_TOO_MANY = _STEPS + [
    {"skill_name": "qt.ai.hp.volatility", "inputs": {}, "depends_on": ["step_2"]},
]


def _plan_payload(
    trace: Dict[str, Any],
    *,
    user_query: str,
    steps: Optional[List[Dict[str, Any]]] = None,
    clarification: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """一份只用于展示的计划记录。"""

    plan: Dict[str, Any] = {
        "plan_id": "plan_match",
        "user_query": user_query,
        "planner_trace": dict(trace),
        "steps": list(steps or []),
    }
    payload: Dict[str, Any] = {
        "plan": plan,
        "execution": {"status": "dry_run", "steps": []},
    }
    if clarification is not None:
        payload["clarification"] = clarification
    return payload


def _match_cards(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """``stage_id=match`` 的说明卡。"""

    return [
        item
        for item in cards
        if item.get("kind") == "mode_notice" and (item.get("payload") or {}).get("stage_id") == "match"
    ]


class TestAi04MatchNoticeDisplay(unittest.TestCase):
    """三份记录的展示，不调用分类。"""

    def test_hold_compare_notice_copies_the_record(self) -> None:
        """持有对比的说明只含记录里的任务种类。"""

        print("\n[TestAi04MatchNotice] 持有对比投影")
        trace = {
            "intent_job": "research.hold_compare",
            "source": "rule",
            "rationale": "portfolio_compare",
        }
        text = render_match_notice(trace, chinese=True)
        print(" trace:", trace)
        print(" text:", text)
        self.assertEqual(text, "任务 research.hold_compare。来源 rule。理由 portfolio_compare。")
        self.assertNotIn("clarify", text)
        self.assertNotIn("open", text)
        self.assertNotIn("strategy.meta", text)
        cards = project_human_cards(
            _plan_payload(
                trace,
                user_query=_HOLD,
                steps=[{"step_id": "step_1", "skill_name": "qt.ai.hp.portfolio", "inputs": {}}],
            ),
            requested_mode="plan",
            query=_HOLD,
        )
        ready = next(item for item in cards if item.get("kind") == "plan_ready")
        notices = _match_cards(cards)
        print(" ready has Job:", "Job:" in str(ready.get("text") or ""))
        print(" notice:", [item.get("text") for item in notices])
        self.assertNotIn("Job:", str(ready.get("text") or ""))
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].get("text"), text)

    def test_unmatched_notice_names_clarify_not_another_job(self) -> None:
        """未匹配说明写记录里的 clarify 和理由。"""

        print("\n[TestAi04MatchNotice] 未匹配投影")
        trace = {"intent_job": "clarify", "source": "rule", "rationale": "llm_uncertain"}
        text = render_match_notice(trace, chinese=True)
        print(" trace:", trace)
        print(" text:", text)
        self.assertIn("clarify", text)
        self.assertIn("llm_uncertain", text)
        self.assertNotIn("research.hold_compare", text)
        self.assertNotIn("open", text)
        cards = project_human_cards(
            _plan_payload(
                trace,
                user_query=_WEATHER,
                clarification={
                    "confirm_prompt": "请改写需求。",
                    "pending": [{"name": "unresolved_intent", "prompt": "请改写需求。"}],
                },
            ),
            requested_mode="plan",
            query=_WEATHER,
        )
        kinds = [item.get("kind") for item in cards]
        notices = _match_cards(cards)
        print(" kinds:", kinds)
        print(" notice:", [item.get("text") for item in notices])
        self.assertIn("clarify", kinds)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].get("text"), text)

    def test_open_confirm_uses_plan_user_query_language(self) -> None:
        """贴卡 query 为空时，语言仍看计划上的中文原句。"""

        print("\n[TestAi04MatchNotice] 开放图空 query")
        trace = {
            "intent_job": "open",
            "source": "user",
            "rationale": "unresolved_compose_open",
        }
        text = render_match_notice(trace, chinese=True)
        print(" trace:", trace)
        print(" text:", text)
        self.assertIn("open", text)
        self.assertIn("user", text)
        self.assertIn("unresolved_compose_open", text)
        self.assertNotIn("research.hold_compare", text)
        self.assertNotIn("clarify", text)
        self.assertNotIn("Task ", text)
        cards = project_human_cards(
            _plan_payload(
                trace,
                user_query=_OPEN_ZH,
                steps=[{"step_id": "step_1", "skill_name": "qt.ai.data.kline", "inputs": {}}],
            ),
            requested_mode="plan",
            query="",
        )
        notices = _match_cards(cards)
        print(" notice:", [item.get("text") for item in notices])
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].get("text"), text)
        self.assertTrue(str(notices[0].get("text") or "").startswith("任务 "))

    def test_rejected_open_graph_notice_sticks_to_the_error_card(self) -> None:
        """超步数走错误卡，说明跟着记录写成 clarify。"""

        print("\n[TestAi04MatchNotice] 超步数错误卡")
        trace = {"intent_job": "clarify", "source": "rule", "rationale": "open_too_many_steps"}
        text = render_match_notice(trace, chinese=True)
        print(" trace:", trace)
        print(" text:", text)
        cards = project_human_cards(
            _plan_payload(
                trace,
                user_query=_OPEN_ZH,
                clarification={
                    "confirm_prompt": "Open plan was rejected (open_too_many_steps).",
                    "pending": [],
                },
            ),
            requested_mode="plan",
            query="",
        )
        kinds = [item.get("kind") for item in cards]
        notices = _match_cards(cards)
        print(" kinds:", kinds)
        print(" notice:", [item.get("text") for item in notices])
        self.assertIn("error", kinds)
        self.assertNotIn("clarify", kinds)
        self.assertEqual(len(notices), 1)
        self.assertEqual(notices[0].get("text"), text)
        self.assertIn("clarify", text)
        self.assertIn("open_too_many_steps", text)
        self.assertNotIn("任务 open", text)
        self.assertNotIn("Task open", text)

    def test_empty_fields_do_not_invent_a_source(self) -> None:
        """缺来源、缺理由、缺任务种类时不补目录句子。"""

        print("\n[TestAi04MatchNotice] 空字段边界")
        full = render_match_notice(
            {"intent_job": "research.hold_compare", "source": "rule", "rationale": "portfolio_compare"},
            chinese=False,
        )
        job_only = render_match_notice({"intent_job": "research.hold_compare"}, chinese=True)
        blank = render_match_notice({"intent_job": "", "source": "rule", "rationale": "portfolio_compare"}, chinese=True)
        print(" full:", full)
        print(" job only:", job_only)
        print(" blank:", repr(blank))
        self.assertEqual(full, "Task research.hold_compare. Source rule. Reason portfolio_compare.")
        self.assertEqual(job_only, "任务 research.hold_compare。")
        self.assertNotIn("来源", job_only)
        self.assertNotIn("rule", job_only)
        self.assertEqual(blank, "")
        cards = project_human_cards(
            _plan_payload(
                {"intent_job": ""},
                user_query=_HOLD,
                steps=[{"step_id": "step_1", "skill_name": "qt.ai.hp.portfolio", "inputs": {}}],
            ),
            requested_mode="plan",
            query=_HOLD,
        )
        print(" blank kinds:", [item.get("kind") for item in cards])
        self.assertEqual(_match_cards(cards), [])
        english = render_match_notice(
            {"intent_job": "strategy.meta", "source": "rule", "rationale": "single_trigger"},
            chinese=False,
        )
        print(" english:", english)
        self.assertTrue(english.startswith("Task strategy.meta"))
        self.assertIn("Source rule", english)
        self.assertIn("Reason single_trigger", english)

    def test_result_and_ask_do_not_grow_a_match_notice(self) -> None:
        """已执行结果卡和 Ask 不追加匹配说明。"""

        print("\n[TestAi04MatchNotice] 结果卡与 Ask 不贴说明")
        trace = {"intent_job": "data.read", "source": "rule", "rationale": "single_trigger"}
        result_cards = project_human_cards(
            {
                "plan": {
                    "plan_id": "plan_done",
                    "user_query": "读取历史",
                    "planner_trace": trace,
                    "steps": [{"step_id": "s1", "skill_name": "qt.ai.data.read", "inputs": {}}],
                },
                "execution": {
                    "status": "success",
                    "steps": [
                        {
                            "step_id": "s1",
                            "skill_name": "qt.ai.data.read",
                            "result": {"ok": True, "payload": {}, "metrics": {}, "data_summary": {}},
                        }
                    ],
                },
            },
            requested_mode="run",
            query="读取历史",
        )
        ask_cards = project_human_cards(
            {
                "mode": "ask",
                "answer": "qteasy is a library.",
                "plan": {
                    "user_query": "什么是 qteasy",
                    "planner_trace": {"intent_job": "route_to_ask", "source": "rule", "rationale": "ask_not_task"},
                },
            },
            requested_mode="plan",
            query="什么是 qteasy",
        )
        print(" result kinds:", [item.get("kind") for item in result_cards])
        print(" ask kinds:", [item.get("kind") for item in ask_cards])
        self.assertEqual(_match_cards(result_cards), [])
        self.assertEqual(_match_cards(ask_cards), [])


class TestAi04MatchNoticeWiring(unittest.TestCase):
    """用户看见的说明来自这一次 plan 留下的记录。"""

    def setUp(self) -> None:
        self.registry = build_default_registry()

    def test_hold_compare_session_notice_matches_the_saved_trace(self) -> None:
        """无模型的组合对比，会话说明等于记录。"""

        print("\n[TestAi04MatchNotice] 接线持有对比")
        calls: List[Any] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            asst.on_stage = lambda stage_id, text: calls.append((stage_id, text))
            payload = asst.plan(_HOLD, response_style="raw", session_id="s-hold")
            trace = (payload.get("plan") or {}).get("planner_trace") or {}
            session = asst.session_store.load("s-hold")
            notices = [
                row
                for row in session.messages
                if (row.get("payload") or {}).get("stage_id") == "match"
            ]
            print(" trace:", trace)
            print(" notices:", [row.get("text") for row in notices])
            print(" calls:", calls)
            self.assertEqual(trace.get("intent_job"), "research.hold_compare")
            self.assertEqual(len(notices), 1)
            self.assertEqual(notices[0].get("text"), render_match_notice(trace, chinese=True))
            self.assertNotIn(("match", notices[0].get("text")), calls)
            self.assertFalse(any(item[0] == "match" for item in calls))

    def test_weather_stays_on_the_recovery_card(self) -> None:
        """对不上清单时说明写 clarify，恢复卡还在。"""

        print("\n[TestAi04MatchNotice] 接线未匹配")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            payload = asst.plan(_WEATHER, response_style="raw", session_id="s-weather")
            trace = (payload.get("plan") or {}).get("planner_trace") or {}
            pending = ((payload.get("plan") or {}).get("assumptions") or {}).get("clarification", {}).get("pending") or []
            names = [str(item.get("name") or "") for item in pending if isinstance(item, dict)]
            notices = _match_cards(payload.get("human_cards") or [])
            print(" trace:", trace)
            print(" pending:", names)
            print(" notice:", [item.get("text") for item in notices])
            self.assertEqual(trace.get("intent_job"), "")
            self.assertIn("intent", names)
            self.assertEqual(notices, [])

    def test_confirmed_open_notice_stays_chinese(self) -> None:
        """确认开放图后，空 query 仍按原句用中文说明。"""

        print("\n[TestAi04MatchNotice] 接线开放图")
        calls: List[Any] = []
        fake = FakeLLMProvider(
            replies=[
                "not-a-protocol",
                json.dumps({"steps": _STEPS}),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                provider=fake,
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            asst.plan(_OPEN_ZH, response_style="raw", session_id="s-open")
            asst.on_stage = lambda stage_id, text: calls.append((stage_id, text))
            second = asst.plan(
                "",
                response_style="raw",
                session_id="s-open",
                patches={"intent": "confirm_open_intent"},
            )
            trace = (second.get("plan") or {}).get("planner_trace") or {}
            user_query = str((second.get("plan") or {}).get("user_query") or "")
            notices = _match_cards(second.get("human_cards") or [])
            session = asst.session_store.load("s-open")
            texts = [str(row.get("text") or "") for row in session.messages]
            print(" trace:", trace)
            print(" user_query:", user_query)
            print(" notice:", [item.get("text") for item in notices])
            print(" calls:", calls)
            self.assertEqual(trace.get("intent_job"), "open")
            self.assertEqual(trace.get("source"), "llm")
            self.assertEqual(trace.get("rationale"), "open_intent")
            self.assertEqual(len(notices), 1)
            self.assertEqual(
                notices[0].get("text"),
                render_match_notice(trace, chinese=True),
            )
            self.assertTrue(str(notices[0].get("text") or "").startswith("任务 "))
            self.assertNotIn("正在创建开放计划", texts)
            self.assertEqual(calls, [])

    def test_too_many_steps_notice_follows_clarify(self) -> None:
        """超步数的说明贴在错误卡旁，任务种类是 clarify。"""

        print("\n[TestAi04MatchNotice] 接线超步数")
        fake = FakeLLMProvider(
            replies=[
                "not-a-protocol",
                json.dumps({"steps": _TOO_MANY}),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                provider=fake,
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            asst.plan(_OPEN_ZH, response_style="raw", session_id="s-many")
            second = asst.plan(
                "",
                response_style="raw",
                session_id="s-many",
                patches={"intent": "confirm_open_intent"},
            )
            trace = (second.get("plan") or {}).get("planner_trace") or {}
            cards = second.get("human_cards") or []
            kinds = [item.get("kind") for item in cards]
            notices = _match_cards(cards)
            print(" trace:", trace)
            print(" kinds:", kinds)
            print(" notice:", [item.get("text") for item in notices])
            self.assertEqual(trace.get("intent_job"), "")
            self.assertEqual(trace.get("rationale"), "open_too_many_steps")
            self.assertIn("clarify", kinds)
            self.assertNotIn("error", kinds)
            self.assertEqual(notices, [])
            self.assertIn("open_too_many_steps", str(cards))

    def test_workbench_draws_match_outside_the_process_fold(self) -> None:
        """匹配说明画在过程折叠外面；活澄清不因后面的匹配说明消失。"""

        print("\n[TestAi04MatchNotice] 工作台不折叠匹配说明")
        src = Path(__file__).resolve().parents[1].joinpath("qteasy_ai/workbench/static/app.js").read_text(encoding="utf-8")
        start = src.index("function renderTurn")
        end = src.index("function renderChat")
        body = src[start:end]
        match_at = body.index('stage_id === "match"')
        fold_at = body.index("PROCESS_KINDS.has(msg.kind)")
        branch = body[match_at:fold_at]
        print(" branch:", branch)
        self.assertLess(match_at, fold_at)
        self.assertIn("flush()", branch)
        self.assertNotIn("pending.push", branch)
        live = src[src.index("function liveClarifyMessage") : src.index("function clarifyStatus")]
        print(" liveClarify:", live)
        self.assertIn('stage_id === "match"', live)
        self.assertIn("continue", live)
