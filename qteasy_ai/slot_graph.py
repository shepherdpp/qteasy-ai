# coding=utf-8
# ======================================
# File: slot_graph.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-03
# Desc:
# 从已组成的步骤图投影用户槽，只做一次填槽，
# 并校验澄清卡的润色与点选。
# ======================================

"""意图已经落到步骤图之后的投影、填槽和澄清卡。

不另写一套槽名单。因子 IC 的手写槽不进这里。
"""

from __future__ import annotations

import ast
import datetime
import json
import re
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Set, Tuple

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
_NEVER_PROJECT = {"page", "layout", "rows", "htypes", "mode"}
_PORTFOLIO_SKILL = "qt.ai.hp.portfolio"
_KLINE_SKILL = "qt.ai.data.kline"
_INDEX_CODES = {
    "000001.SH",
    "000016.SH",
    "000300.SH",
    "000905.SH",
    "000852.SH",
    "399001.SZ",
    "399006.SZ",
    "399300.SZ",
    "399905.SZ",
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
    "weights": "Weights",
    "benchmark": "Benchmark",
    "benchmark_output": "Benchmark output",
    "adj": "Adjustment",
}


def question_label(name: str) -> str:
    """澄清题干用的槽标签。没有登记时退回槽名。"""

    key = str(name or "")
    return str(_LABELS.get(key) or key)


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
    "weights": "Give weights as numbers, such as 6:4. They stay with the held symbols.",
    "benchmark": "Which symbol is the benchmark?",
    "benchmark_output": "tag_along keeps the benchmark beside the portfolio. excess_only keeps only the excess.",
    "adj": "Use an adjustment mark the data call already accepts, such as b or n.",
}
_EXCHANGE_CODE = re.compile(r"\d{6}\.(?:SH|SZ|BJ)", re.IGNORECASE)
_BENCH_TOKEN = r"(沪深\s*300|csi\s*300|\d{6}\.(?:SH|SZ|BJ))"
_BENCHMARK_PHRASE = re.compile(
    r"(?:"
    r"(?:相对|基准|benchmark)\s*[:=：是为]?\s*" + _BENCH_TOKEN +
    r"|以\s*" + _BENCH_TOKEN + r"\s*为\s*基准"
    r")",
    re.IGNORECASE,
)
_WEIGHT_PHRASE = re.compile(
    r"(?:权重|weights|加权)(?:组合)?\s*[:=：]?\s*"
    r"(\d+(?:\.\d+)?[%％]?"
    r"(?:\s*[:：,，比]\s*\d+(?:\.\d+)?[%％]?)+)",
    re.IGNORECASE,
)
_HOLD_COMPARE_JOB = "research.hold_compare"
_DIAGNOSIS_JOBS = {"data.summary", "data.export"}
_DIAGNOSIS_KEYS = {
    "qt.ai.data.kline": {"shares", "start", "end", "freq", "asset_type", "adj"},
    "qt.ai.hp.describe": {"view", "n"},
    "qt.ai.hp.volatility": {
        "window",
        "price_htype",
        "method",
        "annualize",
        "periods_per_year",
    },
    "qt.ai.hp.returns": {"price_htype", "method", "periods", "dropna"},
    "qt.ai.hp.plot": {"highlight", "max_shares_per_figure", "page", "layout"},
}
_DIAGNOSIS_MODEL_SKIP = {
    "window",
    "price_htype",
    "method",
    "annualize",
    "periods_per_year",
    "periods",
    "dropna",
    "view",
    "n",
    "highlight",
    "max_shares_per_figure",
    "page",
    "layout",
    "adj",
}
_DIAGNOSIS_DEFAULTS = {
    "view": "shape",
    "n": 5,
    "window": 20,
    "price_htype": "close",
    "method": "simple",
    "annualize": True,
    "periods": 1,
    "dropna": False,
    "max_shares_per_figure": 5,
    "page": 1,
    "layout": "auto",
}
_RETURN_SKILL = "qt.ai.hp.returns"
_VOL_SKILL = "qt.ai.hp.volatility"
_REPHRASE = "No matching job. Rephrase the request, or ask for a short open plan."
_RECOVERY_ZH = "您的需求无法跟现成的操作模版匹配（job），是否需要我创建一份开放计划？"
_RECOVERY_EN = "This request does not match a built-in operation template (job). Create an open plan?"
_FILL_PREFIX = "Slot protocol. Examples are not values."
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_WINDOW_SPAN = r"(?:(?:\d+|[零〇一二两三四五六七八九十]+)\s*年|一段时间)"
_WINDOW_PHRASE = re.compile(
    rf"(?:过去|近)\s*{_WINDOW_SPAN}|[零〇一二两三四五六七八九十]+\s*年内"
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


FACTOR_IC_SLOT_DECLS: Dict[str, Dict[str, Any]] = {
    "shares": {
        "resolve": "code",
        "min_count": 2,
        "required": True,
        "label": "Symbols",
        "hint": "At least two exchange codes, such as 000001.SZ and 000002.SZ.",
    },
    "start": {
        "format": "YYYYMMDD",
        "required": True,
        "label": "Start date",
        "hint": "A calendar date, such as 20240101.",
    },
    "end": {
        "format": "YYYYMMDD",
        "required": True,
        "label": "End date",
        "hint": "A calendar date, such as 20240331.",
    },
    "factor_htype": {
        "resolve": "column",
        "required": True,
        "label": "Factor column",
        "hint": "One local history column, such as close.",
    },
    "return_htype": {
        "resolve": "column",
        "required": True,
        "label": "Return column",
        "hint": "One different local history column, such as volume.",
    },
}


def code_spec(*, required: bool, element: str = "", min_count: int = 0) -> Dict[str, Any]:
    """代码槽。后缀和别名在同一次填写里收束。

    Parameters
    ----------
    required : bool
        是否必填。
    element : str, optional
        元素类型。有值时计划里存项列表，而不是逗号字符串。
    min_count : int, optional
        至少要有这么多项已确认。

    Returns
    -------
    dict
        带 ``resolve=code`` 的字段。
    """

    spec: Dict[str, Any] = {"type": "string", "required": required, "resolve": "code"}
    if element:
        spec["element"] = element
        spec["cardinality"] = "many"
        spec["min_count"] = int(min_count)
    return spec


def join_code_text(value: Any) -> str:
    """把已确认项的 code 拼成内核要的逗号字符串。

    字符串原样返回。空列表返回空串，让回测和优化仍走自己的缺省池。

    Parameters
    ----------
    value : Any
        计划里的项、项列表，或原来的代码字符串。

    Returns
    -------
    str
        逗号分隔的代码。没有已确认代码时为空串。
    """

    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if str(value.get("status") or "confirmed") != "confirmed":
            return ""
        return str(value.get("code") or "")
    if isinstance(value, (list, tuple)):
        codes: List[str] = []
        for item in value:
            if isinstance(item, dict):
                if str(item.get("status") or "") != "confirmed":
                    continue
                code = str(item.get("code") or "")
            else:
                code = str(item or "").strip()
            if code and code not in codes:
                codes.append(code)
        return ",".join(codes)
    return ""


def weights_spec() -> Dict[str, Any]:
    """权重槽。``mode`` 跟这一格一起提交，不单独投影。

    Returns
    -------
    dict
        带 ``resolve=weights`` 的数组字段。
    """

    return {"type": "array", "required": False, "resolve": "weights"}


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


def kernel_window() -> Dict[str, str]:
    """内核在起止和行数都空着时使用的窗口。

    结束日是今天，开始日是今天减 365 天。不把「过去三年」折成日期。

    Returns
    -------
    dict
        ``start`` 与 ``end``，格式 ``YYYYMMDD``。
    """

    today = datetime.date.today()
    return {
        "end": today.strftime("%Y%m%d"),
        "start": (today - datetime.timedelta(days=365)).strftime("%Y%m%d"),
    }


def window_phrase(query: str) -> bool:
    """问句里有没有窗口说法。只识别，不返回日期。

    Parameters
    ----------
    query : str
        用户原文。

    Returns
    -------
    bool
        出现「过去 / 近 + 年数 + 年」、「过去 / 近一段时间」或中文数字加「年内」时为 True。不折成日期。
    """

    return _WINDOW_PHRASE.search(str(query or "")) is not None




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


def mentions_excess(query: str) -> bool:
    """问句是否要超额。确认槽拼回的 ``benchmark_output excess_only`` 不算。"""

    text = str(query or "")
    if "超额" in text:
        return True
    lowered = text.lower().replace("benchmark_output excess_only", " ")
    return "excess" in lowered


def mentions_cumret(query: str) -> bool:
    """问句是否要累计或累计收益。对数收益不在这里。"""

    text = str(query or "")
    if "累计" in text:
        return True
    lower = text.lower()
    return "cumulative return" in lower or "cumret" in lower


def hold_share_codes(query: str) -> List[str]:
    """问句里的交易所代码和沪深300别名，按出现顺序、不重复。"""

    text = str(query or "")
    hits: List[Tuple[int, str]] = []
    for match in _EXCHANGE_CODE.finditer(text):
        hits.append((match.start(), match.group(0).upper()))
    lowered = text.lower()
    for alias, code in (("沪深300", "000300.SH"), ("csi 300", "000300.SH"), ("csi300", "000300.SH")):
        start = 0
        needle = alias.lower()
        while True:
            pos = lowered.find(needle, start)
            if pos < 0:
                break
            hits.append((pos, code))
            start = pos + len(needle)
    hits.sort(key=lambda item: item[0])
    found: List[str] = []
    for _, code in hits:
        if code not in found:
            found.append(code)
    return found


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


def apply_slot_layer(
    planner: Any,
    steps: List[Any],
    query: str,
    job: str,
    session: Any,
    card_text: Optional[Dict[str, str]] = None,
    card_items: Optional[Dict[str, Any]] = None,
    kept_steps: Optional[Sequence[Dict[str, Any]]] = None,
    carry_steps: Optional[Sequence[Dict[str, Any]]] = None,
) -> Tuple[List[Any], Dict[str, Any]]:
    """投影并填当前图。原句、卡片和澄清跟进共用这一次填写。

    Parameters
    ----------
    planner : Planner
        用来读 schema、造澄清步。
    steps : list
        意图之后的步骤图。
    query : str
        任务原句。解释者不读拼过已确认槽的长句。
    job : str
        已定下的 Job。
    session : ConversationState or None
        已确认槽和上一张卡的冲突说明。
    card_text : dict, optional
        这张卡上的字符串原文，槽名对这一题。
    card_items : dict, optional
        这张卡上的持仓项列表，项上可以有 ``answer``。

    Returns
    -------
    tuple
        ``(steps, extras)``。``extras`` 里可能有无槽澄清卡。
    """

    if _is_fallback(steps):
        return _rewrite_fallback(planner, steps, query)
    return _fill_graph(
        planner,
        steps,
        query,
        session,
        job,
        card_text,
        card_items,
        kept_steps=kept_steps,
        carry_steps=carry_steps,
    )


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
        if "prompt" in old:
            row["prompt"] = old.get("prompt")
        if old.get("index") is not None:
            row["hint"] = str(old.get("hint") or "")
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
    if blob.get("intent_authored") or blob.get("recover_authored") or blob.get("fill_authored"):
        return True
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


def is_history_column(name: str) -> bool:
    """列名是否为可进 HistoryPanel 的 history 数据类型。

    全库只此一份。对不上时返回 False，不把原文当成列名收下。

    Parameters
    ----------
    name : str
        待检查的列名。

    Returns
    -------
    bool
        能作为历史列写入时为 True。
    """

    text = str(name or "").strip()
    if not text:
        return False
    try:
        import qteasy as qt

        frame = qt.find_history_data(text, as_data_frame=True, fuzzy=False)
    except Exception:
        return False
    if frame is None or not hasattr(frame, "iterrows") or bool(getattr(frame, "empty", True)):
        return False
    wanted = text.lower()
    for _, row in frame.iterrows():
        if str(row.get("name") or "").lower() != wanted:
            continue
        if str(row.get("kind") or "") != "history":
            continue
        flags = {part.strip() for part in str(row.get("usable_in") or "").split(",") if part.strip()}
        if "history_panel" in flags:
            return True
    return False


def accept_slot_value(slot: Dict[str, Any], value: Any, source: str) -> Any:
    """按槽上已有的一项合同收值。收不下则 ``None``。

    分发不读 ``value_kind``、Job 名或槽名。有 ``element`` 时先按项列表，
    不把 ``holdings`` 收成代码文本。没有 ``element`` 的 ``resolve=code``
    才写成代码文本，只数不够就不写入。``format`` 为日期时走
    ``accept_yyyymmdd``。``resolve=weights`` 走 ``commit_weight_text``。
    ``resolve=column`` 走这一份 ``is_history_column``。有 ``aliases`` 或
    ``enum`` 时只调用一次 ``_accept_closed``。没有上述合同的字符串原样收下。

    Parameters
    ----------
    slot : dict
        投影槽或卡片上的一题。
    value : any
        解释者交出的值，或这一题的原文。
    source : str
        这一题原文或任务原句。日期例子和代码是否写过都对照这段。

    Returns
    -------
    any
        可以写入的值。项列表可以仍未完成。没有合法值时为 ``None``。
    """

    if value is None:
        return None
    if slot.get("element"):
        return _accept_element_value(slot, value, source)
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
    resolve = str(slot.get("resolve") or "")
    if resolve == "code":
        return _accept_code_text(slot, value, source)
    if str(slot.get("format") or "") == "YYYYMMDD":
        example = str(
            slot.get("example") or date_bound_presentation(str(slot.get("name") or "")).get("example") or ""
        )
        return accept_yyyymmdd(value, example, source)
    if resolve == "weights":
        if isinstance(value, dict) and str(value.get("mode") or "") == "equal":
            return {"mode": "equal"}
        if isinstance(value, (list, tuple)):
            weights = _as_weight_list(value)
            return weights or None
        parsed = commit_weight_text(_joined_text(value) or str(source or ""))
        if parsed["status"] != "value":
            return None
        if parsed["values"].get("mode") == "equal":
            return {"mode": "equal"}
        weights = list(parsed["values"].get("weights") or [])
        return weights or None
    if resolve == "column":
        text = str(value or "").strip()
        if text and is_history_column(text):
            return text
        return None
    if resolve == "dtype":
        text = _joined_text(value)
        return _accept_dtypes(text) if text else None
    if kind not in {"string", ""} and not resolve:
        return value
    text = _joined_text(value)
    if not text:
        return None
    if slot.get("aliases") or slot.get("enum") or slot.get("vocabulary"):
        return _accept_closed(slot, text)
    return text


def _accept_code_text(slot: Dict[str, Any], value: Any, source: str) -> Optional[str]:
    """没有元素合同的代码槽。只数不够就不写入。"""

    text = _normalize_code_value(value, source or _joined_text(value))
    if not text:
        return None
    codes = [part for part in text.split(",") if part]
    minimum = int(slot.get("min_count") or 0)
    if minimum and len(codes) < minimum:
        return None
    return text


def _accept_element_value(slot: Dict[str, Any], value: Any, source: str) -> Any:
    """项列表。每一项都重新过代码规则，已确认不能跳过。"""

    items = _as_item_list(value)
    if items and any(isinstance(item, dict) and str(item.get("answer") or "").strip() for item in items):
        updated: List[Dict[str, Any]] = []
        for item in items:
            row = dict(item)
            answer = str(row.get("answer") or "").strip()
            if not answer:
                updated.append(_tag_submitted_item(row, source))
                continue
            code = _one_reviewed_code(answer)
            if code:
                row["code"] = code
                row["status"] = "confirmed"
                row.pop("error", None)
            else:
                row["error"] = f"{answer!r} is not one exchange code."
                row["status"] = "incomplete"
            updated.append(row)
        if str(slot.get("cardinality") or "") == "one" or str(slot.get("element") or "") == "comparison_code":
            return updated[0]
        return updated
    return _items_from_submitted(value, source, slot)


def coerce_slot_value(slot: Dict[str, Any], value: Any) -> Any:
    """按槽的合同收一个值。对照原文用值本身，避免把已写下的合法值再拒一次。"""

    source = "" if value is None else str(value)
    return accept_slot_value(slot, value, source)


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


_FILL_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "600519 和 000858 做一条等权组合": {
        "holdings": ["600519", "000858"],
        "mode": "equal",
    },
    "000001.SZ 和 000002.SZ 做一条等权组合，相对沪深300": {
        "holdings": ["000001.SZ", "000002.SZ"],
        "mode": "equal",
        "benchmark": "沪深300",
        "benchmark_output": "tag_along",
    },
    "000001.SZ 和 000002.SZ 做一条等权组合，相对沪深300，看超额": {
        "holdings": ["000001.SZ", "000002.SZ"],
        "mode": "equal",
        "benchmark": "沪深300",
        "benchmark_output": "excess_only",
    },
    "000001.SZ 和 000002.SZ 做一条等权组合，相对沪深300，看超额和累计收益": {
        "holdings": ["000001.SZ", "000002.SZ"],
        "mode": "equal",
        "benchmark": "沪深300",
        "benchmark_output": "excess_only",
    },
    "000001.SZ 和 000002.SZ 按权重 6:4 做一条组合，看累计收益": {
        "holdings": ["000001.SZ", "000002.SZ"],
        "weights": "6:4",
    },
    "factor IC of close vs volume for 000001.SZ,000002.SZ from 20240101 to 20240331": {
        "shares": "000001.SZ,000002.SZ",
        "factor_htype": "close",
        "return_htype": "volume",
        "start": "20240101",
        "end": "20240331",
    },
}


