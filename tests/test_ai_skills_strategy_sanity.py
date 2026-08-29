# coding=utf-8
# ======================================
# File: test_ai_skills_strategy_sanity.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-29
# Desc:
# Unittest for qt.ai.strategy.sanity_check
# ======================================

import tempfile
import unittest
from pathlib import Path

from qteasy_ai.skills.strategy_codegen import build_strategy_codegen_hybrid_skill
from qteasy_ai.skills.strategy_sanity import build_strategy_sanity_check_skill
from qteasy_ai.skills.strategy_spec import build_strategy_spec_from_nl_skill


def _write_codegen(temp_dir: str) -> tuple[str, dict]:
    """生成金标准骨架并返回路径与 Spec。"""

    _, spec_handler = build_strategy_spec_from_nl_skill()
    spec = spec_handler(query="20/60 日均线金叉死叉")["payload"]["spec"]
    _, codegen = build_strategy_codegen_hybrid_skill(strategies_dir=temp_dir)
    generated = codegen(spec=spec)
    return generated["payload"]["strategy_path"], spec


class TestAiStrategySanitySkill(unittest.TestCase):
    """测试策略骨架静态校验。"""

    def test_valid_skeleton_passes_pars_and_window(self) -> None:
        """合法骨架：ok，pars 名与 window_length >= slow。"""

        print("\n[TestAiStrategySanitySkill] valid skeleton")
        called = {"n": 0}

        def fake_run(*args, **kwargs):
            called["n"] += 1
            return {}

        with tempfile.TemporaryDirectory() as temp_dir:
            path, spec = _write_codegen(temp_dir)
            meta, handler = build_strategy_sanity_check_skill(run_func=fake_run)
            result = handler(strategy_path=path, spec=spec)
            details = (result.get("payload") or {}).get("details") or {}
            print(" ok:", result["ok"])
            print(" details:", details)
            print(" metrics:", result.get("metrics"))
            print(" run called:", called["n"])
            self.assertTrue(result["ok"])
            self.assertFalse(meta.side_effects.filesystem_write)
            self.assertEqual(called["n"], 0)
            self.assertIn("fast", details.get("par_names") or [])
            self.assertIn("slow", details.get("par_names") or [])
            windows = details.get("window_lengths") or [0]
            self.assertGreaterEqual(max(windows), 60)
            self.assertIn("close_ANY_d", details.get("dtype_ids") or details.get("get_data_ids") or [])

    def test_missing_realize_fails_without_run(self) -> None:
        """缺 realize → 失败且不调用 qt.run。"""

        print("\n[TestAiStrategySanitySkill] missing realize")
        called = {"n": 0}
        source = '''# coding=utf-8
import qteasy as qt
from qteasy import Parameter, StgData

class NoRealize(qt.RuleIterator):
    def __init__(self, **kwargs):
        super().__init__(
            pars=[Parameter((5, 80), name='fast', par_type='int', value=20)],
            name='NoRealize',
            data_types=StgData('close', freq='d', asset_type='ANY', window_length=65),
            **kwargs,
        )
'''
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "no_realize.py"
            path.write_text(source, encoding="utf-8")
            _, handler = build_strategy_sanity_check_skill(
                run_func=lambda *a, **k: called.__setitem__("n", called["n"] + 1)
            )
            result = handler(strategy_path=str(path))
            print(" ok:", result["ok"], "error:", result.get("error"))
            print(" run called:", called["n"])
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["code"], "SANITY_CHECK_FAILED")
            self.assertIn("realize", result["error"]["message"].lower())
            self.assertEqual(called["n"], 0)

    def test_wrong_base_class_fails(self) -> None:
        """错误基类 → 失败。"""

        print("\n[TestAiStrategySanitySkill] wrong base class")
        source = '''# coding=utf-8
class Plain:
    def realize(self):
        return 0.0
'''
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "plain.py"
            path.write_text(source, encoding="utf-8")
            _, handler = build_strategy_sanity_check_skill()
            result = handler(strategy_path=str(path))
            print(" ok:", result["ok"], "error:", result.get("error"))
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["code"], "SANITY_CHECK_FAILED")
            self.assertIn("strategy class", result["error"]["message"].lower())

    def test_get_data_id_mismatch_fails(self) -> None:
        """get_data 列 id 与 data_types 不一致 → 失败。"""

        print("\n[TestAiStrategySanitySkill] get_data mismatch")
        source = '''# coding=utf-8
import qteasy as qt
from qteasy import Parameter, StgData

class BadGetData(qt.RuleIterator):
    def __init__(self, **kwargs):
        super().__init__(
            pars=[
                Parameter((5, 80), name='fast', par_type='int', value=20),
                Parameter((20, 200), name='slow', par_type='int', value=60),
            ],
            name='BadGetData',
            data_types=StgData('close', freq='d', asset_type='ANY', window_length=65),
            **kwargs,
        )

    def realize(self):
        return self.get_data('open_E_d')[-1]
'''
        spec = {
            "signal_type": "PS",
            "run_freq": "d",
            "run_timing": "close",
            "asset_pool": "",
            "htypes": ["close"],
            "window_length": 65,
            "use_latest_data_cycle": False,
            "parameters": [
                {"name": "fast", "default": 20, "range": [5, 80], "par_type": "int", "opt_tag": 1},
                {"name": "slow", "default": 60, "range": [20, 200], "par_type": "int", "opt_tag": 1},
            ],
            "risk_decl": {},
            "template_id": "rule_iterator.sma_cross",
            "assumptions": [],
            "source_query": "",
            "class_name": "BadGetData",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad_get_data.py"
            path.write_text(source, encoding="utf-8")
            _, handler = build_strategy_sanity_check_skill()
            result = handler(strategy_path=str(path), spec=spec)
            print(" ok:", result["ok"], "error:", result.get("error"))
            print(" payload:", result.get("payload"))
            self.assertFalse(result["ok"])
            self.assertEqual(result["error"]["code"], "SANITY_CHECK_FAILED")
            self.assertIn("get_data", result["error"]["message"])


if __name__ == "__main__":
    unittest.main()
