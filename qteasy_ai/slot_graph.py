# coding=utf-8
# ======================================
# File: slot_graph.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-03
# Desc:
# 从已组成的步骤图投影用户槽，分次填槽，
# 并校验澄清卡的润色与点选。
# ======================================

"""意图已经落到步骤图之后的投影、填槽和澄清卡。

不另写一套槽名单。因子 IC 的手写槽不进这里。
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .slot_decl import clarification_prompt
from .wire import align_steps, choice_card
from .wires import format_wire_digest

_SKIP = {"upstream_payload", "upstream_payloads"}
_FILLABLE = {
    "industry",
    "threshold",
    "metric",
    "lookback_days",
    "names",
    "htype_names",
    "shares",
    "start",
    "end",
    "freq",
    "asset_type",
    "strategy_id",
    "statement",
    "period",
    "fields",
    "tables",
    "symbols",
    "asset_pool",
}
_STOP_WORDS = {
    "please",
    "fetch",
    "for",
    "and",
    "from",
    "to",
    "the",
    "data",
    "of",
    "a",
    "an",
    "in",
    "with",
    "get",
    "read",
    "via",
    "into",
    "on",
    "at",
    "by",
    "or",
    "sh",
    "sz",
    "bj",
    "get_history_data",
    "get_reference_data",
    "get_static_data",
    "start",
    "end",
    "freq",
    "shares",
    "rows",
    "symbols",
    "channel",
    "page",
    "asset",
    "type",
    "names",
    "htype",
    "htype_names",
    "asset_type",
    "strategy_id",
    "lookback",
    "lookback_days",
    "threshold",
    "metric",
}
_LABELS = {
    "industry": "Industry",
    "threshold": "Threshold",
    "metric": "Metric",
    "lookback_days": "Lookback days",
    "names": "Data types",
    "htype_names": "History columns",
    "shares": "Symbols",
    "start": "Start date",
    "end": "End date",
    "freq": "Frequency",
    "asset_type": "Asset type",
    "strategy_id": "Strategy",
    "statement": "Statement",
    "tables": "Tables",
    "table_name": "Table",
}
_DATE_HINT = (
    "Download/refill requires an explicit start and end date. "
    "Unbounded full-history download is not allowed."
)
_HINTS = {
    "industry": "Which industry should the screen use? Type it in your own words.",
    "threshold": "Give the return threshold as a decimal. 10% is 0.1.",
    "metric": "Choose drawdown or gain.",
    "lookback_days": "Give the lookback as a whole number of days.",
    "names": "Give the data type names.",
    "htype_names": "Give the history column names.",
    "shares": "Which symbols should this step use?",
    "start": _DATE_HINT,
    "end": _DATE_HINT,
    "strategy_id": "Which built-in strategy? Reply with an id, or use the open input.",
    "freq": "Frequency such as d, w, or m. Other type-correct values are still accepted.",
    "asset_type": "Asset type such as E or FD. Other type-correct values are still accepted.",
}
_REPHRASE = "No matching job. Rephrase the request, or ask for a short open plan."
_RECOVERY_ZH = "您的需求无法跟现成的操作模版匹配（job），是否需要我创建一份开放计划？"
_RECOVERY_EN = "This request does not match a built-in operation template (job). Create an open plan?"
_FILL_PREFIX = "Fill only these empty slots."
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_LOOKBACK_DAY = re.compile(r"(?<!\d)(\d{1,4})\s*(?:日|天|days?|d)\b", re.IGNORECASE)
_BAD_LOOKBACK = re.compile(
    r"(?:lookback(?:_days)?|回看(?:天数)?)\s*[:=：]?\s*(\S+)",
    re.IGNORECASE,
)
_CJK = re.compile(r"[\u4e00-\u9fff]")
_UPSTREAM_KEYS = {"upstream_payload", "upstream_payloads"}
_WINDOW_HINT = (
    "Provide at least one of start or end. "
    "rows alone does not select a history window."
)


def freq_spec() -> Dict[str, Any]:
    """日、周、月频率。``日线`` 收成 ``d``。不在 enum 里的其它写法仍可收下。

    Returns
    -------
    dict
        ``freq`` 字段的 schema。
    """

    return {
        "type": "string",
        "required": False,
        "enum": ["d", "w", "m"],
        "enum_strict": False,
        "aliases": {"日线": "d", "周线": "w", "月线": "m"},
    }


def asset_type_spec() -> Dict[str, Any]:
    """资产代码词表。``指数`` 收成 ``IDX``。词表和别名以外的说法不收下。

    Returns
    -------
    dict
        ``asset_type`` 字段的 schema。
    """

    codes = ["E", "IDX", "FT", "FD", "OPT"]
    return {
        "type": "string",
        "required": False,
        "enum": list(codes),
        "enum_strict": False,
        "vocabulary": list(codes),
        "aliases": {"指数": "IDX", "股票": "E", "基金": "FD", "期货": "FT", "期权": "OPT"},
    }


def dtype_spec(*, required: bool) -> Dict[str, Any]:
    """数据类型槽。值必须能唯一对上数据类型。

    Parameters
    ----------
    required : bool
        是否必填。

    Returns
    -------
    dict
        带 ``resolve=dtype`` 的字符串字段。
    """

    return {"type": "string", "required": required, "resolve": "dtype"}


def date_bound_presentation(name: str) -> Dict[str, str]:
    """日期一端的标签、说明、格式和例子。组约束另放。

    Parameters
    ----------
    name : str
        ``start`` 或 ``end``。其它名字按起点处理。

    Returns
    -------
    dict
        ``label`` / ``hint`` / ``format`` / ``example``。
    """

    if str(name or "") == "end":
        return {
            "label": "End date",
            "hint": "The last day of the range.",
            "format": "YYYYMMDD",
            "example": "20251231",
        }
    return {
        "label": "Start date",
        "hint": "The first day of the range.",
        "format": "YYYYMMDD",
        "example": "20250101",
    }


def date_field_spec(name: str, *, required: bool, constraint: str) -> Dict[str, Any]:
    """日期一端的 schema。题干、格式、例子共用，组约束由调用方传入。

    Parameters
    ----------
    name : str
        ``start`` 或 ``end``。
    required : bool
        是否必填。
    constraint : str
        写在澄清卡上的组约束，不放进 hint。

    Returns
    -------
    dict
        字符串字段 schema。
    """

    shown = date_bound_presentation(name)
    return {
        "type": "string",
        "required": required,
        "label": shown["label"],
        "hint": shown["hint"],
        "format": shown["format"],
        "example": shown["example"],
        "constraint": constraint,
    }


def window_bound_spec(name: str = "start") -> Dict[str, Any]:
    """历史窗口的一端。同一组里至少要有 start 或 end。

    Parameters
    ----------
    name : str, optional
        ``start`` 或 ``end``。决定这一格的标签、说明和例子。

    Returns
    -------
    dict
        ``start`` 或 ``end`` 的字段 schema。组约束在 ``constraint``。
    """

    return date_field_spec(name, required=False, constraint=_WINDOW_HINT)


def refill_bound_spec(name: str) -> Dict[str, Any]:
    """下载日期的一端。起止都必填，不许无界下载。

    Parameters
    ----------
    name : str
        ``start`` 或 ``end``。

    Returns
    -------
    dict
        必填的日期字段 schema。
    """

    return date_field_spec(name, required=True, constraint=_DATE_HINT)


def mentions_return(query: str) -> bool:
    """问句是否提到收益方向或百分数，从而需要谓词步。"""

    text = str(query or "")
    if any(item in text for item in ("跌", "涨", "%", "％")):
        return True
    lower = text.lower()
    return any(item in lower for item in ("drawdown", "drop", "gain", "rally"))


def dtype_tokens(query: str) -> List[str]:
    """按整词抽出数据类型候选。``industry`` 里的 ``name`` 不算一词。"""

    found: List[str] = []
    seen = set()
    for word in _WORD.findall(str(query or "")):
        key = word.lower()
        if key in _STOP_WORDS or key in seen:
            continue
        seen.add(key)
        found.append(word)
    return found


def strategy_id_options() -> List[str]:
    """内置策略 id 的字母序前 5 个。"""

    try:
        from qteasy.built_in import BUILT_IN_STRATEGIES
    except Exception:
        return []
    return sorted(str(key) for key in BUILT_IN_STRATEGIES)[:5]


def industry_option_ids() -> List[str]:
    """本地行业目录返回顺序的前 5 个。读不到则为空。"""

    try:
        from qteasy import QT_DATA_SOURCE

        basic = QT_DATA_SOURCE.read_table_data("stock_basic")
    except Exception:
        return []
    if basic is None or getattr(basic, "empty", True) or "industry" not in getattr(basic, "columns", []):
        return []
    found: List[str] = []
    seen = set()
    for item in basic["industry"].dropna().tolist():
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        found.append(text)
        if len(found) >= 5:
            break
    return found


def table_option_ids() -> List[str]:
    """表目录键顺序的前 5 个。"""

    try:
        from qteasy.datatables import TABLE_MASTERS
    except Exception:
        return []
    return [str(key) for key in list(TABLE_MASTERS)[:5]]


def date_pending_rows() -> List[Dict[str, Any]]:
    """下载缺日期时的两格。组约束写明不许无界下载。"""

    return [
        _pending_row(
            {
                "name": name,
                "type": "string",
                "enum": [],
                "enum_strict": False,
                "constraint": _DATE_HINT,
            }
        )
        for name in ("start", "end")
    ]


def apply_slot_layer(planner: Any, steps: List[Any], query: str, job: str, session: Any) -> Tuple[List[Any], Dict[str, Any]]:
    """投影并填当前图。因子 IC 保持原步骤。

    Parameters
    ----------
    planner : Planner
        用来读 schema、造澄清步。
    steps : list
        意图之后的步骤图。
    query : str
        本轮可见的问句。跟进时已拼上最初那句。
    job : str
        已定下的 Job。
    session : ConversationState or None
        已确认槽和上一张卡的冲突说明。

    Returns
    -------
    tuple
        ``(steps, extras)``。``extras`` 里可能有无槽澄清卡。
    """

    if job == "research.factor_ic":
        return steps, {}
    if _is_fallback(steps):
        return _rewrite_fallback(planner, steps, query)
    return _fill_graph(planner, steps, query, session, job)


def parse_card_answers(
    pending: Sequence[Dict[str, Any]],
    submitted: Dict[str, Any],
    provider: Any = None,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """一次解析澄清卡上的全部格子。

    点选 id 被模型改成另一个值时，这一格不收下。没有模型或整批非法时，
    点选 id 按启发式直接收下。

    Parameters
    ----------
    pending : sequence of dict
        系统出的题。含 ``name`` / ``type`` / ``options``。
    submitted : dict
        槽名到用户原文或选项 id。
    provider : provider, optional
        有则一次调用解析全部格子。

    Returns
    -------
    tuple
        ``(accepted, errors)``。errors 的值是这一格不收下的原因。
    """

    specs = [item for item in pending or [] if isinstance(item, dict) and item.get("name")]
    by_name = {str(item["name"]): item for item in specs}
    raws = {name: submitted[name] for name in by_name if name in (submitted or {})}
    model: Dict[str, Any] = {}
    if provider is not None and raws:
        parsed = _parse_model_slots(provider.chat(_card_prompt(raws)), list(raws))
        model = parsed or {}
        illegal = parsed is None
    else:
        illegal = True
    accepted: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    for name, raw in raws.items():
        spec = by_name[name]
        option_ids = _option_ids(spec)
        raw_text = str(raw).strip()
        if not illegal and name in model and raw_text in option_ids and str(model[name]).strip() != raw_text:
            errors[name] = f"{raw_text!r} was changed to {model[name]!r}. The selected option was not kept."
            continue
        if not illegal and name in model:
            value = coerce_slot_value(spec, model[name])
            if value is None:
                value = coerce_slot_value(spec, raw)
        else:
            value = coerce_slot_value(spec, raw)
        if value is None:
            errors[name] = f"{raw_text!r} cannot be accepted for this field."
        else:
            accepted[name] = value
    return accepted, errors


def apply_polish_text(blob: Dict[str, Any], raw: str, original: str) -> Dict[str, Any]:
    """校验一张卡的润色。违规则整张退回系统英文。

    Parameters
    ----------
    blob : dict
        系统英文澄清卡。
    raw : str
        模型原文。
    original : str
        这个 Task 里用户最初那句。有汉字则润色必须是中文。

    Returns
    -------
    dict
        可用的澄清卡。
    """

    if not isinstance(blob, dict):
        return blob
    if not raw or "[fake-llm]" in raw:
        return blob
    payload = _parse_json(raw)
    if not isinstance(payload, dict):
        return blob
    visible = json.dumps(payload, ensure_ascii=False)
    if _CJK.search(str(original or "")):
        if not _CJK.search(visible):
            return blob
    elif _CJK.search(visible):
        return blob
    new_pending = payload.get("pending")
    old_pending = [item for item in (blob.get("pending") or []) if isinstance(item, dict)]
    if not isinstance(new_pending, list) or len(new_pending) != len(old_pending):
        return blob
    merged: List[Dict[str, Any]] = []
    for old, new in zip(old_pending, new_pending):
        if not isinstance(new, dict) or str(new.get("name") or "") != str(old.get("name") or ""):
            return blob
        old_opts = [item for item in (old.get("options") or []) if isinstance(item, dict)]
        if "options" in new:
            new_opts = new.get("options")
        else:
            new_opts = old_opts
        if not isinstance(new_opts, list) or len(new_opts) != len(old_opts):
            return blob
        relabeled: List[Dict[str, Any]] = []
        for old_opt, new_opt in zip(old_opts, new_opts):
            if not isinstance(new_opt, dict) or str(new_opt.get("id")) != str(old_opt.get("id")):
                return blob
            relabeled.append(
                {
                    "id": old_opt.get("id"),
                    "label": str(new_opt.get("label") or old_opt.get("label") or old_opt.get("id") or ""),
                }
            )
        row = dict(old)
        if new.get("label"):
            row["label"] = str(new.get("label"))
        if new.get("hint") is not None:
            row["hint"] = str(new.get("hint") or "")
        if "error" in new:
            row["error"] = str(new.get("error") or "")
        if old_opts:
            row["options"] = relabeled
        merged.append(row)
    out = dict(blob)
    out["pending"] = merged
    if payload.get("confirm_prompt"):
        out["confirm_prompt"] = str(payload.get("confirm_prompt"))
    return out


def clarification_skips_polish(blob: Dict[str, Any]) -> bool:
    """意图未解恢复卡的句子已经按用户语言写定，不再交给模型改写。"""

    if not isinstance(blob, dict):
        return False
    pending = blob.get("pending")
    if not isinstance(pending, list):
        return False
    return any(
        isinstance(item, dict) and str(item.get("name") or "") in {"unresolved_intent", "wire_choice"}
        for item in pending
    )


def polish_clarification(provider: Any, blob: Dict[str, Any], original: str) -> Dict[str, Any]:
    """有模型且真的出卡时，整张卡润色一次。"""

    if provider is None or not isinstance(blob, dict) or clarification_skips_polish(blob):
        return blob
    raw = provider.chat(
        "Polish this clarification card. Keep every slot name and option id. "
        "You may rewrite the question, hint, error, and option labels. "
        "Do not add or remove options.\n"
        f"Original user text:\n{original}\n"
        f"Card:\n{json.dumps(blob, ensure_ascii=False)}\n"
        "Reply with JSON only.",
    )
    return apply_polish_text(blob, raw, original)


def coerce_slot_value(slot: Dict[str, Any], value: Any) -> Any:
    """按槽的类型、别名、enum 和词表收一个值。收不下则 ``None``。"""

    if value is None:
        return None
    kind = str(slot.get("type") or "string")
    if kind == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"true", "1", "yes"}:
            return True
        if text in {"false", "0", "no"}:
            return False
        return None
    if isinstance(value, bool):
        return None
    if kind == "integer":
        return _as_int(value)
    if kind == "number":
        return _as_float(value)
    if kind not in {"string", ""} and not slot.get("resolve"):
        return value
    text = _joined_text(value)
    if not text:
        return None
    if str(slot.get("resolve") or "") == "dtype":
        return _accept_dtypes(text)
    if slot.get("enum") or slot.get("aliases") or slot.get("vocabulary"):
        return _accept_closed(slot, text)
    return text


def _joined_text(value: Any) -> str:
    """字符串或列表收成逗号分隔文本。列表字面量也拆开。"""

    if isinstance(value, (list, tuple)):
        parts = [str(item).strip() for item in value if str(item).strip() and not isinstance(item, (list, dict))]
        return ",".join(parts)
    text = str(value).strip()
    if len(text) >= 2 and text[0] == "[" and text[-1] == "]":
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError, MemoryError):
            return text
        if isinstance(parsed, (list, tuple)):
            parts = []
            for item in parsed:
                if isinstance(item, (list, dict)):
                    return text
                piece = str(item).strip()
                if piece:
                    parts.append(piece)
            return ",".join(parts)
    return text


def _accept_dtypes(text: str) -> Optional[str]:
    """每个词都要唯一对上数据类型，否则整段不收。"""

    parts = [part.strip() for part in str(text or "").split(",") if part.strip()]
    if not parts:
        return None
    found: List[str] = []
    for part in parts:
        resolved, _missing = resolve_dtype_token(part)
        if not resolved:
            return None
        found.append(resolved)
    return ",".join(found)


def _accept_closed(spec: Dict[str, Any], text: str) -> Optional[str]:
    """别名、enum、词表。有词表时，对不上的字符串不收。"""

    aliases = spec.get("aliases") if isinstance(spec.get("aliases"), dict) else {}
    for key, canon in aliases.items():
        if text == str(key) or text.lower() == str(key).lower():
            return str(canon)
    enum = [str(item) for item in (spec.get("enum") or [])]
    for item in enum:
        if text.lower() == item.lower():
            return item
    vocab = [str(item) for item in (spec.get("vocabulary") or [])]
    for item in vocab:
        if text.lower() == item.lower():
            return item
    if enum and spec.get("enum_strict"):
        return None
    if vocab:
        return None
    return text


def _alias_hit(spec: Dict[str, Any], token: str) -> Optional[str]:
    """这个字段的别名是否收得下这个词。"""

    aliases = spec.get("aliases") if isinstance(spec.get("aliases"), dict) else {}
    for key, canon in aliases.items():
        if token == str(key) or token.lower() == str(key).lower():
            return str(canon)
    return None


def _fill_graph(
    planner: Any,
    steps: List[Any],
    query: str,
    session: Any,
    job: str = "",
) -> Tuple[List[Any], Dict[str, Any]]:
    """填图上还空着的用户槽。缺必填就换成澄清卡。"""

    if _resolve_depends(steps):
        return _unresolved_depends(planner, query)
    if _bind_upstream(planner, steps):
        return _missing_upstream(planner, query)
    rejected = _canonicalize_steps(planner, steps)
    _drop_ungrounded_bounds(planner, steps, query)
    extras: Dict[str, Any] = {}
    projected = _project(planner, steps, rejected)
    confirmed = _confirmed_values(session)
    for slot in projected:
        if slot["filled"] or slot["name"] not in confirmed:
            continue
        value = coerce_slot_value(slot, confirmed[slot["name"]])
        if value is not None and _write_empty(planner, steps, slot["name"], value):
            slot["filled"] = True
            slot["value"] = value
    empty = [slot for slot in projected if not slot["filled"]]
    window_names = _any_of_member_names(planner, steps)
    ask_model = [slot for slot in empty if slot["name"] not in window_names]
    required_empty = [slot for slot in ask_model if slot["required"] or _must_ask(slot, steps)]
    model: Dict[str, Any] = {}
    if required_empty and getattr(planner, "provider", None) is not None:
        parsed = _parse_model_slots(
            planner.provider.chat(_fill_prompt(ask_model, query)),
            [slot["name"] for slot in ask_model],
        )
        model = parsed or {}
    for slot in ask_model:
        if slot["name"] not in model:
            continue
        value = coerce_slot_value(slot, model[slot["name"]])
        if value is not None and _write_empty(planner, steps, slot["name"], value):
            slot["filled"] = True
            slot["value"] = value
    heuristic, ambiguous = _heuristic(
        planner,
        query,
        [slot for slot in projected if not slot["filled"]],
        dtype_query=_utterance_without_slots(query, session),
    )
    for slot in projected:
        if slot["filled"] or slot["name"] not in heuristic:
            continue
        if slot["name"] in {"names", "htype_names"} and ambiguous:
            continue
        value = coerce_slot_value(slot, heuristic[slot["name"]])
        if value is not None and _write_empty(planner, steps, slot["name"], value):
            slot["filled"] = True
            slot["value"] = value
    if _apply_lookback_default(planner, steps, query, projected):
        extras["slot_defaults"] = {"lookback_days": "library"}
    mismatch = align_steps(planner, steps)
    if mismatch:
        return _wire_rejected(planner, steps, query, job, mismatch)
    errors = _take_slot_errors(session)
    open_names = _open_any_of_names(planner, steps, projected)
    pending = _pending_after_fill(projected, steps, ambiguous, errors, query, open_names, rejected)
    if not pending:
        return steps, extras
    extras.pop("slot_defaults", None)
    extras["accepted_steps"] = _accepted_snapshot(steps)
    names = [str(item["name"]) for item in pending]
    hint = str(
        pending[0].get("constraint") or pending[0].get("hint") or clarification_prompt(pending)
    )
    replaced = [
        planner._make_step(
            step_id="step_1",
            skill_name="qt.ai.system.fallback",
            inputs=planner._fallback_step_inputs(
                query=query,
                action="clarify_required",
                reason="missing_required_slots",
                hint=hint,
                missing_info="|".join(names),
                next_step="Fill the fields on the card.",
                details={"slot_pending": pending, "accepted_steps": _accepted_snapshot(steps)},
            ),
        )
    ]
    return replaced, extras


def _wire_rejected(
    planner: Any,
    steps: List[Any],
    query: str,
    job: str,
    mismatch: str,
) -> Tuple[List[Any], Dict[str, Any]]:
    """线接不上。开放图出选择卡，闭合菜谱只留错误说明。"""

    if job == "open":
        card = choice_card(planner, steps, query)
        replaced = [
            planner._make_step(
                step_id="step_1",
                skill_name="qt.ai.system.fallback",
                inputs=planner._fallback_step_inputs(
                    query=query,
                    action="clarify_required",
                    reason="wire_choice",
                    hint=str(card.get("confirm_prompt") or ""),
                    missing_info="none",
                    next_step="Choose how to continue.",
                    details={"clarification": card},
                ),
            )
        ]
        return replaced, {"clarification": card}
    replaced = [
        planner._make_step(
            step_id="step_1",
            skill_name="qt.ai.system.fallback",
            inputs=planner._fallback_step_inputs(
                query=query,
                action="clarify_required",
                reason="wire_product_mismatch",
                hint=mismatch,
                missing_info="none",
                next_step="This recipe connects steps that do not share a declared wire.",
            ),
        )
    ]
    return replaced, {
        "clarification": {
            "restatement": f"You asked: {query}",
            "pending": [],
            "confirm_prompt": mismatch,
        }
    }


def _recovery_clarification(query: str) -> Dict[str, Any]:
    """Job 没认出来时的固定三选。原句含汉字则整张用中文。"""

    chinese = bool(_CJK.search(str(query or "")))
    if chinese:
        prompt = _RECOVERY_ZH
        compose = "给出开放计划"
        abandon = "放弃"
        rewrite = "重写需求"
        label = "开放计划"
    else:
        prompt = _RECOVERY_EN
        compose = "Create an open plan"
        abandon = "Abandon"
        rewrite = "Rewrite the request"
        label = "Open plan"
    return {
        "restatement": f"You asked: {query}",
        "pending": [
            {
                "name": "unresolved_intent",
                "label": label,
                "hint": "",
                "error": "",
                "type": "string",
                "options": [
                    {"id": "compose_open", "label": compose},
                    {"id": "abandon", "label": abandon},
                ],
                "open": {"label": rewrite},
            }
        ],
        "confirm_prompt": prompt,
    }


def _rewrite_fallback(planner: Any, steps: List[Any], query: str) -> Tuple[List[Any], Dict[str, Any]]:
    """无槽的澄清不再长出 supported_skill。下载缺日期改成 start 与 end。"""

    step = steps[0]
    inputs = dict(step.inputs or {})
    info = str(inputs.get("missing_info") or "")
    reason = str(inputs.get("reason") or "")
    if reason == "wire_choice":
        details = inputs.get("details") if isinstance(inputs.get("details"), dict) else {}
        card = details.get("clarification") if isinstance(details, dict) else None
        if isinstance(card, dict):
            inputs["missing_info"] = "none"
            inputs["hint"] = str(card.get("confirm_prompt") or "")
            step.inputs = inputs
            return steps, {"clarification": card}
        return steps, {}
    hint = str(inputs.get("hint") or "")
    action = str(inputs.get("fallback_action") or "")
    if info == "date_range" or reason == "refill_date_range_required":
        inputs["missing_info"] = "start|end"
        inputs["hint"] = _DATE_HINT
        inputs["details"] = {"slot_pending": date_pending_rows()}
        step.inputs = inputs
        return steps, {}
    if action == "clarify_required" and info in {"", "none"} and not reason.startswith("open_"):
        prompt = hint or "Please rephrase the request."
        return steps, {
            "clarification": {
                "restatement": f"You asked: {query}",
                "pending": [],
                "confirm_prompt": prompt,
            }
        }
    if info not in {"supported_skill", "supported_screen_conditions"} and not reason.startswith("open_"):
        return steps, {}
    if action == "clarify_required" and info == "supported_skill" and not reason.startswith("open_"):
        card = _recovery_clarification(query)
        inputs["missing_info"] = "none"
        inputs["hint"] = str(card.get("confirm_prompt") or "")
        step.inputs = inputs
        return steps, {"clarification": card}
    if reason.startswith("open_"):
        prompt = f"Open plan was rejected ({reason}). {hint} Rephrase the request.".strip()
    elif reason == "screen_extra_conditions_not_supported":
        prompt = hint or "PE/market-cap/volume/formula filters are not supported in this stage."
    else:
        prompt = _REPHRASE
    inputs["missing_info"] = "none"
    inputs["hint"] = prompt
    step.inputs = inputs
    return steps, {
        "clarification": {
            "restatement": f"You asked: {query}",
            "pending": [],
            "confirm_prompt": prompt,
        }
    }


def _pending_after_fill(
    projected,
    steps,
    ambiguous,
    errors,
    query,
    open_names: Optional[Set[str]] = None,
    rejected: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """必填仍空、窗口组全空、取值被拒、方向不明或回看不是整数时出题。"""

    opened = open_names or set()
    refused = rejected or set()
    rows: List[Dict[str, Any]] = []
    seen = set()
    for slot in projected:
        if slot["filled"]:
            continue
        ask = (
            slot["required"]
            or slot["name"] in opened
            or slot["name"] in refused
            or _must_ask(slot, steps)
            or slot["name"] == "lookback_days" and _bad_lookback(query)
        )
        if not ask:
            continue
        if slot["name"] in seen:
            continue
        seen.add(slot["name"])
        error = str(errors.get(slot["name"]) or "")
        if slot["name"] in {"names", "htype_names"} and ambiguous and not error:
            error = f"{ambiguous[0]} does not match a single data type."
        if slot["name"] == "lookback_days" and _bad_lookback(query) and not error:
            error = f"{_bad_lookback(query)!r} is not an integer."
        rows.append(_pending_row(slot, error))
    return rows


def _must_ask(slot: Dict[str, Any], steps: Sequence[Any]) -> bool:
    """谓词已经有阈值、但方向还空着时，要问 metric。"""

    if slot["name"] != "metric" or slot.get("filled"):
        return False
    for step in steps:
        if step.skill_name != "qt.ai.research.price_predicate":
            continue
        if (step.inputs or {}).get("threshold") not in (None, ""):
            return True
    return False


def _apply_lookback_default(planner: Any, steps: Sequence[Any], query: str, projected: Sequence[Dict[str, Any]]) -> bool:
    """没说回看天数时写入 126，不追问。说了但不是整数则不写。"""

    if _bad_lookback(query):
        return False
    for slot in projected:
        if slot["name"] == "lookback_days" and slot["filled"]:
            return False
    wrote = False
    for step in steps:
        if step.skill_name != "qt.ai.research.price_predicate":
            continue
        if (step.inputs or {}).get("lookback_days") not in (None, ""):
            continue
        step.inputs["lookback_days"] = 126
        wrote = True
    if wrote:
        for slot in projected:
            if slot["name"] == "lookback_days":
                slot["filled"] = True
                slot["value"] = 126
    return wrote


def _project(
    planner: Any,
    steps: Sequence[Any],
    rejected: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """按图上的 inputs_schema 投影。同名键并成一格，已有值写回空位。"""

    refused = rejected or set()
    order: List[str] = []
    by_name: Dict[str, Dict[str, Any]] = {}
    for step in steps:
        if step.skill_name == "qt.ai.system.fallback":
            continue
        schema = _schema(planner, step.skill_name)
        grouped = _any_of_member_names(planner, [step])
        for key, spec in schema.items():
            if key in _SKIP or not isinstance(spec, dict):
                continue
            required = bool(spec.get("required"))
            if not required and key not in _FILLABLE and key not in grouped and key not in refused:
                continue
            current = (step.inputs or {}).get(key)
            filled = current not in (None, "", [])
            extra = _spec_extras(spec)
            row = by_name.get(key)
            if row is None:
                row = {
                    "name": key,
                    "type": str(spec.get("type") or "string"),
                    "required": required,
                    "enum": [str(item) for item in (spec.get("enum") or [])],
                    "enum_strict": bool(spec.get("enum_strict")),
                    "filled": filled,
                    "value": current if filled else None,
                }
                row.update(extra)
                by_name[key] = row
                order.append(key)
            else:
                row["required"] = bool(row["required"] or required)
                if spec.get("enum") and not row["enum"]:
                    row["enum"] = [str(item) for item in spec.get("enum") or []]
                    row["enum_strict"] = bool(spec.get("enum_strict"))
                for extra_key, extra_value in extra.items():
                    if not row.get(extra_key):
                        row[extra_key] = extra_value
                if filled and not row["filled"]:
                    row["filled"] = True
                    row["value"] = current
    for name, row in by_name.items():
        if row["filled"]:
            _write_empty(planner, steps, name, row["value"])
    return [by_name[name] for name in order]


def _utterance_without_slots(query: str, session: Any) -> str:
    """数据类型解析用的原句。已确认槽拼上的 ``key value`` 不参与。"""

    text = str(query or "").strip()
    task = getattr(session, "task", None)
    slots = getattr(task, "slots", {}) or {} if task is not None else {}
    parts: List[str] = []
    for key, slot in slots.items():
        value = getattr(slot, "value", None)
        if value in (None, ""):
            continue
        parts.append(f"{key} {value}")
    suffix = " ".join(parts)
    if suffix and text.endswith(suffix):
        return text[: -len(suffix)].strip()
    return text


def _heuristic(
    planner: Any,
    query: str,
    slots: Sequence[Dict[str, Any]],
    dtype_query: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[str]]:
    """按槽的类型从问句收值。覆盖不全时留下仍缺的必填。"""

    wanted = {slot["name"] for slot in slots}
    found: Dict[str, Any] = {}
    market = planner._market_inputs(query)
    for key in ("shares", "start", "end", "freq"):
        if key in wanted and market.get(key) not in (None, ""):
            found[key] = market[key]
    if "symbols" in wanted and market.get("shares"):
        found["symbols"] = market["shares"]
    screen = _parse_screen(query)
    for key in ("industry", "threshold", "metric", "lookback_days"):
        if key in wanted and screen.get(key) not in (None, ""):
            found[key] = screen[key]
    ambiguous: List[str] = []
    if "names" in wanted or "htype_names" in wanted:
        joined, ambiguous = _resolve_phrase(query if dtype_query is None else dtype_query)
        if joined and not ambiguous:
            if "names" in wanted:
                found["names"] = joined
            if "htype_names" in wanted:
                found["htype_names"] = joined
    return found, ambiguous


def _parse_screen(query: str) -> Dict[str, Any]:
    """筛股问句里的天数、阈值、方向和行业原话。"""

    text = str(query or "")
    lower = text.lower()
    found: Dict[str, Any] = {}
    if any(item in lower for item in ("半年", "6个月", "六个月", "six months")):
        found["lookback_days"] = 126
    elif any(item in lower for item in ("3个月", "三个月", "一季度", "3 months")):
        found["lookback_days"] = 63
    elif any(item in lower for item in ("1年", "一年", "过去一年", "one year")):
        found["lookback_days"] = 252
    else:
        day = _LOOKBACK_DAY.search(lower)
        if day:
            found["lookback_days"] = int(day.group(1))
    drop = re.search(
        r"(?:跌幅|drawdown|drop)\s*[>≥>=]{0,2}\s*(\d+(?:\.\d+)?)\s*%?",
        text,
        flags=re.IGNORECASE,
    )
    gain = re.search(
        r"(?:涨幅|gain|rally)\s*[>≥>=]{0,2}\s*(\d+(?:\.\d+)?)\s*%?",
        text,
        flags=re.IGNORECASE,
    )
    if drop:
        found["metric"] = "drawdown"
        found["threshold"] = float(drop.group(1)) / 100.0
    elif gain:
        found["metric"] = "gain"
        found["threshold"] = float(gain.group(1)) / 100.0
    else:
        if re.search(r"跌|drawdown|\bdrop\b", text, flags=re.IGNORECASE):
            found["metric"] = "drawdown"
        elif re.search(r"涨|gain|\brally\b", text, flags=re.IGNORECASE):
            found["metric"] = "gain"
        percent = re.search(r"(\d+(?:\.\d+)?)\s*[%％]", text)
        if percent:
            found["threshold"] = float(percent.group(1)) / 100.0
    industry = re.search(r"行业(?:属于|为|是|:|：)\s*([^\s，,。的]+)", text)
    if industry is None:
        industry = re.search(
            r"industry\s*(?:is|=|:|：)\s*([A-Za-z0-9_\u4e00-\u9fff]+)",
            text,
            flags=re.IGNORECASE,
        )
    if industry is None:
        industry = re.search(r"industry\s+([^\s,，。]+)", text, flags=re.IGNORECASE)
    if industry is not None:
        found["industry"] = industry.group(1).strip()
    else:
        for word in re.findall(r"[\u4e00-\u9fff]{2,12}业", text):
            if word != "行业":
                found["industry"] = word
                break
    return found


def _bad_lookback(query: str) -> str:
    """用户明确给了回看、但收不成整数时返回那个词。"""

    if _parse_screen(query).get("lookback_days") not in (None, ""):
        return ""
    match = _BAD_LOOKBACK.search(str(query or ""))
    if match is None:
        return ""
    token = match.group(1).strip("，,。")
    if re.fullmatch(r"\d+", token) or _LOOKBACK_DAY.fullmatch(token):
        return ""
    return token


def _resolve_phrase(query: str) -> Tuple[str, List[str]]:
    """整词对上数据类型。有词对不上时不写下只对上的那一部分。"""

    resolved: List[str] = []
    ambiguous: List[str] = []
    for token in dtype_tokens(query):
        value, missing = resolve_dtype_token(token)
        if value and value not in resolved:
            resolved.append(value)
        elif missing and missing not in ambiguous:
            ambiguous.append(missing)
    if ambiguous:
        return "", ambiguous
    return ",".join(resolved), []


def resolve_dtype_token(token: str) -> Tuple[str, str]:
    """唯一数据类型 id 才返回。``name`` 多个候选时不写成 ``stock_name``。"""

    key = str(token or "").strip()
    if not key:
        return "", ""
    exact = _exact_ids(_find_frame(key), key)
    if key.lower() == "name":
        candidates = set(exact)
        if _exact_ids(_find_frame("stock_name"), "stock_name"):
            candidates.add("stock_name")
        if candidates == {"stock_name"}:
            return "stock_name", ""
        return "", "name"
    if len(exact) == 1:
        return exact[0], ""
    if len(exact) > 1:
        return "", key
    if key.lower() in {"industry", "close", "pe", "cn_gdp", "list_date", "north_money", "stock_name"}:
        return key.lower(), ""
    return "", key


def peek_channel(tokens: Sequence[str]) -> str:
    """用数据类型候选看该走 static、reference 还是 history。"""

    from .intents.recipes import _recommended_channel

    for token in tokens:
        resolved, _missing = resolve_dtype_token(token)
        if resolved:
            channel = _recommended_channel(resolved)
            if channel:
                return channel
        low = token.lower()
        if low in {"industry", "list_date", "stock_name", "name"} or resolved in {"industry", "list_date", "stock_name"}:
            return "static"
        if low in {"cn_gdp", "north_money"} or resolved in {"cn_gdp", "north_money"}:
            return "reference"
        if low in {"close", "pe"} or resolved in {"close", "pe"}:
            return "history"
    return ""


def _pending_row(slot: Dict[str, Any], error: str = "") -> Dict[str, Any]:
    """系统出的一格。选项只在被追问时挂上。"""

    name = str(slot.get("name") or "")
    shown = date_bound_presentation(name) if name in {"start", "end"} else {}
    row: Dict[str, Any] = {
        "name": name,
        "label": str(slot.get("label") or shown.get("label") or _LABELS.get(name, name)),
        "hint": str(slot.get("hint") or shown.get("hint") or _HINTS.get(name) or f"Please provide {name}."),
        "error": str(error or ""),
        "type": str(slot.get("type") or "string"),
        "enum": [str(item) for item in (slot.get("enum") or [])],
        "enum_strict": bool(slot.get("enum_strict")),
    }
    if slot.get("format") or shown.get("format"):
        row["format"] = str(slot.get("format") or shown.get("format"))
    if slot.get("example") or shown.get("example"):
        row["example"] = str(slot.get("example") or shown.get("example"))
    if slot.get("constraint"):
        row["constraint"] = str(slot.get("constraint"))
    if slot.get("resolve"):
        row["resolve"] = str(slot.get("resolve"))
    if isinstance(slot.get("aliases"), dict) and slot.get("aliases"):
        row["aliases"] = {str(key): str(value) for key, value in slot["aliases"].items()}
    if slot.get("vocabulary"):
        row["vocabulary"] = [str(item) for item in slot.get("vocabulary") or []]
    options = _options_for(name, slot)
    if options:
        row["options"] = options
    return row


def _options_for(name: str, slot: Dict[str, Any]) -> List[Dict[str, str]]:
    """这一格的选项。数据类型不给样例。"""

    if name in {"names", "htype_names"}:
        return []
    if name == "strategy_id":
        ids = strategy_id_options()
    elif name == "industry":
        ids = industry_option_ids()
    elif name in {"table_name", "tables"}:
        ids = table_option_ids()
    else:
        ids = [str(item) for item in (slot.get("enum") or [])]
    return [{"id": item, "label": item} for item in ids[:5]]


def _option_ids(spec: Dict[str, Any]) -> List[str]:
    """卡片上的选项 id。"""

    return [str(item.get("id")) for item in (spec.get("options") or []) if isinstance(item, dict) and item.get("id") is not None]


def _fill_prompt(slots: Sequence[Dict[str, Any]], query: str) -> str:
    """填槽提示只列出还空着的投影槽。"""

    lines = [_FILL_PREFIX]
    for slot in slots:
        lines.append(f"slot: {slot['name']}")
    lines.append("User text:")
    lines.append(str(query or ""))
    lines.append("Reply with a JSON object. Keys must be the slot names above.")
    return "\n".join(lines)


def _card_prompt(raws: Dict[str, Any]) -> str:
    """澄清提交的一次解析。每个格子只回到自己的槽名。"""

    lines = ["Parse these clarification answers into the same slot names."]
    for name, value in raws.items():
        lines.append(f"slot {name}: {value}")
    lines.append("Reply with a JSON object. Do not move an answer from one slot to another.")
    return "\n".join(lines)


def _parse_model_slots(raw: str, names: Sequence[str]) -> Optional[Dict[str, Any]]:
    """模型填槽或点选解析。非法、分类罐头或占位回复返回 ``None``。"""

    if not raw or "[fake-llm]" in raw:
        return None
    payload = _parse_json(raw)
    if not isinstance(payload, dict):
        return None
    source = payload.get("slots") if isinstance(payload.get("slots"), dict) else payload
    if not isinstance(source, dict):
        return None
    wanted = {str(name) for name in names}
    if ("job" in payload or "steps" in payload) and not wanted.intersection(source):
        return None
    found = {name: source[name] for name in wanted if name in source}
    if not found:
        return None
    return found


def _parse_json(text: str) -> Optional[Dict[str, Any]]:
    """从模型文本里取一个 JSON 对象。"""

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
    except json.JSONDecodeError:
        start = blob.find("{")
        end = blob.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(blob[start : end + 1])
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def _confirmed_values(session: Any) -> Dict[str, Any]:
    """已确认槽。投影得到的名字也能写回，不限于行情四键。"""

    task = getattr(session, "task", None) if session is not None else None
    slots = getattr(task, "slots", {}) or {} if task is not None else {}
    found: Dict[str, Any] = {}
    for key, slot in slots.items():
        if not getattr(slot, "confirmed", False):
            continue
        value = getattr(slot, "value", None)
        if value not in (None, ""):
            found[str(key)] = value
    return found


def _take_slot_errors(session: Any) -> Dict[str, str]:
    """读出上一张卡没收下的原因，并用掉，避免下一轮还贴着。"""

    task = getattr(session, "task", None) if session is not None else None
    flags = getattr(task, "flags", None) if task is not None else None
    if not isinstance(flags, dict):
        return {}
    raw = flags.pop("_slot_errors", None)
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items() if value}


def _metadata(planner: Any, skill_name: str) -> Any:
    """技能 metadata。读不到则为 ``None``。"""

    try:
        return planner.registry.get_metadata(skill_name)
    except Exception:
        return None


def _schema(planner: Any, skill_name: str) -> Dict[str, Any]:
    """技能的 inputs_schema。读不到则为空。"""

    meta = _metadata(planner, skill_name)
    if meta is None:
        return {}
    return dict(getattr(meta, "inputs_schema", None) or {})


def _any_of_groups(planner: Any, skill_name: str) -> List[List[str]]:
    """技能声明的「至少填一个」分组。"""

    meta = _metadata(planner, skill_name)
    raw = getattr(meta, "any_of", None) if meta is not None else None
    groups: List[List[str]] = []
    for group in raw or []:
        names = [str(item) for item in group if str(item).strip()]
        if names:
            groups.append(names)
    return groups


def _any_of_member_names(planner: Any, steps: Sequence[Any]) -> Set[str]:
    """这些步骤上 any_of 组里的槽名。"""

    names: Set[str] = set()
    for step in steps:
        if getattr(step, "skill_name", "") == "qt.ai.system.fallback":
            continue
        for group in _any_of_groups(planner, step.skill_name):
            names.update(group)
    return names


def _open_any_of_names(planner: Any, steps: Sequence[Any], projected: Sequence[Dict[str, Any]]) -> Set[str]:
    """一组里每一个都还空着时，这些槽名要追问。"""

    filled = {str(slot.get("name") or ""): bool(slot.get("filled")) for slot in projected}
    opened: Set[str] = set()
    for step in steps:
        if getattr(step, "skill_name", "") == "qt.ai.system.fallback":
            continue
        for group in _any_of_groups(planner, step.skill_name):
            if all(not filled.get(name) for name in group):
                opened.update(group)
    return opened


def _spec_extras(spec: Dict[str, Any]) -> Dict[str, Any]:
    """投影时带上 hint、取值标记、别名和词表。"""

    extra: Dict[str, Any] = {}
    if spec.get("label"):
        extra["label"] = str(spec.get("label"))
    if spec.get("hint"):
        extra["hint"] = str(spec.get("hint"))
    if spec.get("format"):
        extra["format"] = str(spec.get("format"))
    if spec.get("example"):
        extra["example"] = str(spec.get("example"))
    if spec.get("constraint"):
        extra["constraint"] = str(spec.get("constraint"))
    if spec.get("resolve"):
        extra["resolve"] = str(spec.get("resolve"))
    aliases = spec.get("aliases") if isinstance(spec.get("aliases"), dict) else {}
    if aliases:
        extra["aliases"] = {str(key): str(value) for key, value in aliases.items()}
    if spec.get("vocabulary"):
        extra["vocabulary"] = [str(item) for item in spec.get("vocabulary") or []]
    return extra


def _needs_upstream(schema: Dict[str, Any]) -> bool:
    """schema 是否声明要读上一步的面板。"""

    return bool(_UPSTREAM_KEYS.intersection(schema))


def _resolve_depends(steps: Sequence[Any]) -> str:
    """把 ``depends_on`` 收成更早一步的 ``step_id``。收不拢则返回原因码。"""

    for index, step in enumerate(steps):
        if step.skill_name == "qt.ai.system.fallback":
            continue
        raw = [str(item).strip() for item in (getattr(step, "depends_on", None) or [])]
        raw = [item for item in raw if item]
        if not raw:
            step.depends_on = []
            continue
        earlier = list(steps[:index])
        earlier_ids = {str(item.step_id) for item in earlier}
        resolved: List[str] = []
        for token in raw:
            if token in earlier_ids:
                resolved.append(token)
                continue
            matches = [str(item.step_id) for item in earlier if str(item.skill_name) == token]
            if len(matches) == 1:
                resolved.append(matches[0])
                continue
            return "unresolved_depends"
        step.depends_on = resolved
    return ""


def _unresolved_depends(planner: Any, query: str) -> Tuple[List[Any], Dict[str, Any]]:
    """依赖对不上更早的步骤号时整单拒绝。"""

    prompt = (
        "Open plan was rejected (unresolved_depends). "
        "depends_on must name an earlier step_id. "
        "Rephrase the request."
    )
    steps = [
        planner._make_step(
            step_id="step_1",
            skill_name="qt.ai.system.fallback",
            inputs=planner._fallback_step_inputs(
                query=query,
                action="clarify_required",
                reason="unresolved_depends",
                hint=prompt,
                missing_info="none",
                next_step="Rephrase the request so each dependency is an earlier step_id.",
            ),
        )
    ]
    return steps, {
        "clarification": {
            "restatement": f"You asked: {query}",
            "pending": [],
            "confirm_prompt": prompt,
        }
    }


def _bind_upstream(planner: Any, steps: Sequence[Any]) -> str:
    """消费步没有边时接到上一步。第一步就是消费步则返回原因码。"""

    for index, step in enumerate(steps):
        if step.skill_name == "qt.ai.system.fallback":
            continue
        schema = _schema(planner, step.skill_name)
        if not _needs_upstream(schema):
            continue
        if list(getattr(step, "depends_on", None) or []):
            continue
        if index == 0:
            return "missing_upstream"
        step.depends_on = [steps[index - 1].step_id]
    return ""


def _missing_upstream(planner: Any, query: str) -> Tuple[List[Any], Dict[str, Any]]:
    """没有上一步的消费步整单拒绝。"""

    prompt = (
        "Open plan was rejected (missing_upstream). "
        "A step that reads the previous panel has no previous step. "
        "Rephrase the request."
    )
    steps = [
        planner._make_step(
            step_id="step_1",
            skill_name="qt.ai.system.fallback",
            inputs=planner._fallback_step_inputs(
                query=query,
                action="clarify_required",
                reason="missing_upstream",
                hint=prompt,
                missing_info="none",
                next_step="Rephrase the request so the first step does not need an earlier panel.",
            ),
        )
    ]
    return steps, {
        "clarification": {
            "restatement": f"You asked: {query}",
            "pending": [],
            "confirm_prompt": prompt,
        }
    }


def _canonicalize_steps(planner: Any, steps: Sequence[Any]) -> Set[str]:
    """按契约收图上已有的值。收不下的键删掉，并记入被拒槽名。"""

    rejected: Set[str] = set()
    for step in steps:
        if step.skill_name == "qt.ai.system.fallback":
            continue
        schema = _schema(planner, step.skill_name)
        inputs = step.inputs if isinstance(step.inputs, dict) else None
        if inputs is None:
            continue
        for key, spec in list(schema.items()):
            if key in _SKIP or not isinstance(spec, dict) or str(spec.get("resolve") or "") == "dtype":
                continue
            if key not in inputs:
                continue
            kind = str(spec.get("type") or "string")
            if kind not in {"string", "integer", "number", "boolean"}:
                continue
            original = inputs.get(key)
            accepted = coerce_slot_value(spec, original)
            if accepted is None:
                inputs.pop(key, None)
                if original not in (None, "", []):
                    rejected.add(key)
            else:
                inputs[key] = accepted
        for key, spec in list(schema.items()):
            if key in _SKIP or not isinstance(spec, dict) or str(spec.get("resolve") or "") != "dtype":
                continue
            if key not in inputs:
                continue
            original = inputs.get(key)
            raw = _joined_text(original)
            accepted = _accept_dtypes(raw) if raw else None
            if accepted:
                inputs[key] = accepted
                continue
            _relocate_alias(schema, inputs, raw)
            inputs.pop(key, None)
            if original not in (None, "", []):
                rejected.add(key)
    return rejected


def _relocate_alias(schema: Dict[str, Any], inputs: Dict[str, Any], raw: str) -> None:
    """频率说法写进数据类型槽时，挪到对应字段。已有合法值则不覆盖。"""

    token = str(raw or "").strip()
    if not token or "," in token:
        return
    for name, spec in schema.items():
        if name in _SKIP or not isinstance(spec, dict) or str(spec.get("resolve") or "") == "dtype":
            continue
        canon = _alias_hit(spec, token)
        if canon is None:
            continue
        current = inputs.get(name)
        if current in (None, "", []):
            inputs[name] = canon
        elif coerce_slot_value(spec, current) is None:
            inputs[name] = canon
        return


def _drop_ungrounded_bounds(planner: Any, steps: Sequence[Any], query: str) -> None:
    """any_of 组里的值只有问句也能抽出同样的值时才留下。"""

    market = planner._market_inputs(query) if hasattr(planner, "_market_inputs") else {}
    if not isinstance(market, dict):
        market = {}
    for step in steps:
        if step.skill_name == "qt.ai.system.fallback":
            continue
        inputs = step.inputs if isinstance(step.inputs, dict) else None
        if inputs is None:
            continue
        for group in _any_of_groups(planner, step.skill_name):
            for name in group:
                current = inputs.get(name)
                if current in (None, "", []):
                    continue
                if str(market.get(name) or "") == str(current):
                    continue
                inputs.pop(name, None)


def _accepted_snapshot(steps: Sequence[Any]) -> List[Dict[str, Any]]:
    """澄清前的步骤，供核对规范化后的输入和边。"""

    rows: List[Dict[str, Any]] = []
    for step in steps:
        if step.skill_name == "qt.ai.system.fallback":
            continue
        inputs = {
            str(key): value
            for key, value in (step.inputs or {}).items()
            if key not in _SKIP
        }
        rows.append(
            {
                "step_id": step.step_id,
                "skill_name": step.skill_name,
                "inputs": inputs,
                "depends_on": [str(item) for item in (step.depends_on or [])],
            }
        )
    return rows


def contract_digest_lines(planner: Any, names: Sequence[str]) -> List[str]:
    """从同一份 metadata 生成开放组图用的短摘要。

    Parameters
    ----------
    planner : Planner
        用来读技能 metadata。
    names : sequence of str
        允许出现的技能名。

    Returns
    -------
    list of str
        每只技能一行：必填、any_of、enum、是否消费上游。
    """

    lines: List[str] = []
    for name in names:
        meta = _metadata(planner, str(name))
        if meta is None:
            continue
        schema = dict(getattr(meta, "inputs_schema", None) or {})
        required = [
            key
            for key, spec in schema.items()
            if isinstance(spec, dict) and spec.get("required") and key not in _SKIP
        ]
        enums = [
            f"{key}:{'|'.join(str(item) for item in (spec.get('enum') or []))}"
            for key, spec in schema.items()
            if isinstance(spec, dict) and spec.get("enum")
        ]
        groups = _any_of_groups(planner, str(name))
        bits = [str(name)]
        if required:
            bits.append("required=" + ",".join(required))
        if groups:
            bits.append("any_of=" + ";".join("|".join(group) for group in groups))
        if enums:
            bits.append("enum=" + ",".join(enums))
        if _needs_upstream(schema):
            bits.append("needs_upstream")
        wire_bits = format_wire_digest(meta)
        if wire_bits:
            bits.append(wire_bits)
        lines.append(" ".join(bits))
    return lines


def _write_empty(planner: Any, steps: Sequence[Any], name: str, value: Any) -> bool:
    """把值写进仍空着的同名输入。已有值不动。"""

    wrote = False
    for step in steps:
        schema = _schema(planner, step.skill_name)
        if name not in schema or name in _SKIP:
            continue
        current = (step.inputs or {}).get(name)
        if current not in (None, "", []):
            continue
        step.inputs[name] = value
        wrote = True
    return wrote


def _is_fallback(steps: Sequence[Any]) -> bool:
    """整单是不是一条澄清 fallback。"""

    if len(steps) != 1:
        return False
    step = steps[0]
    if step.skill_name != "qt.ai.system.fallback":
        return False
    return str((step.inputs or {}).get("fallback_action") or "") == "clarify_required"


def _find_frame(name: str) -> Any:
    """按宽名查数据类型。查不到则 ``None``。"""

    try:
        import qteasy as qt

        return qt.find_history_data(name, as_data_frame=True, fuzzy=False)
    except Exception:
        return None


def _exact_ids(frame: Any, key: str) -> List[str]:
    """精确同名的数据类型 id。同名多行只算一个 id。"""

    if frame is None or getattr(frame, "empty", True) or "name" not in getattr(frame, "columns", []):
        return []
    exact = frame[frame["name"].astype(str).str.lower() == str(key).lower()]
    return sorted({str(item) for item in exact["name"].tolist()})


def _as_int(value: Any) -> Optional[int]:
    """收成整数。布尔和小数都不算。"""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip()
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    return None


def _as_float(value: Any) -> Optional[float]:
    """收成数字。"""

    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return float(text)
    return None
