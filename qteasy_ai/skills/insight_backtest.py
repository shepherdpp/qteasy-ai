# coding=utf-8
# ======================================
# File: insight_backtest.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-27
# Desc:
# qteasy AI 阶段 B L3：只读回测归因摘要。
# ======================================

"""回测内生归因技能（skill_kind=insight，不发起回测/下载）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..contracts import SkillError, SkillMetadata, SkillResult, SkillSideEffects, new_run_id

_CHANGE_HINT = (
    "To change behaviour, inspect strategy_meta parameters "
    "(e.g. qt.ai.strategy_meta.get) and re-run backtest; this skill does not generate strategy code."
)


def _is_backtest_step(step: Dict[str, Any]) -> bool:
    """判断执行步是否为成功回测。"""

    name = str(step.get("skill_name") or "")
    result = step.get("result") or {}
    return name == "qt.ai.backtest.run_builtin" and bool(result.get("ok"))


def _pick_last_backtest_run(runs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """从 run 记录列表中取最近一次成功回测。"""

    for payload in reversed(runs):
        steps = ((payload.get("execution") or {}).get("steps")) or []
        if any(_is_backtest_step(step) for step in steps):
            return payload
        plan_steps = ((payload.get("plan") or {}).get("steps")) or []
        if any(str(step.get("skill_name") or "") == "qt.ai.backtest.run_builtin" for step in plan_steps):
            exec_steps = ((payload.get("execution") or {}).get("steps")) or []
            if exec_steps and any((step.get("result") or {}).get("ok") for step in exec_steps):
                return payload
    return None


def _metrics_from_run(payload: Dict[str, Any]) -> Dict[str, Any]:
    """从 run JSON 取出回测 metrics。"""

    steps = ((payload.get("execution") or {}).get("steps")) or []
    for step in steps:
        if _is_backtest_step(step):
            return dict((step.get("result") or {}).get("metrics") or {})
    return {}


def _artifacts_from_run(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 run JSON 取出 artifacts。"""

    steps = ((payload.get("execution") or {}).get("steps")) or []
    for step in steps:
        if _is_backtest_step(step):
            return list((step.get("result") or {}).get("artifacts") or [])
    return []


def _safe_date_prefix(value: Any) -> str:
    """把回撤锚点收成可用于 contains 的日期前缀；NaT/空串丢弃。"""

    text = str(value or "").strip()
    if not text or text.lower() in {"nat", "nan", "none", "nattype"}:
        return ""
    if "NaT" in text:
        return ""
    return text[:10]


def _trade_summary_from_log(path: str, *, peak_date: str, valley_date: str) -> List[Dict[str, Any]]:
    """读取 trade_log 中回撤邻近日的少量摘要（有文件才读）。"""

    target = Path(path)
    if not target.exists():
        return []
    try:
        import pandas as pd

        frame = pd.read_csv(target)
    except Exception:
        return []
    if frame.empty:
        return []
    date_col = None
    for candidate in ("date", "trade_date", "datetime", "time"):
        if candidate in frame.columns:
            date_col = candidate
            break
    if date_col is None:
        return frame.head(5).to_dict(orient="records")
    text = frame[date_col].astype(str)
    anchors = []
    for item in (peak_date, valley_date):
        prefix = _safe_date_prefix(item)
        if prefix:
            anchors.append(prefix)
    if not anchors:
        return frame.head(5).to_dict(orient="records")
    mask = False
    for prefix in anchors:
        mask = mask | text.str.contains(prefix, na=False)
    nearby = frame.loc[mask]
    if nearby.empty:
        return frame.head(5).to_dict(orient="records")
    return nearby.head(10).to_dict(orient="records")


