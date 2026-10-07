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
from typing import Any, Callable, Dict, List, Optional, Tuple

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
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_KB_ENTRY_TYPES = frozenset({"concept", "trap", "boundary", "pointer"})
_KB_RELATION_RELS = frozenset({
    "see_also",
    "next_topic",
    "contrasts_with",
    "plan_handoff",
})


def _require_entry_type(entry_id: str, payload: Dict[str, Any]) -> str:
    """校验 JSON 条目的 type。适配器内存条目不走这里。"""

    if "type" not in payload or payload.get("type") in (None, ""):
        raise ValueError(f"KB entry {entry_id!r} is missing type")
    entry_type = payload["type"]
    if not isinstance(entry_type, str) or entry_type not in _KB_ENTRY_TYPES:
        raise ValueError(
            f"KB entry {entry_id!r} has invalid type {entry_type!r}; "
            "expected one of concept, trap, boundary, pointer"
        )
    return entry_type


def _parse_manual_anchor(entry_id: str, payload: Dict[str, Any]) -> str:
    """读取手册锚。空字符串允许；非空必须是 docs/source/ 相对路径。"""

    raw = payload.get("manual_anchor", "")
    if raw is None:
        raw = ""
    if not isinstance(raw, str):
        raise ValueError(f"KB entry {entry_id!r} manual_anchor must be a string")
    anchor = raw.strip()
    if anchor and not anchor.startswith("docs/source/"):
        raise ValueError(
            f"KB entry {entry_id!r} manual_anchor must start with 'docs/source/'"
        )
    return anchor


