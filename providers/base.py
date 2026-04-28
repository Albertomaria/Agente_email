"""
Abstract base class that every email provider must implement.

All providers expose the same interface so that Phase 1 (analyze) and
Phase 3 (execute) are completely provider-agnostic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional

from models import AccountConfig, SenderInfo


class EmailProvider(ABC):
    """Common interface for all email providers."""

    def __init__(self, account: AccountConfig) -> None:
        self.account = account

    # ── Connection lifecycle ────────────────────────────────────────────────

    @abstractmethod
    async def connect(self) -> None:
        """
        Authenticate and open a connection to the provider.
        For OAuth providers this triggers the browser flow if no token is cached.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """Release any open connections / sessions."""

    # ── Core operations ─────────────────────────────────────────────────────

    @abstractmethod
    async def list_senders(self) -> AsyncIterator[SenderInfo]:
        """
        Yield one SenderInfo per unique sender in the mailbox.
        Each SenderInfo must include:
          - email, name
          - total_count, unread_count
          - has_unsubscribe, unsubscribe_url / unsubscribe_mailto
          - sample_subject
          - message_ids  (full list, needed by execute phase)
        """

    @abstractmethod
    async def get_emails_by_sender(self, sender_email: str) -> list[str]:
        """
        Return all message IDs for the given sender address.
        Used when we need to refresh the ID list just before execution.
        """

    @abstractmethod
    async def delete_emails(
        self,
        message_ids: list[str],
        progress_cb=None,
    ) -> int:
        """
        Permanently delete the given messages.
        Returns the count of successfully deleted messages.
        Optional async callable progress_cb(current, total) for progress reporting.
        """

    @abstractmethod
    async def get_unsubscribe_header(self, message_id: str) -> Optional[str]:
        """
        Return the raw value of the List-Unsubscribe header for one message,
        or None if absent.
        """

    # ── Helpers with default implementations ───────────────────────────────

    async def __aenter__(self) -> "EmailProvider":
        await self.connect()
        return self

    async def __aexit__(self, *_) -> None:
        await self.disconnect()

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"account={self.account.email!r} "
            f"provider={self.account.provider_type.value}>"
        )
