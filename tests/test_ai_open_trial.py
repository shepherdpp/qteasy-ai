# coding=utf-8
# ======================================
# File: test_ai_open_trial.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-10
# Desc:
# Unittest for G.7 nested closed trial and retreat
# ======================================

import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.cli import build_parser
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.workbench.mapper import map_assistant_payload, step_needs_confirm


class TestAiOpenTrial(unittest.TestCase):
    """一层闭合试错、队列、两种回退、禁止 open 套 open。"""

    def _assistant(self, temp_dir: str) -> QteasyAssistant:
        """临时 MemoryStore 上的助手。"""

        return QteasyAssistant(
            memory_store=MemoryStore(base_dir=temp_dir),
            registry=build_default_registry(),
        )

    def test_propose_trial_matches_closed_ic_confirm(self) -> None:
        """建议试错 → 闭合 factor_ic 步，needs_confirm 与单独跑相同。"""

        print("\n[TestAiOpenTrial] propose trial matches closed IC")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = self._assistant(temp_dir)
            closed = asst.plan("factor IC summary for selection pool", response_style="raw")
            closed_steps = (closed.get("plan") or {}).get("steps") or []
            closed_names = [item.get("skill_name") for item in closed_steps]
            closed_need = [
                step_needs_confirm(item.get("skill_name") or "", item.get("side_effects"))
                for item in closed_steps
            ]
            print(" closed skills:", closed_names)
            print(" closed needs_confirm:", closed_need)
            sid = "g7-trial"
            asst.plan(
                "explore a useful momentum factor for hs300",
                response_style="raw",
                session_id=sid,
            )
            trial = asst.plan("try IC on this factor", response_style="raw", session_id=sid)
            steps = (trial.get("plan") or {}).get("steps") or []
            names = [item.get("skill_name") for item in steps]
            trial_need = [
                step_needs_confirm(item.get("skill_name") or "", item.get("side_effects"))
                for item in steps
            ]
            dto = map_assistant_payload(trial, query="try IC on this factor")
            print(" trial skills:", names)
            print(" trial needs_confirm:", trial_need)
            print(" confirmable:", None if dto.plan_card is None else dto.plan_card.confirmable)
            self.assertEqual(names, ["qt.ai.research.factor_ic_summary"])
            self.assertEqual(trial_need, closed_need)
            self.assertIsNotNone(dto.plan_card)
            self.assertTrue(dto.plan_card.confirmable)
            state = asst.session_store.load(sid)
            print(" current_trial_plan_id:", state.current_trial_plan_id)
            self.assertTrue(state.current_trial_plan_id)
            trial_inputs = steps[0].get("inputs") or {}
            print(" trial inputs:", trial_inputs)
            self.assertEqual(trial_inputs.get("factor_htype"), "momentum")

    def test_second_trial_queues_while_first_active(self) -> None:
        """第一张试错仍 active 时，第二张进队列。"""

        print("\n[TestAiOpenTrial] second trial queued")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = self._assistant(temp_dir)
            sid = "g7-queue"
            asst.plan(
                "explore a useful momentum factor for hs300",
                response_style="raw",
                session_id=sid,
            )
            first = asst.plan("try IC on this factor", response_style="raw", session_id=sid)
            first_id = ((first.get("plan") or {}).get("plan_id") or "")
            second = asst.plan("try IC again", response_style="raw", session_id=sid)
            state = asst.session_store.load(sid)
            statuses = [item.get("status") for item in state.trial_queue]
            print(" first_id:", first_id)
            print(" current:", state.current_trial_plan_id)
            print(" queue:", state.trial_queue)
            print(" second skills:", [s.get("skill_name") for s in ((second.get("plan") or {}).get("steps") or [])])
            self.assertEqual(state.current_trial_plan_id, first_id)
            self.assertIn("queued", statuses)
            self.assertEqual(statuses.count("active"), 1)
            self.assertNotIn(
                "qt.ai.research.factor_ic_summary",
                [s.get("skill_name") for s in ((second.get("plan") or {}).get("steps") or [])],
            )

    def test_abandon_trial_keeps_draft(self) -> None:
        """abandon_trial 清 current_trial_plan_id，草稿仍在。"""

        print("\n[TestAiOpenTrial] abandon trial keeps draft")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = self._assistant(temp_dir)
            sid = "g7-ab-trial"
            asst.plan(
                "explore a useful momentum factor for hs300",
                response_style="raw",
                session_id=sid,
            )
            asst.plan("try IC on this factor", response_style="raw", session_id=sid)
            asst.abandon_trial(sid, response_style="raw")
            state = asst.session_store.load(sid)
            spec = (state.active_design or {}).get("spec_draft") or {}
            print(" trial id after:", state.current_trial_plan_id)
            print(" spec name:", spec.get("name"))
            self.assertEqual(state.current_trial_plan_id, "")
            self.assertEqual(spec.get("name"), "momentum")
            self.assertIsNotNone(state.active_design)

    def test_abandon_open_keeps_session_id(self) -> None:
        """abandon_open 清设计态，session_id 仍在。"""

        print("\n[TestAiOpenTrial] abandon open keeps session")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = self._assistant(temp_dir)
            sid = "g7-ab-open"
            asst.plan(
                "explore a useful momentum factor for hs300",
                response_style="raw",
                session_id=sid,
            )
            asst.abandon_open(sid, response_style="raw")
            state = asst.session_store.load(sid)
            print(" session_id:", state.session_id)
            print(" active_design:", state.active_design)
            self.assertEqual(state.session_id, sid)
            self.assertIsNone(state.active_design)
            dumped = state.to_dict()
            self.assertNotIn("active_design", dumped)
            payload = asst.abandon_open(sid, response_style="raw")
            dto = map_assistant_payload(payload, query="abandon open")
            kinds = [item.kind for item in dto.messages]
            texts = [item.text for item in dto.messages]
            print(" abandon-open kinds:", kinds)
            print(" abandon-open texts:", texts)
            self.assertIn("ask_text", kinds)
            self.assertTrue(any("abandoned" in str(text).lower() for text in texts))
            self.assertTrue(dto.plan_card is None or not dto.plan_card.confirmable)

    def test_lock_after_abandon_is_idle_not_llm_fallback(self) -> None:
        """放弃开放 Job 后再 lock，英文说明而非 llm_uncertain 菜谱。"""

        print("\n[TestAiOpenTrial] lock after abandon idle")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = self._assistant(temp_dir)
            sid = "g7-lock-idle"
            asst.plan(
                "explore a useful momentum factor for hs300",
                response_style="raw",
                session_id=sid,
            )
            asst.abandon_open(sid, response_style="raw")
            locked = asst.plan("lock this spec", response_style="raw", session_id=sid)
            steps = (locked.get("plan") or {}).get("steps") or []
            names = [item.get("skill_name") for item in steps]
            assumptions = (locked.get("plan") or {}).get("assumptions") or {}
            print(" skills:", names)
            print(" open_idle:", assumptions.get("open_idle"), assumptions.get("open_idle_reason"))
            self.assertTrue(assumptions.get("open_idle"))
            self.assertEqual(assumptions.get("open_idle_reason"), "lock_spec")
            self.assertNotIn("qt.ai.system.fallback", names)

    def test_cli_flags_require_session_id(self) -> None:
        """CLI 暴露 --abandon-trial / --abandon-open。"""

        print("\n[TestAiOpenTrial] cli flags")
        parser = build_parser()
        trial = parser.parse_args(["plan", "--abandon-trial", "--session-id", "s1"])
        opened = parser.parse_args(["plan", "--abandon-open", "--session-id", "s1"])
        print(" trial:", trial.abandon_trial, trial.session_id)
        print(" open:", opened.abandon_open, opened.session_id)
        self.assertTrue(trial.abandon_trial)
        self.assertTrue(opened.abandon_open)
        self.assertEqual(trial.session_id, "s1")

    def test_nested_open_is_rejected(self) -> None:
        """再进一个 workflow:open → clarify，不套栈。"""

        print("\n[TestAiOpenTrial] nested open rejected")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = self._assistant(temp_dir)
            sid = "g7-nest"
            asst.plan(
                "explore a useful momentum factor for hs300",
                response_style="raw",
                session_id=sid,
            )
            nested = asst.plan(
                "还没想好规则，帮我设计一个策略",
                response_style="raw",
                session_id=sid,
            )
            steps = (nested.get("plan") or {}).get("steps") or []
            names = [item.get("skill_name") for item in steps]
            reason = ""
            if steps:
                reason = str(((steps[0].get("inputs") or {}).get("reason")) or "")
            clar = nested.get("clarification") or {}
            print(" skills:", names)
            print(" reason:", reason)
            print(" clarification:", clar)
            self.assertIn("qt.ai.system.fallback", names)
            blob = str(reason) + str(clar)
            self.assertTrue("open" in blob.lower() or "abandon" in blob.lower())
            state = asst.session_store.load(sid)
            print(" still exploring:", (state.active_design or {}).get("job"))
            self.assertEqual((state.active_design or {}).get("job"), "research.factor_explore")


if __name__ == "__main__":
    unittest.main()
