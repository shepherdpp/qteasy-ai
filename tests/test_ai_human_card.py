# coding=utf-8
# ======================================
# File: test_ai_human_card.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-11
# Desc:
# Unittest for G.8 human-card kernel / Plan Artifact
# ======================================

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.human_card import (
    HUMAN_CARD_KINDS,
    format_human_cards,
    infer_effective_kind,
    project_human_cards,
    usage_notice_card,
)
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.session import ConversationState, SessionStore
from qteasy_ai.workbench.human import format_human_from_payload
from qteasy_ai.workbench.mapper import classify_artifacts, map_assistant_payload


class TestAiHumanCardProjector(unittest.TestCase):
    """切片 A：投影器 schema / Mode-R 数字 / 空结果 / error。"""

    def test_plan_ready_projects_json_scalars_without_invented_pct(self) -> None:
        """合成 dry-run：kind=plan_ready，正文含 Job/步数，不含捏造百分比。"""

        print("\n[TestAiHumanCardProjector] plan_ready Mode-R")
        payload = {
            "run_id": "run_demo",
            "plan": {
                "plan_id": "plan_demo",
                "mode": "plan",
                "user_query": "list built-in strategies",
                "planner_trace": {"intent_job": "strategy.meta"},
                "steps": [
                    {
                        "step_id": "step_1",
                        "skill_name": "qt.ai.strategy_meta.list",
                        "inputs": {},
                        "side_effects": {"description": "readonly"},
                    }
                ],
            },
            "execution": {"status": "dry_run", "steps": []},
        }
        cards = project_human_cards(
            payload,
            requested_mode="plan",
            query="list built-in strategies",
            registry=build_default_registry(),
        )
        kinds = [item["kind"] for item in cards]
        ready = next(item for item in cards if item["kind"] == "plan_ready")
        print(" kinds:", kinds)
        print(" plan_ready text:", ready["text"])
        self.assertIn("user_text", kinds)
        self.assertIn("plan_ready", kinds)
        self.assertIn(ready["kind"], HUMAN_CARD_KINDS)
        self.assertIn("Job: strategy.meta", ready["text"])
        self.assertIn("Steps: 1", ready["text"])
        self.assertIn("qt.ai.strategy_meta.list", ready["text"])
        self.assertNotIn("+12.3%", ready["text"])
        self.assertNotIn("gold_lock", ready["text"])
        self.assertNotIn("# ToolPlan", ready["text"])

    def test_empty_success_result_has_body(self) -> None:
        """ok=True 且空 payload → result 有 no rows 正文。"""

        print("\n[TestAiHumanCardProjector] empty result body")
        payload = {
            "run_id": "run_empty",
            "plan": {
                "plan_id": "plan_empty",
                "planner_trace": {"intent_job": "data.read"},
                "steps": [{"step_id": "s1", "skill_name": "qt.ai.data.read", "inputs": {}}],
            },
            "execution": {
                "status": "success",
                "steps": [
                    {
                        "step_id": "s1",
                        "skill_name": "qt.ai.data.read",
                        "result": {"ok": True, "payload": {}, "metrics": {}, "data_summary": {}},
                    }
                ],
            },
        }
        cards = project_human_cards(payload, requested_mode="run", query="read data")
        result = next(item for item in cards if item["kind"] == "result")
        print(" result text:", result["text"])
        print(" payload executed:", result["payload"].get("executed"))
        self.assertTrue(str(result["text"]).strip())
        self.assertIn("no rows or metrics", result["text"].lower())
        self.assertTrue(result["payload"].get("executed"))

    def test_error_card_has_next_action(self) -> None:
        """错误 → error 卡含 message 与 next_action。"""

        print("\n[TestAiHumanCardProjector] error next_action")
        payload = {
            "error": {
                "code": "PLAN_ID_NOT_FOUND",
                "message": "Reviewed plan not found in runs/: plan_id='plan_x'.",
            }
        }
        cards = project_human_cards(payload, requested_mode="run", query="", include_user_text=False)
        kinds = [item["kind"] for item in cards]
        err = next(item for item in cards if item["kind"] == "error")
        print(" kinds:", kinds)
        print(" error payload:", err["payload"])
        self.assertIn("error", kinds)
        self.assertIn("Reviewed plan not found", err["text"])
        self.assertTrue(str(err["payload"].get("next_action") or "").strip())

    def test_result_uses_json_hit_count_not_invented(self) -> None:
        """metrics.hit_count=3 必须出现在 result 正文。"""

        print("\n[TestAiHumanCardProjector] hit_count from JSON")
        payload = {
            "plan": {
                "plan_id": "plan_ic",
                "planner_trace": {"intent_job": "research.factor_ic"},
                "steps": [{"step_id": "s1", "skill_name": "qt.ai.research.factor_ic_summary", "inputs": {}}],
            },
            "execution": {
                "status": "success",
                "steps": [
                    {
                        "step_id": "s1",
                        "skill_name": "qt.ai.research.factor_ic_summary",
                        "result": {
                            "ok": True,
                            "payload": {"note": "ic summary"},
                            "metrics": {"hit_count": 3, "ic_mean": 0.05},
                        },
                    }
                ],
            },
        }
        cards = project_human_cards(payload, requested_mode="run", query="factor ic")
        result = next(item for item in cards if item["kind"] == "result")
        print(" result:", result["text"])
        self.assertIn("hit_count=3", result["text"])
        self.assertIn("ic_mean=0.05", result["text"])
        self.assertNotIn("hit_count=99", result["text"])


