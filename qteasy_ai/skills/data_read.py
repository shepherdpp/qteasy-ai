# coding=utf-8
# ======================================
# File: data_read.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-02
# Desc:
# 只读取数 L1：History / Reference / Static 三入口。
# ======================================

"""按 channel 调用 qteasy 三浅入口。"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from ..contracts import SkillError, SkillMetadata, SkillResult, SkillSideEffects, new_run_id

VALID_CHANNELS = ("history", "reference", "static")


def build_data_read_skill(
    history_func: Callable[..., Any] | None = None,
    reference_func: Callable[..., Any] | None = None,
    static_func: Callable[..., Any] | None = None,
) -> tuple[SkillMetadata, Callable[..., dict]]:
    """构建 ``qt.ai.data.read``。

    Parameters
    ----------
    history_func, reference_func, static_func : callable, optional
        注入三入口；默认 ``qteasy.get_*_data``。

    Returns
    -------
    tuple
        ``(SkillMetadata, handler)``。
    """

    if history_func is None or reference_func is None or static_func is None:
        import qteasy as qt

        history_func = history_func or qt.get_history_data
        reference_func = reference_func or qt.get_reference_data
        static_func = static_func or qt.get_static_data

    metadata = SkillMetadata(
        name="qt.ai.data.read",
        version="0.1.0",
        summary="Read-only fetch via get_history_data / get_reference_data / get_static_data.",
        inputs_schema={
            "channel": {"type": "string", "required": True},
            "names": {"type": "string", "required": False},
            "shares": {"type": "string", "required": False},
            "start": {"type": "string", "required": False},
            "end": {"type": "string", "required": False},
            "freq": {"type": "string", "required": False},
        },
        outputs_schema={"metrics": "dict", "data_summary": "dict"},
        side_effects=SkillSideEffects(description="readonly three-entry fetch"),
        required_capabilities=["local_datasource"],
        qteasy_entrypoints=[
            "qteasy.get_history_data",
            "qteasy.get_reference_data",
            "qteasy.get_static_data",
        ],
        skill_kind="api",
    )

    def handler(
        channel: str = "history",
        names: str = "close",
        shares: str = "",
        start: Optional[str] = None,
        end: Optional[str] = None,
        freq: str = "d",
        **kwargs,
    ) -> dict:
        run_id = new_run_id()
        channel_name = str(channel or "history").strip().lower()
        type_names = str(names or "close").strip() or "close"
        inputs_echo = {
            "channel": channel_name,
            "names": type_names,
            "shares": shares,
            "start": start,
            "end": end,
            "freq": freq,
            **kwargs,
        }
        if channel_name not in VALID_CHANNELS:
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                error=SkillError(
                    code="INVALID_CHANNEL",
                    message="channel must be one of: history, reference, static.",
                ),
            )
            return result.to_dict()
        try:
            if channel_name == "history":
                data = history_func(
                    htype_names=type_names,
                    shares=shares or None,
                    start=start,
                    end=end,
                    freq=freq or "d",
                )
            elif channel_name == "reference":
                data = reference_func(
                    names=type_names,
                    start=start,
                    end=end,
                    freq=freq or None,
                )
            else:
                data = static_func(names=type_names, shares=shares or None)
        except Exception as exc:
            message = str(exc)
            hint = message
            lower = message.lower()
            if "get_reference_data" in lower or "reference" in lower:
                hint = f"{message} Use channel=reference with qt.get_reference_data(...)."
            elif "get_static_data" in lower or "static" in lower:
                hint = f"{message} Use channel=static with qt.get_static_data(...)."
            elif "get_history_data" in lower or "history" in lower:
                hint = f"{message} Use channel=history with qt.get_history_data(...)."
            result = SkillResult(
                ok=False,
                skill_name=metadata.name,
                run_id=run_id,
                inputs_echo=inputs_echo,
                error=SkillError(code="DATA_READ_FAILED", message=hint),
            )
            return result.to_dict()
        n_keys = _data_size(data)
        result = SkillResult(
            ok=True,
            skill_name=metadata.name,
            run_id=run_id,
            inputs_echo=inputs_echo,
            metrics={"n_items": n_keys, "channel": channel_name},
            data_summary={"channel": channel_name, "names": type_names},
            payload={"preview": str(type(data))},
        )
        return result.to_dict()

    return metadata, handler


def _data_size(data: Any) -> int:
    """粗算返回对象规模。"""

    if data is None:
        return 0
    if isinstance(data, dict):
        return len(data)
    shape = getattr(data, "shape", None)
    if shape is not None and len(shape) > 0:
        return int(shape[0])
    try:
        return len(data)
    except TypeError:
        return 1
