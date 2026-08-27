# coding=utf-8
# ======================================
# File: test_ai_profile_agent.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-27
# Desc:
# Unittest for qteasy-ai stage B profile
# schema and Agent reserved flags
# ======================================

import tempfile
import unittest

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.contracts import SkillMetadata, SkillSideEffects
from qteasy_ai.memory_store import DEFAULT_PROFILE, MemoryStore, apply_profile_defaults
from qteasy_ai.runtime import SkillRuntime


class TestAiProfileAgent(unittest.TestCase):
    """测试阶段 B 预留 profile.agent 默认值与 run 不读开关。"""

    def test_default_profile_schema_when_file_missing(self) -> None:
        """缺 profile.json 时 load 得到 agent 三开关默认 false。"""

        print("\n[TestAiProfileAgent] default schema when missing")
        print(" DEFAULT_PROFILE:", DEFAULT_PROFILE)
        self.assertEqual(DEFAULT_PROFILE["agent"]["allow_refill"], False)
        self.assertEqual(DEFAULT_PROFILE["agent"]["allow_backtest"], False)
        self.assertEqual(DEFAULT_PROFILE["agent"]["allow_optimize"], False)

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            profile = store.load_profile()
            print(" loaded:", profile)
            self.assertEqual(profile["agent"]["allow_refill"], False)
            self.assertEqual(profile["agent"]["allow_backtest"], False)
            self.assertEqual(profile["agent"]["allow_optimize"], False)

    def test_apply_profile_defaults_keeps_user_keys(self) -> None:
        """已有偏好键保留，缺省 agent 开关被补齐。"""

        raw = {"favorite_symbol": "000300.SH", "agent": {"allow_backtest": True}}
        merged = apply_profile_defaults(raw)
        print("\n[TestAiProfileAgent] merge raw:", raw)
        print(" merged:", merged)
        self.assertEqual(merged["favorite_symbol"], "000300.SH")
        self.assertTrue(merged["agent"]["allow_backtest"])
        self.assertFalse(merged["agent"]["allow_refill"])
        self.assertFalse(merged["agent"]["allow_optimize"])

    def test_assistant_run_ignores_agent_flags(self) -> None:
        """agent 开关全 false 时 assistant.run 仍执行只读 skill（不把门控接到 run）。"""

        print("\n[TestAiProfileAgent] run ignores agent flags")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            store.save_profile(
                {
                    "agent": {
                        "allow_refill": False,
                        "allow_backtest": False,
                        "allow_optimize": False,
                    }
                }
            )
            assistant = QteasyAssistant(memory_store=store, registry=build_default_registry())
            payload = assistant.run("list built-in strategies", response_style="raw")
            status = payload["execution"]["status"]
            steps = payload["execution"]["steps"]
            print(" status:", status)
            print(" step count:", len(steps))
            print(" first skill:", steps[0]["skill_name"] if steps else None)
            self.assertEqual(status, "success")
            self.assertGreaterEqual(len(steps), 1)
            self.assertEqual(steps[0]["skill_name"], "qt.ai.strategy_meta.list")
            self.assertTrue(steps[0]["result"].get("ok"))

    def test_high_side_effect_local_state_unconfirmed(self) -> None:
        """local_state_change 高副作用在 confirmed=False 时 SKILL_CONFIRM_REQUIRED。"""

        runtime = SkillRuntime()
        metadata = SkillMetadata(
            name="qt.ai.data.refill_basic_equity_and_index",
            version="0.2.0",
            summary="refill",
            inputs_schema={},
            outputs_schema={"ok": "bool"},
            side_effects=SkillSideEffects(network=True, filesystem_write=True, local_state_change=True),
        )
        called = {"n": 0}

        def handler(**_) -> dict:
            called["n"] += 1
            return {"ok": True}

        result = runtime.execute(metadata=metadata, handler=handler, kwargs={}, confirmed=False)
        print("\n[TestAiProfileAgent] unconfirmed high side-effect:", result)
        print(" handler called:", called["n"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "SKILL_CONFIRM_REQUIRED")
        self.assertEqual(called["n"], 0)


if __name__ == "__main__":
    unittest.main()
