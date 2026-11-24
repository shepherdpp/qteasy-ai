# coding=utf-8
# ======================================
# File: parse_turn.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-22
# Desc:
# 一次意图解析：一份协议同时给出
# 办事、询问、关系和开放句。
# ======================================

"""用户句到主意图的一次解析。

宪法在调用方、准备提纲之前跑完。本模块只做这一次协议或金句，
以及意图卡和恢复卡的拼装。点选不进这里，也不再向模型要一次。
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence

from .identity import prefix_system_prompt
from .intent_engine import normalize_query_text

FIXED_GUIDE = (
    "Choose a listed job, confirm the open-plan sentence, or rephrase the request."
)
FIXED_RECOVER = (
    "The open plan could not be built. Pick a suggested job or rephrase the request."
)
BLOCK_HINT = (
    "A high side-effect plan is still running. Wait for it to finish, or abandon it, "
    "before starting another."
)
CONFIRM_OPEN_ID = "confirm_open_intent"
_RELATIONS = {"", "new", "revise", "run", "abandon"}
_PROTOCOL_KEYS = (
    "job",
    "intent_text",
    "clarification_text",
    "open_intent",
    "task",
    "questions",
    "candidates",
    "relation",
    "plan_id",
    "fetch",
)

_PARSE_SYSTEM = """\
You parse one qteasy-ai user sentence into one JSON object. Reply with JSON only.

Goal: fill job only when the sentence clearly matches one official Job. Then candidates is [], clarification_text is "", and open_intent is "". Otherwise job is "". Write the question shown to the user, one open-plan sentence the user can confirm, and the few closest official Jobs. Closeness is your judgment. Do not emit a score.

Fields:
- job: an official Job id from the Official jobs list, or "".
- intent_text: one sentence of your understanding, in the same language as the user sentence. Not a slice of the user sentence. Not the card question.
- clarification_text: the question shown to the user, in the same language as the user sentence. "" when job is an official id.
- open_intent: one open-plan sentence the user can confirm, in the same language as the user sentence, or "". It is a string, never true, false, or null. Do not copy the user sentence unless that sentence itself is the plan to run. "" when job is an official id. The user confirms this sentence, not the original sentence and not intent_text.
- task: an exact contiguous slice of the user sentence for the work, or "". Do not translate it and do not drop characters. If no such slice exists, use "".
- questions: an array of exact contiguous slices that are questions. Do not translate them and do not drop characters. They must not overlap task or each other. Do not put "" in the array. When the sentence contains both work and a question, put the work in task and the question in questions. Leave out any question that is not verbatim in the user sentence.
- candidates: an array of {id, label, detail}. Each id comes from the Official jobs list. label and detail use the same language as the user sentence. Do not include open or abandon. Do not make job and candidates both non-empty. [] when job is an official id. When job is "", include the few closest official Jobs.
- relation is one of:
  - new: this sentence starts a new plan.
  - revise: the outline already has a plan that has not run, and this sentence changes it.
  - run: the outline already has a plan that has not run, and this sentence asks to run it.
  - abandon: this sentence abandons the current plan that has not run. Then job is "", candidates is [], and open_intent is "".
  - "": the sentence and the outline do not show which of the above it is.
- plan_id: "" or a plan id already present in the materials.
- fetch: "" unless one earlier turn or one plan in the outline is not complete enough. Only then use turn:<n> or plan:<id>. The current sentence is already in User sentence. Do not fetch it.

Do not include slot values, steps, or flags.

The user message has up to five parts:
- Official jobs: the only legal source for job and candidate ids. Each line is an id and what that job does.
- Outline: earlier turns. It is not the current sentence.
- Fetched: material named by a previous parse of this same sentence. Use it only to complete this parse.
- User sentence: the sentence to parse. Do not replace it with a card reply.
- Card replies: answers typed into the blank box of the intent card for this same user sentence. They are not a new user sentence. Do not replace User sentence with them. task and questions must still be exact contiguous slices of User sentence. Use the replies only to reconsider job, open_intent, candidates, clarification_text, and relation.

Slices in an example belong only to that example's user sentence. Do not copy words that are not in the current user sentence.

