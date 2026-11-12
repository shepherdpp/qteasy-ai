# coding=utf-8
# ======================================
# File: test_ai_04_commit_elements.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-11
# Desc:
# 元素合同：项列表、按项澄清、投影前不预写，以及调用前才拼字符串。
# ======================================

import json
import unittest
from typing import Any, Dict, List

from qteasy_ai.app import build_default_registry
from qteasy_ai.intents import IntentDecision
from qteasy_ai.intents.recipes import compose_recipe
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.session import ConversationState
from qteasy_ai.skills.data_kline import build_data_kline_skill
from qteasy_ai.skills.data_refill import build_data_refill_skill
from qteasy_ai.slot_graph import (
    _item_pending_rows,
    apply_ordered_answers,
    apply_polish_text,
    bind_clarification_text,
)

_QUERY = "帮我用贵州茅台、格力电器、工商银行和招商银行做一个等权持仓组合，看过去3年的持仓收益率，并跟沪深300指数做一个对比。"
_PROTOCOL = {
    "holdings": [
        {"mention": "贵州茅台", "code": "600519.SH"},
        {"mention": "格力电器", "code": "000651.SZ"},
        {"mention": "工商银行", "code": "601398.SH"},
        {"mention": "招商银行", "code": "600036.SH"},
    ],
    "benchmark": {"mention": "沪深300指数", "code": "000300.SH"},
    "weights": [0.25, 0.25, 0.25, 0.25],
    "mode": "weighted",
}
_PREWRITE_KEYS = ("shares", "symbols", "asset_pool", "weights", "benchmark", "asset_type")


def _planner(replies: List[str] = None) -> Planner:
    """假模型或无模型的规划器。"""

    provider = FakeLLMProvider(replies=list(replies or [])) if replies is not None else None
    return Planner(build_default_registry(), provider=provider, env_facts={})


def _snap(plan: Any, skill: str) -> Dict[str, Any]:
    """快照或可见步骤上的 inputs。"""

    accepted = (plan.assumptions or {}).get("accepted_steps") or []
    for step in accepted:
        if str(step.get("skill_name") or "") == skill:
            return dict(step.get("inputs") or {})
    for step in plan.steps:
        if step.skill_name == skill:
            return dict(step.inputs or {})
    return {}


