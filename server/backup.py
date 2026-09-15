import sqlite3
from datetime import datetime
from pathlib import Path

import config


source = sqlite3.connect(config.DATABASE_PATH)
backup_dir = Path(__file__).with_name("backups")
backup_dir.mkdir(exist_ok=True)
target_path = backup_dir / f"wemail-{datetime.now():%Y%m%d-%H%M%S}.db"
target = sqlite3.connect(target_path)
with target:
    source.backup(target)
target.close()
source.close()
print(target_path)
