# coding=utf-8
# ======================================
# File: hp_plot.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-01
# Desc:
# 写文件技能：HistoryPanel.plot 的一页静态 PNG。
# ======================================

"""绘图原子。一次调用一张 Agg PNG，并给出 page_count。"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Callable, Dict, Optional

import numpy as np

from ..contracts import SkillMetadata, SkillResult, SkillSideEffects, new_run_id
from .hp_panel import english_message, failed, panel_from_upstream


def _default_output_path(output_path: Optional[str]) -> str:
    """未指定路径时写到本机 artifacts 目录。"""

    if output_path:
        return output_path
    folder = os.path.join(os.getcwd(), ".qteasy", "ai", "artifacts")
    os.makedirs(folder, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(folder, f"kline_{timestamp}.png")


def _page_count(panel: Any, shares: Any, max_shares_per_figure: int) -> int:
    """与 ``HistoryPanel.plot`` 相同的页数。"""

    names = list(panel.shares)
    if shares in (None, ""):
        chosen = names
    elif isinstance(shares, str):
        chosen = [shares] if shares in names else list(names)
    else:
        chosen = [item for item in list(shares) if item in names] or list(names)
    total = len(chosen)
    if total <= 0:
        return 1
    return int(np.ceil(total / float(max_shares_per_figure)))


def build_hp_plot_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.hp.plot``。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。执行时固定 ``interactive=False``。
    """

    metadata = SkillMetadata(
        name="qt.ai.hp.plot",
        version="0.1.0",
        summary="Save one static page of HistoryPanel.plot as a PNG.",
        inputs_schema={
            "shares": {"type": "string", "required": False},
            "layout": {"type": "string", "required": False},
            "highlight": {"type": "string", "required": False},
            "max_shares_per_figure": {"type": "integer", "required": False},
            "page": {"type": "integer", "required": False},
            "interactive": {"type": "boolean", "required": False},
            "output_path": {"type": "string", "required": False},
            "upstream_payload": {"type": "object", "required": False},
        },
        outputs_schema={"artifacts": "list", "metrics": "dict"},
        side_effects=SkillSideEffects(filesystem_write=True, description="write one PNG"),
        required_capabilities=["matplotlib"],
        qteasy_entrypoints=["qteasy.HistoryPanel.plot"],
        expected_artifact="One chart image in Artifacts, plus page_count.",
    )

    def handler(
        shares: Any = None,
        layout: str = "auto",
        highlight: Any = None,
        max_shares_per_figure: int = 5,
        page: int = 1,
        interactive: bool = False,
        output_path: Optional[str] = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> dict:
        del interactive  # 本里程碑的执行器不打开交互图。
        per_page = int(max_shares_per_figure or 5)
        page_no = int(page or 1)
        target = _default_output_path(output_path)
        inputs_echo = {
            "shares": shares,
            "layout": layout or "auto",
            "highlight": highlight,
            "max_shares_per_figure": per_page,
            "page": page_no,
            "interactive": False,
            "output_path": target,
        }
        panel = panel_from_upstream(upstream_payload)
        if panel is None:
            return failed(
                metadata.name,
                "HP_PANEL_MISSING",
                "A HistoryPanel from the previous step is required.",
                inputs_echo,
            )
        try:
            pages = _page_count(panel, shares, per_page)
            import matplotlib

            try:
                matplotlib.use("Agg", force=True)
            except TypeError:
                matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            plot_kwargs: Dict[str, Any] = {
                "layout": layout or "auto",
                "interactive": False,
                "max_shares_per_figure": per_page,
                "page": page_no,
            }
            if shares not in (None, ""):
                plot_kwargs["shares"] = shares
            if highlight not in (None, ""):
                plot_kwargs["highlight"] = highlight
            fig = panel.plot(**plot_kwargs)
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            fig.savefig(target, dpi=120, bbox_inches="tight", pad_inches=0.1)
            plt.close(fig)
        except Exception as exc:
            return failed(
                metadata.name,
                "HP_PLOT_FAILED",
                english_message(exc, "Failed to plot the panel."),
                inputs_echo,
            )
        result = SkillResult(
            ok=True,
            skill_name=metadata.name,
            run_id=new_run_id(),
            inputs_echo=inputs_echo,
            metrics={"page": page_no, "page_count": pages, "n_rows": int(panel.row_count)},
            data_summary={"output_path": target},
            artifacts=[
                {
                    "type": "image",
                    "path": target,
                    "description": "Static HistoryPanel chart.",
                }
            ],
        )
        return result.to_dict()

    return metadata, handler
