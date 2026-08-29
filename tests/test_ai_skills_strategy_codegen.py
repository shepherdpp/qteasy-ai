# coding=utf-8
# ======================================
# File: test_ai_skills_strategy_codegen.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-29
# Desc:
# Unittest for qt.ai.strategy.codegen_hybrid
# ======================================

import importlib.util
import inspect
import tempfile
import unittest
from pathlib import Path

from qteasy_ai.runtime import SkillRuntime
from qteasy_ai.skills.strategy_codegen import build_strategy_codegen_hybrid_skill
from qteasy_ai.skills.strategy_spec import build_strategy_spec_from_nl_skill


def _golden_spec() -> dict:
    """返回 D.2 金句对应 Spec 字典。"""

    _, handler = build_strategy_spec_from_nl_skill()
    result = handler(query="20/60 日均线金叉死叉")
    return result["payload"]["spec"]


class TestAiStrategyCodegenSkill(unittest.TestCase):
    """测试模板 codegen 写盘边界。"""

    def test_writes_importable_rule_iterator_under_strategies_dir(self) -> None:
        """金标准 Spec 写入 strategies/，可 import 且继承 RuleIterator。"""

        print("\n[TestAiStrategyCodegenSkill] write importable skeleton")
        spec = _golden_spec()
        with tempfile.TemporaryDirectory() as temp_dir:
            meta, handler = build_strategy_codegen_hybrid_skill(strategies_dir=temp_dir)
            result = handler(spec=spec)
            path = Path(result["payload"]["strategy_path"])
            print(" ok:", result["ok"])
            print(" path:", path)
            print(" artifacts:", result["artifacts"])
            print(" source head:\n", path.read_text(encoding="utf-8")[:400])
            self.assertTrue(result["ok"])
            self.assertTrue(meta.side_effects.filesystem_write)
            self.assertTrue(path.exists())
            self.assertEqual(path.parent, Path(temp_dir))
            self.assertNotIn("examples", path.parts)
            self.assertNotIn("site-packages", path.parts)
            spec_loader = importlib.util.spec_from_file_location("gen_sma", path)
            module = importlib.util.module_from_spec(spec_loader)
            spec_loader.loader.exec_module(module)
            cls = getattr(module, spec["class_name"])
            import qteasy as qt

            print(" class:", cls, "mro:", [item.__name__ for item in cls.__mro__])
            self.assertTrue(issubclass(cls, qt.RuleIterator))
            self.assertTrue(inspect.isfunction(cls.realize) or inspect.ismethod(getattr(cls, "realize", None)))
            self.assertIn("realize", cls.__dict__)

    def test_unknown_template_does_not_write(self) -> None:
        """未知 template_id 英文错误且不写盘。"""

        print("\n[TestAiStrategyCodegenSkill] unknown template")
        spec = _golden_spec()
        spec["template_id"] = "general_stg.grid"
        with tempfile.TemporaryDirectory() as temp_dir:
            _, handler = build_strategy_codegen_hybrid_skill(strategies_dir=temp_dir)
            result = handler(spec=spec)
            leftovers = list(Path(temp_dir).glob("*.py"))
            print(" ok:", result["ok"], "error:", result.get("error"))
            print(" leftovers:", leftovers)
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["code"], "UNKNOWN_TEMPLATE_ID")
            self.assertEqual(leftovers, [])

    def test_existing_file_not_overwritten_returns_diff(self) -> None:
        """目标已存在时不覆盖，artifacts 含 diff。"""

        print("\n[TestAiStrategyCodegenSkill] no silent overwrite")
        spec = _golden_spec()
        with tempfile.TemporaryDirectory() as temp_dir:
            _, handler = build_strategy_codegen_hybrid_skill(strategies_dir=temp_dir)
            first = handler(spec=spec)
            path = Path(first["payload"]["strategy_path"])
            original = path.read_text(encoding="utf-8")
            marker = "# ORIGINAL_MARKER\n"
            path.write_text(marker + original, encoding="utf-8")
            second = handler(spec=spec, overwrite=False)
            after = path.read_text(encoding="utf-8")
            artifacts = second.get("artifacts") or []
            print(" ok:", second["ok"], "error:", second.get("error"))
            print(" artifacts kinds:", [item.get("kind") for item in artifacts])
            print(" still has marker:", after.startswith(marker))
            self.assertFalse(second["ok"])
            self.assertEqual(second["error"]["code"], "FILE_EXISTS_CONFIRM_REQUIRED")
            self.assertTrue(after.startswith(marker))
            self.assertEqual(after, marker + original)
            self.assertTrue(any(item.get("kind") == "diff" for item in artifacts))
            self.assertIn("diff", str(artifacts).lower() + str(artifacts[0].get("content", "")).lower())

    def test_unconfirmed_runtime_does_not_write(self) -> None:
        """confirmed=False 时 Runtime 门控，不写盘。"""

        print("\n[TestAiStrategyCodegenSkill] confirm required")
        spec = _golden_spec()
        with tempfile.TemporaryDirectory() as temp_dir:
            meta, handler = build_strategy_codegen_hybrid_skill(strategies_dir=temp_dir)
            runtime = SkillRuntime()
            gated = runtime.execute(
                metadata=meta,
                handler=handler,
                kwargs={"spec": spec},
                confirmed=False,
            )
            leftovers = list(Path(temp_dir).glob("*.py"))
            print(" gated:", gated)
            print(" leftovers:", leftovers)
            self.assertFalse(gated["ok"])
            self.assertEqual(gated["error"]["code"], "SKILL_CONFIRM_REQUIRED")
            self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
