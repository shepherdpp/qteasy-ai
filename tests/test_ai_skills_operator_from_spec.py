# coding=utf-8
# ======================================
# File: test_ai_skills_operator_from_spec.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-29
# Desc:
# Unittest for qt.ai.operator.build_from_spec
# ======================================

import tempfile
import unittest

from qteasy_ai.skills.operator_from_spec import build_operator_from_spec_skill
from qteasy_ai.skills.strategy_codegen import build_strategy_codegen_hybrid_skill
from qteasy_ai.skills.strategy_spec import build_strategy_spec_from_nl_skill


class TestAiOperatorFromSpecSkill(unittest.TestCase):
    """测试 Spec + path 组装 Operator 描述。"""

    def test_payload_has_freq_on_operator_not_run_config(self) -> None:
        """payload 含 run_freq/signal_type/strategy_path；freq 不进 run_config。"""

        print("\n[TestAiOperatorFromSpecSkill] operator payload")
        _, spec_handler = build_strategy_spec_from_nl_skill()
        spec = spec_handler(query="20/60 日均线金叉死叉")["payload"]["spec"]
        captured = {}

        def fake_operator(stg, run_freq="d", signal_type="ps", **kwargs):
            captured["stg"] = stg
            captured["run_freq"] = run_freq
            captured["signal_type"] = signal_type
            captured["kwargs"] = kwargs
            return {"op": True}

        def fake_load(path):
            captured["path"] = path
            return type("DummyStg", (), {})

        with tempfile.TemporaryDirectory() as temp_dir:
            _, codegen = build_strategy_codegen_hybrid_skill(strategies_dir=temp_dir)
            generated = codegen(spec=spec)
            path = generated["payload"]["strategy_path"]
            meta, handler = build_operator_from_spec_skill(
                operator_factory=fake_operator,
                load_func=fake_load,
            )
            result = handler(spec=spec, strategy_path=path)
            payload = result.get("payload") or {}
            print(" ok:", result["ok"])
            print(" payload:", payload)
            print(" captured:", {k: captured.get(k) for k in captured})
            self.assertTrue(result["ok"])
            self.assertFalse(meta.side_effects.filesystem_write)
            self.assertEqual(payload.get("strategy_path"), path)
            self.assertEqual(str(payload.get("run_freq")), "d")
            self.assertEqual(str(payload.get("signal_type")).upper(), "PS")
            self.assertNotIn("freq", payload.get("run_config") or {})
            self.assertEqual(payload.get("run_config"), {})
            self.assertEqual(captured.get("run_freq"), "d")
            self.assertEqual(str(captured.get("signal_type")).lower(), "ps")
            self.assertNotIn("freq", captured.get("kwargs") or {})


if __name__ == "__main__":
    unittest.main()
