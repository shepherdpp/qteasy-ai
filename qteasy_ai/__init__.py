# coding=utf-8
# ======================================
# File: __init__.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-04-15
# Desc:
# qteasy AI 外壳包导出入口，汇总
# 阶段A公开类型与核心对象。
# ======================================

"""qteasy AI 外壳模块（S1.4 阶段A，独立包 qteasy_ai）。"""

__version__ = '0.1.0'

from .contracts import (
    PlanExecutionRecord,
    PlanStepRecord,
    SkillError,
    SkillMetadata,
    SkillResult,
    SkillSideEffects,
    ToolPlan,
    ToolStep,
    new_plan_id,
    new_run_id,
)
from .executor import PlanExecutor
from .config import ConfigCenter
from .output import AssistantOutput
from .memory_store import MemoryStore, merge_env_facts
from .plan_markdown import tool_plan_to_markdown
from .planner import Planner
from .provider import BaseLLMProvider, OpenAICompatProvider
from .renderer import OutputRenderer
from .registry import SkillRegistry
from .run_policy import RunStorePolicy
from .runtime import SkillRuntime

__all__ = [
    "SkillMetadata",
    "SkillSideEffects",
    "ToolStep",
    "ToolPlan",
    "SkillError",
    "SkillResult",
    "PlanStepRecord",
    "PlanExecutionRecord",
    "new_plan_id",
    "new_run_id",
    "SkillRegistry",
    "Planner",
    "PlanExecutor",
    "ConfigCenter",
    "AssistantOutput",
    "OutputRenderer",
    "RunStorePolicy",
    "SkillRuntime",
    "MemoryStore",
    "merge_env_facts",
    "tool_plan_to_markdown",
    "BaseLLMProvider",
    "OpenAICompatProvider",
]
