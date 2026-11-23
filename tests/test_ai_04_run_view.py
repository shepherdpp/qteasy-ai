# coding=utf-8
# ======================================
# File: test_ai_04_run_view.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-19
# Desc:
# 第九步：同一次运行的两级可见性。分类原文和填槽原文
# 由这次 plan 写入 run，展示时只读这份记录。
# ======================================

import json
import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.provider import FakeLLMProvider
from qteasy_ai.run_view import project_run_view, render_run_view
from qteasy_ai.workbench.mapper import step_artifact_index

_LIST = "list built-in strategies"
_FAIL = "show strategy NOPEID"
_FILL = "算因子 IC"
_CLASSIFY = json.dumps({"job": "strategy.meta"})
_FACTOR = json.dumps({"job": "research.factor_ic"})
_FILL_RAW = json.dumps({"shares": "平安银行"}, ensure_ascii=False)
_REJECT = "'平安银行' is not an exchange code."


def _split(text: str) -> str:
    """拆分协议。task 必须是原句里的连续片段。"""

    return json.dumps({"task": text, "question": ""}, ensure_ascii=False)


def _assistant(replies):
    """临时库上的助手。队列按 chat 顺序弹出。"""

    store = MemoryStore(base_dir=tempfile.mkdtemp())
    provider = FakeLLMProvider(replies=list(replies))
    assistant = QteasyAssistant(
        provider=provider,
        memory_store=store,
        registry=build_default_registry(),
    )
    return assistant, store, provider


def _trace(saved):
    """run 里的 planner_trace。"""

    plan = saved.get("plan") if isinstance(saved.get("plan"), dict) else {}
    trace = plan.get("planner_trace") if isinstance(plan.get("planner_trace"), dict) else {}
    return trace


def _result_card(payload):
    """已执行结果卡。"""

    cards = payload.get("human_cards") if isinstance(payload.get("human_cards"), list) else []
    return next(item for item in cards if item.get("kind") == "result")


