# coding=utf-8
# ======================================
# File: data_static.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-02
# Desc:
# 只读技能：get_static_data 取股票或基金的截面属性。
# ======================================

"""截面属性取数原子。必须点名代码。"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..contracts import SkillMetadata, SkillResult, SkillSideEffects, new_run_id
from .hp_panel import english_message, failed
from .preview_rows import tabular_preview_rows


def build_data_static_skill(
    get_static_func: Callable[..., Any] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.data.static``。

    Parameters
    ----------
    get_static_func : callable, optional
        注入 ``qteasy.get_static_data``。缺省时在调用时导入。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。
    """

    if get_static_func is None:
        import qteasy as qt

        get_static_func = qt.get_static_data

    metadata = SkillMetadata(
        name="qt.ai.data.static",
        version="0.1.0",
        summary="Read local static attributes for named shares via get_static_data.",
        inputs_schema={
            "names": {"type": "string", "required": True},
            "shares": {"type": "string", "required": True},
            "asset_type": {"type": "string", "required": False},
        },
        outputs_schema={"payload": "dict"},
        side_effects=SkillSideEffects(description="readonly local static"),
        required_capabilities=["local_datasource"],
        qteasy_entrypoints=["qteasy.get_static_data"],
        expected_artifact="A short preview of static attributes for the named shares.",
    )

    def handler(
        names: Optional[str] = None,
        shares: Optional[str] = None,
        asset_type: Optional[str] = None,
        **kwargs,
    ) -> dict:
        type_names = str(names or "").strip()
        symbol = str(shares or "").strip()
        inputs_echo = {"names": type_names, "shares": symbol, "asset_type": asset_type}
        if not type_names:
            return failed(
                metadata.name,
                "STATIC_NAMES_REQUIRED",
                "names is required to read static data.",
                inputs_echo,
            )
        if not symbol:
            return failed(
                metadata.name,
                "STATIC_SHARES_REQUIRED",
                "shares is required. This skill does not export the whole market.",
                inputs_echo,
            )
        try:
            data = get_static_func(names=type_names, shares=symbol, asset_type=asset_type)
        except Exception as exc:
            return failed(
                metadata.name,
                "STATIC_FETCH_FAILED",
                english_message(exc, "Failed to read static data."),
                inputs_echo,
            )
        preview = tabular_preview_rows(data)
        result = SkillResult(
            ok=True,
            skill_name=metadata.name,
            run_id=new_run_id(),
            inputs_echo=inputs_echo,
            metrics={"n_preview": len(preview)},
            data_summary={"names": type_names, "shares": symbol},
            payload={"preview_rows": preview},
        )
        return result.to_dict()

    return metadata, handler
