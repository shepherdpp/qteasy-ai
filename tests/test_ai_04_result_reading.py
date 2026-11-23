# coding=utf-8
# ======================================
# File: test_ai_04_result_reading.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-19
# Desc:
# 第八步：结果解读只引用记录。非法原文进入生成函数后整段换成模板。
# ======================================

import copy
import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.result_reading import reading_corpus, reading_template, write_result_reading

_QUESTION = "顺便问超额会变成什么"
_GROUNDED = "Fetched 000300.SH. n_rows = 4."
_ILLEGAL = "超额是 4.2%。"


def _plan(user_query: str, questions: list = None) -> dict:
    """一只指数的取数计划。"""

    assumptions = {}
    if questions:
        assumptions["parse_record"] = {"questions": list(questions)}
    return {
        "plan_id": "plan_read",
        "user_query": user_query,
        "steps": [
            {
                "step_id": "s1",
                "skill_name": "qt.ai.data.kline",
                "inputs": {"shares": "000300.SH", "freq": "d"},
            }
        ],
        "assumptions": assumptions,
    }


def _execution(status: str = "success", error: str = "") -> dict:
    """取数记录。成功时只有行数，没有总账。"""

    result = {"ok": status == "success", "metrics": {"n_rows": 4}}
    if error:
        result = {"ok": False, "error": {"message": error}}
    return {
        "status": status,
        "steps": [{"skill_name": "qt.ai.data.kline", "result": result}],
    }


