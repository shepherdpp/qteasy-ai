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


def _score_table(scores: Mapping[str, Any]) -> str:
    """Markdown 分数表。"""

    lines = ["| 维度 | 自动分 | Jackie 复核 |", "|---|---:|---:|"]
    jackie = scores.get("jackie_scores") if isinstance(scores.get("jackie_scores"), Mapping) else {}
    auto = scores.get("auto_scores") if isinstance(scores.get("auto_scores"), Mapping) else {}
    keys = list(auto.keys()) or list(jackie.keys())
    for key in keys:
        lines.append(f"| {key} | {auto.get(key, '')} | {jackie.get(key, '')} |")
    return "\n".join(lines)


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
                "### Friction",
            ]
        )
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
