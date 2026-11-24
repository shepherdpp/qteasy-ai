# coding=utf-8
# ======================================
# File: test_ai_process_receipt.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-07
# Desc:
# 澄清回执在长计算前落盘；阶段占位可被 load；
# 已关闭的卡不再从 run 投影出来。
# ======================================

import json
import tempfile
import unittest
from pathlib import Path

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.human_card import drop_closed_clarification
from qteasy_ai.match_notice import render_match_notice
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.session import SessionStore
from qteasy_ai.workbench.mapper import map_assistant_payload


_ZH = "取 000300.SH 日线，算收益，再出一页图，请生成一个简短的开放计划"
_STEPS = [
    {"skill_name": "qt.ai.data.kline", "inputs": {"shares": "000300.SH"}},
    {"skill_name": "qt.ai.hp.returns", "inputs": {}, "depends_on": ["step_1"]},
    {"skill_name": "qt.ai.hp.plot", "inputs": {"page": 1}, "depends_on": ["step_2"]},
]
_TOO_MANY = _STEPS + [
    {"skill_name": "qt.ai.hp.volatility", "inputs": {}, "depends_on": ["step_2"]},
]


class _ProbeProvider(FakeLLMProvider):
    """开放组图被调用时记下当时已经落盘的会话。"""

    def __init__(self, replies, store, session_id: str) -> None:
        super().__init__(replies=replies)
        self.store = store
        self.session_id = session_id
        self.seen = None

    def chat(self, prompt: str, *, system_prompt: str = "") -> str:
        if str(prompt or "").startswith("Allowed skills:"):
            self.seen = SessionStore(self.store).load(self.session_id)
        return super().chat(prompt, system_prompt=system_prompt)


