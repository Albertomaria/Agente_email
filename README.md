# 📬 Email Cleaner

A local web app to bulk-clean email accounts with 100k+ messages.
Supports **Gmail**, **Outlook/Microsoft**, and any **IMAP** provider.

```
┌─────────────────────────────────────────────────────┐
│  Phase 1 – ANALYZE   Scan all senders & classify    │
│  Phase 2 – REVIEW    Dashboard: Keep / Delete / Unsub│
│  Phase 3 – EXECUTE   Bulk delete + unsubscribe      │
└─────────────────────────────────────────────────────┘
```

---

## Quick Start

### 1. Install dependencies

```bash
cd email-cleaner
pip install -r requirements.txt
```

### 2. Provider setup (one-time)

| Provider | What you need |
|---|---|
| Gmail | `gmail_credentials.json` in project root → [Setup guide](README_Gmail_Setup.md) |
| Outlook / Microsoft | `MICROSOFT_CLIENT_ID` env var → [Setup guide](README_Microsoft_Setup.md) |
| IMAP | Host, port, and password entered in the web UI |

### 3. Run

```bash
python main.py
```

The browser opens automatically at **http://127.0.0.1:8765**

---

## Workflow

### Add an account

Click **+ Add Account** and fill in the provider details.
For Gmail and Microsoft you only need the email address — OAuth handles the rest.

### Phase 1 – Analyze

Click **Analyze** next to an account. The app connects to your mailbox and:
- Iterates through all messages (works with 100k+ emails via batched API calls)
- Groups them by sender
- Counts total and unread per sender
- Detects `List-Unsubscribe` headers
- Classifies each sender as **newsletter**, **transactional**, or **personal**

Progress is shown in real-time via Server-Sent Events.

### Phase 2 – Human Review

The dashboard shows all senders sorted by volume. For each sender you choose:

| Button | Effect |
|---|---|
| ✓ **Keep** | Do nothing (default) |
| 🗑 **Delete** | Delete all emails from this sender |
| 🚫 **Unsub+Delete** | Attempt HTTP unsubscribe, then delete |

Bulk actions are available for newsletters. **Nothing is executed until you click ⚡ Execute.**

### Phase 3 – Execute

Confirm and start execution. The app:
- Deletes emails in batches using the provider's native bulk API
- Attempts HTTP unsubscribe for "Unsub+Delete" actions
- Logs every action to `data/email_cleaner.db`

---

## Project structure

```
email-cleaner/
├── main.py                    # Entry point — starts the web server
├── config.py                  # All paths, scopes, and settings
├── models.py                  # Shared Pydantic data models
├── requirements.txt
│
├── providers/
│   ├── base.py                # EmailProvider abstract interface
│   ├── factory.py             # Returns the right provider for an account
│   ├── gmail.py               # Gmail API (batch metadata + batchDelete)
│   ├── microsoft.py           # Microsoft Graph API (MSAL + batch delete)
│   └── imap_provider.py       # imaplib fallback (any IMAP server)
│
├── phases/
│   ├── analyze.py             # Phase 1: scan & classify senders
│   └── execute.py             # Phase 3: delete & unsubscribe
│
├── storage/
│   ├── credentials.py         # Encrypted local credential store
│   └── database.py            # SQLite persistence (senders, actions, log)
│
├── utils/
│   ├── classifier.py          # Heuristic newsletter/transactional/personal
│   └── logger.py              # Rotating file + console logging
│
├── web/
│   ├── app.py                 # FastAPI routes
│   ├── templates/             # Jinja2 HTML templates
│   └── static/                # CSS and JS
│
├── data/                      # Auto-created at runtime
│   ├── email_cleaner.db       # SQLite database
│   ├── tokens/                # OAuth token cache (never share!)
│   └── logs/                  # Application logs
│
├── README_Gmail_Setup.md
└── README_Microsoft_Setup.md
```

---

## Configuration

All settings are in `config.py`. Key options:

| Variable | Default | Description |
|---|---|---|
| `WEB_HOST` | `127.0.0.1` | Bind address (env: `WEB_HOST`) |
| `WEB_PORT` | `8765` | Port (env: `WEB_PORT`) |
| `GMAIL_BATCH_SIZE` | `500` | Messages per Gmail batch request |
| `MICROSOFT_BATCH_SIZE` | `20` | Requests per Graph API batch call |
| `IMAP_BATCH_SIZE` | `200` | UIDs per IMAP fetch batch |

---

## Security

- OAuth tokens are stored **locally** in `data/tokens/` — never sent anywhere
- IMAP passwords are encrypted at rest using Fernet symmetric encryption
- The encryption key is generated once and stored in `data/.keyfile` (chmod 600)
- Override the key with the `EMAILCLEANER_SECRET` environment variable
- The web server only binds to `127.0.0.1` by default (local access only)

---

## Requirements

- Python 3.10+
- Internet access (for OAuth and API calls)
- For Gmail: a Google Cloud project with Gmail API enabled
- For Microsoft: an Azure app registration

---

## Troubleshooting

**Gmail: "This app isn't verified"**
Click *Advanced → Go to Email Cleaner (unsafe)*. This is normal for personal apps
in testing mode.

**Microsoft: device code not showing**
Make sure the terminal where you ran `python main.py` is visible — the code prints there.

**IMAP: "LOGIN failed"**
Many providers require an **app password** instead of your regular password
when 2FA is enabled. Generate one in your provider's security settings.

**Analysis is slow**
Gmail API batches 500 metadata requests per call — a 100k mailbox takes 2-3 minutes.
Microsoft Graph paginates at 999 messages per page. IMAP is slower and depends
on server speed.
