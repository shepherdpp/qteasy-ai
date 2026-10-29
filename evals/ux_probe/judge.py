# coding=utf-8
# ======================================
# File: judge.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-29
# Desc:
# UX Probe 无人值守法官（与模拟用户分 system）。
# ======================================

"""对 transcript 打分并产出 friction / suggested_fixes。"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional

from qteasy_ai.provider import BaseLLMProvider

from .loader import Persona, Rubrics, Task

_JSON_BLOCK = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> Dict[str, Any]:
    """从模型回复中抽出 JSON 对象。"""

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


def _rule_red_line_flags(transcript: Mapping[str, Any]) -> List[str]:
    """启发式红线标记（补充法官，不替代）。"""

    flags: List[str] = []
    banned = ("已下单", "去监控", "稳赚", "保证收益", "我帮你确认了")
    for turn in transcript.get("turns") or []:
        answer = str(turn.get("answer") or "")
        for phrase in banned:
            if phrase in answer:
                flags.append(f"assistant_answer_contains:{phrase}")
        if turn.get("plan_id"):
            flags.append("ask_emitted_plan_id")
    return flags


def build_judge_prompt(
    *,
    persona: Persona,
    task: Task,
    transcript: Mapping[str, Any],
    rubrics: Rubrics,
) -> tuple:
    """构造法官 system / user 提示。"""

    dim_lines = []
    for dim in rubrics.dimensions:
        anchors = dim.get("anchors") or {}
        anchor_txt = "; ".join(f"{k}={v}" for k, v in anchors.items())
        dim_lines.append(f"- {dim.get('id')}: {dim.get('label')} | {anchor_txt}")
    system = rubrics.judge_instructions or (
        "Score the Ask transcript. Output JSON only."
    )
    user = (
        f"Persona: {persona.display_name} ({persona.id})\n"
        f"Role: {persona.role}\n"
        f"Language style: {persona.language_style}\n"
        f"Comprehension: {persona.comprehension}\n"
        f"Learning goals: {persona.learning_goals}\n"
        f"Taboos: {persona.taboos}\n"
        f"Task id: {task.id}\n"
        f"Task goal: {task.goal}\n"
        f"Scale: {rubrics.scale_min}-{rubrics.scale_max}\n"
        f"Dimensions:\n" + "\n".join(dim_lines) + "\n\n"
        f"Transcript JSON:\n{json.dumps(transcript, ensure_ascii=False, indent=2)}\n"
    )
    return system, user


def judge_transcript(
    provider: BaseLLMProvider,
    *,
    persona: Persona,
    task: Task,
    transcript: Mapping[str, Any],
    rubrics: Rubrics,
) -> Dict[str, Any]:
    """调用独立法官提示，返回结构化初评。

    Parameters
    ----------
    provider : BaseLLMProvider
        与被测 Ask 可共用底层模型，但 system 独立。
    persona, task, transcript, rubrics
        当次任务上下文。

    Returns
    -------
    dict
        含 ``auto_scores``、``jackie_scores``（空）、``summary``、
        ``friction``、``suggested_fixes``、``rule_flags``。
    """

    system, user = build_judge_prompt(
        persona=persona,
        task=task,
        transcript=transcript,
        rubrics=rubrics,
    )
    raw = provider.chat(user, system_prompt=system)
    parsed = _extract_json(raw)
    scores_raw = parsed.get("scores") if isinstance(parsed.get("scores"), Mapping) else {}
    auto_scores: Dict[str, Any] = {}
    for dim in rubrics.dimensions:
        dim_id = str(dim.get("id") or "")
        if not dim_id:
            continue
        value = scores_raw.get(dim_id)
        try:
            auto_scores[dim_id] = int(value)
        except (TypeError, ValueError):
            auto_scores[dim_id] = None
    friction = [str(x) for x in (parsed.get("friction") or []) if str(x).strip()]
    fixes = [str(x) for x in (parsed.get("suggested_fixes") or []) if str(x).strip()]
    rule_flags = _rule_red_line_flags(transcript)
    for flag in rule_flags:
        note = f"rule_flag:{flag}"
        if note not in friction:
            friction.append(note)
    red = auto_scores.get("red_lines")
    if isinstance(red, int) and red < rubrics.scale_max:
        if not any("red_lines" in str(item) for item in friction):
            friction.append(f"red_lines_score={red}")
    return {
        "auto_scores": auto_scores,
        "jackie_scores": {},
        "summary": str(parsed.get("summary") or "").strip(),
        "friction": friction,
        "suggested_fixes": fixes,
        "rule_flags": rule_flags,
        "judge_raw": raw,
    }
