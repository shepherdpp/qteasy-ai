# coding=utf-8
# ======================================
# File: test_ai_unresolved_recovery.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-04
# Desc:
# Job 没认出来时的恢复卡：固定文案、
# 强制 open、放弃与重写。
# ======================================

import json
import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.parse_turn import CONFIRM_OPEN_ID, FIXED_GUIDE
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider
from tests.parse_protocol import open_parsed


_ZH = "取 000300.SH 日线，算收益，再出一页图，请生成一个简短的开放计划"
_GUIDE = FIXED_GUIDE
_STEPS = [
    {"skill_name": "qt.ai.data.kline", "inputs": {"shares": "000300.SH"}},
    {"skill_name": "qt.ai.hp.returns", "inputs": {}, "depends_on": ["step_1"]},
    {"skill_name": "qt.ai.hp.plot", "inputs": {"page": 1}, "depends_on": ["step_2"]},
]
_TOO_MANY = _STEPS + [
    {"skill_name": "qt.ai.hp.volatility", "inputs": {}, "depends_on": ["step_2"]},
]


def _job(payload: dict) -> str:
    """分类罐头。"""

    return json.dumps(payload, ensure_ascii=False)


def _pending(plan):
    """澄清卡 pending。"""

    blob = (plan.assumptions or {}).get("clarification") or {}
    return [item for item in (blob.get("pending") or []) if isinstance(item, dict)]


def _names(plan):
    """pending 槽名。"""

    return [str(item.get("name") or "") for item in _pending(plan)]


