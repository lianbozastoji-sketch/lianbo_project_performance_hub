from __future__ import annotations

import os
import re
import sys
import time
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.sync_api import sync_playwright


WAKE_BUTTON_PATTERNS = (
    r"yes,? get this app back up",
    r"get this app back up",
    r"wake(?: it)? up",
    r"wake app",
    r"rerun",
)


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


def automation_url(value: str) -> str:
    """Open the lightweight background route instead of the normal user interface."""
    parsed = urlparse(normalize_url(value))
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["automation"] = "1"
    token = os.environ.get("AUTOMATION_TOKEN", "").strip()
    if token:
        query["token"] = token
    return urlunparse(parsed._replace(query=urlencode(query)))


def try_click_wake_button(page) -> bool:
    """Click Streamlit Community Cloud's sleep/wake prompt when it is shown."""
    for pattern in WAKE_BUTTON_PATTERNS:
        candidates = page.get_by_role("button", name=re.compile(pattern, re.IGNORECASE))
        try:
            count = min(candidates.count(), 5)
        except Exception:
            count = 0
        for index in range(count):
            candidate = candidates.nth(index)
            try:
                if candidate.is_visible():
                    print(f"Wake prompt detected; clicking button matching: {pattern}")
                    candidate.click(timeout=10_000)
                    return True
            except Exception as exc:
                print(f"Wake button click attempt failed: {exc}")
    return False


def wait_for_streamlit_app(page, timeout_seconds: int = 300) -> bool:
    """Wait until a real Streamlit session is visible, waking/reloading as needed."""
    deadline = time.monotonic() + timeout_seconds
    next_reload = time.monotonic() + 45

    while time.monotonic() < deadline:
        try:
            container = page.locator('[data-testid="stAppViewContainer"]')
            if container.count() and container.first.is_visible():
                print("Streamlit interface loaded.")
                return True
        except Exception:
            pass

        clicked = try_click_wake_button(page)
        if clicked:
            next_reload = time.monotonic() + 60
            time.sleep(8)
            continue

        if time.monotonic() >= next_reload:
            print("App is not ready yet; reloading the page.")
            try:
                page.reload(wait_until="domcontentloaded", timeout=120_000)
            except Exception as exc:
                print(f"Reload warning: {exc}")
            next_reload = time.monotonic() + 45

        time.sleep(3)

    return False


def save_diagnostics(page) -> None:
    screenshot_path = "streamlit_wake_result.png"
    try:
        page.screenshot(path=screenshot_path, full_page=False)
        print(f"Diagnostic screenshot saved as {screenshot_path}")
    except Exception as exc:
        print(f"Could not save diagnostic screenshot: {exc}")

    try:
        print(f"Page title: {page.title()}")
        print(f"Final URL: {page.url}")
    except Exception:
        pass


def main() -> int:
    try:
        app_url = automation_url(os.environ.get("STREAMLIT_APP_URL", ""))
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    print(f"Opening Streamlit app: {app_url}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1365, "height": 900},
            locale="sr-RS",
            timezone_id="Europe/Belgrade",
        )

        try:
            page.goto(app_url, wait_until="domcontentloaded", timeout=120_000)
        except Exception as exc:
            print(f"Initial navigation warning: {exc}")

        ready = wait_for_streamlit_app(page)
        if not ready:
            print("Streamlit app did not become ready within five minutes.", file=sys.stderr)
            save_diagnostics(page)
            browser.close()
            return 3

        # Wait for the automation page to report completion instead of a blind
        # 90 s sleep (synchronization + alerts can take longer on a cold start).
        print("Waiting for background synchronization and notification checks to finish.")
        finished = False
        deadline = time.monotonic() + 420
        while time.monotonic() < deadline:
            try:
                if page.get_by_text("Automation checks completed.").count():
                    finished = True
                    break
                if page.get_by_text(re.compile(r"Sign in|Login", re.IGNORECASE)).count() and page.locator("input[type=password]").count():
                    print("The app showed the login page: AUTOMATION_TOKEN in GitHub does not match Streamlit Secrets.", file=sys.stderr)
                    break
            except Exception:
                pass
            time.sleep(5)
        save_diagnostics(page)
        browser.close()

    if not finished:
        print("Automation did not report completion.", file=sys.stderr)
        return 4
    print("Wake cycle completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
