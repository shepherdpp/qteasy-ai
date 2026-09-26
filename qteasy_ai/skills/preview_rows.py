# coding=utf-8
# ======================================
# File: preview_rows.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-27
# Desc:
# 把取数结果收成带列名、可 JSON 的预览行。
# ======================================

"""取数对象 → Artifact 预览行。"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

PREVIEW_ROW_CAP = 50


def tabular_preview_rows(data: Any, *, cap: int = PREVIEW_ROW_CAP) -> list[dict]:
    """把表状返回值收成记录行，并截到 ``cap``。

    Parameters
    ----------
    data : Any
        DataFrame、Series、按标的/名称分组的字典，或 HistoryPanel。
    cap : int, optional
        最大行数，默认 50。

    Returns
    -------
    list of dict
        列名为键的预览行；时间索引会变成一列。
    """

    limit = max(int(cap), 0)
    converted = _history_panel_frames(data)
    if converted is not data:
        return tabular_preview_rows(converted, cap=limit)
    if isinstance(data, pd.DataFrame):
        return _frame_records(data, limit)
    if isinstance(data, pd.Series):
        name = "value" if data.name is None else str(data.name)
        return _frame_records(data.to_frame(name=name), limit)
    if isinstance(data, dict):
        if data and all(isinstance(value, pd.DataFrame) for value in data.values()):
            pieces = []
            for key, frame in data.items():
                piece = frame.copy()
                piece.insert(0, "share", str(key))
                pieces.append(piece)
            return _frame_records(pd.concat(pieces), limit)
        if data and all(isinstance(value, pd.Series) for value in data.values()):
            aligned = pd.DataFrame({str(key): value for key, value in data.items()})
            return _frame_records(aligned, limit)
        return [
            {"key": str(key), "value": _json_cell(value)}
            for key, value in list(data.items())[:limit]
        ]
    if isinstance(data, list):
        if data and all(isinstance(item, dict) for item in data):
            return [_json_row(item) for item in data[:limit]]
        return [{"value": _json_cell(item)} for item in data[:limit]]
    if data is None:
        return []
    return [{"value": _json_cell(data)}]


def _history_panel_frames(data: Any) -> Any:
    """HistoryPanel 走 ``to_df_dict``；其它对象原样返回。"""

    if isinstance(data, (pd.DataFrame, pd.Series, dict, list, tuple)):
        return data
    converter = getattr(data, "to_df_dict", None)
    if not callable(converter):
        return data
    converted = converter(by="share")
    if converted is data:
        return data
    return converted


def _frame_records(frame: pd.DataFrame, cap: int) -> list[dict]:
    """索引进列，再截断并做成 JSON 安全记录。"""

    view = frame.head(cap).reset_index()
    return [_json_row(row) for row in view.to_dict(orient="records")]


def _json_row(row: dict) -> dict:
    """一行里的每个单元格都可被 ``json.dumps``。"""

    return {str(key): _json_cell(value) for key, value in row.items()}


def _json_cell(value: Any) -> Any:
    """标量改成 JSON 原生类型；时间改成文本；NaN 改成 None。"""

    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(str(_json_cell(item)) for item in value)
    if isinstance(value, dict):
        return {str(key): _json_cell(item) for key, item in value.items()}
    try:
        missing = bool(pd.isna(value))
    except (TypeError, ValueError):
        missing = False
    if missing:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            text = isoformat()
        except (TypeError, ValueError):
            text = None
        if isinstance(text, str):
            return text
    return str(value)
