# coding=utf-8
# ======================================
# File: test_ai_04_b1_hold_compare.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-08
# Desc:
# 0.4 B1：持有对比 research.hold_compare。
# 一条组合，可选并列基准或超额。
# ======================================

import json
import math
import os
import tempfile
import unittest

import numpy as np
import pandas as pd

from qteasy.history import HistoryPanel
from qteasy_ai.app import build_default_registry
from qteasy_ai.executor import PlanExecutor
from qteasy_ai.intents import IntentCatalog
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.session import ConversationState
from qteasy_ai.skills.data_kline import build_data_kline_skill
from qteasy_ai.skills.hp_plot import build_hp_plot_skill
from qteasy_ai.skills.hp_study import (
    build_hp_cum_return_skill,
    build_hp_normalize_skill,
    build_hp_portfolio_skill,
)

_GOLD_TAG = "000001.SZ 和 000002.SZ 做一条等权组合，相对沪深300"
_GOLD_CUM = "000001.SZ 和 000002.SZ 按权重 6:4 做一条组合，看累计收益"
_BANNED = ("backtest", "refill", "codegen", "live", "optimize")
_FACTOR_SLOTS = ["shares", "start", "end", "factor_htype", "return_htype"]


def _pending(plan):
    """澄清卡上的 pending。"""

    blob = (plan.assumptions or {}).get("clarification") or {}
    return [item for item in (blob.get("pending") or []) if isinstance(item, dict)]


def _pending_names(plan):
    """pending 槽名。"""

    return [str(item.get("name") or "") for item in _pending(plan)]


def _skills(plan):
    """步骤技能名。"""

    return [step.skill_name for step in plan.steps]


def _panel(values, shares, dates, columns) -> HistoryPanel:
    """用已知数字做一块面板。values 形状是 (标的, 日期, 列)。"""

    return HistoryPanel(
        values=np.asarray(values, dtype=float),
        levels=list(shares),
        rows=pd.to_datetime(list(dates)),
        columns=list(columns),
    )


def _series(panel: HistoryPanel, share: str) -> list:
    """一个标的、第一列，按时间展开。"""

    index = list(panel.shares).index(share)
    column = np.asarray(panel.values[index, :, 0], dtype=float)
    return [float(item) for item in column]


def _flat(panel: HistoryPanel) -> list:
    """按标的、日期、列展开。非有限数记成 None。"""

    out = []
    for item in np.asarray(panel.values, dtype=float).reshape(-1):
        out.append(None if not np.isfinite(item) else float(item))
    return out


def _near(left, right) -> bool:
    """两边都有限且足够接近。"""

    if len(left) != len(right):
        return False
    return all(math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-8) for a, b in zip(left, right))


