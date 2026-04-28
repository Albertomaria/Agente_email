# Gmail Setup Guide

This guide walks you through creating a Google Cloud project and OAuth credentials
so that **email-cleaner** can access your Gmail account via the Gmail API.

---

## 1. Create a Google Cloud Project

1. Go to [https://console.cloud.google.com/](https://console.cloud.google.com/)
2. Click **Select a project** → **New Project**
3. Give it a name (e.g. `email-cleaner`) and click **Create**

---

## 2. Enable the Gmail API

1. In your new project, open the left menu: **APIs & Services → Library**
2. Search for **Gmail API**
3. Click on it and press **Enable**

---

## 3. Configure the OAuth Consent Screen

1. Go to **APIs & Services → OAuth consent screen**
2. Select **External** (for personal Gmail accounts) and click **Create**
3. Fill in:
   - **App name**: `Email Cleaner`
   - **User support email**: your email
   - **Developer contact**: your email
4. Click **Save and Continue** through the remaining screens (no need to add scopes here)
5. On the **Test users** screen, add your own Gmail address as a test user
6. Click **Back to Dashboard**

> **Note:** The app will stay in "Testing" mode, which is fine for personal use.
> In testing mode, only accounts you add as test users can authenticate.

---

## 4. Create OAuth 2.0 Credentials

1. Go to **APIs & Services → Credentials**
2. Click **+ Create Credentials → OAuth client ID**
3. Set:
   - **Application type**: `Desktop app`
   - **Name**: `email-cleaner`
4. Click **Create**
5. In the dialog that appears, click **Download JSON**
6. Rename the downloaded file to **`gmail_credentials.json`**
7. Place it in the **root of the `email-cleaner` project folder** (next to `main.py`)

---

## 5. First-time Authentication

When you click **Analyze** for a Gmail account for the first time:

1. A browser window will open with a Google sign-in page
2. Sign in with the Gmail account you want to clean
3. You may see a warning: _"Google hasn't verified this app"_ — click **Advanced → Go to Email Cleaner (unsafe)**
4. Grant the requested permissions
5. The browser will show a success page and you can close it
6. A token file will be saved at `data/tokens/gmail/<account_id>.json` for future sessions

---

## 6. Revoking Access

To revoke access at any time:
- Visit [https://myaccount.google.com/permissions](https://myaccount.google.com/permissions)
- Find **Email Cleaner** and click **Remove Access**
- Delete the token file at `data/tokens/gmail/<account_id>.json`

---

## Scopes Used

| Scope | Purpose |
|---|---|
| `gmail.readonly` | Read email metadata (senders, subjects, headers) |
| `gmail.modify` | Delete emails (batchDelete) |

No emails are read or uploaded — only metadata is accessed.
