# coding=utf-8
# ======================================
# File: ask_engine.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-28
# Desc:
# qteasy-ai Ask 目标态引擎：无模型走目录检索；
# 有 Provider 时定主题、点卡，再让作家只读选中正文。
# ======================================

"""Ask 目标态问答引擎。

只依赖 KnowledgeBase 与可选 LLM Provider。不生成可执行 ToolPlan step，
不调用 PlanExecutor，不调用 SkillRegistry handler。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .knowledge_base import KbEntry, KnowledgeBase
from .provider import BaseLLMProvider

_ASK_SYSTEM_PROMPT = (
    "You are a qteasy expert. Answer ONLY using the provided knowledge snippets. "
    "Reply in the same language as the user's Question "
    "(Chinese question → Chinese answer; English question → English answer). "
    "Keep qteasy identifiers, skill names, and code unchanged. "
    "If the snippets are insufficient, say so and suggest Plan mode."
)

_TOPIC_SYSTEM_PROMPT = (
    "You select topics for a qteasy Ask question. "
    "Reply with one JSON object and no other text. "
    "When choosing topics, use only topic ids from the registry. "
    "When naming earlier turns, use only turns and source ids from the history index."
)
_NEEDS_PROVIDER_MESSAGE = (
    "Follow-up questions, references to earlier turns, and relations need a configured language model. "
    "Without a provider, Ask only answers a self-contained question."
)

_CARD_SYSTEM_PROMPT = (
    "You select knowledge cards for a qteasy Ask question. "
    "Reply with one JSON object and no other text. "
    "Use only ids from the menu, or a depth-1 neighbor of a menu card you also select."
)

_COMPOSE_CLAUSES = {
    "contrast": (
        "Composition contrast: organize the answer as a contrast between the linked cards."
    ),
}
_NO_CURATED_RELATION = (
    "No curated relation links these cards. "
    "Answer only the selected cards and say that there is no curated relation (没有策展关联)."
)
def _topic_value(topic_ids: Sequence[str]) -> Any:
    """一个主题写成字符串，多个主题保持注册表顺序的列表。"""

    if len(topic_ids) == 1:
        return topic_ids[0]
    return list(topic_ids)


def _json_object(raw: str) -> Optional[Dict[str, Any]]:
    """整段文本必须是一个 JSON 对象。围栏或散文算非法。"""

    text = (raw or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


@dataclass(frozen=True)
class AskHistoryCard:
    """成功 Ask 的一张卡片。原话和答文只在点名之后进入点卡提示。"""

    turn: int
    kind: str
    card_id: str
    title: str
    summary: str
    user_text: str
    answer_text: str


def build_ask_history_index(
        messages: Sequence[Mapping[str, Any]],
        knowledge_base: KnowledgeBase,
) -> List[AskHistoryCard]:
    """从 ``messages[]`` 现算成功 Ask 的一句话索引。

    只看 ``kind=ask`` 且 ``sources`` 非空的卡。失败的 NOT_FOUND、
    ``plan_ready`` / ``clarify`` / ``result`` 不占轮次。库里已经没有的 id 跳过。
    不读 session 对象。

    Parameters
    ----------
    messages : sequence of mapping
        会话消息。当前这句若还没有 Ask 卡，不会进入索引。
    knowledge_base : KnowledgeBase
        用来取标题和 ``summary``。

    Returns
    -------
    list of AskHistoryCard
        轮次从 1 编号。同一轮多张卡共用用户原话和当时的答文。
    """

    cards: List[AskHistoryCard] = []
    turn = 0
    last_user = ""
    for row in messages or []:
        if not isinstance(row, Mapping):
            continue
        kind = str(row.get("kind") or "")
        if kind == "user_text":
            last_user = str(row.get("text") or "")
            continue
        if kind != "ask":
            continue
        payload = row.get("payload") if isinstance(row.get("payload"), Mapping) else {}
        sources = payload.get("sources") if isinstance(payload, Mapping) else None
        if not isinstance(sources, list):
            continue
        rows_for_turn: List[AskHistoryCard] = []
        seen_ids = set()
        for raw_id in sources:
            card_id = str(raw_id or "").strip()
            if not card_id or card_id in seen_ids:
                continue
            entry = knowledge_base._by_id.get(card_id)
            if entry is None:
                continue
            seen_ids.add(card_id)
            rows_for_turn.append(
                AskHistoryCard(
                    turn=0,
                    kind="ask",
                    card_id=card_id,
                    title=entry.title,
                    summary=entry.summary,
                    user_text=last_user,
                    answer_text=str(row.get("text") or ""),
                )
            )
        if not rows_for_turn:
            continue
        turn += 1
        cards.extend(
            AskHistoryCard(
                turn=turn,
                kind=card.kind,
                card_id=card.card_id,
                title=card.title,
                summary=card.summary,
                user_text=card.user_text,
                answer_text=card.answer_text,
            )
            for card in rows_for_turn
        )
    return cards


def _named_turn_blocks(cards: Sequence[AskHistoryCard]) -> List[AskHistoryCard]:
    """每个被点名的轮次只留一块原话和答文。"""

    blocks: List[AskHistoryCard] = []
    seen = set()
    for card in cards:
        if card.turn in seen:
            continue
        seen.add(card.turn)
        blocks.append(card)
    return blocks


@dataclass
class AskResponse:
    """Ask 目标态结构化响应（不含可执行 plan）。

    Parameters
    ----------
    mode : str
        恒为 ``ask``，保证模式可见。
    ok : bool
        是否成功从 KnowledgeBase 给出答案。
    answer : str
        面向用户的答案。有 Provider 时跟随问句语言；Offline 为英文 KB 模板。
    sources : list of str
        命中的 KB 条目 id。
    narrative : str
        解释层叙事（与 answer 对齐，供 explanation_template 裁剪）。
    python_code : str
        可复现示例代码。
    result_preview : str
        来源与摘要预览。
    raw : dict
        机器可读载荷（命中条目、检索上下文）。
    error : dict, optional
        ``{code, message}``；用户可见 message 为英文。
    """

    mode: str = "ask"
    ok: bool = True
    answer: str = ""
    sources: List[str] = field(default_factory=list)
    narrative: str = ""
    python_code: str = ""
    result_preview: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)
    error: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转为不含 execution / 非空 steps 的字典。"""

        payload: Dict[str, Any] = {
            "mode": self.mode,
            "ok": self.ok,
            "answer": self.answer,
            "sources": list(self.sources),
            "narrative": self.narrative,
            "python_code": self.python_code,
            "result_preview": self.result_preview,
            "raw": dict(self.raw),
            "error": self.error,
        }
        return payload


