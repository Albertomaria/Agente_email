"""
Heuristic classifier for email senders.

Rules are applied in priority order:
  1. List-Unsubscribe header present → newsletter
  2. Email / name / subject match newsletter keywords → newsletter
  3. Known social network domains → social
  4. Finance-related keywords → finance
  5. Email / subject match transactional keywords → transactional
  6. Otherwise → personal
"""
from __future__ import annotations

from models import EmailCategory
import config

FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "yahoo.it", "hotmail.com", "hotmail.it",
    "outlook.com", "live.com", "live.it", "msn.com", "icloud.com",
    "me.com", "mac.com", "aol.com", "protonmail.com", "proton.me",
    "gmx.com", "gmx.net", "web.de", "libero.it", "virgilio.it",
    "alice.it", "tin.it", "tiscali.it", "email.it", "fastwebnet.it",
}

SOCIAL_DOMAINS = [
    "facebook.com", "facebookmail.com", "twitter.com", "x.com",
    "instagram.com", "linkedin.com", "tiktok.com", "youtube.com",
    "pinterest.com", "reddit.com", "snapchat.com", "whatsapp.com",
    "telegram.org", "discord.com", "twitch.tv", "vimeo.com",
    "tumblr.com", "flickr.com", "nextdoor.com", "meetup.com",
]

FINANCE_KEYWORDS = [
    "bank", "banca", "bancario", "credit", "credito", "debit",
    "paypal", "stripe", "wise", "revolut", "n26", "fineco",
    "intesa", "unicredit", "bnl", "mps", "ing", "mediolanum",
    "invoice", "fattura", "payment", "pagamento", "bonifico",
    "estratto conto", "statement", "tax", "tasse", "irpef",
    "assicurazione", "insurance", "mutuo", "mortgage",
    "criptovalute", "bitcoin", "coinbase", "binance",
]


def classify_sender(
    email: str,
    name: str = "",
    sample_subject: str = "",
    has_unsubscribe: bool = False,
) -> EmailCategory:
    """Return the most likely category for a sender."""
    combined = " ".join([email, name, sample_subject]).lower()
    domain = email.split("@")[-1].lower() if "@" in email else ""
    local = email.split("@")[0].lower() if "@" in email else ""

    # Spam probabile: dominio gratuito ma nome/oggetto suggerisce un'azienda
    if domain in FREE_EMAIL_DOMAINS and name and _looks_corporate(name, local):
        return EmailCategory.SUSPICIOUS

    if has_unsubscribe:
        return EmailCategory.NEWSLETTER

    for kw in config.NEWSLETTER_KEYWORDS:
        if kw in combined:
            return EmailCategory.NEWSLETTER

    if any(sd in domain for sd in SOCIAL_DOMAINS):
        return EmailCategory.SOCIAL

    for kw in FINANCE_KEYWORDS:
        if kw in combined:
            return EmailCategory.FINANCE

    for kw in config.TRANSACTIONAL_KEYWORDS:
        if kw in combined:
            return EmailCategory.TRANSACTIONAL

    return EmailCategory.PERSONAL


def _looks_corporate(name: str, local_part: str) -> bool:
    """
    Ritorna True se il display name sembra un'azienda/brand
    ma l'indirizzo email è di un privato (es. nome123@gmail.com).
    Segnali: tutto maiuscolo, parole aziendali, local part con numeri casuali.
    """
    name_upper_ratio = sum(1 for c in name if c.isupper()) / max(len(name), 1)
    has_random_digits = sum(c.isdigit() for c in local_part) >= 3

    corporate_words = [
        "conferma", "confirm", "ordine", "order", "promo", "offerta",
        "sconto", "reward", "premio", "vincita", "vinto", "winner",
        "notifica", "alert", "account", "aggiornamento", "update",
        "verifica", "verify", "sicurezza", "security", "supporto",
        "support", "noreply", "no-reply", "info", "news", "shop",
        "store", "service", "cliente", "customer",
    ]
    name_lower = name.lower()
    has_corporate_word = any(w in name_lower for w in corporate_words)

    # È sospetto se: ha parole aziendali O è tutto maiuscolo E ha numeri casuali nell'indirizzo
    return (has_corporate_word or name_upper_ratio > 0.6) and has_random_digits
