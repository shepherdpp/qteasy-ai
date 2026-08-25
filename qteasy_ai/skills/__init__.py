# coding=utf-8
# ======================================
# File: __init__.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-04-15
# Desc:
# qteasy AI 阶段A只读技能导出入口。
# ======================================

"""阶段A/B0 只读与引导技能集合。"""

from .data_summary import build_data_summary_skill
from .env_guide import build_check_tushare_skill, build_overview_tables_skill
from .research_factor_ic import build_factor_ic_summary_skill
from .strategy_meta import build_strategy_meta_get_skill, build_strategy_meta_list_skill
from .system_fallback import build_system_fallback_skill
from .visual_export import build_visual_export_skill

__all__ = [
    "build_strategy_meta_list_skill",
    "build_strategy_meta_get_skill",
    "build_data_summary_skill",
    "build_visual_export_skill",
    "build_system_fallback_skill",
    "build_check_tushare_skill",
    "build_overview_tables_skill",
    "build_factor_ic_summary_skill",
]
