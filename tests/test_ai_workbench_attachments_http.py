# coding=utf-8
# ======================================
# File: test_ai_workbench_attachments_http.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-24
# Desc:
# Workbench 会话附件 HTTP：上传 / 列表 / 删除 / 限额
# ======================================

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from qteasy_ai.app import QteasyAssistant, build_default_registry
from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.session_attachments import MAX_FILE_BYTES, session_attachments_dir
from qteasy_ai.workbench.http_app import create_app


class TestAiWorkbenchAttachmentsHttp(unittest.TestCase):
    """薄 HTTP 附件增删列。"""

    def _client(self, temp_dir: str):
        from starlette.testclient import TestClient

        store = MemoryStore(base_dir=temp_dir)
        assistant = QteasyAssistant(memory_store=store, registry=build_default_registry())
        app = create_app(assistant=assistant)
        return TestClient(app), store

    def test_upload_list_delete(self) -> None:
        """POST ensure 会话；GET 列表；DELETE 删元数据与文件。"""

        print("\n[TestAiWorkbenchAttachmentsHttp] upload list delete")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, store = self._client(temp_dir)
            sid = "att-http-1"
            uploaded = client.post(
                f"/v1/session/{sid}/attachments",
                files={"file": ("note.md", BytesIO(b"# hi\n"), "text/markdown")},
            )
            body = uploaded.json()
            print(" upload status:", uploaded.status_code, body)
            self.assertEqual(uploaded.status_code, 200)
            self.assertTrue(body.get("ok"))
            att = body.get("attachment") or {}
            att_id = str(att.get("id") or "")
            print(" attachment:", att)
            self.assertTrue(att_id)
            self.assertEqual(att.get("display_name"), "note.md")
            self.assertEqual(att.get("size_bytes"), len(b"# hi\n"))
            disk = session_attachments_dir(store, sid)
            files = list(disk.glob("*"))
            print(" disk files:", [p.name for p in files])
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].read_bytes(), b"# hi\n")

            listed = client.get(f"/v1/session/{sid}/attachments")
            listed_body = listed.json()
            print(" list:", listed.status_code, listed_body)
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(len(listed_body.get("attachments") or []), 1)

            deleted = client.delete(f"/v1/session/{sid}/attachments/{att_id}")
            deleted_body = deleted.json()
            print(" delete:", deleted.status_code, deleted_body)
            self.assertEqual(deleted.status_code, 200)
            self.assertEqual(deleted_body.get("attachments"), [])
            print(" disk after delete:", list(disk.glob("*")) if disk.exists() else [])
            self.assertFalse(any(disk.glob("*")) if disk.exists() else True)

            missing = client.delete(f"/v1/session/{sid}/attachments/{att_id}")
            print(" missing delete:", missing.status_code, missing.json())
            self.assertEqual(missing.status_code, 404)

    def test_reject_type_and_size(self) -> None:
        """非法类型 415；超单文件限额 413。"""

        print("\n[TestAiWorkbenchAttachmentsHttp] reject type and size")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, _store = self._client(temp_dir)
            bad = client.post(
                "/v1/session/att-http-2/attachments",
                files={"file": ("x.exe", BytesIO(b"MZ"), "application/octet-stream")},
            )
            print(" bad type:", bad.status_code, bad.json())
            self.assertEqual(bad.status_code, 415)
            self.assertEqual((bad.json().get("error") or {}).get("code"), "ATTACHMENT_TYPE_REJECTED")

            huge = client.post(
                "/v1/session/att-http-2/attachments",
                files={
                    "file": (
                        "big.txt",
                        BytesIO(b"x" * (MAX_FILE_BYTES + 1)),
                        "text/plain",
                    )
                },
            )
            print(" too large:", huge.status_code, (huge.json().get("error") or {}).get("code"))
            self.assertEqual(huge.status_code, 413)
            self.assertEqual((huge.json().get("error") or {}).get("code"), "ATTACHMENT_TOO_LARGE")

    def test_delete_session_removes_blob_dir(self) -> None:
        """DELETE session 一并清 sessions/{stem}/。"""

        print("\n[TestAiWorkbenchAttachmentsHttp] delete session removes blob")
        with tempfile.TemporaryDirectory() as temp_dir:
            client, store = self._client(temp_dir)
            sid = "att-http-del"
            client.post(
                f"/v1/session/{sid}/attachments",
                files={"file": ("a.txt", BytesIO(b"a"), "text/plain")},
            )
            blob = Path(store.sessions_dir) / sid
            print(" blob before:", blob.is_dir())
            self.assertTrue(blob.is_dir())
            deleted = client.delete(f"/v1/session/{sid}")
            print(" delete session:", deleted.status_code, deleted.json())
            self.assertEqual(deleted.status_code, 200)
            print(" blob after:", blob.exists())
            self.assertFalse(blob.exists())


if __name__ == "__main__":
    unittest.main()
