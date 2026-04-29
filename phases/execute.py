"""
Phase 3 – EXECUTE

Takes the approved SenderAction list from the database and executes them:
  - DELETE: bulk-delete all messages from that sender
  - UNSUBSCRIBE_DELETE: attempt HTTP/mailto unsubscribe first, then delete
  - KEEP: skip

All results are logged to the execution_log table.

Usage (async generator):
    async for event in ExecutePhase(account).run():
        print(event)
"""
from __future__ import annotations

import asyncio
import re
from typing import AsyncIterator, Optional

import httpx

from models import AccountConfig, ActionType, ExecutionResult, ProgressEvent, SenderAction
from providers import get_provider
from storage.database import Database
from utils.logger import get_logger

logger = get_logger(__name__)


class ExecutePhase:
    def __init__(self, account: AccountConfig) -> None:
        self.account = account
        self.db = Database()

    async def run(self) -> AsyncIterator[ProgressEvent]:
        """
        Async generator. Yields ProgressEvent objects.
        """
        account_id = self.account.id
        actions = self.db.get_actions(account_id)
        actionable = [a for a in actions if a.action != ActionType.KEEP]

        if not actionable:
            yield ProgressEvent(
                type="done",
                message="No actions to execute (nothing was marked for deletion).",
            )
            return

        yield ProgressEvent(
            type="progress",
            message=f"Connecting to execute {len(actionable)} actions…",
        )

        provider = get_provider(self.account)
        try:
            await provider.connect()
        except Exception as exc:
            logger.exception("Execute: failed to connect")
            yield ProgressEvent(type="error", message=f"Connection failed: {exc}")
            return

        total_deleted = 0

        try:
            for idx, action in enumerate(actionable, 1):
                sender = self.db.get_senders(account_id)
                sender_map = {s.email: s for s in sender}
                sender_info = sender_map.get(action.sender_email)

                yield ProgressEvent(
                    type="progress",
                    message=f"[{idx}/{len(actionable)}] {action.action.value}: {action.sender_email}",
                    current=idx,
                    total=len(actionable),
                )

                result = ExecutionResult(
                    account_id=account_id,
                    sender_email=action.sender_email,
                    action=action.action,
                )

                try:
                    # ── Unsubscribe step ────────────────────────────────
                    if action.action == ActionType.UNSUBSCRIBE_DELETE and sender_info:
                        unsubbed = await _try_unsubscribe(
                            sender_info.unsubscribe_url,
                            sender_info.unsubscribe_mailto,
                        )
                        result.unsubscribed = unsubbed
                        if unsubbed:
                            logger.info("Unsubscribed from %s", action.sender_email)
                        else:
                            logger.warning("Could not unsubscribe from %s", action.sender_email)

                    # ── Delete step ─────────────────────────────────────
                    # Only use the cached IDs from analysis — never re-query
                    # Gmail as a fallback: a fallback search can silently match
                    # far more messages than expected (special chars, no quoting,
                    # includeSpamTrash not set) and is the root cause of mass
                    # accidental deletions.
                    message_ids = (
                        sender_info.message_ids
                        if sender_info and sender_info.message_ids
                        else []
                    )

                    if not message_ids:
                        logger.warning(
                            "No cached message IDs for %s — skipping (re-run analysis first)",
                            action.sender_email,
                        )
                        result.error = "No cached IDs — skipped. Re-run analysis."
                        result.success = False
                    else:
                        deleted = await provider.delete_emails(message_ids)
                        result.emails_deleted = deleted
                        total_deleted += deleted
                        logger.info(
                            "Deleted %d/%d emails from %s",
                            deleted,
                            len(message_ids),
                            action.sender_email,
                        )

                except Exception as exc:
                    logger.exception("Execute error for %s", action.sender_email)
                    result.success = False
                    result.error = str(exc)

                self.db.log_execution(result)

                yield ProgressEvent(
                    type="progress",
                    message=(
                        f"Done: {action.sender_email} — "
                        f"{result.emails_deleted} deleted"
                        + (" ✓ unsubscribed" if result.unsubscribed else "")
                    ),
                    current=idx,
                    total=len(actionable),
                    data=result.model_dump(),
                )

        finally:
            await provider.disconnect()

        yield ProgressEvent(
            type="done",
            message=f"Execution complete: {total_deleted} emails deleted across {len(actionable)} senders.",
            current=len(actionable),
            total=len(actionable),
            data={"total_deleted": total_deleted},
        )


# ── Unsubscribe helpers ────────────────────────────────────────────────────────

async def _try_unsubscribe(
    http_url: Optional[str],
    mailto: Optional[str],
) -> bool:
    """
    Try to unsubscribe via HTTP GET/POST first, then mailto.
    Returns True if at least one method appeared to succeed.
    """
    if http_url:
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
                # Some lists use POST with an empty body; try GET first
                resp = await client.get(http_url)
                if resp.status_code < 400:
                    return True
                # Try POST
                resp = await client.post(http_url, data={})
                if resp.status_code < 400:
                    return True
        except Exception as e:
            logger.debug("HTTP unsubscribe failed for %s: %s", http_url, e)

    if mailto:
        # mailto: links — we log them but don't actually send email
        # (would require SMTP setup). Mark as partially handled.
        logger.info("mailto unsubscribe (not auto-sent): %s", mailto)
        return False

    return False
