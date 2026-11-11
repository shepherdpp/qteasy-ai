# coding=utf-8
# ======================================
# File: data_statement.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-02
# Desc:
# 只读技能：某一期三大报表。底层仍是 get_history_data。
# ======================================

"""财务报表薄封装。可选环比或同比，不做比率分析。"""

from __future__ import annotations

import math
from datetime import datetime
from functools import lru_cache
from typing import Any, Callable, Optional, Sequence

from ..contracts import SkillMetadata, SkillResult, SkillSideEffects, new_run_id
from ..slot_graph import code_spec
from .hp_panel import english_message, failed
from .preview_rows import tabular_preview_rows

_STATEMENT_TABLE = {
    "income": "income",
    "balance": "balance",
    "cashflow": "cashflow",
}
_DEFAULT_FIELDS = {
    "income": [
        "total_revenue",
        "operate_profit",
        "total_profit",
        "n_income_attr_p",
        "basic_eps",
    ],
    "balance": [
        "money_cap",
        "total_assets",
        "total_liab",
        "total_hldr_eqy_exc_min_int",
    ],
    "cashflow": [
        "n_cashflow_act",
        "n_cashflow_inv_act",
        "n_cash_flows_fnc_act",
        "c_cash_equ_end_period",
    ],
}
_QUARTER_ENDS = ((3, 31), (6, 30), (9, 30), (12, 31))


def _split_fields(fields: Any, defaults: Sequence[str]) -> list[str]:
    """逗号串或列表。空则用该表的默认列。"""

    if fields is None:
        return list(defaults)
    if isinstance(fields, str) and not fields.strip():
        return list(defaults)
    if isinstance(fields, (list, tuple)):
        names = [str(item).strip() for item in fields if str(item).strip()]
        return names or list(defaults)
    names = [item.strip() for item in str(fields).split(",") if item.strip()]
    return names or list(defaults)


@lru_cache(maxsize=8)
def _names_on_table(table: str) -> frozenset:
    """该物理表上已登记的历史数据类型宽名。"""

    from qteasy.datatypes import DATA_TYPE_MAP

    names = set()
    for key, spec in DATA_TYPE_MAP.items():
        if not isinstance(key, tuple) or not key:
            continue
        if not isinstance(spec, (list, tuple)) or len(spec) < 3:
            continue
        meta = spec[2]
        if isinstance(meta, dict) and str(meta.get("table_name") or "") == table:
            names.add(str(key[0]))
    return frozenset(names)


def _parse_period(text: str) -> datetime:
    """``YYYYMMDD`` 或带分隔符的报告期。"""

    digits = "".join(ch for ch in str(text or "") if ch.isdigit())
    if len(digits) < 8:
        raise ValueError(f"period must be YYYYMMDD, got {text!r}.")
    return datetime.strptime(digits[:8], "%Y%m%d")


def _stamp(moment: datetime) -> str:
    """报告期写成 ``YYYYMMDD``。"""

    return moment.strftime("%Y%m%d")


def _previous_quarter_end(moment: datetime) -> datetime:
    """给定日期之前的最近一个季末。"""

    current = datetime(moment.year, moment.month, moment.day)
    prior = [
        datetime(year, month, day)
        for year in (moment.year - 1, moment.year)
        for month, day in _QUARTER_ENDS
        if datetime(year, month, day) < current
    ]
    if not prior:
        raise ValueError(f"Cannot resolve the previous quarter for {_stamp(current)}.")
    return prior[-1]


def _year_ago(moment: datetime) -> datetime:
    """去年同一天。2 月 29 日落到 2 月 28 日。"""

    try:
        return moment.replace(year=moment.year - 1)
    except ValueError:
        return moment.replace(year=moment.year - 1, day=28)


def _date_key(value: Any) -> str:
    """把面板日期收成 ``YYYYMMDD``。"""

    if hasattr(value, "strftime"):
        try:
            return value.strftime("%Y%m%d")
        except (TypeError, ValueError):
            pass
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits[:8]


