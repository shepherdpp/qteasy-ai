# coding=utf-8
# ======================================
# File: knowledge_base.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-28
# Desc:
# qteasy-ai 策展 KnowledgeBase：无模型路径先问句目录，
# 未命中再按 type 桶关键词/tag 检索。主题注册表供有模型选题。
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
from typing import AbstractSet, Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from qteasy_ai.kb_catalog import normalize_question

_KB_DIR = Path(__file__).resolve().parent / "kb"

_WORD_RE = re.compile(r"[a-z0-9_]+", re.IGNORECASE)
_LIST_BUILTINS_RE = re.compile(
    r"list\s+(?:the\s+)?built[\s-]?in\s+strateg(?:y|ies)"
    r"|列出内置策略"
    r"|有哪些内置策略"
    r"|内置策略列表",
    re.IGNORECASE,
)
# 同分时更具体的抽屉优先，避免 trap/boundary 被 concept 并列挤掉。
_TYPE_TIE_RANK = {
    "trap": 0,
    "boundary": 1,
    "pointer": 2,
    "concept": 3,
}
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_KB_ENTRY_TYPES = frozenset({"concept", "trap", "boundary", "pointer"})
_KB_RELATION_RELS = frozenset({
    "see_also",
    "next_topic",
    "contrasts_with",
    "plan_handoff",
})
# 目录命中是定条，分数只用于和关键词命中区分，不参与桶内打分。
_CATALOG_HIT_SCORE = 100.0
_EXCLUSIVE_ENTRY_TYPES = ("trap", "boundary")


@dataclass(frozen=True)
class TopicSpec:
    """主题注册表的一行：id、一句话范围、可选能力地图编号。"""

    id: str
    scope: str
    map_item: Optional[int] = None


def load_topic_registry(path: Path) -> List[TopicSpec]:
    """读取主题注册表。

    Parameters
    ----------
    path : Path
        ``topic_registry.json``。

    Returns
    -------
    list of TopicSpec
        文件中的顺序。

    Raises
    ------
    ValueError
        文件缺失、不是非空列表，或某一行缺 id / scope。
    """

    if not path.is_file():
        raise ValueError(f"KB topic registry is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("topics") if isinstance(payload, dict) else None
    if not isinstance(raw, list) or not raw:
        raise ValueError("KB topic registry must contain a non-empty topics list")
    specs: List[TopicSpec] = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("KB topic registry row must be an object")
        topic_id = item.get("id")
        scope = item.get("scope")
        if not isinstance(topic_id, str) or not topic_id.strip():
            raise ValueError("KB topic registry row is missing id")
        topic_id = topic_id.strip()
        if not isinstance(scope, str) or not scope.strip():
            raise ValueError(f"KB topic {topic_id!r} is missing scope")
        if topic_id in seen:
            raise ValueError(f"KB topic registry duplicates id {topic_id!r}")
        map_item = item.get("map_item", None)
        if "map_item" in item and map_item is None:
            raise ValueError(f"KB topic {topic_id!r} map_item must be an integer")
        if map_item is not None and not isinstance(map_item, int):
            raise ValueError(f"KB topic {topic_id!r} map_item must be an integer")
        seen.add(topic_id)
        specs.append(TopicSpec(id=topic_id, scope=scope.strip(), map_item=map_item))
    return specs


def _parse_topics(
        entry_id: str,
        payload: Mapping[str, Any],
        registered: AbstractSet[str],
) -> List[str]:
    """读取 topics。必须是 1 个已注册主题，最多再加 1 个不同的副主题。"""

    if "topics" not in payload or payload.get("topics") is None:
        raise ValueError(f"KB entry {entry_id!r} is missing topics")
    raw = payload.get("topics")
    if not isinstance(raw, list) or not 1 <= len(raw) <= 2:
        raise ValueError(
            f"KB entry {entry_id!r} topics must be a list of 1 or 2 registered topic ids"
        )
    parsed: List[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"KB entry {entry_id!r} has an invalid topic {item!r}")
        topic = item.strip()
        if topic not in registered:
            raise ValueError(f"KB entry {entry_id!r} has unknown topic {topic!r}")
        if topic in parsed:
            raise ValueError(f"KB entry {entry_id!r} repeats topic {topic!r}")
        parsed.append(topic)
    return parsed


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
    ``topics`` 为 1 个已注册主题，最多再加 1 个副主题。适配器条目为空列表。
    ``manual_anchor`` 不参与选题。
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
    topics: List[str] = field(default_factory=list)
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
            "topics": list(self.topics),
            "manual_anchor": self.manual_anchor,
            "relations": [dict(item) for item in self.relations],
            "score": self.score,
            "kernel_doc_zh": self.kernel_doc_zh,
        }