class AskEngine:
    """Ask 目标态编排：检索 KB，Offline 模板或 LLM 合成。

    Parameters
    ----------
    knowledge_base : KnowledgeBase
        策展知识库。
    provider : BaseLLMProvider, optional
        可选 LLM；缺省走 Offline 模板答案。
    """

    def __init__(
        self,
        *,
        knowledge_base: Optional[KnowledgeBase] = None,
        provider: Optional[BaseLLMProvider] = None,
    ) -> None:
        self.knowledge_base = knowledge_base or KnowledgeBase()
        self.provider = provider

    def ask(
        self,
        query: str,
        *,
        explanation_depth: str = "standard",
        session_context: str = "",
        ask_history: Optional[Sequence[AskHistoryCard]] = None,
    ) -> AskResponse:
        """回答用户问题，不走 plan / skill。

        无 Provider 时只做单句检索，不读历史正文。有 Provider 时不把目录当第一跳：
        定主题、在主题菜单里点卡，作家只读通过校验的正文。已有成功 Ask 时，
        定主题提示只加一句话索引；模型点名轮次后，那些轮次的原话和答文才进入点卡。

        Parameters
        ----------
        query : str
            自然语言问题。
        explanation_depth : {'brief', 'standard', 'deep'}, default 'standard'
            解释层深度；C1 先生成完整通道，深度裁剪由 explanation_template 负责。
        session_context : str, optional
            已确认的 session 槽位文本，只附在作家 prompt 上。
        ask_history : sequence of AskHistoryCard, optional
            调用方从 ``messages[]`` 现算的成功 Ask 索引。本方法不读 session。

        Returns
        -------
        AskResponse
            模式为 ask 的结构化答案。有 Provider 且选题成功时，``raw['ask_focus']``
            含本轮 ``topic`` / ``menu_item`` / ``sources``，供查看，不进入提示。
        """

        text = (query or "").strip()
        depth = explanation_depth if explanation_depth in {"brief", "standard", "deep"} else "standard"
        history = list(ask_history or [])
        if not text:
            return self._not_found(query=text, depth=depth)
        topic_ids: List[str] = []
        if self.provider is None:
            hits = self.knowledge_base.retrieve(text)
            if not hits and history:
                return self._not_found_needs_provider(query=text, depth=depth)
        else:
            hits, topic_ids = self._select_with_provider(text, history)
        if not hits:
            return self._not_found(query=text, depth=depth)

        sources = [item.id for item in hits]
        if self.provider is not None:
            menu_ids = [
                entry.id for entry in self.knowledge_base.menu_for_topics(topic_ids)
            ]
            answer = self._ask_llm(
                query=text,
                hits=hits,
                session_context=session_context,
                menu_ids=menu_ids,
            )
        else:
            answer = self._offline_answer(hits)
            if session_context:
                answer = f"{answer}\n\nSession slots: {session_context}"
        extra: Dict[str, Any] = {}
        if session_context:
            extra["session_context"] = session_context
        if topic_ids:
            extra["ask_focus"] = self._ask_focus_payload(topic_ids, sources)
        return self._pack(
            query=text,
            answer=answer,
            hits=hits,
            sources=sources,
            depth=depth,
            ok=True,
            error=None,
            extra_raw=extra or None,
        )

    def _select_with_provider(
            self,
            query: str,
            history: Sequence[AskHistoryCard],
    ) -> Tuple[List[KbEntry], List[str]]:
        """定主题、点卡、校验。失败时不调用作家。

        Returns
        -------
        tuple
            选中的条目，以及本轮主题 id。失败时两者都空。
        """

        resolved = self._resolve_topics(query, history)
        if resolved is None:
            return [], []
        topic_ids, named = resolved
        if not topic_ids:
            return [], []
        menu = self.knowledge_base.menu_for_topics(topic_ids)
        if not menu:
            return [], []
        card_raw = self.provider.chat(
            self._card_user_prompt(query, menu, named_cards=named),
            system_prompt=_CARD_SYSTEM_PROMPT,
        )
        raw_ids = self._parse_ids_reply(str(card_raw))
        if raw_ids is None:
            return [], []
        menu_ids = {entry.id for entry in menu}
        accepted = self.knowledge_base.validate_card_ids(menu, raw_ids)
        primaries = [entry for entry in accepted if entry.id in menu_ids]
        primaries = self.knowledge_base.prefer_exclusive(primaries)
        if not primaries:
            return [], []
        meta = self.knowledge_base._maybe_strategy_meta(query)
        if meta is not None:
            primaries = list(primaries) + [meta]
        return primaries, topic_ids

    def _resolve_topics(
            self,
            query: str,
            history: Sequence[AskHistoryCard],
    ) -> Optional[Tuple[List[str], List[AskHistoryCard]]]:
        """定主题。有历史时由模型 JSON 决定新问题或点名轮次。

        Returns
        -------
        tuple or None
            主题 id，以及被点名的卡片。新问题时卡片列表为空。失败时为 ``None``。
        """

        topic_raw = self.provider.chat(
            self._topic_user_prompt(query, history),
            system_prompt=_TOPIC_SYSTEM_PROMPT,
        )
        payload = _json_object(str(topic_raw))
        if payload is None or payload.get("uncertain") is True:
            return None
        has_topics = "topics" in payload
        has_prior = "prior" in payload
        if has_topics and has_prior:
            return None
        if has_prior:
            return self._prior_topics(payload, history)
        topic_ids = self._parse_topics_reply(str(topic_raw))
        if not topic_ids:
            return None
        return topic_ids, []

    def _prior_topics(
            self,
            payload: Mapping[str, Any],
            history: Sequence[AskHistoryCard],
    ) -> Optional[Tuple[List[str], List[AskHistoryCard]]]:
        """校验点名。对不上索引时整单失败，不丢掉坏项再继续。"""

        prior = payload.get("prior")
        if not isinstance(prior, list) or not prior or not history:
            return None
        by_turn: Dict[int, List[AskHistoryCard]] = {}
        for card in history:
            by_turn.setdefault(card.turn, []).append(card)
        chosen: List[AskHistoryCard] = []
        seen_turns = set()
        for item in prior:
            if not isinstance(item, Mapping):
                return None
            turn = item.get("turn")
            sources = item.get("sources")
            if isinstance(turn, bool) or not isinstance(turn, int):
                return None
            if turn in seen_turns or turn not in by_turn:
                return None
            seen_turns.add(turn)
            if not isinstance(sources, list) or not sources:
                return None
            allowed = {card.card_id: card for card in by_turn[turn]}
            picked: List[str] = []
            for raw_id in sources:
                if not isinstance(raw_id, str) or not raw_id.strip():
                    return None
                card_id = raw_id.strip()
                if card_id not in allowed or card_id in picked:
                    return None
                picked.append(card_id)
                chosen.append(allowed[card_id])
        topic_ids: List[str] = []
        for card in chosen:
            entry = self.knowledge_base._by_id.get(card.card_id)
            if entry is None:
                return None
            for topic in entry.topics:
                if topic not in topic_ids:
                    topic_ids.append(topic)
        if not topic_ids:
            return None
        return topic_ids, chosen

    def _ask_focus_payload(self, topic_ids: Sequence[str], sources: Sequence[str]) -> Dict[str, Any]:
        """本轮焦点。多个主题不合并成单一 ``data``。

        Parameters
        ----------
        topic_ids : sequence of str
            本轮选定的主题。
        sources : sequence of str
            本轮 Ask sources。

        Returns
        -------
        dict
            ``topic`` / ``menu_item`` / ``sources``。主题没有共用编号时 ``menu_item`` 为 ``None``。
        """

        return {
            "topic": _topic_value(topic_ids),
            "menu_item": self._shared_menu_item(topic_ids),
            "sources": list(sources),
        }

    def _shared_menu_item(self, topic_ids: Sequence[str]) -> Optional[int]:
        """这些主题若共用同一个 ``map_item``，返回该编号。"""

        specs = {spec.id: spec.map_item for spec in self.knowledge_base.topic_specs()}
        items: List[int] = []
        for topic_id in topic_ids:
            if topic_id not in specs:
                return None
            item = specs[topic_id]
            if not isinstance(item, int):
                return None
            items.append(item)
        if items and all(item == items[0] for item in items):
            return items[0]
        return None

    def _topic_user_prompt(self, query: str, history: Sequence[AskHistoryCard]) -> str:
        """定主题提示：注册表一句话。有历史时再加一句话索引，不放原话和答文。"""

        lines = ["Topic registry:"]
        for spec in self.knowledge_base.topic_specs():
            lines.append(f"- {spec.id}: {spec.scope}")
        if history:
            lines.append("Ask history index:")
            for card in history:
                lines.append(
                    f"- turn {card.turn} kind=ask id={card.card_id} "
                    f"title={card.title} summary={card.summary}"
                )
        lines.append(f"Question: {query}")
        if history:
            lines.append(
                'Reply with JSON only: {"topics": ["<id>"]} using 1 or 2 registry ids, '
                'or {"prior": [{"turn": 1, "sources": ["<id>"]}]} naming only turns and '
                'source ids from the index, or {"uncertain": true}.'
            )
        else:
            lines.append(
                'Reply with JSON only: {"topics": ["<id>"]} using 1 or 2 registry ids, '
                'or {"uncertain": true}.'
            )
        return "\n".join(lines)

    def _card_user_prompt(
            self,
            query: str,
            menu: Sequence[KbEntry],
            named_cards: Optional[Sequence[AskHistoryCard]] = None,
    ) -> str:
        """点卡提示：菜单内 id、标题、摘要，以及边上的 rel / 对方 id / 标题。

        Parameters
        ----------
        query : str
            用户原句。
        menu : sequence of KbEntry
            当前主题菜单。
        named_cards : sequence of AskHistoryCard, optional
            模型点名的卡片。只把这些轮次的原话和当时答文写进提示。
        """

        lines: List[str] = []
        blocks = _named_turn_blocks(named_cards or [])
        if blocks:
            lines.append("Named turns:")
            for card in blocks:
                lines.append(f"turn {card.turn}")
                lines.append(f"User: {card.user_text}")
                lines.append(f"Answer shown: {card.answer_text}")
        lines.append("Cards in the selected topics:")
        for entry in menu:
            lines.append(f"- {entry.id}: {entry.title}. {entry.summary}")
            for edge in self.knowledge_base.incident_edges(entry.id):
                arrow = "->" if edge["direction"] == "out" else "<-"
                lines.append(
                    f"  edge {edge['rel']} {arrow} {edge['other_id']}: {edge['title']}"
                )
        lines.append(f"Question: {query}")
        lines.append(
            'Reply with JSON only: {"ids": ["<id>"]} using 1 to 3 ids from this menu '
            "or a depth-1 neighbor of a selected menu card, "
            'or {"uncertain": true}.'
        )
        return "\n".join(lines)

    def _parse_topics_reply(self, raw: str) -> Optional[List[str]]:
        """解析定主题 JSON。未知主题丢掉；丢掉后为空则失败。"""

        payload = _json_object(raw)
        if payload is None or payload.get("uncertain") is True:
            return None
        topics = payload.get("topics")
        if not isinstance(topics, list) or not 1 <= len(topics) <= 2:
            return None
        if not all(isinstance(item, str) and item.strip() for item in topics):
            return None
        registered = {spec.id for spec in self.knowledge_base.topic_specs()}
        kept: List[str] = []
        for item in topics:
            topic = item.strip()
            if topic in registered and topic not in kept:
                kept.append(topic)
        if not kept:
            return None
        return kept

    def _parse_ids_reply(self, raw: str) -> Optional[List[str]]:
        """解析点卡 JSON。原始列表必须是 1～3 个非空字符串。"""

        payload = _json_object(raw)
        if payload is None or payload.get("uncertain") is True:
            return None
        raw_ids = payload.get("ids")
        if not isinstance(raw_ids, list) or not 1 <= len(raw_ids) <= 3:
            return None
        if not all(isinstance(item, str) and item.strip() for item in raw_ids):
            return None
        return [item.strip() for item in raw_ids]

    def _not_found(self, *, query: str, depth: str) -> AskResponse:
        """KB 未命中：英文 not_found，建议 Plan，不调用 LLM。"""

        answer = (
            "No matching qteasy knowledge snippet was found for this question. "
            "Ask will not invent an answer from an empty knowledge base. "
            "If you want to list strategies, download data, backtest, or optimize, "
            "use Plan or preview instead of Ask."
        )
        error = {
            "code": "NOT_FOUND",
            "message": "No matching knowledge snippet. Try Plan mode for executable requests.",
        }
        return self._pack(
            query=query,
            answer=answer,
            hits=[],
            sources=[],
            depth=depth,
            ok=False,
            error=error,
        )

    def _not_found_needs_provider(self, *, query: str, depth: str) -> AskResponse:
        """无 Provider 且已有成功 Ask，但本句自己未命中。不读历史正文。"""

        error = {
            "code": "NOT_FOUND",
            "message": _NEEDS_PROVIDER_MESSAGE,
        }
        return self._pack(
            query=query,
            answer=_NEEDS_PROVIDER_MESSAGE,
            hits=[],
            sources=[],
            depth=depth,
            ok=False,
            error=error,
        )

    def _ask_llm(
            self,
            *,
            query: str,
            hits: List[KbEntry],
            session_context: str = "",
            menu_ids: Optional[Sequence[str]] = None,
    ) -> str:
        """将主答卡正文与合编方式注入 prompt 后调用 Provider。"""

        snippets = []
        for item in hits:
            snippets.append(
                f"[{item.id}] {item.title}\n{item.narrative}\npython:\n{item.python_code}"
            )
        context_block = f"\n\nConfirmed session slots: {session_context}\n" if session_context else "\n"
        compose = self._compose_block(hits, menu_ids=menu_ids or [])
        compose_block = f"\n\n{compose}" if compose else ""
        prompt = (
            f"Question: {query}"
            f"{context_block}"
            "Knowledge snippets:\n"
            + "\n\n".join(snippets)
            + compose_block
            + "\n\nWrite a concise answer in the same language as the Question, "
            "grounded in the snippets. "
            "Do not expand a card that is only mentioned as an invitation."
        )
        return str(self.provider.chat(prompt, system_prompt=_ASK_SYSTEM_PROMPT)).strip()

    def _compose_block(
            self,
            hits: Sequence[KbEntry],
            *,
            menu_ids: Sequence[str],
    ) -> str:
        """主答卡之间才整段对比；菜单外的关联只邀请或列举。"""

        menu_set = set(menu_ids)
        primary_ids = [item.id for item in hits if item.id in menu_set]
        lines: List[str] = []
        internal = self.knowledge_base.edges_among(primary_ids)
        seen_pairs = set()
        for edge in internal:
            if edge["rel"] != "contrasts_with":
                continue
            pair = tuple(sorted((edge["fr"], edge["to"])))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            lines.append(
                f"{_COMPOSE_CLAUSES['contrast']} Linked cards: {edge['fr']} -> {edge['to']}."
            )
        if len(primary_ids) >= 2 and not internal:
            lines.append(_NO_CURATED_RELATION)
        for item in self.knowledge_base.external_invitations(primary_ids, menu_ids):
            title = item["title"]
            if item["rel"] == "see_also":
                lines.append(f"Related see_also: {title}. {item['summary']}")
            elif item["rel"] == "plan_handoff":
                lines.append(
                    "Invitation plan_handoff: you can switch to Plan to go further. "
                    "Do not emit plan_id, steps, or a confirmable plan. "
                    f"Related title: {title}."
                )
            else:
                lines.append(
                    f"Invitation: if you want to know more about {title}, you can ask next. "
                    "Do not expand that card in this answer."
                )
        return "\n".join(lines)

    @staticmethod
    def _offline_answer(hits: List[KbEntry]) -> str:
        """无 Provider 时拼接 KB narrative。"""

        parts = [item.narrative.strip() for item in hits if item.narrative.strip()]
        return "\n\n".join(parts)

    def _pack(
        self,
        *,
        query: str,
        answer: str,
        hits: List[KbEntry],
        sources: List[str],
        depth: str,
        ok: bool,
        error: Optional[Dict[str, Any]],
        extra_raw: Optional[Dict[str, Any]] = None,
    ) -> AskResponse:
        """组装 AskResponse；深度裁剪委托 explanation_template。"""

        python_code = next((item.python_code for item in hits if item.python_code), "")
        risk_notes = "\n".join(item.risk_notes for item in hits if item.risk_notes)
        raw: Dict[str, Any] = {
            "query": query,
            "hits": [item.to_dict() for item in hits],
            "explanation_depth": depth,
            "provider_enabled": self.provider is not None,
        }
        if extra_raw:
            raw.update(extra_raw)
        from .explanation import apply_explanation_depth

        rendered = apply_explanation_depth(
            narrative=answer,
            python_code=python_code,
            result_preview=f"sources={sources}" if sources else "No knowledge sources.",
            depth=depth,
            risk_notes=risk_notes,
        )
        return AskResponse(
            mode="ask",
            ok=ok,
            answer=rendered.narrative,
            sources=list(sources),
            narrative=rendered.narrative,
            python_code=rendered.python_code,
            result_preview=rendered.result_preview,
            raw=raw,
            error=error,
        )
