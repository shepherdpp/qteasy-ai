# coding=utf-8
# ======================================
# File: test_ai_session_attachments.py
# Author: Jackie PENG
# Contact: jackie.pengzhao@gmail.com
# Created: 2026-10-24
# Desc:
# 会话附件：白名单、限额、落盘与 SessionStore 清理
# ======================================

import tempfile
import unittest
from pathlib import Path

from qteasy_ai.memory_store import MemoryStore
from qteasy_ai.session import ConversationState, SessionStore
from qteasy_ai.session_attachments import (
    MAX_FILE_BYTES,
    extension_allowed,
    normalize_attachment,
    save_attachment_bytes,
    session_attachments_dir,
    validate_new_file,
)


class TestAiSessionAttachments(unittest.TestCase):
    """附件元数据、限额与磁盘旁路目录。"""

    def test_normalize_and_whitelist(self) -> None:
        """规范化补全 id/mime；白名单按扩展名。"""

        print("\n[TestAiSessionAttachments] normalize and whitelist")
        raw = normalize_attachment({"source_path": "sessions/a/attachments/x.py"})
        print(" normalized:", raw)
        self.assertIsNotNone(raw)
        assert raw is not None
        self.assertTrue(raw["id"])
        self.assertEqual(raw["display_name"], "x.py")
        self.assertEqual(raw["mime_type"], "text/x-python")
        self.assertEqual(raw["size_bytes"], 0)
        print(" py allowed:", extension_allowed("note.py"))
        print(" exe allowed:", extension_allowed("evil.exe"))
        self.assertTrue(extension_allowed("note.py"))
        self.assertTrue(extension_allowed("shot.PNG"))
        self.assertTrue(extension_allowed("doc.docx"))
        self.assertFalse(extension_allowed("evil.exe"))
        self.assertFalse(extension_allowed("legacy.doc"))

    def test_validate_limits(self) -> None:
        """单文件 10MB、会话合计 50MB。"""

        print("\n[TestAiSessionAttachments] validate limits")
        ok = validate_new_file(filename="a.txt", size_bytes=100, existing=[])
        print(" ok small:", ok)
        self.assertIsNone(ok)
        too_big = validate_new_file(
            filename="a.txt",
            size_bytes=MAX_FILE_BYTES + 1,
            existing=[],
        )
        print(" too_big:", too_big)
        self.assertEqual(too_big, "ATTACHMENT_TOO_LARGE")
        existing = [{"size_bytes": 49 * 1024 * 1024}]
        full = validate_new_file(
            filename="b.txt",
            size_bytes=2 * 1024 * 1024,
            existing=existing,
        )
        print(" session full:", full)
        self.assertEqual(full, "ATTACHMENT_SESSION_FULL")
        bad_type = validate_new_file(filename="x.bin", size_bytes=10, existing=[])
        print(" bad type:", bad_type)
        self.assertEqual(bad_type, "ATTACHMENT_TYPE_REJECTED")

    def test_save_load_roundtrip_and_delete_blob(self) -> None:
        """落盘、读回元数据、删会话时清旁路目录。"""

        print("\n[TestAiSessionAttachments] save load delete blob")
        with tempfile.TemporaryDirectory() as temp_dir:
            store = MemoryStore(base_dir=temp_dir)
            sessions = SessionStore(store)
            state = ConversationState.empty("att-1")
            entry, err = save_attachment_bytes(
                store,
                "att-1",
                filename="hello.py",
                data=b"print(1)\n",
                existing=[],
            )
            print(" save err:", err, "entry:", entry)
            self.assertIsNone(err)
            assert entry is not None
            disk = session_attachments_dir(store, "att-1")
            files = list(disk.glob("*"))
            print(" files:", [p.name for p in files])
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].read_bytes(), b"print(1)\n")
            state.attachments = [entry]
            sessions.save(state)
            loaded = sessions.load("att-1")
            print(" loaded attachments:", loaded.attachments)
            self.assertEqual(len(loaded.attachments), 1)
            self.assertEqual(loaded.attachments[0]["display_name"], "hello.py")
            self.assertEqual(loaded.attachments[0]["size_bytes"], len(b"print(1)\n"))
            self.assertTrue(loaded.attachments[0]["id"])
            blob = store.sessions_dir / "att-1"
            print(" blob exists before delete:", blob.is_dir())
            self.assertTrue(blob.is_dir())
            deleted = sessions.delete("att-1")
            print(" deleted:", deleted, "blob after:", blob.exists())
            self.assertTrue(deleted)
            self.assertFalse(blob.exists())
            self.assertFalse(sessions.exists("att-1"))

    def test_legacy_path_only_attachment(self) -> None:
        """旧只有 source_path 的条目读回时补全字段。"""

        print("\n[TestAiSessionAttachments] legacy path-only")
        state = ConversationState.from_dict(
            {
                "session_id": "legacy",
                "attachments": [{"source_path": "sessions/legacy/attachments/old.txt"}],
            }
        )
        print(" attachments:", state.attachments)
        self.assertEqual(len(state.attachments), 1)
        row = state.attachments[0]
        self.assertEqual(row["source_path"], "sessions/legacy/attachments/old.txt")
        self.assertEqual(row["display_name"], "old.txt")
        self.assertTrue(row["id"])
        self.assertEqual(row["mime_type"], "text/plain")


if __name__ == "__main__":
    unittest.main()
