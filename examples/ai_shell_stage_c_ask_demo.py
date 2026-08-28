# coding=utf-8
# ======================================
# File: ai_shell_stage_c_ask_demo.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-08-28
# Desc:
# Minimal demo for qteasy-ai stage C
# (Ask Offline + preview dry-run)
# ======================================

from qteasy_ai.app import QteasyAssistant


def main() -> None:
    """演示 Ask 目标态（Offline KB）与 preview 干跑。"""

    assistant = QteasyAssistant()
    ask_out = assistant.ask("explain PT vs PS", response_style="raw")
    print("\n[Demo C] Ask mode:", ask_out.get("mode"), "ok:", ask_out.get("ok"))
    print("[Demo C] sources:", ask_out.get("sources"))
    print("[Demo C] answer:\n", ask_out.get("answer", "")[:800])

    preview = assistant.preview(
        "list built-in strategies",
        response_style="raw",
        persist="none",
    )
    print("\n[Demo C] preview status:", preview["execution"]["status"])
    print("[Demo C] preview skills:", [step["skill_name"] for step in preview["plan"]["steps"]])


if __name__ == "__main__":
    main()
