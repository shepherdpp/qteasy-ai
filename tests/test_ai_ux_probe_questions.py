# coding=utf-8
# ======================================
# File: test_ai_ux_probe_questions.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-07
# Desc:
# UX Probe 提问风格：标准原题不变，随机风格另起主题且不复读标准题。
# ======================================

"""UX Probe question-style tests — not a release gate."""

from __future__ import annotations

import json
import random
import unittest

from qteasy_ai.provider import FakeLLMProvider

from evals.ux_probe.loader import load_bundle
from evals.ux_probe.questions import (
    RandomSeries,
    TopicFocus,
    assign_focuses,
    load_topic_catalog,
    normalize_question_style,
    random_user_utterance,
)
from evals.ux_probe.report import render_markdown


class TestAiUxProbeQuestions(unittest.TestCase):
    """标准风格与随机风格的抽样、问句和报告。"""

    def test_normalize_question_style(self) -> None:
        """空值与别名收成 standard / random，其余拒绝。"""

        print("\n[TestAiUxProbeQuestions] 提问风格归一")
        standard = normalize_question_style("")
        random_style = normalize_question_style("random")
        print(" empty:", standard, "random:", random_style)
        self.assertEqual(standard, "standard")
        self.assertEqual(normalize_question_style("standard"), "standard")
        self.assertEqual(random_style, "random")
        with self.assertRaises(ValueError):
            normalize_question_style("freeform")

    def test_catalog_and_focus_avoid_scripted_topics(self) -> None:
        """官方主题可抽；同一种子稳定，且主主题避开该任务的标准题主场。"""

        print("\n[TestAiUxProbeQuestions] 主题抽样避开标准题主场")
        catalog = load_topic_catalog()
        ids = [row["id"] for row in catalog]
        print(" catalog:", ids)
        self.assertIn("backtest", ids)
        self.assertGreaterEqual(len(ids), 2)

        bundle = load_bundle()
        tasks = [
            bundle.tasks["ask_backtest_learn_v1"],
            bundle.tasks["ask_onboarding_v1"],
            bundle.tasks["ask_researcher_boundary_v1"],
        ]
        focuses = assign_focuses(
            catalog,
            [task.random_avoid_topics for task in tasks],
            random.Random(7),
        )
        again = assign_focuses(
            catalog,
            [task.random_avoid_topics for task in tasks],
            random.Random(7),
        )
        print(" focuses:", [(item.primary_id, item.extra_id) for item in focuses])
        self.assertEqual(focuses, again)
        primaries = [item.primary_id for item in focuses]
        self.assertEqual(len(set(primaries)), 3)
        for task, focus in zip(tasks, focuses):
            self.assertNotIn(focus.primary_id, set(task.random_avoid_topics))
            self.assertNotEqual(focus.primary_id, focus.extra_id)

    def test_random_opening_uses_new_theme_and_rejects_script(self) -> None:
        """第一轮记下新主题；模型若复读标准题，改用兜底句。"""

        print("\n[TestAiUxProbeQuestions] 随机开场不复读标准题")
        bundle = load_bundle()
        persona = bundle.personas["zhou_jie"]
        task = bundle.tasks["ask_backtest_learn_v1"]
        focus = TopicFocus(
            primary_id="data-downloading",
            primary_scope="DataSource、数据通道、有界下载",
            extra_id="capability",
            extra_scope="能力地图、Ask/Plan/Agent 分工",
        )
        series = RandomSeries(focus=focus)
        fresh = "下载历史行情会不会连上我的券商账户？"
        happy = FakeLLMProvider(replies=[
            json.dumps(
                {
                    "theme": "数据怎么下载到本地",
                    "goal": "搞懂下载边界，以及这和 Ask/Plan 怎么分工",
                    "text": fresh,
                },
                ensure_ascii=False,
            )
        ])
        text = random_user_utterance(
            happy,
            persona=persona,
            task=task,
            series=series,
            turn_index=0,
            turn_count=len(task.turns),
            prior_turns=[],
        )
        print(" opening:", text)
        print(" theme:", series.theme, "goal:", series.goal)
        self.assertEqual(text, fresh)
        self.assertEqual(series.theme, "数据怎么下载到本地")
        self.assertEqual(series.goal, "搞懂下载边界，以及这和 Ask/Plan 怎么分工")
        self.assertNotEqual(text, task.turns[0].text)

        copied = RandomSeries(focus=focus)
        echo = FakeLLMProvider(replies=[
            json.dumps(
                {
                    "theme": "数据怎么下载到本地",
                    "goal": "搞懂下载边界",
                    "text": task.turns[0].text,
                },
                ensure_ascii=False,
            )
        ])
        fallback = random_user_utterance(
            echo,
            persona=persona,
            task=task,
            series=copied,
            turn_index=0,
            turn_count=len(task.turns),
            prior_turns=[],
        )
        print(" fallback:", fallback)
        self.assertNotEqual(fallback, task.turns[0].text)
        self.assertIn("数据怎么下载到本地", fallback)
        self.assertEqual(copied.theme, "数据怎么下载到本地")

    def test_random_followup_stays_on_theme(self) -> None:
        """后续轮使用模型新问句，提示里带主题并禁止标准题。"""

        print("\n[TestAiUxProbeQuestions] 随机追问沿本轮主题")
        bundle = load_bundle()
        persona = bundle.personas["zhou_jie"]
        task = bundle.tasks["ask_backtest_learn_v1"]
        focus = TopicFocus(
            primary_id="data-downloading",
            primary_scope="有界下载",
            extra_id="capability",
            extra_scope="Ask/Plan 分工",
        )
        series = RandomSeries(focus=focus, theme="数据怎么下载到本地", goal="搞懂下载边界")
        follow = "那缺的日期是自动补，还是要我自己再说一次范围？"
        fake = FakeLLMProvider(replies=[follow])
        text = random_user_utterance(
            fake,
            persona=persona,
            task=task,
            series=series,
            turn_index=1,
            turn_count=len(task.turns),
            prior_turns=[{"query": "下载会连券商吗？", "answer": "不会连券商。"}],
        )
        print(" follow-up:", text)
        print(" prompt has theme:", "数据怎么下载到本地" in fake.prompts[0])
        self.assertEqual(text, follow)
        self.assertIn("数据怎么下载到本地", fake.prompts[0])
        self.assertIn(task.turns[0].text, fake.prompts[0])
        self.assertIn("周姐", fake.prompts[0])

    def test_random_followup_keeps_full_prior_answer(self) -> None:
        """追问提示带上超过 800 字的上一答全文，尾句不被截掉。"""

        print("\n[TestAiUxProbeQuestions] 追问保留上一答全文")
        bundle = load_bundle()
        persona = bundle.personas["zhou_jie"]
        task = bundle.tasks["ask_backtest_learn_v1"]
        focus = TopicFocus(
            primary_id="overview",
            primary_scope="模块如何串联",
            extra_id="optimize",
            extra_scope="优化解释",
        )
        series = RandomSeries(focus=focus, theme="模块怎么串", goal="看懂流水线")
        tail = "TAIL-MARKER-留痕靠自己抄日期。"
        long_answer = ("流水线从数据到回测。" * 80) + tail
        print(" prior answer chars:", len(long_answer))
        follow = "留痕那段你还没说完？"
        fake = FakeLLMProvider(replies=[follow])
        text = random_user_utterance(
            fake,
            persona=persona,
            task=task,
            series=series,
            turn_index=2,
            turn_count=len(task.turns),
            prior_turns=[{"query": "模块怎么串？", "answer": long_answer}],
        )
        print(" tail in prompt:", tail in fake.prompts[0])
        self.assertEqual(text, follow)
        self.assertGreater(len(long_answer), 800)
        self.assertIn(tail, fake.prompts[0])
        self.assertIn(long_answer, fake.prompts[0])

    def test_markdown_shows_random_theme(self) -> None:
        """随机风格的人读报告写出风格、本轮主题和覆盖主题。"""

        print("\n[TestAiUxProbeQuestions] 报告标出随机主题")
        md = render_markdown(
            {
                "generated_at": "2026-11-07T00:00:00Z",
                "current_product": "0.3-ask",
                "question_style": "random",
                "skipped": [],
                "runs": [
                    {
                        "persona": {
                            "id": "zhou_jie",
                            "display_name": "周姐",
                            "role": "半懂",
                        },
                        "task": {
                            "id": "ask_backtest_learn_v1",
                            "goal": "搞懂下载边界",
                            "theme": "数据怎么下载到本地",
                            "topics": [
                                {"id": "data-downloading", "scope": "有界下载"},
                                {"id": "capability", "scope": "Ask/Plan 分工"},
                            ],
                        },
                        "transcript": {"turns": []},
                        "judge": {
                            "auto_scores": {},
                            "summary": "",
                            "journey_summary": {},
                            "persona_voice": {},
                            "friction": [],
                            "suggested_fixes": [],
                        },
                    }
                ],
            }
        )
        print(" style line:", [line for line in md.splitlines() if "提问风格" in line])
        self.assertIn("随机（新主题）", md)
        self.assertIn("**本轮主题：** 数据怎么下载到本地", md)
        self.assertIn("data-downloading（有界下载）", md)
        self.assertIn("capability（Ask/Plan 分工）", md)


if __name__ == "__main__":
    unittest.main()
