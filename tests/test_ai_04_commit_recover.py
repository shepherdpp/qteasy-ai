# coding=utf-8
# ======================================
# File: test_ai_04_commit_recover.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-09
# Desc:
# 分类不确定时先看持有对比提及。
# 指向上一轮的反问不进分类原文。
# ======================================

import json
import unittest

from qteasy_ai.app import build_default_registry
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.session import ConversationState


def _pending_names(plan) -> list:
    """澄清卡槽名。"""

    blob = (plan.assumptions or {}).get("clarification") or {}
    return [str(item.get("name") or "") for item in (blob.get("pending") or []) if isinstance(item, dict)]


class TestAi04CommitRecover(unittest.TestCase):
    """不确定分类的提及恢复。"""

    def setUp(self) -> None:
        self.registry = build_default_registry()

    def _plan(self, query: str, replies: list):
        """用罐头分类跑一轮。"""

        fake = FakeLLMProvider(replies=list(replies))
        plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(query, mode="plan")
        return plan, fake

    def test_uncertain_hold_compare_stays_and_ignores_prior_question(self) -> None:
        """像持有对比就留下并追问比例。句尾反问不进分类。"""

        print("\n[TestAi04CommitRecover] 不确定仍留在持有对比")
        ask = "平安、招行、茅台，轻重不同，放一起成一条线"
        unsure = json.dumps({"job": "research.hold_compare", "uncertain": True}, ensure_ascii=False)
        plan, fake = self._plan(ask, [unsure])
        print(" job:", plan.planner_trace.get("intent_job"), plan.planner_trace.get("intent_rationale"))
        print(" skills:", [step.skill_name for step in plan.steps])
        print(" pending:", _pending_names(plan))
        print(" prompt:", fake.prompts[0])
        self.assertEqual(plan.planner_trace.get("intent_job"), "research.hold_compare")
        self.assertEqual(_pending_names(plan), ["holdings"])
        self.assertNotIn("weights", _pending_names(plan))
        self.assertNotIn("qt.ai.data.history", [step.skill_name for step in plan.steps])
        self.assertNotIn("qt.ai.hp.describe", [step.skill_name for step in plan.steps])
        dumped = json.dumps(
            [dict(step.inputs) for step in plan.steps],
            ensure_ascii=False,
            default=str,
        )
        self.assertNotIn("600519", dumped)

        trailed = ask + "，跟上次是一回事吗"
        again, seen = self._plan(trailed, [unsure])
        print(" trailed job:", again.planner_trace.get("intent_job"))
        print(" trailed prompt:", seen.prompts[0])
        self.assertEqual(again.planner_trace.get("intent_job"), "research.hold_compare")
        self.assertNotIn("是一回事吗", seen.prompts[0])
        self.assertNotIn("跟上次", seen.prompts[0])

    def test_unrelated_uncertain_stays_unmatched(self) -> None:
        """对不上闭合菜谱的短句仍是开放计划恢复，不新造 Job。"""

        print("\n[TestAi04CommitRecover] 对不上的短句保持未匹配")
        unsure = json.dumps({"job": "clarify", "uncertain": True}, ensure_ascii=False)
        plan, _fake = self._plan("今天星期几", [unsure])
        print(" job:", plan.planner_trace.get("intent_job"))
        print(" pending:", _pending_names(plan))
        self.assertNotEqual(plan.planner_trace.get("intent_job"), "research.hold_compare")
        self.assertIn("unresolved_intent", _pending_names(plan))

    def test_prior_question_uses_previous_commit(self) -> None:
        """只有反问时，用上一轮已提交的值回答。没有提交就说明没有可对照的运行。"""

        print("\n[TestAi04CommitRecover] 反问对照上一轮")
        state = ConversationState.empty("commit-prior")
        state.start_task(query="000001.SZ 和 000002.SZ 做一条等权组合", job="research.hold_compare")
        state.set_slot("shares", "000001.SZ,000002.SZ", source="user", confirmed=True)
        state.set_slot("mode", "equal", source="user", confirmed=True)
        plan = Planner(self.registry, provider=FakeLLMProvider(replies=[]), env_facts={}).build_plan(
            "跟上次是一回事吗",
            mode="plan",
            session=state,
        )
        reply = str((plan.assumptions or {}).get("prior_reply") or "")
        print(" reply:", reply)
        self.assertIn("000001.SZ,000002.SZ", reply)
        self.assertIn("equal", reply)
        self.assertEqual(plan.planner_trace.get("rationale"), "prior_question")

        empty = Planner(self.registry, env_facts={}).build_plan("跟上次是一回事吗", mode="plan")
        print(" empty:", empty.assumptions.get("prior_reply"))
        self.assertIn("没有可对照的运行", str(empty.assumptions.get("prior_reply") or ""))


if __name__ == "__main__":
    unittest.main()
