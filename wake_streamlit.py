from __future__ import annotations

import os
import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright


def normalize_url(value: str) -> str:
    url = value.strip()
    if not url:
        raise ValueError("STREAMLIT_APP_URL is empty.")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    if not parsed.netloc:
        raise ValueError(f"Invalid STREAMLIT_APP_URL: {value!r}")
    return url.rstrip("/")


def main() -> int:
    try:
        app_url = normalize_url(os.environ.get("STREAMLIT_APP_URL", ""))
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    print(f"Opening Streamlit app: {app_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1365, "height": 900},
            locale="sr-RS",
            timezone_id="Europe/Belgrade",
        )

        page.goto(app_url, wait_until="domcontentloaded", timeout=120_000)

        # Streamlit establishes its WebSocket session after the page loads.
        # Waiting here gives the app enough time to wake, execute the script,
        # synchronize data, and run the automatic notification checks.
        try:
            page.wait_for_selector('[data-testid="stAppViewContainer"]', timeout=120_000)
            print("Streamlit interface loaded.")
        except Exception:
            print("Streamlit interface selector was not detected; continuing with wait.")

        time.sleep(75)

        title = page.title()
        print(f"Page title: {title}")
        print(f"Final URL: {page.url}")

        screenshot_path = "streamlit_wake_result.png"
        page.screenshot(path=screenshot_path, full_page=False)
        print(f"Diagnostic screenshot saved as {screenshot_path}")

        browser.close()

    print("Wake cycle completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
