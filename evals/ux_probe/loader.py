# coding=utf-8
# ======================================
# File: loader.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-29
# Desc:
# 加载 UX Probe 的 personas / tasks / rubrics YAML。
# ======================================

"""加载体验罗盘 YAML 真源。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import yaml

PROBE_ROOT = Path(__file__).resolve().parent
DEFAULT_PRODUCT = "0.3-ask"

# Ordered product floors for min_product skip logic.
_PRODUCT_ORDER = ("0.3-ask", "0.4-wow", "0.5-ce1", "1.0")


@dataclass
class Persona:
    """一个可复用用户画像。"""

    id: str
    display_name: str
    role: str
    language_style: str
    comprehension: str
    preferences: List[str] = field(default_factory=list)
    learning_goals: List[str] = field(default_factory=list)
    taboos: List[str] = field(default_factory=list)
    plain_language_default: bool = False
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Turn:
    """任务中的一轮用户发言。"""

    id: str
    text: str = ""
    improvise: bool = False
    hint: str = ""


@dataclass
class Task:
    """挂在某画像上的一条可升级任务。"""

    id: str
    persona_id: str
    channel: str
    goal: str
    turns: List[Turn]
    min_product: str = DEFAULT_PRODUCT
    upgrade_of: str = ""
    path: Path = field(default_factory=Path)


@dataclass
class Rubrics:
    """无人值守法官量规。"""

    dimensions: List[Dict[str, Any]]
    judge_instructions: str
    scale_min: int = 1
    scale_max: int = 5
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProbeBundle:
    """一次加载的完整真源。"""

    root: Path
    personas: Dict[str, Persona]
    tasks: Dict[str, Task]
    rubrics: Rubrics


def _read_yaml(path: Path) -> Any:
    """读取 YAML 文件。"""

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def product_rank(label: str) -> int:
    """产品地板排序；未知标签排最后。"""

    key = str(label or "").strip()
    if key in _PRODUCT_ORDER:
        return _PRODUCT_ORDER.index(key)
    return len(_PRODUCT_ORDER)


def meets_min_product(task_min: str, current: str) -> bool:
    """当前产品是否达到任务要求的地板。"""

    return product_rank(current) >= product_rank(task_min)


def load_personas(path: Path) -> Dict[str, Persona]:
    """加载画像表。"""

    payload = _read_yaml(path) or {}
    rows = payload.get("personas") or []
    out: Dict[str, Persona] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        pid = str(row.get("id") or "").strip()
        if not pid:
            continue
        out[pid] = Persona(
            id=pid,
            display_name=str(row.get("display_name") or pid),
            role=str(row.get("role") or ""),
            language_style=str(row.get("language_style") or ""),
            comprehension=str(row.get("comprehension") or ""),
            preferences=[str(x) for x in (row.get("preferences") or [])],
            learning_goals=[str(x) for x in (row.get("learning_goals") or [])],
            taboos=[str(x) for x in (row.get("taboos") or [])],
            plain_language_default=bool(row.get("plain_language_default")),
            raw=dict(row),
        )
    return out


def load_task(path: Path) -> Task:
    """加载单个任务文件。"""

    payload = _read_yaml(path) or {}
    turns_raw = payload.get("turns") or []
    turns: List[Turn] = []
    for idx, item in enumerate(turns_raw):
        if not isinstance(item, Mapping):
            continue
        turns.append(
            Turn(
                id=str(item.get("id") or f"T{idx + 1}"),
                text=str(item.get("text") or "").strip(),
                improvise=bool(item.get("improvise")),
                hint=str(item.get("hint") or "").strip(),
            )
        )
    return Task(
        id=str(payload.get("id") or path.stem),
        persona_id=str(payload.get("persona_id") or "").strip(),
        channel=str(payload.get("channel") or "ask").strip().lower(),
        goal=str(payload.get("goal") or "").strip(),
        turns=turns,
        min_product=str(payload.get("min_product") or DEFAULT_PRODUCT).strip(),
        upgrade_of=str(payload.get("upgrade_of") or "").strip(),
        path=path,
    )


def load_tasks(tasks_dir: Path) -> Dict[str, Task]:
    """加载 tasks 目录下全部 YAML。"""

    out: Dict[str, Task] = {}
    if not tasks_dir.is_dir():
        return out
    for path in sorted(tasks_dir.glob("*.yaml")):
        task = load_task(path)
        out[task.id] = task
    return out


def load_rubrics(path: Path) -> Rubrics:
    """加载打分量规。"""

    payload = _read_yaml(path) or {}
    scale = payload.get("scale") or {}
    return Rubrics(
        dimensions=list(payload.get("dimensions") or []),
        judge_instructions=str(payload.get("judge_instructions") or "").strip(),
        scale_min=int(scale.get("min") or 1),
        scale_max=int(scale.get("max") or 5),
        raw=dict(payload),
    )


def load_bundle(root: Optional[Path] = None) -> ProbeBundle:
    """加载完整 UX Probe 真源。

    Parameters
    ----------
    root : Path, optional
        默认为本包目录 ``evals/ux_probe``。

    Returns
    -------
    ProbeBundle
    """

    base = Path(root) if root is not None else PROBE_ROOT
    personas = load_personas(base / "personas.yaml")
    tasks = load_tasks(base / "tasks")
    rubrics = load_rubrics(base / "rubrics.yaml")
    for task in tasks.values():
        if task.persona_id not in personas:
            raise ValueError(f"task {task.id} references unknown persona {task.persona_id}")
    return ProbeBundle(root=base, personas=personas, tasks=tasks, rubrics=rubrics)
