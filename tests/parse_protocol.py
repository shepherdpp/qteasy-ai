# coding=utf-8
# ======================================
# File: parse_protocol.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-24
# Desc:
# 测试里用一份合并协议确认 Job，或交出已经确认的开放图。
# ======================================

"""旧用例改走一次解析时共用的协议。"""

import json
from typing import Any, Dict, List, Optional

from qteasy_ai.planner import Planner
from qteasy_ai.provider import FakeLLMProvider


def protocol_reply(query: str, job: str, relation: str = "") -> str:
    """一份合法合并协议。办事原文就是这句。"""

    return json.dumps(
        {
            "job": job,
            "intent_text": "",
            "clarification_text": "",
            "open_intent": "",
            "task": query,
            "questions": [],
            "candidates": [],
            "relation": relation,
            "plan_id": "",
            "fetch": "",
        },
        ensure_ascii=False,
    )


def open_parsed(query: str) -> Dict[str, Any]:
    """已经点过推荐开放句的整包。组图会再向模型要步骤。"""

    return {
        "job": "open",
        "confirmed": "open_intent",
        "open_intent": query,
        "task": query,
        "utterance": query,
        "relation": "new",
        "questions": [],
        "candidates": [],
        "flags": {},
        "source": "llm",
        "clarification_text": "",
        "intent_text": "",
        "plan_id": "",
        "fetch": "",
    }


def plan_job(
    registry: Any,
    query: str,
    job: str,
    *,
    relation: str = "",
    env_facts: Optional[Dict[str, Any]] = None,
    session: Any = None,
    replies: Optional[List[str]] = None,
    **kwargs: Any,
) -> Any:
    """用一份协议规划。额外回复排在协议后面，给填槽或组图。"""

    queue = list(replies) if replies is not None else [protocol_reply(query, job, relation)]
    if replies is not None and job:
        queue = [protocol_reply(query, job, relation), *queue]
    planner = Planner(
        registry,
        provider=FakeLLMProvider(replies=queue),
        env_facts=dict(env_facts or {}),
    )
    return planner.build_plan(query, mode="plan", session=session, **kwargs)
