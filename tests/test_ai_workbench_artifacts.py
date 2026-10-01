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

    def test_code_run_confirms_plan_not_editor_draft(self) -> None:
        """代码窗 Run 仅在计划仍可确认时出现，并调用 confirmPlan，不提交编辑器草稿。"""

        print("\n[TestAiWorkbenchArtifacts] code run confirms plan")
        js = (Path(__file__).resolve().parents[1] / "qteasy_ai" / "workbench" / "static" / "app.js").read_text(
            encoding="utf-8"
        )
        branch = js.split('current.type === "strategy_code"')[1].split("else if")[0]
        click = js.split("function onArtifactClick")[1].split("function sessionDisplayName")[0]
        print(" dead card:", "Confirm running edited strategy" in js)
        print(" branch has Run:", "btn-code-run" in branch)
        print(" click calls confirmPlan:", "confirmPlan()" in click)
        self.assertNotIn("Confirm running edited strategy", js)
        self.assertNotIn("btn-code-confirm", js)
        self.assertNotIn("pendingCodeRun", js)
        self.assertIn("plan_card.confirmable", branch)
        self.assertIn("btn-code-run", branch)
        self.assertIn("Editor text is not executed", branch)
        run_click = click.split('t.id === "btn-code-run"')[1].split('t.id === "btn-theme-dark"')[0]
        print(" run click:", run_click.strip())
        self.assertIn("confirmPlan()", run_click)
        self.assertNotIn("code-editor", run_click)
        self.assertNotIn("/v1/run\"", run_click)
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
                        "metrics": {
                            "annual_rtn": 0.12,
                            "mdd": 0.25,
                            "final_value": 112000.0,
                            "peak_date": None,
                        },
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
        self.assertEqual([item["type"] for item in items], ["data_table", "data_table", "data_table"])
        self.assertEqual(items[0]["title"], "qt.ai.insight.summarize_backtest")
        self.assertEqual(items[1]["title"], "nearby trades")
        insight_rows = items[0]["preview"]["preview_rows"]
        print(" insight rows:", insight_rows)
        annual = next(row for row in insight_rows if row.get("field") == "annual_rtn")
        self.assertEqual(annual["value"], 0.12)
        self.assertFalse(any(row.get("field") == "change_hint" for row in insight_rows))
        self.assertFalse(any(row.get("field") == "peak_date" for row in insight_rows))
        self.assertNotIn("change_hint", json.dumps(items[0]))
        trade_rows = items[1]["preview"]["preview_rows"]
        print(" trade rows:", trade_rows)
        self.assertEqual(trade_rows, [{"side": "buy", "price": 10.5}])
        opt_rows = items[2]["preview"]["preview_rows"]
        print(" optimize rows:", opt_rows)
        self.assertEqual(opt_rows[0], {"index": 0, "value": 12})
        self.assertEqual(opt_rows[1], {"index": 1, "value": 26})
        self.assertEqual(opt_rows[2], {"index": 2, "value": 9})
        self.assertEqual(opt_rows[3], {"parameter": "fv", "value": 1.35})
        self.assertEqual(items[2]["preview"]["data_summary"]["opti_method"], "montecarlo")
        self.assertEqual(items[2]["preview"]["data_summary"]["opti_sample_count"], 32)
        empty = classify_artifacts(
            "run_empty_insight",
            [
                {
                    "step_id": "s_empty",
                    "skill_name": "qt.ai.insight.summarize_backtest",
                    "result": {
                        "ok": True,
                        "metrics": {"annual_rtn": None, "mdd": ""},
                        "payload": {"change_hint": "unused", "nearby_trades": []},
                    },
                }
            ],
        )
        print(" empty insight:", empty)
        self.assertEqual(empty, [])

    def test_env_guide_steps_project_data_tables(self) -> None:
        """qt.ai.env.* 把 token 与表探针投影成 data_table，不混列、不丢 False。"""

        print("\n[TestAiWorkbenchArtifacts] env guide tables")
        items = classify_artifacts(
            "run_env",
            [
                {
                    "step_id": "s_token",
                    "skill_name": "qt.ai.env.check_tushare",
                    "result": {
                        "ok": True,
                        "metrics": {"token_present": False, "token_source": "missing"},
                        "data_summary": {"tushare": {"token_present": False, "token_source": "missing"}},
                        "payload": {"env_probe": {"tushare": {"token_present": False}}},
                        "artifacts": [],
                    },
                },
                {
                    "step_id": "s_tables",
                    "skill_name": "qt.ai.env.overview_tables",
                    "result": {
                        "ok": True,
                        "metrics": {
                            "table_count": 2,
                            "missing_count": 1,
                            "missing_tables": ["index_daily"],
                        },
                        "data_summary": {
                            "tables": {
                                "stock_daily": {"exists": True, "rows": 10, "pk_min": None, "pk_max": None},
                                "index_daily": {"exists": False, "rows": 0, "pk_min": None, "pk_max": None},
                            }
                        },
                        "payload": {
                            "env_probe": {
                                "tables": {
                                    "stock_daily": {"exists": True, "rows": 10, "pk_min": None, "pk_max": None},
                                    "index_daily": {"exists": False, "rows": 0, "pk_min": None, "pk_max": None},
                                }
                            }
                        },
                        "artifacts": [],
                    },
                },
            ],
        )
        print(" env items:", json.dumps(items, ensure_ascii=False))
        self.assertEqual([item["type"] for item in items], ["data_table", "data_table"])
        token_rows = items[0]["preview"]["preview_rows"]
        print(" token rows:", token_rows)
        present = next(row for row in token_rows if row.get("field") == "token_present")
        self.assertIs(present["value"], False)
        self.assertEqual(items[0]["preview"]["data_summary"]["token_present"], False)
        self.assertNotIn("tushare", items[0]["preview"]["data_summary"])
        table_rows = items[1]["preview"]["preview_rows"]
        print(" table rows:", table_rows)
        self.assertEqual([row["table"] for row in table_rows], ["stock_daily", "index_daily"])
        self.assertIs(table_rows[1]["exists"], False)
        self.assertEqual(table_rows[0]["rows"], 10)
        self.assertNotIn("pk_min", table_rows[0])
        self.assertNotIn("pk_max", table_rows[0])
        cards = items[1]["preview"]["data_summary"]
        print(" table cards:", cards)
        self.assertEqual(cards["table_count"], 2)
        self.assertEqual(cards["missing_count"], 1)
        self.assertNotIn("missing_tables", cards)
        self.assertNotIn("tables", cards)

    def test_project_universe_hits_become_data_table(self) -> None:
        """筛股 DAG 只把 project_universe 的 hits 投影成一张 data_table。"""

        print("\n[TestAiWorkbenchArtifacts] screen hits table")
        hit = {
            "symbol": "600180.SH",
            "name": "Alpha",
            "return": -0.25,
            "start_price": 4.0,
            "end_price": 3.0,
            "start_date": "20260325",
            "end_date": "20260924",
        }
        items = classify_artifacts(
            "run_screen",
            [
                {
                    "step_id": "s_uni",
                    "skill_name": "qt.ai.research.universe_filter",
                    "result": {
                        "ok": True,
                        "metrics": {"universe_size": 49},
                        "payload": {"symbols": ["600180.SH"], "industry": "仓储物流"},
                    },
                },
                {
                    "step_id": "s_pred",
                    "skill_name": "qt.ai.research.price_predicate",
                    "result": {
                        "ok": True,
                        "metrics": {"hit_count": 1},
                        "payload": {"hits": [hit], "industry": "仓储物流"},
                    },
                },
                {
                    "step_id": "s_proj",
                    "skill_name": "qt.ai.research.project_universe",
                    "result": {
                        "ok": True,
                        "metrics": {"hit_count": 1, "enumerated": False},
                        "payload": {"hits": [hit], "industry_samples": []},
                    },
                },
            ],
        )
        print(" types:", [item["type"] for item in items])
        print(" titles:", [item["title"] for item in items])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["type"], "data_table")
        self.assertEqual(items[0]["title"], "qt.ai.research.project_universe")
        rows = items[0]["preview"]["preview_rows"]
        print(" hit row:", rows[0] if rows else None)
        print(" summary:", items[0]["preview"]["data_summary"])
        self.assertEqual(rows[0]["symbol"], "600180.SH")
        self.assertEqual(rows[0]["name"], "Alpha")
        self.assertEqual(rows[0]["return"], -0.25)
        self.assertEqual(rows[0]["start_price"], 4.0)
        self.assertEqual(rows[0]["end_price"], 3.0)
        self.assertEqual(rows[0]["start_date"], "20260325")
        self.assertEqual(rows[0]["end_date"], "20260924")
        self.assertEqual(items[0]["preview"]["data_summary"]["hit_count"], 1)

        enumerated = classify_artifacts(
            "run_enum",
            [
                {
                    "step_id": "s_proj",
                    "skill_name": "qt.ai.research.project_universe",
                    "result": {
                        "ok": True,
                        "metrics": {"hit_count": 1, "enumerated": True},
                        "payload": {"hits": [{"symbol": "000001.SZ", "name": "Beta"}]},
                    },
                }
            ],
        )
        enum_rows = enumerated[0]["preview"]["preview_rows"]
        print(" enumerated row:", enum_rows[0])
        self.assertEqual(len(enumerated), 1)
        self.assertEqual(enum_rows[0], {"symbol": "000001.SZ", "name": "Beta"})

        empty = classify_artifacts(
            "run_empty",
            [
                {
                    "step_id": "s_proj",
                    "skill_name": "qt.ai.research.project_universe",
                    "result": {
                        "ok": True,
                        "metrics": {"hit_count": 0, "enumerated": False},
                        "payload": {"hits": []},
                    },
                }
            ],
        )
        print(" empty rows:", empty[0]["preview"]["preview_rows"])
        print(" empty summary:", empty[0]["preview"]["data_summary"])
        self.assertEqual(len(empty), 1)
        self.assertEqual(empty[0]["type"], "data_table")
        self.assertEqual(empty[0]["preview"]["preview_rows"], [])
        self.assertEqual(empty[0]["preview"]["data_summary"]["hit_count"], 0)

    def test_factor_ic_summary_projects_data_table(self) -> None:
        """因子 IC 成功步投影 data_table；失败步不造空表。"""

        print("\n[TestAiWorkbenchArtifacts] factor IC summary table")
        metrics = {
            "mean": 0.12,
            "std": 0.34,
            "ir": 0.35,
            "win_rate": 0.6,
            "n_periods": 20,
            "n_valid": 18,
        }
        ic_preview = [0.2, None, -0.1]
        items = classify_artifacts(
            "run_ic",
            [
                {
                    "step_id": "s_ic",
                    "skill_name": "qt.ai.research.factor_ic_summary",
                    "result": {
                        "ok": True,
                        "metrics": metrics,
                        "data_summary": {
                            "factor_htype": "close",
                            "return_htype": "volume",
                            "method": "spearman",
                            "ic_index_start": "2024-01-02",
                            "ic_index_end": "2024-01-31",
                        },
                        "payload": {"ic_preview": ic_preview},
                        "artifacts": [],
                    },
                }
            ],
        )
        print(" items:", json.dumps(items, ensure_ascii=False))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["type"], "data_table")
        self.assertEqual(items[0]["title"], "qt.ai.research.factor_ic_summary")
        self.assertEqual(items[0]["run_id"], "run_ic")
        rows = items[0]["preview"]["preview_rows"]
        print(" rows:", rows)
        print(" summary:", items[0]["preview"]["data_summary"])
        by_field = {row["field"]: row["value"] for row in rows}
        self.assertEqual(
            [row["field"] for row in rows],
            ["mean", "std", "ir", "win_rate", "n_periods", "n_valid", "ic_0", "ic_1", "ic_2"],
        )
        self.assertEqual(by_field["mean"], 0.12)
        self.assertEqual(by_field["std"], 0.34)
        self.assertEqual(by_field["ir"], 0.35)
        self.assertEqual(by_field["win_rate"], 0.6)
        self.assertEqual(by_field["n_periods"], 20)
        self.assertEqual(by_field["n_valid"], 18)
        self.assertEqual(by_field["ic_0"], ic_preview[0])
        self.assertIsNone(by_field["ic_1"])
        self.assertEqual(by_field["ic_2"], ic_preview[2])
        self.assertEqual(items[0]["preview"]["data_summary"]["method"], "spearman")
        self.assertEqual(items[0]["preview"]["data_summary"]["factor_htype"], "close")

        failed = classify_artifacts(
            "run_ic_fail",
            [
                {
                    "step_id": "s_fail",
                    "skill_name": "qt.ai.research.factor_ic_summary",
                    "result": {
                        "ok": False,
                        "metrics": {},
                        "error": {
                            "code": "FACTOR_IC_SUMMARY_FAILED",
                            "message": "Failed to compute factor IC summary: no local history.",
                        },
                    },
                }
            ],
        )
        print(" failed items:", failed)
        self.assertEqual(failed, [])

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
        trade_item = next(
            item
            for item in items
            if item.get("title") == "nearby trades"
        )
        trade = trade_item["preview"]["preview_rows"][0]
        print(" trade row:", trade)
        self.assertFalse(any(row.get("field") == "change_hint" for item in items for row in item["preview"]["preview_rows"]))
        self.assertEqual(trade["Unnamed: 0"], "2015-12-22 15:00:00")
        self.assertIsNone(trade["add. invest"])
        self.assertIsNone(trade["value"])
        self.assertEqual(trade["000300.SH"], 0.0)
        encoded = json.dumps(items, allow_nan=False)
        print(" encoded has null:", "null" in encoded)
        self.assertIn("null", encoded)


if __name__ == "__main__":
    unittest.main()
