# coding=utf-8
# ======================================
# File: run_ai_drill_provider_compare.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-24
# Desc:
# Q-AI.1 实弹演练 Round-D/L 精简对比脚本。
# 在已配置 QTEASY_AI_* 的 shell 中运行，打印
# provider-check 与四条基准 query 的 skill 路由。
# ======================================

"""Round-D / Round-L 精简对比（Jackie 本地补跑）。"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from qteasy_ai.app import QteasyAssistant
from qteasy_ai.cli import _provider_check_payload


QUERIES: List[Dict[str, str]] = [
    {"id": "G1", "mode": "plan", "query": "list built-in strategies"},
    {"id": "G2", "mode": "plan", "query": "show summary of 000300.SH from 20240101 to 20241231"},
    {"id": "G3", "mode": "ask", "query": "explain PT and PS"},
    {"id": "G4", "mode": "plan", "query": "run macd backtest from 20180101 to 20231231"},
]


def _first_skill(payload: Dict[str, Any]) -> str:
    steps = payload.get("plan", {}).get("steps", [])
    if not steps:
        return ""
    return str(steps[0].get("skill_name", ""))


def main() -> int:
    """打印 provider 诊断与四条路由结果。"""

    print("[provider-check]")
    print(json.dumps(_provider_check_payload(), ensure_ascii=False, indent=2))
    assistant = QteasyAssistant()
    print("\n[debug_config]")
    print(json.dumps(assistant.debug_config(), ensure_ascii=False, indent=2))
    print("\n[queries]")
    for item in QUERIES:
        mode = item["mode"]
        query = item["query"]
        if mode == "ask":
            raw = assistant.ask(query, response_style="raw", persist="none")
        else:
            raw = assistant.plan(query, response_style="raw", persist="none")
        if hasattr(raw, "to_dict"):
            payload = raw.to_dict()
        elif hasattr(raw, "raw"):
            payload = raw.raw
        else:
            payload = raw
        plan = payload.get("plan", {})
        print(
            f"- {item['id']}: mode={mode}, steps={len(plan.get('steps', []))}, "
            f"skill={_first_skill(payload)!r}, "
            f"provider_enabled_flag={plan.get('assumptions', {}).get('provider_enabled')}"
        )
    print(
        "\nExpected: skill routing matches Round-R; ask remains 0 steps; "
        "G4 -> system.fallback not_supported_yet."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
