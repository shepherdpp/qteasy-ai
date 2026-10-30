# coding=utf-8
# ======================================
# File: report.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-29
# Desc:
# UX Probe 人读 Markdown 与机读 JSON 报告。
# ======================================

"""写出体验罗盘报告。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping


def write_json_report(path: Path, payload: Mapping[str, Any]) -> Path:
    """写入机读 JSON。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


_GOAL_MET_LABEL = {
    "yes": "达到",
    "partial": "部分达到",
    "no": "未达到",
}


def _score_table(scores: Mapping[str, Any]) -> str:
    """Markdown 分数表。"""

    lines = ["| 维度 | 自动分 | Jackie 复核 |", "|---|---:|---:|"]
    jackie = scores.get("jackie_scores") if isinstance(scores.get("jackie_scores"), Mapping) else {}
    auto = scores.get("auto_scores") if isinstance(scores.get("auto_scores"), Mapping) else {}
    keys = list(auto.keys()) or list(jackie.keys())
    for key in keys:
        lines.append(f"| {key} | {auto.get(key, '')} | {jackie.get(key, '')} |")
    return "\n".join(lines)


def _journey_section(judge: Mapping[str, Any]) -> List[str]:
    """旅程摘要：问了什么 / 答了什么 / 是否达到目的。"""

    journey = judge.get("journey_summary") if isinstance(judge.get("journey_summary"), Mapping) else {}
    goal_raw = str(journey.get("goal_met") or "").strip().lower()
    goal_label = _GOAL_MET_LABEL.get(goal_raw, goal_raw or "（未评）")
    note = str(journey.get("note") or "").strip()
    lines = [
        "### 旅程摘要",
        "",
        f"- **问了什么：** {journey.get('asked') or '（无）'}",
        f"- **答了什么：** {journey.get('answered') or '（无）'}",
        f"- **是否达到目的：** {goal_label}"
        + (f"：{note}" if note else ""),
        "",
    ]
    return lines


def _persona_voice_section(
    persona: Mapping[str, Any],
    judge: Mapping[str, Any],
) -> List[str]:
    """虚拟用户第一人称主观评价。"""

    voice = judge.get("persona_voice") if isinstance(judge.get("persona_voice"), Mapping) else {}
    name = str(persona.get("display_name") or "虚拟用户").strip() or "虚拟用户"
    narrative = str(voice.get("narrative") or "").strip() or "（无）"
    continue_use = str(voice.get("continue_use") or "").strip() or "（未评）"
    recommend = str(voice.get("recommend") or "").strip() or "（未评）"
    return [
        f"### 虚拟用户主观（{name} · 第一人称）",
        "",
        narrative,
        "",
        f"- **还愿不愿意继续用：** {continue_use}",
        f"- **愿不愿意推荐给朋友：** {recommend}",
        "",
    ]


def render_markdown(payload: Mapping[str, Any]) -> str:
    """把一次或一批结果渲染成中文人读报告。"""

    runs: List[Mapping[str, Any]] = list(payload.get("runs") or [])
    lines: List[str] = [
        "# UX Probe 体验罗盘报告",
        "",
        f"- 生成时间：{payload.get('generated_at', '')}",
        f"- 当前产品地板：`{payload.get('current_product', '')}`",
        f"- 说明：**非关单**；低分只作改进指引；Jackie 可填 `jackie_scores` 复核。",
        "",
    ]
    skipped = list(payload.get("skipped") or [])
    if skipped:
        lines.append("## 跳过的任务")
        for item in skipped:
            lines.append(
                f"- `{item.get('task_id')}`：{item.get('reason')}"
            )
        lines.append("")
    for run in runs:
        persona = run.get("persona") or {}
        task = run.get("task") or {}
        judge = run.get("judge") or {}
        lines.extend(
            [
                f"## {persona.get('display_name', '')} · `{task.get('id', '')}`",
                "",
                f"**目标：** {task.get('goal', '').strip()}",
                "",
                _score_table(judge),
                "",
                f"**摘要：** {judge.get('summary') or '（无）'}",
                "",
            ]
        )
        lines.extend(_journey_section(judge))
        lines.extend(_persona_voice_section(persona, judge))
        lines.append("### Friction")
        friction = judge.get("friction") or []
        if friction:
            for item in friction:
                lines.append(f"- {item}")
        else:
            lines.append("- （无）")
        lines.append("")
        lines.append("### Suggested fixes")
        fixes = judge.get("suggested_fixes") or []
        if fixes:
            for item in fixes:
                lines.append(f"- {item}")
        else:
            lines.append("- （无）")
        lines.append("")
        lines.append("### Transcript")
        for turn in run.get("transcript", {}).get("turns") or []:
            lines.append(f"**用户 ({turn.get('id')})：** {turn.get('query')}")
            lines.append("")
            lines.append(
                f"**助手：** sources=`{turn.get('sources')}` ok=`{turn.get('ok')}`"
            )
            lines.append("")
            lines.append(str(turn.get("answer") or "")[:2000])
            lines.append("")
        lines.append("---")
        lines.append("")
    lines.append("## 汇总改进条目（去重建议）")
    seen = set()
    for run in runs:
        for item in (run.get("judge") or {}).get("suggested_fixes") or []:
            key = str(item).strip()
            if key and key not in seen:
                seen.add(key)
                lines.append(f"- {key}")
    if not seen:
        lines.append("- （本轮无建议；或法官未返回）")
    lines.append("")
    return "\n".join(lines)


def write_markdown_report(path: Path, payload: Mapping[str, Any]) -> Path:
    """写入人读 Markdown。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(payload), encoding="utf-8")
    return path
