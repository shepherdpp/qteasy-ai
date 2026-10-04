# coding=utf-8
# ======================================
# File: memory_store.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-04-15
# Desc:
# qteasy AI 外壳本地记忆存储层，负责
# profile/env_facts/runs 的落盘与读取。
# ======================================

"""本地记忆与执行记录存储。

MemoryStore 是阶段A“可追溯”能力的核心支撑模块，解决三个问题：

1. 用户偏好如何保存（profile）；
2. 环境事实如何缓存（env_facts）；
3. 每次执行如何复盘（runs）。

目录约定
--------
默认目录：`./.qteasy/ai/`
可通过环境变量 `QTEASY_AI_HOME` 覆盖根目录。
"""

from __future__ import annotations

import json
import math
import shutil
import os
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import (
    DEFAULT_PROVIDER_TIMEOUT,
    ConfigCenter,
    build_provider_from_overlay,
    provider_diagnostics,
)

# 阶段 B 预留 Agent 授权 schema；默认全 false。CLI / assistant.run 本阶段不消费这些开关。
DEFAULT_PROFILE: Dict[str, Any] = {
    "agent": {
        "allow_refill": False,
        "allow_backtest": False,
        "allow_optimize": False,
    },
    "defaults": {},
}

USER_KB_RAW_PARTS = ("research", "trades", "factors", "strategies")
MODE_R_ID = "mode-r"
_PROVIDER_BUILTIN_MESSAGE = "Mode-R cannot be edited or removed."
_PROVIDER_FIELDS_MESSAGE = "Name and model are required."
_PROVIDER_NOT_FOUND_MESSAGE = "Provider not found."
USER_KB_README = """# user_kb (local research notes)

This directory is YOUR knowledge workspace. It is created on first MemoryStore init.

Layout:

- `rules/` — curated rules you write by hand (not auto-ingested).
- `raw/research/` `raw/trades/` `raw/factors/` `raw/strategies/` — source notes.
- `compiled/` — machine output of compile. Do not edit by hand.

Ask mode searches ONLY the official package KB (`qteasy_ai/kb/`). It does not read `user_kb/`.
The 1.x open design loop is the main consumer of compiled user notes.

Compile an empty catalog:

    from qteasy_ai.memory_store import MemoryStore
    MemoryStore().compile_user_kb()
"""


