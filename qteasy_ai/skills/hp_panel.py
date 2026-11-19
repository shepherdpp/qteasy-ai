# coding=utf-8
# ======================================
# File: hp_panel.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-01
# Desc:
# HistoryPanel 在技能之间的内存传递，以及英文失败消息。
# ======================================

"""面板步骤共用的取面板与英文错误。"""

from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from ..contracts import SkillError, SkillResult, new_run_id

_OHLCV = ("open", "high", "low", "close", "vol")


def order_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    """标准 K 线列按 open、high、low、close、vol 排列。其它列保持原顺序。

    Parameters
    ----------
    frame : DataFrame
        一张行情表。

    Returns
    -------
    DataFrame
        列序调整后的副本。索引名称保持不变。
    """

    columns = [str(name) for name in frame.columns]
    if set(columns) != set(_OHLCV):
        return frame
    ordered = frame.loc[:, list(_OHLCV)]
    return ordered.copy()


def reorder_panel_ohlcv(panel: Any) -> Any:
    """把标准 K 线面板的列序收成 open、high、low、close、vol。

    ``stack_dataframes`` 会按列名排序。这里在堆好之后改回 ``get_kline`` 的列序。

    Parameters
    ----------
    panel : HistoryPanel
        已堆好的面板。

    Returns
    -------
    HistoryPanel
        列序已是 OHLCV 时原样返回，否则换轴后的新面板。
    """

    htypes = [str(name) for name in panel.htypes]
    wanted = list(_OHLCV)
    if htypes == wanted or set(htypes) != set(wanted):
        return panel
    index = [htypes.index(name) for name in wanted]
    values = np.asarray(panel.values, dtype=float)[:, :, index]
    from qteasy.history import HistoryPanel

    return HistoryPanel(
        values,
        levels=list(panel.shares),
        rows=list(panel.hdates),
        columns=wanted,
    )


def english_message(exc: BaseException, fallback: str) -> str:
    """异常文字能用英文说清时沿用，否则用调用方给的英文句子。

    Parameters
    ----------
    exc : BaseException
        捕获到的异常。
    fallback : str
        非英文或带回溯时的替代句。

    Returns
    -------
    str
        可送到工作台的英文句子。
    """

    text = " ".join(str(exc).split())
    if text and text.isascii() and "Traceback" not in text:
        return text
    return fallback


def failed(skill_name: str, code: str, message: str, inputs_echo: Dict[str, Any]) -> Dict[str, Any]:
    """组装一次失败的技能返回。

    Parameters
    ----------
    skill_name : str
        注册名。
    code : str
        技能错误码。
    message : str
        英文说明。
    inputs_echo : dict
        回显的入参，不含面板对象。

    Returns
    -------
    dict
        ``SkillResult.to_dict()``。
    """

    result = SkillResult(
        ok=False,
        skill_name=skill_name,
        run_id=new_run_id(),
        inputs_echo=inputs_echo,
        error=SkillError(code=code, message=message),
    )
    return result.to_dict()


def panel_from_upstream(upstream_payload: Optional[Dict[str, Any]]) -> Any:
    """从上游 payload 取出 HistoryPanel。没有则返回 None。

    Parameters
    ----------
    upstream_payload : dict, optional
        上一步的 ``payload``。

    Returns
    -------
    HistoryPanel or None
        内存中的面板。落盘后的省略标记不算。
    """

    if not isinstance(upstream_payload, dict):
        return None
    panel = upstream_payload.get("panel")
    if type(panel).__name__ != "HistoryPanel":
        return None
    return panel


def as_history_panel(data: Any, shares: str) -> Any:
    """把 ``get_kline`` 的返回值收成 HistoryPanel。

    Parameters
    ----------
    data : Any
        DataFrame、按标的分组的字典，或已经是 HistoryPanel。
    shares : str
        单表堆成面板时用的标的标签。

    Returns
    -------
    HistoryPanel
        非空面板。

    Raises
    ------
    ValueError
        没有可用行情时。
    """

    from qteasy.history import HistoryPanel, stack_dataframes

    if isinstance(data, HistoryPanel):
        if data.is_empty:
            raise ValueError("No kline data returned.")
        return reorder_panel_ohlcv(data)
    if isinstance(data, dict):
        frames = {
            str(key): order_ohlcv(frame)
            for key, frame in data.items()
            if isinstance(frame, pd.DataFrame) and not frame.empty
        }
        if not frames:
            raise ValueError("No kline data returned.")
        return reorder_panel_ohlcv(stack_dataframes(frames, dataframe_as="shares"))
    if isinstance(data, pd.DataFrame):
        if data.empty:
            raise ValueError("No kline data returned.")
        label = str(shares or "").split(",")[0].strip() or "share"
        stacked = stack_dataframes({label: order_ohlcv(data)}, dataframe_as="shares")
        return reorder_panel_ohlcv(stacked)
    raise ValueError("No kline data returned.")
