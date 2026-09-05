# coding=utf-8
# ======================================
# File: __init__.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-02
# Desc:
# IntentCatalog 加载器：jobs / triggers /
# conflicts / gold 等包内 JSON。
# ======================================

"""意图目录（产品表）与引擎决策对象。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_PACK_DIR = Path(__file__).resolve().parent


def _load_json(name: str) -> Dict[str, Any]:
    """读取本包 JSON 表。"""

    path = _PACK_DIR / name
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@dataclass
class IntentDecision:
    """方案 H′ 分类结果：只含 Job / flags，不含 steps。"""

    job: str
    flags: Dict[str, Any] = field(default_factory=dict)
    source: str = "rule"
    rationale: str = ""
    llm_called: bool = False


class IntentCatalog:
    """包内 Intent 表。改表 + gold 测试即可进化理解力。"""

    def __init__(self, root: Optional[Path] = None) -> None:
        base = Path(root) if root is not None else _PACK_DIR
        self.root = base
        self.jobs_doc = _read(base / "jobs.json")
        self.triggers_doc = _read(base / "triggers.json")
        self.conflicts_doc = _read(base / "conflicts.json")
        self.unsupported_doc = _read(base / "unsupported.json")
        self.legal_edges_doc = _read(base / "legal_edges.json")
        self.aliases_doc = _read(base / "aliases.json")
        self.gold_doc = _read(base / "gold.json")

    @property
    def official_ids(self) -> List[str]:
        """官方 Job id 列表。"""

        return [str(item["id"]) for item in self.jobs_doc.get("official", [])]

    @property
    def system_ids(self) -> List[str]:
        """系统出口 id 列表。"""

        return [str(item["id"]) for item in self.jobs_doc.get("system", [])]

    @property
    def all_job_ids(self) -> List[str]:
        """官方 Job ∪ 系统出口。"""

        return self.official_ids + self.system_ids

    def job_summaries(self) -> List[str]:
        """分类 prompt 用的一行定义。"""

        lines: List[str] = []
        for item in self.jobs_doc.get("official", []) + self.jobs_doc.get("system", []):
            lines.append(f"- {item['id']}: {item.get('summary', '')}")
        return lines

    def gold_cases(self) -> List[Dict[str, Any]]:
        """金句表。"""

        return list(self.gold_doc.get("cases") or [])

    def legal_allowed_skills(self) -> List[str]:
        """open 白名单技能。"""

        return list(self.legal_edges_doc.get("allowed_skills") or [])

    def legal_forbidden_skills(self) -> List[str]:
        """open 禁止技能。"""

        return list(self.legal_edges_doc.get("forbidden_skills") or [])

    def legal_max_steps(self) -> int:
        """open DAG 最大步数。"""

        return int(self.legal_edges_doc.get("max_steps") or 3)


def _read(path: Path) -> Dict[str, Any]:
    """读 JSON，缺文件则空 dict。"""

    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_default_catalog() -> IntentCatalog:
    """加载包内默认 Catalog。"""

    return IntentCatalog()


__all__ = ["IntentCatalog", "IntentDecision", "load_default_catalog"]
