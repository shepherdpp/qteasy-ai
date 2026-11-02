# coding=utf-8
# ======================================
# File: hp_transform.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-02
# Desc:
# 面板变换与比较原子：收益、位移、排名、滚动、
# 汇总、相关、比较、掩码与列表达式。
# ======================================

"""HistoryPanel 变换与比较技能。不执行任意 Python。"""

from __future__ import annotations

import operator
from typing import Any, Callable, Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from ..contracts import SkillMetadata, SkillResult, SkillSideEffects, new_run_id
from .hp_panel import english_message, failed, panel_from_upstream
from .preview_rows import tabular_preview_rows

_PANEL_MISSING = "A HistoryPanel from the previous step is required."
_ROLLING_STATS = ("mean", "std", "min", "max", "sum")
_AGG_STATS = ("mean", "sum", "min", "max", "std", "median", "quantile")
_COMPARE_OPS = {
    "gt": operator.gt,
    "ge": operator.ge,
    "lt": operator.lt,
    "le": operator.le,
    "eq": operator.eq,
    "ne": operator.ne,
}
_MASK_PREVIEW_CAP = 20


def _meta(
    name: str,
    summary: str,
    inputs_schema: Dict[str, Any],
    entrypoint: str,
    artifact: str,
) -> SkillMetadata:
    """组装一条只读变换技能的元数据。"""

    return SkillMetadata(
        name=name,
        version="0.1.0",
        summary=summary,
        inputs_schema=inputs_schema,
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly panel transform"),
        required_capabilities=[],
        qteasy_entrypoints=[entrypoint],
        expected_artifact=artifact,
    )


def _upstream_list(upstream_payload: Any, upstream_payloads: Any) -> List[Dict[str, Any]]:
    """执行器会同时给出第一块和全部。有列表时以列表为准。"""

    if isinstance(upstream_payloads, list) and upstream_payloads:
        return [item for item in upstream_payloads if isinstance(item, dict)]
    if isinstance(upstream_payload, dict):
        return [upstream_payload]
    return []


def _find_panel(payloads: Sequence[Dict[str, Any]]) -> Any:
    """取第一块上游面板。"""

    for item in payloads:
        panel = panel_from_upstream(item)
        if panel is not None:
            return panel
    return None


def _find_masks(payloads: Sequence[Dict[str, Any]]) -> List[Any]:
    """按依赖顺序收集 mask。"""

    found = []
    for item in payloads:
        if "mask" in item:
            found.append(item.get("mask"))
    return found


def _require_panel(
    metadata: SkillMetadata,
    inputs_echo: Dict[str, Any],
    upstream_payload: Any,
    upstream_payloads: Any,
) -> Any:
    """没有面板时返回失败字典。"""

    panel = _find_panel(_upstream_list(upstream_payload, upstream_payloads))
    if panel is None:
        return failed(metadata.name, "HP_PANEL_MISSING", _PANEL_MISSING, inputs_echo)
    return panel


def _mask_preview(mask: Any) -> List[Dict[str, Any]]:
    """掩码只预览前若干格，不把整块数组塞进预览。"""

    flat = np.asarray(mask, dtype=bool).reshape(-1)
    limit = min(int(flat.size), _MASK_PREVIEW_CAP)
    return [{"index": index, "value": bool(flat[index])} for index in range(limit)]


def _panel_result(metadata: SkillMetadata, inputs_echo: Dict[str, Any], panel: Any) -> dict:
    """成功的面板结果。完整面板留在 payload。"""

    result = SkillResult(
        ok=True,
        skill_name=metadata.name,
        run_id=new_run_id(),
        inputs_echo=inputs_echo,
        metrics={
            "n_rows": int(panel.row_count),
            "n_shares": len(list(panel.shares)),
            "n_htypes": len(list(panel.htypes)),
        },
        data_summary={
            "htypes": [str(name) for name in panel.htypes],
            "shares": [str(name) for name in panel.shares],
        },
        payload={"panel": panel, "preview_rows": tabular_preview_rows(panel)},
    )
    return result.to_dict()


def _frame_result(metadata: SkillMetadata, inputs_echo: Dict[str, Any], frame: pd.DataFrame) -> dict:
    """成功的表结果。DataFrame 留在内存，预览另给。"""

    result = SkillResult(
        ok=True,
        skill_name=metadata.name,
        run_id=new_run_id(),
        inputs_echo=inputs_echo,
        metrics={"n_rows": int(len(frame.index)), "n_columns": int(len(frame.columns))},
        data_summary={"columns": [str(name) for name in frame.columns]},
        payload={"frame": frame, "preview_rows": tabular_preview_rows(frame)},
    )
    return result.to_dict()


