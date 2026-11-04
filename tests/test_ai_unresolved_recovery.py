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
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider


_ZH = "取 000300.SH 日线，算收益，再出一页图，请生成一个简短的开放计划"
_ZH_PROMPT = "您的需求无法跟现成的操作模版匹配（job），是否需要我创建一份开放计划？"
_EN_PROMPT = "This request does not match a built-in operation template (job). Create an open plan?"
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

        print("\n[TestAiUnresolvedRecovery] 分类落空出固定恢复卡")
        bare = Planner(self.registry, env_facts={}).build_plan("xyzzy unmatched formula 12345", mode="plan")
        print(" bare prompt:", (bare.assumptions.get("clarification") or {}).get("confirm_prompt"))
        self.assertEqual(_names(bare), ["unresolved_intent"])
        self.assertEqual((bare.assumptions.get("clarification") or {}).get("confirm_prompt"), _EN_PROMPT)

        replies = (
            {"job": "clarify"},
            {"job": "data.read", "uncertain": True},
            {"jobs": ["data.read", "data.summary"]},
            {"job": "not-a-job"},
        )
        for payload in replies:
            fake = FakeLLMProvider(replies=[_job(payload), "polish-must-not-run"])
            plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(_ZH, mode="plan")
            row = _pending(plan)[0]
            print(" payload:", payload, "prompts:", len(fake.prompts), "left:", fake.replies)
            print(" prompt:", (plan.assumptions.get("clarification") or {}).get("confirm_prompt"))
            self.assertEqual(len(fake.prompts), 1)
            self.assertEqual(fake.replies, ["polish-must-not-run"])
            self.assertEqual(_names(plan), ["unresolved_intent"])
            self.assertEqual([item["id"] for item in row["options"]], ["compose_open", "abandon"])
            self.assertEqual((plan.assumptions.get("clarification") or {}).get("confirm_prompt"), _ZH_PROMPT)
            self.assertEqual(row["options"][0]["label"], "给出开放计划")
            self.assertEqual(row["options"][1]["label"], "放弃")
            self.assertEqual(row.get("open_label"), "重写需求")
            self.assertNotIn("unresolved_intent", plan.steps[0].inputs)

    def test_certain_open_skips_the_recovery_card(self) -> None:
        """分类已经确定 open 时直接出图，不出现恢复卡。"""

        print("\n[TestAiUnresolvedRecovery] 确定 open 不出恢复卡")
        fake = FakeLLMProvider(replies=[_job({"job": "open"}), json.dumps({"steps": _STEPS})])
        plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(_ZH, mode="plan")
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
        self.assertNotEqual(blocked.steps[0].inputs.get("fallback_action"), "clarify_required")

        too_many = FakeLLMProvider(replies=[_job({"job": "open"}), json.dumps({"steps": _TOO_MANY})])
        rejected = Planner(self.registry, provider=too_many, env_facts={}).build_plan(_ZH, mode="plan")
        print(" open reason:", rejected.steps[0].inputs.get("reason"), _names(rejected))
        self.assertEqual(rejected.steps[0].inputs.get("reason"), "open_too_many_steps")
        self.assertEqual(_names(rejected), [])

        refill = Planner(self.registry, env_facts={}).build_plan(
            "download A-share daily data to local datasource",
            mode="plan",
        )
        print(" refill:", _names(refill))
        self.assertEqual(_names(refill), ["start", "end"])

        factor = Planner(self.registry, env_facts={}).build_plan("factor ic", mode="plan")
        print(" factor:", _names(factor))
        self.assertNotIn("unresolved_intent", _names(factor))
        self.assertIn("factor_htype", _names(factor))

    def test_compose_open_uses_original_sentence_and_skips_classify(self) -> None:
        """点给出开放计划后用原句组图，不再消耗分类回复。"""

        print("\n[TestAiUnresolvedRecovery] 强制 open 不再分类")
        decoy = _job({"job": "data.summary"})
        # 首句会探路分类一次，再正式分类一次；其后才是开放图与不得被消耗的 Job。
        fake = FakeLLMProvider(
            replies=[
                _job({"job": "clarify"}),
                _job({"job": "clarify"}),
                json.dumps({"steps": _STEPS}),
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
            self.assertEqual(clar.get("text"), _ZH_PROMPT)
            self.assertEqual(clar["payload"]["pending"][0].get("open_label"), "重写需求")
            self.assertIsNotNone(shares)
            self.assertEqual(shares.value, "000300.SH")
            self.assertNotIn("unresolved_intent", before.task.slots)
            catalogs = [text for text in fake.prompts if text.startswith("Official and system Job ids:")]
            self.assertEqual(len(catalogs), 2)

            second = asst.plan(
                "",
                response_style="raw",
                session_id=sid,
                patches={"unresolved_intent": "compose_open"},
            )
            after = asst.session_store.load(sid)
            plan = second.get("plan") or {}
            skills = [step.get("skill_name") for step in (plan.get("steps") or [])]
            trace = plan.get("planner_trace") or {}
            catalogs_after = [text for text in fake.prompts if text.startswith("Official and system Job ids:")]
            allowed = [text for text in fake.prompts if text.startswith("Allowed skills:")]
            print(" skills:", skills, "intent:", trace.get("intent_job"))
            print(" catalogs:", len(catalogs_after), "open prompts:", len(allowed), "left:", fake.replies)
            print(" last prompt:", fake.prompts[-1][:80] if fake.prompts else "")
            print(" slots:", list((after.task.slots or {}).keys()) if after.task else None)
            self.assertEqual(after.task.id, before.task.id)
            self.assertEqual(trace.get("intent_job"), "open")
            self.assertEqual(skills, ["qt.ai.data.kline", "qt.ai.hp.returns", "qt.ai.hp.plot"])
            self.assertEqual(len(catalogs_after), 2)
            self.assertEqual(len(allowed), 1)
            self.assertFalse(fake.prompts[-1].startswith("Official and system Job ids:"))
            self.assertNotIn("unresolved_intent", after.task.slots)
            self.assertEqual(after.task.slots["shares"].value, "000300.SH")

    def test_compose_open_too_many_steps_stays_a_reason_card(self) -> None:
        """强制 open 后步数超限，仍是 open_* 说明，没有恢复卡。"""

        print("\n[TestAiUnresolvedRecovery] 强制 open 超步数")
        fake = FakeLLMProvider(
            replies=[
                _job({"job": "clarify"}),
                _job({"job": "clarify"}),
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
                patches={"unresolved_intent": "compose_open"},
            )
            plan = second.get("plan") or {}
            steps = plan.get("steps") or []
            pending = ((plan.get("assumptions") or {}).get("clarification") or {}).get("pending") or []
            reason = (steps[0].get("inputs") or {}).get("reason") if steps else ""
            print(" reason:", reason, "pending:", pending)
            self.assertEqual(reason, "open_too_many_steps")
            self.assertEqual(pending, [])

    def test_abandon_closes_the_task(self) -> None:
        """放弃结束当前请求，不再规划。"""

        print("\n[TestAiUnresolvedRecovery] 放弃收口")
        fake = FakeLLMProvider(
            replies=[_job({"job": "clarify"}), _job({"job": "clarify"}), "must-not-run"]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                provider=fake,
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "s-abandon"
            asst.plan(_ZH, response_style="raw", session_id=sid)
            prompts = len(fake.prompts)
            second = asst.plan(
                "",
                response_style="raw",
                session_id=sid,
                patches={"unresolved_intent": "abandon"},
            )
            after = asst.session_store.load(sid)
            err = second.get("error") or {}
            print(" error:", err, "status:", after.task.status if after.task else None)
            print(" prompts:", prompts, len(fake.prompts), "left:", fake.replies)
            self.assertEqual(err.get("code"), "CLARIFICATION_ABANDONED")
            self.assertIn("abandoned", str(err.get("message") or "").lower())
            self.assertEqual(after.task.status, "done")
            self.assertEqual(len(fake.prompts), prompts)
            self.assertEqual(fake.replies, ["must-not-run"])
            self.assertEqual((second.get("execution") or {}).get("steps"), [])

    def test_rewrite_reclassifies_the_new_sentence(self) -> None:
        """开放输入整句替换原句并重新分类；选项标签文字不是强制 open。"""

        print("\n[TestAiUnresolvedRecovery] 重写后重新分类")
        fake = FakeLLMProvider(replies=[_job({"job": "clarify"}), _job({"job": "clarify"})])
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                provider=fake,
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "s-rewrite"
            asst.plan(_ZH, response_style="raw", session_id=sid)
            before = asst.session_store.load(sid)
            typed = "给出开放计划"
            second = asst.plan(
                "",
                response_style="raw",
                session_id=sid,
                patches={"unresolved_intent": typed},
                allow_composer_slot_fill=False,
            )
            after = asst.session_store.load(sid)
            catalogs = [text for text in fake.prompts if text.startswith("Official and system Job ids:")]
            opened = [text for text in fake.prompts if text.startswith("Allowed skills:")]
            plan = second.get("plan") or {}
            pending = ((plan.get("assumptions") or {}).get("clarification") or {}).get("pending") or []
            print(" catalogs:", len(catalogs), "opened:", len(opened))
            print(" user_query:", after.task.user_query if after.task else None)
            print(" pending:", [item.get("name") for item in pending if isinstance(item, dict)])
            self.assertEqual(len(catalogs), 3)
            self.assertIn(typed, catalogs[-1])
            self.assertNotIn(_ZH, catalogs[-1])
            self.assertEqual(opened, [])
            self.assertNotEqual(after.task.id, before.task.id)
            self.assertEqual(after.task.user_query, typed)
            self.assertEqual(
                [item.get("name") for item in pending if isinstance(item, dict)],
                ["unresolved_intent"],
            )
            self.assertNotIn("unresolved_intent", after.task.slots)

    def test_open_slot_answer_resumes_the_same_graph(self) -> None:
        """开放图缺窗口时，控件提交日期恢复原图，不再分类。"""

        print("\n[TestAiUnresolvedRecovery] 开放图补日期后恢复原图")
        query = "取 000300.SH 的 close，算收益，再出一页图"
        rough = [
            {
                "skill_name": "qt.ai.data.history",
                "inputs": {
                    "freq": "d",
                    "shares": "000300.SH",
                    "htype_names": "close",
                    "asset_type": "IDX",
                },
            },
            {"skill_name": "qt.ai.hp.returns", "inputs": {"method": "pct_change"}},
            {"skill_name": "qt.ai.hp.plot", "inputs": {"shares": "000300.SH"}},
        ]
        decoy = _job({"job": "data.refill"})
        fake = FakeLLMProvider(
            replies=[
                _job({"job": "open"}),
                _job({"job": "open"}),
                json.dumps({"steps": rough}),
            ]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                provider=fake,
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "s-resume-open"
            first = asst.plan(query, response_style="raw", session_id=sid)
            held = asst.session_store.load(sid)
            clar = (first.get("plan") or {}).get("assumptions", {}).get("clarification") or {}
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
            catalogs = [text for text in fake.prompts if text.startswith("Official and system Job ids:")]
            fake.replies.extend(["polish placeholder", "polish placeholder", "polish placeholder", decoy])
            second = asst.plan(
                "",
                response_style="raw",
                session_id=sid,
                patches={"start": "20250101"},
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
            catalogs_after = [text for text in fake.prompts if text.startswith("Official and system Job ids:")]
            print(" skills:", skills, plan.get("execution_mode"))
            print(" depends:", depends)
            print(" history:", (history.get("inputs") or {}))
            print(" catalogs:", len(catalogs), len(catalogs_after), "left:", fake.replies)
            print(" names:", names, "job:", after.task.job if after.task else None)
            self.assertEqual(catalogs_after, catalogs)
            self.assertIn(decoy, fake.replies)
            self.assertEqual(plan.get("execution_mode"), "dry_run")
            self.assertEqual(skills, ["qt.ai.data.history", "qt.ai.hp.returns", "qt.ai.hp.plot"])
            self.assertEqual((history.get("inputs") or {}).get("start"), "20250101")
            self.assertEqual(depends, [[], ["step_1"], ["step_2"]])
            self.assertNotIn("unresolved_intent", names)
            self.assertFalse(str(after.task.job or ""))


if __name__ == "__main__":
    unittest.main()
