# coding=utf-8
# ======================================
# File: datasource_tables.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-02
# Desc:
# 只读技能：单表信息与指定表的总览。不默认扫全库。
# ======================================

"""数据表探针。table_overview 的 tables 必填。"""

from __future__ import annotations

import contextlib
import io
from typing import Any, Callable, Optional, Sequence

from ..contracts import SkillMetadata, SkillResult, SkillSideEffects, new_run_id
from .hp_panel import english_message, failed
from .preview_rows import PREVIEW_ROW_CAP, tabular_preview_rows

_COLUMN_CAP = PREVIEW_ROW_CAP


def column_notes(table_name: str) -> list[dict]:
    """内置表的列名、类型和说明。未知表返回空列表。

    Parameters
    ----------
    table_name : str
        ``TABLE_MASTERS`` 里的表名。

    Returns
    -------
    list of dict
        至多 ``PREVIEW_ROW_CAP`` 行。
    """

    from qteasy.datatables import get_built_in_table_schema

    try:
        columns, dtypes, remarks = get_built_in_table_schema(
            table_name,
            with_remark=True,
            with_primary_keys=False,
        )
    except (TypeError, KeyError):
        return []
    rows = [
        {"column": str(column), "dtype": str(dtype), "remark": str(remark)}
        for column, dtype, remark in zip(columns, dtypes, remarks)
    ]
    return rows[:_COLUMN_CAP]


def _table_names(tables: Any) -> list[str]:
    """把逗号串或列表收成表名。空串丢弃。"""

    if tables is None:
        return []
    if isinstance(tables, str):
        return [item.strip() for item in tables.split(",") if item.strip()]
    if isinstance(tables, (list, tuple)):
        return [str(item).strip() for item in tables if str(item).strip()]
    return []


def _default_table_info(table: str, verbose: bool = False, print_info: bool = False, human: bool = False) -> dict:
    """关闭打印后读一张表的结构化信息。"""

    from qteasy import QT_DATA_SOURCE

    info = QT_DATA_SOURCE.get_table_info(table, verbose=verbose, print_info=print_info, human=human)
    return info if isinstance(info, dict) else {}


def _default_overview(tables: Sequence[str], include_sys_tables: bool = False, print_out: bool = False) -> Any:
    """指定表的总览。调用方负责吞掉库内的进度打印。"""

    from qteasy import QT_DATA_SOURCE

    return QT_DATA_SOURCE.overview(
        tables=list(tables),
        include_sys_tables=include_sys_tables,
        print_out=print_out,
    )


def probe_table(
    table_name: str,
    table_info_func: Callable[..., Any],
    schema_func: Callable[[str], list],
) -> dict:
    """读一张表的存在性、行数、主键范围和列说明。

    Parameters
    ----------
    table_name : str
        表名。
    table_info_func : callable
        ``DataSource.get_table_info`` 或测试替身。
    schema_func : callable
        列说明。未知表可返回空列表。

    Returns
    -------
    dict
        ``exists`` / ``rows`` / ``pk_min`` / ``pk_max`` / ``columns``。

    Raises
    ------
    ValueError
        表名不在内置目录里。
    """

    try:
        info = table_info_func(table_name, verbose=False, print_info=False, human=False)
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"Table '{table_name}' is not a known table.") from exc
    if not isinstance(info, dict):
        info = {}
    if "exists" in info and "rows" in info:
        exists = bool(info["exists"])
        try:
            rows = int(info.get("rows", 0) or 0)
        except (TypeError, ValueError):
            rows = 0
        pk_min = info.get("pk_min", info.get("pk_min1"))
        pk_max = info.get("pk_max", info.get("pk_max1"))
    else:
        exists = bool(info.get("table_exists", False))
        raw_rows = info.get("table_rows", 0)
        try:
            rows = int(raw_rows) if raw_rows not in (None, "") else 0
        except (TypeError, ValueError):
            rows = 0
        pk_min = info.get("pk_min1")
        pk_max = info.get("pk_max1")
    columns = list(schema_func(table_name) or [])[:_COLUMN_CAP]
    return {
        "exists": exists,
        "rows": rows,
        "pk_min": None if pk_min is None else str(pk_min),
        "pk_max": None if pk_max is None else str(pk_max),
        "columns": columns,
    }


