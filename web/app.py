"""
Phase 2 – HUMAN REVIEW  (FastAPI web application)

Routes:
  GET  /                    → account list (home)
  GET  /accounts/add        → add-account form
  POST /accounts/add        → save new account
  POST /accounts/{id}/delete → delete an account
  GET  /analyze/{id}        → start analysis (SSE stream)
  GET  /dashboard/{id}      → sender review dashboard
  POST /dashboard/{id}/action → save a single sender action
  POST /dashboard/{id}/actions → bulk-save actions (JSON body)
  GET  /execute/{id}        → run execution (SSE stream)
  GET  /log/{id}            → execution log
  GET  /api/senders/{id}    → JSON list of senders (for dynamic reload)
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, AsyncIterator

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from models import AccountConfig, ProviderType, SenderAction, ActionType
from providers import get_provider
from phases.analyze import AnalyzePhase
from phases.execute import ExecutePhase
from storage.credentials import CredentialStore
from storage.database import Database
from utils.logger import get_logger

logger = get_logger(__name__)

BASE_DIR = Path(__file__).parent
app = FastAPI(title="Email Cleaner")

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "static")),
    name="static",
)
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

store = CredentialStore()
db = Database()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _provider_icon(pt: ProviderType) -> str:
    return {
        ProviderType.GMAIL: "📧",
        ProviderType.MICROSOFT: "📨",
        ProviderType.IMAP: "🗄️",
    }.get(pt, "✉️")


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


# ── Home ───────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    accounts = store.list_accounts()
    account_data = []
    for acc in accounts:
        meta = db.get_analysis_meta(acc.id)
        account_data.append({
            "account": acc,
            "icon": _provider_icon(acc.provider_type),
            "meta": meta,
        })
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "accounts": account_data},
    )


# ── Add account ────────────────────────────────────────────────────────────────

@app.get("/accounts/add", response_class=HTMLResponse)
async def add_account_form(request: Request):
    return templates.TemplateResponse("add_account.html", {"request": request})


@app.post("/accounts/add")
async def add_account(
    request: Request,
    display_name: str = Form(...),
    email: str = Form(...),
    provider_type: str = Form(...),
    imap_host: Optional[str] = Form(None),
    imap_port: int = Form(993),
    imap_use_ssl: bool = Form(True),
    imap_username: Optional[str] = Form(None),
    password: Optional[str] = Form(None),
):
    pt = ProviderType(provider_type)
    account_id = f"{pt.value}_{email.split('@')[0].lower()}_{uuid.uuid4().hex[:6]}"

    account = AccountConfig(
        id=account_id,
        display_name=display_name,
        email=email,
        provider_type=pt,
        imap_host=imap_host or None,
        imap_port=imap_port,
        imap_use_ssl=imap_use_ssl,
        imap_username=imap_username or None,
        created_at=datetime.utcnow().isoformat(),
    )
    store.save_account(account)

    # Store password for IMAP accounts
    if pt == ProviderType.IMAP and password:
        store.set_password(account_id, password)

    logger.info("Account added: %s (%s)", email, pt.value)
    return RedirectResponse("/", status_code=303)


@app.post("/accounts/{account_id}/delete")
async def delete_account(account_id: str):
    store.delete_account(account_id)
    db.clear_senders(account_id)
    db.clear_actions(account_id)
    return RedirectResponse("/", status_code=303)


# ── Phase 1: Analyze (SSE) ────────────────────────────────────────────────────

@app.get("/analyze/{account_id}")
async def analyze(account_id: str, request: Request):
    account = store.get_account(account_id)
    if not account:
        raise HTTPException(404, "Account not found")

    async def event_stream() -> AsyncIterator[str]:
        phase = AnalyzePhase(account)
        async for event in phase.run():
            yield _sse(event.model_dump())
            if event.type in ("done", "error"):
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/analyze/{account_id}/page", response_class=HTMLResponse)
async def analyze_page(account_id: str, request: Request):
    account = store.get_account(account_id)
    if not account:
        raise HTTPException(404, "Account not found")
    return templates.TemplateResponse(
        "analyze.html",
        {"request": request, "account": account},
    )


# ── Phase 2: Dashboard ────────────────────────────────────────────────────────

@app.get("/dashboard/{account_id}", response_class=HTMLResponse)
async def dashboard(account_id: str, request: Request, sort: str = "total_count"):
    account = store.get_account(account_id)
    if not account:
        raise HTTPException(404, "Account not found")

    meta = db.get_analysis_meta(account_id)
    if not meta or not meta.get("completed"):
        return RedirectResponse(f"/analyze/{account_id}/page", status_code=303)

    senders = db.get_senders(account_id)
    # Load existing actions
    actions_map = {a.sender_email: a.action.value for a in db.get_actions(account_id)}

    # Sort
    if sort == "unread":
        senders.sort(key=lambda s: s.unread_count, reverse=True)
    elif sort == "unread_pct":
        senders.sort(key=lambda s: s.unread_count / s.total_count if s.total_count else 0, reverse=True)
    elif sort == "date":
        senders.sort(key=lambda s: s.last_email_date or "", reverse=True)
    elif sort == "date_asc":
        senders.sort(key=lambda s: s.last_email_date or "9999")
    elif sort == "name":
        senders.sort(key=lambda s: s.name.lower())
    elif sort == "category":
        senders.sort(key=lambda s: s.category.value)
    else:  # default: total_count
        senders.sort(key=lambda s: s.total_count, reverse=True)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "account": account,
            "icon": _provider_icon(account.provider_type),
            "meta": meta,
            "senders": senders,
            "actions_map": actions_map,
            "current_sort": sort,
        },
    )


@app.post("/dashboard/{account_id}/action")
async def set_action(
    account_id: str,
    sender_email: str = Form(...),
    action: str = Form(...),
):
    store.get_account(account_id) or (_ for _ in ()).throw(HTTPException(404))
    db.set_action(
        SenderAction(
            account_id=account_id,
            sender_email=sender_email,
            action=ActionType(action),
        )
    )
    return JSONResponse({"ok": True})


@app.post("/dashboard/{account_id}/actions")
async def set_actions_bulk(account_id: str, request: Request):
    """Accept JSON body: [{"sender_email": "...", "action": "..."}, ...]"""
    body = await request.json()
    actions = [
        SenderAction(
            account_id=account_id,
            sender_email=item["sender_email"],
            action=ActionType(item["action"]),
        )
        for item in body
    ]
    db.set_actions_bulk(actions)
    return JSONResponse({"ok": True, "count": len(actions)})


# ── Phase 3: Execute (SSE) ────────────────────────────────────────────────────

@app.get("/execute/{account_id}")
async def execute(account_id: str, request: Request):
    account = store.get_account(account_id)
    if not account:
        raise HTTPException(404, "Account not found")

    async def event_stream() -> AsyncIterator[str]:
        phase = ExecutePhase(account)
        async for event in phase.run():
            yield _sse(event.model_dump())
            if event.type in ("done", "error"):
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/execute/{account_id}/page", response_class=HTMLResponse)
async def execute_page(account_id: str, request: Request):
    account = store.get_account(account_id)
    if not account:
        raise HTTPException(404, "Account not found")
    actions = db.get_actions(account_id)
    actionable = [a for a in actions if a.action != ActionType.KEEP]

    # Costruisci il riepilogo dettagliato con conteggio email reali
    senders = db.get_senders(account_id)
    sender_map = {s.email: s for s in senders}
    total_emails = 0
    action_summary = []
    for a in actionable:
        s = sender_map.get(a.sender_email)
        count = s.total_count if s else 0
        total_emails += count
        action_summary.append({
            "sender_email": a.sender_email,
            "sender_name": s.name if s else "",
            "action": a.action.value,
            "count": count,
        })
    # Ordina per count decrescente
    action_summary.sort(key=lambda x: x["count"], reverse=True)

    return templates.TemplateResponse(
        "execute.html",
        {
            "request": request,
            "account": account,
            "actionable_count": len(actionable),
            "total_emails": total_emails,
            "action_summary": action_summary,
        },
    )


# ── Execution log ─────────────────────────────────────────────────────────────

@app.get("/log/{account_id}", response_class=HTMLResponse)
async def log_page(account_id: str, request: Request):
    account = store.get_account(account_id)
    if not account:
        raise HTTPException(404, "Account not found")
    logs = db.get_execution_log(account_id)
    return templates.TemplateResponse(
        "log.html",
        {"request": request, "account": account, "logs": logs},
    )


# ── JSON API ──────────────────────────────────────────────────────────────────

@app.get("/api/senders/{account_id}")
async def api_senders(account_id: str):
    senders = db.get_senders(account_id)
    return JSONResponse([s.model_dump() for s in senders])


@app.get("/api/preview/{account_id}")
async def api_preview(account_id: str, sender_email: str):
    account = store.get_account(account_id)
    if not account:
        raise HTTPException(404, "Account not found")
    provider = get_provider(account)
    try:
        await provider.connect()
        previews = await provider.get_preview(sender_email, limit=5)
    finally:
        await provider.disconnect()
    return JSONResponse(previews)
