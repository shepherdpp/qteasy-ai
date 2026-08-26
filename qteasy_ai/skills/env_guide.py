# coding=utf-8
# ======================================
# File: env_guide.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-25
# Desc:
# qteasy AI B0 引导类 L1：Tushare token 与
# 核心数据表只读探针（不联网、不全库扫描）。
# ======================================

"""环境就绪引导技能（skill_kind=guide）。"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence

from ..contracts import SkillError, SkillMetadata, SkillResult, SkillSideEffects, new_run_id

# B0 固定核心表集合，禁止默认扫全库。
DEFAULT_CORE_TABLES: List[str] = [
    "stock_daily",
    "index_daily",
    "trade_calendar",
    "stock_basic",
]


def _default_token_probe() -> Dict[str, Any]:
    """从 QT_CONFIG / 环境变量探测 tushare_token（不联网）。"""

    import os

    env_token = str(os.environ.get("TUSHARE_TOKEN", "") or "").strip()
    if env_token:
        return {"token_present": True, "token_source": "env"}
    try:
        import qteasy as qt

        cfg = getattr(qt, "QT_CONFIG", None) or {}
        qt_token = str(cfg.get("tushare_token", "") or "").strip()
        if qt_token:
            return {"token_present": True, "token_source": "qt_config"}
    except Exception:
        pass
    return {"token_present": False, "token_source": "missing"}


def _default_table_info(table_name: str) -> Dict[str, Any]:
    """调用 qteasy DataSource.get_table_info，关闭打印。"""

    from qteasy import QT_DATA_SOURCE

    info = QT_DATA_SOURCE.get_table_info(table=table_name, verbose=False, print_info=False, human=False)
    return info if isinstance(info, dict) else {}


def _json_safe_scalar(value: Any) -> Any:
    """将表探针标量转为 JSON 友好类型。"""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


def _normalize_table_probe(table_name: str, info: Dict[str, Any]) -> Dict[str, Any]:
    """将 get_table_info 输出归一为 env_facts.tables 条目。"""

    exists = bool(info.get("table_exists", False))
    rows_raw = info.get("table_rows", 0)
    try:
        rows = int(rows_raw) if rows_raw not in (None, "") else 0
    except (TypeError, ValueError):
        rows = 0
    return {
        "exists": exists,
        "rows": rows,
        "pk_min": _json_safe_scalar(info.get("pk_min1")),
        "pk_max": _json_safe_scalar(info.get("pk_max1")),
    }


def build_check_tushare_skill(
    token_getter: Callable[[], Dict[str, Any]] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 Tushare token 只读检查技能。"""

    if token_getter is None:
        token_getter = _default_token_probe

    metadata = SkillMetadata(
        name="qt.ai.env.check_tushare",
        version="0.1.5",
        summary="Check whether Tushare token is configured (no network ping).",
        inputs_schema={},
        outputs_schema={"metrics": "dict", "data_summary": "dict"},
        side_effects=SkillSideEffects(description="readonly"),
        required_capabilities=["qteasy_config"],
        qteasy_entrypoints=["qteasy.QT_CONFIG"],
        skill_kind="guide",
    )

    def handler(**kwargs) -> dict:
        run_id = new_run_id()
        inputs_echo = dict(kwargs)
        try:
            probe = token_getter()
            token_present = bool(probe.get("token_present"))
            token_source = str(probe.get("token_source", "missing"))
            metrics = {
                "token_present": token_present,
                "token_source": token_source,
            }
            data_summary = {"tushare": metrics}
            warnings: List[str] = []
            error = None
            ok = True
            if not token_present:
                warnings.append("Tushare token is not configured.")
                error = SkillError(
                    code="TUSHARE_TOKEN_MISSING",
                    message="Tushare token is not configured. Set tushare_token in qteasy.cfg or TUSHARE_TOKEN env.",
                )
                # 探针本身成功；缺失 token 用 warnings + error 详情，ok 仍 True 便于 merge env_facts
            result = SkillResult(
                ok=ok,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                metrics=metrics,
                data_summary=data_summary,
                warnings=warnings,
                error=error,
                payload={"env_probe": {"tushare": metrics}},
            )
        except Exception as exc:
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                error=SkillError(
                    code="TUSHARE_CHECK_FAILED",
                    message=f"Failed to check Tushare token: {exc}",
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


def build_overview_tables_skill(
    table_info_func: Callable[[str], Dict[str, Any]] | None = None,
    default_tables: Optional[Sequence[str]] = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建核心数据表只读概览技能。"""

    if table_info_func is None:
        table_info_func = _default_table_info
    core_tables = list(default_tables) if default_tables is not None else list(DEFAULT_CORE_TABLES)

    metadata = SkillMetadata(
        name="qt.ai.env.overview_tables",
        version="0.1.5",
        summary="Probe core local data tables (exists/rows); does not scan full database.",
        inputs_schema={
            "tables": {"type": "list", "required": False},
        },
        outputs_schema={"metrics": "dict", "data_summary": "dict"},
        side_effects=SkillSideEffects(description="readonly"),
        required_capabilities=["local_datasource"],
        qteasy_entrypoints=["qteasy.DataSource.get_table_info"],
        skill_kind="guide",
    )

    def handler(tables: Optional[Sequence[str]] = None, **kwargs) -> dict:
        run_id = new_run_id()
        table_names = list(tables) if tables else list(core_tables)
        inputs_echo = {"tables": table_names, **kwargs}
        try:
            tables_probe: Dict[str, Any] = {}
            missing: List[str] = []
            for name in table_names:
                info = table_info_func(name)
                if not isinstance(info, dict):
                    info = {}
                # 支持直接注入归一后的 dict（含 exists/rows）或原始 get_table_info 输出
                if "exists" in info and "rows" in info:
                    entry = {
                        "exists": bool(info["exists"]),
                        "rows": int(info.get("rows", 0) or 0),
                        "pk_min": _json_safe_scalar(info.get("pk_min")),
                        "pk_max": _json_safe_scalar(info.get("pk_max")),
                    }
                else:
                    entry = _normalize_table_probe(name, info)
                tables_probe[name] = entry
                if not entry["exists"]:
                    missing.append(name)
            metrics = {
                "table_count": len(tables_probe),
                "missing_count": len(missing),
                "missing_tables": missing,
            }
            data_summary = {"tables": tables_probe}
            result = SkillResult(
                ok=True,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                metrics=metrics,
                data_summary=data_summary,
                payload={"env_probe": {"tables": tables_probe}},
                warnings=(
                    [f"Missing local tables: {', '.join(missing)}."] if missing else []
                ),
            )
        except Exception as exc:
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                error=SkillError(
                    code="TABLE_OVERVIEW_FAILED",
                    message=f"Failed to overview local tables: {exc}",
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
