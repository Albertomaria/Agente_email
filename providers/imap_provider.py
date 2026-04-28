"""
IMAP provider — fallback for any provider not supported natively.
Uses Python's built-in imaplib (no extra dependencies).

Supports SSL/TLS and STARTTLS connections, username/password or app passwords.
"""
from __future__ import annotations

import asyncio
import email
import email.header
import imaplib
import re
import socket
from collections import defaultdict
from email.utils import parseaddr
from typing import AsyncIterator, Optional

import config
from models import AccountConfig, SenderInfo
from providers.base import EmailProvider
from storage.credentials import CredentialStore
from utils.classifier import classify_sender
from utils.logger import get_logger

logger = get_logger(__name__)


class ImapProvider(EmailProvider):
    """Generic IMAP provider using imaplib."""

    def __init__(self, account: AccountConfig) -> None:
        super().__init__(account)
        self._imap: Optional[imaplib.IMAP4_SSL | imaplib.IMAP4] = None
        self._store = CredentialStore()

    # ── Connection ──────────────────────────────────────────────────────────

    async def connect(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._connect_sync)
        logger.info("IMAP connected: %s @ %s", self.account.email, self.account.imap_host)

    def _connect_sync(self) -> None:
        host = self.account.imap_host or ""
        port = self.account.imap_port or 993
        use_ssl = self.account.imap_use_ssl

        if not host:
            raise ValueError(f"imap_host not set for account {self.account.id}")

        if use_ssl:
            self._imap = imaplib.IMAP4_SSL(host, port)
        else:
            self._imap = imaplib.IMAP4(host, port)
            self._imap.starttls()

        username = self.account.imap_username or self.account.email
        password = self._store.get_password(self.account.id)
        if not password:
            raise RuntimeError(
                f"No password stored for account '{self.account.id}'. "
                "Add the account with a password via the web interface."
            )

        self._imap.login(username, password)

    async def disconnect(self) -> None:
        if self._imap:
            try:
                self._imap.logout()
            except Exception:
                pass
            self._imap = None
        logger.info("IMAP disconnected: %s", self.account.email)

    # ── list_senders ────────────────────────────────────────────────────────

    async def list_senders(self) -> AsyncIterator[SenderInfo]:
        loop = asyncio.get_event_loop()
        logger.info("IMAP: selecting INBOX for %s", self.account.email)
        raw = await loop.run_in_executor(None, self._collect_senders)

        for email_addr, d in raw.items():
            unsub_url, unsub_mailto = _parse_unsubscribe(d.get("unsubscribe"))
            category = classify_sender(
                email_addr,
                d["name"],
                d["subject"],
                has_unsubscribe=bool(d.get("unsubscribe")),
            )
            yield SenderInfo(
                email=email_addr,
                name=d["name"],
                total_count=d["total"],
                unread_count=d["unread"],
                category=category,
                has_unsubscribe=bool(d.get("unsubscribe")),
                unsubscribe_url=unsub_url,
                unsubscribe_mailto=unsub_mailto,
                sample_subject=d["subject"][:120],
                message_ids=d["ids"],
            )

    def _collect_senders(self) -> dict[str, dict]:
        self._imap.select("INBOX", readonly=True)

        # Fetch all message UIDs
        status, data = self._imap.uid("search", None, "ALL")
        if status != "OK":
            return {}

        all_uids = data[0].split()
        logger.info("IMAP: %d messages in INBOX", len(all_uids))

        sender_data: dict[str, dict] = defaultdict(lambda: {
            "name": "",
            "total": 0,
            "unread": 0,
            "ids": [],
            "unsubscribe": None,
            "subject": "",
        })

        # Fetch in batches to avoid huge single requests
        batch_size = config.IMAP_BATCH_SIZE
        for i in range(0, len(all_uids), batch_size):
            chunk = all_uids[i : i + batch_size]
            uid_set = b",".join(chunk)
            status, fetch_data = self._imap.uid(
                "fetch", uid_set, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT LIST-UNSUBSCRIBE)])"
            )
            if status != "OK":
                continue

            for item in fetch_data:
                if not isinstance(item, tuple):
                    continue
                raw_header = item[1]
                flags_str = item[0].decode(errors="replace")
                uid_match = re.search(r"UID (\d+)", flags_str)
                uid = uid_match.group(1) if uid_match else None

                try:
                    msg = email.message_from_bytes(raw_header)
                except Exception:
                    continue

                from_val = _decode_header_value(msg.get("From", ""))
                display_name, email_addr = parseaddr(from_val)
                email_addr = email_addr.lower().strip()
                if not email_addr:
                    continue

                subject = _decode_header_value(msg.get("Subject", ""))
                unsub = msg.get("List-Unsubscribe", "")
                is_unread = r"\Seen" not in flags_str

                d = sender_data[email_addr]
                if uid:
                    d["ids"].append(uid)
                d["name"] = d["name"] or display_name
                d["total"] += 1
                if is_unread:
                    d["unread"] += 1
                if not d["unsubscribe"] and unsub:
                    d["unsubscribe"] = unsub
                if not d["subject"] and subject:
                    d["subject"] = subject

            logger.debug("IMAP batch %d/%d", i + batch_size, len(all_uids))

        return sender_data

    # ── get_emails_by_sender ────────────────────────────────────────────────

    async def get_emails_by_sender(self, sender_email: str) -> list[str]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._search_sender, sender_email)

    def _search_sender(self, sender_email: str) -> list[str]:
        self._imap.select("INBOX", readonly=True)
        status, data = self._imap.uid("search", None, f'FROM "{sender_email}"')
        if status != "OK":
            return []
        return [uid.decode() for uid in data[0].split()]

    # ── delete_emails ───────────────────────────────────────────────────────

    async def delete_emails(self, message_ids: list[str], progress_cb=None) -> int:
        """
        Marks messages as \Deleted and calls EXPUNGE.
        IMAP UIDs are strings; we add \Deleted flag then expunge.
        """
        loop = asyncio.get_event_loop()
        deleted = 0
        batch_size = config.IMAP_BATCH_SIZE

        for i in range(0, len(message_ids), batch_size):
            chunk = message_ids[i : i + batch_size]
            count = await loop.run_in_executor(None, self._delete_batch, chunk)
            deleted += count
            if progress_cb:
                await progress_cb(min(i + batch_size, len(message_ids)), len(message_ids))

        return deleted

    def _delete_batch(self, uids: list[str]) -> int:
        try:
            self._imap.select("INBOX")
            uid_set = ",".join(uids)
            self._imap.uid("store", uid_set, "+FLAGS", r"(\Deleted)")
            self._imap.expunge()
            return len(uids)
        except Exception as e:
            logger.error("IMAP delete batch error: %s", e)
            return 0

    # ── get_unsubscribe_header ──────────────────────────────────────────────

    async def get_unsubscribe_header(self, message_id: str) -> Optional[str]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_header, message_id)

    def _fetch_header(self, uid: str) -> Optional[str]:
        try:
            self._imap.select("INBOX", readonly=True)
            status, data = self._imap.uid(
                "fetch", uid, "(BODY.PEEK[HEADER.FIELDS (LIST-UNSUBSCRIBE)])"
            )
            if status != "OK":
                return None
            for item in data:
                if isinstance(item, tuple):
                    msg = email.message_from_bytes(item[1])
                    val = msg.get("List-Unsubscribe")
                    if val:
                        return val
        except Exception as e:
            logger.debug("IMAP get_unsubscribe_header error: %s", e)
        return None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _decode_header_value(value: str) -> str:
    """Decode RFC 2047-encoded header values."""
    parts = email.header.decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _parse_unsubscribe(header: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not header:
        return None, None
    urls = re.findall(r"<([^>]+)>", header)
    http_url = next((u for u in urls if u.startswith("http")), None)
    mailto = next((u for u in urls if u.startswith("mailto:")), None)
    return http_url, mailto
