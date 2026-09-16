import os
from pathlib import Path


def load_dotenv(path=None):
    target = Path(path or Path(__file__).with_name(".env"))
    if not target.exists():
        return
    for raw in target.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_dotenv()

HOST = os.getenv("UDP_HOST", "0.0.0.0")
PORT = int(os.getenv("UDP_PORT", "18500"))
DATABASE_PATH = os.getenv("DATABASE_PATH", str(Path(__file__).with_name("wemail.db")))
WECHAT_APP_ID = os.getenv("WECHAT_APP_ID", "wx740d98c545a2eed0")
WECHAT_APP_SECRET = os.getenv("WECHAT_APP_SECRET", "")
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")
NOTION_VERSION = os.getenv("NOTION_VERSION", "2025-09-03")
CONTACT_SOURCE = os.getenv("CONTACT_DATA_SOURCE_ID", "31e70d82-c716-8034-b23d-000ba20878af")
MAIL_SOURCE = os.getenv("RAS_DATA_SOURCE_ID", "31e70d82-c716-80ba-b4d2-000b1892f62c")
MAIL_DATABASE = os.getenv("RAS_DATABASE_ID", "31e70d82-c716-80d3-9f2d-e73dcc4033b3")
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "30"))
MAX_DATAGRAM = int(os.getenv("MAX_DATAGRAM", "65507"))
RESPONSE_CHUNK_SIZE = max(512, min(1200, int(os.getenv("RESPONSE_CHUNK_SIZE", "900"))))
MAX_REQUEST_BYTES = int(os.getenv("MAX_REQUEST_BYTES", str(1024 * 1024)))
NOTION_TIMEOUT_SECONDS = int(os.getenv("NOTION_TIMEOUT_SECONDS", "12"))
NOTION_READ_ATTEMPTS = max(1, int(os.getenv("NOTION_READ_ATTEMPTS", "4")))
NOTION_RETRY_BASE_SECONDS = max(0.1, float(os.getenv("NOTION_RETRY_BASE_SECONDS", "1")))
NOTION_SYNC_INTERVAL_SECONDS = int(os.getenv("NOTION_SYNC_INTERVAL_SECONDS", "300"))
NOTION_OUTBOX_POLL_SECONDS = int(os.getenv("NOTION_OUTBOX_POLL_SECONDS", "2"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.getenv("LOG_FILE", str(Path(__file__).with_name("logs") / "wemail-server.log"))


def validate():
    missing = []
    if not WECHAT_APP_SECRET or WECHAT_APP_SECRET == "CHANGE_ME":
        missing.append("WECHAT_APP_SECRET")
    if not NOTION_TOKEN:
        missing.append("NOTION_TOKEN")
    return missing
