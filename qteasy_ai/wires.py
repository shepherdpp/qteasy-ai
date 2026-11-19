# coding=utf-8
# ======================================
# File: wires.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-07
# Desc:
# 研究边和筛股三原子的线格式声明。
# 未列入的技能保持 consumes/produces 为 None。
# ======================================

"""技能注册时挂上的线格式。

检查器只认这里写下的 payload 键和类型名。策略构造链、回测解读和环境探针不在表里。
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

from .contracts import SkillMetadata, Wire

PANEL = Wire("panel", "qteasy.history.HistoryPanel")
FRAME = Wire("frame", "pandas.DataFrame")
SERIES = Wire("frame", "pandas.Series")
MASK = Wire("mask", "numpy.ndarray", "bool")
SYMBOLS = Wire("symbols", "list[str]")
HITS = Wire("hits", "list[dict]")
COMPARISON = Wire("comparison", "list[dict]")

_NONE: Tuple[Wire, ...] = ()
_PANEL: Tuple[Wire, ...] = (PANEL,)
_FRAME: Tuple[Wire, ...] = (FRAME,)


def _panel_io() -> Dict[str, object]:
    """读面板、交面板。"""

    return {"consumes": _PANEL, "produces": _PANEL}


def _frame_or_panel(default_frame: bool) -> Dict[str, object]:
    """``as_panel`` 在表和面板之间切换。默认跟库走。"""

    if default_frame:
        return {
            "consumes": _PANEL,
            "produces": _FRAME,
            "produces_when": {"as_panel": {"true": _PANEL}},
        }
    return {
        "consumes": _PANEL,
        "produces": _PANEL,
        "produces_when": {"as_panel": {"false": _FRAME}},
    }


_SPECS: Dict[str, Dict[str, object]] = {
    "qt.ai.data.history": {"consumes": _NONE, "produces": _PANEL},
    "qt.ai.data.kline": {"consumes": _NONE, "produces": _PANEL},
    "qt.ai.data.reference": {"consumes": _NONE, "produces": _NONE},
    "qt.ai.data.static": {"consumes": _NONE, "produces": _NONE},
    "qt.ai.data.read": {"consumes": _NONE, "produces": _NONE},
    "qt.ai.dtype.find": {"consumes": _NONE, "produces": _NONE},
    "qt.ai.datasource.table_info": {"consumes": _NONE, "produces": _NONE},
    "qt.ai.datasource.table_overview": {"consumes": _NONE, "produces": _NONE},
    "qt.ai.data.statement": {
        "consumes": _NONE,
        "produces": _PANEL,
        "produces_when": {
            "compare": {"qoq": (COMPARISON,), "yoy": (COMPARISON,)},
        },
    },
    "qt.ai.hp.describe": {"consumes": _PANEL, "produces": _NONE},
    "qt.ai.hp.plot": {"consumes": _PANEL, "produces": _NONE},
    "qt.ai.hp.agg": {"consumes": _PANEL, "produces": _FRAME},
    "qt.ai.hp.corr": {"consumes": _PANEL, "produces": _FRAME},
    "qt.ai.hp.performance": {"consumes": _PANEL, "produces": _FRAME},
    "qt.ai.hp.alpha_beta": {
        "consumes": _PANEL,
        "produces": _FRAME,
        "consumes_any_when": {"benchmark": {"": (FRAME, SERIES)}},
    },
    "qt.ai.hp.compare": {"consumes": _PANEL, "produces": (MASK, PANEL)},
    "qt.ai.hp.combine_mask": {"consumes": (MASK,), "produces": (MASK,)},
    "qt.ai.hp.where": {"consumes": (PANEL, MASK), "produces": (MASK, PANEL)},
    "qt.ai.research.universe_filter": {"consumes": _NONE, "produces": (SYMBOLS,)},
    "qt.ai.research.price_predicate": {
        "consumes": (SYMBOLS,),
        "produces": (SYMBOLS, HITS),
    },
    "qt.ai.research.project_universe": {
        "consumes": _NONE,
        "produces": (HITS,),
        "consumes_any": (SYMBOLS, HITS),
    },
}

for _name in (
    "qt.ai.hp.slice",
    "qt.ai.hp.drop",
    "qt.ai.hp.rename",
    "qt.ai.hp.fill",
    "qt.ai.hp.dropna",
    "qt.ai.hp.resample",
    "qt.ai.hp.assign",
    "qt.ai.hp.align",
    "qt.ai.hp.join",
    "qt.ai.hp.shift",
    "qt.ai.hp.diff",
    "qt.ai.hp.pct_change",
    "qt.ai.hp.rank",
    "qt.ai.hp.zscore",
    "qt.ai.hp.rolling",
    "qt.ai.hp.expr",
    "qt.ai.hp.research_preset",
    "qt.ai.hp.portfolio",
    "qt.ai.hp.cum_return",
    "qt.ai.hp.normalize",
):
    _SPECS[_name] = _panel_io()

_SPECS["qt.ai.hp.returns"] = _frame_or_panel(True)
_SPECS["qt.ai.hp.volatility"] = _frame_or_panel(True)
_SPECS["qt.ai.hp.candle_pattern"] = _frame_or_panel(True)
_SPECS["qt.ai.hp.indicator"] = _frame_or_panel(False)


def apply_known_wires(metadata: SkillMetadata) -> None:
    """给已登记的技能挂上线格式。没登记的不动。

    Parameters
    ----------
    metadata : SkillMetadata
        即将注册的技能说明。已有 ``consumes`` 或 ``produces`` 时不覆盖。
    """

    spec = _SPECS.get(metadata.name)
    if spec is None:
        return
    if metadata.consumes is not None or metadata.produces is not None:
        return
    metadata.consumes = spec.get("consumes")  # type: ignore[assignment]
    metadata.produces = spec.get("produces")  # type: ignore[assignment]
    when = spec.get("produces_when")
    if isinstance(when, dict):
        metadata.produces_when = when
    any_of = spec.get("consumes_any")
    if isinstance(any_of, tuple):
        metadata.consumes_any = any_of
    any_when = spec.get("consumes_any_when")
    if isinstance(any_when, dict):
        metadata.consumes_any_when = any_when


def format_wire_digest(metadata: SkillMetadata) -> str:
    """开放组图摘要里的一行线格式。未声明则空串。

    Parameters
    ----------
    metadata : SkillMetadata
        技能说明。

    Returns
    -------
    str
        ``consumes`` / ``produces`` / ``alt`` 片段；不参加检查时为 ``""``。
    """

    if metadata.produces is None and metadata.consumes is None:
        return ""
    parts = [
        "consumes " + _fmt(metadata.consumes),
        "produces " + _fmt(metadata.produces),
    ]
    alts = []
    for key, mapping in (metadata.produces_when or {}).items():
        for token, wires in mapping.items():
            alts.append(f"{key}={token}->{_fmt(wires)}")
    if alts:
        parts.append("alt " + ";".join(alts))
    if metadata.consumes_any:
        parts.append("consumes_any " + _fmt(metadata.consumes_any))
    for key, mapping in (metadata.consumes_any_when or {}).items():
        for token, wires in mapping.items():
            shown = "empty" if token == "" else token
            parts.append(f"consumes_any_when {key}={shown}->{_fmt(wires)}")
    return " ".join(parts)


def _fmt(wires: Optional[Tuple[Wire, ...]]) -> str:
    """把一组线写成 ``key:type``。"""

    if not wires:
        return "none"
    bits = []
    for wire in wires:
        text = f"{wire.key}:{wire.py_type}"
        if wire.dtype:
            text = f"{text}[{wire.dtype}]"
        bits.append(text)
    return ",".join(bits)
