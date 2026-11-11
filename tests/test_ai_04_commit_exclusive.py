# coding=utf-8
# ======================================
# File: test_ai_04_commit_exclusive.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-11
# Desc:
# 当前图上的全部用户槽只由一次协议或一次启发式填写。
# 协议没提交的开着的格不留预写。
# ======================================

import inspect
import json
import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.intents.recipes import _hold_compare_steps
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider


def _registry():
    """默认技能表。"""

    return build_default_registry()


def _plan(query: str, replies=None):
    """无模型，或按队列喂假模型。"""

    provider = FakeLLMProvider(replies=list(replies or [])) if replies is not None else None
    planner = Planner(_registry(), provider=provider, env_facts={})
    plan = planner.build_plan(query, mode="plan")
    return plan, provider


def _skills(plan):
    """可见步骤的技能名。"""

    return [step.skill_name for step in plan.steps]


def _accepted(plan):
    """澄清时留下的步骤快照。没有快照就用可见步骤。"""

    snapshot = (plan.assumptions or {}).get("accepted_steps") or []
    if snapshot:
        return snapshot
    return [{"skill_name": step.skill_name, "inputs": dict(step.inputs or {})} for step in plan.steps]


def _inputs(plan, skill: str):
    """可见步骤里该技能的 inputs。没有则空。"""

    for step in plan.steps:
        if step.skill_name == skill:
            return dict(step.inputs or {})
    return {}


def _snap_inputs(plan, skill: str):
    """快照里该技能的 inputs。"""

    for step in _accepted(plan):
        if str(step.get("skill_name") or "") == skill:
            inputs = step.get("inputs") or {}
            return dict(inputs)
    return {}


def _blob(plan) -> str:
    """可见步骤和快照拼成一段文本。"""

    return json.dumps({"steps": [dict(step.inputs or {}) for step in plan.steps], "accepted": _accepted(plan)}, ensure_ascii=False)


def _pending_names(plan):
    """澄清卡上的槽名。"""

    card = (plan.assumptions or {}).get("clarification") or {}
    return [str(item.get("name") or "") for item in (card.get("pending") or []) if isinstance(item, dict)]


def _executable(plan) -> bool:
    """可见步骤里没有澄清 fallback。"""

    return "qt.ai.system.fallback" not in _skills(plan)


