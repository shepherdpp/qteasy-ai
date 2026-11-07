# coding=utf-8
# ======================================
# File: test_ai_04_a6_slots_from_graph.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-03
# Desc:
# 0.4 A6：槽从步骤图投影。意图与填槽分开，
# 澄清由系统出题，模型只润色卡片文字。
# ======================================

import json
import unittest

from qteasy_ai.app import build_default_registry
from qteasy_ai.human_card import clarification_needs_answer, project_human_cards
from qteasy_ai.plan_markdown import tool_plan_to_markdown
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.session import ConversationState
from qteasy_ai.slot_decl import interpret_declared_slots
from qteasy_ai.slot_graph import (
    apply_polish_text,
    dtype_tokens,
    parse_card_answers,
    strategy_id_options,
    table_option_ids,
)


def _job(job: str) -> str:
    """分类罐头。"""

    return json.dumps({"job": job}, ensure_ascii=False)


def _pending(plan):
    """澄清卡上的 pending。"""

    blob = (plan.assumptions or {}).get("clarification") or {}
    return [item for item in (blob.get("pending") or []) if isinstance(item, dict)]


def _pending_names(plan):
    """pending 槽名。"""

    return [str(item.get("name") or "") for item in _pending(plan)]


class TestAi04A6SlotsFromGraph(unittest.TestCase):
    """槽从步骤图来：投影、填槽、澄清与未解。"""

    def setUp(self) -> None:
        self.registry = build_default_registry()

    def test_intent_and_fill_are_separate_calls(self) -> None:
        """有模型时意图与填槽分两次；润色不能改槽名或选项。"""

        print("\n[TestAi04A6] 意图与填槽分开，润色失败则保留英文")
        screen = "筛股 20d 跌 10% 银行业"
        polish = {
            "confirm_prompt": "请确认这些字段。",
            "pending": [
                {
                    "name": "extra_slot",
                    "hint": "不该出现",
                    "options": [{"id": "drawdown", "label": "回撤"}, {"id": "flat", "label": "持平"}],
                }
            ],
        }
        fake = FakeLLMProvider(
            replies=[
                _job("research.screen"),
                json.dumps(
                    {
                        "industry": "银行业",
                        "lookback_days": 20,
                        "threshold": 0.1,
                        "metric": "drawdown",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(polish, ensure_ascii=False),
            ]
        )
        plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(screen, mode="plan")
        fill_prompts = [text for text in fake.prompts if text.startswith("Fill only these empty slots.")]
        slot_lines = [
            line.split(":", 1)[1].strip()
            for text in fill_prompts
            for line in text.splitlines()
            if line.startswith("slot:")
        ]
        print(" jobs:", plan.planner_trace.get("intent_job"))
        print(" fill prompts:", len(fill_prompts))
        print(" slot lines:", slot_lines)
        print(" skills:", [step.skill_name for step in plan.steps])
        self.assertTrue(fake.prompts[0].startswith("Official and system Job ids:"))
        self.assertEqual(len(fill_prompts), 1)
        self.assertIn("industry", slot_lines)
        self.assertIn("threshold", slot_lines)
        self.assertIn("metric", slot_lines)
        self.assertIn("lookback_days", slot_lines)
        self.assertNotIn("supported_skill", slot_lines)
        self.assertNotIn("fast", slot_lines)
        self.assertNotIn("slow", slot_lines)
        self.assertEqual(plan.steps[0].inputs.get("industry"), "银行业")
        self.assertEqual(plan.steps[1].inputs.get("lookback_days"), 20)
        self.assertEqual(plan.steps[1].inputs.get("threshold"), 0.1)
        self.assertEqual(plan.steps[1].inputs.get("metric"), "drawdown")

        bare = "筛股 20d 10% 银行业"
        good_polish = {
            "confirm_prompt": "请选择涨跌方向。",
            "pending": [
                {
                    "name": "metric",
                    "label": "方向",
                    "hint": "选择回撤或上涨。",
                    "options": [
                        {"id": "drawdown", "label": "回撤"},
                        {"id": "gain", "label": "上涨"},
                    ],
                }
            ],
        }
        bad_polish = {
            "confirm_prompt": "请选择涨跌方向。",
            "pending": [
                {
                    "name": "metric",
                    "hint": "选择回撤或上涨。",
                    "options": [
                        {"id": "drawdown", "label": "回撤"},
                        {"id": "gain", "label": "上涨"},
                        {"id": "flat", "label": "持平"},
                    ],
                }
            ],
        }
        chinese = FakeLLMProvider(
            replies=[
                _job("research.screen"),
                json.dumps({"industry": "银行业", "lookback_days": 20, "threshold": 0.1}, ensure_ascii=False),
                json.dumps(good_polish, ensure_ascii=False),
            ]
        )
        chinese_plan = Planner(self.registry, provider=chinese, env_facts={}).build_plan(bare, mode="plan")
        metric = _pending(chinese_plan)[0]
        labels = [str(item.get("label") or "") for item in metric.get("options") or []]
        print(" polished hint:", metric.get("hint"), "labels:", labels)
        self.assertEqual([str(item.get("id")) for item in metric.get("options") or []], ["drawdown", "gain"])
        self.assertIn("回撤", labels)
        self.assertIn("选择", str(metric.get("hint") or ""))

        english_blob = {
            "confirm_prompt": "Choose drawdown or gain.",
            "pending": [
                {
                    "name": "metric",
                    "label": "Metric",
                    "hint": "Choose drawdown or gain.",
                    "error": "",
                    "options": [
                        {"id": "drawdown", "label": "drawdown"},
                        {"id": "gain", "label": "gain"},
                    ],
                }
            ],
        }
        kept = apply_polish_text(english_blob, json.dumps(bad_polish, ensure_ascii=False), bare)
        print(" rejected polish prompt:", kept.get("confirm_prompt"))
        self.assertEqual(kept.get("confirm_prompt"), "Choose drawdown or gain.")
        self.assertEqual(len(kept["pending"][0]["options"]), 2)

        none_plan = Planner(self.registry, env_facts={}).build_plan(screen, mode="plan")
        print(" no provider skills:", [step.skill_name for step in none_plan.steps])
        self.assertEqual(none_plan.steps[1].inputs.get("metric"), "drawdown")
        self.assertEqual(none_plan.steps[0].inputs.get("industry"), "银行业")

    def test_clicked_option_conflict_keeps_other_slots(self) -> None:
        """点选 id 被改成另一个值时，这一格不写下，其余格留下。"""

        print("\n[TestAi04A6] 点选冲突只拒本格")
        pending = [
            {
                "name": "metric",
                "type": "string",
                "enum": ["drawdown", "gain"],
                "enum_strict": True,
                "options": [
                    {"id": "drawdown", "label": "Drawdown"},
                    {"id": "gain", "label": "Gain"},
                ],
            },
            {"name": "industry", "type": "string"},
        ]
        fake = FakeLLMProvider(
            replies=[json.dumps({"metric": "gain", "industry": "银行业"}, ensure_ascii=False)]
        )
        accepted, errors = parse_card_answers(
            pending,
            {"metric": "drawdown", "industry": "银行业"},
            provider=fake,
        )
        print(" accepted:", accepted)
        print(" errors:", errors)
        self.assertEqual(accepted.get("industry"), "银行业")
        self.assertNotIn("metric", accepted)
        self.assertIn("changed", errors.get("metric", ""))
        self.assertIn("drawdown", errors.get("metric", ""))

    def test_screen_heuristic_and_followup(self) -> None:
        """无模型筛股：20 日、0.1、银行业、方向；裸百分数只问 metric。"""

        print("\n[TestAi04A6] 无模型筛股与行业补答")
        planner = Planner(self.registry, env_facts={})
        phrase = "筛股 20 days 跌 10% 银行业"
        plan = planner.build_plan(phrase, mode="plan")
        names = [step.skill_name for step in plan.steps]
        print(" phrase skills:", names)
        print(" universe:", plan.steps[0].inputs)
        print(" predicate:", plan.steps[1].inputs)
        self.assertEqual(plan.execution_mode, "dry_run")
        self.assertEqual(
            names,
            [
                "qt.ai.research.universe_filter",
                "qt.ai.research.price_predicate",
                "qt.ai.research.project_universe",
            ],
        )
        self.assertEqual(plan.steps[0].inputs.get("industry"), "银行业")
        self.assertEqual(plan.steps[1].inputs.get("lookback_days"), 20)
        self.assertEqual(plan.steps[1].inputs.get("threshold"), 0.1)
        self.assertEqual(plan.steps[1].inputs.get("metric"), "drawdown")
        self.assertEqual(plan.steps[2].inputs.get("max_hits"), 50)
        self.assertNotIn("clarification", plan.assumptions)

        gain = planner.build_plan("筛股 20日 涨 10% 银行业", mode="plan")
        print(" gain metric:", gain.steps[1].inputs.get("metric"), "days:", gain.steps[1].inputs.get("lookback_days"))
        self.assertEqual(gain.steps[1].inputs.get("metric"), "gain")
        self.assertEqual(gain.steps[1].inputs.get("lookback_days"), 20)

        bare = planner.build_plan("筛股 20d 10% 银行业", mode="plan")
        print(" bare pending:", _pending(bare))
        self.assertEqual(_pending_names(bare), ["metric"])
        self.assertEqual(
            [item.get("id") for item in _pending(bare)[0].get("options") or []],
            ["drawdown", "gain"],
        )
        self.assertNotIn("lookback_days", _pending_names(bare))
        self.assertNotIn("industry", _pending_names(bare))
        self.assertNotIn("threshold", _pending_names(bare))

        missing = planner.build_plan("筛股 20d 跌 10%", mode="plan")
        print(" missing industry pending:", _pending(missing))
        self.assertEqual(_pending_names(missing), ["industry"])
        self.assertIn("industry", str(_pending(missing)[0].get("hint") or "").lower())

        state = ConversationState.empty("a6-screen")
        state.start_task(query="筛股 20d 跌 10%", job="research.screen")
        state.set_slot("industry", "银行业", source="user", confirmed=True)
        followed = planner.build_plan("银行业", session=state, skip_classify=True)
        print(" followed skills:", [step.skill_name for step in followed.steps])
        print(" followed industry:", followed.steps[0].inputs.get("industry"))
        print(" followed pending:", _pending_names(followed))
        self.assertEqual(followed.steps[0].inputs.get("industry"), "银行业")
        self.assertNotIn("industry", _pending_names(followed))
        self.assertIn("qt.ai.research.price_predicate", [step.skill_name for step in followed.steps])

        bad = planner.build_plan("筛股 回看 abc 跌 10% 银行业", mode="plan")
        print(" bad lookback pending:", _pending(bad))
        lookback = [item for item in _pending(bad) if item.get("name") == "lookback_days"]
        self.assertTrue(lookback)
        self.assertTrue(str(lookback[0].get("error") or ""))
        self.assertNotIn("abc", [step.inputs.get("lookback_days") for step in bad.steps])
        rejected, reject_errors = parse_card_answers(
            [{"name": "lookback_days", "type": "integer"}],
            {"lookback_days": "abc"},
        )
        print(" card reject:", rejected, reject_errors)
        self.assertNotIn("lookback_days", rejected)
        self.assertIn("lookback_days", reject_errors)

    def test_dtype_tokens_do_not_split_industry(self) -> None:
        """industry 里的 name 子串不是第二个词；对不上的 name 要被点名。"""

        print("\n[TestAi04A6] 数据类型整词")
        tokens = dtype_tokens("get_static_data industry for 000001.SZ")
        both = dtype_tokens("get_static_data industry and name for 000001.SZ")
        print(" industry tokens:", tokens)
        print(" both tokens:", both)
        self.assertEqual(tokens, ["industry"])
        self.assertEqual(both, ["industry", "name"])

        planner = Planner(self.registry, env_facts={})
        plan = planner.build_plan("get_static_data industry and name for 000001.SZ", mode="plan")
        print(" skill:", plan.steps[0].skill_name)
        print(" pending:", _pending(plan))
        self.assertNotEqual(plan.steps[0].skill_name, "qt.ai.data.static")
        blob = json.dumps(plan.assumptions.get("clarification") or {}, ensure_ascii=False)
        self.assertIn("name", blob)
        self.assertIn("does not match a single data type", blob)
        self.assertNotEqual(plan.steps[0].inputs.get("names"), "industry")

        fake = FakeLLMProvider(
            replies=[
                _job("data.read"),
                json.dumps({"names": "industry,stock_name"}, ensure_ascii=False),
            ]
        )
        canned = Planner(self.registry, provider=fake, env_facts={}).build_plan(
            "please fetch industry and name for 000001.SZ",
            mode="plan",
        )
        print(" canned skill:", canned.steps[0].skill_name, canned.steps[0].inputs)
        self.assertEqual(canned.steps[0].skill_name, "qt.ai.data.static")
        self.assertEqual(canned.steps[0].inputs.get("names"), "industry,stock_name")
        self.assertEqual(canned.steps[0].inputs.get("shares"), "000001.SZ")

    def test_unresolved_cards_have_no_supported_skill(self) -> None:
        """对不上的话给出恢复卡；非法 open 仍没有待填槽，也没有 supported_skill。"""

        print("\n[TestAi04A6] 意图未解恢复卡与非法 open")
        planner = Planner(self.registry, env_facts={})
        zh = "取日线、算收益、出一页图"
        for query in ("please fetch …", "xyzzy unmatched formula 12345", zh):
            plan = planner.build_plan(query, mode="plan")
            row = _pending(plan)[0]
            option_ids = [str(item.get("id") or "") for item in (row.get("options") or [])]
            prompt = str((plan.assumptions.get("clarification") or {}).get("confirm_prompt") or "")
            print(" query:", query)
            print(" missing:", plan.steps[0].inputs.get("missing_info"))
            print(" pending:", _pending_names(plan), option_ids)
            print(" prompt:", prompt)
            self.assertEqual(plan.steps[0].skill_name, "qt.ai.system.fallback")
            self.assertNotEqual(plan.steps[0].inputs.get("missing_info"), "supported_skill")
            self.assertNotIn("supported_skill", _pending_names(plan))
            self.assertEqual(_pending_names(plan), ["unresolved_intent"])
            self.assertEqual(option_ids, ["compose_open", "abandon"])
            self.assertNotIn("supported_skill", prompt)
            if query == zh:
                self.assertEqual(
                    prompt,
                    "您的需求无法跟现成的操作模版匹配（job），是否需要我创建一份开放计划？",
                )
                self.assertEqual(row["options"][0]["label"], "给出开放计划")
                self.assertEqual(row["options"][1]["label"], "放弃")
                self.assertEqual((row.get("open") or {}).get("label"), "重写需求")
                self.assertNotIn("open_label", row)
            else:
                self.assertEqual(
                    prompt,
                    "This request does not match a built-in operation template (job). Create an open plan?",
                )
                self.assertEqual(row["options"][0]["label"], "Create an open plan")
                self.assertEqual(row["options"][1]["label"], "Abandon")
                self.assertEqual((row.get("open") or {}).get("label"), "Rewrite the request")
                self.assertNotIn("open_label", row)

        too_many = [
            {"skill_name": "qt.ai.data.kline", "inputs": {"shares": "000300.SH"}},
            {"skill_name": "qt.ai.hp.returns", "inputs": {}},
            {"skill_name": "qt.ai.hp.volatility", "inputs": {}},
            {"skill_name": "qt.ai.hp.plot", "inputs": {"page": 1}},
        ]
        fake = FakeLLMProvider(replies=[_job("open"), json.dumps({"steps": too_many})])
        rejected = Planner(self.registry, provider=fake, env_facts={}).build_plan(
            "取日线、算收益、出一页图",
            mode="plan",
        )
        print(" open reason:", rejected.steps[0].inputs.get("reason"))
        print(" open pending:", _pending_names(rejected))
        self.assertEqual(rejected.steps[0].inputs.get("reason"), "open_too_many_steps")
        self.assertEqual(_pending_names(rejected), [])
        self.assertFalse(clarification_needs_answer(rejected.assumptions.get("clarification")))
        self.assertNotEqual(rejected.steps[0].inputs.get("missing_info"), "supported_skill")
        self.assertIn("open_too_many_steps", str((rejected.assumptions.get("clarification") or {}).get("confirm_prompt")))
        rejected_cards = project_human_cards(
            {
                "plan": {
                    "user_query": "取日线、算收益、出一页图",
                    "assumptions": {"clarification": rejected.assumptions.get("clarification")},
                    "steps": [],
                },
                "execution": {"status": "dry_run", "steps": []},
            },
            requested_mode="plan",
            query="取日线、算收益、出一页图",
            include_user_text=False,
        )
        rejected_kinds = [item.get("kind") for item in rejected_cards]
        print(" open cards:", rejected_kinds)
        self.assertIn("error", rejected_kinds)
        self.assertNotIn("clarify", rejected_kinds)

        steps = [
            {"skill_name": "qt.ai.data.kline", "inputs": {"shares": "000300.SH"}},
            {"skill_name": "qt.ai.hp.returns", "inputs": {}, "depends_on": ["step_1"]},
            {"skill_name": "qt.ai.hp.plot", "inputs": {"page": 1}, "depends_on": ["step_2"]},
        ]
        opened = FakeLLMProvider(replies=[_job("open"), json.dumps({"steps": steps})])
        dry = Planner(self.registry, provider=opened, env_facts={}).build_plan(
            "取日线、算收益、出一页图",
            mode="plan",
        )
        print(" open skills:", [step.skill_name for step in dry.steps], dry.execution_mode)
        print(" kline pending:", _pending_names(dry))
        self.assertEqual(dry.execution_mode, "dry_run")
        self.assertLessEqual(len(dry.steps), 3)
        self.assertEqual(
            [step.skill_name for step in dry.steps],
            ["qt.ai.data.kline", "qt.ai.hp.returns", "qt.ai.hp.plot"],
        )
        self.assertNotIn("start", _pending_names(dry))
        self.assertNotIn("end", _pending_names(dry))

    def test_open_history_contract_normalizes_and_asks(self) -> None:
        """历史图上的非法取值要收成契约值；缺窗口和列名时追问，边要接上。"""

        print("\n[TestAi04A6] 开放历史图按契约验收")
        rough = [
            {
                "skill_name": "qt.ai.data.history",
                "inputs": {
                    "freq": "D",
                    "shares": "000300.SH",
                    "htype_names": "['日线']",
                    "asset_type": "指数",
                },
            },
            {"skill_name": "qt.ai.hp.returns", "inputs": {"method": "pct_change"}},
            {"skill_name": "qt.ai.hp.plot", "inputs": {"shares": "000300.SH"}},
        ]
        asked = "取 000300.SH 日线，算收益，再出一页图"
        fake = FakeLLMProvider(replies=[_job("open"), json.dumps({"steps": rough}, ensure_ascii=False)])
        plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(asked, mode="plan")
        print(" pending:", _pending_names(plan))
        print(" skill:", plan.steps[0].skill_name)
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(_pending_names(plan), ["htype_names", "start", "end"])
        accepted = {
            row["step_id"]: row
            for row in ((plan.assumptions or {}).get("accepted_steps") or [])
        }
        history = (accepted.get("step_1") or {}).get("inputs") or {}
        print(" history:", history)
        print(" depends:", accepted.get("step_2", {}).get("depends_on"), accepted.get("step_3", {}).get("depends_on"))
        self.assertEqual(history.get("freq"), "d")
        self.assertEqual(history.get("asset_type"), "IDX")
        self.assertNotIn("htype_names", history)
        self.assertNotIn("日线", json.dumps(history, ensure_ascii=False))
        self.assertNotIn("指数", json.dumps(history, ensure_ascii=False))
        self.assertEqual((accepted.get("step_2") or {}).get("depends_on"), ["step_1"])
        self.assertEqual((accepted.get("step_3") or {}).get("depends_on"), ["step_2"])
        digest = [text for text in fake.prompts if text.startswith("Allowed skills:")]
        print(" digest lines:", len(digest))
        self.assertTrue(digest)
        self.assertIn("Skill contracts:", digest[0])
        self.assertIn("any_of=start|end", digest[0])
        self.assertIn("needs_upstream", digest[0])

        ready = [
            {
                "skill_name": "qt.ai.data.history",
                "inputs": {
                    "freq": "D",
                    "shares": "000300.SH",
                    "htype_names": "close",
                    "asset_type": "指数",
                    "start": "20240101",
                },
            },
            {"skill_name": "qt.ai.hp.returns", "inputs": {"method": "pct_change"}},
            {"skill_name": "qt.ai.hp.plot", "inputs": {"shares": "000300.SH"}},
        ]
        opened = FakeLLMProvider(replies=[_job("open"), json.dumps({"steps": ready}, ensure_ascii=False)])
        dry = Planner(self.registry, provider=opened, env_facts={}).build_plan(
            "取 000300.SH 从 20240101 起的日线，算收益，再出一页图",
            mode="plan",
        )
        print(" dry skills:", [step.skill_name for step in dry.steps], dry.execution_mode)
        print(" dry inputs:", dry.steps[0].inputs)
        print(" dry depends:", [list(step.depends_on) for step in dry.steps])
        self.assertEqual(dry.execution_mode, "dry_run")
        self.assertEqual(
            [step.skill_name for step in dry.steps],
            ["qt.ai.data.history", "qt.ai.hp.returns", "qt.ai.hp.plot"],
        )
        self.assertEqual(dry.steps[0].inputs.get("freq"), "d")
        self.assertEqual(dry.steps[0].inputs.get("asset_type"), "IDX")
        self.assertEqual(dry.steps[0].inputs.get("htype_names"), "close")
        self.assertEqual(dry.steps[0].inputs.get("start"), "20240101")
        self.assertEqual(list(dry.steps[1].depends_on), ["step_1"])
        self.assertEqual(list(dry.steps[2].depends_on), ["step_2"])
        self.assertNotIn("start", _pending_names(dry))

    def test_refill_strategy_options_factor_ic_and_fast_slow(self) -> None:
        """下载问 start/end；策略选项按字母序；因子 IC 与 fast/slow 不动。"""

        print("\n[TestAi04A6] 日期槽、策略选项、因子 IC、fast/slow")
        refill = Planner(self.registry, env_facts={}).build_plan(
            "download A-share daily data to local datasource",
            mode="plan",
        )
        print(" refill pending:", _pending(refill))
        print(" refill missing:", refill.steps[0].inputs.get("missing_info"))
        self.assertEqual(_pending_names(refill), ["start", "end"])
        self.assertNotEqual(refill.steps[0].inputs.get("missing_info"), "date_range")
        constraint = str(_pending(refill)[0].get("constraint") or "")
        self.assertIn("Unbounded full-history download is not allowed", constraint)

        meta = Planner(self.registry, env_facts={}).build_plan("列出策略参数", mode="plan")
        options = [str(item.get("id") or "") for item in (_pending(meta)[0].get("options") or [])]
        print(" strategy options:", options)
        self.assertEqual(_pending_names(meta), ["strategy_id"])
        self.assertEqual(options, strategy_id_options())
        self.assertEqual(options, sorted(options))
        self.assertNotEqual(options, ["macd", "dma", "bband", "rsi", "kdj"])

        tables = table_option_ids()
        print(" table options:", tables)
        self.assertLessEqual(len(tables), 5)
        from qteasy.datatables import TABLE_MASTERS

        self.assertEqual(tables, [str(key) for key in list(TABLE_MASTERS)[:5]])

        factor = Planner(self.registry, env_facts={}).build_plan("factor ic", mode="plan")
        print(" factor pending:", _pending_names(factor))
        self.assertEqual(
            _pending_names(factor),
            ["shares", "start", "end", "factor_htype", "return_htype"],
        )

        builder = Planner(self.registry, env_facts={}).build_plan("写一个双均线金叉策略", mode="plan")
        print(" builder pending:", _pending_names(builder), builder.steps[0].inputs.get("reason"))
        self.assertEqual(builder.steps[0].inputs.get("reason"), "ma_periods_missing")
        self.assertEqual(_pending_names(builder), ["fast", "slow"])
        self.assertIn("fast", str(builder.steps[0].inputs.get("missing_info") or ""))

        integer_bad = interpret_declared_slots(
            [{"name": "lookback_days", "value_kind": "integer", "cardinality": "one", "label": "Lookback"}],
            {"lookback_days": "abc"},
            is_history_column=lambda _name: False,
        )
        integer_ok = interpret_declared_slots(
            [{"name": "lookback_days", "value_kind": "integer", "cardinality": "one", "label": "Lookback"}],
            {"lookback_days": "20"},
            is_history_column=lambda _name: False,
        )
        unknown = interpret_declared_slots(
            [{"name": "mystery", "value_kind": "mystery", "cardinality": "one", "label": "Mystery"}],
            {"mystery": "abc"},
            is_history_column=lambda _name: False,
        )
        print(" integer bad:", integer_bad["pending"])
        print(" integer ok:", integer_ok["values"])
        print(" unknown:", unknown["pending"])
        self.assertTrue(integer_bad["pending"])
        self.assertEqual(integer_ok["values"].get("lookback_days"), "20")
        self.assertTrue(unknown["pending"])
        self.assertIn("cannot be accepted", str(unknown["pending"][0].get("error") or ""))

        freq = self.registry.get_metadata("qt.ai.data.kline").inputs_schema["freq"]
        metric = self.registry.get_metadata("qt.ai.research.price_predicate").inputs_schema["metric"]
        print(" freq enum:", freq.get("enum"), freq.get("enum_strict"))
        print(" metric enum:", metric.get("enum"), metric.get("enum_strict"))
        self.assertEqual(freq.get("enum"), ["d", "w", "m"])
        self.assertFalse(freq.get("enum_strict"))
        self.assertEqual(metric.get("enum"), ["drawdown", "gain"])
        self.assertTrue(metric.get("enum_strict"))

    def test_depends_resolve_to_earlier_step_id(self) -> None:
        """依赖写成唯一的上游技能名时收成步骤号；对不上则整单拒绝。"""

        print("\n[TestAi04A6] 依赖收成更早的步骤号")
        linked = [
            {"skill_name": "qt.ai.data.kline", "inputs": {"shares": "000300.SH"}},
            {"skill_name": "qt.ai.hp.returns", "inputs": {}, "depends_on": ["qt.ai.data.kline"]},
        ]
        fake = FakeLLMProvider(replies=[_job("open"), json.dumps({"steps": linked})])
        plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(
            "取 000300.SH 日线再算收益",
            mode="plan",
        )
        print(" skills:", [step.skill_name for step in plan.steps])
        print(" depends:", [list(step.depends_on) for step in plan.steps])
        print(" mode:", plan.execution_mode)
        self.assertEqual(plan.execution_mode, "dry_run")
        self.assertEqual(
            [step.skill_name for step in plan.steps],
            ["qt.ai.data.kline", "qt.ai.hp.returns"],
        )
        self.assertEqual(list(plan.steps[0].depends_on), [])
        self.assertEqual(list(plan.steps[1].depends_on), ["step_1"])
        md = tool_plan_to_markdown(plan)
        print(" edge:", "step_1 --> step_2" in md)
        self.assertIn("step_1 --> step_2", md)
        open_systems = [text for text in fake.system_prompts if "depends_on" in text]
        print(" open system mentions step_1:", any("step_1" in text for text in open_systems))
        self.assertTrue(open_systems)
        self.assertIn("step_1", open_systems[0])
        self.assertIn("step_id", open_systems[0])

        ambiguous = [
            {"skill_name": "qt.ai.data.kline", "inputs": {"shares": "000300.SH"}},
            {"skill_name": "qt.ai.data.kline", "inputs": {"shares": "000001.SZ"}},
            {"skill_name": "qt.ai.hp.returns", "inputs": {}, "depends_on": ["qt.ai.data.kline"]},
        ]
        unknown = [
            {"skill_name": "qt.ai.data.kline", "inputs": {"shares": "000300.SH"}},
            {"skill_name": "qt.ai.hp.returns", "inputs": {}, "depends_on": ["step_9"]},
        ]
        forward = [
            {
                "skill_name": "qt.ai.data.kline",
                "inputs": {"shares": "000300.SH"},
                "depends_on": ["step_2"],
            },
            {"skill_name": "qt.ai.hp.returns", "inputs": {}},
        ]
        for label, steps in (("ambiguous", ambiguous), ("unknown", unknown), ("forward", forward)):
            opened = FakeLLMProvider(replies=[_job("open"), json.dumps({"steps": steps})])
            rejected = Planner(self.registry, provider=opened, env_facts={}).build_plan(
                "取 000300.SH 日线再算收益",
                mode="plan",
            )
            reason = rejected.steps[0].inputs.get("reason")
            print(" ", label, rejected.steps[0].skill_name, reason, _pending_names(rejected))
            self.assertEqual(rejected.steps[0].skill_name, "qt.ai.system.fallback")
            self.assertEqual(reason, "unresolved_depends")
            self.assertEqual(_pending_names(rejected), [])
            self.assertFalse(clarification_needs_answer((rejected.assumptions or {}).get("clarification")))
            depend_cards = project_human_cards(
                {
                    "plan": {
                        "user_query": "取 000300.SH 日线再算收益",
                        "assumptions": {"clarification": (rejected.assumptions or {}).get("clarification")},
                        "steps": [],
                    },
                    "execution": {"status": "dry_run", "steps": []},
                },
                requested_mode="plan",
                query="取 000300.SH 日线再算收益",
                include_user_text=False,
            )
            depend_kinds = [item.get("kind") for item in depend_cards]
            print(" ", label, "cards:", depend_kinds)
            self.assertIn("error", depend_kinds)
            self.assertNotIn("clarify", depend_kinds)

        empty = [
            {"skill_name": "qt.ai.data.kline", "inputs": {"shares": "000300.SH"}},
            {"skill_name": "qt.ai.hp.returns", "inputs": {}},
        ]
        bound = FakeLLMProvider(replies=[_job("open"), json.dumps({"steps": empty})])
        dry = Planner(self.registry, provider=bound, env_facts={}).build_plan(
            "取 000300.SH 日线再算收益",
            mode="plan",
        )
        print(" empty depends:", [list(step.depends_on) for step in dry.steps], _pending_names(dry))
        self.assertEqual(dry.execution_mode, "dry_run")
        self.assertEqual(list(dry.steps[1].depends_on), ["step_1"])
        self.assertNotIn("start", _pending_names(dry))
        self.assertNotIn("end", _pending_names(dry))

    def test_date_rows_ask_one_field_with_format(self) -> None:
        """start 与 end 各有题干、格式和例子；组约束不写进 hint。"""

        print("\n[TestAi04A6] 日期格各自发问")
        rough = [
            {
                "skill_name": "qt.ai.data.history",
                "inputs": {
                    "freq": "d",
                    "shares": "000300.SH",
                    "htype_names": "close",
                    "asset_type": "IDX",
                },
            },
            {"skill_name": "qt.ai.hp.returns", "inputs": {}},
        ]
        fake = FakeLLMProvider(replies=[_job("open"), json.dumps({"steps": rough})])
        asked = Planner(self.registry, provider=fake, env_facts={}).build_plan(
            "取 000300.SH 的 close，算收益",
            mode="plan",
        )
        rows = {str(item.get("name") or ""): item for item in _pending(asked)}
        print(" history rows:", {name: {key: rows[name].get(key) for key in ("label", "hint", "format", "example", "constraint")} for name in rows})
        self.assertEqual(list(rows), ["start", "end"])
        self._assert_distinct_date_rows(rows, "rows alone does not select a history window.")

        refill = Planner(self.registry, env_facts={}).build_plan(
            "download A-share daily data to local datasource",
            mode="plan",
        )
        refill_rows = {str(item.get("name") or ""): item for item in _pending(refill)}
        print(
            " refill rows:",
            {name: {key: refill_rows[name].get(key) for key in ("label", "hint", "format", "example", "constraint")} for name in ("start", "end")},
        )
        self.assertEqual([str(item.get("name") or "") for item in _pending(refill)], ["start", "end"])
        self._assert_distinct_date_rows(refill_rows, "Unbounded full-history download is not allowed.")

    def _assert_distinct_date_rows(self, rows, constraint_text: str) -> None:
        """两格题干、hint、例子不同，格式相同，组约束只在 constraint。"""

        start = rows["start"]
        end = rows["end"]
        print(" start:", start.get("label"), start.get("hint"), start.get("example"))
        print(" end:", end.get("label"), end.get("hint"), end.get("example"))
        self.assertNotEqual(start.get("label"), end.get("label"))
        self.assertNotEqual(start.get("hint"), end.get("hint"))
        self.assertNotEqual(start.get("example"), end.get("example"))
        self.assertEqual(start.get("format"), "YYYYMMDD")
        self.assertEqual(end.get("format"), "YYYYMMDD")
        self.assertTrue(str(start.get("example") or ""))
        self.assertTrue(str(end.get("example") or ""))
        self.assertIn(constraint_text, str(start.get("constraint") or ""))
        self.assertIn(constraint_text, str(end.get("constraint") or ""))
        self.assertNotIn(constraint_text, str(start.get("hint") or ""))
        self.assertNotIn(constraint_text, str(end.get("hint") or ""))


if __name__ == "__main__":
    unittest.main()
