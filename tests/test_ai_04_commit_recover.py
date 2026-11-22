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
        split_ask = json.dumps({"task": ask, "question": ""}, ensure_ascii=False)
        plan, fake = self._plan(ask, [split_ask, unsure])
        print(" job:", plan.planner_trace.get("intent_job"), plan.planner_trace.get("intent_rationale"))
        print(" skills:", [step.skill_name for step in plan.steps])
        print(" pending:", _pending_names(plan))
        print(" prompt:", fake.prompts)
        self.assertEqual(plan.planner_trace.get("intent_job"), "research.hold_compare")
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(_pending_names(plan), [])
        self.assertIn("holdings", str(plan.steps[0].inputs.get("missing_info") or ""))
        self.assertNotIn("qt.ai.data.history", [step.skill_name for step in plan.steps])
        self.assertNotIn("qt.ai.hp.describe", [step.skill_name for step in plan.steps])
        dumped = json.dumps(
            [dict(step.inputs) for step in plan.steps],
            ensure_ascii=False,
            default=str,
        )
        self.assertNotIn("600519", dumped)

        trailed = ask + "，跟上次是一回事吗"
        split_trailed = json.dumps(
            {"task": ask, "question": "跟上次是一回事吗"},
            ensure_ascii=False,
        )
        again, seen = self._plan(trailed, [split_trailed, unsure])
        classify = [item for item in seen.prompts if "Official and system Job ids:" in item]
        print(" trailed job:", again.planner_trace.get("intent_job"))
        print(" trailed classify:", classify)
        self.assertEqual(again.planner_trace.get("intent_job"), "research.hold_compare")
        self.assertTrue(classify)
        self.assertNotIn("是一回事吗", classify[0])
        self.assertNotIn("跟上次", classify[0])

    def test_unrelated_uncertain_stays_unmatched(self) -> None:
        """对不上闭合菜谱的短句仍是开放计划恢复，不新造 Job。"""

        print("\n[TestAi04CommitRecover] 对不上的短句保持未匹配")
        unsure = json.dumps({"job": "clarify", "uncertain": True}, ensure_ascii=False)
        split_day = json.dumps({"task": "今天星期几", "question": ""}, ensure_ascii=False)
        plan, _fake = self._plan("今天星期几", [split_day, unsure])
        print(" job:", plan.planner_trace.get("intent_job"))
        print(" pending:", _pending_names(plan))
        self.assertNotEqual(plan.planner_trace.get("intent_job"), "research.hold_compare")
        self.assertIn("unresolved_intent", _pending_names(plan))

    def test_prior_question_uses_previous_commit(self) -> None:
        """有模型的纯反问不进分类。没有模型时也不升成持有对比。"""

        print("\n[TestAi04CommitRecover] 反问不升成持有对比")
        state = ConversationState.empty("commit-prior")
        state.start_task(query="000001.SZ 和 000002.SZ 做一条等权组合", job="research.hold_compare")
        state.set_slot("shares", "000001.SZ,000002.SZ", source="user", confirmed=True)
        state.set_slot("mode", "equal", source="user", confirmed=True)
        asked = "跟上次是一回事吗"
        fake = FakeLLMProvider(
            replies=[json.dumps({"task": "", "question": asked}, ensure_ascii=False)]
        )
        plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(
            asked,
            mode="plan",
            session=state,
        )
        classify = [item for item in fake.prompts if "Official and system Job ids:" in item]
        print(" job:", plan.planner_trace.get("intent_job"))
        print(" classify:", classify)
        print(" prompts:", fake.prompts)
        self.assertNotEqual(plan.planner_trace.get("intent_job"), "research.hold_compare")
        self.assertEqual(classify, [])

        empty = Planner(self.registry, env_facts={}).build_plan(asked, mode="plan")
        print(" empty job:", empty.planner_trace.get("intent_job"))
        self.assertNotEqual(empty.planner_trace.get("intent_job"), "research.hold_compare")


if __name__ == "__main__":
    unittest.main()
