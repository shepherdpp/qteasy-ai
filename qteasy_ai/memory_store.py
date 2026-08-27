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
import shutil
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import ConfigCenter

# 阶段 B 预留 Agent 授权 schema；默认全 false。CLI / assistant.run 本阶段不消费这些开关。
DEFAULT_PROFILE: Dict[str, Any] = {
    "agent": {
        "allow_refill": False,
        "allow_backtest": False,
        "allow_optimize": False,
    }
}


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
        ``date``/``datetime`` 转为 ISO 字符串；其它未知类型转为 ``str``。
    """

    if value is None or isinstance(value, (str, int, float, bool)):
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
        # 初始化时确保目录存在，避免后续写入分支到处做 mkdir。
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.pinned_dir.mkdir(parents=True, exist_ok=True)

    @property
    def profile_path(self) -> Path:
        """profile 文件路径。"""

        return self.base_dir / "profile.json"

    @property
    def env_facts_path(self) -> Path:
        """env facts 文件路径。"""

        return self.base_dir / "env_facts.json"

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
                return json.load(f)
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
