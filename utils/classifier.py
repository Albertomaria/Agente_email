"""
Heuristic classifier for email senders.

Rules are applied in priority order:
  1. List-Unsubscribe header present → newsletter
  2. Email / name / subject match newsletter keywords → newsletter
  3. Email / subject match transactional keywords → transactional
  4. Otherwise → personal
"""
from __future__ import annotations

import re
from models import EmailCategory
import config


def classify_sender(
    email: str,
    name: str = "",
    sample_subject: str = "",
    has_unsubscribe: bool = False,
) -> EmailCategory:
    """Return the most likely category for a sender."""
    combined = " ".join([email, name, sample_subject]).lower()

    if has_unsubscribe:
        return EmailCategory.NEWSLETTER

    for kw in config.NEWSLETTER_KEYWORDS:
        if kw in combined:
            return EmailCategory.NEWSLETTER

    for kw in config.TRANSACTIONAL_KEYWORDS:
        if kw in combined:
            return EmailCategory.TRANSACTIONAL

    return EmailCategory.PERSONAL
