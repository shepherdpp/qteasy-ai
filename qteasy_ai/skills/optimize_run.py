# coding=utf-8
# ======================================
# File: optimize_run.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-27
# Desc:
# qteasy AI 阶段 B L1：内置策略参数优化。
# ======================================

"""内置策略优化技能（AI 默认 montecarlo sample=32）。"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from ..contracts import SkillError, SkillMetadata, SkillResult, SkillSideEffects, new_run_id

DEFAULT_OPTI_METHOD = "montecarlo"
DEFAULT_OPTI_SAMPLE_COUNT = 32


def _json_safe(value: Any) -> Any:
    """将优化输出转为 JSON 友好结构。"""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if hasattr(value, "tolist"):
        try:
            return _json_safe(value.tolist())
        except Exception:
            return str(value)
    return str(value)


def _slice_optimize_output(
    raw: Any,
    *,
    opti_method: str,
    opti_sample_count: int,
) -> Dict[str, Any]:
    """从 qt.run(mode=2) 返回值切片 best_pars / fv。"""

    metrics: Dict[str, Any] = {
        "opti_method": opti_method,
        "opti_sample_count": int(opti_sample_count),
    }
    if isinstance(raw, dict):
        best_pars = raw.get("best_pars", raw.get("pars"))
        fv = raw.get("fv", raw.get("final_value", raw.get("perf")))
        if raw.get("opti_method"):
            metrics["opti_method"] = raw["opti_method"]
        if raw.get("opti_sample_count") is not None:
            metrics["opti_sample_count"] = int(raw["opti_sample_count"])
        metrics["best_pars"] = _json_safe(best_pars)
        metrics["fv"] = _json_safe(fv)
        return metrics
    items = getattr(raw, "items", None)
    perfs = getattr(raw, "perfs", None)
    if callable(items):
        items = None
    if items:
        metrics["best_pars"] = _json_safe(items[0])
        if perfs:
            metrics["fv"] = _json_safe(perfs[0])
        else:
            extras = getattr(raw, "extras", None) or getattr(raw, "extra", None)
            if extras:
                first = extras[0]
                if isinstance(first, dict):
                    metrics["fv"] = _json_safe(first.get("fv", first.get("final_value")))
                else:
                    metrics["fv"] = _json_safe(first)
        return metrics
    metrics["best_pars"] = None
    metrics["fv"] = None
    return metrics


def build_optimize_run_skill(
    run_func: Callable[..., Any] | None = None,
    operator_factory: Callable[[str], Any] | None = None,
    list_func: Callable[[], list] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建内置策略优化技能。

    Parameters
    ----------
    run_func : callable, optional
        注入 ``qteasy.run``。
    operator_factory : callable, optional
        ``strategy_id -> Operator``。
    list_func : callable, optional
        内置策略 ID 列表。

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

    metadata = SkillMetadata(
        name="qt.ai.optimize.run_builtin",
        version="0.2.0",
        summary="Optimize built-in strategy parameters (mode=2, montecarlo sample=32 by default).",
        inputs_schema={
            "strategy_id": {"type": "string", "required": True},
            "asset_pool": {"type": "string", "required": False},
            "shares": {"type": "string", "required": False},
            "invest_start": {"type": "string", "required": False},
            "invest_end": {"type": "string", "required": False},
            "start": {"type": "string", "required": False},
            "end": {"type": "string", "required": False},
            "opti_method": {"type": "string", "required": False},
            "opti_sample_count": {"type": "integer", "required": False},
        },
        outputs_schema={"metrics": "dict"},
        side_effects=SkillSideEffects(
            filesystem_write=True,
            heavy_compute=True,
            description="parameter optimization is heavy compute",
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
        opti_method: str = DEFAULT_OPTI_METHOD,
        opti_sample_count: int = DEFAULT_OPTI_SAMPLE_COUNT,
        **kwargs,
    ) -> dict:
        run_id = new_run_id()
        pool = asset_pool or shares or "000300.SH"
        start_date = invest_start or start
        end_date = invest_end or end
        method = str(opti_method or DEFAULT_OPTI_METHOD)
        sample_count = int(opti_sample_count or DEFAULT_OPTI_SAMPLE_COUNT)
        inputs_echo = {
            "strategy_id": strategy_id,
            "asset_pool": pool,
            "invest_start": start_date,
            "invest_end": end_date,
            "opti_method": method,
            "opti_sample_count": sample_count,
            **kwargs,
        }
        sid = str(strategy_id).strip()
        try:
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
                        message=f"Unknown built-in strategy id: {sid}.",
                    ),
                )
                return result.to_dict()
            canonical = lower_map[sid.lower()]
            operator = operator_factory(canonical)
            strategies: List[Any] = list(getattr(operator, "strategies", []) or [])
            for stg in strategies:
                setter = getattr(stg, "set_opt_tag", None)
                if callable(setter):
                    setter(1)
                elif hasattr(operator, "set_parameter") and hasattr(stg, "name"):
                    try:
                        operator.set_parameter(stg.name, opt_tag=1)
                    except Exception:
                        pass
            import qteasy as qt

            run_kwargs: Dict[str, Any] = {
                "mode": 2,
                "visual": False,
                "report": False,
                "opti_method": method,
                "opti_sample_count": sample_count,
                "asset_pool": pool,
            }
            if start_date:
                run_kwargs["opti_start"] = start_date
                run_kwargs["invest_start"] = start_date
            if end_date:
                run_kwargs["opti_end"] = end_date
                run_kwargs["invest_end"] = end_date
            raw = run_func(operator, **run_kwargs)
            metrics = _slice_optimize_output(raw, opti_method=method, opti_sample_count=sample_count)
            result = SkillResult(
                ok=True,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                metrics=metrics,
                data_summary={"strategy_id": canonical, "mode": 2},
                payload={
                    "assumptions": [
                        f"AI default opti_method={method}",
                        f"AI default opti_sample_count={sample_count} (kernel default is typically 256)",
                    ]
                },
                warnings=[
                    f"Using AI default opti_sample_count={sample_count} (smaller than typical kernel default 256)."
                ],
            )
        except AssertionError as exc:
            message = str(exc)
            if "opt_tag" in message.lower() or "adjustable" in message.lower():
                result = SkillResult(
                    ok=False,
                    skill_name=metadata.name,
                    run_id=run_id,
                    inputs_echo=inputs_echo,
                    error=SkillError(
                        code="OPTIMIZE_NO_ADJUSTABLE_PARS",
                        message=(
                            "None of the strategy parameters is adjustable. "
                            "Set opt_tag to 1 or 2 before optimization."
                        ),
                    ),
                )
                return result.to_dict()
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                error=SkillError(code="OPTIMIZE_FAILED", message=f"Failed to optimize: {exc}"),
            )
        except Exception as exc:
            message = str(exc)
            if "opt_tag" in message.lower() or "adjustable" in message.lower():
                result = SkillResult(
                    ok=False,
                    skill_name=metadata.name,
                    run_id=run_id,
                    inputs_echo=inputs_echo,
                    error=SkillError(
                        code="OPTIMIZE_NO_ADJUSTABLE_PARS",
                        message=(
                            "None of the strategy parameters is adjustable. "
                            "Set opt_tag to 1 or 2 before optimization."
                        ),
                    ),
                )
                return result.to_dict()
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                error=SkillError(code="OPTIMIZE_FAILED", message=f"Failed to optimize: {exc}"),
            )
        return result.to_dict()

    return metadata, handler
