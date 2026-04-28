"""
Microsoft provider — uses Microsoft Graph API with MSAL OAuth 2.0.

Supports Outlook.com, Hotmail, Live.com (tenant=consumers) and
Office 365 / Exchange Online (tenant=<tenant-id>).

Required setup: register an Azure app and set MICROSOFT_CLIENT_ID
in your environment (or .env file). See README_Microsoft_Setup.md.
"""
from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import AsyncIterator, Optional

import msal
import requests

import config
from models import AccountConfig, SenderInfo
from providers.base import EmailProvider
from utils.classifier import classify_sender
from utils.logger import get_logger

logger = get_logger(__name__)

GRAPH = config.MICROSOFT_GRAPH_BASE
_TOKEN_CACHE_DIR = config.MICROSOFT_TOKEN_DIR


class MicrosoftProvider(EmailProvider):
    """Microsoft Graph API provider."""

    def __init__(self, account: AccountConfig) -> None:
        super().__init__(account)
        self._access_token: Optional[str] = None
        self._session: Optional[requests.Session] = None
        self._cache_path = _TOKEN_CACHE_DIR / f"{account.id}.json"

    # ── Connection ──────────────────────────────────────────────────────────

    async def connect(self) -> None:
        loop = asyncio.get_event_loop()
        self._access_token = await loop.run_in_executor(None, self._acquire_token)
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        })
        logger.info("Microsoft connected: %s", self.account.email)

    async def disconnect(self) -> None:
        if self._session:
            self._session.close()
            self._session = None
        logger.info("Microsoft disconnected: %s", self.account.email)

    def _acquire_token(self) -> str:
        client_id = config.MICROSOFT_CLIENT_ID
        if not client_id:
            raise RuntimeError(
                "MICROSOFT_CLIENT_ID is not set. "
                "See README_Microsoft_Setup.md for instructions."
            )

        cache = msal.SerializableTokenCache()
        if self._cache_path.exists():
            cache.deserialize(self._cache_path.read_text())

        app = msal.PublicClientApplication(
            client_id=client_id,
            authority=config.MICROSOFT_AUTHORITY,
            token_cache=cache,
        )

        accounts = app.get_accounts()
        result = None
        if accounts:
            result = app.acquire_token_silent(config.MICROSOFT_SCOPES, account=accounts[0])

        if not result:
            # Device code flow — user visits a URL and enters a code
            flow = app.initiate_device_flow(scopes=config.MICROSOFT_SCOPES)
            if "user_code" not in flow:
                raise RuntimeError(f"Failed to create device flow: {flow}")
            print("\n" + flow["message"])   # printed to console intentionally
            result = app.acquire_token_by_device_flow(flow)

        if "access_token" not in result:
            raise RuntimeError(f"Token acquisition failed: {result.get('error_description')}")

        # Persist cache
        if cache.has_state_changed:
            self._cache_path.write_text(cache.serialize())

        return result["access_token"]

    def _refresh_headers(self) -> None:
        if self._session:
            self._session.headers["Authorization"] = f"Bearer {self._access_token}"

    # ── list_senders ────────────────────────────────────────────────────────

    async def list_senders(self) -> AsyncIterator[SenderInfo]:
        loop = asyncio.get_event_loop()
        logger.info("Fetching messages for %s …", self.account.email)
        raw_senders = await loop.run_in_executor(None, self._collect_senders)

        for email_addr, d in raw_senders.items():
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
        """
        Pages through all messages using Graph API, groups by sender.
        Requests only the fields we need to minimise data transfer.
        """
        sender_data: dict[str, dict] = defaultdict(lambda: {
            "name": "",
            "total": 0,
            "unread": 0,
            "ids": [],
            "unsubscribe": None,
            "subject": "",
        })

        select = "id,from,subject,isRead,internetMessageHeaders"
        url = (
            f"{GRAPH}/me/messages"
            f"?$select={select}"
            f"&$top=999"
        )

        page = 0
        while url:
            resp = self._session.get(url)
            if resp.status_code == 401:
                # Try token refresh once
                self._access_token = self._acquire_token()
                self._refresh_headers()
                resp = self._session.get(url)
            resp.raise_for_status()
            data = resp.json()

            for msg in data.get("value", []):
                from_obj = msg.get("from", {}).get("emailAddress", {})
                email_addr = from_obj.get("address", "").lower().strip()
                display_name = from_obj.get("name", "").strip()
                if not email_addr:
                    continue

                d = sender_data[email_addr]
                d["name"] = d["name"] or display_name
                d["total"] += 1
                if not msg.get("isRead", True):
                    d["unread"] += 1
                d["ids"].append(msg["id"])

                if not d["subject"] and msg.get("subject"):
                    d["subject"] = msg["subject"]

                if not d["unsubscribe"]:
                    headers = msg.get("internetMessageHeaders") or []
                    for h in headers:
                        if h.get("name", "").lower() == "list-unsubscribe":
                            d["unsubscribe"] = h.get("value")
                            break

            page += 1
            logger.debug("Page %d — %d messages so far", page, sum(v["total"] for v in sender_data.values()))
            url = data.get("@odata.nextLink")

        return sender_data

    # ── get_emails_by_sender ────────────────────────────────────────────────

    async def get_emails_by_sender(self, sender_email: str) -> list[str]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._search_by_sender, sender_email)

    def _search_by_sender(self, sender_email: str) -> list[str]:
        ids = []
        url = (
            f"{GRAPH}/me/messages"
            f"?$filter=from/emailAddress/address eq '{sender_email}'"
            f"&$select=id"
            f"&$top=999"
        )
        while url:
            resp = self._session.get(url)
            resp.raise_for_status()
            data = resp.json()
            ids.extend(m["id"] for m in data.get("value", []))
            url = data.get("@odata.nextLink")
        return ids

    # ── delete_emails ───────────────────────────────────────────────────────

    async def delete_emails(self, message_ids: list[str], progress_cb=None) -> int:
        """
        Uses Graph batch API (max 20 requests per batch call).
        Each request permanently deletes one message.
        """
        loop = asyncio.get_event_loop()
        deleted = 0
        batch_size = config.MICROSOFT_BATCH_SIZE

        for i in range(0, len(message_ids), batch_size):
            chunk = message_ids[i : i + batch_size]
            count = await loop.run_in_executor(None, self._batch_delete, chunk)
            deleted += count
            if progress_cb:
                await progress_cb(min(i + batch_size, len(message_ids)), len(message_ids))

        return deleted

    def _batch_delete(self, message_ids: list[str]) -> int:
        """Send one Graph $batch request to delete up to 20 messages."""
        requests_body = [
            {
                "id": str(idx),
                "method": "DELETE",
                "url": f"/me/messages/{msg_id}",
            }
            for idx, msg_id in enumerate(message_ids)
        ]
        resp = self._session.post(
            f"{GRAPH}/$batch",
            json={"requests": requests_body},
        )
        resp.raise_for_status()
        responses = resp.json().get("responses", [])
        ok = sum(1 for r in responses if r.get("status") in (200, 204))
        failed = len(responses) - ok
        if failed:
            logger.warning("%d deletes failed in batch", failed)
        return ok

    # ── get_unsubscribe_header ──────────────────────────────────────────────

    async def get_unsubscribe_header(self, message_id: str) -> Optional[str]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_unsubscribe, message_id)

    def _fetch_unsubscribe(self, message_id: str) -> Optional[str]:
        try:
            resp = self._session.get(
                f"{GRAPH}/me/messages/{message_id}",
                params={"$select": "internetMessageHeaders"},
            )
            resp.raise_for_status()
            headers = resp.json().get("internetMessageHeaders") or []
            for h in headers:
                if h.get("name", "").lower() == "list-unsubscribe":
                    return h.get("value")
        except Exception as e:
            logger.debug("get_unsubscribe_header error: %s", e)
        return None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_unsubscribe(header: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not header:
        return None, None
    urls = re.findall(r"<([^>]+)>", header)
    http_url = next((u for u in urls if u.startswith("http")), None)
    mailto = next((u for u in urls if u.startswith("mailto:")), None)
    return http_url, mailto