Example, unclear job.
User sentence: 把 000300.SH 的走势画出来，波动大不大？
{"job":"","intent_text":"用户想看指数走势，并问波动大不大","clarification_text":"你是要导出走势图，还是看波动和交易日的摘要？也可以确认下面这句开放图意图。","open_intent":"画出 000300.SH 的走势并标出波动","task":"把 000300.SH 的走势画出来","questions":["波动大不大？"],"candidates":[{"id":"data.export","label":"导出走势图","detail":"把走势画出来"},{"id":"data.summary","label":"行情摘要","detail":"看波动和交易日"}],"relation":"new","plan_id":"","fetch":""}

Example, clear official job.
User sentence: 看一下 000300.SH 的波动和交易日
{"job":"data.summary","intent_text":"查看指数的波动和交易日","clarification_text":"","open_intent":"","task":"看一下 000300.SH 的波动和交易日","questions":[],"candidates":[],"relation":"new","plan_id":"","fetch":""}
"""


def parse_utterance(
    engine: Any,
    utterance: str,
    *,
    outline: str = "",
    fetched: str = "",
    identity_dir: Optional[str] = None,
    card_replies: str = "",
) -> Dict[str, Any]:
    """解析一句。有模型走协议，没有模型只认整句金句。

    Parameters
    ----------
    engine : IntentEngine
        提供官方 Job、金句表和模型。本函数不跑宪法。
    utterance : str
        用户原句。
    outline : str, optional
        当前这句之前的会话提纲。
    fetched : str, optional
        已经取回的材料。无模型时忽略，也不再查一次金句。
    identity_dir : str, optional
        用户身份目录，只加在协议的系统提示前。
    card_replies : str, optional
        同一句意图卡上的空白框回复。无模型时忽略。

    Returns
    -------
    dict
        这一次解析的整包。点选不进入这里。
    """

    if getattr(engine, "provider", None) is not None:
        return _parse_with_model(
            engine,
            utterance,
            outline=outline,
            fetched=fetched,
            identity_dir=identity_dir,
            card_replies=card_replies,
        )
    return _parse_without_model(engine, utterance, outline=outline)


def _parse_with_model(
    engine: Any,
    utterance: str,
    *,
    outline: str,
    fetched: str,
    identity_dir: Optional[str],
    card_replies: str = "",
) -> Dict[str, Any]:
    """有模型的一次协议。不查金句。"""

    official = set(engine.catalog.official_ids)
    catalog_lines = "\n".join(
        line
        for line in engine.catalog.job_summaries()
        if line.startswith("- ") and line[2:].split(":", 1)[0].strip() in official
    )
    prompt_parts = [f"Official jobs:\n{catalog_lines}"]
    if str(outline or "").strip():
        prompt_parts.append("Outline:\n" + str(outline).strip())
    if str(fetched or "").strip():
        prompt_parts.append("Fetched:\n" + str(fetched).strip())
    prompt_parts.append("User sentence:\n" + str(utterance or ""))
    if str(card_replies or "").strip():
        prompt_parts.append("Card replies:\n" + str(card_replies).strip())
    prompt = "\n\n".join(prompt_parts)
    try:
        raw = engine.provider.chat(
            prompt,
            system_prompt=prefix_system_prompt(_PARSE_SYSTEM, identity_dir),
        )
    except Exception:
        raw = ""
    package = _package_from_protocol(str(raw or ""), str(utterance or ""), official)
    package["debug_entry"] = {
        "outline": str(outline or ""),
        "fetched": str(fetched or ""),
        "protocol": str(raw or ""),
        "gold_id": "",
        "rationale": "",
    }
    package["source"] = "llm"
    return package


def _parse_without_model(engine: Any, utterance: str, *, outline: str) -> Dict[str, Any]:
    """无模型只认整句金句。不调用模型，也不读取 fetch。"""

    text = str(utterance or "")
    gold = engine._gold_index.get(normalize_query_text(text))
    if gold and gold.get("lock"):
        job = str(gold.get("job") or "")
        relation = str(gold.get("relation") or "")
        if "relation" not in gold or not relation:
            relation = "new" if job else ""
        official = set(engine.catalog.official_ids)
        confirmed = "direct" if job in official else ""
        if relation == "abandon":
            confirmed = ""
            job = ""
        package = _blank(text)
        package.update(
            {
                "job": job,
                "intent_text": text,
                "task": text,
                "relation": relation,
                "confirmed": confirmed,
                "flags": dict(gold.get("flags") or {}),
                "gold_id": str(gold.get("id") or ""),
                "source": "rule",
            }
        )
    else:
        package = _blank(text)
        package.update(
            {
                "clarification_text": FIXED_GUIDE,
                "open_intent": text,
                "source": "rule",
                "gold_id": "",
            }
        )
    package["debug_entry"] = {
        "outline": str(outline or ""),
        "fetched": "",
        "protocol": "",
        "gold_id": str(package.get("gold_id") or ""),
        "rationale": "",
    }
    return package


def present_intent_card(package: Dict[str, Any]) -> Dict[str, Any]:
    """用这一次解析的字段拼意图卡。不调用模型。

    Parameters
    ----------
    package : dict
        尚未确认主意图的解析整包。

    Returns
    -------
    dict
        现有澄清字典，带 ``intent_authored``。
    """

    guide = str(package.get("clarification_text") or "").strip() or FIXED_GUIDE
    options = [
        {
            "id": str(item.get("id") or ""),
            "label": str(item.get("label") or item.get("id") or ""),
            "detail": str(item.get("detail") or ""),
        }
        for item in (package.get("candidates") or [])
        if isinstance(item, dict) and str(item.get("id") or "")
    ]
    open_intent = str(package.get("open_intent") or "").strip()
    if open_intent:
        options.append({"id": CONFIRM_OPEN_ID, "label": open_intent, "detail": ""})
    row: Dict[str, Any] = {
        "name": "intent",
        "prompt": guide,
        "options": options,
        "open": {"label": "Your own open intent"},
    }
    return {
        "intent_authored": True,
        "parse_package": slim_package(package),
        "pending": [row],
        "confirm_prompt": guide,
    }


def present_recover_card(
    package: Dict[str, Any],
    *,
    reason: str,
    official_ids: Sequence[str],
) -> Dict[str, Any]:
    """组图失败后的恢复卡。建议最多两个官方 Job，没有再确认开放句。

    Parameters
    ----------
    package : dict
        已经确认过开放句的整包。询问仍留在里面。
    reason : str
        组图失败原因，写进题干。
    official_ids : sequence of str
        官方 Job。建议之外的 id 丢掉，也不另补。

    Returns
    -------
    dict
        带 ``recover_authored`` 的澄清字典。
    """

    allowed = set(official_ids)
    options: List[Dict[str, str]] = []
    for item in package.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        ident = str(item.get("id") or "")
        if ident not in allowed or ident in {"open", "abandon"}:
            continue
        options.append(
            {
                "id": ident,
                "label": str(item.get("label") or ident),
                "detail": str(item.get("detail") or ""),
            }
        )
        if len(options) == 2:
            break
    prompt = f"Open plan was not built ({reason}). {FIXED_RECOVER}"
    return {
        "recover_authored": True,
        "parse_package": slim_package(package),
        "pending": [
            {
                "name": "recover",
                "prompt": prompt,
                "options": options,
                "open": {"label": "Rewrite the request"},
            }
        ],
        "confirm_prompt": prompt,
    }


def format_card_replies(rows: Sequence[Dict[str, Any]]) -> str:
    """把同一句意图卡上的空白框回复写成 ``Card replies``。

    Parameters
    ----------
    rows : sequence of dict
        每一轮的题干、官方选项、推荐开放句和回复。

    Returns
    -------
    str
        多轮正文。没有回复时为空串。
    """

    blocks: List[str] = []
    for index, row in enumerate(rows or [], 1):
        if not isinstance(row, dict):
            continue
        options = [
            f"{str(item.get('id') or '')} {str(item.get('label') or '')}".strip()
            for item in (row.get("options") or [])
            if isinstance(item, dict) and str(item.get("id") or "")
        ]
        blocks.append(
            "\n".join(
                [
                    f"Round {index}",
                    "Question: " + str(row.get("prompt") or ""),
                    "Official options: " + "; ".join(options),
                    "Recommended open intent: " + str(row.get("open_intent") or ""),
                    "Reply: " + str(row.get("reply") or ""),
                ]
            )
        )
    return "\n\n".join(blocks)


def decide(package: Dict[str, Any], session: Any) -> str:
    """主意图确认之后，按 relation 选新建、修订或停。

    Parameters
    ----------
    package : dict
        解析整包。关系会在改接到新建时写成 ``new``。
    session : ConversationState or None
        用来看未执行计划是否还在。

    Returns
    -------
    str
        ``constitution``、``abandon``、``intent``、``fresh`` 或 ``keep``。
    """

    if package.get("constitution"):
        package["hold_execution"] = False
        return "constitution"
    if "original_relation" not in package:
        package["original_relation"] = str(package.get("relation") or "")
    package["hold_execution"] = package.get("original_relation") in {"run", "revise"}
    relation = str(package.get("relation") or "")
    candidates = package.get("candidates") or []
    open_intent = str(package.get("open_intent") or "")
    if relation == "abandon" and not candidates and not open_intent:
        return "abandon"
    confirmed = str(package.get("confirmed") or "")
    if confirmed not in {"direct", "candidate", "open_intent", "recovery"}:
        return "intent"
    if relation in {"", "new"}:
        package["relation"] = "new"
        return "fresh"
    if relation in {"run", "revise"} and plan_available(session):
        return "keep"
    package["relation"] = "new"
    return "fresh"


def plan_available(session: Any) -> bool:
    """未执行计划还在：澄清中或已就绪，并且有计划号或 Job。

    Parameters
    ----------
    session : ConversationState or None
        当前会话。

    Returns
    -------
    bool
        计划还在时为 True。
    """

    task = getattr(session, "task", None) if session is not None else None
    if task is None:
        return False
    if str(getattr(task, "status", "") or "") not in {"clarifying", "ready"}:
        return False
    return bool(str(getattr(task, "plan_id", "") or "") or str(getattr(task, "job", "") or ""))


def slim_package(package: Dict[str, Any]) -> Dict[str, Any]:
    """卡片上留着点选还要用的字段。询问不删。

    Parameters
    ----------
    package : dict
        解析整包。

    Returns
    -------
    dict
        不含调试条目的副本。
    """

    return {
        "utterance": str(package.get("utterance") or ""),
        "intent_text": str(package.get("intent_text") or ""),
        "clarification_text": str(package.get("clarification_text") or ""),
        "open_intent": str(package.get("open_intent") or ""),
        "job": str(package.get("job") or ""),
        "task": str(package.get("task") or ""),
        "questions": [str(item) for item in (package.get("questions") or [])],
        "candidates": [dict(item) for item in (package.get("candidates") or []) if isinstance(item, dict)],
        "relation": str(package.get("relation") or ""),
        "plan_id": str(package.get("plan_id") or ""),
        "flags": dict(package.get("flags") or {}),
        "source": str(package.get("source") or ""),
        "original_relation": str(package.get("original_relation") or package.get("relation") or ""),
    }


def public_record(package: Dict[str, Any], *, plan_id: str) -> Dict[str, Any]:
    """写进计划和任务的解析记录。

    Parameters
    ----------
    package : dict
        解析整包。
    plan_id : str
        这一次实际使用的计划号。

    Returns
    -------
    dict
        不含协议原文和提纲。
    """

    return {
        "utterance": str(package.get("utterance") or ""),
        "intent_text": str(package.get("intent_text") or ""),
        "clarification_text": str(package.get("clarification_text") or ""),
        "open_intent": str(package.get("open_intent") or ""),
        "job": str(package.get("job") or ""),
        "task": str(package.get("task") or ""),
        "questions": [str(item) for item in (package.get("questions") or [])],
        "relation": str(package.get("relation") or ""),
        "plan_id": str(plan_id or ""),
        "candidates": [dict(item) for item in (package.get("candidates") or []) if isinstance(item, dict)],
        "confirmed_by": str(package.get("confirmed") or ""),
        "card": str(package.get("card") or ""),
        "choice": str(package.get("choice") or ""),
        "constitution_hint": str(package.get("constitution_hint") or ""),
        "block_hint": str(package.get("block_hint") or ""),
        "open_note": str(package.get("open_note") or ""),
        "executable": bool(package.get("executable")),
    }


def load_material(
    spec: str,
    cards: Sequence[Any],
    session: Any,
    store: Any,
) -> str:
    """按 ``turn:`` 或 ``plan:`` 取材料。没有就是 ``missing``。

    Parameters
    ----------
    spec : str
        ``turn:<n>`` 或 ``plan:<id>``。
    cards : sequence
        当前这句之前的提纲索引。
    session : ConversationState or None
        用来对未执行任务。
    store : MemoryStore or None
        用来读 ``runs/<id>.plan.md``。

    Returns
    -------
    str
        材料正文，或 ``missing``。
    """

    text = str(spec or "").strip()
    if text.startswith("turn:"):
        try:
            number = int(text.split(":", 1)[1])
        except (TypeError, ValueError):
            return "missing"
        matched = [card for card in cards if int(getattr(card, "turn", 0) or 0) == number]
        if not matched:
            return "missing"
        user = str(getattr(matched[0], "user_text", "") or "")
        answers = "\n".join(str(getattr(card, "answer_text", "") or "") for card in matched)
        return f"user_text: {user}\nanswer_text: {answers}".strip()
    if text.startswith("plan:"):
        plan_id = text.split(":", 1)[1].strip()
        task = getattr(session, "task", None) if session is not None else None
        if (
            task is not None
            and str(getattr(task, "plan_id", "") or "") == plan_id
            and str(getattr(task, "status", "") or "") in {"clarifying", "ready"}
        ):
            return _task_material(task, store)
        if store is not None and plan_id:
            path = store.runs_dir / f"{plan_id}.plan.md"
            if path.is_file():
                return path.read_text(encoding="utf-8")
        return "missing"
    return "missing"


def constitution_package(utterance: str, decision: Any) -> Dict[str, Any]:
    """宪法拦住时的整包。还没有提纲。

    Parameters
    ----------
    utterance : str
        用户原句。
    decision : IntentDecision
        ``_constitution`` 的结果。

    Returns
    -------
    dict
        带 ``constitution`` 的整包。
    """

    rationale = str(getattr(decision, "rationale", "") or "")
    package = _blank(utterance)
    package.update(
        {
            "constitution": rationale,
            "job": str(getattr(decision, "job", "") or ""),
            "flags": dict(getattr(decision, "flags", None) or {}),
            "source": "rule",
            "debug_entries": [
                {
                    "outline": "",
                    "fetched": "",
                    "protocol": "",
                    "gold_id": "",
                    "rationale": rationale,
                }
            ],
        }
    )
    return package


def _blank(utterance: str) -> Dict[str, Any]:
    """一份空整包。"""

    return {
        "utterance": str(utterance or ""),
        "intent_text": "",
        "clarification_text": "",
        "open_intent": "",
        "job": "",
        "task": "",
        "questions": [],
        "candidates": [],
        "relation": "",
        "plan_id": "",
        "fetch": "",
        "confirmed": "",
        "flags": {},
        "invalid": False,
        "executable": False,
        "source": "",
        "gold_id": "",
        "card": "",
        "choice": "",
        "constitution_hint": "",
        "block_hint": "",
        "open_note": "",
    }


def _package_from_protocol(raw: str, utterance: str, official: set) -> Dict[str, Any]:
    """协议不合法时整份作废，询问也不留下。"""

    payload = _parse_json(raw)
    if not isinstance(payload, dict) or any(key not in payload for key in _PROTOCOL_KEYS):
        return _void(utterance)
    job = payload.get("job")
    intent_text = payload.get("intent_text")
    clarification = payload.get("clarification_text")
    open_intent = payload.get("open_intent")
    task = payload.get("task")
    questions = payload.get("questions")
    candidates = payload.get("candidates")
    relation = payload.get("relation")
    plan_id = payload.get("plan_id")
    fetch = payload.get("fetch")
    if not all(isinstance(item, str) for item in (job, intent_text, clarification, open_intent, task, relation, plan_id, fetch)):
        return _void(utterance)
    if relation not in _RELATIONS:
        return _void(utterance)
    if not _fetch_shape(str(fetch)):
        return _void(utterance)
    if not isinstance(questions, list) or any(not isinstance(item, str) for item in questions):
        return _void(utterance)
    if not isinstance(candidates, list):
        return _void(utterance)
    cleaned: List[Dict[str, str]] = []
    for item in candidates:
        if not isinstance(item, dict):
            return _void(utterance)
        ident = str(item.get("id") or "")
        if ident not in official:
            return _void(utterance)
        cleaned.append(
            {
                "id": ident,
                "label": str(item.get("label") or ident),
                "detail": str(item.get("detail") or ""),
            }
        )
    if str(job) and cleaned:
        return _void(utterance)
    if str(job) in official:
        if str(clarification) or str(open_intent) or cleaned:
            return _void(utterance)
    elif str(job) == "open":
        job = ""
        if not str(open_intent):
            open_intent = utterance
    elif str(job):
        return _void(utterance)
    if not _spans_fit(utterance, str(task), [str(item) for item in questions]):
        return _void(utterance)
    if str(job) in official and not str(task):
        task = utterance
    package = _blank(utterance)
    package.update(
        {
            "job": str(job),
            "intent_text": str(intent_text),
            "clarification_text": str(clarification),
            "open_intent": str(open_intent),
            "task": str(task),
            "questions": [str(item) for item in questions],
            "candidates": cleaned,
            "relation": str(relation),
            "plan_id": str(plan_id),
            "fetch": str(fetch),
            "confirmed": "direct" if str(job) in official else "",
        }
    )
    return package


def _void(utterance: str) -> Dict[str, Any]:
    """整份作废。固定引导加上原句作为待确认的开放句。"""

    package = _blank(utterance)
    package.update(
        {
            "clarification_text": FIXED_GUIDE,
            "open_intent": str(utterance or ""),
            "invalid": True,
        }
    )
    return package


def _fetch_shape(fetch: str) -> bool:
    """空、``turn:`` 正整数、或 ``plan:`` 非空编号。"""

    if fetch == "":
        return True
    if fetch.startswith("turn:"):
        number = fetch.split(":", 1)[1]
        return bool(number) and number.isdigit() and int(number) > 0
    if fetch.startswith("plan:"):
        return bool(fetch.split(":", 1)[1].strip())
    return False


def _spans_fit(utterance: str, task: str, questions: Sequence[str]) -> bool:
    """办事和询问都是原句里的连续片段，而且互不重叠。"""

    spans: List[tuple] = []
    if task:
        start = utterance.find(task)
        if start < 0:
            return False
        spans.append((start, start + len(task)))
    for question in questions:
        if not question:
            return False
        start = utterance.find(question)
        if start < 0:
            return False
        spans.append((start, start + len(question)))
    spans.sort()
    for earlier, later in zip(spans, spans[1:]):
        if later[0] < earlier[1]:
            return False
    return True


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    """从模型原文里取出一个 JSON 对象。"""

    blob = str(text or "").strip()
    if blob.startswith("```"):
        lines = blob.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        blob = "\n".join(lines).strip()
    try:
        payload = json.loads(blob)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass
    start = blob.find("{")
    end = blob.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(blob[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _task_material(task: Any, store: Any) -> str:
    """未执行任务对上时，取出用户句、Job、技能名和输入。"""

    lines = [
        f"user_text: {str(getattr(task, 'user_query', '') or '')}",
        f"job: {str(getattr(task, 'job', '') or '')}",
    ]
    plan_id = str(getattr(task, "plan_id", "") or "")
    payload = store.find_run_by_plan_id(plan_id) if store is not None and plan_id else None
    plan = payload.get("plan") if isinstance(payload, dict) else None
    steps = plan.get("steps") if isinstance(plan, dict) else []
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        lines.append(
            "skill: "
            + str(step.get("skill_name") or "")
            + " inputs: "
            + json.dumps(step.get("inputs") or {}, ensure_ascii=False)
        )
    return "\n".join(lines)
