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
        old_path = config.DATABASE_PATH
        config.DATABASE_PATH = self.path
        self.server = WeMailServer()
        config.DATABASE_PATH = old_path
        self.address = ("127.0.0.1", 30000)

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            path = Path(self.path + suffix)
            if path.exists():
                path.unlink()

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


if __name__ == "__main__":
    unittest.main()
