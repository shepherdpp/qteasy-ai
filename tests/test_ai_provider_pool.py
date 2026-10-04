# coding=utf-8
# ======================================
# File: test_ai_provider_pool.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-04
# Desc:
# Provider 池：迁移、Mode-R 锁定、当前项解析与 CLI。
# ======================================

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Optional

from qteasy_ai.memory_store import MemoryStore


def _dump(payload: Any) -> str:
    """把结果收成字符串，便于断言不含 raw key。"""

    return json.dumps(payload, ensure_ascii=False)


class TestAiProviderPool(unittest.TestCase):
    """provider.json 池：当前项、迁移与拒绝写入。"""

    def _store(self, temp_dir: str) -> MemoryStore:
        """临时目录上的 MemoryStore。"""

        return MemoryStore(base_dir=temp_dir)

    def _write_overlay(self, store: MemoryStore, payload: Dict[str, Any]) -> None:
        """直接写入旧形状或坏 active_id，绕过新 API。"""

        store.provider_overlay_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _disk(self, store: MemoryStore) -> Dict[str, Any]:
        """读回 provider.json。"""

        return json.loads(store.provider_overlay_path.read_text(encoding="utf-8"))

    def _user_items(self, providers: Any) -> list:
        """去掉内置 Mode-R 后的用户项。"""

        return [row for row in providers or [] if str(row.get("id")) != "mode-r"]

    def test_missing_file_defaults_to_mode_r_without_writing(self) -> None:
        """没有文件时当前项是 mode-r，且不创建 provider.json。"""

        print("\n[TestAiProviderPool] 缺文件默认 mode-r")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            view = store.list_providers()
            print(" view:", view)
            print(" file exists:", store.provider_overlay_path.exists())
            self.assertEqual(view["active_id"], "mode-r")
            self.assertEqual([row["id"] for row in view["providers"]], ["mode-r"])
            self.assertTrue(view["providers"][0]["builtin"])
            self.assertFalse(view["providers"][0]["api_key_present"])
            self.assertNotIn("api_key", view["providers"][0])
            self.assertFalse(store.provider_overlay_path.exists())
            env = {"QTEASY_AI_MODEL": "from-env", "QTEASY_AI_API_KEY": "env-secret"}
            self.assertIsNone(store.build_active_provider(env=env))
            self.assertFalse(store.provider_overlay_path.exists())

    def test_migrate_model_and_key_becomes_active_user_item(self) -> None:
        """旧文件 model 与 key 都在时，迁成用户项并作为当前项。"""

        print("\n[TestAiProviderPool] 迁移 model+key")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            self._write_overlay(
                store,
                {
                    "model": "deepseek-chat",
                    "api_key": "sk-migrate-secret",
                    "base_url": "https://api.deepseek.com/v1",
                    "timeout": 42,
                },
            )
            view = store.list_providers()
            disk = self._disk(store)
            print(" view:", view)
            print(" disk active:", disk.get("active_id"), "ids:", [row.get("id") for row in disk.get("providers") or []])
            users = self._user_items(view["providers"])
            self.assertEqual(len(users), 1)
            self.assertEqual(users[0]["name"], "deepseek-chat")
            self.assertEqual(users[0]["model"], "deepseek-chat")
            self.assertEqual(users[0]["base_url"], "https://api.deepseek.com/v1")
            self.assertEqual(users[0]["timeout"], 42)
            self.assertTrue(users[0]["api_key_present"])
            self.assertEqual(view["active_id"], users[0]["id"])
            self.assertNotEqual(view["active_id"], "mode-r")
            self.assertIn("mode-r", [row["id"] for row in view["providers"]])
            self.assertNotIn("sk-migrate-secret", _dump(view))
            disk_user = self._user_items(disk["providers"])[0]
            self.assertEqual(disk_user["api_key"], "sk-migrate-secret")
            self.assertEqual(disk["active_id"], users[0]["id"])

    def test_migrate_model_without_key_stays_on_mode_r(self) -> None:
        """旧文件只有 model 时迁出用户项，当前项仍是 mode-r。"""

        print("\n[TestAiProviderPool] 迁移仅 model")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            self._write_overlay(store, {"model": "demo-only", "base_url": "http://127.0.0.1:9"})
            view = store.list_providers()
            users = self._user_items(view["providers"])
            print(" active:", view["active_id"], "users:", users)
            self.assertEqual(len(users), 1)
            self.assertEqual(users[0]["model"], "demo-only")
            self.assertFalse(users[0]["api_key_present"])
            self.assertEqual(view["active_id"], "mode-r")

    def test_migrate_empty_model_creates_no_user_item(self) -> None:
        """旧文件 model 为空时不造用户项。"""

        print("\n[TestAiProviderPool] 迁移空 model")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            self._write_overlay(store, {"model": "  ", "base_url": "https://api.openai.com/v1", "timeout": 12})
            view = store.list_providers()
            print(" view:", view)
            self.assertEqual(view["active_id"], "mode-r")
            self.assertEqual(self._user_items(view["providers"]), [])

    def test_invalid_active_id_falls_back_to_mode_r(self) -> None:
        """active_id 指向不存在的项时，读出后当前项是 mode-r。"""

        print("\n[TestAiProviderPool] 无效 active_id")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            self._write_overlay(
                store,
                {
                    "active_id": "missing-id",
                    "providers": [
                        {"id": "mode-r", "name": "Mode-R", "builtin": True},
                        {
                            "id": "p-keep",
                            "name": "Keep",
                            "model": "kept-model",
                            "base_url": "http://127.0.0.1:9",
                            "api_key": "keep-secret",
                        },
                    ],
                },
            )
            view = store.list_providers()
            disk = self._disk(store)
            print(" view active:", view["active_id"], "disk active:", disk.get("active_id"))
            self.assertEqual(view["active_id"], "mode-r")
            self.assertEqual(disk["active_id"], "mode-r")
            self.assertEqual(self._user_items(view["providers"])[0]["id"], "p-keep")
            self.assertNotIn("keep-secret", _dump(view))

    def test_remove_and_update_mode_r_are_rejected(self) -> None:
        """删除或给 mode-r 写 model 都被拒绝，内置项仍无 model 与 key。"""

        print("\n[TestAiProviderPool] 拒绝改 mode-r")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            removed = store.remove_provider("mode-r")
            updated = store.update_provider("mode-r", model="gpt-4", api_key="should-not-stick")
            view = store.list_providers()
            print(" remove:", removed)
            print(" update:", updated)
            print(" view:", view)
            self.assertFalse(removed["ok"])
            self.assertEqual(removed["error"], "PROVIDER_BUILTIN_LOCKED")
            self.assertEqual(removed["message"], "Mode-R cannot be edited or removed.")
            self.assertFalse(updated["ok"])
            self.assertEqual(updated["error"], "PROVIDER_BUILTIN_LOCKED")
            self.assertEqual(updated["message"], "Mode-R cannot be edited or removed.")
            builtin = view["providers"][0]
            self.assertEqual(builtin["id"], "mode-r")
            self.assertTrue(builtin["builtin"])
            self.assertFalse(str(builtin.get("model") or "").strip())
            self.assertFalse(builtin["api_key_present"])
            self.assertNotIn("should-not-stick", _dump(view))
            self.assertFalse(store.provider_overlay_path.exists())

    def test_add_requires_name_and_model(self) -> None:
        """缺 name 或缺 model（含空白）不新增条目。"""

        print("\n[TestAiProviderPool] 添加缺字段")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            missing_name = store.add_provider(name="  ", model="some-model", base_url="http://127.0.0.1:9")
            missing_model = store.add_provider(name="Local", model="", base_url="http://127.0.0.1:9")
            view = store.list_providers()
            print(" missing name:", missing_name)
            print(" missing model:", missing_model)
            print(" providers:", view["providers"])
            self.assertFalse(missing_name["ok"])
            self.assertEqual(missing_name["error"], "PROVIDER_FIELDS_REQUIRED")
            self.assertEqual(missing_name["message"], "Name and model are required.")
            self.assertFalse(missing_model["ok"])
            self.assertEqual(missing_model["error"], "PROVIDER_FIELDS_REQUIRED")
            self.assertEqual(view["active_id"], "mode-r")
            self.assertEqual(self._user_items(view["providers"]), [])
            self.assertFalse(store.provider_overlay_path.exists())

    def test_unknown_id_does_not_change_active(self) -> None:
        """更新、删除、切换未知 id 都拒绝，当前项不变。"""

        print("\n[TestAiProviderPool] 未知 id")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            added = store.add_provider(
                name="Local",
                model="llama",
                base_url="http://127.0.0.1:9",
                api_key="known-secret",
            )
            print(" added:", added)
            self.assertTrue(added["ok"])
            self.assertEqual(store.list_providers()["active_id"], "mode-r")
            before = store.list_providers()["active_id"]
            updated = store.update_provider("no-such", name="Other")
            removed = store.remove_provider("no-such")
            used = store.use_provider("no-such")
            print(" update:", updated)
            print(" remove:", removed)
            print(" use:", used)
            self.assertEqual(updated["error"], "PROVIDER_NOT_FOUND")
            self.assertEqual(updated["message"], "Provider not found.")
            self.assertEqual(removed["error"], "PROVIDER_NOT_FOUND")
            self.assertEqual(used["error"], "PROVIDER_NOT_FOUND")
            self.assertFalse(updated["ok"])
            self.assertFalse(removed["ok"])
            self.assertFalse(used["ok"])
            self.assertEqual(store.list_providers()["active_id"], before)
            self.assertEqual(len(self._user_items(store.list_providers()["providers"])), 1)

    def test_blank_api_key_keeps_stored_key_out_of_views(self) -> None:
        """更新时 api_key 为空表示不改；列表与诊断都不回 raw key。"""

        print("\n[TestAiProviderPool] 空 key 保留")
        secret = "raw-key-keep-me"
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            added = store.add_provider(
                name="Cloud",
                model="deepseek-chat",
                base_url="https://api.deepseek.com/v1",
                api_key=secret,
            )
            print(" added id:", added.get("id"))
            self.assertTrue(added["ok"])
            updated = store.update_provider(added["id"], api_key="", name="Cloud renamed")
            disk = self._disk(store)
            view = store.list_providers()
            used = store.use_provider(added["id"])
            diag = store.active_diagnostics()
            print(" updated:", updated["ok"], updated.get("error"))
            print(" disk key kept:", self._user_items(disk["providers"])[0].get("api_key") == secret)
            print(" diag mode:", diag.get("mode"), "present:", diag.get("api_key_present"))
            self.assertTrue(updated["ok"])
            self.assertEqual(self._user_items(disk["providers"])[0]["api_key"], secret)
            self.assertEqual(self._user_items(view["providers"])[0]["name"], "Cloud renamed")
            self.assertNotIn(secret, _dump(view))
            self.assertNotIn("api_key", _dump(view).replace("api_key_present", ""))
            self.assertTrue(used["ok"])
            self.assertTrue(diag["api_key_present"])
            self.assertNotIn(secret, _dump(diag))
            self.assertNotIn("api_key", diag)

    def test_use_builds_provider_and_remove_active_returns_none(self) -> None:
        """选中用户项能建出该 model；删掉当前项后回到 mode-r 且 Provider 为 None。"""

        print("\n[TestAiProviderPool] use 后删除当前项")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            added = store.add_provider(
                name="Local",
                model="llama3.1",
                base_url="http://127.0.0.1:11434/v1",
                api_key="ollama",
                timeout=30,
            )
            print(" added:", added.get("id"), "active before use:", store.list_providers()["active_id"])
            self.assertTrue(added["ok"])
            self.assertEqual(store.list_providers()["active_id"], "mode-r")
            used = store.use_provider(added["id"])
            provider = store.build_active_provider()
            print(" used active:", store.list_providers()["active_id"])
            print(" provider model:", None if provider is None else provider.model)
            print(" provider timeout:", None if provider is None else provider.timeout)
            self.assertTrue(used["ok"])
            self.assertEqual(store.list_providers()["active_id"], added["id"])
            self.assertIsNotNone(provider)
            self.assertEqual(provider.model, "llama3.1")
            self.assertEqual(provider.base_url, "http://127.0.0.1:11434/v1")
            self.assertEqual(provider.timeout, 30)
            removed = store.remove_provider(added["id"])
            env = {"QTEASY_AI_MODEL": "from-env", "QTEASY_AI_API_KEY": "env-secret"}
            after = store.build_active_provider(env=env)
            diag = store.active_diagnostics(env=env)
            print(" after remove active:", store.list_providers()["active_id"], "provider:", after)
            print(" diag:", diag.get("mode"), diag.get("configured"))
            self.assertTrue(removed["ok"])
            self.assertEqual(store.list_providers()["active_id"], "mode-r")
            self.assertIsNone(after)
            self.assertEqual(diag["mode"], "rule")
            self.assertFalse(diag["configured"])
            self.assertNotIn("env-secret", _dump(diag))

    def test_mode_r_ignores_env_model(self) -> None:
        """当前项是 mode-r 时，环境变量里的 model 与 key 不生效。"""

        print("\n[TestAiProviderPool] mode-r 忽略环境变量")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = self._store(temp_dir)
            env = {
                "QTEASY_AI_MODEL": "deepseek-chat",
                "QTEASY_AI_API_KEY": "env-only-secret",
                "QTEASY_AI_BASE_URL": "https://api.deepseek.com/v1",
            }
            provider = store.build_active_provider(env=env)
            diag = store.active_diagnostics(env=env)
            print(" provider:", provider)
            print(" diag mode:", diag.get("mode"), "model:", diag.get("model"), "configured:", diag.get("configured"))
            self.assertIsNone(provider)
            self.assertEqual(diag["mode"], "rule")
            self.assertEqual(diag["model"], "")
            self.assertFalse(diag["configured"])
            self.assertFalse(diag["ok"])
            self.assertEqual(diag["active_id"], "mode-r")
            self.assertNotIn("env-only-secret", _dump(diag))
            self.assertNotIn("api_key", diag)


