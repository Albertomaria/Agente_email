"""
Phase 1 – ANALYZE

Connects to the account via the appropriate provider, iterates over all
senders, stores results in SQLite, and streams progress events.

Usage (async generator):
    async for event in AnalyzePhase(account).run():
        print(event)
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from models import AccountConfig, AnalysisResult, ProgressEvent
from providers import get_provider
from storage.database import Database
from utils.logger import get_logger

logger = get_logger(__name__)


class AnalyzePhase:
    def __init__(self, account: AccountConfig) -> None:
        self.account = account
        self.db = Database()

    async def run(self) -> AsyncIterator[ProgressEvent]:
        """
        Async generator that yields ProgressEvent objects.
        Clears any previous analysis results for this account first.
        """
        account_id = self.account.id
        self.db.clear_senders(account_id)
        self.db.set_analysis_meta(
            account_id, total_emails=0, total_senders=0, completed=False
        )

        provider = get_provider(self.account)

        try:
            yield ProgressEvent(type="progress", message="Connecting to email provider…")
            await provider.connect()
            yield ProgressEvent(type="progress", message="Connected. Fetching sender list…")

            total_emails = 0
            total_senders = 0

            async for sender_info in provider.list_senders():
                # Persist immediately so UI can poll incrementally
                self.db.upsert_sender(account_id, sender_info)
                total_emails += sender_info.total_count
                total_senders += 1

                yield ProgressEvent(
                    type="progress",
                    message=f"Scanned {total_senders} senders ({total_emails} emails)…",
                    current=total_senders,
                    total=0,  # unknown up-front
                    data={
                        "sender": sender_info.email,
                        "count": sender_info.total_count,
                    },
                )

            self.db.set_analysis_meta(
                account_id,
                total_emails=total_emails,
                total_senders=total_senders,
                completed=True,
            )

            yield ProgressEvent(
                type="done",
                message=f"Analysis complete: {total_senders} senders, {total_emails} emails.",
                current=total_senders,
                total=total_senders,
                data={"total_emails": total_emails, "total_senders": total_senders},
            )

        except Exception as exc:
            logger.exception("Analysis failed for account %s", account_id)
            self.db.set_analysis_meta(
                account_id,
                total_emails=0,
                total_senders=0,
                completed=False,
                error=str(exc),
            )
            yield ProgressEvent(
                type="error",
                message=f"Error during analysis: {exc}",
            )
        finally:
            await provider.disconnect()
