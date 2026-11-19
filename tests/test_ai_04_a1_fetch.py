# coding=utf-8
# ======================================
# File: test_ai_04_a1_fetch.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-02
# Desc:
# 0.4 A1：本地取数原子、目录探针与财报薄封装。
# ======================================

import contextlib
import io
import unittest

import numpy as np
import pandas as pd

from qteasy.history import HistoryPanel
from qteasy_ai.app import build_default_registry
from qteasy_ai.skills.data_history import build_data_history_skill
from qteasy_ai.skills.data_reference import build_data_reference_skill
from qteasy_ai.skills.data_statement import build_data_statement_skill
from qteasy_ai.skills.data_static import build_data_static_skill
from qteasy_ai.skills.datasource_tables import (
    build_table_info_skill,
    build_table_overview_skill,
)
from qteasy_ai.skills.dtype_find import build_dtype_find_skill

_INCOME_DEFAULT = [
    "total_revenue",
    "operate_profit",
    "total_profit",
    "n_income_attr_p",
    "basic_eps",
]


def _panel(values, shares, columns, dates) -> HistoryPanel:
    """用已知数组做一块面板。values 形状为 (标的, 时间, 列)。"""

    return HistoryPanel(
        np.asarray(values, dtype=float),
        levels=list(shares),
        rows=pd.to_datetime(list(dates)),
        columns=list(columns),
    )