class TestAiProcessReceipt(unittest.TestCase):
    """作答回执与阶段占位。"""

    def setUp(self) -> None:
        self.registry = build_default_registry()

    def test_compose_open_is_saved_before_the_graph_returns(self) -> None:
        """组图回调还没返回时，磁盘上已是已答，并有开放计划占位。"""

        print("\n[TestAiProcessReceipt] 组图前已落盘回执与占位")
        calls = []
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            fake = _ProbeProvider(
                replies=[
                    "not-a-protocol",
                    json.dumps({"steps": _STEPS}),
                    json.dumps({"shares": "000300.SH"}),
                ],
                store=store,
                session_id="s-receipt",
            )
            asst = QteasyAssistant(provider=fake, registry=self.registry, memory_store=store)
            asst.plan(_ZH, response_style="raw", session_id="s-receipt")
            asst.on_stage = lambda stage_id, text: calls.append((stage_id, text))
            second = asst.plan(
                "",
                response_style="raw",
                session_id="s-receipt",
                patches={"intent": "confirm_open_intent"},
            )
            seen = fake.seen
            texts = [str(row.get("text") or "") for row in (seen.messages if seen else [])]
            pending = None if seen is None or seen.task is None else seen.task.pending_clarification
            plan = second.get("plan") or {}
            skills = [step.get("skill_name") for step in (plan.get("steps") or [])]
            print(" texts:", texts)
            print(" calls:", calls)
            print(" pending during compose:", pending)
            print(" skills:", skills)
            self.assertIsNotNone(seen)
            self.assertEqual(calls, [])
            self.assertTrue((pending or {}).get("intent_authored"))
            self.assertEqual(
                skills,
                ["qt.ai.data.kline", "qt.ai.hp.returns", "qt.ai.hp.plot"],
            )
            self.assertEqual((plan.get("planner_trace") or {}).get("intent_job"), "open")

    def test_unmatched_notice_then_too_many_keeps_the_placeholder(self) -> None:
        """未匹配先写一句；超步数后占位还在，且不回到三选卡。"""

        print("\n[TestAiProcessReceipt] 未匹配与超步数")
        calls = []
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
            asst.on_stage = lambda stage_id, text: calls.append((stage_id, text))
            sid = "s-stage"
            first_payload = asst.plan(_ZH, response_style="raw", session_id=sid)
            first = asst.session_store.load(sid)
            first_texts = [str(row.get("text") or "") for row in first.messages]
            first_names = [
                item.get("name")
                for item in (((first_payload.get("plan") or {}).get("assumptions") or {}).get("clarification") or {}).get("pending") or []
                if isinstance(item, dict)
            ]
            print(" first:", first_texts)
            print(" first pending:", first_names)
            print(" first calls:", calls)
            self.assertEqual(first_names, ["intent"])
            self.assertEqual(calls, [])

            calls.clear()
            second = asst.plan(
                "",
                response_style="raw",
                session_id=sid,
                patches={"intent": "confirm_open_intent"},
            )
            after = asst.session_store.load(sid)
            texts = [str(row.get("text") or "") for row in after.messages]
            print(" after:", texts)
            print(" second calls:", calls)
            plan = second.get("plan") or {}
            reason = ((plan.get("steps") or [{}])[0].get("inputs") or {}).get("reason")
            print(" reason:", reason)
            self.assertEqual(reason, "open_too_many_steps")
            self.assertNotIn("正在创建开放计划", texts)
            pending_names = [
                item.get("name")
                for item in ((after.task.pending_clarification or {}).get("pending") or [])
                if isinstance(item, dict)
            ]
            print(" pending:", pending_names, "status:", after.task.status if after.task else None)
            print(" calls:", calls)
            self.assertEqual(pending_names, ["recover"])
            self.assertEqual(after.task.status, "clarifying")
            self.assertEqual(calls, [])

    def test_closed_run_clarification_is_not_projected_again(self) -> None:
        """已答之后，旧 run 的澄清块不再变成一张未答卡。"""

        print("\n[TestAiProcessReceipt] 已关闭澄清不再投影")
        fake = FakeLLMProvider(
            replies=[
                "not-a-protocol",
                json.dumps({"steps": _STEPS}),
                json.dumps({"shares": "000300.SH"}),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                provider=fake,
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "s-closed"
            first = asst.plan(_ZH, response_style="raw", session_id=sid)
            asst.plan(
                "",
                response_style="raw",
                session_id=sid,
                patches={"intent": "confirm_open_intent"},
            )
            session = asst.session_store.load(sid)
            stale = {
                "plan": {
                    "plan_id": "plan_old",
                    "mode": "plan",
                    "assumptions": {"clarification": (first.get("plan") or {}).get("assumptions", {}).get("clarification")},
                    "steps": [
                        {
                            "step_id": "step_1",
                            "skill_name": "qt.ai.system.fallback",
                            "inputs": {"fallback_action": "clarify_required"},
                        }
                    ],
                },
                "clarification": (first.get("plan") or {}).get("assumptions", {}).get("clarification"),
                "execution": {"status": "dry_run", "steps": []},
            }
            state = map_assistant_payload(stale, session=session, query=_ZH)
            kinds = [item.kind for item in state.messages]
            print(" kinds:", kinds)
            print(" missing:", state.sidebar.missing)
            print(" transcript tail:", [row.get("kind") for row in session.messages[-4:]])
            self.assertNotIn("clarify", kinds)
            self.assertEqual(state.sidebar.missing, [])
            guides = [row for row in session.messages if "Choose a listed job" in str(row.get("text") or "")]
            print(" intent guides:", len(guides))
            self.assertTrue(guides)
            cleaned = drop_closed_clarification(stale)
            print(" cleaned keys:", sorted(cleaned))
            self.assertNotIn("clarification", cleaned)
            self.assertNotIn("clarification", (cleaned.get("plan") or {}).get("assumptions") or {})

    def test_matched_job_notice_uses_summary_not_trace(self) -> None:
        """匹配到现成 Job 时，说明等于这份记录，不另查目录。"""

        print("\n[TestAiProcessReceipt] 已匹配 Job 跟记录")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            payload = asst.plan("list built-in strategies", response_style="raw", session_id="s-match")
            trace = (payload.get("plan") or {}).get("planner_trace") or {}
            session = asst.session_store.load("s-match")
            notices = [row for row in session.messages if (row.get("payload") or {}).get("stage_id") == "match"]
            print(" trace:", trace)
            print(" notices:", [row.get("text") for row in notices])
            self.assertEqual(len(notices), 1)
            text = str(notices[0].get("text") or "")
            self.assertEqual(text, render_match_notice(trace, chinese=False))
            self.assertIn(str(trace.get("intent_job") or ""), text)
            self.assertNotIn("qt.ai", text)
            self.assertNotIn("planner_trace", text)
            if "llm_uncertain" in text:
                self.assertIn("llm_uncertain", str(trace.get("rationale") or ""))
            src = Path(__file__).resolve().parents[1].joinpath("qteasy_ai/workbench/static/app.js").read_text(encoding="utf-8")
            print(" web receipt:", "用户已选" in src, "Selected:" in src)
            self.assertIn("用户已选", src)
            self.assertIn("Selected:", src)
            self.assertIn("clarifySettled", src)