def _exact_sentence_candidates(query: str) -> Dict[str, Any]:
    """整句相等时返回一份常量候选。对不上就是空字典。

    不切分原句，也不调用代码、权重或基准解析。调用方改得到的列表不会写回这张表。

    Parameters
    ----------
    query : str
        任务原句。只做整句相等。

    Returns
    -------
    dict
        槽名到常量。没有这一句时为空字典。
    """

    found = _FILL_TEMPLATES.get(str(query or ""))
    if not found:
        return {}
    copied: Dict[str, Any] = {}
    for key, value in found.items():
        copied[key] = list(value) if isinstance(value, list) else value
    return copied


def _portfolio_needs_weight(slot: Dict[str, Any], steps: Sequence[Any]) -> bool:
    """组合步既没有 mode 也没有权重列表时，权重格仍要问。

    不读任务原句。等权或加权已经写在步骤上时不再问。

    Parameters
    ----------
    slot : dict
        当前投影槽。
    steps : sequence
        当前步骤。

    Returns
    -------
    bool
        这一格是权重，并且组合步上还没有 mode 或数字权重。
    """

    if str(slot.get("name") or "") != "weights" or slot.get("filled"):
        return False
    saw_portfolio = False
    for step in steps:
        if step.skill_name != _PORTFOLIO_SKILL:
            continue
        saw_portfolio = True
        inputs = step.inputs if isinstance(step.inputs, dict) else {}
        if str(inputs.get("mode") or "") in {"equal", "weighted"}:
            return False
        if _as_weight_list(inputs.get("weights")):
            return False
    return saw_portfolio


_NOT_GIVEN = "用户未明确给出"


def _user_source_text(sentence: str, history: Sequence[Dict[str, Any]]) -> str:
    """质检对照用的用户原文：办事原文加上历次回答，不从里面再抽候选。"""

    parts = [str(sentence or "")]
    for turn in history or []:
        if not isinstance(turn, dict):
            continue
        for row in turn.get("slots") or []:
            if not isinstance(row, dict):
                continue
            answer = row.get("answer")
            if isinstance(answer, str) and answer.strip():
                parts.append(answer)
            elif isinstance(answer, list):
                parts.append(_kept_element_source(answer))
    return "\n".join(part for part in parts if part)


def _judge_slots(
    projected: Sequence[Dict[str, Any]],
    steps: Sequence[Any],
    candidates: Dict[str, Any],
    mentioned: Set[str],
    sentence: str,
    history: Sequence[Dict[str, Any]],
    held_back: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """同一次判断。收下的是 value 和 source，拒绝的是理由字符串。

    空着的必填用现有拒因。点到了但没有值才写「用户未明确给出」。
    没点到又有缺省声明的格子在这一次收下，来源是 default。
    """

    accepted: Dict[str, Dict[str, Any]] = {}
    rejected: Dict[str, str] = {}
    held = held_back or {}
    user_text = _user_source_text(sentence, history)
    for slot in projected:
        name = str(slot.get("name") or "")
        if not name:
            continue
        if name in held and name not in mentioned:
            rejected[name] = _reject_reason(slot, held[name])
            continue
        if name in mentioned:
            raw = candidates.get(name)
            if raw in (None, "", []):
                rejected[name] = _NOT_GIVEN
                continue
            source = user_text
            if slot.get("element"):
                value = accept_slot_value(slot, raw, source)
            else:
                value = accept_slot_value(slot, raw, source)
            if value in (None, "", []):
                rejected[name] = _reject_reason(slot, raw)
                continue
            accepted[name] = {"value": value, "source": "user"}
            continue
        current = _read_input(steps, name)
        if current not in (None, "", []):
            if isinstance(current, (list, dict)):
                source = _kept_element_source(current)
            else:
                source = str(current)
            checked = accept_slot_value(slot, current, source)
            if checked in (None, "", []):
                rejected[name] = _reject_reason(slot, current)
            continue
        mode_ready = str((candidates or {}).get("mode") or "") in {"equal", "weighted"}
        if _portfolio_needs_weight(slot, steps) and not mode_ready:
            rejected[name] = _reject_reason(slot, "")
            continue
        metric_open = (
            name == "metric"
            and (
                _must_ask(slot, steps)
                or (candidates or {}).get("threshold") not in (None, "", [])
            )
        )
        if metric_open or slot.get("required"):
            rejected[name] = _reject_reason(slot, "")
            continue
        if not _has_declared_default(slot):
            continue
        value = _slot_default_value(slot)
        if value in (None, "", []):
            rejected[name] = _reject_reason(slot, "" if value in (None, "") else value)
            continue
        checked = accept_slot_value(
            slot,
            value,
            "" if isinstance(value, (list, dict)) else str(value),
        )
        if checked in (None, "", []):
            rejected[name] = _reject_reason(slot, value)
            continue
        accepted[name] = {"value": checked, "source": "default"}
    return {"accepted": accepted, "rejected": rejected}


def _apply_judged(
    planner: Any,
    steps: Sequence[Any],
    projected: Sequence[Dict[str, Any]],
    report: Dict[str, Any],
    candidates: Dict[str, Any],
) -> None:
    """把收下的 value 写回步骤。被拒的格子清掉。mode 只在权重没被拒时写入。"""

    accepted = report.get("accepted") if isinstance(report.get("accepted"), dict) else {}
    rejected = report.get("rejected") if isinstance(report.get("rejected"), dict) else {}
    by_name = {str(slot.get("name") or ""): slot for slot in projected}
    for name, item in accepted.items():
        if not isinstance(item, dict):
            continue
        value = item.get("value")
        slot = by_name.get(str(name))
        if slot is None:
            continue
        if str(slot.get("resolve") or "") == "weights" and isinstance(value, dict):
            if str(value.get("mode") or "") == "equal":
                _clear_on_skill(steps, _PORTFOLIO_SKILL, "weights")
                _set_on_skill(steps, _PORTFOLIO_SKILL, "mode", "equal")
            slot["filled"] = True
            slot["value"] = value
            continue
        _write_element(planner, steps, str(name), value)
        slot["value"] = value
        slot["filled"] = _element_complete(slot, value) if slot.get("element") else True
    for name in rejected:
        _clear_slot(planner, steps, str(name))
        slot = by_name.get(str(name))
        if slot is not None:
            slot["filled"] = False
            slot["value"] = None
    if "weights" in rejected:
        return
    mode = str((candidates or {}).get("mode") or "")
    if mode in {"equal", "weighted"}:
        if mode == "equal":
            _clear_on_skill(steps, _PORTFOLIO_SKILL, "weights")
        _set_on_skill(steps, _PORTFOLIO_SKILL, "mode", mode)
        planner._fill_mode = mode


def _model_fill_candidates(
    planner: Any,
    steps: Sequence[Any],
    projected: Sequence[Dict[str, Any]],
    sentence: str,
    history: Sequence[Dict[str, Any]],
    revision_query: str,
) -> Tuple[Dict[str, Any], str]:
    """有模型时只调用一次填槽协议。回答在提示词里，不按槽名交成候选。"""

    slots = [slot for slot in projected if str(slot.get("name") or "")]
    raw = planner.provider.chat(
        _fill_prompt(
            planner,
            slots,
            sentence,
            history,
            revision_query=revision_query,
            accepted=_shown_accepted(steps, projected),
        )
    )
    parsed = _parse_model_slots(raw, [str(slot.get("name") or "") for slot in slots]) or {}
    return parsed, str(raw or "")


def _open_slot_answers(history: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """每个槽的最后一条。有回答且 error 为空时，这条还没被质检拒绝。"""

    last: Dict[str, Dict[str, Any]] = {}
    for turn in history or []:
        if not isinstance(turn, dict):
            continue
        for row in turn.get("slots") or []:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "")
            if name:
                last[name] = row
    found: Dict[str, Dict[str, Any]] = {}
    for name, row in last.items():
        answer = row.get("answer")
        if answer in (None, "", []):
            continue
        if str(row.get("error") or "").strip():
            continue
        found[name] = row
    return found


def _static_fill_candidates(
    sentence: str,
    history: Sequence[Dict[str, Any]],
) -> Tuple[Dict[str, Any], str, str]:
    """没有模型。还没有澄清时查金句表；已有澄清时只取最后一条回答。"""

    if history:
        last = history[-1] if isinstance(history[-1], dict) else {}
        found: Dict[str, Any] = {}
        for row in last.get("slots") or []:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "")
            if name:
                found[name] = row.get("answer")
        return found, "card", ""
    found = _exact_sentence_candidates(sentence)
    return found, "template", sentence if found else ""


