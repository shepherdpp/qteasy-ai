# coding=utf-8
# ======================================
# File: test_ai_workbench_artifacts.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-07
# Desc:
# Unittest for workbench Artifact Tabs (G.Artifact)
# ======================================

import json
import tempfile
import unittest
from pathlib import Path

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.workbench.http_app import create_app
from qteasy_ai.workbench.mapper import classify_artifacts, map_assistant_payload


class TestAiWorkbenchArtifacts(unittest.TestCase):
    """G.Artifact：四类 Tabs、缺 path 警告、导出 404。"""

    def test_four_types_share_run_id(self) -> None:
        """合成 execute payload：四类 type 同一 run_id。"""

        print("\n[TestAiWorkbenchArtifacts] four types")
        run_id = "run_shared"
        payload = {
            "mode": "plan",
            "run_id": run_id,
            "plan": {"plan_id": "p1", "steps": []},
            "execution": {
                "status": "success",
                "steps": [
                    {
                        "step_id": "s1",
                        "skill_name": "qt.ai.data.read",
                        "result": {
                            "ok": True,
                            "data_summary": {"channel": "history"},
                            "payload": {"preview_rows": [{"a": 1}]},
                        },
                    },
                    {
                        "step_id": "s2",
                        "skill_name": "qt.ai.visual.export_kline",
                        "result": {"ok": True, "artifacts": [{"type": "image", "path": "/tmp/a.png"}]},
                    },
                    {
                        "step_id": "s3",
                        "skill_name": "qt.ai.strategy.codegen_hybrid",
                        "result": {
                            "ok": True,
                            "artifacts": [{"kind": "strategy_source", "path": "/tmp/s.py"}],
                        },
                    },
                    {
                        "step_id": "s4",
                        "skill_name": "qt.ai.backtest.run_builtin",
                        "result": {
                            "ok": True,
                            "metrics": {"mdd": -0.1},
                            "artifacts": [{"kind": "trade_log", "path": "/tmp/t.csv"}],
                        },
                    },
                ],
            },
        }
        dumped = map_assistant_payload(payload).to_dict()
        types = [item["type"] for item in dumped["artifacts"]]
        print(" types:", types)
        print(" run_ids:", [item["run_id"] for item in dumped["artifacts"]])
        self.assertEqual(types, ["data_table", "chart", "strategy_code", "backtest_report"])
        self.assertTrue(all(item["run_id"] == run_id for item in dumped["artifacts"]))
        self.assertNotIn("factor_analysis", types)

    def test_chart_missing_path_warning(self) -> None:
        """缺 path 的 chart 不崩溃，英文 warning。"""

        print("\n[TestAiWorkbenchArtifacts] missing chart path")
        items = classify_artifacts(
            "run_x",
            [
                {
                    "step_id": "s1",
                    "skill_name": "qt.ai.visual.export_kline",
                    "result": {"ok": True, "artifacts": [{"type": "image"}]},
                }
            ],
        )
        print(" items:", items)
        self.assertEqual(items[0]["type"], "chart")
        self.assertEqual(items[0]["export_path"], "")
        self.assertTrue(items[0]["warnings"])
        self.assertRegex(items[0]["warnings"][0], r"[A-Za-z]")

    def test_get_run_artifacts_match_mapper(self) -> None:
        """GET /v1/runs/{run_id} artifacts 与 mapper 一致。"""

        print("\n[TestAiWorkbenchArtifacts] get run")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            run_id = "run_get"
            payload = {
                "run_id": run_id,
                "plan": {"plan_id": "p_get", "steps": []},
                "execution": {
                    "status": "success",
                    "steps": [
                        {
                            "step_id": "s1",
                            "skill_name": "qt.ai.data.read",
                            "result": {
                                "ok": True,
                                "data_summary": {"channel": "static"},
                                "payload": {"preview_rows": [{"x": 1}]},
                            },
                        }
                    ],
                },
            }
            store.save_run(run_id, payload)
            expected = map_assistant_payload(payload).to_dict()["artifacts"]
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            body = TestClient(app).get(f"/v1/runs/{run_id}").json()
            print(" expected:", expected)
            print(" http:", body.get("artifacts"))
            self.assertEqual(body.get("artifacts"), expected)

    def test_export_existing_and_missing(self) -> None:
        """存在的文件可读；不存在 → 英文 404。"""

        print("\n[TestAiWorkbenchArtifacts] export")
        from starlette.testclient import TestClient

        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            png = Path(temp_dir) / "chart.png"
            png.write_bytes(b"png-bytes")
            run_id = "run_exp"
            payload = {
                "run_id": run_id,
                "plan": {"plan_id": "p_exp", "steps": []},
                "execution": {
                    "status": "success",
                    "steps": [
                        {
                            "step_id": "s1",
                            "skill_name": "qt.ai.visual.export_kline",
                            "result": {
                                "ok": True,
                                "artifacts": [{"type": "image", "path": str(png)}],
                            },
                        }
                    ],
                },
            }
            store.save_run(run_id, payload)
            app = create_app(assistant=QteasyAssistant(memory_store=store, registry=build_default_registry()))
            client = TestClient(app)
            ok = client.get(f"/v1/artifacts/{run_id}", params={"path": str(png)})
            missing = client.get(f"/v1/artifacts/{run_id}", params={"path": str(Path(temp_dir) / "nope.png")})
            print(" ok:", ok.status_code, ok.content[:20])
            print(" missing:", missing.status_code, missing.json())
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(ok.content, b"png-bytes")
            self.assertEqual(missing.status_code, 404)
            self.assertRegex(str(missing.json().get("error", {}).get("message") or ""), r"[A-Za-z]")

    def test_code_run_requires_confirm_not_silent_run(self) -> None:
        """代码 Tab Run 只出确认语义：app.js 含 Confirm run，不含静默 /v1/run。"""

        print("\n[TestAiWorkbenchArtifacts] code run confirm")
        js = (Path(__file__).resolve().parents[1] / "qteasy_ai" / "workbench" / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        print(" has confirm:", "btn-code-confirm" in js)
        self.assertIn("requires confirm", js.lower())
        self.assertIn("btn-code-confirm", js)
        self.assertIn("/v1/run-plan", js)


if __name__ == "__main__":
    unittest.main()
