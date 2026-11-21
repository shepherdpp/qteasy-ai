# coding=utf-8
# ======================================
# File: test_ai_04_split_question.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-18
# Desc:
# 有模型时把办事和附带提问拆开。
# 无模型整句进入现有分类，不认标记词。
# ======================================

import json
import tempfile
import unittest
from typing import Any, Dict, List

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.session import ConversationState
from qteasy_ai.slot_graph import split_task_and_question

_CUM = "主要做累计、顺便问超额会变成什么"
_TASK = "主要做累计"
_QUESTION = "顺便问超额会变成什么"
_WORTH = "哪个更值得"
_PRIOR = "跟上次是不是一回事"
_EXCESS_Q = "超额会怎样"
_READY = "600519 和 000858 做一条等权组合，看累计收益"
_CLAUSE_LINES = (
    "task 是要执行的连续原文，question 是顺口问的连续原文，可以是空字符串。",
    "两段都必须是用户原句里的连续片段，不许改写。",
    "question 非空时，task 不得包含它，两段不得重叠。做不到就两段都交空字符串。",
    "「主要做累计、顺便问超额会变成什么」拆成办事「主要做累计」、提问「顺便问超额会变成什么」",
    "「哪个更值得」办事为空、提问是整句",
    "一句没有附带提问的话，提问为空、办事是整句",
)
_BANNED_NAMES = (
    "research.hold_compare",
    "data.refill",
    "backtest.builtin",
    "route_to_ask",
    "benchmark_output",
    "excess_close",
    "holdings",
    "shares",
    "htypes",
)


def _job_reply() -> str:
    """分类器若被调用才会用到的持有对比回复。"""

    return json.dumps({"job": "research.hold_compare", "uncertain": False}, ensure_ascii=False)


def _split_reply(task: str, question: str) -> str:
    """拆分协议。"""

    return json.dumps({"task": task, "question": question}, ensure_ascii=False)


def _pending_names(plan: Any) -> List[str]:
    """澄清卡上的题名。"""

    blob = (plan.assumptions or {}).get("clarification") or {}
    return [str(item.get("name") or "") for item in (blob.get("pending") or []) if isinstance(item, dict)]


def _graph_rows(plan: Any) -> List[Dict[str, Any]]:
    """澄清时看已收下的步骤图，否则看可见步骤。"""

    accepted = (plan.assumptions or {}).get("accepted_steps") or []
    if accepted:
        return [dict(step) for step in accepted if isinstance(step, dict)]
    return [
        {"skill_name": step.skill_name, "inputs": dict(step.inputs or {})}
        for step in plan.steps
    ]


def _skills(plan: Any) -> List[str]:
    """步骤图上的技能名。"""

    return [str(step.get("skill_name") or "") for step in _graph_rows(plan)]


def _inputs(plan: Any, skill: str) -> Dict[str, Any]:
    """指定技能的 inputs。"""

    for step in _graph_rows(plan):
        if step.get("skill_name") == skill:
            return dict(step.get("inputs") or {})
    return {}


def _classify_prompts(fake: FakeLLMProvider) -> List[str]:
    """分类协议的用户提示。拆分提示不含这段开头。"""

    return [item for item in fake.prompts if "Official and system Job ids:" in item]


def _confirmed(state: ConversationState) -> Dict[str, Any]:
    """已确认槽。"""

    task = state.task
    slots = getattr(task, "slots", {}) or {} if task is not None else {}
    return {
        str(name): slot.value
        for name, slot in slots.items()
        if getattr(slot, "confirmed", False) and slot.value not in (None, "")
    }


