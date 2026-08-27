# coding=utf-8
# ======================================
# File: data_refill.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-27
# Desc:
# qteasy AI 阶段 B L1：本地数据源 refill
# （股票/指数日线，禁止无界全历史）。
# ======================================

"""本地数据源下载技能（高副作用）。"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence

from ..contracts import SkillError, SkillMetadata, SkillResult, SkillSideEffects, new_run_id
from .env_guide import _default_token_probe

DEFAULT_REFILL_TABLES: List[str] = ["stock_daily", "index_daily"]

_TOKEN_HINT = (
    "Tushare token is not configured. Set environment variable TUSHARE_TOKEN "
    "or QT_CONFIG['tushare_token'] (qteasy.cfg) before calling refill."
)


def build_data_refill_skill(
    refill_func: Callable[..., Any] | None = None,
    token_getter: Callable[[], Dict[str, Any]] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建基础股票/指数日线 refill 技能。

    Parameters
    ----------
    refill_func : callable, optional
        注入 ``qteasy.refill_data_source``；单测必须注入，禁止真联网。
    token_getter : callable, optional
        返回 ``{"token_present": bool, ...}`` 的探针。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。
    """

    if token_getter is None:
        token_getter = _default_token_probe
    if refill_func is None:
        import qteasy as qt

        refill_func = qt.refill_data_source

    metadata = SkillMetadata(
        name="qt.ai.data.refill_basic_equity_and_index",
        version="0.2.0",
        summary="Download stock_daily and index_daily into the local datasource (high cost).",
        inputs_schema={
            "start": {"type": "string", "required": True},
            "end": {"type": "string", "required": True},
            "tables": {"type": "list", "required": False},
            "symbols": {"type": "string", "required": False},
        },
        outputs_schema={"metrics": "dict", "data_summary": "dict"},
        side_effects=SkillSideEffects(
            network=True,
            filesystem_write=True,
            local_state_change=True,
            heavy_compute=True,
            description="network download and local datasource write",
        ),
        required_capabilities=["tushare_token", "local_datasource"],
        qteasy_entrypoints=["qteasy.core.refill_data_source"],
        skill_kind="api",
    )

    def handler(
        start: str = "",
        end: str = "",
        tables: Optional[Sequence[str]] = None,
        symbols: Optional[str] = None,
        **kwargs,
    ) -> dict:
        run_id = new_run_id()
        table_names = list(tables) if tables else list(DEFAULT_REFILL_TABLES)
        inputs_echo = {
            "start": start,
            "end": end,
            "tables": table_names,
            "symbols": symbols,
            **kwargs,
        }
        if not str(start).strip() or not str(end).strip():
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                error=SkillError(
                    code="REFILL_DATE_RANGE_REQUIRED",
                    message="start and end dates are required. Unbounded full-history download is not allowed.",
                    details={"missing_info": "date_range"},
                ),
            )
            return result.to_dict()
        try:
            probe = token_getter() or {}
            if not bool(probe.get("token_present")):
                result = SkillResult(
                    ok=False,
                    skill_name=metadata.name,
                    run_id=run_id,
                    inputs_echo=inputs_echo,
                    metrics={"token_present": False},
                    error=SkillError(
                        code="TUSHARE_TOKEN_MISSING",
                        message=_TOKEN_HINT,
                    ),
                )
                return result.to_dict()
            refill_kwargs: Dict[str, Any] = {
                "tables": table_names,
                "start_date": str(start).strip(),
                "end_date": str(end).strip(),
                "refill_dependent_tables": True,
            }
            if symbols:
                refill_kwargs["symbols"] = symbols
            refill_func(**refill_kwargs)
            assumptions = []
            if not symbols:
                assumptions.append("all symbols for those tables (high cost)")
            result = SkillResult(
                ok=True,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                metrics={
                    "table_count": len(table_names),
                    "start": str(start).strip(),
                    "end": str(end).strip(),
                },
                data_summary={
                    "tables": table_names,
                    "symbols": symbols or "ALL",
                    "refill_dependent_tables": True,
                },
                payload={"assumptions": assumptions},
                warnings=(
                    ["No symbols given: refill will cover all symbols for those tables (high cost)."]
                    if not symbols
                    else []
                ),
            )
        except Exception as exc:
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                error=SkillError(
                    code="REFILL_FAILED",
                    message=f"Failed to refill local datasource: {exc}",
                ),
            )
        return result.to_dict()

    return metadata, handler
