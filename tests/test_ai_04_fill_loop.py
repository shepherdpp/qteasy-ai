# coding=utf-8
# ======================================
# File: test_ai_04_fill_loop.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-22
# Desc:
# 填槽和质检合成一圈：一次候选、一次质检、拒绝后再出澄清卡。
# ======================================

import inspect
import json
import tempfile
import unittest
from typing import Any, Dict, List

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.human_card import project_human_cards
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.slot_graph import (
    _author_clarification,
    _dumb_rows,
    _fill_cycle,
    _fill_graph,
    _judge_slots,
    _model_clarification,
    _reject_reason,
    kernel_window,
)

_GOLD = "600519 和 000858 做一条等权组合"
_MARK = "MARKER-ONLY-IN-TASK"
_FACTOR = "factor IC of close vs volume for 000001.SZ,000002.SZ from 20240101 to 20240331"
_NOT_GIVEN = "用户未明确给出"


def _planner(replies: List[str] = None) -> Planner:
    """无模型，或按队列喂假模型。"""

    provider = FakeLLMProvider(replies=list(replies or [])) if replies is not None else None
    return Planner(build_default_registry(), provider=provider, env_facts={})


def _assistant(temp_dir: str, replies: List[str] = None) -> QteasyAssistant:
    """临时目录里的助手。"""

    provider = FakeLLMProvider(replies=list(replies or [])) if replies is not None else None
    return QteasyAssistant(
        provider=provider,
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


def _parse(sentence: str, job: str) -> str:
    """一次合并协议。办事原文就是这句，没有附带询问。"""

    return json.dumps(
        {
            "job": job,
            "intent_text": sentence,
            "clarification_text": "",
            "open_intent": "",
            "task": sentence,
            "questions": [],
            "candidates": [],
            "relation": "new",
            "plan_id": "",
            "fetch": "",
        },
        ensure_ascii=False,
    )


def _skills(plan: Dict[str, Any]) -> List[str]:
    """可见步骤的技能名。"""

    return [str(step.get("skill_name") or "") for step in (plan.get("steps") or [])]


class TestAi04FillLoop(unittest.TestCase):
    """一圈只出一次候选，质检只跑一次。"""

    def test_filled_illegal_date_is_still_rejected(self) -> None:
        """步骤上已经标成已填的非法日期，无模型跑一圈后不留下。"""

        print("\n[TestAi04FillLoop] 已填非法日期仍拒")
        planner = _planner()
        step = planner._make_step(
            step_id="step_1",
            skill_name="qt.ai.data.kline",
            inputs={"start": "20251340"},
        )
        steps, _extras = _fill_graph(planner, [step], _GOLD, None, "")
        visible = [item.skill_name for item in steps]
        pending = (_extras.get("clarification") or {}).get("pending") or []
        start_row = next((item for item in pending if item.get("name") == "start"), {})
        print(" skills:", visible)
        print(" start error:", start_row.get("error"), "prompt:", start_row.get("prompt"))
        print(" step start:", (steps[0].inputs or {}).get("start") if steps else None)
        self.assertIn("20251340", str(start_row.get("prompt") or "") + str(start_row.get("error") or ""))
        self.assertEqual(visible, ["qt.ai.system.fallback"])
        self.assertEqual((steps[0].inputs or {}).get("fallback_action"), "clarify_required")
        self.assertNotEqual((steps[0].inputs or {}).get("start"), "20251340")

    def test_model_answer_stays_in_the_prompt(self) -> None:
        """有模型时澄清回答只进提示词。协议没交的日期不补写。"""

        print("\n[TestAi04FillLoop] 回答只进提示词")
        sentence = f"{_MARK} 600519 和 000858 做一条等权组合"
        fill = json.dumps({"start": "20251340"})
        card = json.dumps({
            "questions": [
                {
                    "name": name,
                    "explanation": "20251340 is not a date." if name == "start" else f"Need {name}.",
                    "options": [{"id": "a", "label": "a"}, {"id": "b", "label": "b"}],
                    "open": {"label": "其它"},
                }
                for name in ("start", "weights", "holdings")
            ]
        })
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(
                temp_dir,
                [
                    _parse(sentence, "research.hold_compare"),
                    fill,
                    card,
                ],
            )
            first = assistant.plan(sentence, response_style="raw", session_id="s-prompt", debug=True)
            plan = _plan(first)
            rows = _pending(plan)
            print(" first pending:", [item.get("name") for item in rows])
            self.assertTrue(rows)
            provider = FakeLLMProvider(replies=[json.dumps({"mode": "equal"})])
            assistant.apply_provider(provider)
            second = assistant.plan(
                "",
                response_style="raw",
                session_id="s-prompt",
                patches={"start": "20250405"},
                debug=True,
            )
            plan = _plan(second)
            prompt = provider.prompts[0] if provider.prompts else ""
            blob = json.dumps(plan.get("steps") or [], ensure_ascii=False)
            debug = ((plan.get("planner_trace") or {}).get("fill_debug") or [])
            print(" prompt has marker:", _MARK in prompt)
            print(" prompt has answer:", "20250405" in prompt)
            print(" written blob has 20250405:", "20250405" in blob)
            print(" debug source:", [item.get("candidate_source") for item in debug])
            self.assertIn(_MARK, prompt)
            self.assertIn("20250405", prompt)
            self.assertNotIn("20250405", blob)
            self.assertNotIn(_MARK, blob)

    def test_card_protocol_asks_only_rejected(self) -> None:
        """出卡协议要有说明、选项和开放输入，并且只问 rejected。"""

        print("\n[TestAi04FillLoop] 出卡协议只问拒绝")
        sentence = "算因子 IC"
        bad = json.dumps({"shares": "平安银行"}, ensure_ascii=False)
        def _question(name: str, explanation: str) -> Dict[str, Any]:
            return {
                "name": name,
                "explanation": explanation,
                "options": [
                    {"id": "000001.SZ", "label": "000001.SZ"},
                    {"id": "000002.SZ", "label": "000002.SZ"},
                ],
                "open": {"label": "其它"},
            }

        good_card = json.dumps({
            "questions": [
                _question("shares", "平安银行 is not an exchange code. Give codes."),
                _question("start", "Need a start date."),
                _question("end", "Need an end date."),
                _question("factor_htype", "Need a factor column."),
                _question("return_htype", "Need a return column."),
                {
                    "name": "not_a_slot",
                    "explanation": "ignore",
                    "options": [{"id": "x", "label": "x"}, {"id": "y", "label": "y"}],
                    "open": {"label": "其它"},
                },
            ]
        }, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(
                temp_dir,
                [
                    _parse(sentence, "research.factor_ic"),
                    bad,
                    good_card,
                ],
            )
            result = assistant.plan(sentence, response_style="raw", session_id="s-card")
            plan = _plan(result)
            rows = _pending(plan)
            names = [item.get("name") for item in rows]
            provider = assistant.planner.provider
            card_prompts = [text for text in provider.prompts if text.startswith("Clarification protocol.")]
            print(" pending:", names)
            print(" card prompts:", len(card_prompts))
            print(" fill chats:", sum(1 for text in provider.prompts if text.startswith("Slot protocol.")))
            self.assertTrue(card_prompts)
            self.assertIn("Task sentence:", card_prompts[0])
            self.assertIn("Rejected:", card_prompts[0])
            shares = next(item for item in rows if item.get("name") == "shares")
            self.assertIn("shares", names)
            self.assertNotIn("not_a_slot", names)
            self.assertTrue(shares.get("prompt"))
            self.assertTrue(shares.get("error"))
            self.assertIn("平安银行", str(shares.get("error") or "") + str(shares.get("prompt") or ""))
            self.assertGreaterEqual(len(shares.get("options") or []), 2)
            self.assertTrue((plan.get("assumptions") or {}).get("clarification", {}).get("fill_authored"))

    def test_judge_report_has_two_blocks(self) -> None:
        """质检报告只有 accepted 和 rejected。空值与非法值理由不同。"""

        print("\n[TestAi04FillLoop] 报告两块")
        required = {
            "name": "symbol",
            "type": "string",
            "required": True,
        }
        touched_empty = {
            "name": "start",
            "type": "string",
            "required": False,
            "format": "YYYYMMDD",
            "example": "20250101",
            "default_kind": "kernel_window",
        }
        illegal = {
            "name": "when",
            "type": "string",
            "required": False,
            "format": "YYYYMMDD",
            "example": "20250101",
        }
        untouched = {
            "name": "end",
            "type": "string",
            "required": False,
            "format": "YYYYMMDD",
            "example": "20250101",
            "default_kind": "kernel_window",
        }
        report = _judge_slots(
            [required, touched_empty, illegal, untouched],
            [],
            {"start": "", "when": "20251340"},
            {"start", "when"},
            _GOLD,
            [],
        )
        print(" keys:", sorted(report))
        print(" accepted:", report.get("accepted"))
        print(" rejected:", report.get("rejected"))
        self.assertEqual(set(report), {"accepted", "rejected"})
        print(" empty required:", report["rejected"].get("symbol"))
        self.assertNotEqual(report["rejected"].get("symbol"), _NOT_GIVEN)
        self.assertTrue(report["rejected"].get("symbol"))
        self.assertEqual(report["rejected"].get("start"), _NOT_GIVEN)
        self.assertIn("20251340", report["rejected"].get("when") or "")
        self.assertNotEqual(report["rejected"].get("when"), _NOT_GIVEN)
        end = report["accepted"].get("end") or {}
        print(" default end:", end)
        self.assertEqual(end.get("source"), "default")
        self.assertEqual(end.get("value"), kernel_window()["end"])
        self.assertNotIn("suggestion", report)
        self.assertNotIn("recommended", report)
        self.assertNotIn("options", report)

    def test_kernel_default_and_empty_key_differ(self) -> None:
        """金句没点到日期就收下缺省。键交成空才写用户未明确给出。"""

        print("\n[TestAi04FillLoop] 缺省与空键")
        plan = _planner().build_plan(_GOLD, mode="plan")
        assumptions = plan.assumptions or {}
        defaults = assumptions.get("slot_defaults") or {}
        print(" confirmable:", "qt.ai.system.fallback" not in [step.skill_name for step in plan.steps])
        print(" defaults:", defaults)
        self.assertEqual(defaults.get("start"), "default")
        self.assertEqual(defaults.get("end"), "default")
        window = kernel_window()
        kline = {}
        for step in plan.steps:
            if step.skill_name == "qt.ai.data.kline":
                kline = dict(step.inputs or {})
        print(" kline:", kline.get("start"), kline.get("end"), "kernel:", window)
        self.assertEqual(kline.get("start"), window["start"])
        self.assertEqual(kline.get("end"), window["end"])

        empty_key = _judge_slots(
            [{
                "name": "start",
                "type": "string",
                "required": False,
                "format": "YYYYMMDD",
                "example": "20250101",
                "default_kind": "kernel_window",
            }],
            [],
            {"start": ""},
            {"start"},
            _GOLD,
            [],
        )
        print(" empty key:", empty_key["rejected"])
        self.assertEqual(empty_key["rejected"].get("start"), _NOT_GIVEN)
        self.assertNotIn("start", empty_key["accepted"])

        illegal = _judge_slots(
            [{
                "name": "start",
                "type": "string",
                "required": False,
                "format": "YYYYMMDD",
                "example": "20250101",
                "default_kind": "kernel_window",
            }],
            [],
            {"start": "20251340"},
            {"start"},
            _GOLD,
            [],
        )
        print(" illegal:", illegal["rejected"])
        self.assertIn("20251340", illegal["rejected"].get("start") or "")
        self.assertNotEqual(illegal["rejected"].get("start"), _NOT_GIVEN)

    def test_round_cap_still_calls_the_interpreter(self) -> None:
        """圈数到 4 再交，无模型仍出弱智卡，不把任务标成结束。"""

        print("\n[TestAi04FillLoop] 圈数用尽仍解释")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir)
            sid = "s-cap"
            assistant.plan("帮我下载日线", response_style="raw", session_id=sid)
            for index, day in enumerate(("20240101", "20240201", "20240301", "20240401"), start=1):
                result = assistant.plan(
                    "",
                    response_style="raw",
                    session_id=sid,
                    patches={"start": day},
                )
                print(" round", index, "status keys:", sorted(result))
            loaded = assistant.session_store.load(sid)
            print(" after 4:", loaded.task.status, loaded.task.clarify_round)
            self.assertNotEqual(loaded.task.status, "done")
            self.assertEqual(loaded.task.clarify_round, 4)
            self.assertIsNotNone(loaded.task.pending_clarification)
            again = assistant.plan(
                "",
                response_style="raw",
                session_id=sid,
                patches={"start": "20240501"},
            )
            plan = _plan(again)
            print(" again skills:", _skills(plan))
            print(" again round:", (again.get("session") or {}).get("clarify_round"))
            self.assertIn("plan", again)
            self.assertEqual(_skills(plan)[0], "qt.ai.system.fallback")
            self.assertEqual((again.get("session") or {}).get("clarify_round"), 4)
            loaded = assistant.session_store.load(sid)
            self.assertNotEqual(loaded.task.status, "done")

    def test_round_cap_with_model_still_chats_once_each(self) -> None:
        """圈数到 4 再交，有模型仍各调用一次填槽和出卡。"""

        print("\n[TestAi04FillLoop] 有模型圈数用尽仍各问一次")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir)
            sid = "s-cap-model"
            assistant.plan("帮我下载日线", response_style="raw", session_id=sid)
            for day in ("20240101", "20240201", "20240301", "20240401"):
                assistant.plan("", response_style="raw", session_id=sid, patches={"start": day})
            provider = FakeLLMProvider(replies=[json.dumps({"start": "20251340"})])
            assistant.apply_provider(provider)
            again = assistant.plan(
                "",
                response_style="raw",
                session_id=sid,
                patches={"start": "20240501"},
                debug=True,
            )
            fill_chats = [text for text in provider.prompts if text.startswith("Slot protocol.")]
            card_chats = [text for text in provider.prompts if text.startswith("Clarification protocol.")]
            print(" fill chats:", len(fill_chats), "card chats:", len(card_chats))
            print(" skills:", _skills(_plan(again)))
            self.assertEqual(len(fill_chats), 1)
            self.assertEqual(len(card_chats), 1)
            self.assertEqual(_skills(_plan(again))[0], "qt.ai.system.fallback")
            self.assertEqual((again.get("session") or {}).get("clarify_round"), 4)

    def test_debug_false_hides_fill_protocol(self) -> None:
        """debug 关闭时不写 fill_output 和 fill_debug。打开时按圈留下协议。"""

        print("\n[TestAi04FillLoop] debug 开关")
        sentence = "算因子 IC"
        bad = json.dumps({"shares": "平安银行"}, ensure_ascii=False)
        card = json.dumps({
            "questions": [
                {
                    "name": name,
                    "explanation": "'平安银行' is not an exchange code." if name == "shares" else f"Need {name}.",
                    "options": [
                        {"id": "000001.SZ", "label": "000001.SZ"},
                        {"id": "000002.SZ", "label": "000002.SZ"},
                    ],
                    "open": {"label": "Other"},
                }
                for name in ("factor_htype", "return_htype", "shares", "start", "end")
            ]
        }, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(
                temp_dir,
                [
                    _parse(sentence, "research.factor_ic"),
                    bad,
                    card,
                ],
            )
            quiet = assistant.plan(sentence, response_style="raw", session_id="s-quiet", debug=False)
            plan = _plan(quiet)
            trace = plan.get("planner_trace") or {}
            record = (plan.get("assumptions") or {}).get("fill_record") or {}
            print(" quiet keys:", sorted(trace))
            print(" questions:", record.get("questions"))
            self.assertNotIn("fill_output", trace)
            self.assertNotIn("fill_debug", trace)
            self.assertNotIn("平安银行", json.dumps(trace.get("validation_rejects") or []))
            self.assertIn("平安银行", json.dumps(record.get("questions") or [], ensure_ascii=False))

        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(
                temp_dir,
                [
                    _parse(sentence, "research.factor_ic"),
                    bad,
                    card,
                    bad,
                    card,
                ],
            )
            first = assistant.plan(sentence, response_style="raw", session_id="s-debug", debug=True)
            plan = _plan(first)
            debug = (plan.get("planner_trace") or {}).get("fill_debug") or []
            print(" debug entries:", len(debug))
            print(" first entry keys:", sorted(debug[0]) if debug else [])
            self.assertTrue(debug)
            self.assertIn(sentence, json.dumps(debug[0], ensure_ascii=False))
            self.assertTrue(debug[0].get("protocol") or debug[0].get("card_protocol") or debug[0].get("dumb_card"))
            second = assistant.plan(
                "",
                response_style="raw",
                session_id="s-debug",
                patches={"shares": "平安银行"},
                debug=True,
            )
            plan = _plan(second)
            debug = (plan.get("planner_trace") or {}).get("fill_debug") or []
            task = assistant.session_store.load("s-debug").task
            print(" after second:", len(debug), "task:", len(task.fill_debug or []))
            self.assertGreaterEqual(len(task.fill_debug or []), 2)
            self.assertIn("平安银行", json.dumps(task.fill_debug[0], ensure_ascii=False))

    def test_empty_options_stay_on_one_card(self) -> None:
        """空选项协议只出一次卡，题干是模型的说明。"""

        print("\n[TestAi04FillLoop] 空选项只出一次卡")
        sentence = "算因子 IC"
        explanation = "请明确要使用的内置策略名称"
        bad = json.dumps({"shares": "平安银行"}, ensure_ascii=False)
        names = ("factor_htype", "return_htype", "shares", "start", "end")
        card = json.dumps({
            "questions": [
                {
                    "name": name,
                    "explanation": explanation,
                    "options": [],
                    "open": {"label": "Other"},
                }
                for name in names
            ]
        }, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(
                temp_dir,
                [
                    _parse(sentence, "research.factor_ic"),
                    bad,
                    card,
                ],
            )
            result = assistant.plan(sentence, response_style="raw", session_id="s-empty", debug=True)
            plan = _plan(result)
            rows = _pending(plan)
            prompts = [
                text for text in assistant.planner.provider.prompts
                if text.startswith("Clarification protocol.")
            ]
            debug = (plan.get("planner_trace") or {}).get("fill_debug") or []
            print(" prompts:", len(prompts))
            print(" prompts text:", [row.get("prompt") for row in rows])
            print(" options:", [row.get("options") for row in rows])
            print(" dumb:", [item.get("dumb_card") for item in debug])
            self.assertEqual(len(prompts), 1)
            self.assertIn("Write the questions the user will see.", prompts[0])
            self.assertNotIn('"explanation":""', prompts[0])
            self.assertTrue(rows)
            self.assertTrue(all(row.get("prompt") == explanation for row in rows))
            self.assertTrue(all(not row.get("options") for row in rows))
            self.assertTrue(all(row.get("error") for row in rows))
            self.assertNotIn(explanation, " ".join(str(row.get("error") or "") for row in rows))
            self.assertTrue(debug)
            self.assertTrue(debug[0].get("card_protocol"))
            self.assertNotIn("dumb_card", debug[0])

    def test_unreadable_card_keeps_the_reject_reason(self) -> None:
        """出卡不是 JSON 时只叫一次。计划不可确认，确认句不拼拒因。"""

        print("\n[TestAi04FillLoop] 读不成问句仍停在澄清")
        sentence = "macd 回测 000001.SZ 和 000002.SZ"
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(
                temp_dir,
                [
                    _parse(sentence, "backtest.builtin"),
                    json.dumps({}),
                    "not-json",
                ],
            )
            result = assistant.plan(sentence, response_style="raw", session_id="s-bad", debug=True)
            plan = _plan(result)
            clar = (plan.get("assumptions") or {}).get("clarification") or {}
            prompts = [
                text for text in assistant.planner.provider.prompts
                if text.startswith("Clarification protocol.")
            ]
            debug = (plan.get("planner_trace") or {}).get("fill_debug") or []
            steps = plan.get("steps") or []
            info = str((steps[0].get("inputs") or {}).get("missing_info") or "")
            reasons = (debug[0].get("reasons") or {}) if debug else {}
            cards = project_human_cards(
                {"plan": plan, "execution": {"status": "dry_run", "steps": []}},
                requested_mode="plan",
                query=sentence,
                include_user_text=False,
            )
            kinds = [str(card.get("kind") or "") for card in cards]
            print(" card prompts:", len(prompts))
            print(" pending:", clar.get("pending"))
            print(" confirm:", clar.get("confirm_prompt"))
            print(" missing:", info)
            print(" reasons:", reasons)
            print(" kinds:", kinds)
            self.assertEqual(len(prompts), 1)
            self.assertEqual(clar.get("pending"), [])
            self.assertFalse(clar.get("confirm_prompt"))
            self.assertNotIn("Which built-in strategy?", str(clar.get("confirm_prompt")))
            for name, reason in reasons.items():
                self.assertNotIn(f"{name}: {reason}", str(clar.get("confirm_prompt") or ""))
                self.assertIn(str(name), info.split("|"))
            self.assertTrue(clar.get("fill_authored"))
            self.assertEqual([step.get("skill_name") for step in steps], ["qt.ai.system.fallback"])
            self.assertNotEqual(info, "none")
            self.assertTrue(debug)
            self.assertTrue(debug[0].get("card_protocol"))
            self.assertNotIn("dumb_card", debug[0])
            self.assertNotIn("card_protocol_retry", debug[0])
            self.assertNotIn("plan_ready", kinds)
            self.assertIn("error", kinds)

    def test_partial_card_keeps_written_questions(self) -> None:
        """三个被拒槽里只写了一格，卡片只留这一格。"""

        print("\n[TestAi04FillLoop] 没盖住的槽不另开分支")
        sentence = f"{_MARK} 600519 和 000858 做一条等权组合"
        explanation = "开始日不是真实日期，请给一个八位日期"
        fill = json.dumps({"start": "20251340"})
        card = json.dumps({
            "questions": [
                {
                    "name": "start",
                    "explanation": explanation,
                    "options": [],
                    "open": {"label": "其它"},
                }
            ]
        }, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(
                temp_dir,
                [
                    _parse(sentence, "research.hold_compare"),
                    fill,
                    card,
                ],
            )
            result = assistant.plan(sentence, response_style="raw", session_id="s-part", debug=True)
            plan = _plan(result)
            rows = _pending(plan)
            names = [str(row.get("name") or "") for row in rows]
            kept = {
                str(item.get("name") or "")
                for item in ((plan.get("assumptions") or {}).get("fill_record") or {}).get("slots") or []
            }
            prompts = [
                text for text in assistant.planner.provider.prompts
                if text.startswith("Clarification protocol.")
            ]
            steps = plan.get("steps") or []
            cards = project_human_cards(
                {"plan": plan, "execution": {"status": "dry_run", "steps": []}},
                requested_mode="plan",
                query=sentence,
                include_user_text=False,
            )
            kinds = [str(card.get("kind") or "") for card in cards]
            print(" prompts:", len(prompts))
            print(" pending:", names)
            print(" prompt:", rows[0].get("prompt") if rows else "")
            print(" kept:", sorted(kept))
            print(" kinds:", kinds)
            self.assertEqual(len(prompts), 1)
            self.assertEqual(names, ["start"])
            self.assertEqual(rows[0].get("prompt"), explanation)
            self.assertNotIn("weights", names)
            self.assertNotIn("holdings", names)
            self.assertNotIn("start", kept)
            self.assertNotIn("weights", kept)
            self.assertNotIn("holdings", kept)
            self.assertEqual([step.get("skill_name") for step in steps], ["qt.ai.system.fallback"])
            self.assertNotIn("plan_ready", kinds)
            self.assertIn("clarify", kinds)

    def test_history_carries_the_reject_reason(self) -> None:
        """交卷后历次澄清带上拒因，下一圈填槽提示词看得到。"""

        print("\n[TestAi04FillLoop] 历次澄清带拒因")
        sentence = f"{_MARK} 600519 和 000858 做一条等权组合"
        reason = "20251340 is not a date."
        fill = json.dumps({"start": "20251340"})
        card = json.dumps({
            "questions": [
                {
                    "name": name,
                    "explanation": reason if name == "start" else f"Need {name}.",
                    "options": [{"id": "a", "label": "a"}, {"id": "b", "label": "b"}],
                    "open": {"label": "其它"},
                }
                for name in ("start", "weights", "holdings")
            ]
        })
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(
                temp_dir,
                [
                    _parse(sentence, "research.hold_compare"),
                    fill,
                    card,
                ],
            )
            first = assistant.plan(sentence, response_style="raw", session_id="s-hist", debug=True)
            shown = next(item for item in _pending(_plan(first)) if item.get("name") == "start")
            print(" first error:", shown.get("error"))
            self.assertTrue(shown.get("error"))
            assistant.apply_provider(FakeLLMProvider(replies=[json.dumps({"mode": "equal"})]))
            assistant.plan(
                "",
                response_style="raw",
                session_id="s-hist",
                patches={"start": "20250405"},
                debug=True,
            )
            task = assistant.session_store.load("s-hist").task
            history = task.clarify_history or []
            slot = (history[0].get("slots") or [{}])[0] if history else {}
            prompt = assistant.planner.provider.prompts[0] if assistant.planner.provider.prompts else ""
            print(" history error:", slot.get("error"))
            print(" prompt has error:", slot.get("error") in prompt)
            self.assertEqual(slot.get("error"), shown.get("error"))
            self.assertIn(f"error={shown.get('error')}", prompt)

    def test_null_freq_is_not_written(self) -> None:
        """用户没给出的频率交 null，步骤上不写 d。"""

        print("\n[TestAi04FillLoop] null 不写成 d")
        planner = _planner([json.dumps({"freq": None})])
        step = planner._make_step(
            step_id="step_1",
            skill_name="qt.ai.data.kline",
            inputs={},
        )
        steps, extras = _fill_graph(planner, [step], "看 000001.SZ 的行情", None, "")
        prompt = planner.provider.prompts[0]
        blob = json.dumps(
            [dict(item.inputs or {}) for item in steps],
            ensure_ascii=False,
        )
        snapshot = json.dumps((extras.get("accepted_steps") or []), ensure_ascii=False)
        print(" prompt extracts only named values:", "Extract only values the user actually named." in prompt)
        print(" prompt uses null:", "Use null for a slot the user did not name." in prompt)
        print(" steps:", blob)
        print(" snapshot:", snapshot)
        self.assertIn("Extract only values the user actually named.", prompt)
        self.assertIn("Do not invent or repair a value.", prompt)
        self.assertIn("Use null for a slot the user did not name.", prompt)
        self.assertIn("Do not pick one the user did not say.", prompt)
        self.assertNotIn('"freq": "d"', blob)
        self.assertNotIn('"freq": "d"', snapshot)

    def test_cycle_source_has_no_job_branch(self) -> None:
        """循环和质检源码里没有按任务名分叉，报告也不带建议值。"""

        print("\n[TestAi04FillLoop] 源码守卫")
        cycle = inspect.getsource(_fill_cycle)
        judge = inspect.getsource(_judge_slots)
        author = inspect.getsource(_author_clarification)
        print(" cycle has if job:", "if job" in cycle)
        print(" judge has options:", "options" in judge)
        self.assertNotIn("if job", cycle)
        self.assertNotIn("if job", judge)
        self.assertNotIn("suggestion", judge)
        self.assertNotIn("recommended", judge)
        self.assertNotIn("options", judge)
        self.assertNotIn("_finish_portfolio_graph", cycle)
        self.assertNotIn("_finish_portfolio_graph", judge)
        self.assertNotIn("_bake_describe_view", cycle)
        self.assertIn("def _author_clarification", author)
        model = inspect.getsource(_model_clarification)
        dumb = inspect.getsource(_dumb_rows)
        print(" model chat count:", model.count("provider.chat"))
        print(" model has dumb:", "_dumb_rows" in model)
        self.assertEqual(model.count("provider.chat"), 1)
        self.assertNotIn("_dumb_rows", model)
        self.assertNotIn("_pending_row", model)
        self.assertNotIn("_open_label", model)
        self.assertNotIn("provider.chat", dumb)


if __name__ == "__main__":
    unittest.main()
