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

    def _registry_with_stubs(self, called: dict):
        """用替身替换回测/实盘 handler，避免真跑长回测。"""

        from qteasy_ai.registry import SkillRegistry

        default = build_default_registry()
        registry = SkillRegistry()

        def backtest_stub(**_kwargs) -> dict:
            called["backtest"] = called.get("backtest", 0) + 1
            return {"ok": True, "payload": {"stub": True}}

        def live_stub(**_kwargs) -> dict:
            called["live"] = called.get("live", 0) + 1
            return {"ok": True, "payload": {"stub": True}}

        for meta in default.list_skills():
            if meta.name == "qt.ai.backtest.run_builtin":
                registry.register(meta, backtest_stub)
            elif meta.name == "qt.ai.pipeline.live_trade_plan_only":
                registry.register(meta, live_stub)
            else:
                registry.register(meta, default._impl[meta.name])
        return registry

    def test_agent_auto_blocks_backtest_when_disallowed(self) -> None:
        """agent_auto + allow_backtest=False → dry-run，不调 backtest handler。"""

        print("\n[TestAiProfileAgent] agent_auto block backtest")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            store.save_profile({"agent": {"allow_backtest": False}})
            called = {}
            assistant = QteasyAssistant(
                memory_store=store,
                registry=self._registry_with_stubs(called),
            )
            payload = assistant.run(
                "用 macd 做回测，2018 到 2023",
                response_style="raw",
                session_id="auto-bt",
                agent_auto=True,
            )
            print(" status:", payload["execution"]["status"], "called:", called)
            print(" assumptions:", payload["plan"].get("assumptions"))
            self.assertEqual(payload["execution"]["status"], "dry_run")
            self.assertEqual(called.get("backtest", 0), 0)
            self.assertIn("qt.ai.backtest.run_builtin", payload["plan"]["assumptions"].get("allow_gate_blocked") or [])

    def test_agent_auto_executes_backtest_when_allowed(self) -> None:
        """agent_auto + allow_backtest=True → 可 execute（替身 handler）。"""

        print("\n[TestAiProfileAgent] agent_auto allow backtest")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            store.save_profile({"agent": {"allow_backtest": True}})
            called = {}
            assistant = QteasyAssistant(
                memory_store=store,
                registry=self._registry_with_stubs(called),
            )
            payload = assistant.run(
                "用 macd 做回测，2018 到 2023",
                response_style="raw",
                session_id="auto-ok",
                agent_auto=True,
            )
            print(" status:", payload["execution"]["status"], "called:", called)
            self.assertIn(payload["execution"]["status"], ["success", "partial_failed"])
            self.assertGreaterEqual(called.get("backtest", 0), 1)

    def test_live_never_auto(self) -> None:
        """live 步在 agent_auto 下永不执行。"""

        print("\n[TestAiProfileAgent] live never auto")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            store.save_profile(
                {
                    "agent": {
                        "allow_refill": True,
                        "allow_backtest": True,
                        "allow_optimize": True,
                    }
                }
            )
            called = {}
            assistant = QteasyAssistant(
                memory_store=store,
                registry=self._registry_with_stubs(called),
            )
            payload = assistant.run(
                "准备实盘交易",
                response_style="raw",
                session_id="auto-live",
                agent_auto=True,
            )
            names = [s["skill_name"] for s in payload["plan"]["steps"]]
            print(" skills:", names, "status:", payload["execution"]["status"], "called:", called)
            self.assertIn("qt.ai.pipeline.live_trade_plan_only", names)
            self.assertEqual(payload["execution"]["status"], "dry_run")
            self.assertEqual(called.get("live", 0), 0)

    def test_oneshot_run_still_ignores_allow_flags(self) -> None:
        """一次性 run(query) 无 agent_auto 保持 B，不读开关。"""

        print("\n[TestAiProfileAgent] oneshot run ignores allow")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            store.save_profile({"agent": {"allow_backtest": False}})
            called = {}
            assistant = QteasyAssistant(
                memory_store=store,
                registry=self._registry_with_stubs(called),
            )
            payload = assistant.run("用 macd 做回测，2018 到 2023", response_style="raw")
            print(" status:", payload["execution"]["status"], "called:", called)
            self.assertIn(payload["execution"]["status"], ["success", "partial_failed"])
            self.assertGreaterEqual(called.get("backtest", 0), 1)


if __name__ == "__main__":
    unittest.main()
