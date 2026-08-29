# coding=utf-8
# ======================================
# File: strategy_sanity.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-29
# Desc:
# qteasy AI 阶段 D：策略骨架静态校验。
# ======================================

"""对生成策略做失败要早的静态检查，不调用 qt.run。"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ..contracts import (
    SkillError,
    SkillMetadata,
    SkillResult,
    SkillSideEffects,
    StrategySpec,
    new_run_id,
)
from .strategy_spec import resolve_spec_from_inputs


def load_strategy_class(path: Path):
    """从策略源码文件加载 qteasy 策略类。

    Parameters
    ----------
    path : Path
        策略 ``.py`` 路径。

    Returns
    -------
    type
        策略类。

    Raises
    ------
    FileNotFoundError, ImportError, ValueError
        文件不存在、无法加载或找不到策略类。
    """

    target = Path(path)
    if not target.exists():
        raise FileNotFoundError(f"strategy file not found: {target}")
    module = _load_module(target)
    cls = _find_strategy_class(module)
    if cls is None:
        raise ValueError(f"no qteasy strategy class found in {target}")
    return cls


def _load_module(path: Path):
    """从文件路径加载模块。"""

    spec_loader = importlib.util.spec_from_file_location(f"sanity_{path.stem}", path)
    if spec_loader is None or spec_loader.loader is None:
        raise ImportError(f"Cannot load strategy module from {path}")
    module = importlib.util.module_from_spec(spec_loader)
    spec_loader.loader.exec_module(module)
    return module


def _find_strategy_class(module) -> Optional[type]:
    """找出模块中的 qteasy 策略类。"""

    import qteasy as qt

    found = []
    for name in dir(module):
        obj = getattr(module, name)
        if inspect_is_strategy_class(obj, qt):
            if getattr(obj, "__module__", "") == module.__name__:
                found.append(obj)
    return found[0] if found else None


def inspect_is_strategy_class(obj: Any, qt: Any) -> bool:
    """判断是否为 qteasy 策略类。"""

    if not isinstance(obj, type):
        return False
    base = getattr(qt, "BaseStrategy", None) or getattr(qt, "RuleIterator", None)
    if base is None:
        return False
    try:
        return issubclass(obj, base) and obj is not base
    except TypeError:
        return False


def _ast_get_data_ids(source: str) -> Set[str]:
    """从 realize 中收集 get_data 字符串参数。"""

    ids: Set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ids
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_get_data = (
            (isinstance(func, ast.Attribute) and func.attr == "get_data")
            or (isinstance(func, ast.Name) and func.id == "get_data")
        )
        if not is_get_data or not node.args:
            continue
        arg0 = node.args[0]
        if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
            ids.add(arg0.value)
    return ids


def _has_realize(cls: type) -> bool:
    """类自身是否实现 realize。"""

    return "realize" in getattr(cls, "__dict__", {})


def check_strategy_file(
    path: Path,
    spec: Optional[StrategySpec] = None,
) -> Tuple[bool, List[str], Dict[str, Any]]:
    """校验策略文件，返回 (ok, issues, details)。"""

    issues: List[str] = []
    details: Dict[str, Any] = {"strategy_path": str(path)}
    if not path.exists():
        return False, [f"strategy file not found: {path}"], details
    source = path.read_text(encoding="utf-8")
    module = _load_module(path)
    cls = _find_strategy_class(module)
    if cls is None:
        issues.append("no qteasy strategy class found (expected RuleIterator/GeneralStg/FactorSorter)")
        return False, issues, details
    details["class_name"] = cls.__name__
    import qteasy as qt

    if not issubclass(cls, qt.RuleIterator):
        issues.append(f"class {cls.__name__} is not a RuleIterator (this stage only supports RuleIterator SMA cross)")
    if not _has_realize(cls):
        issues.append(f"class {cls.__name__} does not implement realize()")
    instance = cls()
    par_names: List[str] = []
    named = getattr(instance, "par_names", None)
    if named:
        par_names = [str(item) for item in named]
    else:
        pars = getattr(instance, "pars", None)
        if isinstance(pars, dict):
            items = pars.values()
        elif isinstance(pars, (list, tuple)):
            items = pars
        else:
            items = []
        for item in items:
            name = getattr(item, "name", None) or (item.get("name") if isinstance(item, dict) else None)
            if name:
                par_names.append(str(name))
    details["par_names"] = par_names
    expected_names = []
    slow_value = None
    if spec is not None:
        expected_names = [str(item.get("name")) for item in spec.parameters]
        for item in spec.parameters:
            if item.get("name") == "slow":
                slow_value = int(item.get("default") or 0)
    if expected_names:
        missing = [name for name in expected_names if name not in par_names]
        if missing:
            issues.append(f"missing parameter names: {missing}")
    data_types = getattr(instance, "data_types", None) or {}
    window_lengths: List[int] = []
    dtype_ids: List[str] = []
    if isinstance(data_types, dict):
        for dtype_id, dtype in data_types.items():
            dtype_ids.append(str(dtype_id))
            window_lengths.append(int(getattr(dtype, "window_length", 0) or 0))
    elif isinstance(data_types, (list, tuple)):
        for dtype in data_types:
            dtype_ids.append(str(getattr(dtype, "dtype_id", getattr(dtype, "name", ""))))
            window_lengths.append(int(getattr(dtype, "window_length", 0) or 0))
    details["dtype_ids"] = dtype_ids
    details["window_lengths"] = window_lengths
    max_window = max(window_lengths) if window_lengths else 0
    if slow_value is not None and max_window < slow_value:
        issues.append(f"window_length {max_window} < slow {slow_value}")
    get_data_ids = _ast_get_data_ids(source)
    details["get_data_ids"] = sorted(get_data_ids)
    if dtype_ids and get_data_ids:
        unknown = [item for item in get_data_ids if item not in dtype_ids]
        if unknown:
            issues.append(
                f"get_data ids {unknown} do not match data_types {dtype_ids}"
            )
    return (len(issues) == 0), issues, details


def build_strategy_sanity_check_skill(
    run_func: Callable[..., Any] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.strategy.sanity_check``。

    Parameters
    ----------
    run_func : callable, optional
        仅用于断言本技能不调用回测；实现中忽略该参数。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。
    """

    metadata = SkillMetadata(
        name="qt.ai.strategy.sanity_check",
        version="0.1.0",
        summary="Statically check a generated strategy file (realize/pars/StgData/window) without running backtests.",
        inputs_schema={
            "strategy_path": {"type": "string", "required": False},
            "spec": {"type": "object", "required": False},
        },
        outputs_schema={"issues": "list"},
        side_effects=SkillSideEffects(description="readonly static check"),
        required_capabilities=[],
        qteasy_entrypoints=["qteasy.RuleIterator"],
        skill_kind="api",
    )
    _unused_run_func = run_func  # 静态检查禁止调用 qt.run；保留注入点供单测证明未回测

    def handler(
        strategy_path: str = "",
        spec: Any = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> dict:
        run_id = new_run_id()
        payload_in = upstream_payload if isinstance(upstream_payload, dict) else {}
        path_text = str(strategy_path or payload_in.get("strategy_path") or "").strip()
        spec_raw = resolve_spec_from_inputs(spec=spec, upstream_payload=upstream_payload, **kwargs)
        spec_obj = StrategySpec.from_dict(spec_raw) if spec_raw else None
        inputs_echo = {"strategy_path": path_text}
        if not path_text:
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                error=SkillError(
                    code="STRATEGY_PATH_MISSING",
                    message="sanity_check requires strategy_path.",
                ),
            )
            return result.to_dict()
        ok, issues, details = check_strategy_file(Path(path_text), spec=spec_obj)
        if not ok:
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                payload={"issues": issues, "details": details, "spec": spec_raw},
                error=SkillError(
                    code="SANITY_CHECK_FAILED",
                    message="Generated strategy failed static checks: " + "; ".join(issues),
                    details={"issues": issues},
                ),
            )
            return result.to_dict()
        result = SkillResult(
            ok=True,
            skill_name=metadata.name,
            run_id=run_id,
            inputs_echo=inputs_echo,
            payload={
                "issues": [],
                "details": details,
                "strategy_path": path_text,
                "spec": spec_raw,
            },
            metrics={"issue_count": 0},
            data_summary=details,
        )
        return result.to_dict()

    return metadata, handler
