import argparse
import json
import sqlite3
from pathlib import Path

import config
from storage import Storage


def load_rows(path):
    text = Path(path).read_text(encoding="utf-8-sig").strip()
    if not text:
        return []
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def date_value(value):
    if isinstance(value, dict):
        return value.get("$date") or value.get("date") or ""
    return str(value or "")


def main():
    parser = argparse.ArgumentParser(description="Import CloudBase JSON/JSONL into WeMail SQLite")
    parser.add_argument("--users")
    parser.add_argument("--events")
    parser.add_argument("--entries")
    parser.add_argument("--reading")
    args = parser.parse_args()
    storage = Storage()
    counts = {}

    if args.users:
        rows = load_rows(args.users)
        for row in rows:
            openid = row.get("openid") or row.get("_openid")
            if not openid:
                continue
            storage.save_profile(openid, {
                "nickname": row.get("nickname"), "avatar_data": row.get("avatarUrl"),
                "phone_number": row.get("phoneNumber"), "phone_masked": row.get("phoneMasked"),
                "contact_id": row.get("contactId"), "contact_name": row.get("contactName"),
                "address": row.get("address"), "postcode": row.get("postcode"),
            })
        counts["users"] = len(rows)

    with storage.connect() as db:
        if args.events:
            rows = load_rows(args.events)
            for row in rows:
                db.execute("""INSERT OR REPLACE INTO events(id,type,title,description,deadline,participant_limit,allow_note,status,participant_count,owner_name,owner_openid,winner_name,winner_openid,drawn_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    row.get("_id"), row.get("type", "lottery"), row.get("title", ""), row.get("description", ""),
                    date_value(row.get("deadline")), int(row.get("limit") or 0), int(bool(row.get("allowNote"))), row.get("status", "open"),
                    int(row.get("participantCount") or 0), row.get("ownerName", ""), row.get("ownerOpenid", ""), row.get("winnerName", ""),
                    row.get("winnerOpenid", ""), date_value(row.get("drawnAt")) or None, date_value(row.get("createdAt")) or storage.now(), date_value(row.get("updatedAt")) or storage.now(),
                ))
            counts["events"] = len(rows)
        if args.entries:
            rows = load_rows(args.entries)
            for row in rows:
                db.execute("""INSERT OR REPLACE INTO event_entries(id,event_id,openid,name,avatar_data,note,created_at) VALUES(?,?,?,?,?,?,?)""", (
                    row.get("_id"), row.get("eventId"), row.get("openid") or row.get("_openid"), row.get("name", "微信用户"), row.get("avatarUrl", ""), row.get("note", ""), date_value(row.get("createdAt")) or storage.now(),
                ))
            counts["event_entries"] = len(rows)
        if args.reading:
            rows = load_rows(args.reading)
            for row in rows:
                openid = row.get("openid") or row.get("_openid")
                db.execute("""INSERT OR REPLACE INTO reading_progress(id,openid,book,chapter_index,chapter_title,completed,progress,updated_at) VALUES(?,?,?,?,?,?,?,?)""", (
                    row.get("_id"), openid, row.get("book", ""), int(row.get("chapterIndex") or 0), row.get("chapterTitle", ""), int(bool(row.get("completed"))), float(row.get("progress") or 0), date_value(row.get("updatedAt")) or storage.now(),
                ))
            counts["reading_progress"] = len(rows)
    print(json.dumps(counts, ensure_ascii=False))


if __name__ == "__main__":
    main()
