"""
Email Cleaner — entry point

Run:
    python main.py

Then open http://127.0.0.1:8765 in your browser.
"""
import sys
import webbrowser
import threading
import time

import uvicorn

import config
from web.app import app
from utils.logger import get_logger

logger = get_logger(__name__)


def _open_browser(url: str, delay: float = 1.5) -> None:
    def _open():
        time.sleep(delay)
        webbrowser.open(url)
    t = threading.Thread(target=_open, daemon=True)
    t.start()


def main() -> None:
    url = f"http://{config.WEB_HOST}:{config.WEB_PORT}"
    logger.info("Starting Email Cleaner at %s", url)
    print(f"\n{'─'*50}")
    print(f"  📬 Email Cleaner")
    print(f"  Open: {url}")
    print(f"{'─'*50}\n")

    _open_browser(url)

    uvicorn.run(
        app,
        host=config.WEB_HOST,
        port=config.WEB_PORT,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