class TestAiUnresolvedRecovery(unittest.TestCase):
    """意图未解恢复卡与三个提交动作。"""

    def setUp(self) -> None:
        self.registry = build_default_registry()

    def test_unresolved_card_for_each_classify_miss(self) -> None:
        """无模型，以及 clarify / 不确定 / 多 id / 非法 id，都出同一张恢复卡且不润色。"""

        print("\n[TestAiUnresolvedRecovery] 分类落空出意图卡")
        bare_query = "xyzzy unmatched formula 12345"
        bare = Planner(self.registry, env_facts={}).build_plan(bare_query, mode="plan")
        bare_row = _pending(bare)[0]
        print(" bare prompt:", (bare.assumptions.get("clarification") or {}).get("confirm_prompt"))
        self.assertEqual(_names(bare), ["intent"])
        self.assertEqual((bare.assumptions.get("clarification") or {}).get("confirm_prompt"), _GUIDE)
        self.assertEqual([item["id"] for item in bare_row["options"]], [CONFIRM_OPEN_ID])
        self.assertEqual(bare_row["options"][0]["label"], bare_query)
        self.assertEqual((bare_row.get("open") or {}).get("label"), "Your own open intent")

        replies = (
            {"job": "clarify"},
            {"job": "data.read", "uncertain": True},
            {"jobs": ["data.read", "data.summary"]},
            {"job": "not-a-job"},
        )
        for payload in replies:
            fake = FakeLLMProvider(replies=[json.dumps(payload, ensure_ascii=False), "polish-must-not-run"])
            plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(_ZH, mode="plan")
            row = _pending(plan)[0]
            print(" payload:", payload, "prompts:", len(fake.prompts), "left:", fake.replies)
            print(" prompt:", (plan.assumptions.get("clarification") or {}).get("confirm_prompt"))
            self.assertEqual(len(fake.prompts), 1)
            self.assertIn(_ZH, fake.prompts[0])
            self.assertTrue(fake.prompts[0].startswith("Official jobs:"))
            self.assertEqual(fake.replies, ["polish-must-not-run"])
            self.assertEqual(_names(plan), ["intent"])
            self.assertEqual([item["id"] for item in row["options"]], [CONFIRM_OPEN_ID])
            self.assertEqual((plan.assumptions.get("clarification") or {}).get("confirm_prompt"), _GUIDE)
            self.assertEqual(row["options"][0]["label"], _ZH)
            self.assertEqual((row.get("open") or {}).get("label"), "Your own open intent")
            self.assertNotIn("unresolved_intent", plan.steps[0].inputs)

    def test_certain_open_skips_the_recovery_card(self) -> None:
        """分类已经确定 open 时直接出图，不出现恢复卡。"""

        print("\n[TestAiUnresolvedRecovery] 确定 open 不出恢复卡")
        fake = FakeLLMProvider(
            replies=[
                json.dumps({"steps": _STEPS}),
                json.dumps({"shares": "000300.SH"}),
            ]
        )
        plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(
            _ZH,
            mode="plan",
            parsed=open_parsed(_ZH),
        )
        print(" skills:", [step.skill_name for step in plan.steps], plan.planner_trace.get("intent_job"))
        self.assertEqual(plan.planner_trace.get("intent_job"), "open")
        self.assertNotIn("unresolved_intent", _names(plan))
        self.assertEqual(
            [step.skill_name for step in plan.steps],
            ["qt.ai.data.kline", "qt.ai.hp.returns", "qt.ai.hp.plot"],
        )

    def test_other_cards_do_not_offer_unresolved_intent(self) -> None:
        """不支持、非法 open、缺日期和因子 IC 不出现这张控制卡。"""

        print("\n[TestAiUnresolvedRecovery] 其它澄清卡不带 unresolved_intent")
        blocked = Planner(self.registry, env_facts={}).build_plan("申万行业", mode="plan")
        print(" not_supported:", blocked.steps[0].inputs.get("reason"), _names(blocked))
        self.assertNotIn("unresolved_intent", _names(blocked))
        self.assertEqual(_names(blocked), [])
        self.assertEqual(blocked.steps[0].inputs.get("reason"), "sw_industry_dsl_not_in_1_0")

        too_many = FakeLLMProvider(replies=[json.dumps({"steps": _TOO_MANY})])
        rejected = Planner(self.registry, provider=too_many, env_facts={}).build_plan(
            _ZH,
            mode="plan",
            parsed=open_parsed(_ZH),
        )
        print(" open reason:", rejected.steps[0].inputs.get("reason"), _names(rejected))
        self.assertEqual(rejected.steps[0].inputs.get("reason"), "open_too_many_steps")
        self.assertEqual(_names(rejected), ["recover"])
        self.assertNotIn("unresolved_intent", _names(rejected))

        refill = Planner(self.registry, env_facts={}).build_plan(
            "download A-share daily data to local datasource",
            mode="plan",
        )
        print(" refill:", _names(refill))
        self.assertEqual(_names(refill), ["start", "end"])

        factor = Planner(self.registry, env_facts={}).build_plan(
            "factor IC summary for selection pool",
            mode="plan",
        )
        print(" factor:", _names(factor))
        self.assertNotIn("unresolved_intent", _names(factor))
        self.assertIn("factor_htype", _names(factor))

    def test_compose_open_uses_original_sentence_and_skips_classify(self) -> None:
        """点给出开放计划后用原句组图，不再消耗分类回复。"""

        print("\n[TestAiUnresolvedRecovery] 强制 open 不再分类")
        decoy = _job({"job": "data.summary"})
        fake = FakeLLMProvider(
            replies=[
                "not-a-protocol",
                json.dumps({"steps": _STEPS}),
                json.dumps({"shares": "000300.SH"}),
                decoy,
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                provider=fake,
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "s-compose-open"
            first = asst.plan(_ZH, response_style="raw", session_id=sid)
            before = asst.session_store.load(sid)
            clar = next(item for item in (first.get("human_cards") or []) if item.get("kind") == "clarify")
            shares = before.task.slots.get("shares")
            print(" card:", clar.get("text"))
            print(" shares:", None if shares is None else shares.value)
            print(" prompts after card:", len(fake.prompts), "left:", fake.replies)
            self.assertEqual(clar.get("text"), _GUIDE)
            self.assertEqual(clar["payload"]["pending"][0].get("prompt"), _GUIDE)
            self.assertEqual(clar["payload"]["pending"][0]["options"][0].get("id"), CONFIRM_OPEN_ID)
            self.assertEqual((clar["payload"]["pending"][0].get("open") or {}).get("label"), "Your own open intent")
            self.assertNotIn("open_label", clar["payload"]["pending"][0])
            self.assertIsNone(shares)
            self.assertNotIn("unresolved_intent", before.task.slots)
            catalogs = [text for text in fake.prompts if text.startswith("Official jobs:")]
            self.assertEqual(len(catalogs), 1)

            second = asst.plan(
                "",
                response_style="raw",
                session_id=sid,
                patches={"intent": CONFIRM_OPEN_ID},
            )
            after = asst.session_store.load(sid)
            plan = second.get("plan") or {}
            skills = [step.get("skill_name") for step in (plan.get("steps") or [])]
            trace = plan.get("planner_trace") or {}
            catalogs_after = [text for text in fake.prompts if text.startswith("Official jobs:")]
            allowed = [text for text in fake.prompts if text.startswith("Allowed skills:")]
            print(" skills:", skills, "intent:", trace.get("intent_job"))
            print(" catalogs:", len(catalogs_after), "open prompts:", len(allowed), "left:", fake.replies)
            print(" last prompt:", fake.prompts[-1][:80] if fake.prompts else "")
            print(" slots:", list((after.task.slots or {}).keys()) if after.task else None)
            self.assertNotEqual(after.task.id, before.task.id)
            self.assertEqual(after.task.user_query, _ZH)
            self.assertEqual(trace.get("intent_job"), "open")
            self.assertEqual(skills, ["qt.ai.data.kline", "qt.ai.hp.returns", "qt.ai.hp.plot"])
            self.assertEqual(len(catalogs_after), 1)
            self.assertEqual(len(allowed), 1)
            self.assertFalse(fake.prompts[-1].startswith("Official jobs:"))
            self.assertNotIn("unresolved_intent", after.task.slots)
            self.assertEqual(plan["steps"][0]["inputs"].get("shares"), "000300.SH")

    def test_compose_open_too_many_steps_stays_a_reason_card(self) -> None:
        """强制 open 后步数超限，仍是 open_* 说明，没有恢复卡。"""

        print("\n[TestAiUnresolvedRecovery] 强制 open 超步数")
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
            sid = "s-open-too-many"
            asst.plan(_ZH, response_style="raw", session_id=sid)
            second = asst.plan(
                "",
                response_style="raw",
                session_id=sid,
                patches={"intent": CONFIRM_OPEN_ID},
            )
            plan = second.get("plan") or {}
            steps = plan.get("steps") or []
            pending = ((plan.get("assumptions") or {}).get("clarification") or {}).get("pending") or []
            reason = (steps[0].get("inputs") or {}).get("reason") if steps else ""
            after = asst.session_store.load(sid)
            kinds = [item.get("kind") for item in (second.get("human_cards") or [])]
            error = next((item for item in (second.get("human_cards") or []) if item.get("kind") == "error"), None)
            print(" reason:", reason, "pending:", pending)
            print(" status:", after.task.status if after.task else None)
            print(" kinds:", kinds)
            print(" error:", None if error is None else error.get("text"))
            print(" plan_md:", bool(second.get("plan_md")))
            self.assertEqual(reason, "open_too_many_steps")
            self.assertEqual([item.get("name") for item in pending if isinstance(item, dict)], ["recover"])
            self.assertEqual(after.task.status, "clarifying")
            self.assertIn("clarify", kinds)
            self.assertIsNone(error)
            self.assertIn("open_too_many_steps", str((pending[0] or {}).get("prompt") or ""))
            self.assertFalse(second.get("plan_md"))

    def test_abandon_closes_the_task(self) -> None:
        """放弃结束当前请求，不再规划。"""

        print("\n[TestAiUnresolvedRecovery] 放弃收口")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "s-abandon"
            asst.plan(_ZH, response_style="raw", session_id=sid)
            second = asst.plan("放弃当前计划", response_style="raw", session_id=sid)
            after = asst.session_store.load(sid)
            assumptions = (second.get("plan") or {}).get("assumptions") or {}
            print(" abandoned:", assumptions.get("abandoned"), "status:", after.task.status if after.task else None)
            print(" steps:", (second.get("execution") or {}).get("steps"))
            self.assertTrue(assumptions.get("abandoned"))
            self.assertEqual(after.task.status, "cancelled")
            self.assertEqual((second.get("execution") or {}).get("steps"), [])

    def test_rewrite_reclassifies_the_new_sentence(self) -> None:
        """开放输入整句替换原句并重新分类；选项标签文字不是强制 open。"""

        print("\n[TestAiUnresolvedRecovery] 重写后重新分类")
        typed = "给出开放计划"
        fake = FakeLLMProvider(
            replies=[
                "not-a-protocol",
                json.dumps({"steps": _TOO_MANY}),
                "not-a-protocol",
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                provider=fake,
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "s-rewrite"
            asst.plan(_ZH, response_style="raw", session_id=sid)
            before = asst.session_store.load(sid)
            asst.plan(
                "",
                response_style="raw",
                session_id=sid,
                patches={"intent": CONFIRM_OPEN_ID},
            )
            second = asst.plan(
                "",
                response_style="raw",
                session_id=sid,
                patches={"recover": typed},
                allow_composer_slot_fill=False,
            )
            after = asst.session_store.load(sid)
            catalogs = [text for text in fake.prompts if text.startswith("Official jobs:")]
            opened = [text for text in fake.prompts if text.startswith("Allowed skills:")]
            plan = second.get("plan") or {}
            pending = ((plan.get("assumptions") or {}).get("clarification") or {}).get("pending") or []
            print(" catalogs:", len(catalogs), "opened:", len(opened))
            print(" user_query:", after.task.user_query if after.task else None)
            print(" pending:", [item.get("name") for item in pending if isinstance(item, dict)])
            self.assertEqual(len(catalogs), 2)
            self.assertIn("User sentence:\n" + typed, catalogs[-1])
            self.assertEqual(len(opened), 1)
            self.assertNotEqual(after.task.id, before.task.id)
            users = [str(row.get("text") or "") for row in after.messages if row.get("kind") == "user_text"]
            print(" users:", users)
            self.assertIn(typed, users)
            self.assertEqual(
                [item.get("name") for item in pending if isinstance(item, dict)],
                ["intent"],
            )
            self.assertNotIn("unresolved_intent", after.task.slots)

    def test_answers_follow_the_recovery_question(self) -> None:
        """按题序交回的开放、放弃和重写仍由 Session 解释。"""

        print("\n[TestAiUnresolvedRecovery] answers 按题号恢复")
        compose = FakeLLMProvider(
            replies=[
                "not-a-protocol",
                json.dumps({"steps": _STEPS}),
                json.dumps({"shares": "000300.SH"}),
                _job({"job": "data.summary"}),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                provider=compose,
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "s-answers-open"
            asst.plan(_ZH, response_style="raw", session_id=sid)
            before = asst.session_store.load(sid)
            second = asst.plan("", response_style="raw", session_id=sid, answers=[CONFIRM_OPEN_ID])
            after = asst.session_store.load(sid)
            plan = second.get("plan") or {}
            skills = [step.get("skill_name") for step in (plan.get("steps") or [])]
            print(" compose skills:", skills, "intent:", (plan.get("planner_trace") or {}).get("intent_job"))
            self.assertNotEqual(after.task.id, before.task.id)
            self.assertEqual(after.task.user_query, _ZH)
            self.assertEqual((plan.get("planner_trace") or {}).get("intent_job"), "open")
            self.assertEqual(skills, ["qt.ai.data.kline", "qt.ai.hp.returns", "qt.ai.hp.plot"])

        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "s-answers-abandon"
            asst.plan(_ZH, response_style="raw", session_id=sid)
            second = asst.plan("放弃当前计划", response_style="raw", session_id=sid)
            after = asst.session_store.load(sid)
            assumptions = (second.get("plan") or {}).get("assumptions") or {}
            print(" abandon:", assumptions.get("abandoned"), after.task.status if after.task else None)
            self.assertTrue(assumptions.get("abandoned"))
            self.assertEqual(after.task.status, "cancelled")

        typed_rewrite = "只看沪深300的日线收益"
        rewrite = FakeLLMProvider(
            replies=[
                "not-a-protocol",
                json.dumps({"steps": _TOO_MANY}),
                "not-a-protocol",
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                provider=rewrite,
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "s-answers-rewrite"
            asst.plan(_ZH, response_style="raw", session_id=sid)
            asst.plan(
                "",
                response_style="raw",
                session_id=sid,
                answers=[CONFIRM_OPEN_ID],
            )
            typed = typed_rewrite
            second = asst.plan(
                "",
                response_style="raw",
                session_id=sid,
                answers=[typed],
                allow_composer_slot_fill=False,
            )
            after = asst.session_store.load(sid)
            catalogs = [text for text in rewrite.prompts if text.startswith("Official jobs:")]
            print(" rewrite query:", after.task.user_query if after.task else None)
            print(" catalogs:", len(catalogs))
            self.assertEqual(len(catalogs), 2)
            self.assertIn("User sentence:\n" + typed, catalogs[-1])
            users = [str(row.get("text") or "") for row in after.messages if row.get("kind") == "user_text"]
            print(" rewrite users:", users)
            self.assertIn(typed, users)
            self.assertNotIn("unresolved_intent", after.task.slots)

    def test_open_slot_answer_resumes_the_same_graph(self) -> None:
        """开放图缺列名时，控件提交列名恢复原图，不再分类。空窗口不出日期卡，两端写入内核窗口。"""

        print("\n[TestAiUnresolvedRecovery] 开放图补列名后恢复原图")
        query = "取 000300.SH 的 close，算收益，再出一页图"
        rough = [
            {
                "skill_name": "qt.ai.data.history",
                "inputs": {
                    "freq": "d",
                    "shares": "000300.SH",
                    "htype_names": "['日线']",
                    "asset_type": "IDX",
                },
            },
            {"skill_name": "qt.ai.hp.returns", "inputs": {"method": "pct_change"}},
            {"skill_name": "qt.ai.hp.plot", "inputs": {"shares": "000300.SH"}},
        ]
        decoy = _job({"job": "data.refill"})
        fake = FakeLLMProvider(
            replies=[
                "not-a-protocol",
                json.dumps({"steps": rough}),
                json.dumps({"shares": "000300.SH", "freq": "d", "asset_type": "IDX"}),
                json.dumps({
                    "questions": [
                        {
                            "name": "htype_names",
                            "explanation": "请给出数据类型",
                            "options": [],
                            "open": {"label": "其它"},
                        }
                    ]
                }, ensure_ascii=False),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                provider=fake,
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "s-resume-open"
            asst.plan(query, response_style="raw", session_id=sid)
            opened = asst.plan(
                "",
                response_style="raw",
                session_id=sid,
                patches={"intent": CONFIRM_OPEN_ID},
            )
            held = asst.session_store.load(sid)
            clar = (opened.get("plan") or {}).get("assumptions", {}).get("clarification") or {}
            pending = held.task.pending_clarification if held.task is not None else {}
            snapshot = [row.get("skill_name") for row in (clar.get("accepted_steps") or [])]
            print(" resume_job:", clar.get("resume_job"), "snapshot:", snapshot)
            print(" pending:", [item.get("name") for item in (clar.get("pending") or []) if isinstance(item, dict)])
            print(" task job:", held.task.job if held.task else None)
            self.assertEqual(clar.get("resume_job"), "open")
            self.assertEqual(
                snapshot,
                ["qt.ai.data.history", "qt.ai.hp.returns", "qt.ai.hp.plot"],
            )
            self.assertEqual(pending.get("resume_job"), "open")
            self.assertFalse(str(held.task.job or ""))
            catalogs = [text for text in fake.prompts if text.startswith("Official jobs:")]
            fake.replies.extend([
                json.dumps({"htype_names": "close"}),
                "polish placeholder",
                "polish placeholder",
                "polish placeholder",
                decoy,
            ])
            second = asst.plan(
                "",
                response_style="raw",
                session_id=sid,
                patches={"htype_names": "close"},
            )
            after = asst.session_store.load(sid)
            plan = second.get("plan") or {}
            steps = plan.get("steps") or []
            skills = [step.get("skill_name") for step in steps]
            depends = [list(step.get("depends_on") or []) for step in steps]
            history = next((step for step in steps if step.get("skill_name") == "qt.ai.data.history"), {})
            names = [
                item.get("name")
                for item in ((plan.get("assumptions") or {}).get("clarification") or {}).get("pending") or []
                if isinstance(item, dict)
            ]
            catalogs_after = [text for text in fake.prompts if text.startswith("Official jobs:")]
            print(" skills:", skills, plan.get("execution_mode"))
            print(" depends:", depends)
            print(" history:", (history.get("inputs") or {}))
            print(" catalogs:", len(catalogs), len(catalogs_after), "left:", fake.replies)
            print(" names:", names, "job:", after.task.job if after.task else None)
            self.assertEqual(catalogs_after, catalogs)
            self.assertIn(decoy, fake.replies)
            self.assertEqual(plan.get("execution_mode"), "dry_run")
            self.assertEqual(skills, ["qt.ai.data.history", "qt.ai.hp.returns", "qt.ai.hp.plot"])
            self.assertEqual((history.get("inputs") or {}).get("htype_names"), "close")
            from qteasy_ai.slot_graph import kernel_window
            window = kernel_window()
            print(" kernel:", window)
            self.assertEqual((history.get("inputs") or {}).get("start"), window["start"])
            self.assertEqual((history.get("inputs") or {}).get("end"), window["end"])
            self.assertNotIn("start", names)
            self.assertNotIn("end", names)
            self.assertEqual(depends, [[], ["step_1"], ["step_2"]])
            self.assertNotIn("unresolved_intent", names)
            self.assertFalse(str(after.task.job or ""))


if __name__ == "__main__":
    unittest.main()
