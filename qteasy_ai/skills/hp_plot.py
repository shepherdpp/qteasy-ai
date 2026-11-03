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
from typing import Any, Callable, Dict, List, Optional, Sequence

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


def _payloads(upstream_payload: Any, upstream_payloads: Any) -> List[Dict[str, Any]]:
    """有上游列表时以列表为准，否则用第一块。

    Parameters
    ----------
    upstream_payload : Any
        第一块上游 payload。
    upstream_payloads : Any
        全部上游 payload。

    Returns
    -------
    list of dict
        可用的上游字典。
    """

    if isinstance(upstream_payloads, list) and upstream_payloads:
        return [item for item in upstream_payloads if isinstance(item, dict)]
    if isinstance(upstream_payload, dict):
        return [upstream_payload]
    return []


def _squeeze_highlight(mask: Any) -> Any:
    """三维且末维为 1 的掩码收成二维。其它形状原样交给库。

    Parameters
    ----------
    mask : Any
        高亮条件。

    Returns
    -------
    Any
        库可接受的 ``max`` / ``min``、一维或二维布尔数组，或原本的对象。
    """

    if isinstance(mask, str):
        return mask
    array = np.asarray(mask)
    if array.ndim == 3 and array.shape[-1] == 1:
        array = np.asarray(array[:, :, 0])
    return array


def _resolve_highlight(highlight: Any, payloads: Sequence[Dict[str, Any]]) -> Any:
    """``max`` / ``min`` 优先。否则用上游布尔掩码。

    Parameters
    ----------
    highlight : Any
        调用方传入的高亮。
    payloads : sequence of dict
        上游 payload。

    Returns
    -------
    Any
        传给 ``HistoryPanel.plot`` 的高亮；没有则 ``None``。
    """

    if highlight in ("max", "min"):
        return highlight
    if highlight not in (None, ""):
        return _squeeze_highlight(highlight)
    for item in payloads:
        mask = item.get("mask")
        if mask is not None:
            return _squeeze_highlight(mask)
    return None


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
            "upstream_payloads": {"type": "array", "required": False},
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
        upstream_payloads: Optional[Sequence[Any]] = None,
        **kwargs,
    ) -> dict:
        del interactive  # 本里程碑的执行器不打开交互图。
        per_page = int(max_shares_per_figure or 5)
        page_no = int(page or 1)
        target = _default_output_path(output_path)
        payloads = _payloads(upstream_payload, upstream_payloads)
        resolved = _resolve_highlight(highlight, payloads)
        echo_highlight = highlight
        if highlight in (None, "") and resolved is not None:
            echo_highlight = "upstream_mask"
        inputs_echo = {
            "shares": shares,
            "layout": layout or "auto",
            "highlight": echo_highlight,
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
            if resolved is not None:
                plot_kwargs["highlight"] = resolved
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