class TestAi04B1HoldCompare(unittest.TestCase):
    """持有对比：一条组合，基准可并列或只留超额。"""

    def setUp(self) -> None:
        self.registry = build_default_registry()
        self.planner = Planner(self.registry, env_facts={})

    def test_gold_enters_and_catalog_stays(self) -> None:
        """两条金句是同一个 Job。默认对齐到 1，说了累计收益就换成简单累计。"""

        print("\n[TestAi04B1] 金句进门，目录不另写槽")
        tag = self.planner.build_plan(_GOLD_TAG, mode="plan")
        cum = self.planner.build_plan(_GOLD_CUM, mode="plan")
        catalog = IntentCatalog()
        factor_names = [str(row.get("name") or "") for row in catalog.job_slots("research.factor_ic")]
        print(" tag job:", tag.planner_trace.get("intent_job"), _skills(tag))
        print(" tag depends:", [list(step.depends_on) for step in tag.steps])
        print(" cum job:", cum.planner_trace.get("intent_job"), _skills(cum))
        print(" cum depends:", [list(step.depends_on) for step in cum.steps])
        print(" max_steps:", catalog.legal_max_steps())
        print(" hold slots:", catalog.job_slots("research.hold_compare"))
        print(" factor slots:", factor_names)
        self.assertEqual(tag.planner_trace.get("intent_job"), "research.hold_compare")
        self.assertEqual(cum.planner_trace.get("intent_job"), "research.hold_compare")
        self.assertEqual(
            _skills(tag),
            ["qt.ai.data.kline", "qt.ai.hp.portfolio", "qt.ai.hp.normalize", "qt.ai.hp.plot"],
        )
        self.assertEqual(
            _skills(cum),
            ["qt.ai.data.kline", "qt.ai.hp.portfolio", "qt.ai.hp.cum_return", "qt.ai.hp.plot"],
        )
        self.assertEqual(cum.steps[2].inputs.get("method"), "simple")
        self.assertNotIn("htypes", cum.steps[2].inputs)
        for plan in (tag, cum):
            ids = [step.step_id for step in plan.steps]
            names = " ".join(_skills(plan))
            print(" chain:", names)
            for banned in _BANNED:
                self.assertNotIn(banned, names)
            if plan is tag:
                self.assertNotIn("qt.ai.hp.cum_return", names)
            if "qt.ai.hp.cum_return" in _skills(plan):
                self.assertNotIn("qt.ai.hp.normalize", _skills(plan))
            for step in plan.steps:
                for dep in step.depends_on:
                    self.assertLess(ids.index(dep), ids.index(step.step_id))
        self.assertEqual(catalog.legal_max_steps(), 3)
        self.assertEqual(catalog.job_slots("research.hold_compare"), [])
        self.assertEqual(factor_names, _FACTOR_SLOTS)

    def test_who_is_stronger_stays_unresolved(self) -> None:
        """谁更强不是持有对比，澄清卡里也没有 supported_skill。"""

        print("\n[TestAi04B1] 谁更强留在恢复卡")
        for query in ("谁更强", "相对沪深300谁更强"):
            plan = self.planner.build_plan(query, mode="plan")
            prompt = str((plan.assumptions.get("clarification") or {}).get("confirm_prompt") or "")
            print(" query:", query)
            print(" job:", plan.planner_trace.get("intent_job"))
            print(" pending:", _pending_names(plan))
            print(" missing:", plan.steps[0].inputs.get("missing_info"))
            print(" prompt:", prompt)
            self.assertNotEqual(plan.planner_trace.get("intent_job"), "research.hold_compare")
            self.assertNotIn("supported_skill", _pending_names(plan))
            self.assertNotEqual(plan.steps[0].inputs.get("missing_info"), "supported_skill")
            self.assertNotIn("supported_skill", prompt)

    def test_tag_along_normalize_and_cumret_numbers(self) -> None:
        """并列基准不进等权。对齐到 1 与简单累计收益分开，不叠在一起。"""

        print("\n[TestAi04B1] 并列基准的组合、归一化、累计收益")
        tag = self.planner.build_plan(_GOLD_TAG, mode="plan")
        cum = self.planner.build_plan(_GOLD_CUM, mode="plan")
        print(" benchmark:", tag.steps[1].inputs.get("benchmark"))
        print(" weights:", tag.steps[1].inputs.get("weights"))
        print(" output:", tag.steps[1].inputs.get("benchmark_output"))
        print(" cum skills:", _skills(cum))
        self.assertEqual(tag.steps[1].inputs.get("benchmark"), "000300.SH")
        self.assertNotIn("weights", tag.steps[1].inputs)
        self.assertNotIn("000300.SH", tag.steps[1].inputs.get("weights") or [])

        panel = _panel(
            [[[10.0], [12.0]], [[30.0], [18.0]]],
            ["A", "B"],
            ["2024-01-02", "2024-01-03"],
            ["close"],
        )
        portfolio = build_hp_portfolio_skill()[1]
        tagged = portfolio(
            benchmark="B",
            benchmark_output="tag_along",
            upstream_payload={"panel": panel},
        )
        tagged_panel = tagged["payload"]["panel"]
        portfolio_close = _series(tagged_panel, "PORTFOLIO")
        benchmark_close = _series(tagged_panel, "B")
        print(" portfolio close:", portfolio_close, "hand:", [10.0, 12.0])
        print(" benchmark close:", benchmark_close)
        self.assertTrue(tagged["ok"])
        self.assertTrue(_near(portfolio_close, [10.0, 12.0]))
        self.assertFalse(_near(portfolio_close, [20.0, 15.0]))

        normalized = build_hp_normalize_skill()[1](upstream_payload={"panel": tagged_panel})
        norm_panel = normalized["payload"]["panel"]
        norm_portfolio = _series(norm_panel, "PORTFOLIO")
        norm_benchmark = _series(norm_panel, "B")
        print(" norm portfolio:", norm_portfolio, "hand:", [1.0, 1.2])
        print(" norm benchmark:", norm_benchmark, "hand:", [1.0, 0.6])
        print(" norm htypes:", list(norm_panel.htypes))
        self.assertTrue(normalized["ok"])
        self.assertNotIn("htypes", tag.steps[2].inputs)
        self.assertTrue(_near(norm_portfolio, [1.0, 1.2]))
        self.assertTrue(_near(norm_benchmark, [1.0, 0.6]))

        returned = build_hp_cum_return_skill()[1](
            method="simple",
            upstream_payload={"panel": tagged_panel},
        )
        returned_portfolio = _series(returned["payload"]["panel"], "PORTFOLIO")
        print(" cumret portfolio:", returned_portfolio, "hand:", [0.0, 0.2])
        print(" cum skills have normalize:", "qt.ai.hp.normalize" in _skills(cum))
        self.assertTrue(returned["ok"])
        self.assertTrue(_near(returned_portfolio, [0.0, 0.2]))
        self.assertNotIn("qt.ai.hp.normalize", _skills(cum))

    def test_excess_plots_raw_series(self) -> None:
        """超额直接留下 excess_close。负超额不归一化；正超额的累计收益是 [0, 2]。"""

        print("\n[TestAi04B1] 超额直接画 excess_close")
        raw = self.planner.build_plan(
            "000001.SZ 和 000002.SZ 做一条等权组合，相对沪深300，看超额",
            mode="plan",
        )
        both = self.planner.build_plan(
            "000001.SZ 和 000002.SZ 做一条等权组合，相对沪深300，看超额和累计收益",
            mode="plan",
        )
        print(" raw skills:", _skills(raw))
        print(" raw output:", raw.steps[1].inputs.get("benchmark_output"))
        print(" both skills:", _skills(both))
        print(" both htypes:", both.steps[2].inputs.get("htypes"), both.steps[2].inputs.get("method"))
        self.assertEqual(_skills(raw), ["qt.ai.data.kline", "qt.ai.hp.portfolio", "qt.ai.hp.plot"])
        self.assertNotIn("qt.ai.hp.normalize", _skills(raw))
        self.assertEqual(raw.steps[1].inputs.get("benchmark_output"), "excess_only")
        self.assertEqual(
            _skills(both),
            ["qt.ai.data.kline", "qt.ai.hp.portfolio", "qt.ai.hp.cum_return", "qt.ai.hp.plot"],
        )
        self.assertEqual(both.steps[2].inputs.get("htypes"), "excess_close")
        self.assertEqual(both.steps[2].inputs.get("method"), "simple")

        losing = _panel(
            [[[10.0], [12.0]], [[30.0], [18.0]]],
            ["A", "B"],
            ["2024-01-02", "2024-01-03"],
            ["close"],
        )
        portfolio = build_hp_portfolio_skill()[1]
        excess = portfolio(
            benchmark="B",
            benchmark_output="excess_only",
            upstream_payload={"panel": losing},
        )
        excess_panel = excess["payload"]["panel"]
        drawn = _flat(excess_panel)
        print(" excess column:", list(excess_panel.htypes), drawn, "hand:", [-20.0, -6.0])
        self.assertTrue(excess["ok"])
        self.assertEqual(list(excess_panel.htypes), ["excess_close"])
        self.assertEqual(list(excess_panel.shares), ["PORTFOLIO"])
        self.assertTrue(_near(drawn, [-20.0, -6.0]))
        self.assertFalse(_near(drawn, [1.0, 0.3]))

        winning = _panel(
            [[[12.0], [18.0]], [[10.0], [12.0]]],
            ["A", "B"],
            ["2024-01-02", "2024-01-03"],
            ["close"],
        )
        ahead = portfolio(
            benchmark="B",
            benchmark_output="excess_only",
            upstream_payload={"panel": winning},
        )
        ahead_panel = ahead["payload"]["panel"]
        ahead_values = _flat(ahead_panel)
        print(" positive excess:", ahead_values, "hand:", [2.0, 6.0])
        returned = build_hp_cum_return_skill()[1](
            htypes="excess_close",
            method="simple",
            upstream_payload={"panel": ahead_panel},
        )
        returned_values = _flat(returned["payload"]["panel"])
        print(" positive cumret:", list(returned["payload"]["panel"].htypes), returned_values, "hand:", [0.0, 2.0])
        self.assertTrue(_near(ahead_values, [2.0, 6.0]))
        self.assertTrue(returned["ok"])
        self.assertTrue(_near(returned_values, [0.0, 2.0]))

        negative = _panel(
            [[[-20.0], [-6.0]]],
            ["PORTFOLIO"],
            ["2024-01-02", "2024-01-03"],
            ["excess_close"],
        )
        empty = build_hp_cum_return_skill()[1](
            htypes="excess_close",
            method="simple",
            upstream_payload={"panel": negative},
        )
        empty_values = _flat(empty["payload"]["panel"])
        print(" negative cumret:", empty_values)
        self.assertTrue(empty["ok"])
        self.assertTrue(all(item is None for item in empty_values))

    def test_late_benchmark_joins_shares(self) -> None:
        """说了超额却没有基准代码才追问。回答后再并进 shares，并补占位权重。"""

        print("\n[TestAi04B1] 后补基准并进 shares")
        asked = "000001.SZ 和 000002.SZ 按权重 6:4 做一条组合，看超额"
        waiting = self.planner.build_plan(asked, mode="plan")
        print(" pending:", _pending_names(waiting))
        print(" missing:", waiting.steps[0].inputs.get("missing_info"))
        self.assertEqual(_pending_names(waiting), ["benchmark"])

        state = ConversationState.empty("b1-benchmark")
        state.start_task(query=asked, job="research.hold_compare")
        state.set_slot("benchmark", "000300.SH", source="user", confirmed=True)
        followed = self.planner.build_plan("000300.SH", session=state, skip_classify=True)
        kline = followed.steps[0].inputs
        portfolio = followed.steps[1].inputs
        codes = str(kline.get("shares") or "").split(",")
        weights = list(portfolio.get("weights") or [])
        print(" skills:", _skills(followed))
        print(" shares:", codes)
        print(" benchmark:", portfolio.get("benchmark"))
        print(" weights:", weights)
        self.assertEqual(followed.planner_trace.get("intent_job"), "research.hold_compare")
        self.assertIn("000300.SH", codes)
        self.assertIn("000001.SZ", codes)
        self.assertIn("000002.SZ", codes)
        self.assertEqual(portfolio.get("benchmark"), "000300.SH")
        self.assertEqual(len(weights), len(codes))
        bench_at = codes.index("000300.SH")
        print(" placeholder index:", bench_at, "value:", weights[bench_at])
        self.assertTrue(math.isclose(float(weights[bench_at]), 0.0, rel_tol=0.0, abs_tol=1e-8))
        self.assertNotIn("000300.SH", weights)
        self.assertTrue(_near([weights[0], weights[1]], [6.0, 4.0]))

    def test_optional_slots_model_and_other_jobs(self) -> None:
        """权重和基准不追问。6:4 只在组合步写成 weighted。别的 Job 不出现折叠槽。"""

        print("\n[TestAi04B1] 可选槽、模型填槽、体检与导出")
        bare = self.planner.build_plan("000001.SZ 和 000002.SZ 做一条等权组合", mode="plan")
        weighted = self.planner.build_plan(_GOLD_CUM, mode="plan")
        mixed = self.planner.build_plan("000001.SZ 和 000300.SH 做一条等权组合", mode="plan")
        summary = self.planner.build_plan("波动率", mode="plan")
        export = self.planner.build_plan("导出", mode="plan")
        print(" bare pending:", _pending_names(bare))
        print(" weights:", weighted.steps[1].inputs.get("weights"))
        print(" modes:", [(step.skill_name, step.inputs.get("mode")) for step in weighted.steps])
        print(" mixed asset:", mixed.steps[0].inputs.get("asset_type"))
        print(" summary pending:", _pending_names(summary))
        print(" export pending:", _pending_names(export))
        self.assertNotIn("weights", _pending_names(bare))
        self.assertNotIn("benchmark", _pending_names(bare))
        self.assertTrue(_near(list(weighted.steps[1].inputs.get("weights") or []), [6.0, 4.0]))
        self.assertEqual(weighted.steps[1].inputs.get("mode"), "weighted")
        for step in weighted.steps:
            if step.skill_name != "qt.ai.hp.portfolio":
                self.assertNotIn("mode", step.inputs)
        self.assertNotIn(mixed.steps[0].inputs.get("asset_type"), ("E", "IDX"))
        self.assertNotIn("adj", _pending_names(summary))
        self.assertNotIn("benchmark_output", _pending_names(summary))
        self.assertNotIn("adj", _pending_names(export))
        self.assertNotIn("benchmark_output", _pending_names(export))

        fake = FakeLLMProvider(
            replies=[
                json.dumps({"job": "research.hold_compare"}, ensure_ascii=False),
                json.dumps(
                    {
                        "shares": "000001.SZ,000300.SH",
                        "asset_type": "E",
                        "page": 1,
                        "mode": "weighted",
                        "supported_skill": "x",
                        "htypes": "close",
                        "layout": "auto",
                        "rows": 5,
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        canned = Planner(self.registry, provider=fake, env_facts={}).build_plan("做一条等权组合", mode="plan")
        blob = json.dumps([dict(step.inputs) for step in canned.steps], ensure_ascii=False)
        print(" canned skills:", _skills(canned))
        print(" canned inputs:", blob)
        self.assertEqual(canned.steps[0].inputs.get("shares"), "000001.SZ,000300.SH")
        self.assertNotIn(canned.steps[0].inputs.get("asset_type"), ("E", "IDX"))
        self.assertNotIn("supported_skill", blob)
        self.assertNotIn('"page"', blob)
        self.assertNotIn('"mode"', blob)
        self.assertNotIn('"htypes"', blob)
        self.assertNotIn('"layout"', blob)
        self.assertNotIn('"rows"', blob)

    def test_kline_shares_and_one_png(self) -> None:
        """问句里的代码只进 K 线。默认链归一化有数，出图一张且不交互。"""

        print("\n[TestAi04B1] 取数代码与一张 PNG")
        plan = self.planner.build_plan(_GOLD_TAG, mode="plan")
        shares = str(plan.steps[0].inputs.get("shares") or "")
        plot_shares = plan.steps[3].inputs.get("shares")
        print(" kline shares:", shares)
        print(" plot shares:", plot_shares)
        for code in ("000001.SZ", "000002.SZ", "000300.SH"):
            self.assertIn(code, shares)
        self.assertEqual(plan.steps[0].skill_name, "qt.ai.data.kline")
        self.assertIn(plot_shares, (None, ""))

        panel = _panel(
            [[[10.0], [12.0]], [[30.0], [18.0]]],
            ["A", "B"],
            ["2024-01-02", "2024-01-03"],
            ["close"],
        )
        tagged = build_hp_portfolio_skill()[1](
            benchmark="B",
            benchmark_output="tag_along",
            upstream_payload={"panel": panel},
        )
        normalized = build_hp_normalize_skill()[1](
            upstream_payload={"panel": tagged["payload"]["panel"]},
        )
        values = _flat(normalized["payload"]["panel"])
        print(" normalized:", values, "hand portfolio:", [1.0, 1.2], "hand benchmark:", [1.0, 0.6])
        self.assertTrue(normalized["ok"])
        self.assertTrue(any(item is not None for item in values))
        self.assertFalse(all(item is None for item in values))
        self.assertTrue(_near(values, [1.0, 1.2, 1.0, 0.6]))

        handler = build_hp_plot_skill()[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "hold.png")
            plotted = handler(
                interactive=True,
                output_path=path,
                upstream_payload={"panel": normalized["payload"]["panel"]},
            )
            print(
                " plot ok:",
                plotted["ok"],
                "page_count:",
                plotted["metrics"]["page_count"],
                "interactive:",
                plotted["inputs_echo"].get("interactive"),
                "artifacts:",
                plotted.get("artifacts"),
            )
            self.assertTrue(plotted["ok"])
            self.assertEqual(len(plotted["artifacts"]), 1)
            self.assertEqual(plotted["metrics"]["page_count"], 1)
            self.assertFalse(plotted["inputs_echo"].get("interactive"))
            self.assertTrue(str(plotted["artifacts"][0]["path"]).endswith(".png"))
            self.assertTrue(os.path.isfile(plotted["artifacts"][0]["path"]))

    def test_unparsed_weights_and_benchmark_are_asked(self) -> None:
        """加权没收到数字就追问。基准写在代码后面要能收下；没收下且代码里有指数就追问。"""

        print("\n[TestAi04B1] 权重和基准不再静默算错")
        percent = self.planner.build_plan(
            "000001.SZ 和 000002.SZ 按权重 60%,40% 做一条组合",
            mode="plan",
        )
        ratio = self.planner.build_plan(
            "000001.SZ 和 000002.SZ 加权组合 6比4",
            mode="plan",
        )
        bare = self.planner.build_plan("000001.SZ 和 000002.SZ 做一条加权组合", mode="plan")
        leading = self.planner.build_plan(
            "000001.SZ 和 000002.SZ 做一条等权组合，以 000300.SH 为基准",
            mode="plan",
        )
        named = self.planner.build_plan(
            "000001.SZ 和 000002.SZ 做一条等权组合，基准是沪深300",
            mode="plan",
        )
        unclear = self.planner.build_plan(
            "000001.SZ 和 000300.SH 做一条等权组合，请说明基准",
            mode="plan",
        )
        print(" percent weights:", percent.steps[1].inputs.get("weights"), _pending_names(percent))
        print(" ratio weights:", ratio.steps[1].inputs.get("weights"), _pending_names(ratio))
        print(" bare pending:", _pending_names(bare))
        print(" leading benchmark:", leading.steps[1].inputs.get("benchmark"), leading.steps[1].inputs.get("benchmark_output"))
        print(" named benchmark:", named.steps[1].inputs.get("benchmark"), named.steps[0].inputs.get("shares"))
        print(" unclear pending:", _pending_names(unclear), unclear.steps[0].skill_name)
        self.assertTrue(_near(list(percent.steps[1].inputs.get("weights") or []), [60.0, 40.0]))
        self.assertEqual(percent.steps[1].inputs.get("mode"), "weighted")
        self.assertNotIn("weights", _pending_names(percent))
        self.assertTrue(_near(list(ratio.steps[1].inputs.get("weights") or []), [6.0, 4.0]))
        self.assertEqual(ratio.steps[1].inputs.get("mode"), "weighted")
        self.assertEqual(_pending_names(bare), ["weights"])
        self.assertEqual(leading.steps[1].inputs.get("benchmark"), "000300.SH")
        self.assertEqual(leading.steps[1].inputs.get("benchmark_output"), "tag_along")
        self.assertIn("000300.SH", str(leading.steps[0].inputs.get("shares") or ""))
        self.assertEqual(named.steps[1].inputs.get("benchmark"), "000300.SH")
        self.assertEqual(named.steps[1].inputs.get("benchmark_output"), "tag_along")
        self.assertEqual(unclear.steps[0].skill_name, "qt.ai.system.fallback")
        self.assertEqual(_pending_names(unclear), ["benchmark"])

    def test_confirmed_output_and_open_plan_stay(self) -> None:
        """卡上已经写的超额输出不被问句改回去。开放计划里的归一化保留。"""

        print("\n[TestAi04B1] 已确认的超额输出，以及开放计划")
        keep_excess = ConversationState.empty("b1-keep-excess")
        keep_excess.start_task(
            query="000001.SZ 和 000002.SZ 做一条等权组合，相对沪深300",
            job="research.hold_compare",
        )
        keep_excess.set_slot("benchmark_output", "excess_only", source="user", confirmed=True)
        excess_plan = self.planner.build_plan("好", session=keep_excess, skip_classify=True)
        keep_tag = ConversationState.empty("b1-keep-tag")
        keep_tag.start_task(
            query="000001.SZ 和 000002.SZ 做一条等权组合，相对沪深300，看超额",
            job="research.hold_compare",
        )
        keep_tag.set_slot("benchmark_output", "tag_along", source="user", confirmed=True)
        tag_plan = self.planner.build_plan("好", session=keep_tag, skip_classify=True)
        print(" card excess skills:", _skills(excess_plan), excess_plan.steps[1].inputs.get("benchmark_output"))
        print(" card tag skills:", _skills(tag_plan), tag_plan.steps[1].inputs.get("benchmark_output"))
        self.assertEqual(excess_plan.steps[1].inputs.get("benchmark_output"), "excess_only")
        self.assertNotIn("qt.ai.hp.normalize", _skills(excess_plan))
        self.assertEqual(tag_plan.steps[1].inputs.get("benchmark_output"), "tag_along")

        opened = [
            {
                "skill_name": "qt.ai.data.kline",
                "inputs": {"shares": "000001.SZ,000002.SZ,000300.SH"},
                "depends_on": [],
            },
            {
                "skill_name": "qt.ai.hp.portfolio",
                "inputs": {"benchmark": "000300.SH", "benchmark_output": "tag_along"},
                "depends_on": ["step_1"],
            },
            {
                "skill_name": "qt.ai.hp.normalize",
                "inputs": {},
                "depends_on": ["step_2"],
            },
        ]
        fake = FakeLLMProvider(replies=[json.dumps({"steps": opened}, ensure_ascii=False)])
        open_plan = Planner(self.registry, provider=fake, env_facts={}).build_plan(
            "000001.SZ 和 000002.SZ 看超额",
            mode="plan",
            forced_job="open",
        )
        print(" open skills:", _skills(open_plan))
        print(" open output:", open_plan.steps[1].inputs.get("benchmark_output"))
        self.assertEqual(
            _skills(open_plan),
            ["qt.ai.data.kline", "qt.ai.hp.portfolio", "qt.ai.hp.normalize"],
        )
        self.assertEqual(open_plan.steps[1].inputs.get("benchmark_output"), "tag_along")

    def test_executor_runs_planned_inputs(self) -> None:
        """假取数按计划跑到出图。补过占位的权重和并列基准都进原子。"""

        print("\n[TestAi04B1] 执行器跑完计划里的输入")
        book = {
            "000001.SZ": [10.0, 12.0],
            "000002.SZ": [30.0, 18.0],
            "000300.SH": [40.0, 20.0],
        }

        def _fake_kline(**kwargs):
            codes = [item.strip() for item in str(kwargs.get("shares") or "").split(",") if item.strip()]
            print(" fetched:", codes)
            frames = {}
            for code in codes:
                close = np.asarray(book[code], dtype=float)
                index = pd.date_range("2024-01-02", periods=len(close), freq="D")
                index.name = "date"
                frames[code] = pd.DataFrame(
                    {
                        "open": close,
                        "high": close,
                        "low": close,
                        "close": close,
                        "vol": np.full(len(close), 1.0),
                    },
                    index=index,
                )
            return frames

        meta, handler = build_data_kline_skill(get_kline_func=_fake_kline)
        self.registry._impl[meta.name] = handler

        def _run(query: str) -> dict:
            plan = self.planner.build_plan(query, mode="plan")
            plan.execution_mode = "execute"
            print(" plan skills:", _skills(plan))
            print(" plan weights:", plan.steps[1].inputs.get("weights"))
            print(" plan benchmark:", plan.steps[1].inputs.get("benchmark"), plan.steps[1].inputs.get("benchmark_output"))
            with tempfile.TemporaryDirectory() as temp_dir:
                executor = PlanExecutor(self.registry, memory_store=MemoryStore(base_dir=temp_dir))
                return executor.execute(plan, confirm=True)

        equal = _run(_GOLD_TAG)
        equal_steps = equal["execution"]["steps"]
        equal_panel = equal_steps[1]["result"]["payload"]["panel"]
        equal_portfolio = _series(equal_panel, "PORTFOLIO")
        equal_benchmark = _series(equal_panel, "000300.SH")
        equal_plot = equal_steps[-1]["result"]
        print(" equal portfolio:", equal_portfolio, "hand:", [20.0, 15.0])
        print(" equal benchmark:", equal_benchmark, "hand:", [40.0, 20.0])
        print(" equal plot:", equal_plot.get("metrics"), equal_plot.get("artifacts"))
        self.assertTrue(equal_steps[1]["result"]["ok"])
        self.assertEqual(list(equal_panel.htypes), ["close"])
        self.assertTrue(_near(equal_portfolio, [20.0, 15.0]))
        self.assertTrue(_near(equal_benchmark, [40.0, 20.0]))
        self.assertFalse(_near(equal_portfolio, [26.66666667, 16.66666667]))
        self.assertEqual(equal_plot["metrics"]["page_count"], 1)
        self.assertEqual(len(equal_plot["artifacts"]), 1)
        self.assertFalse(equal_plot["inputs_echo"].get("interactive"))
        self.assertTrue(os.path.isfile(equal_plot["artifacts"][0]["path"]))

        book["000001.SZ"] = [10.0, 12.0]
        book["000002.SZ"] = [20.0, 30.0]
        book["000300.SH"] = [30.0, 18.0]
        weighted = _run("000001.SZ 和 000002.SZ 按权重 6:4 做一条组合，相对沪深300")
        weighted_steps = weighted["execution"]["steps"]
        weighted_panel = weighted_steps[1]["result"]["payload"]["panel"]
        weighted_portfolio = _series(weighted_panel, "PORTFOLIO")
        weighted_benchmark = _series(weighted_panel, "000300.SH")
        print(" weighted portfolio:", weighted_portfolio, "hand:", [14.0, 19.2])
        print(" weighted benchmark:", weighted_benchmark, "hand:", [30.0, 18.0])
        self.assertTrue(_near(list(weighted["plan"]["steps"][1]["inputs"].get("weights") or []), [6.0, 4.0, 0.0]))
        self.assertTrue(_near(weighted_portfolio, [14.0, 19.2]))
        self.assertFalse(_near(weighted_portfolio, [15.0, 21.0]))
        self.assertTrue(_near(weighted_benchmark, [30.0, 18.0]))
        self.assertEqual(weighted_steps[-1]["result"]["metrics"]["page_count"], 1)
        self.assertEqual(len(weighted_steps[-1]["result"]["artifacts"]), 1)


if __name__ == "__main__":
    unittest.main()