def build_table_info_skill(
    table_info_func: Callable[..., Any] | None = None,
    schema_func: Callable[[str], list] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.datasource.table_info``。

    Parameters
    ----------
    table_info_func, schema_func : callable, optional
        注入表探针和列说明。缺省走本地数据源，且 ``print_info=False``。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。一次一张表。
    """

    if table_info_func is None:
        table_info_func = _default_table_info
    if schema_func is None:
        schema_func = column_notes

    metadata = SkillMetadata(
        name="qt.ai.datasource.table_info",
        version="0.1.0",
        summary="Describe one local table: existence, rows, primary-key range, and columns.",
        inputs_schema={"table_name": {"type": "string", "required": True}},
        outputs_schema={"payload": "dict", "data_summary": "dict"},
        side_effects=SkillSideEffects(description="readonly table info"),
        required_capabilities=["local_datasource"],
        qteasy_entrypoints=["qteasy.get_table_info"],
        expected_artifact="Whether one named table exists, its row count, key range, and column notes.",
    )

    def handler(table_name: Optional[str] = None, **kwargs) -> dict:
        name = str(table_name or "").strip()
        inputs_echo = {"table_name": name}
        if not name:
            return failed(
                metadata.name,
                "TABLE_NAME_REQUIRED",
                "table_name is required. This skill reads one table at a time.",
                inputs_echo,
            )
        try:
            probe = probe_table(name, table_info_func, schema_func)
        except ValueError as exc:
            return failed(
                metadata.name,
                "TABLE_UNKNOWN",
                english_message(exc, f"Table '{name}' is not a known table."),
                inputs_echo,
            )
        except Exception as exc:
            return failed(
                metadata.name,
                "TABLE_INFO_FAILED",
                english_message(exc, f"Failed to read table '{name}'."),
                inputs_echo,
            )
        summary = {
            "table": name,
            "exists": probe["exists"],
            "rows": probe["rows"],
            "pk_min": probe["pk_min"],
            "pk_max": probe["pk_max"],
        }
        result = SkillResult(
            ok=True,
            skill_name=metadata.name,
            run_id=new_run_id(),
            inputs_echo=inputs_echo,
            metrics={"exists": probe["exists"], "rows": probe["rows"], "n_columns": len(probe["columns"])},
            data_summary=summary,
            payload={
                "columns": probe["columns"],
                "preview_rows": probe["columns"],
                "env_probe": {"tables": {name: summary}},
            },
        )
        return result.to_dict()

    return metadata, handler


def build_table_overview_skill(
    overview_func: Callable[..., Any] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.datasource.table_overview``。

    Parameters
    ----------
    overview_func : callable, optional
        注入 ``DataSource.overview``。缺省时读本地数据源。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。省略 ``tables`` 会被拒绝。
    """

    if overview_func is None:
        overview_func = _default_overview

    metadata = SkillMetadata(
        name="qt.ai.datasource.table_overview",
        version="0.1.0",
        summary="Overview named local tables. tables is required.",
        inputs_schema={
            "tables": {"type": "list", "required": True},
            "include_sys_tables": {"type": "boolean", "required": False},
        },
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly table overview"),
        required_capabilities=["local_datasource"],
        qteasy_entrypoints=["qteasy.get_table_overview"],
        expected_artifact="A truncated overview of the named tables.",
    )

    def handler(
        tables: Any = None,
        include_sys_tables: bool = False,
        **kwargs,
    ) -> dict:
        names = _table_names(tables)
        inputs_echo = {"tables": names, "include_sys_tables": bool(include_sys_tables)}
        if not names:
            return failed(
                metadata.name,
                "TABLES_REQUIRED",
                "tables is required. Omitting it does not scan the whole data source.",
                inputs_echo,
            )
        out_buf, err_buf = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
                frame = overview_func(
                    tables=names,
                    include_sys_tables=bool(include_sys_tables),
                    print_out=False,
                )
        except Exception as exc:
            return failed(
                metadata.name,
                "TABLE_OVERVIEW_FAILED",
                english_message(exc, "Failed to overview the named tables."),
                inputs_echo,
            )
        preview = tabular_preview_rows(frame, cap=PREVIEW_ROW_CAP)
        result = SkillResult(
            ok=True,
            skill_name=metadata.name,
            run_id=new_run_id(),
            inputs_echo=inputs_echo,
            metrics={"n_preview": len(preview), "n_tables": len(names)},
            data_summary={"tables": names},
            payload={"preview_rows": preview},
        )
        return result.to_dict()

    return metadata, handler
