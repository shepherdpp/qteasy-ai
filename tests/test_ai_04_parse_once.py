# coding=utf-8
# ======================================
# File: test_ai_04_parse_once.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-22
# Desc:
# 第四步：一句只解析一次。计划不在改接新建，
# 组图失败出恢复卡，点选不回模型。
# ======================================

import inspect
import json
import tempfile
import unittest
from typing import Any, Dict, List

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.intent_engine import IntentEngine
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.parse_turn import FIXED_GUIDE, present_intent_card, parse_utterance
from qteasy_ai.provider import FakeLLMProvider

_TASK = "600519 和 000858 做一条等权组合"
_QUESTION = "QUESTION-MARKER"
_SENTENCE = f"{_TASK} {_QUESTION}"
_INTENT = "INTENT-MARKER-NOT-A-SPAN"
_UNSAFE = "please run rm -rf /tmp"


def _protocol(**overrides: Any) -> str:
    """一份合并协议。缺的键补成空。"""

    payload: Dict[str, Any] = {
        "job": "",
        "intent_text": "",
        "clarification_text": "",
        "open_intent": "",
        "task": "",
        "questions": [],
        "candidates": [],
        "relation": "",
        "plan_id": "",
        "fetch": "",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


def _assistant(temp_dir: str, replies: List[str] = None) -> QteasyAssistant:
    """临时目录里的助手。"""

    provider = FakeLLMProvider(replies=list(replies or [])) if replies is not None else None
    return QteasyAssistant(
        provider=provider,
        registry=build_default_registry(),
        memory_store=MemoryStore(base_dir=temp_dir),
    )


def _plan(result: Dict[str, Any]) -> Dict[str, Any]:
    """raw 结果里的计划。"""

    plan = result.get("plan") or {}
    return plan if isinstance(plan, dict) else {}


def _record(plan: Dict[str, Any]) -> Dict[str, Any]:
    """解析记录。"""

    record = (plan.get("assumptions") or {}).get("parse_record") or {}
    return record if isinstance(record, dict) else {}


def _card(plan: Dict[str, Any]) -> Dict[str, Any]:
    """澄清卡。"""

    card = (plan.get("assumptions") or {}).get("clarification") or {}
    return card if isinstance(card, dict) else {}


def _inputs_blob(plan: Dict[str, Any]) -> str:
    """步骤输入的文本。"""

    chunks = []
    for step in plan.get("steps") or []:
        if isinstance(step, dict):
            chunks.append(json.dumps(step.get("inputs") or {}, ensure_ascii=False))
    return "\n".join(chunks)


def _prompt_examples(system: str) -> List[Dict[str, Any]]:
    """系统提示里每份示例的用户句和 JSON。"""

    rows: List[Dict[str, Any]] = []
    marker = "User sentence: "
    for part in system.split("Example, ")[1:]:
        start = part.find(marker)
        rest = part[start + len(marker):]
        sentence, _, after = rest.partition("\n")
        payload = json.loads(after.strip().splitlines()[0])
        rows.append({"sentence": sentence, "payload": payload})
    return rows


def _seed(assistant: QteasyAssistant, sid: str, *, plan_id: str, status: str) -> None:
    """放一份还没执行的计划。"""

    state = assistant.session_store.load(sid)
    state.start_task(query="已有计划", job="research.hold_compare")
    state.task.status = status
    state.task.plan_id = plan_id
    assistant.session_store.save(state)


class TestAi04ParseOnce(unittest.TestCase):
    """一句只解析一次，确认之后才改图。"""

    def test_one_protocol_carries_job_and_question(self) -> None:
        """一次协议同时给出 Job、意图句、办事和询问。"""

        print("\n[TestAi04ParseOnce] 一次协议带上询问")
        reply = _protocol(
            job="research.hold_compare",
            intent_text=_INTENT,
            task=_TASK,
            questions=[_QUESTION],
            relation="new",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir, [reply, "{}"])
            result = assistant.plan(_SENTENCE, response_style="raw", session_id="s-once", debug=False)
            plan = _plan(result)
            record = _record(plan)
            assumptions = plan.get("assumptions") or {}
            trace = plan.get("planner_trace") or {}
            provider = assistant.planner.provider
            parse_prompts = [item for item in provider.prompts if "User sentence:" in item]
            blob = _inputs_blob(plan)
            task = assistant.session_store.load("s-once").task
            print(" job:", record.get("job"), "intent:", record.get("intent_text"))
            print(" task:", record.get("task"), "questions:", record.get("questions"))
            print(" parse chats:", len(parse_prompts), "executable:", record.get("executable"))
            print(" inputs have markers:", _INTENT in blob, _QUESTION in blob)
            self.assertEqual(record.get("job"), "research.hold_compare")
            self.assertEqual(record.get("intent_text"), _INTENT)
            self.assertEqual(record.get("task"), _TASK)
            self.assertEqual(record.get("questions"), [_QUESTION])
            self.assertEqual(record.get("clarification_text"), "")
            self.assertEqual(record.get("open_intent"), "")
            self.assertTrue(record.get("executable"))
            self.assertEqual(len(parse_prompts), 1)
            self.assertNotIn(_INTENT, blob)
            self.assertNotIn(_QUESTION, blob)
            self.assertNotIn("questions", assumptions)
            self.assertNotIn("parse_debug", assumptions)
            self.assertNotIn("parse_debug", trace)
            self.assertNotIn("classify_protocol", trace)
            self.assertEqual(list(getattr(task, "parse_debug", None) or []), [])

    def test_fetch_once_and_no_model_ignores_it(self) -> None:
        """点名只再解析一次。无模型忽略 fetch，也不再查金句。"""

        print("\n[TestAi04ParseOnce] 点名重解析")
        first = _protocol(fetch="turn:1", task=_TASK, questions=[_QUESTION])
        second = _protocol(
            job="research.hold_compare",
            intent_text=_INTENT,
            task=_TASK,
            questions=[_QUESTION],
            relation="new",
            fetch="turn:99",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir, [first, second, "{}"])
            state = assistant.session_store.load("s-fetch")
            state.append_user_text("TURN-ONE-FULL-SENTENCE")
            state.append_messages([{"kind": "plan_ready", "text": "计划已生成", "payload": {}}])
            assistant.session_store.save(state)
            calls: List[str] = []
            engine = assistant.planner.intent_engine
            original = engine._constitution

            def _counted(query: str, q_lower: str) -> Any:
                calls.append(query)
                return original(query, q_lower)

            engine._constitution = _counted  # type: ignore[method-assign]
            result = assistant.plan(_SENTENCE, response_style="raw", session_id="s-fetch", debug=True)
            plan = _plan(result)
            record = _record(plan)
            prompts = [item for item in assistant.planner.provider.prompts if "User sentence:" in item]
            debug_rows = (plan.get("planner_trace") or {}).get("parse_debug") or []
            print(" parse chats:", len(prompts), "constitution calls:", len(calls))
            print(" second has turn:", "TURN-ONE-FULL-SENTENCE" in prompts[-1] if prompts else False)
            print(" job:", record.get("job"), "questions:", record.get("questions"))
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(prompts), 2)
            self.assertNotIn("Fetched:", prompts[0])
            self.assertIn("Fetched:", prompts[1])
            self.assertIn("TURN-ONE-FULL-SENTENCE", prompts[1])
            self.assertIn("计划已生成", prompts[1])
            self.assertEqual(record.get("job"), "research.hold_compare")
            self.assertEqual(record.get("questions"), [_QUESTION])
            self.assertEqual(len(debug_rows), 2)
            bare = IntentEngine(provider=None)
            ignored = parse_utterance(bare, _TASK, fetched="SHOULD-NOT-CHANGE-GOLD")
            print(" no-model job:", ignored.get("job"), "fetch:", ignored.get("fetch"))
            self.assertEqual(ignored.get("job"), "research.hold_compare")
            self.assertEqual(ignored.get("fetch"), "")
            self.assertEqual(bare.provider, None)

    def test_relation_picks_plan_id_not_status(self) -> None:
        """新建换计划号，修订留下。状态不参与。无模型的重写停在意图卡。"""

        print("\n[TestAi04ParseOnce] relation 决定计划号")
        fresh = _protocol(job="data.summary", intent_text="summary", task="看摘要", relation="new")
        revise = _protocol(job="data.summary", intent_text="summary", task="看摘要", relation="revise")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir, [fresh, "{}"])
            _seed(assistant, "s-rel", plan_id="plan_keep", status="clarifying")
            new_plan = _plan(assistant.plan("看摘要", response_style="raw", session_id="s-rel"))
            new_id = str(new_plan.get("plan_id") or "")
            print(" clarifying+new:", new_id, "relation:", _record(new_plan).get("relation"))
            self.assertNotEqual(new_id, "plan_keep")
            self.assertEqual(_record(new_plan).get("relation"), "new")
            self.assertTrue(_record(new_plan).get("executable"))
            assistant.apply_provider(FakeLLMProvider(replies=[revise, "{}"]))
            _seed(assistant, "s-rel", plan_id="plan_keep", status="ready")
            kept = _plan(assistant.plan("看摘要", response_style="raw", session_id="s-rel"))
            print(" ready+revise:", kept.get("plan_id"), "relation:", _record(kept).get("relation"))
            self.assertEqual(kept.get("plan_id"), "plan_keep")
            self.assertEqual(_record(kept).get("relation"), "revise")
            assistant.apply_provider(None)
            _seed(assistant, "s-rel", plan_id="plan_keep", status="ready")
            card_plan = _plan(assistant.plan("重新写一份计划", response_style="raw", session_id="s-rel"))
            task = assistant.session_store.load("s-rel").task
            print(" rewrite card:", _card(card_plan).get("intent_authored"), "plan:", task.plan_id, task.status)
            self.assertTrue(_card(card_plan).get("intent_authored"))
            self.assertFalse(_record(card_plan).get("executable"))
            self.assertEqual(task.plan_id, "plan_keep")
            self.assertNotEqual(task.status, "cancelled")

    def test_run_does_not_execute_and_missing_plan_becomes_new(self) -> None:
        """运行不执行。计划不在就改成 new，询问还在。"""

        print("\n[TestAi04ParseOnce] 运行不执行，计划不在改接新建")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir, None)
            called = {"run_plan": 0}

            def _run_plan(*args: Any, **kwargs: Any) -> Any:
                called["run_plan"] += 1
                raise AssertionError("run_plan")

            assistant.run_plan = _run_plan  # type: ignore[method-assign]
            _seed(assistant, "s-run", plan_id="plan_keep", status="ready")
            parked = assistant.run("运行上述计划", response_style="raw", session_id="s-run")
            parked_plan = _plan(parked)
            print(" no-model card:", _card(parked_plan).get("intent_authored"), "run_plan:", called["run_plan"])
            print(" execution:", (parked.get("execution") or {}).get("status"))
            self.assertTrue(_card(parked_plan).get("intent_authored"))
            self.assertEqual(called["run_plan"], 0)
            self.assertEqual((parked.get("execution") or {}).get("status"), "dry_run")
            self.assertEqual(assistant.session_store.load("s-run").task.plan_id, "plan_keep")

            assistant.apply_provider(FakeLLMProvider(replies=[
                _protocol(job="data.summary", intent_text="summary", task="看摘要", relation="run"),
                "{}",
            ]))
            kept = assistant.run("看摘要", response_style="raw", session_id="s-run")
            kept_plan = _plan(kept)
            print(
                " run kept:",
                kept_plan.get("plan_id"),
                _record(kept_plan).get("relation"),
                (kept.get("execution") or {}).get("status"),
            )
            self.assertEqual(kept_plan.get("plan_id"), "plan_keep")
            self.assertEqual(_record(kept_plan).get("relation"), "run")
            self.assertTrue(_record(kept_plan).get("executable"))
            self.assertEqual((kept.get("execution") or {}).get("status"), "dry_run")
            self.assertEqual(called["run_plan"], 0)

            assistant.session_store.load("s-run")
            state = assistant.session_store.load("s-gone")
            assistant.session_store.save(state)
            assistant.apply_provider(FakeLLMProvider(replies=[
                _protocol(
                    job="data.summary",
                    intent_text="summary",
                    task="看摘要",
                    questions=["ASK-BIT"],
                    relation="run",
                ),
                "{}",
            ]))
            made = assistant.run("看摘要 ASK-BIT", response_style="raw", session_id="s-gone")
            made_plan = _plan(made)
            print(
                " run missing:",
                made_plan.get("plan_id"),
                _record(made_plan).get("relation"),
                _record(made_plan).get("questions"),
                (made.get("execution") or {}).get("status"),
            )
            self.assertEqual(_record(made_plan).get("relation"), "new")
            self.assertTrue(str(made_plan.get("plan_id") or ""))
            self.assertNotEqual(made_plan.get("plan_id"), "plan_keep")
            self.assertEqual(_record(made_plan).get("questions"), ["ASK-BIT"])
            self.assertTrue(_record(made_plan).get("executable"))
            self.assertEqual((made.get("execution") or {}).get("status"), "dry_run")
            self.assertEqual(called["run_plan"], 0)

    def test_intent_card_and_recover_card_are_different_clicks(self) -> None:
        """意图卡沿用 relation。恢复卡先改成 new。组图失败不回模型确认原句。"""

        print("\n[TestAi04ParseOnce] 意图卡和恢复卡分路")
        utterance = "开放这句 OPEN-SENTENCE"
        issued = _protocol(
            clarification_text="请选一个官方 Job，或确认开放句。",
            open_intent="OPEN-SENTENCE",
            task="开放这句",
            questions=["OPEN-SENTENCE"],
            candidates=[
                {"id": "data.summary", "label": "摘要", "detail": "先看摘要"},
                {"id": "data.export", "label": "导出", "detail": "再导出"},
            ],
            relation="revise",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir, [issued])
            _seed(assistant, "s-card", plan_id="plan_keep", status="ready")
            shown = assistant.plan(utterance, response_style="raw", session_id="s-card", debug=True)
            shown_plan = _plan(shown)
            card = _card(shown_plan)
            row = (card.get("pending") or [{}])[0]
            option_ids = [item.get("id") for item in row.get("options") or []]
            chats_after_card = len(assistant.planner.provider.prompts)
            print(" prompt:", row.get("prompt"), "options:", option_ids)
            print(" open label:", (row.get("open") or {}).get("label"), "chats:", chats_after_card)
            self.assertTrue(card.get("intent_authored"))
            self.assertFalse(card.get("recover_authored"))
            self.assertEqual(row.get("prompt"), "请选一个官方 Job，或确认开放句。")
            self.assertEqual(option_ids, ["data.summary", "data.export", "confirm_open_intent"])
            self.assertEqual((row.get("options") or [])[-1].get("label"), "OPEN-SENTENCE")
            self.assertNotIn("open_confirm", row)
            self.assertEqual((row.get("open") or {}).get("label"), "Your own open intent")
            self.assertNotIn("selected", row)
            self.assertNotIn("default", row)
            self.assertEqual(chats_after_card, 1)
            self.assertEqual(_record(shown_plan).get("questions"), ["OPEN-SENTENCE"])
            self.assertFalse(_record(shown_plan).get("executable"))

            assistant.apply_provider(None)
            clicked = assistant.plan(
                "",
                response_style="raw",
                session_id="s-card",
                patches={"intent": "data.export"},
            )
            clicked_plan = _plan(clicked)
            print(
                " click job:",
                _record(clicked_plan).get("job"),
                "relation:",
                _record(clicked_plan).get("relation"),
                "plan:",
                clicked_plan.get("plan_id"),
                "provider:",
                assistant.planner.provider,
            )
            self.assertEqual(_record(clicked_plan).get("job"), "data.export")
            self.assertEqual(_record(clicked_plan).get("confirmed_by"), "candidate")
            self.assertEqual(_record(clicked_plan).get("relation"), "revise")
            self.assertEqual(_record(clicked_plan).get("questions"), ["OPEN-SENTENCE"])
            self.assertEqual(clicked_plan.get("plan_id"), "plan_keep")
            self.assertIsNone(assistant.planner.provider)
            self.assertTrue(_record(clicked_plan).get("executable"))

            assistant.apply_provider(FakeLLMProvider(replies=[issued, "not json"]))
            _seed(assistant, "s-card", plan_id="plan_keep", status="ready")
            assistant.plan(utterance, response_style="raw", session_id="s-card")
            compose_provider = FakeLLMProvider(replies=["not json"])
            assistant.apply_provider(compose_provider)
            opened = assistant.plan(
                "",
                response_style="raw",
                session_id="s-card",
                patches={"intent": "confirm_open_intent"},
            )
            opened_plan = _plan(opened)
            recover = _card(opened_plan)
            recover_row = (recover.get("pending") or [{}])[0]
            recover_ids = [item.get("id") for item in recover_row.get("options") or []]
            print(" recover:", recover.get("recover_authored"), "ids:", recover_ids)
            print(" compose prompt:", compose_provider.prompts[0] if compose_provider.prompts else "")
            self.assertTrue(recover.get("recover_authored"))
            self.assertFalse(recover.get("intent_authored"))
            self.assertNotIn("confirm_open_intent", recover_ids)
            self.assertLessEqual(len(recover_ids), 2)
            self.assertIn("OPEN-SENTENCE", compose_provider.prompts[0])
            self.assertIn("not built", str(recover_row.get("prompt") or ""))
            self.assertEqual(_record(opened_plan).get("questions"), ["OPEN-SENTENCE"])
            self.assertFalse(_record(opened_plan).get("executable"))

            before = len(assistant.planner.provider.prompts)
            assistant.apply_provider(None)
            recovered = assistant.plan(
                "",
                response_style="raw",
                session_id="s-card",
                patches={"recover": "data.summary"},
            )
            recovered_plan = _plan(recovered)
            print(
                " recover click:",
                _record(recovered_plan).get("relation"),
                recovered_plan.get("plan_id"),
                "provider:",
                assistant.planner.provider,
            )
            self.assertEqual(_record(recovered_plan).get("job"), "data.summary")
            self.assertEqual(_record(recovered_plan).get("confirmed_by"), "recovery")
            self.assertEqual(_record(recovered_plan).get("relation"), "new")
            self.assertNotEqual(recovered_plan.get("plan_id"), "plan_keep")
            self.assertEqual(_record(recovered_plan).get("questions"), ["OPEN-SENTENCE"])
            self.assertIsNone(assistant.planner.provider)
            self.assertTrue(_record(recovered_plan).get("executable"))
            self.assertGreaterEqual(before, 1)

            assistant.apply_provider(None)
            _seed(assistant, "s-card", plan_id="plan_keep", status="ready")
            lone = _plan(assistant.plan("没有候选项的开放句", response_style="raw", session_id="s-card"))
            quiet = assistant.plan(
                "",
                response_style="raw",
                session_id="s-card",
                patches={"intent": "confirm_open_intent"},
            )
            quiet_plan = _plan(quiet)
            quiet_row = (_card(quiet_plan).get("pending") or [{}])[0]
            print(" no-model recover options:", quiet_row.get("options"), "open:", (quiet_row.get("open") or {}).get("label"))
            self.assertTrue(_card(lone).get("intent_authored"))
            self.assertTrue(_card(quiet_plan).get("recover_authored"))
            self.assertEqual(quiet_row.get("options") or [], [])
            self.assertNotIn("open_confirm", quiet_row)
            self.assertNotIn("confirm_open_intent", [item.get("id") for item in quiet_row.get("options") or []])
            self.assertEqual((quiet_row.get("open") or {}).get("label"), "Rewrite the request")
            self.assertFalse(_record(quiet_plan).get("executable"))

            assistant.apply_provider(FakeLLMProvider(replies=["{}"]))
            rewritten = assistant.plan(
                "",
                response_style="raw",
                session_id="s-card",
                patches={"recover": _UNSAFE},
            )
            rewritten_plan = _plan(rewritten)
            print(" rewrite hint:", _record(rewritten_plan).get("constitution_hint"))
            print(" rewrite chats:", len(assistant.planner.provider.prompts))
            self.assertIn("Shell command", str(_record(rewritten_plan).get("constitution_hint") or ""))
            self.assertEqual(assistant.planner.provider.prompts, [])

    def test_question_only_stays_on_the_intent_card(self) -> None:
        """只有询问时停在意图卡，不调用 ask。"""

        print("\n[TestAi04ParseOnce] 只有询问")
        reply = _protocol(
            clarification_text="这句还没有办事。",
            task="",
            questions=["哪个更值得"],
            relation="",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir, [reply])

            def _ask(*args: Any, **kwargs: Any) -> Any:
                raise AssertionError("ask")

            assistant.ask = _ask  # type: ignore[method-assign]
            result = assistant.plan("哪个更值得", response_style="raw", session_id="s-ask")
            plan = _plan(result)
            print(" card:", _card(plan).get("intent_authored"), "questions:", _record(plan).get("questions"))
            self.assertTrue(_card(plan).get("intent_authored"))
            self.assertEqual(_record(plan).get("questions"), ["哪个更值得"])
            self.assertFalse(_record(plan).get("executable"))
            self.assertEqual(_record(plan).get("job"), "")
            self.assertIn("plan", result)

    def test_unsafe_stops_before_the_outline(self) -> None:
        """不安全句不解析，也不准备提纲。"""

        print("\n[TestAi04ParseOnce] 宪法在提纲之前")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir, ["{}"])
            calls: List[str] = []
            import qteasy_ai.ask_engine as ask_engine

            original = ask_engine.render_session_outline

            def _outline(*args: Any, **kwargs: Any) -> str:
                calls.append("outline")
                return original(*args, **kwargs)

            ask_engine.render_session_outline = _outline
            try:
                result = assistant.plan(_UNSAFE, response_style="raw", session_id="s-unsafe", debug=True)
            finally:
                ask_engine.render_session_outline = original
            plan = _plan(result)
            record = _record(plan)
            debug_rows = (plan.get("planner_trace") or {}).get("parse_debug") or []
            print(" hint:", record.get("constitution_hint"), "chats:", len(assistant.planner.provider.prompts))
            print(" debug:", debug_rows, "outline calls:", calls)
            self.assertEqual(assistant.planner.provider.prompts, [])
            self.assertEqual(calls, [])
            self.assertIn("Shell command execution is not supported", str(record.get("constitution_hint") or ""))
            self.assertEqual(debug_rows[0].get("rationale"), "constitution_unsafe")
            self.assertFalse(record.get("executable"))

    def test_parse_source_guards(self) -> None:
        """解析和出卡不再走旧的词表、金句或第二次出卡。"""

        print("\n[TestAi04ParseOnce] 源码守卫")
        import qteasy_ai.parse_turn as parse_turn

        body = inspect.getsource(parse_turn.parse_utterance)
        model = inspect.getsource(parse_turn._parse_with_model)
        gold = inspect.getsource(parse_turn._parse_without_model)
        card = inspect.getsource(parse_turn.present_intent_card)
        constitution = inspect.getsource(IntentEngine._constitution)
        print(" parse lines:", len(body.splitlines()), "card lines:", len(card.splitlines()))
        self.assertNotIn("looks_like_hold_compare", body)
        self.assertNotIn("revision_target", body)
        self.assertNotIn("is_skip_clarify", body)
        self.assertNotIn(".chat(", card)
        self.assertNotIn("_gold_index", model)
        self.assertNotIn("gold_cases", model)
        self.assertNotIn(".chat(", gold)
        self.assertIn("_trigger_hits", constitution)

    def test_parse_prompt_states_goal_and_catalog(self) -> None:
        """系统提示写明目标和字段，清单带官方 Job 摘要。"""

        print("\n[TestAi04ParseOnce] 解析提示写出目标和清单")
        outline = "OUTLINE-ROUND-ONE"
        fake = FakeLLMProvider(replies=[_protocol()])
        engine = IntentEngine(provider=fake)
        parse_utterance(engine, "随便一句", outline=outline)
        system = fake.system_prompts[0]
        user = fake.prompts[0]
        jobs_block = user.split("Outline:")[0]
        examples = _prompt_examples(system)
        print(" system:", system)
        print(" official jobs:", jobs_block)
        print(" examples:", [(row["sentence"], row["payload"].get("task"), row["payload"].get("questions"), row["payload"].get("job")) for row in examples])
        self.assertIn("fill job only when the sentence clearly matches one official Job", system)
        self.assertIn("never true, false, or null", system)
        self.assertIn("the question shown to the user", system)
        self.assertIn("in the same language as the user sentence", system)
        self.assertIn("exact contiguous slice", system)
        self.assertIn("must not overlap", system)
        self.assertIn("Do not translate", system)
        self.assertIn("Each id comes from the Official jobs list", system)
        self.assertIn("Do not fetch it", system)
        self.assertIn("new: this sentence starts a new plan.", system)
        self.assertIn(
            "revise: the outline already has a plan that has not run, and this sentence changes it.",
            system,
        )
        self.assertIn(
            "run: the outline already has a plan that has not run, and this sentence asks to run it.",
            system,
        )
        self.assertIn(
            'abandon: this sentence abandons the current plan that has not run. Then job is "", candidates is [], and open_intent is "".',
            system,
        )
        self.assertIn(
            '"": the sentence and the outline do not show which of the above it is.',
            system,
        )
        self.assertEqual(len(examples), 4)
        for row in examples:
            sentence = str(row["sentence"])
            payload = row["payload"]
            task = str(payload.get("task") or "")
            questions = [str(item) for item in (payload.get("questions") or [])]
            print(" slice:", task, questions, "in", sentence)
            if task:
                self.assertIn(task, sentence)
            for question in questions:
                self.assertIn(question, sentence)
                self.assertNotIn(question, task)
        self.assertEqual(examples[1]["payload"].get("job"), "data.summary")
        self.assertNotEqual(examples[1]["payload"].get("job"), "research.hold_compare")
        self.assertIn(
            "- research.hold_compare: Hold named symbols as one portfolio, optionally beside a benchmark or as excess.",
            jobs_block,
        )
        self.assertIn("Outline:\n" + outline, user)
        self.assertNotIn("- open:", user)
        self.assertNotIn("Fetched:", user)
        self.assertIn("Card replies:", system)
        self.assertIn("not a new user sentence", system)
        self.assertIn(
            "Use the replies only to reconsider job, open_intent, candidates, clarification_text, and relation.",
            system,
        )
        self.assertNotIn("Card replies:", user)

    def test_explicit_open_plan_stays_in_the_prompt_and_on_the_card(self) -> None:
        """明确要开放图时提示留空 job。正例 task 是原句片段。固定协议不改回持有对比。"""

        print("\n[TestAi04ParseOnce] 明确开放图留在提示和意图卡")
        import qteasy_ai.parse_turn as parse_turn

        fake = FakeLLMProvider(replies=[_protocol()])
        parse_utterance(IntentEngine(provider=fake), "随便一句")
        system = fake.system_prompts[0]
        examples = _prompt_examples(system)
        positive = [row for row in examples if "开放图" in str(row["sentence"])]
        negative = [
            row for row in examples
            if row["payload"].get("job") == "research.hold_compare"
        ]
        print(" positive:", [(row["sentence"], row["payload"].get("task"), row["payload"].get("job")) for row in positive])
        print(" negative:", [(row["sentence"], row["payload"].get("job")) for row in negative])
        print(" parse source has 开放图:", "开放图" in inspect.getsource(parse_turn.parse_utterance))
        self.assertIn("explicitly asks for an open plan or an open graph", system)
        self.assertEqual(len(positive), 1)
        sentence = str(positive[0]["sentence"])
        payload = positive[0]["payload"]
        task = str(payload.get("task") or "")
        self.assertIn(task, sentence)
        self.assertIn("开放图", task)
        self.assertEqual(payload.get("job"), "")
        self.assertTrue(str(payload.get("open_intent") or ""))
        self.assertEqual(len(negative), 1)
        self.assertNotIn("开放图", str(negative[0]["sentence"]))
        self.assertNotIn("开放图", inspect.getsource(parse_turn.parse_utterance))
        utterance = "输入 600519 和 000858 做一条等权组合，帮我做一份开放图。"
        reply = _protocol(
            job="",
            intent_text="用户要一份开放图",
            clarification_text="请确认这句开放图。",
            open_intent="用 600519 和 000858 做一条等权组合的开放图",
            task=utterance,
            candidates=[{"id": "research.hold_compare", "label": "持有对比", "detail": "等权"}],
            relation="new",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir, [reply])
            result = assistant.plan(utterance, response_style="raw", session_id="s-open-first")
            plan = _plan(result)
            skills = [
                str(step.get("skill_name") or "")
                for step in (plan.get("steps") or [])
                if isinstance(step, dict)
            ]
            print(" job:", _record(plan).get("job"), "card:", _card(plan).get("intent_authored"), "skills:", skills)
            self.assertTrue(_card(plan).get("intent_authored"))
            self.assertNotEqual(_record(plan).get("job"), "research.hold_compare")
            self.assertNotIn("qt.ai.hp.portfolio", skills)
            self.assertNotIn("qt.ai.data.kline", skills)

    def test_boolean_open_intent_still_voids_the_package(self) -> None:
        """open_intent 写成布尔值时，整包作废，中文题干不留下。"""

        print("\n[TestAi04ParseOnce] 布尔 open_intent 仍整包作废")
        utterance = "什么是最大回撤？"
        reply = json.dumps(
            {
                "job": "",
                "intent_text": "用户在问定义",
                "clarification_text": "中文题干应被丢掉",
                "open_intent": True,
                "task": "",
                "questions": [utterance],
                "candidates": [],
                "relation": "",
                "plan_id": "",
                "fetch": "",
            },
            ensure_ascii=False,
        )
        fake = FakeLLMProvider(replies=[reply])
        package = parse_utterance(IntentEngine(provider=fake), utterance)
        print(" guide:", package.get("clarification_text"))
        print(" open:", package.get("open_intent"), "invalid:", package.get("invalid"))
        print(" questions:", package.get("questions"), "candidates:", package.get("candidates"), "job:", package.get("job"))
        self.assertEqual(package.get("clarification_text"), FIXED_GUIDE)
        self.assertNotIn("中文题干应被丢掉", str(package.get("clarification_text") or ""))
        self.assertEqual(package.get("questions"), [])
        self.assertEqual(package.get("candidates"), [])
        self.assertEqual(package.get("job"), "")
        self.assertTrue(package.get("invalid"))
        self.assertEqual(package.get("open_intent"), utterance)

    def test_typed_open_sentence_is_a_reply(self) -> None:
        """空白框打出与推荐开放句相同的文字时，按回复再解析。"""

        print("\n[TestAi04ParseOnce] 打出开放句原文仍是回复")
        utterance = "开放这句 OPEN-SENTENCE"
        issued = _protocol(
            clarification_text="请选一个官方 Job，或确认开放句。",
            open_intent="OPEN-SENTENCE",
            task="开放这句",
            questions=["OPEN-SENTENCE"],
            candidates=[{"id": "data.summary", "label": "摘要", "detail": "先看摘要"}],
            relation="new",
        )
        follow = _protocol(
            job="data.summary",
            intent_text="改为摘要",
            task=utterance,
            relation="new",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir, [issued, follow, "{}"])
            shown = assistant.plan(utterance, response_style="raw", session_id="s-same", debug=True)
            self.assertTrue(_card(_plan(shown)).get("intent_authored"))
            typed = assistant.plan(
                "",
                response_style="raw",
                session_id="s-same",
                patches={"intent": "OPEN-SENTENCE"},
                debug=True,
            )
            typed_plan = _plan(typed)
            prompts = [item for item in assistant.planner.provider.prompts if "User sentence:" in item]
            print(" confirmed:", _record(typed_plan).get("confirmed_by"), "job:", _record(typed_plan).get("job"))
            print(" prompts:", len(prompts), "last has reply:", "Reply: OPEN-SENTENCE" in prompts[-1])
            self.assertEqual(_record(typed_plan).get("job"), "data.summary")
            self.assertNotEqual(_record(typed_plan).get("confirmed_by"), "open_intent")
            self.assertEqual(_record(typed_plan).get("confirmed_by"), "direct")
            self.assertIn("User sentence:\n" + utterance, prompts[-1])
            self.assertIn("Card replies:", prompts[-1])
            self.assertIn("Reply: OPEN-SENTENCE", prompts[-1])

    def test_blank_reply_reparses_the_original_sentence(self) -> None:
        """空白框回到原句。连续回复留在 Card replies。Composer 另发一句不带上。"""

        print("\n[TestAi04ParseOnce] 空白框回到原句")
        utterance = "开放这句 OPEN-SENTENCE"
        issued = _protocol(
            clarification_text="请选一个官方 Job，或确认开放句。",
            open_intent="OPEN-SENTENCE",
            task="开放这句",
            questions=["OPEN-SENTENCE"],
            candidates=[{"id": "data.summary", "label": "摘要", "detail": "先看摘要"}],
            relation="new",
        )
        again = _protocol(
            clarification_text="还要再选一次。",
            open_intent="OPEN-SENTENCE",
            task="开放这句",
            questions=["OPEN-SENTENCE"],
            candidates=[{"id": "data.export", "label": "导出", "detail": "再导出"}],
            relation="new",
        )
        third = _protocol(
            clarification_text="第三次仍未确认。",
            open_intent="OPEN-SENTENCE",
            task="开放这句",
            questions=["OPEN-SENTENCE"],
            candidates=[{"id": "data.summary", "label": "摘要", "detail": "先看摘要"}],
            relation="new",
        )
        fresh = _protocol(
            job="data.summary",
            intent_text="新的一句",
            task="全新的一句",
            relation="new",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir, [issued, again, third, fresh, "{}"])
            state = assistant.session_store.load("s-reply")
            state.append_user_text("EARLIER-TURN")
            state.append_messages([{"kind": "plan_ready", "text": "旧计划", "payload": {}}])
            assistant.session_store.save(state)
            shown = assistant.plan(utterance, response_style="raw", session_id="s-reply", debug=True)
            self.assertTrue(_card(_plan(shown)).get("intent_authored"))
            first = assistant.plan(
                "",
                response_style="raw",
                session_id="s-reply",
                patches={"intent": "做一张开放步骤图"},
                debug=True,
            )
            state = assistant.session_store.load("s-reply")
            user_texts = [item.get("text") for item in state.messages if item.get("kind") == "user_text"]
            prompts = [item for item in assistant.planner.provider.prompts if "User sentence:" in item]
            outline = prompts[-1].split("Outline:\n", 1)[1].split("\n\nUser sentence:", 1)[0]
            print(" user texts:", user_texts)
            print(" outline has earlier:", "EARLIER-TURN" in outline, "has utterance:", utterance in outline)
            print(" query:", state.task.user_query if state.task else "")
            self.assertEqual(user_texts, ["EARLIER-TURN", utterance])
            self.assertIn("User sentence:\n" + utterance, prompts[-1])
            self.assertIn("Card replies:", prompts[-1])
            self.assertIn("Reply: 做一张开放步骤图", prompts[-1])
            self.assertIn("EARLIER-TURN", outline)
            self.assertNotIn(utterance, outline)
            self.assertNotIn("做一张开放步骤图", outline)
            self.assertEqual(state.task.user_query, utterance)
            self.assertTrue(_card(_plan(first)).get("intent_authored"))

            second = assistant.plan(
                "",
                response_style="raw",
                session_id="s-reply",
                patches={"intent": "再写一句开放意图"},
                debug=True,
            )
            prompts = [item for item in assistant.planner.provider.prompts if "User sentence:" in item]
            print(" rounds:", prompts[-1].count("Reply:"))
            self.assertIn("Reply: 做一张开放步骤图", prompts[-1])
            self.assertIn("Reply: 再写一句开放意图", prompts[-1])
            self.assertGreaterEqual(prompts[-1].count("Round "), 2)
            self.assertTrue(_card(_plan(second)).get("intent_authored"))
            state = assistant.session_store.load("s-reply")
            user_texts = [item.get("text") for item in state.messages if item.get("kind") == "user_text"]
            self.assertEqual(user_texts, ["EARLIER-TURN", utterance])

            composer = assistant.plan("全新的一句", response_style="raw", session_id="s-reply", debug=True)
            prompts = [item for item in assistant.planner.provider.prompts if "User sentence:" in item]
            print(" composer sentence:", "User sentence:\n全新的一句" in prompts[-1], "card replies:", "Card replies:" in prompts[-1])
            print(" composer job:", _record(_plan(composer)).get("job"))
            self.assertIn("User sentence:\n全新的一句", prompts[-1])
            self.assertNotIn("Card replies:", prompts[-1])

    def test_blocked_reply_keeps_the_same_card(self) -> None:
        """空白框过不了宪法时留下说明，原卡继续可答。"""

        print("\n[TestAi04ParseOnce] 空白框被宪法拦住仍留原卡")
        utterance = "开放这句 OPEN-SENTENCE"
        issued = _protocol(
            clarification_text="请选一个官方 Job，或确认开放句。",
            open_intent="OPEN-SENTENCE",
            task="开放这句",
            questions=["OPEN-SENTENCE"],
            candidates=[{"id": "data.summary", "label": "摘要", "detail": "先看摘要"}],
            relation="new",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir, [issued])
            shown = assistant.plan(utterance, response_style="raw", session_id="s-block", debug=True)
            before = _card(_plan(shown))
            before_row = (before.get("pending") or [{}])[0]
            chats = len(assistant.planner.provider.prompts)
            blocked = assistant.plan(
                "",
                response_style="raw",
                session_id="s-block",
                patches={"intent": _UNSAFE},
                debug=True,
            )
            state = assistant.session_store.load("s-block")
            notices = [
                str(item.get("text") or "")
                for item in state.messages
                if item.get("kind") == "mode_notice"
            ]
            pending = state.task.pending_clarification if state.task is not None else {}
            pending_row = ((pending or {}).get("pending") or [{}])[0]
            message_blob = "\n".join(str(item.get("text") or "") for item in state.messages)
            print(" notices:", notices)
            print(" chats:", len(assistant.planner.provider.prompts), "status:", state.task.status if state.task else "")
            print(" pending prompt:", pending_row.get("prompt"), "replies:", list(getattr(state.task, "intent_card_replies", None) or []))
            self.assertEqual(len(assistant.planner.provider.prompts), chats)
            self.assertTrue(any("Shell command" in item for item in notices))
            self.assertEqual(list(getattr(state.task, "intent_card_replies", None) or []), [])
            self.assertEqual(pending_row.get("prompt"), before_row.get("prompt"))
            self.assertEqual(
                [item.get("id") for item in pending_row.get("options") or []],
                [item.get("id") for item in before_row.get("options") or []],
            )
            self.assertNotEqual(state.task.status, "done")
            self.assertNotIn(_UNSAFE, message_blob)
            self.assertTrue(_card(_plan(blocked)).get("intent_authored"))

            assistant.apply_provider(None)
            quiet = assistant.plan("没有候选项的开放句", response_style="raw", session_id="s-quiet")
            self.assertEqual(_record(_plan(quiet)).get("open_intent"), "没有候选项的开放句")
            kept = assistant.plan(
                "",
                response_style="raw",
                session_id="s-quiet",
                patches={"intent": "自己的开放句"},
            )
            quiet_state = assistant.session_store.load("s-quiet")
            print(" no-model open:", _record(_plan(kept)).get("open_intent"), "provider:", assistant.planner.provider)
            self.assertIsNone(assistant.planner.provider)
            self.assertEqual(_record(_plan(kept)).get("open_intent"), "没有候选项的开放句")
            self.assertTrue(_card(_plan(kept)).get("intent_authored"))

            unsafe = assistant.plan(
                "",
                response_style="raw",
                session_id="s-quiet",
                patches={"intent": _UNSAFE},
            )
            unsafe_state = assistant.session_store.load("s-quiet")
            unsafe_row = ((unsafe_state.task.pending_clarification or {}).get("pending") or [{}])[0]
            unsafe_notices = [
                str(item.get("text") or "")
                for item in unsafe_state.messages
                if item.get("kind") == "mode_notice"
            ]
            print(" no-model notices:", unsafe_notices, "status:", unsafe_state.task.status)
            self.assertTrue(any("Shell command" in item for item in unsafe_notices))
            self.assertEqual(unsafe_row.get("prompt"), (_card(_plan(kept)).get("pending") or [{}])[0].get("prompt"))
            self.assertNotEqual(unsafe_state.task.status, "done")
            self.assertNotIn(_UNSAFE, "\n".join(str(item.get("text") or "") for item in unsafe_state.messages))
            self.assertTrue(_card(_plan(unsafe)).get("intent_authored"))
