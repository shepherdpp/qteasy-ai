# coding=utf-8
# ======================================
# File: data_reference.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-02
# Desc:
# 只读技能：get_reference_data 取宏观与基准序列。
# ======================================

"""参考序列取数原子。结果不进 HistoryPanel。"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..contracts import SkillMetadata, SkillResult, SkillSideEffects, new_run_id
from .hp_panel import english_message, failed
from .preview_rows import tabular_preview_rows


def build_data_reference_skill(
    get_reference_func: Callable[..., Any] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.data.reference``。

    Parameters
    ----------
    get_reference_func : callable, optional
        注入 ``qteasy.get_reference_data``。缺省时在调用时导入。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。
    """

    if get_reference_func is None:
        import qteasy as qt

        get_reference_func = qt.get_reference_data

    metadata = SkillMetadata(
        name="qt.ai.data.reference",
        version="0.1.0",
        summary="Read local reference series via get_reference_data.",
        inputs_schema={
            "names": {"type": "string", "required": True},
            "start": {"type": "string", "required": False},
            "end": {"type": "string", "required": False},
            "freq": {"type": "string", "required": False, "enum": ["d", "w", "m"], "enum_strict": False},
            "rows": {"type": "integer", "required": False},
            "asset_type": {"type": "string", "required": False, "enum": ["E", "FD"], "enum_strict": False},
        },
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly local reference"),
        required_capabilities=["local_datasource"],
        qteasy_entrypoints=["qteasy.get_reference_data"],
        expected_artifact="A short preview of reference series. They are not a HistoryPanel.",
    )

    def handler(
        names: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        freq: Optional[str] = None,
        rows: Optional[int] = None,
        asset_type: Optional[str] = None,
        **kwargs,
    ) -> dict:
        type_names = str(names or "").strip()
        inputs_echo = {
            "names": type_names,
            "start": start,
            "end": end,
            "freq": freq,
            "rows": rows,
            "asset_type": asset_type,
        }
        if not type_names:
            return failed(
                metadata.name,
                "REFERENCE_NAMES_REQUIRED",
                "names is required to read reference data.",
                inputs_echo,
            )
        try:
            data = get_reference_func(
                names=type_names,
                start=start,
                end=end,
                freq=freq,
                rows=rows,
                asset_type=asset_type,
            )
        except Exception as exc:
            return failed(
                metadata.name,
                "REFERENCE_FETCH_FAILED",
                english_message(exc, "Failed to read reference data."),
                inputs_echo,
            )
        preview = tabular_preview_rows(data)
        result = SkillResult(
            ok=True,
            skill_name=metadata.name,
            run_id=new_run_id(),
            inputs_echo=inputs_echo,
            metrics={"n_preview": len(preview)},
            data_summary={"names": type_names},
            payload={"preview_rows": preview},
        )
        return result.to_dict()

    return metadata, handler
