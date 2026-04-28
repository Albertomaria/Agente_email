"""
Centralized logging configuration.

Log files are written to data/logs/email_cleaner.log with daily rotation.
"""
import logging
import logging.handlers
from pathlib import Path

import config


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(logging.DEBUG)

    # ── Console handler ────────────────────────────────────────────────────
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter("%(levelname)-8s %(name)s: %(message)s"))
    logger.addHandler(ch)

    # ── File handler (rotating daily) ─────────────────────────────────────
    log_file = config.LOGS_DIR / "email_cleaner.log"
    fh = logging.handlers.TimedRotatingFileHandler(
        str(log_file), when="midnight", backupCount=7, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    )
    logger.addHandler(fh)

    return logger
