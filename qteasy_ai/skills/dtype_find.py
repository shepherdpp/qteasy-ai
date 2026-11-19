# coding=utf-8
# ======================================
# File: dtype_find.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-02
# Desc:
# 只读技能：find_history_data 按名称匹配数据类型。
# ======================================

"""数据类型查找。执行时固定返回 DataFrame，避免打印到终端。"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..contracts import SkillMetadata, SkillResult, SkillSideEffects, new_run_id
from .hp_panel import english_message, failed
from .preview_rows import PREVIEW_ROW_CAP, tabular_preview_rows


def build_dtype_find_skill(
    find_func: Callable[..., Any] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.dtype.find``。

    Parameters
    ----------
    find_func : callable, optional
        注入 ``qteasy.find_history_data``。缺省时在调用时导入。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。内部固定 ``as_data_frame=True``。
    """

    if find_func is None:
        import qteasy as qt

        find_func = qt.find_history_data

    metadata = SkillMetadata(
        name="qt.ai.dtype.find",
        version="0.1.0",
        summary="Match history data types by name or description.",
        inputs_schema={
            "s": {"type": "string", "required": True},
            "match_description": {"type": "boolean", "required": False},
            "fuzzy": {"type": "boolean", "required": False},
            "freq": {"type": "string", "required": False},
            "asset_type": {"type": "string", "required": False},
            "match_threshold": {"type": "number", "required": False},
            "table": {"type": "string", "required": False},
        },
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly dtype lookup"),
        required_capabilities=["local_datasource"],
        qteasy_entrypoints=["qteasy.find_history_data"],
        expected_artifact="A truncated table of matching data types.",
    )

    def handler(
        s: Optional[str] = None,
        match_description: bool = False,
        fuzzy: bool = False,
        freq: Optional[str] = None,
        asset_type: Optional[str] = None,
        match_threshold: float = 0.85,
        table: Optional[str] = None,
        **kwargs,
    ) -> dict:
        query = str(s or "").strip()
        inputs_echo = {
            "s": query,
            "match_description": match_description,
            "fuzzy": fuzzy,
            "freq": freq,
            "asset_type": asset_type,
            "match_threshold": match_threshold,
            "table": table,
        }
        if not query:
            return failed(
                metadata.name,
                "DTYPE_QUERY_REQUIRED",
                "s is required to find history data types.",
                inputs_echo,
            )
        try:
            data = find_func(
                query,
                match_description=bool(match_description),
                fuzzy=bool(fuzzy),
                freq=freq,
                asset_type=asset_type,
                match_threshold=match_threshold,
                table=table,
                as_data_frame=True,
            )
        except Exception as exc:
            return failed(
                metadata.name,
                "DTYPE_FIND_FAILED",
                english_message(exc, "Failed to find history data types."),
                inputs_echo,
            )
        preview = tabular_preview_rows(data, cap=PREVIEW_ROW_CAP)
        result = SkillResult(
            ok=True,
            skill_name=metadata.name,
            run_id=new_run_id(),
            inputs_echo=inputs_echo,
            metrics={"n_preview": len(preview)},
            data_summary={"query": query},
            payload={"preview_rows": preview},
        )
        return result.to_dict()

    return metadata, handler