def _parse_relations(entry_id: str, payload: Dict[str, Any]) -> List[Dict[str, str]]:
    """读取 relations。缺省为空列表；rel 必须落在冻结枚举内。"""

    raw = payload.get("relations", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ValueError(f"KB entry {entry_id!r} relations must be a list")
    parsed: List[Dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError(f"KB entry {entry_id!r} relation must be an object")
        rel = item.get("rel")
        target = item.get("to")
        if not isinstance(rel, str) or rel not in _KB_RELATION_RELS:
            raise ValueError(f"KB entry {entry_id!r} has invalid relation rel {rel!r}")
        if not isinstance(target, str) or not target.strip():
            raise ValueError(f"KB entry {entry_id!r} relation is missing a non-empty 'to'")
        parsed.append({"rel": rel, "to": target})
    return parsed


@dataclass
class KbEntry:
    """一条机器可读知识条目。

    ``type`` 只要求 JSON 策展条目（concept / trap / boundary / pointer）。
    适配器内存条目（如 strategy_meta）保持空字符串，不落 JSON。
    ``manual_anchor`` 不参与打分。
    """

    id: str
    title: str
    summary: str
    narrative: str
    python_code: str = ""
    risk_notes: str = ""
    tags: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    type: str = ""
    manual_anchor: str = ""
    relations: List[Dict[str, str]] = field(default_factory=list)
    score: float = 0.0
    kernel_doc_zh: str = ""

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
            "type": self.type,
            "manual_anchor": self.manual_anchor,
            "relations": [dict(item) for item in self.relations],
            "score": self.score,
            "kernel_doc_zh": self.kernel_doc_zh,
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
            entry_id = str(payload["id"])
            entries.append(
                KbEntry(
                    id=entry_id,
                    title=str(payload.get("title", "")),
                    summary=str(payload.get("summary", "")),
                    narrative=str(payload.get("narrative", "")),
                    python_code=str(payload.get("python_code", "")),
                    risk_notes=str(payload.get("risk_notes", "")),
                    tags=[str(item) for item in payload.get("tags", [])],
                    keywords=[str(item) for item in payload.get("keywords", [])],
                    type=_require_entry_type(entry_id, payload),
                    manual_anchor=_parse_manual_anchor(entry_id, payload),
                    relations=_parse_relations(entry_id, payload),
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
            按分数降序；无命中时为空列表。低于最高分一半的命中会被丢弃，避免低分 bleed。
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
                type=entry.type,
                manual_anchor=entry.manual_anchor,
                relations=[dict(item) for item in entry.relations],
                score=score,
                kernel_doc_zh=entry.kernel_doc_zh,
            )
            scored.append(hit)
        strategy_hit = self._maybe_strategy_meta(q)
        if strategy_hit is not None:
            scored.append(strategy_hit)
        scored.sort(key=lambda item: item.score, reverse=True)
        if scored:
            top_score = scored[0].score
            floor = top_score * 0.5
            scored = [item for item in scored if item.score >= floor]
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

    @staticmethod
    def _term_in_query(term: str, query_lower: str, q_tokens: set) -> bool:
        """整 token / 词边界匹配，避免 ``run`` 命中 ``run_freq``。"""

        key = (term or "").strip().lower()
        if not key:
            return False
        if " " in key or _CJK_RE.search(key) or "." in key:
            return key in query_lower
        if key in q_tokens or (key + "s") in q_tokens or (key + "es") in q_tokens:
            return True
        pattern = r"(?<![a-z0-9_.])" + re.escape(key) + r"(?![a-z0-9_])"
        return bool(re.search(pattern, query_lower))

    def _score(self, *, query: str, entry: KbEntry) -> float:
        """计算 query 与条目的重叠分数。"""

        q_lower = query.lower()
        q_tokens = set(self._tokenize(query))
        score = 0.0
        for keyword in entry.keywords:
            if self._term_in_query(keyword, q_lower, q_tokens):
                score += 3.0
        for tag in entry.tags:
            if self._term_in_query(tag, q_lower, q_tokens):
                score += 2.0
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
            english_doc, kernel_zh = self._wrap_strategy_doc(strategy_id, doc_text)
            if english_doc:
                narrative_parts.append(english_doc)
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
            kernel_zh = ""
        return KbEntry(
            id="strategy_meta",
            title="Built-in strategy metadata",
            summary="Live read of qteasy.built_in_list / built_in_doc.",
            narrative="\n".join(narrative_parts),
            python_code=python_code,
            risk_notes="Ask answers metadata only. Use Plan to execute qt.ai.strategy_meta.* skills.",
            tags=["strategy", "meta"],
            keywords=["strategy", "macd", "dma"],
            type="",
            manual_anchor="",
            relations=[],
            score=8.0 if strategy_id else 4.0,
            kernel_doc_zh=kernel_zh,
        )

    @staticmethod
    def _wrap_strategy_doc(strategy_id: str, doc_text: str) -> Tuple[str, str]:
        """内核中文 docstring 英文化顶层说明，原文放入 kernel_doc_zh。

        Parameters
        ----------
        strategy_id : str
            内置策略 ID。
        doc_text : str
            ``qt.built_in_doc`` 原文。

        Returns
        -------
        english_narrative : str
            顶层英文说明。
        kernel_doc_zh : str
            中文内核原文；英文 docstring 时为空。
        """

        raw = (doc_text or "").strip()
        if not raw:
            return "", ""
        if not _CJK_RE.search(raw):
            return raw[:800], ""
        lines = [
            f"The {strategy_id} strategy is a built-in qteasy timing strategy.",
        ]
        if "PT" in raw or "目标仓位" in raw:
            lines.append("Signal type: PT (target-weight / target position percentage).")
        default_match = re.search(r"默认参数:\s*(\([^)]+\))", raw)
        if default_match:
            lines.append(f"Default parameters: {default_match.group(1)}.")
        if "MACD值大于0" in raw or "大于0时" in raw:
            lines.append("When the MACD value is greater than 0, set the target position to 1.")
        if "MACD值小于0" in raw or "小于0时" in raw:
            lines.append("When the MACD value is less than 0, set the target position to 0.")
        if "短周期" in raw and "长周期" in raw:
            lines.append(
                "Strategy parameters include short period (s), long period (l), "
                "and MACD DEA period (m)."
            )
        return "\n".join(lines), raw[:800]

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
