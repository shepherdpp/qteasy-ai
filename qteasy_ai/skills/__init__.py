# coding=utf-8
# ======================================
# File: __init__.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-04-15
# Desc:
# qteasy AI 技能导出入口。
# ======================================

"""阶段 A/B 技能集合。"""

from .backtest_run import build_backtest_run_skill
from .data_refill import build_data_refill_skill
from .data_summary import build_data_summary_skill
from .env_guide import build_check_tushare_skill, build_overview_tables_skill
from .insight_backtest import build_insight_backtest_skill
from .live_plan import build_live_trade_plan_only_skill
from .optimize_run import build_optimize_run_skill
from .operator_from_spec import build_operator_from_spec_skill
from .research_factor_ic import build_factor_ic_summary_skill
from .research_screen import (
    build_price_predicate_skill,
    build_project_universe_skill,
    build_research_screen_skill,
    build_universe_filter_skill,
)
from .data_read import build_data_read_skill
from .strategy_codegen import build_strategy_codegen_hybrid_skill
from .strategy_meta import build_strategy_meta_get_skill, build_strategy_meta_list_skill
from .strategy_sanity import build_strategy_sanity_check_skill
from .strategy_spec import build_strategy_spec_from_nl_skill
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
    "build_data_refill_skill",
    "build_backtest_run_skill",
    "build_optimize_run_skill",
    "build_research_screen_skill",
    "build_universe_filter_skill",
    "build_price_predicate_skill",
    "build_project_universe_skill",
    "build_data_read_skill",
    "build_insight_backtest_skill",
    "build_strategy_spec_from_nl_skill",
    "build_strategy_codegen_hybrid_skill",
    "build_strategy_sanity_check_skill",
    "build_operator_from_spec_skill",
    "build_live_trade_plan_only_skill",
]
