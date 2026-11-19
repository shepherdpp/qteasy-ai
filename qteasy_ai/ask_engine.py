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
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .identity import prefix_system_prompt
from .knowledge_base import KbEntry, KnowledgeBase
from .provider import BaseLLMProvider

_ASK_SYSTEM_PROMPT = (
    "You are a qteasy expert. Answer ONLY using the provided knowledge snippets. "
    "Reply in the same language as the user's Question "
    "(Chinese question → Chinese answer; English question → English answer). "
    "Keep qteasy identifiers, skill names, and code unchanged. "
    "Commonsense risk points may be stated when helpful, but label them as a "
    "general principle, not a handbook entry "
    "(past returns do not guarantee future profit; do not tune and judge on the "
    "same window; do not compare strategies by return alone). "
    "A user-level definition may rephrase only the provided snippets; you may "
    "mark it as a plain explanation with handbook semantics authoritative; "
    "never invent entry names, slots, exception text, or performance numbers "
    "absent from the snippets. "
    "If this turn did not explain the concept the user asked about, do not imply "
    "the concept was already answered (for example by saying they should already "
    "use Ask); capability boundaries remain allowed (concepts in Ask, real runs "
    "in Plan). "
    "Switch to Plan only for actionable requests, not as a closing line for "
    "concept questions. Do not treat assistant.preview as the only next step "
    "for beginners; if the workbench entry card is not selected, say you do not "
    "know where the web buttons are. "
    "If the user numbered several questions, answer each number before any boundary reminder. "
    "State the same boundary, and the same list of what the cards do not say, at most once. "
    "Do not tell the user the words 片段, 策展关联, or 实名指针. "
    "If the user misstates the previous turn, correct it in one plain sentence. "
    "Do not open with 先修正一点. "
    "If the snippets are insufficient, say so and suggest Plan mode."
)

_PLAIN_LANGUAGE_WRITER_CLAUSE = (
    "先人话：优先用日常说法解释；标识符后置或省略，"
    "除非用户明确要看符号或代码。"
    "不要贴出代码块，也不要把 op.set_parameter 这类调用写进正文。"
)
_BACKTEST_OPTIMIZE_OOS_WRITER_CLAUSE = (
    "When a selected card is about backtest or optimize, you may add one "
    "annotated general principle: split history into an earlier window and a "
    "later window and run each once; do not compare by return alone. "
    "Do not invent a cut date, split ratio, or claim a handbook comparison protocol. "
    "Say that principle at most once in the answer."
)

_PLAIN_LANGUAGE_SIGNALS = (
    "不懂代码",
    "外行",
    "我妈能懂",
    "别讲术语",
    "别给代码",
    "别跟我说代码",
    "不要代码",
    "大白话",
    "说人话",
    "讲太复杂",
    "别翻代码",
)
_CONTEXT_TURN_CAP = 4
_OUTLINE_RECENT_TURNS = 2
_CONTEXT_REFERENCE_RE = re.compile(
    r"刚才|前面|之前|上面|上次|你说|earlier|you said|"
    r"第\s*(?:[0-9]+|[一二三四五六七八九十两]+)\s*[条项点]",
    re.IGNORECASE,
)
_ITEM_MENTION_RE = re.compile(
    r"第\s*([0-9]+|[一二三四五六七八九十两]+)\s*[条项点]"
)
_NUMBERED_LINE_RE = re.compile(
    r"^\s*(?:(\d+)|([一二三四五六七八九十两]+))[\.、．]\s*(\S.*?)\s*$"
)
_ZH_DIGIT = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_EARLIER_ANSWER_WRITER_CLAUSE = (
    "The session outline is part of this conversation, including brief lines for older turns. "
    "Use it to resolve references such as 刚才, 之前, 第N条, or a request to repeat an earlier answer. "
    "Do not claim an item is missing when it appears in the outline. "
    "Do not invent the unabridged wording of a turn that is only summarized. "
    "New facts still come from the knowledge snippets."
)

