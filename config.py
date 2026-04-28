"""
Global configuration for email-cleaner.
All paths, scopes, and defaults are defined here.
"""
import os
from pathlib import Path

# ─── Base paths ───────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
TOKENS_DIR = DATA_DIR / "tokens"
LOGS_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "email_cleaner.db"

# Create dirs if missing
for _d in [DATA_DIR, TOKENS_DIR, LOGS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ─── Web server ───────────────────────────────────────────────────────────────
WEB_HOST = os.getenv("WEB_HOST", "127.0.0.1")
WEB_PORT = int(os.getenv("WEB_PORT", "8765"))

# ─── Gmail OAuth 2.0 ─────────────────────────────────────────────────────────
GMAIL_SCOPES = [
    "https://mail.google.com/",  # necessario per batchDelete (cancellazione permanente)
]
GMAIL_CREDENTIALS_FILE = BASE_DIR / "gmail_credentials.json"   # from Google Cloud Console
GMAIL_TOKEN_DIR = TOKENS_DIR / "gmail"
GMAIL_TOKEN_DIR.mkdir(parents=True, exist_ok=True)

# OAuth redirect URI for the local server
OAUTH_REDIRECT_PORT = 8766
OAUTH_REDIRECT_URI = f"http://localhost:{OAUTH_REDIRECT_PORT}/oauth/callback"

# ─── Microsoft Graph API ─────────────────────────────────────────────────────
MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID", "")
MICROSOFT_TENANT_ID = os.getenv("MICROSOFT_TENANT_ID", "consumers")  # 'consumers' for personal accounts
MICROSOFT_SCOPES = [
    "https://graph.microsoft.com/Mail.Read",
    "https://graph.microsoft.com/Mail.ReadWrite",
    "offline_access",
]
MICROSOFT_TOKEN_DIR = TOKENS_DIR / "microsoft"
MICROSOFT_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
MICROSOFT_AUTHORITY = f"https://login.microsoftonline.com/{MICROSOFT_TENANT_ID}"
MICROSOFT_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# ─── Analysis settings ───────────────────────────────────────────────────────
# Max emails to process per sender during analysis (0 = unlimited)
MAX_EMAILS_PER_SENDER = 0
# Batch size for API calls
GMAIL_BATCH_SIZE = 50
MICROSOFT_BATCH_SIZE = 20   # Graph API batch limit
IMAP_BATCH_SIZE = 200

# ─── Classifier keywords ─────────────────────────────────────────────────────
NEWSLETTER_KEYWORDS = [
    "newsletter", "unsubscribe", "mailing list", "list-unsubscribe",
    "noreply", "no-reply", "donotreply", "notification", "updates@",
    "news@", "digest", "weekly", "monthly", "bulletin",
]
TRANSACTIONAL_KEYWORDS = [
    "order", "invoice", "receipt", "confirm", "booking", "reservation",
    "ticket", "payment", "transaction", "delivery", "shipment", "tracking",
    "account", "password", "reset", "verify", "verification", "alert",
    "support@", "billing@", "noreply@", "info@",
]

# ─── Encryption key (derived from machine ID if not set) ─────────────────────
# Used to encrypt stored credentials at rest.
# Override with EMAILCLEANER_SECRET env var for extra security.
ENCRYPTION_KEY_ENV = "EMAILCLEANER_SECRET"