def _cli(args: list, home: str, extra: Optional[Dict[str, str]] = None) -> subprocess.CompletedProcess:
    """在临时 HOME 下跑 qteasy-ai CLI。"""

    env = dict(os.environ)
    env["QTEASY_AI_HOME"] = home
    env.pop("QTEASY_AI_MODEL", None)
    env.pop("QTEASY_AI_API_KEY", None)
    env.pop("QTEASY_AI_BASE_URL", None)
    env.pop("QTEASY_AI_TIMEOUT", None)
    if extra:
        env.update(extra)
    return subprocess.run(
        [sys.executable, "-m", "qteasy_ai.cli", *args],
        capture_output=True,
        text=True,
        env=env,
    )


class TestAiProviderPoolCli(unittest.TestCase):
    """CLI provider 子命令与 provider-check 看当前项。"""

    def test_cli_rejects_mode_r_unknown_id_and_missing_fields(self) -> None:
        """删 mode-r、未知 id、缺 name/model 都非零退出，且不写坏池。"""

        print("\n[TestAiProviderPoolCli] CLI 拒绝")
        with tempfile.TemporaryDirectory() as temp_dir:
            removed = _cli(["provider", "remove", "mode-r"], temp_dir)
            print(" remove mode-r:", removed.returncode, removed.stdout, removed.stderr)
            self.assertNotEqual(removed.returncode, 0)
            self.assertIn("Mode-R cannot be edited or removed.", removed.stdout)
            missing_name = _cli(
                ["provider", "add", "--name", "  ", "--model", "m", "--base-url", "http://127.0.0.1:9"],
                temp_dir,
            )
            missing_model = _cli(
                ["provider", "add", "--name", "Local", "--model", " ", "--base-url", "http://127.0.0.1:9"],
                temp_dir,
            )
            print(" missing name:", missing_name.returncode, missing_name.stdout)
            print(" missing model:", missing_model.returncode, missing_model.stdout)
            self.assertNotEqual(missing_name.returncode, 0)
            self.assertNotEqual(missing_model.returncode, 0)
            self.assertIn("Name and model are required.", missing_name.stdout)
            self.assertIn("Name and model are required.", missing_model.stdout)
            unknown = _cli(["provider", "use", "missing-id"], temp_dir)
            print(" use missing:", unknown.returncode, unknown.stdout)
            self.assertNotEqual(unknown.returncode, 0)
            self.assertIn("Provider not found.", unknown.stdout)
            listed = _cli(["provider", "list"], temp_dir)
            payload = json.loads(listed.stdout)
            print(" list:", payload)
            self.assertEqual(listed.returncode, 0)
            self.assertEqual(payload["active_id"], "mode-r")
            self.assertEqual([row["id"] for row in payload["providers"]], ["mode-r"])

    def test_cli_add_update_use_check_hides_raw_key(self) -> None:
        """添加后空 key 更新仍保留磁盘 key；list 与 provider-check 不含明文。"""

        print("\n[TestAiProviderPoolCli] CLI 添加与诊断")
        secret = "cli-raw-key"
        with tempfile.TemporaryDirectory() as temp_dir:
            added = _cli(
                [
                    "provider", "add",
                    "--name", "Cloud",
                    "--model", "deepseek-chat",
                    "--base-url", "https://api.deepseek.com/v1",
                    "--api-key", secret,
                    "--timeout", "42",
                ],
                temp_dir,
            )
            print(" add:", added.returncode, added.stdout)
            self.assertEqual(added.returncode, 0)
            created = json.loads(added.stdout)
            self.assertNotIn(secret, added.stdout)
            provider_id = created["id"]
            updated = _cli(["provider", "update", provider_id, "--api-key", ""], temp_dir)
            print(" update blank key:", updated.returncode, updated.stdout)
            self.assertEqual(updated.returncode, 0)
            disk = json.loads(Path(temp_dir, "provider.json").read_text(encoding="utf-8"))
            stored = [row for row in disk["providers"] if row["id"] == provider_id][0]
            print(" disk key kept:", stored.get("api_key") == secret, "active:", disk.get("active_id"))
            self.assertEqual(stored["api_key"], secret)
            self.assertEqual(disk["active_id"], "mode-r")
            used = _cli(["provider", "use", provider_id], temp_dir)
            checked = _cli(["provider-check"], temp_dir)
            print(" check:", checked.returncode, checked.stdout)
            self.assertEqual(used.returncode, 0)
            self.assertEqual(checked.returncode, 0)
            diag = json.loads(checked.stdout)
            self.assertTrue(diag["ok"])
            self.assertEqual(diag["mode"], "cloud_llm")
            self.assertEqual(diag["model"], "deepseek-chat")
            self.assertEqual(diag["base_url"], "https://api.deepseek.com/v1")
            self.assertEqual(diag["timeout"], 42)
            self.assertTrue(diag["api_key_present"])
            self.assertNotIn(secret, checked.stdout)
            self.assertNotIn(secret, updated.stdout)
            listed = _cli(["provider", "list"], temp_dir)
            self.assertNotIn(secret, listed.stdout)

    def test_cli_provider_check_mode_r_ignores_env(self) -> None:
        """空池时 provider-check 是 rule，即使环境里有 model 和 key。"""

        print("\n[TestAiProviderPoolCli] provider-check 忽略环境")
        with tempfile.TemporaryDirectory() as temp_dir:
            checked = _cli(
                ["provider-check"],
                temp_dir,
                extra={
                    "QTEASY_AI_MODEL": "deepseek-chat",
                    "QTEASY_AI_API_KEY": "env-check-secret",
                    "QTEASY_AI_BASE_URL": "https://api.deepseek.com/v1",
                },
            )
            print(" check:", checked.returncode, checked.stdout)
            self.assertEqual(checked.returncode, 0)
            diag = json.loads(checked.stdout)
            self.assertFalse(diag["ok"])
            self.assertEqual(diag["mode"], "rule")
            self.assertEqual(diag["model"], "")
            self.assertNotIn("env-check-secret", checked.stdout)

    def test_cli_remove_unknown_and_update_unknown(self) -> None:
        """删除或更新不存在的 id 非零退出，当前项仍是 mode-r。"""

        print("\n[TestAiProviderPoolCli] CLI 未知 id")
        with tempfile.TemporaryDirectory() as temp_dir:
            removed = _cli(["provider", "remove", "missing-id"], temp_dir)
            updated = _cli(["provider", "update", "missing-id", "--name", "Nope"], temp_dir)
            print(" remove:", removed.returncode, removed.stdout)
            print(" update:", updated.returncode, updated.stdout)
            self.assertNotEqual(removed.returncode, 0)
            self.assertNotEqual(updated.returncode, 0)
            self.assertIn("Provider not found.", removed.stdout)
            self.assertIn("Provider not found.", updated.stdout)
            listed = json.loads(_cli(["provider", "list"], temp_dir).stdout)
            self.assertEqual(listed["active_id"], "mode-r")

    def test_cli_argparse_requires_name_and_model(self) -> None:
        """命令行缺 --name 或 --model 时非零退出。"""

        print("\n[TestAiProviderPoolCli] CLI 缺参数")
        with tempfile.TemporaryDirectory() as temp_dir:
            no_name = _cli(["provider", "add", "--model", "m", "--base-url", "http://127.0.0.1:9"], temp_dir)
            no_model = _cli(["provider", "add", "--name", "Local", "--base-url", "http://127.0.0.1:9"], temp_dir)
            print(" no name:", no_name.returncode)
            print(" no model:", no_model.returncode)
            self.assertNotEqual(no_name.returncode, 0)
            self.assertNotEqual(no_model.returncode, 0)