_TOPIC_SYSTEM_PROMPT = (
    "You select topics for a qteasy Ask question. "
    "Reply with one JSON object and no other text. "
    "When choosing topics, use only topic ids from the registry. "
    "When naming earlier turns, use only turns and source ids from the history index. "
    "topics and prior may appear together or alone. "
    "Also set \"plain_language\": true when the user wants plain language or fewer "
    "jargon terms first; listed substrings in the user prompt are reference signals "
    "only, not the only signals—synonyms outside that list still count. "
    "Omit the field or set false when they do not ask for that register. "
    "Do not set plain_language when you reply with {\"uncertain\": true}."
)


def query_requests_plain_language(text: str) -> bool:
    """无 Provider 路径：子串词表是否要求先人话（有 Provider 时不作代码硬门）。"""

    blob = str(text or "")
    if not blob:
        return False
    return any(token in blob for token in _PLAIN_LANGUAGE_SIGNALS)


def query_references_earlier_turn(text: str) -> bool:
    """问句是否像在指代前文。启发式用，允许误伤。"""

    return bool(_CONTEXT_REFERENCE_RE.search(str(text or "")))


def _clip(text: str, limit: int) -> str:
    """按字符截断，并去掉换行，供提纲的短行使用。"""

    body = str(text or "").replace("\n", " ").strip()
    if len(body) <= limit:
        return body
    return body[:limit]


def _zh_item_number(token: str) -> Optional[int]:
    """把「二」「12」「十二」解析成正整数。解析不了则返回 None。"""

    raw = str(token or "").strip()
    if raw.isdigit():
        number = int(raw)
        return number if number >= 1 else None
    if not raw or any(char not in _ZH_DIGIT and char != "十" for char in raw):
        return None
    if raw == "十":
        return 10
    if "十" not in raw:
        if len(raw) == 1 and raw in _ZH_DIGIT:
            return _ZH_DIGIT[raw]
        return None
    left, right = raw.split("十", 1)
    if left == "":
        tens = 1
    elif left in _ZH_DIGIT:
        tens = _ZH_DIGIT[left]
    else:
        return None
    if right == "":
        ones = 0
    elif right in _ZH_DIGIT:
        ones = _ZH_DIGIT[right]
    else:
        return None
    number = tens * 10 + ones
    return number if number >= 1 else None


def _single_numbered_item(query: str) -> Optional[int]:
    """问句里恰好一种「第 N 条/项/点」时返回 N。没有或有多种则不插入子卡。"""

    found = []
    for match in _ITEM_MENTION_RE.finditer(str(query or "")):
        number = _zh_item_number(match.group(1))
        if number is not None:
            found.append(number)
    unique = set(found)
    if len(unique) != 1:
        return None
    return unique.pop()


def _numbered_items(answer: str) -> List[Tuple[str, str]]:
    """抽出答文里的编号行。没有编号的散文不在这里。"""

    items: List[Tuple[str, str]] = []
    for line in str(answer or "").splitlines():
        match = _NUMBERED_LINE_RE.match(line)
        if match is None:
            continue
        token = match.group(1) or match.group(2) or ""
        body = str(match.group(3) or "").strip()
        if token and body:
            items.append((token, body))
    return items


def _full_turn_ids(turns: Sequence[int], promoted: Sequence[int]) -> set:
    """全文名额最多 4 轮：先留给 prior 点名的轮次，再补最近 2 轮。"""

    full: List[int] = []
    for turn in promoted:
        if turn in full or turn not in turns:
            continue
        full.append(turn)
        if len(full) >= _CONTEXT_TURN_CAP:
            return set(full)
    for turn in list(turns)[-_OUTLINE_RECENT_TURNS:]:
        if turn in full:
            continue
        if len(full) >= _CONTEXT_TURN_CAP:
            break
        full.append(turn)
    return set(full)


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_NEEDS_PROVIDER_MESSAGE = (
    "Follow-up questions, references to earlier turns, and relations need a configured language model. "
    "Without a provider, Ask only answers a self-contained question."
)
_NEEDS_PROVIDER_ANSWER_ZH = (
    "追问、指代前文以及关联需要配置大模型。"
    "未配置 Provider 时，Ask 只回答本句就能命中的自足问题。"
)
_NOT_FOUND_MESSAGE = "No matching knowledge snippet. Try Plan mode for executable requests."
_NOT_FOUND_ANSWER_EN = (
    "No matching qteasy knowledge snippet was found for this question. "
    "Ask will not invent an answer from an empty knowledge base. "
    "If you want to list strategies, download data, backtest, or optimize, "
    "use Plan or preview instead of Ask."
)
_NOT_FOUND_ANSWER_ZH = (
    "官方知识库中没有与这个问题匹配的条目。"
    "Ask 不会在空库上编造答案。"
    "若要列出策略、下载数据、回测或优化，请改用 Plan 或 preview。"
)

