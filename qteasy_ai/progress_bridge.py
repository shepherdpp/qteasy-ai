# coding=utf-8
# ======================================
# File: progress_bridge.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-09-23
# Desc:
# 只桥 qteasy.core.tqdm，把 refill 批进度接到 on_progress。
# ======================================

"""把 ``qteasy.core.tqdm.update`` 转发到本线程 contextvar。

只替换 ``qteasy.core.tqdm``，不改内核签名，不桥 ``optimization``。
装一次、不在 finally 里换回去。未绑定回调时行为与原 tqdm 相同。
"""

from __future__ import annotations

import time
from contextvars import ContextVar, Token
from typing import Any, Callable, Optional

_ProgressCb = Callable[[int, int, str], None]

_progress_cb: ContextVar[Optional[_ProgressCb]] = ContextVar("qt_ai_tqdm_progress", default=None)
_last_emit: ContextVar[tuple] = ContextVar("qt_ai_tqdm_last", default=(0.0, -1.0))

_THROTTLE_S = 0.4
_THROTTLE_RATIO = 0.01
_patched = False


def bind_progress_callback(callback: Optional[_ProgressCb]) -> Token:
    """在本线程绑定 tqdm 进度回调。"""

    _last_emit.set((0.0, -1.0))
    return _progress_cb.set(callback)


def reset_progress_callback(token: Token) -> None:
    """恢复绑定时的 contextvar。"""

    _progress_cb.reset(token)


def _should_emit(done: int, total: int) -> bool:
    """首尾必推；中间按约 1% 或 0.4s 节流。"""

    now = time.monotonic()
    last_t, last_ratio = _last_emit.get()
    ratio = (float(done) / float(total)) if total else 0.0
    first = last_ratio < 0
    last_batch = total > 0 and done >= total
    if first or last_batch or (now - last_t) >= _THROTTLE_S or abs(ratio - last_ratio) >= _THROTTLE_RATIO:
        _last_emit.set((now, ratio))
        return True
    return False


def install_qteasy_tqdm_bridge() -> None:
    """把 ``qteasy.core.tqdm`` 换成会转发的子类。重复调用是 no-op。"""

    global _patched
    if _patched:
        return
    try:
        import qteasy.core as qt_core
    except Exception:
        return
    base = getattr(qt_core, "tqdm", None)
    if base is None:
        return

    class BridgedTqdm(base):
        """转发 update 到本线程 on_progress。"""

        def update(self, n: Any = 1) -> Any:
            result = super().update(n)
            cb = _progress_cb.get()
            if cb is None:
                return result
            n_done = int(getattr(self, "n", 0) or 0)
            n_total = int(getattr(self, "total", 0) or 0)
            label = str(getattr(self, "desc", "") or "")
            if not _should_emit(n_done, n_total):
                return result
            try:
                cb(n_done, n_total, label)
            except Exception:
                pass
            return result

    qt_core.tqdm = BridgedTqdm
    _patched = True
