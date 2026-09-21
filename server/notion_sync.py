import json
import logging
import threading
import time

import config
import notion_api

LOGGER = logging.getLogger("wemail.sync")


class NotionSyncWorker:
    def __init__(self, storage):
        self.storage = storage
        self.stop_event = threading.Event()
        self.pull_thread = threading.Thread(target=self.run_pull, name="notion-pull", daemon=True)
        self.push_thread = threading.Thread(target=self.run_push, name="notion-push", daemon=True)

    def start(self):
        self.pull_thread.start()
        self.push_thread.start()
        LOGGER.info("notion sync workers started pull_interval=%ds outbox_poll=%ds", config.NOTION_SYNC_INTERVAL_SECONDS, config.NOTION_OUTBOX_POLL_SECONDS)

    def pull(self):
        started = time.monotonic()
        contacts = notion_api.fetch_contacts()
        self.storage.replace_notion_contacts(contacts)
        mails = notion_api.fetch_mails()
        self.storage.replace_notion_mails(mails)
        LOGGER.info("notion pull ok contacts=%d mails=%d elapsed_ms=%d", len(contacts), len(mails), int((time.monotonic() - started) * 1000))

    def push_task(self, task):
        payload = json.loads(task["payload"])
        if task["operation"] == "mail.create":
            page_id = notion_api.create_mail_remote(payload)
            self.storage.complete_outbox(task["id"], task["entity_id"], page_id, task["operation"])
        elif task["operation"] == "mail.sign":
            page_id = self.storage.notion_page_id(task["entity_id"])
            if not page_id:
                raise RuntimeError("信件尚未完成 Notion 创建，稍后重试")
            notion_api.sign_mail_remote(page_id)
            self.storage.complete_outbox(task["id"], task["entity_id"], operation=task["operation"])
        elif task["operation"] == "contact.update":
            properties = notion_api.contact_update_properties(payload["fields"])
            if not properties:
                raise RuntimeError("联系人更新负载为空")
            notion_api.update_contact_remote(payload["contactId"], properties)
            self.storage.complete_outbox(task["id"], task["entity_id"], operation=task["operation"])
        else:
            raise RuntimeError(f"未知同步操作 {task['operation']}")
        LOGGER.info("notion push ok task=%d operation=%s entity=%s", task["id"], task["operation"], task["entity_id"])

    def process_outbox(self):
        for task in self.storage.due_outbox():
            try:
                self.push_task(task)
            except Exception as error:
                attempts = int(task["attempts"]) + 1
                self.storage.fail_outbox(task["id"], attempts, error)
                LOGGER.warning("notion push failed task=%d operation=%s attempt=%d error=%s", task["id"], task["operation"], attempts, error)

    def run_pull(self):
        while not self.stop_event.is_set():
            try:
                self.pull()
            except Exception:
                LOGGER.exception("notion pull failed; local cache remains available")
            self.stop_event.wait(config.NOTION_SYNC_INTERVAL_SECONDS)

    def run_push(self):
        while not self.stop_event.is_set():
            self.process_outbox()
            self.stop_event.wait(config.NOTION_OUTBOX_POLL_SECONDS)