def _mask_result(
    metadata: SkillMetadata,
    inputs_echo: Dict[str, Any],
    mask: Any,
    panel: Any = None,
) -> dict:
    """成功的布尔掩码。可选带回原面板，供下一步广播。"""

    array = np.array(mask, dtype=bool, copy=True)
    payload: Dict[str, Any] = {"mask": array, "preview_rows": _mask_preview(array)}
    if panel is not None:
        payload["panel"] = panel
    result = SkillResult(
        ok=True,
        skill_name=metadata.name,
        run_id=new_run_id(),
        inputs_echo=inputs_echo,
        metrics={"n_true": int(array.sum()), "shape": [int(item) for item in array.shape]},
        data_summary={"dtype": "bool"},
        payload=payload,
    )
    return result.to_dict()


def _library_call(
    metadata: SkillMetadata,
    inputs_echo: Dict[str, Any],
    action: Callable[[], Any],
    code: str,
    fallback: str,
) -> Any:
    """调用库。失败时把英文句子送出，不送回溯。"""

    try:
        return action()
    except Exception as exc:
        return failed(metadata.name, code, english_message(exc, fallback), inputs_echo)


def _finish_panel(metadata: SkillMetadata, inputs_echo: Dict[str, Any], produced: Any, fallback: str) -> dict:
    """库返回面板则成功，否则英文失败。"""

    if isinstance(produced, dict):
        return produced
    if type(produced).__name__ != "HistoryPanel":
        return failed(metadata.name, "HP_TRANSFORM_FAILED", fallback, inputs_echo)
    return _panel_result(metadata, inputs_echo, produced)


def _finish_frame(metadata: SkillMetadata, inputs_echo: Dict[str, Any], produced: Any, fallback: str) -> dict:
    """库返回表则成功，否则英文失败。"""

    if isinstance(produced, dict):
        return produced
    if not isinstance(produced, pd.DataFrame):
        return failed(metadata.name, "HP_TRANSFORM_FAILED", fallback, inputs_echo)
    return _frame_result(metadata, inputs_echo, produced)


def _upstream_schema() -> Dict[str, Any]:
    """上游面板与掩码都由执行器注入。"""

    return {
        "upstream_payload": {"type": "object", "required": False},
        "upstream_payloads": {"type": "array", "required": False},
    }