class TestAi04RunView(unittest.TestCase):
    """默认逐步视图和调试展开都读同一份已保存 run。"""

    def test_success_run_shows_steps_and_hides_protocol(self) -> None:
        """列出内置策略：两级的成败和输入一致，产物索引来自这一步。"""

        print("\n[TestAi04RunView] 成功运行两级一致")
        split = _split(_LIST)
        assistant, store, provider = _assistant([split, _CLASSIFY])
        planned = assistant.plan(_LIST, response_style="raw")
        plan_id = str((planned.get("plan") or {}).get("plan_id") or "")
        executed = assistant.run_plan(plan_id, response_style="raw")
        run_id = str(executed.get("run_id") or "")
        saved = store.load_run(run_id)
        trace = _trace(saved)
        view = project_run_view(saved)
        off = render_run_view(view, debug=False)
        on = render_run_view(view, debug=True)
        steps = (saved.get("execution") or {}).get("steps") or []
        index = step_artifact_index(run_id, steps)
        card = _result_card(executed)
        print(" prompts:", len(provider.prompts), "split consumed:", provider.prompts[:1])
        print(" classify_protocol:", trace.get("classify_protocol"))
        print(" fill_output:", trace.get("fill_output"))
        print(" view:", view)
        print(" off:", off)
        print(" on:", on)
        print(" index:", index)
        print(" card steps:", card.get("payload", {}).get("steps"))
        self.assertEqual((saved.get("execution") or {}).get("status"), "success")
        self.assertEqual(steps[0].get("skill_name"), "qt.ai.strategy_meta.list")
        self.assertFalse(trace.get("classify_protocol"))
        record = ((saved.get("plan") or {}).get("assumptions") or {}).get("parse_record") or {}
        self.assertEqual(record.get("job"), "strategy.meta")
        self.assertNotIn("fill_output", trace)
        self.assertTrue(view["steps"][0]["ok"])
        self.assertEqual(view["steps"][0]["input_summary"], "(none)")
        self.assertEqual(view["steps"][0]["error"], "")
        self.assertFalse(view.get("classify_protocol"))
        self.assertNotIn("fill_output", view)
        self.assertTrue(on.startswith(off))
        self.assertIn("ok=True", off)
        self.assertIn("inputs: (none)", off)
        self.assertIn("ok=True", on)
        self.assertIn("inputs: (none)", on)
        self.assertNotIn("Classify protocol", off)
        self.assertNotIn(split, off)
        self.assertNotIn(_CLASSIFY, off)
        self.assertTrue(any(
            item.get("type") == "data_table" and item.get("title") == "qt.ai.strategy_meta.list"
            for item in index
        ))
        card_steps = card["payload"]["steps"]
        self.assertEqual(card_steps[0]["artifacts"], [
            item for item in index if item.get("step_id") == card_steps[0]["step_id"]
        ])
        self.assertEqual(card_steps[0]["artifacts"][0]["type"], "data_table")
        self.assertEqual(card_steps[0]["artifacts"][0]["run_id"], run_id)
        self.assertEqual(card_steps[0]["artifacts"][0]["title"], "qt.ai.strategy_meta.list")

    def test_failed_strategy_keeps_error_when_debug_is_off(self) -> None:
        """未知策略 id 执行失败。关掉调试仍能看见错误原文。"""

        print("\n[TestAi04RunView] 失败运行关掉开关仍有错误")
        split = _split(_FAIL)
        # 菜谱写出的 strategy_id 会被未确认预写清掉，填槽 chat 必须把 NOPEID 交回来才会执行。
        fill_raw = json.dumps({"strategy_id": "NOPEID"})
        assistant, store, provider = _assistant([split, _CLASSIFY, fill_raw])
        planned = assistant.plan(_FAIL, response_style="raw")
        plan_id = str((planned.get("plan") or {}).get("plan_id") or "")
        executed = assistant.run_plan(plan_id, response_style="raw")
        run_id = str(executed.get("run_id") or "")
        saved = store.load_run(run_id)
        trace = _trace(saved)
        before = len(provider.prompts)
        view = project_run_view(saved)
        after = len(provider.prompts)
        off = render_run_view(view, debug=False)
        on = render_run_view(view, debug=True)
        steps = (saved.get("execution") or {}).get("steps") or []
        message = str(((steps[0].get("result") or {}).get("error") or {}).get("message") or "")
        print(" prompts:", before, "after view:", after)
        print(" skill:", steps[0].get("skill_name"), "inputs:", view["steps"][0]["input_summary"])
        print(" status:", (saved.get("execution") or {}).get("status"))
        print(" error:", message)
        print(" off:", off)
        print(" on:", on)
        print(" classify_protocol:", trace.get("classify_protocol"))
        self.assertEqual(steps[0].get("skill_name"), "qt.ai.strategy_meta.get")
        self.assertNotEqual(steps[0].get("skill_name"), "qt.ai.strategy_meta.list")
        self.assertIn("strategy_id=NOPEID", view["steps"][0]["input_summary"])
        self.assertFalse(view["steps"][0]["ok"])
        self.assertTrue(message.startswith("Failed to get strategy details:"))
        self.assertIn(message, off)
        self.assertIn(message, on)
        self.assertTrue(on.startswith(off))
        self.assertFalse(trace.get("classify_protocol"))
        self.assertFalse(view.get("classify_protocol"))
        record = ((saved.get("plan") or {}).get("assumptions") or {}).get("parse_record") or {}
        self.assertEqual(record.get("job"), "strategy.meta")
        self.assertNotIn(_CLASSIFY, off)
        self.assertNotIn(split, off)
        self.assertEqual(before, after)

    def test_fill_protocol_is_saved_and_only_shown_when_debug_is_on(self) -> None:
        """填槽原文和拒因由这次 plan 写入，调试展开才显示。"""

        print("\n[TestAi04RunView] 填槽原文只在调试展开")
        split = _split(_FILL)
        assistant, store, provider = _assistant([split, _FACTOR, _FILL_RAW])
        planned = assistant.plan(_FILL, response_style="raw", debug=True)
        run_id = str(planned.get("run_id") or "")
        saved = store.load_run(run_id)
        trace = _trace(saved)
        before = len(provider.prompts)
        view = project_run_view(saved)
        after = len(provider.prompts)
        off = render_run_view(view, debug=False)
        on = render_run_view(view, debug=True)
        print(" prompt count:", before)
        print(" classify_protocol:", trace.get("classify_protocol"))
        print(" fill_output:", trace.get("fill_output"))
        print(" rejects:", trace.get("validation_rejects"))
        print(" off:", off)
        print(" on:", on)
        record = ((saved.get("plan") or {}).get("assumptions") or {}).get("fill_record") or {}
        debug_rows = trace.get("fill_debug") or []
        print(" fill_record questions:", record.get("questions"))
        print(" fill_debug:", debug_rows[:1])
        self.assertFalse(trace.get("classify_protocol"))
        record = ((saved.get("plan") or {}).get("assumptions") or {}).get("parse_record") or {}
        self.assertEqual(record.get("job"), "research.factor_ic")
        self.assertTrue(trace.get("parse_debug"))
        self.assertNotIn("fill_output", trace)
        self.assertIn(_FILL_RAW, json.dumps(debug_rows, ensure_ascii=False))
        self.assertNotIn(split, json.dumps(debug_rows, ensure_ascii=False))
        print(" questions:", record.get("questions"))
        self.assertEqual(record.get("questions") or [], [])
        self.assertIn(_REJECT, json.dumps(debug_rows, ensure_ascii=False))
        self.assertFalse(view.get("classify_protocol"))
        self.assertEqual(view.get("fill_debug"), trace.get("fill_debug"))
        self.assertIn("research.factor_ic", on)
        self.assertIn(_FILL_RAW, on)
        self.assertIn(_REJECT, on)
        self.assertNotIn(_FACTOR, off)
        self.assertNotIn(_FILL_RAW, off)
        self.assertNotIn(_REJECT, off)
        self.assertNotIn("Classify protocol", off)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