class TestAi04SplitQuestion(unittest.TestCase):
    """办事子句和附带提问。"""

    def setUp(self) -> None:
        self.registry = build_default_registry()

    def _plan(self, query: str, replies: List[str], **kwargs: Any):
        """用罐头模型跑一轮计划。"""

        fake = FakeLLMProvider(replies=list(replies))
        plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(query, mode="plan", **kwargs)
        return plan, fake

    def test_system_prompt_is_four_sentences(self) -> None:
        """系统提示只有四句说明和例子，用户提示是整句。"""

        print("\n[TestAi04SplitQuestion] 拆分系统提示")
        fake = FakeLLMProvider(replies=[_split_reply("随便一句", "")])
        split = split_task_and_question("随便一句", fake)
        print(" status:", split.status)
        print(" user:", fake.prompts)
        print(" system:", fake.system_prompts[0])
        self.assertEqual(fake.prompts, ["随便一句"])
        system = fake.system_prompts[0]
        for line in _CLAUSE_LINES:
            self.assertIn(line, system)
        for name in _BANNED_NAMES:
            self.assertNotIn(name, system)
        self.assertIn("超额", system)

    def test_cumulative_task_does_not_become_excess_graph(self) -> None:
        """有模型时办事只留累计，提问里的超额不进图。"""

        print("\n[TestAi04SplitQuestion] 累计为主，超额留在提问")
        plan, fake = self._plan(
            _CUM,
            [
                _split_reply(_TASK, _QUESTION),
                _job_reply(),
                "{}",
            ],
        )
        skills = _skills(plan)
        portfolio = _inputs(plan, "qt.ai.hp.portfolio")
        cum = _inputs(plan, "qt.ai.hp.cum_return")
        questions = (plan.assumptions or {}).get("questions")
        print(" job:", plan.planner_trace.get("intent_job"))
        print(" skills:", skills)
        print(" benchmark_output:", portfolio.get("benchmark_output"))
        print(" cum:", cum)
        print(" questions:", questions)
        print(" prompts:", fake.prompts)
        print(" classify:", _classify_prompts(fake))
        classify = "\n".join(_classify_prompts(fake))
        self.assertIn(_TASK, classify)
        self.assertNotIn("超额", classify)
        self.assertNotIn("顺便问", classify)
        self.assertEqual(plan.planner_trace.get("intent_job"), "research.hold_compare")
        self.assertIn("qt.ai.hp.cum_return", skills)
        self.assertNotEqual(portfolio.get("benchmark_output"), "excess_only")
        self.assertNotIn("excess_close", json.dumps(cum, ensure_ascii=False))
        self.assertEqual(questions, [_QUESTION])
        dumped = json.dumps(_graph_rows(plan), ensure_ascii=False, default=str)
        visible = json.dumps([dict(step.inputs) for step in plan.steps], ensure_ascii=False, default=str)
        self.assertNotIn(_QUESTION, dumped)
        self.assertNotIn(_QUESTION, visible)

    def test_overlapping_spans_stay_unmarked_and_leave_classify_reply(self) -> None:
        """办事含着提问时不拆，分类回复留在队列里。"""

        print("\n[TestAi04SplitQuestion] 两段重叠")
        plan, fake = self._plan(
            _CUM,
            [
                _split_reply(_CUM, _QUESTION),
                _job_reply(),
            ],
        )
        print(" job:", plan.planner_trace.get("intent_job"))
        print(" questions:", (plan.assumptions or {}).get("questions"))
        print(" replies:", fake.replies)
        print(" skills:", _skills(plan))
        print(" pending:", _pending_names(plan))
        self.assertEqual(fake.replies, [_job_reply()])
        self.assertEqual(_classify_prompts(fake), [])
        self.assertNotIn("questions", plan.assumptions or {})
        self.assertNotEqual(plan.planner_trace.get("intent_job"), "research.hold_compare")
        self.assertNotEqual(_inputs(plan, "qt.ai.hp.portfolio").get("benchmark_output"), "excess_only")
        self.assertIn("unresolved_intent", _pending_names(plan))

    def test_question_only_does_not_classify(self) -> None:
        """只有提问时不分类，也不送去 Ask。"""

        print("\n[TestAi04SplitQuestion] 只有提问")
        plan, fake = self._plan(
            _WORTH,
            [
                _split_reply("", _WORTH),
                _job_reply(),
            ],
        )
        print(" job:", plan.planner_trace.get("intent_job"))
        print(" pending:", _pending_names(plan))
        print(" replies:", fake.replies)
        print(" prompts:", fake.prompts)
        self.assertEqual(fake.prompts, [_WORTH])
        self.assertEqual(fake.replies, [_job_reply()])
        self.assertEqual(_classify_prompts(fake), [])
        self.assertIn("unresolved_intent", _pending_names(plan))
        self.assertNotEqual(plan.planner_trace.get("intent_job"), "research.hold_compare")
        self.assertNotEqual(plan.planner_trace.get("intent_job"), "route_to_ask")

    def test_prior_question_on_existing_plan_is_not_classified(self) -> None:
        """已有计划上的纯提问不进分类，也不拍 prior_inputs。"""

        print("\n[TestAi04SplitQuestion] 已有计划上的跟上次")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            first = assistant.plan(
                "600519 和 000858 做一条等权组合",
                response_style="raw",
                session_id="s-prior",
            )
            state = assistant.session_store.load("s-prior")
            before = _confirmed(state)
            first_job = str(((first.get("plan") or {}).get("planner_trace") or {}).get("intent_job") or "")
            print(" first job:", first_job, "status:", None if state.task is None else state.task.status)
            print(" slots before:", before)
            fake = FakeLLMProvider(replies=[_split_reply("", _PRIOR), _job_reply()])
            assistant.planner.provider = fake
            second = assistant.plan(_PRIOR, response_style="raw", session_id="s-prior")
            state = assistant.session_store.load("s-prior")
            plan = second.get("plan") or {}
            assumptions = plan.get("assumptions") or {}
            trace = plan.get("planner_trace") or {}
            print(" job:", trace.get("intent_job"))
            print(" questions:", assumptions.get("questions"))
            print(" prompts:", fake.prompts)
            print(" replies:", fake.replies)
            print(" slots after:", _confirmed(state))
            print(" prior_inputs:", getattr(state, "prior_inputs", None))
            self.assertEqual(fake.prompts, [_PRIOR])
            self.assertEqual(fake.replies, [_job_reply()])
            self.assertEqual(_classify_prompts(fake), [])
            self.assertEqual(trace.get("intent_job"), first_job)
            self.assertEqual(assumptions.get("questions"), [_PRIOR])
            self.assertNotIn("上一轮提交的是", json.dumps(second, ensure_ascii=False, default=str))
            self.assertEqual(_confirmed(state), before)
            self.assertFalse(getattr(state, "prior_inputs", None))

    def test_classification_json_is_unmarked(self) -> None:
        """拆分拿到分类 JSON 就停，不再拿整句去分类。"""

        print("\n[TestAi04SplitQuestion] 非法协议")
        plan, fake = self._plan(_CUM, [_job_reply()])
        print(" job:", plan.planner_trace.get("intent_job"))
        print(" rationale:", plan.planner_trace.get("rationale"))
        print(" prompts:", fake.prompts)
        print(" replies:", fake.replies)
        print(" questions:", (plan.assumptions or {}).get("questions"))
        print(" pending:", _pending_names(plan))
        self.assertEqual(fake.prompts, [_CUM])
        self.assertEqual(fake.replies, [])
        self.assertEqual(_classify_prompts(fake), [])
        self.assertNotEqual(plan.planner_trace.get("intent_job"), "research.hold_compare")
        self.assertIn("unresolved_intent", _pending_names(plan))
        self.assertNotIn("questions", plan.assumptions or {})

    def test_revision_question_does_not_enter_patch(self) -> None:
        """有模型的修改句只记提问，累计图和已确认槽保持。"""

        print("\n[TestAi04SplitQuestion] 修改句超额会怎样")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            first = assistant.plan(_READY, response_style="raw", session_id="s-rev")
            plan = first.get("plan") or {}
            skills = [str(step.get("skill_name") or "") for step in (plan.get("steps") or [])]
            pending = [
                str(item.get("name") or "")
                for item in (((plan.get("assumptions") or {}).get("clarification") or {}).get("pending") or [])
                if isinstance(item, dict)
            ]
            accepted = (plan.get("assumptions") or {}).get("accepted_steps") or []
            graph = [str(step.get("skill_name") or "") for step in accepted] or skills
            print(" first skills:", skills)
            print(" first graph:", graph)
            print(" first pending:", pending)
            print(" first job:", (plan.get("planner_trace") or {}).get("intent_job"))
            print(" first visible:", skills)
            self.assertIn("qt.ai.hp.cum_return", graph)
            self.assertEqual(skills, ["qt.ai.system.fallback"])
            self.assertIn("holdings", pending)
            state = assistant.session_store.load("s-rev")
            before = _confirmed(state)
            print(" slots before:", before)
            fake = FakeLLMProvider(replies=[_split_reply("", _EXCESS_Q), _job_reply()])
            assistant.planner.provider = fake
            second = assistant.plan(_EXCESS_Q, response_style="raw", session_id="s-rev")
            state = assistant.session_store.load("s-rev")
            plan = second.get("plan") or {}
            assumptions = dict(plan.get("assumptions") or {})
            questions = assumptions.pop("questions", None)
            portfolio = {}
            cum = {}
            kept_skills = []
            for step in plan.get("steps") or []:
                kept_skills.append(str(step.get("skill_name") or ""))
                if step.get("skill_name") == "qt.ai.hp.portfolio":
                    portfolio = dict(step.get("inputs") or {})
                if step.get("skill_name") == "qt.ai.hp.cum_return":
                    cum = dict(step.get("inputs") or {})
            dumped = json.dumps(
                {
                    "steps": plan.get("steps"),
                    "assumptions": assumptions,
                    "patches": second.get("patches"),
                    "note": second.get("note") or assumptions.get("note"),
                },
                ensure_ascii=False,
                default=str,
            )
            print(" skills:", kept_skills)
            print(" benchmark_output:", portfolio.get("benchmark_output"))
            print(" cum:", cum)
            print(" questions:", questions)
            print(" replies:", fake.replies)
            print(" slots after:", _confirmed(state))
            print(" prior_inputs:", getattr(state, "prior_inputs", None))
            self.assertEqual(fake.replies, [_job_reply()])
            self.assertEqual(_classify_prompts(fake), [])
            self.assertEqual(questions, [_EXCESS_Q])
            self.assertIn("qt.ai.hp.cum_return", kept_skills)
            self.assertNotEqual(portfolio.get("benchmark_output"), "excess_only")
            self.assertNotIn("excess_close", json.dumps(cum, ensure_ascii=False))
            self.assertNotIn(_EXCESS_Q, dumped)
            self.assertEqual(_confirmed(state), before)
            self.assertFalse(getattr(state, "prior_inputs", None))
            holdings = portfolio.get("holdings") or []
            codes = [str(item.get("code") or "") for item in holdings if isinstance(item, dict)]
            print(" codes:", codes, "mode:", portfolio.get("mode"))
            self.assertEqual(codes, [])
            self.assertNotEqual(portfolio.get("mode"), "equal")

    def test_card_resume_and_open_do_not_split(self) -> None:
        """卡片、恢复步骤和 forced open 不调用拆分。"""

        print("\n[TestAi04SplitQuestion] 三个入口不拆")
        state = ConversationState.empty("card-skip")
        state.start_task(query=_READY, job="research.hold_compare")
        state.task.status = "clarifying"
        card_fake = FakeLLMProvider(replies=[_job_reply()])
        card_plan = Planner(self.registry, provider=card_fake, env_facts={}).build_plan(
            "",
            mode="plan",
            session=state,
            skip_classify=True,
            card_text={},
        )
        print(" card job:", card_plan.planner_trace.get("intent_job"))
        print(" card pending:", _pending_names(card_plan))
        print(" card systems:", card_fake.system_prompts)
        self.assertEqual(card_plan.planner_trace.get("intent_job"), "research.hold_compare")
        self.assertNotIn("unresolved_intent", _pending_names(card_plan))
        self.assertNotIn(_CLAUSE_LINES[0], "\n".join(card_fake.system_prompts))

        resume_fake = FakeLLMProvider(replies=[_split_reply("不要拆", "不要问")])
        resume_plan = Planner(self.registry, provider=resume_fake, env_facts={}).build_plan(
            "恢复原步骤",
            mode="plan",
            resume_steps=[
                {
                    "skill_name": "qt.ai.data.kline",
                    "inputs": {"shares": "000001.SZ"},
                    "depends_on": [],
                }
            ],
        )
        print(" resume job:", resume_plan.planner_trace.get("intent_job"))
        print(" resume systems:", resume_fake.system_prompts)
        self.assertNotIn(_CLAUSE_LINES[0], "\n".join(resume_fake.system_prompts))
        self.assertEqual(resume_plan.planner_trace.get("intent_job"), "open")

        opened = [
            {
                "skill_name": "qt.ai.data.kline",
                "inputs": {"shares": "000001.SZ"},
                "depends_on": [],
            }
        ]
        open_fake = FakeLLMProvider(replies=[json.dumps({"steps": opened}, ensure_ascii=False)])
        open_plan = Planner(self.registry, provider=open_fake, env_facts={}).build_plan(
            "000001.SZ 看超额",
            mode="plan",
            forced_job="open",
        )
        print(" open job:", open_plan.planner_trace.get("intent_job"))
        print(" open systems:", open_fake.system_prompts)
        self.assertNotIn(_CLAUSE_LINES[0], "\n".join(open_fake.system_prompts))
        self.assertEqual(open_plan.planner_trace.get("intent_job"), "open")

    def test_without_model_whole_sentence_is_task(self) -> None:
        """无模型不认标记词，整句是办事，提问为空。"""

        print("\n[TestAi04SplitQuestion] 无模型整句")
        samples = (
            _CUM,
            _PRIOR,
            "超额会怎样。",
            "主要做累计、顺便问",
        )
        for text in samples:
            split = split_task_and_question(text, None)
            print(" text:", text, "task:", split.task, "question:", split.question, "status:", split.status)
            self.assertEqual(split.task, text)
            self.assertEqual(split.question, "")
            self.assertEqual(split.status, "marked")

    def test_without_model_high_risk_sentence_stays_constitutional(self) -> None:
        """无模型不拆，两个高风险办事仍由宪法拦住。"""

        print("\n[TestAi04SplitQuestion] 无模型高风险")
        plan = Planner(self.registry, env_facts={}).build_plan("下载并回测，顺便问哪个好", mode="plan")
        print(" job:", plan.planner_trace.get("intent_job"))
        print(" rationale:", plan.planner_trace.get("rationale"))
        print(" skills:", _skills(plan))
        print(" questions:", (plan.assumptions or {}).get("questions"))
        self.assertEqual(plan.planner_trace.get("rationale"), "multi_high_risk_intent")
        self.assertEqual(_skills(plan), ["qt.ai.system.fallback"])
        self.assertNotIn("questions", plan.assumptions or {})


if __name__ == "__main__":
    unittest.main()
