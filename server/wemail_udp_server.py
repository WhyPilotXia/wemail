import base64
import gzip
import json
import logging
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from logging.handlers import RotatingFileHandler
from pathlib import Path

import config
import notion_api
from notion_sync import NotionSyncWorker
from storage import Storage

LOGGER = logging.getLogger("wemail.server")


class ProtocolError(Exception):
    pass


class RateLimiter:
    def __init__(self, limit=240, window=60):
        self.limit = limit
        self.window = window
        self.hits = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, address):
        now = time.time()
        key = address[0]
        with self.lock:
            queue = self.hits[key]
            while queue and queue[0] <= now - self.window:
                queue.popleft()
            if len(queue) >= self.limit:
                return False
            queue.append(now)
            return True


class WeMailServer:
    def __init__(self):
        self.storage = Storage()
        self.fragments = {}
        self.responses = {}
        self.inflight = set()
        self.lock = threading.RLock()
        self.limiter = RateLimiter()

    @staticmethod
    def wechat_get(path, params):
        url = f"https://api.weixin.qq.com{path}?{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(url, timeout=12) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"微信接口 HTTP {error.code}") from error
        if data.get("errcode"):
            raise RuntimeError(f"微信接口错误 {data['errcode']}: {data.get('errmsg', '')}")
        return data

    @staticmethod
    def wechat_post(path, params, body):
        url = f"https://api.weixin.qq.com{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"微信接口 HTTP {error.code}") from error
        if data.get("errcode"):
            raise RuntimeError(f"微信接口错误 {data['errcode']}: {data.get('errmsg', '')}")
        return data

    def access_token(self):
        now = time.time()
        cached = getattr(self, "_access_token", None)
        if cached and cached[1] > now + 120:
            return cached[0]
        data = self.wechat_get("/cgi-bin/token", {"grant_type": "client_credential", "appid": config.WECHAT_APP_ID, "secret": config.WECHAT_APP_SECRET})
        token = data.get("access_token")
        if not token:
            raise RuntimeError("微信未返回 access_token")
        self._access_token = (token, now + int(data.get("expires_in", 7200)))
        return token

    @staticmethod
    def public_profile(profile):
        return {
            "nickname": profile.get("nickname", "微信用户"), "avatarUrl": profile.get("avatar_data", ""),
            "phoneNumber": profile.get("phone_number", ""), "contactId": profile.get("contact_id", ""),
            "contactName": profile.get("contact_name", ""), "address": profile.get("address", ""),
            "postcode": profile.get("postcode", ""),
        }

    def login(self, code):
        if not config.WECHAT_APP_SECRET:
            raise RuntimeError("服务器尚未配置 WECHAT_APP_SECRET")
        data = self.wechat_get("/sns/jscode2session", {"appid": config.WECHAT_APP_ID, "secret": config.WECHAT_APP_SECRET, "js_code": code, "grant_type": "authorization_code"})
        openid = data.get("openid")
        if not openid:
            raise RuntimeError("微信登录未返回 openid")
        self.storage.get_profile(openid)
        return self.storage.create_session(openid)

    def bind_phone(self, openid, code):
        token = self.access_token()
        data = self.wechat_post("/wxa/business/getuserphonenumber", {"access_token": token}, {"code": code})
        phone = (data.get("phone_info") or {}).get("phoneNumber")
        if not phone:
            raise RuntimeError("未能获取手机号")
        matches = [item for item in self.storage.list_notion_contacts() if notion_api.phone_key(item["phone"]) == notion_api.phone_key(phone)]
        if len(matches) > 1:
            raise RuntimeError("该手机号匹配到多位联系人，请联系管理员处理")
        patch = {"phone_number": notion_api.phone_key(phone)}
        if len(matches) == 1:
            item = matches[0]
            patch.update({"contact_id": item["id"], "contact_name": item["name"], "address": item["address1"], "postcode": item["postcode1"]})
        return {"profile": self.public_profile(self.storage.save_profile(openid, patch))}

    def dispatch(self, event):
        action = str(event.get("action") or "")
        if action == "auth.login":
            return self.login(str(event.get("code") or ""))
        openid = self.storage.session_openid(event.get("token"))
        if not openid:
            raise PermissionError("登录已过期")
        profile = self.storage.get_profile(openid)
        if action == "profile.get":
            mail = self.storage.list_notion_mails(profile)
            return {"openid": openid, "profile": self.public_profile(profile), "stats": mail["stats"], "recent": mail["records"][:3], "sync": self.storage.sync_status()}
        if action == "profile.update":
            patch = event.get("patch") or {}
            mapping = {"nickname": "nickname", "avatarData": "avatar_data", "address": "address", "postcode": "postcode"}
            converted = {target: patch[source] for source, target in mapping.items() if source in patch}
            if len(converted.get("avatar_data", "")) > 64000:
                raise ValueError("头像过大，请选择更小的图片")
            return self.public_profile(self.storage.save_profile(openid, converted))
        if action == "profile.bindPhone":
            return self.bind_phone(openid, str(event.get("code") or ""))
        if action == "contacts.list":
            contacts = self.storage.list_notion_contacts(profile)
            if not contacts and not self.storage.sync_status()["contactsLastSync"]:
                raise RuntimeError("通讯录尚未完成首次同步，请稍后重试并检查服务端 Notion 日志")
            return contacts
        if action == "mail.list":
            result = self.storage.list_notion_mails(profile)
            result["sync"] = self.storage.sync_status()
            return result
        if action == "mail.create":
            return self.storage.create_local_mail(profile, event)
        if action == "mail.sign":
            return self.storage.sign_local_mail(profile, str(event.get("pageId") or ""))
        if action == "events.list":
            return self.storage.list_events(openid, str(event.get("type") or "lottery"))
        if action == "events.create":
            return self.storage.create_event(openid, profile, event)
        if action == "events.join":
            return self.storage.join_event(openid, profile, str(event.get("eventId") or ""), event.get("note"))
        if action == "events.draw":
            return self.storage.draw_event(openid, str(event.get("eventId") or ""))
        if action == "reading.get":
            return self.storage.get_progress(openid, str(event.get("book") or ""))
        if action == "reading.save":
            return self.storage.save_progress(openid, event)
        raise ValueError("未知操作")

    @staticmethod
    def encode_response(request_id, response):
        text = json.dumps(response, ensure_ascii=True, separators=(",", ":"))
        compressed = gzip.compress(text.encode("utf-8"), compresslevel=5)
        use_gzip = len(text) >= 4096 and len(compressed) * 4 // 3 < len(text)
        payload = base64.b64encode(compressed).decode("ascii") if use_gzip else text
        total = max(1, (len(payload) + config.RESPONSE_CHUNK_SIZE - 1) // config.RESPONSE_CHUNK_SIZE)
        return [json.dumps({
            "v": 2, "t": "s", "id": request_id, "p": part, "n": total, "z": 1 if use_gzip else 0,
            "d": payload[part * config.RESPONSE_CHUNK_SIZE:(part + 1) * config.RESPONSE_CHUNK_SIZE],
        }, ensure_ascii=False, separators=(",", ":")).encode("utf-8") for part in range(total)]

    def cleanup(self):
        now = time.time()
        with self.lock:
            for key, value in list(self.fragments.items()):
                if value["created"] < now - 20:
                    self.fragments.pop(key, None)
            for key, value in list(self.responses.items()):
                if value["created"] < now - 60:
                    self.responses.pop(key, None)

    def receive_packet(self, raw, address):
        if raw.startswith(b'{"type":"wemail-udp-echo"'):
            return "echo", raw
        try:
            packet = json.loads(raw.decode("utf-8"))
        except Exception as error:
            raise ProtocolError("无效 JSON 数据包") from error
        if packet.get("v") != 2 or packet.get("t") != "q":
            raise ProtocolError("不支持的协议")
        request_id = str(packet.get("id") or "")[:80]
        total = int(packet.get("n") or 0)
        part = int(packet.get("p") if packet.get("p") is not None else -1)
        if not request_id or total < 1 or total > 120 or part < 0 or part >= total:
            raise ProtocolError("无效分片")
        cache_key = (address[0], request_id)
        with self.lock:
            cached = self.responses.get(cache_key)
            if cached:
                LOGGER.info("request replay_cache id=%s ip=%s packets=%d", request_id, address[0], len(cached["packets"]))
                return "response", cached["packets"]
            if cache_key in self.inflight:
                LOGGER.info("request retry_inflight id=%s ip=%s", request_id, address[0])
                return "pending", None
            state = self.fragments.setdefault(cache_key, {"created": time.time(), "total": total, "parts": {}})
            if state["total"] != total:
                raise ProtocolError("分片参数不一致")
            state["parts"][part] = str(packet.get("d") or "")
            if len(state["parts"]) < total:
                return "pending", None
            text = "".join(state["parts"][index] for index in range(total))
            self.fragments.pop(cache_key, None)
            self.inflight.add(cache_key)
        if len(text.encode("utf-8")) > config.MAX_REQUEST_BYTES:
            with self.lock:
                self.inflight.discard(cache_key)
            raise ProtocolError("请求体过大")
        try:
            event = json.loads(text)
        except Exception as error:
            with self.lock:
                self.inflight.discard(cache_key)
            raise ProtocolError("请求体解析失败") from error
        timestamp = int(event.get("timestamp") or 0)
        if abs(int(time.time() * 1000) - timestamp) > 120000:
            with self.lock:
                self.inflight.discard(cache_key)
            raise ProtocolError("请求时间已过期")
        return "request", (cache_key, request_id, event)

    def execute(self, item, server, address):
        cache_key, request_id, event = item
        action = event.get("action") or "unknown"
        started = time.monotonic()
        LOGGER.info("request start id=%s action=%s ip=%s port=%d", request_id, action, address[0], address[1])
        try:
            response = {"ok": True, "data": self.dispatch(event)}
        except PermissionError as error:
            response = {"ok": False, "code": "UNAUTHORIZED", "message": str(error), "requestId": request_id}
        except Exception as error:
            LOGGER.exception("request failed id=%s action=%s ip=%s", request_id, action, address[0])
            response = {"ok": False, "code": "UPSTREAM_ERROR", "message": str(error) or "服务异常", "requestId": request_id}
        packets = self.encode_response(request_id, response)
        with self.lock:
            self.inflight.discard(cache_key)
            self.responses[cache_key] = {"created": time.time(), "packets": packets}
        sent = 0
        for packet in packets:
            try:
                server.sendto(packet, address)
                sent += 1
            except OSError as error:
                LOGGER.warning("response send_error id=%s action=%s ip=%s port=%d sent=%d/%d error=%s", request_id, action, address[0], address[1], sent, len(packets), error)
                break
        LOGGER.info("request finish id=%s action=%s ok=%s elapsed_ms=%d packets=%d/%d", request_id, action, response.get("ok"), int((time.monotonic() - started) * 1000), sent, len(packets))


def configure_logging():
    level = getattr(logging, config.LOG_LEVEL, logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    handlers = [logging.StreamHandler()]
    if config.LOG_FILE:
        log_path = Path(config.LOG_FILE)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"))
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    for handler in handlers:
        handler.setFormatter(formatter)
        root.addHandler(handler)


def main():
    configure_logging()
    missing = config.validate()
    if missing:
        LOGGER.warning("missing configuration: %s", ", ".join(missing))
    application = WeMailServer()
    sync_worker = NotionSyncWorker(application.storage)
    sync_worker.start()
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((config.HOST, config.PORT))
    pool = ThreadPoolExecutor(max_workers=16, thread_name_prefix="wemail")
    LOGGER.info("WeMail UDP server listening on %s:%d log_file=%s", config.HOST, config.PORT, config.LOG_FILE or "disabled")
    while True:
        try:
            raw, address = server.recvfrom(config.MAX_DATAGRAM)
        except ConnectionResetError as error:
            LOGGER.warning("udp receive reset ignored error=%s", error)
            continue
        except OSError:
            LOGGER.exception("udp receive error; retrying")
            time.sleep(0.1)
            continue
        if not application.limiter.allow(address):
            LOGGER.warning("rate limited ip=%s", address[0])
            continue
        application.cleanup()
        try:
            kind, item = application.receive_packet(raw, address)
            if kind == "echo":
                server.sendto(item, address)
            elif kind == "response":
                for packet in item:
                    server.sendto(packet, address)
            elif kind == "request":
                pool.submit(application.execute, item, server, address)
        except ProtocolError as error:
            LOGGER.warning("protocol error from %s:%d: %s", address[0], address[1], error)
        except Exception:
            LOGGER.exception("unexpected datagram error from %s:%d", address[0], address[1])


if __name__ == "__main__":
    main()
