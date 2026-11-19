# coding=utf-8
# ======================================
# File: serve_exit.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-11-12
# Desc:
# qteasy-ai serve 的 Ctrl+C 确认：5 秒内 y 才退出。
# ======================================

"""``qteasy-ai serve`` 控制台 Ctrl+C 的 5 秒确认。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import select
import signal
import sys
import threading
from types import FrameType
from typing import Callable, IO, Iterator, Optional

import uvicorn

CONFIRM_TIMEOUT_S = 5.0
SHUTDOWN_PROMPT = "Shut down this qteasy-ai workbench (y/[n])? "

logger = logging.getLogger("uvicorn.error")


def stdin_is_interactive(stdin: Optional[IO[str]] = None) -> bool:
    """标准输入是交互式终端时才做退出确认。

    管道、重定向和 Windows 保持 uvicorn 收到 SIGINT 立刻退出。

    Parameters
    ----------
    stdin : IO[str], optional
        要检查的流。默认 ``sys.stdin``。

    Returns
    -------
    bool
        可以安全地在该流上提示并 ``select`` 时为 True。
    """

    if sys.platform.startswith("win"):
        return False
    stream = sys.stdin if stdin is None else stdin
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except (OSError, ValueError):
        return False


def interpret_shutdown_line(line: str) -> str:
    """把一行回答收成 ``yes`` 或 ``no``。

    ``y`` / ``yes``（大小写不敏感）为确认。空行、``n`` 以及其余输入都是否定。
    行内同时出现 ``n`` 时否定，与 Jupyter 一致（``yn`` 不退出）。

    Parameters
    ----------
    line : str
        ``readline`` 得到的一行，可含换行。

    Returns
    -------
    str
        ``yes`` 或 ``no``。
    """

    text = line.lower()
    if text.startswith("y") and "n" not in text:
        return "yes"
    return "no"


def wait_shutdown_choice(stdin: IO[str], timeout_s: float = CONFIRM_TIMEOUT_S) -> str:
    """提示并在 ``timeout_s`` 秒内读一行退出确认。

    提示写到 stdout，不带时间戳。超时先换行，让随后的日志从下一行开始。
    有输入时不额外换行：用户按下的回车已经把光标推到下一行。

    Parameters
    ----------
    stdin : IO[str]
        读取确认的文本流，须能被 ``select``（管道或真正的 stdin）。
    timeout_s : float, optional
        等待秒数。默认 5。

    Returns
    -------
    str
        ``yes``、``no`` 或 ``timeout``。
    """

    sys.stdout.write(SHUTDOWN_PROMPT)
    sys.stdout.flush()
    try:
        readable, _, _ = select.select([stdin], [], [], timeout_s)
    except (InterruptedError, OSError, ValueError):
        return "timeout"
    if not readable:
        sys.stdout.write("\n")
        sys.stdout.flush()
        return "timeout"
    try:
        line = stdin.readline()
    except (OSError, ValueError):
        return "no"
    return interpret_shutdown_line(line)


class ConfirmExitServer(uvicorn.Server):
    """单进程 serve。交互式终端上第一次 Ctrl+C 先确认，再关停。"""

    def __init__(self, config: uvicorn.Config) -> None:
        super().__init__(config)
        self._stopping = False
        self._confirming = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        """在 uvicorn 装好处理器之后，仅把交互式 SIGINT 换成确认。

        SIGTERM 仍走 uvicorn，供 Settings Quit 立刻退出。
        离开 ``serve`` 时由父类还原进程原来的处理器。

        Parameters
        ----------
        无

        Yields
        ------
        None
        """

        with super().capture_signals():
            if threading.current_thread() is threading.main_thread() and stdin_is_interactive():
                try:
                    self._loop = asyncio.get_running_loop()
                except RuntimeError:
                    self._loop = None
                if self._loop is not None:
                    self._stopping = False
                    self._confirming = False
                    signal.signal(signal.SIGINT, self._handle_sigint)
            yield

    def _handle_sigint(self, sig: int, frame: Optional[FrameType]) -> None:
        """第一次 Ctrl+C：下一击改为立刻停，并在后台线程里问确认。

        Parameters
        ----------
        sig : int
            信号编号。这里不用。
        frame : FrameType or None
            中断时的栈帧。这里不用。

        Returns
        -------
        None
        """

        del sig, frame
        signal.signal(signal.SIGINT, self._force_stop)
        if self._confirming:
            return
        self._confirming = True
        threading.Thread(target=self._confirm_exit, name="serve-exit-confirm", daemon=True).start()

    def _force_stop(self, sig: int, frame: Optional[FrameType]) -> None:
        """确认还在等时再次 Ctrl+C，或关停过程中再按，立刻停。

        Parameters
        ----------
        sig : int
            信号编号。这里不用。
        frame : FrameType or None
            中断时的栈帧。这里不用。

        Returns
        -------
        None
        """

        del sig, frame
        self._stopping = True
        self.should_exit = True
        self.force_exit = True
        logger.critical("received signal SIGINT, stopping")

    def _confirm_exit(self) -> None:
        """读 5 秒确认。``y`` 关停；其余恢复 SIGINT，服务器继续跑。

        Parameters
        ----------
        无

        Returns
        -------
        None
        """

        logger.info("interrupted")
        choice = wait_shutdown_choice(sys.stdin, CONFIRM_TIMEOUT_S)
        if self._stopping or self.should_exit:
            return
        loop = self._loop
        if loop is None:
            return
        if choice == "yes":
            logger.critical("Shutdown confirmed")
            self._schedule(loop, self._request_shutdown)
            return
        if choice == "timeout":
            logger.info("No answer for 5s:")
        logger.info("resuming operation...")
        self._schedule(loop, self._restore_sigint_handler)

    def _request_shutdown(self) -> None:
        """在事件循环线程上请求 uvicorn 正常关停。

        Parameters
        ----------
        无

        Returns
        -------
        None
        """

        self.should_exit = True

    def _restore_sigint_handler(self) -> None:
        """回到第一次 Ctrl+C 的确认处理器。必须在主线程调用。

        Parameters
        ----------
        无

        Returns
        -------
        None
        """

        if self._stopping or self.should_exit:
            return
        self._confirming = False
        signal.signal(signal.SIGINT, self._handle_sigint)

    @staticmethod
    def _schedule(loop: asyncio.AbstractEventLoop, callback: Callable[[], None]) -> None:
        """把回调排到事件循环上。循环已关时忽略。

        Parameters
        ----------
        loop : asyncio.AbstractEventLoop
            ``serve`` 运行中的事件循环。
        callback : Callable[[], None]
            要在主线程执行的函数。

        Returns
        -------
        None
        """

        try:
            loop.call_soon_threadsafe(callback)
        except RuntimeError:
            return
