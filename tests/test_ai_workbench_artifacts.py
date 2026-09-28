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
        self.assertIn("id=\"code-editor\"", js)
        self.assertIn("highlightPython", js)
        self.assertIn("code-highlight", js)
        self.assertNotIn("monaco", js.lower())

    def test_insight_and_optimize_project_data_table(self) -> None:
        """insight / optimize 的 metrics 必须投影成 data_table，而不是没有 Artifact。"""

        print("\n[TestAiWorkbenchArtifacts] insight and optimize tables")
        items = classify_artifacts(
            "run_io",
            [
                {
                    "step_id": "s_insight",
                    "skill_name": "qt.ai.insight.summarize_backtest",
                    "result": {
                        "ok": True,
                        "metrics": {"annual_rtn": 0.12, "mdd": 0.25, "final_value": 112000.0},
                        "payload": {
                            "change_hint": "Review strategy_meta parameters.",
                            "nearby_trades": [{"side": "buy", "price": 10.5}],
                        },
                    },
                },
                {
                    "step_id": "s_opt",
                    "skill_name": "qt.ai.optimize.run_builtin",
                    "result": {
                        "ok": True,
                        "metrics": {
                            "best_pars": [12, 26, 9],
                            "fv": 1.35,
                            "opti_method": "montecarlo",
                            "opti_sample_count": 32,
                        },
                    },
                },
            ],
        )
        print(" items:", json.dumps(items, ensure_ascii=False))
        self.assertEqual([item["type"] for item in items], ["data_table", "data_table"])
        insight_rows = items[0]["preview"]["preview_rows"]
        print(" insight rows:", insight_rows)
        annual = next(row for row in insight_rows if row.get("field") == "annual_rtn")
        hint = next(row for row in insight_rows if row.get("field") == "change_hint")
        self.assertEqual(annual["value"], 0.12)
        self.assertEqual(hint["value"], "Review strategy_meta parameters.")
        self.assertEqual(insight_rows[-1], {"side": "buy", "price": 10.5})
        opt_rows = items[1]["preview"]["preview_rows"]
        print(" optimize rows:", opt_rows)
        self.assertEqual(opt_rows[0], {"index": 0, "value": 12})
        self.assertEqual(opt_rows[1], {"index": 1, "value": 26})
        self.assertEqual(opt_rows[2], {"index": 2, "value": 9})
        self.assertEqual(opt_rows[3], {"parameter": "fv", "value": 1.35})
        self.assertEqual(items[1]["preview"]["data_summary"]["opti_method"], "montecarlo")
        self.assertEqual(items[1]["preview"]["data_summary"]["opti_sample_count"], 32)

    def test_backtest_report_text_not_metrics_card(self) -> None:
        """回测 Artifact 正文是 report_result 文本，不用 metrics 卡片冒充。"""

        print("\n[TestAiWorkbenchArtifacts] backtest report text")
        report = "Backtest Report\nfinal value:              ¥   112,000.00\n"
        items = classify_artifacts(
            "run_bt",
            [
                {
                    "step_id": "s4",
                    "skill_name": "qt.ai.backtest.run_builtin",
                    "result": {
                        "ok": True,
                        "metrics": {"mdd": -0.1, "final_value": 112000.0},
                        "artifacts": [{"kind": "trade_log", "path": "/tmp/t.csv"}],
                        "payload": {"report_text": report},
                    },
                }
            ],
        )
        print(" preview:", items[0]["preview"])
        self.assertEqual(items[0]["type"], "backtest_report")
        self.assertEqual(items[0]["preview"]["report"], report)
        self.assertNotIn("metrics", items[0]["preview"])
        self.assertEqual(items[0]["export_path"], "/tmp/t.csv")
        js = (Path(__file__).resolve().parents[1] / "qteasy_ai" / "workbench" / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        report_branch = js.split('current.type === "backtest_report"')[1].split("else if")[0]
        print(" report branch:", report_branch[:400])
        self.assertIn("report-text", report_branch)
        self.assertNotIn("metricsCards", report_branch)

    def test_insight_nan_trades_stay_json_compliant(self) -> None:
        """nearby_trades 里的 NaN/Inf 投影为 null，Starlette allow_nan=False 能序列化。"""

        print("\n[TestAiWorkbenchArtifacts] insight nan trades")
        items = classify_artifacts(
            "run_nan",
            [
                {
                    "step_id": "s_insight",
                    "skill_name": "qt.ai.insight.summarize_backtest",
                    "result": {
                        "ok": True,
                        "metrics": {"annual_rtn": 0.12},
                        "payload": {
                            "change_hint": "Review strategy_meta parameters.",
                            "nearby_trades": [
                                {
                                    "Unnamed: 0": "2015-12-22 15:00:00",
                                    "add. invest": float("nan"),
                                    "value": float("inf"),
                                    "000300.SH": 0.0,
                                }
                            ],
                        },
                    },
                }
            ],
        )
        trade = items[0]["preview"]["preview_rows"][-1]
        print(" trade row:", trade)
        self.assertEqual(trade["Unnamed: 0"], "2015-12-22 15:00:00")
        self.assertIsNone(trade["add. invest"])
        self.assertIsNone(trade["value"])
        self.assertEqual(trade["000300.SH"], 0.0)
        encoded = json.dumps(items, allow_nan=False)
        print(" encoded has null:", "null" in encoded)
        self.assertIn("null", encoded)


if __name__ == "__main__":
    unittest.main()