def _fill_cycle(
    planner: Any,
    steps: Sequence[Any],
    projected: Sequence[Dict[str, Any]],
    sentence: str,
    history: Sequence[Dict[str, Any]],
    revision_query: str = "",
    model_revision: bool = False,
    held_back: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """一圈只出一次候选，再质检一次。不按任务名分叉，也不写计划记录。"""

    provider = getattr(planner, "provider", None)
    if provider is not None and model_revision:
        candidates, protocol = _read_model_revision(
            planner, steps, projected, sentence, revision_query
        )
        source = "model"
    elif provider is not None:
        candidates, protocol = _model_fill_candidates(
            planner, steps, projected, sentence, history, revision_query
        )
        source = "model"
    else:
        candidates, source, protocol = _static_fill_candidates(sentence, history)
    open_rows = _open_slot_answers(history)
    for name, row in open_rows.items():
        candidates[name] = row.get("answer")
    mentioned = {str(key) for key in candidates if str(key) != "mode"}
    report = _judge_slots(
        projected,
        steps,
        candidates,
        mentioned,
        sentence,
        history,
        held_back,
    )
    rejected = report.get("rejected") if isinstance(report.get("rejected"), dict) else {}
    for name, row in open_rows.items():
        reason = str(rejected.get(name) or "")
        if not reason or reason == _NOT_GIVEN:
            continue
        row["error"] = reason
    debug = {
        "fill_source": sentence,
        "history": [dict(item) for item in history if isinstance(item, dict)],
        "candidate_source": source,
        "protocol": protocol,
        "candidates": dict(candidates),
        "reasons": dict(report.get("rejected") or {}),
    }
    planner._fill_debug_entry = debug
    return {"report": report, "candidates": candidates, "debug": debug}


def _open_label(text: str) -> Dict[str, str]:
    """澄清卡上的开放输入。"""

    return {"label": "其它" if _CJK.search(str(text or "")) else "Other"}


def _dumb_rows(
    projected: Sequence[Dict[str, Any]],
    rejected: Mapping[str, str],
    sentence: str,
) -> List[Dict[str, Any]]:
    """弱智卡。说明和拒因都是拒绝理由。没有合同缺省就不编缺省项。"""

    by_name = {str(slot.get("name") or ""): slot for slot in projected}
    rows: List[Dict[str, Any]] = []
    for name, reason in rejected.items():
        slot = by_name.get(str(name)) or {"name": str(name)}
        lead = reason == _NOT_GIVEN and _has_declared_default(slot)
        row = _pending_row(slot, reason, sentence, lead_default=lead)
        row["prompt"] = reason
        row["error"] = reason
        if "open" not in row:
            row["open"] = _open_label(sentence)
        rows.append(row)
    return rows


def _card_prompt(
    sentence: str,
    history: Sequence[Dict[str, Any]],
    accepted: Mapping[str, Any],
    rejected: Mapping[str, str],
    projected: Sequence[Dict[str, Any]],
) -> str:
    """出卡提示词。先写目标和字段含义，再列出被拒槽的材料。"""

    by_name = {str(slot.get("name") or ""): slot for slot in projected}
    lines = [
        "Clarification protocol.",
        "Write the questions the user will see. Do not fill slots and do not choose the answer.",
        (
            "For every rejected slot, write one question in the user's language. "
            "explanation says why you ask, what was unclear, and what a clear answer looks like. "
            "options are likely choices: id from the legal ids below, label in the user's language. "
            "open is the label of a free-text answer. Do not ask about Accepted slots."
        ),
        "reason: why this round was refused. Explain it. The card shows this text separately.",
        (
            "contract, enum: legal ids you may offer. "
            "If contract is empty, offer choices that fit format and constraint."
        ),
        "format, constraint: the rule to explain.",
        "example: an illustration to mention, not a preselected answer.",
        "default: the declared default. Offer it when the user has not given a value.",
        "Task sentence: the original request. It does not change.",
        str(sentence or ""),
        (
            "Clarification history: earlier questions and the user's answers. "
            "error is why that answer was refused."
        ),
    ]
    lines.extend(_history_lines(history))
    lines.append("Accepted: values already kept. Do not ask about these.")
    shown = {}
    for name, item in accepted.items():
        if isinstance(item, dict):
            shown[name] = item.get("value")
    lines.extend(_accepted_lines(shown))
    lines.append("Rejected: slots that failed this round. Write one question for each.")
    for name, reason in rejected.items():
        slot = by_name.get(str(name)) or {"name": str(name)}
        ids = [str(item.get("id")) for item in _options_for(str(name), slot)]
        lines.append(f"name={name}")
        lines.append(f"reason={reason}")
        lines.append("contract=" + ",".join(ids))
        if slot.get("format"):
            lines.append(f"format={slot.get('format')}")
        if slot.get("example"):
            lines.append(f"example={slot.get('example')}")
        if slot.get("constraint"):
            lines.append(f"constraint={slot.get('constraint')}")
        if slot.get("enum"):
            lines.append("enum=" + ",".join(str(item) for item in slot.get("enum") or []))
        if _has_declared_default(slot):
            lines.append(f"default={_default_label(slot)}")
    lines.append("Reply with one question object per rejected slot:")
    lines.append(
        '{"questions":[{"name":"<slot>","explanation":"...","options":'
        '[{"id":"...","label":"..."}],"open":{"label":"..."}}]}'
    )
    lines.append("name must be the rejected slot name.")
    return "\n".join(lines)


def _parse_card_questions(
    raw: str,
    rejected: Mapping[str, str],
) -> List[Dict[str, Any]]:
    """抄下协议里已经写到的被拒槽。没写到的不补行。

    不是 JSON，或没有一题对上被拒槽时，返回空列表。
    """

    if not raw or "[fake-llm]" in raw:
        return []
    payload = _parse_json(raw)
    questions = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(questions, list):
        return []
    by_q: Dict[str, Dict[str, Any]] = {}
    for item in questions:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if name in rejected and name not in by_q:
            by_q[name] = item
    rows: List[Dict[str, Any]] = []
    for name, reason in rejected.items():
        item = by_q.get(str(name))
        if not isinstance(item, dict):
            continue
        choices = item.get("options") if isinstance(item.get("options"), list) else []
        opened = item.get("open") if isinstance(item.get("open"), dict) else None
        row: Dict[str, Any] = {
            "name": str(name),
            "prompt": str(item.get("explanation") or "").strip(),
            "error": reason,
            "options": [dict(opt) for opt in choices if isinstance(opt, dict)],
        }
        if opened:
            row["open"] = dict(opened)
        rows.append(row)
    return rows


def _model_clarification(
    planner: Any,
    projected: Sequence[Dict[str, Any]],
    sentence: str,
    history: Sequence[Dict[str, Any]],
    accepted: Mapping[str, Any],
    rejected: Mapping[str, str],
) -> List[Dict[str, Any]]:
    """有模型时只出一次引导问句。写到的被拒槽留下，没写到的不补。"""

    if not rejected:
        return []
    debug = getattr(planner, "_fill_debug_entry", None)
    if not isinstance(debug, dict):
        debug = {}
        planner._fill_debug_entry = debug
    raw = planner.provider.chat(
        _card_prompt(sentence, history, accepted, rejected, projected)
    )
    debug["card_protocol"] = str(raw or "")
    return _parse_card_questions(raw, rejected) or []


def _author_clarification(
    planner: Any,
    projected: Sequence[Dict[str, Any]],
    sentence: str,
    history: Sequence[Dict[str, Any]],
    accepted: Mapping[str, Any],
    rejected: Mapping[str, str],
) -> List[Dict[str, Any]]:
    """有拒绝才出卡。没有模型时出弱智卡。有模型时只叫一次出卡。不写槽。"""

    debug = getattr(planner, "_fill_debug_entry", None)
    if not isinstance(debug, dict):
        debug = {}
        planner._fill_debug_entry = debug
    provider = getattr(planner, "provider", None)
    if provider is None:
        if not rejected:
            return []
        debug["dumb_card"] = True
        return _dumb_rows(projected, rejected, sentence)
    return _model_clarification(
        planner, projected, sentence, history, accepted, rejected
    )


def _remember_fill_record(
    planner: Any,
    status: str,
    report: Dict[str, Any],
    history: Sequence[Dict[str, Any]],
    questions: Sequence[Dict[str, Any]],
) -> None:
    """这一圈的用户可见记录先放在规划器上，由 finalize_plan 写入计划。"""

    slots: List[Dict[str, Any]] = []
    for name, item in (report.get("accepted") or {}).items():
        if not isinstance(item, dict):
            continue
        slots.append({"name": str(name), "value": item.get("value"), "source": item.get("source")})
    mode = str(getattr(planner, "_fill_mode", "") or "")
    if mode in {"equal", "weighted"} and not any(item.get("name") == "mode" for item in slots):
        slots.append({"name": "mode", "value": mode, "source": "user"})
    planner._fill_mode = ""
    planner._fill_record = {
        "status": status,
        "slots": slots,
        "questions": [dict(item) for item in questions if isinstance(item, dict)],
        "answers": [dict(item) for item in history if isinstance(item, dict)],
    }


def _fill_graph(
    planner: Any,
    steps: List[Any],
    query: str,
    session: Any,
    job: str = "",
    card_text: Optional[Dict[str, str]] = None,
    card_items: Optional[Dict[str, Any]] = None,
    kept_steps: Optional[Sequence[Dict[str, Any]]] = None,
    carry_steps: Optional[Sequence[Dict[str, Any]]] = None,
) -> Tuple[List[Any], Dict[str, Any]]:
    """填图上还空着的用户槽。缺必填就换成澄清卡。

    ``card_text`` 是这张卡上的字符串原文。``card_items`` 是带 ``answer`` 的项列表。
    有模型时，候选只来自这一次协议；没有模型且没有卡片时，只查整句金句表。
    协议或金句没交出的槽保持未完成。没被点到、槽上又有声明的格子仍走缺省。
    """

    if _resolve_depends(steps):
        return _unresolved_depends(planner, query)
    if _bind_upstream(planner, steps):
        return _missing_upstream(planner, query)
    incoming: Dict[str, Any] = {}
    for step in steps:
        inputs = getattr(step, "inputs", None)
        if not isinstance(inputs, dict):
            continue
        for key, value in inputs.items():
            if value not in (None, "", []) and key not in incoming:
                incoming[key] = value
    rejected = _canonicalize_steps(planner, steps)
    if kept_steps is not None:
        overlay_kept_inputs(steps, kept_steps)
    extras: Dict[str, Any] = {}
    projected = _project(planner, steps, rejected, job)
    confirmed = _confirmed_values(session)
    recipe_htype = ""
    for step in steps:
        if step.skill_name == "qt.ai.data.history":
            recipe_htype = str((step.inputs or {}).get("htype_names") or "") or recipe_htype
    if carry_steps is not None:
        for step in steps:
            if isinstance(getattr(step, "inputs", None), dict):
                step.inputs.pop("shares", None)
    prewritten: Dict[str, Any] = {}
    for slot in projected:
        name = str(slot.get("name") or "")
        if not name or name in confirmed:
            continue
        current = _read_input(steps, name)
        if current not in (None, "", []):
            prewritten[name] = current
    _clear_open_prewrite(steps, projected, confirmed, kept_steps=kept_steps)
    closed_items: Dict[str, Any] = {}
    held_back: Dict[str, Any] = {}
    for slot in projected:
        if slot["filled"] or slot["name"] not in confirmed:
            continue
        if carry_steps is not None and slot["name"] == "shares":
            continue
        raw = confirmed[slot["name"]]
        if slot.get("element"):
            closed_items[slot["name"]] = raw
            continue
        if slot["name"] == "weights" and isinstance(raw, dict) and str(raw.get("mode") or "") == "equal":
            _set_on_skill(steps, _PORTFOLIO_SKILL, "mode", "equal")
            slot["filled"] = True
            slot["value"] = raw
            continue
        value = accept_slot_value(slot, raw, "" if isinstance(raw, (list, dict)) else str(raw))
        if value is None:
            held_back[slot["name"]] = raw
            continue
        if _write_empty(planner, steps, slot["name"], value):
            slot["filled"] = True
            slot["value"] = value
    for name, raw in confirmed.items():
        if carry_steps is not None and name == "shares":
            continue
        if any(str(slot.get("name") or "") == name for slot in projected):
            continue
        _write_empty(planner, steps, name, raw)
    for name, raw in prewritten.items():
        slot = next((item for item in projected if str(item.get("name") or "") == name), None)
        if slot is None or name in held_back:
            continue
        source = _kept_element_source(raw) if isinstance(raw, (list, dict)) else str(raw)
        if accept_slot_value(slot, raw, source) in (None, "", []):
            held_back[name] = raw
    for name, raw in incoming.items():
        if name in prewritten or name in held_back:
            continue
        slot = next((item for item in projected if str(item.get("name") or "") == name), None)
        if slot is None:
            continue
        source = _kept_element_source(raw) if isinstance(raw, (list, dict)) else str(raw)
        if accept_slot_value(slot, raw, source) in (None, "", []):
            held_back[name] = raw
    if kept_steps is not None or carry_steps is not None:
        if carry_steps is not None:
            carry_confirmed_inputs(planner, carry_steps, steps, session)
            if recipe_htype and not dtype_tokens(query):
                for step in steps:
                    if step.skill_name != "qt.ai.data.history":
                        continue
                    if str((step.inputs or {}).get("htype_names") or "").strip():
                        continue
                    step.inputs["htype_names"] = recipe_htype
        _sync_projected(planner, steps, projected)
    sentence = str(query or "")
    history: List[Dict[str, Any]] = []
    task = getattr(session, "task", None) if session is not None else None
    if task is not None:
        stored = str(getattr(task, "fill_source", "") or "")
        if stored:
            sentence = stored
        history = [
            dict(item)
            for item in (getattr(task, "clarify_history", None) or [])
            if isinstance(item, dict)
        ]
    revision_query = str(getattr(planner, "_revision_query", "") or "")
    model_revision = (
        getattr(planner, "provider", None) is not None
        and not history
        and (kept_steps is not None or carry_steps is not None)
    )
    for name, raw in list(closed_items.items()):
        _write_element(planner, steps, name, raw)
    cycle = _fill_cycle(
        planner,
        steps,
        projected,
        sentence,
        history,
        revision_query=revision_query,
        model_revision=model_revision,
        held_back=held_back,
    )
    report = cycle["report"]
    candidates = cycle["candidates"]
    confirmed_now = _confirmed_values(session)
    accepted_now = report.get("accepted")
    if isinstance(accepted_now, dict):
        from_template = str((cycle.get("debug") or {}).get("candidate_source") or "") == "template"
        for name, raw in confirmed_now.items():
            item = accepted_now.get(name)
            if from_template and name in candidates and isinstance(item, dict) and item.get("value") != raw:
                accepted_now.pop(name, None)
    _apply_judged(planner, steps, projected, report, candidates)
    _seal_elements(planner, steps, projected, closed_items)
    for step in steps:
        if step.skill_name != _PORTFOLIO_SKILL or not isinstance(step.inputs, dict):
            continue
        normalize_portfolio_weight(step.inputs)
    rejected = dict(report.get("rejected") or {})
    for name in _reject_weight_count(steps):
        rejected.setdefault(name, "Weight count does not match the holdings.")
        _clear_slot(planner, steps, name)
    same_column = reject_same_history_column(projected, set(report.get("accepted") or {}), steps, planner)
    for name, reason in same_column.items():
        rejected.setdefault(str(name), str(reason))
        _clear_slot(planner, steps, str(name))
    accepted = report.get("accepted")
    if isinstance(accepted, dict):
        for name in rejected:
            accepted.pop(str(name), None)
    report["rejected"] = rejected
    defaults = {
        str(name): "default"
        for name, item in (report.get("accepted") or {}).items()
        if isinstance(item, dict) and item.get("source") == "default" and str(name) not in rejected
    }
    item_rows: List[Dict[str, Any]] = []
    for slot in projected:
        extra_rows = _item_pending_rows(slot)
        if extra_rows:
            item_rows.extend(extra_rows)
    need_card = bool(rejected) or bool(item_rows)
    if need_card:
        _remember_diagnosis_defaults(session, projected)
        pending = _author_clarification(
            planner,
            projected,
            sentence,
            history,
            report.get("accepted") or {},
            rejected,
        )
        if getattr(planner, "provider", None) is None or not rejected:
            seen = {str(item.get("name") or "") + ":" + str(item.get("index") or "") for item in pending}
            for row in item_rows:
                key = str(row.get("name") or "") + ":" + str(row.get("index") or "")
                if key not in seen:
                    pending.append(row)
        _remember_fill_record(planner, "clarify", report, history, pending)
        if not pending and not rejected:
            return steps, extras
        extras["accepted_steps"] = _accepted_snapshot(steps)
        names = []
        for item in pending:
            slot_name = str(item.get("name") or "")
            if slot_name and slot_name not in names:
                names.append(slot_name)
        if pending:
            lead = pending[0]
            label = str(lead.get("label") or "")
            detail = str(lead.get("constraint") or lead.get("hint") or "")
            pieces = [label] if label else []
            if detail and detail != label:
                pieces.append(detail)
            hint = "\n".join(pieces)
        else:
            names = [str(name) for name in rejected]
            hint = ""
        replaced = [
            planner._make_step(
                step_id="step_1",
                skill_name="qt.ai.system.fallback",
                inputs=planner._fallback_step_inputs(
                    query="",
                    action="clarify_required",
                    reason="missing_required_slots",
                    hint=hint,
                    missing_info="|".join(names),
                    next_step="Fill the fields on the card.",
                    details={
                        "slot_pending": pending,
                        "accepted_steps": list(extras["accepted_steps"]),
                        "fill_authored": True,
                    },
                ),
            )
        ]
        extras["clarification"] = {
            "restatement": f"You asked: {sentence}",
            "pending": pending,
            "confirm_prompt": hint,
            "fill_authored": True,
        }
        return replaced, extras
    mismatch = align_steps(planner, steps)
    if mismatch:
        _remember_fill_record(planner, "passed", report, history, [])
        return _wire_rejected(planner, steps, sentence, job, mismatch)
    if defaults:
        extras["slot_defaults"] = defaults
    if job in _DIAGNOSIS_JOBS:
        _bake_describe_view(steps, projected)
        _remember_diagnosis_defaults(session, projected)
    if job == _HOLD_COMPARE_JOB:
        _sync_projected(planner, steps, projected)
        _finish_portfolio_graph(steps, sentence)
        _sync_projected(planner, steps, projected)
    code_missing = any(
        str(slot.get("resolve") or "") == "code" and slot.get("required") and not slot.get("filled")
        for slot in projected
    )
    if (
        not getattr(planner, "_wire_resume", False)
        and not code_missing
        and wants_chart(sentence)
        and not any(step.skill_name == "qt.ai.hp.plot" for step in steps)
    ):
        _remember_fill_record(planner, "clarify", report, history, [])
        return _blocked_plan(planner, sentence, "A chart was requested but the plan has no plot step.")
    choice = _statistic_options(steps)
    if choice:
        extras["statistic_options"] = choice
    _remember_fill_record(planner, "passed", report, history, [])
    return steps, extras



def _blocked_plan(planner: Any, query: str, reason: str) -> Tuple[List[Any], Dict[str, Any]]:
    """参数没收下，或要图却没有绘图步。计划不可确认。"""

    replaced = [
        planner._make_step(
            step_id="step_1",
            skill_name="qt.ai.system.fallback",
            inputs=planner._fallback_step_inputs(
                query=query,
                action="clarify_required",
                reason=reason,
                hint=reason,
                missing_info="none",
                next_step="The open plan did not pass the parameter commit.",
            ),
        )
    ]
    return replaced, {}


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
                "prompt": prompt,
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
    job: str = "",
    force_names: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """必填仍空、窗口组全空、取值被拒、方向不明，或提到了却没有合法值时出题。"""

    opened = open_names or set()
    refused = rejected or set()
    forced = force_names or set()
    rows: List[Dict[str, Any]] = []
    seen = set()
    for slot in projected:
        item_rows = _item_pending_rows(slot)
        if item_rows is not None:
            rows.extend(item_rows)
            seen.add(slot["name"])
            continue
        error = str(errors.get(slot["name"]) or "")
        if slot["filled"] and not error:
            continue
        ask = (
            slot["required"]
            or slot["name"] in opened
            or slot["name"] in refused
            or slot["name"] in forced
            or bool(str(errors.get(slot["name"]) or ""))
            or _must_ask(slot, steps)
            or _portfolio_needs_weight(slot, steps)
        )
        if not ask:
            continue
        if slot["name"] in seen:
            continue
        seen.add(slot["name"])
        if slot["name"] in {"names", "htype_names"} and ambiguous and not error:
            error = f"{ambiguous[0]} does not match a single data type."
        rows.append(_pending_row(slot, error, query))
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


def _literal_slot_default(slot: Dict[str, Any]) -> Any:
    """槽上声明的字面缺省。不读技能名。

    Parameters
    ----------
    slot : dict
        投影槽。

    Returns
    -------
    any
        ``default`` 字段。没有则为 ``None``。
    """

    return slot.get("default")


def _kernel_window_slot_default(slot: Dict[str, Any]) -> Any:
    """按槽名从内核窗口取一端。

    Parameters
    ----------
    slot : dict
        投影槽。名字要对上 ``kernel_window`` 的键。

    Returns
    -------
    str or None
        对上的那一端。对不上则为 ``None``。
    """

    return kernel_window().get(str(slot.get("name") or ""))


def _slot_default_value(slot: Dict[str, Any]) -> Any:
    """这一格声明的那一种缺省。有 ``default_kind`` 时不用字面 ``default``。

    Parameters
    ----------
    slot : dict
        投影槽。

    Returns
    -------
    any
        可以写入的缺省。没有对应函数时为 ``None``。
    """

    kind = str(slot.get("default_kind") or "").strip()
    if kind == "kernel_window":
        return _kernel_window_slot_default(slot)
    if kind:
        return None
    if "default" in slot and slot.get("default") not in (None, ""):
        return _literal_slot_default(slot)
    return None


def _project(
    planner: Any,
    steps: Sequence[Any],
    rejected: Optional[Set[str]] = None,
    job: str = "",
) -> List[Dict[str, Any]]:
    """按图上的 inputs_schema 投影。同名键并成一格，已有值写回空位。"""

    refused = rejected or set()
    order: List[str] = []
    by_name: Dict[str, Dict[str, Any]] = {}
    diagnosis = job in _DIAGNOSIS_JOBS
    for step in steps:
        if step.skill_name == "qt.ai.system.fallback":
            continue
        schema = _step_fields(step, _schema(planner, step.skill_name))
        grouped = _any_of_member_names(planner, [step])
        allowed = _DIAGNOSIS_KEYS.get(step.skill_name, set()) if diagnosis else set()
        for key, spec in schema.items():
            if not isinstance(spec, dict) or key in _SKIP:
                continue
            if spec.get("assemble_only") or spec.get("user_slot") is False:
                continue
            if diagnosis and step.skill_name == "qt.ai.hp.plot" and key == "shares":
                continue
            diagnosis_key = diagnosis and key in allowed
            if not diagnosis_key and (key in _NEVER_PROJECT):
                continue
            required = bool(spec.get("required"))
            contract = bool(
                required
                or key in grouped
                or key in refused
                or spec.get("resolve")
                or spec.get("format")
                or spec.get("enum")
                or spec.get("aliases")
                or spec.get("vocabulary")
                or spec.get("element")
                or spec.get("min_count")
            )
            if not diagnosis_key and not contract:
                continue
            current = (step.inputs or {}).get(key)
            if spec.get("element") and current in (None, "", []):
                filled = False
            elif spec.get("element"):
                filled = _element_complete(spec, current)
            elif str(spec.get("resolve") or "") == "code":
                codes = [part for part in str(current or "").split(",") if part.strip()]
                minimum = int(spec.get("min_count") or 0)
                filled = len(codes) >= minimum if minimum else bool(codes)
            else:
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


def _pending_row(
    slot: Dict[str, Any],
    error: str = "",
    query: str = "",
    lead_default: Optional[bool] = None,
) -> Dict[str, Any]:
    """系统出的一格。选项只在被追问时挂上。

    Parameters
    ----------
    slot : dict
        投影槽。
    error : str, optional
        上一轮没收下的原因。
    query : str, optional
        本轮问句。有汉字时，缺省槽的开放输入写「其它」。

    Returns
    -------
    dict
        澄清卡上的一行。
    """

    name = str(slot.get("name") or "")
    shown = date_bound_presentation(name) if name in {"start", "end"} else {}
    label = str(slot.get("label") or shown.get("label") or _LABELS.get(name, name))
    row: Dict[str, Any] = {
        "name": name,
        "label": label,
        "prompt": label,
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
    lead = (
        (not slot.get("required") and _has_declared_default(slot))
        if lead_default is None
        else bool(lead_default) and _has_declared_default(slot)
    )
    if lead:
        shown = _default_label(slot)
        row["default_value"] = shown
        options = [{"id": "default", "label": str(shown)}] + [
            item for item in options if str(item.get("id")) != "default"
        ]
        row["open"] = {"label": "其它" if _CJK.search(str(query or "")) else "Other"}
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


def _history_lines(history: Optional[Sequence[Dict[str, Any]]]) -> List[str]:
    """把历次澄清展开成提示词行。还没有澄清时为空。"""

    lines: List[str] = []
    for turn in history or []:
        if not isinstance(turn, dict):
            continue
        for row in turn.get("slots") or []:
            if not isinstance(row, dict):
                continue
            lines.append(f"name={row.get('name') or ''}")
            lines.append(f"prompt={row.get('prompt') or ''}")
            lines.append(
                "options=" + json.dumps(row.get("options") or [], ensure_ascii=False, default=str)
            )
            lines.append(
                "answer=" + json.dumps(row.get("answer"), ensure_ascii=False, default=str)
            )
            lines.append(f"error={row.get('error') or ''}")
    return lines


def _accepted_lines(accepted: Optional[Mapping[str, Any]]) -> List[str]:
    """已经收下的值，一行一个槽。"""

    lines: List[str] = []
    for name, value in (accepted or {}).items():
        lines.append(f"{name}={json.dumps(value, ensure_ascii=False, default=str)}")
    return lines


def _shown_accepted(steps: Sequence[Any], projected: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """步骤上已经有的值，供提示词的 Accepted 段。"""

    found: Dict[str, Any] = {}
    for slot in projected:
        name = str(slot.get("name") or "")
        if not name:
            continue
        current = _read_input(steps, name)
        if current not in (None, "", []):
            found[name] = current
    return found


def _fill_prompt(
    planner: Any,
    slots: Sequence[Dict[str, Any]],
    query: str,
    history: Optional[Sequence[Dict[str, Any]]] = None,
    revision_query: str = "",
    accepted: Optional[Mapping[str, Any]] = None,
) -> str:
    """一次协议列出投影槽。开头写明目标和字段含义，再给办事原文和历次澄清。

    不再按卡片盖住的槽省略办事原文。修改句另起一行，不写进 ``fill_source``。
    """

    lines = [
        _FILL_PREFIX,
        "Extract only values the user actually named. Do not ask questions. Do not invent or repair a value.",
        (
            "Submit a value only when it appears in the task sentence, the revision, "
            "or a clarification answer. Otherwise submit null. Null means the user did not give one. "
            "Leave out a slot that is already under Accepted unless the user changed it."
        ),
        "enum: legal values. Do not pick one the user did not say.",
        "aliases: use the mapped value only when the user used that word.",
        "format, constraint: what a clear value looks like. Not a value to submit.",
        "example: an illustration. Not a value.",
        "resolve: how the value is stored, such as an exchange code or weights.",
    ]
    for slot in slots:
        bits = [f"slot: {slot['name']}", f"type={slot.get('type') or 'string'}"]
        if slot.get("required"):
            bits.append("required")
        if slot.get("enum"):
            bits.append("enum=" + ",".join(str(item) for item in slot.get("enum") or []))
        if slot.get("aliases"):
            bits.append("aliases=" + ",".join(f"{key}->{value}" for key, value in slot.get("aliases").items()))
        if slot.get("format"):
            bits.append(f"format={slot.get('format')}")
        if slot.get("resolve"):
            bits.append(f"resolve={slot.get('resolve')}")
        if slot.get("example"):
            bits.append(f"example={slot.get('example')} (not a value)")
        if slot.get("constraint"):
            bits.append(f"constraint={slot.get('constraint')}")
        lines.append(" ".join(bits))
    if any(str(slot.get("resolve") or "") == "weights" for slot in slots):
        lines.append("mode is submitted with weights. It is not a separate slot.")
    lines.append("Task sentence: the original request. It does not change.")
    lines.append(str(query or ""))
    if str(revision_query or "").strip():
        lines.append("Revision: the change in this turn, when present.")
        lines.append(str(revision_query))
    lines.append(
        "Clarification history: earlier questions and the user's answers. "
        "error is why that answer was refused. Submit the answer as given. "
        "Do not replace it with a legal value."
    )
    lines.extend(_history_lines(history))
    lines.append("Accepted: values already kept.")
    lines.extend(_accepted_lines(accepted))
    lines.append(
        "Reply with a JSON object whose keys are the slot names above. "
        "Use null for a slot the user did not name."
    )
    return "\n".join(lines)


def _parse_model_slots(raw: str, names: Sequence[str]) -> Optional[Dict[str, Any]]:
    """模型填槽或点选解析。非法、分类罐头或占位回复返回 ``None``。

    键在协议里且值为 null 时保留，值为 ``None``。键不在协议里则不出现。
    """

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
    found = {}
    for name in wanted:
        if name in source:
            found[name] = source[name]
    if source.get("mode") not in (None, ""):
        found["mode"] = source.get("mode")
    if not found:
        return None
    return found


def _read_model_revision(
    planner: Any,
    steps: Sequence[Any],
    projected: Sequence[Dict[str, Any]],
    query: str,
    revision_query: str = "",
) -> Tuple[Dict[str, Any], str]:
    """有模型且没有澄清时的修改句。这一次协议就是候选，不再另叫填槽。

    缺键留给质检：已经收下的值不在这里清掉。协议原文交给这一圈的 debug。

    Parameters
    ----------
    planner : planner
        带语言模型的规划器。
    steps : sequence
        当前步骤。只用来读已经写下的值。
    projected : sequence of dict
        当前图上的投影槽。
    query : str
        办事原文 ``fill_source``。
    revision_query : str, optional
        这一句修改。不写进 ``fill_source``。

    Returns
    -------
    tuple
        解析出的槽名到值，以及协议原文。
    """

    slots = [slot for slot in projected if str(slot.get("name") or "")]
    raw = planner.provider.chat(
        _fill_prompt(
            planner,
            slots,
            query,
            None,
            revision_query=revision_query,
            accepted=_shown_accepted(steps, projected),
        )
    )
    parsed = _parse_model_slots(raw, [str(slot.get("name") or "") for slot in slots]) or {}
    return parsed, str(raw or "")


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


def _step_fields(step: Any, schema: Dict[str, Any]) -> Dict[str, Any]:
    """共享 schema 被这一步的槽声明盖过。声明不进 inputs。"""

    fields = {
        key: dict(spec) if isinstance(spec, dict) else spec
        for key, spec in (schema or {}).items()
    }
    decls = getattr(step, "slot_decls", None) or {}
    if not isinstance(decls, dict):
        return fields
    for key, decl in decls.items():
        name = str(key)
        if not isinstance(decl, dict) or name not in fields:
            continue
        base = dict(fields.get(name) or {})
        base.update(decl)
        fields[name] = base
    return fields


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
    """一组里每一个都还空着时，这些槽名要追问。

    带缺省的选填槽不因此入题。用户提到了却没有合法值时，另由 force 出题。
    """

    filled = {str(slot.get("name") or ""): bool(slot.get("filled")) for slot in projected}
    by_name = {str(slot.get("name") or ""): slot for slot in projected}
    opened: Set[str] = set()
    for step in steps:
        if getattr(step, "skill_name", "") == "qt.ai.system.fallback":
            continue
        for group in _any_of_groups(planner, step.skill_name):
            if not all(not filled.get(name) for name in group):
                continue
            for name in group:
                slot = by_name.get(name) or {}
                if not slot.get("required") and _has_declared_default(slot):
                    continue
                opened.add(name)
    return opened


def _has_declared_default(slot: Dict[str, Any]) -> bool:
    """这一格是否声明了缺省值或内核缺省。

    Parameters
    ----------
    slot : dict
        投影槽或 schema 字段。

    Returns
    -------
    bool
        有 ``default`` 或 ``default_kind`` 时为 True。
    """

    if str(slot.get("default_kind") or "").strip():
        return True
    return "default" in slot and slot.get("default") not in (None, "")


def _unresolved_optional_defaults(projected: Sequence[Dict[str, Any]], mentioned: Set[str]) -> Set[str]:
    """提到了但没有合法值，并且选填、声明了缺省的槽。

    Parameters
    ----------
    projected : sequence of dict
        投影槽。
    mentioned : set of str
        解释者交出的槽名。不读任务名或技能名。

    Returns
    -------
    set of str
        要并进 force 的槽名。
    """

    found: Set[str] = set()
    for slot in projected:
        name = str(slot.get("name") or "")
        if name not in mentioned or slot.get("required") or not _has_declared_default(slot):
            continue
        found.add(name)
    return found


def _source_names_date(digits: str, source: str) -> bool:
    """对照文本里有没有能收成这同一个八位日期的写法。

    八位本身、去掉分隔符后仍是这八位、``YYYY年M月D日``，以及年份边界
    （某年到某年的两端、``今年`` 的两端、``到某年`` 的年末、单独某年的两端）
    算收得成。``过去两年`` 这类说法不算。

    Parameters
    ----------
    digits : str
        已经通过日历检查的八位。
    source : str
        对照文本。第四 B 步复查时是步骤上已经写下的那八位，不是用户原句。

    Returns
    -------
    bool
        收得成这同一个日期时为 True。
    """

    text = str(source or "")
    if len(digits) != 8 or not text:
        return False
    if re.search(rf"(?<!\d){re.escape(digits)}(?!\d)", text):
        return True
    for match in re.finditer(r"(20\d{2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{1,2})", text):
        formed = f"{int(match.group(1)):04d}{int(match.group(2)):02d}{int(match.group(3)):02d}"
        if formed == digits:
            return True
    for match in re.finditer(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text):
        formed = f"{int(match.group(1)):04d}{int(match.group(2)):02d}{int(match.group(3)):02d}"
        if formed == digits:
            return True
    return digits in _named_year_bounds(text)


def _named_year_bounds(text: str) -> Set[str]:
    """对照文本里，年份边界已经会写出的八位日期。

    跟市场日期抽取同一套先后：年份区间、``今年``、``到某年`` 只给年末、
    单独某年给两端。``某年某月`` 不按整年收。

    Parameters
    ----------
    text : str
        对照文本。

    Returns
    -------
    set of str
        这些写法对应的八位。没有则为空集。
    """

    year_range = re.search(
        r"(20\d{2})\s*年?\s*(?:[~\-–—]|至|到|to)\s*(20\d{2})\s*年?",
        text,
        flags=re.IGNORECASE,
    )
    if year_range:
        first = int(year_range.group(1))
        second = int(year_range.group(2))
        if first <= second:
            return {f"{first:04d}0101", f"{second:04d}1231"}
        return set()
    if "今年" in text:
        year = datetime.date.today().year
        return {f"{year:04d}0101", f"{year:04d}1231"}
    end_bound = re.search(
        r"(?:到|至|until|\bto\b)\s*(20\d{2})\s*年?",
        text,
        flags=re.IGNORECASE,
    )
    if end_bound is not None and not re.match(r"\s*\d{1,2}\s*月", text[end_bound.end():]):
        year = int(end_bound.group(1))
        bare = re.search(r"(20\d{2})\s*年", text)
        if bare is None or bare.group(1) == end_bound.group(1):
            return {f"{year:04d}1231"}
    bare = re.search(r"(20\d{2})\s*年(?!\s*\d{1,2}\s*月)", text)
    if bare is not None:
        year = int(bare.group(1))
        return {f"{year:04d}0101", f"{year:04d}1231"}
    return set()


def accept_yyyymmdd(value: Any, example: str, source: str) -> Optional[str]:
    """日期槽的唯一校验。收下则返回 ``YYYYMMDD``。

    八位且日历合法之后，对照文本里还要收得成这同一个日期。
    收不成则 ``None``。第四 B 步复查时对照的是已经写下的那八位。

    Parameters
    ----------
    value : any
        解释者交出的值，或这一题的原文。
    example : str
        卡片上的例子。例子本身不是值；原文写得出这个日期才收下。
    source : str
        对照文本。用户原句、卡片原文，或步骤上已经写下的八位。

    Returns
    -------
    str or None
        合法且原文收得成的八位日期，否则 ``None``。
    """

    raw = "" if value is None else str(value)
    digits = re.sub(r"\D", "", raw)
    if len(digits) != 8:
        token = re.search(r"(?<!\d)(\d{8})(?!\d)", raw)
        digits = token.group(1) if token else ""
    if len(digits) != 8:
        return None
    try:
        datetime.datetime.strptime(digits, "%Y%m%d")
    except ValueError:
        return None
    if not _source_names_date(digits, str(source or "")):
        return None
    return digits


def _submitted_legal(slot: Dict[str, Any], raw: Any, query: str) -> bool:
    """这一次提交能不能按该槽现有校验收下。

    Parameters
    ----------
    slot : dict
        投影槽。
    raw : any
        协议里的值。``None`` 是提到了但没有值。
    query : str
        用户原文。日期例子出现在原文里时仍可收下。

    Returns
    -------
    bool
        能写入时为 True。
    """

    if raw is None:
        return False
    return accept_slot_value(slot, raw, query) not in (None, "", [])


def _reject_reason(slot: Dict[str, Any], raw: Any) -> str:
    """这一格没收下时给卡片的原因。引用这一次提交的原文。"""

    text = raw if isinstance(raw, str) else _joined_text(raw) or str(raw)
    resolve = str(slot.get("resolve") or "")
    if str(slot.get("format") or "") == "YYYYMMDD":
        return f"{text!r} is not a YYYYMMDD date."
    if resolve == "column":
        if "," in text or "，" in text:
            return f"{text!r} is not one value."
        return f"{text!r} is not a history column."
    if resolve == "code":
        normalized = _normalize_code_value(text, text)
        minimum = int(slot.get("min_count") or 0)
        count = len([part for part in str(normalized or "").split(",") if part])
        if normalized and minimum and count < minimum:
            return f"{text!r} needs at least {minimum} exchange codes."
        return f"{text!r} is not an exchange code."
    if resolve == "weights":
        parsed = commit_weight_text(str(text or ""))
        return str(parsed.get("reason") or f"{text!r} cannot be accepted for this field.")
    return f"{text!r} cannot be accepted for this field."


def reject_same_history_column(
    projected: Sequence[Dict[str, Any]],
    submitted: Set[str],
    steps: Sequence[Any],
    planner: Any,
) -> Dict[str, str]:
    """两格历史列名相同则拒这一次提交的那一格。

    同一句里两格一起交时，按投影顺序拒后面那一格。前面已经合法的那一格不动。
    只提交了其中一格、且与另一格相同，拒的是这一次提交的那一格。

    Parameters
    ----------
    projected : sequence of dict
        投影槽，顺序即投影顺序。
    submitted : set of str
        这一次提交写过的槽名。
    steps : sequence
        当前步骤。被拒的那一格从输入里清掉。
    planner : Planner
        用来按 schema 找到该槽所在的步骤。

    Returns
    -------
    dict
        被拒槽名到原因。
    """

    columns = [slot for slot in projected if str(slot.get("resolve") or "") == "column"]
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for slot in columns:
        value = str(slot.get("value") or "").strip()
        if not value:
            continue
        grouped.setdefault(value.casefold(), []).append(slot)
    errors: Dict[str, str] = {}
    for group in grouped.values():
        if len(group) < 2:
            continue
        named = [slot for slot in group if str(slot.get("name") or "") in submitted]
        if not named:
            continue
        victim = named[-1] if len(named) > 1 else named[0]
        name = str(victim.get("name") or "")
        shown = str(victim.get("value") or "")
        errors[name] = f"{shown!r} must differ; it is the same history column as another field."
        victim["filled"] = False
        victim["value"] = None
        for step in steps:
            schema = _step_fields(step, _schema(planner, step.skill_name))
            if name in schema and isinstance(step.inputs, dict):
                step.inputs.pop(name, None)
    return errors


def _default_label(slot: Dict[str, Any]) -> Any:
    """正在追问时，缺省选项上显示的值。

    Parameters
    ----------
    slot : dict
        投影槽。

    Returns
    -------
    any
        内核窗口的一端，或声明的 ``default``。
    """

    if str(slot.get("default_kind") or "") == "kernel_window":
        window = kernel_window()
        name = str(slot.get("name") or "")
        if name in window:
            return window[name]
    return slot.get("default")


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
    if spec.get("element"):
        extra["element"] = str(spec.get("element"))
    if spec.get("role"):
        extra["role"] = str(spec.get("role"))
    if spec.get("min_count") not in (None, ""):
        extra["min_count"] = int(spec.get("min_count") or 0)
    if spec.get("cardinality"):
        extra["cardinality"] = str(spec.get("cardinality"))
    aliases = spec.get("aliases") if isinstance(spec.get("aliases"), dict) else {}
    if aliases:
        extra["aliases"] = {str(key): str(value) for key, value in aliases.items()}
    if spec.get("vocabulary"):
        extra["vocabulary"] = [str(item) for item in spec.get("vocabulary") or []]
    if "default" in spec and spec.get("default") not in (None, ""):
        extra["default"] = spec.get("default")
    if spec.get("default_kind"):
        extra["default_kind"] = str(spec.get("default_kind"))
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
    """把值写进仍空着的同名输入。已有值不动。绘图步上的 shares 留空。"""

    wrote = False
    for step in steps:
        if name == "shares" and step.skill_name == "qt.ai.hp.plot":
            continue
        schema = _schema(planner, step.skill_name)
        if name not in schema or name in _SKIP:
            continue
        current = (step.inputs or {}).get(name)
        if current not in (None, "", []):
            continue
        step.inputs[name] = value
        wrote = True
    return wrote


def _portfolio_user_key(has_portfolio: bool, skill_name: str, key: str) -> bool:
    """组合图上才投影权重、基准、超额输出和复权标记。"""

    if not has_portfolio:
        return False
    if skill_name == _PORTFOLIO_SKILL and key in {"weights", "benchmark", "benchmark_output"}:
        return True
    return skill_name == _KLINE_SKILL and key == "adj"






def _weight_cue(query: str) -> bool:
    """问句是否明确要加权。"""

    text = _weight_text(query)
    if "权重" in text or "加权" in text:
        return True
    return "weights" in text.lower()


def _benchmark_cue(query: str) -> bool:
    """问句是否提到基准。槽名 ``benchmark_output`` 不算。"""

    text = str(query or "")
    if "基准" in text:
        return True
    scrubbed = text.lower().replace("benchmark_output", " ")
    return re.search(r"\bbenchmark\b", scrubbed) is not None


def _parse_benchmark(query: str) -> str:
    """相对、基准是、或以某代码为基准。沪深300收成 000300.SH。"""

    match = _BENCHMARK_PHRASE.search(str(query or ""))
    if match is None:
        return ""
    token = match.group(1) or match.group(2) or ""
    return _as_share_code(token)


_UNIQUE_INDEX = {
    "000016": "000016.SH",
    "000300": "000300.SH",
    "000905": "000905.SH",
    "000852": "000852.SH",
    "399001": "399001.SZ",
    "399006": "399006.SZ",
    "399300": "399300.SZ",
    "399905": "399905.SZ",
}
_AMBIGUOUS_BARE = {"000001"}
_EQUAL_PHRASES = ("等权", "一样重要", "一样重", "equal weight", "equally weighted")
_FREQ_WORDS = (
    ("周线", "w"),
    ("周频", "w"),
    ("按周", "w"),
    ("日线", "d"),
    ("日频", "d"),
    ("月线", "m"),
    ("月频", "m"),
)
_HOLD_MENTIONS = (
    "放一起",
    "放在一起",
    "一条线",
    "等权",
    "持有对比",
    "做一条组合",
    "一条组合",
    "一样重要",
)
_CHART_MENTIONS = ("出图", "一条线", "看图", "画一张", "图表", "一页图")


def _empty_commit() -> Dict[str, Any]:
    """一次提交的空结果。"""

    return {
        "values": {},
        "unresolved": [],
        "mentioned": [],
        "excess": False,
        "cumret": False,
    }


def _symbol_tokens(text: str) -> List[Tuple[int, str, str]]:
    """按出现顺序抽出带后缀代码、沪深300 和裸六位。"""

    hits: List[Tuple[int, str, str]] = []
    for match in _EXCHANGE_CODE.finditer(text):
        hits.append((match.start(), "suffixed", match.group(0).upper()))
    lowered = text.lower()
    for alias, code in (
        ("沪深300", "000300.SH"),
        ("csi 300", "000300.SH"),
        ("csi300", "000300.SH"),
        ("hs300", "000300.SH"),
    ):
        start = 0
        needle = alias.lower()
        while True:
            pos = lowered.find(needle, start)
            if pos < 0:
                break
            hits.append((pos, "alias", code))
            start = pos + len(needle)
    covered = [(pos, pos + 9) for pos, kind, _code in hits if kind == "suffixed"]
    for match in re.finditer(r"(?<!\d)(\d{6})(?!\d)", text):
        start = match.start()
        if any(left <= start < right for left, right in covered):
            continue
        hits.append((start, "bare", match.group(1)))
    hits.sort(key=lambda item: item[0])
    return hits


def _resolve_bare(digits: str, text: str, pos: int) -> Tuple[str, str]:
    """裸六位收成唯一代码。两义或没有交易所时返回空代码和原因。"""

    if digits in _AMBIGUOUS_BARE:
        return "", f"{digits} matches both an index and a stock."
    if digits in _UNIQUE_INDEX:
        return _UNIQUE_INDEX[digits], ""
    if digits.startswith(("5", "6")):
        return digits + ".SH", ""
    if digits.startswith(("0", "3")):
        return digits + ".SZ", ""
    if digits.startswith(("4", "8")):
        return digits + ".BJ", ""
    return "", f"{digits} has no exchange suffix."


def commit_shares(query: str) -> Dict[str, Any]:
    """代码一次提交。部分命中不算完成，公司名不猜代码。

    Returns
    -------
    dict
        ``status`` 为 ``absent`` / ``value`` / ``unresolved``。
        ``value`` 是逗号分隔的代码。``reason`` 是未完成原因。
    """

    text = str(query or "")
    tokens = _symbol_tokens(text)
    if not tokens:
        return {"status": "absent", "value": "", "reason": ""}
    found: List[str] = []
    for pos, kind, token in tokens:
        if kind == "bare":
            code, reason = _resolve_bare(token, text, pos)
        else:
            code = _as_share_code(token)
            if code and _suffix_conflict(code):
                return {
                    "status": "unresolved",
                    "value": "",
                    "reason": f"{code} suffix does not match its prefix.",
                }
            reason = "" if code else "A named symbol was not resolved."
        if reason or not code:
            return {
                "status": "unresolved",
                "value": "",
                "reason": reason or "A named symbol was not resolved.",
            }
        if code not in found:
            found.append(code)
    return {"status": "value", "value": ",".join(found), "reason": ""}


def _freq_mentioned(text: str) -> bool:
    """问句是否点了频率。"""

    if any(word in text for word, _code in _FREQ_WORDS):
        return True
    return "频率" in text or bool(re.search(r"\bfreq\b", text, flags=re.IGNORECASE))


def commit_freq(query: str) -> Dict[str, Any]:
    """频率一次提交。点了名却收不成时不靠缺省日线通过。

    Returns
    -------
    dict
        ``status`` / ``value`` / ``reason``。
    """

    text = str(query or "")
    for word, code in _FREQ_WORDS:
        if word in text:
            return {"status": "value", "value": code, "reason": ""}
    match = re.search(
        r"\bfreq\s*[:=：]\s*(1min|5min|15min|30min|60min|d|w|m)\b",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return {"status": "value", "value": match.group(1).lower(), "reason": ""}
    if _freq_mentioned(text):
        return {"status": "unresolved", "value": "", "reason": "Frequency was mentioned but not recognized."}
    return {"status": "absent", "value": "", "reason": ""}


def _ratio_values(text: str) -> List[float]:
    """冒号、比号或百分数列表。没有完整比例则空列表。"""

    match = re.search(
        r"(\d+(?:\.\d+)?[%％]?(?:\s*[:：比,/，]\s*\d+(?:\.\d+)?[%％]?)+)",
        str(text or ""),
    )
    if match is None:
        return []
    values: List[float] = []
    for part in re.split(r"\s*[:：比,/，]\s*", match.group(1)):
        number = _as_float(str(part).strip().rstrip("%").rstrip("％"))
        if number is None:
            return []
        values.append(float(number))
    return values


def _weight_text(text: str) -> str:
    """去掉「不参与权重」，避免把否定句当成要加权。"""

    return str(text or "").replace("不参与权重", " ")


def commit_weight_text(text: str) -> Dict[str, Any]:
    """权重说法一次提交。数字收成列表，等权不带 weights。

    Parameters
    ----------
    text : str
        原句或澄清卡上的回答。

    Returns
    -------
    dict
        ``status`` 为 ``absent`` / ``value`` / ``unresolved``。
        ``values`` 含 ``mode``，加权时还有 ``weights``。
    """

    raw = _weight_text(text)
    ratio = _ratio_values(raw)
    if ratio:
        return {"status": "value", "values": {"mode": "weighted", "weights": ratio}, "reason": ""}
    folded = raw.lower()
    if _negates_equal(raw):
        return {
            "status": "unresolved",
            "values": {},
            "reason": "Equal weight was negated.",
        }
    if any(phrase in raw or phrase in folded for phrase in _EQUAL_PHRASES):
        return {"status": "value", "values": {"mode": "equal"}, "reason": ""}
    mentioned = (
        "权重" in raw
        or "加权" in raw
        or "轻重" in raw
        or "weights" in folded
    )
    if mentioned:
        return {
            "status": "unresolved",
            "values": {},
            "reason": "Weight language was not a number list or equal weight.",
        }
    return {"status": "absent", "values": {}, "reason": ""}


def commit_query(query: str) -> Dict[str, Any]:
    """从一句问话提交代码、频率、权重和基准。未完成的键不写入 values。

    Returns
    -------
    dict
        ``values`` / ``unresolved`` / ``mentioned`` / ``excess`` / ``cumret``。
    """

    text = str(query or "")
    out = _empty_commit()
    out["excess"] = mentions_excess(text)
    out["cumret"] = mentions_cumret(text)
    shares = commit_shares(text)
    if shares["status"] == "value":
        out["values"]["shares"] = shares["value"]
        out["mentioned"].append("shares")
    elif shares["status"] == "unresolved":
        out["unresolved"].append({"name": "shares", "reason": shares["reason"]})
        out["mentioned"].append("shares")
    freq = commit_freq(text)
    if freq["status"] == "value":
        out["values"]["freq"] = freq["value"]
        out["mentioned"].append("freq")
    elif freq["status"] == "unresolved":
        out["unresolved"].append({"name": "freq", "reason": freq["reason"]})
        out["mentioned"].append("freq")
    weights = commit_weight_text(text)
    if weights["status"] == "value":
        out["values"].update(weights["values"])
        out["mentioned"].append("weights")
    elif weights["status"] == "unresolved":
        out["unresolved"].append({"name": "weights", "reason": weights["reason"]})
        out["mentioned"].append("weights")
    benchmark = _parse_benchmark(text)
    if benchmark:
        out["values"]["benchmark"] = benchmark
        out["mentioned"].append("benchmark")
    elif _benchmark_cue(text):
        out["unresolved"].append({"name": "benchmark", "reason": "Benchmark was mentioned without a symbol."})
        out["mentioned"].append("benchmark")
    return out


def normalize_portfolio_weight(inputs: Dict[str, Any]) -> str:
    """把组合步上的权重收成合法调用。返回未完成原因，成功则空串。

    Parameters
    ----------
    inputs : dict
        组合步的 inputs。就地改写。

    Returns
    -------
    str
        未完成原因。已经合法时为空串。
    """

    raw = inputs.get("weights")
    if isinstance(raw, dict) and str(raw.get("mode") or "") == "equal":
        inputs.pop("weights", None)
        inputs["mode"] = "equal"
        return ""
    if isinstance(raw, str):
        return ""
    weights = _as_weight_list(raw)
    if weights:
        inputs["weights"] = weights
        inputs["mode"] = "weighted"
        return ""
    return ""


def wants_chart(query: str) -> bool:
    """问句是否要点一张图或一条线。"""

    text = str(query or "")
    return any(phrase in text for phrase in _CHART_MENTIONS)


def looks_like_hold_compare(query: str) -> bool:
    """这句在分类不确定时仍像持有对比。"""

    text = str(query or "")
    if any(phrase in text for phrase in _HOLD_MENTIONS):
        return True
    if "组合" in text and "对比" in text:
        return True
    return "组合" in text and len(re.findall(r"(?<!\d)\d{6}(?!\d)", text)) >= 2


_NOT_SWITCHABLE = {"clarify", "open", "unsafe", "not_supported", "route_to_ask"}
_SLOT_WORDS = (
    "周线",
    "周频",
    "按周",
    "日线",
    "日频",
    "月线",
    "月频",
    "沪深300",
    "hs300",
    "csi300",
    "csi 300",
    "基准",
)


def _points_at_held(query: str) -> bool:
    """这句用「这两只」或「这两支」指已有持有。"""

    text = str(query or "")
    return "这两只" in text or "这两支" in text


def _has_benchmark_mention(query: str) -> bool:
    """这句点到基准槽。别名和「基准」都算。"""

    if _benchmark_cue(query):
        return True
    return any(kind == "alias" for _pos, kind, _code in _symbol_tokens(query))


def _touches_existing_slot(query: str) -> bool:
    """这句点到频率、基准或日期。"""

    if commit_freq(query).get("status") != "absent":
        return True
    if window_phrase(query):
        return True
    if re.search(r"(?<!\d)20\d{6}(?!\d)", str(query or "")):
        return True
    return _has_benchmark_mention(query)


def _strip_slot_words(query: str) -> str:
    """拿掉频率、基准、窗口和八位日期，留下句子里其余的要求。"""

    text = str(query or "")
    text = _WINDOW_PHRASE.sub(" ", text)
    text = re.sub(r"(?<!\d)20\d{6}(?!\d)", " ", text)
    for word in _SLOT_WORDS:
        text = re.sub(re.escape(word), " ", text, flags=re.IGNORECASE)
    return text


def _closed_official_job(job: str) -> str:
    """另一个官方闭合 Job。系统出口和开放图返回空串。"""

    name = str(job or "").strip()
    if not name or name in _NOT_SWITCHABLE:
        return ""
    from .intents import IntentCatalog

    catalog = IntentCatalog()
    if name not in set(catalog.official_ids):
        return ""
    if catalog.job_workflow(name) != "closed":
        return ""
    return name


def _other_job_after_slots(query: str) -> str:
    """去掉槽上的词之后，触发词还指着哪一个闭合 Job。"""

    from .intent_engine import IntentEngine

    decision = IntentEngine(provider=None).classify(_strip_slot_words(query))
    return _closed_official_job(str(decision.job or ""))


def revision_target(current_job: str, query: str, classified_job: str) -> str:
    """这一句要不要换成另一张图。空串表示留在当前图。

    先看这一句点到的槽，再看它有没有用「这两只」指已有持有。
    分类结果只在上面都不中、且它是另一个官方闭合 Job 时才换图。

    Parameters
    ----------
    current_job : str
        当前计划的 Job。
    query : str
        这一句跟进，不拼上一句。
    classified_job : str
        只对这一句分类得到的 Job。

    Returns
    -------
    str
        目标 Job。不换时为空串。
    """

    text = str(query or "")
    if (
        _touches_existing_slot(text)
        and not _points_at_held(text)
        and not _other_job_after_slots(text)
    ):
        return ""
    hold = str(current_job or "") == _HOLD_COMPARE_JOB
    pointed = _points_at_held(text)
    freq = commit_freq(text).get("status") == "value"
    held_codes = [token for _pos, kind, token in _symbol_tokens(text) if kind != "alias"]
    fresh_codes = bool(held_codes) and commit_shares(text).get("status") != "absent"
    weights = _weight_cue(text) or bool(_ratio_values(text))
    benchmark = _has_benchmark_mention(text)
    if hold and pointed and freq and not fresh_codes and not weights and not benchmark:
        return "data.read"
    if hold and pointed and freq and not fresh_codes and not weights and benchmark:
        return ""
    other = _closed_official_job(classified_job)
    if other and other != str(current_job or ""):
        return other
    return ""


class ClauseSplit(NamedTuple):
    """办事子句和附带提问。

    ``status`` 为 ``marked`` 时两段可以交给分类。``unmarked`` 时都不交。
    """

    task: str
    question: str
    status: str


_CLAUSE_SPLIT_SYSTEM = (
    "task 是要执行的连续原文，question 是顺口问的连续原文，可以是空字符串。\n"
    "两段都必须是用户原句里的连续片段，不许改写。\n"
    "question 非空时，task 不得包含它，两段不得重叠。做不到就两段都交空字符串。\n"
    "「主要做累计、顺便问超额会变成什么」拆成办事「主要做累计」、提问「顺便问超额会变成什么」；"
    "「哪个更值得」办事为空、提问是整句；一句没有附带提问的话，提问为空、办事是整句。"
)


def split_task_and_question(
    query: str,
    provider: Optional[Any] = None,
    *,
    identity_dir: Any = None,
) -> ClauseSplit:
    """有模型时按协议拆出办事和提问。没有模型时整句都是办事。

    Parameters
    ----------
    query : str
        用户原句。
    provider : optional
        语言模型。没有时不拆句。
    identity_dir : optional
        身份前缀用的用户库目录。

    Returns
    -------
    ClauseSplit
        ``task``、``question`` 和 ``marked`` / ``unmarked``。
    """

    text = str(query or "").strip()
    if provider is None:
        return ClauseSplit(text, "", "marked")
    from .identity import prefix_system_prompt

    try:
        raw = provider.chat(
            text,
            system_prompt=prefix_system_prompt(_CLAUSE_SPLIT_SYSTEM, identity_dir),
        )
    except Exception:
        return ClauseSplit("", "", "unmarked")
    return _clause_from_protocol(text, str(raw or ""))


def _clause_from_protocol(text: str, raw: str) -> ClauseSplit:
    """协议对不上、两段重叠或不是原句片段时标成 unmarked。"""

    payload = _parse_json(raw)
    if not isinstance(payload, dict):
        return ClauseSplit("", "", "unmarked")
    if "job" in payload or "jobs" in payload:
        return ClauseSplit("", "", "unmarked")
    if "task" not in payload or "question" not in payload:
        return ClauseSplit("", "", "unmarked")
    task = payload.get("task")
    question = payload.get("question")
    if not isinstance(task, str) or not isinstance(question, str):
        return ClauseSplit("", "", "unmarked")
    if task == "" and question == "":
        return ClauseSplit("", "", "unmarked")
    if task and task not in text:
        return ClauseSplit("", "", "unmarked")
    if question and question not in text:
        return ClauseSplit("", "", "unmarked")
    if task and question and _clause_spans_conflict(text, task, question):
        return ClauseSplit("", "", "unmarked")
    return ClauseSplit(task, question, "marked")


def _clause_spans_conflict(text: str, task: str, question: str) -> bool:
    """提问非空时，办事不得包含它，两段也不得重叠。"""

    if question in task or task in question:
        return True
    task_at = text.find(task)
    question_at = text.find(question)
    if task_at < 0 or question_at < 0:
        return True
    task_end = task_at + len(task)
    question_end = question_at + len(question)
    return task_at < question_end and question_at < task_end


def committed_benchmark_role(inputs: Mapping[str, Any]) -> Tuple[str, str]:
    """已提交基准的代码和角色。

    字符串非空即已提交。字典只有 ``status`` 为 ``confirmed`` 才取 ``code``。
    有代码且 ``benchmark_output`` 为 ``excess_only`` 时角色是 ``excess``，
    有代码时是 ``beside``，没有代码时是 ``none``。

    Parameters
    ----------
    inputs : mapping
        组合步已提交输入。

    Returns
    -------
    tuple of str
        ``(code, role)``。``role`` 只为 ``beside``、``excess`` 或 ``none``。
    """

    raw = inputs.get("benchmark") if isinstance(inputs, Mapping) else None
    code = ""
    if isinstance(raw, str):
        code = raw.strip()
    elif isinstance(raw, Mapping) and str(raw.get("status") or "") == "confirmed":
        code = str(raw.get("code") or "").strip()
    output = str(inputs.get("benchmark_output") or "").strip() if isinstance(inputs, Mapping) else ""
    if code and output == "excess_only":
        return code, "excess"
    if code:
        return code, "beside"
    return "", "none"


def format_committed_slot(name: str, value: Any) -> str:
    """把已提交槽收成槽位上的一行。空串表示不写。

    Parameters
    ----------
    name : str
        ``holdings``、``benchmark``、``weights`` 或 ``mode``。
    value : any
        该槽的已提交值。

    Returns
    -------
    str
        代码、权重、``equal`` / ``weighted`` 或基准代码。不写角色，也不写空值。
    """

    if name == "holdings":
        rows = value if isinstance(value, list) else []
        codes = [
            str(item.get("code") or "").strip()
            for item in rows
            if isinstance(item, Mapping)
            and str(item.get("status") or "") == "confirmed"
            and str(item.get("code") or "").strip()
        ]
        return ",".join(codes)
    if name == "benchmark":
        code, _role = committed_benchmark_role({"benchmark": value})
        return code
    if name == "weights" and isinstance(value, (list, tuple)):
        if value and all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in value):
            return str(list(value))
        return ""
    if name == "mode":
        text = str(value or "").strip()
        if text in {"equal", "weighted"}:
            return text
    return ""


def drop_role_conflicts(text: str, role: str) -> str:
    """角色不是旁挂时，丢掉含旁挂说法的句子。

    Parameters
    ----------
    text : str
        技能说明或预期产物。按句号拆开。
    role : str
        ``beside``、``excess`` 或 ``none``。

    Returns
    -------
    str
        留下的句子用 ``. `` 接回。全部丢掉时为空串。
    """

    raw = str(text or "").strip()
    if not raw:
        return ""
    kept: List[str] = []
    for part in re.split(r"\.\s+|。", raw):
        sentence = part.strip().rstrip(".").strip()
        if not sentence:
            continue
        if role != "beside" and ("beside" in sentence.lower() or "基准留在旁边" in sentence):
            continue
        kept.append(sentence)
    if not kept:
        return ""
    return ". ".join(kept) + "."


def committed_fact_lines(steps: Sequence[Any]) -> List[str]:
    """从已写入的 inputs 投影代码、频率、复权、权重和基准角色。"""

    lines: List[str] = []
    for step in steps:
        skill = str(getattr(step, "skill_name", "") or "")
        if isinstance(step, dict):
            skill = str(step.get("skill_name") or "")
            inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
        else:
            inputs = getattr(step, "inputs", None) or {}
        if not isinstance(inputs, dict):
            continue
        if skill == _KLINE_SKILL:
            shares = str(inputs.get("shares") or "").strip()
            if shares:
                freq = str(inputs.get("freq") or "d")
                adj = str(inputs.get("adj") or "").strip()
                line = f"Fetched {shares} at freq={freq}."
                if adj:
                    line = f"Fetched {shares} at freq={freq}, adj={adj}."
                lines.append(line)
        if skill == _PORTFOLIO_SKILL:
            mode = str(inputs.get("mode") or "equal")
            weights = inputs.get("weights")
            code, role = committed_benchmark_role(inputs)
            if mode == "weighted" and isinstance(weights, (list, tuple)):
                bits = f"Portfolio mode=weighted weights={list(weights)}"
            else:
                bits = "Portfolio mode=equal"
            if role == "excess":
                bits += f", benchmark={code} as excess"
            elif role == "beside":
                bits += f", benchmark={code} beside the portfolio"
            else:
                bits += ", no benchmark"
            lines.append(bits + ".")
    return lines


def _parse_weights(query: str) -> List[float]:
    """权重、加权或 weights 后面的数字。6:4、6比4、60%,40% 都收下。"""

    match = _WEIGHT_PHRASE.search(str(query or ""))
    if match is None:
        return []
    values: List[float] = []
    for part in re.split(r"\s*[:：,，比]\s*", match.group(1)):
        number = _as_float(str(part).strip().rstrip("%").rstrip("％"))
        if number is None:
            return []
        values.append(number)
    return values














def _bake_describe_view(steps: Sequence[Any], projected: Sequence[Dict[str, Any]]) -> None:
    """没指定视图时把 shape 写进摘要步。已经有值或已确认的不覆盖。"""

    for step in steps:
        if step.skill_name != "qt.ai.hp.describe":
            continue
        if (step.inputs or {}).get("view") not in (None, ""):
            continue
        step.inputs["view"] = "shape"
    for slot in projected:
        if slot.get("name") != "view" or slot.get("filled"):
            continue
        slot["filled"] = True
        slot["value"] = "shape"


def _remember_diagnosis_defaults(session: Any, projected: Sequence[Dict[str, Any]]) -> None:
    """可选槽的库默认进侧栏，不写进步骤。已有槽不覆盖。"""

    if session is None or getattr(session, "task", None) is None:
        return
    existing = set((session.task.slots or {}).keys())
    for slot in projected:
        name = str(slot.get("name") or "")
        if name not in _DIAGNOSIS_DEFAULTS or name in existing:
            continue
        if slot.get("filled") and name != "view":
            continue
        if name == "view" and slot.get("filled") and slot.get("value") not in (None, "", "shape"):
            continue
        session.set_slot(name, _DIAGNOSIS_DEFAULTS[name], source="default", confirmed=False)


def _statistic_options(steps: Sequence[Any]) -> Dict[str, Any]:
    """统计步上的两选。没有这一步时为空。"""

    current = ""
    for step in steps:
        if step.skill_name in {_VOL_SKILL, _RETURN_SKILL}:
            current = step.skill_name
            break
    if not current:
        return {}
    return {
        "current": current,
        "options": [
            {"id": _VOL_SKILL, "label": "Volatility"},
            {"id": _RETURN_SKILL, "label": "Returns"},
        ],
    }




def _as_share_code(value: Any) -> str:
    """交易所代码，或沪深300别名。对不上则空字符串。"""

    text = str(value or "").strip()
    compact = re.sub(r"\s+", "", text).lower()
    if "沪深300" in compact or compact in {"csi300"} or "csi300" in compact:
        return "000300.SH"
    code = text.upper()
    if re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", code):
        return code
    return ""


def _reviewed_code(piece: str, query: str) -> str:
    """已经带后缀走 ``_as_share_code``。只有六位数字才走 ``_resolve_bare``。

    Parameters
    ----------
    piece : str
        一项里的代码原文。
    query : str
        对照用的用户原文。只交给 ``_resolve_bare``。

    Returns
    -------
    str
        收得下的交易所代码。收不下则空串，不留六位原文。
    """

    text = str(piece or "").strip()
    code = _as_share_code(text)
    if code:
        if _suffix_conflict(code):
            return ""
        return code
    if re.fullmatch(r"\d{6}", text):
        resolved, reason = _resolve_bare(text, query, max(str(query or "").find(text), 0))
        if reason or not resolved:
            return ""
        return resolved
    return ""


def _split_codes(value: Any) -> List[str]:
    """逗号分隔的代码，按原顺序去重。"""

    if isinstance(value, (list, tuple)):
        raw = list(value)
    else:
        raw = str(value or "").replace("，", ",").split(",")
    found: List[str] = []
    for item in raw:
        code = _as_share_code(item)
        if code and code not in found:
            found.append(code)
    return found


def _as_weight_list(value: Any) -> List[float]:
    """已经是数字列表才收下。"""

    if not isinstance(value, (list, tuple)) or isinstance(value, (str, bytes)):
        return []
    values: List[float] = []
    for item in value:
        number = _as_float(item)
        if number is None:
            return []
        values.append(number)
    return values


def _mixed_equity_index(codes: Sequence[str]) -> bool:
    """同一份代码里既有指数也有别的标的。"""

    upper = [str(code).upper() for code in codes]
    has_index = any(code in _INDEX_CODES for code in upper)
    has_other = any(code not in _INDEX_CODES for code in upper)
    return has_index and has_other


def _pad_weights(shares: Sequence[str], benchmark: str, weights: Sequence[float]) -> List[float]:
    """按并完之后的顺序，在基准下标补 0。长度对不上就保持原列表。"""

    bench = benchmark.upper()
    held = [code for code in shares if code != bench]
    values = [float(item) for item in weights]
    if len(values) != len(held) or len(values) == len(list(shares)):
        return values
    padded: List[float] = []
    cursor = 0
    for code in shares:
        if code == bench:
            padded.append(0.0)
        else:
            padded.append(values[cursor])
            cursor += 1
    return padded


def _drop_named_steps(steps: List[Any], skill_name: str) -> None:
    """去掉指定技能，并把后继依赖改到它原来的上游。"""

    removed = {
        step.step_id: list(step.depends_on or [])
        for step in steps
        if step.skill_name == skill_name
    }
    if not removed:
        return
    kept = [step for step in steps if step.step_id not in removed]
    for step in kept:
        wired: List[str] = []
        for dep in list(step.depends_on or []):
            parents = removed.get(dep)
            incoming = parents if parents is not None else [dep]
            for parent in incoming:
                if parent not in wired:
                    wired.append(parent)
        step.depends_on = wired
    steps[:] = kept


def _set_on_skill(steps: Sequence[Any], skill_name: str, name: str, value: Any) -> None:
    """把值写进指定技能的输入。已有步骤都覆盖。"""

    for step in steps:
        if step.skill_name != skill_name:
            continue
        step.inputs[name] = value


def _clear_on_skill(steps: Sequence[Any], skill_name: str, name: str) -> None:
    """从指定技能的输入里去掉一个键。"""

    for step in steps:
        if step.skill_name != skill_name:
            continue
        step.inputs.pop(name, None)


def _sync_projected(planner: Any, steps: Sequence[Any], projected: Sequence[Dict[str, Any]]) -> None:
    """按步骤上的现值重算投影槽是否已填。"""

    for slot in projected:
        name = str(slot.get("name") or "")
        found = None
        for step in steps:
            if name == "shares" and step.skill_name == "qt.ai.hp.plot":
                continue
            schema = _schema(planner, step.skill_name)
            if name not in schema:
                continue
            current = (step.inputs or {}).get(name)
            if current not in (None, "", []):
                found = current
                break
        if found is None:
            slot["value"] = None
            slot["filled"] = _element_complete(slot, None) if slot.get("element") else False
        elif slot.get("element"):
            slot["value"] = found
            slot["filled"] = _element_complete(slot, found)
        else:
            slot["filled"] = True
            slot["value"] = found


def _kept_input_values(kept_steps: Optional[Sequence[Any]]) -> Dict[str, List[Any]]:
    """上一份计划每个输入名上的值。清扫只用来认出刚盖回去的那一份。"""

    found: Dict[str, List[Any]] = {}
    for row in kept_steps or []:
        if isinstance(row, dict):
            inputs = row.get("inputs")
        else:
            inputs = getattr(row, "inputs", None)
        if not isinstance(inputs, dict):
            continue
        for key, value in inputs.items():
            found.setdefault(str(key), []).append(value)
    return found


def _same_as_kept(current: Any, saved: Sequence[Any]) -> bool:
    """当前值和上一份计划里的同名输入相同。"""

    if any(current == item for item in saved):
        return True
    if isinstance(current, list):
        codes = ",".join(
            str(item.get("code") or "")
            for item in current
            if isinstance(item, dict) and str(item.get("code") or "")
        )
        return any(codes == item for item in saved if isinstance(item, str) and codes)
    return False


def overlay_kept_inputs(steps: Sequence[Any], kept_steps: Optional[Sequence[Any]]) -> None:
    """按 step_id 把上一份计划的 inputs 盖回同名步骤。

    Parameters
    ----------
    steps : sequence
        这一轮重新投影用的步骤。
    kept_steps : sequence
        上一份计划的步骤。没有同名步骤时不写。
    """

    by_id: Dict[str, Any] = {}
    for row in kept_steps or []:
        if isinstance(row, dict) and row.get("step_id"):
            by_id[str(row.get("step_id"))] = row
    for step in steps:
        row = by_id.get(str(getattr(step, "step_id", "") or ""))
        if not isinstance(row, dict):
            continue
        inputs = row.get("inputs") if isinstance(row.get("inputs"), dict) else {}
        for key, value in inputs.items():
            step.inputs[str(key)] = value


def _confirmed_holding_codes(steps: Sequence[Any]) -> List[str]:
    """上一份计划里已经确认的持有代码。不读取数步拼过基准的 shares。"""

    codes: List[str] = []
    for step in steps or []:
        if isinstance(step, dict):
            inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
            skill = str(step.get("skill_name") or "")
        else:
            inputs = step.inputs if isinstance(getattr(step, "inputs", None), dict) else {}
            skill = str(getattr(step, "skill_name", "") or "")
        if skill != _PORTFOLIO_SKILL and "holdings" not in inputs:
            continue
        for item in inputs.get("holdings") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("status") or "") != "confirmed":
                continue
            code = str(item.get("code") or "").strip()
            if code and code not in codes:
                codes.append(code)
    return codes


def carry_confirmed_inputs(
    planner: Any,
    old_steps: Sequence[Any],
    new_steps: Sequence[Any],
    session: Any,
) -> None:
    """换图后把已确认的同名值写入仍空的槽。shares 只抄已确认持有代码。

    Parameters
    ----------
    planner : Planner
        用来看新图的 schema。
    old_steps : sequence
        被换掉的步骤。持有代码从这里读。
    new_steps : sequence
        新图。没有的名字不写。
    session : ConversationState or None
        已确认槽。这次抄写不写成新的用户确认。
    """

    confirmed = _confirmed_values(session)
    for name, value in confirmed.items():
        if name == "shares":
            continue
        _write_empty(planner, new_steps, name, value)
    codes = _confirmed_holding_codes(old_steps)
    if not codes:
        return
    joined = ",".join(codes)
    for step in new_steps:
        schema = _schema(planner, step.skill_name)
        if "shares" not in schema:
            continue
        current = (step.inputs or {}).get("shares")
        if current not in (None, "", []):
            continue
        step.inputs["shares"] = joined




def _clear_open_prewrite(
    steps: Sequence[Any],
    projected: Sequence[Dict[str, Any]],
    confirmed: Dict[str, Any],
    kept_steps: Optional[Sequence[Any]] = None,
) -> Set[str]:
    """清掉未确认投影槽上的预写。已确认的值，以及上一份计划里的同值，留下。

    Returns
    -------
    set of str
        被清掉的槽名。解释者还要读这些槽，预写本身不留下。
    """

    names = set(confirmed)
    backed = [value for value in confirmed.values() if value not in (None, "", [])]
    kept_values = _kept_input_values(kept_steps)
    cleared: Set[str] = set()
    for slot in projected:
        name = str(slot.get("name") or "")
        if name in names:
            continue
        kept = False
        popped = False
        saved = kept_values.get(name) or []
        for step in steps:
            inputs = step.inputs if isinstance(getattr(step, "inputs", None), dict) else None
            if inputs is None or name not in inputs:
                continue
            current = inputs.get(name)
            same = any(current == item for item in backed) or _same_as_kept(current, saved)
            if not same and isinstance(current, list):
                codes = ",".join(
                    str(item.get("code") or "")
                    for item in current
                    if isinstance(item, dict) and str(item.get("code") or "")
                )
                same = any(codes == item for item in backed if isinstance(item, str))
            if same:
                kept = True
                continue
            inputs.pop(name, None)
            popped = True
        if kept:
            continue
        slot["filled"] = False
        slot["value"] = None
        if popped:
            cleared.add(name)
    return cleared


def _expected_stock_suffix(digits: str) -> str:
    """股票前缀表对应的后缀。认不出则空串。"""

    if digits.startswith(("5", "6")):
        return "SH"
    if digits.startswith(("0", "3")):
        return "SZ"
    if digits.startswith(("4", "8")):
        return "BJ"
    return ""


def _suffix_conflict(code: str) -> bool:
    """股票后缀和前缀表不一致。指数表和已写后缀的 000001 不是冲突。"""

    text = str(code or "").upper()
    if text in set(_UNIQUE_INDEX.values()) or text in {"000001.SH", "000001.SZ"}:
        return False
    digits, dot, suffix = text.partition(".")
    if not dot or digits in _UNIQUE_INDEX:
        return False
    expected = _expected_stock_suffix(digits)
    if not expected:
        return False
    return suffix != expected


def _negates_equal(text: str) -> bool:
    """句中否定等权。"""

    return re.search(r"(?:不要|别|并非|不是).{0,6}等权", str(text or "")) is not None


def _user_wrote_code(code: str, query: str) -> bool:
    """用户原文里有这只代码，或有能对上的别名。裸 000001 必须写出后缀。"""

    text = str(query or "")
    upper = str(code or "").upper()
    if upper and upper in text.upper():
        return True
    compact = re.sub(r"\s+", "", text)
    folded = compact.lower()
    if upper == "000300.SH" and ("沪深300" in compact or "csi300" in folded or "hs300" in folded):
        return True
    digits = upper.split(".", 1)[0]
    if digits == "000001":
        return False
    return bool(digits) and digits in text


def _normalize_code_value(value: Any, query: str) -> Optional[str]:
    """把已经放进某一格的代码收成合法形式。收不下则 ``None``。"""

    text = _joined_text(value)
    if not text:
        return None
    parts = [part.strip() for part in text.split(",") if part.strip()]
    found: List[str] = []
    for part in parts:
        code = _reviewed_code(part, query)
        if not code or not _user_wrote_code(code, query):
            return None
        if code not in found:
            found.append(code)
    return ",".join(found) if found else None


_EDGE_PREFIXES = (
    "帮我用",
    "请用",
    "请说明",
    "并说明",
    "帮我",
    "并跟",
    "基准是",
    "下载",
    "回测",
    "优化",
    "取数",
    "说明",
    "相对",
    "跟",
    "进行",
    "看",
    "用",
    "以",
    "并",
    "的",
)
_EDGE_SUFFIXES = (
    "做一个等权持仓组合",
    "做一条等权组合",
    "做一个等权组合",
    "做一条组合",
    "等权持仓组合",
    "等权组合",
    "持仓组合",
    "做一个对比",
    "做一条加权组合",
    "加权组合",
    "请说明基准",
    "说明基准",
    "为基准",
    "是指数",
    "不要等权",
    "的波动率",
    "持仓收益率",
    "累计收益",
    "波动率",
    "放一起",
    "收益率",
    "超额",
    "周线",
    "日线",
    "月线",
    "指数",
    "组合",
    "对比",
    "基准",
    "最大回撤",
    "做回测",
    "成一条线",
    "轻重不同",
    "回撤",
    "年化",
    "回测",
    "给我看",
)
_TASK_MARKERS = (
    "回测",
    "年化",
    "回撤",
    "策略",
    "均线",
    "金叉",
    "死叉",
    "择时",
    "优化",
    "下载",
    "波动",
    "给我",
    "上跑",
    "权重",
)
_EDGE_WEIGHT = re.compile(
    r"\s*(?:(?:按)?权重|加权组合)\s*\d+(?:\.\d+)?[%％]?(?:\s*[:：比]\s*\d+(?:\.\d+)?[%％]?)*$"
)
_EDGE_DATES = re.compile(r"\s*从\s*\d{4,8}\s*到\s*\d{4,8}$")
_PIECE_SPLIT = re.compile(r"[、，,]|(?:和|与)")


def _element_complete(slot: Dict[str, Any], value: Any) -> bool:
    """元素合同：每一项都已确认，且已确认项数不少于声明。

    空角色只看元素类型和项数。空着的可选槽算完成。非空字符串不算完成。
    """

    if isinstance(value, str) and value.strip():
        return False
    items = _as_item_list(value)
    minimum = int(slot.get("min_count") or 0)
    if not items:
        return False
    if any(str(item.get("status") or "") != "confirmed" for item in items):
        return False
    return len(items) >= minimum


def _as_item_list(value: Any) -> List[Dict[str, Any]]:
    """一项或项列表。其它形状当空。"""

    if isinstance(value, dict) and any(key in value for key in ("code", "mention", "status")):
        return [dict(value)]
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _one_item(value: Any) -> Optional[Dict[str, Any]]:
    """单值槽上的那一项。字符串代码包成已确认项。"""

    if isinstance(value, dict) and any(key in value for key in ("code", "mention", "status")):
        item = dict(value)
        item.setdefault("mention", "")
        item.setdefault("code", str(item.get("code") or ""))
        item.setdefault("status", "confirmed")
        return item
    if isinstance(value, list):
        items = _as_item_list(value)
        return dict(items[0]) if items else None
    text = str(value or "").strip()
    if not text:
        return None
    code = _as_share_code(text) or text
    return {"mention": "", "code": code, "status": "confirmed"}


def _is_alias_piece(piece: str) -> bool:
    """这段是不是沪深300一类别名，而不是用户写出的交易所代码。"""

    compact = re.sub(r"\s+", "", str(piece or "")).lower()
    return "沪深300" in compact or "csi300" in compact


def _trim_piece(text: str) -> str:
    """去掉任务虚词边角。切不开时改这里，不加回用字到做字的窗口。"""

    piece = str(text or "").strip(" ，,。;；、")
    changed = True
    prefixes = sorted(_EDGE_PREFIXES, key=len, reverse=True)
    suffixes = sorted(_EDGE_SUFFIXES, key=len, reverse=True)
    while piece and changed:
        changed = False
        for prefix in prefixes:
            if piece.startswith(prefix):
                piece = piece[len(prefix):].strip(" ，,。;；、")
                changed = True
                break
        leading = re.sub(r"^[A-Za-z][A-Za-z0-9_]*\s*", "", piece).strip(" ，,。;；、")
        if leading != piece:
            piece = leading
            changed = True
        shortened = re.sub(
            rf"^(?:过去|近)\s*{_WINDOW_SPAN}",
            "",
            piece,
        ).strip(" ，,。;；、")
        if shortened != piece:
            piece = shortened
            changed = True
        unweighted = _EDGE_WEIGHT.sub("", piece).strip(" ，,。;；、")
        if unweighted != piece:
            piece = unweighted
            changed = True
        undated = _EDGE_DATES.sub("", piece).strip(" ，,。;；、")
        if undated != piece:
            piece = undated
            changed = True
        for suffix in suffixes:
            if piece.endswith(suffix):
                piece = piece[: -len(suffix)].strip(" ，,。;；、")
                changed = True
                break
    return piece


def _exact_alias(piece: str) -> bool:
    """整段就是沪深300一类对照名，而不是夹在任务句里。"""

    compact = re.sub(r"\s+", "", str(piece or "")).lower()
    return compact in {"沪深300", "csi300"}


def _keep_piece(piece: str) -> bool:
    """代码、整段别名或短中文名留下。任务句、年份和夹着英文的边角丢掉。"""

    if not piece:
        return False
    if re.fullmatch(r"\d{6}(?:\.(?:SH|SZ|BJ))?", piece, flags=re.IGNORECASE):
        return True
    if _exact_alias(piece):
        return True
    if re.fullmatch(r"\d+(?:\.\d+)?[%％]?", piece):
        return False
    if re.search(r"[A-Za-z]", piece) or re.search(r"\d", piece):
        return False
    if any(marker in piece for marker in _TASK_MARKERS):
        return False
    if any(phrase in piece for phrase in _CHART_MENTIONS):
        return False
    return re.fullmatch(r"[\u4e00-\u9fff]{2,8}", piece) is not None




def _token_pieces(query: str, *, include_alias: bool) -> List[str]:
    """没有分隔符时只收代码。别名默认不收进持有。"""

    found: List[str] = []
    for _pos, kind, token in _symbol_tokens(query):
        if kind == "alias":
            if not include_alias:
                continue
            piece = "沪深300"
        else:
            piece = token
        if piece not in found:
            found.append(piece)
    return found


def _status_for_piece(piece: str, query: str) -> Tuple[str, str]:
    """用户写出的唯一代码已确认。冲突、裸 000001 和非代码没有 code。"""

    code = _reviewed_code(piece, query)
    if code and _user_wrote_code(code, query):
        return code, "confirmed"
    return "", "incomplete"














def _kept_element_source(value: Any) -> str:
    """用已经收下的代码和提及当原文，避免跟进句把没再提到的项清掉。"""

    items = value if isinstance(value, list) else [value]
    parts: List[str] = []
    for item in items:
        if isinstance(item, dict):
            code = str(item.get("code") or "").strip()
            mention = str(item.get("mention") or "").strip()
            if code:
                parts.append(code)
            if mention and mention not in parts:
                parts.append(mention)
        elif item not in (None, ""):
            parts.append(str(item).strip())
    return " ".join(part for part in parts if part)


def _tag_submitted_item(item: Any, query: str) -> Dict[str, Any]:
    """协议交来的一项。用户没写的代码保持 pending，不另切一句造提及。"""

    if isinstance(item, str):
        mention = item.strip()
        raw_code = mention
    elif isinstance(item, dict):
        mention = str(item.get("mention") or "")
        raw_code = str(item.get("code") or "")
    else:
        return {"mention": "", "code": "", "status": "incomplete"}
    code = _reviewed_code(raw_code or mention, query)
    if not code:
        shown = mention or raw_code
        return {"mention": shown, "code": "", "status": "incomplete"}
    status = "confirmed" if _user_wrote_code(code, query) else "pending"
    return {"mention": mention, "code": code, "status": status}


def _items_from_submitted(value: Any, query: str, slot: Dict[str, Any]) -> Any:
    """协议里的项列表或单值项。缺了 holdings 时不从原句再切。"""

    rows: List[Any]
    if isinstance(value, list):
        rows = list(value)
    elif isinstance(value, str) and ("," in value or "，" in value):
        rows = [part.strip() for part in value.replace("，", ",").split(",") if part.strip()]
    elif value in (None, "", []):
        rows = []
    else:
        rows = [value]
    tagged = [_tag_submitted_item(item, query) for item in rows]
    if not tagged:
        return None
    if str(slot.get("cardinality") or "") == "one" or str(slot.get("element") or "") == "comparison_code":
        return tagged[0]
    return tagged


def _write_element(planner: Any, steps: Sequence[Any], name: str, value: Any) -> None:
    """把项写进声明了这个槽的步骤。已有值也覆盖。"""

    for step in steps:
        if name == "shares" and step.skill_name == "qt.ai.hp.plot":
            continue
        schema = _schema(planner, step.skill_name)
        decls = getattr(step, "slot_decls", None) or {}
        if name not in schema and name not in decls:
            continue
        step.inputs[name] = value


def _accepted_inputs(
    steps: Sequence[Any],
    submitted: Dict[str, Any],
    pending: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """本轮收下、且下一张卡不再问的值。

    名字只来自这一轮的提交。步骤上已经清掉的不收。组图常量不在提交里，不收。

    Parameters
    ----------
    steps : sequence
        还没换成澄清步的步骤。
    submitted : dict
        这一轮提交的槽。
    pending : sequence of dict
        下一张卡还要问的题。

    Returns
    -------
    dict
        槽名到步骤上的现值。
    """

    asking = {str(item.get("name") or "") for item in pending if isinstance(item, dict)}
    found: Dict[str, Any] = {}
    for name in submitted:
        key = str(name or "")
        if not key or key in asking:
            continue
        value = _read_input(steps, key)
        if value in (None, "", []):
            continue
        found[key] = value
    return found


def _read_input(steps: Sequence[Any], name: str) -> Any:
    """步骤上这个槽的现值。"""

    for step in steps:
        if name == "shares" and step.skill_name == "qt.ai.hp.plot":
            continue
        current = (step.inputs or {}).get(name)
        if current not in (None, "", []):
            return current
    return None


def _merge_closed_items(previous: Any, fresh: Any, slot: Dict[str, Any]) -> Any:
    """已确认的项盖过这一轮重新解释的同下标项。"""

    one = (
        str(slot.get("cardinality") or "") == "one"
        or str(slot.get("element") or "") == "comparison_code"
    )
    if one:
        prev = _one_item(previous)
        if prev is not None and str(prev.get("status") or "") == "confirmed":
            return prev
        return _one_item(fresh) or prev
    prev_items = _as_item_list(previous)
    fresh_items = _as_item_list(fresh)
    if not fresh_items:
        return prev_items or None
    if not prev_items:
        return fresh_items
    merged: List[Dict[str, Any]] = []
    for index in range(max(len(prev_items), len(fresh_items))):
        prev = prev_items[index] if index < len(prev_items) else None
        new = fresh_items[index] if index < len(fresh_items) else None
        if isinstance(new, dict):
            merged.append(dict(new))
        elif isinstance(prev, dict):
            merged.append(dict(prev))
    return merged or None


def _seal_elements(
    planner: Any,
    steps: Sequence[Any],
    projected: Sequence[Dict[str, Any]],
    closed: Dict[str, Any],
) -> None:
    """解释之后，用解释前关上的已确认项盖回去。"""

    for slot in projected:
        if not slot.get("element"):
            continue
        name = str(slot.get("name") or "")
        merged = _merge_closed_items(closed.get(name), _read_input(steps, name), slot)
        if merged in (None, "", []):
            slot["filled"] = _element_complete(slot, None)
            slot["value"] = None
            continue
        _write_element(planner, steps, name, merged)
        slot["value"] = merged
        slot["filled"] = _element_complete(slot, merged)






def _confirmed_benchmark_code(value: Any) -> str:
    """从基准项取出已确认的 code。字符串只在还没包成项时用。"""

    if isinstance(value, dict):
        if str(value.get("status") or "") != "confirmed":
            return ""
        return str(value.get("code") or "")
    return _as_share_code(value)


def _holding_items(steps: Sequence[Any]) -> List[Dict[str, Any]]:
    """组合步上的持有项。"""

    for step in steps:
        if step.skill_name != _PORTFOLIO_SKILL:
            continue
        return _as_item_list((step.inputs or {}).get("holdings"))
    return []




def _held_codes(steps: Sequence[Any]) -> List[str]:
    """已确认的持有代码。基准不计入只数。"""

    holdings = _holding_items(steps)
    if holdings:
        return [
            str(item.get("code") or "")
            for item in holdings
            if str(item.get("status") or "") == "confirmed" and item.get("code")
        ]
    benchmark = ""
    for step in steps:
        if step.skill_name == _PORTFOLIO_SKILL:
            benchmark = _confirmed_benchmark_code((step.inputs or {}).get("benchmark")) or benchmark
    codes: List[str] = []
    for step in steps:
        if step.skill_name != _KLINE_SKILL:
            continue
        for code in _split_codes((step.inputs or {}).get("shares")):
            if code != benchmark and code not in codes:
                codes.append(code)
    return codes


def _reject_weight_count(steps: Sequence[Any]) -> Set[str]:
    """权重只数和已确认持仓不一致时清掉权重。基准不计入。"""

    weights: List[float] = []
    for step in steps:
        if step.skill_name == _PORTFOLIO_SKILL:
            weights = _as_weight_list((step.inputs or {}).get("weights"))
    held = _held_codes(steps)
    if weights and held and len(weights) != len(held):
        _clear_weight_mode(steps)
        return {"weights"}
    return set()


def _clear_weight_mode(steps: Sequence[Any]) -> None:
    """清掉组合步上的权重和 mode。"""

    for step in steps:
        if step.skill_name != _PORTFOLIO_SKILL:
            continue
        step.inputs.pop("weights", None)
        step.inputs.pop("mode", None)


def _place_submitted(
    planner: Any,
    steps: Sequence[Any],
    projected: Sequence[Dict[str, Any]],
    submitted: Dict[str, Any],
) -> None:
    """把这一轮候选写上步骤，供质检读取。这里不调用 ``accept_slot_value``。"""

    by_name = {str(slot.get("name") or ""): slot for slot in projected}
    for name, raw in submitted.items():
        key = str(name or "")
        if not key or key == "mode" or raw in (None, "", []):
            continue
        slot = by_name.get(key)
        if slot is None:
            continue
        _write_element(planner, steps, key, raw)
        slot["value"] = raw


def _clear_slot(planner: Any, steps: Sequence[Any], name: str) -> None:
    """从声明了这个槽的步骤上删掉现值。"""

    for step in steps:
        if name == "shares" and step.skill_name == "qt.ai.hp.plot":
            continue
        schema = _schema(planner, step.skill_name)
        decls = getattr(step, "slot_decls", None) or {}
        if name not in schema and name not in decls:
            continue
        if isinstance(step.inputs, dict):
            step.inputs.pop(name, None)


def _apply_inspected(
    planner: Any,
    steps: Sequence[Any],
    projected: Sequence[Dict[str, Any]],
    report: Dict[str, Any],
) -> None:
    """把质检收下的值写回步骤。拒因格清掉，避免六位原文留在步骤上。"""

    accepted = dict(report.get("accepted") or {})
    errors = set(report.get("errors") or {})
    for slot in projected:
        name = str(slot.get("name") or "")
        if name in accepted:
            value = accepted[name]
            if str(slot.get("resolve") or "") == "weights" and isinstance(value, dict):
                if str(value.get("mode") or "") == "equal":
                    _clear_on_skill(steps, _PORTFOLIO_SKILL, "weights")
                    _set_on_skill(steps, _PORTFOLIO_SKILL, "mode", "equal")
                slot["filled"] = True
                slot["value"] = value
                continue
            _write_element(planner, steps, name, value)
            slot["value"] = value
            slot["filled"] = (
                _element_complete(slot, value) if slot.get("element") else True
            )
            continue
        if name in errors:
            _clear_slot(planner, steps, name)
            slot["filled"] = False
            slot["value"] = None


def _holding_confirm_prompt(mention: str, code: str) -> str:
    """一项持仓的确认题干。名字只用 mention 和 code。"""

    left = str(mention or "").strip()
    right = str(code or "").strip()
    chinese = bool(_CJK.search(left + right))
    if left and right and left != right:
        shown = f"{left}（{right}）" if chinese else f"{left} ({right})"
    else:
        shown = left or right
    if chinese:
        return f"请确认{shown}。" if shown else "请确认这项持仓。"
    return f"Confirm {shown}." if shown else "Confirm this holding."


def _item_pending_rows(slot: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """多值代码槽按未确认的项出页。没有项时交给整格追问。

    建议代码是一个选项。开放输入是最后一行。题干是确认句。
    """

    if not slot.get("element"):
        return None
    if str(slot.get("cardinality") or "") == "one":
        return None
    items = _as_item_list(slot.get("value"))
    if not items:
        return None
    if all(str(item.get("status") or "") == "confirmed" for item in items):
        return None
    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(items):
        if str(item.get("status") or "") == "confirmed":
            continue
        row = _pending_row(slot)
        mention = str(item.get("mention") or "")
        code = str(item.get("code") or "")
        row["index"] = index
        row["mention"] = mention
        row["code"] = code
        row["items"] = items
        row["prompt"] = _holding_confirm_prompt(mention, code)
        row["hint"] = ""
        if str(item.get("error") or "").strip():
            row["error"] = str(item.get("error"))
        row["open"] = {"label": "其它" if _CJK.search(mention + code) else "Other"}
        if code:
            row["options"] = [{"id": code, "label": code}]
        else:
            row.pop("options", None)
        rows.append(row)
    return rows


def is_bound_item_list(value: Any) -> bool:
    """已经按项写好的列表。不要再按槽名解析成一段文本。"""

    if not isinstance(value, list) or not value:
        return False
    return all(
        isinstance(item, dict) and any(key in item for key in ("code", "mention", "status"))
        for item in value
    )


def _reviewed_share_text(text: str) -> str:
    """整格代码槽过 ``commit_shares``。只有 ``value`` 才返回代码串。"""

    parsed = commit_shares(str(text or ""))
    if str(parsed.get("status") or "") != "value":
        return ""
    return str(parsed.get("value") or "")


def _one_reviewed_code(text: str) -> str:
    """持仓一题：复核后恰好一只代码才可以确认。"""

    value = _reviewed_share_text(text)
    codes = [part for part in value.split(",") if part]
    if len(codes) != 1:
        return ""
    return codes[0]


def apply_ordered_answers(
    rows: Sequence[Any],
    answers: Sequence[Any],
) -> Optional[Dict[str, Any]]:
    """按题序把答案绑成槽补丁。不在这里决定收不收。

    选项 id ``default`` 换成该行 ``default_value``。其它选项 id 换成该 id。
    开放输入保持原文。带 ``index`` 的持仓项只把这一题原文放进 ``answer``，
    不改建议代码，也不把 ``status`` 写成已确认。``resolve=code`` 的整格
    原文写入补丁，收不下也不删键。题数对不上时返回 ``None``。空串表示
    这一轮没答。

    Parameters
    ----------
    rows : sequence
        卡片上的题，顺序与 Session 交出的 ``pending`` 相同。
    answers : sequence
        与题同一顺序的答案。

    Returns
    -------
    dict or None
        槽名到值。项列表已经写好，调用方不要再按槽名解析这些键。
    """

    pending_rows = [item for item in (rows or []) if isinstance(item, dict)]
    values = list(answers or [])
    if len(pending_rows) != len(values):
        return None
    patches: Dict[str, Any] = {}
    lists: Dict[str, List[Dict[str, Any]]] = {}
    for row, raw in zip(pending_rows, values):
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        if row.get("index") is not None and isinstance(row.get("items"), list):
            if name not in lists:
                lists[name] = [
                    dict(item) if isinstance(item, dict) else {"mention": "", "code": "", "status": "incomplete"}
                    for item in (row.get("items") or [])
                ]
            try:
                cursor = int(row.get("index"))
            except (TypeError, ValueError):
                cursor = -1
            text = str(raw or "").strip()
            if text == "default" and row.get("default_value") not in (None, ""):
                text = str(row.get("default_value"))
            if text and 0 <= cursor < len(lists[name]):
                lists[name][cursor]["answer"] = text
            continue
        if isinstance(raw, str):
            text = raw.strip()
        else:
            text = raw
        if text in (None, ""):
            continue
        if str(text) == "default" and row.get("default_value") not in (None, ""):
            text = row.get("default_value")
        patches[name] = text
    for name, items in lists.items():
        patches[name] = items
    return patches




def _finish_portfolio_graph(steps: List[Any], query: str) -> None:
    """持有都确认后才把代码拼进取数 shares。基准项留在 inputs 里。"""

    portfolios = [step for step in steps if step.skill_name == _PORTFOLIO_SKILL]
    if not portfolios:
        return
    holdings = _holding_items(steps)
    ready = bool(holdings) and all(str(item.get("status") or "") == "confirmed" for item in holdings)
    benchmark = ""
    for step in portfolios:
        benchmark = _confirmed_benchmark_code((step.inputs or {}).get("benchmark")) or benchmark
    kline_codes: List[str] = []
    if ready:
        kline_codes = [str(item.get("code") or "") for item in holdings if item.get("code")]
        if benchmark and benchmark not in kline_codes:
            kline_codes.append(benchmark)
        for step in steps:
            if step.skill_name != _KLINE_SKILL:
                continue
            if kline_codes:
                step.inputs["shares"] = ",".join(kline_codes)
            asset = str((step.inputs or {}).get("asset_type") or "").strip().upper()
            if asset in {"E", "IDX"} and _mixed_equity_index(kline_codes):
                step.inputs.pop("asset_type", None)
    excess_only = False
    for step in portfolios:
        weights = _as_weight_list((step.inputs or {}).get("weights"))
        if (
            ready
            and benchmark
            and weights
            and kline_codes
            and str((step.inputs or {}).get("mode") or "") != "equal"
        ):
            weights = _pad_weights(kline_codes, benchmark, weights)
            step.inputs["weights"] = weights
        current = str((step.inputs or {}).get("benchmark_output") or "").strip()
        if not benchmark:
            if not isinstance((step.inputs or {}).get("benchmark"), dict):
                step.inputs.pop("benchmark", None)
            step.inputs.pop("benchmark_output", None)
            current = ""
        if current == "excess_only":
            excess_only = True
    if not excess_only:
        return
    _drop_named_steps(steps, "qt.ai.hp.normalize")
    for step in steps:
        if step.skill_name != "qt.ai.hp.cum_return":
            continue
        if (step.inputs or {}).get("htypes") in (None, ""):
            step.inputs["htypes"] = "excess_close"


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