_CARD_SYSTEM_PROMPT = (
    "You select knowledge cards for a qteasy Ask question. "
    "Reply with one JSON object and no other text. "
    "Use only ids from the menu, or a depth-1 neighbor of a menu card you also select. "
    "When one question covers multiple matters, pick one card per matter you can cover "
    "(still at most 3 ids). If a matter has no matching card, still select cards for the "
    "matters that do; do not reply with {\"uncertain\": true} for the whole question. "
    "If workbench_entry is on the menu and the question asks which web button to click, "
    "select workbench_entry."
)

_COMPOSE_CLAUSES = {
    "contrast": (
        "Composition contrast: organize the answer as a contrast between the linked cards."
    ),
}
_NO_CURATED_RELATION = (
    "No curated relation links these cards. "
    "Answer each selected card on its own. "
    "Do not tell the user the words 策展关联, 片段, or 实名指针."
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
    """成功 Ask 的一张卡片。点卡和作家只在指代或 prior 时看到滚动提纲。"""

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


def _promoted_turns(cards: Sequence[AskHistoryCard]) -> List[int]:
    """prior 点名的轮次，保持点名顺序。"""

    turns: List[int] = []
    for card in cards:
        if card.turn not in turns:
            turns.append(card.turn)
    return turns


def _named_turn_blocks(cards: Sequence[AskHistoryCard]) -> List[AskHistoryCard]:
    """每个轮次只留一块原话和答文。"""

    blocks: List[AskHistoryCard] = []
    seen = set()
    for card in cards:
        if card.turn in seen:
            continue
        seen.add(card.turn)
        blocks.append(card)
    return blocks


def _render_turn_outline(
        block: AskHistoryCard,
        *,
        fidelity: str,
        age: int,
        full: bool,
) -> List[str]:
    """一轮提纲。定主题不放答文全文；点卡和作家近详远略。"""

    items = _numbered_items(block.answer_text)
    if fidelity == "topic":
        lines = [f"turn {block.turn}", f"User: {_clip(block.user_text, 40)}"]
        if not items:
            return lines
        limit = 80 if age < 4 else 24
        lines.append("Items:")
        for token, body in items:
            lines.append(f"{token}. {_clip(body, limit)}")
        return lines
    if full:
        return [
            f"turn {block.turn}",
            f"User: {block.user_text}",
            f"Answer shown: {block.answer_text}",
        ]
    if age <= 3:
        lines = [f"turn {block.turn}", f"User: {_clip(block.user_text, 80)}"]
        shown = items[:12]
        if shown:
            lines.append("Items:")
            for token, body in shown:
                lines.append(f"{token}. {_clip(body, 120)}")
        else:
            lines.append(f"Lead: {_clip(block.answer_text, 200)}")
        return lines
    user = _clip(block.user_text, 40)
    if items:
        bits = "; ".join(f"{token}. {_clip(body, 24)}" for token, body in items)
        return [f"turn {block.turn} | User: {user} | Items: {bits}"]
    return [f"turn {block.turn} | User: {user} | Lead: {_clip(block.answer_text, 60)}"]


def render_session_outline(
        cards: Sequence[AskHistoryCard],
        *,
        fidelity: str,
        promoted_turns: Sequence[int] = (),
) -> str:
    """整段 Session 的滚动提纲。没有轮次时为空串。

    ``fidelity="topic"`` 只放截断的用户原话和编号行。
    ``fidelity="context"`` 给点卡和作家：最近两轮和 prior 点名的轮次可以是全文，
    全文最多 4 轮，更早的轮次改成中等或一行简略。

    Parameters
    ----------
    cards : sequence of AskHistoryCard
        成功 Ask 索引。同一轮多张卡只渲染一次。
    fidelity : {'topic', 'context'}
        定主题用 topic，点卡和作家用 context。
    promoted_turns : sequence of int, optional
        prior 点名的轮次，按列表顺序占用全文名额。

    Returns
    -------
    str
        以 ``Session outline:`` 开头的文本；没有轮次时为空串。
    """

    blocks = _named_turn_blocks(cards)
    if not blocks:
        return ""
    latest = blocks[-1].turn
    turns = [block.turn for block in blocks]
    full_turns = _full_turn_ids(turns, promoted_turns) if fidelity == "context" else set()
    lines = ["Session outline:"]
    for block in blocks:
        lines.extend(
            _render_turn_outline(
                block,
                fidelity=fidelity,
                age=latest - block.turn,
                full=block.turn in full_turns,
            )
        )
    return "\n".join(lines) + "\n\n"


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
        ``{code, message}``；机器可读 message 为英文；用户可见答文在 answer。
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
        self.identity_dir = None

    def ask(
        self,
        query: str,
        *,
        explanation_depth: str = "standard",
        session_context: str = "",
        ask_history: Optional[Sequence[AskHistoryCard]] = None,
        plain_language: bool = False,
    ) -> AskResponse:
        """回答用户问题，不走 plan / skill。

        无 Provider 时只做单句检索，不读历史正文。有 Provider 时不把目录当第一跳：
        定主题、在主题菜单里点卡，作家读通过校验的正文。已有成功 Ask 时，
        定主题提示加一句话索引和滚动提纲，提纲不放答文全文。``topics`` 与 ``prior``
        可单独或同时出现。合法 ``prior`` 或问句像指代时，点卡和作家看到近详远略提纲；
        只有 ``prior`` 时用被点名卡片的主题打开菜单并仍然点卡。只有 ``topics`` 且
        问句不像指代时，点卡和作家不看提纲。问句点名第 N 项且父卡有 ``details`` 时，
        把对应子卡插进命中。
        ``raw['ask_plain_language']`` 仅表示本轮新判定（供 session 粘住）；作家是否
        加降术语条款看 ``plain_language`` 参数或本轮判定。

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
        plain_language : bool, default False
            调用方已粘住的语域布尔；为真时作家提示加先人话条款。

        Returns
        -------
        AskResponse
            模式为 ask 的结构化答案。有 Provider 且选题成功时，``raw['ask_focus']``
            含本轮 ``topic`` / ``menu_item`` / ``sources``，供查看，不进入提示。
        """

        text = (query or "").strip()
        depth = explanation_depth if explanation_depth in {"brief", "standard", "deep"} else "standard"
        history = list(ask_history or [])
        latched_plain = bool(plain_language)
        if not text:
            return self._with_plain_flag(self._not_found(query=text, depth=depth), False)
        topic_ids: List[str] = []
        turn_plain = False
        context_cards: List[AskHistoryCard] = []
        promoted_turns: List[int] = []
        if self.provider is None:
            turn_plain = query_requests_plain_language(text)
            hits = self.knowledge_base.retrieve(text)
            if not hits and history:
                return self._with_plain_flag(
                    self._not_found_needs_provider(query=text, depth=depth),
                    turn_plain,
                )
        else:
            hits, topic_ids, turn_plain, context_cards, promoted_turns = (
                self._select_with_provider(text, history)
            )
        if not hits:
            return self._with_plain_flag(self._not_found(query=text, depth=depth), turn_plain)

        sources = [item.id for item in hits]
        effective_plain = latched_plain or turn_plain
        if self.provider is not None:
            menu_ids = [
                entry.id for entry in self.knowledge_base.menu_for_topics(topic_ids)
            ]
            answer = self._ask_llm(
                query=text,
                hits=hits,
                session_context=session_context,
                menu_ids=menu_ids,
                plain_language=effective_plain,
                context_cards=context_cards,
                promoted_turns=promoted_turns,
            )
        else:
            answer = self._offline_answer(hits)
            if session_context:
                answer = f"{answer}\n\nSession slots: {session_context}"
        extra: Dict[str, Any] = {"ask_plain_language": bool(turn_plain)}
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
            extra_raw=extra,
        )

    def _select_with_provider(
            self,
            query: str,
            history: Sequence[AskHistoryCard],
    ) -> Tuple[List[KbEntry], List[str], bool, List[AskHistoryCard], List[int]]:
        """定主题、点卡、校验。失败时不调用作家。

        Returns
        -------
        tuple
            选中的条目、本轮主题 id、本轮 ``plain_language``、
            要交给点卡和作家的历史卡片、prior 点名的轮次。
            失败时条目、主题、历史和轮次为空，语域为 False。
        """

        resolved = self._resolve_topics(query, history)
        if resolved is None:
            return [], [], False, [], []
        topic_ids, context_cards, promoted, turn_plain = resolved
        if not topic_ids:
            return [], [], False, [], []
        menu = self.knowledge_base.menu_for_topics(topic_ids)
        if not menu:
            return [], [], False, [], []
        card_raw = self.provider.chat(
            self._card_user_prompt(
                query,
                menu,
                context_cards=context_cards,
                promoted_turns=promoted,
            ),
            system_prompt=_CARD_SYSTEM_PROMPT,
        )
        raw_ids = self._parse_ids_reply(str(card_raw))
        if raw_ids is None:
            return [], [], False, [], []
        menu_ids = {entry.id for entry in menu}
        accepted = self.knowledge_base.validate_card_ids(menu, raw_ids)
        primaries = [entry for entry in accepted if entry.id in menu_ids]
        primaries = self.knowledge_base.prefer_exclusive(primaries)
        if not primaries:
            return [], [], False, [], []
        hits = self._with_detail_children(query, primaries)
        meta = self.knowledge_base._maybe_strategy_meta(query)
        if meta is not None:
            hits = list(hits) + [meta]
        return hits, topic_ids, bool(turn_plain), list(context_cards), list(promoted)

    def _resolve_topics(
            self,
            query: str,
            history: Sequence[AskHistoryCard],
    ) -> Optional[Tuple[List[str], List[AskHistoryCard], List[int], bool]]:
        """定主题。``topics`` 与 ``prior`` 可单独或同时出现。

        ``topics`` 有效时菜单听它。合法 ``prior`` 或指代问句把整段历史交给
        点卡和作家做滚动提纲；prior 点名的轮次优先占全文名额。只有合法
        ``prior`` 时，菜单来自被点名卡片的主题。``topics`` 有效但 ``prior``
        缺失或非法时，指代问句仍附提纲，不因此失败。

        Returns
        -------
        tuple or None
            主题 id、上文卡片、prior 点名轮次、``plain_language``。
            失败或 ``uncertain`` 时为 ``None``（不置语域）。
        """

        topic_raw = self.provider.chat(
            self._topic_user_prompt(query, history),
            system_prompt=_TOPIC_SYSTEM_PROMPT,
        )
        payload = _json_object(str(topic_raw))
        if payload is None or payload.get("uncertain") is True:
            return None
        turn_plain = payload.get("plain_language") is True
        topic_ids = (
            self._parse_topics_reply(str(topic_raw)) if "topics" in payload else None
        )
        prior = self._prior_topics(payload, history) if "prior" in payload else None
        history_cards = list(history)
        if topic_ids:
            if prior is not None:
                return topic_ids, history_cards, _promoted_turns(prior[1]), turn_plain
            if query_references_earlier_turn(query):
                return topic_ids, history_cards, [], turn_plain
            return topic_ids, [], [], turn_plain
        if prior is not None:
            prior_topics, prior_cards = prior
            return prior_topics, history_cards, _promoted_turns(prior_cards), turn_plain
        return None

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

    def _detail_child_id(self, parent: KbEntry, item_n: int) -> Optional[str]:
        """父卡上 item 等于 N 的 details 目标。没有或不是一条则不插入。"""

        targets: List[str] = []
        for rel in parent.relations:
            if self.knowledge_base._relation_compose.get(rel["rel"]) != "detail":
                continue
            if rel.get("item") != item_n:
                continue
            target = str(rel.get("to") or "").strip()
            if target and target not in targets:
                targets.append(target)
        if len(targets) != 1:
            return None
        return targets[0]

    def _with_detail_children(self, query: str, hits: Sequence[KbEntry]) -> List[KbEntry]:
        """问句只有一个第 N 项时，把已选父卡的 details 子卡插到父卡后面。

        结果最多 3 张。超出时从末尾丢掉，但不丢掉这对父卡和子卡。
        不沿子卡再爬。问句没有编号，或有两种编号时，不插入。
        """

        item_n = _single_numbered_item(query)
        if item_n is None:
            return list(hits)
        ordered = list(hits)
        protected = set()
        for parent in list(hits):
            child_id = self._detail_child_id(parent, item_n)
            if child_id is None or child_id == parent.id:
                continue
            child = self.knowledge_base._by_id.get(child_id)
            if child is None:
                continue
            protected.add(parent.id)
            protected.add(child_id)
            ordered = [item for item in ordered if item.id != child_id]
            spliced: List[KbEntry] = []
            for item in ordered:
                spliced.append(item)
                if item.id == parent.id:
                    spliced.append(self.knowledge_base._clone_scored(child, 0.0))
            ordered = spliced
        while len(ordered) > 3:
            drop_at = None
            for index in range(len(ordered) - 1, -1, -1):
                if ordered[index].id not in protected:
                    drop_at = index
                    break
            if drop_at is None:
                break
            del ordered[drop_at]
        return ordered

    def _topic_user_prompt(self, query: str, history: Sequence[AskHistoryCard]) -> str:
        """定主题提示：注册表一句话。有历史时再加索引和提纲，提纲不放答文全文。"""

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
            lines.append(render_session_outline(history, fidelity="topic").rstrip("\n"))
        lines.append(
            "Plain-language reference signals (hints only, not required): "
            + "、".join(_PLAIN_LANGUAGE_SIGNALS)
        )
        lines.append(f"Question: {query}")
        lines.append(
            "If the question also asks which web button to click "
            "(点哪个, 按钮, 网页), include onboarding as the second topic."
        )
        if history:
            lines.append(
                "Reply with JSON only. topics and prior may be used alone or together. "
                '{"topics": ["<id>"], "plain_language": true|false} '
                "using 1 or 2 registry ids. "
                'Optionally add "prior": [{"turn": 1, "sources": ["<id>"]}] '
                "when the question refers to earlier answers, naming only turns and "
                "source ids from the index. The session outline is only for resolving "
                "earlier turns and numbered items. "
                "Send prior without topics when there is no new topic and the question "
                "only continues those earlier turns. "
                "Omit prior when the question does not depend on earlier answers. "
                'Or {"uncertain": true}. '
                "plain_language is optional; omit or false when not requested."
            )
        else:
            lines.append(
                'Reply with JSON only: {"topics": ["<id>"], "plain_language": true|false} '
                "using 1 or 2 registry ids, or {\"uncertain\": true}. "
                "plain_language is optional; omit or false when not requested."
            )
        return "\n".join(lines)

    def _card_user_prompt(
            self,
            query: str,
            menu: Sequence[KbEntry],
            context_cards: Optional[Sequence[AskHistoryCard]] = None,
            promoted_turns: Optional[Sequence[int]] = None,
    ) -> str:
        """点卡提示：菜单内 id、标题、摘要，以及边上的 rel / 对方 id / 标题。

        Parameters
        ----------
        query : str
            用户原句。
        menu : sequence of KbEntry
            当前主题菜单。
        context_cards : sequence of AskHistoryCard, optional
            指代或 prior 时的整段历史。渲染成近详远略提纲。
        promoted_turns : sequence of int, optional
            prior 点名的轮次，优先渲染为全文。
        """

        lines: List[str] = []
        outline = render_session_outline(
            context_cards or [],
            fidelity="context",
            promoted_turns=promoted_turns or [],
        )
        if outline:
            lines.append(outline.rstrip("\n"))
            lines.append(
                "Use this session outline together with the question when choosing cards. "
                "Still choose ids only from the menu below."
            )
        lines.append("Cards in the selected topics:")
        for entry in menu:
            lines.append(f"- {entry.id}: {entry.title}. {entry.summary}")
            for edge in self.knowledge_base.incident_edges(entry.id):
                arrow = "->" if edge["direction"] == "out" else "<-"
                item_bit = f" item={edge['item']}" if edge.get("item") else ""
                lines.append(
                    f"  edge {edge['rel']} {arrow} {edge['other_id']}{item_bit}: {edge['title']}"
                )
        lines.append(f"Question: {query}")
        lines.append(
            "When the question expands one numbered item and a details edge lists that item, "
            "include both the parent menu card and that target."
        )
        lines.append(
            "If workbench_entry is on this menu and the question asks which web button to click, "
            "select workbench_entry."
        )
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
        """KB 未命中：静态答文跟问句语言，建议 Plan，不调用 LLM。"""

        answer = _NOT_FOUND_ANSWER_ZH if _CJK_RE.search(str(query or "")) else _NOT_FOUND_ANSWER_EN
        error = {
            "code": "NOT_FOUND",
            "message": _NOT_FOUND_MESSAGE,
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

        answer = (
            _NEEDS_PROVIDER_ANSWER_ZH
            if _CJK_RE.search(str(query or ""))
            else _NEEDS_PROVIDER_MESSAGE
        )
        error = {
            "code": "NOT_FOUND",
            "message": _NEEDS_PROVIDER_MESSAGE,
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

    def _with_plain_flag(self, response: AskResponse, turn_plain: bool) -> AskResponse:
        """把本轮语域判定写入 ``raw``，供 session 粘住；不改已粘住的会话字段。"""

        response.raw["ask_plain_language"] = bool(turn_plain)
        return response

    def _ask_llm(
            self,
            *,
            query: str,
            hits: List[KbEntry],
            session_context: str = "",
            menu_ids: Optional[Sequence[str]] = None,
            plain_language: bool = False,
            context_cards: Optional[Sequence[AskHistoryCard]] = None,
            promoted_turns: Optional[Sequence[int]] = None,
    ) -> str:
        """将主答卡正文、可选提纲与合编方式注入 prompt 后调用 Provider。"""

        snippets = []
        for item in hits:
            snippets.append(
                f"[{item.id}] {item.title}\n{item.narrative}\npython:\n{item.python_code}"
            )
        context_block = f"\n\nConfirmed session slots: {session_context}\n" if session_context else "\n"
        earlier = render_session_outline(
            context_cards or [],
            fidelity="context",
            promoted_turns=promoted_turns or [],
        )
        compose = self._compose_block(hits, menu_ids=menu_ids or [])
        compose_block = f"\n\n{compose}" if compose else ""
        prompt = (
            f"Question: {query}"
            f"{context_block}"
            f"{earlier}"
            "Knowledge snippets:\n"
            + "\n\n".join(snippets)
            + compose_block
            + "\n\nWrite a concise answer in the same language as the Question, "
            "grounded in the snippets. "
            "Do not expand a card that is only mentioned as an invitation."
        )
        system = _ASK_SYSTEM_PROMPT
        if earlier:
            system = f"{system} {_EARLIER_ANSWER_WRITER_CLAUSE}"
        if plain_language:
            system = f"{system} {_PLAIN_LANGUAGE_WRITER_CLAUSE}"
        if any(
            topic in ("backtest", "optimize")
            for item in hits
            for topic in item.topics
        ):
            system = f"{system} {_BACKTEST_OPTIMIZE_OOS_WRITER_CLAUSE}"
        return str(
            self.provider.chat(
                prompt,
                system_prompt=prefix_system_prompt(
                    system,
                    getattr(self, "identity_dir", None),
                ),
            )
        ).strip()

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
        hit_ids = [item.id for item in hits]
        for edge in self.knowledge_base.edges_among(hit_ids):
            if edge.get("compose") != "detail":
                continue
            lines.append(
                f"Detail item {edge['item']} of {edge['fr']} is expanded by {edge['to']}. "
                f"Explain that item from {edge['to']}. "
                f"Do not restate the other items of {edge['fr']}."
            )
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
