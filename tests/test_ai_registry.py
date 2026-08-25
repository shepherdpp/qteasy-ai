# coding=utf-8
# ======================================
# File: test_ai_registry.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-04-15
# Desc:
# Unittest for qteasy ai registry contracts
# ======================================

import unittest

from qteasy_ai.contracts import SkillMetadata, SkillSideEffects
from qteasy_ai.registry import SkillRegistry


class TestAiRegistry(unittest.TestCase):
    """测试 SkillRegistry 的注册与调用。"""

    def test_register_list_and_call(self) -> None:
        """验证 registry 注册、查询和调用闭环。"""

        registry = SkillRegistry()
        metadata = SkillMetadata(
            name="qt.ai.test.echo",
            version="0.1.0",
            summary="Echo input.",
            inputs_schema={"text": {"type": "string"}},
            outputs_schema={"echo": "string"},
            side_effects=SkillSideEffects(description="readonly"),
        )

        def handler(text: str = "hello") -> dict:
            return {"ok": True, "echo": text}

        registry.register(metadata, handler)
        skill_names = [item.name for item in registry.list_skills()]
        result = registry.call("qt.ai.test.echo", text="world")

        print("\n[TestAiRegistry] 已注册技能:", skill_names)
        print(" result:", result)
        self.assertEqual(skill_names, ["qt.ai.test.echo"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["echo"], "world")
        print(" default skill_kind:", metadata.skill_kind)
        self.assertEqual(metadata.skill_kind, "api")

    def test_skill_kind_guide_default_api(self) -> None:
        """验证 skill_kind 默认为 api，引导技能可标为 guide。"""

        api_meta = SkillMetadata(
            name="qt.ai.test.api",
            version="0.1.0",
            summary="API skill.",
            inputs_schema={},
            outputs_schema={},
        )
        guide_meta = SkillMetadata(
            name="qt.ai.test.guide",
            version="0.1.0",
            summary="Guide skill.",
            inputs_schema={},
            outputs_schema={},
            skill_kind="guide",
        )
        print("\n[TestAiRegistry] api skill_kind:", api_meta.skill_kind)
        print(" guide skill_kind:", guide_meta.skill_kind)
        self.assertEqual(api_meta.skill_kind, "api")
        self.assertEqual(guide_meta.skill_kind, "guide")


if __name__ == "__main__":
    unittest.main()
