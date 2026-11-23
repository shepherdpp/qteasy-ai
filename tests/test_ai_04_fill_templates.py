# coding=utf-8
# ======================================
# File: test_ai_04_fill_templates.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-21
# Desc:
# 填槽候选只来自整句金句表或这一次协议。
# 协议漏键、非法协议、对不上的长句都停在澄清。
# ======================================

import inspect
import json
import unittest
from typing import Any, Dict, List, Optional

from qteasy_ai.app import build_default_registry
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.slot_graph import (
    _author_clarification,
    _fill_graph,
    _finish_portfolio_graph,
    _model_fill_candidates,
    _static_fill_candidates,
    kernel_window,
)

_EQUAL = "600519 和 000858 做一条等权组合"
_TAG = "000001.SZ 和 000002.SZ 做一条等权组合，相对沪深300"
_EXCESS = "000001.SZ 和 000002.SZ 做一条等权组合，相对沪深300，看超额"
_EXCESS_CUM = "000001.SZ 和 000002.SZ 做一条等权组合，相对沪深300，看超额和累计收益"
_WEIGHTS = "000001.SZ 和 000002.SZ 按权重 6:4 做一条组合，看累计收益"
_FACTOR = "factor IC of close vs volume for 000001.SZ,000002.SZ from 20240101 to 20240331"
_WINDOW = "600519 和 000858 做一条等权组合，看过去3年的持仓收益率，并跟沪深300做一个对比"
_HISTORY_DAY = "读取历史 close 000300.SH 20240315"
_HISTORY_YEAR = "读取历史 close 000300.SH 到 2023 年"
_CHAIN = ["qt.ai.data.kline", "qt.ai.hp.portfolio", "qt.ai.hp.normalize", "qt.ai.hp.plot"]
_EXCESS_CHAIN = ["qt.ai.data.kline", "qt.ai.hp.portfolio", "qt.ai.hp.plot"]
_CUM_CHAIN = ["qt.ai.data.kline", "qt.ai.hp.portfolio", "qt.ai.hp.cum_return", "qt.ai.hp.plot"]
_BANNED_CALLS = (
    "_heuristic(",
    "_apply_sentence_values",
    "_affirms_equal",
    "_negates_equal",
    "window_phrase",
    "_market_inputs",
    "_element_mentioned",
    "_screen_mentioned",
    "_diagnosis_mentioned",
    "_weight_mentioned",
    "_alias_mentioned",
    "commit_weight_text(",
    "commit_shares(",
    "commit_query(",
    "mentions_excess",
)


def _plan(query: str, replies: Optional[List[str]] = None):
    """无模型，或按队列喂假模型。有模型时队首是整句拆分。"""

    queued = list(replies or [])
    if replies is not None:
        queued.insert(0, json.dumps({"task": query, "question": ""}, ensure_ascii=False))
    provider = FakeLLMProvider(replies=queued) if replies is not None else None
    planner = Planner(build_default_registry(), provider=provider, env_facts={})
    return planner.build_plan(query, mode="plan")


def _with_model(query: str, job: str, payload: Dict[str, Any]):
    """拆句、分类、填槽三则固定协议。"""

    return _plan(
        query,
        [
            json.dumps({"job": job}, ensure_ascii=False),
            json.dumps(payload, ensure_ascii=False),
        ],
    )


def _skills(plan) -> List[str]:
    """可见步骤的技能名。"""

    return [step.skill_name for step in plan.steps]


def _inputs(plan, skill: str) -> Dict[str, Any]:
    """快照或可见步骤上的 inputs。"""

    accepted = (plan.assumptions or {}).get("accepted_steps") or []
    for step in accepted:
        if str(step.get("skill_name") or "") == skill:
            return dict(step.get("inputs") or {})
    for step in plan.steps:
        if step.skill_name == skill:
            return dict(step.inputs or {})
    return {}


def _pending_names(plan) -> List[str]:
    """澄清卡上的槽名。"""

    blob = (plan.assumptions or {}).get("clarification") or {}
    return [str(item.get("name") or "") for item in (blob.get("pending") or []) if isinstance(item, dict)]


