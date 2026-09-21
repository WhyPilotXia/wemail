import base64
import gzip
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

import config
from wemail_udp_server import WeMailServer


class ProtocolTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        Path(self.path).unlink()
        self.server = WeMailServer(storage_path=self.path)
        self.address = ("127.0.0.1", 30000)

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            path = Path(self.path + suffix)
            if path.exists():
                path.unlink()

    def session_for(self, openid, phone_number="", contact_id=""):
        self.server.storage.save_profile(openid, {"phone_number": phone_number, "contact_id": contact_id, "contact_name": contact_id})
        return self.server.storage.create_session(openid)["token"]

    def packet(self, request_id, body, part=0, total=1, text=None):
        payload = text if text is not None else json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        return json.dumps({"v": 2, "t": "q", "id": request_id, "p": part, "n": total, "d": payload}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def test_echo_is_returned_unchanged(self):
        raw = b'{"type":"wemail-udp-echo","requestId":"test"}'
        kind, value = self.server.receive_packet(raw, self.address)
        self.assertEqual(kind, "echo")
        self.assertEqual(value, raw)

    def test_compact_request_and_timestamp(self):
        body = {"action": "reading.get", "token": "invalid", "timestamp": int(time.time() * 1000)}
        kind, item = self.server.receive_packet(self.packet("request-1", body), self.address)
        self.assertEqual(kind, "request")
        self.assertEqual(item[2]["action"], "reading.get")

    def test_request_fragments_are_reassembled(self):
        body = json.dumps({"action": "reading.get", "token": "invalid", "timestamp": int(time.time() * 1000)}, separators=(",", ":"))
        middle = len(body) // 2
        kind, _ = self.server.receive_packet(self.packet("request-2", {}, 0, 2, body[:middle]), self.address)
        self.assertEqual(kind, "pending")
        kind, item = self.server.receive_packet(self.packet("request-2", {}, 1, 2, body[middle:]), self.address)
        self.assertEqual(kind, "request")
        self.assertEqual(item[2]["token"], "invalid")

    def test_large_response_uses_gzip_and_roundtrips(self):
        response = {"ok": True, "data": [{"name": "测试联系人", "address": "四川省成都市" * 20} for _ in range(200)]}
        packets = self.server.encode_response("response-1", response)
        envelopes = [json.loads(packet) for packet in packets]
        self.assertEqual(envelopes[0]["z"], 1)
        self.assertTrue(all(len(packet) <= 1400 for packet in packets))
        compressed = base64.b64decode("".join(item["d"] for item in envelopes))
        restored = json.loads(gzip.decompress(compressed))
        self.assertEqual(restored, response)

    def test_profile_sized_response_uses_mtu_safe_fragments(self):
        avatar = "data:image/jpeg;base64," + base64.b64encode(os.urandom(7500)).decode("ascii")
        response = {"ok": True, "data": {"profile": {"avatarUrl": avatar}}}
        packets = self.server.encode_response("response-profile", response)
        envelopes = [json.loads(packet) for packet in packets]
        self.assertGreater(len(packets), 1)
        self.assertTrue(all(len(packet) <= 1400 for packet in packets))
        joined = "".join(item["d"] for item in envelopes)
        restored = json.loads(gzip.decompress(base64.b64decode(joined))) if envelopes[0]["z"] else json.loads(joined)
        self.assertEqual(restored, response)

    def test_small_response_is_not_compressed(self):
        response = {"ok": True, "data": {"saved": True}}
        packet = json.loads(self.server.encode_response("response-2", response)[0])
        self.assertEqual(packet["z"], 0)
        self.assertEqual(json.loads(packet["d"]), response)

    def test_contacts_require_matched_contact(self):
        token = self.session_for("outsider", "13800138000")
        with self.assertRaisesRegex(PermissionError, "仅限已关联联系人身份"):
            self.server.dispatch({"action": "contacts.list", "token": token})
        try:
            self.server.dispatch({"action": "contacts.list", "token": token})
        except PermissionError as error:
            self.assertEqual(getattr(error, "CODE", ""), "IDENTITY_REQUIRED")

    def test_identity_bind_flow_over_udp_dispatch(self):
        self.server.storage.replace_notion_contacts([
            {"id": "contact-x", "name": "王五", "phone": "13600136000", "address1": "北京市"},
        ])
        token = self.server.storage.create_session("openid-x")["token"]
        pending = self.server.dispatch({"action": "profile.bindIdentity", "token": token, "name": "王五", "phone": "13600136000"})
        self.assertEqual(pending["state"], "pending")
        self.assertEqual(pending["contactName"], "王五")
        self.assertNotIn("boundNickname", pending)
        with self.assertRaisesRegex(ValueError, "未在联系人表中找到"):
            self.server.dispatch({"action": "profile.bindIdentity", "token": token, "name": "赵六", "phone": "13600136000"})
        bound = self.server.dispatch({"action": "profile.bindIdentity", "token": token, "confirmToken": pending["confirmToken"], "nickname": "测试昵称"})
        self.assertEqual(bound["profile"]["contactName"], "王五")
        conflict = self.server.dispatch({"action": "profile.bindIdentity", "token": token, "name": "王五", "phone": "13600136000"})
        self.assertEqual(conflict["state"], "bound_self")

    def test_identity_bind_rate_limit(self):
        self.server.storage.replace_notion_contacts([{"id": "contact-y", "name": "测试", "phone": "13500135000"}])
        token = self.server.storage.create_session("openid-y")["token"]
        for _ in range(5):
            with self.assertRaises(ValueError):
                self.server.dispatch({"action": "profile.bindIdentity", "token": token, "name": "测试", "phone": "000"})
        with self.assertRaisesRegex(PermissionError, "过于频繁"):
            self.server.dispatch({"action": "profile.bindIdentity", "token": token, "name": "测试", "phone": "000"})

    def test_profile_get_returns_full_contact_fields(self):
        self.server.storage.replace_notion_contacts([
            {"id": "contact-z", "name": "王五", "phone": "13600136000", "email": "wangwu@mail.com",
             "address1": "地址一", "postcode1": "610000", "address2": "地址二", "postcode2": "100000", "qq": "12345678"},
        ])
        token = self.server.storage.create_session("openid-z")["token"]
        pending = self.server.dispatch({"action": "profile.bindIdentity", "token": token, "name": "王五", "phone": "13600136000"})
        self.server.dispatch({"action": "profile.bindIdentity", "token": token, "confirmToken": pending["confirmToken"], "nickname": "小王"})
        data = self.server.dispatch({"action": "profile.get", "token": token})
        profile = data["profile"]
        self.assertEqual(profile["contactId"], "contact-z")
        self.assertEqual(profile["contactPhone"], "13600136000")
        self.assertEqual(profile["contactEmail"], "wangwu@mail.com")
        self.assertEqual(profile["contactAddress1"], "地址一")
        self.assertEqual(profile["contactPostcode1"], "610000")
        self.assertEqual(profile["contactAddress2"], "地址二")
        self.assertEqual(profile["contactPostcode2"], "100000")
        self.assertEqual(profile["contactQq"], "12345678")
        # 修改联系人字段：走本地更新 + outbox 异步写回
        updated = self.server.dispatch({"action": "profile.update", "token": token, "patch": {"nickname": "小王", "address1": "新地址一", "qq": "88888888"}})
        self.assertEqual(updated["contactAddress1"], "新地址一")
        self.assertEqual(updated["contactQq"], "88888888")
        tasks = self.server.storage.due_outbox()
        self.assertEqual(tasks[0]["operation"], "contact.update")
        # 未绑定者修改联系人字段应被拒绝（预期错误不弹窗）
        outsider_token = self.server.storage.create_session("openid-outsider")["token"]
        with self.assertRaises(PermissionError):
            self.server.dispatch({"action": "profile.update", "token": outsider_token, "patch": {"address1": "越权地址"}})

    def test_only_configured_admin_can_create_events(self):
        previous = config.ADMIN_PHONE
        config.ADMIN_PHONE = "13800138000"
        try:
            member_token = self.session_for("member", "13900139000", "member-contact")
            with self.assertRaisesRegex(PermissionError, "仅管理员"):
                self.server.dispatch({"action": "events.create", "token": member_token, "title": "普通用户活动", "deadline": "2099-01-01 20:00"})
            admin_token = self.session_for("admin", "13800138000", "admin-contact")
            created = self.server.dispatch({"action": "events.create", "token": admin_token, "title": "管理员活动", "deadline": "2099-01-01 20:00"})
            self.assertTrue(created["_id"])
            listed = self.server.dispatch({"action": "events.list", "token": admin_token, "type": "lottery"})
            self.assertTrue(listed["isAdmin"])
        finally:
            config.ADMIN_PHONE = previous


if __name__ == "__main__":
    unittest.main()
