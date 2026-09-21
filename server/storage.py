import hashlib
import json
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import config
from notion_api import name_key


class ContactBindingRequiredError(PermissionError):
    """用户未关联联系人身份，对应服务层 IDENTITY_REQUIRED 预期错误。"""


def phone_key(value):
    digits = "".join(char for char in str(value or "") if char.isdigit())
    return digits[2:] if digits.startswith("86") and len(digits) == 13 else digits


class Storage:
    def __init__(self, path=None):
        self.path = path or config.DATABASE_PATH
        self.lock = threading.RLock()
        self.init_schema()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self):
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
              openid TEXT PRIMARY KEY,
              nickname TEXT NOT NULL DEFAULT '微信用户',
              avatar_data TEXT NOT NULL DEFAULT '',
              phone_number TEXT NOT NULL DEFAULT '',
              contact_id TEXT NOT NULL DEFAULT '',
              contact_name TEXT NOT NULL DEFAULT '',
              address TEXT NOT NULL DEFAULT '',
              postcode TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
              token TEXT PRIMARY KEY,
              openid TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_openid ON sessions(openid);
            CREATE TABLE IF NOT EXISTS events (
              id TEXT PRIMARY KEY,
              type TEXT NOT NULL,
              title TEXT NOT NULL,
              description TEXT NOT NULL DEFAULT '',
              deadline TEXT NOT NULL,
              participant_limit INTEGER NOT NULL DEFAULT 0,
              allow_note INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL DEFAULT 'open',
              participant_count INTEGER NOT NULL DEFAULT 0,
              owner_name TEXT NOT NULL DEFAULT '',
              owner_openid TEXT NOT NULL,
              winner_name TEXT NOT NULL DEFAULT '',
              winner_openid TEXT NOT NULL DEFAULT '',
              drawn_at TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS event_entries (
              id TEXT PRIMARY KEY,
              event_id TEXT NOT NULL,
              openid TEXT NOT NULL,
              name TEXT NOT NULL,
              avatar_data TEXT NOT NULL DEFAULT '',
              note TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              UNIQUE(event_id, openid),
              FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS reading_progress (
              id TEXT PRIMARY KEY,
              openid TEXT NOT NULL,
              book TEXT NOT NULL,
              chapter_index INTEGER NOT NULL DEFAULT 0,
              chapter_title TEXT NOT NULL DEFAULT '',
              completed INTEGER NOT NULL DEFAULT 0,
              progress REAL NOT NULL DEFAULT 0,
              updated_at TEXT NOT NULL,
              UNIQUE(openid, book)
            );
            CREATE TABLE IF NOT EXISTS contact_bindings (
              contact_id TEXT PRIMARY KEY,
              openid TEXT NOT NULL,
              nickname TEXT NOT NULL DEFAULT '',
              bound_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_bindings_openid ON contact_bindings(openid);
            CREATE TABLE IF NOT EXISTS notion_contacts (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL DEFAULT '',
              phone TEXT NOT NULL DEFAULT '',
              email TEXT NOT NULL DEFAULT '',
              address1 TEXT NOT NULL DEFAULT '',
              postcode1 TEXT NOT NULL DEFAULT '',
              address2 TEXT NOT NULL DEFAULT '',
              postcode2 TEXT NOT NULL DEFAULT '',
              qq TEXT NOT NULL DEFAULT '',
              synced_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notion_mails (
              id TEXT PRIMARY KEY,
              notion_page_id TEXT UNIQUE,
              send_date TEXT NOT NULL DEFAULT '',
              tracking_no TEXT NOT NULL DEFAULT '',
              mail_type TEXT NOT NULL DEFAULT '平信',
              received INTEGER NOT NULL DEFAULT 0,
              sender_id TEXT NOT NULL DEFAULT '',
              recipient_id TEXT NOT NULL DEFAULT '',
              sync_state TEXT NOT NULL DEFAULT 'synced',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notion_outbox (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              operation TEXT NOT NULL,
              entity_id TEXT NOT NULL,
              payload TEXT NOT NULL,
              attempts INTEGER NOT NULL DEFAULT 0,
              next_attempt_at TEXT NOT NULL,
              last_error TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_outbox_due ON notion_outbox(next_attempt_at, id);
            CREATE TABLE IF NOT EXISTS sync_meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """)

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def get_profile(self, openid):
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE openid=?", (openid,)).fetchone()
            if row:
                return dict(row)
            now = self.now()
            db.execute("INSERT INTO users(openid, created_at, updated_at) VALUES(?,?,?)", (openid, now, now))
            return dict(db.execute("SELECT * FROM users WHERE openid=?", (openid,)).fetchone())

    def save_profile(self, openid, patch):
        allowed = {
            "nickname": 200, "avatar_data": 64000, "phone_number": 32,
            "contact_id": 100, "contact_name": 200, "address": 300, "postcode": 32,
        }
        values = {key: str(value or "")[:allowed[key]] for key, value in patch.items() if key in allowed}
        self.get_profile(openid)
        if values:
            values["updated_at"] = self.now()
            columns = ",".join(f"{key}=?" for key in values)
            with self.connect() as db:
                db.execute(f"UPDATE users SET {columns} WHERE openid=?", (*values.values(), openid))
        return self.get_profile(openid)

    def create_session(self, openid):
        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=config.SESSION_DAYS)
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires_at<?", (now.isoformat(),))
            db.execute(
                "INSERT INTO sessions(token,openid,expires_at,created_at) VALUES(?,?,?,?)",
                (token, openid, expires.isoformat(), now.isoformat()),
            )
        return {"token": token, "expiresAt": int(expires.timestamp() * 1000), "openid": openid}

    def session_openid(self, token):
        if not token:
            return None
        with self.connect() as db:
            row = db.execute("SELECT openid,expires_at FROM sessions WHERE token=?", (token,)).fetchone()
        if not row or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
            return None
        return row["openid"]

    def bind_verification(self, openid, name, phone):
        """核验姓名+手机号是否命中本地 Notion 联系人缓存。

        返回 state（pending / bound_self / bound_other）与联系人信息；
        pending 时附带 confirm_token，确认绑定和强绑解绑都须回传该令牌。
        """
        key = phone_key(phone)
        if not key:
            raise ValueError("请输入有效的手机号")
        name_match = name_key(name)
        matches = [item for item in self.list_notion_contacts() if phone_key(item["phone"]) == key and name_key(item["name"]) == name_match]
        if not matches:
            raise ValueError("未在联系人表中找到该姓名与手机号，请核对后重试")
        if len(matches) > 1:
            raise RuntimeError("该手机号匹配到多位同名联系人，请联系管理员处理")
        contact = matches[0]
        confirm_token = self._bind_token(openid, contact["id"])
        existing = self.get_binding(contact["id"])
        if existing:
            info = {"contactId": contact["id"], "contactName": contact["name"], "phoneNumber": key, "boundNickname": existing["nickname"], "boundOpenid": existing["openid"], "confirmToken": confirm_token}
            return {"state": "bound_self" if existing["openid"] == openid else "bound_other", **info}
        return {"state": "pending", "contactId": contact["id"], "contactName": contact["name"], "phoneNumber": key, "confirmToken": confirm_token}

    def confirm_binding(self, openid, nickname, confirm_token):
        """凭 confirm_token 执行绑定；bound_other 时须 force=True 强制解绑原账户。"""
        contact = self._contact_for_token(openid, confirm_token)
        contact_id = contact["id"]
        existing = self.get_binding(contact_id)
        if existing and existing["openid"] != openid:
            raise PermissionError("当前身份信息已被其他账户绑定，请返回重新验证")
        self.get_profile(openid)
        now = self.now()
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            nickname = str(nickname or "微信用户")[:200]
            db.execute(
                """INSERT INTO contact_bindings(contact_id,openid,nickname,bound_at,updated_at) VALUES(?,?,?,?,?)
                  ON CONFLICT(contact_id) DO UPDATE SET openid=excluded.openid,nickname=excluded.nickname,updated_at=excluded.updated_at""",
                (contact_id, openid, nickname, now, now),
            )
            patch = {
                "phone_number": phone_key(contact["phone"]),
                "contact_id": contact_id,
                "contact_name": contact["name"],
                "address": contact["address1"] or "",
                "postcode": contact["postcode1"] or "",
            }
            columns = ",".join(f"{key}=?" for key in patch)
            db.execute(f"UPDATE users SET {columns},updated_at=? WHERE openid=?", (*patch.values(), now, openid))
        return {"profile": self.public_profile(self.get_profile(openid))}

    def force_transfer_binding(self, openid, nickname, confirm_token):
        """将已被他人绑定的联系人转移到当前 openid，原 openid 的联系人快照字段被清空。"""
        contact = self._contact_for_token(openid, confirm_token)
        contact_id = contact["id"]
        existing = self.get_binding(contact_id)
        if not existing or existing["openid"] == openid:
            return self.confirm_binding(openid, nickname, confirm_token)
        previous_openid = existing["openid"]
        self.get_profile(openid)
        now = self.now()
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            nickname = str(nickname or "微信用户")[:200]
            db.execute(
                """INSERT INTO contact_bindings(contact_id,openid,nickname,bound_at,updated_at) VALUES(?,?,?,?,?)
                  ON CONFLICT(contact_id) DO UPDATE SET openid=excluded.openid,nickname=excluded.nickname,updated_at=excluded.updated_at""",
                (contact_id, openid, nickname, now, now),
            )
            patch = {
                "phone_number": phone_key(contact["phone"]),
                "contact_id": contact_id,
                "contact_name": contact["name"],
                "address": contact["address1"] or "",
                "postcode": contact["postcode1"] or "",
            }
            columns = ",".join(f"{key}=?" for key in patch)
            db.execute(f"UPDATE users SET {columns},updated_at=? WHERE openid=?", (*patch.values(), now, openid))
            db.execute(
                "UPDATE users SET phone_number='',contact_id='',contact_name='',address='',postcode='',updated_at=? WHERE openid=?",
                (now, previous_openid),
            )
        return {"profile": self.public_profile(self.get_profile(openid))}

    def get_binding(self, contact_id):
        if not contact_id:
            return None
        with self.connect() as db:
            row = db.execute("SELECT * FROM contact_bindings WHERE contact_id=?", (contact_id,)).fetchone()
        return dict(row) if row else None

    def _contact_for_token(self, openid, confirm_token):
        for item in self.list_notion_contacts():
            if self._bind_token(openid, item["id"]) == confirm_token:
                return item
        raise ValueError("验证已过期，请返回重新验证")

    def _bind_token(self, openid, contact_id):
        material = f"{openid}:{contact_id}:{config.BIND_TOKEN_SECRET}".encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    @staticmethod
    def public_profile(profile):
        return {
            "nickname": profile.get("nickname", "微信用户"),
            "avatarUrl": profile.get("avatar_data", ""),
            "phoneNumber": profile.get("phone_number", ""),
            "contactId": profile.get("contact_id", ""),
            "contactName": profile.get("contact_name", ""),
            "address": profile.get("address", ""),
            "postcode": profile.get("postcode", ""),
        }

    def list_events(self, openid, event_type):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM events WHERE type=? ORDER BY created_at DESC LIMIT 50", (event_type,)).fetchall()
            joined = {row[0] for row in db.execute("SELECT event_id FROM event_entries WHERE openid=?", (openid,)).fetchall()}
        result = []
        labels = {"open": "进行中", "drawn": "已开奖", "full": "已满员", "closed": "已截止"}
        for row in rows:
            item = dict(row)
            item["_id"] = item.pop("id")
            item["limit"] = item.pop("participant_limit")
            item.pop("allow_note", None)
            item["participantCount"] = item.pop("participant_count")
            item["ownerName"] = item.pop("owner_name")
            owner = item.pop("owner_openid")
            item["winnerName"] = item.pop("winner_name")
            item.pop("winner_openid")
            item["createdAt"] = item.pop("created_at")
            item["updatedAt"] = item.pop("updated_at")
            item["joined"] = item["_id"] in joined
            item["isOwner"] = owner == openid
            item["statusText"] = labels.get(item["status"], "已截止")
            result.append(item)
        return result

    def create_event(self, openid, profile, data):
        event_id = secrets.token_hex(16)
        now = self.now()
        deadline = str(data.get("deadline") or "").replace(" ", "T")
        if not data.get("title") or not deadline:
            raise ValueError("请填写标题和截止时间")
        with self.connect() as db:
            db.execute(
                "INSERT INTO events(id,type,title,description,deadline,participant_limit,status,owner_name,owner_openid,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (event_id, "signup" if data.get("type") == "signup" else "lottery", str(data["title"])[:80], str(data.get("description") or "")[:500], deadline, max(0, int(data.get("limit") or 0)), "open", profile.get("contact_name") or profile.get("nickname") or "微信用户", openid, now, now),
            )
        return {"_id": event_id}

    def join_event(self, openid, profile, event_id):
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            event = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
            if not event:
                raise ValueError("活动不存在")
            deadline = datetime.fromisoformat(event["deadline"].replace("Z", "+00:00"))
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone(timedelta(hours=8)))
            if event["status"] != "open" or deadline <= datetime.now(timezone.utc):
                raise ValueError("活动已截止")
            if db.execute("SELECT 1 FROM event_entries WHERE event_id=? AND openid=?", (event_id, openid)).fetchone():
                raise ValueError("你已经参与过了")
            count = int(event["participant_count"] or 0)
            limit = int(event["participant_limit"] or 0)
            if limit and count >= limit:
                raise ValueError("报名人数已满")
            next_count = count + 1
            db.execute(
                "INSERT INTO event_entries(id,event_id,openid,name,avatar_data,created_at) VALUES(?,?,?,?,?,?)",
                (secrets.token_hex(16), event_id, openid, profile.get("contact_name") or profile.get("nickname") or "微信用户", profile.get("avatar_data") or "", self.now()),
            )
            db.execute("UPDATE events SET participant_count=?,status=?,updated_at=? WHERE id=?", (next_count, "full" if limit and next_count >= limit else "open", self.now(), event_id))
        return {"joined": True}

    def draw_event(self, openid, event_id):
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            event = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
            if not event:
                raise ValueError("活动不存在")
            if event["owner_openid"] != openid:
                raise ValueError("只有发起人可以开奖")
            if event["status"] == "drawn":
                raise ValueError("活动已经开奖")
            winner = db.execute("SELECT * FROM event_entries WHERE event_id=? ORDER BY RANDOM() LIMIT 1", (event_id,)).fetchone()
            name = winner["name"] if winner else ""
            winner_openid = winner["openid"] if winner else ""
            db.execute("UPDATE events SET status='drawn',winner_name=?,winner_openid=?,drawn_at=?,updated_at=? WHERE id=?", (name, winner_openid, self.now(), self.now(), event_id))
        return {"winnerName": name}

    def get_progress(self, openid, book):
        with self.connect() as db:
            row = db.execute("SELECT * FROM reading_progress WHERE openid=? AND book=?", (openid, book)).fetchone()
        if not row:
            return {"book": book, "chapterIndex": 0, "completed": False}
        return {"book": row["book"], "chapterIndex": row["chapter_index"], "chapterTitle": row["chapter_title"], "completed": bool(row["completed"]), "progress": row["progress"], "updatedAt": row["updated_at"]}

    def save_progress(self, openid, data):
        book = str(data.get("book") or "")[:100]
        if not book:
            raise ValueError("缺少书名")
        item = {
            "book": book,
            "chapterIndex": max(0, int(data.get("chapterIndex") or 0)),
            "chapterTitle": str(data.get("chapterTitle") or "")[:200],
            "completed": bool(data.get("completed")),
            "progress": max(0.0, min(1.0, float(data.get("progress") or 0))),
            "updatedAt": self.now(),
        }
        row_id = secrets.token_hex(16)
        with self.connect() as db:
            db.execute("""INSERT INTO reading_progress(id,openid,book,chapter_index,chapter_title,completed,progress,updated_at)
              VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(openid,book) DO UPDATE SET chapter_index=excluded.chapter_index,chapter_title=excluded.chapter_title,completed=excluded.completed,progress=excluded.progress,updated_at=excluded.updated_at""",
              (row_id, openid, item["book"], item["chapterIndex"], item["chapterTitle"], int(item["completed"]), item["progress"], item["updatedAt"]))
        return item

    def replace_notion_contacts(self, contacts):
        now = self.now()
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            incoming = set()
            for item in contacts:
                contact_id = str(item.get("id") or "")
                if not contact_id:
                    continue
                incoming.add(contact_id)
                values = tuple(str(item.get(key) or "") for key in (
                    "name", "phone", "email", "address1", "postcode1",
                    "address2", "postcode2", "qq",
                ))
                db.execute("""INSERT INTO notion_contacts(id,name,phone,email,address1,postcode1,address2,postcode2,qq,synced_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,phone=excluded.phone,email=excluded.email,address1=excluded.address1,postcode1=excluded.postcode1,address2=excluded.address2,postcode2=excluded.postcode2,qq=excluded.qq,synced_at=excluded.synced_at""",
                  (contact_id, *values, now))
            if incoming:
                placeholders = ",".join("?" for _ in incoming)
                db.execute(f"DELETE FROM notion_contacts WHERE id NOT IN ({placeholders})", tuple(incoming))
            db.execute("INSERT INTO sync_meta(key,value,updated_at) VALUES('contacts_last_sync',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at", (now, now))

    def list_notion_contacts(self, profile=None):
        profile = profile or {}
        with self.connect() as db:
            rows = db.execute("SELECT * FROM notion_contacts ORDER BY name COLLATE NOCASE").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item.pop("synced_at", None)
            item["isMe"] = profile.get("contact_id") == item["id"]
            result.append(item)
        return result

    CONTACT_FIELD_LIMITS = {"phone": 32, "email": 200, "address1": 300, "postcode1": 32, "address2": 300, "postcode2": 32, "qq": 20}

    def update_contact(self, openid, profile, patch):
        """修改自己绑定的 Notion 联系人资料：本地缓存即时生效，Notion 异步写回。

        Notion 是联系人资料的权威源；本方法先写本地 notion_contacts 供前端即时显示，
        再通过 notion_outbox 异步 PATCH Notion 页面。若同步失败（Notion 不可达等），
        下一次拉取同步会用 Notion 原值覆盖本地缓存，保持权威源语义。
        """
        contact_id = profile.get("contact_id")
        if not contact_id:
            raise ContactBindingRequiredError("请先在‘我的’中关联联系人身份")
        fields = {}
        for key, value in (patch or {}).items():
            if key not in self.CONTACT_FIELD_LIMITS:
                raise ValueError(f"不支持修改的字段： {key}")
            text = str(value or "").strip()
            if len(text) > self.CONTACT_FIELD_LIMITS[key]:
                raise ValueError(f"{key} 内容过长")
            fields[key] = text
        if not fields:
            raise ValueError("没有需要修改的字段")
        contact = None
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM notion_contacts WHERE id=?", (contact_id,)).fetchone()
            if not row:
                raise ValueError("联系人不存在或通讯录尚未同步，请稍后重试")
            contact = dict(row)
            binding = db.execute("SELECT openid FROM contact_bindings WHERE contact_id=?", (contact_id,)).fetchone()
            if not binding or binding["openid"] != openid:
                raise PermissionError("仅绑定该联系人资料的账户可以修改")
            columns = []
            values = []
            for key, value in fields.items():
                columns.append(f"{key}=?")
                values.append(value)
            columns.append("synced_at=?")
            now = self.now()
            values.append(now)
            db.execute(f"UPDATE notion_contacts SET {','.join(columns)} WHERE id=?", (*values, contact_id))
            payload = {"contactId": contact_id, "fields": fields}
            db.execute("INSERT INTO notion_outbox(operation,entity_id,payload,next_attempt_at,created_at) VALUES('contact.update',?,?,?,?)", (contact_id, json.dumps(payload, ensure_ascii=False), now, now))
        # 保持 users 快照字段与联系人地址/邮编一致（寄件地址默认地址1）
        snapshot_patch = {}
        if "address1" in fields:
            snapshot_patch["address"] = fields["address1"]
        if "postcode1" in fields:
            snapshot_patch["postcode"] = fields["postcode1"]
        if "phone" in fields:
            snapshot_patch["phone_number"] = phone_key(fields["phone"])
        if snapshot_patch:
            self.save_profile(openid, snapshot_patch)
        return {"contact": self.contact_public(dict(row=contact, **fields))}

    def contact_public(self, contact):
        return {
            "id": contact.get("id", ""),
            "name": contact.get("name", ""),
            "phone": contact.get("phone", ""),
            "email": contact.get("email", ""),
            "address1": contact.get("address1", ""),
            "postcode1": contact.get("postcode1", ""),
            "address2": contact.get("address2", ""),
            "postcode2": contact.get("postcode2", ""),
            "qq": contact.get("qq", ""),
        }

    def replace_notion_mails(self, mails):
        now = self.now()
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for item in mails:
                page_id = str(item.get("pageId") or "")
                if not page_id:
                    continue
                db.execute("""INSERT INTO notion_mails(id,notion_page_id,send_date,tracking_no,mail_type,received,sender_id,recipient_id,sync_state,created_at,updated_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(notion_page_id) DO UPDATE SET send_date=excluded.send_date,tracking_no=excluded.tracking_no,mail_type=excluded.mail_type,received=CASE WHEN notion_mails.sync_state='pending_sign' THEN notion_mails.received ELSE excluded.received END,sender_id=excluded.sender_id,recipient_id=excluded.recipient_id,updated_at=excluded.updated_at""",
                  (page_id, page_id, item.get("sendDate", ""), item.get("trackingNo", ""), item.get("mailType", "平信"), int(bool(item.get("received"))), item.get("senderId", ""), item.get("recipientId", ""), "synced", now, now))
            db.execute("INSERT INTO sync_meta(key,value,updated_at) VALUES('mails_last_sync',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at", (now, now))

    def list_notion_mails(self, profile):
        contact_id = profile.get("contact_id")
        with self.connect() as db:
            rows = db.execute("""SELECT m.*,s.name AS sender_name,r.name AS recipient_name FROM notion_mails m
              LEFT JOIN notion_contacts s ON s.id=m.sender_id LEFT JOIN notion_contacts r ON r.id=m.recipient_id
              WHERE ?<>'' AND ? IN (m.sender_id,m.recipient_id) ORDER BY m.send_date DESC,m.created_at DESC LIMIT 300""", (contact_id or "", contact_id or "")).fetchall()
        records = []
        since = datetime.now(timezone.utc) - timedelta(days=14)
        for row in rows:
            item = {"pageId": row["id"], "sendDate": row["send_date"], "trackingNo": row["tracking_no"], "mailType": row["mail_type"], "received": bool(row["received"]), "senderId": row["sender_id"], "recipientId": row["recipient_id"], "senderName": row["sender_name"] or "", "recipientName": row["recipient_name"] or "", "direction": "sent" if row["sender_id"] == contact_id else "received", "syncState": row["sync_state"]}
            try:
                value = datetime.fromisoformat(item["sendDate"].replace("Z", "+00:00"))
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                item["recent"] = value >= since
            except Exception:
                item["recent"] = False
            records.append(item)
        return {"records": records, "stats": {"sent": sum(item["direction"] == "sent" and item["recent"] for item in records), "received": sum(item["direction"] == "received" and item["recent"] for item in records), "unsigned": sum(item["direction"] == "received" and not item["received"] for item in records)}}

    def create_local_mail(self, profile, data):
        if not profile.get("contact_id"):
            raise ValueError("请先在‘我的’中关联联系人身份")
        if data.get("senderId") != profile["contact_id"]:
            raise ValueError("寄件人必须是当前登录用户")
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM notion_contacts WHERE id=?", (data.get("recipientId"),)).fetchone():
                raise ValueError("收件人不存在或通讯录尚未同步")
            local_id = "local-" + secrets.token_hex(12)
            now = self.now()
            tracking_no = str(data.get("trackingNo") or "").strip()[:100]
            if tracking_no and not all(char.isascii() and (char.isalnum() or char == "-") for char in tracking_no):
                raise ValueError("邮件编号仅支持字母、数字和连字符")
            title = str(data.get("title") or "")[:100] if config.MAIL_NOTE_ENABLED else "由 WeMail 小程序登记"
            payload = {"localId": local_id, "senderId": profile["contact_id"], "recipientId": data.get("recipientId"), "sendDate": data.get("sendDate"), "mailType": str(data.get("mailType") or "平信")[:100], "trackingNo": tracking_no, "title": title or "由 WeMail 小程序登记"}
            db.execute("INSERT INTO notion_mails(id,send_date,tracking_no,mail_type,received,sender_id,recipient_id,sync_state,created_at,updated_at) VALUES(?,?,?,?,0,?,?, 'pending_create',?,?)", (local_id, payload["sendDate"] or "", payload["trackingNo"], payload["mailType"], payload["senderId"], payload["recipientId"], now, now))
            db.execute("INSERT INTO notion_outbox(operation,entity_id,payload,next_attempt_at,created_at) VALUES('mail.create',?,?,?,?)", (local_id, json.dumps(payload, ensure_ascii=False), now, now))
        return {"created": True, "pageId": local_id, "syncState": "pending_create"}

    def sign_local_mail(self, profile, mail_id):
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM notion_mails WHERE id=?", (mail_id,)).fetchone()
            if not row:
                raise ValueError("信件不存在")
            if row["recipient_id"] != profile.get("contact_id"):
                raise ValueError("只有收件人可以签收")
            now = self.now()
            db.execute("UPDATE notion_mails SET received=1,sync_state='pending_sign',updated_at=? WHERE id=?", (now, mail_id))
            db.execute("INSERT INTO notion_outbox(operation,entity_id,payload,next_attempt_at,created_at) VALUES('mail.sign',?,?,?,?)", (mail_id, json.dumps({"localId": mail_id}), now, now))
        return {"signed": True, "syncState": "pending_sign"}

    def due_outbox(self, limit=20):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM notion_outbox WHERE next_attempt_at<=? ORDER BY id LIMIT ?", (self.now(), limit)).fetchall()]

    def complete_outbox(self, task_id, entity_id, notion_page_id=None, operation=None):
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if operation == "mail.create" and notion_page_id:
                db.execute("UPDATE notion_mails SET notion_page_id=?,sync_state='synced',updated_at=? WHERE id=?", (notion_page_id, self.now(), entity_id))
            elif operation == "mail.sign":
                db.execute("UPDATE notion_mails SET sync_state='synced',updated_at=? WHERE id=?", (self.now(), entity_id))
            db.execute("DELETE FROM notion_outbox WHERE id=?", (task_id,))

    def fail_outbox(self, task_id, attempts, error):
        delay = min(1800, 5 * (2 ** min(attempts, 8)))
        next_time = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
        with self.connect() as db:
            db.execute("UPDATE notion_outbox SET attempts=?,next_attempt_at=?,last_error=? WHERE id=?", (attempts, next_time, str(error)[:500], task_id))

    def notion_page_id(self, entity_id):
        with self.connect() as db:
            row = db.execute("SELECT notion_page_id FROM notion_mails WHERE id=?", (entity_id,)).fetchone()
        return row["notion_page_id"] if row else None

    def sync_status(self):
        with self.connect() as db:
            meta = {row["key"]: row["value"] for row in db.execute("SELECT key,value FROM sync_meta").fetchall()}
            pending = db.execute("SELECT COUNT(*) FROM notion_outbox").fetchone()[0]
        return {"contactsLastSync": meta.get("contacts_last_sync", ""), "mailsLastSync": meta.get("mails_last_sync", ""), "pendingWrites": pending}
