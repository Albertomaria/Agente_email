"""
Gmail provider — uses Gmail API v1 with OAuth 2.0.

Required setup: place gmail_credentials.json (downloaded from Google Cloud Console)
in the project root. See README_Gmail_Setup.md for instructions.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import time
import threading
from collections import defaultdict
from pathlib import Path
from typing import AsyncIterator, Optional
from urllib.parse import urlparse, parse_qs
from wsgiref.simple_server import WSGIRequestHandler, make_server

import httplib2
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import config
from models import AccountConfig, SenderInfo, EmailCategory
from providers.base import EmailProvider
from utils.classifier import classify_sender
from utils.logger import get_logger

logger = get_logger(__name__)


class GmailProvider(EmailProvider):
    """Gmail API provider with full OAuth 2.0 support."""

    def __init__(self, account: AccountConfig) -> None:
        super().__init__(account)
        self._service = None
        self._creds: Optional[Credentials] = None
        self._token_path = config.GMAIL_TOKEN_DIR / f"{account.id}.json"

    # ── Connection ──────────────────────────────────────────────────────────

    async def connect(self) -> None:
        loop = asyncio.get_event_loop()
        self._creds = await loop.run_in_executor(None, self._load_or_refresh_creds)
        self._service = build("gmail", "v1", credentials=self._creds, cache_discovery=False)
        logger.info("Gmail connected: %s", self.account.email)

    async def disconnect(self) -> None:
        self._service = None
        logger.info("Gmail disconnected: %s", self.account.email)

    def _load_or_refresh_creds(self) -> Credentials:
        creds = None
        if self._token_path.exists():
            creds = Credentials.from_authorized_user_file(
                str(self._token_path), config.GMAIL_SCOPES
            )

        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            self._save_token(creds)
            return creds

        # Full OAuth flow
        credentials_file = str(config.GMAIL_CREDENTIALS_FILE)
        flow = InstalledAppFlow.from_client_secrets_file(credentials_file, config.GMAIL_SCOPES)
        creds = flow.run_local_server(
            port=0,  # 0 = OS sceglie una porta libera automaticamente
            prompt="consent",
            open_browser=True,
        )
        self._save_token(creds)
        return creds

    def _save_token(self, creds: Credentials) -> None:
        self._token_path.write_text(creds.to_json())
        logger.debug("Gmail token saved: %s", self._token_path)

    # ── list_senders ────────────────────────────────────────────────────────

    async def list_senders(self) -> AsyncIterator[SenderInfo]:
        """
        Fetches all message IDs, retrieves minimal metadata in batches,
        groups by sender, then enriches each sender with unread count
        and List-Unsubscribe detection.
        """
        loop = asyncio.get_event_loop()

        # Step 1: collect all message IDs
        logger.info("Fetching message list for %s …", self.account.email)
        all_ids = await loop.run_in_executor(None, self._fetch_all_message_ids)
        logger.info("Total messages: %d", len(all_ids))

        # Step 2: fetch metadata in batches (From, Subject, List-Unsubscribe)
        logger.info("Fetching metadata in batches …")
        meta_map = await loop.run_in_executor(None, self._fetch_metadata_batch, all_ids)

        # Step 3: group by sender
        sender_data: dict[str, dict] = defaultdict(lambda: {
            "name": "",
            "total": 0,
            "unread": 0,
            "ids": [],
            "unsubscribe": None,
            "subject": "",
        })

        for msg_id, meta in meta_map.items():
            from_addr = meta.get("from", "").strip()
            email_addr, display_name = _parse_from(from_addr)
            if not email_addr:
                continue

            key = email_addr.lower()
            d = sender_data[key]
            d["name"] = d["name"] or display_name
            d["total"] += 1
            if not meta.get("read", True):
                d["unread"] += 1
            d["ids"].append(msg_id)
            if not d["unsubscribe"] and meta.get("unsubscribe"):
                d["unsubscribe"] = meta["unsubscribe"]
            if not d["subject"] and meta.get("subject"):
                d["subject"] = meta["subject"]

        # Step 4: yield SenderInfo objects
        for email_addr, d in sender_data.items():
            unsub_url, unsub_mailto = _parse_unsubscribe(d["unsubscribe"])
            category = classify_sender(
                email_addr,
                d["name"],
                d["subject"],
                has_unsubscribe=bool(d["unsubscribe"]),
            )
            yield SenderInfo(
                email=email_addr,
                name=d["name"],
                total_count=d["total"],
                unread_count=d["unread"],
                category=category,
                has_unsubscribe=bool(d["unsubscribe"]),
                unsubscribe_url=unsub_url,
                unsubscribe_mailto=unsub_mailto,
                sample_subject=d["subject"][:120],
                message_ids=d["ids"],
            )

    def _fetch_all_message_ids(self) -> list[str]:
        """Pages through messages.list to collect all IDs including Spam and Trash."""
        ids = []
        page_token = None
        while True:
            kwargs = {
                "userId": "me",
                "maxResults": 500,
                "includeSpamTrash": False,  # spam e cestino si svuotano direttamente da Gmail
            }
            if page_token:
                kwargs["pageToken"] = page_token
            resp = self._service.users().messages().list(**kwargs).execute()
            msgs = resp.get("messages", [])
            ids.extend(m["id"] for m in msgs)
            page_token = resp.get("nextPageToken")
            logger.debug("Fetched %d IDs so far…", len(ids))
            if not page_token:
                break
        logger.info("Total message IDs fetched: %d", len(ids))
        return ids

    def _fetch_metadata_batch(self, message_ids: list[str]) -> dict[str, dict]:
        """
        Fetch From / Subject / List-Unsubscribe / labels for all messages
        using Gmail batch HTTP requests, with retry on rate-limit errors.
        """
        results = {}
        batch_size = config.GMAIL_BATCH_SIZE
        max_retries = 3

        def _callback(request_id, response, exception):
            if exception:
                logger.debug("Batch item error for %s: %s", request_id, exception)
                return
            headers = {
                h["name"].lower(): h["value"]
                for h in response.get("payload", {}).get("headers", [])
            }
            labels = response.get("labelIds", [])
            results[request_id] = {
                "from": headers.get("from", ""),
                "subject": headers.get("subject", ""),
                "unsubscribe": headers.get("list-unsubscribe", ""),
                "read": "UNREAD" not in labels,
            }

        total = len(message_ids)
        for i in range(0, total, batch_size):
            chunk = message_ids[i : i + batch_size]
            for attempt in range(max_retries):
                try:
                    batch = self._service.new_batch_http_request(callback=_callback)
                    for msg_id in chunk:
                        batch.add(
                            self._service.users().messages().get(
                                userId="me",
                                id=msg_id,
                                format="metadata",
                                metadataHeaders=["From", "Subject", "List-Unsubscribe"],
                            ),
                            request_id=msg_id,
                        )
                    batch.execute()
                    break  # success
                except Exception as e:
                    wait = 2 ** attempt  # backoff: 1s, 2s, 4s
                    logger.warning(
                        "Batch %d/%d failed (attempt %d/%d): %s — retry in %ds",
                        i + batch_size, total, attempt + 1, max_retries, e, wait,
                    )
                    time.sleep(wait)
            else:
                logger.error("Batch %d/%d failed after %d attempts, skipping.", i, total, max_retries)

            # Piccola pausa tra batch per rispettare i rate limit Gmail (250 QPS)
            time.sleep(0.1)
            logger.debug("Batch %d/%d processed (%d results so far)", i + batch_size, total, len(results))

        logger.info("Metadata fetch complete: %d/%d messages processed", len(results), total)
        return results

    # ── get_emails_by_sender ────────────────────────────────────────────────

    async def get_emails_by_sender(self, sender_email: str) -> list[str]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._search_by_sender, sender_email)

    def _search_by_sender(self, sender_email: str) -> list[str]:
        ids = []
        page_token = None
        query = f"from:{sender_email}"
        while True:
            kwargs = {"userId": "me", "q": query, "maxResults": 500}
            if page_token:
                kwargs["pageToken"] = page_token
            resp = self._service.users().messages().list(**kwargs).execute()
            ids.extend(m["id"] for m in resp.get("messages", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return ids

    # ── delete_emails ───────────────────────────────────────────────────────

    async def delete_emails(self, message_ids: list[str], progress_cb=None) -> int:
        """
        Permanently deletes messages using batchDelete (max 1000 per call).
        """
        loop = asyncio.get_event_loop()
        deleted = 0
        chunk_size = 1000  # Gmail batchDelete limit
        for i in range(0, len(message_ids), chunk_size):
            chunk = message_ids[i : i + chunk_size]
            await loop.run_in_executor(
                None,
                lambda c=chunk: self._service.users()
                .messages()
                .batchDelete(userId="me", body={"ids": c})
                .execute(),
            )
            deleted += len(chunk)
            logger.info("batchDelete OK: %d emails deleted", len(chunk))
            if progress_cb:
                await progress_cb(min(i + chunk_size, len(message_ids)), len(message_ids))
        return deleted

    # ── get_preview ─────────────────────────────────────────────────────────

    async def get_preview(self, sender_email: str, limit: int = 5) -> list[dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_preview, sender_email, limit)

    def _fetch_preview(self, sender_email: str, limit: int) -> list[dict]:
        try:
            resp = self._service.users().messages().list(
                userId="me",
                q=f"from:{sender_email}",
                maxResults=limit,
            ).execute()
            previews = []
            for m in resp.get("messages", [])[:limit]:
                msg = self._service.users().messages().get(
                    userId="me",
                    id=m["id"],
                    format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                ).execute()
                headers = {
                    h["name"].lower(): h["value"]
                    for h in msg.get("payload", {}).get("headers", [])
                }
                previews.append({
                    "subject": headers.get("subject", "(no subject)"),
                    "date": headers.get("date", ""),
                    "snippet": msg.get("snippet", ""),
                })
            return previews
        except Exception as e:
            logger.debug("get_preview error: %s", e)
            return []

    # ── get_unsubscribe_header ──────────────────────────────────────────────

    async def get_unsubscribe_header(self, message_id: str) -> Optional[str]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._get_header, message_id)

    def _get_header(self, message_id: str) -> Optional[str]:
        try:
            resp = (
                self._service.users()
                .messages()
                .get(
                    userId="me",
                    id=message_id,
                    format="metadata",
                    metadataHeaders=["List-Unsubscribe"],
                )
                .execute()
            )
            for h in resp.get("payload", {}).get("headers", []):
                if h["name"].lower() == "list-unsubscribe":
                    return h["value"]
        except HttpError:
            pass
        return None


# ── Helpers ────────────────────────────────────────────────────────────────────

_FROM_RE = re.compile(r'^(?:"?([^"<]*)"?\s*)?<?([^>@\s]+@[^>\s]+)>?$')


def _parse_from(from_str: str) -> tuple[str, str]:
    """Returns (email_addr, display_name) from a From header value."""
    m = _FROM_RE.match(from_str.strip())
    if m:
        name = (m.group(1) or "").strip().strip('"')
        email = m.group(2).strip().lower()
        return email, name
    # Fallback: if it looks like a bare email
    if "@" in from_str:
        return from_str.strip().lower(), ""
    return "", ""


def _parse_unsubscribe(header: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Parse List-Unsubscribe header into (http_url, mailto).
    Header format: <https://...>, <mailto:...>
    """
    if not header:
        return None, None
    urls = re.findall(r"<([^>]+)>", header)
    http_url = next((u for u in urls if u.startswith("http")), None)
    mailto = next((u for u in urls if u.startswith("mailto:")), None)
    return http_url, mailto
