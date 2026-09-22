# coding=utf-8
# ======================================
# File: session_replay_queries.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-22
# Desc:
# 五份历史 Session 的非空 Composer 句（仓内 fixture，不含 live JSON）。
# ======================================

"""回放金标准语料。空 query 的 Change params 不进本表。"""

from typing import Dict, List

ReplayTurn = Dict[str, str]

FIXTURES: Dict[str, List[ReplayTurn]] = {
    "mu9zei7t": [
        {"mode": "ask", "query": "什么是qteasy"},
        {"mode": "plan", "query": "请帮我列出所有内置交易策略"},
        {"mode": "plan", "query": "请帮我列出所有内置交易策略"},
        {"mode": "plan", "query": "请列出内置交易策略的参数和信息"},
        {"mode": "plan", "query": "bband"},
        {"mode": "plan", "query": "strategy_id swma"},
        {"mode": "plan", "query": "请帮我写一个交易策略，基于MACD交易策略，参数为（23，34，67）。"},
        {"mode": "plan", "query": "abandon trial"},
        {"mode": "plan", "query": "abandon open"},
        {"mode": "plan", "query": "abandon open"},
        {"mode": "plan", "query": "abandon trial"},
        {"mode": "plan", "query": "abandon trial"},
    ],
    "muahqq6w": [
        {"mode": "ask", "query": "请介绍一下qteasy"},
        {"mode": "plan", "query": "请帮我列出所有的内置交易策略"},
        {"mode": "plan", "query": "请列出交易策略的参数和信息"},
        {"mode": "plan", "query": "rsi"},
        {"mode": "plan", "query": "strategy_id macd"},
        {"mode": "plan", "query": "请帮我创建一份交易策略，基于MACD，参数为（12， 26， 9）"},
        {"mode": "plan", "query": "abandon trial"},
        {"mode": "plan", "query": "abandon trial"},
        {"mode": "plan", "query": "请帮我下载HS300最近1年的日K线数据"},
        {"mode": "plan", "query": "abandon abandon"},
        {"mode": "plan", "query": "skip"},
    ],
    "mub3do17": [
        {"mode": "plan", "query": "请帮我列出所有内置交易策略"},
        {"mode": "plan", "query": "请告诉我SWMA策略的参数和介绍"},
        {"mode": "plan", "query": "note 我要看MACD的参数"},
        {"mode": "plan", "query": "请帮我看内置交易策略的参数"},
        {"mode": "plan", "query": "bband"},
        {"mode": "plan", "query": "请帮我写一个交易策略"},
        {"mode": "plan", "query": "abandon open"},
        {"mode": "plan", "query": "请帮我看内置交易策略的参数"},
        {"mode": "plan", "query": "skip"},
        {"mode": "plan", "query": "请帮我看内置交易策略的参数"},
        {"mode": "plan", "query": "bband"},
        {"mode": "plan", "query": "strategy_id swma"},
        {"mode": "plan", "query": "note bband"},
    ],
    "mub9u1go": [
        {"mode": "plan", "query": "请列出内置策略的参数和介绍"},
        {"mode": "plan", "query": "dma"},
        {"mode": "plan", "query": "strategy_id trix"},
        {"mode": "plan", "query": "note 列出macd的参数"},
    ],
    "mube2wfi": [
        {"mode": "plan", "query": "请列出所有内置交易策略"},
        {"mode": "plan", "query": "请列出交易策略的参数和介绍"},
        {"mode": "plan", "query": "bband"},
        {"mode": "plan", "query": "请读取最近1年的沪深300指数K线数据并显示为K线图"},
        {"mode": "plan", "query": "请读取最近一年的沪深300指数的K线数据"},
        {"mode": "plan", "query": "请列出TRIX策略的参数"},
        {"mode": "plan", "query": "请读取沪深300指数最近一年的K线数据"},
    ],
}

KLINE_HINTS = ("K线", "k线", "读取")
META_GET_SKILLS = frozenset({"qt.ai.strategy_meta.get"})
DESIGN_KEYS = ("active_design", "trial_queue", "current_trial_plan_id")
