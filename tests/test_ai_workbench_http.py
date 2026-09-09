# coding=utf-8
# ======================================
# File: test_ai_workbench_http.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-07
# Desc:
# Unittest for Starlette workbench adapter (G.3)
# ======================================

import json
import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.workbench.http_app import create_app


class TestAiWorkbenchHttp(unittest.TestCase):
    """G.3：HTTP 只调 Assistant，与 CLI 同 runs/。"""

    def _client(self, temp_dir: str, **profile):
        """同一 MemoryStore 的 TestClient。"""

        from starlette.testclient import TestClient

        store = MemoryStore(base_dir=temp_dir)
        if profile:
            store.save_profile(dict(profile))
        assistant = QteasyAssistant(memory_store=store, registry=build_default_registry())
        app = create_app(assistant=assistant)
        return TestClient(app), store, assistant

    def test_plan_persists_same_runs(self) -> None:
        """POST /v1/plan 的 plan_id 能在 runs/ 找到。"""

        print("\n[TestAiWorkbenchHttp] plan persists")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, store, _asst = self._client(temp_dir)
            res = client.post("/v1/plan", json={"query": "list built-in strategies"})
            body = res.json()
            print(" status_code:", res.status_code)
            print(" execution:", body.get("execution"))
            print(" plan_id:", (body.get("plan_card") or {}).get("plan_id"))
            self.assertEqual(res.status_code, 200)
            plan_id = (body.get("plan_card") or {}).get("plan_id")
            self.assertTrue(plan_id)
            found = store.find_run_by_plan_id(plan_id)
            print(" found plan_id:", (found.get("plan") or {}).get("plan_id"))
            self.assertEqual((found.get("plan") or {}).get("plan_id"), plan_id)
            self.assertEqual((found.get("execution") or {}).get("status"), "dry_run")

    def test_run_plan_does_not_rehybrid(self) -> None:
        """先 plan A，再 plan B，run-plan A 仍执行 A 的 skill。"""

        print("\n[TestAiWorkbenchHttp] run-plan no rehybrid")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, store, _asst = self._client(temp_dir)
            first = client.post("/v1/plan", json={"query": "list built-in strategies"}).json()
            plan_id = first["plan_card"]["plan_id"]
            client.post("/v1/plan", json={"query": "帮我下载日线"})
            executed = client.post("/v1/run-plan", json={"plan_id": plan_id})
            body = executed.json()
            skills = [s["skill_name"] for s in (body.get("execution") or {}).get("steps") or []]
            print(" plan_id:", plan_id)
            print(" execute skills:", skills)
            print(" status:", (body.get("execution") or {}).get("status"))
            self.assertEqual(executed.status_code, 200)
            self.assertIn("qt.ai.strategy_meta.list", skills)
            self.assertNotIn("qt.ai.data.refill_basic_equity_and_index", skills)

    def test_plan_without_run_plan_not_success(self) -> None:
        """只 plan 不 run-plan → 无 success execute。"""

        print("\n[TestAiWorkbenchHttp] plan only dry_run")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, store, _asst = self._client(temp_dir)
            client.post("/v1/plan", json={"query": "list built-in strategies"})
            statuses = []
            for run_id in store.list_runs():
                rec = store.load_run(run_id)
                statuses.append((rec.get("execution") or {}).get("status"))
            print(" statuses:", statuses)
            self.assertTrue(statuses)
            self.assertTrue(all(item == "dry_run" for item in statuses))

    def test_ask_hits_kb_no_skill(self) -> None:
        """POST /v1/ask 命中 what_is_qteasy，无 skill handler 产物。"""

        print("\n[TestAiWorkbenchHttp] ask kb")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store, _asst = self._client(temp_dir)
            res = client.post("/v1/ask", json={"query": "什么是 qteasy"})
            body = res.json()
            print(" mode:", body.get("mode"))
            print(" sources:", body.get("sources"))
            print(" artifacts:", body.get("artifacts"))
            self.assertEqual(body.get("mode"), "ask")
            self.assertIn("what_is_qteasy", body.get("sources") or [])
            self.assertEqual(body.get("artifacts") or [], [])
            kinds = [m["kind"] for m in body.get("messages") or []]
            self.assertNotIn("plan_card", kinds)

    def test_agent_auto_refill_blocked(self) -> None:
        """POST /v1/run + agent_auto + allow_refill=false → 门控英文错误。"""

        print("\n[TestAiWorkbenchHttp] allow_refill blocked")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store, _asst = self._client(
                temp_dir,
                agent={"allow_refill": False, "allow_backtest": False, "allow_optimize": False},
            )
            res = client.post(
                "/v1/run",
                json={
                    "query": "download daily data from 20180101 to 20231231",
                    "session_id": "auto-refill",
                    "agent_auto": True,
                },
            )
            body = res.json()
            print(" execution:", body.get("execution"))
            print(" error:", body.get("error"))
            self.assertEqual((body.get("execution") or {}).get("status"), "dry_run")
            err = body.get("error") or {}
            self.assertEqual(err.get("code"), "ALLOW_GATE_BLOCKED")
            self.assertRegex(str(err.get("message") or ""), r"[A-Za-z]")

    def test_missing_and_unknown_plan_id(self) -> None:
        """缺 plan_id / 未知 id → 4xx 英文，不改走 query run。"""

        print("\n[TestAiWorkbenchHttp] plan_id errors")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, store, _asst = self._client(temp_dir)
            missing = client.post("/v1/run-plan", json={})
            unknown = client.post("/v1/run-plan", json={"plan_id": "plan_does_not_exist"})
            print(" missing:", missing.status_code, missing.json())
            print(" unknown:", unknown.status_code, unknown.json())
            self.assertEqual(missing.status_code, 400)
            self.assertIn("plan_id", str(missing.json().get("error", {}).get("message") or "").lower())
            self.assertEqual(unknown.status_code, 404)
            self.assertRegex(str(unknown.json().get("error", {}).get("message") or ""), r"[A-Za-z]")
            self.assertEqual(store.list_runs(), [])

    def test_session_followup_keeps_intent(self) -> None:
        """同一 session_id 改槽不换 Job。"""

        print("\n[TestAiWorkbenchHttp] session followup")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store, asst = self._client(temp_dir)
            first = client.post(
                "/v1/plan",
                json={
                    "query": "帮我写一个基于 20/60 日均线金叉死叉的择时策略，并用 2015–2020 年沪深300做回测",
                    "session_id": "s-web",
                },
            ).json()
            second = client.post(
                "/v1/plan",
                json={"query": "把慢线改成 50", "session_id": "s-web"},
            ).json()
            sess = client.get("/v1/session/s-web").json()
            job1 = (first.get("sidebar") or {}).get("active_intent") or {}
            job2 = (second.get("sidebar") or {}).get("active_intent") or {}
            print(" job1:", job1, "job2:", job2)
            print(" session sidebar:", sess.get("sidebar"))
            self.assertEqual(job1.get("job"), "strategy.builder")
            self.assertEqual(job2.get("job"), "strategy.builder")
            loaded = asst.session_store.load("s-web")
            print(" loaded job:", loaded.active_intent)
            self.assertEqual((loaded.active_intent or {}).get("job"), "strategy.builder")

    def test_sse_has_step_or_fallback_list(self) -> None:
        """execute 后 SSE 至少一条 step_status，或同步 steps 非空。"""

        print("\n[TestAiWorkbenchHttp] sse events")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store, _asst = self._client(temp_dir)
            planned = client.post("/v1/plan", json={"query": "list built-in strategies"}).json()
            plan_id = planned["plan_card"]["plan_id"]
            executed = client.post("/v1/run-plan", json={"plan_id": plan_id}).json()
            run_id = executed.get("run_id")
            steps = (executed.get("execution") or {}).get("steps") or []
            print(" run_id:", run_id, "sync steps:", steps)
            self.assertTrue(steps)
            events = client.get(f"/v1/runs/{run_id}/events")
            print(" sse:", events.status_code, events.text[:240])
            self.assertEqual(events.status_code, 200)
            self.assertIn("step_status", events.text)

    def test_list_sessions_and_workspace_index(self) -> None:
        """GET /v1/sessions 列举会话；/v1/workspace 按 session 返回产物索引。"""

        print("\n[TestAiWorkbenchHttp] sessions and workspace")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, store, asst = self._client(temp_dir)
            client.post("/v1/plan", json={"query": "list built-in strategies", "session_id": "web-demo"})
            listed = client.get("/v1/sessions")
            body = listed.json()
            ids = [row.get("session_id") for row in (body.get("sessions") or [])]
            print(" sessions status:", listed.status_code)
            print(" session ids:", ids)
            self.assertEqual(listed.status_code, 200)
            self.assertTrue(body.get("ok"))
            self.assertIn("web-demo", ids)
            empty = client.get("/v1/workspace")
            print(" workspace no session:", empty.status_code, empty.json())
            self.assertEqual(empty.status_code, 200)
            self.assertEqual(empty.json().get("artifacts"), [])
            scoped = client.get("/v1/workspace", params={"session_id": "web-demo"})
            print(" workspace scoped:", scoped.status_code, scoped.json())
            self.assertEqual(scoped.status_code, 200)
            self.assertEqual(scoped.json().get("session_id"), "web-demo")
            self.assertIn("artifacts", scoped.json())
            demo = store.strategies_dir / "demo.py"
            demo.write_text("class Demo:\n    pass\n", encoding="utf-8")
            preview = client.get("/v1/workspace/file", params={"path": "strategies/demo.py"})
            print(" file status:", preview.status_code, preview.json().get("content", "")[:40])
            self.assertEqual(preview.status_code, 200)
            self.assertIn("class Demo", preview.json().get("content") or "")
            outside = client.get("/v1/workspace/file", params={"path": "../secret.py"})
            print(" outside:", outside.status_code, outside.json())
            self.assertEqual(outside.status_code, 404)
            loaded = asst.session_store.load("web-demo")
            print(" loaded session_id:", loaded.session_id)
            print(" loaded messages:", loaded.messages)
            self.assertEqual(loaded.session_id, "web-demo")
            self.assertTrue(any(m.get("kind") == "user_text" for m in loaded.messages))

    def test_get_session_restores_plan_from_plan_id(self) -> None:
        """GET /v1/session 按 current_plan_id 回填 plan_card / execution。"""

        print("\n[TestAiWorkbenchHttp] session restore plan")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store, asst = self._client(temp_dir)
            planned = client.post(
                "/v1/plan",
                json={"query": "list built-in strategies", "session_id": "s-restore"},
            )
            body = planned.json()
            plan_id = (body.get("plan_card") or {}).get("plan_id")
            print(" plan status:", planned.status_code)
            print(" plan_id:", plan_id)
            loaded = asst.session_store.load("s-restore")
            print(" current_plan_id:", loaded.current_plan_id)
            self.assertTrue(plan_id)
            self.assertEqual(loaded.current_plan_id, plan_id)
            sess = client.get("/v1/session/s-restore")
            restored = sess.json()
            card = restored.get("plan_card") or {}
            print(" restore status:", sess.status_code)
            print(" restored plan_id:", card.get("plan_id"))
            print(" restored steps:", card.get("steps"))
            print(" execution:", restored.get("execution"))
            print(" turns:", restored.get("turns"))
            self.assertEqual(sess.status_code, 200)
            self.assertEqual(card.get("plan_id"), plan_id)
            self.assertTrue(card.get("steps"))
            self.assertEqual(card["steps"][0].get("skill_name"), "qt.ai.strategy_meta.list")
            self.assertEqual((restored.get("execution") or {}).get("status"), "dry_run")
            self.assertTrue(card.get("confirmable"))
            self.assertTrue(restored.get("turns"))
            kinds = [m.get("kind") for m in (restored.get("transcript") or [])]
            texts = [m.get("text") for m in (restored.get("transcript") or [])]
            print(" transcript kinds:", kinds)
            print(" transcript texts:", texts)
            self.assertIn("user_text", kinds)
            self.assertTrue(any(k in {"ask_text", "clarification"} for k in kinds))
            self.assertTrue(any("Plan ready" in str(t) or "Clarif" in str(t) or "qteasy" in str(t).lower() for t in texts))

    def test_run_plan_optional_sse_keeps_default_json(self) -> None:
        """?stream=1 返回 SSE；默认 POST 仍是 JSON 且含 steps。"""

        print("\n[TestAiWorkbenchHttp] run-plan sse optional")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store, _asst = self._client(temp_dir)
            planned = client.post("/v1/plan", json={"query": "list built-in strategies"}).json()
            plan_id = planned["plan_card"]["plan_id"]
            default = client.post("/v1/run-plan", json={"plan_id": plan_id, "session_id": "s-sse"})
            print(" json status:", default.status_code)
            print(" json ctype:", default.headers.get("content-type"))
            print(" json steps:", (default.json().get("execution") or {}).get("steps"))
            self.assertEqual(default.status_code, 200)
            self.assertIn("application/json", default.headers.get("content-type") or "")
            self.assertTrue((default.json().get("execution") or {}).get("steps"))
            planned2 = client.post("/v1/plan", json={"query": "list built-in strategies"}).json()
            plan_id2 = planned2["plan_card"]["plan_id"]
            streamed = client.post(
                "/v1/run-plan",
                params={"stream": "1"},
                json={"plan_id": plan_id2, "session_id": "s-sse"},
                headers={"Accept": "text/event-stream"},
            )
            print(" sse status:", streamed.status_code)
            print(" sse ctype:", streamed.headers.get("content-type"))
            print(" sse text:", streamed.text[:400])
            self.assertEqual(streamed.status_code, 200)
            self.assertIn("text/event-stream", streamed.headers.get("content-type") or "")
            self.assertIn("event: step_status", streamed.text)
            self.assertIn("event: state", streamed.text)
            self.assertIn("qt.ai.strategy_meta.list", streamed.text)

    def test_confirm_list_strategies_persists_artifact(self) -> None:
        """两次同文案 Plan 后 Confirm：messages 含 Finished，Artifacts 含策略表。"""

        print("\n[TestAiWorkbenchHttp] confirm list strategies artifact")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store, asst = self._client(temp_dir)
            sid = "s-list-art"
            first = client.post(
                "/v1/plan",
                json={"query": "list built-in strategies", "session_id": sid},
            ).json()
            second = client.post(
                "/v1/plan",
                json={"query": "list built-in strategies", "session_id": sid},
            ).json()
            plan_id = (second.get("plan_card") or {}).get("plan_id")
            print(" first plan:", (first.get("plan_card") or {}).get("plan_id"))
            print(" second plan:", plan_id)
            self.assertTrue(plan_id)
            loaded = asst.session_store.load(sid)
            ready = [m for m in loaded.messages if str(m.get("text") or "").startswith("Plan ready:")]
            print(" plan ready count:", len(ready), ready)
            self.assertGreaterEqual(len(ready), 2)
            self.assertTrue(all("List built-in strategies" in str(m.get("text") or "") for m in ready))
            user_lines = [m for m in loaded.messages if m.get("kind") == "user_text"]
            print(" user_text count:", len(user_lines))
            self.assertEqual(len(user_lines), 2)
            ran = client.post("/v1/run-plan", json={"plan_id": plan_id, "session_id": sid})
            body = ran.json()
            print(" run status:", ran.status_code, (body.get("execution") or {}).get("status"))
            print(" artifacts:", body.get("artifacts"))
            print(" transcript:", body.get("transcript"))
            self.assertEqual(ran.status_code, 200)
            self.assertEqual((body.get("execution") or {}).get("status"), "success")
            arts = body.get("artifacts") or []
            self.assertTrue(arts)
            self.assertEqual(arts[0].get("type"), "data_table")
            rows = ((arts[0].get("preview") or {}).get("preview_rows")) or []
            print(" strategy rows head:", rows[:5])
            self.assertTrue(rows)
            self.assertIn("strategy", rows[0])
            texts = [str(m.get("text") or "") for m in (body.get("transcript") or [])]
            self.assertTrue(any(t.startswith("Finished:") for t in texts))
            again = asst.session_store.load(sid)
            print(" task_complete:", again.task_complete, "awaiting_abandon:", again.awaiting_abandon)
            self.assertTrue(again.task_complete)
            self.assertFalse(again.awaiting_abandon)
            ws = client.get("/v1/workspace", params={"session_id": sid}).json()
            print(" workspace arts:", ws.get("artifacts"))
            self.assertTrue(ws.get("artifacts"))

    def test_after_list_complete_new_builder_query_is_new_intent(self) -> None:
        """列策略 Confirm 完成后，再要写均线策略不得再走 strategy_meta.get。"""

        print("\n[TestAiWorkbenchHttp] after list complete → builder")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store, asst = self._client(temp_dir)
            sid = "s-after-list"
            planned = client.post(
                "/v1/plan",
                json={"query": "请帮我列出所有的内置交易策略", "session_id": sid},
            ).json()
            plan_id = (planned.get("plan_card") or {}).get("plan_id")
            ran = client.post("/v1/run-plan", json={"plan_id": plan_id, "session_id": sid})
            print(" list exec:", ran.status_code, (ran.json().get("execution") or {}).get("status"))
            self.assertEqual((ran.json().get("execution") or {}).get("status"), "success")
            done = asst.session_store.load(sid)
            print(" after list:", done.active_intent, "complete:", done.task_complete)
            self.assertTrue(done.task_complete)
            nxt = client.post(
                "/v1/plan",
                json={
                    "query": "帮我写一个基于 20/60 日均线金叉死叉的择时策略，并用 2015–2020 年沪深300做回测",
                    "session_id": sid,
                },
            )
            body = nxt.json()
            loaded = asst.session_store.load(sid)
            print(" next status:", nxt.status_code)
            print(" next job:", (loaded.active_intent or {}).get("job"))
            print(" next turn:", loaded.turns[-1] if loaded.turns else None)
            print(" next card:", body.get("plan_card"))
            print(" next messages:", body.get("transcript") or body.get("messages"))
            self.assertEqual(nxt.status_code, 200)
            self.assertEqual(loaded.turns[-1].get("kind"), "new_intent")
            self.assertFalse(loaded.turns[-1].get("skip_classify"))
            job = str((loaded.active_intent or {}).get("job") or "")
            self.assertNotEqual(job, "strategy.meta")
            steps = (body.get("plan_card") or {}).get("steps") or []
            skills = [str(s.get("skill_name") or "") for s in steps]
            print(" skills:", skills)
            self.assertFalse(any(name == "qt.ai.strategy_meta.get" for name in skills))
            self.assertFalse(any(name == "qt.ai.strategy_meta.list" for name in skills))

    def test_confirm_bband_get_shows_strategy_doc_artifact(self) -> None:
        """strategy_meta.get 执行后 Artifacts 含策略文档表。"""

        print("\n[TestAiWorkbenchHttp] bband get artifact")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store, _asst = self._client(temp_dir)
            sid = "s-bband"
            planned = client.post(
                "/v1/plan",
                json={"query": "show me bband strategy parameters", "session_id": sid},
            ).json()
            plan_id = (planned.get("plan_card") or {}).get("plan_id")
            skills = [
                str(s.get("skill_name") or "")
                for s in (planned.get("plan_card") or {}).get("steps") or []
            ]
            print(" plan_id:", plan_id, "skills:", skills)
            self.assertTrue(plan_id)
            self.assertIn("qt.ai.strategy_meta.get", skills)
            ran = client.post("/v1/run-plan", json={"plan_id": plan_id, "session_id": sid})
            body = ran.json()
            print(" exec:", (body.get("execution") or {}).get("status"))
            print(" artifacts:", body.get("artifacts"))
            self.assertEqual(ran.status_code, 200)
            self.assertEqual((body.get("execution") or {}).get("status"), "success")
            arts = body.get("artifacts") or []
            self.assertTrue(arts)
            self.assertEqual(arts[0].get("type"), "data_table")
            summary = (arts[0].get("preview") or {}).get("data_summary") or {}
            print(" summary:", summary)
            self.assertEqual(summary.get("strategy_id"), "bband")
            rows = (arts[0].get("preview") or {}).get("preview_rows") or []
            print(" doc lines head:", rows[:3])
            self.assertTrue(rows)
            ws = client.get("/v1/workspace", params={"session_id": sid}).json()
            print(" workspace:", len(ws.get("artifacts") or []))
            self.assertTrue(ws.get("artifacts"))

    def test_http_error_includes_next_action(self) -> None:
        """4xx 错误含英文 next_action。"""

        print("\n[TestAiWorkbenchHttp] error next_action")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store, _asst = self._client(temp_dir)
            missing = client.post("/v1/run-plan", json={})
            body = missing.json()
            print(" missing:", missing.status_code, body)
            self.assertEqual(missing.status_code, 400)
            err = body.get("error") or {}
            self.assertRegex(str(err.get("message") or ""), r"[A-Za-z]")
            self.assertRegex(str(err.get("next_action") or ""), r"[A-Za-z]")
            self.assertIn("Confirm", str(err.get("next_action") or ""))

    def test_session_transcript_keeps_assistant_reply(self) -> None:
        """同一 session 先 Ask 再 GET：transcript 含用户句与助手回答。"""

        print("\n[TestAiWorkbenchHttp] session transcript dialogue")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, store, _asst = self._client(temp_dir)
            asked = client.post(
                "/v1/ask",
                json={"query": "What is qteasy?", "session_id": "s-chat"},
            )
            print(" ask status:", asked.status_code)
            print(" ask kinds:", [m.get("kind") for m in (asked.json().get("messages") or [])])
            self.assertEqual(asked.status_code, 200)
            sess = client.get("/v1/session/s-chat")
            hist = sess.json().get("transcript") or []
            kinds = [m.get("kind") for m in hist]
            texts = [m.get("text") for m in hist]
            print(" restore kinds:", kinds)
            print(" restore texts:", texts)
            listed = [row.get("session_id") for row in client.get("/v1/sessions").json().get("sessions") or []]
            print(" listed sessions:", listed)
            self.assertIn("user_text", kinds)
            self.assertIn("ask_text", kinds)
            self.assertTrue(any("qteasy" in str(t).lower() and m == "ask_text" for m, t in zip(kinds, texts)))
            self.assertNotIn("s-chat.transcript", listed)
            disk = store.sessions_dir / "s-chat.json"
            print(" session file:", disk.is_file(), (disk.read_text(encoding="utf-8")[:200] if disk.is_file() else ""))
            self.assertTrue(disk.is_file())
            saved = json.loads(disk.read_text(encoding="utf-8"))
            print(" saved message kinds:", [m.get("kind") for m in saved.get("messages") or []])
            self.assertTrue(any(m.get("kind") == "ask_text" for m in saved.get("messages") or []))
            print(" restored mode:", sess.json().get("mode"))
            self.assertEqual(sess.json().get("mode"), "ask")

            other = client.post("/v1/ask", json={"query": "What is a DataSource?", "session_id": "s-other"})
            print(" other ask:", other.status_code)
            back = client.get("/v1/session/s-chat")
            back_kinds = [m.get("kind") for m in (back.json().get("transcript") or [])]
            back_texts = [m.get("text") for m in (back.json().get("transcript") or [])]
            print(" after switch kinds:", back_kinds)
            print(" after switch texts:", back_texts)
            self.assertIn("ask_text", back_kinds)
            self.assertTrue(any("qteasy" in str(t).lower() for t in back_texts))
            other_arts = client.get("/v1/workspace", params={"session_id": "s-other"}).json().get("artifacts") or []
            chat_arts = client.get("/v1/workspace", params={"session_id": "s-chat"}).json().get("artifacts") or []
            print(" artifact counts other/chat:", len(other_arts), len(chat_arts))
            other_runs = {a.get("run_id") for a in other_arts}
            chat_runs = {a.get("run_id") for a in chat_arts}
            self.assertTrue(other_runs.isdisjoint(chat_runs) or not other_runs or not chat_runs)

            rewind = client.post(
                "/v1/session/s-chat/rewind",
                json={"message_index": 0, "query": "What is HistoryPanel?", "mode": "ask"},
            )
            print(" rewind:", rewind.status_code, rewind.json().get("transcript"))
            self.assertEqual(rewind.status_code, 200)
            rw = rewind.json().get("transcript") or []
            print(" rewind kinds:", [m.get("kind") for m in rw])
            self.assertTrue(any("HistoryPanel" in str(m.get("text") or "") for m in rw if m.get("kind") == "user_text"))
            self.assertFalse(any(m.get("text") == "What is qteasy?" for m in rw if m.get("kind") == "user_text"))

            prov = client.get("/v1/provider")
            print(" provider:", prov.status_code, prov.json())
            self.assertEqual(prov.status_code, 200)
            self.assertNotIn("api_key", prov.json())
            self.assertIn("api_key_present", prov.json())
            self.assertIn("configured", prov.json())
            denied = client.post("/v1/provider", json={"model": "x", "confirmed": False})
            print(" provider deny:", denied.status_code, denied.json())
            self.assertEqual(denied.status_code, 400)
            ok_prov = client.post(
                "/v1/provider",
                json={"model": "demo-model", "base_url": "http://127.0.0.1:9", "api_key": "sk-test", "confirmed": True},
            )
            print(" provider save:", ok_prov.status_code, ok_prov.json())
            self.assertEqual(ok_prov.status_code, 200)
            self.assertNotIn("api_key", ok_prov.json())
            self.assertTrue(ok_prov.json().get("api_key_present"))
            self.assertEqual(ok_prov.json().get("mode"), "local_llm")

    def test_workspace_artifacts_stay_on_own_session(self) -> None:
        """Session A 的 run 产物不得出现在 Session B 的 workspace。"""

        print("\n[TestAiWorkbenchHttp] artifacts scoped to session")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, store, _asst = self._client(temp_dir)
            run_id = "run_c6a"
            store.save_run(
                run_id,
                {
                    "run_id": run_id,
                    "execution": {
                        "status": "success",
                        "steps": [
                            {
                                "skill_name": "qt.ai.data.read",
                                "result": {
                                    "ok": True,
                                    "data_summary": {"n_rows": 1},
                                    "payload": {"preview_rows": [{"close": 1.0}]},
                                },
                            }
                        ],
                    },
                },
            )
            from qteasy_ai.session import ConversationState, SessionStore

            sessions = SessionStore(store)
            left = ConversationState.empty("sess-a")
            left.append_messages(
                [{"kind": "ask_text", "text": "table ready", "payload": {"run_id": run_id, "executed": True}}]
            )
            sessions.save(left)
            sessions.save(ConversationState.empty("sess-b"))
            arts_a = client.get("/v1/workspace", params={"session_id": "sess-a"}).json().get("artifacts") or []
            arts_b = client.get("/v1/workspace", params={"session_id": "sess-b"}).json().get("artifacts") or []
            print(" arts A:", arts_a)
            print(" arts B:", arts_b)
            self.assertTrue(any(item.get("run_id") == run_id for item in arts_a))
            self.assertTrue(all(item.get("session_id") == "sess-a" for item in arts_a))
            self.assertFalse(any(item.get("run_id") == run_id for item in arts_b))


if __name__ == "__main__":
    unittest.main()
