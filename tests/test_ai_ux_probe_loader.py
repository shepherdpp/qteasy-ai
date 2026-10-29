# coding=utf-8
# ======================================
# File: test_ai_ux_probe_loader.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-29
# Desc:
# UX Probe YAML 加载与任务筛选（非关单闸门；仅防骨架退步）。
# ======================================

"""UX Probe loader smoke tests — not a release gate."""

from __future__ import annotations

import unittest
from pathlib import Path

from evals.ux_probe.loader import DEFAULT_PRODUCT, load_bundle, meets_min_product
from evals.ux_probe.report import render_markdown
from evals.ux_probe.runner import select_tasks


class TestAiUxProbeLoader(unittest.TestCase):
    """画像/任务/量规骨架与 min_product 跳过逻辑。"""

    def test_bundle_seeds_three_personas_and_skips_wow(self) -> None:
        """三画像就位；0.4 Wow 任务在 0.3 地板下跳过。"""

        print("\n[TestAiUxProbeLoader] 加载 YAML 并筛选任务")
        bundle = load_bundle()
        print(" personas:", sorted(bundle.personas))
        print(" tasks:", sorted(bundle.tasks))
        self.assertEqual(
            sorted(bundle.personas),
            ["chen_yan", "lin_xiaoman", "zhou_jie"],
        )
        self.assertIn("ask_onboarding_v1", bundle.tasks)
        self.assertIn("ask_backtest_learn_v1", bundle.tasks)
        self.assertIn("ask_researcher_boundary_v1", bundle.tasks)
        self.assertIn("ask_wow_hp_timing_v1", bundle.tasks)
        self.assertTrue(bundle.rubrics.dimensions)
        self.assertTrue(bundle.rubrics.judge_instructions)

        selected, skipped = select_tasks(bundle, current_product=DEFAULT_PRODUCT)
        selected_ids = [item.id for item in selected]
        skipped_ids = [item["task_id"] for item in skipped]
        print(" selected:", selected_ids)
        print(" skipped:", skipped)
        self.assertIn("ask_onboarding_v1", selected_ids)
        self.assertIn("ask_wow_hp_timing_v1", skipped_ids)
        self.assertFalse(meets_min_product("0.4-wow", "0.3-ask"))
        self.assertTrue(meets_min_product("0.3-ask", "0.3-ask"))

    def test_markdown_report_marks_not_a_gate(self) -> None:
        """人读报告标明非关单。"""

        print("\n[TestAiUxProbeLoader] 报告模板非关单声明")
        md = render_markdown(
            {
                "generated_at": "2026-10-29T00:00:00Z",
                "current_product": "0.3-ask",
                "skipped": [{"task_id": "ask_wow_hp_timing_v1", "reason": "min_product"}],
                "runs": [],
            }
        )
        print(" markdown head:", md.splitlines()[:6])
        self.assertIn("非关单", md)
        self.assertIn("ask_wow_hp_timing_v1", md)

    def test_markdown_report_includes_journey_and_persona_voice(self) -> None:
        """人读报告含旅程摘要与第一人称主观（继续用/推荐）。"""

        print("\n[TestAiUxProbeLoader] 报告含 journey_summary / persona_voice")
        md = render_markdown(
            {
                "generated_at": "2026-10-29T12:00:00Z",
                "current_product": "0.3-ask",
                "skipped": [],
                "runs": [
                    {
                        "persona": {
                            "id": "lin_xiaoman",
                            "display_name": "林小满",
                            "role": "初学者",
                        },
                        "task": {
                            "id": "ask_onboarding_v1",
                            "goal": "搞懂不会自动真下单",
                        },
                        "transcript": {"turns": []},
                        "judge": {
                            "auto_scores": {"plain_language": 3},
                            "jackie_scores": {},
                            "summary": "边界讲清，术语仍偏多",
                            "journey_summary": {
                                "asked": "会不会拿我的钱买股票；回测是啥",
                                "answered": "不会真下单；回测=拿过去练一遍",
                                "goal_met": "partial",
                                "note": "安全边界清楚，术语仍硌人",
                            },
                            "persona_voice": {
                                "narrative": "我听懂了不会偷下单，但半路冒出一堆英文词，心里还是紧。",
                                "continue_use": "犹豫",
                                "recommend": "不愿意",
                            },
                            "friction": [],
                            "suggested_fixes": ["writer：初学禁出 allow_live"],
                        },
                    }
                ],
            }
        )
        print(" md snippet:\n", "\n".join(md.splitlines()[8:28]))
        self.assertIn("### 旅程摘要", md)
        self.assertIn("会不会拿我的钱买股票", md)
        self.assertIn("部分达到", md)
        self.assertIn("### 虚拟用户主观（林小满 · 第一人称）", md)
        self.assertIn("还愿不愿意继续用", md)
        self.assertIn("犹豫", md)
        self.assertIn("愿不愿意推荐给朋友", md)
        self.assertIn("不愿意", md)


if __name__ == "__main__":
    unittest.main()
