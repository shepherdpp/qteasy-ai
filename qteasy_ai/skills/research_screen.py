# coding=utf-8
# ======================================
# File: research_screen.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-27
# Desc:
# qteasy AI 阶段 B L2：只读筛股（行业精确匹配
# + 本地行情区间收益）。
# ======================================

"""只读筛股技能（规则抽参，不自动 refill）。"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence

import pandas as pd

from ..contracts import SkillError, SkillMetadata, SkillResult, SkillSideEffects, new_run_id

MAX_INDUSTRY_SAMPLES = 15
DEFAULT_MAX_HITS = 50


def _to_yyyymmdd(value: Any) -> str:
    """将日期值格式化为 YYYYMMDD。"""

    return pd.to_datetime(value).strftime("%Y%m%d")


def _default_latest_screen_end() -> str:
    """取本地 stock_daily 最新交易日；读不到则退回今天。"""

    try:
        from qteasy import QT_DATA_SOURCE

        info = QT_DATA_SOURCE.get_table_info(
            table="stock_daily",
            verbose=False,
            print_info=False,
            human=False,
        )
        raw = (info or {}).get("pk_max2")
        if raw is not None and str(raw).strip() not in {"", "N/A", "None"}:
            return _to_yyyymmdd(raw)
    except Exception:
        pass
    return pd.Timestamp.today().strftime("%Y%m%d")


def _resolve_screen_window(
    start: Optional[str],
    end: Optional[str],
    lookback_days: int,
    latest_end_func: Callable[[], str],
) -> tuple:
    """为筛股补齐 start/end。

    ``qt.get_history_data`` 不允许 start 与 end 同时为空；仅传 ``rows``
    仍会在底层报错。缺省 end 取本地行情最新日，start 按 lookback 交易日
    折成日历跨度（含节假日缓冲）。
    """

    end_value = str(end).strip() if end else ""
    start_value = str(start).strip() if start else ""
    if not end_value:
        end_value = str(latest_end_func() or "").strip() or pd.Timestamp.today().strftime("%Y%m%d")
    end_value = _to_yyyymmdd(end_value)
    if not start_value:
        span = max(int(lookback_days or 0) * 7 // 5 + 14, 8)
        start_value = (pd.to_datetime(end_value) - pd.Timedelta(days=span)).strftime("%Y%m%d")
    else:
        start_value = _to_yyyymmdd(start_value)
    return start_value, end_value


def _series_from_history_item(item: Any) -> Optional[pd.Series]:
    """从单标的历史对象取出 close 序列。"""

    if item is None:
        return None
    if isinstance(item, pd.Series):
        return item.dropna()
    if isinstance(item, pd.DataFrame):
        if item.empty:
            return None
        col = "close" if "close" in item.columns else item.columns[0]
        return item[col].astype(float).dropna()
    return None


def _closes_by_symbol(data: Any, symbols: Sequence[str]) -> Dict[str, pd.Series]:
    """将 get_history_data / 注入结果归一为 symbol -> close Series。"""

    result: Dict[str, pd.Series] = {}
    if data is None:
        return result
    if isinstance(data, dict):
        for symbol in symbols:
            series = _series_from_history_item(data.get(symbol))
            if series is not None and len(series) >= 2:
                result[symbol] = series
        if result:
            return result
        for key, item in data.items():
            series = _series_from_history_item(item)
            if series is not None and len(series) >= 2:
                result[str(key)] = series
        return result
    if isinstance(data, pd.DataFrame):
        if data.empty:
            return result
        if isinstance(data.columns, pd.MultiIndex):
            for symbol in symbols:
                try:
                    subset = data.loc[:, symbol]
                except Exception:
                    continue
                series = _series_from_history_item(subset)
                if series is not None and len(series) >= 2:
                    result[symbol] = series
            return result
        if len(symbols) == 1 and "close" in data.columns:
            series = _series_from_history_item(data)
            if series is not None and len(series) >= 2:
                result[symbols[0]] = series
            return result
        for col in data.columns:
            series = data[col].astype(float).dropna()
            if len(series) >= 2:
                result[str(col)] = series
        return result
    # HistoryPanel: 尽量用 to_df / slice，失败则忽略
    to_df = getattr(data, "slice_to_dataframe", None) or getattr(data, "to_dataframe", None)
    if callable(to_df):
        try:
            frame = to_df()
            return _closes_by_symbol(frame, symbols)
        except Exception:
            return result
    return result


def _default_list_industries() -> List[str]:
    """从本地 stock_basic 读取行业短名样例。"""

    from qteasy import QT_DATA_SOURCE

    basic = QT_DATA_SOURCE.read_table_data("stock_basic")
    if basic is None or basic.empty or "industry" not in basic.columns:
        return []
    values = [str(item).strip() for item in basic["industry"].dropna().unique().tolist() if str(item).strip()]
    return sorted(set(values))


def build_research_screen_skill(
    filter_stocks_func: Callable[..., pd.DataFrame] | None = None,
    history_func: Callable[..., Any] | None = None,
    list_industries_func: Callable[[], List[str]] | None = None,
    latest_end_func: Callable[[], str] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建只读筛股技能。

    Parameters
    ----------
    filter_stocks_func : callable, optional
        注入 ``qteasy.filter_stocks``。
    history_func : callable, optional
        注入行情读取（``get_history_data`` / ``get_kline``）。
    list_industries_func : callable, optional
        返回数据源中的行业短名列表，供 0 命中澄清。
    latest_end_func : callable, optional
        返回本地行情最新交易日（YYYYMMDD）；缺省读 stock_daily 主键。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。
    """

    if filter_stocks_func is None:
        import qteasy as qt

        filter_stocks_func = qt.filter_stocks
    if history_func is None:
        import qteasy as qt

        history_func = qt.get_history_data
    if list_industries_func is None:
        list_industries_func = _default_list_industries
    if latest_end_func is None:
        latest_end_func = _default_latest_screen_end

    metadata = SkillMetadata(
        name="qt.ai.research.screen_stocks",
        version="0.2.0",
        summary="Screen local stocks by industry (exact match) and lookback simple return.",
        inputs_schema={
            "industry": {"type": "string", "required": True},
            "threshold": {"type": "number", "required": True},
            "metric": {"type": "string", "required": False},
            "lookback_days": {"type": "integer", "required": False},
            "start": {"type": "string", "required": False},
            "end": {"type": "string", "required": False},
            "max_hits": {"type": "integer", "required": False},
        },
        outputs_schema={"metrics": "dict", "payload": "dict"},
        side_effects=SkillSideEffects(
            heavy_compute=True,
            description="readonly full-universe scan on local data",
        ),
        required_capabilities=["local_datasource"],
        qteasy_entrypoints=["qteasy.filter_stocks", "qteasy.get_history_data"],
        skill_kind="api",
    )

    def handler(
        industry: str = "",
        threshold: float = 0.0,
        metric: str = "drawdown",
        lookback_days: int = 126,
        start: Optional[str] = None,
        end: Optional[str] = None,
        max_hits: int = DEFAULT_MAX_HITS,
        **kwargs,
    ) -> dict:
        run_id = new_run_id()
        industry_name = str(industry).strip()
        metric_name = str(metric or "drawdown").strip().lower()
        thresh = float(threshold)
        inputs_echo = {
            "industry": industry_name,
            "threshold": thresh,
            "metric": metric_name,
            "lookback_days": lookback_days,
            "start": start,
            "end": end,
            "max_hits": max_hits,
            **kwargs,
        }
        try:
            catalog = list(list_industries_func() or [])
            if industry_name and catalog and industry_name not in catalog:
                samples = catalog[:MAX_INDUSTRY_SAMPLES]
                result = SkillResult(
                    ok=False,
                    skill_name=metadata.name,
                    run_id=run_id,
                    inputs_echo=inputs_echo,
                    error=SkillError(
                        code="CLARIFY_REQUIRED",
                        message=(
                            f"Industry '{industry_name}' has 0 exact matches in stock_basic. "
                            "stock_basic.industry uses Tushare short names, not national GB categories. "
                            "Please pick one of the sample industry names."
                        ),
                        details={
                            "missing_info": "industry",
                            "industry_samples": samples,
                        },
                    ),
                    payload={"industry_samples": samples, "hit_count": 0},
                )
                return result.to_dict()
            pool = filter_stocks_func(industry=industry_name) if industry_name else filter_stocks_func()
            if pool is None or (hasattr(pool, "empty") and pool.empty):
                samples = (catalog or list_industries_func() or [])[:MAX_INDUSTRY_SAMPLES]
                result = SkillResult(
                    ok=False,
                    skill_name=metadata.name,
                    run_id=run_id,
                    inputs_echo=inputs_echo,
                    error=SkillError(
                        code="CLARIFY_REQUIRED",
                        message=(
                            f"Industry '{industry_name}' matched 0 stocks. "
                            "Please use an exact Tushare industry short name from the samples."
                        ),
                        details={
                            "missing_info": "industry",
                            "industry_samples": samples,
                        },
                    ),
                    payload={"industry_samples": samples, "hit_count": 0},
                )
                return result.to_dict()
            if hasattr(pool, "index"):
                symbols = [str(item) for item in pool.index.tolist()]
            else:
                symbols = [str(item) for item in list(pool)]
            names: Dict[str, str] = {}
            if hasattr(pool, "columns") and "name" in pool.columns:
                for code in symbols:
                    try:
                        names[code] = str(pool.loc[code, "name"])
                    except Exception:
                        names[code] = code
            start_date, end_date = _resolve_screen_window(
                start,
                end,
                int(lookback_days or 126),
                latest_end_func,
            )
            inputs_echo["start"] = start_date
            inputs_echo["end"] = end_date
            history = history_func(
                htype_names="close",
                shares=symbols,
                start=start_date,
                end=end_date,
                freq="d",
            )
            closes = _closes_by_symbol(history, symbols)
            if not closes:
                result = SkillResult(
                    ok=False,
                    skill_name=metadata.name,
                    run_id=run_id,
                    inputs_echo=inputs_echo,
                    error=SkillError(
                        code="SCREEN_DATA_MISSING",
                        message=(
                            "No local price data for screening. "
                            "Run env check or refill stock_daily first; this skill never auto-refills."
                        ),
                    ),
                )
                return result.to_dict()
            hits: List[Dict[str, Any]] = []
            window = int(lookback_days or 0)
            for symbol, series in closes.items():
                if window > 0 and len(series) > window:
                    series = series.iloc[-window:]
                start_close = float(series.iloc[0])
                end_close = float(series.iloc[-1])
                if start_close == 0:
                    continue
                ret = end_close / start_close - 1.0
                matched = False
                if metric_name in {"drawdown", "drop", "跌幅"}:
                    matched = ret <= -abs(thresh)
                else:
                    matched = ret >= abs(thresh)
                if matched:
                    try:
                        start_px_date = _to_yyyymmdd(series.index[0])
                    except Exception:
                        start_px_date = str(series.index[0])
                    try:
                        end_px_date = _to_yyyymmdd(series.index[-1])
                    except Exception:
                        end_px_date = str(series.index[-1])
                    hits.append(
                        {
                            "symbol": symbol,
                            "name": names.get(symbol, symbol),
                            "return": float(ret),
                            "start_price": start_close,
                            "end_price": end_close,
                            "start_date": start_px_date,
                            "end_date": end_px_date,
                        }
                    )
            hits.sort(key=lambda item: item["return"])
            truncated = False
            limit = int(max_hits or DEFAULT_MAX_HITS)
            if len(hits) > limit:
                hits = hits[:limit]
                truncated = True
            result = SkillResult(
                ok=True,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                metrics={"hit_count": len(hits)},
                data_summary={
                    "industry": industry_name,
                    "universe_size": len(symbols),
                    "priced_size": len(closes),
                    "end_default": "latest trading day in local datasource",
                },
                payload={"hits": hits},
                warnings=(
                    [f"Hit list truncated to max_hits={limit}."]
                    if truncated
                    else []
                ),
            )
        except Exception as exc:
            message = str(exc)
            if "stock_basic" in message.lower() or "no stock basic" in message.lower():
                result = SkillResult(
                    ok=False,
                    skill_name=metadata.name,
                    run_id=run_id,
                    inputs_echo=inputs_echo,
                    error=SkillError(
                        code="SCREEN_DATA_MISSING",
                        message=(
                            "Local stock_basic (or price tables) are missing. "
                            "Run env check or refill first; screening never auto-downloads."
                        ),
                    ),
                )
                return result.to_dict()
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                error=SkillError(
                    code="SCREEN_FAILED",
                    message=f"Failed to screen stocks: {exc}",
                ),
            )
        return result.to_dict()

    return metadata, handler


