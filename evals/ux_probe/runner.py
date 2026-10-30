# coding=utf-8
# ======================================
# File: runner.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-29
# Desc:
# UX Probe runner：模拟用户 + Ask 多轮 + 可选法官。
# ======================================

"""执行体验罗盘任务并产出 transcript / 报告载荷。"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from qteasy_ai.app import QteasyAssistant
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.provider import BaseLLMProvider, FakeLLMProvider

from .judge import judge_transcript
from .loader import (
    DEFAULT_PRODUCT,
    Persona,
    ProbeBundle,
    Task,
    Turn,
    load_bundle,
    meets_min_product,
)
from .report import write_json_report, write_markdown_report


def _utc_now() -> str:
    """UTC ISO 时间戳。"""

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _assistant_answer_fields(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """从 ask 原始 dict 抽出报告字段。"""

    error = payload.get("error") if isinstance(payload.get("error"), Mapping) else {}
    return {
        "ok": bool(payload.get("ok")),
        "answer": str(payload.get("answer") or payload.get("narrative") or ""),
        "sources": list(payload.get("sources") or []),
        "plan_id": payload.get("plan_id"),
        "error_code": error.get("code") if error else None,
    }


def improvise_user_utterance(
    provider: BaseLLMProvider,
    *,
    persona: Persona,
    task: Task,
    turn: Turn,
    prior_turns: Sequence[Mapping[str, Any]],
) -> str:
    """按画像与目标即兴下一句用户话。"""

    system = (
        "You role-play one end user talking to qteasy-ai Ask. "
        "Stay in character. Output ONLY the next user message in the user's language. "
        "No markdown fences. Do not ask for guaranteed profits or live order placement."
    )
    history = []
    for item in prior_turns:
        history.append(f"USER: {item.get('query')}")
        history.append(f"ASSISTANT: {str(item.get('answer') or '')[:800]}")
    user = (
        f"Persona name: {persona.display_name}\n"
        f"Role: {persona.role}\n"
        f"Language style: {persona.language_style}\n"
        f"Preferences: {persona.preferences}\n"
        f"Taboos: {persona.taboos}\n"
        f"Task goal: {task.goal}\n"
        f"Hint for this turn: {turn.hint or 'Continue toward the goal.'}\n"
        f"Prior turns:\n" + ("\n".join(history) if history else "(none)") + "\n"
        "Write the next user utterance now."
    )
    text = str(provider.chat(user, system_prompt=system) or "").strip()
    return text or (turn.hint or "能再说清楚一点吗？")


def run_task_ask(
    assistant: QteasyAssistant,
    *,
    persona: Persona,
    task: Task,
    sim_provider: BaseLLMProvider,
    session_prefix: str,
) -> Dict[str, Any]:
    """同一 session 跑完一条 Ask 任务，返回 transcript。"""

    session_id = f"{session_prefix}-{task.id}-{persona.id}"
    turns_out: List[Dict[str, Any]] = []
    for turn in task.turns:
        if turn.improvise or not turn.text:
            query = improvise_user_utterance(
                sim_provider,
                persona=persona,
                task=task,
                turn=turn,
                prior_turns=turns_out,
            )
            source = "improvise"
        else:
            query = turn.text
            source = "script"
        raw = assistant.ask(query, response_style="raw", session_id=session_id)
        if not isinstance(raw, Mapping):
            raw = {"ok": False, "answer": str(raw), "sources": []}
        fields = _assistant_answer_fields(raw)
        turns_out.append(
            {
                "id": turn.id,
                "query": query,
                "query_source": source,
                **fields,
            }
        )
    return {
        "session_id": session_id,
        "channel": "ask",
        "turns": turns_out,
    }


def select_tasks(
    bundle: ProbeBundle,
    *,
    task_ids: Optional[Sequence[str]] = None,
    current_product: str = DEFAULT_PRODUCT,
) -> tuple:
    """选出要跑与要跳过的任务。"""

    wanted = list(task_ids) if task_ids else sorted(bundle.tasks.keys())
    selected: List[Task] = []
    skipped: List[Dict[str, str]] = []
    for tid in wanted:
        task = bundle.tasks.get(tid)
        if task is None:
            skipped.append({"task_id": tid, "reason": "unknown task id"})
            continue
        if task.channel != "ask":
            skipped.append({"task_id": tid, "reason": f"channel {task.channel} not implemented yet"})
            continue
        if not meets_min_product(task.min_product, current_product):
            skipped.append(
                {
                    "task_id": tid,
                    "reason": f"min_product {task.min_product} > current {current_product}",
                }
            )
            continue
        selected.append(task)
    return selected, skipped


def run_probe(
    *,
    root: Optional[Path] = None,
    task_ids: Optional[Sequence[str]] = None,
    current_product: str = DEFAULT_PRODUCT,
    judge: bool = True,
    provider: Optional[BaseLLMProvider] = None,
    memory_store: Optional[MemoryStore] = None,
    out_dir: Optional[Path] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """跑体验罗盘并写 JSON/Markdown 报告。

    Parameters
    ----------
    root : Path, optional
        YAML 真源根目录。
    task_ids : sequence of str, optional
        只跑这些任务；默认全部（仍受 min_product 过滤）。
    current_product : str
        当前产品地板，默认 ``0.3-ask``。
    judge : bool
        是否调用无人值守法官。
    provider : BaseLLMProvider, optional
        被测 Ask 与模拟用户/法官共用；缺省用 MemoryStore 活动项。
    memory_store : MemoryStore, optional
    out_dir : Path, optional
        报告目录，默认 ``evals/ux_probe/runs/<run_id>``。
    run_id : str, optional
        运行目录名。

    Returns
    -------
    dict
        报告载荷（含写出路径）。
    """

    bundle = load_bundle(root)
    store = memory_store or MemoryStore()
    active = provider
    if active is None:
        active = store.build_active_provider()
    if active is None:
        active = FakeLLMProvider(
            replies=[
                json.dumps({"topics": ["overview"]}, ensure_ascii=False),
                json.dumps({"ids": ["what_is_qteasy"]}, ensure_ascii=False),
                "FAKE: conceptual answer without live trading.",
            ]
            * 40
        )
    # Isolated session files for the probe; do not pollute user sessions.
    probe_store = MemoryStore(base_dir=tempfile.mkdtemp(prefix="ux_probe_"))
    assistant = QteasyAssistant(provider=active, memory_store=probe_store)

    selected, skipped = select_tasks(
        bundle, task_ids=task_ids, current_product=current_product
    )
    rid = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = Path(out_dir) if out_dir is not None else (bundle.root / "runs" / rid)
    target.mkdir(parents=True, exist_ok=True)

    runs: List[Dict[str, Any]] = []
    for task in selected:
        persona = bundle.personas[task.persona_id]
        transcript = run_task_ask(
            assistant,
            persona=persona,
            task=task,
            sim_provider=active,
            session_prefix=rid,
        )
        judgment: Dict[str, Any]
        if judge:
            judgment = judge_transcript(
                active,
                persona=persona,
                task=task,
                transcript=transcript,
                rubrics=bundle.rubrics,
            )
        else:
            judgment = {
                "auto_scores": {},
                "jackie_scores": {},
                "summary": "",
                "journey_summary": {
                    "asked": "",
                    "answered": "",
                    "goal_met": "",
                    "note": "",
                },
                "persona_voice": {
                    "narrative": "",
                    "continue_use": "",
                    "recommend": "",
                },
                "friction": [],
                "suggested_fixes": [],
                "rule_flags": [],
            }
        runs.append(
            {
                "persona": {
                    "id": persona.id,
                    "display_name": persona.display_name,
                    "role": persona.role,
                },
                "task": {
                    "id": task.id,
                    "goal": task.goal,
                    "min_product": task.min_product,
                    "channel": task.channel,
                },
                "transcript": transcript,
                "judge": judgment,
            }
        )

    payload: Dict[str, Any] = {
        "generated_at": _utc_now(),
        "run_id": rid,
        "current_product": current_product,
        "not_a_gate": True,
        "skipped": skipped,
        "runs": runs,
    }
    json_path = write_json_report(target / "report.json", payload)
    md_path = write_markdown_report(target / "report.md", payload)
    payload["paths"] = {"json": str(json_path), "markdown": str(md_path)}
    # refresh markdown is already written; keep paths on returned dict
    write_json_report(json_path, payload)
    return payload
