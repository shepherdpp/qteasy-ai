# coding=utf-8
# ======================================
# File: ai_shell_stage_g_workbench_demo.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-07
# Desc:
# Minimal demo: build workbench HTTP app
# (same Assistant as CLI).
# ======================================

"""Print how to serve the G workbench. Does not bind a port in CI."""

from qteasy_ai.app import QteasyAssistant
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.workbench.http_app import create_app


def main() -> None:
    """创建应用并打印路由提示。"""

    store = MemoryStore()
    app = create_app(assistant=QteasyAssistant(memory_store=store))
    routes = [getattr(route, "path", str(route)) for route in app.routes]
    print("\n[Demo G] user_kb:", store.user_kb_dir)
    print("[Demo G] routes:", routes)
    print("[Demo G] serve with: qteasy-ai serve --host 127.0.0.1 --port 8765")


if __name__ == "__main__":
    main()