def apply_profile_defaults(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """将读取到的 profile 与默认 agent 开关合并。

    Parameters
    ----------
    raw : dict or None
        磁盘上的原始 profile；缺文件时为空字典。

    Returns
    -------
    Dict[str, Any]
        保证含 ``agent.allow_refill/allow_backtest/allow_optimize``，用户键保留。
    """

    profile: Dict[str, Any] = dict(raw or {})
    agent_defaults = dict(DEFAULT_PROFILE["agent"])
    existing_agent = profile.get("agent")
    if not isinstance(existing_agent, dict):
        existing_agent = {}
    profile["agent"] = {**agent_defaults, **existing_agent}
    existing_defaults = profile.get("defaults")
    if not isinstance(existing_defaults, dict):
        existing_defaults = {}
    profile["defaults"] = dict(existing_defaults)
    return profile


def _json_safe(value: Any) -> Any:
    """将对象递归转为 JSON 可序列化形态。

    Parameters
    ----------
    value : Any
        任意嵌套结构。

    Returns
    -------
    Any
        ``date``/``datetime`` 转为 ISO 字符串；非有限浮点转为 ``None``；其它未知类型转为 ``str``。
    """

    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat() + ("Z" if value.tzinfo is None else "")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def merge_env_facts(old: Dict[str, Any], probe: Dict[str, Any]) -> Dict[str, Any]:
    """深合并 env_facts：探针结果覆盖同名键，tables 按表名合并。

    Parameters
    ----------
    old : Dict[str, Any]
        已有环境事实（可为空字典）。
    probe : Dict[str, Any]
        本次探针写入的片段（如 tushare / tables）。

    Returns
    -------
    Dict[str, Any]
        合并后的 env_facts；会刷新 ``updated_at``（UTC ISO + Z）。

    Examples
    --------
    >>> merge_env_facts({}, {"tushare": {"token_present": True}})["tushare"]["token_present"]
    True
    """

    merged: Dict[str, Any] = dict(old) if old else {}
    for key, value in (probe or {}).items():
        if key == "updated_at":
            continue
        if key == "tables" and isinstance(value, dict):
            tables = dict(merged.get("tables") or {})
            for table_name, table_info in value.items():
                if isinstance(table_info, dict) and isinstance(tables.get(table_name), dict):
                    tables[table_name] = {**tables[table_name], **table_info}
                else:
                    tables[table_name] = table_info
            merged["tables"] = tables
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    merged["updated_at"] = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    return merged


def _provider_error(code: str, message: str) -> Dict[str, Any]:
    """池操作失败结果。"""

    return {"ok": False, "error": code, "message": message}


def _mode_r_provider() -> Dict[str, Any]:
    """内置 Mode-R 项：无模型、无 key。"""

    return {"id": MODE_R_ID, "name": "Mode-R", "builtin": True}


def _default_provider_pool() -> Dict[str, Any]:
    """缺文件时的内存默认池。"""

    return {"active_id": MODE_R_ID, "providers": [_mode_r_provider()]}


def _public_provider(item: Dict[str, Any]) -> Dict[str, Any]:
    """去掉 raw api_key 的列表项。"""

    timeout = item.get("timeout")
    if timeout in ("", None):
        timeout_out: Any = None
    else:
        timeout_out = int(timeout)
    return {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or ""),
        "builtin": bool(item.get("builtin") or item.get("id") == MODE_R_ID),
        "model": str(item.get("model") or "").strip(),
        "base_url": str(item.get("base_url") or "").strip(),
        "timeout": timeout_out,
        "api_key_present": bool(str(item.get("api_key") or "").strip()),
    }


def _find_provider(pool: Dict[str, Any], provider_id: str) -> Optional[Dict[str, Any]]:
    """按 id 查找池内项。"""

    for item in pool.get("providers") or []:
        if isinstance(item, dict) and str(item.get("id") or "") == provider_id:
            return item
    return None


def _new_provider_id(pool: Dict[str, Any]) -> str:
    """生成不与现有项冲突的用户 id。"""

    existing = {str(item.get("id") or "") for item in pool.get("providers") or []}
    while True:
        candidate = "p-" + uuid.uuid4().hex[:8]
        if candidate not in existing and candidate != MODE_R_ID:
            return candidate


def _migrate_legacy_provider(blob: Dict[str, Any]) -> Dict[str, Any]:
    """把单份覆盖层迁成池。空 model 不造用户项。"""

    pool = _default_provider_pool()
    model = str(blob.get("model") or "").strip()
    if not model:
        return pool
    item: Dict[str, Any] = {
        "id": _new_provider_id(pool),
        "name": model,
        "model": model,
        "base_url": str(blob.get("base_url") or "").strip(),
    }
    if blob.get("timeout") not in (None, ""):
        item["timeout"] = int(blob["timeout"])
    key = str(blob.get("api_key") or "").strip()
    if key:
        item["api_key"] = key
        pool["active_id"] = item["id"]
    pool["providers"].append(item)
    return pool


def _normalize_provider_pool(blob: Dict[str, Any]) -> tuple:
    """保证 mode-r 在池内，并修正无效 active_id。"""

    changed = False
    providers: List[Dict[str, Any]] = []
    seen = set()
    for raw in blob.get("providers") or []:
        if not isinstance(raw, dict):
            changed = True
            continue
        item_id = str(raw.get("id") or "").strip()
        if not item_id or item_id in seen:
            changed = True
            continue
        seen.add(item_id)
        if item_id == MODE_R_ID or raw.get("builtin"):
            if raw.get("model") or raw.get("api_key") or raw.get("base_url") or not raw.get("builtin"):
                changed = True
            providers.append(_mode_r_provider())
            continue
        providers.append(dict(raw))
    if MODE_R_ID not in seen:
        providers.insert(0, _mode_r_provider())
        changed = True
    else:
        providers.sort(key=lambda row: 0 if row.get("id") == MODE_R_ID else 1)
    active_id = str(blob.get("active_id") or MODE_R_ID)
    ids = {str(row.get("id") or "") for row in providers}
    if active_id not in ids:
        active_id = MODE_R_ID
        changed = True
    return {"active_id": active_id, "providers": providers}, changed


