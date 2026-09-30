# coding=utf-8
# ======================================
# File: serve_log.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-30
# Desc:
# workbench serve 的控制台日志：时间戳、去掉客户端地址，
# 并把 qteasy core 的 stderr 调到 WARNING。
# ======================================

"""``qteasy-ai serve`` 的控制台日志配置。"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict

SERVE_LOG_DATEFMT = "%m-%d %H:%M:%S"


def build_serve_log_config() -> Dict[str, Any]:
    """复制 uvicorn 默认日志配置，加上时间并去掉客户端地址。

    Parameters
    ----------
    无

    Returns
    -------
    dict
        传给 ``uvicorn.run(log_config=...)`` 的配置。不改 uvicorn 包内全局字典。
    """

    import uvicorn.config

    cfg = copy.deepcopy(uvicorn.config.LOGGING_CONFIG)
    cfg["formatters"]["default"]["fmt"] = "%(asctime)s %(levelprefix)s %(message)s"
    cfg["formatters"]["default"]["datefmt"] = SERVE_LOG_DATEFMT
    cfg["formatters"]["access"]["fmt"] = (
        '%(asctime)s %(levelprefix)s "%(request_line)s" %(status_code)s'
    )
    cfg["formatters"]["access"]["datefmt"] = SERVE_LOG_DATEFMT
    return cfg


def configure_qteasy_console_for_serve() -> None:
    """把 qteasy ``core`` 的控制台 handler 调到 WARNING，并换上带颜色的格式。

    只改非文件的 ``StreamHandler``。文件日志的级别和格式保持不变。
    就地修改已有 handler，不另加一条，避免同一条 ERROR 打两遍。

    Parameters
    ----------
    无

    Returns
    -------
    None
    """

    import qteasy  # noqa: F401  导入即挂上 core logger
    from uvicorn.logging import DefaultFormatter

    formatter = DefaultFormatter(
        "%(asctime)s %(levelprefix)s %(module)s - %(message)s",
        datefmt=SERVE_LOG_DATEFMT,
    )
    logger = logging.getLogger("core")
    for handler in logger.handlers:
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler):
            handler.setLevel(logging.WARNING)
            handler.setFormatter(formatter)
