"""
Factory that returns the right EmailProvider for an AccountConfig.
"""
from __future__ import annotations

from models import AccountConfig, ProviderType
from providers.base import EmailProvider


def get_provider(account: AccountConfig) -> EmailProvider:
    """Instantiate and return the correct provider for *account*."""
    if account.provider_type == ProviderType.GMAIL:
        from providers.gmail import GmailProvider
        return GmailProvider(account)
    elif account.provider_type == ProviderType.MICROSOFT:
        from providers.microsoft import MicrosoftProvider
        return MicrosoftProvider(account)
    elif account.provider_type == ProviderType.IMAP:
        from providers.imap_provider import ImapProvider
        return ImapProvider(account)
    else:
        raise ValueError(f"Unknown provider type: {account.provider_type}")
