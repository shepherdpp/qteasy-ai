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
from .data_history import build_data_history_skill
from .data_kline import build_data_kline_skill
from .data_reference import build_data_reference_skill
from .data_statement import build_data_statement_skill
from .data_static import build_data_static_skill
from .datasource_tables import build_table_info_skill, build_table_overview_skill
from .dtype_find import build_dtype_find_skill
from .hp_describe import build_hp_describe_skill
from .hp_plot import build_hp_plot_skill
from .hp_shape import (
    build_hp_align_skill,
    build_hp_assign_skill,
    build_hp_drop_skill,
    build_hp_dropna_skill,
    build_hp_fill_skill,
    build_hp_join_skill,
    build_hp_rename_skill,
    build_hp_resample_skill,
    build_hp_slice_skill,
)
from .hp_volatility import build_hp_volatility_skill
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

__all__ = [
    "build_strategy_meta_list_skill",
    "build_strategy_meta_get_skill",
    "build_data_history_skill",
    "build_data_kline_skill",
    "build_data_reference_skill",
    "build_data_statement_skill",
    "build_data_static_skill",
    "build_table_info_skill",
    "build_table_overview_skill",
    "build_dtype_find_skill",
    "build_hp_describe_skill",
    "build_hp_slice_skill",
    "build_hp_drop_skill",
    "build_hp_rename_skill",
    "build_hp_fill_skill",
    "build_hp_dropna_skill",
    "build_hp_resample_skill",
    "build_hp_assign_skill",
    "build_hp_align_skill",
    "build_hp_join_skill",
    "build_hp_plot_skill",
    "build_hp_volatility_skill",
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
