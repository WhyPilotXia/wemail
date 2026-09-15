import json
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import config


class Storage:
    def __init__(self, path=config.DATABASE_PATH):
        self.path = path
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
              phone_masked TEXT NOT NULL DEFAULT '',
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
            "phone_masked": 32, "contact_id": 100, "contact_name": 200,
            "address": 300, "postcode": 32,
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
            item["allowNote"] = bool(item.pop("allow_note"))
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
                "INSERT INTO events(id,type,title,description,deadline,participant_limit,allow_note,status,owner_name,owner_openid,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (event_id, "signup" if data.get("type") == "signup" else "lottery", str(data["title"])[:80], str(data.get("description") or "")[:500], deadline, max(0, int(data.get("limit") or 0)), int(bool(data.get("allowNote"))), "open", profile.get("contact_name") or profile.get("nickname") or "微信用户", openid, now, now),
            )
        return {"_id": event_id}

    def join_event(self, openid, profile, event_id, note=""):
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
                "INSERT INTO event_entries(id,event_id,openid,name,avatar_data,note,created_at) VALUES(?,?,?,?,?,?,?)",
                (secrets.token_hex(16), event_id, openid, profile.get("contact_name") or profile.get("nickname") or "微信用户", profile.get("avatar_data") or "", str(note or "")[:500], self.now()),
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
                db.execute("""INSERT INTO notion_contacts(id,name,phone,email,address1,postcode1,address2,postcode2,qq,synced_at)
                  VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,phone=excluded.phone,email=excluded.email,address1=excluded.address1,postcode1=excluded.postcode1,address2=excluded.address2,postcode2=excluded.postcode2,qq=excluded.qq,synced_at=excluded.synced_at""",
                  (contact_id, item.get("name", ""), item.get("phone", ""), item.get("email", ""), item.get("address1", ""), item.get("postcode1", ""), item.get("address2", ""), item.get("postcode2", ""), item.get("qq", ""), now))
            if incoming:
                placeholders = ",".join("?" for _ in incoming)
                db.execute(f"DELETE FROM notion_contacts WHERE id NOT IN ({placeholders})", tuple(incoming))
            db.execute("INSERT INTO sync_meta(key,value,updated_at) VALUES('contacts_last_sync',?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at", (now, now))

    def list_notion_contacts(self, profile=None, reveal_phone=False):
        profile = profile or {}
        with self.connect() as db:
            rows = db.execute("SELECT * FROM notion_contacts ORDER BY name COLLATE NOCASE").fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item.pop("synced_at", None)
            if not reveal_phone:
                phone = "".join(char for char in item["phone"] if char.isdigit())
                item["phone"] = f"{phone[:3]}****{phone[-4:]}" if len(phone) >= 7 else ""
            item["isMe"] = profile.get("contact_id") == item["id"]
            result.append(item)
        return result

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
            raise ValueError("请先在‘我的’中绑定手机号并匹配联系人")
        if data.get("senderId") != profile["contact_id"]:
            raise ValueError("寄件人必须是当前登录用户")
        with self.connect() as db:
            if not db.execute("SELECT 1 FROM notion_contacts WHERE id=?", (data.get("recipientId"),)).fetchone():
                raise ValueError("收件人不存在或通讯录尚未同步")
            local_id = "local-" + secrets.token_hex(12)
            now = self.now()
            payload = {"localId": local_id, "senderId": profile["contact_id"], "recipientId": data.get("recipientId"), "sendDate": data.get("sendDate"), "mailType": str(data.get("mailType") or "平信")[:100], "trackingNo": str(data.get("trackingNo") or "")[:100], "title": str(data.get("title") or "由 WeMail 小程序提交")[:100]}
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