class TestAi04CommitExclusive(unittest.TestCase):
    """一张图一次填写。"""

    def test_equal_weight_one_pass(self) -> None:
        """等权金句由同一次启发式给出代码和 mode。"""

        print("\n[TestAi04CommitExclusive] 等权金句一次启发式")
        query = "600519 和 000858 做一条等权组合"
        plan, _provider = _plan(query)
        shares = str(_inputs(plan, "qt.ai.data.kline").get("shares") or "")
        mode = _inputs(plan, "qt.ai.hp.portfolio").get("mode")
        print(" skills:", _skills(plan))
        print(" shares:", shares, "mode:", mode)
        self.assertEqual(shares, "600519.SH,000858.SZ")
        self.assertEqual(mode, "equal")
        self.assertEqual(_skills(plan), ["qt.ai.data.kline", "qt.ai.hp.portfolio", "qt.ai.hp.normalize", "qt.ai.hp.plot"])

    def test_model_partial_protocol_drops_prewrite_shares(self) -> None:
        """协议只给频率和权重时，预写的代码不留下。"""

        print("\n[TestAi04CommitExclusive] 协议漏写代码则不留预写")
        query = "600519 和 000858 做一条等权组合"
        plan, provider = _plan(
            query,
            [
                json.dumps({"job": "research.hold_compare"}),
                json.dumps({"freq": "d", "mode": "equal", "weights": []}),
            ],
        )
        prompts = provider.prompts if provider is not None else []
        print(" prompts:", [item[:80] for item in prompts])
        print(" blob:", _blob(plan))
        self.assertTrue(any("Slot protocol" in item for item in prompts))
        self.assertNotIn("600519.SH", _blob(plan))
        self.assertNotIn("000858.SZ", _blob(plan))
        self.assertFalse(_executable(plan))

    def test_negated_equal_stays_unfinished(self) -> None:
        """不要等权不写成 mode=equal。"""

        print("\n[TestAi04CommitExclusive] 否定等权")
        plan, _provider = _plan("600519 和 000858 不要等权，做一条组合")
        print(" mode:", _snap_inputs(plan, "qt.ai.hp.portfolio").get("mode"), "skills:", _skills(plan))
        self.assertNotEqual(_snap_inputs(plan, "qt.ai.hp.portfolio").get("mode"), "equal")
        self.assertNotIn('"mode": "equal"', _blob(plan))
        self.assertFalse(_executable(plan))

    def test_bare_000001_stays_unresolved(self) -> None:
        """裸 000001 不补后缀，旁边的股票或指数也不补。"""

        print("\n[TestAi04CommitExclusive] 裸 000001")
        alone, _provider = _plan("000001 做一条等权组合")
        paired, _provider = _plan("000001 和 000858 做一条等权组合")
        hinted, _provider = _plan("000001 股票 和 000858 做一条等权组合")
        print(" alone:", _blob(alone))
        print(" paired:", _blob(paired))
        print(" hinted:", _blob(hinted))
        for plan in (alone, paired, hinted):
            self.assertNotIn("000001.SH", _blob(plan))
            self.assertNotIn("000001.SZ", _blob(plan))
            self.assertFalse(_executable(plan))

    def test_user_written_suffixes_stay(self) -> None:
        """用户写出的 000001 后缀和 000300.SH 留下。"""

        print("\n[TestAi04CommitExclusive] 用户写出的后缀")
        sh_plan, _provider = _plan("000001.SH 和 600519 做一条等权组合")
        both, _provider = _plan("000001.SZ 和 000300.SH 做一条等权组合")
        print(" sh:", _inputs(sh_plan, "qt.ai.data.kline").get("shares"))
        print(" both:", _inputs(both, "qt.ai.data.kline").get("shares"), _skills(both))
        self.assertIn("000001.SH", str(_inputs(sh_plan, "qt.ai.data.kline").get("shares") or ""))
        self.assertEqual(_inputs(both, "qt.ai.data.kline").get("shares"), "000001.SZ,000300.SH")
        self.assertEqual(
            _skills(both),
            ["qt.ai.data.kline", "qt.ai.hp.portfolio", "qt.ai.hp.normalize", "qt.ai.hp.plot"],
        )

    def test_prefix_conflict_is_unfinished(self) -> None:
        """后缀和前缀表不一致时整格未完成。这两只代码只是例子。"""

        print("\n[TestAi04CommitExclusive] 前缀冲突")
        plan, _provider = _plan("600519.SZ 和 000858.SH 做一条等权组合")
        kline = _snap_inputs(plan, "qt.ai.data.kline")
        print(" kline:", kline, "executable:", _executable(plan))
        self.assertNotIn("600519.SZ", str(kline.get("shares") or ""))
        self.assertNotIn("000858.SH", str(kline.get("shares") or ""))
        self.assertFalse(_executable(plan))

    def test_company_names_are_not_guessed(self) -> None:
        """公司名不猜代码。模型提交的代码若用户没写，也不留下。"""

        print("\n[TestAi04CommitExclusive] 公司名")
        plain, _provider = _plan("茅台和五粮液放一起")
        modeled, provider = _plan(
            "茅台和五粮液放一起",
            [
                json.dumps({"job": "research.hold_compare"}),
                json.dumps({"shares": "600519.SH", "mode": "equal"}),
            ],
        )
        print(" plain:", _blob(plain))
        print(" modeled:", _blob(modeled))
        self.assertNotIn("600519", _blob(plain))
        self.assertNotIn("600519", _blob(modeled))
        self.assertTrue(any("Slot protocol" in item for item in provider.prompts))

    def test_weights_pad_and_reject_extra(self) -> None:
        """两只加基准可以垫 0。三只权重对不上就不执行。"""

        print("\n[TestAi04CommitExclusive] 权重只数")
        legal, _provider = _plan("600519 和 000858 按权重 6:4 做一条组合，基准是沪深300")
        illegal, _provider = _plan("600519 和 000858 按权重 6:4:1 做一条组合，基准是沪深300")
        weights = _inputs(legal, "qt.ai.hp.portfolio").get("weights")
        print(" legal weights:", weights, "skills:", _skills(legal))
        print(" illegal skills:", _skills(illegal), "pending:", _pending_names(illegal))
        self.assertEqual(list(weights), [6.0, 4.0, 0.0])
        self.assertTrue(_executable(legal))
        self.assertNotIn("qt.ai.hp.portfolio", _skills(illegal))
        self.assertFalse(_executable(illegal))

    def test_benchmark_answer_binds_one_cell(self) -> None:
        """六四开后回答沪深300指数，只写基准，持有和权重仍在，且不重新分类。"""

        print("\n[TestAi04CommitExclusive] 基准回答只绑定该格")
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(memory_store=MemoryStore(temp_dir), registry=_registry())
            session_id = "bench-bind"
            first = assistant.plan(
                "600519 和 000858 按权重 6:4 做一条组合，请说明基准",
                response_style="raw",
                session_id=session_id,
            )
            print(" first pending:", ((first.get("clarification") or {}).get("pending")))
            second = assistant.plan("沪深300指数", response_style="raw", session_id=session_id)
        plan = second.get("plan") or {}
        assumptions = plan.get("assumptions") or {}
        trace = plan.get("planner_trace") or second.get("planner_trace") or {}
        accepted = assumptions.get("accepted_steps") or plan.get("steps") or []
        print(" source:", assumptions.get("intent_source"), trace.get("source"))
        print(" accepted:", accepted)
        self.assertEqual(assumptions.get("intent_source"), "session")
        blob = json.dumps(accepted, ensure_ascii=False)
        self.assertIn("600519.SH", blob)
        self.assertIn("000858.SZ", blob)
        self.assertIn("000300.SH", blob)
        self.assertIn("6.0", blob)
        self.assertIn("4.0", blob)

    def test_history_one_date_and_example_is_not_a_value(self) -> None:
        """历史窗口只交开始日。协议抄来的结束日例子不留下。"""

        print("\n[TestAi04CommitExclusive] 历史日期")
        plain, _provider = _plan("读取历史 close 000300.SH 20240315")
        history = _inputs(plain, "qt.ai.data.history")
        print(" plain history:", history)
        self.assertEqual(history.get("start"), "20240315")
        self.assertIn(history.get("end"), (None, ""))
        self.assertNotIn("20250101", _blob(plain))
        self.assertNotIn("20251231", _blob(plain))
        modeled, _provider = _plan(
            "读取历史 close 000300.SH",
            [
                json.dumps({"job": "data.read"}),
                json.dumps({"start": "20240315", "end": "20251231", "htype_names": "close", "shares": "000300.SH"}),
            ],
        )
        modeled_inputs = _snap_inputs(modeled, "qt.ai.data.history") or _inputs(modeled, "qt.ai.data.history")
        print(" modeled:", modeled_inputs, _blob(modeled))
        self.assertEqual(str(modeled_inputs.get("start") or ""), "20240315")
        self.assertNotIn("20251231", _blob(modeled))
        self.assertNotIn("20250101", _blob(modeled))

    def test_omitted_htype_is_not_filled_by_heuristic(self) -> None:
        """有模型时协议没写 htype，启发式不能从 close 再补上。"""

        print("\n[TestAi04CommitExclusive] 协议漏写 htype")
        plan, provider = _plan(
            "读取历史 close 000300.SH",
            [
                json.dumps({"job": "data.read"}),
                json.dumps({"start": "20240315", "shares": "000300.SH"}),
            ],
        )
        history = _snap_inputs(plan, "qt.ai.data.history")
        print(" prompts:", [item[:80] for item in provider.prompts])
        print(" history:", history, "blob:", _blob(plan))
        self.assertTrue(any("htype_names" in item and "start" in item for item in provider.prompts))
        self.assertIn(history.get("htype_names"), (None, ""))

    def test_illegal_protocol_does_not_call_heuristic(self) -> None:
        """非法协议之后不再用启发式补 .SH、.SZ 或等权。"""

        print("\n[TestAi04CommitExclusive] 非法协议")
        plan, provider = _plan(
            "把这两只放一起",
            [
                json.dumps({"job": "research.hold_compare"}),
                "not-json",
            ],
        )
        print(" prompts:", [item[:80] for item in provider.prompts])
        print(" blob:", _blob(plan))
        self.assertTrue(any("Slot protocol" in item for item in provider.prompts))
        self.assertNotIn(".SH", _blob(plan))
        self.assertNotIn(".SZ", _blob(plan))
        self.assertNotIn("equal", _blob(plan))
        self.assertFalse(_executable(plan))

    def test_end_year_is_filled_not_preconfirmed(self) -> None:
        """到某年只写结束日，且新任务不把日期标成已确认。"""

        print("\n[TestAi04CommitExclusive] 到某年只写结束日")
        from qteasy_ai.session_gate import new_task_patches

        patches = new_task_patches("读取历史 close 000300.SH 到 2023 年")
        plan, _provider = _plan("读取历史 close 000300.SH 到 2023 年")
        history = _inputs(plan, "qt.ai.data.history")
        print(" patches:", patches)
        print(" history:", history)
        self.assertNotIn("start", patches)
        self.assertNotIn("end", patches)
        self.assertEqual(history.get("end"), "20231231")
        self.assertIn(history.get("start"), (None, ""))

    def test_recipe_calls_stay_in_source(self) -> None:
        """菜谱源码仍同时调用 commit_query 和 _market_inputs。"""

        print("\n[TestAi04CommitExclusive] 预写调用留在源码")
        source = inspect.getsource(_hold_compare_steps)
        print(" has commit:", "commit_query" in source, "has market:", "_market_inputs" in source)
        self.assertIn("commit_query", source)
        self.assertIn("_market_inputs", source)


if __name__ == "__main__":
    unittest.main()
