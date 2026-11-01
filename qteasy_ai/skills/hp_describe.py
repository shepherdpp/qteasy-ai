# coding=utf-8
# ======================================
# File: hp_describe.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-01
# Desc:
# 只读技能：HistoryPanel 的结构视图，不倾倒整块 values。
# ======================================

"""面板结构摘要。head / tail 默认 5 行，硬上限 20。"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from ..contracts import SkillMetadata, SkillResult, SkillSideEffects, new_run_id
from .hp_panel import failed, panel_from_upstream
from .preview_rows import tabular_preview_rows

_VIEWS = ("info", "head", "tail", "shape", "htypes", "shares")
_HEAD_DEFAULT = 5
_HEAD_CAP = 20


def _row_limit(n: Optional[int]) -> int:
    """head / tail 行数：默认 5，超过 20 的请求截到 20。"""

    if n is None:
        return _HEAD_DEFAULT
    try:
        value = int(n)
    except (TypeError, ValueError):
        return _HEAD_DEFAULT
    if value < 1:
        return 1
    return min(value, _HEAD_CAP)


def _shape_row(panel: Any) -> Dict[str, int]:
    """行数、标的数、列数。"""

    return {
        "n_rows": int(panel.row_count),
        "n_shares": len(list(panel.shares)),
        "n_htypes": len(list(panel.htypes)),
    }


def build_hp_describe_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.describe``。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。
    """

    metadata = SkillMetadata(
        name="qt.ai.hp.describe",
        version="0.1.0",
        summary="Structural view of an upstream HistoryPanel.",
        inputs_schema={
            "view": {"type": "string", "required": False},
            "n": {"type": "integer", "required": False},
            "upstream_payload": {"type": "object", "required": False},
        },
        outputs_schema={"metrics": "dict", "payload": "dict"},
        side_effects=SkillSideEffects(description="readonly panel view"),
        required_capabilities=[],
        qteasy_entrypoints=["qteasy.HistoryPanel.head", "qteasy.HistoryPanel.tail"],
        expected_artifact="A short structural table. The full values array is not included.",
    )

    def handler(
        view: str = "shape",
        n: Optional[int] = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> dict:
        chosen = str(view or "shape").strip().lower()
        inputs_echo = {"view": chosen, "n": n}
        panel = panel_from_upstream(upstream_payload)
        if panel is None:
            return failed(
                metadata.name,
                "HP_PANEL_MISSING",
                "A HistoryPanel from the previous step is required.",
                inputs_echo,
            )
        if chosen not in _VIEWS:
            return failed(
                metadata.name,
                "HP_DESCRIBE_FAILED",
                "view must be one of info, head, tail, shape, htypes, shares.",
                inputs_echo,
            )
        shape = _shape_row(panel)
        htypes = [str(name) for name in panel.htypes]
        shares = [str(name) for name in panel.shares]
        dates = list(panel.hdates)
        if chosen == "shape":
            preview = [dict(shape)]
            summary = dict(shape)
            metrics = dict(shape)
        elif chosen == "htypes":
            preview = [{"htype": name} for name in htypes]
            summary = {"n_htypes": shape["n_htypes"]}
            metrics = {"n_htypes": shape["n_htypes"]}
        elif chosen == "shares":
            preview = [{"share": name} for name in shares]
            summary = {"n_shares": shape["n_shares"]}
            metrics = {"n_shares": shape["n_shares"]}
        elif chosen == "info":
            summary = {
                **shape,
                "htypes": htypes,
                "shares": shares,
                "index_start": str(dates[0]) if dates else "",
                "index_end": str(dates[-1]) if dates else "",
            }
            preview = [dict(shape)]
            metrics = dict(shape)
        else:
            limit = _row_limit(n)
            frame = panel.head(limit) if chosen == "head" else panel.tail(limit)
            preview = tabular_preview_rows(frame, cap=limit)
            summary = {"view": chosen, "n": limit, "n_rows": shape["n_rows"]}
            metrics = {"n": limit, "n_rows": shape["n_rows"]}
        result = SkillResult(
            ok=True,
            skill_name=metadata.name,
            run_id=new_run_id(),
            inputs_echo=inputs_echo,
            metrics=metrics,
            data_summary=summary,
            payload={"preview_rows": preview},
        )
        return result.to_dict()

    return metadata, handler