class TestAi04CommitElements(unittest.TestCase):
    """槽声明上的元素合同。"""

    def test_two_written_codes_are_confirmed_holdings(self) -> None:
        """两只写出的代码刚好是两项已确认持有。"""

        print("\n[TestAi04CommitElements] 两只代码")
        plan = _planner().build_plan("600519 和 000858 做一条等权组合", mode="plan")
        holdings = _snap(plan, "qt.ai.hp.portfolio").get("holdings") or []
        shares = _snap(plan, "qt.ai.data.kline").get("shares")
        print(" holdings:", holdings)
        print(" shares:", shares)
        self.assertEqual([item.get("code") for item in holdings], ["600519.SH", "000858.SZ"])
        self.assertTrue(all(item.get("status") == "confirmed" for item in holdings))
        self.assertEqual(shares, "600519.SH,000858.SZ")

    def test_volatility_names_stay_incomplete(self) -> None:
        """波动率哨兵里的公司名切成两项，不猜代码。"""

        print("\n[TestAi04CommitElements] 波动率公司名")
        plan = _planner().build_plan("茅台和五粮液的波动率", mode="plan")
        shares = _snap(plan, "qt.ai.data.kline").get("shares") or []
        print(" job:", plan.planner_trace.get("intent_job"))
        print(" shares:", shares, "executable:", "qt.ai.system.fallback" not in [step.skill_name for step in plan.steps])
        self.assertEqual(plan.planner_trace.get("intent_job"), "data.summary")
        self.assertEqual([item.get("mention") for item in shares], ["茅台", "五粮液"])
        self.assertTrue(all(item.get("status") == "incomplete" and not item.get("code") for item in shares))
        self.assertTrue(all("role" not in item for item in shares))
        self.assertIn("qt.ai.system.fallback", [step.skill_name for step in plan.steps])

    def test_recipes_do_not_prewrite_symbols(self) -> None:
        """这些菜谱在填槽前不写标的、权重和基准。因子 IC 不在这张表里。"""

        print("\n[TestAi04CommitElements] 投影前不预写")
        planner = _planner()
        cases = {
            "research.hold_compare": "000001.SZ 和 000002.SZ 做一条等权组合，相对沪深300",
            "data.summary": "000001.SZ 和 000002.SZ 的波动率",
            "data.export": "导出 000001.SZ 的行情",
            "data.read": "读取历史 close 000001.SZ",
            "data.refill": "下载 000001.SZ 和 000002.SZ 从 20240101 到 20240131",
            "backtest.builtin": "macd 回测 000001.SZ 和 000002.SZ",
            "optimize.builtin": "优化 macd 000001.SZ 和 000002.SZ",
        }
        for job, query in cases.items():
            steps = compose_recipe(planner, IntentDecision(job=job), query)
            blob = json.dumps([dict(step.inputs or {}) for step in steps], ensure_ascii=False)
            print(" recipe:", job, blob)
            for step in steps:
                for key in _PREWRITE_KEYS:
                    self.assertNotIn(key, step.inputs, msg=f"{job} prewrote {key}")

    def test_pools_keep_item_lists(self) -> None:
        """补数和回测的多值代码在计划里是项列表，不是一段非空字符串。"""

        print("\n[TestAi04CommitElements] 补数和回测项列表")
        planner = _planner()
        refill_state = ConversationState.empty("refill-items")
        refill_state.start_task(
            query="下载 000001.SZ 和 000002.SZ 从 20240101 到 20240131",
            job="data.refill",
        )
        refill = planner.build_plan(
            "下载 000001.SZ 和 000002.SZ 从 20240101 到 20240131",
            session=refill_state,
            skip_classify=True,
        )
        symbols = _snap(refill, "qt.ai.data.refill_basic_equity_and_index").get("symbols")
        print(" symbols:", symbols)
        self.assertIsInstance(symbols, list)
        self.assertEqual([item.get("code") for item in symbols], ["000001.SZ", "000002.SZ"])
        self.assertTrue(all(item.get("status") == "confirmed" for item in symbols))
        self.assertTrue(all("role" not in item for item in symbols))

        back_state = ConversationState.empty("backtest-items")
        back_state.start_task(query="macd 回测茅台和五粮液", job="backtest.builtin")
        backed = planner.build_plan("macd 回测茅台和五粮液", session=back_state, skip_classify=True)
        pool = _snap(backed, "qt.ai.backtest.run_builtin").get("asset_pool")
        print(" asset_pool:", pool, "executable:", [step.skill_name for step in backed.steps])
        self.assertIsInstance(pool, list)
        self.assertEqual([item.get("mention") for item in pool], ["茅台", "五粮液"])
        self.assertTrue(all(item.get("status") == "incomplete" and not item.get("code") for item in pool))
        self.assertIn("qt.ai.system.fallback", [step.skill_name for step in backed.steps])

    def test_model_asset_type_is_not_a_user_slot(self) -> None:
        """两只股票上模型写的 asset_type 不进取数。"""

        print("\n[TestAi04CommitElements] asset_type 不是用户槽")
        protocol = {
            "holdings": [
                {"mention": "600519", "code": "600519.SH"},
                {"mention": "000858", "code": "000858.SZ"},
            ],
            "mode": "equal",
            "asset_type": "E",
        }
        plan = _planner(
            [json.dumps({"job": "research.hold_compare"}), json.dumps(protocol)]
        ).build_plan("600519 和 000858 做一条等权组合", mode="plan")
        kline = _snap(plan, "qt.ai.data.kline")
        print(" kline:", kline)
        self.assertNotIn("asset_type", kline)

    def test_confirmed_item_survives_the_next_fill(self) -> None:
        """已确认的项在下一轮解释前关上，其余项保持协议里的代码。"""

        print("\n[TestAi04CommitElements] 已确认项先关上")
        planner = _planner(
            [
                json.dumps({"job": "research.hold_compare"}),
                json.dumps(_PROTOCOL),
                json.dumps(_PROTOCOL),
            ]
        )
        first = planner.build_plan(_QUERY, mode="plan")
        portfolio = _snap(first, "qt.ai.hp.portfolio")
        holdings = list(portfolio.get("holdings") or [])
        pending = ((first.assumptions or {}).get("clarification") or {}).get("pending") or []
        page = next(item for item in pending if item.get("index") == 0)
        print(" first holdings:", holdings)
        print(" page:", page.get("mention"), page.get("index"))
        bound = bind_clarification_text(
            ["holdings"],
            "600519.SH",
            items=page.get("items"),
            index=page.get("index"),
        )
        print(" bound:", bound["holdings"])
        state = ConversationState.empty("seal-items")
        state.start_task(query=_QUERY, job="research.hold_compare")
        state.set_slot("holdings", bound["holdings"], source="user", confirmed=True)
        state.set_slot("benchmark", portfolio.get("benchmark"), source="user", confirmed=True)
        second = planner.build_plan(_QUERY, session=state, skip_classify=True)
        again = list(_snap(second, "qt.ai.hp.portfolio").get("holdings") or [])
        print(" second holdings:", again)
        self.assertEqual(again[0].get("status"), "confirmed")
        self.assertEqual(again[0].get("code"), "600519.SH")
        self.assertEqual([item.get("code") for item in again[1:]], ["000651.SZ", "601398.SH", "600036.SH"])
        self.assertTrue(all(item.get("status") == "pending" for item in again[1:]))

        sealed = [dict(item) for item in again]
        for item in sealed:
            item["status"] = "confirmed"
        state.set_slot("holdings", sealed, source="user", confirmed=True)
        third = planner.build_plan(_QUERY, session=state, skip_classify=True)
        done = _snap(third, "qt.ai.hp.portfolio")
        shares = _snap(third, "qt.ai.data.kline").get("shares")
        print(" third holdings:", done.get("holdings"))
        print(" shares:", shares, "mode:", done.get("mode"), "benchmark:", done.get("benchmark"))
        self.assertEqual(
            shares,
            "600519.SH,000651.SZ,601398.SH,600036.SH,000300.SH",
        )
        self.assertEqual(done.get("mode"), "equal")
        self.assertIsInstance(done.get("benchmark"), dict)
        self.assertEqual(done.get("benchmark").get("code"), "000300.SH")
        self.assertEqual(done.get("benchmark").get("status"), "confirmed")

    def test_handlers_join_confirmed_codes(self) -> None:
        """取数和补数在调用内核前拼字符串，计划里的列表不动。"""

        print("\n[TestAi04CommitElements] handler 拼字符串")
        items = [
            {"mention": "甲", "code": "000001.SZ", "status": "confirmed"},
            {"mention": "乙", "code": "000002.SZ", "status": "confirmed"},
        ]
        seen: Dict[str, Any] = {}

        def _fake_kline(**kwargs: Any) -> Any:
            seen["shares"] = kwargs.get("shares")
            raise RuntimeError("stop after join")

        _meta, handler = build_data_kline_skill(get_kline_func=_fake_kline)
        result = handler(shares=items)
        print(" kline echo:", result.get("inputs_echo", {}).get("shares"), "seen:", seen.get("shares"))
        print(" list after call:", items)
        self.assertEqual(result.get("inputs_echo", {}).get("shares"), "000001.SZ,000002.SZ")
        self.assertEqual(seen.get("shares"), "000001.SZ,000002.SZ")
        self.assertEqual(items[0]["mention"], "甲")
        self.assertEqual(items[1]["status"], "confirmed")

        _refill_meta, refill = build_data_refill_skill(token_getter=lambda: {"token_present": False})
        echoed = refill(
            start="20240101",
            end="20240131",
            symbols=items,
        )
        print(" refill echo:", echoed.get("inputs_echo", {}).get("symbols"))
        self.assertEqual(echoed.get("inputs_echo", {}).get("symbols"), "000001.SZ,000002.SZ")
        self.assertEqual([item.get("code") for item in items], ["000001.SZ", "000002.SZ"])

    def test_ordered_answers_keep_each_holding(self) -> None:
        """四题同名 holdings 按题序写回，认不出的那一项保持 pending。"""

        print("\n[TestAi04CommitElements] 四题答案按序折进 holdings")
        slot = {
            "name": "holdings",
            "label": "holdings",
            "hint": "Please provide holdings.",
            "type": "array",
            "element": "code",
            "cardinality": "many",
            "resolve": "code",
            "value": [
                {"mention": "贵州茅台", "code": "600519.SH", "status": "pending"},
                {"mention": "格力电器", "code": "000651.SZ", "status": "pending"},
                {"mention": "工商银行", "code": "601398.SH", "status": "pending"},
                {"mention": "招商银行", "code": "600036.SH", "status": "pending"},
            ],
        }
        rows = _item_pending_rows(slot)
        prompts = [str(item.get("prompt") or "") for item in rows or []]
        print(" prompts:", prompts)
        print(" hints:", [item.get("hint") for item in rows or []])
        self.assertEqual(
            prompts,
            [
                "请确认贵州茅台（600519.SH）。",
                "请确认格力电器（000651.SZ）。",
                "请确认工商银行（601398.SH）。",
                "请确认招商银行（600036.SH）。",
            ],
        )
        self.assertEqual(len(set(prompts)), 4)
        self.assertTrue(all(item.get("hint") == "" for item in rows or []))
        self.assertEqual(rows[0].get("options"), [{"id": "600519.SH", "label": "600519.SH"}])
        self.assertEqual(rows[0].get("open"), {"label": "其它"})
        self.assertEqual((rows[3].get("options") or [{}])[0].get("id"), "600036.SH")
        unnamed = _item_pending_rows(
            {
                "name": "holdings",
                "type": "array",
                "element": "code",
                "cardinality": "many",
                "value": [{"mention": "贵州茅台", "code": "", "status": "pending"}],
            }
        )
        code_only = _item_pending_rows(
            {
                "name": "holdings",
                "type": "array",
                "element": "code",
                "cardinality": "many",
                "value": [{"mention": "600036.SH", "code": "600036.SH", "status": "pending"}],
            }
        )
        print(" no code:", unnamed[0].get("prompt"), unnamed[0].get("options"), unnamed[0].get("open"))
        print(" code only:", code_only[0].get("prompt"), code_only[0].get("open"))
        self.assertEqual(unnamed[0].get("prompt"), "请确认贵州茅台。")
        self.assertNotIn("options", unnamed[0])
        self.assertEqual(unnamed[0].get("open"), {"label": "其它"})
        self.assertEqual(code_only[0].get("prompt"), "Confirm 600036.SH.")
        self.assertEqual(code_only[0]["options"][0]["id"], "600036.SH")
        self.assertEqual(code_only[0].get("open"), {"label": "Other"})
        polished = json.dumps(
            {
                "confirm_prompt": "还有字段没补齐。请确认下面的持仓。",
                "pending": [
                    {
                        "name": "holdings",
                        "hint": "This slot is for 招商银行.",
                        "prompt": "不要改题干",
                        "options": [{"id": item["options"][0]["id"], "label": "建议代码"}],
                    }
                    for item in rows
                ],
            },
            ensure_ascii=False,
        )
        kept = apply_polish_text(
            {"confirm_prompt": "Some fields are still missing.", "pending": rows},
            polished,
            "贵州茅台",
        )
        print(" polished hint:", kept["pending"][0].get("hint"))
        print(" polished prompt:", kept["pending"][0].get("prompt"))
        self.assertEqual(kept["pending"][0].get("hint"), "")
        self.assertEqual(kept["pending"][0].get("prompt"), rows[0]["prompt"])
        self.assertEqual(kept["pending"][0]["options"][0]["id"], "600519.SH")
        folded = apply_ordered_answers(
            rows,
            ["600519.SH", "000651.SZ", "601398.SH", "600036.SH"],
        )
        holdings = list((folded or {}).get("holdings") or [])
        print(" folded:", [(item.get("code"), item.get("status")) for item in holdings])
        self.assertEqual([item.get("status") for item in holdings], ["confirmed"] * 4)
        self.assertEqual(
            [item.get("code") for item in holdings],
            ["600519.SH", "000651.SZ", "601398.SH", "600036.SH"],
        )
        mixed = apply_ordered_answers(
            rows,
            ["600519.SH", "不是代码", "601398.SH", "600036.SH"],
        )
        again = list((mixed or {}).get("holdings") or [])
        print(" mixed:", [(item.get("mention"), item.get("code"), item.get("status")) for item in again])
        self.assertEqual(
            [item.get("status") for item in again],
            ["confirmed", "pending", "confirmed", "confirmed"],
        )
        self.assertEqual(again[1].get("code"), "000651.SZ")
        named = apply_ordered_answers(
            rows,
            ["贵州茅台", "000651.SZ", "601398.SH", "600036.SH"],
        )
        named_rows = list((named or {}).get("holdings") or [])
        print(" company:", [(item.get("mention"), item.get("code"), item.get("status")) for item in named_rows])
        self.assertEqual(named_rows[0].get("status"), "pending")
        self.assertEqual(named_rows[0].get("code"), "600519.SH")
        self.assertEqual(named_rows[1].get("status"), "confirmed")
        bare = apply_ordered_answers(
            rows,
            ["000001", "000651.SZ", "601398.SH", "600036.SH"],
        )
        bare_rows = list((bare or {}).get("holdings") or [])
        print(" bare:", [(item.get("code"), item.get("status")) for item in bare_rows])
        self.assertEqual(bare_rows[0].get("status"), "pending")
        self.assertEqual(bare_rows[0].get("code"), "600519.SH")
        company_slot = apply_ordered_answers(
            [{"name": "shares", "resolve": "code", "prompt": "Symbols"}],
            ["贵州茅台"],
        )
        passed_slot = apply_ordered_answers(
            [{"name": "shares", "resolve": "code", "prompt": "Symbols"}],
            ["600519.SH"],
        )
        print(" shares company:", company_slot, "passed:", passed_slot)
        self.assertEqual(company_slot, {})
        self.assertEqual(passed_slot, {"shares": "600519.SH"})
        distinct = apply_ordered_answers(
            [
                {"name": "start", "prompt": "Start"},
                {"name": "end", "prompt": "End"},
            ],
            ["20200101", "20231231"],
        )
        print(" distinct:", distinct)
        self.assertEqual(distinct, {"start": "20200101", "end": "20231231"})
        self.assertIsNone(apply_ordered_answers(rows, ["600519.SH"]))


if __name__ == "__main__":
    unittest.main()
