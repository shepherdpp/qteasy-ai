# coding=utf-8
# ======================================
# File: run_ai_e8_live_robustness.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-05
# Desc:
# 可选真模型审核 H′ 改写/多意图/宪法抽检。
# 不进入 unittest discover。
# ======================================

"""对 d_paraphrase / d_multi_intent / 宪法抽检调用真实 Provider。

无 ``QTEASY_AI_MODEL`` 时打印 skip 并以 0 退出。有模型时打印 Markdown 表供 Jackie 人工审核。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from qteasy_ai.config import ConfigCenter
from qteasy_ai.intent_engine import IntentEngine
from qteasy_ai.intents import load_default_catalog
from qteasy_ai.provider import OpenAICompatProvider

_CORPUS = Path(__file__).resolve().parent / "ai_corpus" / "e8_h_prime_robustness.json"
_LIVE_FAMILIES = frozenset({"d_paraphrase", "d_multi_intent"})
_CONST_SAMPLE_IDS = frozenset(
    {"C-USF-D1", "C-UNS-D1", "C-MR-D1", "C-LV-D1"}
)


def _load_cases() -> List[Dict[str, Any]]:
    """读取 H′ 鲁棒语料。"""

    with _CORPUS.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return list(payload.get("cases") or [])


def _select_live_cases(cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """选出审核子集：改写、多意图、宪法抽检。"""

    selected: List[Dict[str, Any]] = []
    for case in cases:
        family = str(case.get("family") or "")
        case_id = str(case.get("id") or "")
        if family in _LIVE_FAMILIES or case_id in _CONST_SAMPLE_IDS:
            selected.append(case)
    return selected


def main() -> int:
    """有 Provider 则打印审核表；否则 skip。"""

    model = str(os.environ.get("QTEASY_AI_MODEL") or "").strip()
    if not model:
        print("skip: QTEASY_AI_MODEL is unset; live robustness review not run.")
        return 0

    config_center = ConfigCenter()
    provider_cfg = config_center.resolve_provider_config()
    api_key = str(provider_cfg.get("api_key") or "").strip()
    if not api_key:
        print("skip: provider API key missing; live robustness review not run.")
        return 0

    provider = OpenAICompatProvider(
        model=model,
        api_key=api_key,
        base_url=str(provider_cfg.get("base_url") or "https://api.openai.com/v1"),
        timeout=int(provider_cfg.get("timeout") or 120),
        config_center=config_center,
    )
    engine = IntentEngine(catalog=load_default_catalog(), provider=provider)
    cases = _select_live_cases(_load_cases())
    print("| id | expected_job | actual_job | match | rationale |")
    print("|---|---|---|---|---|")
    for case in cases:
        case_id = str(case.get("id") or "")
        expected = str(case.get("expected_job") or "")
        query = str(case.get("query") or "")
        decision = engine.classify(query)
        actual = decision.job
        match = "yes" if actual == expected else "no"
        rationale = str(decision.rationale or "").replace("|", "/")
        print(f"| {case_id} | {expected} | {actual} | {match} | {rationale} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
