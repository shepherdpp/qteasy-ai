# coding=utf-8
# ======================================
# File: test_ai_gold_paths.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-11
# Desc:
# 金路径注册表。BJ-LEARN-01 是 A7 的一条回测追问样本。
# ======================================

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Mapping

from qteasy_ai.app import QteasyAssistant
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.provider import FakeLLMProvider

_CORPUS = Path(__file__).resolve().parent / "ai_corpus" / "gold_paths.json"
_KB_DIR = Path(__file__).resolve().parents[1] / "qteasy_ai" / "kb"
_BACKTEST_NARRATIVE = "A built-in backtest Job needs a strategy_id"
_OPTIMIZE_NARRATIVE = "Plan `optimize DMA parameters` routes to `qt.ai.optimize.run_builtin`"
_DOWNLOAD_WITHOUT_DATES = "download A-share daily data to local datasource"


def _load_paths() -> List[Dict[str, Any]]:
    """读取金路径注册表。"""

    payload = json.loads(_CORPUS.read_text(encoding="utf-8"))
    paths = payload.get("paths")
    if not isinstance(paths, list):
        raise AssertionError("gold_paths paths must be a list")
    return paths


def _card_narrative(card_id: str) -> str:
    """卡片文件里的 narrative，当作内容金标准。"""

    raw = json.loads((_KB_DIR / f"{card_id}.json").read_text(encoding="utf-8"))
    return str(raw.get("narrative") or "")


def _menu_line_ids(prompt: str) -> List[str]:
    """点卡提示里以「- id:」开头的菜单 id。"""

    found: List[str] = []
    for line in str(prompt or "").splitlines():
        if not line.startswith("- ") or ":" not in line:
            continue
        found.append(line[2:].split(":", 1)[0].strip())
    return found


def _protocol_replies(step: Mapping[str, Any]) -> List[str]:
    """一步 Ask 的替身回复：定主题、点卡、作家。"""

    kind = str(step.get("kind") or "")
    if kind == "prior":
        first = json.dumps({"prior": step.get("prior")}, ensure_ascii=False)
    else:
        first = json.dumps({"topics": step.get("topics")}, ensure_ascii=False)
    return [
        first,
        json.dumps({"ids": step.get("ids")}, ensure_ascii=False),
        str(step.get("answer") or ""),
    ]