class TestAiHumanCardSessionWrite(unittest.TestCase):
    """切片 B：装配层写入 messages[] / human_cards。"""

    def test_plan_session_writes_plan_ready(self) -> None:
        """plan(session_id) 落盘含 plan_ready，无 plan_card 消息。"""

        print("\n[TestAiHumanCardSessionWrite] plan writes plan_ready")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            payload = asst.plan("list built-in strategies", response_style="raw", session_id="s-plan")
            cards = payload.get("human_cards") or []
            kinds = [item["kind"] for item in cards]
            session = asst.session_store.load("s-plan")
            saved_kinds = [item["kind"] for item in session.messages]
            print(" payload kinds:", kinds)
            print(" saved kinds:", saved_kinds)
            print(" human_cards count:", len(cards))
            self.assertIn("plan_ready", kinds)
            self.assertNotIn("plan_card", kinds)
            self.assertNotIn("step_status", saved_kinds)
            self.assertIn("plan_ready", saved_kinds)
            self.assertEqual(infer_effective_kind(payload), "plan")

    def test_ask_session_writes_ask_not_plan_ready(self) -> None:
        """ask(session_id) 写入 ask，无 plan_ready。"""

        print("\n[TestAiHumanCardSessionWrite] ask writes ask")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            payload = asst.ask("什么是 qteasy", response_style="raw", session_id="s-ask")
            kinds = [item["kind"] for item in (payload.get("human_cards") or [])]
            session = asst.session_store.load("s-ask")
            saved = [item["kind"] for item in session.messages]
            print(" payload kinds:", kinds)
            print(" saved kinds:", saved)
            print(" answer head:", str(payload.get("answer") or "")[:80])
            self.assertIn("ask", kinds)
            self.assertNotIn("plan_ready", kinds)
            self.assertNotIn("plan_ready", saved)
            self.assertIn("ask", saved)

    def test_load_aliases_ask_text_and_drops_unknown(self) -> None:
        """旧 ask_text 加载为 ask；未知 kind 丢弃。"""

        print("\n[TestAiHumanCardSessionWrite] kind aliases")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            sessions = SessionStore(store)
            path = sessions.path_for("legacy")
            path.write_text(
                json.dumps(
                    {
                        "session_id": "legacy",
                        "messages": [
                            {"kind": "ask_text", "text": "hello qteasy", "payload": {}},
                            {"kind": "clarification", "text": "need dates", "payload": {}},
                            {"kind": "future_kind", "text": "ignore me", "payload": {}},
                            {"kind": "plan_card", "text": "skip", "payload": {}},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            loaded = sessions.load("legacy")
            kinds = [item["kind"] for item in loaded.messages]
            texts = [item["text"] for item in loaded.messages]
            print(" loaded kinds:", kinds)
            print(" loaded texts:", texts)
            self.assertIn("ask", kinds)
            self.assertIn("clarify", kinds)
            self.assertNotIn("ask_text", kinds)
            self.assertNotIn("future_kind", kinds)
            self.assertNotIn("plan_card", kinds)


class TestAiHumanCardDegrade(unittest.TestCase):
    """切片 C：run/plan 降级 Ask；CLI 无子命令。"""

    def test_plan_and_run_faq_degrade_to_ask(self) -> None:
        """概念题 plan/run → Ask 卡 + mode_notice，不 execute。"""

        print("\n[TestAiHumanCardDegrade] FAQ degrade")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            planned = asst.plan("什么是 qteasy", response_style="raw")
            ran = asst.run("什么是 qteasy", response_style="raw")
            print(" plan mode:", planned.get("mode"), planned.get("requested_mode"), planned.get("effective_kind"))
            print(" run mode:", ran.get("mode"), ran.get("requested_mode"), ran.get("effective_kind"))
            print(" plan exec:", (planned.get("execution") or {}).get("status"))
            print(" run exec:", (ran.get("execution") or {}).get("status"))
            for payload, requested in ((planned, "plan"), (ran, "run")):
                kinds = [item["kind"] for item in (payload.get("human_cards") or [])]
                print(" kinds:", requested, kinds)
                self.assertEqual(payload.get("mode"), "ask")
                self.assertEqual(payload.get("requested_mode"), requested)
                self.assertEqual(payload.get("effective_kind"), "ask")
                self.assertIn("ask", kinds)
                self.assertIn("mode_notice", kinds)
                self.assertNotIn("plan_ready", kinds)
                self.assertNotEqual((payload.get("execution") or {}).get("status"), "success")
                state = map_assistant_payload(payload, query="什么是 qteasy")
                self.assertTrue(state.plan_card is None or not state.plan_card.confirmable)

    def test_cli_no_subcommand_prints_usage_card(self) -> None:
        """无子命令打印用法卡，不自动 run。"""

        print("\n[TestAiHumanCardDegrade] CLI usage")
        card = usage_notice_card()
        text = format_human_cards([card], payload={"mode": "notice"})
        print(" usage card:", text)
        self.assertEqual(card["kind"], "mode_notice")
        self.assertIn("qteasy-ai ask", card["text"])
        self.assertIn("run --plan-id", card["text"])
        cmd = [sys.executable, "-m", "qteasy_ai.cli"]
        completed = subprocess.run(cmd, capture_output=True, text=True)
        print(" exit:", completed.returncode)
        print(" stdout:", completed.stdout[:400])
        print(" stderr:", completed.stderr[:200])
        self.assertEqual(completed.returncode, 0)
        self.assertIn("qteasy-ai ask", completed.stdout)
        self.assertIn("qteasy-ai plan", completed.stdout)
        self.assertIn("run --plan-id", completed.stdout)
        self.assertNotIn("execution", completed.stdout.lower().split("does not run")[0] if False else completed.stdout[:80])


class TestAiHumanCardPlanArtifact(unittest.TestCase):
    """切片 D：plan Artifact、json_wins、run 不写 plan.md。"""

    def test_plan_dry_run_writes_md_artifact_run_does_not(self) -> None:
        """plan 写 plan.md Artifact；同句 run 不创建 md。"""

        print("\n[TestAiHumanCardPlanArtifact] plan md vs run")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            asst = QteasyAssistant(registry=build_default_registry(), memory_store=store)
            planned = asst.plan("list built-in strategies", response_style="raw")
            plan_run_id = str(planned.get("run_id") or "")
            md_plan = store.runs_dir / f"{plan_run_id}.plan.md"
            json_plan = store.runs_dir / f"{plan_run_id}.json"
            state = map_assistant_payload(planned, query="list built-in strategies")
            art_types = [item.type for item in state.artifacts]
            ready = next(item for item in (planned.get("human_cards") or []) if item["kind"] == "plan_ready")
            print(" plan run_id:", plan_run_id)
            print(" md exists:", md_plan.is_file())
            print(" artifact types:", art_types)
            print(" plan_ready has ToolPlan?:", "# ToolPlan" in ready["text"])
            self.assertTrue(json_plan.is_file())
            self.assertTrue(md_plan.is_file())
            self.assertIn("plan", art_types)
            self.assertNotIn("# ToolPlan", ready["text"])

            before = {path.name for path in store.runs_dir.glob("*.plan.md")}
            ran = asst.run("list built-in strategies", response_style="raw")
            run_id = str(ran.get("run_id") or "")
            after = {path.name for path in store.runs_dir.glob("*.plan.md")}
            run_state = map_assistant_payload(ran, query="list built-in strategies")
            run_types = [item.type for item in run_state.artifacts]
            print(" run_id:", run_id)
            print(" md before/after:", before, after)
            print(" run artifacts:", run_types)
            print(" run json:", (store.runs_dir / f"{run_id}.json").is_file())
            self.assertTrue((store.runs_dir / f"{run_id}.json").is_file())
            self.assertFalse((store.runs_dir / f"{run_id}.plan.md").is_file())
            self.assertEqual(after, before)
            self.assertNotIn("plan", run_types)

    def test_json_wins_mutated_markdown_does_not_change_execute(self) -> None:
        """改磁盘 md 后 run_plan 仍执行 JSON skill。"""

        print("\n[TestAiHumanCardPlanArtifact] json_wins")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            asst = QteasyAssistant(registry=build_default_registry(), memory_store=store)
            planned = asst.plan("list built-in strategies", response_style="raw")
            plan_id = str((planned.get("plan") or {}).get("plan_id") or "")
            run_id = str(planned.get("run_id") or "")
            md_path = store.runs_dir / f"{run_id}.plan.md"
            original = md_path.read_text(encoding="utf-8")
            md_path.write_text(original + "\n\n# HACKED\nskill: qt.ai.backtest.run_builtin\n", encoding="utf-8")
            print(" plan_id:", plan_id)
            print(" mutated head:", md_path.read_text(encoding="utf-8")[-80:])
            executed = asst.run_plan(plan_id, response_style="raw")
            steps = (executed.get("execution") or {}).get("steps") or []
            skills = [item.get("skill_name") for item in steps]
            print(" exec status:", (executed.get("execution") or {}).get("status"))
            print(" skills:", skills)
            self.assertEqual((executed.get("execution") or {}).get("status"), "success")
            self.assertEqual(skills, ["qt.ai.strategy_meta.list"])
            self.assertNotIn("qt.ai.backtest.run_builtin", skills)

    def test_change_slot_new_plan_id_and_md(self) -> None:
        """改槽后新 plan_id 与另一份 md。"""

        print("\n[TestAiHumanCardPlanArtifact] change slot new plan_id")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            asst = QteasyAssistant(registry=build_default_registry(), memory_store=store)
            sid = "s-slot"
            first = asst.plan(
                "帮我写一个基于 20/60 日均线金叉死叉的择时策略，并用 2015–2020 年沪深300做回测",
                response_style="raw",
                session_id=sid,
            )
            first_id = str((first.get("plan") or {}).get("plan_id") or "")
            first_run = str(first.get("run_id") or "")
            second = asst.plan("把慢线改成 50", response_style="raw", session_id=sid)
            second_id = str((second.get("plan") or {}).get("plan_id") or "")
            second_run = str(second.get("run_id") or "")
            print(" first:", first_id, first_run)
            print(" second:", second_id, second_run)
            self.assertTrue(first_id)
            self.assertTrue(second_id)
            self.assertNotEqual(first_id, second_id)
            self.assertTrue((store.runs_dir / f"{first_run}.plan.md").is_file())
            self.assertTrue((store.runs_dir / f"{second_run}.plan.md").is_file())
            self.assertNotEqual(first_run, second_run)


class TestAiHumanCardClarify(unittest.TestCase):
    """切片 E：clarify 选项卡中断。"""

    def test_refill_missing_writes_clarify_and_pending(self) -> None:
        """缺槽 refill：clarify + pending_clarification，本轮不 execute。"""

        print("\n[TestAiHumanCardClarify] refill clarify")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            payload = asst.plan("帮我下载日线", response_style="raw", session_id="s-refill")
            session = asst.session_store.load("s-refill")
            kinds = [item["kind"] for item in (payload.get("human_cards") or [])]
            print(" kinds:", kinds)
            print(" pending:", session.pending_clarification)
            print(" missing:", session.missing)
            print(" exec:", (payload.get("execution") or {}).get("status"))
            self.assertIn("clarify", kinds)
            self.assertIsInstance(session.pending_clarification, dict)
            self.assertTrue(session.missing or session.pending_clarification.get("pending"))
            self.assertEqual((payload.get("execution") or {}).get("status"), "dry_run")
            follow = asst.plan("start 20240101 end 20241231", response_style="raw", session_id="s-refill")
            again = asst.session_store.load("s-refill")
            print(" follow job:", (again.active_intent or {}).get("job"))
            print(" follow missing:", again.missing)
            print(" follow kinds:", [item["kind"] for item in (follow.get("human_cards") or [])])
            self.assertEqual((again.active_intent or {}).get("job"), "data.refill")

    def test_abandon_clarify_has_options(self) -> None:
        """放弃确认：payload.options 非空。"""

        print("\n[TestAiHumanCardClarify] abandon options")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "s-abandon"
            asst.plan("list built-in strategies", response_style="raw", session_id=sid)
            payload = asst.plan("download daily bars from 20180101 to 20201231", response_style="raw", session_id=sid)
            session = asst.session_store.load(sid)
            cards = payload.get("human_cards") or []
            clarify = next((item for item in cards if item["kind"] == "clarify"), None)
            print(" awaiting:", session.awaiting_abandon)
            print(" pending:", session.pending_clarification)
            print(" clarify:", None if clarify is None else clarify)
            print(" kinds:", [item["kind"] for item in cards])
            self.assertIsNotNone(clarify)
            options = (clarify or {}).get("payload", {}).get("options") or []
            print(" options:", options)
            self.assertTrue(options)
            self.assertTrue(any(str(item.get("id") or "") == "abandon" for item in options if isinstance(item, dict)))


class TestAiHumanCardHumanCli(unittest.TestCase):
    """切片 F：--human 消费内核卡。"""

    def test_format_human_matches_kernel_cards(self) -> None:
        """有/无 session 时 stdout 与 human_cards 正文一致。"""

        print("\n[TestAiHumanCardHumanCli] human consumes cards")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            payload = asst.plan("list built-in strategies", response_style="raw", session_id="s-h")
            text = format_human_from_payload(
                payload,
                query="list built-in strategies",
                session=asst.session_store.load("s-h"),
                registry=asst.registry,
            )
            kernel = format_human_cards(payload.get("human_cards") or [], payload=payload)
            print(" human:", text)
            print(" kernel:", kernel)
            self.assertEqual(text, kernel)
            self.assertIn("[MODE: PLAN]", text)
            self.assertIn("Confirm: qteasy-ai run --plan-id", text)
            self.assertIn("plan_id:", text)
            self.assertIn("run_id:", text)
            self.assertNotIn("gold_lock", text)
            lone = asst.plan("list built-in strategies", response_style="raw")
            lone_text = format_human_from_payload(lone, query="list built-in strategies", registry=asst.registry)
            print(" no-session human:", lone_text[:200])
            self.assertEqual(lone_text, format_human_cards(lone.get("human_cards") or [], payload=lone))


class TestAiHumanCardMapperNoDoubleWrite(unittest.TestCase):
    """切片 G：mapper 不发明第二套散文。"""

    def test_mapper_uses_human_cards_without_extra_assistant_prose(self) -> None:
        """已有 human_cards 时 mapper 不追加 plan_card 消息。"""

        print("\n[TestAiHumanCardMapperNoDoubleWrite] mapper consume")
        with tempfile.TemporaryDirectory() as temp_dir:
            asst = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            payload = asst.plan("list built-in strategies", response_style="raw", session_id="s-map")
            state = map_assistant_payload(
                payload,
                session=asst.session_store.load("s-map"),
                query="list built-in strategies",
            )
            kinds = [item.kind for item in state.messages]
            print(" mapped kinds:", kinds)
            print(" plan_card confirmable:", None if state.plan_card is None else state.plan_card.confirmable)
            self.assertIn("plan_ready", kinds)
            self.assertNotIn("plan_card", kinds)
            self.assertNotIn("ask_text", kinds)
            self.assertEqual(kinds.count("plan_ready"), 1)
            self.assertIsNotNone(state.plan_card)
            self.assertTrue(state.plan_card.confirmable)
            arts = classify_artifacts(str(payload.get("run_id") or ""), [])
            print(" classify empty exec:", arts)
            self.assertEqual(arts, [])


if __name__ == "__main__":
    unittest.main()