class TestAi04ResultReading(unittest.TestCase):
    """解读函数把指不回记录的整段换成模板。"""

    def test_grounded_echo_is_kept(self) -> None:
        """模型只复述记录里的代码和行数时，原句留下。"""

        print("\n[TestAi04ResultReading] 指回记录的原句留下")
        plan = _plan("one index")
        execution = _execution()
        provider = FakeLLMProvider(replies=[_GROUNDED])
        corpus = reading_corpus(plan, execution)
        text = write_result_reading(plan, execution, provider=provider)
        print(" corpus:", corpus)
        print(" system:", provider.system_prompts)
        print(" model:", _GROUNDED)
        print(" returned:", text)
        self.assertTrue(provider.prompts)
        self.assertEqual(text, _GROUNDED)
        self.assertNotEqual(text, reading_template(plan, execution))

    def test_outrun_or_rank_becomes_template(self) -> None:
        """跑赢或排名指不回记录时，整段换成模板。"""

        print("\n[TestAi04ResultReading] 跑赢或排名整段降级")
        plan = _plan("one index")
        execution = _execution()
        model = "这只跑赢了，排名第1。"
        provider = FakeLLMProvider(replies=[model])
        text = write_result_reading(plan, execution, provider=provider)
        template = reading_template(plan, execution)
        print(" model:", model)
        print(" returned:", text)
        self.assertEqual(text, template)
        self.assertNotIn("跑赢", text)
        self.assertNotIn("排名", text)
        self.assertIn("000300.SH", text)
        self.assertNotIn("总账", text)

    def test_partial_excess_replaces_whole_paragraph(self) -> None:
        """前半句指回记录、后半句多一个超额数字时，整段换成模板。"""

        print("\n[TestAi04ResultReading] 部分作答整段降级")
        plan = _plan("one index", [_QUESTION])
        execution = _execution()
        before_plan = copy.deepcopy(plan)
        before_execution = copy.deepcopy(execution)
        model = "Fetched 000300.SH. 超额是 4.2%。"
        provider = FakeLLMProvider(replies=[model])
        text = write_result_reading(plan, execution, provider=provider)
        template = reading_template(plan, execution)
        print(" corpus:", reading_corpus(plan, execution))
        print(" model:", model)
        print(" returned:", text)
        self.assertEqual(text, template)
        self.assertNotEqual(text, model)
        self.assertNotIn("4.2", text)
        self.assertIn(_QUESTION, text)
        self.assertEqual(plan, before_plan)
        self.assertEqual(execution, before_execution)

    def test_foreign_code_becomes_template(self) -> None:
        """记录里没有的代码整段换成模板。"""

        print("\n[TestAi04ResultReading] 外来代码整段降级")
        plan = _plan("one index")
        execution = _execution()
        model = "另写 600519.SH。"
        provider = FakeLLMProvider(replies=[model])
        text = write_result_reading(plan, execution, provider=provider)
        print(" model:", model)
        print(" returned:", text)
        self.assertEqual(text, reading_template(plan, execution))
        self.assertNotIn("600519", text)

    def test_one_index_does_not_invent_ledger(self) -> None:
        """只有一只指数时，不编出总账。"""

        print("\n[TestAi04ResultReading] 一只指数没有总账")
        plan = _plan("看一只指数")
        execution = _execution()
        model = "总账是 8%。"
        provider = FakeLLMProvider(replies=[model])
        text = write_result_reading(plan, execution, provider=provider)
        template = reading_template(plan, execution)
        print(" model:", model)
        print(" returned:", text)
        self.assertEqual(text, template)
        self.assertIn("000300.SH", text)
        self.assertIn("This record has no other total.", text)
        self.assertNotIn("总账", text)
        self.assertNotIn("8", text)

    def test_failure_replaces_success_claim(self) -> None:
        """失败记录不留下成功句。没有数字的 Run succeeded. 也整段换掉。"""

        print("\n[TestAi04ResultReading] 失败记录换掉成功句")
        error = "symbol 000001 was not found"
        plan = _plan("fetch one index")
        execution = _execution("partial_failed", error)
        ledger = "Run succeeded. 总账 3%。"
        provider = FakeLLMProvider(replies=[ledger])
        text = write_result_reading(plan, execution, provider=provider)
        template = reading_template(plan, execution)
        print(" model:", ledger)
        print(" returned:", text)
        self.assertEqual(text, template)
        self.assertIn(error, text)
        self.assertIn("The run did not finish.", text)
        self.assertNotIn("succeeded", text)
        self.assertNotIn("总账", text)
        self.assertNotIn("3", text)

        bare = "Run succeeded."
        bare_provider = FakeLLMProvider(replies=[bare])
        bare_text = write_result_reading(plan, execution, provider=bare_provider)
        print(" bare model:", bare)
        print(" bare returned:", bare_text)
        self.assertEqual(bare_text, template)
        self.assertNotIn("succeeded", bare_text)

    def test_no_model_fills_the_same_template(self) -> None:
        """没有模型时直接填同一份模板，不调用 chat。"""

        print("\n[TestAi04ResultReading] 无模型填同一模板")
        success_plan = _plan("one index")
        success_execution = _execution()
        success = write_result_reading(success_plan, success_execution, provider=None)
        print(" success:", success)
        self.assertEqual(success, reading_template(success_plan, success_execution))
        self.assertIn("one index", success)
        self.assertIn("000300.SH", success)

        error = "symbol 000001 was not found"
        failed_plan = _plan("fetch one index")
        failed_execution = _execution("partial_failed", error)
        failed = write_result_reading(failed_plan, failed_execution, provider=None)
        print(" failed:", failed)
        self.assertEqual(failed, reading_template(failed_plan, failed_execution))
        self.assertIn(error, failed)

    def test_chinese_card_keeps_template_after_polish(self) -> None:
        """中文问句先被润色吃掉一条对不上的回复，第二条非法解读才进生成函数。"""

        print("\n[TestAi04ResultReading] 中文贴卡先退回润色")
        polish_reply = "润色 99999"
        provider = FakeLLMProvider(replies=[polish_reply, _ILLEGAL])
        text = self._attach("看这只指数", provider)
        print(" prompts:", provider.prompts)
        print(" card:", text)
        print(" replies left:", provider.replies)
        self.assertIn("**Run succeeded.**", text)
        self.assertIn("This record has no other total.", text)
        self.assertNotIn("4.2", text)
        self.assertTrue(provider.prompts)
        self.assertIn("Fields:", provider.prompts[-1])
        self.assertNotIn("**Run succeeded.**", provider.prompts[-1])
        self.assertEqual(provider.replies, [])

    def test_english_card_reads_the_only_reply(self) -> None:
        """问句不含中文时润色不调用模型，队列里只有非法解读。"""

        print("\n[TestAi04ResultReading] 英文贴卡只消费解读")
        provider = FakeLLMProvider(replies=[_ILLEGAL])
        text = self._attach("show the index", provider)
        print(" prompts:", provider.prompts)
        print(" card:", text)
        print(" replies left:", provider.replies)
        self.assertIn("This record has no other total.", text)
        self.assertNotIn("4.2", text)
        self.assertEqual(len(provider.prompts), 1)
        self.assertIn("Fields:", provider.prompts[-1])
        self.assertNotIn("**Run succeeded.**", provider.prompts[-1])
        self.assertEqual(provider.replies, [])

    def _attach(self, query: str, provider: FakeLLMProvider) -> str:
        """走装配层贴卡，并确认步骤没有被改写。"""

        plan = _plan(query, [_QUESTION])
        execution = _execution()
        payload = {
            "run_id": "run_read",
            "plan": plan,
            "execution": execution,
        }
        before_plan = copy.deepcopy(plan["steps"])
        before_execution = copy.deepcopy(execution["steps"])
        with tempfile.TemporaryDirectory() as temp_dir:
            assistant = QteasyAssistant(
                provider=provider,
                registry=build_default_registry(),
                memory_store=MemoryStore(base_dir=temp_dir),
            )
            assistant._attach_human_cards(
                payload,
                query=query,
                requested_mode="run",
                session=None,
            )
        self.assertEqual(plan["steps"], before_plan)
        self.assertEqual(execution["steps"], before_execution)
        result = next(item for item in payload["human_cards"] if item["kind"] == "result")
        print(" kind:", result["kind"])
        self.assertEqual(result["kind"], "result")
        return str(result["text"])


if __name__ == "__main__":
    unittest.main()