class KnowledgeBase:
    """从 ``qteasy_ai/kb/*.json`` 加载策展条目。

    无模型检索先查 compile 问句目录，命中则定条；未命中再在胜出的 type 桶内检索。
    主题注册表与 ``topics`` 供有 Provider 时定主题、点卡，不改变这条无模型路径。

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
        self._topic_specs: List[TopicSpec] = load_topic_registry(
            self.kb_dir / "_source" / "topic_registry.json"
        )
        self._registered_topics = {spec.id for spec in self._topic_specs}
        self._entries: List[KbEntry] = self._load_entries()
        self._by_id: Dict[str, KbEntry] = {entry.id: entry for entry in self._entries}
        self._question_catalog: Dict[str, str] = self._load_question_catalog()

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
                    topics=_parse_topics(entry_id, payload, self._registered_topics),
                    manual_anchor=_parse_manual_anchor(entry_id, payload),
                    relations=_parse_relations(entry_id, payload),
                )
            )
        return entries

    def _load_question_catalog(self) -> Dict[str, str]:
        """加载 compile 生成的问句目录。文件不存在时目录为空。"""

        path = self.kb_dir / "_generated" / "question_catalog.json"
        if not path.is_file():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw = payload.get("questions", {})
        if not isinstance(raw, dict):
            raise ValueError("KB question catalog 'questions' must be an object")
        catalog: Dict[str, str] = {}
        for key, entry_id in raw.items():
            if not isinstance(key, str) or not isinstance(entry_id, str) or not entry_id:
                raise ValueError("KB question catalog has an invalid question mapping")
            catalog[key] = entry_id
        return catalog

    def topic_specs(self) -> List[TopicSpec]:
        """当前主题注册表，顺序与文件一致。"""

        return list(self._topic_specs)

    def menu_for_topics(self, topic_ids: Sequence[str]) -> List[KbEntry]:
        """命中主题下的卡片。副主题的卡会出现在两个菜单里。

        Parameters
        ----------
        topic_ids : sequence of str
            已选定的主题 id。

        Returns
        -------
        list of KbEntry
            加载顺序中、topics 与 ``topic_ids`` 有交集的条目。
        """

        wanted = {topic_id for topic_id in topic_ids if topic_id}
        if not wanted:
            return []
        return [entry for entry in self._entries if wanted.intersection(entry.topics)]

    def validate_card_ids(self, menu: Sequence[KbEntry], raw_ids: Sequence[str]) -> List[KbEntry]:
        """按返回顺序保留菜单内的卡，以及这些卡的深度 1 邻居。

        邻居包括菜单卡的出边 ``to``，以及指向菜单卡的入边来源。不沿边再爬。
        菜单外且不是这些邻居的 id 丢掉。邻居不在已加载条目里也丢掉。

        Parameters
        ----------
        menu : sequence of KbEntry
            当前主题菜单。
        raw_ids : sequence of str
            模型返回的 id，调用方已限制为 1～3 个字符串。

        Returns
        -------
        list of KbEntry
            校验后的条目。可能为空。
        """

        menu_ids = {entry.id for entry in menu}
        selected_menu: List[str] = []
        for card_id in raw_ids:
            if card_id in menu_ids and card_id not in selected_menu:
                selected_menu.append(card_id)
        neighbors = self._depth1_neighbor_ids(selected_menu)
        accepted: List[str] = []
        for card_id in raw_ids:
            if card_id in accepted:
                continue
            if card_id not in self._by_id:
                continue
            if card_id in menu_ids or card_id in neighbors:
                accepted.append(card_id)
        return [self._clone_scored(self._by_id[card_id], 0.0) for card_id in accepted]

    def _depth1_neighbor_ids(self, selected_menu_ids: Sequence[str]) -> set:
        """已选菜单卡的一跳邻居，不含这些卡自身。"""

        selected = set(selected_menu_ids)
        if not selected:
            return set()
        neighbors = set()
        for entry in self._entries:
            targets = [item["to"] for item in entry.relations]
            if entry.id in selected:
                for target in targets:
                    if target not in selected and target in self._by_id:
                        neighbors.add(target)
            elif any(target in selected for target in targets):
                neighbors.add(entry.id)
        return neighbors

    @staticmethod
    def prefer_exclusive(hits: Sequence[KbEntry]) -> List[KbEntry]:
        """trap 或 boundary 被点中时只留那一类，不与概念卡拌在一起。

        两类同时出现时，只留先出现的那一类。

        Parameters
        ----------
        hits : sequence of KbEntry
            校验后的选中卡。

        Returns
        -------
        list of KbEntry
            交给作家的卡片。
        """

        chosen = ""
        for item in hits:
            if item.type in _EXCLUSIVE_ENTRY_TYPES:
                chosen = item.type
                break
        if not chosen:
            return list(hits)
        return [item for item in hits if item.type == chosen]

    @staticmethod
    def _clone_scored(entry: KbEntry, score: float) -> KbEntry:
        """复制一条命中并写上分数。"""

        return KbEntry(
            id=entry.id,
            title=entry.title,
            summary=entry.summary,
            narrative=entry.narrative,
            python_code=entry.python_code,
            risk_notes=entry.risk_notes,
            tags=list(entry.tags),
            keywords=list(entry.keywords),
            type=entry.type,
            topics=list(entry.topics),
            manual_anchor=entry.manual_anchor,
            relations=[dict(item) for item in entry.relations],
            score=score,
            kernel_doc_zh=entry.kernel_doc_zh,
        )

    def retrieve(self, query: str, *, limit: int = 3) -> List[KbEntry]:
        """先查问句目录，未命中再在胜出的 type 桶内按关键词与 tag 检索。

        规范化问句若在 compile 目录中，只返回该条，不再打分，也不并入
        ``strategy_meta``。未命中时，各 type 桶分别打分，只保留最高分桶；
        同分时 trap、boundary、pointer、concept 依次优先。半高分地板与
        ``limit`` 作用在该桶上。``strategy_meta`` 不占 type 桶，仅在抽出
        具体策略 id 或问句明确列出内置策略时并入，再一起套地板。

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
        catalog_id = self._question_catalog.get(normalize_question(q))
        if catalog_id:
            catalog_entry = self._by_id.get(catalog_id)
            if catalog_entry is not None:
                return [self._clone_scored(catalog_entry, _CATALOG_HIT_SCORE)]
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
                topics=list(entry.topics),
                manual_anchor=entry.manual_anchor,
                relations=[dict(item) for item in entry.relations],
                score=score,
                kernel_doc_zh=entry.kernel_doc_zh,
            )
            scored.append(hit)
        winner = self._winning_type(scored)
        if winner is None:
            scored = []
        else:
            scored = [item for item in scored if item.type == winner]
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
    def _winning_type(scored: List[KbEntry]) -> Optional[str]:
        """取得分最高的 type。同分时 trap 优先于 boundary、pointer、concept。"""

        best: Dict[str, float] = {}
        for item in scored:
            previous = best.get(item.type)
            if previous is None or item.score > previous:
                best[item.type] = item.score
        if not best:
            return None
        return min(
            best,
            key=lambda entry_type: (-best[entry_type], _TYPE_TIE_RANK.get(entry_type, 9)),
        )

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

    @staticmethod
    def _is_list_builtins(query: str) -> bool:
        """问句是否明确要求列出内置策略。泛词「策略」不算。"""

        return bool(_LIST_BUILTINS_RE.search(query or ""))

    def _maybe_strategy_meta(self, query: str) -> Optional[KbEntry]:
        """抽出具体策略 id，或问句明确列出内置策略时，从内置 API 组装条目。"""

        list_requested = self._is_list_builtins(query)
        list_func = self._resolve_list_func()
        doc_func = self._resolve_doc_func()
        if list_func is None:
            return None
        try:
            names = [str(item) for item in list(list_func())]
        except Exception:
            return None
        strategy_id = self._extract_strategy_id(query=query, names=names)
        if not strategy_id and not list_requested:
            return None
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
            topics=[],
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
        """按词边界抽出已知策略 ID，避免短 id 嵌进别的单词。"""

        q_lower = query.lower()
        for name in sorted(names, key=len, reverse=True):
            key = name.lower()
            if not key:
                continue
            pattern = r"(?<![a-z0-9_])" + re.escape(key) + r"(?![a-z0-9_])"
            if re.search(pattern, q_lower):
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
