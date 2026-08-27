# coding=utf-8
# ======================================
# File: ai_shell_stage_b_demo.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-27
# Desc:
# Minimal demo for qteasy-ai stage B
# (refill / backtest / screen plan.md)
# ======================================

from qteasy_ai.app import QteasyAssistant


def main() -> None:
    """运行阶段 B 最小演示（默认只 plan，避免本机无数据/无 token 时误执行）。"""

    assistant = QteasyAssistant()
    p0 = assistant.plan(
        "用 macd 在沪深300上跑 2018-2023 回测，给我看年化与最大回撤",
        response_style="raw",
    )
    print("\n[Demo B] P0 plan skills:")
    print([step["skill_name"] for step in p0["plan"]["steps"]])
    print("\n[Demo B] plan_md preview:")
    print(p0.get("plan_md", "")[:600])

    screen = assistant.plan(
        "请搜索过去半年内所有跌幅>20%，且行业属于制造业的股票。",
        response_style="raw",
    )
    print("\n[Demo B] screen plan skill/inputs:")
    print(screen["plan"]["steps"][0]["skill_name"], screen["plan"]["steps"][0]["inputs"])

    refill = assistant.plan(
        "download daily data from 20180101 to 20231231",
        response_style="raw",
    )
    print("\n[Demo B] refill plan skill:")
    print(refill["plan"]["steps"][0]["skill_name"])
    # 本机已配置 TUSHARE_TOKEN 且接受高副作用时，可改为 assistant.run(...)
    # CLI `qteasy-ai run "..."` 视为人在回路的一次确认；Notebook %%qtai --mode run 仍需 --confirm
    # refill_run = assistant.run("download daily data from 20180101 to 20231231", response_style="raw")


if __name__ == "__main__":
    main()
