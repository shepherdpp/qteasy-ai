# coding=utf-8
# ======================================
# File: test_ai_04_commit_card.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-09
# Desc:
# 确认卡和结果卡投影同一次已提交参数。
# ======================================

import unittest

from qteasy_ai.app import build_default_registry
from qteasy_ai.human_card import _slim_plan_ready_lines, _slim_result_lines
from qteasy_ai.plan_markdown import tool_plan_to_markdown

_CODES = "600519.SH,000858.SZ,000300.SH"


def _plan(steps: list) -> dict:
    """只含步骤的计划。"""

    return {
        "plan_id": "plan_commit_card",
        "mode": "plan",
        "user_query": "commit card",
        "steps": steps,
        "assumptions": {},
    }


def _rows(steps: list) -> list:
    """投影用的步骤行。"""

    return [
        {
            "step_id": item["step_id"],
            "skill_name": item["skill_name"],
            "inputs": dict(item["inputs"]),
            "side_effects": {"description": "readonly"},
        }
        for item in steps
    ]


class TestAi04CommitCard(unittest.TestCase):
    """两张卡读同一份 inputs。"""

    def setUp(self) -> None:
        self.registry = build_default_registry()

    def test_projection_reads_committed_role(self) -> None:
        """三张卡只投影已提交输入和该步记录。角色只在事实行。"""

        print("\n[TestAi04CommitCard] 旁挂、无基准、失败、未确认字典")
        confirmed = {"code": "000300.SH", "status": "confirmed"}
        beside_steps = _portfolio_steps(
            _CODES,
            {"mode": "equal", "benchmark": confirmed, "benchmark_output": "tag_along"},
        )
        ready, markdown, result, slots = self._three_cards(
            beside_steps,
            _success("qt.ai.hp.portfolio", {"n_shares": 3}),
        )
        for text in (ready, markdown, result):
            self.assertIn(_CODES, text)
            self.assertIn("equal", text)
            self.assertNotIn("committed inputs", text)
            self.assertNotIn("status", text)
        self.assertIn("benchmark=000300.SH beside the portfolio", ready)
        self.assertIn("benchmark=000300.SH beside the portfolio", result)
        self.assertIn("benchmark=000300.SH beside the portfolio", markdown.split("## Slots", 1)[0])
        self.assertIn(_CODES, slots)
        self.assertIn("equal", slots)
        self.assertIn("000300.SH", slots)
        self.assertNotIn("tag_along", slots)
        self.assertNotIn("benchmark_output", slots)
        self.assertIn("A benchmark is kept beside it", result)
        self.assertIn("A benchmark is kept beside it", markdown)

        plain_steps = _portfolio_steps(_CODES, {"mode": "equal"})
        ready, markdown, result, _slots = self._three_cards(
            plain_steps,
            _success("qt.ai.hp.portfolio", {"n_shares": 3}),
        )
        for text in (ready, markdown, result):
            self.assertIn("no benchmark", text)
            self.assertNotIn("beside", text.lower())
            self.assertNotIn("基准留在旁边", text)
            self.assertNotIn("committed inputs", text)
        self.assertIn("A new panel with one portfolio row", markdown)
        self.assertNotIn("kept beside", markdown)

        failed = {
            "status": "partial_failed",
            "steps": [
                {
                    "skill_name": "qt.ai.hp.portfolio",
                    "result": {
                        "ok": False,
                        "error": {"message": "symbol 000001 was not found"},
                    },
                }
            ],
        }
        ready, markdown, result, _slots = self._three_cards(beside_steps, failed)
        print(" failed result:", result)
        self.assertIn("symbol 000001 was not found", result)
        self.assertIn("**Run did not finish.**", result)
        self.assertNotIn("**Run succeeded.**", result)
        self.assertNotIn("Check the name", result)
        self.assertIn("benchmark=000300.SH beside the portfolio", ready)
        self.assertIn(_CODES, markdown)
        self.assertIn("equal", markdown)

        for benchmark in ({"code": "000300.SH"}, {"code": "000300.SH", "status": "pending"}):
            quiet_steps = _portfolio_steps(
                "600519.SH,000858.SZ",
                {"mode": "equal", "benchmark": benchmark, "benchmark_output": "tag_along"},
            )
            ready, markdown, result, slots = self._three_cards(
                quiet_steps,
                _success("qt.ai.hp.portfolio", {"n_shares": 2}),
            )
            print(" unconfirmed:", benchmark, ready)
            for text in (ready, result):
                self.assertIn("no benchmark", text)
                self.assertNotIn("000300.SH", text)
            self.assertNotIn("000300.SH", slots)

        string_steps = _portfolio_steps(
            "600519.SH,000858.SZ",
            {"mode": "equal", "benchmark": "000300.SH", "benchmark_output": "tag_along"},
        )
        ready, _markdown, result, slots = self._three_cards(
            string_steps,
            _success("qt.ai.hp.portfolio", {"n_shares": 2}),
        )
        self.assertIn("benchmark=000300.SH beside the portfolio", ready)
        self.assertIn("benchmark=000300.SH beside the portfolio", result)
        self.assertIn("000300.SH", slots)

    def _three_cards(self, steps: list, execution: dict) -> tuple:
        """计划卡、计划 Markdown、结果卡，以及 Markdown 的槽位段。"""

        plan = _plan(steps)
        ready = "\n".join(
            _slim_plan_ready_lines(
                plan=plan,
                card_steps=_rows(steps),
                plan_id="plan_commit_card",
                run_id="run_commit_card",
                plan_md_file="",
                confirmable=True,
            )
        )
        markdown = tool_plan_to_markdown(plan, registry=self.registry)
        lines, _mode = _slim_result_lines(
            plan=plan,
            execution=execution,
            registry=self.registry,
        )
        result = "\n".join(lines)
        slots = markdown.split("## Slots", 1)[1] if "## Slots" in markdown else ""
        print(" ready:", ready)
        print(" markdown:", markdown)
        print(" result:", result)
        print(" benchmark code:", "000300.SH")
        print(" slots:", slots)
        return ready, markdown, result, slots

    def test_equal_cards_omit_benchmark_sentence(self) -> None:
        """等权、没有基准时写出代码和 equal，不说基准留在旁边。"""

        print("\n[TestAi04CommitCard] 等权无基准")
        steps = [
            {
                "step_id": "step_1",
                "skill_name": "qt.ai.data.kline",
                "inputs": {"shares": "000001.SZ,000002.SZ", "freq": "d"},
            },
            {
                "step_id": "step_2",
                "skill_name": "qt.ai.hp.portfolio",
                "inputs": {"mode": "equal"},
            },
        ]
        ready = "\n".join(
            _slim_plan_ready_lines(
                plan=_plan(steps),
                card_steps=_rows(steps),
                plan_id="plan_commit_card",
                run_id="run_commit_card",
                plan_md_file="",
                confirmable=True,
            )
        )
        _lines, _mode = _slim_result_lines(
            plan=_plan(steps),
            execution=_success("qt.ai.hp.portfolio", {"n_shares": 2}),
            registry=self.registry,
        )
        result = "\n".join(_lines)
        print(" ready:", ready)
        print(" result:", result)
        for text in (ready, result):
            self.assertIn("000001.SZ,000002.SZ", text)
            self.assertIn("equal", text)
            self.assertNotIn("beside", text.lower())
            self.assertNotIn("基准留在旁边", text)

    def test_excess_and_weekly_use_committed_inputs(self) -> None:
        """超额不说基准留在旁边。周线结果写出 w。个数对不上时旁挂事实行仍在。"""

        print("\n[TestAi04CommitCard] 超额、周线和个数不一致")
        excess_steps = [
            {
                "step_id": "step_1",
                "skill_name": "qt.ai.data.kline",
                "inputs": {"shares": "000001.SZ,000002.SZ", "freq": "d"},
            },
            {
                "step_id": "step_2",
                "skill_name": "qt.ai.hp.portfolio",
                "inputs": {
                    "mode": "equal",
                    "benchmark": "000300.SH",
                    "benchmark_output": "excess_only",
                },
            },
        ]
        excess, _mode = _slim_result_lines(
            plan=_plan(excess_steps),
            execution=_success("qt.ai.hp.portfolio", {"n_shares": 2}),
            registry=self.registry,
        )
        excess_text = "\n".join(excess)
        print(" excess:", excess_text)
        self.assertIn("excess", excess_text)
        self.assertNotIn("beside", excess_text.lower())
        self.assertNotIn("基准留在旁边", excess_text)

        weekly_steps = [
            {
                "step_id": "step_1",
                "skill_name": "qt.ai.data.kline",
                "inputs": {"shares": "000300.SH", "freq": "w"},
            }
        ]
        weekly, _mode = _slim_result_lines(
            plan=_plan(weekly_steps),
            execution=_success("qt.ai.data.kline", {"n_rows": 52}),
            registry=self.registry,
        )
        weekly_text = "\n".join(weekly)
        print(" weekly:", weekly_text)
        self.assertIn("freq=w", weekly_text)

        mismatch_steps = _portfolio_steps(
            _CODES,
            {"mode": "equal", "benchmark": "000300.SH", "benchmark_output": "tag_along"},
        )
        mismatch, _mode = _slim_result_lines(
            plan=_plan(mismatch_steps),
            execution=_success("qt.ai.hp.portfolio", {"n_shares": 1}),
            registry=self.registry,
        )
        mismatch_text = "\n".join(mismatch)
        print(" mismatch:", mismatch_text)
        self.assertIn("benchmark=000300.SH beside the portfolio", mismatch_text)
        self.assertNotIn("committed inputs", mismatch_text)
        self.assertIn(_CODES, mismatch_text)


def _portfolio_steps(shares: str, portfolio: dict) -> list:
    """取数步加一条组合步。"""

    return [
        {
            "step_id": "step_1",
            "skill_name": "qt.ai.data.kline",
            "inputs": {"shares": shares, "freq": "d"},
        },
        {
            "step_id": "step_2",
            "skill_name": "qt.ai.hp.portfolio",
            "inputs": dict(portfolio),
        },
    ]


def _success(skill_name: str, metrics: dict) -> dict:
    """一步成功结果。"""

    return {
        "status": "success",
        "steps": [
            {
                "skill_name": skill_name,
                "result": {
                    "ok": True,
                    "skill_name": skill_name,
                    "metrics": dict(metrics),
                    "payload": {},
                },
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
