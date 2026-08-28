# coding=utf-8
# ======================================
# File: explanation.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-28
# Desc:
# qteasy-ai 解释层模板：按深度裁剪
# narrative / python_code / result_preview。
# ======================================

"""可配置深度的解释层模板。

Ask 与 Plan pretty 共用同一套通道，避免两套叙事。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


VALID_DEPTHS = ("brief", "standard", "deep")


@dataclass
class ExplanationChannels:
    """解释层三通道（raw 由调用方另行携带）。"""

    narrative: str
    python_code: str
    result_preview: str


def normalize_explanation_depth(depth: str) -> str:
    """将深度参数归一为 brief / standard / deep。"""

    value = str(depth or "standard").strip().lower()
    if value not in VALID_DEPTHS:
        return "standard"
    return value


def apply_explanation_depth(
    *,
    narrative: str,
    python_code: str,
    result_preview: str,
    depth: str = "standard",
    risk_notes: str = "",
) -> ExplanationChannels:
    """按深度裁剪解释通道。

    Parameters
    ----------
    narrative : str
        完整叙事。
    python_code : str
        可复现示例代码。
    result_preview : str
        结果/来源预览。
    depth : {'brief', 'standard', 'deep'}, default 'standard'
        brief 仅保留 narrative（python_code 置空）；
        standard 三通道齐全；
        deep 在 narrative 中追加风险/假设提示，并保留完整代码。
    risk_notes : str, optional
        deep 模式追加的风险说明。

    Returns
    -------
    ExplanationChannels
        裁剪后的三通道。
    """

    level = normalize_explanation_depth(depth)
    text = (narrative or "").strip()
    code = (python_code or "").strip()
    preview = (result_preview or "").strip()
    notes = (risk_notes or "").strip()

    if level == "brief":
        return ExplanationChannels(narrative=text, python_code="", result_preview=preview)

    if level == "deep":
        extra_parts = []
        if notes:
            extra_parts.append(f"Risk / assumptions:\n{notes}")
        if extra_parts:
            text = text + "\n\n" + "\n\n".join(extra_parts)
        return ExplanationChannels(
            narrative=text,
            python_code=code,
            result_preview=preview,
        )

    return ExplanationChannels(narrative=text, python_code=code, result_preview=preview)


def channels_to_dict(channels: ExplanationChannels) -> Dict[str, Any]:
    """转为字典。"""

    return {
        "narrative": channels.narrative,
        "python_code": channels.python_code,
        "result_preview": channels.result_preview,
    }