class MemoryStore:
    """管理 profile/env_facts/runs 的最小落盘。

    Parameters
    ----------
    base_dir : str, optional
        存储根目录。未提供时按环境变量或默认路径自动推断。
    """

    def __init__(self, base_dir: Optional[str] = None) -> None:
        config_center = ConfigCenter()
        base_dir = config_center.resolve(
            "ai_home",
            explicit=base_dir,
            env_key="QTEASY_AI_HOME",
            qt_key="ai_home",
            default=".qteasy/ai/",
        )
        self.base_dir = Path(base_dir)
        self.runs_dir = self.base_dir / "runs"
        self.pinned_dir = self.base_dir / "pinned"
        self.strategies_dir = self.base_dir / "strategies"
        self.sessions_dir = self.base_dir / "sessions"
        self.user_kb_dir = self.base_dir / "user_kb"
        # 初始化时确保目录存在，避免后续写入分支到处做 mkdir。
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.pinned_dir.mkdir(parents=True, exist_ok=True)
        self.strategies_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.ensure_user_kb_scaffold()

    @property
    def profile_path(self) -> Path:
        """profile 文件路径。"""

        return self.base_dir / "profile.json"

    @property
    def env_facts_path(self) -> Path:
        """env facts 文件路径。"""

        return self.base_dir / "env_facts.json"

    @property
    def provider_overlay_path(self) -> Path:
        """工作台 Provider 覆盖层路径。"""

        return self.base_dir / "provider.json"

    def load_provider_overlay(self) -> Dict[str, Any]:
        """读取工作台保存的 Provider 覆盖；缺文件为空字典。"""

        blob = self._read_json(self.provider_overlay_path, default={})
        return dict(blob) if isinstance(blob, dict) else {}

    def save_provider_overlay(self, overlay: Dict[str, Any]) -> None:
        """保存 Provider 覆盖层（不含完整 api_key 日志）。"""

        payload = {
            "model": str(overlay.get("model") or "").strip(),
            "base_url": str(overlay.get("base_url") or "").strip(),
            "timeout": overlay.get("timeout"),
            "updated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }
        key = str(overlay.get("api_key") or "").strip()
        if key:
            payload["api_key"] = key
        elif "api_key" not in overlay:
            old = self.load_provider_overlay()
            if old.get("api_key"):
                payload["api_key"] = old["api_key"]
        self._write_json(self.provider_overlay_path, payload)

    def list_providers(self) -> Dict[str, Any]:
        """返回池的公开视图，不含 raw api_key。"""

        pool = self.load_provider_pool()
        return {
            "ok": True,
            "active_id": pool["active_id"],
            "providers": [_public_provider(item) for item in pool["providers"]],
        }

    def load_provider_pool(self) -> Dict[str, Any]:
        """读取并规范化 Provider 池。缺文件时不写盘。"""

        path = self.provider_overlay_path
        if not path.exists():
            return _default_provider_pool()
        blob = self._read_json(path, default={})
        if not isinstance(blob, dict):
            blob = {}
        if "providers" not in blob:
            pool = _migrate_legacy_provider(blob)
            self._write_provider_pool(pool)
            return pool
        pool, changed = _normalize_provider_pool(blob)
        if changed:
            self._write_provider_pool(pool)
        return pool

    def add_provider(
        self,
        *,
        name: str,
        model: str,
        base_url: str = "",
        api_key: str = "",
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """添加用户项，不切换当前项。"""

        clean_name = str(name or "").strip()
        clean_model = str(model or "").strip()
        if not clean_name or not clean_model:
            return _provider_error("PROVIDER_FIELDS_REQUIRED", _PROVIDER_FIELDS_MESSAGE)
        pool = self.load_provider_pool()
        item: Dict[str, Any] = {
            "id": _new_provider_id(pool),
            "name": clean_name,
            "model": clean_model,
            "base_url": str(base_url or "").strip(),
        }
        if timeout not in (None, ""):
            item["timeout"] = int(timeout)
        key = str(api_key or "").strip()
        if key:
            item["api_key"] = key
        pool["providers"].append(item)
        self._write_provider_pool(pool)
        view = self.list_providers()
        view["id"] = item["id"]
        return view

    def update_provider(
        self,
        provider_id: str,
        *,
        name: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Dict[str, Any]:
        """修改用户项。api_key 为空表示保留原 key。"""

        target = str(provider_id or "").strip()
        if target == MODE_R_ID:
            return _provider_error("PROVIDER_BUILTIN_LOCKED", _PROVIDER_BUILTIN_MESSAGE)
        pool = self.load_provider_pool()
        item = _find_provider(pool, target)
        if item is None or item.get("builtin"):
            return _provider_error("PROVIDER_NOT_FOUND", _PROVIDER_NOT_FOUND_MESSAGE)
        if name is not None and str(name).strip():
            item["name"] = str(name).strip()
        if model is not None and str(model).strip():
            item["model"] = str(model).strip()
        if base_url is not None:
            item["base_url"] = str(base_url).strip()
        if timeout is not None:
            item["timeout"] = int(timeout)
        if api_key is not None and str(api_key).strip():
            item["api_key"] = str(api_key).strip()
        self._write_provider_pool(pool)
        return self.list_providers()

    def remove_provider(self, provider_id: str) -> Dict[str, Any]:
        """删除用户项。删掉当前项时回到 mode-r。"""

        target = str(provider_id or "").strip()
        if target == MODE_R_ID:
            return _provider_error("PROVIDER_BUILTIN_LOCKED", _PROVIDER_BUILTIN_MESSAGE)
        pool = self.load_provider_pool()
        item = _find_provider(pool, target)
        if item is None or item.get("builtin"):
            return _provider_error("PROVIDER_NOT_FOUND", _PROVIDER_NOT_FOUND_MESSAGE)
        pool["providers"] = [row for row in pool["providers"] if row.get("id") != target]
        if pool.get("active_id") == target:
            pool["active_id"] = MODE_R_ID
        self._write_provider_pool(pool)
        return self.list_providers()

    def use_provider(self, provider_id: str) -> Dict[str, Any]:
        """切换当前项。mode-r 始终可选。"""

        target = str(provider_id or "").strip()
        pool = self.load_provider_pool()
        if _find_provider(pool, target) is None:
            return _provider_error("PROVIDER_NOT_FOUND", _PROVIDER_NOT_FOUND_MESSAGE)
        pool["active_id"] = target
        self._write_provider_pool(pool)
        return self.list_providers()

    def build_active_provider(self, *, env: Optional[Dict[str, str]] = None) -> Any:
        """按当前项构建 Provider。mode-r 返回 None，不合并环境变量。"""

        item = self._active_provider_item()
        if item is None or item.get("id") == MODE_R_ID or item.get("builtin"):
            return None
        return build_provider_from_overlay(item, env=env)

    def active_diagnostics(self, *, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """当前项诊断。mode-r 固定为 rule，且不含 raw api_key。"""

        view = self.list_providers()
        item = self._active_provider_item()
        if item is None or item.get("id") == MODE_R_ID or item.get("builtin"):
            return {
                "ok": False,
                "configured": False,
                "provider": "none",
                "mode": "rule",
                "model": "",
                "base_url": "",
                "timeout": DEFAULT_PROVIDER_TIMEOUT,
                "api_key_present": False,
                "message": "Provider not configured.",
                "config_sources": {},
                "active_id": MODE_R_ID,
                "providers": view["providers"],
            }
        diag = provider_diagnostics(item, env=env)
        diag["configured"] = bool(diag.get("ok"))
        diag["active_id"] = item.get("id")
        diag["providers"] = view["providers"]
        diag.pop("api_key", None)
        return diag

    def _active_provider_item(self) -> Optional[Dict[str, Any]]:
        """当前项的落盘记录；无效时视为 mode-r。"""

        pool = self.load_provider_pool()
        return _find_provider(pool, str(pool.get("active_id") or "")) or _mode_r_provider()

    def _write_provider_pool(self, pool: Dict[str, Any]) -> None:
        """把规范化后的池写入 provider.json。"""

        providers: List[Dict[str, Any]] = []
        for item in pool.get("providers") or []:
            if item.get("id") == MODE_R_ID or item.get("builtin"):
                providers.append(_mode_r_provider())
                continue
            stored: Dict[str, Any] = {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "model": str(item.get("model") or "").strip(),
                "base_url": str(item.get("base_url") or "").strip(),
            }
            if item.get("timeout") not in (None, ""):
                stored["timeout"] = int(item["timeout"])
            key = str(item.get("api_key") or "").strip()
            if key:
                stored["api_key"] = key
            providers.append(stored)
        if not any(row.get("id") == MODE_R_ID for row in providers):
            providers.insert(0, _mode_r_provider())
        active_id = str(pool.get("active_id") or MODE_R_ID)
        if active_id not in {row["id"] for row in providers}:
            active_id = MODE_R_ID
        self._write_json(
            self.provider_overlay_path,
            {
                "active_id": active_id,
                "providers": providers,
                "updated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            },
        )

    def _read_json(self, path: Path, default: Dict[str, Any]) -> Dict[str, Any]:
        """读取 JSON 文件，不存在或损坏时返回默认值。

        Notes
        -----
        阶段A采用“宽松读取”策略：不存在即返回默认值。
        B0 起对损坏 JSON 也降级：备份为 ``*.corrupt.json`` 后返回默认值，
        避免 CLI/Assistant 因本地记忆损坏而无法启动。
        """

        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, (dict, list)):
                return _json_safe(loaded)
            return loaded
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
            # 损坏文件备份后降级，便于用户排查手工编辑/写半截问题。
            backup = path.with_suffix(path.suffix + ".corrupt.json")
            try:
                if path.exists():
                    path.replace(backup)
            except OSError:
                pass
            print(
                f"[MemoryStore] Warning: failed to read {path} ({exc}); "
                f"using default and moved corrupt file to {backup}."
            )
            return default

    def _write_json(self, path: Path, data: Dict[str, Any]) -> None:
        """写入 JSON 文件（先写临时文件再替换，降低截断风险）。

        统一 UTF-8 + pretty JSON，方便用户直接查看和手工修复。
        """

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(_json_safe(data), f, ensure_ascii=False, indent=2)
            f.write("\n")
        tmp_path.replace(path)

    @staticmethod
    def session_stem(session_id: str) -> str:
        """会话文件名安全化。

        Parameters
        ----------
        session_id : str
            原始 session_id。

        Returns
        -------
        str
            仅保留字母数字与 ``-_``。
        """

        return "".join(
            ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(session_id or "default")
        )

    def ui_transcript_path(self, session_id: str) -> Path:
        """Web 对话副本路径（与 ``{id}.json`` 并列，不进 SessionStore 列举）。"""

        return self.sessions_dir / f"{self.session_stem(session_id)}.transcript.json"

    def load_ui_transcript(self, session_id: str) -> List[Dict[str, Any]]:
        """读取工作台可见对话；缺文件为空列表。

        Parameters
        ----------
        session_id : str
            会话 id。

        Returns
        -------
        list of dict
            ``kind`` / ``text`` / ``payload`` 消息。
        """

        blob = self._read_json(self.ui_transcript_path(session_id), default={})
        rows = blob.get("messages") if isinstance(blob, dict) else []
        out: List[Dict[str, Any]] = []
        for item in rows or []:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "").strip()
            if not kind:
                continue
            out.append(
                {
                    "kind": kind,
                    "text": str(item.get("text") or ""),
                    "payload": dict(item.get("payload") or {})
                    if isinstance(item.get("payload"), dict)
                    else {},
                }
            )
        return out

    def append_ui_transcript(
        self,
        session_id: str,
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """追加可见消息并落盘；同 kind+text 的尾部重复跳过。

        Parameters
        ----------
        session_id : str
            会话 id；空则不写。
        messages : list of dict
            本轮要追加的消息。

        Returns
        -------
        list of dict
            追加后的完整副本（最多 120 条）。
        """

        sid = str(session_id or "").strip()
        if not sid:
            return []
        hist = self.load_ui_transcript(sid)
        seen_tail = {(row.get("kind"), row.get("text")) for row in hist[-8:]}
        for raw in messages or []:
            if not isinstance(raw, dict):
                continue
            kind = str(raw.get("kind") or "").strip()
            if kind in {"", "plan_card", "step_status"}:
                continue
            text = str(raw.get("text") or "")
            if not text:
                continue
            key = (kind, text)
            if key in seen_tail:
                continue
            seen_tail.add(key)
            hist.append(
                {
                    "kind": kind,
                    "text": text,
                    "payload": dict(raw.get("payload") or {})
                    if isinstance(raw.get("payload"), dict)
                    else {},
                }
            )
        hist = hist[-120:]
        self._write_json(self.ui_transcript_path(sid), {"messages": hist})
        return hist

    def load_profile(self) -> Dict[str, Any]:
        """读取 profile，并补齐默认 ``agent`` 授权开关。"""

        return apply_profile_defaults(self._read_json(self.profile_path, default={}))

    def save_profile(self, profile: Dict[str, Any]) -> None:
        """保存 profile。

        自动追加 `updated_at`，用于判断记忆新鲜度与变更时间。
        """

        payload = dict(profile)
        payload["updated_at"] = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        self._write_json(self.profile_path, payload)

    def load_env_facts(self) -> Dict[str, Any]:
        """读取环境事实。"""

        return self._read_json(self.env_facts_path, default={})

    def save_env_facts(self, env_facts: Dict[str, Any]) -> None:
        """保存环境事实。

        自动追加 `updated_at`，用于判断环境探测结果是否过期。
        """

        payload = dict(env_facts)
        payload["updated_at"] = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        self._write_json(self.env_facts_path, payload)

    def save_run(self, run_id: str, run_payload: Dict[str, Any]) -> str:
        """保存执行记录并返回路径。

        Parameters
        ----------
        run_id : str
            执行记录唯一 ID。
        run_payload : Dict[str, Any]
            执行结果内容。

        Returns
        -------
        str
            已保存 run 文件路径。
        """

        target = self.runs_dir / f"{run_id}.json"
        payload = dict(run_payload)
        payload["saved_at"] = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        self._write_json(target, payload)
        return str(target)

    def save_plan_md(self, run_id: str, plan_md: str) -> str:
        """将人读轨 plan.md 落盘到 runs 目录。

        Parameters
        ----------
        run_id : str
            与 JSON run 对齐的 ID。
        plan_md : str
            Markdown 文本。

        Returns
        -------
        str
            已保存的 ``{run_id}.plan.md`` 路径。
        """

        target = self.runs_dir / f"{run_id}.plan.md"
        target.write_text(plan_md or "", encoding="utf-8")
        return str(target)

    def load_run(self, run_id: str) -> Dict[str, Any]:
        """按 run_id 读取执行记录。"""

        target = self.runs_dir / f"{run_id}.json"
        return self._read_json(target, default={})

    def find_run_by_plan_id(self, plan_id: str) -> Dict[str, Any]:
        """按 ``plan.plan_id`` 扫描 ``runs/*.json``，返回最近一条匹配记录。

        Parameters
        ----------
        plan_id : str
            ToolPlan.plan_id。

        Returns
        -------
        dict
            完整 run payload；未找到则为空 dict。
        """

        wanted = str(plan_id or "").strip()
        if not wanted:
            return {}
        matches: List[tuple] = []
        for path in self.runs_dir.glob("*.json"):
            payload = self._read_json(path, default={})
            plan = payload.get("plan") if isinstance(payload, dict) else None
            if isinstance(plan, dict) and str(plan.get("plan_id") or "") == wanted:
                matches.append((path.stat().st_mtime, payload))
        if not matches:
            return {}
        matches.sort(key=lambda item: item[0])
        return dict(matches[-1][1])

    def list_runs(self) -> List[str]:
        """返回 run_id 列表。

        返回值按文件名排序，便于前端稳定展示与测试断言。
        """

        return sorted(path.stem for path in self.runs_dir.glob("*.json"))

    def clear_runs(self) -> None:
        """清空 runs 目录。

        该方法只删除 `runs/*.json`，不触及 profile/env_facts。
        """

        for path in self.runs_dir.glob("*.json"):
            path.unlink(missing_ok=True)

    def list_pinned(self) -> List[str]:
        """返回 pinned run_id 列表。"""

        return sorted(path.stem.split("__", 1)[0] for path in self.pinned_dir.glob("*.json"))

    def pin_run(self, run_id: str, *, tag: str = "") -> str:
        """将 runs 中记录钉住到 pinned。"""

        source = self.runs_dir / f"{run_id}.json"
        if not source.exists():
            raise FileNotFoundError(f"Run file not found for pinning: {run_id}")
        safe_tag = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in tag.strip()) if tag else ""
        target_name = f"{run_id}.json" if not safe_tag else f"{run_id}__{safe_tag}.json"
        target = self.pinned_dir / target_name
        shutil.copy2(source, target)
        return str(target)

    def cleanup_runs(self, *, max_age_days: int, max_count: int, max_total_mb: int) -> Dict[str, Any]:
        """按天数/数量/空间限制清理 runs。"""

        max_age_days = max(0, int(max_age_days))
        max_count = max(1, int(max_count))
        max_total_bytes = max(1, int(max_total_mb)) * 1024 * 1024

        now = datetime.utcnow().timestamp()
        run_files = sorted(self.runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        deleted: List[str] = []

        # 1) 先按 age 清理
        for path in list(run_files):
            age_days = (now - path.stat().st_mtime) / 86400
            if age_days > max_age_days:
                path.unlink(missing_ok=True)
                deleted.append(path.name)

        run_files = sorted(self.runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)

        # 2) 按数量清理
        if len(run_files) > max_count:
            for path in run_files[max_count:]:
                path.unlink(missing_ok=True)
                deleted.append(path.name)
            run_files = run_files[:max_count]

        # 3) 按空间清理
        total_bytes = sum(path.stat().st_size for path in run_files if path.exists())
        if total_bytes > max_total_bytes:
            for path in sorted(run_files, key=lambda p: p.stat().st_mtime):
                if total_bytes <= max_total_bytes:
                    break
                size = path.stat().st_size
                path.unlink(missing_ok=True)
                deleted.append(path.name)
                total_bytes -= size

        remaining = sorted(self.runs_dir.glob("*.json"))
        remaining_bytes = sum(path.stat().st_size for path in remaining)
        return {
            "deleted_count": len(deleted),
            "deleted_files": sorted(set(deleted)),
            "remaining_count": len(remaining),
            "remaining_total_mb": round(remaining_bytes / 1024 / 1024, 4),
        }

    def resolve_under_base(self, rel_or_abs: str) -> Optional[Path]:
        """将相对或绝对路径解析到 ``base_dir`` 内；越界返回 None。

        Parameters
        ----------
        rel_or_abs : str
            工作区相对路径或绝对路径。

        Returns
        -------
        Path or None
            解析后的真实路径；越界、空串则为 None。
        """

        raw = str(rel_or_abs or "").strip()
        if not raw:
            return None
        base = self.base_dir.expanduser().resolve()
        candidate = Path(raw).expanduser()
        try:
            target = candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()
            target.relative_to(base)
        except (OSError, ValueError):
            return None
        return target

    def list_workspace_tree(self, *, max_depth: int = 3) -> List[Dict[str, Any]]:
        """只读列举 runs / strategies / user_kb 树，供工作台 Workspace.Files。

        Parameters
        ----------
        max_depth : int, optional
            目录最大深度，默认 3。

        Returns
        -------
        list of dict
            三棵根目录的 ``name`` / ``kind`` / ``path`` / ``children``。
        """

        depth = max(0, int(max_depth))

        def walk(dir_path: Path, rel: str, remaining: int) -> Dict[str, Any]:
            children: List[Dict[str, Any]] = []
            node: Dict[str, Any] = {
                "name": dir_path.name or rel,
                "kind": "dir",
                "path": rel,
                "children": children,
            }
            if remaining <= 0 or not dir_path.is_dir():
                return node
            try:
                entries = sorted(
                    dir_path.iterdir(),
                    key=lambda item: (not item.is_dir(), item.name.lower()),
                )
            except OSError:
                return node
            for child in entries:
                if child.name.startswith("."):
                    continue
                try:
                    child_rel = str(child.relative_to(self.base_dir))
                except ValueError:
                    child_rel = child.name
                if child.is_dir():
                    children.append(walk(child, child_rel, remaining - 1))
                elif child.is_file():
                    children.append({"name": child.name, "kind": "file", "path": child_rel})
            return node

        roots = [
            (self.runs_dir, "runs"),
            (self.strategies_dir, "strategies"),
            (self.user_kb_dir, "user_kb"),
        ]
        trees: List[Dict[str, Any]] = []
        for folder, rel in roots:
            folder.mkdir(parents=True, exist_ok=True)
            trees.append(walk(folder, rel, depth))
        return trees

    def ensure_user_kb_scaffold(self) -> None:
        """落下用户 KB 分区与英文 README；不检索、不写入官方 kb。"""

        self.user_kb_dir.mkdir(parents=True, exist_ok=True)
        (self.user_kb_dir / "rules").mkdir(parents=True, exist_ok=True)
        raw_root = self.user_kb_dir / "raw"
        raw_root.mkdir(parents=True, exist_ok=True)
        for part in USER_KB_RAW_PARTS:
            (raw_root / part).mkdir(parents=True, exist_ok=True)
        (self.user_kb_dir / "compiled").mkdir(parents=True, exist_ok=True)
        readme = self.user_kb_dir / "README.md"
        if not readme.exists():
            readme.write_text(USER_KB_README, encoding="utf-8")

    def user_kb_partitions_ok(self) -> bool:
        """必有分区是否齐全。额外子目录允许存在。"""

        if not (self.user_kb_dir / "rules").is_dir():
            return False
        if not (self.user_kb_dir / "compiled").is_dir():
            return False
        if not (self.user_kb_dir / "README.md").is_file():
            return False
        for part in USER_KB_RAW_PARTS:
            if not (self.user_kb_dir / "raw" / part).is_dir():
                return False
        return True

    def compile_user_kb(self) -> Dict[str, Any]:
        """从 rules/ 与 raw/ 生成 compiled/catalog.json；空库仍合法。"""

        self.ensure_user_kb_scaffold()
        entries: List[Dict[str, Any]] = []
        for folder in (self.user_kb_dir / "rules", self.user_kb_dir / "raw"):
            if not folder.is_dir():
                continue
            for path in sorted(folder.rglob("*")):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in {".md", ".txt", ".json"}:
                    continue
                rel = path.relative_to(self.user_kb_dir).as_posix()
                try:
                    text = path.read_text(encoding="utf-8")
                except OSError:
                    continue
                title = path.stem
                first = ""
                for line in text.splitlines():
                    if line.strip():
                        first = line.strip()
                        break
                if first.startswith("#"):
                    title = first.lstrip("# ").strip() or title
                elif first.startswith("{"):
                    try:
                        blob = json.loads(text)
                        if isinstance(blob, dict) and blob.get("title"):
                            title = str(blob.get("title"))
                    except json.JSONDecodeError:
                        pass
                tags = [
                    part
                    for part in path.relative_to(self.user_kb_dir).parts[:-1]
                    if part not in {"raw", "rules"}
                ]
                run_id = ""
                match = re.search(r"run[_-]?id[:\s]+([A-Za-z0-9_-]+)", text, flags=re.IGNORECASE)
                if match:
                    run_id = match.group(1)
                entries.append(
                    {
                        "title": title,
                        "path": rel,
                        "tags": tags,
                        "run_id": run_id,
                    }
                )
        catalog: Dict[str, Any] = {
            "version": 1,
            "entries": entries,
            "source": "user_kb",
        }
        path = self.user_kb_dir / "compiled" / "catalog.json"
        self._write_json(path, catalog)
        return catalog
