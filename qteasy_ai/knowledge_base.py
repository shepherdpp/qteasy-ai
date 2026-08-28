# coding=utf-8
# ======================================
# File: knowledge_base.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-28
# Desc:
# qteasy-ai 策展 KnowledgeBase：关键词/tag
# 检索，供 Ask 目标态主消费。
# ======================================

"""qteasy 专用结构化知识库（Ask 目标态主消费方）。

本模块只做只读检索，不调用 SkillRegistry / PlanExecutor。
策略元数据可注入 ``list_func`` / ``doc_func``（默认对接 ``qteasy.built_in_*``），
仍不经过 skill handler。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_KB_DIR = Path(__file__).resolve().parent / "kb"

_STRATEGY_QUERY_HINTS = (
    "strategy",
    "macd",
    "dma",
    "built-in",
    "builtin",
    "built in",
    "策略",
    "参数",
)

_WORD_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)


@dataclass
class KbEntry:
    """一条机器可读知识条目。"""

    id: str
    title: str
    summary: str
    narrative: str
    python_code: str = ""
    risk_notes: str = ""
    tags: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转为字典。"""

        return {
            "id": self.id,
            "title": self.title,
            "summary": self.summary,
            "narrative": self.narrative,
            "python_code": self.python_code,
            "risk_notes": self.risk_notes,
            "tags": list(self.tags),
            "keywords": list(self.keywords),
            "score": self.score,
        }


