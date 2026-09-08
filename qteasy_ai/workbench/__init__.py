# coding=utf-8
# ======================================
# File: __init__.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-07
# Desc:
# qteasy-ai 工作台壳（G）：DTO / HTTP / TUI。
# ======================================

"""工作台壳：Web 与最小 TUI 共用 DTO，不重做 Planner。"""

from .dto import WorkbenchState
from .mapper import classify_artifacts, map_assistant_payload

__all__ = ["WorkbenchState", "classify_artifacts", "map_assistant_payload"]
