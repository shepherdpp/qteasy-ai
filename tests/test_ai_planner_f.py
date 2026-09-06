# coding=utf-8
# ======================================
# File: test_ai_planner_f.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-05
# Desc:
# Unittest for Phase F session plan assembly
# ======================================

import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.session import SessionStore

GOLDEN_D1 = "帮我写一个基于 20/60 日均线金叉死叉的择时策略，并用 2015–2020 年沪深300做回测"


class TestAiPlannerF(unittest.TestCase):
    """F.3 澄清四步 + F.4 profile / env_facts。"""

    def _assistant(self, temp_dir: str, **profile: object) -> QteasyAssistant:
        """临时目录里的助手。"""

        store = MemoryStore(base_dir=temp_dir)
        if profile:
            store.save_profile(dict(profile))
        return QteasyAssistant(memory_store=store, registry=build_default_registry())

    def test_refill_clarify_then_fill_same_job(self) -> None:
        """无日期下载先澄清，跟进日期后仍是同一 refill Job。"""

        print("\n[TestAiPlannerF] refill clarify then fill")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = self._assistant(temp_dir)
            first = assistant.plan("帮我下载日线", response_style="raw", session_id="s-refill")
            plan = first["plan"]
            clarification = first.get("clarification") or (plan.get("assumptions") or {}).get("clarification")
            print(" first skills:", [s["skill_name"] for s in plan["steps"]])
            print(" first trace:", plan.get("planner_trace"))
            print(" clarification:", clarification)
            print(" session:", first.get("session"))
            self.assertEqual(plan["steps"][0]["skill_name"], "qt.ai.system.fallback")
            self.assertEqual(plan["steps"][0]["inputs"].get("fallback_action"), "clarify_required")
            self.assertIsInstance(clarification, dict)
            self.assertIn("restatement", clarification)
            self.assertTrue(clarification.get("pending"))
            self.assertTrue(clarification.get("confirm_prompt"))
            self.assertEqual(first["session"]["clarify_round"], 1)

            second = assistant.plan(
                "20240101 到 20241231",
                response_style="raw",
                session_id="s-refill",
            )
            names = [s["skill_name"] for s in second["plan"]["steps"]]
            refill = [s for s in second["plan"]["steps"] if s["skill_name"] == "qt.ai.data.refill_basic_equity_and_index"]
            print(" second skills:", names)
            print(" second trace:", second["plan"].get("planner_trace"))
            print(" refill inputs:", refill[0]["inputs"] if refill else None)
            self.assertEqual(second["plan"]["planner_trace"].get("intent_job"), "data.refill")
            self.assertEqual(second["plan"]["planner_trace"].get("source"), "session")
            self.assertTrue(refill)
            self.assertEqual(refill[0]["inputs"].get("start"), "20240101")
            self.assertEqual(refill[0]["inputs"].get("end"), "20241231")

            confirm = assistant.plan("对，理解正确", response_style="raw", session_id="s-refill")
            cnames = [s["skill_name"] for s in confirm["plan"]["steps"]]
            print(" confirm skills:", cnames)
            print(" confirm trace:", confirm["plan"].get("planner_trace"))
            self.assertIn("qt.ai.data.refill_basic_equity_and_index", cnames)
            self.assertEqual(confirm["plan"]["planner_trace"].get("intent_job"), "data.refill")
            self.assertEqual(confirm["plan"]["planner_trace"].get("source"), "session")
            store = SessionStore(assistant.memory_store)
            state = store.load("s-refill")
            print(" confirmed slots:", {k: v.to_dict() for k, v in state.slots.items()})
            self.assertTrue(state.slots["start"].confirmed)
            self.assertTrue(state.slots["end"].confirmed)

    def test_clarify_round_caps_at_three(self) -> None:
        """第 4 次仍缺槽 → 整单 clarify，round 停在 3。"""

        print("\n[TestAiPlannerF] clarify round cap")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = self._assistant(temp_dir)
            sid = "s-cap"
            assistant.plan("帮我下载日线", response_style="raw", session_id=sid)
            for extra in ("然后呢", "继续", "还缺什么"):
                assistant.plan(extra, response_style="raw", session_id=sid)
            fourth = assistant.plan("再想想", response_style="raw", session_id=sid)
            print(" fourth session:", fourth.get("session"))
            print(" fourth skill:", fourth["plan"]["steps"][0]["skill_name"])
            print(" fourth action:", fourth["plan"]["steps"][0]["inputs"].get("fallback_action"))
            self.assertEqual(fourth["session"]["clarify_round"], 3)
            self.assertEqual(fourth["plan"]["steps"][0]["skill_name"], "qt.ai.system.fallback")
            self.assertEqual(fourth["plan"]["steps"][0]["inputs"].get("fallback_action"), "clarify_required")

    def test_builder_followup_changes_slow_with_session(self) -> None:
        """有 session 时改慢线修订上一份 Spec，不是全新单句。"""

        print("\n[TestAiPlannerF] builder change slow")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = self._assistant(temp_dir)
            first = assistant.plan(GOLDEN_D1, response_style="raw", session_id="s-d")
            print(" first job:", first["plan"]["planner_trace"].get("intent_job"))
            print(" first skills:", [s["skill_name"] for s in first["plan"]["steps"]])
            self.assertEqual(first["plan"]["planner_trace"].get("intent_job"), "strategy.builder")
            second = assistant.plan("把慢线改成 60", response_style="raw", session_id="s-d")
            print(" second job:", second["plan"]["planner_trace"].get("intent_job"))
            print(" second source:", second["plan"]["planner_trace"].get("source"))
            print(" second skills:", [s["skill_name"] for s in second["plan"]["steps"]])
            self.assertEqual(second["plan"]["planner_trace"].get("intent_job"), "strategy.builder")
            self.assertEqual(second["plan"]["planner_trace"].get("source"), "session")
            store = SessionStore(assistant.memory_store)
            state = store.load("s-d")
            print(" slow slot:", state.slots.get("slow").to_dict() if "slow" in state.slots else None)
            self.assertEqual(state.slots["slow"].value, 60)
            self.assertEqual(state.slots["slow"].source, "user")
            self.assertTrue(state.slots["slow"].confirmed)
            spec = [s for s in second["plan"]["steps"] if s["skill_name"] == "qt.ai.strategy.spec_from_nl"]
            self.assertTrue(spec)
            self.assertEqual(spec[0]["inputs"].get("slow"), 60)

    def test_no_session_followup_stays_single_turn(self) -> None:
        """无 session_id 保持今日单句（D G7）。"""

        print("\n[TestAiPlannerF] no session_id single turn")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = self._assistant(temp_dir)
            assistant.plan(GOLDEN_D1, response_style="raw")
            follow = assistant.plan("把慢线改成 60", response_style="raw")
            names = [s["skill_name"] for s in follow["plan"]["steps"]]
            print(" follow skills:", names)
            print(" follow trace:", follow["plan"].get("planner_trace"))
            self.assertEqual(names[0], "qt.ai.system.fallback")
            self.assertNotEqual(follow["plan"]["planner_trace"].get("source"), "session")

    def test_profile_optional_shares_default(self) -> None:
        """选填 shares 来自 profile.defaults，source=default 未确认。"""

        print("\n[TestAiPlannerF] profile optional shares")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = self._assistant(
                temp_dir,
                defaults={"shares": "000300.SH"},
            )
            pretty = assistant.plan(
                "用 macd 做回测，2018 到 2023",
                response_style="user_friendly",
                session_id="s-def",
            )
            raw = pretty.raw
            plan = raw["plan"]
            bt = [s for s in plan["steps"] if s["skill_name"] == "qt.ai.backtest.run_builtin"]
            print(" skills:", [s["skill_name"] for s in plan["steps"]])
            print(" bt inputs:", bt[0]["inputs"] if bt else None)
            print(" assumptions:", plan.get("assumptions"))
            print(" narrative:", pretty.narrative)
            self.assertTrue(bt)
            self.assertEqual(bt[0]["inputs"].get("asset_pool"), "000300.SH")
            self.assertEqual((plan.get("assumptions") or {}).get("slot_defaults", {}).get("shares"), "profile")
            self.assertIn("profile", pretty.narrative.lower())
            store = SessionStore(assistant.memory_store)
            state = store.load("s-def")
            print(" shares slot:", state.slots["shares"].to_dict())
            self.assertEqual(state.slots["shares"].value, "000300.SH")
            self.assertEqual(state.slots["shares"].source, "default")
            self.assertFalse(state.slots["shares"].confirmed)

    def test_no_defaults_does_not_invent_shares(self) -> None:
        """无 defaults 且句中无标的 → 不发明 shares。"""

        print("\n[TestAiPlannerF] no invented shares")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = self._assistant(temp_dir)
            payload = assistant.plan(
                "用 macd 做回测，2018 到 2023",
                response_style="raw",
                session_id="s-none",
            )
            bt = [s for s in payload["plan"]["steps"] if s["skill_name"] == "qt.ai.backtest.run_builtin"]
            print(" bt inputs:", bt[0]["inputs"] if bt else None)
            self.assertTrue(bt)
            self.assertFalse(bt[0]["inputs"].get("asset_pool"))
            store = SessionStore(assistant.memory_store)
            state = store.load("s-none")
            print(" slots:", {k: v.to_dict() for k, v in state.slots.items()})
            self.assertNotIn("shares", state.slots)

    def test_env_facts_gate_not_bypassed_by_session(self) -> None:
        """缺 token 仍前置 check_tushare，session 不绕过。"""

        print("\n[TestAiPlannerF] env_facts gate")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            store.save_env_facts({"tushare": {"token_present": False}})
            assistant = QteasyAssistant(memory_store=store, registry=build_default_registry())
            payload = assistant.plan(
                "download daily data from 20180101 to 20231231",
                response_style="raw",
                session_id="s-env",
            )
            names = [s["skill_name"] for s in payload["plan"]["steps"]]
            print(" skills:", names)
            self.assertEqual(names[0], "qt.ai.env.check_tushare")
            self.assertIn("qt.ai.data.refill_basic_equity_and_index", names)


if __name__ == "__main__":
    unittest.main()
