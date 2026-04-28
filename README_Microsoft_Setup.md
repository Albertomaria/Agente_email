# Microsoft (Outlook / Hotmail / Office 365) Setup Guide

This guide walks you through registering an Azure application so that
**email-cleaner** can access your Microsoft email via the Microsoft Graph API.

Works with: **Outlook.com, Hotmail.com, Live.com** (personal) and
**Office 365 / Exchange Online** (work/school accounts).

---

## 1. Register an Azure App

1. Go to [https://portal.azure.com/](https://portal.azure.com/)
   - Sign in with **any** Microsoft account (doesn't have to be the mailbox you want to clean)
2. In the search bar, type **App registrations** and open it
3. Click **+ New registration**
4. Fill in:
   - **Name**: `email-cleaner`
   - **Supported account types**: Choose one:
     - **Personal Microsoft accounts only** → for Outlook.com / Hotmail
     - **Accounts in any organizational directory and personal Microsoft accounts** → for both
     - **Accounts in this organizational directory only** → for single tenant Office 365
5. Leave **Redirect URI** blank (we use device code flow, no redirect needed)
6. Click **Register**
7. **Copy the Application (client) ID** — you'll need this in step 3

---

## 2. Enable Public Client Flow (required for device code)

1. In your app registration, go to **Authentication**
2. Scroll down to **Advanced settings**
3. Set **Allow public client flows** to **Yes**
4. Click **Save**

---

## 3. Set API Permissions

1. Go to **API permissions**
2. Click **+ Add a permission → Microsoft Graph → Delegated permissions**
3. Search for and add:
   - `Mail.Read`
   - `Mail.ReadWrite`
   - `offline_access` (for refresh tokens)
4. Click **Add permissions**
5. You do **not** need admin consent for these delegated permissions

---

## 4. Configure email-cleaner

Set the `MICROSOFT_CLIENT_ID` environment variable to your Application (client) ID.

**Option A — `.env` file** (recommended):

Create a file called `.env` in the project root:

```
MICROSOFT_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

Then install `python-dotenv` (already in requirements.txt) and add at the top of `main.py`:

```python
from dotenv import load_dotenv
load_dotenv()
```

**Option B — shell export**:

```bash
# Windows (Command Prompt)
set MICROSOFT_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# Windows (PowerShell)
$env:MICROSOFT_CLIENT_ID="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"

# macOS / Linux
export MICROSOFT_CLIENT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

---

## 5. Tenant Configuration (Office 365 / Work accounts)

For **personal accounts** (Outlook.com, Hotmail) the default `consumers` tenant works.

For **work or school accounts**, you may need to set the tenant ID:

```
MICROSOFT_TENANT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

Find your tenant ID in the Azure portal under **Azure Active Directory → Overview**.

---

## 6. First-time Authentication (Device Code Flow)

When you click **Analyze** for a Microsoft account for the first time:

1. A message will appear in the **terminal** where you ran `python main.py`:
   ```
   To sign in, use a web browser to open the page https://microsoft.com/devicelogin
   and enter the code XXXXXXXXX to authenticate.
   ```
2. Open that URL in any browser and enter the code
3. Sign in with the Microsoft account you want to clean
4. Grant the requested permissions
5. A token cache is saved at `data/tokens/microsoft/<account_id>.json` for future sessions

---

## 7. Revoking Access

To revoke access:
- Visit [https://myapps.microsoft.com/](https://myapps.microsoft.com/)
- Find **email-cleaner** in your apps and revoke it
- Delete `data/tokens/microsoft/<account_id>.json`

---

## Permissions Used

| Permission | Purpose |
|---|---|
| `Mail.Read` | Read email metadata (senders, subjects, headers) |
| `Mail.ReadWrite` | Delete emails via Graph API |
| `offline_access` | Keep you signed in across sessions |

No email content is read — only metadata headers are accessed.
