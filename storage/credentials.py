"""
Secure local credential storage.

Passwords / sensitive values are encrypted with Fernet symmetric encryption
before being written to disk. The encryption key is derived from an
environment variable (EMAILCLEANER_SECRET) or a machine-specific fallback.

AccountConfig objects (non-sensitive) are stored as plain JSON.
"""
from __future__ import annotations

import json
import os
import platform
import hashlib
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

import config
from models import AccountConfig

_ACCOUNTS_FILE = config.DATA_DIR / "accounts.json"
_SECRETS_FILE = config.DATA_DIR / "secrets.enc"


def _get_or_create_key() -> bytes:
    """
    Derive a stable Fernet key from the secret env var or machine ID.
    The key is cached in a local key file so it survives restarts.
    """
    key_file = config.DATA_DIR / ".keyfile"

    # If env override is set, derive key from it
    secret_env = os.environ.get(config.ENCRYPTION_KEY_ENV, "")
    if secret_env:
        raw = hashlib.sha256(secret_env.encode()).digest()
    elif key_file.exists():
        return key_file.read_bytes()
    else:
        # Generate a fresh key and persist it
        key = Fernet.generate_key()
        key_file.write_bytes(key)
        # Restrict permissions on Unix
        try:
            key_file.chmod(0o600)
        except Exception:
            pass
        return key

    # Derive a URL-safe base64 key from the 32-byte SHA-256 digest
    import base64
    key = base64.urlsafe_b64encode(raw)
    return key


_FERNET = Fernet(_get_or_create_key())


def _load_secrets() -> dict[str, str]:
    if not _SECRETS_FILE.exists():
        return {}
    try:
        decrypted = _FERNET.decrypt(_SECRETS_FILE.read_bytes())
        return json.loads(decrypted.decode())
    except Exception:
        return {}


def _save_secrets(data: dict[str, str]) -> None:
    encrypted = _FERNET.encrypt(json.dumps(data).encode())
    _SECRETS_FILE.write_bytes(encrypted)
    try:
        _SECRETS_FILE.chmod(0o600)
    except Exception:
        pass


class CredentialStore:
    """Manages account configs and encrypted passwords."""

    # ── Accounts ────────────────────────────────────────────────────────────

    def list_accounts(self) -> list[AccountConfig]:
        if not _ACCOUNTS_FILE.exists():
            return []
        raw = json.loads(_ACCOUNTS_FILE.read_text(encoding="utf-8"))
        return [AccountConfig(**a) for a in raw]

    def get_account(self, account_id: str) -> Optional[AccountConfig]:
        for acc in self.list_accounts():
            if acc.id == account_id:
                return acc
        return None

    def save_account(self, account: AccountConfig) -> None:
        accounts = self.list_accounts()
        existing_ids = [a.id for a in accounts]
        if account.id in existing_ids:
            accounts = [account if a.id == account.id else a for a in accounts]
        else:
            accounts.append(account)
        _ACCOUNTS_FILE.write_text(
            json.dumps([a.model_dump() for a in accounts], indent=2),
            encoding="utf-8",
        )

    def delete_account(self, account_id: str) -> None:
        accounts = [a for a in self.list_accounts() if a.id != account_id]
        _ACCOUNTS_FILE.write_text(
            json.dumps([a.model_dump() for a in accounts], indent=2),
            encoding="utf-8",
        )
        # Also delete stored password
        secrets = _load_secrets()
        secrets.pop(account_id, None)
        _save_secrets(secrets)

    # ── Passwords (IMAP) ────────────────────────────────────────────────────

    def set_password(self, account_id: str, password: str) -> None:
        secrets = _load_secrets()
        secrets[account_id] = password
        _save_secrets(secrets)

    def get_password(self, account_id: str) -> Optional[str]:
        return _load_secrets().get(account_id)
