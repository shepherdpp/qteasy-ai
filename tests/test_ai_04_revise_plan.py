# coding=utf-8
# ======================================
# File: test_ai_04_revise_plan.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-18
# Desc:
# 未执行计划只被补充和升级：同一 plan_id、点到的槽、换图快照和三个出口。
# ======================================

import json
import re
import tempfile
import unittest
from typing import Any, Dict, List, Optional

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.slot_graph import revision_target

_FIRST = "我想找两只股票创建一个组合，进行对比。"
_BENCH = "最好跟 HS300 做个对比。"
_WINDOW = "取三年内的数据。"
_WEEK = "改成周线"
_DAILY = "改成看这两只的日线"
_DAILY_BENCH = "改成看这两只的日线，基准仍用沪深300"
_FOUR = "我需要的四支股票都必须在组合里。"
_NAMES = "帮我用贵州茅台、格力电器、工商银行和招商银行做一个等权持仓组合，看过去3年的持仓收益率，并跟沪深300指数做一个对比。"
_READY = "600519 和 000858 做一条等权组合，看过去一段时间的持仓收益率，并跟沪深300做一个对比"
_FREQ_READY = "600519 和 000858 做一条等权组合，周线"
_END_ONLY = "600519 和 000858 做一条等权组合，到 2023 年"
_DATE = re.compile(r"(?<!\d)20\d{6}(?!\d)")


def _assistant(temp_dir: str) -> QteasyAssistant:
    """无模型助手，计划落在临时目录。"""

    return QteasyAssistant(
        registry=build_default_registry(),
        memory_store=MemoryStore(base_dir=temp_dir),
    )


def _plan(result: Dict[str, Any]) -> Dict[str, Any]:
    """raw 结果里的计划。"""

    plan = result.get("plan") or {}
    return plan if isinstance(plan, dict) else {}


def _job(plan: Dict[str, Any]) -> str:
    """计划上的 Job。"""

    trace = plan.get("planner_trace") or {}
    assumptions = plan.get("assumptions") or {}
    return str(trace.get("intent_job") or assumptions.get("intent_job") or "")


