# coding=utf-8
# ======================================
# File: visual_export.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-04-15
# Desc:
# qteasy AI 阶段A只读技能：K线图导出。
# ======================================

"""K线导出技能。"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Callable, Optional

import pandas as pd

from ..contracts import SkillError, SkillMetadata, SkillResult, SkillSideEffects, new_run_id


def _default_output_path(output_path: Optional[str]) -> str:
    """计算默认输出路径。"""

    if output_path:
        return output_path
    folder = os.path.join(os.getcwd(), ".qteasy", "ai", "artifacts")
    os.makedirs(folder, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(folder, f"kline_{timestamp}.png")


def _normalize_plot_type(plot_type: Optional[str]) -> str:
    """把 plot_type 收成 candle 或 line。"""

    if plot_type is None:
        return "candle"
    raw = str(plot_type).strip().lower()
    if raw in {"", "candle"}:
        return "candle"
    if raw in {"line", "close"}:
        return "line"
    raise ValueError(f"Unsupported plot_type: {plot_type}. Use 'candle' or 'line'.")


def _share_label(shares: str) -> str:
    """单表堆成面板时用的标的标签。"""

    text = str(shares or "").strip()
    if not text:
        return "share"
    first = text.split(",")[0].strip()
    return first or "share"


def _as_history_panel(data: Any, shares: str) -> Any:
    """把 get_kline 的返回值收成 HistoryPanel。"""

    from qteasy.history import HistoryPanel, stack_dataframes

    if isinstance(data, HistoryPanel):
        if data.is_empty:
            raise ValueError("No data returned.")
        return data
    if isinstance(data, dict):
        frames = {
            str(key): frame
            for key, frame in data.items()
            if isinstance(frame, pd.DataFrame) and not frame.empty
        }
        if not frames:
            raise ValueError("No data returned.")
        return stack_dataframes(frames, dataframe_as="shares")
    if isinstance(data, pd.DataFrame):
        if data.empty:
            raise ValueError("No data returned.")
        return stack_dataframes({_share_label(shares): data}, dataframe_as="shares")
    raise ValueError("No data returned.")


def _panel_for_plot(panel: Any, plot_type: str) -> Any:
    """蜡烛图要求完整 OHLC；折线只保留 close。"""

    from qteasy.hp_visual_spec import _match_ohlc_family

    if plot_type == "line":
        htypes = list(panel.htypes)
        close_name = next(
            (name for name in htypes if name == "close" or str(name).startswith("close|")),
            None,
        )
        if close_name is None:
            raise ValueError("A close column is required to export a close curve.")
        return panel[close_name]
    if _match_ohlc_family(list(panel.htypes)) is None:
        raise ValueError(
            "K-line export requires a complete OHLC panel. "
            "Close-only curves need plot_type='line'."
        )
    return panel


def build_visual_export_skill(
    get_kline_func: Callable[..., Any] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 K 线导出技能。"""

    if get_kline_func is None:
        import qteasy as qt

        get_kline_func = qt.get_kline

    metadata = SkillMetadata(
        name="qt.ai.visual.export_kline",
        version="0.1.0",
        summary="Export kline chart image.",
        inputs_schema={
            "shares": {"type": "string", "required": False},
            "start": {"type": "string", "required": False},
            "end": {"type": "string", "required": False},
            "freq": {"type": "string", "required": False},
            "output_path": {"type": "string", "required": False},
            "plot_type": {"type": "string", "required": False},
        },
        outputs_schema={"artifacts": "list"},
        side_effects=SkillSideEffects(filesystem_write=True, description="export image file"),
        required_capabilities=["matplotlib"],
        qteasy_entrypoints=["qteasy.get_kline"],
        expected_artifact="A chart image in Artifacts.",
    )

    def handler(
        shares: str = "000300.SH",
        start: Optional[str] = None,
        end: Optional[str] = None,
        freq: str = "D",
        output_path: Optional[str] = None,
        plot_type: Optional[str] = "candle",
        **kwargs,
    ) -> dict:
        run_id = new_run_id()
        target_path = _default_output_path(output_path)
        inputs_echo = {
            "shares": shares,
            "start": start,
            "end": end,
            "freq": freq,
            "output_path": target_path,
            "plot_type": plot_type,
            **kwargs,
        }
        try:
            data = get_kline_func(
                shares=shares,
                start=start,
                end=end,
                freq=freq,
                as_panel=True,
            )
            panel = _as_history_panel(data, shares)
            kind = _normalize_plot_type(plot_type)
            chart = _panel_for_plot(panel, kind)
            # 工作台线程必须用 Agg。qt.candle() 会弹窗并叠 MA/MACD，这里只取静态 Figure。
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig = chart.plot(interactive=False)
            os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)
            # 与 IPython display(fig) 相同：裁掉默认 subplot 灰边，不重排子图。
            fig.savefig(target_path, dpi=120, bbox_inches="tight", pad_inches=0.1)
            plt.close(fig)
            dates = list(panel.hdates)
            result = SkillResult(
                ok=True,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                metrics={"n_rows": int(panel.row_count)},
                data_summary={"index_start": str(dates[0]), "index_end": str(dates[-1])},
                artifacts=[
                    {
                        "type": "image",
                        "path": target_path,
                        "description": "Exported kline chart.",
                    }
                ],
            )
        except Exception as exc:
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                error=SkillError(
                    code="KLINE_EXPORT_FAILED",
                    message=f"Failed to export kline chart: {exc}",
                ),
            )

        return {
            "ok": result.ok,
            "skill_name": result.skill_name,
            "run_id": result.run_id,
            "inputs_echo": result.inputs_echo,
            "metrics": result.metrics,
            "data_summary": result.data_summary,
            "payload": result.payload,
            "warnings": result.warnings,
            "error": None if result.error is None else result.error.__dict__,
            "artifacts": result.artifacts,
        }

    return metadata, handler