class KnowledgeBase:
    """从 ``qteasy_ai/kb/*.json`` 加载策展条目并按关键词打分检索。

    Parameters
    ----------
    kb_dir : Path, optional
        知识 JSON 目录，默认包内 ``kb/``。
    list_func : callable, optional
        返回内置策略 ID 列表；默认 ``qt.built_in_list``。
    doc_func : callable, optional
        返回策略说明文本；默认 ``qt.built_in_doc``。
    """

    def __init__(
        self,
        *,
        kb_dir: Optional[Path] = None,
        list_func: Optional[Callable[..., list]] = None,
        doc_func: Optional[Callable[..., Any]] = None,
    ) -> None:
        self.kb_dir = Path(kb_dir) if kb_dir is not None else _KB_DIR
        self._list_func = list_func
        self._doc_func = doc_func
        self._entries: List[KbEntry] = self._load_entries()

    def _load_entries(self) -> List[KbEntry]:
        """加载目录中全部 JSON 条目。"""

        entries: List[KbEntry] = []
        if not self.kb_dir.exists():
            return entries
        for path in sorted(self.kb_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or not payload.get("id"):
                continue
            entries.append(
                KbEntry(
                    id=str(payload["id"]),
                    title=str(payload.get("title", "")),
                    summary=str(payload.get("summary", "")),
                    narrative=str(payload.get("narrative", "")),
                    python_code=str(payload.get("python_code", "")),
                    risk_notes=str(payload.get("risk_notes", "")),
                    tags=[str(item) for item in payload.get("tags", [])],
                    keywords=[str(item) for item in payload.get("keywords", [])],
                )
            )
        return entries

    def retrieve(self, query: str, *, limit: int = 3) -> List[KbEntry]:
        """按关键词与 tag 重叠检索条目。

        Parameters
        ----------
        query : str
            用户自然语言问题。
        limit : int, default 3
            返回条数上限。

        Returns
        -------
        list of KbEntry
            按分数降序；无命中时为空列表。
        """

        q = (query or "").strip()
        if not q:
            return []
        scored: List[KbEntry] = []
        for entry in self._entries:
            score = self._score(query=q, entry=entry)
            if score <= 0:
                continue
            hit = KbEntry(
                id=entry.id,
                title=entry.title,
                summary=entry.summary,
                narrative=entry.narrative,
                python_code=entry.python_code,
                risk_notes=entry.risk_notes,
                tags=list(entry.tags),
                keywords=list(entry.keywords),
                score=score,
            )
            scored.append(hit)
        strategy_hit = self._maybe_strategy_meta(q)
        if strategy_hit is not None:
            scored.append(strategy_hit)
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[: max(1, int(limit))] if scored else []

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """切出用于打分的 token。"""

        lower = text.lower()
        tokens = _WORD_RE.findall(lower)
        extra = []
        for word in ("pt", "ps", "vs", "macd", "dma"):
            if word in lower and word not in tokens:
                extra.append(word)
        return tokens + extra

    def _score(self, *, query: str, entry: KbEntry) -> float:
        """计算 query 与条目的重叠分数。"""

        q_lower = query.lower()
        score = 0.0
        for keyword in entry.keywords:
            key = keyword.lower()
            if not key:
                continue
            if key in q_lower:
                score += 3.0
        for tag in entry.tags:
            tag_l = tag.lower()
            if tag_l and tag_l in q_lower:
                score += 2.0
        q_tokens = set(self._tokenize(query))
        id_tokens = set(self._tokenize(entry.id.replace("_", " ")))
        score += 1.0 * len(q_tokens & id_tokens)
        return score

    def _maybe_strategy_meta(self, query: str) -> Optional[KbEntry]:
        """策略问答时从内置 API 组装一条 strategy_meta 条目。"""

        q_lower = query.lower()
        if not any(hint in q_lower for hint in _STRATEGY_QUERY_HINTS):
            return None
        list_func = self._resolve_list_func()
        doc_func = self._resolve_doc_func()
        if list_func is None:
            return None
        try:
            names = [str(item) for item in list(list_func())]
        except Exception:
            return None
        strategy_id = self._extract_strategy_id(query=query, names=names)
        narrative_parts = [
            "Built-in strategy metadata is read from qteasy APIs (not via a skill handler).",
        ]
        python_code = "import qteasy as qt\nprint(qt.built_in_list())"
        if strategy_id:
            doc_text = ""
            if doc_func is not None:
                try:
                    doc_text = str(doc_func(strategy_id) or "")
                except Exception:
                    doc_text = ""
            narrative_parts.append(f"Matched strategy_id={strategy_id}.")
            if doc_text:
                narrative_parts.append(doc_text[:800])
            python_code = (
                "import qteasy as qt\n"
                f"print(qt.built_in_doc('{strategy_id}'))\n"
                f"obj = qt.get_built_in_strategy('{strategy_id}')\n"
                "print(type(obj).__name__)"
            )
        else:
            preview = ", ".join(names[:20])
            narrative_parts.append(f"Built-in strategy ids (truncated): {preview}.")
            if len(names) > 20:
                narrative_parts.append(f"Total count: {len(names)}.")
        return KbEntry(
            id="strategy_meta",
            title="Built-in strategy metadata",
            summary="Live read of qteasy.built_in_list / built_in_doc.",
            narrative="\n".join(narrative_parts),
            python_code=python_code,
            risk_notes="Ask answers metadata only. Use Plan to execute qt.ai.strategy_meta.* skills.",
            tags=["strategy", "meta"],
            keywords=["strategy", "macd", "dma"],
            score=8.0 if strategy_id else 4.0,
        )

    @staticmethod
    def _extract_strategy_id(*, query: str, names: List[str]) -> str:
        """从问句中匹配已知策略 ID。"""

        q_lower = query.lower()
        for name in sorted(names, key=len, reverse=True):
            if name.lower() in q_lower:
                return name
        return ""

    def _resolve_list_func(self) -> Optional[Callable[..., list]]:
        """解析策略列表函数。"""

        if self._list_func is not None:
            return self._list_func
        try:
            import qteasy as qt

            return qt.built_in_list
        except Exception:
            return None

    def _resolve_doc_func(self) -> Optional[Callable[..., Any]]:
        """解析策略文档函数。"""

        if self._doc_func is not None:
            return self._doc_func
        try:
            import qteasy as qt

            return qt.built_in_doc
        except Exception:
            return None
