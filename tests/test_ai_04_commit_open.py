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
import tempfile
import unittest
from typing import Any, Dict, List

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.human_card import project_human_cards
from qteasy_ai.intents import IntentCatalog
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.runtime import SkillRuntime


class TestAi04CommitOpen(unittest.TestCase):
    """开放图的权重和出图前提。"""

    def setUp(self) -> None:
        self.registry = build_default_registry()

    def test_numeric_weights_gain_weighted_mode(self) -> None:
        """组合步只有数字权重时，同一次写入 mode=weighted。"""

        print("\n[TestAi04CommitOpen] 开放图补 weighted")
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
        fake = FakeLLMProvider(
            replies=[
                json.dumps({"steps": opened}, ensure_ascii=False),
                json.dumps(
                    {
                        "shares": "000001.SZ,000002.SZ,000858.SZ",
                        "weights": [0.5, 0.3, 0.2],
                    },
                    ensure_ascii=False,
                ),
            ]
        )
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
        """回测仍拒绝。要图却没有绘图步的断言在代码已经收下的用例里。"""

        print("\n[TestAi04CommitOpen] 要图没有 plot")
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

    def test_two_fund_codes_stay_one_string(self) -> None:
        """开放图取数没有元素合同。两只基金各收一次，不留用户没说的资产类型。"""

        print("\n[TestAi04CommitOpen] 两只基金整格代码")
        query = "510300 和 510500 的日线"
        compose = {
            "steps": [
                {
                    "skill_name": "qt.ai.data.kline",
                    "inputs": {"shares": "510300.SH", "asset_type": "FD"},
                    "depends_on": [],
                }
            ]
        }
        protocol = {"shares": "510300,510500", "freq": "d"}
        plan = Planner(
            self.registry,
            provider=FakeLLMProvider(
                replies=[
                    json.dumps(compose, ensure_ascii=False),
                    json.dumps(protocol, ensure_ascii=False),
                ]
            ),
            env_facts={},
        ).build_plan(query, mode="plan", forced_job="open")
        print(" skills:", [step.skill_name for step in plan.steps])
        print(" inputs:", [dict(step.inputs or {}) for step in plan.steps])
        self.assertEqual([step.skill_name for step in plan.steps], ["qt.ai.data.kline"])
        shares = str(plan.steps[0].inputs.get("shares") or "")
        print(" shares:", shares, "asset_type:", plan.steps[0].inputs.get("asset_type"))
        self.assertEqual(shares, "510300.SH,510500.SH")
        self.assertNotIn("asset_type", plan.steps[0].inputs)
        self.assertNotIsInstance(plan.steps[0].inputs.get("shares"), list)
        missing = SkillRuntime().precheck(
            self.registry.get_metadata("qt.ai.data.kline"),
            dict(plan.steps[0].inputs or {}),
        )
        print(" precheck:", missing)
        self.assertEqual(missing, [])
        kinds, confirmable = _card_state(plan, self.registry)
        print(" cards:", kinds, "confirmable:", confirmable)
        self.assertTrue(confirmable)

    def test_open_limits_still_reject(self) -> None:
        """超步数仍是 open_too_many_steps。回测、补数、代码生成和实盘仍不出现。"""

        print("\n[TestAi04CommitOpen] 步数与禁止技能")
        too_many = {
            "steps": [
                {"skill_name": "qt.ai.data.kline", "inputs": {}, "depends_on": []},
                {"skill_name": "qt.ai.hp.returns", "inputs": {}, "depends_on": ["step_1"]},
                {"skill_name": "qt.ai.hp.normalize", "inputs": {}, "depends_on": ["step_2"]},
                {"skill_name": "qt.ai.hp.plot", "inputs": {}, "depends_on": ["step_3"]},
            ]
        }
        crowded = Planner(
            self.registry,
            provider=FakeLLMProvider(replies=[json.dumps(too_many)]),
            env_facts={},
        ).build_plan("取日线再出一页图", mode="plan", forced_job="open")
        print(" too many:", crowded.assumptions.get("downgrade_reason"))
        self.assertEqual(crowded.assumptions.get("downgrade_reason"), "open_too_many_steps")
        banned = [
            "qt.ai.backtest.run_builtin",
            "qt.ai.data.refill_basic_equity_and_index",
            "qt.ai.strategy.codegen_hybrid",
            "qt.ai.pipeline.live_trade_plan_only",
        ]
        for name in banned:
            refused = Planner(
                self.registry,
                provider=FakeLLMProvider(
                    replies=[json.dumps({"steps": [{"skill_name": name, "inputs": {}, "depends_on": []}]})]
                ),
                env_facts={},
            ).build_plan("做一下", mode="plan", forced_job="open")
            visible = " ".join(step.skill_name for step in refused.steps)
            print(" banned:", name, refused.assumptions.get("downgrade_reason"), visible)
            self.assertEqual(refused.assumptions.get("downgrade_reason"), "open_forbidden_skill")
            self.assertNotIn(name, visible)

    def test_page_without_plot_waits_until_codes_are_accepted(self) -> None:
        """代码收下之后，原句要一页图而图上没有绘图步，计划不可确认。"""

        print("\n[TestAi04CommitOpen] 代码已收但没有绘图")
        query = "510300 和 510500 再出一页图"
        compose = {
            "steps": [
                {
                    "skill_name": "qt.ai.data.kline",
                    "inputs": {"shares": "510300.SH"},
                    "depends_on": [],
                },
                {
                    "skill_name": "qt.ai.hp.describe",
                    "inputs": {},
                    "depends_on": ["step_1"],
                },
            ]
        }
        plan = Planner(
            self.registry,
            provider=FakeLLMProvider(
                replies=[
                    json.dumps(compose, ensure_ascii=False),
                    json.dumps({"shares": "510300,510500", "freq": "d"}, ensure_ascii=False),
                ]
            ),
            env_facts={},
        ).build_plan(query, mode="plan", forced_job="open")
        print(" skills:", [step.skill_name for step in plan.steps])
        print(" reason:", plan.steps[0].inputs.get("reason") if plan.steps else None)
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(
            plan.steps[0].inputs.get("reason"),
            "A chart was requested but the plan has no plot step.",
        )
        kinds, confirmable = _card_state(plan, self.registry)
        print(" cards:", kinds, "confirmable:", confirmable)
        self.assertFalse(confirmable)

    def test_preset_page_sentence_keeps_its_plot(self) -> None:
        """预设图本来就有绘图步。再出一页图仍可确认，也不另出日期卡。"""

        print("\n[TestAi04CommitOpen] 预设图再出一页图")
        query = "600519 和 000858 做一条等权组合，再出一页图"
        plan = Planner(self.registry, env_facts={}).build_plan(query, mode="plan")
        skills = [step.skill_name for step in plan.steps]
        pending = [
            str(item.get("name") or "")
            for item in (((plan.assumptions or {}).get("clarification") or {}).get("pending") or [])
            if isinstance(item, dict)
        ]
        print(" skills:", skills)
        print(" pending:", pending)
        self.assertIn("qt.ai.hp.plot", skills)
        self.assertNotIn("start", pending)
        self.assertNotIn("end", pending)
        kinds, confirmable = _card_state(plan, self.registry)
        print(" cards:", kinds, "confirmable:", confirmable)
        self.assertTrue(confirmable)

    def test_open_code_card_rejects_company_and_accepts_digits(self) -> None:
        """原句没写代码就出代码卡。平安银行不可确认；用户写出的 600519 收成带后缀代码。"""

        print("\n[TestAi04CommitOpen] 开放图代码卡")
        query = "取一支股票的日线，算收益，再出一页图"
        compose = {
            "steps": [
                {
                    "skill_name": "qt.ai.data.kline",
                    "inputs": {"shares": "600519.SH", "asset_type": "E"},
                    "depends_on": [],
                },
                {
                    "skill_name": "qt.ai.hp.returns",
                    "inputs": {},
                    "depends_on": ["step_1"],
                },
                {
                    "skill_name": "qt.ai.hp.plot",
                    "inputs": {},
                    "depends_on": ["step_2"],
                },
            ]
        }
        refused = self._answer_open_code(query, compose, "平安银行", "open-name")
        visible = {
            "steps": refused.get("steps") or [],
            "accepted_steps": (refused.get("assumptions") or {}).get("accepted_steps") or [],
        }
        print(" company skills:", [step.get("skill_name") for step in visible["steps"]])
        pending = _pending(refused)
        print(" company error:", [(item.get("name"), item.get("error")) for item in pending])
        self.assertIn("qt.ai.system.fallback", [step.get("skill_name") for step in visible["steps"]])
        self.assertTrue(any("平安银行" in str(item.get("error") or "") for item in pending))
        self.assertNotIn("平安银行", json.dumps(visible, ensure_ascii=False))
        accepted = self._answer_open_code(query, compose, "600519", "open-code")
        steps = list(accepted.get("steps") or [])
        print(" digit skills:", [step.get("skill_name") for step in steps])
        kline = next((step.get("inputs") or {} for step in steps if step.get("skill_name") == "qt.ai.data.kline"), {})
        returns = next((step.get("inputs") or {} for step in steps if step.get("skill_name") == "qt.ai.hp.returns"), {})
        pending = [
            str(item.get("name") or "")
            for item in (((accepted.get("assumptions") or {}).get("clarification") or {}).get("pending") or [])
            if isinstance(item, dict)
        ]
        print(" shares:", kline.get("shares"), "as_panel:", returns.get("as_panel"), "pending:", pending)
        self.assertEqual(kline.get("shares"), "600519.SH")
        self.assertNotIn("asset_type", kline)
        self.assertTrue(returns.get("as_panel"))
        self.assertNotIn("as_panel", pending)
        self.assertNotIn("start", pending)
        self.assertNotIn("end", pending)
        self.assertNotIn("qt.ai.system.fallback", [step.get("skill_name") for step in steps])

    def test_preset_code_card_rejects_company_name(self) -> None:
        """无代码的摘要句走同一个交卷入口。公司名不能确认。"""

        print("\n[TestAi04CommitOpen] 预设图公司名")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=self.registry,
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            first = _raw_plan(assistant.plan("看一下波动率", response_style="raw", session_id="preset-name"))
            rows = _pending(first)
            print(" pending:", [(item.get("name"), item.get("prompt")) for item in rows])
            self.assertTrue(rows)
            self.assertTrue(any(item.get("name") == "shares" for item in rows))
            second = _raw_plan(
                assistant.plan("", response_style="raw", session_id="preset-name", answers=["平安银行"])
            )
            print(" skills:", [step.get("skill_name") for step in second.get("steps") or []])
            self.assertIn("qt.ai.system.fallback", [step.get("skill_name") for step in second.get("steps") or []])

    def test_empty_failure_details_keep_code_and_message(self) -> None:
        """handler 返回失败且 details 为空时，记录里补上 code 和 message。不真取数。"""

        print("\n[TestAi04CommitOpen] 失败 details")
        metadata = self.registry.get_metadata("qt.ai.data.kline")

        def handler(**kwargs: Any) -> Dict[str, Any]:
            return {
                "ok": False,
                "skill_name": metadata.name,
                "error": {
                    "code": "KLINE_FETCH_FAILED",
                    "message": "local kline was not read",
                    "details": {},
                },
            }

        result = SkillRuntime().execute(
            metadata=metadata,
            handler=handler,
            kwargs={"shares": "600519.SH"},
        )
        details = ((result.get("error") or {}).get("details") or {})
        print(" details:", details)
        self.assertEqual(details.get("code"), "KLINE_FETCH_FAILED")
        self.assertEqual(details.get("message"), "local kline was not read")

        def explode(**kwargs: Any) -> Dict[str, Any]:
            raise RuntimeError("handler exploded")

        blown = SkillRuntime().execute(
            metadata=metadata,
            handler=explode,
            kwargs={"shares": "600519.SH"},
        )
        blown_details = (blown.get("error") or {}).get("details") or {}
        print(" exception details:", blown_details)
        self.assertIn("side_effect_level", blown_details)

    def _answer_open_code(self, query: str, compose: Dict[str, Any], answer: str, sid: str) -> Dict[str, Any]:
        """组图、填槽协议和交卷分开。交卷走 answers。"""

        job = json.dumps({"job": "open"})
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=self.registry,
                provider=FakeLLMProvider(
                    replies=[
                        json.dumps({"task": query, "question": ""}, ensure_ascii=False),
                        job,
                        job,
                        json.dumps(compose, ensure_ascii=False),
                        json.dumps({"freq": "d"}, ensure_ascii=False),
                    ]
                ),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            first = _raw_plan(assistant.plan(query, response_style="raw", session_id=sid))
            rows = _pending(first)
            print(" entry:", sid, "pending:", [(item.get("name"), item.get("prompt")) for item in rows])
            self.assertEqual([item.get("name") for item in rows], ["shares"])
            return _raw_plan(assistant.plan("", response_style="raw", session_id=sid, answers=[answer]))


def _raw_plan(result: Any) -> Dict[str, Any]:
    """助手 raw 结果里的计划。"""

    if not isinstance(result, dict):
        return {}
    plan = result.get("plan") or result
    return plan if isinstance(plan, dict) else {}


def _pending(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """澄清卡上的题。"""

    blob = (plan.get("assumptions") or {}).get("clarification") or {}
    return [item for item in (blob.get("pending") or []) if isinstance(item, dict)]


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
