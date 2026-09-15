import os
import sys
import tempfile
import unittest
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from storage import Storage


class StorageTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        Path(self.path).unlink()
        self.storage = Storage(self.path)

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            path = Path(self.path + suffix)
            if path.exists():
                path.unlink()

    def test_profile_and_session(self):
        profile = self.storage.get_profile("openid-a")
        self.assertEqual(profile["nickname"], "微信用户")
        profile = self.storage.save_profile("openid-a", {"nickname": "测试用户", "address": "成都"})
        self.assertEqual(profile["nickname"], "测试用户")
        self.assertEqual(profile["address"], "成都")
        session = self.storage.create_session("openid-a")
        self.assertEqual(self.storage.session_openid(session["token"]), "openid-a")

    def test_event_join_is_unique_and_draw_works(self):
        owner = self.storage.save_profile("owner", {"nickname": "发起人"})
        participant = self.storage.save_profile("member", {"nickname": "参与者"})
        event = self.storage.create_event("owner", owner, {
            "type": "lottery", "title": "测试抽奖", "deadline": "2099-01-01 20:00", "limit": 2,
        })
        self.assertTrue(self.storage.join_event("member", participant, event["_id"])["joined"])
        with self.assertRaisesRegex(ValueError, "已经参与"):
            self.storage.join_event("member", participant, event["_id"])
        listed = self.storage.list_events("member", "lottery")
        self.assertTrue(listed[0]["joined"])
        self.assertEqual(self.storage.draw_event("owner", event["_id"])["winnerName"], "参与者")

    def test_reading_progress_upsert(self):
        self.storage.save_progress("openid-a", {"book": "测试书", "chapterIndex": 2, "progress": 0.5})
        self.storage.save_progress("openid-a", {"book": "测试书", "chapterIndex": 3, "completed": True, "progress": 1})
        progress = self.storage.get_progress("openid-a", "测试书")
        self.assertEqual(progress["chapterIndex"], 3)
        self.assertTrue(progress["completed"])

    def test_notion_cache_and_outbox(self):
        self.storage.replace_notion_contacts([{"id": "sender", "name": "寄件人", "phone": "13800138000"}, {"id": "receiver", "name": "收件人", "phone": "13900139000"}])
        profile = self.storage.save_profile("openid-a", {"contact_id": "sender", "contact_name": "寄件人"})
        created = self.storage.create_local_mail(profile, {"senderId": "sender", "recipientId": "receiver", "sendDate": "2026-09-16", "mailType": "平信"})
        self.assertEqual(created["syncState"], "pending_create")
        self.assertEqual(len(self.storage.due_outbox()), 1)
        listed = self.storage.list_notion_mails(profile)
        self.assertEqual(listed["records"][0]["pageId"], created["pageId"])
        self.storage.complete_outbox(self.storage.due_outbox()[0]["id"], created["pageId"], "notion-page-1", "mail.create")
        with self.storage.connect() as db:
            state = db.execute("SELECT sync_state FROM notion_mails WHERE id=?", (created["pageId"],)).fetchone()[0]
        self.assertEqual(state, "synced")

    def test_sign_is_local_first(self):
        self.storage.replace_notion_contacts([{"id": "sender", "name": "寄件人"}, {"id": "receiver", "name": "收件人"}])
        self.storage.replace_notion_mails([{"pageId": "mail-1", "senderId": "sender", "recipientId": "receiver", "sendDate": "2026-09-16", "received": False}])
        profile = self.storage.save_profile("openid-b", {"contact_id": "receiver", "contact_name": "收件人"})
        result = self.storage.sign_local_mail(profile, "mail-1")
        self.assertEqual(result["syncState"], "pending_sign")
        self.assertTrue(self.storage.list_notion_mails(profile)["records"][0]["received"])
        self.assertEqual(self.storage.due_outbox()[0]["operation"], "mail.sign")


if __name__ == "__main__":
    unittest.main()
