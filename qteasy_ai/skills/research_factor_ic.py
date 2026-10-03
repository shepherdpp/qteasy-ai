# coding=utf-8
# ======================================
# File: research_factor_ic.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-25
# Desc:
# qteasy AI B0 只读研究技能：因子 IC 摘要。
# ======================================

"""因子 IC 摘要只读技能（L1）。"""

from __future__ import annotations

from typing import Any, Callable

from ..contracts import SkillError, SkillMetadata, SkillResult, SkillSideEffects, new_run_id


def _share_codes(shares: Any) -> list[str]:
    """把标的参数拆成代码列表。"""

    if shares is None or shares == "":
        return []
    if isinstance(shares, (list, tuple)):
        raw_parts = [str(item) for item in shares]
    else:
        raw_parts = str(shares).replace("，", ",").replace(";", ",").split(",")
    codes: list[str] = []
    for part in raw_parts:
        for piece in part.split():
            text = piece.strip()
            if text:
                codes.append(text)
    return codes


def local_history_panel_builder(
    get_history_data: Callable[..., Any] | None = None,
    **inputs: Any,
) -> Any:
    """从本地行情构造截面 IC 用的 HistoryPanel。

    少于两个代码或缺少日期时直接报错，不访问数据源。空面板或取数失败时
    要求先 refill。不在此处计算或 shift 收益列。

    Parameters
    ----------
    get_history_data : callable, optional
        本地取数入口；默认 ``qteasy.get_history_data``。
    **inputs
        ``shares`` / ``start`` / ``end`` / ``freq`` / ``factor_htype`` / ``return_htype``。

    Returns
    -------
    HistoryPanel
        含所请求两列的面板。

    Raises
    ------
    ValueError
        池子、日期、列或本地数据不足。
    """

    factor_htype = str(inputs.get("factor_htype") or "factor")
    return_htype = str(inputs.get("return_htype") or "ret")
    start = inputs.get("start")
    end = inputs.get("end")
    freq = inputs.get("freq") or "d"
    codes = _share_codes(inputs.get("shares"))
    if len(codes) < 2 or not start or not end:
        raise ValueError(
            "Name at least two symbols and a date range (start and end), "
            "plus factor_htype and return_htype that already exist in local history. "
            "Example: factor IC of close vs volume for 000001.SZ,000002.SZ "
            "from 20240101 to 20240331. "
            "This skill does not compute or shift return columns."
        )

    fetcher = get_history_data
    if fetcher is None:
        import qteasy as qt

        fetcher = qt.get_history_data
    share_text = ",".join(codes)
    try:
        panel = fetcher(
            htype_names=[factor_htype, return_htype],
            shares=codes,
            start=start,
            end=end,
            freq=freq,
            as_data_frame=False,
        )
    except Exception as exc:
        raise ValueError(
            f"No local history for {share_text} from {start} to {end}. "
            "Refill that range, then retry. "
            "This skill does not compute or shift return columns. "
            f"Cause: {exc}"
        ) from exc
    if panel is None or not hasattr(panel, "is_empty") or bool(panel.is_empty):
        raise ValueError(
            f"No local history for {share_text} from {start} to {end}. "
            "Refill that range, then retry. "
            "This skill does not compute or shift return columns."
        )
    columns = [str(name) for name in list(panel.htypes)]
    missing = [name for name in (factor_htype, return_htype) if name not in columns]
    if missing:
        raise ValueError(
            f"Unknown column(s) {missing} on the local HistoryPanel; columns are {columns}. "
            "Use factor_htype and return_htype that already exist locally. "
            "This skill does not compute or shift return columns."
        )
    return panel


def build_factor_ic_summary_skill(
    panel_builder: Callable[..., Any] | None = None,
    factor_ic_func: Callable[..., Any] | None = None,
    factor_ic_summary_func: Callable[..., Any] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建因子 IC 摘要技能。

    Parameters
    ----------
    panel_builder : callable, optional
        返回 HistoryPanel 的工厂。未提供时使用 ``local_history_panel_builder``。
    factor_ic_func / factor_ic_summary_func : callable, optional
        注入 ``qteasy.research`` 入口，便于单测。
    """

    if factor_ic_func is None or factor_ic_summary_func is None:
        from qteasy.research import factor_ic as _factor_ic
        from qteasy.research import factor_ic_summary as _factor_ic_summary

        if factor_ic_func is None:
            factor_ic_func = _factor_ic
        if factor_ic_summary_func is None:
            factor_ic_summary_func = _factor_ic_summary

    metadata = SkillMetadata(
        name="qt.ai.research.factor_ic_summary",
        version="0.1.5",
        summary="Compute cross-sectional factor IC summary (read-only research).",
        inputs_schema={
            "factor_htype": {"type": "string", "required": False},
            "return_htype": {"type": "string", "required": False},
            "method": {"type": "string", "required": False},
            "min_assets": {"type": "integer", "required": False},
            "shares": {"type": "string", "required": False},
            "start": {"type": "string", "required": False},
            "end": {"type": "string", "required": False},
            "freq": {"type": "string", "required": False},
        },
        outputs_schema={"metrics": "dict", "data_summary": "dict"},
        side_effects=SkillSideEffects(description="readonly"),
        required_capabilities=["qteasy.research"],
        qteasy_entrypoints=["qteasy.research.factor_ic", "qteasy.research.factor_ic_summary"],
        skill_kind="api",
        expected_artifact="A data table in Artifacts with the factor IC summary.",
    )

    def handler(
        factor_htype: str = "factor",
        return_htype: str = "ret",
        method: str = "spearman",
        min_assets: int = 2,
        **kwargs,
    ) -> dict:
        run_id = new_run_id()
        inputs_echo = {
            "factor_htype": factor_htype,
            "return_htype": return_htype,
            "method": method,
            "min_assets": min_assets,
            **kwargs,
        }
        try:
            builder = panel_builder if panel_builder is not None else local_history_panel_builder
            panel = builder(**inputs_echo)
            ic = factor_ic_func(
                panel,
                factor_htype,
                return_htype,
                method=method,
                min_assets=int(min_assets),
            )
            summary = factor_ic_summary_func(ic)
            metrics = {
                "mean": float(summary.loc["mean"]),
                "std": float(summary.loc["std"]),
                "ir": float(summary.loc["ir"]),
                "win_rate": float(summary.loc["win_rate"]),
                "n_periods": int(len(ic)),
                "n_valid": int(ic.dropna().shape[0]),
            }
            data_summary = {
                "factor_htype": factor_htype,
                "return_htype": return_htype,
                "method": method,
                "ic_index_start": str(ic.index.min()) if len(ic) else None,
                "ic_index_end": str(ic.index.max()) if len(ic) else None,
            }
            result = SkillResult(
                ok=True,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                metrics=metrics,
                data_summary=data_summary,
                payload={"ic_preview": [None if (v != v) else float(v) for v in ic.head(10).tolist()]},
            )
        except Exception as exc:
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                error=SkillError(
                    code="FACTOR_IC_SUMMARY_FAILED",
                    message=f"Failed to compute factor IC summary: {exc}",
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