class TestAi04A1Fetch(unittest.TestCase):
    """取数、目录与财报原子。注入假函数，不读本地库。"""

    def test_history_returns_panel_with_known_close(self) -> None:
        """history 固定 as_data_frame=False，收盘价与传入面板一致。"""

        print("\n[TestAi04A1Fetch] history close")
        panel = _panel([[[10.0], [12.5]]], ["000001.SZ"], ["close"], ["2024-01-02", "2024-01-03"])
        called = {}

        def fake_history(**kwargs):
            called.update(kwargs)
            return panel

        _, handler = build_data_history_skill(get_history_func=fake_history)
        result = handler(
            htype_names="close",
            shares="000001.SZ",
            start="20240102",
            end="20240103",
            freq="d",
        )
        got = result["payload"]["panel"]
        close = float(got.values[0, -1, 0])
        print(" called:", called)
        print(" close:", close, "htypes:", list(got.htypes))
        self.assertTrue(result["ok"])
        self.assertIs(got, panel)
        self.assertEqual(close, 12.5)
        self.assertFalse(called["as_data_frame"])
        self.assertEqual(called["htype_names"], "close")
        self.assertEqual(called["shares"], "000001.SZ")

    def test_history_requires_shares_and_a_date(self) -> None:
        """缺代码或缺日期窗时不调用取数。"""

        print("\n[TestAi04A1Fetch] history required")
        called = []

        def fake_history(**kwargs):
            called.append(kwargs)
            raise AssertionError("should not fetch")

        _, handler = build_data_history_skill(get_history_func=fake_history)
        missing_shares = handler(htype_names="close", start="20240101", end="20240131")
        missing_window = handler(htype_names="close", shares="000001.SZ", rows=10)
        print(" shares error:", missing_shares["error"])
        print(" window error:", missing_window["error"])
        self.assertFalse(missing_shares["ok"])
        self.assertIn("shares", missing_shares["error"]["message"])
        self.assertFalse(missing_window["ok"])
        self.assertIn("start", missing_window["error"]["message"])
        self.assertEqual(called, [])
        self.assertNotIn("Traceback", missing_shares["error"]["message"])

    def test_history_passes_ascii_library_error(self) -> None:
        """库的英文错形状说明原样送出，回溯句换成英文短句。"""

        print("\n[TestAi04A1Fetch] history errors")

        def wrong_shape(**kwargs):
            raise ValueError("industry is static; use qt.get_static_data(...) instead.")

        _, handler = build_data_history_skill(get_history_func=wrong_shape)
        result = handler(htype_names="industry", shares="000001.SZ", start="20240101")
        print(" error:", result["error"])
        self.assertFalse(result["ok"])
        self.assertIn("get_static_data", result["error"]["message"])

        def boom(**kwargs):
            raise RuntimeError("Traceback (most recent call last): hidden")

        _, handler_boom = build_data_history_skill(get_history_func=boom)
        failed = handler_boom(htype_names="close", shares="000001.SZ", end="20240131")
        print(" boom:", failed["error"])
        self.assertNotIn("Traceback", failed["error"]["message"])

    def test_reference_preview_has_no_panel(self) -> None:
        """reference 只给截断预览，不放 HistoryPanel。"""

        print("\n[TestAi04A1Fetch] reference")
        series = pd.Series(
            [1.5, 2.5],
            index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
            name="cn_gdp",
        )

        def fake_reference(**kwargs):
            return {"cn_gdp": series}

        _, handler = build_data_reference_skill(get_reference_func=fake_reference)
        result = handler(names="cn_gdp", start="20240101", end="20240131")
        preview = result["payload"]["preview_rows"]
        print(" preview:", preview)
        self.assertTrue(result["ok"])
        self.assertNotIn("panel", result["payload"])
        self.assertTrue(any(row.get("cn_gdp") == 2.5 for row in preview))
        missing = handler(start="20240101")
        print(" missing:", missing["error"])
        self.assertFalse(missing["ok"])
        self.assertIn("names", missing["error"]["message"])

    def test_static_requires_names_and_shares(self) -> None:
        """static 拒绝空股票池，成功时预览含行业。"""

        print("\n[TestAi04A1Fetch] static")
        called = []

        def fake_static(**kwargs):
            called.append(kwargs)
            return pd.DataFrame({"industry": ["银行"]}, index=pd.Index(["000001.SZ"], name="qt_code"))

        _, handler = build_data_static_skill(get_static_func=fake_static)
        empty = handler(names="industry", shares="  ")
        print(" empty:", empty["error"])
        self.assertFalse(empty["ok"])
        self.assertIn("shares", empty["error"]["message"])
        self.assertEqual(called, [])
        result = handler(names="industry", shares="000001.SZ", asset_type="E")
        print(" preview:", result["payload"]["preview_rows"])
        print(" called:", called)
        self.assertTrue(result["ok"])
        self.assertEqual(called[0]["shares"], "000001.SZ")
        self.assertEqual(called[0]["asset_type"], "E")
        self.assertIn("银行", str(result["payload"]["preview_rows"]))

    def test_dtype_find_forces_frame_and_truncates(self) -> None:
        """find 固定 as_data_frame=True，预览最多 50 行。"""

        print("\n[TestAi04A1Fetch] dtype.find")
        frame = pd.DataFrame({"name": [f"n{i}" for i in range(60)], "freq": ["d"] * 60})
        called = {}

        def fake_find(*args, **kwargs):
            called["args"] = args
            called["kwargs"] = kwargs
            return frame

        _, handler = build_dtype_find_skill(find_func=fake_find)
        result = handler(s="pe", as_data_frame=False)
        preview = result["payload"]["preview_rows"]
        print(" kwargs:", called["kwargs"])
        print(" n_preview:", len(preview), "first:", preview[0]["name"])
        self.assertTrue(result["ok"])
        self.assertTrue(called["kwargs"]["as_data_frame"])
        self.assertEqual(len(preview), 50)
        self.assertEqual(preview[0]["name"], "n0")

    def test_table_info_structured_and_quiet(self) -> None:
        """table_info 返回存在性、行数、主键和列说明，且不打印。"""

        print("\n[TestAi04A1Fetch] table_info")
        seen = {}

        def fake_info(*args, **kwargs):
            seen["args"] = args
            seen["kwargs"] = kwargs
            if kwargs.get("print_info", True):
                print("LEAK")
            return {
                "table_exists": True,
                "table_rows": 3,
                "pk_min1": "000001.SZ",
                "pk_max1": "000002.SZ",
            }

        def fake_schema(table):
            return [{"column": "ts_code", "dtype": "varchar(9)", "remark": "证券代码"}]

        _, handler = build_table_info_skill(table_info_func=fake_info, schema_func=fake_schema)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            result = handler(table_name="stock_daily")
        summary = result["data_summary"]
        columns = result["payload"]["columns"]
        print(" summary:", summary)
        print(" columns:", columns)
        print(" stdout:", repr(buf.getvalue()))
        print(" flags:", seen["kwargs"])
        self.assertEqual(buf.getvalue(), "")
        self.assertFalse(seen["kwargs"]["print_info"])
        self.assertFalse(seen["kwargs"]["verbose"])
        self.assertFalse(seen["kwargs"]["human"])
        self.assertTrue(result["ok"])
        self.assertTrue(summary["exists"])
        self.assertEqual(summary["rows"], 3)
        self.assertEqual(summary["pk_min"], "000001.SZ")
        self.assertEqual(summary["pk_max"], "000002.SZ")
        self.assertEqual(columns[0]["column"], "ts_code")
        self.assertEqual(columns[0]["remark"], "证券代码")

    def test_table_info_missing_and_unknown(self) -> None:
        """无数据的已知表 ok 且 exists=false；未知表名英文停止。"""

        print("\n[TestAi04A1Fetch] table_info missing/unknown")

        def fake_info(*args, **kwargs):
            table = args[0] if args else kwargs.get("table")
            if table == "no_such_table":
                raise ValueError(f"in valid table name: {table}")
            return {"table_exists": False, "table_rows": 0, "pk_min1": None, "pk_max1": None}

        _, handler = build_table_info_skill(table_info_func=fake_info, schema_func=lambda table: [])
        missing = handler(table_name="stock_daily")
        unknown = handler(table_name="no_such_table")
        print(" missing:", missing["data_summary"], missing["ok"])
        print(" unknown:", unknown["error"])
        self.assertTrue(missing["ok"])
        self.assertFalse(missing["data_summary"]["exists"])
        self.assertEqual(missing["data_summary"]["rows"], 0)
        self.assertFalse(unknown["ok"])
        self.assertIn("no_such_table", unknown["error"]["message"])
        self.assertIn("known", unknown["error"]["message"])
        self.assertNotIn("Traceback", unknown["error"]["message"])

    def test_table_overview_rejects_empty_and_truncates(self) -> None:
        """overview 拒绝空 tables，调用时关掉打印，预览截到 50 行。"""

        print("\n[TestAi04A1Fetch] table_overview")
        called = []

        def fake_overview(**kwargs):
            called.append(kwargs)
            print("NOISE_OUT")
            import sys
            print("NOISE_ERR", file=sys.stderr)
            frame = pd.DataFrame({"records": list(range(60))})
            return frame

        _, handler = build_table_overview_skill(overview_func=fake_overview)
        empty = handler(tables="")
        omitted = handler()
        print(" empty:", empty["error"])
        print(" omitted:", omitted["error"])
        self.assertFalse(empty["ok"])
        self.assertFalse(omitted["ok"])
        self.assertEqual(called, [])
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            result = handler(tables=["stock_daily", "index_daily"])
        preview = result["payload"]["preview_rows"]
        print(" called:", called)
        print(" n_preview:", len(preview), "first records:", preview[0]["records"])
        print(" leaked out:", repr(buf_out.getvalue()), "err:", repr(buf_err.getvalue()))
        self.assertTrue(result["ok"])
        self.assertEqual(called[0]["tables"], ["stock_daily", "index_daily"])
        self.assertFalse(called[0]["include_sys_tables"])
        self.assertFalse(called[0]["print_out"])
        self.assertEqual(len(preview), 50)
        self.assertEqual(preview[0]["records"], 0)
        self.assertNotIn("NOISE_OUT", buf_out.getvalue())
        self.assertNotIn("NOISE_ERR", buf_err.getvalue())

    def test_statement_default_fields_and_override(self) -> None:
        """利润表默认列；fields 可换成该表已有列。"""

        print("\n[TestAi04A1Fetch] statement fields")
        calls = []

        def fake_history(**kwargs):
            calls.append(dict(kwargs))
            names = [item.strip() for item in str(kwargs["htype_names"]).split(",") if item.strip()]
            values = np.ones((1, 1, len(names)))
            return _panel(values, ["000001.SZ"], names, ["2024-03-31"])

        _, handler = build_data_statement_skill(
            history_func=fake_history,
            table_exists_func=lambda name: True,
        )
        result = handler(shares="000001.SZ", period="20240331", statement="income")
        requested = [item.strip() for item in calls[0]["htype_names"].split(",")]
        panel = result["payload"]["panel"]
        print(" requested:", requested)
        print(" htypes:", list(panel.htypes), "value:", float(panel.values[0, 0, 0]))
        self.assertTrue(result["ok"])
        self.assertEqual(requested, _INCOME_DEFAULT)
        self.assertEqual(list(panel.htypes), _INCOME_DEFAULT)
        self.assertEqual(float(panel.values[0, 0, 0]), 1.0)
        self.assertEqual(calls[0]["freq"], "q")
        self.assertFalse(calls[0]["as_data_frame"])
        calls.clear()
        overridden = handler(
            shares="000001.SZ",
            period="20240331",
            statement="income",
            fields="revenue",
        )
        print(" override:", calls[0]["htype_names"], list(overridden["payload"]["panel"].htypes))
        self.assertTrue(overridden["ok"])
        self.assertEqual(calls[0]["htype_names"], "revenue")
        self.assertEqual(list(overridden["payload"]["panel"].htypes), ["revenue"])

    def test_statement_rejects_foreign_field_and_missing_table(self) -> None:
        """不属于该表的列，以及缺表，都用英文停止且不取数。"""

        print("\n[TestAi04A1Fetch] statement reject")
        calls = []

        def fake_history(**kwargs):
            calls.append(kwargs)
            raise AssertionError("should not fetch")

        _, handler = build_data_statement_skill(
            history_func=fake_history,
            table_exists_func=lambda name: name != "income",
        )
        foreign = handler(
            shares="000001.SZ",
            period="20240331",
            statement="balance",
            fields="close",
        )
        missing = handler(shares="000001.SZ", period="20240331", statement="income")
        print(" foreign:", foreign["error"])
        print(" missing:", missing["error"])
        self.assertFalse(foreign["ok"])
        self.assertIn("close", foreign["error"]["message"])
        self.assertFalse(missing["ok"])
        self.assertIn("income", missing["error"]["message"])
        self.assertIn("missing", missing["error"]["message"].lower())
        self.assertNotIn("Traceback", missing["error"]["message"])
        self.assertEqual(calls, [])

    def test_statement_qoq_and_zero_base(self) -> None:
        """环比差额与变化比例对照手工值；上期为 0 时比例为空。"""

        print("\n[TestAi04A1Fetch] statement qoq")

        def fake_history(**kwargs):
            names = [item.strip() for item in str(kwargs["htype_names"]).split(",") if item.strip()]
            # 20231231 -> 100 / 40，20240331 -> 110 / 50；零基调用另做。
            if names == ["total_revenue"]:
                values = [[[0.0], [5.0]]]
            else:
                values = [[[100.0, 40.0], [110.0, 50.0]]]
            return _panel(
                values,
                ["000001.SZ"],
                names,
                ["2023-12-31", "2024-03-31"],
            )

        seen = []

        def recording(**kwargs):
            seen.append(dict(kwargs))
            return fake_history(**kwargs)

        _, handler = build_data_statement_skill(
            history_func=recording,
            table_exists_func=lambda name: True,
        )
        result = handler(
            shares="000001.SZ",
            period="20240331",
            statement="income",
            fields="total_revenue,operate_profit",
            compare="qoq",
        )
        rows = result["payload"]["comparison"]
        print(" window:", seen[0]["start"], seen[0]["end"])
        print(" rows:", rows)
        self.assertTrue(result["ok"])
        self.assertEqual(seen[0]["start"], "20231231")
        self.assertEqual(seen[0]["end"], "20240331")
        self.assertEqual(len(seen), 1)
        self.assertEqual(rows[0]["field"], "total_revenue")
        self.assertEqual(rows[0]["current"], 110.0)
        self.assertEqual(rows[0]["previous"], 100.0)
        self.assertEqual(rows[0]["difference"], 10.0)
        self.assertAlmostEqual(rows[0]["change_ratio"], 0.1)
        self.assertEqual(rows[1]["field"], "operate_profit")
        self.assertEqual(rows[1]["difference"], 10.0)
        self.assertAlmostEqual(rows[1]["change_ratio"], 0.25)
        zero = handler(
            shares="000001.SZ",
            period="20240331",
            statement="income",
            fields="total_revenue",
            compare="qoq",
        )
        zero_row = zero["payload"]["comparison"][0]
        print(" zero row:", zero_row)
        self.assertTrue(zero["ok"])
        self.assertEqual(zero_row["current"], 5.0)
        self.assertEqual(zero_row["previous"], 0.0)
        self.assertEqual(zero_row["difference"], 5.0)
        self.assertIsNone(zero_row["change_ratio"])

    def test_statement_yoy_window_and_missing_period(self) -> None:
        """同比取去年同日；对比期不在面板里时英文点名该期。"""

        print("\n[TestAi04A1Fetch] statement yoy / missing period")
        calls = []

        def fake_history(**kwargs):
            calls.append(dict(kwargs))
            return _panel([[[110.0]]], ["000001.SZ"], ["total_revenue"], ["2024-03-31"])

        _, handler = build_data_statement_skill(
            history_func=fake_history,
            table_exists_func=lambda name: True,
        )
        missing = handler(
            shares="000001.SZ",
            period="20240331",
            statement="income",
            fields="total_revenue",
            compare="qoq",
        )
        print(" missing period:", missing["error"])
        self.assertFalse(missing["ok"])
        self.assertIn("20231231", missing["error"]["message"])
        calls.clear()

        def yoy_history(**kwargs):
            calls.append(dict(kwargs))
            return _panel(
                [[[80.0], [110.0]]],
                ["000001.SZ"],
                ["total_revenue"],
                ["2023-03-31", "2024-03-31"],
            )

        _, handler_yoy = build_data_statement_skill(
            history_func=yoy_history,
            table_exists_func=lambda name: True,
        )
        result = handler_yoy(
            shares="000001.SZ",
            period="20240331",
            statement="income",
            fields="total_revenue",
            compare="yoy",
        )
        row = result["payload"]["comparison"][0]
        print(" yoy window:", calls[0]["start"], calls[0]["end"])
        print(" yoy row:", row)
        self.assertTrue(result["ok"])
        self.assertEqual(calls[0]["start"], "20230331")
        self.assertEqual(calls[0]["end"], "20240331")
        self.assertEqual(row["previous"], 80.0)
        self.assertEqual(row["current"], 110.0)
        self.assertEqual(row["difference"], 30.0)
        self.assertAlmostEqual(row["change_ratio"], 30.0 / 80.0)

    def test_fetch_skills_are_registered(self) -> None:
        """新取数原子在默认注册表里。"""

        print("\n[TestAi04A1Fetch] registry")
        names = {item.name for item in build_default_registry().list_skills()}
        expected = {
            "qt.ai.data.history",
            "qt.ai.data.reference",
            "qt.ai.data.static",
            "qt.ai.data.statement",
            "qt.ai.dtype.find",
            "qt.ai.datasource.table_info",
            "qt.ai.datasource.table_overview",
        }
        print(" missing:", sorted(expected - names))
        self.assertTrue(expected <= names)


if __name__ == "__main__":
    unittest.main()