def build_insight_backtest_skill(
    load_run_func: Callable[[str], Dict[str, Any]] | None = None,
    list_run_payloads_func: Callable[[], List[Dict[str, Any]]] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建回测归因摘要技能。

    Parameters
    ----------
    load_run_func : callable, optional
        ``run_id -> run JSON dict``。
    list_run_payloads_func : callable, optional
        返回已保存 run 记录（时间升序），用于默认「最近一次成功回测」。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。
    """

    if load_run_func is None or list_run_payloads_func is None:
        from ..memory_store import MemoryStore

        store = MemoryStore()
        if load_run_func is None:
            load_run_func = store.load_run

        if list_run_payloads_func is None:

            def list_run_payloads_func() -> List[Dict[str, Any]]:
                return [store.load_run(item) for item in store.list_runs()]

    metadata = SkillMetadata(
        name="qt.ai.insight.summarize_backtest",
        version="0.2.0",
        summary="Read-only summary of an existing backtest run (drawdown window, no codegen).",
        inputs_schema={
            "run_id": {"type": "string", "required": False},
        },
        outputs_schema={"metrics": "dict", "payload": "dict"},
        side_effects=SkillSideEffects(description="readonly insight"),
        required_capabilities=[],
        qteasy_entrypoints=[],
        skill_kind="insight",
    )

    def handler(
        run_id: str = "",
        upstream_run_id: str = "",
        upstream_metrics: Optional[Dict[str, Any]] = None,
        upstream_artifacts: Optional[List[Dict[str, Any]]] = None,
        **kwargs,
    ) -> dict:
        skill_run_id = new_run_id()
        inputs_echo = {
            "run_id": run_id,
            "upstream_run_id": upstream_run_id,
            **kwargs,
        }
        try:
            metrics = dict(upstream_metrics or {})
            artifacts = list(upstream_artifacts or [])
            source_run_id = str(run_id or upstream_run_id or "").strip()
            if not metrics:
                payload: Dict[str, Any] = {}
                if source_run_id and load_run_func is not None:
                    payload = load_run_func(source_run_id) or {}
                elif list_run_payloads_func is not None:
                    payload = _pick_last_backtest_run(list_run_payloads_func() or []) or {}
                    source_run_id = str(payload.get("run_id") or source_run_id)
                if payload:
                    metrics = _metrics_from_run(payload)
                    if not artifacts:
                        artifacts = _artifacts_from_run(payload)
            if not metrics:
                result = SkillResult(
                    ok=False,
                    skill_name=metadata.name,
                    run_id=skill_run_id,
                    inputs_echo=inputs_echo,
                    error=SkillError(
                        code="INSIGHT_NO_BACKTEST",
                        message="No backtest artifacts found. Run a built-in backtest first.",
                        details={"next_step": "Call qt.ai.backtest.run_builtin, then summarize again."},
                    ),
                )
                return result.to_dict()
            peak = metrics.get("peak_date")
            valley = metrics.get("valley_date")
            recover = metrics.get("recover_date")
            mdd = metrics.get("mdd")
            trade_rows: List[Dict[str, Any]] = []
            for item in artifacts:
                if not isinstance(item, dict):
                    continue
                if item.get("kind") in {"trade_log", "trade_log_file"} and item.get("path"):
                    trade_rows = _trade_summary_from_log(
                        str(item["path"]),
                        peak_date=str(peak or ""),
                        valley_date=str(valley or ""),
                    )
                    break
            insight_metrics = {
                "annual_rtn": metrics.get("annual_rtn"),
                "mdd": mdd,
                "peak_date": peak,
                "valley_date": valley,
                "recover_date": recover,
                "final_value": metrics.get("final_value"),
            }
            result = SkillResult(
                ok=True,
                skill_name=metadata.name,
                run_id=skill_run_id,
                inputs_echo=inputs_echo,
                metrics=insight_metrics,
                data_summary={"source_run_id": source_run_id},
                payload={
                    "drawdown": {
                        "mdd": mdd,
                        "peak_date": peak,
                        "valley_date": valley,
                        "recover_date": recover,
                    },
                    "nearby_trades": trade_rows,
                    "change_hint": _CHANGE_HINT,
                },
                warnings=[],
            )
        except Exception as exc:
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=skill_run_id,
                inputs_echo=inputs_echo,
                error=SkillError(
                    code="INSIGHT_FAILED",
                    message=f"Failed to summarize backtest: {exc}",
                ),
            )
        return result.to_dict()

    return metadata, handler
