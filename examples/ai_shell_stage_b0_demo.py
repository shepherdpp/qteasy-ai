# coding=utf-8
# ======================================
# File: ai_shell_stage_b0_demo.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-25
# Desc:
# Minimal demo for qteasy-ai stage B0
# (env check + data summary plan.md)
# ======================================

from qteasy_ai.app import QteasyAssistant


def main() -> None:
    """运行阶段 B0 最小演示。"""

    assistant = QteasyAssistant()
    env_plan = assistant.plan("帮我看 Tushare 是否配好、本地缺哪些表", response_style="raw")
    print("\n[Demo B0] env plan skills:")
    print([step["skill_name"] for step in env_plan["plan"]["steps"]])
    print("\n[Demo B0] plan_md preview:")
    print(env_plan.get("plan_md", "")[:500])

    summary_plan = assistant.plan(
        "show summary of 000300.SH from 20240101 to 20241231",
        response_style="raw",
    )
    print("\n[Demo B0] summary plan skill:")
    print(summary_plan["plan"]["steps"][0]["skill_name"])
    # 本机有行情表时可改为 run；此处默认仅 plan，避免无数据失败
    # summary_run = assistant.run("show summary of 000300.SH from 20240101 to 20241231", response_style="raw")


if __name__ == "__main__":
    main()