def _confirmable(plan) -> bool:
    """可见步骤里没有澄清回退。"""

    return "qt.ai.system.fallback" not in _skills(plan)


def _blob(plan) -> str:
    """快照、可见步骤和澄清卡拼成一段，用来找不该出现的值。"""

    payload = {
        "steps": [
            {"skill_name": step.skill_name, "inputs": dict(step.inputs or {})}
            for step in plan.steps
        ],
        "assumptions": plan.assumptions or {},
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


def _codes(value: Any) -> str:
    """持有或基准收成能看出交易所代码的文本。"""

    return json.dumps(value, ensure_ascii=False, default=str)


class TestAi04FillTemplates(unittest.TestCase):
    """整句金句表和这一次协议。"""

    def test_six_sentences_without_model(self) -> None:
        """无模型六句金句：可见槽值和技能与表一致。"""

        print("\n[TestAi04FillTemplates] 无模型六句金句")
        window = kernel_window()
        equal = _plan(_EQUAL)
        equal_portfolio = _inputs(equal, "qt.ai.hp.portfolio")
        equal_kline = _inputs(equal, "qt.ai.data.kline")
        print(" equal skills:", _skills(equal))
        print(" equal shares:", equal_kline.get("shares"), "mode:", equal_portfolio.get("mode"))
        print(" equal dates:", equal_kline.get("start"), equal_kline.get("end"))
        print(" equal defaults:", (equal.assumptions or {}).get("slot_defaults"), "pending:", _pending_names(equal))
        self.assertEqual(_skills(equal), _CHAIN)
        self.assertEqual(equal_kline.get("shares"), "600519.SH,000858.SZ")
        self.assertEqual(equal_portfolio.get("mode"), "equal")
        self.assertNotIn("weights", equal_portfolio)
        self.assertEqual(equal_kline.get("start"), window["start"])
        self.assertEqual(equal_kline.get("end"), window["end"])
        self.assertEqual((equal.assumptions or {}).get("slot_defaults"), {"start": "default", "end": "default"})
        self.assertNotIn("start", _pending_names(equal))
        self.assertNotIn("end", _pending_names(equal))
        self.assertTrue(_confirmable(equal))

        tag = _plan(_TAG)
        tag_portfolio = _inputs(tag, "qt.ai.hp.portfolio")
        print(" tag skills:", _skills(tag), "benchmark:", _codes(tag_portfolio.get("benchmark")))
        print(" tag mode:", tag_portfolio.get("mode"), "weights:", tag_portfolio.get("weights"))
        print(" tag output:", tag_portfolio.get("benchmark_output"))
        self.assertEqual(_skills(tag), _CHAIN)
        self.assertIn("000300.SH", _codes(tag_portfolio.get("benchmark")))
        self.assertEqual(tag_portfolio.get("mode"), "equal")
        self.assertNotIn("weights", tag_portfolio)
        self.assertEqual(tag_portfolio.get("benchmark_output"), "tag_along")

        excess = _plan(_EXCESS)
        excess_portfolio = _inputs(excess, "qt.ai.hp.portfolio")
        print(" excess skills:", _skills(excess), "output:", excess_portfolio.get("benchmark_output"))
        self.assertEqual(_skills(excess), _EXCESS_CHAIN)
        self.assertNotIn("qt.ai.hp.normalize", _skills(excess))
        self.assertEqual(excess_portfolio.get("benchmark_output"), "excess_only")
        self.assertEqual(excess_portfolio.get("mode"), "equal")

        both = _plan(_EXCESS_CUM)
        both_portfolio = _inputs(both, "qt.ai.hp.portfolio")
        both_cum = _inputs(both, "qt.ai.hp.cum_return")
        print(" both skills:", _skills(both), "htypes:", both_cum.get("htypes"), "output:", both_portfolio.get("benchmark_output"))
        self.assertEqual(_skills(both), _CUM_CHAIN)
        self.assertEqual(both_cum.get("htypes"), "excess_close")
        self.assertEqual(both_portfolio.get("benchmark_output"), "excess_only")
        self.assertEqual(both_portfolio.get("mode"), "equal")

        weighted = _plan(_WEIGHTS)
        weighted_portfolio = _inputs(weighted, "qt.ai.hp.portfolio")
        weighted_cum = _inputs(weighted, "qt.ai.hp.cum_return")
        print(" weighted skills:", _skills(weighted))
        print(" weighted mode:", weighted_portfolio.get("mode"), "weights:", weighted_portfolio.get("weights"))
        print(" weighted method:", weighted_cum.get("method"))
        self.assertEqual(_skills(weighted), _CUM_CHAIN)
        self.assertNotIn("qt.ai.hp.normalize", _skills(weighted))
        self.assertEqual(weighted_portfolio.get("mode"), "weighted")
        self.assertEqual(list(weighted_portfolio.get("weights") or []), [6.0, 4.0])
        self.assertEqual(weighted_cum.get("method"), "simple")

        factor = _plan(_FACTOR)
        factor_inputs = _inputs(factor, "qt.ai.research.factor_ic_summary")
        print(" factor skills:", _skills(factor), "inputs:", factor_inputs)
        self.assertEqual(_skills(factor), ["qt.ai.research.factor_ic_summary"])
        self.assertEqual(factor_inputs.get("shares"), "000001.SZ,000002.SZ")
        self.assertEqual(factor_inputs.get("factor_htype"), "close")
        self.assertEqual(factor_inputs.get("return_htype"), "volume")
        self.assertEqual(factor_inputs.get("start"), "20240101")
        self.assertEqual(factor_inputs.get("end"), "20240331")

    def test_six_sentences_with_model_match_table(self) -> None:
        """有模型时同一份槽值来自协议，可见结果与无模型相同。"""

        print("\n[TestAi04FillTemplates] 有模型六句协议与金句可见结果相同")
        window = kernel_window()
        equal = _with_model(
            _EQUAL,
            "research.hold_compare",
            {"holdings": ["600519", "000858"], "mode": "equal"},
        )
        equal_portfolio = _inputs(equal, "qt.ai.hp.portfolio")
        equal_kline = _inputs(equal, "qt.ai.data.kline")
        print(" equal shares:", equal_kline.get("shares"), "mode:", equal_portfolio.get("mode"))
        print(" equal dates:", equal_kline.get("start"), equal_kline.get("end"), "defaults:", (equal.assumptions or {}).get("slot_defaults"))
        self.assertEqual(_skills(equal), _CHAIN)
        self.assertEqual(equal_kline.get("shares"), "600519.SH,000858.SZ")
        self.assertEqual(equal_portfolio.get("mode"), "equal")
        self.assertEqual(equal_kline.get("start"), window["start"])
        self.assertEqual(equal_kline.get("end"), window["end"])

        tag = _with_model(
            _TAG,
            "research.hold_compare",
            {
                "holdings": ["000001.SZ", "000002.SZ"],
                "mode": "equal",
                "benchmark": "沪深300",
                "benchmark_output": "tag_along",
            },
        )
        tag_portfolio = _inputs(tag, "qt.ai.hp.portfolio")
        print(" tag benchmark:", _codes(tag_portfolio.get("benchmark")), "output:", tag_portfolio.get("benchmark_output"))
        self.assertEqual(_skills(tag), _CHAIN)
        self.assertIn("000300.SH", _codes(tag_portfolio.get("benchmark")))
        self.assertEqual(tag_portfolio.get("benchmark_output"), "tag_along")
        self.assertNotIn("weights", tag_portfolio)

        excess = _with_model(
            _EXCESS,
            "research.hold_compare",
            {
                "holdings": ["000001.SZ", "000002.SZ"],
                "mode": "equal",
                "benchmark": "沪深300",
                "benchmark_output": "excess_only",
            },
        )
        print(" excess skills:", _skills(excess), "output:", _inputs(excess, "qt.ai.hp.portfolio").get("benchmark_output"))
        self.assertEqual(_skills(excess), _EXCESS_CHAIN)
        self.assertEqual(_inputs(excess, "qt.ai.hp.portfolio").get("benchmark_output"), "excess_only")

        both = _with_model(
            _EXCESS_CUM,
            "research.hold_compare",
            {
                "holdings": ["000001.SZ", "000002.SZ"],
                "mode": "equal",
                "benchmark": "沪深300",
                "benchmark_output": "excess_only",
            },
        )
        print(" both htypes:", _inputs(both, "qt.ai.hp.cum_return").get("htypes"))
        self.assertEqual(_skills(both), _CUM_CHAIN)
        self.assertEqual(_inputs(both, "qt.ai.hp.cum_return").get("htypes"), "excess_close")

        weighted = _with_model(
            _WEIGHTS,
            "research.hold_compare",
            {"holdings": ["000001.SZ", "000002.SZ"], "weights": "6:4"},
        )
        weighted_portfolio = _inputs(weighted, "qt.ai.hp.portfolio")
        print(" weighted mode:", weighted_portfolio.get("mode"), "weights:", weighted_portfolio.get("weights"))
        self.assertEqual(_skills(weighted), _CUM_CHAIN)
        self.assertEqual(weighted_portfolio.get("mode"), "weighted")
        self.assertEqual(list(weighted_portfolio.get("weights") or []), [6.0, 4.0])

        factor = _with_model(
            _FACTOR,
            "research.factor_ic",
            {
                "shares": "000001.SZ,000002.SZ",
                "factor_htype": "close",
                "return_htype": "volume",
                "start": "20240101",
                "end": "20240331",
            },
        )
        factor_inputs = _inputs(factor, "qt.ai.research.factor_ic_summary")
        print(" factor inputs:", factor_inputs)
        self.assertEqual(_skills(factor), ["qt.ai.research.factor_ic_summary"])
        self.assertEqual(factor_inputs.get("shares"), "000001.SZ,000002.SZ")
        self.assertEqual(factor_inputs.get("start"), "20240101")
        self.assertEqual(factor_inputs.get("end"), "20240331")

    def test_protocol_omits_mode_and_weights(self) -> None:
        """协议不写 mode 和权重时，不补等权，也不写数字权重。"""

        print("\n[TestAi04FillTemplates] 协议漏 mode 和权重")
        plan = _with_model(
            _EQUAL,
            "research.hold_compare",
            {"holdings": ["600519", "000858"]},
        )
        portfolio = _inputs(plan, "qt.ai.hp.portfolio")
        print(" confirmable:", _confirmable(plan), "mode:", portfolio.get("mode"), "weights:", portfolio.get("weights"))
        print(" blob has equal:", "equal" in _blob(plan))
        self.assertNotEqual(portfolio.get("mode"), "equal")
        self.assertNotIn("equal", _blob(plan))
        self.assertFalse(portfolio.get("weights"))
        self.assertFalse(_confirmable(plan))

    def test_omitted_date_keys_keep_kernel_window(self) -> None:
        """协议不写起止时，声明缺省写入内核窗口，不收句中的八位或到某年。"""

        print("\n[TestAi04FillTemplates] 协议漏日期仍用内核窗口")
        window = kernel_window()
        payload = {"shares": "000300.SH", "htype_names": "close"}
        for query in (_HISTORY_DAY, _HISTORY_YEAR):
            plan = _with_model(query, "data.read", payload)
            history = _inputs(plan, "qt.ai.data.history") or _inputs(plan, "qt.ai.data.read")
            defaults = (plan.assumptions or {}).get("slot_defaults") or {}
            blob = _blob(plan)
            print(" query:", query)
            print(" confirmable:", _confirmable(plan), "dates:", history.get("start"), history.get("end"))
            print(" defaults:", defaults, "pending:", _pending_names(plan))
            self.assertTrue(_confirmable(plan))
            self.assertTrue(defaults)
            self.assertEqual(history.get("start"), window["start"])
            self.assertEqual(history.get("end"), window["end"])
            self.assertEqual(defaults.get("start"), "default")
            self.assertEqual(defaults.get("end"), "default")
            written = json.dumps(history, ensure_ascii=False)
            self.assertNotIn("20240315", written)
            self.assertNotIn("20231231", written)

    def test_protocol_omits_benchmark_output(self) -> None:
        """协议有基准但没有 benchmark_output 时，不从「看超额」补出 excess_only。"""

        print("\n[TestAi04FillTemplates] 协议漏 benchmark_output")
        plan = _with_model(
            _EXCESS,
            "research.hold_compare",
            {
                "holdings": ["000001.SZ", "000002.SZ"],
                "mode": "equal",
                "benchmark": "沪深300",
            },
        )
        portfolio = _inputs(plan, "qt.ai.hp.portfolio")
        print(" skills:", _skills(plan), "output:", portfolio.get("benchmark_output"))
        self.assertNotEqual(portfolio.get("benchmark_output"), "excess_only")
        self.assertNotIn("qt.ai.hp.normalize", _skills(plan))

    def test_illegal_protocol_does_not_use_table(self) -> None:
        """金句配上非法填槽文本时，不回退到金句表。"""

        print("\n[TestAi04FillTemplates] 金句加非法协议")
        plan = _plan(
            _EQUAL,
            [
                json.dumps({"job": "research.hold_compare"}, ensure_ascii=False),
                "not-json",
            ],
        )
        blob = _blob(plan)
        print(" confirmable:", _confirmable(plan))
        print(" has suffix:", ".SH" in blob, ".SZ" in blob, "equal:", "equal" in blob)
        self.assertFalse(_confirmable(plan))
        self.assertNotIn(".SH", blob)
        self.assertNotIn(".SZ", blob)
        self.assertNotIn("equal", blob)

    def test_window_sentence_is_not_a_template(self) -> None:
        """过去 3 年的长句不在表上，不猜代码、等权或基准。"""

        print("\n[TestAi04FillTemplates] 非金句窗口长句")
        plan = _plan(_WINDOW)
        blob = _blob(plan)
        window = kernel_window()
        print(" confirmable:", _confirmable(plan), "pending:", _pending_names(plan))
        print(" blob:", blob)
        self.assertFalse(_confirmable(plan))
        self.assertNotIn("600519.SH", blob)
        self.assertNotIn("000858.SZ", blob)
        self.assertNotIn("equal", blob)
        self.assertNotIn("000300.SH", blob)
        self.assertNotIn("start", _pending_names(plan))
        self.assertNotIn("end", _pending_names(plan))
        for token in ("2023", "2024", "2025"):
            if token in blob and token not in (window["start"], window["end"]):
                self.assertIn(token, window["start"] + window["end"])
        for date in (window["start"], window["end"]):
            continue
        import re
        found = re.findall(r"(?<!\d)20\d{6}(?!\d)", blob)
        print(" dates in blob:", found, "kernel:", window)
        for date in found:
            self.assertIn(date, {window["start"], window["end"]})

    def test_fill_functions_do_not_scan_the_sentence(self) -> None:
        """四个填槽函数的源码不再调用原句扫描。"""

        print("\n[TestAi04FillTemplates] 四函数源码守卫")
        functions = (
            _fill_graph,
            _model_fill_candidates,
            _static_fill_candidates,
            _finish_portfolio_graph,
            _author_clarification,
        )
        for func in functions:
            source = inspect.getsource(func)
            hits = [name for name in _BANNED_CALLS if name in source]
            print(" ", func.__name__, "hits:", hits)
            self.assertEqual(hits, [])
        model_source = inspect.getsource(_model_fill_candidates)
        static_source = inspect.getsource(_static_fill_candidates)
        print(" model scans gold:", "_exact_sentence_candidates" in model_source)
        print(" static chats:", "provider.chat" in static_source)
        self.assertNotIn("_exact_sentence_candidates", model_source)
        self.assertNotIn("provider.chat", static_source)
