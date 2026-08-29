# coding=utf-8
# ======================================
# File: ai_shell_stage_d_strategybuilder_demo.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-29
# Desc:
# Minimal demo for qteasy-ai stage D
# (StrategyBuilder plan dry-run)
# ======================================

from qteasy_ai.app import QteasyAssistant

GOLDEN = (
    "帮我写一个基于 20/60 日均线金叉死叉的择时策略，"
    "并用 2015–2020 年沪深300做回测"
)


def main() -> None:
    """演示 StrategyBuilder 金句的 Plan dry-run（不写盘、不回测）。"""

    assistant = QteasyAssistant()
    plan_out = assistant.plan(GOLDEN, response_style="raw", persist="none")
    steps = plan_out["plan"]["steps"]
    names = [step["skill_name"] for step in steps]
    print("\n[Demo D] mode:", plan_out.get("mode") or plan_out["plan"].get("execution_mode"))
    print("[Demo D] execution:", plan_out["execution"]["status"])
    print("[Demo D] skills:", names)
    print("[Demo D] depends_on:", [step.get("depends_on") for step in steps])

    live = assistant.plan("start live trade now", response_style="raw", persist="none")
    print("[Demo D] live skill:", live["plan"]["steps"][0]["skill_name"])


if __name__ == "__main__":
    main()
