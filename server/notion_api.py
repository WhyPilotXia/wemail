import json
import logging
import socket
import threading
import time
import urllib.error
import urllib.request

import config

_CACHE = {}
_CACHE_LOCK = threading.Lock()
LOGGER = logging.getLogger("wemail.notion")


def cached(key, ttl, loader):
    now = time.time()
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if item and item[0] > now:
            LOGGER.debug("cache hit key=%s", key)
            return item[1]
    try:
        value = loader()
    except Exception:
        if item:
            LOGGER.warning("cache stale_fallback key=%s", key)
            return item[1]
        raise
    with _CACHE_LOCK:
        _CACHE[key] = (now + ttl, value)
    return value


def invalidate(prefix):
    with _CACHE_LOCK:
        for key in list(_CACHE):
            if key.startswith(prefix):
                _CACHE.pop(key, None)


def request(path, method="GET", body=None):
    if not config.NOTION_TOKEN:
        raise RuntimeError("服务器尚未配置 NOTION_TOKEN")
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    attempts = config.NOTION_READ_ATTEMPTS if method == "GET" or path.endswith("/query") else 1
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            f"https://api.notion.com/v1{path}",
            data=payload,
            method=method,
            headers={
                "Authorization": f"Bearer {config.NOTION_TOKEN}",
                "Notion-Version": config.NOTION_VERSION,
                "Content-Type": "application/json",
                "Connection": "close",
            },
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=config.NOTION_TIMEOUT_SECONDS) as response:
                result = json.loads(response.read().decode("utf-8"))
            LOGGER.info("notion ok method=%s path=%s attempt=%d elapsed_ms=%d", method, path, attempt, int((time.monotonic() - started) * 1000))
            return result
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read().decode("utf-8")).get("message")
            except Exception:
                detail = None
            LOGGER.warning("notion http_error method=%s path=%s status=%d elapsed_ms=%d", method, path, error.code, int((time.monotonic() - started) * 1000))
            raise RuntimeError(detail or f"Notion {error.code}") from error
        except (socket.timeout, TimeoutError, urllib.error.URLError) as error:
            elapsed = int((time.monotonic() - started) * 1000)
            LOGGER.warning("notion network_error method=%s path=%s attempt=%d/%d elapsed_ms=%d error=%s", method, path, attempt, attempts, elapsed, error)
            if attempt >= attempts:
                raise RuntimeError(f"Notion 网络超时，已尝试 {attempt} 次") from error
            time.sleep(0.3 * attempt)


def read(prop=None):
    prop = prop or {}
    kind = prop.get("type")
    if kind in ("title", "rich_text"):
        return "".join(item.get("plain_text", "") for item in prop.get(kind, [])).strip()
    if kind in ("phone_number", "email", "url", "number", "checkbox"):
        return prop.get(kind)
    if kind == "date":
        return (prop.get("date") or {}).get("start", "")
    if kind == "relation":
        return [item.get("id") for item in prop.get("relation", [])]
    if kind == "select":
        return (prop.get("select") or {}).get("name", "")
    return ""


def query_all(source_id, page_size=100, sorts=None):
    results = []
    cursor = None
    while True:
        body = {"page_size": page_size}
        if cursor:
            body["start_cursor"] = cursor
        if sorts:
            body["sorts"] = sorts
        response = request(f"/data_sources/{source_id}/query", "POST", body)
        results.extend(response.get("results", []))
        cursor = response.get("next_cursor") if response.get("has_more") else None
        if not cursor or len(results) >= 300:
            return results


def contact(row):
    props = row.get("properties", {})
    return {
        "id": row["id"],
        "name": read(props.get("姓名/昵称")),
        "phone": read(props.get("电话")),
        "email": read(props.get("电子邮箱")),
        "address1": read(props.get("地址1")),
        "postcode1": read(props.get("邮编1")),
        "address2": read(props.get("地址2")),
        "postcode2": read(props.get("邮编2")),
        "qq": read(props.get("QQ")),
    }


def phone_key(value):
    digits = "".join(char for char in str(value or "") if char.isdigit())
    return digits[2:] if digits.startswith("86") and len(digits) == 13 else digits


