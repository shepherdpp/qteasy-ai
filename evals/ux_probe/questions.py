# coding=utf-8
# ======================================
# File: questions.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-07
# Desc:
# UX Probe 提问风格：标准原题，或按画像生成新主题系列。
# ======================================

"""体验罗盘的两种提问风格。

标准风格复用任务 YAML 里的原句。随机风格先从官方主题表抽一个
与该任务标准题错开的主题，再按画像口吻连问，系列中可带入另一个主题。
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from qteasy_ai.provider import BaseLLMProvider

from .loader import Persona, Task

QUESTION_STYLE_STANDARD = "standard"
QUESTION_STYLE_RANDOM = "random"
QUESTION_STYLES = (QUESTION_STYLE_STANDARD, QUESTION_STYLE_RANDOM)

_DEFAULT_TOPIC_REGISTRY = (
    Path(__file__).resolve().parents[2]
    / "qteasy_ai"
    / "kb"
    / "_source"
    / "topic_registry.json"
)
_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True)
class TopicFocus:
    """随机风格一次会话抽中的主主题与可带入的第二主题。"""

    primary_id: str
    primary_scope: str
    extra_id: str
    extra_scope: str


@dataclass
class RandomSeries:
    """随机风格在多轮之间积累的主题与目的。"""

    focus: TopicFocus
    theme: str = ""
    goal: str = ""
    topics: List[Dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.topics:
            self.topics = [
                {"id": self.focus.primary_id, "scope": self.focus.primary_scope},
                {"id": self.focus.extra_id, "scope": self.focus.extra_scope},
            ]


def normalize_question_style(value: Optional[str]) -> str:
    """把风格收成 ``standard`` 或 ``random``。

    Parameters
    ----------
    value : str, optional
        调用方传入的风格。空值视为标准风格。

    Returns
    -------
    str
        ``standard`` 或 ``random``。

    Raises
    ------
    ValueError
        风格无法识别。
    """

    key = str(value or QUESTION_STYLE_STANDARD).strip().lower()
    if key in {"", QUESTION_STYLE_STANDARD, "std"}:
        return QUESTION_STYLE_STANDARD
    if key in {QUESTION_STYLE_RANDOM, "rand"}:
        return QUESTION_STYLE_RANDOM
    raise ValueError(
        f"Unknown question style: {value}. Use standard or random."
    )


def load_topic_catalog(path: Optional[Path] = None) -> List[Dict[str, str]]:
    """读取官方主题 id 与 scope。

    Parameters
    ----------
    path : Path, optional
        主题表 JSON。默认用官方 ``topic_registry.json``。

    Returns
    -------
    list of dict
        每项含 ``id`` 与 ``scope``。
    """

    target = Path(path) if path is not None else _DEFAULT_TOPIC_REGISTRY
    payload = json.loads(target.read_text(encoding="utf-8"))
    catalog: List[Dict[str, str]] = []
    for row in payload.get("topics") or []:
        if not isinstance(row, Mapping):
            continue
        topic_id = str(row.get("id") or "").strip()
        scope = str(row.get("scope") or "").strip()
        if topic_id and scope:
            catalog.append({"id": topic_id, "scope": scope})
    if len(catalog) < 2:
        raise ValueError("topic catalog needs at least 2 topics")
    return catalog


def assign_focuses(
    catalog: Sequence[Mapping[str, str]],
    avoid_sets: Sequence[Sequence[str]],
    rng: random.Random,
) -> List[TopicFocus]:
    """为每个任务抽一个主主题，并再配一个不同的第二主题。

    主主题尽量避开该任务的 ``random_avoid_topics``，也尽量不与本轮
    其他任务的主主题重复。第二主题只要求与主主题不同。

    Parameters
    ----------
    catalog : sequence of mapping
        主题表，每项含 ``id`` 与 ``scope``。
    avoid_sets : sequence of sequence of str
        与任务顺序对齐的回避主题 id。
    rng : random.Random
        本次运行的随机源。

    Returns
    -------
    list of TopicFocus
    """

    items = [
        {"id": str(row["id"]), "scope": str(row["scope"])}
        for row in catalog
        if str(row.get("id") or "").strip() and str(row.get("scope") or "").strip()
    ]
    if len(items) < 2:
        raise ValueError("topic catalog needs at least 2 topics")
    order = list(items)
    rng.shuffle(order)
    used_primary: set = set()
    focuses: List[TopicFocus] = []
    for avoid in avoid_sets:
        banned = {str(item) for item in avoid}
        pool = [
            row for row in order
            if row["id"] not in banned and row["id"] not in used_primary
        ]
        if not pool:
            pool = [row for row in order if row["id"] not in used_primary] or list(order)
        primary = pool[0]
        used_primary.add(primary["id"])
        extra_pool = [row for row in order if row["id"] != primary["id"]]
        extra = extra_pool[0]
        focuses.append(
            TopicFocus(
                primary_id=primary["id"],
                primary_scope=primary["scope"],
                extra_id=extra["id"],
                extra_scope=extra["scope"],
            )
        )
    return focuses


def _extract_json(text: str) -> Dict[str, Any]:
    """从模型回复中抽出一个 JSON 对象。"""

    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass
    match = _JSON_BLOCK.search(raw)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_text(text: str) -> str:
    """比较用：去掉空白。"""

    return re.sub(r"\s+", "", str(text or "")).strip()


def _scripted_texts(task: Task) -> List[str]:
    """任务 YAML 里写死的用户原句。"""

    return [turn.text.strip() for turn in task.turns if turn.text.strip()]


def _copies_script(text: str, scripted: Sequence[str]) -> bool:
    """是否与某一句标准题完全相同。"""

    key = _normalize_text(text)
    if not key:
        return False
    return any(key == _normalize_text(item) for item in scripted)


def _fallback_question(
    persona: Persona,
    series: RandomSeries,
    turn_index: int,
    turn_count: int,
) -> str:
    """模型没给出可用问句时，按画像口吻兜底。"""

    theme = series.theme or series.focus.primary_scope
    extra = series.focus.extra_scope
    last = turn_index >= max(turn_count - 1, 0)
    if persona.plain_language_default or persona.comprehension == "beginner":
        if turn_index == 0:
            return f"我是外行。请用大白话讲讲：{theme}。先别给代码。"
        if last:
            return "我还是有点怕：按你刚才说的做，会不会替我真的去下单？用大白话说。"
        return f"那「{extra}」跟刚才说的有什么关系？还是用大白话。"
    if persona.comprehension == "advanced":
        if turn_index == 0:
            return f"请核对这个机制：{theme}。请说明边界，不要编造数字。"
        if last:
            return (
                f"如果知识片段没写清，就直说。我想确认「{extra}」"
                "和前面的机制是不是同一层。"
            )
        return f"把「{extra}」和刚才的机制放在一起，指出它们各自的边界。"
    if turn_index == 0:
        return f"用能落地的说法讲讲：{theme}。我半懂，别写成论文。"
    if last:
        return f"如果我要自己做，Ask 能帮到哪一步？「{extra}」呢？别替我确认执行。"
    return f"接着说「{extra}」，跟刚才的差别用一句话讲清。"


def _persona_block(persona: Persona, task: Task) -> str:
    """模拟用户提示里的画像段。"""

    scripted = _scripted_texts(task)
    banned = "\n".join(f"- {line}" for line in scripted) or "- (none)"
    return (
        f"Persona name: {persona.display_name}\n"
        f"Role: {persona.role}\n"
        f"Language style: {persona.language_style}\n"
        f"Comprehension: {persona.comprehension}\n"
        f"Preferences: {persona.preferences}\n"
        f"Learning goals (tone only, not the theme): {persona.learning_goals}\n"
        f"Taboos: {persona.taboos}\n"
        "Do not copy or lightly reuse these standard questions:\n"
        f"{banned}\n"
    )


def _opening_prompts(
    persona: Persona,
    task: Task,
    series: RandomSeries,
    turn_count: int,
) -> tuple:
    """第一轮：定主题，并写出第一句问话。"""

    system = (
        "You role-play one end user about to talk to qteasy-ai Ask. "
        "Stay in character. Output ONLY one JSON object with keys "
        "theme, goal, and text. No markdown fences. "
        "theme is one short Chinese sentence naming this run's subject. "
        "goal is one Chinese sentence describing what this series of questions "
        "is trying to understand. text is the first user message in Chinese. "
        "Do not ask for stock tips, guaranteed profits, or live order placement."
    )
    user = (
        _persona_block(persona, task)
        + f"Primary topic id: {series.focus.primary_id}\n"
        + f"Primary topic scope (this MUST be the theme): {series.focus.primary_scope}\n"
        + f"Extra topic id: {series.focus.extra_id}\n"
        + f"Extra topic scope (later turns may also touch this): {series.focus.extra_scope}\n"
        + f"This series will have {turn_count} user turns. Write only turn 1 now.\n"
        "The theme must follow the primary scope, not the persona's usual script.\n"
        "Write the JSON object now."
    )
    return system, user


def format_prior_turns(prior_turns: Sequence[Mapping[str, Any]]) -> str:
    """把已发生的问答写成追问提示。上一答全文进入提示。

    Parameters
    ----------
    prior_turns : sequence of mapping
        每轮含 ``query`` 与 ``answer``。

    Returns
    -------
    str
        ``USER`` / ``ASSISTANT`` 行。没有历史时为 ``(none)``。
    """

    lines: List[str] = []
    for item in prior_turns:
        lines.append(f"USER: {item.get('query')}")
        lines.append(f"ASSISTANT: {str(item.get('answer') or '')}")
    return "\n".join(lines) if lines else "(none)"


def _followup_prompts(
    persona: Persona,
    task: Task,
    series: RandomSeries,
    turn_index: int,
    turn_count: int,
    prior_turns: Sequence[Mapping[str, Any]],
) -> tuple:
    """后续轮：接着上一答，仍围绕本轮主题。"""

    system = (
        "You role-play one end user talking to qteasy-ai Ask. "
        "Stay in character. Output ONLY the next user message in Chinese. "
        "No markdown fences, no JSON. "
        "Do not ask for stock tips, guaranteed profits, or live order placement."
    )
    last = turn_index >= turn_count - 1
    if last:
        step = (
            "This is the last turn. Ask the one remaining confusion or the "
            "boundary this persona cares about."
        )
    else:
        step = (
            "Follow up on the assistant's last answer. Stay on the theme. "
            "If the extra topic is not in the conversation yet, bring it in."
        )
    user = (
        _persona_block(persona, task)
        + f"Theme for this run: {series.theme or series.focus.primary_scope}\n"
        + f"Series goal: {series.goal}\n"
        + f"Primary scope: {series.focus.primary_scope}\n"
        + f"Extra scope: {series.focus.extra_scope}\n"
        + f"Turn {turn_index + 1} of {turn_count}. {step}\n"
        + "Prior turns:\n"
        + format_prior_turns(prior_turns)
        + "\nWrite the next user utterance now."
    )
    return system, user


def random_user_utterance(
    provider: BaseLLMProvider,
    *,
    persona: Persona,
    task: Task,
    series: RandomSeries,
    turn_index: int,
    turn_count: int,
    prior_turns: Sequence[Mapping[str, Any]],
) -> str:
    """生成随机风格的下一句用户问话。

    第一轮同时写下本轮 ``theme`` 与 ``goal``。问句若空、或与标准题相同，
    改用画像口吻的兜底句。

    Parameters
    ----------
    provider : BaseLLMProvider
        模拟用户的模型。不要求与被测 Ask 分开。
    persona, task, series
        画像、原任务（用于避开标准题）和本轮抽中的主题。
    turn_index, turn_count : int
        从 0 起的轮次，以及本任务的总轮数。
    prior_turns : sequence of mapping
        已经发生的问与答。

    Returns
    -------
    str
        下一句用户问话。
    """

    scripted = _scripted_texts(task)
    if turn_index <= 0:
        system, user = _opening_prompts(persona, task, series, turn_count)
        raw = str(provider.chat(user, system_prompt=system) or "")
        payload = _extract_json(raw)
        theme = str(payload.get("theme") or "").strip()
        goal = str(payload.get("goal") or "").strip()
        text = str(payload.get("text") or "").strip()
        if theme:
            series.theme = theme
        if goal:
            series.goal = goal
        if not series.theme:
            series.theme = series.focus.primary_scope
        if not series.goal:
            series.goal = f"按画像口吻搞懂：{series.theme}"
    else:
        system, user = _followup_prompts(
            persona, task, series, turn_index, turn_count, prior_turns,
        )
        raw = str(provider.chat(user, system_prompt=system) or "").strip()
        payload = _extract_json(raw)
        text = str(payload.get("text") or "").strip() if payload.get("text") else raw
        if text.startswith("{") and payload:
            text = str(payload.get("text") or "").strip()
    if _copies_script(text, scripted) or not str(text or "").strip():
        text = _fallback_question(persona, series, turn_index, turn_count)
    return str(text).strip()
