"""
Shared data models used across all modules.
"""
from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ProviderType(str, Enum):
    GMAIL = "gmail"
    MICROSOFT = "microsoft"
    IMAP = "imap"


class EmailCategory(str, Enum):
    NEWSLETTER = "newsletter"
    TRANSACTIONAL = "transactional"
    SOCIAL = "social"
    FINANCE = "finance"
    PERSONAL = "personal"
    SUSPICIOUS = "suspicious"  # spam probabile: dominio gratuito con nome aziendale


class ActionType(str, Enum):
    KEEP = "keep"
    DELETE = "delete"
    UNSUBSCRIBE_DELETE = "unsubscribe_delete"


# ─── Account ──────────────────────────────────────────────────────────────────

class AccountConfig(BaseModel):
    """Represents a configured email account."""
    id: str                          # unique slug, e.g. "gmail_alberto"
    display_name: str                # human-friendly label
    email: str
    provider_type: ProviderType
    # IMAP-only fields
    imap_host: Optional[str] = None
    imap_port: Optional[int] = 993
    imap_use_ssl: bool = True
    imap_username: Optional[str] = None
    # Sensitive fields (password / tokens) stored separately in credentials store
    created_at: Optional[str] = None


# ─── Sender analysis ──────────────────────────────────────────────────────────

class SenderInfo(BaseModel):
    """Aggregated information about a single sender after analysis."""
    email: str
    name: str = ""
    total_count: int = 0
    unread_count: int = 0
    category: EmailCategory = EmailCategory.PERSONAL
    has_unsubscribe: bool = False
    unsubscribe_url: Optional[str] = None
    unsubscribe_mailto: Optional[str] = None
    sample_subject: str = ""
    # Internal: list of message IDs (not persisted in full, used during execute)
    message_ids: list[str] = Field(default_factory=list)


class AnalysisResult(BaseModel):
    """Full result of a Phase 1 analysis for one account."""
    account_id: str
    total_emails: int = 0
    total_senders: int = 0
    senders: list[SenderInfo] = Field(default_factory=list)
    completed: bool = False
    error: Optional[str] = None


# ─── Actions ──────────────────────────────────────────────────────────────────

class SenderAction(BaseModel):
    """User-approved action for one sender."""
    account_id: str
    sender_email: str
    action: ActionType


class ExecutionResult(BaseModel):
    """Result of Phase 3 execution for one sender."""
    account_id: str
    sender_email: str
    action: ActionType
    emails_deleted: int = 0
    unsubscribed: bool = False
    success: bool = True
    error: Optional[str] = None


# ─── Progress events (SSE) ────────────────────────────────────────────────────

class ProgressEvent(BaseModel):
    """Streamed during long-running operations."""
    type: str          # "progress" | "done" | "error"
    message: str = ""
    current: int = 0
    total: int = 0
    data: Optional[dict] = None
