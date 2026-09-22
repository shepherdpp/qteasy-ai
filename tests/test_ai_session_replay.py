# coding=utf-8
# ======================================
# File: test_ai_session_replay.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-22
# Desc:
# 五份历史 Composer 句无 UI 回放金标准
# ======================================

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.human_card import format_human_cards
from qteasy_ai.memory_store import MemoryStore

from tests.fixtures.session_replay_queries import DESIGN_KEYS, FIXTURES, KLINE_HINTS, META_GET_SKILLS


def _user_texts(session: Any) -> List[str]:
    """session.messages 中的 Composer 原文。"""

    return [
        str(row.get("text") or "")
        for row in (session.messages or [])
        if str(row.get("kind") or "") == "user_text"
    ]


def _plan_skills(payload: Dict[str, Any]) -> List[str]:
    """本轮 dry-run skill 名。"""

    plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
    return [str(item.get("skill_name") or "") for item in (plan.get("steps") or []) if isinstance(item, dict)]


def _dumped_keys(session: Any) -> List[str]:
    """落盘键。"""

    return list((session.to_dict() or {}).keys())


class TestAiSessionReplay(unittest.TestCase):
    """只经 QteasyAssistant.plan/ask，不启 HTTP。"""

    def _assistant(self, temp_dir: str) -> QteasyAssistant:
        """临时 MemoryStore 上的助手。"""

        return QteasyAssistant(
            memory_store=MemoryStore(base_dir=temp_dir),
            registry=build_default_registry(),
        )

    def _replay(self, asst: QteasyAssistant, fixture_id: str, sid: str) -> List[Dict[str, Any]]:
        """按 fixture 串跑，打印每步 status/job/user_text/kinds。"""

        traces: List[Dict[str, Any]] = []
        for index, turn in enumerate(FIXTURES[fixture_id], start=1):
            query = str(turn.get("query") or "")
            mode = str(turn.get("mode") or "plan")
            if mode == "ask":
                payload = asst.ask(query, response_style="raw", session_id=sid)
            else:
                payload = asst.plan(query, response_style="raw", session_id=sid)
            session = asst.session_store.load(sid)
            kinds = [str(row.get("kind") or "") for row in (session.messages or [])]
            users = _user_texts(session)
            job = str(session.task.job or "") if session.task is not None else ""
            status = session.task_status()
            print(
                f"\n[{fixture_id} #{index}] mode={mode} status={status} job={job}"
            )
            print(" query:", query)
            print(" latest user_text:", users[-1] if users else "")
            print(" kinds:", kinds[-8:])
            print(" dumped keys:", sorted(_dumped_keys(session)))
            traces.append(
                {
                    "query": query,
                    "mode": mode,
                    "payload": payload,
                    "status": status,
                    "job": job,
                    "users": users,
                    "kinds": kinds,
                    "skills": _plan_skills(payload),
                    "session": session,
                }
            )
        return traces

    def _assert_no_design(self, session: Any) -> None:
        """落盘无设计环键。"""

        dumped = session.to_dict()
        print(" design keys present:", [key for key in DESIGN_KEYS if key in dumped])
        for key in DESIGN_KEYS:
            self.assertNotIn(key, dumped)
        self.assertFalse(hasattr(session, "live_design"))
        self.assertFalse(hasattr(session, "active_design"))

    def _assert_composer_logged(self, traces: List[Dict[str, Any]]) -> None:
        """每一句 Composer 都在 user_text。"""

        expected = [str(item["query"]) for item in traces]
        users = list(traces[-1]["users"])
        print(" expected composer:", expected)
        print(" user_text:", users)
        self.assertEqual(users, expected)

    def test_replay_mu9zei7t(self) -> None:
        """Ask 无 Task；bband 填槽；ready 后 strategy_id swma 新 Task；abandon 不进设计环。"""

        print("\n[TestAiSessionReplay] mu9zei7t")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = self._assistant(temp_dir)
            sid = "replay-mu9zei7t"
            traces = self._replay(asst, "mu9zei7t", sid)
            session = traces[-1]["session"]
            self._assert_composer_logged(traces)
            self._assert_no_design(session)
            ask_trace = traces[0]
            print(" ask task:", ask_trace["session"].task, "job:", ask_trace["job"])
            self.assertEqual(ask_trace["mode"], "ask")
            self.assertTrue(ask_trace["session"].task is None or not str(ask_trace["job"] or ""))
            bband = traces[4]
            print(" bband status:", bband["status"], "answer kinds:", bband["kinds"])
            clar = [
                row
                for row in bband["session"].messages
                if str(row.get("kind") or "") == "clarify"
            ]
            answers = [
                str((row.get("payload") or {}).get("answer") or "")
                for row in clar
                if (row.get("payload") or {}).get("answer")
            ]
            print(" clarify answers:", answers)
            self.assertTrue(any("bband" in item for item in answers) or bband["status"] in {"ready", "done", "clarifying"})
            swma = traces[5]
            print(" swma job:", swma["job"], "status:", swma["status"])
            self.assertNotEqual(swma["query"], "bband")
            self.assertIn("strategy_id swma", swma["users"])

    def test_replay_muahqq6w(self) -> None:
        """下载句是 data.refill 类新 Task，不是被策略任务吸走。"""

        print("\n[TestAiSessionReplay] muahqq6w")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = self._assistant(temp_dir)
            sid = "replay-muahqq6w"
            traces = self._replay(asst, "muahqq6w", sid)
            session = traces[-1]["session"]
            self._assert_composer_logged(traces)
            self._assert_no_design(session)
            download = traces[8]
            print(" download job:", download["job"], "skills:", download["skills"])
            self.assertIn(download["query"], download["users"])
            self.assertNotEqual(download["job"], "strategy.meta")
            self.assertFalse(any(name in META_GET_SKILLS for name in download["skills"]))

    def test_replay_mub3do17(self) -> None:
        """bband 填槽有 answer；写策略取消未完成参数任务并 mode_notice。"""

        print("\n[TestAiSessionReplay] mub3do17")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = self._assistant(temp_dir)
            sid = "replay-mub3do17"
            traces = self._replay(asst, "mub3do17", sid)
            session = traces[-1]["session"]
            self._assert_composer_logged(traces)
            self._assert_no_design(session)
            bband = traces[4]
            clar = [
                row
                for row in bband["session"].messages
                if str(row.get("kind") or "") == "clarify"
            ]
            print(" bband clarify payloads:", [row.get("payload") for row in clar])
            self.assertTrue(
                any(str((row.get("payload") or {}).get("answer") or "") == "bband" for row in clar)
            )
            write = traces[5]
            cards = write["payload"].get("human_cards") or []
            notices = [item for item in cards if item.get("kind") == "mode_notice"]
            print(" write job:", write["job"], "notices:", [item.get("text") for item in notices])
            self.assertTrue(any("Previous topic skipped" in str(item.get("text") or "") for item in notices))

    def test_replay_mub9u1go(self) -> None:
        """dma 填槽有 user_text+answer；其后两句均为新 Task。"""

        print("\n[TestAiSessionReplay] mub9u1go")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = self._assistant(temp_dir)
            sid = "replay-mub9u1go"
            traces = self._replay(asst, "mub9u1go", sid)
            session = traces[-1]["session"]
            self._assert_composer_logged(traces)
            self._assert_no_design(session)
            dma = traces[1]
            clar = [
                row
                for row in dma["session"].messages
                if str(row.get("kind") or "") == "clarify"
            ]
            print(" dma answers:", [(row.get("payload") or {}).get("answer") for row in clar])
            self.assertTrue(any(str((row.get("payload") or {}).get("answer") or "") == "dma" for row in clar))
            trix = traces[2]
            note = traces[3]
            print(" trix job:", trix["job"], "note job:", note["job"])
            self.assertIn("strategy_id trix", trix["users"])
            self.assertIn("note 列出macd的参数", note["users"])
            notices = [
                str(item.get("text") or "")
                for item in (trix["payload"].get("human_cards") or [])
                if item.get("kind") == "mode_notice"
            ]
            print(" trix notices:", notices)
            self.assertTrue(any("Previous topic skipped" in item for item in notices))

    def test_replay_mube2wfi_kline_not_swallowed(self) -> None:
        """每个 K 线句都是 user_text；Job 为读数/K线而非 strategy.meta.get。"""

        print("\n[TestAiSessionReplay] mube2wfi")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = self._assistant(temp_dir)
            sid = "replay-mube2wfi"
            traces = self._replay(asst, "mube2wfi", sid)
            session = traces[-1]["session"]
            self._assert_composer_logged(traces)
            self._assert_no_design(session)
            bband = traces[2]
            clar = [
                row
                for row in bband["session"].messages
                if str(row.get("kind") or "") == "clarify"
            ]
            print(" bband kept:", [(row.get("payload") or {}).get("answer") for row in clar])
            self.assertTrue(any(str((row.get("payload") or {}).get("answer") or "") == "bband" for row in clar))
            kline_turns = [item for item in traces if any(hint in item["query"] for hint in KLINE_HINTS)]
            print(" kline count:", len(kline_turns))
            self.assertGreaterEqual(len(kline_turns), 3)
            for item in kline_turns:
                print(" kline job/skills:", item["query"], item["job"], item["skills"])
                self.assertIn(item["query"], item["users"])
                self.assertFalse(any(name in META_GET_SKILLS for name in item["skills"]))
                self.assertNotEqual(item["job"], "strategy.meta")

    def test_cli_human_matches_user_text_count(self) -> None:
        """同一 session 文件，format_human_cards 与 messages user_text 条数一致。"""

        print("\n[TestAiSessionReplay] human vs user_text")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = self._assistant(temp_dir)
            sid = "replay-human"
            asst.plan("请列出所有内置交易策略", response_style="raw", session_id=sid)
            asst.plan("请列出交易策略的参数和介绍", response_style="raw", session_id=sid)
            session = asst.session_store.load(sid)
            users = _user_texts(session)
            human = format_human_cards(list(session.messages), payload={"mode": "plan"})
            print(" users:", users)
            print(" human:", human)
            self.assertEqual(len(users), 2)
            for text in users:
                self.assertIn(text, human)
            path = Path(asst.session_store.path_for(sid))
            on_disk = json.loads(path.read_text(encoding="utf-8"))
            disk_users = [
                str(row.get("text") or "")
                for row in (on_disk.get("messages") or [])
                if str(row.get("kind") or "") == "user_text"
            ]
            print(" disk users:", disk_users)
            self.assertEqual(disk_users, users)
            self.assertNotIn("qteasy_ai.workbench", Path(__import__("qteasy_ai.session", fromlist=["x"]).__file__).read_text(encoding="utf-8"))

    def test_session_modules_do_not_import_workbench(self) -> None:
        """session.py / session_gate.py 不得 import workbench。"""

        print("\n[TestAiSessionReplay] no workbench import")
        root = Path(__file__).resolve().parents[1] / "qteasy_ai"
        for name in ("session.py", "session_gate.py"):
            text = (root / name).read_text(encoding="utf-8")
            print(" file:", name, "has workbench:", "qteasy_ai.workbench" in text or "from .workbench" in text)
            self.assertNotIn("qteasy_ai.workbench", text)
            self.assertNotIn("from .workbench", text)


if __name__ == "__main__":
    unittest.main()