def mask_phone(value):
    phone = phone_key(value)
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 7 else ""


def fetch_contacts():
    result = []
    for row in query_all(config.CONTACT_SOURCE):
        item = contact(row)
        if item["name"] or item["phone"]:
            result.append(item)
    return result


def contacts(profile=None, reveal_phone=False):
    profile = profile or {}
    result = []
    for source in fetch_contacts():
        item = dict(source)
        if not reveal_phone:
            item["phone"] = mask_phone(item["phone"]) if item["phone"] else ""
        item["isMe"] = profile.get("contact_id") == item["id"]
        result.append(item)
    return result


def fetch_mails():
    rows = query_all(config.MAIL_SOURCE, 50, [{"property": "寄出日期", "direction": "descending"}])
    result = []
    for row in rows:
        props = row.get("properties", {})
        senders = read(props.get("寄件人")) or []
        recipients = read(props.get("收件人")) or []
        result.append({"pageId": row["id"], "sendDate": read(props.get("寄出日期")), "trackingNo": read(props.get("邮件编号")), "mailType": read(props.get("备注")) or "平信", "received": bool(read(props.get("签收"))), "senderId": senders[0] if senders else "", "recipientId": recipients[0] if recipients else ""})
    return result


def mail_list(profile):
    if not config.NOTION_TOKEN:
        return {"records": [], "stats": {"sent": 0, "received": 0, "unsigned": 0}, "setupRequired": True}
    rows = cached("mail:rows", 30, lambda: query_all(config.MAIL_SOURCE, 50, [{"property": "寄出日期", "direction": "descending"}]))
    contact_list = contacts()
    names = {item["id"]: item["name"] for item in contact_list}
    records = []
    for row in rows:
        props = row.get("properties", {})
        senders = read(props.get("寄件人")) or []
        recipients = read(props.get("收件人")) or []
        item = {
            "pageId": row["id"], "sendDate": read(props.get("寄出日期")),
            "trackingNo": read(props.get("邮件编号")), "mailType": read(props.get("备注")) or "平信",
            "received": bool(read(props.get("签收"))), "senderId": senders[0] if senders else "",
            "recipientId": recipients[0] if recipients else "",
        }
        item["senderName"] = names.get(item["senderId"], "")
        item["recipientName"] = names.get(item["recipientId"], "")
        records.append(item)
    contact_id = profile.get("contact_id")
    mine = [item for item in records if contact_id and contact_id in (item["senderId"], item["recipientId"])]
    for item in mine:
        item["direction"] = "sent" if item["senderId"] == contact_id else "received"
    from datetime import datetime, timedelta, timezone
    since = datetime.now(timezone.utc) - timedelta(days=14)
    def recent(item):
        try:
            value = datetime.fromisoformat(item["sendDate"].replace("Z", "+00:00"))
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value >= since
        except Exception:
            return False
    return {"records": mine, "stats": {
        "sent": sum(item["senderId"] == contact_id and recent(item) for item in mine),
        "received": sum(item["recipientId"] == contact_id and recent(item) for item in mine),
        "unsigned": sum(item["recipientId"] == contact_id and not item["received"] for item in mine),
    }}


def create_mail_remote(data):
    properties = {
        " ": {"title": [{"text": {"content": str(data.get("title") or "由 WeMail 小程序提交")[:100]}}]},
        "寄件人": {"relation": [{"id": data["senderId"]}]},
        "收件人": {"relation": [{"id": data["recipientId"]}]},
        "寄出日期": {"date": {"start": data.get("sendDate")}},
        "备注": {"rich_text": [{"text": {"content": str(data.get("mailType") or "平信")[:100]}}]},
        "签收": {"checkbox": False},
    }
    if data.get("trackingNo"):
        properties["邮件编号"] = {"rich_text": [{"text": {"content": str(data["trackingNo"])[:100]}}]}
    result = request("/pages", "POST", {"parent": {"database_id": config.MAIL_DATABASE}, "properties": properties})
    return result["id"]


def sign_mail_remote(page_id):
    request(f"/pages/{page_id}", "PATCH", {"properties": {"签收": {"checkbox": True}}})