def _pending(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    """澄清卡上的题。"""

    card = (plan.get("assumptions") or {}).get("clarification") or {}
    return [item for item in (card.get("pending") or []) if isinstance(item, dict)]


def _inputs(plan: Dict[str, Any], skill: str) -> Dict[str, Any]:
    """快照或可见步骤上的 inputs。"""

    accepted = (plan.get("assumptions") or {}).get("accepted_steps") or []
    for step in accepted:
        if str(step.get("skill_name") or "") == skill:
            return dict(step.get("inputs") or {})
    for step in plan.get("steps") or []:
        if str(step.get("skill_name") or "") == skill:
            return dict(step.get("inputs") or {})
    return {}


def _skills(plan: Dict[str, Any]) -> List[str]:
    """可见步骤的技能名。"""

    return [str(step.get("skill_name") or "") for step in (plan.get("steps") or [])]


def _confirmable(plan: Dict[str, Any]) -> bool:
    """有真实步骤，且没有澄清回退、也没有待答题。"""

    skills = _skills(plan)
    if not skills:
        return False
    return "qt.ai.system.fallback" not in skills and not _pending(plan)


def _show(label: str, result: Dict[str, Any], session: Any) -> Dict[str, Any]:
    """断言前打印计划身份、槽和能否确认。"""

    plan = _plan(result)
    task = getattr(session, "task", None)
    portfolio = _inputs(plan, "qt.ai.hp.portfolio")
    kline = _inputs(plan, "qt.ai.data.kline")
    history = _inputs(plan, "qt.ai.data.history")
    print(f" [{label}] plan_id:", plan.get("plan_id"), "job:", _job(plan))
    print(" status:", None if task is None else task.status, "task_query:", None if task is None else task.user_query)
    print(" confirmable:", _confirmable(plan), "pending:", [item.get("name") for item in _pending(plan)])
    print(" portfolio:", portfolio)
    print(" kline:", kline)
    print(" history:", history)
    print(" execution:", (result.get("execution") or {}).get("status"))
    return plan


def _codes(holdings: Any) -> List[str]:
    """持有项里的代码。"""

    return [str(item.get("code") or "") for item in holdings or [] if isinstance(item, dict)]


class TestAi04RevisePlan(unittest.TestCase):
    """同一份未执行计划上的升级。"""

    def test_three_sentences_stay_on_one_plan(self) -> None:
        """组合对比、HS300、三年内都留在第一份计划上。"""

        print("\n[TestAi04RevisePlan] 三句升级")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir)
            first = assistant.plan(_FIRST, response_style="raw", session_id="s-three")
            state = assistant.session_store.load("s-three")
            plan = _show("first", first, state)
            holdings = _inputs(plan, "qt.ai.hp.portfolio").get("holdings") or []
            print(" holdings:", holdings)
            self.assertEqual(_job(plan), "research.hold_compare")
            self.assertFalse(holdings)
            self.assertIn("holdings", [item.get("name") for item in _pending(plan)])
            self.assertFalse(_confirmable(plan))
            self.assertNotEqual((first.get("execution") or {}).get("status"), "success")
            plan_id = str(plan.get("plan_id") or "")
            self.assertTrue(plan_id)
            self.assertEqual(state.task.user_query, _FIRST)

            second = assistant.plan(_BENCH, response_style="raw", session_id="s-three")
            state = assistant.session_store.load("s-three")
            plan = _show("bench", second, state)
            portfolio = _inputs(plan, "qt.ai.hp.portfolio")
            benchmark = portfolio.get("benchmark") or {}
            holdings = portfolio.get("holdings") or []
            print(" benchmark:", benchmark, "holdings:", holdings)
            self.assertEqual(plan.get("plan_id"), plan_id)
            self.assertEqual(str(benchmark.get("code") or ""), "000300.SH")
            self.assertNotIn("000300.SH", _codes(holdings))
            self.assertFalse(holdings)
            self.assertIn("holdings", [item.get("name") for item in _pending(plan)])
            self.assertNotIn(_BENCH, json.dumps(_pending(plan), ensure_ascii=False))
            self.assertEqual(state.task.user_query, _FIRST)

            third = assistant.plan(_WINDOW, response_style="raw", session_id="s-three")
            state = assistant.session_store.load("s-three")
            plan = _show("window", third, state)
            names = [item.get("name") for item in _pending(plan)]
            blob = json.dumps(
                {
                    "accepted": (plan.get("assumptions") or {}).get("accepted_steps"),
                    "steps": plan.get("steps"),
                },
                ensure_ascii=False,
            )
            portfolio = _inputs(plan, "qt.ai.hp.portfolio")
            print(" pending:", names, "dates:", _DATE.findall(blob))
            self.assertEqual(plan.get("plan_id"), plan_id)
            self.assertIn("start", names)
            self.assertIn("end", names)
            self.assertFalse(_DATE.search(blob))
            self.assertFalse(portfolio.get("holdings") or [])
            self.assertEqual(str((portfolio.get("benchmark") or {}).get("code") or ""), "000300.SH")
            self.assertFalse(_confirmable(plan))
            self.assertEqual(state.task.user_query, _FIRST)

    def test_week_freq_does_not_switch_graph(self) -> None:
        """只写频率留在持有对比，句里的「改成」不换图。"""

        print("\n[TestAi04RevisePlan] 周线不换图")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir)
            assistant.plan(_FIRST, response_style="raw", session_id="s-week")
            result = assistant.plan(_WEEK, response_style="raw", session_id="s-week")
            state = assistant.session_store.load("s-week")
            plan = _show("week", result, state)
            freq = _inputs(plan, "qt.ai.data.kline").get("freq")
            print(" freq:", freq, "skills:", _skills(plan))
            self.assertEqual(_job(plan), "research.hold_compare")
            self.assertEqual(freq, "w")
            self.assertNotIn("qt.ai.data.history", _skills(plan))
            self.assertNotIn(
                "qt.ai.data.history",
                json.dumps((plan.get("assumptions") or {}).get("accepted_steps") or [], ensure_ascii=False),
            )

    def test_daily_on_these_two_switches_to_data_read(self) -> None:
        """可确认的持有对比换成取数，shares 不含基准，旧步骤留在快照。"""

        print("\n[TestAi04RevisePlan] 这两只日线换取数")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir)
            first = assistant.plan(_READY, response_style="raw", session_id="s-daily")
            state = assistant.session_store.load("s-daily")
            opened = _show("opened", first, state)
            self.assertEqual([item.get("name") for item in _pending(opened)], ["start", "end"])
            second = assistant.plan(
                "",
                response_style="raw",
                session_id="s-daily",
                answers=["default", "default"],
            )
            state = assistant.session_store.load("s-daily")
            ready = _show("ready", second, state)
            plan_id = str(ready.get("plan_id") or "")
            kline = _inputs(ready, "qt.ai.data.kline")
            portfolio = _inputs(ready, "qt.ai.hp.portfolio")
            print(" ready shares:", kline.get("shares"), "benchmark:", portfolio.get("benchmark"))
            self.assertTrue(_confirmable(ready))
            self.assertIn("000300.SH", str(kline.get("shares") or ""))
            markdown = str(second.get("plan_md") or "")
            print(" plan_md head:", "\n".join(markdown.splitlines()[:8]))
            self.assertIn("## What will run", markdown)
            self.assertIn("600519.SH", markdown)
            self.assertIn("000300.SH", markdown)

            third = assistant.plan(_DAILY, response_style="raw", session_id="s-daily")
            state = assistant.session_store.load("s-daily")
            plan = _show("switched", third, state)
            history = _inputs(plan, "qt.ai.data.history")
            replaced = (plan.get("assumptions") or {}).get("replaced_steps") or []
            old_shares = ""
            old_bench = ""
            for row in replaced:
                if str(row.get("skill_name") or "") == "qt.ai.data.kline":
                    old_shares = str((row.get("inputs") or {}).get("shares") or "")
                if str(row.get("skill_name") or "") == "qt.ai.hp.portfolio":
                    old_bench = str(((row.get("inputs") or {}).get("benchmark") or {}).get("code") or "")
            print(" history:", history, "old shares:", old_shares, "old bench:", old_bench)
            self.assertEqual(plan.get("plan_id"), plan_id)
            self.assertEqual(_job(plan), "data.read")
            self.assertEqual(state.task.job, "data.read")
            self.assertIn("qt.ai.data.history", _skills(plan))
            self.assertEqual(history.get("shares"), "600519.SH,000858.SZ")
            self.assertNotIn("000300", str(history.get("shares") or ""))
            self.assertEqual(history.get("freq"), "d")
            self.assertNotIn("benchmark", history)
            self.assertTrue(all("benchmark" not in (row.get("inputs") or {}) for row in (plan.get("steps") or [])))
            self.assertIn("000300.SH", old_shares)
            self.assertEqual(old_bench, "000300.SH")

    def test_benchmark_on_these_two_stays(self) -> None:
        """点了基准的这两只日线不换图，频率写成 d。"""

        print("\n[TestAi04RevisePlan] 带基准的日线留在持有对比")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir)
            assistant.plan(_READY, response_style="raw", session_id="s-stay")
            assistant.plan("", response_style="raw", session_id="s-stay", answers=["default", "default"])
            result = assistant.plan(_DAILY_BENCH, response_style="raw", session_id="s-stay")
            state = assistant.session_store.load("s-stay")
            plan = _show("stay", result, state)
            portfolio = _inputs(plan, "qt.ai.hp.portfolio")
            freq = _inputs(plan, "qt.ai.data.kline").get("freq")
            print(" freq:", freq, "benchmark:", portfolio.get("benchmark"))
            self.assertEqual(_job(plan), "research.hold_compare")
            self.assertEqual(freq, "d")
            self.assertEqual(str((portfolio.get("benchmark") or {}).get("code") or ""), "000300.SH")
            self.assertNotIn("qt.ai.data.history", _skills(plan))

    def test_revision_target_branches(self) -> None:
        """支路甲忽略分类器；支路乙认这两只加频率；基准句在支路丙之前返回空串。"""

        print("\n[TestAi04RevisePlan] revision_target")
        for query in (_BENCH, _WINDOW, _WEEK):
            stayed = revision_target("research.hold_compare", query, "data.read")
            print(" stay:", query, stayed)
            self.assertEqual(stayed, "")
            stayed_opt = revision_target("research.hold_compare", query, "optimize.builtin")
            print(" stay opt:", query, stayed_opt)
            self.assertEqual(stayed_opt, "")
        switched = revision_target("research.hold_compare", _DAILY, "clarify")
        blocked = revision_target("research.hold_compare", _DAILY_BENCH, "data.read")
        print(" daily:", switched, "blocked:", blocked)
        self.assertEqual(switched, "data.read")
        self.assertEqual(blocked, "")
        optimized = revision_target("backtest.builtin", "再帮我优化参数", "optimize.builtin")
        print(" optimize:", optimized)
        self.assertEqual(optimized, "optimize.builtin")

    def test_one_cell_keeps_the_rest(self) -> None:
        """只写基准不动代码和频率；只写开始日不动结束日和代码。"""

        print("\n[TestAi04RevisePlan] 只改一格")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir)
            assistant.plan(_FREQ_READY, response_style="raw", session_id="s-one-bench")
            result = assistant.plan(_BENCH, response_style="raw", session_id="s-one-bench")
            state = assistant.session_store.load("s-one-bench")
            plan = _show("one-bench", result, state)
            portfolio = _inputs(plan, "qt.ai.hp.portfolio")
            kline = _inputs(plan, "qt.ai.data.kline")
            print(" codes:", _codes(portfolio.get("holdings")), "freq:", kline.get("freq"))
            self.assertEqual(_codes(portfolio.get("holdings")), ["600519.SH", "000858.SZ"])
            self.assertEqual(kline.get("freq"), "w")
            self.assertEqual(str((portfolio.get("benchmark") or {}).get("code") or ""), "000300.SH")

            assistant.plan(_END_ONLY, response_style="raw", session_id="s-one-date")
            dated = assistant.plan("20200101", response_style="raw", session_id="s-one-date")
            state = assistant.session_store.load("s-one-date")
            plan = _show("one-date", dated, state)
            kline = _inputs(plan, "qt.ai.data.kline")
            portfolio = _inputs(plan, "qt.ai.hp.portfolio")
            print(" start:", kline.get("start"), "end:", kline.get("end"), "codes:", _codes(portfolio.get("holdings")))
            self.assertEqual(kline.get("start"), "20200101")
            self.assertEqual(kline.get("end"), "20231231")
            self.assertEqual(_codes(portfolio.get("holdings")), ["600519.SH", "000858.SZ"])

    def test_four_names_survive_followup(self) -> None:
        """四项盖回后还在，已确认的两项不变，跟进句不进 note。"""

        print("\n[TestAi04RevisePlan] 四支股票")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir)
            first = assistant.plan(_NAMES, response_style="raw", session_id="s-four")
            state = assistant.session_store.load("s-four")
            plan = _show("names", first, state)
            holdings = _inputs(plan, "qt.ai.hp.portfolio").get("holdings") or []
            print(" count:", len(holdings))
            self.assertEqual(len(holdings), 4)
            rows = _pending(plan)
            answers: List[str] = []
            wanted = {0: "600519.SH", 1: "000858.SZ"}
            for row in rows:
                if row.get("name") == "holdings" and row.get("index") is not None:
                    answers.append(wanted.get(int(row.get("index")), ""))
                else:
                    answers.append("")
            print(" answers:", answers)
            assistant.plan("", response_style="raw", session_id="s-four", answers=answers)
            followed = assistant.plan(_FOUR, response_style="raw", session_id="s-four")
            state = assistant.session_store.load("s-four")
            plan = _show("follow", followed, state)
            holdings = list(_inputs(plan, "qt.ai.hp.portfolio").get("holdings") or [])
            assumptions = plan.get("assumptions") or {}
            slot = state.task.slots.get("holdings") if state.task is not None else None
            print(" holdings:", holdings, "slot confirmed:", None if slot is None else slot.confirmed)
            self.assertNotIn("note", assumptions)
            self.assertNotIn("note", json.dumps(followed.get("patches") or {}, ensure_ascii=False))
            self.assertEqual(len(holdings), 4)
            self.assertEqual(holdings[0].get("code"), "600519.SH")
            self.assertEqual(holdings[1].get("code"), "000858.SZ")
            self.assertEqual(holdings[0].get("status"), "confirmed")
            self.assertEqual(holdings[1].get("status"), "confirmed")
            self.assertTrue(all(not item.get("code") for item in holdings[2:]))
            self.assertTrue(all(item.get("status") in {"pending", "incomplete"} for item in holdings[2:]))
            self.assertFalse(_confirmable(plan))
            self.assertTrue(slot is None or not slot.confirmed)

    def test_optimize_followup_switches_on_the_same_plan(self) -> None:
        """回测上的「再帮我优化参数」升级到优化，旧步骤留在快照。"""

        print("\n[TestAi04RevisePlan] 优化参数换图")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir)
            first = assistant.plan(
                "macd 回测 000001.SZ 从 20200101 到 20201231",
                response_style="raw",
                session_id="s-opt",
            )
            state = assistant.session_store.load("s-opt")
            opened = _show("backtest", first, state)
            plan_id = str(opened.get("plan_id") or "")
            self.assertEqual(_job(opened), "backtest.builtin")
            second = assistant.plan("再帮我优化参数", response_style="raw", session_id="s-opt")
            state = assistant.session_store.load("s-opt")
            plan = _show("optimize", second, state)
            replaced = (plan.get("assumptions") or {}).get("replaced_steps") or []
            print(" replaced skills:", [row.get("skill_name") for row in replaced])
            self.assertEqual(plan.get("plan_id"), plan_id)
            self.assertEqual(state.task.id, assistant.session_store.load("s-opt").task.id)
            self.assertEqual(_job(plan), "optimize.builtin")
            self.assertEqual(state.task.job, "optimize.builtin")
            self.assertTrue(replaced)
            self.assertNotEqual(_job(plan), "data.read")

    def test_three_exits(self) -> None:
        """放弃取消这份计划；Cancel 和 Confirm 之后的下一句不再改它。"""

        print("\n[TestAi04RevisePlan] 三个出口")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = _assistant(temp_dir)
            assistant.plan(_FIRST, response_style="raw", session_id="s-abandon")
            abandoned = assistant.plan("放弃当前计划并重开", response_style="raw", session_id="s-abandon")
            state = assistant.session_store.load("s-abandon")
            plan = _show("abandon", abandoned, state)
            print(" abandoned job:", _job(plan), "steps:", _skills(plan))
            self.assertEqual(state.task.status, "cancelled")
            self.assertFalse(_confirmable(plan))

            assistant.plan(_FIRST, response_style="raw", session_id="s-cancel")
            before = assistant.session_store.load("s-cancel")
            old_id = str(before.task.plan_id or "")
            saved = assistant.memory_store.find_run_by_plan_id(old_id)
            saved_steps = json.dumps(((saved.get("plan") or {}).get("steps") or []), ensure_ascii=False, sort_keys=True)
            print(" cancel before:", old_id, saved_steps)
            assistant.cancel_unexecuted_plan("s-cancel")
            cancelled = assistant.session_store.load("s-cancel")
            self.assertEqual(cancelled.task.status, "cancelled")
            nxt = assistant.plan(_BENCH, response_style="raw", session_id="s-cancel")
            after = assistant.session_store.load("s-cancel")
            plan = _show("after-cancel", nxt, after)
            again = assistant.memory_store.find_run_by_plan_id(old_id)
            again_steps = json.dumps(((again.get("plan") or {}).get("steps") or []), ensure_ascii=False, sort_keys=True)
            print(" new plan:", plan.get("plan_id"), "old steps same:", again_steps == saved_steps)
            self.assertNotEqual(plan.get("plan_id"), old_id)
            self.assertEqual(again_steps, saved_steps)

            ready = assistant.plan(_FREQ_READY, response_style="raw", session_id="s-confirm")
            state = assistant.session_store.load("s-confirm")
            confirmed = _show("confirm-ready", ready, state)
            self.assertTrue(_confirmable(confirmed))
            plan_id = str(confirmed.get("plan_id") or "")
            copied = assistant.memory_store.find_run_by_plan_id(plan_id)
            copied_steps = json.dumps(((copied.get("plan") or {}).get("steps") or []), ensure_ascii=False, sort_keys=True)
            try:
                assistant.run_plan(plan_id, response_style="raw", session_id="s-confirm")
            except Exception as exc:
                print(" run_plan error:", type(exc).__name__, exc)
            running = assistant.session_store.load("s-confirm")
            print(" after confirm status:", None if running.task is None else running.task.status)
            later = assistant.plan(_BENCH, response_style="raw", session_id="s-confirm")
            state = assistant.session_store.load("s-confirm")
            plan = _show("after-confirm", later, state)
            kept = assistant.memory_store.find_run_by_plan_id(plan_id)
            kept_steps = json.dumps(((kept.get("plan") or {}).get("steps") or []), ensure_ascii=False, sort_keys=True)
            print(" confirm plan same:", kept_steps == copied_steps, "new:", plan.get("plan_id"))
            self.assertNotEqual(plan.get("plan_id"), plan_id)
            self.assertEqual(kept_steps, copied_steps)


if __name__ == "__main__":
    unittest.main()
