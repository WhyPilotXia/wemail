import json
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
        self.assertNotIn("allowNote", listed[0])
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
        created = self.storage.create_local_mail(profile, {"senderId": "sender", "recipientId": "receiver", "sendDate": "2026-09-16", "mailType": "平信", "title": "不应保存的备注"})
        self.assertEqual(created["syncState"], "pending_create")
        pending = self.storage.due_outbox()
        self.assertEqual(len(pending), 1)
        self.assertEqual(__import__("json").loads(pending[0]["payload"])["title"], "由 WeMail 小程序登记")
        listed = self.storage.list_notion_mails(profile)
        self.assertEqual(listed["records"][0]["pageId"], created["pageId"])
        self.storage.complete_outbox(pending[0]["id"], created["pageId"], "notion-page-1", "mail.create")
        with self.storage.connect() as db:
            state = db.execute("SELECT sync_state FROM notion_mails WHERE id=?", (created["pageId"],)).fetchone()[0]
        self.assertEqual(state, "synced")

    def test_mail_tracking_number_rejects_free_text(self):
        self.storage.replace_notion_contacts([{"id": "sender", "name": "寄件人"}, {"id": "receiver", "name": "收件人"}])
        profile = self.storage.save_profile("openid-a", {"contact_id": "sender", "contact_name": "寄件人"})
        with self.assertRaisesRegex(ValueError, "邮件编号仅支持"):
            self.storage.create_local_mail(profile, {"senderId": "sender", "recipientId": "receiver", "sendDate": "2026-09-16", "trackingNo": "生日快乐"})

    def test_notion_contact_null_optional_fields_are_normalized(self):
        self.storage.replace_notion_contacts([{
            "id": "contact-null-fields",
            "name": "测试联系人",
            "phone": None,
            "email": None,
            "address1": None,
            "postcode1": None,
            "address2": None,
            "postcode2": None,
            "qq": None,
        }])
        contact = self.storage.list_notion_contacts()[0]
        for field in ("phone", "email", "address1", "postcode1", "address2", "postcode2", "qq"):
            self.assertEqual(contact[field], "")

    def test_notion_contacts_return_all_fields(self):
        self.storage.replace_notion_contacts([{
            "id": "contact-full-fields",
            "name": "完整联系人",
            "phone": "13800138000",
            "email": "user@example.com",
            "address1": "地址一",
            "postcode1": "610000",
            "address2": "地址二",
            "postcode2": "100000",
            "qq": "12345678",
        }])
        contact = self.storage.list_notion_contacts()[0]
        self.assertEqual(contact["phone"], "13800138000")
        self.assertEqual(contact["email"], "user@example.com")
        self.assertEqual(contact["address1"], "地址一")
        self.assertEqual(contact["postcode1"], "610000")
        self.assertEqual(contact["address2"], "地址二")
        self.assertEqual(contact["postcode2"], "100000")
        self.assertEqual(contact["qq"], "12345678")

    def test_identity_bind_and_conflict_transfer(self):
        self.storage.replace_notion_contacts([
            {"id": "contact-a", "name": "张三", "phone": "13800138000", "address1": "成都市", "postcode1": "610000"},
            {"id": "contact-b", "name": "李四", "phone": "13900139000"},
        ])
        verify = self.storage.bind_verification("openid-a", "张三", "13800138000")
        self.assertEqual(verify["state"], "pending")
        self.assertEqual(verify["contactName"], "张三")
        result = self.storage.confirm_binding("openid-a", "昵称甲", verify["confirmToken"])
        self.assertEqual(result["profile"]["contactId"], "contact-a")
        self.assertEqual(result["profile"]["contactName"], "张三")
        self.assertEqual(result["profile"]["address"], "成都市")
        binding = self.storage.get_binding("contact-a")
        self.assertEqual(binding["openid"], "openid-a")
        self.assertEqual(binding["nickname"], "昵称甲")

        # 重复核验：自己已绑定
        again = self.storage.bind_verification("openid-a", "张三", "13800138000")
        self.assertEqual(again["state"], "bound_self")

        # 他人核验：返回 bound_other
        other = self.storage.bind_verification("openid-b", "张三", "13800138000")
        self.assertEqual(other["state"], "bound_other")
        self.assertEqual(other["boundNickname"], "昵称甲")
        self.assertEqual(other["boundOpenid"], "openid-a")

        # 非强制确认应被拒绝
        with self.assertRaisesRegex(PermissionError, "已被其他账户绑定"):
            self.storage.confirm_binding("openid-b", "昵称乙", other["confirmToken"])

        # 强制换绑：原账户解绑，新账户拿到联系人
        transferred = self.storage.force_transfer_binding("openid-b", "昵称乙", other["confirmToken"])
        self.assertEqual(transferred["profile"]["contactId"], "contact-a")
        self.assertEqual(transferred["profile"]["contactName"], "张三")
        old_profile = self.storage.get_profile("openid-a")
        self.assertEqual(old_profile["contact_id"], "")
        self.assertEqual(old_profile["contact_name"], "")
        self.assertEqual(old_profile["phone_number"], "")
        binding = self.storage.get_binding("contact-a")
        self.assertEqual(binding["openid"], "openid-b")
        self.assertEqual(binding["nickname"], "昵称乙")

        # 手机号核验失败
        with self.assertRaisesRegex(ValueError, "未在联系人表中找到"):
            self.storage.bind_verification("openid-c", "张三", "13700137000")

    def test_identity_name_with_nickname_brackets(self):
        # Notion 姓名“张三（老张）”，用户输入纯姓名“张三”可匹配
        self.storage.replace_notion_contacts([
            {"id": "contact-bracket", "name": "张三（老张）", "phone": "13800138000"},
            {"id": "contact-ascii", "name": "李四(SiLi)", "phone": "13900139000"},
        ])
        verify = self.storage.bind_verification("openid-a", "张三", "13800138000")
        self.assertEqual(verify["state"], "pending")
        self.assertEqual(verify["contactId"], "contact-bracket")
        # 英文括号同样支持
        verify_ascii = self.storage.bind_verification("openid-a", "李四", "13900139000")
        self.assertEqual(verify_ascii["contactId"], "contact-ascii")
        # 用户输入带括号原文也可匹配（两侧对称处理）
        verify_raw = self.storage.bind_verification("openid-a", "张三（老张）", "13800138000")
        self.assertEqual(verify_raw["contactId"], "contact-bracket")
        # 姓名不匹配仍应失败
        with self.assertRaisesRegex(ValueError, "未在联系人表中找到"):
            self.storage.bind_verification("openid-a", "王五", "13800138000")

    def test_update_contact_writes_cache_and_enqueues_outbox(self):
        self.storage.replace_notion_contacts([
            {"id": "contact-a", "name": "张三", "phone": "13800138000", "address1": "旧地址", "postcode1": "610000"},
        ])
        verify = self.storage.bind_verification("openid-a", "张三", "13800138000")
        self.storage.confirm_binding("openid-a", "昵称甲", verify["confirmToken"])
        profile = self.storage.get_profile("openid-a")

        # 未绑定联系人时不可修改
        with self.assertRaises(PermissionError):
            self.storage.update_contact("openid-c", self.storage.get_profile("openid-c"), {"qq": "123"})

        # 非绑定者不可修改（openid-b 绑定的是 contact-b，尝试改 contact-a 属越权）
        self.storage.replace_notion_contacts([
            {"id": "contact-a", "name": "张三", "phone": "13800138000", "address1": "新地址", "postcode1": "100000", "qq": "88888888"},
            {"id": "contact-b", "name": "李四", "phone": "13900139000"},
        ])
        verify_b = self.storage.bind_verification("openid-b", "李四", "13900139000")
        self.storage.confirm_binding("openid-b", "昵称乙", verify_b["confirmToken"])
        profile_b = self.storage.get_profile("openid-b")
        profile_b["contact_id"] = "contact-a"  # 模拟试图修改他人联系人
        with self.assertRaisesRegex(PermissionError, "仅绑定该联系人资料的账户"):
            self.storage.update_contact("openid-b", profile_b, {"qq": "123"})

        # 合法修改：本地缓存即时更新，outbox 入队 contact.update
        result = self.storage.update_contact("openid-a", profile, {"address1": "新地址", "postcode1": "100000", "qq": "88888888"})
        self.assertEqual(result["contact"]["address1"], "新地址")
        self.assertEqual(result["contact"]["qq"], "88888888")
        cached = [item for item in self.storage.list_notion_contacts() if item["id"] == "contact-a"][0]
        self.assertEqual(cached["address1"], "新地址")
        self.assertEqual(cached["postcode1"], "100000")
        tasks = self.storage.due_outbox()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["operation"], "contact.update")
        self.assertEqual(json.loads(tasks[0]["payload"])["fields"]["address1"], "新地址")

        # users 快照字段随地址1/邮编1/手机号联动
        updated_profile = self.storage.get_profile("openid-a")
        self.assertEqual(updated_profile["address"], "新地址")
        self.assertEqual(updated_profile["postcode"], "100000")

        # 不支持的字段应拒绝
        with self.assertRaisesRegex(ValueError, "不支持修改的字段"):
            self.storage.update_contact("openid-a", profile, {"name": "新名字"})
        # 空补丁应拒绝
        with self.assertRaisesRegex(ValueError, "没有需要修改的字段"):
            self.storage.update_contact("openid-a", profile, {})

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
