"""
restore_trash.py — Ripristina tutte le email dal Cestino alla Posta in arrivo.

Uso:
    python restore_trash.py <account_id>

Dove <account_id> è l'ID account visibile nell'URL del dashboard, es:
    gmail_gcm.moro_abc123

Lo script usa lo stesso token OAuth già salvato dall'app, quindi non serve
rifare il login se l'analisi ha già funzionato una volta.
"""
import sys
import time
from pathlib import Path

# Assicurati di essere nella cartella email-cleaner
sys.path.insert(0, str(Path(__file__).parent))

import config
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


def load_creds(account_id: str) -> Credentials:
    token_path = config.GMAIL_TOKEN_DIR / f"{account_id}.json"
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), config.GMAIL_SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json())
        return creds
    # Nuovo login se necessario
    flow = InstalledAppFlow.from_client_secrets_file(
        str(config.GMAIL_CREDENTIALS_FILE), config.GMAIL_SCOPES
    )
    creds = flow.run_local_server(port=0, prompt="consent", open_browser=True)
    token_path.write_text(creds.to_json())
    return creds


def fetch_trash_ids(service) -> list[str]:
    print("Recupero ID email nel cestino...")
    ids = []
    page_token = None
    while True:
        kwargs = {
            "userId": "me",
            "labelIds": ["TRASH"],
            "maxResults": 500,
            "includeSpamTrash": True,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        resp = service.users().messages().list(**kwargs).execute()
        msgs = resp.get("messages", [])
        ids.extend(m["id"] for m in msgs)
        page_token = resp.get("nextPageToken")
        print(f"  trovati {len(ids)} finora...", end="\r")
        if not page_token:
            break
    print(f"\nTotale email nel cestino: {len(ids)}")
    return ids


def restore_batch(service, ids: list[str]) -> None:
    chunk_size = 1000
    total = len(ids)
    restored = 0
    for i in range(0, total, chunk_size):
        chunk = ids[i:i + chunk_size]
        for attempt in range(5):
            try:
                service.users().messages().batchModify(
                    userId="me",
                    body={
                        "ids": chunk,
                        "removeLabelIds": ["TRASH"],
                        "addLabelIds": ["INBOX"],
                    },
                ).execute()
                restored += len(chunk)
                pct = round(restored / total * 100)
                print(f"  Ripristinate {restored}/{total} ({pct}%)...", end="\r")
                break
            except Exception as e:
                wait = 2 ** attempt
                print(f"\n  Errore (tentativo {attempt+1}/5): {e} — riprovo in {wait}s")
                time.sleep(wait)
        time.sleep(0.3)  # rispetta rate limit
    print(f"\nFatto! {restored}/{total} email spostate in Posta in arrivo.")


def main():
    if len(sys.argv) < 2:
        # Lista account disponibili
        token_dir = config.GMAIL_TOKEN_DIR
        tokens = list(token_dir.glob("*.json"))
        if not tokens:
            print("Nessun account Gmail configurato.")
            print("Uso: python restore_trash.py <account_id>")
            sys.exit(1)
        if len(tokens) == 1:
            account_id = tokens[0].stem
            print(f"Account trovato: {account_id}")
        else:
            print("Account disponibili:")
            for i, t in enumerate(tokens):
                print(f"  [{i}] {t.stem}")
            idx = int(input("Scegli numero: "))
            account_id = tokens[idx].stem
    else:
        account_id = sys.argv[1]

    print(f"\nAccount: {account_id}")
    print("Caricamento credenziali...")
    creds = load_creds(account_id)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    trash_ids = fetch_trash_ids(service)
    if not trash_ids:
        print("Il cestino è già vuoto.")
        return

    print(f"\nPronti a ripristinare {len(trash_ids)} email in Posta in arrivo.")
    confirm = input("Confermi? (s/n): ").strip().lower()
    if confirm != "s":
        print("Annullato.")
        return

    restore_batch(service, trash_ids)


if __name__ == "__main__":
    main()
