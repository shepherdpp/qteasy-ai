# coding=utf-8
# ======================================
# File: operator_from_spec.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-29
# Desc:
# qteasy AI 阶段 D：Spec + 源码 → Operator 描述。
# ======================================

"""从 StrategySpec 与策略文件构造 Operator 加载描述（频率不进 qt.run）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from ..contracts import (
    SkillError,
    SkillMetadata,
    SkillResult,
    SkillSideEffects,
    StrategySpec,
    new_run_id,
)
from .strategy_sanity import load_strategy_class
from .strategy_spec import resolve_spec_from_inputs


def build_operator_from_spec_skill(
    operator_factory: Callable[..., Any] | None = None,
    load_func: Callable[[str], Any] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.operator.build_from_spec``。

    Parameters
    ----------
    operator_factory : callable, optional
        注入 ``qteasy.Operator``。
    load_func : callable, optional
        ``strategy_path -> strategy class``，单测可注入。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。
    """

    if operator_factory is None:
        import qteasy as qt

        operator_factory = qt.Operator
    if load_func is None:
        load_func = lambda path: load_strategy_class(Path(path))

    metadata = SkillMetadata(
        name="qt.ai.operator.build_from_spec",
        version="0.1.0",
        summary="Build an Operator from StrategySpec and generated source (run_freq stays on Operator, not qt.run).",
        inputs_schema={
            "spec": {"type": "object", "required": False},
            "strategy_path": {"type": "string", "required": False},
        },
        outputs_schema={"strategy_path": "str", "run_freq": "str", "signal_type": "str"},
        side_effects=SkillSideEffects(description="readonly Operator assembly in memory"),
        required_capabilities=[],
        qteasy_entrypoints=["qteasy.Operator"],
        skill_kind="api",
    )

    def handler(
        spec: Any = None,
        strategy_path: str = "",
        upstream_payload: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> dict:
        run_id = new_run_id()
        payload_in = upstream_payload if isinstance(upstream_payload, dict) else {}
        spec_raw = resolve_spec_from_inputs(spec=spec, upstream_payload=upstream_payload, **kwargs)
        path_text = str(strategy_path or payload_in.get("strategy_path") or "").strip()
        inputs_echo = {"strategy_path": path_text}
        if not spec_raw:
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                error=SkillError(
                    code="SPEC_MISSING",
                    message="build_from_spec requires a StrategySpec payload.",
                ),
            )
            return result.to_dict()
        if not path_text:
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                error=SkillError(
                    code="STRATEGY_PATH_MISSING",
                    message="build_from_spec requires strategy_path.",
                ),
            )
            return result.to_dict()
        spec_obj = StrategySpec.from_dict(spec_raw)
        signal_type = str(spec_obj.signal_type or "PS").lower()
        run_freq = str(spec_obj.run_freq or "d")
        run_timing = str(spec_obj.run_timing or "close")
        try:
            cls = load_func(path_text)
            try:
                operator = operator_factory(
                    cls, signal_type=signal_type, run_freq=run_freq, run_timing=run_timing
                )
            except TypeError:
                operator = operator_factory(cls, run_freq=run_freq)
        except Exception as exc:
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                error=SkillError(
                    code="OPERATOR_BUILD_FAILED",
                    message=f"Failed to build Operator from spec: {exc}",
                ),
            )
            return result.to_dict()
        result = SkillResult(
            ok=True,
            skill_name=metadata.name,
            run_id=run_id,
            inputs_echo=inputs_echo,
            payload={
                "strategy_path": path_text,
                "class_name": getattr(cls, "__name__", spec_obj.class_name),
                "signal_type": signal_type.upper(),
                "run_freq": run_freq,
                "run_timing": run_timing,
                "spec": spec_obj.to_dict(),
                "operator_ready": operator is not None,
                "run_config": {},
            },
            data_summary={
                "strategy_path": path_text,
                "run_freq": run_freq,
                "signal_type": signal_type.upper(),
            },
        )
        return result.to_dict()

    return metadata, handler
