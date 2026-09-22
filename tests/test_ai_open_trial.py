# coding=utf-8
# ======================================
# File: test_ai_open_trial.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-10
# Desc:
# Unittest：G.7 Session 设计环已拆除
# ======================================

import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.cli import build_parser
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.workbench.mapper import map_assistant_payload


class TestAiOpenTrial(unittest.TestCase):
    """设计环字段与操作面已拆除。"""

    def _assistant(self, temp_dir: str) -> QteasyAssistant:
        """临时 MemoryStore 上的助手。"""

        return QteasyAssistant(
            memory_store=MemoryStore(base_dir=temp_dir),
            registry=build_default_registry(),
        )

    def test_explore_does_not_persist_design_loop(self) -> None:
        """探索句走闭合 recipe 或 clarify，落盘无 active_design。"""

        print("\n[TestAiOpenTrial] explore no design persist")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = self._assistant(temp_dir)
            sid = "g7-trial"
            payload = asst.plan(
                "explore a useful momentum factor for hs300",
                response_style="raw",
                session_id=sid,
            )
            state = asst.session_store.load(sid)
            dumped = state.to_dict()
            kinds = [str(item.get("kind") or "") for item in (payload.get("human_cards") or [])]
            print(" keys:", sorted(dumped.keys()))
            print(" kinds:", kinds)
            print(" has live_design:", hasattr(state, "live_design"))
            print(" job:", state.task.job if state.task else None)
            self.assertNotIn("active_design", dumped)
            self.assertNotIn("trial_queue", dumped)
            self.assertNotIn("current_trial_plan_id", dumped)
            self.assertFalse(hasattr(state, "live_design"))
            self.assertNotIn("design_card", kinds)

    def test_abandon_trial_is_retired(self) -> None:
        """助手不再暴露 abandon_trial；自然语言走 Composer 新 Task。"""

        print("\n[TestAiOpenTrial] abandon trial retired")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = self._assistant(temp_dir)
            sid = "g7-ab-trial"
            asst.plan("list built-in strategies", response_style="raw", session_id=sid)
            print(" has abandon_trial:", hasattr(asst, "abandon_trial"))
            self.assertFalse(hasattr(asst, "abandon_trial"))
            payload = asst.plan("abandon trial", response_style="raw", session_id=sid)
            state = asst.session_store.load(sid)
            kinds = [str(item.get("kind") or "") for item in (payload.get("human_cards") or [])]
            dumped = state.to_dict()
            print(" kinds:", kinds)
            print(" dumped keys:", sorted(dumped.keys()))
            self.assertNotIn("active_design", dumped)
            self.assertNotIn("design_card", kinds)

    def test_abandon_open_keeps_session_id(self) -> None:
        """助手不再暴露 abandon_open；session_id 仍在。"""

        print("\n[TestAiOpenTrial] abandon open keeps session")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = self._assistant(temp_dir)
            sid = "g7-ab-open"
            asst.plan("list built-in strategies", response_style="raw", session_id=sid)
            print(" has abandon_open:", hasattr(asst, "abandon_open"))
            self.assertFalse(hasattr(asst, "abandon_open"))
            payload = asst.plan("abandon open", response_style="raw", session_id=sid)
            state = asst.session_store.load(sid)
            dto = map_assistant_payload(payload, query="abandon open")
            kinds = [item.kind for item in dto.messages]
            dumped = state.to_dict()
            print(" session_id:", state.session_id)
            print(" kinds:", kinds)
            print(" dumped keys:", sorted(dumped.keys()))
            self.assertEqual(state.session_id, sid)
            self.assertNotIn("active_design", dumped)

    def test_cli_flags_removed(self) -> None:
        """CLI 不再解析 --abandon-*。"""

        print("\n[TestAiOpenTrial] cli flags removed")
        parser = build_parser()
        help_text = parser.format_help()
        print(" help has abandon-trial:", "--abandon-trial" in help_text)
        print(" help has abandon-open:", "--abandon-open" in help_text)
        print(" help has confirm-kb-write:", "--confirm-kb-write" in help_text)
        self.assertNotIn("--abandon-trial", help_text)
        self.assertNotIn("--abandon-open", help_text)
        self.assertNotIn("--confirm-kb-write", help_text)


if __name__ == "__main__":
    unittest.main()
