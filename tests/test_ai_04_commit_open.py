# coding=utf-8
# ======================================
# File: test_ai_04_commit_open.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-09
# Desc:
# 开放图走同一次提交。要图却没有 plot 时不可确认。
# ======================================

import json
import unittest

from qteasy_ai.app import build_default_registry
from qteasy_ai.human_card import project_human_cards
from qteasy_ai.intents import IntentCatalog
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.slot_graph import commit_open_graph


class _Step:
    """手工步骤，只带技能名和输入。"""

    def __init__(self, skill_name: str, inputs: dict) -> None:
        self.skill_name = skill_name
        self.inputs = dict(inputs)


class TestAi04CommitOpen(unittest.TestCase):
    """开放图的权重和出图前提。"""

    def setUp(self) -> None:
        self.registry = build_default_registry()

    def test_numeric_weights_gain_weighted_mode(self) -> None:
        """组合步只有数字权重时，同一次写入 mode=weighted。"""

        print("\n[TestAi04CommitOpen] 开放图补 weighted")
        step = _Step("qt.ai.hp.portfolio", {"weights": [0.5, 0.3, 0.2]})
        reason = commit_open_graph([step], "000001.SZ 000002.SZ 000858.SZ 做一条组合")
        print(" reason:", reason)
        print(" inputs:", step.inputs)
        self.assertEqual(reason, "")
        self.assertEqual(step.inputs.get("mode"), "weighted")
        self.assertEqual(step.inputs.get("weights"), [0.5, 0.3, 0.2])

        opened = [
            {
                "skill_name": "qt.ai.data.kline",
                "inputs": {"shares": "000001.SZ,000002.SZ,000858.SZ"},
                "depends_on": [],
            },
            {
                "skill_name": "qt.ai.hp.portfolio",
                "inputs": {"weights": [0.5, 0.3, 0.2]},
                "depends_on": ["step_1"],
            },
            {
                "skill_name": "qt.ai.hp.plot",
                "inputs": {},
                "depends_on": ["step_2"],
            },
        ]
        fake = FakeLLMProvider(replies=[json.dumps({"steps": opened}, ensure_ascii=False)])
        plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(
            "000001.SZ 000002.SZ 000858.SZ 做一条组合",
            mode="plan",
            forced_job="open",
        )
        print(" plan skills:", [step.skill_name for step in plan.steps])
        print(" plan mode:", plan.steps[1].inputs.get("mode"), plan.steps[1].inputs.get("weights"))
        self.assertEqual(plan.steps[1].inputs.get("mode"), "weighted")
        kinds, confirmable = _card_state(plan, self.registry)
        print(" cards:", kinds, "confirmable:", confirmable)
        self.assertIn("plan_ready", kinds)
        self.assertTrue(confirmable)
        self.assertEqual(IntentCatalog().legal_max_steps(), 3)

    def test_chart_without_plot_is_not_confirmable(self) -> None:
        """要一条线却停在 describe，确认门前失败。回测仍拒绝。"""

        print("\n[TestAi04CommitOpen] 要图没有 plot")
        described = [
            {
                "skill_name": "qt.ai.data.history",
                "inputs": {"shares": "000001.SZ"},
                "depends_on": [],
            },
            {
                "skill_name": "qt.ai.hp.portfolio",
                "inputs": {"weights": [0.5, 0.5]},
                "depends_on": ["step_1"],
            },
            {
                "skill_name": "qt.ai.hp.describe",
                "inputs": {},
                "depends_on": ["step_2"],
            },
        ]
        fake = FakeLLMProvider(replies=[json.dumps({"steps": described}, ensure_ascii=False)])
        plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(
            "平安和招行放一起成一条线",
            mode="plan",
            forced_job="open",
        )
        print(" describe skills:", [step.skill_name for step in plan.steps])
        print(" reason:", plan.steps[0].inputs.get("reason"))
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertNotIn("qt.ai.hp.describe", [step.skill_name for step in plan.steps])
        kinds, confirmable = _card_state(plan, self.registry)
        print(" cards:", kinds, "confirmable:", confirmable)
        self.assertNotIn("plan_ready", kinds)
        self.assertFalse(confirmable)

        banned = [
            {
                "skill_name": "qt.ai.backtest.run_builtin",
                "inputs": {},
                "depends_on": [],
            }
        ]
        refused = Planner(
            self.registry,
            provider=FakeLLMProvider(replies=[json.dumps({"steps": banned}, ensure_ascii=False)]),
            env_facts={},
        ).build_plan("回测一下", mode="plan", forced_job="open")
        names = " ".join(step.skill_name for step in refused.steps)
        print(" banned skills:", names)
        print(" banned reason:", refused.assumptions.get("downgrade_reason"))
        self.assertNotIn("backtest", names)
        self.assertNotIn("refill", names)
        self.assertNotIn("codegen", names)
        self.assertNotIn("live", names)


def _card_state(plan, registry):
    """人读卡种类，以及计划卡是否可确认。没有计划卡时不可确认。"""

    cards = project_human_cards(
        {
            "run_id": "run_commit_open",
            "plan": {
                "plan_id": plan.plan_id,
                "mode": plan.mode,
                "user_query": plan.user_query,
                "assumptions": dict(plan.assumptions or {}),
                "steps": [
                    {
                        "step_id": step.step_id,
                        "skill_name": step.skill_name,
                        "inputs": dict(step.inputs or {}),
                        "side_effects": {"description": "readonly"},
                    }
                    for step in plan.steps
                ],
            },
            "execution": {"status": "dry_run", "steps": []},
        },
        requested_mode="plan",
        query=plan.user_query,
        registry=registry,
        include_user_text=False,
    )
    ready = next((item for item in cards if item["kind"] == "plan_ready"), None)
    confirmable = bool((ready or {}).get("payload", {}).get("confirmable"))
    return [item["kind"] for item in cards], confirmable


if __name__ == "__main__":
    unittest.main()
