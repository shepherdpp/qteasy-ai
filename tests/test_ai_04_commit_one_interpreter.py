# coding=utf-8
# ======================================
# File: test_ai_04_commit_one_interpreter.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-14
# Desc:
# 第三C步：一个解释者、每种值一份校验。卡片、原句和澄清跟进只差交给解释者的那一段。
# ======================================

import datetime
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.planner import Planner
from qteasy_ai.session import ConversationState
from qteasy_ai.slot_graph import (
    accept_slot_value,
    apply_ordered_answers,
    asset_type_spec,
    freq_spec,
)

_SPAN = "600519 和 000858 做一条等权组合，看过去一段时间的持仓收益率，并跟沪深300做一个对比"
_FACTOR = (
    "factor IC of close vs volume for 000001.SZ,000002.SZ "
    "from 20240101 to 20240331"
)
_ROOT = Path(__file__).resolve().parents[1]
_GUARDED = (
    _ROOT / "qteasy_ai" / "app.py",
    _ROOT / "qteasy_ai" / "slot_decl.py",
    _ROOT / "qteasy_ai" / "session_gate.py",
    _ROOT / "qteasy_ai" / "planner.py",
)


def _pending(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """原始计划上的澄清题。"""

    blob = ((plan.get("assumptions") or {}).get("clarification") or {})
    return [item for item in (blob.get("pending") or []) if isinstance(item, dict)]


def _plan(payload: Any) -> Dict[str, Any]:
    """assistant.plan 的 raw 计划。"""

    if not isinstance(payload, dict):
        return {}
    plan = payload.get("plan") or payload
    return plan if isinstance(plan, dict) else {}


def _inputs(plan: Dict[str, Any], skill: str) -> Dict[str, Any]:
    """可见步骤或快照里该技能的输入。"""

    for step in list(plan.get("steps") or []) + list((plan.get("assumptions") or {}).get("accepted_steps") or []):
        if isinstance(step, dict) and step.get("skill_name") == skill:
            return dict(step.get("inputs") or {})
    return {}


def _confirmed(assistant: QteasyAssistant, sid: str) -> Dict[str, Any]:
    """会话里已确认的槽。"""

    loaded = assistant.session_store.load(sid)
    task = loaded.task if loaded is not None else None
    found: Dict[str, Any] = {}
    for name, slot in (getattr(task, "slots", {}) or {}).items():
        if getattr(slot, "confirmed", False):
            found[str(name)] = slot.value
    return found


class TestAi04CommitOneInterpreter(unittest.TestCase):
    """原句、卡片和澄清跟进共用一个解释者和一份校验。"""

    def test_date_card_confirms_only_the_card(self) -> None:
        """没有卡片的那一轮确认持仓和基准。日期卡再确认日期。组图常量不进会话。"""

        print("\n[TestAi04OneInterpreter] 原句确认持仓，日期卡确认日期")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "one-dates"
            first = _plan(assistant.plan(_SPAN, response_style="raw", session_id=sid))
            rows = _pending(first)
            print(" entry: web answers")
            print(" query:", _SPAN)
            print(" pending:", [item.get("name") for item in rows])
            answers = ["20250101", "20261010"]
            folded = apply_ordered_answers(rows, answers)
            print(" folded:", folded)
            second = _plan(assistant.plan("", response_style="raw", session_id=sid, answers=answers))
            kline = _inputs(second, "qt.ai.data.kline")
            portfolio = _inputs(second, "qt.ai.hp.portfolio")
            confirmed = _confirmed(assistant, sid)
            print(" kline:", kline.get("start"), kline.get("end"))
            print(" portfolio:", portfolio.get("holdings"), portfolio.get("benchmark"), portfolio.get("mode"))
            print(" confirmed:", confirmed)
            print(" confirmable:", "qt.ai.system.fallback" not in [step.get("skill_name") for step in second.get("steps") or []])
            self.assertEqual(kline.get("start"), "20250101")
            self.assertEqual(kline.get("end"), "20261010")
            self.assertEqual(
                [item.get("code") for item in (portfolio.get("holdings") or [])],
                ["600519.SH", "000858.SZ"],
            )
            self.assertEqual((portfolio.get("benchmark") or {}).get("code"), "000300.SH")
            self.assertEqual(portfolio.get("mode"), "equal")
            self.assertEqual(confirmed.get("start"), "20250101")
            self.assertEqual(confirmed.get("end"), "20261010")
            self.assertEqual(
                [item.get("code") for item in (confirmed.get("holdings") or [])],
                ["600519.SH", "000858.SZ"],
            )
            self.assertEqual((confirmed.get("benchmark") or {}).get("code"), "000300.SH")
            self.assertEqual(confirmed.get("mode"), "equal")
            self.assertNotIn("shares", confirmed)
            self.assertNotIn("method", confirmed)

    def test_factor_sentence_and_short_code_list(self) -> None:
        """金句五格写进同一步。只数不够的代码文本不因为非空就写下。"""

        print("\n[TestAi04OneInterpreter] 因子 IC 原句与只数")
        planner = Planner(build_default_registry(), env_facts={})
        plan = planner.build_plan(_FACTOR, mode="plan")
        inputs = plan.steps[0].inputs if plan.steps else {}
        print(" entry: sentence")
        print(" query:", _FACTOR)
        print(" skills:", [step.skill_name for step in plan.steps])
        print(" inputs:", inputs)
        print(" confirmable:", plan.steps[0].skill_name != "qt.ai.system.fallback")
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.research.factor_ic_summary")
        self.assertEqual(inputs.get("shares"), "000001.SZ,000002.SZ")
        self.assertEqual(inputs.get("factor_htype"), "close")
        self.assertEqual(inputs.get("return_htype"), "volume")
        self.assertEqual(inputs.get("start"), "20240101")
        self.assertEqual(inputs.get("end"), "20240331")
        self.assertNotIsInstance(inputs.get("shares"), list)

        short = planner.build_plan(
            "factor IC of close vs volume for 000001.SZ from 20240101 to 20240331",
            mode="plan",
        )
        pending = [
            str(item.get("name") or "")
            for item in ((short.assumptions or {}).get("clarification") or {}).get("pending") or []
            if isinstance(item, dict)
        ]
        accepted = ((short.assumptions or {}).get("accepted_steps") or [{}])[0].get("inputs") or {}
        print(" short pending:", pending)
        print(" short shares:", accepted.get("shares"))
        self.assertIn("shares", pending)
        self.assertNotEqual(accepted.get("shares"), "000001.SZ")

    def test_fill_slot_keeps_company_name_on_the_same_item(self) -> None:
        """澄清中打出公司名仍是这一题，不换题，也不提前确认。"""

        print("\n[TestAi04OneInterpreter] 澄清跟进公司名")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            sid = "one-company"
            query = "贵州茅台和格力电器做一条等权组合，相对沪深300"
            first = _plan(assistant.plan(query, response_style="raw", session_id=sid))
            rows = _pending(first)
            print(" entry: composer fill_slot")
            print(" query:", query)
            print(" pending:", [(item.get("name"), item.get("index"), item.get("mention")) for item in rows])
            second = _plan(assistant.plan("贵州茅台", response_style="raw", session_id=sid))
            again = _pending(second)
            confirmed = _confirmed(assistant, sid)
            print(" next:", [(item.get("name"), item.get("index"), item.get("error")) for item in again])
            print(" confirmed:", confirmed)
            print(" job:", ((second.get("assumptions") or {}).get("intent_job") or (second.get("plan") or {}).get("planner_trace")))
            self.assertTrue(again)
            self.assertEqual(again[0].get("name"), rows[0].get("name"))
            self.assertIn("贵州茅台", str(again[0].get("error") or ""))
            self.assertNotIn("holdings", confirmed)

    def test_copy_uses_confirmed_values_and_composition_renames(self) -> None:
        """已确认的值按槽名抄。补数步在组图时把 shares 写成 symbols。未确认的日期不抄。"""

        print("\n[TestAi04OneInterpreter] 抄回与组图改键")
        planner = Planner(build_default_registry(), env_facts={})
        ready = ConversationState.empty("one-copy")
        ready.start_task(query="下载数据", job="data.refill")
        ready.set_slot("start", "20240101", source="user", confirmed=True)
        ready.set_slot("end", "20240331", source="user", confirmed=True)
        ready.set_slot("shares", "000001.SZ,000002.SZ", source="user", confirmed=True)
        plan = planner.build_plan("下载数据", mode="plan", session=ready, skip_classify=True)
        accepted = (plan.assumptions or {}).get("accepted_steps") or []
        refill = next(step for step in accepted if step.get("skill_name") == "qt.ai.data.refill_basic_equity_and_index")
        symbols = refill.get("inputs", {}).get("symbols")
        print(" confirmed inputs:", refill.get("inputs"))
        print(" symbols:", symbols)
        print(" pending:", [item.get("name") for item in (((plan.assumptions or {}).get("clarification") or {}).get("pending") or [])])
        self.assertEqual(refill.get("inputs", {}).get("start"), "20240101")
        self.assertEqual(refill.get("inputs", {}).get("end"), "20240331")
        self.assertEqual(
            [(item.get("code"), item.get("status")) for item in symbols],
            [("000001.SZ", "pending"), ("000002.SZ", "pending")],
        )

        held = ConversationState.empty("one-unconfirmed")
        held.start_task(query="下载数据", job="data.refill")
        held.set_slot("start", "20240101", source="user", confirmed=False)
        held.set_slot("end", "20240331", source="user", confirmed=False)
        quiet = planner.build_plan("下载数据", mode="plan", session=held, skip_classify=True)
        blob = json.dumps([dict(step.inputs) for step in quiet.steps], ensure_ascii=False)
        print(" unconfirmed blob:", blob)
        self.assertNotIn("20240101", blob)

    def test_kernel_window_and_recent_year_are_not_prewritten(self) -> None:
        """用户没点缺省时，计划里没有内核窗口。近一年也不预写。"""

        print("\n[TestAi04OneInterpreter] 缺省不预写")
        planner = Planner(build_default_registry(), env_facts={})
        today = datetime.date.today()
        window_start = (today - datetime.timedelta(days=365)).strftime("%Y%m%d")
        window_end = today.strftime("%Y%m%d")
        backtest = planner.build_plan("macd 回测", mode="plan")
        blob = json.dumps([dict(step.inputs) for step in backtest.steps], ensure_ascii=False, default=str)
        print(" backtest:", blob)
        self.assertNotIn(window_start, blob)
        recent = planner.build_plan("000300.SH 近一年波动率", mode="plan")
        recent_blob = json.dumps([dict(step.inputs) for step in recent.steps], ensure_ascii=False, default=str)
        print(" recent:", recent_blob)
        self.assertNotIn(window_start, recent_blob)
        self.assertNotIn(window_end, recent_blob)
        year = planner.build_plan("000300.SH 今年波动率", mode="plan")
        print(" this year:", year.steps[0].inputs.get("start"), year.steps[0].inputs.get("end"))
        self.assertEqual(year.steps[0].inputs.get("start"), f"{today.year:04d}0101")
        self.assertEqual(year.steps[0].inputs.get("end"), f"{today.year:04d}1231")

    def test_open_resume_does_not_splice_confirmed_text(self) -> None:
        """开放图恢复时，解释者读到的原文不含拼上去的已确认槽。"""

        print("\n[TestAi04OneInterpreter] 开放图不拼接")
        planner = Planner(build_default_registry(), env_facts={})
        session = ConversationState.empty("one-open")
        session.start_task(query="draw a chart", job="open")
        session.set_slot("shares", "600519.SH", source="user", confirmed=True)
        plan = planner.build_plan(
            "continue the graph",
            mode="plan",
            session=session,
            resume_steps=[{"skill_name": "qt.ai.data.kline", "inputs": {}}],
        )
        print(" user_query:", plan.user_query)
        print(" inputs:", plan.steps[0].inputs)
        self.assertEqual(plan.user_query, "continue the graph")
        self.assertNotIn("600519.SH", plan.user_query)
        self.assertNotIn("draw a chart", plan.user_query)

    def test_one_validator_keeps_freq_asset_and_weight_rules(self) -> None:
        """频率、资产类型和权重各走已有合同。对不上的频率词不另包拒绝。"""

        print("\n[TestAi04OneInterpreter] 一份校验")
        freq = accept_slot_value(freq_spec(), "日线", "日线")
        loose = accept_slot_value(freq_spec(), "tick", "tick")
        stock = accept_slot_value(asset_type_spec(), "股票", "股票")
        missed = accept_slot_value(asset_type_spec(), "不是资产", "不是资产")
        print(" freq:", freq, "loose:", loose, "stock:", stock, "missed:", missed)
        self.assertEqual(freq, "d")
        self.assertEqual(loose, "tick")
        self.assertEqual(stock, "E")
        self.assertIsNone(missed)

    def test_source_guard_keeps_literals_in_the_interpreter(self) -> None:
        """日期格式、频率词、等权和声明解释不得再出现在旁路文件。折叠不调用代码提交。"""

        print("\n[TestAi04OneInterpreter] 源码守卫")
        banned = (
            "interpret_declared_slots",
            "_session_query_text",
            "parse_card_answers",
            "YYYYMMDD",
            "等权",
            "周线",
            "月线",
            '"股票": "E"',
            '"指数": "IDX"',
            '"基金": "FD"',
        )
        for path in _GUARDED:
            text = path.read_text(encoding="utf-8")
            for token in banned:
                print(" scan:", path.name, token, token in text)
                self.assertNotIn(token, text)
            for line in text.splitlines():
                if "日线" in line and "日均线" not in line:
                    self.fail(f"{path.name} still contains 日线: {line}")
        folded = inspect.getsource(apply_ordered_answers)
        print(" fold mentions commit_shares:", "commit_shares" in folded)
        self.assertNotIn("commit_shares", folded)
        self.assertNotIn("bind_clarification_text", inspect.getsource(__import__("qteasy_ai.slot_graph", fromlist=["slot_graph"])))