def build_hp_returns_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.returns``。默认 ``as_panel=False``，与库一致。"""

    schema = {
        "price_htype": {"type": "string", "required": False},
        "method": {"type": "string", "required": False},
        "periods": {"type": "integer", "required": False},
        "as_panel": {"type": "boolean", "required": False},
        "dropna": {"type": "boolean", "required": False},
    }
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.returns",
        "Simple or log returns of one price column.",
        schema,
        "qteasy.HistoryPanel.returns",
        "A return table, or a one-column HistoryPanel when as_panel is true.",
    )

    def handler(
        price_htype: str = "close",
        method: str = "simple",
        periods: int = 1,
        as_panel: bool = False,
        dropna: bool = False,
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {
            "price_htype": price_htype,
            "method": method,
            "periods": periods,
            "as_panel": as_panel,
            "dropna": dropna,
        }
        panel = _require_panel(metadata, inputs_echo, upstream_payload, upstream_payloads)
        if isinstance(panel, dict):
            return panel
        produced = _library_call(
            metadata,
            inputs_echo,
            lambda: panel.returns(
                price_htype=price_htype,
                method=method,
                periods=periods,
                as_panel=bool(as_panel),
                dropna=bool(dropna),
            ),
            "HP_TRANSFORM_FAILED",
            "Failed to compute returns.",
        )
        if isinstance(produced, dict):
            return produced
        if type(produced).__name__ == "HistoryPanel":
            return _panel_result(metadata, inputs_echo, produced)
        if isinstance(produced, pd.DataFrame):
            return _frame_result(metadata, inputs_echo, produced)
        return failed(
            metadata.name,
            "HP_TRANSFORM_FAILED",
            "returns did not return a table or a HistoryPanel.",
            inputs_echo,
        )

    return metadata, handler


def build_hp_shift_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.shift``。正 periods 看历史。"""

    schema = {
        "periods": {"type": "integer", "required": False},
        "htypes": {"type": "string", "required": False},
        "fill_value": {"type": "number", "required": False},
    }
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.shift",
        "Shift selected columns along the time axis.",
        schema,
        "qteasy.HistoryPanel.shift",
        "A HistoryPanel of the same shape, with values moved along time.",
    )

    def handler(
        periods: int = 1,
        htypes: Optional[str] = None,
        fill_value: float = np.nan,
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {"periods": periods, "htypes": htypes, "fill_value": fill_value}
        panel = _require_panel(metadata, inputs_echo, upstream_payload, upstream_payloads)
        if isinstance(panel, dict):
            return panel
        produced = _library_call(
            metadata,
            inputs_echo,
            lambda: panel.shift(periods, htypes=htypes, fill_value=fill_value),
            "HP_TRANSFORM_FAILED",
            "Failed to shift the HistoryPanel.",
        )
        return _finish_panel(metadata, inputs_echo, produced, "shift did not return a HistoryPanel.")

    return metadata, handler


def build_hp_diff_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.diff``。"""

    schema = {
        "periods": {"type": "integer", "required": False},
        "htypes": {"type": "string", "required": False},
    }
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.diff",
        "First difference of selected columns along time.",
        schema,
        "qteasy.HistoryPanel.diff",
        "A HistoryPanel of first differences along time.",
    )

    def handler(
        periods: int = 1,
        htypes: Optional[str] = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {"periods": periods, "htypes": htypes}
        panel = _require_panel(metadata, inputs_echo, upstream_payload, upstream_payloads)
        if isinstance(panel, dict):
            return panel
        produced = _library_call(
            metadata,
            inputs_echo,
            lambda: panel.diff(periods, htypes=htypes),
            "HP_TRANSFORM_FAILED",
            "Failed to difference the HistoryPanel.",
        )
        return _finish_panel(metadata, inputs_echo, produced, "diff did not return a HistoryPanel.")

    return metadata, handler


def build_hp_pct_change_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.pct_change``。不解析价格列名。"""

    schema = {
        "periods": {"type": "integer", "required": False},
        "htypes": {"type": "string", "required": False},
    }
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.pct_change",
        "Percent change of selected columns along time.",
        schema,
        "qteasy.HistoryPanel.pct_change",
        "A HistoryPanel of percent changes along time.",
    )

    def handler(
        periods: int = 1,
        htypes: Optional[str] = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {"periods": periods, "htypes": htypes}
        panel = _require_panel(metadata, inputs_echo, upstream_payload, upstream_payloads)
        if isinstance(panel, dict):
            return panel
        produced = _library_call(
            metadata,
            inputs_echo,
            lambda: panel.pct_change(periods, htypes=htypes),
            "HP_TRANSFORM_FAILED",
            "Failed to compute percent change.",
        )
        return _finish_panel(metadata, inputs_echo, produced, "pct_change did not return a HistoryPanel.")

    return metadata, handler


def build_hp_rank_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.rank``。``by`` 没有库默认值。"""

    schema = {
        "by": {"type": "string", "required": True},
        "axis": {"type": "string", "required": False},
        "method": {"type": "string", "required": False},
        "new_htype": {"type": "string", "required": False},
    }
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.rank",
        "Cross-sectional rank of one column.",
        schema,
        "qteasy.HistoryPanel.rank",
        "The same HistoryPanel plus one rank column.",
    )

    def handler(
        by: Optional[str] = None,
        axis: str = "share",
        method: str = "average",
        new_htype: Optional[str] = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {"by": by, "axis": axis, "method": method, "new_htype": new_htype}
        if not str(by or "").strip():
            return failed(metadata.name, "HP_TRANSFORM_FAILED", "by is required.", inputs_echo)
        panel = _require_panel(metadata, inputs_echo, upstream_payload, upstream_payloads)
        if isinstance(panel, dict):
            return panel
        call = {"by": str(by), "axis": axis, "method": method}
        if new_htype:
            call["new_htype"] = new_htype
        produced = _library_call(
            metadata,
            inputs_echo,
            lambda: panel.rank(**call),
            "HP_TRANSFORM_FAILED",
            "Failed to rank the HistoryPanel.",
        )
        return _finish_panel(metadata, inputs_echo, produced, "rank did not return a HistoryPanel.")

    return metadata, handler


def build_hp_zscore_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.zscore``。截面默认不带窗口。"""

    schema = {
        "by": {"type": "string", "required": True},
        "method": {"type": "string", "required": False},
        "window": {"type": "integer", "required": False},
        "new_htype": {"type": "string", "required": False},
    }
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.zscore",
        "Cross-sectional or rolling z-score of one column.",
        schema,
        "qteasy.HistoryPanel.zscore",
        "The same HistoryPanel plus one z-score column.",
    )

    def handler(
        by: Optional[str] = None,
        method: str = "cs",
        window: Optional[int] = None,
        new_htype: Optional[str] = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {"by": by, "method": method, "window": window, "new_htype": new_htype}
        if not str(by or "").strip():
            return failed(metadata.name, "HP_TRANSFORM_FAILED", "by is required.", inputs_echo)
        panel = _require_panel(metadata, inputs_echo, upstream_payload, upstream_payloads)
        if isinstance(panel, dict):
            return panel
        call: Dict[str, Any] = {"by": str(by), "method": method}
        if window is not None:
            call["window"] = window
        if new_htype:
            call["new_htype"] = new_htype
        produced = _library_call(
            metadata,
            inputs_echo,
            lambda: panel.zscore(**call),
            "HP_TRANSFORM_FAILED",
            "Failed to compute z-score.",
        )
        return _finish_panel(metadata, inputs_echo, produced, "zscore did not return a HistoryPanel.")

    return metadata, handler


def build_hp_rolling_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.rolling``。``stat`` 只接受滚动对象上的五个方法。"""

    schema = {
        "window": {"type": "integer", "required": True},
        "stat": {"type": "string", "required": True},
        "min_periods": {"type": "integer", "required": False},
        "center": {"type": "boolean", "required": False},
        "by": {"type": "string", "required": False},
    }
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.rolling",
        "Rolling mean, std, min, max, or sum along time.",
        schema,
        "qteasy.HistoryPanel.rolling",
        "A HistoryPanel of one rolling statistic over a fixed window.",
    )

    def handler(
        window: Optional[int] = None,
        stat: Optional[str] = None,
        min_periods: Optional[int] = None,
        center: bool = False,
        by: str = "share",
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {
            "window": window,
            "stat": stat,
            "min_periods": min_periods,
            "center": center,
            "by": by,
        }
        stat_name = str(stat or "").strip()
        if window is None:
            return failed(metadata.name, "HP_TRANSFORM_FAILED", "window is required.", inputs_echo)
        if stat_name not in _ROLLING_STATS:
            allowed = ", ".join(_ROLLING_STATS)
            return failed(
                metadata.name,
                "HP_TRANSFORM_FAILED",
                f"stat must be one of {allowed}, got {stat_name!r}.",
                inputs_echo,
            )
        panel = _require_panel(metadata, inputs_echo, upstream_payload, upstream_payloads)
        if isinstance(panel, dict):
            return panel

        def action() -> Any:
            call: Dict[str, Any] = {"window": window, "center": bool(center), "by": by}
            if min_periods is not None:
                call["min_periods"] = min_periods
            roller = panel.rolling(**call)
            return getattr(roller, stat_name)()

        produced = _library_call(
            metadata,
            inputs_echo,
            action,
            "HP_TRANSFORM_FAILED",
            "Failed to compute the rolling statistic.",
        )
        return _finish_panel(metadata, inputs_echo, produced, "rolling did not return a HistoryPanel.")

    return metadata, handler


def build_hp_agg_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.agg``。整段汇总，不是滚动窗口。"""

    schema = {
        "stat": {"type": "string", "required": True},
        "by": {"type": "string", "required": False},
        "skipna": {"type": "boolean", "required": False},
        "q": {"type": "number", "required": False},
    }
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.agg",
        "Aggregate each share or each column over the whole panel.",
        schema,
        "qteasy.HistoryPanel.mean",
        "A summary table with one value per share or per column.",
    )

    def handler(
        stat: Optional[str] = None,
        by: str = "share",
        skipna: bool = True,
        q: float = 0.5,
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {"stat": stat, "by": by, "skipna": skipna, "q": q}
        stat_name = str(stat or "").strip()
        if stat_name not in _AGG_STATS:
            allowed = ", ".join(_AGG_STATS)
            return failed(
                metadata.name,
                "HP_TRANSFORM_FAILED",
                f"stat must be one of {allowed}, got {stat_name!r}.",
                inputs_echo,
            )
        panel = _require_panel(metadata, inputs_echo, upstream_payload, upstream_payloads)
        if isinstance(panel, dict):
            return panel

        def action() -> pd.DataFrame:
            if stat_name == "quantile":
                return panel.quantile(q=q, by=by, skipna=bool(skipna))
            return getattr(panel, stat_name)(by=by, skipna=bool(skipna))

        produced = _library_call(
            metadata,
            inputs_echo,
            action,
            "HP_TRANSFORM_FAILED",
            "Failed to aggregate the HistoryPanel.",
        )
        return _finish_frame(metadata, inputs_echo, produced, "agg did not return a table.")

    return metadata, handler


def build_hp_corr_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.corr``。某一列上标的之间的相关矩阵。"""

    schema = {
        "htype": {"type": "string", "required": True},
        "method": {"type": "string", "required": False},
        "min_periods": {"type": "integer", "required": False},
    }
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.corr",
        "Correlation matrix of shares on one column.",
        schema,
        "qteasy.HistoryPanel.corr",
        "A share-by-share correlation matrix for one column.",
    )

    def handler(
        htype: Optional[str] = None,
        method: str = "pearson",
        min_periods: int = 1,
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {"htype": htype, "method": method, "min_periods": min_periods}
        if not str(htype or "").strip():
            return failed(metadata.name, "HP_TRANSFORM_FAILED", "htype is required.", inputs_echo)
        panel = _require_panel(metadata, inputs_echo, upstream_payload, upstream_payloads)
        if isinstance(panel, dict):
            return panel
        produced = _library_call(
            metadata,
            inputs_echo,
            lambda: panel.corr(str(htype), method=method, min_periods=min_periods),
            "HP_TRANSFORM_FAILED",
            "Failed to compute the correlation matrix.",
        )
        return _finish_frame(metadata, inputs_echo, produced, "corr did not return a table.")

    return metadata, handler


def build_hp_compare_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.compare``。列对标量，或列对同一面板的另一列。"""

    schema = {
        "htype": {"type": "string", "required": True},
        "op": {"type": "string", "required": True},
        "value": {"type": "number", "required": False},
        "other_htype": {"type": "string", "required": False},
    }
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.compare",
        "Compare one column with a number or with another column.",
        schema,
        "qteasy.HistoryPanel.__gt__",
        "A boolean mask from one column comparison, plus the original panel.",
    )

    def handler(
        htype: Optional[str] = None,
        op: Optional[str] = None,
        value: Any = None,
        other_htype: Optional[str] = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {"htype": htype, "op": op, "value": value, "other_htype": other_htype}
        op_name = str(op or "").strip()
        if not str(htype or "").strip():
            return failed(metadata.name, "HP_COMPARE_FAILED", "htype is required.", inputs_echo)
        if op_name not in _COMPARE_OPS:
            allowed = ", ".join(_COMPARE_OPS)
            return failed(
                metadata.name,
                "HP_COMPARE_FAILED",
                f"op must be one of {allowed}, got {op_name!r}.",
                inputs_echo,
            )
        has_value = value is not None
        has_other = bool(str(other_htype or "").strip())
        if has_value == has_other:
            return failed(
                metadata.name,
                "HP_COMPARE_FAILED",
                "Provide either a numeric value or another column, not both and not neither.",
                inputs_echo,
            )
        panel = _require_panel(metadata, inputs_echo, upstream_payload, upstream_payloads)
        if isinstance(panel, dict):
            return panel

        def action() -> Any:
            left = panel.subpanel(htypes=str(htype))
            compare = _COMPARE_OPS[op_name]
            if has_value:
                return compare(left, value)
            right = panel.subpanel(htypes=str(other_htype).strip())
            return compare(left, right)

        produced = _library_call(
            metadata,
            inputs_echo,
            action,
            "HP_TRANSFORM_FAILED",
            "Failed to compare the HistoryPanel.",
        )
        if isinstance(produced, dict):
            return produced
        return _mask_result(metadata, inputs_echo, produced, panel)

    return metadata, handler


def build_hp_combine_mask_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.combine_mask``。``and`` / ``or`` / ``not``，形状必须相同。"""

    schema = {"op": {"type": "string", "required": True}}
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.combine_mask",
        "Combine boolean masks with and, or, or not.",
        schema,
        "numpy.logical_and",
        "One boolean mask combined from earlier masks.",
    )

    def handler(
        op: Optional[str] = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {"op": op}
        op_name = str(op or "").strip().lower()
        if op_name not in ("and", "or", "not"):
            return failed(
                metadata.name,
                "HP_MASK_REQUIRED",
                "op must be one of and, or, not.",
                inputs_echo,
            )
        masks = _find_masks(_upstream_list(upstream_payload, upstream_payloads))
        if op_name == "not" and len(masks) != 1:
            return failed(
                metadata.name,
                "HP_MASK_REQUIRED",
                "not takes exactly one boolean mask.",
                inputs_echo,
            )
        if op_name != "not" and len(masks) < 2:
            return failed(
                metadata.name,
                "HP_MASK_REQUIRED",
                "and and or take at least two boolean masks.",
                inputs_echo,
            )
        arrays = []
        for mask in masks:
            if isinstance(mask, str) or callable(mask):
                return failed(
                    metadata.name,
                    "HP_MASK_REQUIRED",
                    "Each mask must be a boolean array.",
                    inputs_echo,
                )
            arrays.append(np.asarray(mask, dtype=bool))
        shape = arrays[0].shape
        if any(item.shape != shape for item in arrays):
            return failed(
                metadata.name,
                "HP_MASK_REQUIRED",
                "Boolean masks must share one shape.",
                inputs_echo,
            )
        if op_name == "not":
            combined = np.logical_not(arrays[0])
        elif op_name == "and":
            combined = np.logical_and.reduce(arrays)
        else:
            combined = np.logical_or.reduce(arrays)
        return _mask_result(metadata, inputs_echo, combined)

    return metadata, handler


def build_hp_where_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.where``。只接受上游布尔掩码，不接受字符串或函数。"""

    metadata = _meta(
        "qt.ai.hp.where",
        "Broadcast a boolean mask onto a HistoryPanel.",
        _upstream_schema(),
        "qteasy.HistoryPanel.where",
        "A boolean mask broadcast to the panel shape. Values are not filtered.",
    )

    def handler(
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo: Dict[str, Any] = {}
        payloads = _upstream_list(upstream_payload, upstream_payloads)
        masks = _find_masks(payloads)
        mask = masks[0] if masks else None
        if isinstance(mask, str) or callable(mask):
            return failed(
                metadata.name,
                "HP_WHERE_REJECTED",
                "hp.where accepts only a boolean mask from a previous step, not a string or a function.",
                inputs_echo,
            )
        panel = _find_panel(payloads)
        if panel is None:
            return failed(metadata.name, "HP_PANEL_MISSING", _PANEL_MISSING, inputs_echo)
        if mask is None:
            return failed(
                metadata.name,
                "HP_MASK_REQUIRED",
                "A boolean mask from a previous step is required.",
                inputs_echo,
            )
        produced = _library_call(
            metadata,
            inputs_echo,
            lambda: panel.where(mask),
            "HP_TRANSFORM_FAILED",
            "Failed to broadcast the boolean mask.",
        )
        if isinstance(produced, dict):
            return produced
        return _mask_result(metadata, inputs_echo, produced, panel)

    return metadata, handler


def build_hp_expr_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.expr``。只用库自己的列表达式。"""

    schema = {
        "new_htype": {"type": "string", "required": True},
        "expression": {"type": "string", "required": True},
        "inplace": {"type": "boolean", "required": False},
    }
    schema.update(_upstream_schema())
    metadata = _meta(
        "qt.ai.hp.expr",
        "Add one column from a column-arithmetic expression.",
        schema,
        "qteasy.HistoryPanel.expr",
        "The same HistoryPanel plus one column computed from existing columns.",
    )

    def handler(
        new_htype: Optional[str] = None,
        expression: Optional[str] = None,
        inplace: bool = False,
        upstream_payload: Optional[Dict[str, Any]] = None,
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        inputs_echo = {"new_htype": new_htype, "expression": expression, "inplace": inplace}
        if not str(new_htype or "").strip() or not isinstance(expression, str) or not expression.strip():
            return failed(
                metadata.name,
                "HP_EXPR_FAILED",
                "new_htype and expression are required.",
                inputs_echo,
            )
        panel = _require_panel(metadata, inputs_echo, upstream_payload, upstream_payloads)
        if isinstance(panel, dict):
            return panel
        produced = _library_call(
            metadata,
            inputs_echo,
            lambda: panel.expr(new_htype, expression, inplace=bool(inplace)),
            "HP_EXPR_FAILED",
            "Failed to evaluate the column expression.",
        )
        if isinstance(produced, dict):
            return produced
        if type(produced).__name__ != "HistoryPanel":
            return failed(
                metadata.name,
                "HP_EXPR_FAILED",
                "expr did not return a HistoryPanel.",
                inputs_echo,
            )
        return _panel_result(metadata, inputs_echo, produced)

    return metadata, handler