def _industry_miss_result(
    *,
    skill_name: str,
    run_id: str,
    inputs_echo: Dict[str, Any],
    industry_name: str,
    samples: List[str],
    hit_count: int = 0,
) -> dict:
    """行业 0 命中时返回样例，避免静默空集。"""

    result = SkillResult(
        ok=False,
        skill_name=skill_name,
        run_id=run_id,
        inputs_echo=inputs_echo,
        error=SkillError(
            code="CLARIFY_REQUIRED",
            message=(
                f"Industry '{industry_name}' has 0 exact matches in stock_basic. "
                "stock_basic.industry uses Tushare short names, not national GB categories. "
                "Please pick one of the sample industry names."
            ),
            details={
                "missing_info": "industry",
                "industry_samples": samples,
            },
        ),
        payload={"industry_samples": samples, "hit_count": hit_count},
    )
    return result.to_dict()


def build_universe_filter_skill(
    filter_stocks_func: Callable[..., pd.DataFrame] | None = None,
    list_industries_func: Callable[[], List[str]] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """Universe L1：``filter_stocks`` 行业精确匹配。"""

    if filter_stocks_func is None:
        import qteasy as qt

        filter_stocks_func = qt.filter_stocks
    if list_industries_func is None:
        list_industries_func = _default_list_industries

    metadata = SkillMetadata(
        name="qt.ai.research.universe_filter",
        version="0.1.0",
        summary="Filter local stock universe by exact Tushare industry short name.",
        inputs_schema={
            "industry": {"type": "string", "required": True},
        },
        outputs_schema={"metrics": "dict", "payload": "dict"},
        side_effects=SkillSideEffects(description="readonly filter_stocks"),
        required_capabilities=["local_datasource"],
        qteasy_entrypoints=["qteasy.filter_stocks"],
        skill_kind="api",
    )

    def handler(industry: str = "", **kwargs) -> dict:
        run_id = new_run_id()
        industry_name = str(industry).strip()
        inputs_echo = {"industry": industry_name, **kwargs}
        catalog = list(list_industries_func() or [])
        if industry_name and catalog and industry_name not in catalog:
            return _industry_miss_result(
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                industry_name=industry_name,
                samples=catalog[:MAX_INDUSTRY_SAMPLES],
            )
        pool = filter_stocks_func(industry=industry_name) if industry_name else filter_stocks_func()
        if pool is None or (hasattr(pool, "empty") and pool.empty):
            samples = (catalog or list_industries_func() or [])[:MAX_INDUSTRY_SAMPLES]
            return _industry_miss_result(
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                industry_name=industry_name,
                samples=samples,
            )
        if hasattr(pool, "index"):
            symbols = [str(item) for item in pool.index.tolist()]
        else:
            symbols = [str(item) for item in list(pool)]
        names: Dict[str, str] = {}
        if hasattr(pool, "columns") and "name" in pool.columns:
            for code in symbols:
                try:
                    names[code] = str(pool.loc[code, "name"])
                except Exception:
                    names[code] = code
        result = SkillResult(
            ok=True,
            skill_name=metadata.name,
            run_id=run_id,
            inputs_echo=inputs_echo,
            metrics={"universe_size": len(symbols)},
            payload={"symbols": symbols, "names": names, "industry": industry_name},
        )
        return result.to_dict()

    return metadata, handler


def build_price_predicate_skill(
    history_func: Callable[..., Any] | None = None,
    latest_end_func: Callable[[], str] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """可选价格谓词 L1：区间简单收益阈值。"""

    if history_func is None:
        import qteasy as qt

        history_func = qt.get_history_data
    if latest_end_func is None:
        latest_end_func = _default_latest_screen_end

    metadata = SkillMetadata(
        name="qt.ai.research.price_predicate",
        version="0.1.0",
        summary="Optional lookback simple-return predicate on an upstream universe.",
        inputs_schema={
            "threshold": {"type": "number", "required": True},
            "metric": {"type": "string", "required": False},
            "lookback_days": {"type": "integer", "required": False},
            "start": {"type": "string", "required": False},
            "end": {"type": "string", "required": False},
            "upstream_payload": {"type": "object", "required": False},
        },
        outputs_schema={"metrics": "dict", "payload": "dict"},
        side_effects=SkillSideEffects(
            heavy_compute=True,
            description="readonly local price scan",
        ),
        required_capabilities=["local_datasource"],
        qteasy_entrypoints=["qteasy.get_history_data"],
        skill_kind="api",
    )

    def handler(
        threshold: float = 0.0,
        metric: str = "drawdown",
        lookback_days: int = 126,
        start: Optional[str] = None,
        end: Optional[str] = None,
        upstream_payload: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> dict:
        run_id = new_run_id()
        metric_name = str(metric or "drawdown").strip().lower()
        thresh = float(threshold)
        payload_in = dict(upstream_payload or {})
        symbols = [str(item) for item in (payload_in.get("symbols") or [])]
        names = dict(payload_in.get("names") or {})
        inputs_echo = {
            "threshold": thresh,
            "metric": metric_name,
            "lookback_days": lookback_days,
            "start": start,
            "end": end,
            **kwargs,
        }
        if not symbols:
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                error=SkillError(
                    code="SCREEN_DATA_MISSING",
                    message="Price predicate needs an upstream universe (symbols).",
                ),
            )
            return result.to_dict()
        start_date, end_date = _resolve_screen_window(
            start, end, int(lookback_days or 126), latest_end_func
        )
        inputs_echo["start"] = start_date
        inputs_echo["end"] = end_date
        history = history_func(
            htype_names="close",
            shares=symbols,
            start=start_date,
            end=end_date,
            freq="d",
        )
        closes = _closes_by_symbol(history, symbols)
        hits: List[Dict[str, Any]] = []
        window = int(lookback_days or 0)
        for symbol, series in closes.items():
            if window > 0 and len(series) > window:
                series = series.iloc[-window:]
            start_close = float(series.iloc[0])
            end_close = float(series.iloc[-1])
            if start_close == 0:
                continue
            ret = end_close / start_close - 1.0
            if metric_name in {"drawdown", "drop", "跌幅"}:
                matched = ret <= -abs(thresh)
            else:
                matched = ret >= abs(thresh)
            if not matched:
                continue
            try:
                start_px_date = _to_yyyymmdd(series.index[0])
            except Exception:
                start_px_date = str(series.index[0])
            try:
                end_px_date = _to_yyyymmdd(series.index[-1])
            except Exception:
                end_px_date = str(series.index[-1])
            hits.append(
                {
                    "symbol": symbol,
                    "name": names.get(symbol, symbol),
                    "return": float(ret),
                    "start_price": start_close,
                    "end_price": end_close,
                    "start_date": start_px_date,
                    "end_date": end_px_date,
                }
            )
        hits.sort(key=lambda item: item["return"])
        result = SkillResult(
            ok=True,
            skill_name=metadata.name,
            run_id=run_id,
            inputs_echo=inputs_echo,
            metrics={"hit_count": len(hits)},
            payload={
                "hits": hits,
                "symbols": [item["symbol"] for item in hits],
                "names": names,
                "industry": payload_in.get("industry", ""),
            },
        )
        return result.to_dict()

    return metadata, handler


def build_project_universe_skill() -> tuple[SkillMetadata, Callable[..., dict]]:
    """投影 L1：输出 hits 或无阈值时的 universe 枚举。"""

    metadata = SkillMetadata(
        name="qt.ai.research.project_universe",
        version="0.1.0",
        summary="Project universe or predicate hits to a user-facing table.",
        inputs_schema={
            "max_hits": {"type": "integer", "required": False},
            "upstream_payload": {"type": "object", "required": False},
        },
        outputs_schema={"metrics": "dict", "payload": "dict"},
        side_effects=SkillSideEffects(description="readonly projection"),
        required_capabilities=[],
        qteasy_entrypoints=[],
        skill_kind="api",
    )

    def handler(
        max_hits: int = DEFAULT_MAX_HITS,
        upstream_payload: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> dict:
        run_id = new_run_id()
        payload_in = dict(upstream_payload or {})
        hits = list(payload_in.get("hits") or [])
        enumerated = False
        if not hits:
            enumerated = True
            names = dict(payload_in.get("names") or {})
            for symbol in payload_in.get("symbols") or []:
                hits.append({"symbol": str(symbol), "name": names.get(str(symbol), str(symbol))})
        limit = int(max_hits or DEFAULT_MAX_HITS)
        truncated = False
        if len(hits) > limit:
            hits = hits[:limit]
            truncated = True
        result = SkillResult(
            ok=True,
            skill_name=metadata.name,
            run_id=run_id,
            inputs_echo={"max_hits": limit, **kwargs},
            metrics={"hit_count": len(hits), "enumerated": enumerated},
            payload={"hits": hits, "industry_samples": payload_in.get("industry_samples") or []},
            warnings=([f"Hit list truncated to max_hits={limit}."] if truncated else []),
        )
        return result.to_dict()

    return metadata, handler