def _number(value: Any) -> Optional[float]:
    """可比较的浮点。NaN 与 Inf 记为空。"""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _default_table_exists(table_name: str) -> bool:
    """本地是否已有这张表。未知表名视为没有。"""

    from qteasy import QT_DATA_SOURCE

    try:
        info = QT_DATA_SOURCE.get_table_info(table_name, verbose=False, print_info=False, human=False)
    except (TypeError, ValueError, KeyError):
        return False
    if not isinstance(info, dict):
        return False
    return bool(info.get("table_exists", False))


def build_data_statement_skill(
    history_func: Callable[..., Any] | None = None,
    table_exists_func: Callable[[str], bool] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.data.statement``。

    Parameters
    ----------
    history_func : callable, optional
        注入 ``qteasy.get_history_data``。频率固定为 ``q``。
    table_exists_func : callable, optional
        注入缺表检查。缺省读本地数据源。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。
    """

    if history_func is None:
        import qteasy as qt

        history_func = qt.get_history_data
    if table_exists_func is None:
        table_exists_func = _default_table_exists

    metadata = SkillMetadata(
        name="qt.ai.data.statement",
        version="0.1.0",
        summary="Read one reporting period of income, balance, or cashflow via get_history_data.",
        inputs_schema={
            "shares": code_spec(required=True),
            "period": {"type": "string", "required": True},
            "statement": {
                "type": "string",
                "required": True,
                "enum": ["income", "balance", "cashflow"],
                "enum_strict": True,
            },
            "fields": {"type": "string", "required": False},
            "compare": {"type": "string", "required": False},
        },
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly statement"),
        required_capabilities=["local_datasource"],
        qteasy_entrypoints=["qteasy.get_history_data"],
        expected_artifact="One reporting period, or a comparison table with current, previous, difference, and change ratio.",
    )

    def handler(
        shares: Optional[str] = None,
        period: Optional[str] = None,
        statement: Optional[str] = None,
        fields: Any = None,
        compare: Optional[str] = None,
        **kwargs,
    ) -> dict:
        symbol = str(shares or "").strip()
        kind = str(statement or "").strip().lower()
        compare_name = str(compare or "").strip().lower()
        inputs_echo = {
            "shares": symbol,
            "period": period,
            "statement": kind,
            "fields": fields,
            "compare": compare_name or None,
        }
        if not symbol:
            return failed(
                metadata.name,
                "STATEMENT_SHARES_REQUIRED",
                "shares is required to read a statement.",
                inputs_echo,
            )
        if kind not in _STATEMENT_TABLE:
            return failed(
                metadata.name,
                "STATEMENT_KIND_INVALID",
                "statement must be one of income, balance, cashflow.",
                inputs_echo,
            )
        if compare_name and compare_name not in {"qoq", "yoy"}:
            return failed(
                metadata.name,
                "STATEMENT_COMPARE_INVALID",
                "compare must be qoq or yoy.",
                inputs_echo,
            )
        try:
            current = _parse_period(str(period or ""))
        except ValueError as exc:
            return failed(
                metadata.name,
                "STATEMENT_PERIOD_INVALID",
                english_message(exc, "period must be YYYYMMDD."),
                inputs_echo,
            )
        table_name = _STATEMENT_TABLE[kind]
        if not table_exists_func(table_name):
            return failed(
                metadata.name,
                "STATEMENT_TABLE_MISSING",
                f"Local table '{table_name}' is missing. data.statement stopped.",
                inputs_echo,
            )
        chosen = _split_fields(fields, _DEFAULT_FIELDS[kind])
        allowed = _names_on_table(table_name)
        foreign = [name for name in chosen if name not in allowed]
        if foreign:
            return failed(
                metadata.name,
                "STATEMENT_FIELD_UNKNOWN",
                f"Field '{foreign[0]}' is not on the {kind} statement.",
                inputs_echo,
            )
        if compare_name == "qoq":
            previous = _previous_quarter_end(current)
        elif compare_name == "yoy":
            previous = _year_ago(current)
        else:
            previous = current
        try:
            data = history_func(
                htype_names=",".join(chosen),
                shares=symbol,
                start=_stamp(previous),
                end=_stamp(current),
                freq="q",
                asset_type="E",
                as_data_frame=False,
            )
        except Exception as exc:
            return failed(
                metadata.name,
                "STATEMENT_FETCH_FAILED",
                english_message(exc, "Failed to read statement history."),
                inputs_echo,
            )
        if type(data).__name__ != "HistoryPanel" or data.is_empty:
            return failed(
                metadata.name,
                "STATEMENT_FETCH_FAILED",
                f"No local statement rows for {symbol}.",
                inputs_echo,
            )
        current_key = _stamp(current)
        previous_key = _stamp(previous)
        located = _locate(data, symbol, current_key, previous_key if compare_name else None)
        if isinstance(located, str):
            return failed(metadata.name, "STATEMENT_PERIOD_MISSING", located, inputs_echo)
        share_index, current_index, previous_index, panel = located
        if not compare_name:
            kept = _keep_dates(panel, [current_key])
            result = SkillResult(
                ok=True,
                skill_name=metadata.name,
                run_id=new_run_id(),
                inputs_echo=inputs_echo,
                metrics={"n_fields": len(chosen), "n_rows": int(kept.row_count)},
                data_summary={"statement": kind, "period": current_key, "fields": chosen},
                payload={"panel": kept, "preview_rows": tabular_preview_rows(kept)},
            )
            return result.to_dict()
        rows = _comparison_rows(
            panel,
            share_index,
            current_index,
            previous_index,
            chosen,
            symbol,
        )
        result = SkillResult(
            ok=True,
            skill_name=metadata.name,
            run_id=new_run_id(),
            inputs_echo=inputs_echo,
            metrics={"n_fields": len(rows), "compare": compare_name},
            data_summary={
                "statement": kind,
                "period": current_key,
                "previous_period": previous_key,
                "compare": compare_name,
            },
            payload={"comparison": rows, "preview_rows": rows},
        )
        return result.to_dict()

    return metadata, handler


def _locate(panel: Any, share: str, current_key: str, previous_key: Optional[str]) -> Any:
    """定位标的和报告期。失败时返回英文句子。"""

    labels = [str(item) for item in panel.shares]
    requested = [item.strip() for item in share.split(",") if item.strip()]
    if len(requested) != 1:
        if requested[0] not in labels:
            return f"Share '{requested[0]}' is not in the statement panel."
    target = requested[0]
    if target not in labels:
        return f"Share '{target}' is not in the statement panel."
    share_index = labels.index(target)
    dates = list(panel.hdates)
    keys = [_date_key(item) for item in dates]
    if current_key not in keys:
        return f"Report period {current_key} is not in the local statement for {target}."
    current_index = keys.index(current_key)
    previous_index = None
    if previous_key is not None:
        if previous_key not in keys:
            return f"Comparison period {previous_key} is not in the local statement for {target}."
        previous_index = keys.index(previous_key)
    return share_index, current_index, previous_index, panel


def _keep_dates(panel: Any, keys: Sequence[str]) -> Any:
    """只留下这些报告期。"""

    dates = list(panel.hdates)
    chosen = [item for item in dates if _date_key(item) in set(keys)]
    if not chosen:
        return panel
    return panel.subpanel(hdates=chosen)


def _comparison_rows(
    panel: Any,
    share_index: int,
    current_index: int,
    previous_index: int,
    fields: Sequence[str],
    share: str,
) -> list[dict]:
    """本期、对比期、差额和变化比例。上期为 0 时比例为空。"""

    htypes = [str(name) for name in panel.htypes]
    rows = []
    symbol = share.split(",")[0].strip()
    for name in fields:
        if name not in htypes:
            current = None
            previous = None
        else:
            column = htypes.index(name)
            current = _number(panel.values[share_index, current_index, column])
            previous = _number(panel.values[share_index, previous_index, column])
        if current is None or previous is None:
            difference = None
        else:
            difference = current - previous
        if difference is None or previous in (None, 0, 0.0):
            change_ratio = None
        else:
            change_ratio = difference / previous
        rows.append(
            {
                "share": symbol,
                "field": name,
                "current": current,
                "previous": previous,
                "difference": difference,
                "change_ratio": change_ratio,
            }
        )
    return rows
