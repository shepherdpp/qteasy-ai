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


def build_factor_ic_summary_skill(
    panel_builder: Callable[..., Any] | None = None,
    factor_ic_func: Callable[..., Any] | None = None,
    factor_ic_summary_func: Callable[..., Any] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建因子 IC 摘要技能。

    Parameters
    ----------
    panel_builder : callable, optional
        返回 HistoryPanel 的工厂；未提供时由默认实现从行情构造（B0 测试以注入为主）。
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
        },
        outputs_schema={"metrics": "dict", "data_summary": "dict"},
        side_effects=SkillSideEffects(description="readonly"),
        required_capabilities=["qteasy.research"],
        qteasy_entrypoints=["qteasy.research.factor_ic", "qteasy.research.factor_ic_summary"],
        skill_kind="api",
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
            if panel_builder is None:
                raise ValueError(
                    "No panel_builder configured. Provide a HistoryPanel via skill injection "
                    "or pass a panel_builder when registering this skill."
                )
            panel = panel_builder(**inputs_echo)
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