class TestAiGoldPaths(unittest.TestCase):
    """表驱动金路径。只跑 enabled 的路径。"""

    def test_registry_enables_only_bj_learn_01(self) -> None:
        """02/03 只占位，注册表不把它们标成可跑。"""

        print("\n[TestAiGoldPaths] 注册表只启用 BJ-LEARN-01")
        paths = _load_paths()
        ids = [str(item.get("id") or "") for item in paths]
        enabled = [str(item.get("id") or "") for item in paths if item.get("enabled") is True]
        disabled = [item for item in paths if item.get("enabled") is not True]
        print(" ids:", ids)
        print(" enabled:", enabled)
        print(" disabled:", [item.get("id") for item in disabled])
        self.assertEqual(ids, ["BJ-LEARN-01", "BJ-LEARN-02", "BJ-LEARN-03"])
        self.assertEqual(enabled, ["BJ-LEARN-01"])
        self.assertEqual([item.get("id") for item in disabled], ["BJ-LEARN-02", "BJ-LEARN-03"])
        for item in disabled:
            self.assertFalse(item.get("steps"))

    def test_bj_learn_01_followup_stays_on_backtest(self) -> None:
        """同一 session：回测、两条再解释、对比，然后已有回测 Plan 金句。"""

        print("\n[TestAiGoldPaths] BJ-LEARN-01 回测追问")
        path = next(item for item in _load_paths() if item.get("id") == "BJ-LEARN-01")
        steps = list(path.get("steps") or [])
        answers = {str(step.get("id")): str(step.get("answer") or "") for step in steps}
        backtest_narrative = _card_narrative("backtest_intro")
        optimize_narrative = _card_narrative("optimize_intro")
        print(" backtest narrative has strategy_id:", _BACKTEST_NARRATIVE in backtest_narrative)
        print(" optimize narrative has run_builtin:", _OPTIMIZE_NARRATIVE in optimize_narrative)
        self.assertIn(_BACKTEST_NARRATIVE, backtest_narrative)
        self.assertIn(_OPTIMIZE_NARRATIVE, optimize_narrative)

        replies: List[str] = []
        for step in steps:
            if str(step.get("channel") or "") == "ask":
                replies.extend(_protocol_replies(step))
        fake = FakeLLMProvider(replies=replies)
        session_id = str(path.get("session_id") or "")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                memory_store=MemoryStore(base_dir=temp_dir),
                provider=fake,
            )
            cursor = 0
            for step in steps:
                channel = str(step.get("channel") or "")
                query = str(step.get("query") or "")
                step_id = str(step.get("id") or "")
                if channel == "ask":
                    before = len(fake.prompts)
                    payload = assistant.ask(query, response_style="raw", session_id=session_id)
                    used = fake.prompts[before:]
                    print(" step:", step_id, "query:", query)
                    print(" sources:", payload.get("sources"))
                    print(" prompts:", len(used))
                    self._assert_ask_step(payload, step, used, answers)
                    state = assistant.session_store.load(session_id)
                    print(" task is None:", state.task is None)
                    self.assertIsNone(state.task)
                    cursor = len(fake.prompts)
                    continue
                self.assertEqual(channel, "plan")
                self.assertEqual(cursor, len(fake.prompts))
                assistant.apply_provider(None)
                planned = assistant.plan(query, response_style="raw", session_id=session_id)
                self._assert_plan_step(planned, step)
                print(" prompts after plan:", len(fake.prompts))
                self.assertEqual(len(fake.prompts), cursor)

    def test_download_without_dates_still_clarifies(self) -> None:
        """无日期的 download 仍要求补日期，不改成一笔默认下载。"""

        print("\n[TestAiGoldPaths] 无日期 download 仍澄清")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(memory_store=MemoryStore(base_dir=temp_dir))
            payload = assistant.plan(_DOWNLOAD_WITHOUT_DATES, response_style="raw")
        plan = payload.get("plan") or {}
        steps = list(plan.get("steps") or [])
        execution = payload.get("execution") or {}
        inputs = dict((steps[0].get("inputs") or {}) if steps else {})
        print(" skill:", steps[0].get("skill_name") if steps else None)
        print(" fallback_action:", inputs.get("fallback_action"))
        print(" missing_info:", inputs.get("missing_info"))
        print(" execution:", execution.get("status"), execution.get("steps"))
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].get("skill_name"), "qt.ai.system.fallback")
        self.assertEqual(inputs.get("fallback_action"), "clarify_required")
        self.assertEqual(inputs.get("missing_info"), "date_range")
        self.assertEqual(execution.get("status"), "dry_run")
        self.assertEqual(execution.get("steps"), [])

    def _assert_ask_step(
            self,
            payload: Mapping[str, Any],
            step: Mapping[str, Any],
            prompts: List[str],
            answers: Mapping[str, str],
    ) -> None:
        """Ask 步：sources、菜单、节选位置，以及无 plan_id。"""

        sources = list(payload.get("sources") or [])
        expected = list(step.get("expect_sources") or [])
        print(" expected sources:", expected)
        self.assertEqual(payload.get("mode"), "ask")
        self.assertNotIn("execution", payload)
        self.assertNotIn("plan_id", payload)
        self.assertNotIn("plan_id", str(payload.get("answer") or ""))
        self.assertEqual(sources, expected)
        self.assertEqual(sources[0], "backtest_intro")
        self.assertEqual(len(prompts), 3)
        topic_prompt, card_prompt, writer_prompt = prompts
        excerpt_from = str(step.get("excerpt_from") or "")
        if excerpt_from:
            excerpt = answers[excerpt_from]
            user_query = self._query_of(excerpt_from)
            print(" topic has excerpt:", excerpt in topic_prompt)
            print(" card has excerpt:", excerpt in card_prompt)
            print(" writer has excerpt:", excerpt in writer_prompt)
            print(" menu ids:", _menu_line_ids(card_prompt))
            self.assertIn("Ask history index:", topic_prompt)
            self.assertNotIn(excerpt, topic_prompt)
            self.assertNotIn(user_query, topic_prompt)
            self.assertIn(f"User: {user_query}", card_prompt)
            self.assertIn(f"Answer shown: {excerpt}", card_prompt)
            self.assertNotIn(excerpt, writer_prompt)
            self.assertEqual(set(_menu_line_ids(card_prompt)), set(step.get("menu_ids") or []))
            self.assertNotIn("data_three_entries", card_prompt)
            self.assertNotIn("data-downloading", card_prompt)
            self.assertNotIn("env_ready", card_prompt)
            self.assertIn("optimize_intro", card_prompt)
            self.assertIn(_BACKTEST_NARRATIVE, writer_prompt)
            return
        print(" card has named turns:", "Named turns:" in card_prompt)
        self.assertNotIn("Named turns:", card_prompt)
        self.assertNotIn("L1-ANSWER-MARKER", card_prompt)
        self.assertNotIn("L1-ANSWER-MARKER", writer_prompt)
        self.assertIn(_BACKTEST_NARRATIVE, writer_prompt)
        if step.get("id") == "L3":
            self.assertIn(_BACKTEST_NARRATIVE, writer_prompt)
            self.assertIn(_OPTIMIZE_NARRATIVE, writer_prompt)
            self.assertNotIn("L2-ANSWER-MARKER", writer_prompt)

    def _assert_plan_step(self, payload: Mapping[str, Any], step: Mapping[str, Any]) -> None:
        """Plan 步：已有回测金句的步骤与副作用可见，未确认不执行。"""

        plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
        execution = payload.get("execution") if isinstance(payload.get("execution"), dict) else {}
        plan_steps = list(plan.get("steps") or [])
        names = [str(item.get("skill_name") or "") for item in plan_steps]
        trace = plan.get("planner_trace") if isinstance(plan.get("planner_trace"), dict) else {}
        first = plan_steps[0] if plan_steps else {}
        inputs = first.get("inputs") if isinstance(first.get("inputs"), dict) else {}
        effects = first.get("side_effects") if isinstance(first.get("side_effects"), dict) else {}
        cards = list(payload.get("human_cards") or [])
        ready = next((item for item in cards if item.get("kind") == "plan_ready"), {})
        ready_text = str(ready.get("text") or "")
        print(" job:", trace.get("intent_job"))
        print(" skills:", names)
        print(" strategy_id:", inputs.get("strategy_id"))
        print(" asset_pool:", inputs.get("asset_pool"))
        print(" side_effects:", effects)
        print(" execution:", execution.get("status"), execution.get("steps"))
        print(" plan_ready:", ready_text)
        self.assertEqual(trace.get("intent_job"), step.get("expect_job"))
        self.assertEqual(names, list(step.get("expect_skills") or []))
        self.assertEqual(str(inputs.get("strategy_id") or "").lower(), step.get("expect_strategy_id"))
        self.assertEqual(inputs.get("asset_pool"), step.get("expect_asset_pool"))
        self.assertTrue(effects.get("filesystem_write"))
        self.assertTrue(effects.get("heavy_compute"))
        self.assertEqual(execution.get("status"), "dry_run")
        self.assertEqual(execution.get("steps"), [])
        self.assertIn("qt.ai.backtest.run_builtin", str(payload.get("plan_md") or ""))
        self.assertIn("Plan ready.", ready_text)
        self.assertIn("needs confirm", ready_text)

    def _query_of(self, step_id: str) -> str:
        """注册表里某一步的用户句。"""

        path = next(item for item in _load_paths() if item.get("id") == "BJ-LEARN-01")
        for step in path.get("steps") or []:
            if step.get("id") == step_id:
                return str(step.get("query") or "")
        raise AssertionError(f"missing step {step_id}")


if __name__ == "__main__":
    unittest.main()
