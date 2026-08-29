# coding=utf-8
# ======================================
# File: backtest_run.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-27
# Desc:
# qteasy AI 阶段 B L1：内置策略回测。
# ======================================

"""内置策略回测技能（高副作用：写 trade_log）。"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional
from pathlib import Path

from ..contracts import SkillError, SkillMetadata, SkillResult, SkillSideEffects, new_run_id


def _json_safe_metric(value: Any) -> Any:
    """将回测指标转为 JSON 友好标量。"""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        try:
            text = value.isoformat()
            return text[:10] if "T" in text or len(text) >= 10 else text
        except Exception:
            return str(value)
    if hasattr(value, "date"):
        try:
            return str(value.date())
        except Exception:
            return str(value)
    return str(value)


def _slice_backtest_output(raw: Any) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """从内核回测 dict 切片 metrics / artifacts，不塞入完整 DataFrame。"""

    metrics: Dict[str, Any] = {}
    artifacts: List[Dict[str, Any]] = []
    if not isinstance(raw, dict):
        return metrics, artifacts
    for key in ("final_value", "annual_rtn", "mdd", "peak_date", "valley_date", "recover_date"):
        if key in raw and raw[key] is not None:
            metrics[key] = _json_safe_metric(raw[key])
    for key, kind in (
        ("trade_log_file", "trade_log"),
        ("trade_log", "trade_log"),
        ("complete_values_file", "complete_values_file"),
    ):
        path = raw.get(key)
        if isinstance(path, str) and path.strip():
            artifacts.append({"kind": kind, "path": path.strip()})
    return metrics, artifacts


def build_backtest_run_skill(
    run_func: Callable[..., Any] | None = None,
    operator_factory: Callable[..., Any] | None = None,
    list_func: Callable[[], list] | None = None,
    load_func: Callable[[str], Any] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建内置或生成策略回测技能。

    Parameters
    ----------
    run_func : callable, optional
        注入 ``qteasy.run``；单测返回金标准 dict，避免真回测。
    operator_factory : callable, optional
        ``strategy_id 或策略类 -> Operator``。
    list_func : callable, optional
        内置策略 ID 列表。
    load_func : callable, optional
        ``strategy_path -> 策略类``；有 ``strategy_path`` 时不查内置 ID。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。
    """

    if run_func is None:
        import qteasy as qt

        run_func = qt.run
    if operator_factory is None:
        import qteasy as qt

        operator_factory = qt.Operator
    if list_func is None:
        import qteasy as qt

        list_func = qt.built_in_list
    if load_func is None:
        from .strategy_sanity import load_strategy_class

        load_func = lambda path: load_strategy_class(Path(path))

    metadata = SkillMetadata(
        name="qt.ai.backtest.run_builtin",
        version="0.2.0",
        summary="Run a built-in or generated-strategy backtest (mode=1) and return sliced metrics.",
        inputs_schema={
            "strategy_id": {"type": "string", "required": True},
            "asset_pool": {"type": "string", "required": False},
            "shares": {"type": "string", "required": False},
            "invest_start": {"type": "string", "required": False},
            "invest_end": {"type": "string", "required": False},
            "start": {"type": "string", "required": False},
            "end": {"type": "string", "required": False},
            "freq": {"type": "string", "required": False},
            "strategy_path": {"type": "string", "required": False},
            "signal_type": {"type": "string", "required": False},
        },
        outputs_schema={"metrics": "dict", "artifacts": "list"},
        side_effects=SkillSideEffects(
            filesystem_write=True,
            heavy_compute=True,
            description="backtest writes trade_log / value curve files",
        ),
        required_capabilities=["local_datasource"],
        qteasy_entrypoints=["qteasy.Operator", "qteasy.run"],
        skill_kind="api",
    )

    def handler(
        strategy_id: str = "",
        asset_pool: Optional[str] = None,
        shares: Optional[str] = None,
        invest_start: Optional[str] = None,
        invest_end: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        freq: str = "d",
        strategy_path: str = "",
        signal_type: str = "",
        upstream_payload: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> dict:
        run_id = new_run_id()
        payload_in = upstream_payload if isinstance(upstream_payload, dict) else {}
        path_text = str(strategy_path or payload_in.get("strategy_path") or "").strip()
        spec_raw = payload_in.get("spec") if isinstance(payload_in.get("spec"), dict) else {}
        pool = asset_pool or shares or spec_raw.get("asset_pool") or "000300.SH"
        start_date = invest_start or start or spec_raw.get("invest_start")
        end_date = invest_end or end or spec_raw.get("invest_end")
        run_freq = freq or spec_raw.get("run_freq") or payload_in.get("run_freq") or "d"
        sig = (
            signal_type
            or payload_in.get("signal_type")
            or spec_raw.get("signal_type")
            or "PS"
        )
        inputs_echo = {
            "strategy_id": strategy_id,
            "asset_pool": pool,
            "invest_start": start_date,
            "invest_end": end_date,
            "freq": run_freq,
            "strategy_path": path_text,
            **kwargs,
        }
        sid = str(strategy_id).strip()
        try:
            if path_text:
                stg_obj = load_func(path_text)
                try:
                    operator = operator_factory(
                        stg_obj,
                        run_freq=run_freq,
                        signal_type=str(sig).lower(),
                    )
                except TypeError:
                    try:
                        operator = operator_factory(stg_obj, run_freq=run_freq)
                    except TypeError:
                        operator = operator_factory(stg_obj)
                canonical = getattr(stg_obj, "__name__", path_text)
            else:
                known = [str(item).strip() for item in list_func() if str(item).strip()]
                lower_map = {item.lower(): item for item in known}
                if sid.lower() not in lower_map:
                    result = SkillResult(
                        ok=False,
                        skill_name=metadata.name,
                        run_id=run_id,
                        inputs_echo=inputs_echo,
                        error=SkillError(
                            code="UNKNOWN_STRATEGY_ID",
                            message=f"Unknown built-in strategy id: {sid}. Use strategy_meta.list to inspect available ids.",
                        ),
                    )
                    return result.to_dict()
                canonical = lower_map[sid.lower()]
                try:
                    operator = operator_factory(canonical, run_freq=run_freq)
                except TypeError:
                    operator = operator_factory(canonical)
            import qteasy as qt

            # freq 不是 QT_CONFIG 键；运行频率应落在 Operator(run_freq=...) 上
            run_kwargs: Dict[str, Any] = {
                "mode": getattr(qt, "BACKTEST_MODE", 1),
                "visual": False,
                "report": False,
                "trade_log": True,
                "asset_pool": pool,
            }
            if start_date:
                run_kwargs["invest_start"] = start_date
            if end_date:
                run_kwargs["invest_end"] = end_date
            raw = run_func(operator, **run_kwargs)
            metrics, artifacts = _slice_backtest_output(raw)
            result = SkillResult(
                ok=True,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                metrics=metrics,
                data_summary={"strategy_id": canonical, "asset_pool": pool, "mode": 1},
                artifacts=artifacts,
                payload={"strategy_id": canonical, "strategy_path": path_text},
            )
        except Exception as exc:
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                error=SkillError(
                    code="BACKTEST_FAILED",
                    message=f"Failed to run built-in backtest: {exc}",
                ),
            )
        return result.to_dict()

    return metadata, handler
