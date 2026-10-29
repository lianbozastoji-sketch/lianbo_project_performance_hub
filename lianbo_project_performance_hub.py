import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import importlib
import gspread
import contextlib as _contextlib
import ui_theme as ui
from ui_theme import theme_css
try:
    import oee_insights as oi
except ImportError:  # oee_insights.py not uploaded yet
    oi = None

# Files that are older than this application version (shown to the admin).
OUTDATED_SUPPORT_FILES = []
try:
    # v11.1: all code files live next to this file (no folders needed for upload).
    from google_sheets_engine import (
        install_google_sheets_engine,
        clear_google_sheets_read_cache,
        fresh_reads,
    )
except ImportError:
    try:
        from core.google_sheets_engine import (
            install_google_sheets_engine,
            clear_google_sheets_read_cache,
            fresh_reads,
        )
    except ImportError:
        # An older core/google_sheets_engine.py is still in the repository. The app
        # keeps working (without live-read protection) instead of crashing.
        from core.google_sheets_engine import (
            install_google_sheets_engine,
            clear_google_sheets_read_cache,
        )

        def fresh_reads():
            return _contextlib.nullcontext()

        OUTDATED_SUPPORT_FILES.append("google_sheets_engine.py")

if not hasattr(ui, "headline_html") and hasattr(ui, "drill_card_html"):
    OUTDATED_SUPPORT_FILES.append("ui_theme.py")
if not hasattr(ui, "drill_card_html"):
    # Old ui_theme.py in the repository: keep the app running with a plain card.
    import html as _ui_html

    def _plain_drill_card(title, badge, data):
        tiles = " · ".join(f"{t.get('label')}: {t.get('value')}" for t in data.get("tiles", []))
        return f"<div><b>{_ui_html.escape(str(title))}</b><br>{_ui_html.escape(tiles)}</div>"

    ui.drill_card_html = _plain_drill_card
    ui.drill_empty_html = lambda title, message: f"<div><b>{_ui_html.escape(str(title))}</b> — {_ui_html.escape(str(message))}</div>"
    OUTDATED_SUPPORT_FILES.append("ui_theme.py")

# Install a process-wide cache/rate limiter before any worksheet is read.
GOOGLE_SHEETS_ENGINE = install_google_sheets_engine()


def _live_reads(func):
    """Decorator: every sheet read inside a write path sees the live sheet.

    Row numbers used for updates are computed from these reads, so they must
    never come from the cache.
    """
    import functools as _functools

    @_functools.wraps(func)
    def wrapper(*args, **kwargs):
        with fresh_reads():
            return func(*args, **kwargs)
    return wrapper

from google.oauth2.service_account import Credentials
import base64
import os
import re
import unicodedata
import requests
import hmac
import json
import hashlib
import html
import math
import secrets
import threading
import time as time_module
import uuid


class _LazyModule:
    """Import heavy optional UI modules only when the selected page needs them."""

    def __init__(self, module_name):
        self.module_name = module_name
        self._module = None

    def __getattr__(self, name):
        if self._module is None:
            self._module = importlib.import_module(self.module_name)
        return getattr(self._module, name)


px = _LazyModule("plotly.express")
go = _LazyModule("plotly.graph_objects")

try:
    import extra_streamlit_components as stx
except Exception:
    stx = None
try:
    from missing_work_service import calculate_monthly_penalty
except ImportError:
    from services.missing_work_service import calculate_monthly_penalty
try:
    from activity_data_layer import (
        ALL_ACTIVITY_COLUMNS, all_activities_to_kpi_raw, normalize_app_rows,
        normalize_forms_rows, normalize_forms_rows_detailed, rows_to_matrix, person_name_key,
        parse_date_value, parse_time_value, detect_slash_date_order,
    )
except ImportError as _activity_import_error:
    st.error(
        "Fajl **activity_data_layer.py** u GitHub repozitorijumu je stara verzija. "
        "Zameni ga verzijom iz paketa v9.9.0 (kao i core/google_sheets_engine.py, "
        "services/missing_work_service.py i email_service.py), pa osveži aplikaciju."
    )
    st.caption(f"Detalj: {_activity_import_error}")
    st.stop()

# Automatic checks run whenever the deployed app is awake/used. For guaranteed 11:00 delivery,
# keep the Streamlit deployment active or invoke the manual check functions from an external scheduler.
from io import BytesIO
from zoneinfo import ZoneInfo
from datetime import time, date, timedelta, datetime

st.set_page_config(page_title="Lianbo Project Performance Hub", page_icon="📊", layout="wide")
if oi is None:
    st.error("Nedostaje fajl oee_insights.py u GitHub repozitorijumu. Postavi ga iz paketa v11 (isti folder kao glavni fajl).")
    st.stop()
if not hasattr(ui, "headline_html"):
    st.error("U GitHub repozitorijumu je stari ui_theme.py. Postavi ui_theme.py iz paketa v11 (isti folder kao glavni fajl).")
    st.stop()

# Browser cookie manager used by the real Remember me option.
class _LazyCookieManager:
    """The cookie component is created only when a cookie is really needed
    (login page, login, logout). Creating it on every run rendered an extra
    browser component on every click, caused an extra script run on every page
    and the "trouble loading the cookie_manager component" warning."""

    def __init__(self):
        self._instance = None

    def _manager(self):
        if self._instance is None:
            self._instance = stx.CookieManager(key="lianbo_cookie_manager")
        return self._instance

    def get_all(self, *args, **kwargs):
        return self._manager().get_all(*args, **kwargs)

    def get(self, *args, **kwargs):
        return self._manager().get(*args, **kwargs)

    def set(self, *args, **kwargs):
        return self._manager().set(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return self._manager().delete(*args, **kwargs)


COOKIE_MANAGER = _LazyCookieManager() if stx is not None else None
REMEMBER_COOKIE_NAME = "lianbo_project_hub_remember"
REMEMBER_DAYS = 30
PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 600_000
LOGIN_MAX_ATTEMPTS = 5
LOGIN_ATTEMPT_WINDOW_SEC = 15 * 60

APP_VERSION = "v11.3.1"
TARGET_ACTIVITIES_PER_DAY = 4
BACKGROUND_IMAGE = "project_department.jpg"
APP_LOGO_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAUAAAABMCAMAAAAr+55XAAAAkFBMVEXsXljxl5NSZJ1dq9Oi0ugrZqEnoNM5InIIgruYrMvlGA9njrmJlbrU1+PrQzs2PIFGM3tzxeXvg33ButGGeaf2wb5RO4L+/v4mVpUCmtIZU5UWTI8CeLTw6exUeaoCicTP2ecEaaYwR4npNy+puNL51tVBKnXmIxvV5vGQpsf1t7T3yMa5x9znKyNriLQ7NHu67e2TAAAAMHRSTlP///////////////////////////////////////////////////////////////9Ppz/1AAAPl0lEQVR42u2cC3uiOBeAuaqIaC8zA8WGYoVyUen//3ffOScXEsWK03Z3n89mn53BkATy5lxDdq34YvFcV/vlPomiV05cL77RYl1qULuTp6f7/vf9RADU6rynp4lb/wAcwucBr4kubfdPpwAnT9jqvv4BeKq9HNak11BvMqbqByCWSElbL4K1onVfR8dm8ekG9fgjgJKVEi7Pu3cnsnICnsPD6lpr9gPwHMF7oNdLmgI2uQeoExPzNxeW5xda5Dn7gufkef1pgOheJZtTegri04BfGfmSERMvaxAy/9bKvlmEmeOEYVMMz44VTdg5TgYN2An40VhZEdAoXdjs2acA1mexDaK8VoHrzs/CLMtC39n3b9/5WIclP5pWl6xlSbPmdGp1k6WyQXLcoEmcTCthFxb5ML0w658Dw0SfCWM0Jf56fnGeAQkoyTopegoO1UGlvzcaA740kSVdJ93x84oO8KkGadIZ/UP+LFWgzdAi7LuE3+QF+mRN/YlA2iT4Ao7WE8U9Znu9Acwz+Zp+D5CpSmdvwk6Mkq4zc2KFr02cGhgDLMy7BCfpjgiyxteXSaxEln8iE1FK/PICoYtXq5eu6xrcCtRKtn8DMB0CmA4APOGHDTpDdJKTFuvsQ4DI2CRYd6eD0Erkfw3wHhBReRrMdzEslA2uz4fHA2RhMjAxX5sXCwemnjQfAzRsx/AqiffLrwGokXAFnRc9QqlBgZUgRj3Cvo03DuZ4gHs/HZqXq/uIoQaa8g0CTBJXl780OVPSswQHALo9CclPbRXUZPyguBAAepGUwiOCUOF+LcBFMggwY32vYeEJLgBch0x7yPmyPmcHrQG3AShcg5+Qp/rIcWAuEnGB0wnW9Mv7SoB1pvnFtSYXqkVhOgfVYjEEcN2PoSnn3lgkcOipaXDZOIDMnUlm/AquSfzq+8lQFO2JiJtaziCU4TRnY3zKaIB7v6fm+0M2rtFmqzfo8lOAfthlPcC9WiRThn14UKorcTEOoPcyg4LC5NLVjPOrz0WEwrfwbrOZCwIsun0hwKKfSlfs3f5X2Ed5auLNPlB8tAikB7jAkNuXD8mHZNgJi/2+aDpdJIdF8BhgPXnmJJ5fCMTzjPh9FFBPKIPzZs+8vervfR1A5SFSsnrdWlmwPv6QUVtgaGMWnQIksRUOQ2FhnSaAnezV9KKfJvsxAN1nAWBGF8/PLu1rTY411+3LhO9ieS/PshcH6X4DQC5ywQnAPiSnuKRWIuicABTRMwfIedMImp8PtejS741iOAJgPnk2C7KpDd+BHhgD6jqiAuH0vUtqDATN4n0DwMAweCqUPgKY9wD3gxIYNccmsDeiprsIhsPycwDdAX6RayqsV5/uvJIvOenMvgtg8hmAaREXjmyuwpywF0Bj94Cp4HAUwL0pgbQ/oPNzFT3vHov6xSXV5PcflcB1EQfp+lhZw37MoxT7KgmM69yd9QwCY0/wSYsHJ0qfa1EXkSORBXwP+w4b2HweIEhgwwGmWjKtIs1eKI9CqHEA8emBqymwd7TffBxNy21oz9WU2A1GbW39jRPBdfkqgElWDAA8cra5cy1A6ONupBeoJy9is0WEg67MfGX9i9iIRvH0ZthxE47cGfwLgE7X7b8OIMhgfRFgdj3A2FUczCRNZr08jVMsPWUGRcf42wBCGtaACfsqgGuVC/cAjzKO6C8kkPkbLIFIjCU//gP3EWqRtMhcuRdB6Pm82XjfBzBNvxJgv6OjORH2GSfCYx/iN6tVOsz56bTMvS7ea0IiiMX9LwNELwztUjMS7LeyjnaugvR6gIoCJrYvs2ce5b3MZhwmk1nzswHQw2YedQ29/7YEFlnmKILNUSCdNsY7+n8hgSFCwJWh9Iz41VqOJ+TLUxUSIN6YUd9rASb/IEAMhfI8X5hjRP7gPraWIptfED4C6PlgydJQhiWz4yzjpT7KWgTAF9Th0Bfm8xqA+rbTdwNME+43pHdN+X6MvpngN9qnwH4zoRgLMCCArkwt3OMsjX+/zPuo2RUSiXFPsEk3/ka+wYVDBNoeetaIz7SXvPAXADT2/+SGlr6jmAT7Gj/FN462N5vVFwCywG0C6MncNPVxoXlmQdGJmaNJXuaugUuZS+5j52y/D4KmCf2PI0JX34MTux0XAKKCfVqF631RqA0wsWWYa7AS/KAOb3/uA9UwwNzHL88bP/MJIMAInjdcqoZ2WUSwDWGfAopXABAKyDD/fP0xQPNL0BiAHR58+XQu3CSp+n6pwpbG+GjCzyXo+6n1ZYD6h3v0Ay6PpuvZRsO3eaYVU5UbspGg0RAAgrTWmTZGekECjVUfBfBLc2HdC6MV/Oij0vB2qgEwUluK8KjUZzyc8eiv501feKKWqypXZH/QaJLHdYi91UAXkrrwWoDBFwFMB8iorDf5+AvzOYDGt1faO3cpmvb8jVFcLdjGn6gBOUU+GL4QwAueayBT/6cB9jv14cDGy8ln4TSMxwBMTgEGMXNNfjxEqV0dp2SMAM2v05fimUh7538DoLn7d4bgOgnZtQDXDgJMQYPzmYHP50FyPfMhWvHDgKH6CnVGw1mbenDpMKT+2SY0DxelZwGqbfbXcPiYUj74TSQ5UeF0nZmmLcpOv+CDLW/YmLMxkaP1euUAgXyBgZ0sGGDTYHWYhSHf9kOlhRt4D9LIOnt91ca5vLFV4Gm8FP5Zq/iMDvml2vG2YE118C8JfKN+dvpBOaoSEsh/rrUxQtWpQQmkJ6bZ8eG/fOEYx7PwwFy2H3e8LXdeVUle0ba6GBDzqFAVuVFQqyOw9R4iJnK5aZjTKAmNscZx8sv5SF10GT2hB0hFU+FAHe0LOUDxSwHsO4mvcrJFD3AhzwcmC9YgJD/rCja0n+yoU5oYyXRFPfKAZZ6tUHicjoMMUL2amIXGscThD/Qs8Pl8mFgGp+s6EOjX1xEAoTvLi6IIxFyLoKASFNqkClEXmT/7swuqE003ki362fedcrqGjOGMYuaF29H5B7/rLp7x1TORpguaAjo0EuDeD3qbbiY0IIC5/tVjj80we9mT+GF6BFCa4CuOe/8bJYdcpYhGNBzMhRHBqkOZLIwPzmTpRSbuO1mmrw8FQQB9QfQX8a2UIYARauEKhCjvirhI1wMBZZGcHOUGu+LDkjkrFMDgpgHGzjsAJCNYICrdOYuvzoHwtABLniOBmJhM4ArhF7cNsEOAqMN1HefJq14cftRNOmxEKJPxDpEHKwD47rDbBhi8v69W7zwGZY7Ob8Vp5QZTIYIBXjjTFXS9HRN45quc844lGADIdXOx0usErgbk7tF5X72/35AGn/ku/GuKAPlW7WLV01qJ7W80kppUCt8TiY5TJ75xgDmXQK6JAfiTFS9g3ISbfpdVcE9T2EeHA3y8ZRvIioVzh/jupmTdkKaA9b7i4clC1VBl0av+dIpd7xxnEd0oQBY4zh1geHt7u5v+ecSaxfRdlCk3bsxRNVSpWLFf1BP6T4HhbYjhEcAA6U3feJn+Yr1ecpHMuYaTnCmAPajCUX2B4a/LBNnOtkv4u9xBKakKL7EjK+2HtqSr3W9ao9Ju4cdvuhuXLe/JL1vxqN1ODMRwmJgPIxrSMGVb8qFsPgw8Tl6KW/EOhhMjx3CTYc8d/lGOALhQ9ICBEC0QQa6Y71Nu7RZ3vQTeTe+0rINp/afTy9FgaW2rgwVY7C0Uy4Yq24IruGD2spofLHz/nXXAv2xrvmSxfVgiRts6zKslVsetdYBB6FktDrM9WCUOc7B2SGpZVRWNDO3s0prTQ2BsfAhWbqtqCR3gXSqEAc/F4egmg5vYfmdtbcZvXwIYORqAhfIpQjP/LISP1ihPjf8QL9f6313O52x41W2F8z0cltv5toVpzLdLQMoeYIrWlqa5286BFMwAp2BjKwA+PxB8mjhAq2jGMNPD4bC12M6qDsgROs2XMMwB+rRLGMaaP2CzarmtlsD397bCp1Q0ztxCflUlnwudD8slDgztYV3bMTawFyFOpuRY3qa9SGqQoO7NxBRo/S8KYASrWtoHeFn4o93h5MrlwcL/jL0FAbJRfECMdssKALaHOYqUXcFEkIBdthZdL6sHuOIiSD1AAbE7Kiawh5/2cg63oZGQQFiu1t7y5aJx4LcACJStFuQbn2vjIFzjUcjtUU5E0ZneFaRQXJZ/gahJJMGdDvAIEzpiQfZyNL3D9wQWJWFBCSGAaNGggtQO7RcCRGHBCXKAIICkidvDA95tY2tuCZPGdbRVw3CFR1OGlG0OsNqWbInwtxW3ETA0B2hvq5ZGRqXFpS133DagnowKY7gITbkC4hrbwjmjTrMTO3mip1JapyNcCJodoZiHpQUTKHGtD6ikD4dtyb0CEwBjkjcJsPpNNqp6wFVomZRAZMEBbg9zWBgBFjwPn4zVA7QQYEUjIzsmAFbbHV8aBAhSbG1pBKuyR8aBDEVw+uY8Csnd2vJjwZ+7xxMzKTGxtl+fBUqoFtx8DNC2HkoOkKQKJbDdoa/YchmzWgmw3YoZcgnkem4jQHsIIAwD0yOLyWxcDpTAdqwE4uNBAkG2ue6OB4iApm8UB8MSwDhKkCIugI/IjZc/zkJ4kNay9VjoxDSeB8goUgGANr0jAiyhCnXG3gEoS6pwafcA0XHAXUvYwwEJBJ+O5guhtzQMqjA5EV0CI7KBv4kU2UNuA0tpA+FPUOYHdhVAUNE7QhWhSxPvpanj4o7KH8f5Faj/k4i93dr6Grz9YqMAzvnzGWoO+Ned8MI2+VzwhlXvhWE1URZOvPCOO1cr0gECVRhmR16YnKrwwiV5YXt+4BKIawNqfUArAmPweAA9biW9sEVwUZTHA2QLLj2tCq9gWr0g5o+Pj0XxGEU6IlisZaung6OykFLFVigTYnIk9jDEA8RgFSkA98IWj9xIAnkkJ+4KFTYAUhyIcQpEmvO5cEgcIEmgBIi953Nu5kqLIkcbn7vklh/fgUvGNRKoURH84OUlyhPaUoUrFPprS1kK08nwIqKYgcnKUmUEqNOxzCfE3WgnMxG8G8mBwGsyObRo3z60TDWk2zSG6MHA0e+0l6AsxVaj6Q+5GmBsC6ECwwTxwhA+25IitD38DcH/1/3A40YU1fOo4iiTmIsbiNKyfwAOx7vLg3ARpUWarIQe4gi8U+q5+A/AEz1VArizuMCBteUI6RaLWXy7ZQTAnSXzQHBQ298UtR22ywc0+WD6hnPsH4Cmp9gJDeaBdYt7Hoclz7wqi/0AvBRt7MjJxxHuT9AWHIZZc4yzIO602h+AYwqeZUJcwh3zPAqsoHWbzuN6gLG+O0MxJoUt7KYV+FqAKHi2lkfEP8W6tsOtS9xx+R+BPrbeP/8jsAAAAABJRU5ErkJggg=="
SERVICE_ACCOUNT_FILE = "service_account.json"

KPI_SHEET_ID = "1f-mLNXA-oPlc-Q9z8vAh7RKzvblZvdYSLT0sq6aAgJY"
KPI_SHEET_NAME = "Form Responses 1"
# Unified activity database. Google Forms and in-app TASK_ACTIVITY are synchronized here.
ALL_ACTIVITIES_SHEET_ID = "1Iclk5l5XGil-c-TDJ08WIhkA3Pk0q-kqcBrMxm09i9M"
ALL_ACTIVITIES_SHEET_NAME = "all_activities"
# Read-only Google Forms source with technician downtime interventions.
PROCESS_DOWNTIME_SHEET_ID = "1HdC357shptB8qWvaKzRqZ925mikdv7yui1mLiw2bujs"
PROCESS_DOWNTIME_SHEET_NAME = "Form Responses 1"
PROCESS_DOWNTIME_SOURCE = "DOWNTIME"
PROCESS_DOWNTIME_CATEGORY = "Zastoji / intervencije"
ACTIVE_TECH_SHEET_NAME = "Aktivni Tehničari"
# New normalized missing-work-time log. The legacy Active Technicians sheet stays untouched.
MISSING_WORK_TIME_SHEET_NAME = "MISSING_WORK_TIME"
TECHNICIANS_SHEET_NAME = "Technicians"
TASKS_SHEET_NAME = "TASKS"
TASK_ACTIVITY_SHEET_NAME = "TASK_ACTIVITY"
EMAIL_LOG_SHEET_NAME = "EMAIL_LOG"
ENVA_MINUTES = 5
TECHNICIAN_TARGETS_SHEET_NAME = "TECHNICIAN_TARGETS"
# Technician photos are stored as compressed Base64 strings in TECHNICIAN_TARGETS.
# Google Drive upload is intentionally not used because standard Gmail Drive accounts do not support service-account storage quota.
TECHNICIAN_PHOTO_FOLDER_ID = ""
OEE_SHEET_ID = "15_eNq1q7zJIgQ7wQEaEAR1s-VjNp-Kub1dSv4mz5XRo"
OEE_INPUT_SHEET_NAMES = ["OEE_input", "OEE_INPUT", "OEE Input", "OEE input"]
OEE_MASTER_SHEET_NAMES = ["MASTER_DATA", "MASTER DATA", "Master Data"]

# OEE IWON (Improved Weekly OEE Necessary) planning database.
# This is intentionally separate from the real OEE database: IWON is a management target scenario.
OEE_IWON_SHEET_ID = "1Q2V7VZlSfDH3ZAb80j5hoprDkaWyRuS9COV7wzDqVnw"
OEE_IWON_TARGET_SHEET_NAMES = ["Admin podešavanja", "OEE_IWON_TARGETS", "Admin podesavanja"]
OEE_IWON_RESULT_SHEET_NAMES = ["OEE_IWON"]
OEE_IWON_TARGET_COLUMNS = ["Year", "CW", "Project", "Process", "Target_OEE", "Updated_By", "Updated_At"]
OEE_IWON_RESULT_COLUMNS = ["Year", "CW", "Project", "Process", "Machine", "Availability", "Performance", "Quality", "OEE", "Calculated_At"]

BOTTLENECK_SHEET_ID = "18g4FPWu7SWET0bKFS6XZuabhxUrm0sZy1K_j2aetFwE"
BOTTLENECK_SHEET_NAME = "Form Responses 1"

# Central BN database: separate Google Spreadsheet with two worksheets.
BN_DATABASE_SHEET_ID = "1dxsLQkIXYFC6YjNqqX1YTiFZk6DoqzeKh00UXHgrmfE"
BN_MACHINES_SHEET_NAME = "BN_MACHINES"
BN_RECORDS_SHEET_NAME = "BN_RECORDS"
BN_RECORD_COLUMNS = [
    "BN_ID", "Source", "Source_ID", "Date", "Machine_ID", "Project", "Machine",
    "BN_Time", "Station", "Entered_By", "Entered_By_Username", "Entered_By_Email", "Created_At", "Updated_At",
]
BN_DEVIATION_LIMIT_SEC = 3.0

LINE_VERIFICATION_SHEET_ID = "1jhc_JfbjPLWT9QRfIqDeVeIirKWJrWQBexFMtLc573c"
LINE_VERIFICATION_SHEET_NAMES = ["Form_Responses", "Form Responses 1", "Form responses 1"]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

PROJECT_ORDER = ["APP350", "APP550", "EMR4"]

# =====================================================
# LOGIN / AUTHORISATION GOOGLE SHEET
# =====================================================
AUTH_SHEET_ID = "1os2824HIUTJkbCkiskM3s5gXdv0zOEL0VUL1CrC6O_s"
USER_SHEET_NAMES = ["User&Password", "USERS"]
PERMISSION_SHEET_NAMES = ["Autorisation1", "Authorisation1", "PERMISSIONS"]


@st.cache_data(show_spinner=False)
def get_base64_image(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    return None


def _background_image_url():
    """Serve the background as a static file instead of ~300 KB of Base64.

    Embedding the picture in CSS re-sent it to the browser on every click,
    which was one of the main causes of slow interaction on phones. With
    ``server.enableStaticServing`` (see .streamlit/config.toml) the browser
    downloads it once and caches it. The Base64 path remains as a fallback
    when the static folder is missing.
    """
    static_path = os.path.join("static", BACKGROUND_IMAGE)
    if os.path.exists(static_path):
        return f"app/static/{BACKGROUND_IMAGE}"
    # No static folder: plain dark background. Base64 would re-send ~200 KB on
    # every click and make the app slow, so it is no longer used.
    return None


bg_url = _background_image_url()
if bg_url:
    background_css = f"""
    .stApp {{
        background-image:
            linear-gradient(135deg, rgba(3, 10, 18, 0.92), rgba(7, 19, 34, 0.88), rgba(3, 10, 18, 0.94)),
            url("{bg_url}");
        background-size: cover;
        background-position: center;
        background-attachment: fixed;
    }}
    .stApp::before {{
        content: "";
        position: fixed;
        inset: 0;
        z-index: -1;
        background: radial-gradient(circle at 18% 8%, rgba(37, 99, 235, 0.18), transparent 34%),
                    radial-gradient(circle at 82% 18%, rgba(14, 165, 233, 0.12), transparent 30%),
                    rgba(2, 6, 23, 0.38);
        backdrop-filter: blur(2px);
    }}
    """
else:
    background_css = ".stApp { background: radial-gradient(circle at top left, #10233d 0, #07111f 42%, #030712 100%); }"

# v10: one consolidated industrial design system (ui_theme.py) replaces the
# eleven overlapping CSS blocks of earlier versions.
st.markdown(theme_css(background_css), unsafe_allow_html=True)

SELECT_ON_FOCUS_JS = """
<script>
(function () {
  const doc = window.parent && window.parent.document;
  if (!doc || doc.__lianboSelectOnFocus) { return; }
  doc.__lianboSelectOnFocus = true;
  doc.addEventListener("focusin", function (event) {
    const el = event.target;
    if (el && el.tagName === "INPUT" && (el.type === "number" || el.getAttribute("data-testid") === "stNumberInputField")) {
      setTimeout(function () { try { el.select(); } catch (e) {} }, 0);
    }
  }, true);
})();
</script>
"""


def install_select_on_focus():
    """Clicking a number field selects its value (typing replaces it instead of '0.00' + digits)."""
    try:
        components.html(SELECT_ON_FOCUS_JS, height=0)
    except Exception:
        pass


@st.cache_resource
def get_client():
    """Create Google Sheets/Drive client.

    Streamlit Cloud: reads credentials from st.secrets["gcp_service_account"].
    Local PC: falls back to service_account.json if present.
    """
    try:
        if "gcp_service_account" in st.secrets:
            service_account_info = dict(st.secrets["gcp_service_account"])
            if "private_key" in service_account_info:
                service_account_info["private_key"] = service_account_info["private_key"].replace("\\n", "\n")
            creds = Credentials.from_service_account_info(service_account_info, scopes=SCOPES)
        else:
            creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        return gspread.authorize(creds)
    except FileNotFoundError:
        raise FileNotFoundError(
            "Google credentials not found. On Streamlit Cloud add [gcp_service_account] in Secrets, "
            "or upload service_account.json for local/private deployment."
        )


@st.cache_data(ttl=180)
def load_worksheet(sheet_id, sheet_name):
    ws = get_worksheet(sheet_id, sheet_name)
    return pd.DataFrame(ws.get_all_records())

@st.cache_resource
def get_spreadsheet(sheet_id):
    """Open and cache a spreadsheet handle without sleeping inside the cache lock.

    Request throttling is handled by the process-wide Google Sheets engine.  A
    quota error is allowed to fail quickly so one cold cache miss cannot block
    every Streamlit session for more than a minute.
    """
    return get_client().open_by_key(sheet_id)


@st.cache_resource(ttl=1800)
def get_worksheet(sheet_id, sheet_name):
    """Reuse worksheet handles; data reads still use the separate TTL cache."""
    return get_spreadsheet(sheet_id).worksheet(sheet_name)


@st.cache_data(ttl=180)
def load_all_activities():
    """Read the unified ALL_ACTIVITIES database."""
    ws = get_worksheet(ALL_ACTIVITIES_SHEET_ID, ALL_ACTIVITIES_SHEET_NAME)
    values = ws.get_all_values()
    if not values:
        return pd.DataFrame(columns=ALL_ACTIVITY_COLUMNS)
    headers = [str(x).strip() for x in values[0]]
    rows = [r + [""] * max(0, len(headers) - len(r)) for r in values[1:]]
    df = pd.DataFrame([r[:len(headers)] for r in rows], columns=headers)
    for col in ALL_ACTIVITY_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[ALL_ACTIVITY_COLUMNS].copy()


@st.cache_data(ttl=180, show_spinner=False)
def build_kpi_dataset():
    """ALL_ACTIVITIES -> prepared KPI frame, cached (parsing thousands of rows on
    every click made the KPI page slow). Cleared after every synchronization."""
    all_activities_df = load_all_activities()
    if all_activities_df.empty:
        return all_activities_df, None, []
    technicians, _ = load_technicians_master()
    all_activities_for_kpi = all_activities_df.reset_index(drop=True)
    df_kpi_raw = all_activities_to_kpi_raw(all_activities_for_kpi, technicians).reset_index(drop=True)
    raw_sources = all_activities_for_kpi["Source"].fillna("").astype(str).str.strip().str.upper()
    source_labels = {
        "FORM": "KPI formular",
        "APP": "Work Tickets",
        PROCESS_DOWNTIME_SOURCE: "Zastoji tehničara",
    }
    df_kpi_raw["Izvor"] = raw_sources.map(source_labels).fillna(raw_sources.replace("", "Nepoznat izvor"))
    df_kpi_raw["_Activity_Source"] = raw_sources
    df_kpi_raw["_Effective_Duration_Minutes"] = all_activities_for_kpi["Effective_Duration"]
    df_kpi, kpi_missing = prepare_kpi_data(df_kpi_raw)
    return all_activities_df, df_kpi, kpi_missing


def _yes_value(value):
    return str(value).strip().upper() in ["YES", "Y", "DA", "TRUE", "1", "YAS"]


def parse_mixed_datetime(value):
    """Parse ISO, European (23.10.2026 / 23.10.2026. / 23. 10. 2026.), slash,
    two-digit-year and Google serial dates without swapping day and month."""
    return parse_date_value(value)


def parse_mixed_datetime_series(series):
    """Series variant of :func:`parse_mixed_datetime` (cached per distinct value)."""
    if series is None:
        return pd.Series(dtype="datetime64[ns]")
    values = pd.Series(series)
    if values.empty:
        return pd.Series(dtype="datetime64[ns]", index=values.index)
    cache = {}

    def parse_one(value):
        try:
            key = (type(value).__name__, value if not isinstance(value, float) or value == value else "nan")
            hash(key)
        except TypeError:
            return parse_date_value(value)
        if key not in cache:
            cache[key] = parse_date_value(value)
        return cache[key]

    return pd.to_datetime(values.map(parse_one), errors="coerce")


def parse_time_series(series):
    """Parse a column of clock times where formats can be mixed (08:30, 8:30:00,
    8.30, Sheets fractions). Pandas otherwise infers one format from the first
    row and turns every differently formatted row into NaT, which silently
    removed entries from KPI."""
    values = pd.Series(series)
    return values.map(parse_time_value)


def is_weekend_day(value):
    """Returns True for Saturday/Sunday. Used to block missing-time alerts and logs."""
    try:
        ts = parse_mixed_datetime(value)
        if pd.isna(ts):
            return False
        return int(ts.weekday()) >= 5
    except Exception:
        return False


def is_workday(value):
    """Monday-Friday only. Weekends are not treated as missing-entry days."""
    return not is_weekend_day(value)


@st.cache_data(ttl=180)
def load_technicians_master():
    """Reads the new master technician database from the 'Technicians' sheet."""
    required = [
        "Technician_ID",
        "Technician_Name",
        "Username",
        "Position",
        "Department",
        "Email",
        "Active",
        "Picture",
        "Receive_Task_Email",
        "Receive_Task_Reminder",
        "Receive_Missing_Time_Email",
        "Receive_BN_Email",
        "Supervisor",
    ]

    try:
        ws = get_worksheet(KPI_SHEET_ID, TECHNICIANS_SHEET_NAME)
        values = ws.get_all_values()
        if not values:
            return pd.DataFrame(columns=required), []

        header = [str(h).replace("\ufeff", "").replace("​", "").strip() for h in values[0]]
        keep_idx = [i for i, h in enumerate(header) if h]
        header = [header[i] for i in keep_idx]
        rows = [[row[i] if i < len(row) else "" for i in keep_idx] for row in values[1:]]
        df = pd.DataFrame(rows, columns=header)
        df = clean_columns(df)

        def norm_col(x):
            txt = unicodedata.normalize("NFKD", str(x)).replace("\ufeff", "").replace("​", "")
            return re.sub(r"[^a-z0-9]+", "", txt.strip().lower())

        aliases = {
            "technicianid": "Technician_ID",
            "techid": "Technician_ID",
            "id": "Technician_ID",
            "technicianname": "Technician_Name",
            "technician": "Technician_Name",
            "tehnicar": "Technician_Name",
            "name": "Technician_Name",
            "username": "Username",
            "position": "Position",
            "department": "Department",
            "email": "Email",
            "emailaddress": "Email",
            "active": "Active",
            "aktivan": "Active",
            "picture": "Picture",
            "photo": "Picture",
            "photobase64": "Picture",
            "receivetaskemail": "Receive_Task_Email",
            "taskemail": "Receive_Task_Email",
            "receiveemail": "Receive_Task_Email",
            "receivetaskreminder": "Receive_Task_Reminder",
            "taskreminder": "Receive_Task_Reminder",
            "reminderemail": "Receive_Task_Reminder",
            "receivemissingtimeemail": "Receive_Missing_Time_Email",
            "receivemissingtime": "Receive_Missing_Time_Email",
            "missingtimeemail": "Receive_Missing_Time_Email",
            "receivebnemail": "Receive_BN_Email",
            "bnemail": "Receive_BN_Email",
            "receivebottleneckemail": "Receive_BN_Email",
            "supervisor": "Supervisor",
            "issupervisor": "Supervisor",
            "alertonly": "Supervisor",
        }
        rename_map = {}
        for col in df.columns:
            key = norm_col(col)
            if key in aliases:
                rename_map[col] = aliases[key]
        df = df.rename(columns=rename_map)

        for col in required:
            if col not in df.columns:
                df[col] = ""

        df = df[required].copy()
        for col in required:
            df[col] = df[col].astype(str).replace({"nan": "", "None": ""}).str.strip()

        # Default blank Active and Receive_Task_Email to YES for newly created rows.
        df.loc[df["Active"].eq(""), "Active"] = "YES"
        for notify_col in ["Receive_Task_Email", "Receive_Task_Reminder", "Receive_Missing_Time_Email", "Receive_BN_Email"]:
            df.loc[df[notify_col].eq(""), notify_col] = "YES"
        # Supervisor means alert-only user: receives selected notifications but is not
        # checked for missing work time and is not penalized in technician evaluation.
        df.loc[df["Supervisor"].eq(""), "Supervisor"] = "NO"
        df = df[df["Technician_Name"].astype(str).str.strip() != ""]
        return df, []

    except Exception as e:
        return pd.DataFrame(columns=required), [f"Technicians sheet could not be loaded: {type(e).__name__}: {e}"]


@st.cache_data(ttl=60)
def load_active_technicians():
    """Returns active technicians from the new 'Technicians' master sheet.

    Fallback: if the new sheet is not available yet, the old 'Aktivni Tehničari'
    sheet is still used so the existing KPI module does not break during migration.
    """
    technicians_master, master_errors = load_technicians_master()
    if not technicians_master.empty:
        active = technicians_master[
            technicians_master["Active"].apply(_yes_value)
            & ~technicians_master["Supervisor"].apply(_yes_value)
        ]
        return sorted(list(dict.fromkeys(active["Technician_Name"].dropna().astype(str).str.strip().tolist())))

    try:
        ws = get_worksheet(KPI_SHEET_ID, ACTIVE_TECH_SHEET_NAME)
        values = ws.get_all_values()

        technicians = []
        for row in values[1:]:
            name = str(row[0]).strip() if len(row) >= 1 else ""
            active = str(row[1]).strip().upper() if len(row) >= 2 else "DA"

            if name and active in ["DA", "YES", "TRUE", "1"]:
                technicians.append(name)

        return sorted(list(dict.fromkeys(technicians)))

    except Exception as e:
        st.error("Greška pri čitanju aktivnih tehničara. Proveri tab 'Technicians'.")
        if master_errors:
            st.write(master_errors)
        st.write(e)
        return []


@st.cache_data(ttl=60)
def load_technician_targets():
    """
    Čita Google Sheet tab za targete tehničara.

    Očekivane kolone:
    Technician | Active | Period Type | Target Activities/Hour | Target Activities | Target Utilization

    Namerno ne koristi load_worksheet()/get_all_records(), jer Google Sheet ponekad
    ima prazne dodatne kolone i tada get_all_records() može da pukne.
    """
    required = [
        "Technician",
        "Active",
        "Period Type",
        "Target Activities/Hour",
        "Target Activities",
        "Target Utilization",
    ]
    optional = [
        "Department",
        "Position",
        "Photo_File_ID",
        "Photo_File_Name",
        "Photo_Updated_At",
        "Photo_Base64",
    ]

    try:
        def norm(x):
            return str(x).strip().lower().replace(" ", "").replace("_", "")

        target_norm = norm(TECHNICIAN_TARGETS_SHEET_NAME)
        ws = None
        worksheets = []
        available_tabs = []

        # 1) Exact title match through the cached worksheet handle (no metadata
        #    request on every cache refresh).
        try:
            ws = get_worksheet(KPI_SHEET_ID, TECHNICIAN_TARGETS_SHEET_NAME)
        except Exception:
            ws = None

        # 2) Tolerant match: ignores spaces/underscores/case
        if ws is None:
            worksheets = get_spreadsheet(KPI_SHEET_ID).worksheets()
            available_tabs = [candidate.title for candidate in worksheets]
            for candidate in worksheets:
                if norm(candidate.title) == target_norm:
                    ws = candidate
                    break

        if ws is None:
            return pd.DataFrame(), [
                f"TECHNICIAN_TARGETS tab nije pronađen. Dostupni tabovi: {', '.join(available_tabs)}"
            ]

        values = ws.get_all_values()
        if not values:
            return pd.DataFrame(), ["TECHNICIAN_TARGETS tab je prazan"]

        raw_header = [str(h) for h in values[0]]
        # Skidamo BOM/nevidljive znakove i prazne dodatne kolone iz Google Sheeta.
        header = []
        keep_idx = []
        for i, h in enumerate(raw_header):
            hh = str(h).replace("\ufeff", "").replace("​", "").strip()
            if hh != "":
                header.append(hh)
                keep_idx.append(i)

        data_rows = []
        for row in values[1:]:
            data_rows.append([(row[i] if i < len(row) else "") for i in keep_idx])

        targets = pd.DataFrame(data_rows, columns=header)
        targets = clean_columns(targets)

        # Tolerantno mapiranje kolona: prihvata razmake, underscore, %, /, BOM i case razlike.
        import re
        import unicodedata

        def norm_col(x):
            txt = unicodedata.normalize("NFKD", str(x))
            txt = txt.replace("\ufeff", "").replace("​", "")
            txt = txt.strip().lower()
            return re.sub(r"[^a-z0-9]+", "", txt)

        aliases = {
            "technician": "Technician",
            "tehnician": "Technician",
            "technicar": "Technician",
            "tehnicar": "Technician",
            "active": "Active",
            "aktivan": "Active",
            "periodtype": "Period Type",
            "period": "Period Type",
            "targetactivitieshour": "Target Activities/Hour",
            "targetactivitiesperhour": "Target Activities/Hour",
            "targetactivityhour": "Target Activities/Hour",
            "targetaph": "Target Activities/Hour",
            "targetactivities": "Target Activities",
            "targetactivity": "Target Activities",
            "targetutilization": "Target Utilization",
            "targetutilisation": "Target Utilization",
            "targetutilizationpercent": "Target Utilization",
            "targetutilisationpercent": "Target Utilization",
            "department": "Department",
            "position": "Position",
            "photofileid": "Photo_File_ID",
            "photoid": "Photo_File_ID",
            "photofilename": "Photo_File_Name",
            "photoname": "Photo_File_Name",
            "photoupdatedat": "Photo_Updated_At",
            "photoupdated": "Photo_Updated_At",
            "photobase64": "Photo_Base64",
            "base64photo": "Photo_Base64",
            "photoencoded": "Photo_Base64",
        }

        rename_map = {}
        for col in targets.columns:
            key = norm_col(col)
            if key in aliases:
                rename_map[col] = aliases[key]
        targets = targets.rename(columns=rename_map)

        # If the sheet contains duplicate canonical columns (for example an extra
        # Technician column created by a previous faulty save), collapse them.
        # For each logical column we keep the first non-empty value from left to right.
        canonical_order = required + optional
        collapsed = pd.DataFrame(index=targets.index)
        for canonical in canonical_order:
            matching_cols = [c for c in targets.columns if str(c) == canonical]
            if matching_cols:
                temp = targets[matching_cols].astype(str).replace({"nan": "", "None": ""})
                if isinstance(temp, pd.Series):
                    collapsed[canonical] = temp
                else:
                    collapsed[canonical] = temp.bfill(axis=1).iloc[:, 0]
        # Preserve any not-yet-recognized columns only if they do not collide with required names.
        for col in targets.columns:
            if col not in collapsed.columns and str(col).strip() not in ["", "nan", "None"]:
                collapsed[col] = targets[col]
        targets = collapsed
        # Final safety: remove any duplicated column names after collapsing.
        targets = targets.loc[:, ~targets.columns.duplicated()].copy()

        # Fallback po poziciji ako Google Sheets vrati čudan/nevidljiv karakter u headeru.
        if "Technician" not in targets.columns and len(targets.columns) >= 1:
            targets = targets.rename(columns={targets.columns[0]: "Technician"})
        if "Active" not in targets.columns and len(targets.columns) >= 2:
            targets = targets.rename(columns={targets.columns[1]: "Active"})
        if "Period Type" not in targets.columns and len(targets.columns) >= 3:
            targets = targets.rename(columns={targets.columns[2]: "Period Type"})
        if "Target Activities/Hour" not in targets.columns and len(targets.columns) >= 4:
            targets = targets.rename(columns={targets.columns[3]: "Target Activities/Hour"})
        if "Target Activities" not in targets.columns and len(targets.columns) >= 5:
            targets = targets.rename(columns={targets.columns[4]: "Target Activities"})
        if "Target Utilization" not in targets.columns and len(targets.columns) >= 6:
            targets = targets.rename(columns={targets.columns[5]: "Target Utilization"})

        missing = [col for col in required if col not in targets.columns]
        if missing:
            return pd.DataFrame(), [
                "Nedostaju kolone: " + ", ".join(missing),
                "Pronađene kolone: " + ", ".join([str(c) for c in targets.columns]),
                "Originalne kolone iz sheeta: " + ", ".join([str(c) for c in header]),
                "Tab koji je pročitan: " + ws.title,
            ]

        for col in optional:
            if col not in targets.columns:
                targets[col] = ""

        targets = targets[required + optional].copy()
        targets["Technician"] = targets["Technician"].astype(str).str.strip()
        targets["Active"] = targets["Active"].astype(str).str.strip().str.upper()
        targets["Period Type"] = targets["Period Type"].astype(str).str.strip().str.title()

        targets["Target Activities/Hour"] = targets["Target Activities/Hour"].apply(lambda x: normalize_float_value(x, 0.0))
        targets["Target Activities"] = targets["Target Activities"].apply(lambda x: normalize_float_value(x, 0.0))
        targets["Target Utilization"] = targets["Target Utilization"].apply(lambda x: normalize_percent_value(x, 85.0))
        # Active kolona je tolerantna:
        # - prihvata YES/Y/DA/TRUE/1
        # - prihvata i čestu grešku u unosu "YAS"
        # - blokira samo eksplicitno neaktivne vrednosti NO/N/NE/FALSE/0
        active_values = targets["Active"].astype(str).str.strip().str.upper()
        inactive_values = ["NO", "N", "NE", "FALSE", "0"]
        active_mask = ~active_values.isin(inactive_values)

        targets = targets[
            (targets["Technician"] != "")
            & active_mask
        ]

        return targets, []

    except Exception as e:
        return pd.DataFrame(), [f"TECHNICIAN_TARGETS nije mogao da se učita: {type(e).__name__}: {e}"]

def grade_from_score(score):
    score = 0 if pd.isna(score) else float(score)
    if score >= 90:
        return "A", "Excellent"
    if score >= 80:
        return "B", "Very Good"
    if score >= 70:
        return "C", "Good"
    if score >= 60:
        return "D", "Needs Improvement"
    return "E", "Poor"


def score_ratio(actual, target):
    if pd.isna(actual) or pd.isna(target) or target <= 0:
        return 0.0
    return min(float(actual) / float(target), 1.0) * 100



def normalize_percent_value(value, default=85.0):
    """Return a clean 0-100 percentage for values coming from Google Sheets.

    Handles these common cases:
    - 85
    - 85%
    - 0.85
    - 8500 or 8500% caused by percent-formatted Sheet cells after raw write
    """
    try:
        txt = str(value).replace(",", ".").replace("%", "").strip()
        if txt == "" or txt.lower() in ["nan", "none"]:
            return float(default)
        num = float(txt)
        if not math.isfinite(num) or num < 0:
            return float(default)
        if num <= 1:
            num *= 100
        elif num > 100:
            # Google Sheets can expose 85 entered into a percent-formatted cell
            # as 8500/8500%.  Values just above 100 are ambiguous and invalid,
            # so never silently turn 105 into 1.05%.
            if num < 1000 or num > 10000:
                return float(default)
            num /= 100
        return max(0.0, min(float(num), 100.0))
    except Exception:
        return float(default)


def normalize_float_value(value, default=0.0):
    try:
        txt = str(value).replace(",", ".").replace("%", "").strip()
        if txt == "" or txt.lower() in ["nan", "none"]:
            return default
        number = float(txt)
        return number if math.isfinite(number) else default
    except Exception:
        return default


def parse_ui_date(value, fallback=None):
    """Parses user-facing date text and avoids mobile browser DateInput issues."""
    if fallback is None:
        fallback = date.today()
    if isinstance(value, date):
        return value
    parsed = parse_mixed_datetime(value)
    if pd.isna(parsed):
        return fallback
    return parsed.date()


def parse_ui_time(value, fallback=None):
    """Parses HH:MM text and avoids mobile browser TimeInput React issues."""
    if fallback is None:
        fallback = time(8, 0)
    if isinstance(value, time):
        return value
    txt = str(value).strip().replace(".", ":")
    for fmt in ["%H:%M", "%H:%M:%S"]:
        try:
            return datetime.strptime(txt, fmt).time().replace(second=0, microsecond=0)
        except ValueError:
            continue
    parsed = pd.to_datetime(txt, errors="coerce")
    if pd.isna(parsed):
        return fallback
    return parsed.time().replace(second=0, microsecond=0)


def format_ui_time(value):
    """Returns HH:MM from time-like values."""
    if isinstance(value, time):
        return value.strftime("%H:%M")
    text = str(value or "").strip().replace(".", ":")
    if not text or text.casefold() in {"nan", "none", "nat"}:
        return ""
    for fmt in ["%H:%M", "%H:%M:%S"]:
        try:
            return datetime.strptime(text, fmt).strftime("%H:%M")
        except (TypeError, ValueError):
            continue
    return ""

def _column_number_to_letter(col_num):
    """Converts 1-based column number to Excel/Sheets column letter."""
    result = ""
    while col_num:
        col_num, remainder = divmod(col_num - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _get_note_from_notes_matrix(notes, row_idx, col_idx):
    """
    Reads Google Sheets note from gspread get_notes() output.
    Supports both list-of-lists and dict style outputs, depending on gspread version.
    row_idx and col_idx are 1-based.
    """
    if notes is None:
        return ""

    try:
        if isinstance(notes, dict):
            a1 = f"{_column_number_to_letter(col_idx)}{row_idx}"
            return str(notes.get(a1, "") or "").strip()

        if isinstance(notes, list):
            r = row_idx - 1
            c = col_idx - 1
            if r < len(notes) and isinstance(notes[r], list) and c < len(notes[r]):
                return str(notes[r][c] or "").strip()
    except Exception:
        return ""

    return ""




def _get_or_create_worksheet(sheet_id, sheet_name, headers=None):
    """Return worksheet; create it with headers only if it really does not exist.

    Uses the cached worksheet handle (no metadata request per call) and reads only
    the header row instead of the whole sheet.
    """
    try:
        ws = get_worksheet(sheet_id, sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        get_worksheet.clear()
        ws = get_spreadsheet(sheet_id).add_worksheet(title=sheet_name, rows=1000, cols=max(len(headers or []), 5))
        if headers:
            ws.update("A1", [headers])
        return ws

    if headers:
        existing = [str(x).strip() for x in ws.row_values(1)]
        if not existing:
            ws.update("A1", [headers])
        elif existing[:len(headers)] != headers:
            # Keep existing data, only normalize header row.
            ws.update(f"A1:{_column_number_to_letter(len(headers))}1", [headers])
    return ws


def _normalize_date_string(value):
    ts = parse_mixed_datetime(value)
    if pd.isna(ts):
        return ""
    return ts.strftime("%d.%m.%Y")


@st.cache_data(ttl=60)
def load_missing_work_time_log():
    """Read normalized MISSING_WORK_TIME sheet.

    Expected columns:
    Timestamp | Technician_ID | Technician_Name | Missing_Date | Note
    """
    headers = ["Timestamp", "Technician_ID", "Technician_Name", "Missing_Date", "Note"]
    try:
        ws = _get_or_create_worksheet(KPI_SHEET_ID, MISSING_WORK_TIME_SHEET_NAME, headers)
        values = ws.get_all_values()
        if not values or len(values) <= 1:
            return pd.DataFrame(columns=headers)
        return _missing_work_values_to_frame(values, headers)
    except Exception:
        return pd.DataFrame(columns=headers + ["Missing_Date_Norm"])


def _missing_work_values_to_frame(values, headers):
    """Build the MISSING_WORK_TIME frame; tolerant to extra/short columns."""
    if not values or len(values) <= 1:
        return pd.DataFrame(columns=headers + ["Missing_Date_Norm"])
    header = [str(h).replace("\ufeff", "").replace("​", "").strip() for h in values[0]]
    width = len(header)
    rows = [list(r[:width]) + [""] * max(0, width - len(r)) for r in values[1:]]
    df = pd.DataFrame(rows, columns=header)
    df = df.loc[:, [c for c in df.columns if str(c).strip()]]
    df = clean_columns(df)
    df = df.loc[:, ~df.columns.duplicated()]
    for col in headers:
        if col not in df.columns:
            df[col] = ""
    df = df[headers].copy()
    for col in headers:
        df[col] = df[col].astype(str).replace({"nan": "", "None": ""}).str.strip()
    df["Missing_Date_Norm"] = df["Missing_Date"].apply(_normalize_date_string)
    return df


def get_active_technician_records():
    """Active technicians as records from Technicians master, with ID/email/name."""
    tech_df, _ = load_technicians_master()
    if tech_df.empty:
        return []
    active = tech_df[tech_df["Active"].apply(_yes_value)].copy()
    records = []
    for _, row in active.iterrows():
        name = str(row.get("Technician_Name", "")).strip()
        tech_id = str(row.get("Technician_ID", "")).strip()
        email = str(row.get("Email", "")).strip()
        if name:
            records.append({
                "Technician_ID": tech_id,
                "Technician_Name": name,
                "Email": email,
                "Receive_Missing_Time_Email": str(row.get("Receive_Missing_Time_Email", "YES")).strip(),
                "Supervisor": str(row.get("Supervisor", "NO")).strip(),
            })
    return records


def _technician_id_for_name(technician_name):
    selected = str(technician_name).strip()
    tech_df, _ = load_technicians_master()
    if tech_df.empty:
        return ""
    match = tech_df[tech_df["Technician_Name"].astype(str).str.strip() == selected]
    if match.empty:
        # Fallback: username match if evaluation selector uses username.
        match = tech_df[tech_df["Username"].astype(str).str.strip() == selected]
    if match.empty:
        return ""
    return str(match.iloc[0].get("Technician_ID", "")).strip()

def _missing_work_header_key(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _normalize_technician_id(value):
    """Normalize IDs such as TECH-000002, tech 000002 or TECH_000002."""
    raw = str(value or "").strip().upper()
    compact = re.sub(r"[^A-Z0-9]+", "", raw)
    match = re.search(r"TECH(\d+)", compact)
    if match:
        return f"TECH-{int(match.group(1)):06d}"
    return raw


def _read_missing_work_time_raw():
    """Read MISSING_WORK_TIME directly and normalize all known header variants."""
    expected = ["Timestamp", "Technician_ID", "Technician_Name", "Missing_Date", "Note"]
    ws = _get_or_create_worksheet(
        KPI_SHEET_ID,
        MISSING_WORK_TIME_SHEET_NAME,
        expected,
    )
    values = ws.get_all_values()
    if not values or len(values) <= 1:
        return pd.DataFrame(columns=expected)

    raw_headers = [
        str(value).replace("\ufeff", "").replace("​", "").strip()
        for value in values[0]
    ]
    width = len(raw_headers)
    rows = [
        list(row[:width]) + [""] * max(0, width - len(row))
        for row in values[1:]
    ]
    df = pd.DataFrame(rows, columns=raw_headers)

    aliases = {
        "timestamp": "Timestamp",
        "technicianid": "Technician_ID",
        "technicianname": "Technician_Name",
        "techniciannam": "Technician_Name",
        "technician": "Technician_Name",
        "missingdate": "Missing_Date",
        "date": "Missing_Date",
        "note": "Note",
        "notes": "Note",
    }
    rename_map = {}
    for column in df.columns:
        canonical = aliases.get(_missing_work_header_key(column))
        if canonical:
            rename_map[column] = canonical
    df = df.rename(columns=rename_map)

    for column in expected:
        if column not in df.columns:
            df[column] = ""

    df = df[expected].copy()
    for column in expected:
        df[column] = (
            df[column]
            .fillna("")
            .astype(str)
            .replace({"nan": "", "None": ""})
            .str.strip()
        )

    df["Technician_ID_Norm"] = df["Technician_ID"].map(_normalize_technician_id)
    df["Technician_Name_Norm"] = df["Technician_Name"].map(_normalize_name_key)
    df["Missing_Date_Parsed"] = parse_mixed_datetime_series(
        df["Missing_Date"]
    ).dt.normalize()
    return df


def load_missing_entry_penalty_log(technician):
    """Read the normalized log and delegate calculation to the v9 service."""
    result_columns = [
        "Godina", "Mesec", "Missing Entries", "Justified Missing Entries",
        "Unjustified Missing Entries", "Penalty Points", "Penalty Details",
    ]
    selected_name = str(technician or "").strip()
    selected_id = _technician_id_for_name(selected_name)

    tech_master, _ = load_technicians_master()
    supervisor = False
    if not tech_master.empty:
        master = tech_master.copy()
        master["_id_norm"] = master["Technician_ID"].map(_normalize_technician_id)
        master["_name_norm"] = master["Technician_Name"].map(_normalize_name_key)
        row = master[
            (master["_id_norm"] == _normalize_technician_id(selected_id))
            | (master["_name_norm"] == _normalize_name_key(selected_name))
        ]
        supervisor = bool(not row.empty and _yes_value(row.iloc[0].get("Supervisor", "NO")))

    try:
        raw = _read_missing_work_time_raw()
        service_result = calculate_monthly_penalty(
            raw,
            selected_name,
            selected_id,
            is_weekend=is_weekend_day,
            supervisor=supervisor,
        )
        st.session_state["_missing_penalty_debug"] = service_result.debug
        st.session_state.pop("_missing_penalty_error", None)
        return service_result.monthly
    except Exception as exc:
        st.session_state["_missing_penalty_debug"] = {
            "technician": selected_name,
            "technician_id": selected_id,
            "service_called": True,
            "error": f"{type(exc).__name__}: {exc}",
        }
        st.session_state["_missing_penalty_error"] = f"{type(exc).__name__}: {exc}"
        return pd.DataFrame(columns=result_columns)

def build_monthly_evaluation_data(df_source, technician, target_row, penalty_df=None):
    wanted = _normalize_name_key(technician)
    tech_df = df_source[df_source["Tehničar/Inženjer"].astype(str).map(_normalize_name_key) == wanted].copy()

    if tech_df.empty:
        monthly_eval = pd.DataFrame(columns=[
            "Godina", "Mesec", "Effective_Hours", "Activities", "Active_Days"
        ])
    else:
        monthly_eval = tech_df.groupby(["Godina", "Mesec"]).agg(
            Effective_Hours=("Duration_Hours", "sum"),
            Activities=("Duration_Hours", "count"),
        ).reset_index()
        work_days = tech_df[["Godina", "Mesec", "Tehničar/Inženjer", "Radni_dan"]].drop_duplicates()
        work_days = work_days.groupby(["Godina", "Mesec"]).size().reset_index(name="Active_Days")
        monthly_eval = monthly_eval.merge(work_days, on=["Godina", "Mesec"], how="left")

    # A month containing only missing-work records must still appear in evaluation.
    if penalty_df is not None and not penalty_df.empty and monthly_eval.empty:
        monthly_eval = penalty_df[["Godina", "Mesec"]].drop_duplicates().copy()
        monthly_eval["Effective_Hours"] = 0.0
        monthly_eval["Activities"] = 0
        monthly_eval["Active_Days"] = 0
    monthly_eval["Work_Hours"] = monthly_eval["Active_Days"] * 8
    monthly_eval["Utilization_%"] = (monthly_eval["Effective_Hours"] / monthly_eval["Work_Hours"] * 100).fillna(0)
    monthly_eval["Activities_Per_Hour"] = (monthly_eval["Activities"] / monthly_eval["Work_Hours"]).fillna(0)
    monthly_eval["Undocumented_Time"] = (monthly_eval["Work_Hours"] - monthly_eval["Effective_Hours"]).clip(lower=0)

    target_aph = float(target_row["Target Activities/Hour"])
    target_activities = float(target_row["Target Activities"])
    target_utilization = float(target_row["Target Utilization"])

    monthly_eval["Utilization Score"] = monthly_eval["Utilization_%"].apply(lambda x: score_ratio(x, target_utilization))
    monthly_eval["Activities/Hour Score"] = monthly_eval["Activities_Per_Hour"].apply(lambda x: score_ratio(x, target_aph))
    monthly_eval["Activities Count Score"] = monthly_eval["Activities"].apply(lambda x: score_ratio(x, target_activities))
    monthly_eval["Raw Overall Score"] = (
        monthly_eval["Utilization Score"] * 0.40
        + monthly_eval["Activities/Hour Score"] * 0.30
        + monthly_eval["Activities Count Score"] * 0.30
    )

    if penalty_df is not None and not penalty_df.empty:
        penalty_cols = [
            "Godina", "Mesec", "Missing Entries", "Justified Missing Entries",
            "Unjustified Missing Entries", "Penalty Points", "Penalty Details"
        ]
        # Outer merge keeps months that contain missing entries even when the technician
        # has no activity at all in that month. KPI values then default to zero.
        monthly_eval = monthly_eval.merge(penalty_df[penalty_cols], on=["Godina", "Mesec"], how="outer")
        for metric_col in ["Effective_Hours", "Activities", "Active_Days", "Work_Hours",
                           "Utilization_%", "Activities_Per_Hour", "Undocumented_Time",
                           "Utilization Score", "Activities/Hour Score",
                           "Activities Count Score", "Raw Overall Score"]:
            if metric_col in monthly_eval.columns:
                monthly_eval[metric_col] = monthly_eval[metric_col].fillna(0)
    else:
        monthly_eval["Missing Entries"] = 0
        monthly_eval["Justified Missing Entries"] = 0
        monthly_eval["Unjustified Missing Entries"] = 0
        monthly_eval["Penalty Points"] = 0.0
        monthly_eval["Penalty Details"] = "0 unjustified / 0 justified"

    for col in ["Missing Entries", "Justified Missing Entries", "Unjustified Missing Entries", "Penalty Points"]:
        monthly_eval[col] = monthly_eval[col].fillna(0)
    monthly_eval["Penalty Details"] = monthly_eval["Penalty Details"].fillna("0 unjustified / 0 justified")

    monthly_eval["Overall Score"] = (monthly_eval["Raw Overall Score"] - monthly_eval["Penalty Points"]).clip(lower=0, upper=100)
    monthly_eval["Month Date"] = pd.to_datetime(
        monthly_eval["Godina"].astype(int).astype(str) + "-" + monthly_eval["Mesec"].astype(int).astype(str).str.zfill(2) + "-01",
        errors="coerce",
    )
    monthly_eval["Month"] = monthly_eval["Month Date"].dt.strftime("%b %Y")
    monthly_eval = monthly_eval.sort_values(["Godina", "Mesec"])
    monthly_eval[["Overall Grade", "Overall Grade Text"]] = monthly_eval["Overall Score"].apply(lambda x: pd.Series(grade_from_score(x)))
    return monthly_eval


def show_evaluation_card(title, score):
    grade, text = grade_from_score(score)
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-title">{title}</div>
            <div class="metric-value">{grade}</div>
            <div class="metric-delta">{score:.1f}/100 · {text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )



def _safe_filename(value):
    txt = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    txt = re.sub(r"[^A-Za-z0-9._-]+", "_", txt).strip("_")
    return txt or "technician_photo"



def photo_to_base64(uploaded_file, max_side=420, max_chars=45000):
    """Compresses an uploaded technician photo and returns a data URI safe for a Google Sheets cell."""
    if uploaded_file is None:
        return "", ""

    original_name = uploaded_file.name or "photo.jpg"
    file_bytes = uploaded_file.getvalue()

    try:
        from PIL import Image
        image = Image.open(BytesIO(file_bytes))
        image = image.convert("RGB")
        image.thumbnail((max_side, max_side))

        for quality in [82, 76, 70, 64, 58, 52, 46, 40]:
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=quality, optimize=True)
            encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
            data_uri = f"data:image/jpeg;base64,{encoded}"
            if len(data_uri) <= max_chars:
                return data_uri, _safe_filename(os.path.splitext(original_name)[0]) + ".jpg"

        # If the image is still too large, reduce dimensions and try once more.
        image.thumbnail((300, 300))
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=42, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        data_uri = f"data:image/jpeg;base64,{encoded}"
        if len(data_uri) <= max_chars:
            return data_uri, _safe_filename(os.path.splitext(original_name)[0]) + ".jpg"

        raise ValueError("Photo is still too large after compression. Use a smaller image.")
    except ImportError:
        # Fallback if Pillow is not installed: store the raw file only when it fits into one Sheets cell.
        ext = os.path.splitext(original_name)[1].lower().replace(".", "") or "png"
        mime = "image/jpeg" if ext in ["jpg", "jpeg"] else f"image/{ext}"
        encoded = base64.b64encode(file_bytes).decode("utf-8")
        data_uri = f"data:{mime};base64,{encoded}"
        if len(data_uri) > max_chars:
            raise ValueError("Photo is too large and Pillow is not installed for compression. Install Pillow or use a smaller image.")
        return data_uri, original_name


def show_base64_image(data_uri, width=150, caption=None):
    """Displays a Base64 data URI in Streamlit."""
    data_uri = str(data_uri or "").strip()
    if not data_uri:
        return
    st.image(data_uri, width=width, caption=caption)

def _find_header_index(headers, column_name):
    def norm(x):
        return re.sub(r"[^a-z0-9]+", "", str(x).strip().lower())
    target = norm(column_name)
    for idx, header in enumerate(headers, start=1):
        if norm(header) == target:
            return idx
    return None


def _canonical_admin_header(header):
    """Maps equivalent Sheet headers to one internal name.

    This prevents duplicate columns/rows when the Sheet uses underscore style
    such as Target_Activities instead of Target Activities.
    """
    def norm(x):
        return re.sub(r"[^a-z0-9]+", "", str(x).strip().lower())

    aliases = {
        "technician": "Technician",
        "tehnicar": "Technician",
        "active": "Active",
        "aktivan": "Active",
        "periodtype": "Period_Type",
        "targetactivitieshour": "Target Activities/Hour",
        "targetaph": "Target Activities/Hour",
        "targetactivities": "Target Activities",
        "targetutilization": "Target Utilization",
        "targetutilizationpct": "Target Utilization",
        "department": "Department",
        "position": "Position",
        "photofileid": "Photo_File_ID",
        "photofilename": "Photo_File_Name",
        "photoupdatedat": "Photo_Updated_At",
        "photobase64": "Photo_Base64",
    }
    return aliases.get(norm(header), str(header).strip())


def _find_canonical_header_index(headers, canonical_name):
    for idx, header in enumerate(headers, start=1):
        if _canonical_admin_header(header) == canonical_name:
            return idx
    return None


@_live_reads
def ensure_worksheet_columns(ws, required_columns):
    """Ensure the worksheet has all required columns and canonicalize known headers.

    This function intentionally does not delete duplicate columns. It rewrites known
    header names to canonical names and appends only truly missing logical columns.
    """
    values = ws.get_all_values()
    headers = values[0] if values else []
    if not headers:
        ws.update("A1", [required_columns])
        return required_columns

    headers = [str(h).replace("\ufeff", "").replace("​", "").strip() for h in headers]
    canonical_headers = []
    existing_canonicals = set()

    for h in headers:
        if h == "":
            canonical_headers.append(h)
            continue
        ch = _canonical_admin_header(h)
        canonical_headers.append(ch)
        existing_canonicals.add(ch)

    changed = canonical_headers != headers
    for col in required_columns:
        if _canonical_admin_header(col) not in existing_canonicals:
            canonical_headers.append(col)
            existing_canonicals.add(_canonical_admin_header(col))
            changed = True

    if changed:
        ws.update("A1", [canonical_headers])
    return canonical_headers

@_live_reads
def save_technician_admin_record(
    technician,
    active,
    period_type,
    target_aph,
    target_activities,
    target_utilization,
    department,
    position,
    username="",
    email="",
    receive_task_email="Yes",
    receive_task_reminder="Yes",
    receive_missing_time_email="Yes",
    receive_bn_email="Yes",
    supervisor="No",
    photo_file_id="",
    photo_file_name="",
    photo_base64="",
):
    """Creates or updates a technician in the new Technicians master sheet.

    Compatibility rule:
    - TECHNICIAN_TARGETS is still updated because Technician Evaluation uses it.
    - The old 'Aktivni Tehničari' sheet is not used as the master anymore.
      It is only kept for existing missing-entry logs until that logic is migrated.
    """
    technician = str(technician).strip()
    if not technician:
        raise ValueError("Technician name is required.")

    client = get_client()
    sh = get_spreadsheet(KPI_SHEET_ID)
    targets_ws = sh.worksheet(TECHNICIAN_TARGETS_SHEET_NAME)
    technicians_ws = sh.worksheet(TECHNICIANS_SHEET_NAME)
    active_ws = sh.worksheet(ACTIVE_TECH_SHEET_NAME)

    def normalize_name(x):
        return re.sub(r"\s+", " ", str(x or "").strip()).casefold()

    def existing_by_position(row, pos):
        return row[pos - 1] if len(row) >= pos else ""

    wanted = normalize_name(technician)
    active_status = "YES" if _yes_value(active) else "NO"
    receive_task_status = "YES" if _yes_value(receive_task_email) else "NO"
    receive_task_reminder_status = "YES" if _yes_value(receive_task_reminder) else "NO"
    receive_missing_time_status = "YES" if _yes_value(receive_missing_time_email) else "NO"
    receive_bn_status = "YES" if _yes_value(receive_bn_email) else "NO"
    supervisor_status = "YES" if _yes_value(supervisor) else "NO"

    # =====================================================
    # 1) Update the new TECHNICIANS master sheet
    # =====================================================
    technician_columns = [
        "Technician_ID", "Technician_Name", "Username", "Position", "Department",
        "Email", "Active", "Picture", "Receive_Task_Email",
        "Receive_Task_Reminder", "Receive_Missing_Time_Email", "Receive_BN_Email",
        "Supervisor"
    ]
    technicians_ws.update("A1:M1", [technician_columns])
    tech_values = technicians_ws.get_all_values()
    if not tech_values:
        tech_values = [technician_columns]

    technician_row_idx = None
    for row_idx, row in enumerate(tech_values[1:], start=2):
        row_name = row[1] if len(row) >= 2 else ""
        if normalize_name(row_name) == wanted:
            technician_row_idx = row_idx
            break

    if technician_row_idx is None:
        technician_row_idx = len(tech_values) + 1
        existing_tech_row = []
    else:
        existing_tech_row = tech_values[technician_row_idx - 1] if technician_row_idx <= len(tech_values) else []

    existing_id = existing_by_position(existing_tech_row, 1)
    if not existing_id:
        max_num = 0
        for row in tech_values[1:]:
            raw_id = row[0] if len(row) >= 1 else ""
            m = re.search(r"(\d+)$", str(raw_id))
            if m:
                max_num = max(max_num, int(m.group(1)))
        existing_id = f"TECH-{max_num + 1:06d}"

    existing_picture = existing_by_position(existing_tech_row, 8)
    master_picture = photo_base64 or existing_picture

    technicians_ws.update(f"A{technician_row_idx}:M{technician_row_idx}", [[
        existing_id,
        technician,
        str(username or existing_by_position(existing_tech_row, 3)).strip(),
        str(position or existing_by_position(existing_tech_row, 4)).strip(),
        str(department or existing_by_position(existing_tech_row, 5)).strip(),
        str(email or existing_by_position(existing_tech_row, 6)).strip(),
        active_status,
        master_picture,
        receive_task_status,
        receive_task_reminder_status,
        receive_missing_time_status,
        receive_bn_status,
        supervisor_status,
    ]])

    # =====================================================
    # 2) Keep the old 'Aktivni Tehničari' missing-entry sheet compatible
    # =====================================================
    # This sheet keeps its original structure:
    # Tehničar | Aktivan | date | date | ...
    # It is no longer the master database, but it must contain every active/inactive
    # technician row so the existing missing-hours date logging continues to work.
    active_values = active_ws.get_all_values()
    if not active_values:
        active_ws.update("A1:B1", [["Tehničar", "Aktivan"]])
        active_values = [["Tehničar", "Aktivan"]]

    active_headers = active_values[0]
    active_tech_col = _find_header_index(active_headers, "Tehničar") or 1
    active_status_col = _find_header_index(active_headers, "Aktivan") or 2

    active_row_idx = None
    for row_idx, row in enumerate(active_values[1:], start=2):
        row_name = row[active_tech_col - 1] if len(row) >= active_tech_col else ""
        if normalize_name(row_name) == wanted:
            active_row_idx = row_idx
            break

    legacy_active_status = "DA" if active_status == "YES" else "NE"
    if active_row_idx is None:
        next_row = len(active_values) + 1
        active_ws.update(f"A{next_row}:B{next_row}", [[technician, legacy_active_status]])
    else:
        active_ws.update_cell(active_row_idx, active_tech_col, technician)
        active_ws.update_cell(active_row_idx, active_status_col, legacy_active_status)

    # =====================================================
    # 3) Update TECHNICIAN_TARGETS for current evaluation logic
    # =====================================================
    target_columns = [
        "Technician", "Active", "Period_Type", "Target Activities/Hour", "Target Activities", "Target Utilization",
        "Department", "Position", "Photo_File_ID", "Photo_File_Name", "Photo_Updated_At", "Photo_Base64"
    ]

    targets_ws.update("A1:L1", [target_columns])
    values = targets_ws.get_all_values()
    if not values:
        values = [target_columns]

    target_row_idx = None
    for row_idx, row in enumerate(values[1:], start=2):
        row_name = row[0] if len(row) >= 1 else ""
        if normalize_name(row_name) == wanted:
            target_row_idx = row_idx
            break

    if target_row_idx is None:
        target_row_idx = len(values) + 1
        existing_row = []
    else:
        existing_row = values[target_row_idx - 1] if target_row_idx <= len(values) else []

    target_existing_photo = existing_by_position(existing_row, 12)
    now_value = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if (photo_file_id or photo_base64) else existing_by_position(existing_row, 11)
    row_values = [
        technician,
        active_status,
        period_type,
        target_aph,
        target_activities,
        f"{normalize_percent_value(target_utilization, 85.0):g}%",
        department,
        position,
        photo_file_id or existing_by_position(existing_row, 9),
        photo_file_name or existing_by_position(existing_row, 10),
        now_value,
        photo_base64 or target_existing_photo or master_picture,
    ]

    targets_ws.update(f"A{target_row_idx}:L{target_row_idx}", [row_values])

    return True

def log_missing_technician_dates(missing_technicians, alert_day_ts):
    """Write missing work time into normalized MISSING_WORK_TIME sheet.

    The legacy 'Aktivni Tehničari' sheet is intentionally not used anymore.
    One row = one missing date for one technician.
    Duplicate key: Technician_ID + Missing_Date.
    """
    if not missing_technicians:
        return 0, []
    if is_weekend_day(alert_day_ts):
        return 0, []

    headers = ["Timestamp", "Technician_ID", "Technician_Name", "Missing_Date", "Note"]
    ws = _get_or_create_worksheet(KPI_SHEET_ID, MISSING_WORK_TIME_SHEET_NAME, headers)

    date_str = pd.to_datetime(alert_day_ts).strftime("%d.%m.%Y")
    timestamp = datetime.now(ZoneInfo("Europe/Belgrade")).strftime("%d.%m.%Y %H:%M:%S")

    tech_df, _ = load_technicians_master()
    by_name = {}
    if not tech_df.empty:
        for _, row in tech_df.iterrows():
            name = str(row.get("Technician_Name", "")).strip()
            if name:
                by_name[name] = row
                by_name[person_name_key(name)] = row

    # Duplicate protection must use the live sheet. A failed read raises instead
    # of returning an empty frame, otherwise every retry appended duplicates.
    with fresh_reads():
        existing_df = _missing_work_values_to_frame(ws.get_all_values(), headers)
    existing_keys = set()
    if not existing_df.empty:
        for _, row in existing_df.iterrows():
            key = (
                str(row.get("Technician_ID", "")).strip(),
                _normalize_date_string(row.get("Missing_Date", "")),
            )
            existing_keys.add(key)

    rows_to_append = []
    skipped = []
    for technician in missing_technicians:
        name = str(technician).strip()
        if not name:
            continue
        row = by_name.get(name)
        if row is None:
            row = by_name.get(person_name_key(name))
        tech_id = str(row.get("Technician_ID", "")).strip() if row is not None else ""

        # Fallback for temporary old data with no ID; still avoid duplicate by name/date.
        if tech_id:
            key = (tech_id, date_str)
            duplicate = key in existing_keys
        else:
            duplicate = False
            if not existing_df.empty:
                duplicate = any(
                    (person_name_key(r.get("Technician_Name", "")) == person_name_key(name) and _normalize_date_string(r.get("Missing_Date", "")) == date_str)
                    for _, r in existing_df.iterrows()
                )

        if duplicate:
            skipped.append(name)
            continue

        rows_to_append.append([timestamp, tech_id, name, date_str, ""])
        if tech_id:
            existing_keys.add((tech_id, date_str))

    if rows_to_append:
        ws.append_rows(rows_to_append, value_input_option="USER_ENTERED", table_range="A1")
        load_missing_work_time_log.clear()

    return len(rows_to_append), skipped




def _norm_text(value):
    return str(value).strip()


def _norm_key(value):
    return str(value).strip().lower().replace(" ", "_").replace("-", "_")


def _session_user():
    """Return the authenticated user without relying on a late module global."""
    user = st.session_state.get("user", {})
    return user if isinstance(user, dict) else {}


def _session_permissions():
    permissions = _session_user().get("permissions", {})
    return permissions if isinstance(permissions, dict) else {}


def _password_is_hashed(value):
    return str(value or "").startswith(f"{PASSWORD_HASH_SCHEME}$")


def _hash_password(password):
    """Create a salted PBKDF2-SHA256 password record using stdlib only."""
    raw = str(password or "")
    if not raw:
        raise ValueError("Password is required.")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", raw.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
    )
    salt_text = base64.urlsafe_b64encode(salt).decode("ascii")
    digest_text = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"{PASSWORD_HASH_SCHEME}${PASSWORD_HASH_ITERATIONS}${salt_text}${digest_text}"


def _verify_password(stored_password, supplied_password):
    """Verify current hashes and legacy plaintext values in constant time."""
    stored = str(stored_password or "")
    supplied = str(supplied_password or "")
    if _password_is_hashed(stored):
        try:
            scheme, iterations_text, salt_text, digest_text = stored.split("$", 3)
            iterations = int(iterations_text)
            if scheme != PASSWORD_HASH_SCHEME or not 100_000 <= iterations <= 2_000_000:
                return False
            salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
            expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
            calculated = hashlib.pbkdf2_hmac(
                "sha256", supplied.encode("utf-8"), salt, iterations
            )
            return hmac.compare_digest(calculated, expected)
        except (TypeError, ValueError, UnicodeError):
            return False
    return hmac.compare_digest(stored.encode("utf-8"), supplied.encode("utf-8"))


def _password_auth_version(stored_password):
    """Non-secret fingerprint used to revoke remember tokens after password change."""
    return hashlib.sha256(str(stored_password or "").encode("utf-8")).hexdigest()[:24]


@_live_reads
def _upgrade_legacy_password(username, supplied_password):
    """Atomically replace one verified legacy plaintext password with a hash."""
    ws, _ = open_first_existing_worksheet(get_client(), AUTH_SHEET_ID, USER_SHEET_NAMES)
    values = ws.get_all_values()
    if not values:
        return None
    headers = [str(value).strip() for value in values[0]]
    username_col = next((i for i, value in enumerate(headers) if _norm_sheet_col(value) == "username"), None)
    password_col = next((i for i, value in enumerate(headers) if _norm_sheet_col(value) == "password"), None)
    if username_col is None or password_col is None:
        return None

    wanted = str(username or "").strip().casefold()
    matches = []
    for row_number, row in enumerate(values[1:], start=2):
        row_username = row[username_col] if username_col < len(row) else ""
        if str(row_username).strip().casefold() == wanted:
            matches.append((row_number, row))
    if len(matches) != 1:
        return None

    row_number, row = matches[0]
    stored = row[password_col] if password_col < len(row) else ""
    if _password_is_hashed(stored):
        return stored if _verify_password(stored, supplied_password) else None
    if not _verify_password(stored, supplied_password):
        return None

    upgraded = _hash_password(supplied_password)
    ws.update_cell(row_number, password_col + 1, upgraded)
    load_users_and_permissions.clear()
    load_admin_users_data.clear()
    return upgraded


@st.cache_resource
def _legacy_password_migration_state():
    return {"lock": threading.Lock(), "complete": False}


@_live_reads
def _migrate_all_legacy_passwords():
    """Hash every remaining legacy password in one live, serialized batch write."""
    state = _legacy_password_migration_state()
    with state["lock"]:
        if state["complete"]:
            return {}

        ws, _ = open_first_existing_worksheet(get_client(), AUTH_SHEET_ID, USER_SHEET_NAMES)
        values = ws.get_all_values()
        if not values:
            state["complete"] = True
            return {}
        headers = [str(value).strip() for value in values[0]]
        username_col = next((i for i, value in enumerate(headers) if _norm_sheet_col(value) == "username"), None)
        password_col = next((i for i, value in enumerate(headers) if _norm_sheet_col(value) == "password"), None)
        if username_col is None or password_col is None:
            raise ValueError("User&Password sheet nema Username/Password kolone.")

        password_letter = _column_number_to_letter(password_col + 1)
        updates = []
        migrated = {}
        for row_number, row in enumerate(values[1:], start=2):
            username = row[username_col] if username_col < len(row) else ""
            stored = row[password_col] if password_col < len(row) else ""
            username_key = str(username or "").strip().casefold()
            if not username_key or not str(stored or "") or _password_is_hashed(stored):
                continue
            hashed = _hash_password(stored)
            migrated[username_key] = hashed
            updates.append({
                "range": f"{password_letter}{row_number}",
                "values": [[hashed]],
            })

        if updates:
            ws.batch_update(updates, value_input_option="RAW")
            load_users_and_permissions.clear()
            load_admin_users_data.clear()
        state["complete"] = True
        return migrated


@st.cache_resource
def _login_attempt_store():
    return {"lock": threading.Lock(), "attempts": {}}


def _login_retry_after(username):
    key = str(username or "").strip().casefold() or "<blank>"
    now = time_module.monotonic()
    state = _login_attempt_store()
    with state["lock"]:
        recent = [
            stamp for stamp in state["attempts"].get(key, [])
            if now - stamp < LOGIN_ATTEMPT_WINDOW_SEC
        ]
        state["attempts"][key] = recent
        if len(recent) < LOGIN_MAX_ATTEMPTS:
            return 0
        return max(1, int(LOGIN_ATTEMPT_WINDOW_SEC - (now - recent[0])))


def _record_login_failure(username):
    key = str(username or "").strip().casefold() or "<blank>"
    now = time_module.monotonic()
    state = _login_attempt_store()
    with state["lock"]:
        recent = [
            stamp for stamp in state["attempts"].get(key, [])
            if now - stamp < LOGIN_ATTEMPT_WINDOW_SEC
        ]
        recent.append(now)
        state["attempts"][key] = recent


def _clear_login_failures(username):
    key = str(username or "").strip().casefold() or "<blank>"
    state = _login_attempt_store()
    with state["lock"]:
        state["attempts"].pop(key, None)


@st.cache_resource(ttl=1800)
def open_first_existing_worksheet(_client, sheet_id, possible_names):
    spreadsheet = get_spreadsheet(sheet_id)
    existing = {ws.title: ws for ws in spreadsheet.worksheets()}
    for name in possible_names:
        if name in existing:
            return existing[name], name
    raise ValueError(f"Ne postoji nijedan od tabova: {possible_names}. Postojeći tabovi: {list(existing.keys())}")


USER_MODULE_ACCESS = [
    ("Work_Tickets", "Work Tickets"),
    ("KPI_Process", "KPI Process"),
    ("Bottleneck", "Bottleneck"),
    ("OEE", "OEE"),
    ("Line_Verification", "Line Verification / Dummy"),
    ("Administration", "Administration"),
]
USER_ACCESS_COLUMNS = [
    column
    for module_key, _ in USER_MODULE_ACCESS
    for column in (f"View_{module_key}", f"Edit_{module_key}")
]
USER_NOTIFICATION_COLUMNS = [
    "Receive_Task_Email",
    "Receive_Task_Reminder",
    "Receive_Missing_Time_Email",
    "Receive_BN_Email",
]


@st.cache_data(ttl=60)
def load_users_and_permissions():
    client = get_client()

    users_ws, users_tab = open_first_existing_worksheet(client, AUTH_SHEET_ID, USER_SHEET_NAMES)
    perm_ws, perm_tab = open_first_existing_worksheet(client, AUTH_SHEET_ID, PERMISSION_SHEET_NAMES)

    users = pd.DataFrame(users_ws.get_all_records())
    permissions = pd.DataFrame(perm_ws.get_all_records())

    users = clean_columns(users)
    permissions = clean_columns(permissions)

    # Normalise required user columns
    user_required = ["Username", "Password", "Full_Name", "Role", "Active"]
    missing_users = [c for c in user_required if c not in users.columns]
    if missing_users:
        raise ValueError(f"Nedostaju kolone u User&Password tabu: {missing_users}")

    if "Role" not in permissions.columns:
        raise ValueError("Nedostaje kolona 'Role' u Autorisation tabu.")

    # Optional user columns used by Work Tickets / notifications.
    # They are added safely if older User&Password sheets do not have them yet.
    for optional_col in ["Email", "Technician_ID", *USER_ACCESS_COLUMNS, *USER_NOTIFICATION_COLUMNS]:
        if optional_col not in users.columns:
            users[optional_col] = ""

    users["Username_norm"] = users["Username"].astype(str).str.strip().str.lower()
    users["Password_norm"] = users["Password"].astype(str)
    users["Role_norm"] = users["Role"].astype(str).str.strip().str.lower()
    users["Active_norm"] = users["Active"].astype(str).str.strip().str.upper()
    users["Technician_ID_norm"] = users["Technician_ID"].astype(str).str.strip().str.upper()

    permissions["Role_norm"] = permissions["Role"].astype(str).str.strip().str.lower()

    return users, permissions, users_tab, perm_tab


def build_permission_dict(permissions_df, role):
    role_norm = str(role).strip().lower()
    row = permissions_df[permissions_df["Role_norm"] == role_norm]
    if row.empty:
        return {}

    row = row.iloc[0].to_dict()
    result = {}

    for col, value in row.items():
        if col in ["Role", "Role_norm"]:
            continue
        result[_norm_key(col)] = str(value).strip().upper() == "YES"

    return result


def has_permission(permission_dict, permission_name):
    key = _norm_key(permission_name)
    return bool(permission_dict.get(key, False))


def is_admin_user(user_data=None):
    if user_data is None:
        user_data = st.session_state.get("user", {})
    return str(user_data.get("role", "")).strip().lower() == "admin"


def has_any_permission(permission_dict, permission_names, allow_admin=True, user_data=None):
    if allow_admin and user_data is not None and is_admin_user(user_data):
        return True
    return any(has_permission(permission_dict, name) for name in permission_names)


# =====================================================
# V2.0 MODULE REGISTRY / PERMISSION MATRIX
# =====================================================
# One central source of truth controls:
# - sidebar visibility
# - direct-access protection
# - admin permission columns
# - labels shown to users
#
# Important rule: a module is shown only when the role has one of the
# listed permission aliases set to YES in the Authorisation/Permissions sheet.
# Admin keeps fallback access so the system cannot be locked accidentally.
MODULE_REGISTRY = [
    {
        "access_key": "Work_Tickets",
        "admin_label": "Work Tickets",
        "user_label": "My Tasks",
        "icon": "🧾",
        "permission_aliases": ["My_Tasks", "Work_Tickets", "Task", "Tasks"],
        "description": "Zadaci, Kanban tabla i unos vremena rada. Unos ovde automatski ide u KPI.",
        "admin_only_label": False,
    },
    {
        "access_key": "KPI_Process",
        "admin_label": "KPI Process",
        "user_label": "KPI Process",
        "icon": "📊",
        "permission_aliases": ["KPI_Process", "KPI", "KPI_Dashboard"],
        "description": "Iskorišćenost, aktivnosti, ocena tehničara, alarmi i izvoz izveštaja.",
        "admin_only_label": False,
    },
    {
        "access_key": "Bottleneck",
        "admin_label": "Bottleneck",
        "user_label": "Bottleneck",
        "icon": "⏱️",
        "permission_aliases": ["BN_Entry", "BN_Module", "Bottleneck", "BN"],
        "description": "Unos i praćenje bottleneck vremena po mašini, sa zaštitom od duplikata.",
        "admin_only_label": False,
    },
    {
        "access_key": "OEE",
        "admin_label": "OEE",
        "user_label": "OEE",
        "icon": "🏭",
        "permission_aliases": ["OEE"],
        "description": "Unos smena i OEE analiza: dostupnost, performanse i kvalitet.",
        "admin_only_label": False,
    },
    {
        "access_key": "Uprava",
        "admin_label": "Uprava",
        "user_label": "Uprava",
        "icon": "🧭",
        "permission_aliases": ["Uprava", "Management", "Reports", "OEE"],
        "description": "Cela fabrika na jednom ekranu: OEE po projektu, najveći gubici, akcije i pokrivenost unosa.",
        "admin_only_label": False,
    },
    {
        "access_key": "Line_Verification",
        "admin_label": "Line Verification / Dummy",
        "user_label": "Line Verification / Dummy",
        "icon": "✅",
        "permission_aliases": ["Line_Verification", "Line Verification", "Dummy", "Line_Verification_Dummy"],
        "description": "Provera linija dummy komadima: OK/NOK pregled i nedeljni alarm.",
        "admin_only_label": False,
    },
    {
        "access_key": "Administration",
        "admin_label": "Administration",
        "user_label": "Administration",
        "icon": "⚙️",
        "permission_aliases": ["Admin_panel", "Administration", "Settings"],
        "description": "Korisnici, lozinke, prava pristupa i OEE podešavanja.",
        "admin_only_label": True,
    },
]


def get_module_config(module_label):
    for module in MODULE_REGISTRY:
        if module_label in [module["admin_label"], module["user_label"]]:
            return module
    return None


def module_display_name(module):
    if is_admin_user():
        return module["admin_label"]
    return module["user_label"]


def module_display_label(module_name):
    module = get_module_config(module_name)
    if not module:
        return module_name
    return f"{module.get('icon', '')} {module_name}"


def _parse_user_override(value):
    raw = str(value or "").strip().upper()
    if raw in ["YES", "Y", "DA", "TRUE", "1", "ALLOW", "ALLOWED"]:
        return True
    if raw in ["NO", "N", "NE", "FALSE", "0", "BLOCK", "BLOCKED"]:
        return False
    return None


def build_effective_permission_dict(permissions_df, user_row):
    """Merge role permissions with optional per-user View/Edit overrides."""
    result = build_permission_dict(permissions_df, user_row.get("Role", ""))
    admin_default = str(user_row.get("Role", "")).strip().lower() == "admin"

    for module in MODULE_REGISTRY:
        access_key = module["access_key"]
        aliases = module.get("permission_aliases", [])
        role_allowed = admin_default or any(has_permission(result, alias) for alias in aliases)
        view_override = _parse_user_override(user_row.get(f"View_{access_key}", ""))
        edit_override = _parse_user_override(user_row.get(f"Edit_{access_key}", ""))
        can_view = role_allowed if view_override is None else view_override
        can_edit = role_allowed if edit_override is None else edit_override
        if edit_override is True and view_override is not False:
            can_view = True
        if not can_view:
            can_edit = False
        result[_norm_key(f"View_{access_key}")] = bool(can_view)
        result[_norm_key(f"Edit_{access_key}")] = bool(can_edit)
    return result


def has_module_access(permission_dict, module_label, action="view", user_data=None):
    module = get_module_config(module_label)
    if not module:
        return False
    access_key = module.get("access_key", _norm_key(module.get("admin_label", module_label)))
    effective_key = _norm_key(f"{action}_{access_key}")
    if effective_key in permission_dict:
        return bool(permission_dict[effective_key])
    # Compatibility for remembered sessions created before the v9.3 columns existed.
    return has_any_permission(
        permission_dict,
        module.get("permission_aliases", []),
        allow_admin=True,
        user_data=user_data,
    )


def can_view_module(module_label, permission_dict=None):
    permissions = _session_permissions() if permission_dict is None else permission_dict
    return has_module_access(
        permissions, module_label, "view", user_data=_session_user()
    )


def can_edit_module(module_label, permission_dict=None):
    permissions = _session_permissions() if permission_dict is None else permission_dict
    return has_module_access(
        permissions, module_label, "edit", user_data=_session_user()
    )


def user_allowed_modules(permission_dict, user_data=None):
    user_data = user_data or st.session_state.get("user", {})
    modules = []

    for module in MODULE_REGISTRY:
        if has_module_access(
            permission_dict, module["admin_label"], "view", user_data=user_data
        ):
            modules.append(module_display_name(module))

    # Remove duplicates while preserving order. This protects roles that have both
    # My_Tasks and Work_Tickets aliases enabled.
    return list(dict.fromkeys(modules))


def require_module_access(internal_module_name, permission_aliases):
    module = get_module_config(internal_module_name)
    allowed = can_view_module(internal_module_name) if module else has_any_permission(
        _session_permissions(), permission_aliases, allow_admin=True, user_data=_session_user()
    )
    if not allowed:
        st.error(f"Nemaš dozvolu za {internal_module_name} modul.")
        st.stop()


def require_module_edit(internal_module_name):
    if not can_edit_module(internal_module_name):
        st.error(f"Imaš samo pregled za {internal_module_name}; unos i izmene nisu dozvoljeni.")
        st.stop()


def _user_payload_from_row(user, permissions):
    permission_dict = build_effective_permission_dict(permissions, user)
    return {
        "username": user["Username"],
        "full_name": user["Full_Name"],
        "role": user["Role"],
        "email": str(user.get("Email", "") or "").strip(),
        "technician_id": str(user.get("Technician_ID", "") or "").strip(),
        "permissions": permission_dict,
        "auth_version": _password_auth_version(user.get("Password", user.get("Password_norm", ""))),
    }


def authenticate_user(username, password):
    users, permissions, users_tab, perm_tab = load_users_and_permissions()
    username_norm = str(username).strip().lower()
    password_raw = str(password)
    candidates = users[
        (users["Username_norm"] == username_norm)
        & (users["Active_norm"] == "YES")
    ]
    for _, candidate in candidates.iterrows():
        stored = str(candidate.get("Password_norm", "") or "")
        if not _verify_password(stored, password_raw):
            continue
        user_row = candidate.to_dict()
        if not _password_is_hashed(stored):
            migrated = _migrate_all_legacy_passwords()
            upgraded = migrated.get(username_norm)
            if not upgraded:
                # Another worker may have completed the batch between our cached
                # authentication read and this migration attempt.
                upgraded = _upgrade_legacy_password(username_norm, password_raw)
            if not upgraded:
                return None
            user_row["Password"] = upgraded
            user_row["Password_norm"] = upgraded
        else:
            _migrate_all_legacy_passwords()
        payload = _user_payload_from_row(user_row, permissions)
        payload["users_tab"] = users_tab
        payload["permissions_tab"] = perm_tab
        return payload
    return None


def _load_active_user_without_password(username):
    """Restore a remembered session only for a user who still exists and is active."""
    users, permissions, users_tab, perm_tab = load_users_and_permissions()
    username_norm = str(username).strip().lower()
    match = users[(users["Username_norm"] == username_norm) & (users["Active_norm"] == "YES")]
    if match.empty:
        return None
    payload = _user_payload_from_row(match.iloc[0].to_dict(), permissions)
    payload["users_tab"] = users_tab
    payload["permissions_tab"] = perm_tab
    return payload


def _remember_secret():
    """Return the explicitly configured signing key or disable Remember me."""
    try:
        configured = str(st.secrets.get("REMEMBER_ME_SECRET", "") or "").strip()
        if configured:
            return configured.encode("utf-8")
    except Exception:
        return None
    return None


def _make_remember_token(username, auth_version):
    secret = _remember_secret()
    if not secret:
        return None
    expires = int(time_module.time()) + REMEMBER_DAYS * 24 * 60 * 60
    payload = json.dumps(
        {"u": str(username), "v": str(auth_version or ""), "exp": expires},
        separators=(",", ":"),
    )
    signature = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
    import base64 as _b64
    encoded = _b64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
    return f"{encoded}.{signature}"


def _read_remember_token(token):
    if not token or "." not in str(token):
        return None
    try:
        secret = _remember_secret()
        if not secret:
            return None
        import base64 as _b64
        encoded, supplied = str(token).rsplit(".", 1)
        payload = _b64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")
        expected = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            return None
        data = json.loads(payload)
        if int(data.get("exp", 0)) < int(time_module.time()):
            return None
        username = str(data.get("u", "")).strip()
        auth_version = str(data.get("v", "")).strip()
        if not username or not auth_version:
            return None
        return {"username": username, "auth_version": auth_version}
    except Exception:
        return None


def _set_remember_cookie(user_data):
    if COOKIE_MANAGER is None:
        return False
    try:
        token = _make_remember_token(
            user_data.get("username", ""), user_data.get("auth_version", "")
        )
        if not token:
            return False
        COOKIE_MANAGER.set(
            REMEMBER_COOKIE_NAME,
            token,
            expires_at=datetime.now() + timedelta(days=REMEMBER_DAYS),
            key="set_lianbo_remember_cookie",
        )
        return True
    except Exception:
        return False


def _delete_remember_cookie():
    if COOKIE_MANAGER is None:
        return
    try:
        COOKIE_MANAGER.delete(REMEMBER_COOKIE_NAME, key="delete_lianbo_remember_cookie")
    except Exception:
        return


def _try_restore_remembered_login():
    if COOKIE_MANAGER is None or st.session_state.get("remember_restore_attempted"):
        return False
    try:
        # The cookie component reports browser cookies only after it has been
        # rendered once. Reading on the very first run always returned None and
        # Remember me never worked; allow a few runs until cookies are loaded.
        all_cookies = COOKIE_MANAGER.get_all() or {}
    except Exception:
        all_cookies = {}
    attempts = int(st.session_state.get("remember_restore_runs", 0)) + 1
    st.session_state["remember_restore_runs"] = attempts
    if not all_cookies and attempts < 3:
        return False
    st.session_state["remember_restore_attempted"] = True
    try:
        token = all_cookies.get(REMEMBER_COOKIE_NAME) or COOKIE_MANAGER.get(REMEMBER_COOKIE_NAME)
        token_data = _read_remember_token(token)
        if not token_data:
            return False
        user_data = _load_active_user_without_password(token_data["username"])
        if not user_data:
            _delete_remember_cookie()
            return False
        if not hmac.compare_digest(
            str(token_data.get("auth_version", "")).encode("utf-8"),
            str(user_data.get("auth_version", "")).encode("utf-8"),
        ):
            _delete_remember_cookie()
            return False
        st.session_state["authenticated"] = True
        st.session_state["user"] = user_data
        st.session_state.setdefault("selected_module", None)
        st.session_state["remember_me_active"] = True
        return True
    except Exception:
        return False


def require_login():
    st.session_state.setdefault("authenticated", False)
    if st.session_state["authenticated"]:
        return True
    if _try_restore_remembered_login():
        st.rerun()

    st.markdown(f"""
    <div class="login-card">
        <img class="login-logo" src="data:image/png;base64,{APP_LOGO_BASE64}" />
        <div class="login-title">Sign in</div>
        <div class="login-subtitle">Lianbo Project Performance Hub</div>
    </div>
    """, unsafe_allow_html=True)

    left_login, center_login, right_login = st.columns([1.2, 1.0, 1.2])
    with center_login:
        remember_available = COOKIE_MANAGER is not None and _remember_secret() is not None
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username", placeholder="Username")
            password = st.text_input("Password", type="password", placeholder="Password")
            remember_me = st.checkbox(
                "Remember me",
                value=remember_available,
                key="login_remember_me",
                disabled=not remember_available,
            )
            login_clicked = st.form_submit_button("Login", use_container_width=True)
        if not remember_available:
            st.caption("Remember me is disabled until REMEMBER_ME_SECRET is configured.")

    st.markdown('<div class="login-helper">Access controlled by administrator</div>', unsafe_allow_html=True)

    if login_clicked:
        retry_after = _login_retry_after(username)
        if retry_after > 0:
            st.error(
                f"Previše neuspešnih pokušaja. Pokušaj ponovo za približno "
                f"{max(1, math.ceil(retry_after / 60))} min."
            )
        else:
            try:
                user_data = authenticate_user(username, password)
                if user_data is None:
                    _record_login_failure(username)
                    st.error("Pogrešan username/password ili korisnik nije aktivan.")
                else:
                    _clear_login_failures(username)
                    st.session_state["authenticated"] = True
                    st.session_state["user"] = user_data
                    st.session_state["selected_module"] = None
                    st.session_state["remember_me_active"] = bool(remember_me)
                    if remember_me:
                        _set_remember_cookie(user_data)
                    else:
                        _delete_remember_cookie()
                    st.rerun()
            except Exception as e:
                st.error("Login nije uspeo. Proveri AUTH Google Sheet, tabove, kolone i permission za service account.")
                st.write(e)
    st.stop()


def logout():
    _delete_remember_cookie()
    for key in ["authenticated", "user", "selected_module", "remember_me_active", "remember_restore_attempted"]:
        st.session_state.pop(key, None)
    st.rerun()


GLOBAL_REFRESH_SESSION_KEYS = {
    "_all_activities_sync_done",
    "_all_activities_sync_result",
    "automatic_checks_last_run",
    "missing_work_time_check_result",
    "missing_bn_check_result",
    "open_task_reminder_result",
    "bn_deviation_batch_result",
    "_task_status_sync_done",
    "_work_ticket_id_migration_done",
    "_work_ticket_id_migration_result",
    "_bn_forms_sync_at",
    "_bn_forms_sync_result",
}


def invalidate_all_app_data():
    """Invalidate every module data cache without logging the user out.

    The authenticated user, selected module and Remember me state are intentionally
    preserved. All Google Sheets data, cached spreadsheet/client resources and
    module synchronization markers are rebuilt on the next rerun.
    """
    # Data snapshots are refreshed globally, but the authenticated Google client
    # and opened Spreadsheet resources are intentionally preserved. Recreating
    # them on every refresh causes unnecessary metadata requests and 429 errors.
    st.cache_data.clear()
    clear_google_sheets_read_cache()
    mark_activity_sync_needed()
    try:
        getattr(GOOGLE_SHEETS_ENGINE, "stats", {})["last_stale_at"] = 0.0
    except Exception:
        pass

    for key in list(st.session_state.keys()):
        if key in GLOBAL_REFRESH_SESSION_KEYS or key.startswith((
            "_all_activities_",
            "_task_status_",
            "_data_engine_",
            "_oee_cache_",
            "_bn_cache_",
            "_kpi_cache_",
        )):
            st.session_state.pop(key, None)

    st.session_state["_global_refresh_notice"] = (
        "Svi moduli su osveženi. Google Sheets podaci i ALL_ACTIVITIES sync "
        "biće ponovo učitani iz izvora."
    )
    st.session_state["_global_refresh_at"] = datetime.now(ZoneInfo("Europe/Belgrade")).strftime(
        "%d.%m.%Y %H:%M:%S"
    )


def refresh_data():
    invalidate_all_app_data()
    st.rerun()


def clean_columns(df):
    df = df.copy()
    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.replace("\xa0", " ", regex=False)
        .str.replace(r"\s+", " ", regex=True)
        .str.replace(".", "", regex=False)
    )
    return df


COLOR_MAP = {
    "Effective_Hours": "#22D3EE",
    "Work_Hours": "#3B82F6",
    "Undocumented_Time": "#EF4444",
    "Activities": "#F59E0B",
    "Utilization_%": "#22C55E",
    "Activity_Factor_%": "#A78BFA",
    "Efficiency_%": "#14B8A6",
    "Activities_Per_Hour": "#14B8A6",
    "Total_Hours": "#22D3EE",
    "Cumulative_%": "#F59E0B",
    "BN_sec": "#22D3EE",
    "Average_BN_sec": "#22C55E",
    "Max_BN_sec": "#EF4444",
    "Checks": "#22D3EE",
    "NOK_Checks": "#EF4444",
}

# Human readable (Serbian) series names for legends and tooltips.
SERIES_LABELS = {
    "Effective_Hours": "Efektivni sati",
    "Work_Hours": "Radni sati",
    "Undocumented_Time": "Nedokumentovano",
    "Activities": "Aktivnosti",
    "Utilization_%": "Iskorišćenost %",
    "Activity_Factor_%": "Faktor aktivnosti %",
    "Efficiency_%": "Aktivnosti / sat",
    "Activities_Per_Hour": "Aktivnosti / sat",
    "Total_Hours": "Ukupno sati",
    "Cumulative_%": "Kumulativ %",
    "BN_sec": "BN [s]",
    "NOK_Checks": "NOK provere",
    "Overall Score": "Ukupna ocena",
}

AXIS_LABELS = {
    "Radni_dan": "Radni dan", "Mesec": "Mesec", "Godina": "Godina", "Datum": "Datum",
    "Tehničar/Inženjer": "Tehničar", "Kategorija rada": "Kategorija", "Opis aktivnosti": "Aktivnost",
    "Date": "Datum", "Project": "Projekat", "Machine": "Mašina",
}

_MONTH_NAMES = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Maj", 6: "Jun", 7: "Jul", 8: "Avg", 9: "Sep", 10: "Okt", 11: "Nov", 12: "Dec"}


def series_label(name):
    return SERIES_LABELS.get(name, str(name).replace("_", " "))


def format_x_label(value, x_col=None):
    if x_col == "Mesec":
        try:
            return _MONTH_NAMES.get(int(value), str(value))
        except (TypeError, ValueError):
            return str(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%d.%m.%Y")
    try:
        if hasattr(value, "strftime"):
            return value.strftime("%d.%m.%Y")
    except Exception:
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def style_chart(fig):
    """Industrial chart theme shared by every module (one look everywhere)."""
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(10,17,32,0.55)",
        colorway=ui.CHART_COLORS,
        font=dict(family="Inter, Segoe UI, Arial", size=12, color="#CBD5E1"),
        title=dict(x=0.01, xanchor="left", font=dict(family="Inter, Segoe UI, Arial", size=15, color="#F1F5F9")),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(family="Inter, Segoe UI, Arial", size=11, color="#CBD5E1"),
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        margin=dict(l=48, r=24, t=64, b=44),
        hoverlabel=dict(bgcolor="#0F172A", bordercolor="#22D3EE", font=dict(size=12, color="#F8FAFC")),
        separators=",.",
    )
    fig.update_xaxes(
        showgrid=False,
        zeroline=False,
        showline=True,
        linecolor="rgba(148,163,184,0.35)",
        ticks="outside",
        tickcolor="rgba(148,163,184,0.35)",
        tickfont=dict(color="#A9B9CF", size=11),
        title_font=dict(color="#93A4BC", size=11),
    )
    fig.update_yaxes(
        gridcolor="rgba(148,163,184,0.12)",
        griddash="dot",
        zeroline=False,
        showline=False,
        tickfont=dict(color="#A9B9CF", size=11),
        title_font=dict(color="#93A4BC", size=11),
    )
    return fig


def add_label_box(fig, x, y, text):
    fig.add_annotation(
        x=x, y=y, text=text, showarrow=False, yshift=10,
        bgcolor="rgba(15, 23, 42, 0.86)", bordercolor="rgba(148, 163, 184, 0.22)", borderwidth=1, borderpad=3,
        font=dict(family="Inter, Segoe UI, Arial", size=10, color="#F8FAFC"),
        xanchor="center", yanchor="bottom",
    )


def _value_format(decimals):
    return ":,.0f" if decimals == 0 else f":,.{int(decimals)}f"


def create_grouped_bar(data, x_col, y_cols, title, y_title="", decimals=2, target=None):
    """Clean grouped bar chart: value labels on bars (hidden automatically when
    crowded), Serbian series names, optional target line."""
    fig = go.Figure()
    if data.empty:
        fig.update_layout(title=title)
        return style_chart(fig)
    x_labels = [format_x_label(v, x_col) for v in data[x_col].tolist()]
    fmt = _value_format(decimals)
    show_text = len(x_labels) * max(len(y_cols), 1) <= 36
    for y_col in y_cols:
        y_values = pd.to_numeric(data[y_col], errors="coerce").fillna(0).tolist()
        label = series_label(y_col)
        fig.add_trace(go.Bar(
            x=x_labels,
            y=y_values,
            name=label,
            marker=dict(color=COLOR_MAP.get(y_col), line=dict(width=0)),
            texttemplate=("%{y" + fmt + "}") if show_text else None,
            textposition="outside",
            textfont=dict(size=10, color="#CBD5E1"),
            cliponaxis=False,
            hovertemplate="<b>%{x}</b><br>" + label + ": %{y" + fmt + "}<extra></extra>",
        ))
    if target is not None:
        fig.add_hline(y=float(target), line_dash="dash", line_color="#F59E0B", line_width=1.5,
                      annotation_text=f"Cilj {target:g}", annotation_position="top left",
                      annotation_font=dict(color="#F59E0B", size=10))
    fig.update_layout(
        title=title,
        barmode="group",
        bargap=0.28,
        bargroupgap=0.06,
        xaxis=dict(type="category", title=AXIS_LABELS.get(x_col, x_col)),
        yaxis=dict(title=y_title),
        uniformtext=dict(minsize=8, mode="hide"),
        showlegend=len(y_cols) > 1,
    )
    return style_chart(fig)


def create_oee_gauge(value, title, max_value=None):
    try:
        value = float(value)
    except Exception:
        value = 0.0

    if max_value is None:
        max_value = 100
    max_value = 100.0

    # OEE and components are capped at 100% for dashboard display and calculation.
    red_end = min(60, max_value)
    yellow_end = min(85, max_value)

    bar_color = "#22C55E" if value >= yellow_end else ("#F59E0B" if value >= red_end else "#EF4444")
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=value,
        number={"suffix": "%", "valueformat": ".1f", "font": {"family": "Inter, Segoe UI, Arial", "size": 30, "color": "#F8FAFC"}},
        title={"text": title, "font": {"family": "Inter, Segoe UI, Arial", "size": 13, "color": "#93A4BC"}},
        gauge={
            "shape": "angular",
            "axis": {"range": [0, max_value], "tickwidth": 1, "tickcolor": "#475569", "tickfont": {"size": 10, "color": "#93A4BC"}},
            "bar": {"color": bar_color, "thickness": 0.28},
            "bgcolor": "rgba(15,23,42,0.6)",
            "borderwidth": 0,
            "steps": [
                {"range": [0, red_end], "color": "rgba(239,68,68,0.22)"},
                {"range": [red_end, yellow_end], "color": "rgba(245,158,11,0.22)"},
                {"range": [yellow_end, max_value], "color": "rgba(34,197,94,0.22)"},
            ],
            "threshold": {
                "line": {"color": "#F59E0B", "width": 3},
                "thickness": 0.85,
                "value": 85,
            },
        },
    ))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Segoe UI, Arial", color="#E5E7EB"),
        margin=dict(l=18, r=18, t=45, b=12),
        height=230,
    )
    return fig


def show_gauge_row(items, key_prefix, max_value=None):
    cols = st.columns(len(items))
    for idx, (label, value) in enumerate(items):
        with cols[idx]:
            safe_key = f"{key_prefix}_{idx}_{label}".replace(" ", "_").replace("|", "_").replace("/", "_").replace(".", "_")
            st.plotly_chart(create_oee_gauge(value, label, max_value=max_value), use_container_width=True, key=safe_key)


def create_line_chart(data, x_col, y_col, title, y_title="", decimals=2, target=None):
    """Trend line with soft area fill, value labels for short series and the
    latest value highlighted."""
    fig = go.Figure()
    if data.empty:
        fig.update_layout(title=title)
        return style_chart(fig)
    x_labels = [format_x_label(v, x_col) for v in data[x_col].tolist()]
    y_values = pd.to_numeric(data[y_col], errors="coerce").fillna(0).tolist()
    color = COLOR_MAP.get(y_col, "#22D3EE")
    fmt = _value_format(decimals)
    label = series_label(y_col)
    short = len(x_labels) <= 16
    fig.add_trace(go.Scatter(
        x=x_labels,
        y=y_values,
        mode="lines+markers+text" if short else "lines+markers",
        name=label,
        line=dict(color=color, width=2.6, shape="spline", smoothing=0.6),
        marker=dict(size=7, color=color, line=dict(width=1.5, color="#0A1120")),
        fill="tozeroy",
        fillcolor="rgba(34,211,238,0.08)",
        texttemplate=("%{y" + fmt + "}") if short else None,
        textposition="top center",
        textfont=dict(size=10, color="#CBD5E1"),
        hovertemplate="<b>%{x}</b><br>" + label + ": %{y" + fmt + "}<extra></extra>",
    ))
    if x_labels:
        fig.add_trace(go.Scatter(
            x=[x_labels[-1]], y=[y_values[-1]], mode="markers", showlegend=False, hoverinfo="skip",
            marker=dict(size=13, color=color, line=dict(width=3, color="#F8FAFC")),
        ))
    if target is not None:
        fig.add_hline(y=float(target), line_dash="dash", line_color="#F59E0B", line_width=1.5,
                      annotation_text=f"Cilj {target:g}", annotation_position="top left",
                      annotation_font=dict(color="#F59E0B", size=10))
    fig.update_layout(
        title=title,
        xaxis=dict(type="category", title=AXIS_LABELS.get(x_col, x_col)),
        yaxis=dict(title=y_title, rangemode="tozero"),
        showlegend=False,
        hovermode="x",
    )
    return style_chart(fig)


def create_pareto_chart(data, label_col, value_col, cumulative_col, title):
    """Classic industrial Pareto: sorted bars + cumulative % line on a second axis
    with the 80 % reference."""
    fig = go.Figure()
    if data.empty:
        fig.update_layout(title=title)
        return style_chart(fig)
    labels = [str(v) if len(str(v)) <= 28 else str(v)[:27] + "…" for v in data[label_col].tolist()]
    values = pd.to_numeric(data[value_col], errors="coerce").fillna(0).tolist()
    cumulative = pd.to_numeric(data[cumulative_col], errors="coerce").fillna(0).tolist()
    colors = ["#22D3EE" if c <= 80 else "#475569" for c in cumulative]
    fig.add_trace(go.Bar(
        x=labels, y=values, name="Sati", marker=dict(color=colors, line=dict(width=0)),
        texttemplate="%{y:,.1f}", textposition="outside", textfont=dict(size=10, color="#CBD5E1"), cliponaxis=False,
        customdata=data[label_col].astype(str).tolist(),
        hovertemplate="<b>%{customdata}</b><br>%{y:,.2f} h<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=labels, y=cumulative, name="Kumulativ %", yaxis="y2", mode="lines+markers",
        line=dict(color="#F59E0B", width=2.4), marker=dict(size=7, color="#F59E0B"),
        hovertemplate="Kumulativ: %{y:,.1f} %<extra></extra>",
    ))
    fig.add_shape(type="line", xref="paper", x0=0, x1=1, yref="y2", y0=80, y1=80,
                  line=dict(color="rgba(245,158,11,0.55)", width=1, dash="dash"))
    fig.add_annotation(xref="paper", x=0.0, yref="y2", y=80, text="80 %", showarrow=False, yshift=8,
                       xanchor="left", font=dict(color="#F59E0B", size=10))
    fig.update_layout(
        title=title,
        xaxis=dict(type="category", tickangle=-30, title=""),
        yaxis=dict(title="h"),
        yaxis2=dict(title="%", overlaying="y", side="right", range=[0, 105], showgrid=False,
                    tickfont=dict(color="#F59E0B", size=11), ticksuffix=" %"),
        bargap=0.3,
        height=480,
    )
    return style_chart(fig)


def create_pie_chart(category, names_col="Kategorija rada", values_col="Effective_Hours", title="Vreme po kategoriji", unit="h"):
    """Donut chart with the total in the center."""
    data = category.copy()
    data[values_col] = pd.to_numeric(data[values_col], errors="coerce").fillna(0)
    total = float(data[values_col].sum())
    fig = go.Figure(go.Pie(
        labels=data[names_col].astype(str).tolist(),
        values=data[values_col].tolist(),
        hole=0.62,
        sort=True,
        direction="clockwise",
        textinfo="percent",
        textposition="inside",
        insidetextorientation="horizontal",
        marker=dict(colors=ui.CHART_COLORS, line=dict(color="#0A1120", width=2)),
        hovertemplate="<b>%{label}</b><br>%{value:,.1f} " + unit + " · %{percent}<extra></extra>",
    ))
    fig.update_layout(
        title=title,
        legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02),
        annotations=[dict(
            text=f"<b>{ui.format_number(total, 1)}</b><br>{unit} ukupno",
            x=0.5, y=0.5, showarrow=False, font=dict(size=20, color="#F1F5F9"),
        )],
    )
    style_chart(fig)
    fig.update_layout(legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.02))
    return fig


def create_excel_report(df, daily, monthly, yearly, category, tech_all, pareto, alerts_missing=None, alerts_over_8h=None):
    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        sheets = {
            "Filtered Data": df,
            "Daily": daily,
            "Monthly": monthly,
            "Yearly": yearly,
            "Categories": category,
            "Technicians": tech_all,
            "Pareto": pareto,
        }
        if alerts_missing is not None:
            sheets["Alerts Missing"] = alerts_missing
        if alerts_over_8h is not None:
            sheets["Alerts Over 8h"] = alerts_over_8h
        for sheet_name, sheet_df in sheets.items():
            sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)
        workbook = writer.book
        header_format = workbook.add_format({"bold": True, "font_color": "white", "bg_color": "#1E88E5", "border": 1})
        number_format = workbook.add_format({"num_format": "0.00"})
        for sheet_name, sheet_df in sheets.items():
            worksheet = writer.sheets[sheet_name]
            worksheet.freeze_panes(1, 0)
            worksheet.set_column(0, 30, 20)
            for col_num, value in enumerate(sheet_df.columns.values):
                worksheet.write(0, col_num, value, header_format)
            for col_num, col_name in enumerate(sheet_df.columns):
                if pd.api.types.is_numeric_dtype(sheet_df[col_name]):
                    worksheet.set_column(col_num, col_num, 18, number_format)
    output.seek(0)
    return output


def prepare_kpi_data(df_raw):
    df_raw = clean_columns(df_raw)
    required_columns = [
        "Timestamp", "Tehničar/Inženjer", "Kategorija rada", "Opis aktivnosti",
        "Datum", "Vreme početka", "Vreme završetka aktivnosti",
    ]
    missing = [col for col in required_columns if col not in df_raw.columns]
    if missing:
        return None, missing
    df = df_raw.copy()
    df["Datum"] = parse_mixed_datetime_series(df["Datum"])
    # Times are parsed value by value. Mixed formats (08:30 from the app,
    # 08:30:00 from downtime, 8:30 from Forms) previously made pandas infer one
    # format and turn the other rows into NaT, so those entries vanished.
    df["Vreme početka"] = parse_time_series(df["Vreme početka"])
    df["Vreme završetka aktivnosti"] = parse_time_series(df["Vreme završetka aktivnosti"])
    invalid_mask = df["Datum"].isna() | df["Vreme početka"].isna() | df["Vreme završetka aktivnosti"].isna()
    dropped_count = int(invalid_mask.sum())
    df = df[~invalid_mask].copy()
    if df.empty:
        empty = df.assign(Start=pd.Series(dtype="datetime64[ns]"), End=pd.Series(dtype="datetime64[ns]"))
        empty["Duration_Hours"] = pd.Series(dtype=float)
        empty["Radni_dan"] = pd.Series(dtype="datetime64[ns]")
        empty["Godina"] = pd.Series(dtype=int)
        empty["Mesec"] = pd.Series(dtype=int)
        empty.attrs["dropped_rows"] = dropped_count
        return empty, []
    base_day = df["Datum"].dt.normalize()
    df["Start"] = base_day + pd.to_timedelta(df["Vreme početka"].map(lambda t: t.hour * 3600 + t.minute * 60 + t.second), unit="s")
    df["End"] = base_day + pd.to_timedelta(df["Vreme završetka aktivnosti"].map(lambda t: t.hour * 3600 + t.minute * 60 + t.second), unit="s")
    df.loc[df["End"] < df["Start"], "End"] = df["End"] + pd.Timedelta(days=1)
    df["Duration_Hours"] = (df["End"] - df["Start"]).dt.total_seconds() / 3600
    # Downtime records carry the technician's confirmed work duration in
    # VREME ZASTOJA. Prefer that value over the raw clock difference, which can
    # include waiting time or span midnight.
    if "_Activity_Source" in df.columns and "_Effective_Duration_Minutes" in df.columns:
        effective_minutes = pd.to_numeric(df["_Effective_Duration_Minutes"], errors="coerce")
        downtime_mask = (
            df["_Activity_Source"].astype(str).str.strip().str.upper().eq(PROCESS_DOWNTIME_SOURCE)
            & effective_minutes.gt(0)
        )
        df.loc[downtime_mask, "Duration_Hours"] = effective_minutes[downtime_mask] / 60
        df = df.drop(columns=["_Activity_Source", "_Effective_Duration_Minutes"], errors="ignore")
    df = df[df["Duration_Hours"] >= 0]
    df["Radni_dan"] = df["Datum"]

    # Robustna logika za treću/noćnu smenu.
    # Cilj: aktivnosti između 00:00 i 05:59 pripadaju prethodnom proizvodnom danu.
    # Međutim, ako je operater u formi već izabrao prethodni dan (npr. Timestamp je 11.06,
    # a Datum u formi je 10.06), ne smemo još jednom da oduzmemo dan.
    #
    # Primer A: Timestamp 11.06, Datum 11.06, start 00:45 -> Radni_dan = 10.06.
    # Primer B: Timestamp 11.06, Datum 10.06, start 00:45 -> Radni_dan = 10.06.
    night_shift_mask = df["Vreme početka"].apply(
        lambda x: pd.notna(x) and time(0, 0) <= x < time(6, 0)
    )

    timestamp_dt = parse_mixed_datetime_series(df["Timestamp"]) if "Timestamp" in df.columns else pd.Series(pd.NaT, index=df.index)
    timestamp_day = timestamp_dt.dt.normalize()
    previous_timestamp_day = timestamp_day - pd.Timedelta(days=1)

    # Ako je Datum isti kao Timestamp dan, onda ga pomeramo na prethodni dan.
    # Ako je Datum već prethodni Timestamp dan, ostavljamo ga kako jeste.
    # Ako Timestamp ne može da se pročita, koristimo osnovno pravilo: Datum - 1.
    already_previous_day = night_shift_mask & timestamp_day.notna() & (df["Datum"].dt.normalize() == previous_timestamp_day)
    needs_previous_day = night_shift_mask & ~already_previous_day

    df.loc[needs_previous_day, "Radni_dan"] = df.loc[needs_previous_day, "Datum"] - pd.Timedelta(days=1)
    df["Godina"] = df["Radni_dan"].dt.year
    df["Mesec"] = df["Radni_dan"].dt.month
    df.attrs["dropped_rows"] = dropped_count
    return df, []


def find_column(columns, contains_all):
    for col in columns:
        c = str(col).lower()
        if all(term.lower() in c for term in contains_all):
            return col
    return None


def prepare_bottleneck_data(df_raw):
    df_raw = clean_columns(df_raw)
    project_col = find_column(df_raw.columns, ["project"])
    date_col = find_column(df_raw.columns, ["date"])
    timestamp_col = find_column(df_raw.columns, ["timestamp"])
    bn_col = find_column(df_raw.columns, ["bottleneck", "time"]) or find_column(df_raw.columns, ["seconds"])
    station_col = find_column(df_raw.columns, ["station"])
    machine_cols = [col for col in df_raw.columns if "machine selection" in str(col).lower()]
    missing = []
    for needed, name in [(project_col, "Project"), (date_col, "Date"), (bn_col, "Bottleneck time"), (station_col, "Station")]:
        if needed is None:
            missing.append(name)
    if not machine_cols:
        missing.append("Machine selection")
    if missing:
        return pd.DataFrame(), missing
    df = df_raw.copy()
    df["Machine"] = ""
    for col in machine_cols:
        values = df[col].astype(str).str.strip().replace(["nan", "None"], "")
        df["Machine"] = df["Machine"].mask(df["Machine"].astype(str).str.strip().eq(""), values)
    df["Machine"] = df["Machine"].replace(["", "nan", "None"], pd.NA)
    df["Project"] = df[project_col].astype(str).str.strip()
    # The Forms date column and the Timestamp share the sheet locale; together
    # they reveal whether slash dates are day/month or month/day.
    order_sample = list(df[date_col].tolist())
    if timestamp_col in df.columns:
        order_sample += list(df[timestamp_col].tolist())
    date_order = detect_slash_date_order(order_sample)
    df["Date"] = pd.to_datetime(df[date_col].map(lambda v: parse_date_value(v, date_order)), errors="coerce")
    # Legacy parse is kept only to recognise rows imported by older versions.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            df["Legacy_Date"] = pd.to_datetime(df[date_col], errors="coerce")
        except Exception:
            df["Legacy_Date"] = pd.NaT
    df["Timestamp"] = df[timestamp_col] if timestamp_col in df.columns else ""
    # Decimal comma (12,5) was turned into NaN and the BN entry was dropped.
    df["BN_sec"] = pd.to_numeric(df[bn_col].astype(str).str.strip().str.replace(",", ".", regex=False), errors="coerce")
    df["Station"] = df[station_col].astype(str).str.strip()
    df = df[["Timestamp", "Date", "Legacy_Date", "Project", "Machine", "BN_sec", "Station"]].copy()
    df = df.dropna(subset=["Date", "Project", "Machine", "BN_sec", "Station"])
    df = df[(df["Project"].astype(str).str.strip() != "") & (df["Station"].astype(str).str.strip() != "") & (df["BN_sec"] >= 0)]
    df["Godina"] = df["Date"].dt.year
    df["Mesec"] = df["Date"].dt.month
    return df, []



# =====================================================
# LINE VERIFICATION / DUMMY MODULE HELPERS
# =====================================================

@st.cache_data(ttl=60)
def load_line_verification_raw():
    client = get_client()
    ws, used_tab = open_first_existing_worksheet(client, LINE_VERIFICATION_SHEET_ID, LINE_VERIFICATION_SHEET_NAMES)
    return pd.DataFrame(ws.get_all_records()), used_tab


def prepare_line_verification_data(df_raw):
    df_raw = clean_columns(df_raw)

    timestamp_col = find_column(df_raw.columns, ["timestamp"])
    inspector_col = find_column(df_raw.columns, ["proverio"])
    project_col = find_column(df_raw.columns, ["projekat"])
    machine_col = find_column(df_raw.columns, ["mašina"]) or find_column(df_raw.columns, ["masina"]) or find_column(df_raw.columns, ["machine"])
    dummy_col = find_column(df_raw.columns, ["dummy"]) or find_column(df_raw.columns, ["column 4"])
    result_col = find_column(df_raw.columns, ["detektovala", "komade"]) or find_column(df_raw.columns, ["ok/ng"]) or find_column(df_raw.columns, ["linija", "komade"])
    problem_col = find_column(df_raw.columns, ["detektovan", "problem"])

    missing = []
    for needed, name in [
        (timestamp_col, "Timestamp"),
        (inspector_col, "Proverio"),
        (project_col, "Projekat"),
        (machine_col, "Mašina"),
        (result_col, "Da li je linija detektovala komade"),
    ]:
        if needed is None:
            missing.append(name)

    if missing:
        return pd.DataFrame(), missing

    df = df_raw.copy()
    lv_order = detect_slash_date_order(df[timestamp_col].tolist())
    df["Timestamp"] = pd.to_datetime(df[timestamp_col].map(lambda v: parse_date_value(v, lv_order)), errors="coerce")
    df["Date"] = df["Timestamp"].dt.normalize()
    df["Proverio"] = df[inspector_col].astype(str).str.strip()
    df["Project"] = df[project_col].astype(str).str.strip()
    df["Machine"] = df[machine_col].astype(str).str.strip()
    df["Dummy_Parts"] = df[dummy_col].astype(str).str.strip() if dummy_col is not None else ""
    df["Raw_Result"] = df[result_col].astype(str).str.strip()
    df["Detected_Problem"] = df[problem_col].astype(str).str.strip() if problem_col is not None else ""

    ok_values = {"DA", "YES", "OK", "O.K.", "TRUE", "1", "Y"}
    df["Result"] = df["Raw_Result"].astype(str).str.strip().str.upper().apply(lambda x: "OK" if x in ok_values else "NOK")

    df = df[["Timestamp", "Date", "Proverio", "Project", "Machine", "Dummy_Parts", "Raw_Result", "Result", "Detected_Problem"]].copy()
    df = df.dropna(subset=["Timestamp", "Date"])
    df = df[(df["Project"].astype(str).str.strip() != "") & (df["Machine"].astype(str).str.strip() != "")]
    df["Godina"] = df["Date"].dt.year
    df["Mesec"] = df["Date"].dt.month
    return df, []


def render_line_verification_module():

    try:
        df_lv_raw, used_tab = load_line_verification_raw()
        df_lv, lv_missing = prepare_line_verification_data(df_lv_raw)
    except Exception as e:
        st.error("Ne mogu da učitam Line Verification / Dummy podatke.")
        st.write(e)
        st.stop()

    if df_lv.empty:
        st.error("Nema Line Verification / Dummy podataka za prikaz. Proveri Google Sheet, naziv taba i kolone.")
        if lv_missing:
            st.write("Nedostaje:", lv_missing)
        st.write("Pronađene kolone:")
        st.write(clean_columns(df_lv_raw).columns.tolist() if 'df_lv_raw' in locals() else [])
        st.stop()

    st.sidebar.header("Line Verification filteri")

    min_date = df_lv["Date"].min().date()
    max_date = df_lv["Date"].max().date()
    date_range = st.sidebar.date_input(
        "Raspon datuma",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max(max_date, date.today()),
        format="DD.MM.YYYY",
        key="lv_date_range",
    )

    base_for_filters = df_lv.copy()
    filtered = df_lv.copy()
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date = pd.to_datetime(date_range[0])
        end_date = pd.to_datetime(date_range[1])
        filtered = filtered[(filtered["Date"] >= start_date) & (filtered["Date"] <= end_date)]

    project_values = sorted(filtered["Project"].dropna().astype(str).unique().tolist())
    ordered_projects = [p for p in PROJECT_ORDER if p in project_values]
    extra_projects = [p for p in project_values if p not in ordered_projects]
    project_options = ["Svi"] + ordered_projects + extra_projects
    selected_project = st.sidebar.selectbox("Projekat", project_options, key="lv_project_filter")
    if selected_project != "Svi":
        filtered = filtered[filtered["Project"].astype(str) == selected_project]
        base_for_filters = base_for_filters[base_for_filters["Project"].astype(str) == selected_project]

    machine_options = ["Sve"] + sorted(filtered["Machine"].dropna().astype(str).unique().tolist())
    selected_machine = st.sidebar.selectbox("Linija / Mašina", machine_options, key="lv_machine_filter")
    if selected_machine != "Sve":
        filtered = filtered[filtered["Machine"].astype(str) == selected_machine]
        base_for_filters = base_for_filters[base_for_filters["Machine"].astype(str) == selected_machine]

    inspector_options = ["Svi"] + sorted(filtered["Proverio"].dropna().astype(str).unique().tolist())
    selected_inspector = st.sidebar.selectbox("Proverio", inspector_options, key="lv_inspector_filter")
    if selected_inspector != "Svi":
        filtered = filtered[filtered["Proverio"].astype(str) == selected_inspector]
        base_for_filters = base_for_filters[base_for_filters["Proverio"].astype(str) == selected_inspector]

    result_options = ["All", "OK", "NOK"]
    selected_result = st.sidebar.selectbox("Rezultat", result_options, key="lv_result_filter")
    if selected_result != "All":
        filtered = filtered[filtered["Result"] == selected_result]

    dashboard_tab, input_overview_tab, alerts_tab = st.tabs(["Dashboard", "Pregled unosa", "Alerts"])

    with dashboard_tab:
        if filtered.empty:
            st.warning("Nema podataka za izabrane filtere.")
            st.stop()

        total_checks = len(filtered)
        ok_checks = int((filtered["Result"] == "OK").sum())
        nok_checks = int((filtered["Result"] == "NOK").sum())
        success_rate = (ok_checks / total_checks * 100) if total_checks else 0

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Broj urađenih provera", total_checks)
        k2.metric("Broj OK provera", ok_checks)
        k3.metric("Broj NOK provera", nok_checks)
        k4.metric("% uspešnosti", f"{success_rate:.2f}%")

        st.divider()

        view_project_tab, view_machine_tab, view_trend_tab, view_entries_tab = st.tabs([
            "Pregled po projektu",
            "Pregled po liniji / mašini",
            "NOK trend",
            "Pregled unosa",
        ])

        with view_project_tab:
            st.markdown("### Pregled po projektu")
            project_overview = filtered.groupby("Project").agg(
                Ukupno_provera=("Result", "size"),
                OK_provera=("Result", lambda x: int((x == "OK").sum())),
                NOK_provera=("Result", lambda x: int((x == "NOK").sum())),
            ).reset_index()
            project_overview["% uspešnosti"] = project_overview.apply(
                lambda r: (r["OK_provera"] / r["Ukupno_provera"] * 100) if r["Ukupno_provera"] else 0,
                axis=1,
            ).round(2)
            project_display = project_overview.rename(columns={
                "Project": "Projekat",
                "Ukupno_provera": "Broj provera",
                "OK_provera": "OK",
                "NOK_provera": "NOK",
            })
            st.dataframe(project_display, use_container_width=True)

            project_summary = filtered.groupby(["Project", "Result"]).size().reset_index(name="Checks")
            fig_project = px.bar(
                project_summary,
                x="Project",
                y="Checks",
                color="Result",
                barmode="group",
                title="Broj provera po projektu",
                text="Checks",
            )
            fig_project.update_traces(textposition="outside")
            st.plotly_chart(style_chart(fig_project), use_container_width=True, key="lv_project_checks")

        with view_machine_tab:
            st.markdown("### Pregled po liniji / mašini")
            machine_overview = filtered.groupby(["Project", "Machine"]).agg(
                Ukupno_provera=("Result", "size"),
                OK_provera=("Result", lambda x: int((x == "OK").sum())),
                NOK_provera=("Result", lambda x: int((x == "NOK").sum())),
            ).reset_index()
            machine_overview["% uspešnosti"] = machine_overview.apply(
                lambda r: (r["OK_provera"] / r["Ukupno_provera"] * 100) if r["Ukupno_provera"] else 0,
                axis=1,
            ).round(2)
            machine_display = machine_overview.rename(columns={
                "Project": "Projekat",
                "Machine": "Mašina",
                "Ukupno_provera": "Broj provera",
                "OK_provera": "OK",
                "NOK_provera": "NOK",
            })
            st.dataframe(machine_display, use_container_width=True)

            machine_summary = filtered.groupby(["Project", "Machine", "Result"]).size().reset_index(name="Checks")
            fig_machine = px.bar(
                machine_summary,
                x="Machine",
                y="Checks",
                color="Result",
                facet_col="Project" if machine_summary["Project"].nunique() > 1 else None,
                barmode="group",
                title="Broj provera po liniji / mašini",
                text="Checks",
            )
            fig_machine.update_traces(textposition="outside")
            st.plotly_chart(style_chart(fig_machine), use_container_width=True, key="lv_machine_checks")

        with view_trend_tab:
            st.markdown("### NOK trend po danima")
            nok_trend = filtered[filtered["Result"] == "NOK"].groupby("Date").size().reset_index(name="NOK_Checks")
            all_days = pd.DataFrame({"Date": pd.date_range(filtered["Date"].min(), filtered["Date"].max(), freq="D")})
            nok_trend = all_days.merge(nok_trend, on="Date", how="left").fillna({"NOK_Checks": 0})
            st.plotly_chart(
                create_line_chart(nok_trend, "Date", "NOK_Checks", "NOK trend po danima", "NOK provere", 0),
                use_container_width=True,
                key="lv_nok_daily_trend",
            )

        with view_entries_tab:
            st.markdown("### Pregled unosa")
            display = filtered.sort_values("Timestamp", ascending=False).copy()
            display["Timestamp"] = display["Timestamp"].dt.strftime("%d.%m.%Y %H:%M")
            display["Date"] = display["Date"].dt.strftime("%d.%m.%Y")
            display = display.rename(columns={
                "Timestamp": "Vreme unosa",
                "Date": "Datum",
                "Project": "Projekat",
                "Machine": "Mašina",
                "Dummy_Parts": "Dummy komadi",
                "Raw_Result": "Odgovor",
                "Result": "Rezultat",
                "Detected_Problem": "Detektovan problem",
            })
            display_cols = ["Vreme unosa", "Datum", "Proverio", "Projekat", "Mašina", "Dummy komadi", "Odgovor", "Rezultat", "Detektovan problem"]
            st.dataframe(display[[c for c in display_cols if c in display.columns]].head(200), use_container_width=True)

    with input_overview_tab:
        st.subheader("Pregled unosa")
        st.caption("Pregled Line Verification / Dummy unosa po projektu, mašini i detaljan spisak unosa za izabrane filtere.")

        if filtered.empty:
            st.warning("Nema podataka za izabrane filtere.")
        else:
            overview_total = len(filtered)
            overview_ok = int((filtered["Result"] == "OK").sum())
            overview_nok = int((filtered["Result"] == "NOK").sum())
            overview_rate = (overview_ok / overview_total * 100) if overview_total else 0

            oc1, oc2, oc3, oc4 = st.columns(4)
            oc1.metric("Ukupno unosa", overview_total)
            oc2.metric("OK unosa", overview_ok)
            oc3.metric("NOK unosa", overview_nok)
            oc4.metric("% uspešnosti", f"{overview_rate:.2f}%")

            st.divider()

            overview_project_tab, overview_machine_tab, overview_details_tab = st.tabs(["Pregled po projektu", "Pregled po mašini", "Detaljni unosi"])

            with overview_project_tab:
                st.markdown("### Pregled unosa po projektu")
                project_overview = filtered.groupby("Project").agg(
                    Ukupno=("Result", "size"),
                    OK=("Result", lambda x: int((x == "OK").sum())),
                    NOK=("Result", lambda x: int((x == "NOK").sum())),
                ).reset_index()
                project_overview["% uspešnosti"] = project_overview.apply(
                    lambda r: (r["OK"] / r["Ukupno"] * 100) if r["Ukupno"] else 0, axis=1
                ).round(2)
                project_display = project_overview.rename(columns={"Project": "Projekat"})
                st.dataframe(project_display, use_container_width=True)

                project_chart_df = filtered.groupby(["Project", "Result"]).size().reset_index(name="Unosa")
                fig_project_overview = px.bar(
                    project_chart_df,
                    x="Project",
                    y="Unosa",
                    color="Result",
                    barmode="group",
                    title="Pregled unosa po projektu",
                    text="Unosa",
                )
                fig_project_overview.update_traces(textposition="outside")
                st.plotly_chart(style_chart(fig_project_overview), use_container_width=True, key="lv_input_project_overview_chart")

            with overview_machine_tab:
                st.markdown("### Pregled unosa po mašini")
                machine_overview = filtered.groupby(["Project", "Machine"]).agg(
                    Ukupno=("Result", "size"),
                    OK=("Result", lambda x: int((x == "OK").sum())),
                    NOK=("Result", lambda x: int((x == "NOK").sum())),
                ).reset_index()
                machine_overview["% uspešnosti"] = machine_overview.apply(
                    lambda r: (r["OK"] / r["Ukupno"] * 100) if r["Ukupno"] else 0, axis=1
                ).round(2)
                machine_display = machine_overview.rename(columns={"Project": "Projekat", "Machine": "Mašina"})
                st.dataframe(machine_display, use_container_width=True)

                machine_chart_df = filtered.groupby(["Project", "Machine", "Result"]).size().reset_index(name="Unosa")
                fig_machine_overview = px.bar(
                    machine_chart_df,
                    x="Machine",
                    y="Unosa",
                    color="Result",
                    facet_col="Project" if machine_chart_df["Project"].nunique() > 1 else None,
                    barmode="group",
                    title="Pregled unosa po mašini",
                    text="Unosa",
                )
                fig_machine_overview.update_traces(textposition="outside")
                st.plotly_chart(style_chart(fig_machine_overview), use_container_width=True, key="lv_input_machine_overview_chart")

            with overview_details_tab:
                st.markdown("### Detaljni unosi")
                detail_display = filtered.sort_values("Timestamp", ascending=False).copy()
                detail_display["Timestamp"] = detail_display["Timestamp"].dt.strftime("%d.%m.%Y %H:%M")
                detail_display["Date"] = detail_display["Date"].dt.strftime("%d.%m.%Y")
                detail_display = detail_display.rename(columns={
                    "Timestamp": "Vreme unosa",
                    "Date": "Datum",
                    "Project": "Projekat",
                    "Machine": "Mašina",
                    "Dummy_Parts": "Dummy komadi",
                    "Raw_Result": "Odgovor",
                    "Result": "Rezultat",
                    "Detected_Problem": "Detektovan problem",
                })
                detail_cols = ["Vreme unosa", "Datum", "Proverio", "Projekat", "Mašina", "Dummy komadi", "Odgovor", "Rezultat", "Detektovan problem"]
                st.dataframe(detail_display[[c for c in detail_cols if c in detail_display.columns]], use_container_width=True)

    with alerts_tab:
        st.subheader("Alerts")
        st.caption("Automatski alarm za Line Verification / Dummy. Provera se radi za ponedeljak, a alarm se aktivira u utorak u 06:30 i traje do sledećeg ponedeljka.")

        try:
            now_local = datetime.now(ZoneInfo("Europe/Belgrade"))
        except Exception:
            now_local = datetime.now()

        today_local = now_local.date()
        current_monday = today_local - timedelta(days=today_local.weekday())
        alert_start_dt = datetime.combine(current_monday + timedelta(days=1), time(6, 30))
        alert_end_dt = datetime.combine(current_monday + timedelta(days=7), time(0, 0))
        now_naive = now_local.replace(tzinfo=None) if getattr(now_local, "tzinfo", None) else now_local

        alert_is_active = alert_start_dt <= now_naive < alert_end_dt
        selected_alarm_date = current_monday
        alarm_day = pd.to_datetime(selected_alarm_date).normalize()
        alarm_df = base_for_filters[base_for_filters["Date"] == alarm_day].copy()

        s1, s2, s3 = st.columns(3)
        s1.metric("Ponedeljak koji se proverava", selected_alarm_date.strftime("%d.%m.%Y"))
        s2.metric("Alarm start", alert_start_dt.strftime("%d.%m.%Y %H:%M"))
        s3.metric("Alarm važi do", alert_end_dt.strftime("%d.%m.%Y %H:%M"))

        if not alert_is_active:
            if now_naive < alert_start_dt:
                st.info(f"ℹ️ Alarm još nije aktivan. Sledeća automatska provera je u utorak {alert_start_dt.strftime('%d.%m.%Y %H:%M')}.")
            else:
                st.info("ℹ️ Trenutni alarm ciklus je završen. Novi alarm ciklus počinje sledećeg utorka u 06:30.")

        expected_base = base_for_filters.copy()
        if selected_project != "Svi":
            expected_base = expected_base[expected_base["Project"].astype(str) == selected_project]
        if selected_machine != "Sve":
            expected_base = expected_base[expected_base["Machine"].astype(str) == selected_machine]
        if selected_inspector != "Svi":
            expected_base = expected_base[expected_base["Proverio"].astype(str) == selected_inspector]

        expected_projects = sorted(expected_base["Project"].dropna().astype(str).unique().tolist())
        expected_project_machine = expected_base[["Project", "Machine"]].drop_duplicates().copy()

        if expected_project_machine.empty:
            st.warning("Nema istorijskih Project/Machine kombinacija za izabrane filtere. Ne mogu da izračunam očekivane alarme.")
            st.stop()

        project_day_counts = alarm_df.groupby("Project").size().reset_index(name="Unosa") if not alarm_df.empty else pd.DataFrame(columns=["Project", "Unosa"])
        project_status = pd.DataFrame({"Project": expected_projects}).merge(project_day_counts, on="Project", how="left").fillna({"Unosa": 0})
        project_status["Status"] = project_status["Unosa"].apply(lambda x: "OK" if x > 0 else ("ALARM" if alert_is_active else "WAITING"))
        project_status["Alert"] = project_status.apply(
            lambda r: "Ima unos" if r["Unosa"] > 0 else ("Nema unos" if alert_is_active else "Čeka utorak 06:30"),
            axis=1,
        )

        machine_day_counts = alarm_df.groupby(["Project", "Machine"]).size().reset_index(name="Unosa") if not alarm_df.empty else pd.DataFrame(columns=["Project", "Machine", "Unosa"])
        machine_status = expected_project_machine.merge(machine_day_counts, on=["Project", "Machine"], how="left").fillna({"Unosa": 0})
        machine_status["Status"] = machine_status["Unosa"].apply(lambda x: "OK" if x > 0 else ("ALARM" if alert_is_active else "WAITING"))
        machine_status["Alert"] = machine_status.apply(
            lambda r: "Ima unos" if r["Unosa"] > 0 else ("Nema unos" if alert_is_active else "Čeka utorak 06:30"),
            axis=1,
        )

        total_expected_projects = len(project_status)
        project_alarm_count = int((project_status["Status"] == "ALARM").sum())
        total_expected_machines = len(machine_status)
        machine_alarm_count = int((machine_status["Status"] == "ALARM").sum())

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Očekivani projekti", total_expected_projects)
        c2.metric("Projekti bez unosa", project_alarm_count)
        c3.metric("Očekivane mašine", total_expected_machines)
        c4.metric("Mašine bez unosa", machine_alarm_count)

        if alert_is_active and (project_alarm_count > 0 or machine_alarm_count > 0):
            missing_projects = project_status.loc[project_status["Status"] == "ALARM", "Project"].tolist()
            missing_machines = machine_status.loc[machine_status["Status"] == "ALARM", ["Project", "Machine"]].copy()
            msg_lines = [f"🚨 Line Verification / Dummy alarm za ponedeljak {selected_alarm_date.strftime('%d.%m.%Y')}"]
            msg_lines.append(f"Alarm je aktivan od {alert_start_dt.strftime('%d.%m.%Y %H:%M')} do {alert_end_dt.strftime('%d.%m.%Y %H:%M')}.")
            if missing_projects:
                msg_lines.append("Projekti bez unosa: " + ", ".join(missing_projects))
            if not missing_machines.empty:
                machine_text = "; ".join([f"{r.Project} / {r.Machine}" for r in missing_machines.itertuples(index=False)])
                msg_lines.append("Mašine bez unosa: " + machine_text)
            st.error("\n".join(msg_lines))
        elif alert_is_active:
            st.success(f"✅ Svi očekivani projekti i mašine imaju Line Verification / Dummy unos za ponedeljak {selected_alarm_date.strftime('%d.%m.%Y')}.")
        else:
            st.info("Status je pripremljen, ali se ALARM status neće aktivirati pre utorka u 06:30.")

        project_alert_tab, machine_alert_tab, details_alert_tab = st.tabs(["Pregled po projektu", "Pregled po mašini", "Unosi za ponedeljak"])

        with project_alert_tab:
            st.markdown("### Pregled po projektu")
            project_display = project_status.copy()
            project_display = project_display.rename(columns={"Project": "Projekat"})
            project_display["Datum"] = selected_alarm_date.strftime('%d.%m.%Y')
            project_display = project_display[["Datum", "Projekat", "Unosa", "Status", "Alert"]]
            st.dataframe(project_display, use_container_width=True)

            fig_project_alert = px.bar(
                project_status,
                x="Project",
                y="Unosa",
                color="Status",
                title="Alarm pregled po projektu",
                text="Unosa",
            )
            fig_project_alert.update_traces(textposition="outside")
            st.plotly_chart(style_chart(fig_project_alert), use_container_width=True, key="lv_alarm_project_chart")

        with machine_alert_tab:
            st.markdown("### Pregled po mašini")
            machine_display = machine_status.copy()
            machine_display = machine_display.rename(columns={"Project": "Projekat", "Machine": "Mašina"})
            machine_display["Datum"] = selected_alarm_date.strftime('%d.%m.%Y')
            machine_display = machine_display[["Datum", "Projekat", "Mašina", "Unosa", "Status", "Alert"]]
            st.dataframe(machine_display, use_container_width=True)

            fig_machine_alert = px.bar(
                machine_status,
                x="Machine",
                y="Unosa",
                color="Status",
                facet_col="Project" if machine_status["Project"].nunique() > 1 else None,
                title="Alarm pregled po mašini",
                text="Unosa",
            )
            fig_machine_alert.update_traces(textposition="outside")
            st.plotly_chart(style_chart(fig_machine_alert), use_container_width=True, key="lv_alarm_machine_chart")

        with details_alert_tab:
            st.markdown("### Unosi za proveravani ponedeljak")
            if alarm_df.empty:
                st.warning("Nema nijedan unos za proveravani ponedeljak.")
            else:
                c1, c2, c3 = st.columns(3)
                c1.metric("Unosa za ponedeljak", len(alarm_df))
                c2.metric("OK", int((alarm_df["Result"] == "OK").sum()))
                c3.metric("NOK", int((alarm_df["Result"] == "NOK").sum()))

                display_alarm = alarm_df.sort_values("Timestamp", ascending=False).copy()
                display_alarm["Timestamp"] = display_alarm["Timestamp"].dt.strftime("%d.%m.%Y %H:%M")
                display_alarm["Date"] = display_alarm["Date"].dt.strftime("%d.%m.%Y")
                display_cols = ["Timestamp", "Proverio", "Project", "Machine", "Dummy_Parts", "Raw_Result", "Result", "Detected_Problem"]
                st.dataframe(display_alarm[[c for c in display_cols if c in display_alarm.columns]], use_container_width=True)

        st.info("Napomena: alarm koristi istorijske Project/Machine kombinacije kao očekivane provere. Ako dodaš novu mašinu, prvi unos će je automatski ubaciti u alarm pregled.")



# =====================================================
# OEE MODULE HELPERS
# =====================================================

def safe_div(numerator, denominator):
    try:
        denominator = float(denominator)
        numerator = float(numerator)
        if not math.isfinite(numerator) or not math.isfinite(denominator) or denominator == 0:
            return 0
        return numerator / denominator
    except Exception:
        return 0


def cap_percent(value, lower=0, upper=100):
    try:
        value = float(value)
        if not math.isfinite(value):
            value = float(lower)
    except Exception:
        value = float(lower)
    return max(lower, min(upper, value))



def parse_oee_date_series(series):
    """Robust OEE date parser.

    Google Sheets can return dates as:
    - Serbian/European text: 15.06.2026 or 15/06/2026
    - ISO text: 2026-06-15
    - Google/Excel serial number

    The OEE dashboard must always use the real date from the Datum column and
    never the order in which rows were entered in the sheet.
    """
    s = series.copy()

    # Parse ISO and European text independently so ambiguous ISO values are not
    # reinterpreted as day-first dates.
    parsed = parse_mixed_datetime_series(s)

    # Second pass: handle Google/Excel serial dates if any values are numeric.
    numeric = pd.to_numeric(s, errors="coerce")
    serial_mask = parsed.isna() & numeric.notna()
    if serial_mask.any():
        # Google Sheets / Excel serial date origin.
        parsed.loc[serial_mask] = pd.to_datetime(
            numeric.loc[serial_mask],
            unit="D",
            origin="1899-12-30",
            errors="coerce",
        )

    return parsed.dt.normalize()


def normalise_oee_master(df_raw):
    df = clean_columns(df_raw)
    rename_map = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key == "project": rename_map[col] = "Project"
        elif key == "process": rename_map[col] = "Process"
        elif key == "machine": rename_map[col] = "Machine"
        elif key in ["ct", "ct_s", "ct sec", "ct_sec"]: rename_map[col] = "CT"
        elif key == "target": rename_map[col] = "Target"
        elif key == "active": rename_map[col] = "Active"
        elif key in ["1 shift", "shift_min", "shift min", "shift"]: rename_map[col] = "1 shift"
    df = df.rename(columns=rename_map)
    required = ["Project", "Process", "Machine", "CT", "Target", "Active", "1 shift"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.DataFrame(), missing
    df = df[required].copy()
    for c in ["Project", "Process", "Machine", "Active"]:
        df[c] = df[c].astype(str).str.strip()
    for c in ["CT", "Target", "1 shift"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df = df[df["Active"].astype(str).str.strip().str.upper().isin(["DA", "YES", "TRUE", "1"])]
    df = df[(df["Project"] != "") & (df["Process"] != "") & (df["Machine"] != "")]
    return df.reset_index(drop=True), []


def _worksheet_range_to_dataframe(ws, a1_range):
    """Read only the columns used by a table instead of the worksheet's full used range.

    Google Sheets often keeps formatting or old values far to the right of the real table.
    ``get_all_records()`` then transfers those unused cells on every cache refresh.  A bounded
    range is substantially faster and all OEE normalisers already handle numeric/string values.
    """
    try:
        values = ws.get(a1_range, value_render_option="UNFORMATTED_VALUE")
    except TypeError:
        # Compatibility with older gspread releases.
        values = ws.get(a1_range)
    if not values:
        return pd.DataFrame()

    headers = [str(x).replace("\ufeff", "").replace("​", "").strip() for x in values[0]]
    while headers and not headers[-1]:
        headers.pop()
    if not headers:
        return pd.DataFrame()

    rows = []
    for row in values[1:]:
        padded = list(row) + [""] * max(0, len(headers) - len(row))
        rows.append(padded[:len(headers)])
    return pd.DataFrame(rows, columns=headers)


@st.cache_data(ttl=600, show_spinner=False)
def load_oee_master():
    client = get_client()
    ws, used_tab = open_first_existing_worksheet(client, OEE_SHEET_ID, OEE_MASTER_SHEET_NAMES)
    raw = _worksheet_range_to_dataframe(ws, "A:G")
    return normalise_oee_master(raw)


@st.cache_data(ttl=300, show_spinner=False)
def load_oee_input():
    client = get_client()
    ws, used_tab = open_first_existing_worksheet(client, OEE_SHEET_ID, OEE_INPUT_SHEET_NAMES)
    raw = _worksheet_range_to_dataframe(ws, "A:R")
    return prepare_oee_input_data(raw)


def prepare_oee_input_data(df_raw):
    if df_raw is None or df_raw.empty:
        return pd.DataFrame(), []
    df = clean_columns(df_raw)
    rename_map = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key == "datum": rename_map[col] = "Datum"
        elif key == "cw": rename_map[col] = "CW"
        elif key == "dan": rename_map[col] = "Dan"
        elif key in ["project", "projekat"]: rename_map[col] = "Project"
        elif key in ["process", "proces"]: rename_map[col] = "Process"
        elif key in ["machine", "mašina", "masina"]: rename_map[col] = "Machine"
        elif key in ["shift", "smena"]: rename_map[col] = "Shift"
        elif key in ["ct_s", "ct", "ct s"]: rename_map[col] = "CT_s"
        elif key == "open time": rename_map[col] = "Open time"
        elif key == "number of shifts": rename_map[col] = "Number of shifts"
        elif key == "ok pcs": rename_map[col] = "OK pcs."
        elif key == "ok pcs.": rename_map[col] = "OK pcs."
        elif key == "nok pcs": rename_map[col] = "NOK pcs."
        elif key == "nok pcs.": rename_map[col] = "NOK pcs."
        elif key == "total pcs": rename_map[col] = "Total Pcs"
        elif key == "down time": rename_map[col] = "Down time"
        elif key == "organisational loss": rename_map[col] = "Organisational loss"
        elif key == "target pcs": rename_map[col] = "Target pcs."
        elif key == "target pcs.": rename_map[col] = "Target pcs."
        elif key in ["submitted_by", "submitted by", "created_by", "created by", "unos napravio", "uneseno od"]: rename_map[col] = "Submitted_By"
        elif key in ["included_shifts", "included shifts", "ukljucene smene", "uključene smene"]: rename_map[col] = "Included_Shifts"
    df = df.rename(columns=rename_map)
    required = ["Datum", "CW", "Dan", "Project", "Process", "Machine", "CT_s", "Open time", "Number of shifts", "OK pcs.", "NOK pcs.", "Total Pcs", "Down time", "Organisational loss", "Target pcs."]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.DataFrame(), missing
    optional_cols = ["Submitted_By", "Shift", "Included_Shifts"]
    for col in optional_cols:
        if col not in df.columns:
            df[col] = ""
    df = df[required + optional_cols].copy()
    # IMPORTANT:
    # OEE must be calculated by the real production date from column "Datum",
    # not by the order in which rows are entered in Google Sheets.
    df["Datum"] = parse_oee_date_series(df["Datum"])

    for c in ["CW", "CT_s", "Open time", "Number of shifts", "OK pcs.", "NOK pcs.", "Total Pcs", "Down time", "Organisational loss", "Target pcs."]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    for c in ["Project", "Process", "Machine", "Submitted_By", "Shift", "Included_Shifts"]:
        if c in df.columns:
            df[c] = df[c].astype(str).str.strip()

    # Rows created before v9.3 have no Shift value. Treat them as a combined
    # daily entry so old production data remains valid and is never duplicated.
    df.loc[df["Shift"].eq(""), "Shift"] = "All shifts"

    df = df.dropna(subset=["Datum"])
    if df.empty:
        return df, []

    # Recalculate calendar fields from Datum so wrong/old input values in CW/Dan
    # cannot remove Monday/other days from charts.
    # This is the key rule: row input order in Google Sheets is irrelevant.
    # If Monday is entered after Tuesday/Wednesday, it still belongs to the same ISO week
    # and is included in Weekly/Monthly/Yearly aggregation.
    iso = df["Datum"].dt.isocalendar()
    df["Godina"] = iso.year.astype(int)
    # Keep ISO year for Year + CW matching, and calendar year for monthly/yearly views.
    # These differ around New Year (for example 01 January can belong to the previous ISO year).
    df["Calendar_Year"] = df["Datum"].dt.year.astype(int)
    df["Week"] = iso.week.astype(int)
    df["Mesec"] = df["Datum"].dt.month.astype(int)
    df["CW"] = df["Week"].astype(int)
    df["Dan"] = df["Datum"].dt.day_name()
    df["Week_Start"] = df["Datum"] - pd.to_timedelta(df["Datum"].dt.weekday, unit="D")
    df["Week_End"] = df["Week_Start"] + pd.Timedelta(days=6)

    # Stable chronological ordering for all OEE pages and charts.
    # We also keep original rows; no drop_duplicates here, because several machines/processes
    # can validly exist on the same production date.
    df = df.sort_values(["Godina", "Week", "Datum", "Project", "Process", "Machine", "Shift"]).reset_index(drop=True)

    return calculate_oee_metrics(df), []


def calculate_oee_metrics(df):
    df = df.copy()

    # Final OEE rule set v1.5.1:
    # Plant Run Time   = Open time - Down time
    # Machine Run Time for CT performance = Open time - Down time - Organisational loss
    # Plant Availability   = (Open time - Down time) / Open time
    # Machine Availability = Machine Run Time / Machine Available Time
    # Machine Available Time excludes organisational loss so the KPI shows only machine losses.
    df["Plant_Run_Time"] = (df["Open time"] - df["Down time"]).clip(lower=0)
    df["Machine_Run_Time"] = (df["Open time"] - df["Down time"] - df["Organisational loss"]).clip(lower=0)
    df["Machine_Availability_Numerator"] = df["Machine_Run_Time"]
    df["Machine_Available_Time"] = (df["Open time"] - df["Organisational loss"]).clip(lower=0)
    df["Ideal_Time_min"] = df["Total Pcs"] * df["CT_s"] / 60

    def pct(numerator, denominator, upper=100):
        denominator = pd.to_numeric(denominator, errors="coerce").fillna(0)
        numerator = pd.to_numeric(numerator, errors="coerce").fillna(0)
        result = numerator.div(denominator.where(denominator.ne(0))).mul(100).fillna(0)
        return result.clip(lower=0, upper=upper)

    df["Quality_%"] = pct(df["OK pcs."], df["Total Pcs"])
    df["Plant_Availability_%"] = pct(df["Plant_Run_Time"], df["Open time"])
    df["Machine_Availability_%"] = pct(df["Machine_Availability_Numerator"], df["Machine_Available_Time"])
    df["Plant_Performance_CT_Raw_%"] = pct(df["Ideal_Time_min"], df["Plant_Run_Time"], upper=float("inf"))
    df["Machine_Performance_CT_Raw_%"] = pct(df["Ideal_Time_min"], df["Machine_Run_Time"], upper=float("inf"))
    df["Plant_Performance_CT_%"] = df["Plant_Performance_CT_Raw_%"].clip(upper=100)
    df["Machine_Performance_CT_%"] = df["Machine_Performance_CT_Raw_%"].clip(upper=100)
    df["Performance_Target_%"] = pct(df["OK pcs."], df["Target pcs."])

    df["Plant_OEE_CT_%"] = df["Plant_Availability_%"] * df["Plant_Performance_CT_%"] * df["Quality_%"] / 10000
    df["Machine_OEE_CT_%"] = df["Machine_Availability_%"] * df["Machine_Performance_CT_%"] * df["Quality_%"] / 10000
    df["Plant_OEE_Target_%"] = df["Plant_Availability_%"] * df["Performance_Target_%"] * df["Quality_%"] / 10000
    df["Machine_OEE_Target_%"] = df["Machine_Availability_%"] * df["Performance_Target_%"] * df["Quality_%"] / 10000

    oee_cols = ["Plant_OEE_CT_%", "Machine_OEE_CT_%", "Plant_OEE_Target_%", "Machine_OEE_Target_%"]
    for col in oee_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).clip(lower=0, upper=100)

    return df


def aggregate_oee(df, group_cols):
    if df.empty:
        return pd.DataFrame()
    agg = df.groupby(group_cols, dropna=False, sort=True).agg(
        Open_Time=("Open time", "sum"),
        Down_Time=("Down time", "sum"),
        Organisational_Loss=("Organisational loss", "sum"),
        OK_pcs=("OK pcs.", "sum"),
        NOK_pcs=("NOK pcs.", "sum"),
        Total_Pcs=("Total Pcs", "sum"),
        Target_pcs=("Target pcs.", "sum"),
        Ideal_Time_min=("Ideal_Time_min", "sum"),
        Records=("Machine", "count"),
    ).reset_index()
    agg["Plant_Run_Time"] = (agg["Open_Time"] - agg["Down_Time"]).clip(lower=0)
    agg["Machine_Run_Time"] = (agg["Open_Time"] - agg["Down_Time"] - agg["Organisational_Loss"]).clip(lower=0)
    agg["Machine_Availability_Numerator"] = agg["Machine_Run_Time"]
    agg["Machine_Available_Time"] = (agg["Open_Time"] - agg["Organisational_Loss"]).clip(lower=0)
    def pct(numerator, denominator, upper=100):
        # numpy instead of pandas where/div/clip: same result, several times faster
        # (aggregate_oee runs about ten times on every OEE page).
        num = np.nan_to_num(np.asarray(pd.to_numeric(numerator, errors="coerce"), dtype=float))
        den = np.nan_to_num(np.asarray(pd.to_numeric(denominator, errors="coerce"), dtype=float))
        with np.errstate(divide="ignore", invalid="ignore"):
            result = np.where(den != 0, num / np.where(den != 0, den, 1.0) * 100.0, 0.0)
        return pd.Series(np.clip(np.nan_to_num(result), 0, upper), index=numerator.index)

    agg["Quality_%"] = pct(agg["OK_pcs"], agg["Total_Pcs"])
    agg["Plant_Availability_%"] = pct(agg["Plant_Run_Time"], agg["Open_Time"])
    agg["Machine_Availability_%"] = pct(agg["Machine_Availability_Numerator"], agg["Machine_Available_Time"])
    agg["Plant_Performance_CT_%"] = pct(agg["Ideal_Time_min"], agg["Plant_Run_Time"])
    agg["Machine_Performance_CT_%"] = pct(agg["Ideal_Time_min"], agg["Machine_Run_Time"])
    agg["Performance_Target_%"] = pct(agg["OK_pcs"], agg["Target_pcs"])
    agg["Plant_OEE_CT_%"] = agg["Plant_Availability_%"] * agg["Plant_Performance_CT_%"] * agg["Quality_%"] / 10000
    agg["Machine_OEE_CT_%"] = agg["Machine_Availability_%"] * agg["Machine_Performance_CT_%"] * agg["Quality_%"] / 10000
    agg["Plant_OEE_Target_%"] = agg["Plant_Availability_%"] * agg["Performance_Target_%"] * agg["Quality_%"] / 10000
    agg["Machine_OEE_Target_%"] = agg["Machine_Availability_%"] * agg["Performance_Target_%"] * agg["Quality_%"] / 10000

    oee_cols = ["Plant_OEE_CT_%", "Machine_OEE_CT_%", "Plant_OEE_Target_%", "Machine_OEE_Target_%"]
    for col in oee_cols:
        agg[col] = pd.to_numeric(agg[col], errors="coerce").fillna(0).clip(lower=0, upper=100)

    return agg


def aggregate_oee_as_weighted_daily(df):
    """Period KPI built from daily results, so a strong day cannot hide a weak one.

    1. Each day + machine is calculated from its summed raw shift data and each
       component is capped at 100% (over-performance or a wrong CT on one day
       can no longer erase another day's loss - the v9.4.9 rule that had been
       lost again).
    2. Every component is averaged with the weight of its own denominator
       (Availability: available time, Performance: run time / target pieces,
       Quality: total pieces).
    3. OEE = Availability x Performance x Quality, so the card stays consistent.
    """
    if df.empty:
        return pd.DataFrame()

    work = df.copy()
    work["Datum"] = parse_oee_date_series(work["Datum"])
    work = work.dropna(subset=["Datum"])
    if work.empty:
        return pd.DataFrame()

    totals = aggregate_oee(work.assign(OEE_Total="Total"), ["OEE_Total"])
    group_cols = ["Datum"] + [c for c in ("Project", "Process", "Machine") if c in work.columns]
    daily = aggregate_oee(work, group_cols)
    if daily.empty or totals.empty:
        return totals

    def weighted(value_col, weight_col):
        weights = pd.to_numeric(daily[weight_col], errors="coerce").fillna(0).clip(lower=0)
        values = pd.to_numeric(daily[value_col], errors="coerce").fillna(0)
        total_weight = float(weights.sum())
        if total_weight <= 0:
            return float(totals.iloc[0].get(value_col, 0) or 0)
        return float((values * weights).sum() / total_weight)

    rules = {
        "Plant_Availability_%": "Open_Time",
        "Machine_Availability_%": "Machine_Available_Time",
        "Plant_Performance_CT_%": "Plant_Run_Time",
        "Machine_Performance_CT_%": "Machine_Run_Time",
        "Performance_Target_%": "Target_pcs",
        "Quality_%": "Total_Pcs",
    }
    result = totals.copy()
    for value_col, weight_col in rules.items():
        result.loc[result.index[0], value_col] = min(max(weighted(value_col, weight_col), 0.0), 100.0)

    row = result.iloc[0]
    result.loc[result.index[0], "Plant_OEE_CT_%"] = row["Plant_Availability_%"] * row["Plant_Performance_CT_%"] * row["Quality_%"] / 10000
    result.loc[result.index[0], "Machine_OEE_CT_%"] = row["Machine_Availability_%"] * row["Machine_Performance_CT_%"] * row["Quality_%"] / 10000
    result.loc[result.index[0], "Plant_OEE_Target_%"] = row["Plant_Availability_%"] * row["Performance_Target_%"] * row["Quality_%"] / 10000
    result.loc[result.index[0], "Machine_OEE_Target_%"] = row["Machine_Availability_%"] * row["Performance_Target_%"] * row["Quality_%"] / 10000
    for col in ("Plant_OEE_CT_%", "Machine_OEE_CT_%", "Plant_OEE_Target_%", "Machine_OEE_Target_%"):
        result[col] = pd.to_numeric(result[col], errors="coerce").fillna(0).clip(lower=0, upper=100)
    return result


OEE_INPUT_COLUMNS = [
    "Datum", "CW", "Dan", "Project", "Process", "Machine", "CT_s",
    "Open time", "Number of shifts", "OK pcs.", "NOK pcs.", "Total Pcs",
    "Down time", "Organisational loss", "Target pcs.", "Submitted_By", "Shift", "Included_Shifts"
]

OEE_SHIFT_OPTIONS = [
    "1st shift (06:00-14:00)",
    "2nd shift (14:00-22:00)",
    "3rd shift (22:00-06:00)",
    "All shifts",
]


def ensure_oee_input_columns(ws):
    """Add audit/shift columns to OEE_input without moving legacy columns or data.

    v9.4.2 adds Included_Shifts at the end of the row. Existing A:Q data is never
    moved; the new field is appended as column R and is populated only by new or
    updated entries.
    """
    headers = [str(h).replace("\ufeff", "").replace("​", "").strip() for h in ws.row_values(1)]
    if not headers:
        ws.update("A1:R1", [OEE_INPUT_COLUMNS])
        return OEE_INPUT_COLUMNS

    changed = False

    if not headers or all(h == "" for h in headers):
        headers = OEE_INPUT_COLUMNS.copy()
        changed = True
    else:
        # Keep existing headers and append missing optional columns. Shift remains
        # column Q; Included_Shifts is appended as R, so legacy production rows stay intact.
        normalized = [re.sub(r"[^a-z0-9]+", "", h.lower()) for h in headers]
        if "submittedby" not in normalized:
            headers.append("Submitted_By")
            normalized.append("submittedby")
            changed = True
        if "shift" not in normalized:
            headers.append("Shift")
            normalized.append("shift")
            changed = True
        if "includedshifts" not in normalized:
            headers.append("Included_Shifts")
            changed = True

    if changed:
        end_col = _column_number_to_letter(len(headers))
        ws.update(f"A1:{end_col}1", [headers])
    return headers


def get_oee_input_ws():
    client = get_client()
    ws, used_tab = open_first_existing_worksheet(client, OEE_SHEET_ID, OEE_INPUT_SHEET_NAMES)
    ensure_oee_input_columns(ws)
    return ws


def get_current_oee_submitter():
    user = st.session_state.get("user", {}) if "st" in globals() else {}
    return str(user.get("full_name") or user.get("username") or "Unknown").strip()


def _oee_included_shifts_text(shift, included_shifts=None):
    """Return a compact, analysis-friendly description of the selected shifts."""
    shift_value = str(shift or "All shifts").strip()
    if shift_value != "All shifts":
        if shift_value.startswith("1st"):
            return "1st"
        if shift_value.startswith("2nd"):
            return "2nd"
        if shift_value.startswith("3rd"):
            return "3rd"
        return shift_value

    if included_shifts is None:
        return ""
    if isinstance(included_shifts, str):
        values = [x.strip() for x in re.split(r"[,|;]+", included_shifts) if x.strip()]
    else:
        values = [str(x).strip() for x in included_shifts if str(x).strip()]
    order = {"1st": 1, "2nd": 2, "3rd": 3}
    values = sorted(dict.fromkeys(values), key=lambda x: order.get(x, 99))
    return " | ".join(values)


def build_oee_row(selected_date, project, process, machine, ct, target, shift_min, number_of_shifts, ok_pcs, nok_pcs, down_time, org_loss, submitted_by="", shift="All shifts", included_shifts=None):
    dt = pd.to_datetime(selected_date)
    open_time = float(number_of_shifts) * float(shift_min)
    target_total = float(target) * float(number_of_shifts)
    total_pcs = int(ok_pcs) + int(nok_pcs)
    return [
        dt.strftime("%d.%m.%Y"),
        int(dt.isocalendar().week),
        dt.strftime("%A"),
        project,
        process,
        machine,
        float(ct),
        float(open_time),
        float(number_of_shifts),
        int(ok_pcs),
        int(nok_pcs),
        int(total_pcs),
        float(down_time),
        float(org_loss),
        float(target_total),
        str(submitted_by or get_current_oee_submitter()),
        str(shift or "All shifts"),
        _oee_included_shifts_text(shift, included_shifts),
    ]


def find_oee_existing_record(ws, selected_date, project, process, machine, shift):
    """Return an exact-shift row and incompatible combined/individual rows.

    This is important because the same machine can be used for separate processes,
    for example Inspection Rotor and Inspection Stator, with different CT values.

    Uses batch_get on only the needed columns instead of reading the whole sheet.
    OEE_INPUT fixed layout:
    A = Datum, D = Project, E = Process, F = Machine, Q = Shift
    """
    target_date = pd.to_datetime(selected_date).strftime("%d.%m.%Y")
    target_project = str(project).strip()
    target_process = str(process).strip()
    target_machine = str(machine).strip()
    target_shift = str(shift or "All shifts").strip()

    try:
        with fresh_reads():
            columns = ws.batch_get(["A:A", "D:D", "E:E", "F:F", "Q:Q"])
    except Exception:
        # Fallback if batch_get is not available in the installed gspread version.
        with fresh_reads():
            values = ws.get_all_values()
        columns = [
            [[row[0]] for row in values if len(row) > 0],
            [[row[3]] for row in values if len(row) > 3],
            [[row[4]] for row in values if len(row) > 4],
            [[row[5]] for row in values if len(row) > 5],
            [[row[16]] for row in values if len(row) > 16],
        ]

    dates = [r[0] if r else "" for r in columns[0]] if len(columns) > 0 else []
    projects = [r[0] if r else "" for r in columns[1]] if len(columns) > 1 else []
    processes = [r[0] if r else "" for r in columns[2]] if len(columns) > 2 else []
    machines = [r[0] if r else "" for r in columns[3]] if len(columns) > 3 else []
    shifts = [r[0] if r else "" for r in columns[4]] if len(columns) > 4 else []

    max_len = max(len(dates), len(projects), len(processes), len(machines), len(shifts), 1)
    matches = []
    for i in range(1, max_len):  # skip header row; sheet row number = i + 1
        row_date = str(dates[i]).strip() if i < len(dates) else ""
        parsed = parse_mixed_datetime(row_date)
        row_date_norm = parsed.strftime("%d.%m.%Y") if not pd.isna(parsed) else row_date
        row_project = str(projects[i]).strip() if i < len(projects) else ""
        row_process = str(processes[i]).strip() if i < len(processes) else ""
        row_machine = str(machines[i]).strip() if i < len(machines) else ""
        row_shift = str(shifts[i]).strip() if i < len(shifts) else ""
        if not row_shift:
            row_shift = "All shifts"

        if (
            row_date_norm == target_date
            and row_project == target_project
            and row_process == target_process
            and row_machine == target_machine
        ):
            matches.append({"row": i + 1, "shift": row_shift})

    exact_row = next((m["row"] for m in matches if m["shift"] == target_shift), None)
    if target_shift == "All shifts":
        conflicts = [m for m in matches if m["shift"] != "All shifts"]
    else:
        conflicts = [m for m in matches if m["shift"] == "All shifts"]
    return {"exact_row": exact_row, "conflicts": conflicts, "matches": matches}


def find_oee_existing_row(ws, selected_date, project, process, machine, shift="All shifts"):
    """Backward-compatible exact duplicate helper."""
    return find_oee_existing_record(ws, selected_date, project, process, machine, shift)["exact_row"]


def save_oee_record(row_values, existing_row=None, ws=None):
    if ws is None:
        ws = get_oee_input_ws()
    if existing_row:
        old_ct = None
        try:
            old_row = ws.row_values(int(existing_row))
            old_ct = normalize_float_value(old_row[6] if len(old_row) >= 7 else "", None)
        except Exception:
            old_ct = None

        cell_range = f"A{existing_row}:R{existing_row}"
        ws.update(cell_range, [_safe_row(row_values)], value_input_option="USER_ENTERED")

        try:
            new_ct = normalize_float_value(row_values[6], None)
            if old_ct is not None and new_ct is not None and abs(float(old_ct) - float(new_ct)) > 1e-9:
                send_bn_change_email({
                    "Date": row_values[0],
                    "Project": row_values[3],
                    "Process": row_values[4],
                    "Machine": row_values[5],
                    "Old_BN": old_ct,
                    "New_BN": new_ct,
                    "Changed_By": row_values[15] if len(row_values) > 15 else get_current_oee_submitter(),
                })
        except Exception as exc:
            st.session_state["_oee_save_notification_warning"] = (
                "OEE zapis je sačuvan, ali obaveštenje o promeni CT nije poslato: "
                f"{type(exc).__name__}: {exc}"
            )

        # Immediately invalidate cached OEE/dashboard data after update.
        # Without this, a backdated Monday entry can be saved correctly in Google Sheets
        # but Weekly/Monthly/Yearly pages can still show the old cached Tuesday/Wednesday-only view.
        load_oee_input.clear()
        return "updated"
    ws.append_row(_safe_row(row_values), value_input_option="USER_ENTERED", table_range="A1")
    # Immediately invalidate cached OEE/dashboard data after append.
    # OEE aggregation is calculated from all real production dates, not from row order.
    load_oee_input.clear()
    return "saved"



IWON_TARGET_TAB_GID = 1806481969  # the tab where the targets are typed by hand


def _norm_tab_name(name):
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower())


def _iwon_target_tabs():
    """Tabs that can hold IWON targets: the hand-made tab (by its ID) first, then the known names."""
    spreadsheet = get_spreadsheet(OEE_IWON_SHEET_ID)
    tabs = spreadsheet.worksheets()
    ordered = [ws for ws in tabs if getattr(ws, "id", None) == IWON_TARGET_TAB_GID]
    names = {_norm_tab_name(n) for n in OEE_IWON_TARGET_SHEET_NAMES}
    ordered += [ws for ws in tabs if _norm_tab_name(ws.title) in names and ws not in ordered]
    return ordered


def _tab_values_unformatted(ws):
    try:
        return ws.get("A1:BZ2000", value_render_option="UNFORMATTED_VALUE") or []
    except TypeError:
        return ws.get_all_values()


def _is_app_target_layout(values):
    head = [str(x).strip() for x in (values[0] if values else [])][:5]
    return not values or head == OEE_IWON_TARGET_COLUMNS[:5]


@st.cache_data(ttl=120, show_spinner=False)
def load_iwon_target_sources():
    """Every tab with targets: (title, gid, parsed rows, read info, app-layout?)."""
    sources = []
    for ws in _iwon_target_tabs():
        values = _tab_values_unformatted(ws)
        frame, info = oi.parse_iwon_targets(values, default_year=_now_local().year)
        sources.append({"title": ws.title, "gid": getattr(ws, "id", None), "frame": frame, "info": info,
                        "app_layout": _is_app_target_layout(values)})
    return sources


def load_oee_iwon_targets():
    """Targets from all target tabs. The hand-made tab (gid in the link) wins for the same week."""
    frames = [src["frame"] for src in reversed(load_iwon_target_sources()) if not src["frame"].empty]
    if not frames:
        return pd.DataFrame(columns=OEE_IWON_TARGET_COLUMNS)
    data = pd.concat(frames, ignore_index=True)
    data["_k"] = data["Project"].str.strip().str.casefold() + "|" + data["Process"].str.strip().str.casefold()
    data = data.drop_duplicates(subset=["Year", "CW", "_k"], keep="last").drop(columns=["_k"])
    data["Updated_By"], data["Updated_At"] = "", ""
    data["Year"] = data["Year"].astype(int)
    data["CW"] = data["CW"].astype(int)
    return data[OEE_IWON_TARGET_COLUMNS].reset_index(drop=True)


load_oee_iwon_targets.clear = lambda: load_iwon_target_sources.clear()


def iwon_targets_writable_ws():
    """Where the app may save targets: a tab in the app layout (never rewrites a hand-made layout)."""
    for ws in _iwon_target_tabs():
        if _is_app_target_layout(_tab_values_unformatted(ws)[:1]):
            return ws
    spreadsheet = get_spreadsheet(OEE_IWON_SHEET_ID)
    ws = spreadsheet.add_worksheet(title="OEE_IWON_TARGETS", rows=2000, cols=10)
    ws.update("A1:G1", [OEE_IWON_TARGET_COLUMNS])
    return ws


def iwon_targets_editable():
    """False when the hand-made tab exists in its own layout: then the sheet is the only source."""
    return not any(src["gid"] == IWON_TARGET_TAB_GID and not src["app_layout"] for src in load_iwon_target_sources())


@st.cache_data(ttl=300, show_spinner=False)
def load_oee_iwon_results():
    client = get_client()
    ws, _ = open_first_existing_worksheet(client, OEE_IWON_SHEET_ID, OEE_IWON_RESULT_SHEET_NAMES)
    raw = _worksheet_range_to_dataframe(ws, "A:J")
    if raw.empty:
        return pd.DataFrame(columns=OEE_IWON_RESULT_COLUMNS)
    raw = clean_columns(raw)
    for col in OEE_IWON_RESULT_COLUMNS:
        if col not in raw.columns:
            raw[col] = ""
    for col in ["Year", "CW", "Availability", "Performance", "Quality", "OEE"]:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    raw["Year"] = raw["Year"].fillna(0).astype(int)
    raw["CW"] = raw["CW"].fillna(0).astype(int)
    for col in ["Project", "Process", "Machine"]:
        raw[col] = raw[col].astype(str).str.strip()
    return raw[OEE_IWON_RESULT_COLUMNS].copy()


@_live_reads
def save_oee_iwon_target(year, cw, project, process, target_oee, updated_by=""):
    """Upsert one weekly target without touching any other target rows."""
    ws = iwon_targets_writable_ws()
    values = ws.get("A:G")
    if not values:
        ws.update("A1:G1", [OEE_IWON_TARGET_COLUMNS])
        values = [OEE_IWON_TARGET_COLUMNS]
    headers = [str(x).strip() for x in values[0]]
    if headers[:7] != OEE_IWON_TARGET_COLUMNS:
        ws.update("A1:G1", [OEE_IWON_TARGET_COLUMNS])
        values = ws.get("A:G")

    match_row = None
    for idx, row in enumerate(values[1:], start=2):
        padded = row + [""] * (7 - len(row))
        try:
            row_year = int(float(padded[0] or 0))
            row_cw = int(float(padded[1] or 0))
        except Exception:
            continue
        if (
            row_year == int(year)
            and row_cw == int(cw)
            and str(padded[2]).strip() == str(project).strip()
            and str(padded[3]).strip() == str(process).strip()
        ):
            match_row = idx
            break

    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output = [
        int(year), int(cw), str(project).strip(), str(process).strip(),
        round(float(target_oee), 2), str(updated_by).strip(), now_text,
    ]
    if match_row:
        ws.update(f"A{match_row}:G{match_row}", [output], value_input_option="USER_ENTERED")
    else:
        ws.append_row(_safe_row(output), value_input_option="USER_ENTERED", table_range="A1")
    load_oee_iwon_targets.clear()
    return True


@_live_reads
def save_oee_iwon_target_grid(year, project, process, grid_df, updated_by=""):
    """Save the complete CW01-CW53 target plan for one Year + Project + Process.

    Only columns A:G are managed. Any analysis/formulas to the right of column G are left untouched.
    Blank Target_OEE cells mean that the target for that CW is not defined.
    """
    ws = iwon_targets_writable_ws()
    try:
        values = ws.get("A:G", value_render_option="UNFORMATTED_VALUE")
    except TypeError:
        values = ws.get("A:G")
    if not values:
        values = [OEE_IWON_TARGET_COLUMNS]
        ws.update("A1:G1", [OEE_IWON_TARGET_COLUMNS])
    elif [str(x).strip() for x in values[0]][:7] != OEE_IWON_TARGET_COLUMNS:
        ws.update("A1:G1", [OEE_IWON_TARGET_COLUMNS])

    keep = []
    for row in values[1:]:
        padded = row + [""] * (7 - len(row))
        try:
            same_scope = (
                int(float(padded[0] or 0)) == int(year)
                and str(padded[2]).strip() == str(project).strip()
                and str(padded[3]).strip() == str(process).strip()
            )
        except Exception:
            same_scope = False
        if not same_scope:
            keep.append(padded[:7])

    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    replacement = []
    work = grid_df.copy() if grid_df is not None else pd.DataFrame()
    if not work.empty and "CW" in work.columns and "Target_OEE" in work.columns:
        work["CW"] = pd.to_numeric(work["CW"], errors="coerce")
        work["Target_OEE"] = pd.to_numeric(work["Target_OEE"], errors="coerce")
        work = work.dropna(subset=["CW", "Target_OEE"])
        work = work[(work["CW"] >= 1) & (work["CW"] <= 53)]
        work = work[(work["Target_OEE"] > 0) & (work["Target_OEE"] <= 99)]
        for _, row in work.sort_values("CW").iterrows():
            replacement.append([
                int(year), int(row["CW"]), str(project).strip(), str(process).strip(),
                round(float(row["Target_OEE"]), 2), str(updated_by).strip(), now_text,
            ])

    matrix = keep + replacement
    old_last_row = max(len(values), 1)
    new_last_row = len(matrix) + 1
    clear_last_row = max(old_last_row, new_last_row)
    if clear_last_row >= 2:
        ws.batch_clear([f"A2:G{clear_last_row}"])
    if matrix:
        ws.update(f"A2:G{new_last_row}", matrix, value_input_option="USER_ENTERED")
    load_oee_iwon_targets.clear()
    return len(replacement)


def _balanced_iwon_components(actual_a, actual_p, actual_q, target_oee):
    """Return a balanced A/P/Q target whose product equals the requested OEE.

    The baseline Machine OEE components are used only internally. When improvement is required,
    all components are raised by the same relative factor until one reaches 100%; any remaining
    gap is then redistributed over the other components. This keeps the target scenario balanced
    while still respecting the mathematical OEE relation A × P × Q.
    """
    vals = [max(float(actual_a), 0.01), max(float(actual_p), 0.01), max(float(actual_q), 0.01)]
    vals = [min(100.0, v) for v in vals]
    target = max(0.0, min(float(target_oee), 99.0))
    if target <= 0:
        return 0.0, 0.0, 0.0

    current = vals[0] * vals[1] * vals[2] / 10000.0
    if current >= target:
        # Keep the management scenario exactly on the requested target.
        factor = (target / current) ** (1.0 / 3.0) if current > 0 else 1.0
        vals = [v * factor for v in vals]
    else:
        active = {0, 1, 2}
        for _ in range(8):
            current = vals[0] * vals[1] * vals[2] / 10000.0
            if current >= target - 1e-10 or not active:
                break
            factor = (target / current) ** (1.0 / len(active))
            hit_cap = False
            for i in list(active):
                candidate = vals[i] * factor
                if candidate >= 100.0:
                    vals[i] = 100.0
                    active.remove(i)
                    hit_cap = True
                else:
                    vals[i] = candidate
            if not hit_cap:
                break

    vals = [min(100.0, max(0.0, v)) for v in vals]
    achieved = vals[0] * vals[1] * vals[2] / 10000.0
    if achieved + 0.005 < target:
        raise ValueError(f"Target OEE {target:.2f}% nije matematički dostižan.")
    return tuple(round(v, 4) for v in vals)


def _delete_worksheet_rows_batch(ws, row_numbers):
    """Delete physical worksheet rows in one API request, bottom to top."""
    rows = sorted({int(row) for row in row_numbers if int(row) >= 2})
    if not rows:
        return 0
    groups = []
    start = previous = rows[0]
    for row in rows[1:]:
        if row == previous + 1:
            previous = row
            continue
        groups.append((start, previous))
        start = previous = row
    groups.append((start, previous))
    requests = [
        {
            "deleteDimension": {
                "range": {
                    "sheetId": ws.id,
                    "dimension": "ROWS",
                    "startIndex": start - 1,
                    "endIndex": end,
                }
            }
        }
        for start, end in reversed(groups)
    ]
    ws.spreadsheet.batch_update({"requests": requests})
    invalidate = getattr(GOOGLE_SHEETS_ENGINE, "invalidate_worksheet", None)
    if invalidate:
        invalidate(ws)
    return len(rows)


@_live_reads
def _upsert_iwon_result_rows(ws, year, cw, project, process, rows):
    """Upsert IWON rows for one scope without clearing the worksheet.

    This is deliberately row-scoped: opening IWON must never erase formulas, charts or analysis
    that the user may build in the same spreadsheet.
    """
    values = ws.get("A:J")
    if not values:
        ws.update("A1:J1", [OEE_IWON_RESULT_COLUMNS])
        values = [OEE_IWON_RESULT_COLUMNS]
    elif [str(x).strip() for x in values[0]][:10] != OEE_IWON_RESULT_COLUMNS:
        ws.update("A1:J1", [OEE_IWON_RESULT_COLUMNS])
        values = ws.get("A:J")

    existing_by_machine = {}
    duplicate_rows = []
    for idx, row in enumerate(values[1:], start=2):
        padded = row + [""] * (10 - len(row))
        try:
            same_scope = (
                int(float(padded[0] or 0)) == int(year)
                and int(float(padded[1] or 0)) == int(cw)
                and str(padded[2]).strip() == str(project).strip()
                and str(padded[3]).strip() == str(process).strip()
            )
        except Exception:
            same_scope = False
        if not same_scope:
            continue
        machine = str(padded[4]).strip()
        if machine in existing_by_machine:
            duplicate_rows.append(idx)
        else:
            existing_by_machine[machine] = idx

    new_machines = {str(output[4]).strip() for output in rows}
    stale_rows = [idx for machine, idx in existing_by_machine.items() if machine not in new_machines]
    reusable_rows = sorted(set(stale_rows + duplicate_rows))
    next_row = max(len(values) + 1, 2)
    updates = []

    for output in rows:
        machine = str(output[4]).strip()
        row_idx = existing_by_machine.get(machine)
        if not row_idx:
            row_idx = reusable_rows.pop(0) if reusable_rows else next_row
            if row_idx == next_row:
                next_row += 1
        updates.append({"range": f"A{row_idx}:J{row_idx}", "values": [output]})

    # One values.batchUpdate replaces the old update/append loop.  This is the main protection
    # against the Google Sheets "Write requests per minute" error when a process has many machines.
    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")

    # Remove leftover stale/duplicate rows physically; clearing cells forever
    # leaves an expanding worksheet full of holes.
    _delete_worksheet_rows_batch(ws, reusable_rows)


def calculate_and_store_iwon_week(actual_week_df, year, cw, project, process):
    """Generate one saved weekly IWON scenario from real Machine OEE data.

    This function is intentionally called from Administration only. The Weekly IWON dashboard is
    read-only and always renders the already persisted OEE_IWON rows.
    """
    targets = load_oee_iwon_targets()
    project_key = str(project).strip().casefold()
    process_key = str(process).strip().casefold()
    match = targets[
        (targets["Year"] == int(year))
        & (targets["CW"] == int(cw))
        & (targets["Project"].astype(str).str.strip().str.casefold() == project_key)
        & (targets["Process"].astype(str).str.strip().str.casefold() == process_key)
    ]
    if match.empty:
        raise ValueError(
            f"Nije definisan IWON target za {year}-CW{int(cw):02d} / {project} / {process}."
        )
    target = float(match.iloc[-1]["Target_OEE"])
    if not pd.notna(target) or target <= 0 or target > 99:
        raise ValueError("IWON Target OEE mora biti između 0 i 99%.")

    scoped = actual_week_df[
        (actual_week_df["Project"].astype(str).str.strip().str.casefold() == project_key)
        & (actual_week_df["Process"].astype(str).str.strip().str.casefold() == process_key)
    ].copy()
    if scoped.empty:
        if actual_week_df.empty:
            raise ValueError(
                f"CW{int(cw):02d} nema nijedan stvarni OEE unos za {int(year)}. "
                "IWON može da se generiše samo za nedelju koja već ima Machine OEE podatke."
            )

        available = actual_week_df[["Project", "Process"]].drop_duplicates().copy()
        available_pairs = [
            f"{str(r.Project).strip()} / {str(r.Process).strip()}"
            for r in available.itertuples(index=False)
        ]
        sample = "; ".join(available_pairs[:8])
        if len(available_pairs) > 8:
            sample += "; …"
        raise ValueError(
            f"CW{int(cw):02d} ima OEE podatke, ali nema podatke za {project} / {process}. "
            + (f"Dostupno u toj nedelji: {sample}" if sample else "")
        )

    rows = []
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # GLOBAL row mirrors the existing Machine=All OEE behaviour: it is calculated from summed
    # raw data for the entire selected process, never as an arithmetic average of machines.
    global_actual = aggregate_oee(scoped.assign(_IWON_SCOPE="GLOBAL"), ["_IWON_SCOPE"])
    if not global_actual.empty:
        r = global_actual.iloc[0]
        a, p, q = _balanced_iwon_components(
            r.get("Machine_Availability_%", 0),
            r.get("Machine_Performance_CT_%", 0),
            r.get("Quality_%", 0),
            target,
        )
        rows.append([
            int(year), int(cw), str(project), str(process), "GLOBAL",
            a, p, q, round(target, 4), now_text,
        ])

    actual_by_machine = aggregate_oee(scoped, ["Project", "Process", "Machine"])
    for _, r in actual_by_machine.iterrows():
        a, p, q = _balanced_iwon_components(
            r.get("Machine_Availability_%", 0),
            r.get("Machine_Performance_CT_%", 0),
            r.get("Quality_%", 0),
            target,
        )
        rows.append([
            int(year), int(cw), str(project), str(process), str(r.get("Machine", "")).strip(),
            a, p, q, round(target, 4), now_text,
        ])

    client = get_client()
    ws, _ = open_first_existing_worksheet(client, OEE_IWON_SHEET_ID, OEE_IWON_RESULT_SHEET_NAMES)
    _upsert_iwon_result_rows(ws, year, cw, project, process, rows)
    load_oee_iwon_results.clear()
    return target, len(rows)


def show_iwon_week_view(year, cw, project, process, machine_filter="Sve"):
    """Render only the saved target scenario from OEE_IWON. No actual values are shown."""
    data = load_oee_iwon_results()
    project_key = str(project).strip().casefold()
    process_key = str(process).strip().casefold()
    data = data[
        (data["Year"] == int(year))
        & (data["CW"] == int(cw))
        & (data["Project"].astype(str).str.strip().str.casefold() == project_key)
        & (data["Process"].astype(str).str.strip().str.casefold() == process_key)
    ].copy()
    if data.empty:
        st.warning(
            "Nema sačuvanog OEE IWON scenarija za izabranu nedelju/proces. "
            "U tabu IWON → Plan i prognoza izaberi CW i klikni Generiši plan."
        )
        return

    if machine_filter == "Sve":
        selected = data[data["Machine"].astype(str).str.upper() == "GLOBAL"]
        if selected.empty:
            # Backward-compatible fallback for a sheet generated by the first v9.4 build.
            selected = data.iloc[[0]]
    else:
        selected = data[
            data["Machine"].astype(str).str.strip().str.casefold()
            == str(machine_filter).strip().casefold()
        ]

    if selected.empty:
        st.warning("Nema sačuvanog IWON targeta za izabranu mašinu.")
        return

    row = selected.iloc[0]
    cards = '<div class="oee-card-row">'
    cards += render_oee_progress_card("OEE IWON", row["OEE"], is_main=True)
    cards += render_oee_progress_card("Availability", row["Availability"])
    cards += render_oee_progress_card("Performance", row["Performance"])
    cards += render_oee_progress_card("Q-rate", row["Quality"])
    cards += '</div>'
    st.markdown(cards, unsafe_allow_html=True)

    st.markdown("### IWON target overview")
    plot_oee_components_bar(
        [
            {"Metric": "OEE", "Value": row["OEE"]},
            {"Metric": "Availability", "Value": row["Availability"]},
            {"Metric": "Q-rate", "Value": row["Quality"]},
            {"Metric": "Performance", "Value": row["Performance"]},
        ],
        f"OEE IWON | {int(year)}-CW{int(cw):02d} | {project} | {process}",
        f"iwon_components_{year}_{cw}_{project}_{process}_{machine_filter}",
        show_target=False,
    )

    machine_rows = data[data["Machine"].astype(str).str.upper() != "GLOBAL"].copy()
    if machine_filter == "Sve" and len(machine_rows) > 1:
        st.markdown("### Target per machine")
        display = machine_rows[["Machine", "Availability", "Performance", "Quality", "OEE"]].copy()
    else:
        display = selected[["Machine", "Availability", "Performance", "Quality", "OEE"]].copy()

    for c in ["Availability", "Performance", "Quality", "OEE"]:
        display[c] = pd.to_numeric(display[c], errors="coerce").round(2)
    st.dataframe(display, use_container_width=True, hide_index=True)


def aggregate_iwon_period(actual_period_df, project, process, group_cols=None, include_global=True, iwon_data=None):
    """Roll saved weekly IWON scenarios into any calendar period.

    Weekly A/P/Q percentages cannot be added or averaged directly.  Each component is weighted
    by the same real denominator used by Machine OEE, limited to the dates in the selected period:
      * Availability -> Machine available time
      * Performance  -> Machine run time
      * Quality      -> Total pieces
    The period IWON OEE is then recalculated as Availability × Performance × Quality.
    This also splits an ISO week correctly when it crosses a month or year boundary.
    """
    group_cols = list(dict.fromkeys(group_cols or []))
    empty_columns = group_cols + [
        "Machine", "Availability", "Performance", "Quality", "IWON_OEE_%",
        "Covered_CWs", "Expected_CWs", "Coverage_%",
    ]
    if actual_period_df is None or actual_period_df.empty:
        return pd.DataFrame(columns=empty_columns), pd.DataFrame()

    actual = actual_period_df.copy()
    required = {"Project", "Process", "Machine"}
    if not required.issubset(actual.columns):
        return pd.DataFrame(columns=empty_columns), pd.DataFrame()

    project_key = str(project).strip().casefold()
    process_key = str(process).strip().casefold()
    actual = actual[
        actual["Project"].astype(str).str.strip().str.casefold().eq(project_key)
        & actual["Process"].astype(str).str.strip().str.casefold().eq(process_key)
    ].copy()
    if actual.empty:
        return pd.DataFrame(columns=empty_columns), pd.DataFrame()

    if "Godina" not in actual.columns or "Week" not in actual.columns:
        actual["Datum"] = parse_oee_date_series(actual.get("Datum", pd.Series(index=actual.index, dtype=object)))
        iso = actual["Datum"].dt.isocalendar()
        actual["Godina"] = iso.year.astype("Int64")
        actual["Week"] = iso.week.astype("Int64")

    # Derive the denominator columns when this helper receives an older prepared OEE frame.
    for col in ["Open time", "Down time", "Organisational loss", "Total Pcs"]:
        if col not in actual.columns:
            actual[col] = 0.0
        actual[col] = pd.to_numeric(actual[col], errors="coerce").fillna(0.0)
    if "Machine_Available_Time" not in actual.columns:
        actual["Machine_Available_Time"] = (
            actual["Open time"] - actual["Organisational loss"]
        ).clip(lower=0)
    if "Machine_Run_Time" not in actual.columns:
        actual["Machine_Run_Time"] = (
            actual["Open time"] - actual["Down time"] - actual["Organisational loss"]
        ).clip(lower=0)

    for col in ["Machine_Available_Time", "Machine_Run_Time", "Total Pcs"]:
        actual[col] = pd.to_numeric(actual[col], errors="coerce").fillna(0.0).clip(lower=0)

    # Build machine rows and, only when requested, one GLOBAL copy matching Machine = Sve.
    actual["IWON_Machine"] = actual["Machine"].astype(str).str.strip()
    actual["IWON_Machine_Key"] = actual["IWON_Machine"].str.casefold()
    frames = [actual]
    if include_global:
        global_actual = actual.copy()
        global_actual["IWON_Machine"] = "GLOBAL"
        global_actual["IWON_Machine_Key"] = "global"
        frames.append(global_actual)
    weighted_source = pd.concat(frames, ignore_index=True)

    weekly_group_cols = list(dict.fromkeys(
        group_cols + ["Godina", "Week", "IWON_Machine_Key", "IWON_Machine"]
    ))
    weekly_weights = weighted_source.groupby(weekly_group_cols, dropna=False, sort=True).agg(
        Availability_Weight=("Machine_Available_Time", "sum"),
        Performance_Weight=("Machine_Run_Time", "sum"),
        Quality_Weight=("Total Pcs", "sum"),
    ).reset_index()

    saved = load_oee_iwon_results() if iwon_data is None else iwon_data.copy()
    if saved.empty:
        missing = weekly_weights.copy()
        return pd.DataFrame(columns=empty_columns), missing

    saved = saved[
        saved["Project"].astype(str).str.strip().str.casefold().eq(project_key)
        & saved["Process"].astype(str).str.strip().str.casefold().eq(process_key)
    ].copy()
    saved["Godina"] = pd.to_numeric(saved["Year"], errors="coerce").astype("Int64")
    saved["Week"] = pd.to_numeric(saved["CW"], errors="coerce").astype("Int64")
    saved["IWON_Machine_Key"] = saved["Machine"].astype(str).str.strip().str.casefold()
    for col in ["Availability", "Performance", "Quality", "OEE"]:
        saved[col] = pd.to_numeric(saved[col], errors="coerce")
    saved = saved.dropna(subset=["Godina", "Week", "Availability", "Performance", "Quality"])
    saved = saved.drop_duplicates(["Godina", "Week", "IWON_Machine_Key"], keep="last")

    merged = weekly_weights.merge(
        saved[["Godina", "Week", "IWON_Machine_Key", "Availability", "Performance", "Quality", "OEE"]],
        on=["Godina", "Week", "IWON_Machine_Key"],
        how="left",
        validate="many_to_one",
    )
    missing_mask = merged[["Availability", "Performance", "Quality"]].isna().any(axis=1)
    missing = merged.loc[missing_mask, group_cols + ["Godina", "Week", "IWON_Machine"]].copy()
    covered = merged.loc[~missing_mask].copy()
    if covered.empty:
        return pd.DataFrame(columns=empty_columns), missing

    final_group_cols = list(dict.fromkeys(group_cols + ["IWON_Machine_Key", "IWON_Machine"]))
    weighted_rules = {
        "Availability": "Availability_Weight",
        "Performance": "Performance_Weight",
        "Quality": "Quality_Weight",
    }
    for value_col, weight_col in weighted_rules.items():
        covered[f"_{value_col}_Numerator"] = covered[value_col] * covered[weight_col]

    sum_columns = [
        "Availability_Weight", "Performance_Weight", "Quality_Weight",
        "_Availability_Numerator", "_Performance_Numerator", "_Quality_Numerator",
    ]
    result = covered.groupby(final_group_cols, dropna=False, sort=True)[sum_columns].sum().reset_index()
    means = covered.groupby(final_group_cols, dropna=False, sort=True)[
        ["Availability", "Performance", "Quality"]
    ].mean().reset_index()
    result = result.merge(means, on=final_group_cols, how="left", suffixes=("", "_Mean"))

    for value_col, weight_col in weighted_rules.items():
        denominator = result[weight_col]
        calculated = result[f"_{value_col}_Numerator"].div(denominator.where(denominator.ne(0)))
        result[value_col] = calculated.fillna(result[value_col]).clip(lower=0, upper=100)

    expected_counts = weekly_weights.groupby(final_group_cols, dropna=False).size().rename("Expected_CWs")
    covered_counts = covered.groupby(final_group_cols, dropna=False).size().rename("Covered_CWs")
    result = result.merge(expected_counts.reset_index(), on=final_group_cols, how="left")
    result = result.merge(covered_counts.reset_index(), on=final_group_cols, how="left")
    result["Coverage_%"] = (
        result["Covered_CWs"].div(result["Expected_CWs"].where(result["Expected_CWs"].ne(0))).mul(100)
    ).fillna(0).clip(lower=0, upper=100)
    result["IWON_OEE_%"] = (
        result["Availability"] * result["Performance"] * result["Quality"] / 10000.0
    ).clip(lower=0, upper=100)
    result = result.rename(columns={"IWON_Machine": "Machine"})

    keep_cols = [c for c in empty_columns if c in result.columns]
    return result[keep_cols].copy(), missing

def format_oee_percent_columns(df):
    df = df.copy()
    percent_cols = [c for c in df.columns if c.endswith("_%")]
    for c in percent_cols:
        df[c] = df[c].round(2)
    numeric_cols = df.select_dtypes(include="number").columns
    for c in numeric_cols:
        if c not in percent_cols:
            df[c] = df[c].round(2)
    return df


def clear_oee_operational_input_fields():
    """Clear only operational OEE input fields after successful save/update."""
    for key in ("oee_ok", "oee_nok", "oee_down", "oee_org"):
        st.session_state[key] = None
    _clear_oee_cause_rows()


OEE_CAUSE_ROW_KEYS = {"down": "oee_down_rows", "org": "oee_org_rows"}


def _oee_cause_rows(kind):
    rows = st.session_state.get(OEE_CAUSE_ROW_KEYS[kind])
    if not isinstance(rows, list) or not rows:
        rows = [uuid.uuid4().hex[:8]]
        st.session_state[OEE_CAUSE_ROW_KEYS[kind]] = rows
    return rows


def _oee_add_cause_row(kind):
    st.session_state[OEE_CAUSE_ROW_KEYS[kind]] = _oee_cause_rows(kind) + [uuid.uuid4().hex[:8]]


def _oee_remove_cause_row(kind, row_id):
    rows = [r for r in _oee_cause_rows(kind) if r != row_id]
    st.session_state[OEE_CAUSE_ROW_KEYS[kind]] = rows or [uuid.uuid4().hex[:8]]
    st.session_state.pop(f"oee_{kind}_cause_{row_id}", None)
    st.session_state.pop(f"oee_{kind}_min_{row_id}", None)


def _clear_oee_cause_rows():
    for kind, list_key in OEE_CAUSE_ROW_KEYS.items():
        for row_id in st.session_state.get(list_key) or []:
            st.session_state.pop(f"oee_{kind}_cause_{row_id}", None)
            st.session_state.pop(f"oee_{kind}_min_{row_id}", None)
        st.session_state.pop(list_key, None)


def render_oee_cause_rows(down_time, org_loss, logged_events):
    """Under 'Zastoj' / 'Org. gubici': one row per stop (reason typed freely + minutes).

    One stop of 30 min or two of 10 + 20 min are different stories, so every
    stop gets its own row ('➕' adds one); the rows must add up to the minutes
    typed above.
    """
    logged = logged_events if logged_events is not None else oi.normalize_events(None)
    rows_out = []
    for kind, total, loss_type, title, example in (
        ("down", float(down_time or 0), oi.LOSS_DOWNTIME, "Zastoji", "npr. zamena senzora na OP30"),
        ("org", float(org_loss or 0), oi.LOSS_ORGANISATIONAL, "Organizacioni gubici", "npr. čekanje materijala"),
    ):
        already = float(logged.loc[logged["Loss_Type"] == loss_type, "Minutes"].sum()) if not logged.empty else 0.0
        if total <= 0:
            continue
        with st.container(border=True):
            st.markdown(f"**{title} — {_sr_num(total)} min:** upiši svaki {'zastoj' if kind == 'down' else 'gubitak'} posebno")
            if already > 0:
                st.caption(f"Već prijavljeno u formi tehničara: {_sr_num(already)} min (uračunato).")
            row_ids = _oee_cause_rows(kind)
            entered = 0.0
            for index, row_id in enumerate(row_ids):
                min_key = f"oee_{kind}_min_{row_id}"
                if min_key not in st.session_state:
                    remaining = int(round(max(total - already - entered, 0.0)))
                    st.session_state[min_key] = remaining if index == 0 and remaining > 0 else None
                c_cause, c_min, c_add, c_del = st.columns([6, 3, 1, 1])
                with c_cause:
                    reason = st.text_input(
                        "Razlog", key=f"oee_{kind}_cause_{row_id}", placeholder=example,
                        label_visibility="visible" if index == 0 else "collapsed",
                    )
                with c_min:
                    minutes = st.number_input(
                        "Minuta", min_value=0, step=1, value=None, key=min_key, placeholder="0",
                        label_visibility="visible" if index == 0 else "collapsed",
                    )
                with c_add:
                    if index == 0:
                        st.markdown('<div style="height:1.9rem"></div>', unsafe_allow_html=True)
                    if index == len(row_ids) - 1:
                        st.button("➕", key=f"oee_{kind}_add_{row_id}", on_click=_oee_add_cause_row, args=(kind,),
                                  help="Dodaj još jedan zastoj", use_container_width=True)
                with c_del:
                    if index == 0:
                        st.markdown('<div style="height:1.9rem"></div>', unsafe_allow_html=True)
                    if len(row_ids) > 1:
                        st.button("✖", key=f"oee_{kind}_del_{row_id}", on_click=_oee_remove_cause_row,
                                  args=(kind, row_id), help="Obriši ovaj red", use_container_width=True)
                entered += float(minutes or 0)
                rows_out.append({"Uzrok": reason or "", "Minuta": float(minutes or 0), "Vrsta": loss_type})
            covered = already + entered
            if abs(covered - total) < 0.01:
                st.markdown(f'<span style="color:#4ADE80;font-weight:700">✓ Raspoređeno {_sr_num(covered)} od {_sr_num(total)} min</span>',
                            unsafe_allow_html=True)
            elif covered < total:
                st.markdown(f'<span style="color:#FBBF24;font-weight:700">Nedostaje još {_sr_num(total - covered)} min '
                            f'(raspoređeno {_sr_num(covered)} od {_sr_num(total)})</span>', unsafe_allow_html=True)
            else:
                st.markdown(f'<span style="color:#F87171;font-weight:700">Previše: {_sr_num(covered - total)} min više nego upisano '
                            f'({_sr_num(covered)} od {_sr_num(total)})</span>', unsafe_allow_html=True)
    return pd.DataFrame(rows_out, columns=["Uzrok", "Minuta", "Vrsta"])


def _save_pending_oee_allocation():
    """Write the causes of the saved OEE row; the OEE row itself is already safe."""
    pending = st.session_state.pop("oee_pending_alloc", None)
    if not pending:
        return
    try:
        replace_oee_allocation(pending["date"], pending["project"], pending["process"], pending["machine"],
                               pending["shift"], pending["allocation"])
    except Exception as exc:
        st.session_state["_oee_save_notification_warning"] = (
            f"OEE zapis JE sačuvan, ali uzroci zastoja nisu upisani (Google Sheets: {exc}). Otvori unos ponovo i sačuvaj."
        )


def add_oee_chart_label_column(df):
    df = df.copy()
    if "Project" in df.columns and "Process" in df.columns:
        df["Project_Process"] = df["Project"].astype(str) + " | " + df["Process"].astype(str)
    return df


def get_oee_display_columns(df):
    cols = [
        "Datum", "Godina", "Week", "Mesec", "Project", "Process", "Machine", "Shift", "Included_Shifts", "Submitted_By",
        "Open_Time", "Down_Time", "Organisational_Loss",
        "OK_pcs", "NOK_pcs", "Total_Pcs", "Target_pcs",
        "Machine_OEE_CT_%", "Plant_OEE_CT_%",
        "Machine_OEE_Target_%", "Plant_OEE_Target_%",
        "Machine_Availability_%", "Plant_Availability_%",
        "Machine_Performance_CT_%", "Plant_Performance_CT_%",
        "Quality_%", "Performance_Target_%", "Records",
    ]
    return [c for c in cols if c in df.columns]


def show_project_process_kpi_blocks(data, title_prefix, key_prefix, date_label=None):
    """Dashboard machine overview: one machine block with 4 OEE gauges.
    Values shown per machine:
    - Machine OEE CT
    - Plant OEE CT
    - Machine OEE Target
    - Plant OEE Target
    """
    if data.empty:
        st.warning("Nema OEE podataka za izabrani period.")
        return

    period_text = f" | {date_label}" if date_label else ""

    for project in sorted(data["Project"].dropna().unique().tolist()):
        project_df = data[data["Project"] == project].copy()
        for process in sorted(project_df["Process"].dropna().unique().tolist()):
            process_df = project_df[project_df["Process"] == process].copy()
            for machine in sorted(process_df["Machine"].dropna().unique().tolist()):
                block_df = process_df[process_df["Machine"] == machine].copy()
                if block_df.empty:
                    continue

                row = block_df.iloc[0]
                title = f"{project} | {process} | {machine}{period_text}"
                st.markdown(f"### {title}")
                show_gauge_row([
                    ("Machine OEE CT", row.get("Machine_OEE_CT_%", 0)),
                    ("Plant OEE CT", row.get("Plant_OEE_CT_%", 0)),
                    ("Machine OEE Target", row.get("Machine_OEE_Target_%", 0)),
                    ("Plant OEE Target", row.get("Plant_OEE_Target_%", 0)),
                ], f"{key_prefix}_{project}_{process}_{machine}_4oee")

                show_cols = get_oee_display_columns(block_df)
                display_df = block_df[show_cols].copy()
                if "Datum" in display_df.columns:
                    display_df["Datum"] = pd.to_datetime(display_df["Datum"], errors="coerce").dt.strftime("%d.%m.%Y")
                st.dataframe(format_oee_percent_columns(display_df), use_container_width=True)

def show_machine_oee_breakdown_blocks(data, key_prefix, date_label=None):
    """Show four gauge rows per machine:
    1) Machine OEE CT + machine availability + machine CT performance + quality
    2) Plant OEE CT + plant availability + plant CT performance + quality
    3) Machine OEE Target + machine availability + target performance + quality
    4) Plant OEE Target + plant availability + target performance + quality
    """
    if data.empty:
        st.warning("Nema OEE podataka za izabrani period.")
        return

    period_text = f" | {date_label}" if date_label else ""

    breakdown_specs = [
        ("Machine OEE CT", [
            ("OEE CT", "Machine_OEE_CT_%"),
            ("Availability", "Machine_Availability_%"),
            ("Performance CT", "Machine_Performance_CT_%"),
            ("Q-rate", "Quality_%"),
        ]),
        ("Plant OEE CT", [
            ("OEE CT", "Plant_OEE_CT_%"),
            ("Availability", "Plant_Availability_%"),
            ("Performance CT", "Plant_Performance_CT_%"),
            ("Q-rate", "Quality_%"),
        ]),
        ("Machine OEE Target", [
            ("OEE Target", "Machine_OEE_Target_%"),
            ("Availability", "Machine_Availability_%"),
            ("Performance Target", "Performance_Target_%"),
            ("Q-rate", "Quality_%"),
        ]),
        ("Plant OEE Target", [
            ("OEE Target", "Plant_OEE_Target_%"),
            ("Availability", "Plant_Availability_%"),
            ("Performance Target", "Performance_Target_%"),
            ("Q-rate", "Quality_%"),
        ]),
    ]

    for project in sorted(data["Project"].dropna().unique().tolist()):
        project_df = data[data["Project"] == project].copy()
        for process in sorted(project_df["Process"].dropna().unique().tolist()):
            process_df = project_df[project_df["Process"] == process].copy()
            for machine in sorted(process_df["Machine"].dropna().unique().tolist()):
                block_df = process_df[process_df["Machine"] == machine].copy()
                if block_df.empty:
                    continue
                row = block_df.iloc[0]
                machine_title = f"{project} | {process} | {machine}{period_text}"
                st.markdown(f"## {machine_title}")

                for chart_title, items in breakdown_specs:
                    st.markdown(f"#### {chart_title}")
                    gauge_items = [(label, float(row.get(col, 0) or 0)) for label, col in items]
                    show_gauge_row(gauge_items, f"{key_prefix}_{machine_title}_{chart_title}")

                show_cols = get_oee_display_columns(block_df)
                display_df = block_df[show_cols].copy()
                if "Datum" in display_df.columns:
                    display_df["Datum"] = pd.to_datetime(display_df["Datum"], errors="coerce").dt.strftime("%d.%m.%Y")
                st.dataframe(format_oee_percent_columns(display_df), use_container_width=True)

def show_project_summary_metrics(data, title, key_prefix):
    if data.empty:
        st.warning("Nema OEE podataka za izabrani period.")
        return
    st.markdown(f"### {title}")
    st.plotly_chart(
        create_grouped_bar(
            data,
            "Project",
            ["Machine_OEE_CT_%", "Machine_Availability_%", "Machine_Performance_CT_%", "Quality_%"],
            title,
            "%",
            2,
        ),
        use_container_width=True,
        key=f"{key_prefix}_project_metrics_chart",
    )
    show_cols = get_oee_display_columns(data)
    st.dataframe(format_oee_percent_columns(data[show_cols]), use_container_width=True)



# =====================================================
# WORK TICKETS / KANBAN MODULE
# =====================================================

TASK_REQUIRED_COLUMNS = [
    "Task_ID", "Assigned_Technician_ID", "Assigned_To", "Assigned_Email", "Process", "Task_Title", "Task_Priority", "Status",
    "Start_Date", "Start_Time", "End_Date", "End_Time", "Calculated_Duration", "Effective_Duration",
    "Created_By", "Created_By_Email", "Created_At", "Closed_By", "Closed_At",
]

TASK_ACTIVITY_REQUIRED_COLUMNS = [
    "Activity_ID", "Task_ID", "Assigned_Technician_ID", "Assigned_To", "Task_Title", "Start_Date", "Start_Time", "End_Date", "End_Time",
    "Calculated_Duration", "Effective_Duration",
]


def _norm_sheet_col(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _get_kpi_worksheet(sheet_name):
    client = get_client()
    return get_worksheet(KPI_SHEET_ID, sheet_name)


def _clean_header_cell(value):
    return str(value or "").replace("\ufeff", "").replace("\u200b", "").strip()


def _ensure_sheet_headers(ws, required_columns, header_row=None):
    """Make sure every required column exists; read only the header row.

    ``header_row`` can be passed when the caller already has the sheet values,
    so no extra Google request is made.
    """
    if header_row is None:
        header_row = ws.row_values(1)
    headers = [_clean_header_cell(h) for h in header_row]
    while headers and not headers[-1]:
        headers.pop()
    if not headers:
        ws.update("A1", [list(required_columns)])
        return list(required_columns)
    existing = {_norm_sheet_col(h) for h in headers if h}
    changed = False
    for col in required_columns:
        if _norm_sheet_col(col) not in existing:
            headers.append(col)
            existing.add(_norm_sheet_col(col))
            changed = True
    if changed:
        ws.update(f"A1:{_column_number_to_letter(len(headers))}1", [headers])
    return headers


def _canonical_header_map(headers, required_columns):
    """Map each sheet column index to the canonical column name used in code.

    "Assigned To", "assigned_to" and "Assigned_To" are the same column. Earlier
    such a spelling difference meant the value was silently written/read as
    empty, which made saved tasks look missing.
    """
    canonical = {_norm_sheet_col(c): c for c in required_columns}
    mapping = {}
    used = set()
    for index, header in enumerate(headers):
        clean = _clean_header_cell(header)
        if not clean:
            continue
        name = canonical.get(_norm_sheet_col(clean), clean)
        if name in used:
            continue  # first occurrence wins; never let a duplicate blank column overwrite data
        used.add(name)
        mapping[index] = name
    return mapping


def _records_frame_from_values(values, required_columns):
    """Build a DataFrame with canonical column names and the sheet row number."""
    if not values:
        return pd.DataFrame(columns=list(required_columns) + ["_row"])
    mapping = _canonical_header_map(values[0], required_columns)
    rows = []
    for row_number, row in enumerate(values[1:], start=2):
        if not any(str(cell).strip() for cell in row):
            continue
        item = {name: (row[index] if index < len(row) else "") for index, name in mapping.items()}
        item["_row"] = row_number
        rows.append(item)
    columns = list(dict.fromkeys(list(mapping.values()) + list(required_columns) + ["_row"]))
    df = pd.DataFrame(rows, columns=columns)
    for col in required_columns:
        df[col] = df[col].fillna("").astype(str)
    return df


def _load_ticket_sheet(sheet_name, required_columns):
    ws = _get_kpi_worksheet(sheet_name)
    values = ws.get_all_values()
    headers = _ensure_sheet_headers(ws, required_columns, header_row=values[0] if values else [])
    if values:
        values = [headers] + values[1:]
    return _records_frame_from_values(values, required_columns)


@st.cache_data(ttl=180)
def load_tasks_data():
    try:
        df = _load_ticket_sheet(TASKS_SHEET_NAME, TASK_REQUIRED_COLUMNS)
        df["Status"] = df["Status"].astype(str).str.strip().replace({"": "Open"})
        return df, []
    except Exception as e:
        return pd.DataFrame(), [f"TASKS sheet error: {type(e).__name__}: {e}"]


@st.cache_data(ttl=180)
def load_task_activity_data():
    try:
        return _load_ticket_sheet(TASK_ACTIVITY_SHEET_NAME, TASK_ACTIVITY_REQUIRED_COLUMNS), []
    except Exception as e:
        return pd.DataFrame(), [f"TASK_ACTIVITY sheet error: {type(e).__name__}: {e}"]


def _downtime_clean(value):
    """Return a safe trimmed text value for the external downtime source."""
    if value is None:
        return ""
    if pd.api.types.is_scalar(value) and pd.isna(value):
        return ""
    text = str(value).replace("\ufeff", "").replace("​", "").strip()
    return "" if text.casefold() in {"nan", "none", "nat"} else text


def _downtime_header_key(value):
    """Normalize Serbian/English headers without relying on their capitalization."""
    text = _downtime_clean(value).replace("Đ", "Dj").replace("đ", "dj")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


def _downtime_name_key(value):
    """Canonical person key: case/diacritics/punctuation/order independent.

    Examples such as 'Nikolić Bojan', 'Bojan Nikolic' and 'BOJAN NIKOLIĆ'
    intentionally resolve to the same key. Fuzzy matching is not used because
    it could silently assign a stoppage to the wrong person.
    """
    text = _downtime_clean(value).replace("Đ", "Dj").replace("đ", "dj")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    tokens = re.findall(r"[a-z0-9]+", text)
    return "|".join(sorted(tokens))


def _downtime_find_column(columns, aliases):
    normalized = {}
    for column in columns:
        normalized.setdefault(_downtime_header_key(column), column)
    for alias in aliases:
        match = normalized.get(_downtime_header_key(alias))
        if match is not None:
            return match
    return None


def _downtime_date_text(value):
    """Parse a Google Sheets date and return the ALL_ACTIVITIES date format."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Google Sheets/Excel serial date (1899-12-30 epoch).
        number = float(value)
        if 20_000 <= number <= 100_000:
            parsed = pd.Timestamp("1899-12-30") + pd.to_timedelta(number, unit="D")
            return parsed.strftime("%d.%m.%Y")
    parsed = parse_mixed_datetime(_downtime_clean(value))
    return "" if pd.isna(parsed) else parsed.strftime("%d.%m.%Y")


def _downtime_time_seconds(value):
    """Parse a time-of-day value from text, datetime or a Sheets day fraction."""
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.hour * 3600 + value.minute * 60 + value.second
    if isinstance(value, time):
        return value.hour * 3600 + value.minute * 60 + value.second
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        fraction = number % 1
        return int(round(fraction * 86400)) % 86400

    text = _downtime_clean(value)
    if not text:
        return None
    numeric = text.replace(",", ".")
    if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", numeric):
        try:
            number = float(numeric)
            return int(round((number % 1) * 86400)) % 86400
        except (TypeError, ValueError, OverflowError):
            return None
    match = re.search(r"(?<!\d)(\d{1,2})[:.](\d{1,2})(?:[:.](\d{1,2}))?", text)
    if match:
        hour, minute, second = int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)
        if 0 <= hour < 24 and 0 <= minute < 60 and 0 <= second < 60:
            return hour * 3600 + minute * 60 + second
    parsed = parse_mixed_datetime(text)
    if pd.notna(parsed):
        return parsed.hour * 3600 + parsed.minute * 60 + parsed.second
    return None


def _downtime_time_text(seconds):
    if seconds is None:
        return ""
    seconds = int(round(seconds)) % 86400
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def _downtime_duration_minutes(value):
    """Parse VREME ZASTOJA; Google Forms commonly returns H:MM:SS."""
    if isinstance(value, pd.Timedelta):
        return max(value.total_seconds() / 60, 0.0)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if number <= 0:
            return 0.0
        # A decimal below one is normally a Google Sheets fraction of a day.
        return number * 1440 if number < 1 else number

    text = _downtime_clean(value)
    if not text:
        return 0.0
    match = re.fullmatch(r"\s*(\d+)\s*:\s*(\d{1,2})(?:\s*:\s*(\d{1,2}(?:[.,]\d+)?))?\s*", text)
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = float((match.group(3) or "0").replace(",", "."))
        if minutes < 60 and seconds < 60:
            return max(hours * 60 + minutes + seconds / 60, 0.0)
    unit_match = re.fullmatch(
        r"\s*(?:(\d+(?:[.,]\d+)?)\s*h)?\s*(?:(\d+(?:[.,]\d+)?)\s*(?:m|min))?\s*",
        text.casefold(),
    )
    if unit_match and any(unit_match.groups()):
        hours = float((unit_match.group(1) or "0").replace(",", "."))
        minutes = float((unit_match.group(2) or "0").replace(",", "."))
        return max(hours * 60 + minutes, 0.0)
    try:
        number = float(text.replace(",", "."))
        return max(number * 1440 if 0 < number < 1 else number, 0.0)
    except Exception:
        return 0.0


def _downtime_technician_lookup(technicians):
    """Return only active, non-supervisor technicians registered in the app."""
    candidates = {}
    missing_ids = []
    if technicians is None or technicians.empty:
        return {}, [], []

    for _, row in technicians.iterrows():
        if not _yes_value(row.get("Active", "YES")) or _yes_value(row.get("Supervisor", "NO")):
            continue
        tech_id = _downtime_clean(row.get("Technician_ID", "")).upper()
        name = _downtime_clean(row.get("Technician_Name", ""))
        if not name:
            continue
        if not tech_id:
            missing_ids.append(name)
            continue
        key = _downtime_name_key(name)
        if key:
            candidates.setdefault(key, {})[tech_id] = name

    lookup, ambiguous = {}, []
    for key, people in candidates.items():
        if len(people) == 1:
            tech_id, name = next(iter(people.items()))
            lookup[key] = {"Technician_ID": tech_id, "Technician_Name": name}
        else:
            ambiguous.extend(sorted(set(people.values())))
    return lookup, sorted(set(ambiguous)), sorted(set(missing_ids))


def normalize_process_downtime_rows(source_df, technicians, imported_at):
    """Convert the external downtime form into ALL_ACTIVITIES rows.

    The source remains read-only. Rows belonging to people who are not active
    technicians in the app are intentionally ignored.
    """
    info = {
        "source_rows": 0,
        "valid_rows": 0,
        "ignored_rows": 0,
        "invalid_rows": 0,
        "ignored_names": [],
        "ambiguous_master_names": [],
        "missing_technician_ids": [],
        "errors": [],
    }
    if source_df is None or source_df.empty:
        return [], info

    df = source_df.copy()
    info["source_rows"] = len(df)
    columns = df.columns
    timestamp_col = _downtime_find_column(columns, ["Timestamp", "Vremenska oznaka", "Vreme unosa"])
    technician_col = _downtime_find_column(columns, ["IME", "Tehničar", "Tehnicar", "Technician"])
    project_col = _downtime_find_column(columns, ["Projekat", "Project"])
    date_col = _downtime_find_column(columns, ["DATUM PROBLEMA", "Datum problema", "Datum", "Date"])
    resolved_date_col = _downtime_find_column(columns, ["DATUM REŠENJA PROBLEMA", "Datum resenja problema"])
    start_col = _downtime_find_column(columns, ["POČETAK ZASTOJA", "Pocetak zastoja", "Start", "Start time"])
    end_col = _downtime_find_column(columns, ["ZAVRŠETAK ZASTOJA", "Zavrsetak zastoja", "End", "End time"])
    duration_col = _downtime_find_column(columns, ["VREME ZASTOJA", "Vrijeme zastoja", "Trajanje zastoja", "Duration"])
    cause_col = _downtime_find_column(columns, ["UZROK ZASTOJA", "Uzrok", "Cause"])
    downtime_type_col = _downtime_find_column(columns, ["TIP ZASTOJA", "Vrsta zastoja", "Downtime type"])
    error_type_col = _downtime_find_column(columns, ["TIP GREŠKE", "Tip greske", "Error type"])
    sector_col = _downtime_find_column(columns, ["SEKTOR", "Sector"])
    place_col = _downtime_find_column(columns, ["MESTO ZASTOJA", "Mjesto zastoja", "Lokacija", "Machine", "Mašina"])

    missing = []
    if technician_col is None:
        missing.append("IME")
    if date_col is None and timestamp_col is None:
        missing.append("DATUM PROBLEMA")
    if start_col is None:
        missing.append("POČETAK ZASTOJA")
    if duration_col is None and end_col is None:
        missing.append("VREME ZASTOJA/ZAVRŠETAK ZASTOJA")
    if missing:
        info["errors"].append("Downtime source missing columns: " + ", ".join(missing))
        return [], info

    technician_lookup, ambiguous, missing_ids = _downtime_technician_lookup(technicians)
    info["ambiguous_master_names"] = ambiguous
    info["missing_technician_ids"] = missing_ids
    if not technician_lookup:
        info["errors"].append("No active app technicians with Technician_ID are available for downtime matching.")
        return [], info

    rows, ignored_names = [], set()
    for _, source_row in df.iterrows():
        source_name = _downtime_clean(source_row.get(technician_col, ""))
        if not source_name:
            info["invalid_rows"] += 1
            continue
        technician = technician_lookup.get(_downtime_name_key(source_name))
        if technician is None:
            info["ignored_rows"] += 1
            ignored_names.add(source_name)
            continue

        timestamp_value = _downtime_clean(source_row.get(timestamp_col, "")) if timestamp_col else ""
        work_date = _downtime_date_text(source_row.get(date_col, "")) if date_col else ""
        if not work_date and timestamp_col:
            work_date = _downtime_date_text(source_row.get(timestamp_col, ""))
        if not work_date and resolved_date_col:
            work_date = _downtime_date_text(source_row.get(resolved_date_col, ""))

        start_seconds = _downtime_time_seconds(source_row.get(start_col, "")) if start_col else None
        end_seconds = _downtime_time_seconds(source_row.get(end_col, "")) if end_col else None
        duration_minutes = _downtime_duration_minutes(source_row.get(duration_col, "")) if duration_col else 0.0
        if duration_minutes <= 0 and start_seconds is not None and end_seconds is not None:
            elapsed_seconds = end_seconds - start_seconds
            if elapsed_seconds < 0:
                elapsed_seconds += 86400
            duration_minutes = elapsed_seconds / 60
        if start_seconds is None and end_seconds is not None and duration_minutes > 0:
            start_seconds = int(round(end_seconds - duration_minutes * 60)) % 86400
        if end_seconds is None and start_seconds is not None and duration_minutes > 0:
            end_seconds = int(round(start_seconds + duration_minutes * 60)) % 86400

        if not work_date or start_seconds is None or end_seconds is None or duration_minutes <= 0:
            info["invalid_rows"] += 1
            continue

        project = _downtime_clean(source_row.get(project_col, "")) if project_col else ""
        place = _downtime_clean(source_row.get(place_col, "")) if place_col else ""
        cause = _downtime_clean(source_row.get(cause_col, "")) if cause_col else ""
        error_type = _downtime_clean(source_row.get(error_type_col, "")) if error_type_col else ""
        downtime_type = _downtime_clean(source_row.get(downtime_type_col, "")) if downtime_type_col else ""
        sector = _downtime_clean(source_row.get(sector_col, "")) if sector_col else ""
        main_description = cause or error_type or downtime_type or "Intervencija na zastoju"
        context = [item for item in [project, place] if item]
        task_title = main_description + (" | " + " / ".join(context) if context else "")

        # Never use the mutable Google Sheet row number as an identity.  A timestamp
        # is preferred; the remaining immutable source fields make old rows stable
        # even if someone inserts or deletes rows above them.
        source_payload = "|".join([
            PROCESS_DOWNTIME_SHEET_ID,
            PROCESS_DOWNTIME_SHEET_NAME,
            timestamp_value,
            source_name,
            work_date,
            _downtime_time_text(start_seconds),
            _downtime_time_text(end_seconds),
            f"{duration_minutes:.6f}",
            project,
            place,
            cause,
            error_type,
            downtime_type,
            sector,
        ])
        source_id = f"DOWNTIME-{hashlib.sha1(source_payload.encode('utf-8')).hexdigest()[:20]}"
        activity_id = f"ACT-{hashlib.sha1(source_id.encode('utf-8')).hexdigest()[:20]}"
        task_context = " / ".join(item for item in [project, sector, place, downtime_type, error_type] if item)
        rows.append({
            "Activity_ID": activity_id,
            "Source": PROCESS_DOWNTIME_SOURCE,
            "Source_ID": source_id,
            "Technician_ID": technician["Technician_ID"],
            "Technician_Name": technician["Technician_Name"],
            "Work_Date": work_date,
            "Start_Time": _downtime_time_text(start_seconds),
            "End_Time": _downtime_time_text(end_seconds),
            "Calculated_Duration": round(duration_minutes, 2),
            "Effective_Duration": round(duration_minutes, 2),
            "Process": PROCESS_DOWNTIME_CATEGORY,
            "Task_Title": task_title[:500],
            "Task_ID": task_context[:250],
            "Imported_At": imported_at,
        })

    info["valid_rows"] = len(rows)
    info["ignored_names"] = sorted(ignored_names, key=str.casefold)
    return rows, info


@st.cache_data(ttl=180)
def get_all_activities_status():
    """Return persistent initialization status without importing any data."""
    try:
        ws = get_worksheet(ALL_ACTIVITIES_SHEET_ID, ALL_ACTIVITIES_SHEET_NAME)
        source_ids = [str(x).strip() for x in ws.col_values(3)[1:] if str(x).strip()]
        row_count = len(source_ids)
        return {"initialized": row_count > 0, "row_count": row_count, "error": ""}
    except Exception as exc:
        return {"initialized": False, "row_count": 0, "error": f"{type(exc).__name__}: {exc}"}


@st.cache_resource
def _activity_sync_state():
    """Process-wide synchronization state shared by every user session."""
    return {"lock": threading.Lock(), "last_run": 0.0, "dirty": True, "last_result": {}}


def mark_activity_sync_needed():
    """Called after any write that must appear in KPI (Work Ticket activity)."""
    try:
        _activity_sync_state()["dirty"] = True
    except Exception:
        pass


ACTIVITY_SYNC_MIN_INTERVAL_SEC = 120


def ensure_activities_synced(max_age_seconds=ACTIVITY_SYNC_MIN_INTERVAL_SEC):
    """Keep ALL_ACTIVITIES current without slowing every page view.

    KPI previously read ALL_ACTIVITIES only, while the import from Google Forms,
    Work Tickets and downtime ran only through the background automation (which
    never started without AUTOMATION_TOKEN). Entries therefore looked missing.
    Now the KPI page synchronizes when something new was saved or when the last
    synchronization is older than two minutes, at most once at a time for the
    whole server.
    """
    state = _activity_sync_state()
    age = time_module.time() - float(state.get("last_run", 0.0) or 0.0)
    if not state.get("dirty") and age < max_age_seconds:
        return state.get("last_result") or {"status": "fresh"}
    return sync_all_activities(force=True)


def _read_sheet_records_fresh(sheet_id, sheet_name):
    """Same output as :func:`load_worksheet` but always read from Google."""
    ws = get_worksheet(sheet_id, sheet_name)
    with fresh_reads():
        return pd.DataFrame(ws.get_all_records())


def _repair_form_dates(all_ws, form_rows, existing_records):
    """Correct Work_Date of FORM rows imported with a swapped day/month.

    Runs only when the Forms date column is detected as US month/day/year.
    Rows are matched by their stable Source_ID; nothing else is touched.
    """
    wanted = {row["Source_ID"]: row["Work_Date"] for row in form_rows}
    updates = []
    for row_number, source_id, work_date in existing_records:
        target = wanted.get(source_id)
        if target and target != work_date and _normalize_date_string(work_date) != target:
            updates.append({"range": f"F{row_number}", "values": [[target]]})
    if updates:
        for chunk_start in range(0, len(updates), 500):
            all_ws.batch_update(updates[chunk_start:chunk_start + 500], value_input_option="USER_ENTERED")
    return len(updates)


def sync_all_activities(force=False):
    """Synchronize Forms, Work Tickets and technician downtime into ALL_ACTIVITIES.

    Existing source sheets are read-only. Only new deterministic Source_ID values are appended,
    so reruns do not create duplicates. A single batch append is used to limit API requests.
    A process-wide lock guarantees that two users (or the automation and a user)
    never synchronize at the same time, which previously could append duplicates.
    """
    state = _activity_sync_state()
    session_key = "_all_activities_sync_done"
    if st.session_state.get(session_key) and not force:
        return st.session_state.get("_all_activities_sync_result", {"status": "session_cached"})

    acquired = state["lock"].acquire(timeout=90)
    if not acquired:
        return state.get("last_result") or {"status": "busy", "errors": ["Synchronization already running."]}
    try:
        # Another session may have finished a sync while we waited for the lock.
        if force and not state.get("dirty") and time_module.time() - float(state.get("last_run", 0.0)) < 15:
            return state.get("last_result") or {"status": "fresh"}
        result = _sync_all_activities_locked()
        if result.get("status") == "ok":
            state["dirty"] = False
            state["last_run"] = time_module.time()
            state["last_result"] = result
            # Only a successful sync is remembered for the session; a failed one
            # is retried on the next request instead of being hidden.
            st.session_state[session_key] = True
            st.session_state["_all_activities_sync_result"] = result
        return result
    finally:
        state["lock"].release()


def _sync_all_activities_locked():
    result = {
        "status": "ok",
        "forms_added": 0,
        "app_added": 0,
        "downtime_added": 0,
        "errors": [],
        "forms_total": 0,
        "forms_skipped_rows": 0,
        "forms_skipped_examples": [],
        "forms_date_order": "dmy",
        "forms_dates_repaired": 0,
        "app_total": 0,
        "downtime_total": 0,
        "downtime_source_rows": 0,
        "downtime_ignored_rows": 0,
        "downtime_invalid_rows": 0,
        "downtime_ignored_names": [],
        "duplicates_skipped": 0,
        "all_total_before": 0,
        "all_total_after": 0,
    }
    try:
        all_ws = get_worksheet(ALL_ACTIVITIES_SHEET_ID, ALL_ACTIVITIES_SHEET_NAME)
        with fresh_reads():
            header = [str(x).strip() for x in all_ws.row_values(1)]
            if header[:len(ALL_ACTIVITY_COLUMNS)] != ALL_ACTIVITY_COLUMNS:
                # Keep the user-created sheet, but standardize the first row exactly once.
                all_ws.update("A1:N1", [ALL_ACTIVITY_COLUMNS])
            id_columns = all_ws.get("C:F")
        existing_records = []
        for row_number, row in enumerate(id_columns[1:], start=2):
            source_id = str(row[0]).strip() if row else ""
            if source_id:
                work_date = str(row[3]).strip() if len(row) > 3 else ""
                existing_records.append((row_number, source_id, work_date))
        existing_ids = {source_id for _, source_id, _ in existing_records}
        result["all_total_before"] = len(existing_records)
        technicians, tech_errors = load_technicians_master()
        result["errors"].extend(tech_errors or [])
        imported_at = datetime.now(ZoneInfo("Europe/Belgrade")).strftime("%d.%m.%Y %H:%M:%S")

        forms_df = _read_sheet_records_fresh(KPI_SHEET_ID, KPI_SHEET_NAME)
        form_rows, form_errors, form_info = normalize_forms_rows_detailed(forms_df, technicians, imported_at)
        result["errors"].extend(form_errors)
        result["forms_total"] = len(form_rows)
        result["forms_skipped_rows"] = form_info.get("skipped_rows", 0)
        result["forms_skipped_examples"] = form_info.get("skipped_examples", [])
        result["forms_date_order"] = form_info.get("date_order", "dmy")
        if result["forms_date_order"] == "mdy":
            result["forms_dates_repaired"] = _repair_form_dates(all_ws, form_rows, existing_records)

        migrate_work_ticket_ids()
        load_task_activity_data.clear()
        load_tasks_data.clear()
        with fresh_reads():
            app_df, app_errors = load_task_activity_data()
            result["errors"].extend(app_errors or [])
            # TASK_ACTIVITY intentionally stays compact; enrich it from TASKS for KPI process/category.
            tasks_df, task_errors = load_tasks_data()
        result["errors"].extend(task_errors or [])
        if not app_df.empty and not tasks_df.empty:
            tasks_by_id = {}
            legacy_task_map = {}
            for _, task in tasks_df.iterrows():
                task_id = str(task.get("Task_ID", "") or "").strip()
                details = {
                    "Process": str(task.get("Process", "")).strip(),
                    "Task_ID": task_id,
                }
                if task_id:
                    tasks_by_id[task_id] = details
                legacy_task_map.setdefault(_task_link_key(task), []).append(details)
            app_df = app_df.copy()
            process_values, task_ids = [], []
            for _, activity in app_df.iterrows():
                activity_task_id = str(activity.get("Task_ID", "") or "").strip()
                matched = tasks_by_id.get(activity_task_id, {})
                if not matched:
                    legacy_candidates = legacy_task_map.get(_task_link_key(activity), [])
                    matched = legacy_candidates[0] if len(legacy_candidates) == 1 else {}
                process_values.append(matched.get("Process", ""))
                task_ids.append(matched.get("Task_ID", activity_task_id))
            app_df["Process"] = process_values
            app_df["Task_ID"] = task_ids
        app_rows, normalize_errors = normalize_app_rows(app_df, technicians, imported_at)
        result["errors"].extend(normalize_errors)
        result["app_total"] = len(app_rows)

        # External downtime form is optional and read-only. If access has not yet
        # been granted, the other KPI sources still synchronize normally.
        downtime_rows = []
        try:
            downtime_df = _read_sheet_records_fresh(PROCESS_DOWNTIME_SHEET_ID, PROCESS_DOWNTIME_SHEET_NAME)
            downtime_rows, downtime_info = normalize_process_downtime_rows(
                downtime_df, technicians, imported_at
            )
            result["downtime_total"] = len(downtime_rows)
            result["downtime_source_rows"] = downtime_info.get("source_rows", 0)
            result["downtime_ignored_rows"] = downtime_info.get("ignored_rows", 0)
            result["downtime_invalid_rows"] = downtime_info.get("invalid_rows", 0)
            result["downtime_ignored_names"] = downtime_info.get("ignored_names", [])
            result["downtime_ambiguous_master_names"] = downtime_info.get("ambiguous_master_names", [])
            result["downtime_missing_technician_ids"] = downtime_info.get("missing_technician_ids", [])
            result["errors"].extend(downtime_info.get("errors", []))
        except Exception as downtime_exc:
            result["downtime_status"] = "unavailable"
            result["errors"].append(
                "Downtime source could not be loaded: "
                f"{type(downtime_exc).__name__}: {downtime_exc}"
            )

        def only_new(candidates):
            fresh = []
            for row in candidates:
                if row["Source_ID"] in existing_ids:
                    continue
                existing_ids.add(row["Source_ID"])  # also removes duplicates inside one batch
                fresh.append(row)
            return fresh

        new_form_rows = only_new(form_rows)
        new_app_rows = only_new(app_rows)
        new_downtime_rows = only_new(downtime_rows)
        rows = new_form_rows + new_app_rows + new_downtime_rows
        if rows:
            for chunk_start in range(0, len(rows), 2000):
                chunk = rows[chunk_start:chunk_start + 2000]
                all_ws.append_rows([_safe_row(r) for r in rows_to_matrix(chunk)], value_input_option="USER_ENTERED", table_range="A1")
        load_all_activities.clear()
        build_kpi_dataset.clear()
        result["forms_added"] = len(new_form_rows)
        result["app_added"] = len(new_app_rows)
        result["downtime_added"] = len(new_downtime_rows)
        result["total_added"] = len(rows)
        result["duplicates_skipped"] = max(
            result["forms_total"] + result["app_total"] + result["downtime_total"]
            - result["total_added"],
            0,
        )
        result["all_total_after"] = result["all_total_before"] + result["total_added"]
        result["synced_at"] = imported_at
        get_all_activities_status.clear()
    except gspread.exceptions.APIError as exc:
        result.update({"status": "google_api_error", "errors": [str(exc)]})
    except Exception as exc:
        result.update({"status": "error", "errors": [f"{type(exc).__name__}: {exc}"]})
    return result


def clear_all_activity_sync_state():
    st.session_state.pop("_all_activities_sync_done", None)
    st.session_state.pop("_all_activities_sync_result", None)
    load_all_activities.clear()
    build_kpi_dataset.clear()
    get_all_activities_status.clear()


def _find_header_col(headers, column_name):
    wanted = _norm_sheet_col(column_name)
    for i, h in enumerate(headers, start=1):
        if _norm_sheet_col(h) == wanted:
            return i
    return None


def _gs_safe_value(value):
    """Convert pandas/numpy/date values into JSON-serializable values for gspread."""
    if pd.api.types.is_scalar(value) and pd.isna(value):
        return ""

    original_value = value
    try:
        if hasattr(value, "item") and not isinstance(value, (str, bytes)):
            value = value.item()
    except (TypeError, ValueError, AttributeError):
        value = original_value

    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime("%d.%m.%Y %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, time):
        return value.strftime("%H:%M")
    if isinstance(value, float):
        if not math.isfinite(value):
            return ""
        return round(float(value), 6)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, str):
        return _sheet_safe_text(value)
    return value


_NUMBER_TEXT_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")


def _sheet_safe_text(text):
    """Stop Google Sheets from treating free text as a formula.

    With USER_ENTERED, a task title such as "-podesiti senzor", "+5 min" or
    "=OK" is evaluated as a formula and saved as #ERROR!, so the entry looked
    lost. Such text gets a leading apostrophe, which Sheets hides.
    """
    if not text:
        return text
    if text[0] in "=+-@" and not _NUMBER_TEXT_RE.match(text.strip()):
        return "'" + text
    return text


def _safe_row(values):
    """Apply :func:`_gs_safe_value` to every cell of a row."""
    return [_gs_safe_value(value) for value in values]


def _append_dict_to_sheet(sheet_name, row_dict, required_columns):
    ws = _get_kpi_worksheet(sheet_name)
    headers = _ensure_sheet_headers(ws, required_columns)
    mapping = _canonical_header_map(headers, required_columns)
    by_norm = {_norm_sheet_col(k): v for k, v in row_dict.items()}
    row = []
    for index, header in enumerate(headers):
        name = mapping.get(index, header)
        value = row_dict.get(name, by_norm.get(_norm_sheet_col(header), ""))
        row.append(_gs_safe_value(value))
    # table_range="A1" anchors the append to column A; without it Google can
    # detect a different "table" and place the row in shifted columns.
    ws.append_row(row, value_input_option="USER_ENTERED", table_range="A1")
    if sheet_name == TASK_ACTIVITY_SHEET_NAME:
        clear_all_activity_sync_state()
        mark_activity_sync_needed()


def _new_task_id():
    return f"TASK-{uuid.uuid4().hex}"


def _new_activity_id():
    return f"ACT-{uuid.uuid4().hex}"


def _task_link_key(record):
    technician_id = str(record.get("Assigned_Technician_ID", "") or "").strip().upper()
    technician_name = _normalize_name_key(record.get("Assigned_To", ""))
    person_key = f"ID:{technician_id}" if technician_id else f"NAME:{technician_name}"
    title_key = str(record.get("Task_Title", "") or "").strip().casefold()
    return person_key, title_key


def _live_sheet_records(sheet_name, required_columns):
    """Read a mutation target live; cached row numbers are never trusted here."""
    ws = _get_kpi_worksheet(sheet_name)
    with fresh_reads():
        values = ws.get_all_values()
    headers = _ensure_sheet_headers(ws, required_columns, header_row=values[0] if values else [])
    mapping = _canonical_header_map(headers, required_columns)
    records = []
    for row_number, row in enumerate(values[1:], start=2):
        if not any(str(cell).strip() for cell in row):
            continue
        record = {name: (row[index] if index < len(row) else "") for index, name in mapping.items()}
        for col in required_columns:
            record.setdefault(col, "")
        record["_row"] = row_number
        records.append(record)
    return ws, headers, records


@st.cache_resource
def _ticket_migration_state():
    return {"lock": threading.Lock(), "last_run": 0.0, "result": {}}


def migrate_work_ticket_ids():
    """Add stable IDs to legacy tasks/activities without guessing ambiguous links.

    Runs at most once every 10 minutes for the whole server (previously two
    full live reads for every user session) and never twice at the same time.
    """
    if st.session_state.get("_work_ticket_id_migration_done"):
        return st.session_state.get("_work_ticket_id_migration_result", {})
    state = _ticket_migration_state()
    with state["lock"]:
        if time_module.time() - state["last_run"] < 600 and state["result"]:
            st.session_state["_work_ticket_id_migration_done"] = True
            st.session_state["_work_ticket_id_migration_result"] = state["result"]
            return state["result"]
        result = _migrate_work_ticket_ids_locked()
        state["last_run"] = time_module.time()
        state["result"] = result
        return result


def _migrate_work_ticket_ids_locked():
    task_ws, task_headers, tasks = _live_sheet_records(TASKS_SHEET_NAME, TASK_REQUIRED_COLUMNS)
    task_id_col = _find_header_col(task_headers, "Task_ID")
    task_updates = []
    seen_task_ids = set()
    task_ids_by_link = {}
    for task in tasks:
        task_id = str(task.get("Task_ID", "") or "").strip()
        if not task_id or task_id in seen_task_ids:
            task_id = _new_task_id()
            task["Task_ID"] = task_id
            task_updates.append({
                "range": f"{_column_number_to_letter(task_id_col)}{task['_row']}",
                "values": [[task_id]],
            })
        seen_task_ids.add(task_id)
        task_ids_by_link.setdefault(_task_link_key(task), []).append(task_id)
    if task_updates:
        task_ws.batch_update(task_updates, value_input_option="RAW")

    activity_ws, activity_headers, activities = _live_sheet_records(
        TASK_ACTIVITY_SHEET_NAME, TASK_ACTIVITY_REQUIRED_COLUMNS
    )
    activity_id_col = _find_header_col(activity_headers, "Activity_ID")
    activity_task_id_col = _find_header_col(activity_headers, "Task_ID")
    activity_updates = []
    seen_activity_ids = set()
    ambiguous_links = 0
    linked_legacy = 0
    for activity in activities:
        activity_id = str(activity.get("Activity_ID", "") or "").strip()
        if not activity_id or activity_id in seen_activity_ids:
            activity_id = _new_activity_id()
            activity["Activity_ID"] = activity_id
            activity_updates.append({
                "range": f"{_column_number_to_letter(activity_id_col)}{activity['_row']}",
                "values": [[activity_id]],
            })
        seen_activity_ids.add(activity_id)

        if not str(activity.get("Task_ID", "") or "").strip():
            candidates = task_ids_by_link.get(_task_link_key(activity), [])
            if len(candidates) == 1:
                activity["Task_ID"] = candidates[0]
                linked_legacy += 1
                activity_updates.append({
                    "range": f"{_column_number_to_letter(activity_task_id_col)}{activity['_row']}",
                    "values": [[candidates[0]]],
                })
            elif len(candidates) > 1:
                ambiguous_links += 1
    if activity_updates:
        activity_ws.batch_update(activity_updates, value_input_option="RAW")

    if task_updates or activity_updates:
        clear_work_ticket_cache()
        clear_all_activity_sync_state()
    result = {
        "task_ids_added": len(task_updates),
        "activity_cells_updated": len(activity_updates),
        "legacy_activities_linked": linked_legacy,
        "ambiguous_legacy_activities": ambiguous_links,
    }
    st.session_state["_work_ticket_id_migration_done"] = True
    st.session_state["_work_ticket_id_migration_result"] = result
    return result



# =====================================================
# EMAIL NOTIFICATION MODULE
# =====================================================

EMAIL_LOG_COLUMNS = [
    "Timestamp", "Email_Type", "Recipient", "Subject", "Status", "Related_ID", "Error_Message"
]


def _get_secret_value(*keys, default=""):
    """Read Streamlit secrets from either root keys or [email]/[smtp] sections."""
    try:
        for key in keys:
            if isinstance(key, tuple) and len(key) == 2:
                section, item = key
                if section in st.secrets and item in st.secrets[section]:
                    return st.secrets[section][item]
            elif key in st.secrets:
                return st.secrets[key]
    except Exception:
        return default
    return default


def _email_settings():
    # Supports both old and new secret names so existing Streamlit secrets do not break.
    host = _get_secret_value(
        ("email", "SMTP_HOST"), ("email", "SMTP_SERVER"),
        ("smtp", "host"), ("smtp", "server"),
        "SMTP_HOST", "SMTP_SERVER", default=""
    )
    port = int(_get_secret_value(("email", "SMTP_PORT"), ("smtp", "port"), "SMTP_PORT", default=587) or 587)
    username = _get_secret_value(
        ("email", "SMTP_USER"), ("email", "SMTP_USERNAME"),
        ("smtp", "username"), ("smtp", "user"),
        "SMTP_USER", "SMTP_USERNAME", default=""
    )
    password = _get_secret_value(("email", "SMTP_PASSWORD"), ("smtp", "password"), "SMTP_PASSWORD", default="")
    sender = _get_secret_value(
        ("email", "EMAIL_SENDER"), ("email", "FROM_EMAIL"),
        ("smtp", "sender"), ("smtp", "from_email"),
        "EMAIL_SENDER", "FROM_EMAIL", default=username
    )
    sender_name = _get_secret_value(("email", "EMAIL_SENDER_NAME"), "EMAIL_SENDER_NAME", default="Lianbo Project Performance Hub")
    enabled = _yes_value(_get_secret_value(("email", "EMAIL_ENABLED"), "EMAIL_ENABLED", default="YES"))
    return {"host": host, "port": port, "username": username, "password": password, "sender": sender, "sender_name": sender_name, "enabled": enabled}


def _ensure_email_log_sheet():
    """Cached EMAIL_LOG handle; header check reads only row 1 (not the whole log)."""
    return _get_or_create_worksheet(KPI_SHEET_ID, EMAIL_LOG_SHEET_NAME, EMAIL_LOG_COLUMNS)


def _log_email_event(email_type, recipient, subject, status, related_id="", error_message=""):
    try:
        row = {
            "Timestamp": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            "Email_Type": email_type,
            "Recipient": recipient,
            "Subject": subject,
            "Status": status,
            "Related_ID": related_id,
            "Error_Message": error_message,
        }
        ws = _ensure_email_log_sheet()
        # RAW keeps Related_ID (for example "23.10.2026") as text, so the
        # duplicate-alert check can match it regardless of the sheet locale.
        ws.append_row([_gs_safe_value(row.get(h, "")) for h in EMAIL_LOG_COLUMNS], value_input_option="RAW", table_range="A1")
    except Exception as exc:
        st.session_state["_email_log_error"] = f"{type(exc).__name__}: {exc}"


def get_notification_recipients(notification_column, include_names=False):
    """Return active recipients from Technicians plus per-user notification settings."""
    recipients = []
    tech_df, _ = load_technicians_master()
    if not tech_df.empty and notification_column in tech_df.columns:
        mask = tech_df["Active"].apply(_yes_value) & tech_df[notification_column].apply(_yes_value)
        rows = tech_df[mask].copy()
        for _, row in rows.iterrows():
            email = str(row.get("Email", "") or "").strip()
            if email:
                recipients.append({"Technician_Name": str(row.get("Technician_Name", "") or "").strip(), "Email": email})

    try:
        users_df, _ = load_admin_users_data()
        if not users_df.empty and notification_column in users_df.columns:
            mask = users_df["Active"].apply(_yes_value) & users_df[notification_column].apply(_yes_value)
            for _, row in users_df[mask].iterrows():
                email = str(row.get("Email", "") or "").strip()
                if email:
                    recipients.append({"Technician_Name": str(row.get("Full_Name", "") or "").strip(), "Email": email})
    except Exception as exc:
        st.session_state["_notification_recipient_warning"] = f"{type(exc).__name__}: {exc}"

    if not recipients:
        return []
    rows = pd.DataFrame(recipients).drop_duplicates(subset=["Email"])
    if include_names:
        return rows[["Technician_Name", "Email"]].to_dict("records")
    return sorted(rows["Email"].tolist())


def recipient_accepts_notification(email, notification_column):
    """Respect explicit per-user opt-out while preserving legacy direct task e-mails."""
    wanted = str(email or "").strip().casefold()
    if not wanted:
        return False
    try:
        users_df, _ = load_admin_users_data()
        if not users_df.empty and notification_column in users_df.columns:
            matches = users_df[
                users_df["Email"].astype(str).str.strip().str.casefold().eq(wanted)
                & users_df["Active"].apply(_yes_value)
            ]
            if not matches.empty:
                override = _parse_user_override(matches.iloc[0].get(notification_column, ""))
                if override is not None:
                    return override
        tech_df, _ = load_technicians_master()
        if not tech_df.empty and notification_column in tech_df.columns:
            matches = tech_df[
                tech_df["Email"].astype(str).str.strip().str.casefold().eq(wanted)
                & tech_df["Active"].apply(_yes_value)
            ]
            if not matches.empty:
                return _yes_value(matches.iloc[0].get(notification_column, "YES"))
    except Exception as exc:
        st.session_state["_notification_preference_warning"] = f"{type(exc).__name__}: {exc}"
        return False
    return True


def get_email_service():
    from email_service import EmailService

    kwargs = dict(
        get_client_func=get_client,
        sheet_id=KPI_SHEET_ID,
        log_sheet_name=EMAIL_LOG_SHEET_NAME,
        log_columns=EMAIL_LOG_COLUMNS,
    )
    try:
        return EmailService(log_worksheet_func=_ensure_email_log_sheet, **kwargs)
    except TypeError:
        # Older email_service.py still in the repository.
        return EmailService(**kwargs)


def send_email_notification(email_type, recipients, subject, body, related_id=""):
    """Central notification entry point used by all modules.

    Actual SMTP handling and EMAIL_LOG writing are isolated in email_service.py.
    This keeps Work Tickets, BN, KPI and future modules on one shared e-mail service.
    """
    return get_email_service().send_email(email_type, recipients, subject, body, related_id)


def send_task_created_email(task_row):
    recipient = str(task_row.get("Assigned_Email", "") or "").strip()
    if not recipient:
        email_map, _ = _get_technician_email_map()
        recipient = email_map.get(str(task_row.get("Assigned_To", "") or "").strip(), "")
    if not recipient:
        return {"sent": 0, "failed": 0, "skipped": "Assigned email missing"}
    if not recipient_accepts_notification(recipient, "Receive_Task_Email"):
        return {"sent": 0, "failed": 0, "skipped": "Task e-mail disabled for recipient"}
    subject = f"New task assigned: {task_row.get('Task_Title', '')}"
    body = (
        "A new task has been assigned to you.\n\n"
        f"Assigned to: {task_row.get('Assigned_To', '')}\n"
        f"Process: {task_row.get('Process', '')}\n"
        f"Task: {task_row.get('Task_Title', '')}\n"
        f"Priority: {task_row.get('Task_Priority', task_row.get('Task_Duration', ''))}\n"
        f"Status: {task_row.get('Status', '')}\n\n"
        "Please update the task status/activity in Lianbo Project Performance Hub."
    )
    return send_email_notification("TASK_CREATED", [recipient], subject, body, str(task_row.get("Task_Title", "")))




def send_task_completed_email(task_row, completed_by="", completed_at="", duration_min=""):
    """Notify creator and assignee only for a delegated task.

    A technician who created a task for himself/herself does not receive a redundant
    completion message. For a delegated task, both the creator and assignee are notified.
    """
    assigned_email = str(task_row.get("Assigned_Email", "") or "").strip().lower()
    created_email = str(task_row.get("Created_By_Email", "") or "").strip().lower()
    assigned_name = str(task_row.get("Assigned_To", "") or "").strip()
    created_name = str(task_row.get("Created_By", "") or "").strip()

    is_self_created = False
    if assigned_email and created_email:
        is_self_created = assigned_email == created_email
    elif assigned_name and created_name:
        is_self_created = _normalize_name_key(assigned_name) == _normalize_name_key(created_name)

    if is_self_created:
        return {"sent": 0, "failed": 0, "skipped": "Self-created task; completion e-mail suppressed", "errors": []}

    recipients = list(dict.fromkeys([
        r for r in [created_email, assigned_email]
        if r and recipient_accepts_notification(r, "Receive_Task_Email")
    ]))
    if not recipients:
        return {"sent": 0, "failed": 0, "skipped": "Completion recipients missing", "errors": []}

    subject = f"Task completed: {task_row.get('Task_Title', '')}"
    body = (
        "Task has been completed.\n\n"
        f"Task: {task_row.get('Task_Title', '')}\n"
        f"Process: {task_row.get('Process', '')}\n"
        f"Assigned to: {task_row.get('Assigned_To', '')}\n"
        f"Completed by: {completed_by or task_row.get('Closed_By', '')}\n"
        f"Completed at: {completed_at or task_row.get('Closed_At', '')}\n"
        f"Duration: {duration_min or task_row.get('Calculated_Duration', '')} min\n\n"
        "This is an automatic notification from Lianbo Project Performance Hub."
    )
    return send_email_notification("TASK_COMPLETED", recipients, subject, body, str(task_row.get("Task_Title", "")))


def _current_user_display_name():
    user = _session_user()
    return str(user.get("full_name") or user.get("username") or "").strip()


def _current_user_email():
    return str(_session_user().get("email", "") or "").strip()

def send_missing_time_email(missing_technicians, alert_day):
    """Send missing-time e-mail to each missing technician and responsible users.

    Recipients:
    - The technician's own e-mail from Technicians sheet.
    - All active users/technicians with Receive_Missing_Time_Email = YES.
    """
    if is_weekend_day(alert_day):
        return {"sent": 0, "failed": 0, "skipped": "Weekend"}

    supervisor_recipients = get_notification_recipients("Receive_Missing_Time_Email")
    day_txt = pd.to_datetime(alert_day).strftime("%d.%m.%Y")
    names = [str(x).strip() for x in missing_technicians if str(x).strip()]

    tech_df, _ = load_technicians_master()
    technician_recipients = []
    if not tech_df.empty:
        missing_set = set(names)
        for _, row in tech_df.iterrows():
            name = str(row.get("Technician_Name", "")).strip()
            email = str(row.get("Email", "")).strip()
            if name in missing_set and email and _yes_value(row.get("Active", "YES")):
                technician_recipients.append(email)

    recipients = list(dict.fromkeys([
        r for r in technician_recipients + supervisor_recipients
        if str(r).strip() and recipient_accepts_notification(r, "Receive_Missing_Time_Email")
    ]))
    if not recipients:
        return {"sent": 0, "failed": 0, "skipped": "No recipients"}

    subject = f"Missing work time alert: {day_txt}"
    body = (
        f"Missing work time / activity entry detected for {day_txt}.\n\n"
        "Technicians without entry:\n"
        + "\n".join([f"- {name}" for name in names])
        + "\n\nIf this absence is justified, admin should add a note in MISSING_WORK_TIME sheet."
    )
    return send_email_notification("MISSING_TIME", recipients, subject, body, day_txt)



def _canonicalize_bn_headers(df, expected_headers):
    """Map Google Sheet headers case-insensitively to canonical BN column names."""
    df = clean_columns(df)
    if df.empty and len(df.columns) == 0:
        return pd.DataFrame(columns=expected_headers)

    def header_key(value):
        return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())

    aliases = {
        "machineid": "Machine_ID",
        "project": "Project",
        "machine": "Machine",
        "active": "Active",
        "bnid": "BN_ID",
        "source": "Source",
        "sourceid": "Source_ID",
        "date": "Date",
        "bntime": "BN_Time",
        "station": "Station",
        "enteredby": "Entered_By",
        "enteredbyusername": "Entered_By_Username",
        "enteredbyemail": "Entered_By_Email",
        "createdat": "Created_At",
        "updatedat": "Updated_At",
    }

    rename_map = {}
    for column in df.columns:
        canonical = aliases.get(header_key(column))
        if canonical:
            rename_map[column] = canonical

    df = df.rename(columns=rename_map)

    for column in expected_headers:
        if column not in df.columns:
            df[column] = ""

    return df[expected_headers].copy()


@st.cache_data(ttl=60)
def load_bn_machines():
    ws = get_worksheet(BN_DATABASE_SHEET_ID, BN_MACHINES_SHEET_NAME)
    raw_df = pd.DataFrame(ws.get_all_records())
    df = _canonicalize_bn_headers(
        raw_df,
        ["Machine_ID", "Project", "Machine", "Active"],
    )

    # Normalize whitespace and active values without changing stored data.
    for column in ["Machine_ID", "Project", "Machine", "Active"]:
        df[column] = df[column].fillna("").astype(str).str.strip()

    return df

@st.cache_data(ttl=60)
def load_bn_records():
    ws = get_worksheet(BN_DATABASE_SHEET_ID, BN_RECORDS_SHEET_NAME)
    return _bn_values_to_frame(ws.get_all_values())


def _bn_values_to_frame(vals):
    """BN_RECORDS values -> frame; index i is sheet row i + 2 (blank rows kept)."""
    if not vals:
        return pd.DataFrame(columns=BN_RECORD_COLUMNS)
    headers = [str(x).strip() for x in vals[0]]
    width = len(headers)
    rows = [list(row[:width]) + [""] * max(0, width - len(row)) for row in vals[1:]]
    raw_df = pd.DataFrame(rows, columns=headers)
    raw_df = raw_df.loc[:, [bool(str(c).strip()) for c in raw_df.columns]]
    raw_df = raw_df.loc[:, ~raw_df.columns.duplicated()]
    return _canonicalize_bn_headers(raw_df, BN_RECORD_COLUMNS)

def _bn_norm(v):
    return re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKD", str(v or "")).encode("ascii","ignore").decode().lower())

def _bn_machine_lookup(master):
    return {(_bn_norm(r.Project),_bn_norm(r.Machine)):str(r.Machine_ID).strip() for r in master.itertuples()}

def _bn_id(prefix,*parts):
    import hashlib
    return prefix+"-"+hashlib.sha1("|".join(str(x) for x in parts).encode()).hexdigest()[:20]

def _bn_clear_cache():
    load_bn_machines.clear(); load_bn_records.clear()

@st.cache_resource
def _bn_sync_lock():
    return threading.Lock()


def _load_bn_records_fresh():
    ws = get_worksheet(BN_DATABASE_SHEET_ID, BN_RECORDS_SHEET_NAME)
    with fresh_reads():
        vals = ws.get_all_values()
    return ws, _bn_values_to_frame(vals)


def sync_bn_forms_to_records():
    """Import new BN Google Forms responses; never twice, never with swapped dates."""
    lock = _bn_sync_lock()
    if not lock.acquire(timeout=60):
        return {"imported": 0, "status": "busy"}
    try:
        master=load_bn_machines(); lookup=_bn_machine_lookup(master)
        bn_form_ws = get_worksheet(BOTTLENECK_SHEET_ID, BOTTLENECK_SHEET_NAME)
        with fresh_reads():
            raw = pd.DataFrame(bn_form_ws.get_all_records())
        form, missing=prepare_bottleneck_data(raw)
        if missing: return {"imported":0,"missing_columns":missing}
        ws, existing = _load_bn_records_fresh()
        existing_ids=set(existing["Source_ID"].astype(str)) if not existing.empty else set()
        existing_dates = {}
        if not existing.empty:
            for idx, rec in existing.iterrows():
                sid_value = str(rec.get("Source_ID", "")).strip()
                if sid_value:
                    existing_dates[sid_value] = (int(idx) + 2, str(rec.get("Date", "")).strip())
        now=datetime.now(ZoneInfo("Europe/Belgrade")).strftime("%d.%m.%Y %H:%M:%S")
        rows=[]; unmapped=[]; repairs=[]
        for i,r in form.iterrows():
            mid=lookup.get((_bn_norm(r["Project"]),_bn_norm(r["Machine"])),"")
            if not mid:
                unmapped.append(f'{r["Project"]} / {r["Machine"]}'); continue
            day=pd.Timestamp(r["Date"]).strftime("%d.%m.%Y")
            legacy = r.get("Legacy_Date")
            legacy_day = pd.Timestamp(legacy).strftime("%d.%m.%Y") if pd.notna(legacy) else ""
            sid=_bn_id("FORM",r.get("Timestamp",""),legacy_day,mid,r["BN_sec"],i)
            if sid in existing_ids:
                row_number, stored = existing_dates.get(sid, (None, ""))
                if row_number and _normalize_date_string(stored) != day:
                    repairs.append({"range": f"D{row_number}", "values": [[day]]})
                continue
            existing_ids.add(sid)
            rows.append([_bn_id("BN",sid),"FORM",sid,day,mid,r["Project"],r["Machine"],float(r["BN_sec"]),str(r.get("Station","")).strip(),"Google Forms","","",now,now])
        if repairs:
            ws.batch_update(repairs, value_input_option="USER_ENTERED")
        if rows:
            ws.append_rows([_safe_row(r) for r in rows],value_input_option="USER_ENTERED",table_range="A1")
        if rows or repairs:
            _bn_clear_cache()
        return {"imported":len(rows),"dates_repaired":len(repairs),"unmapped":sorted(set(unmapped))}
    finally:
        lock.release()

def maybe_sync_bn_forms(force=False):
    """Synchronize BN Forms at most once every 30 minutes per active session."""
    now = datetime.now(ZoneInfo("Europe/Belgrade"))
    last = st.session_state.get("_bn_forms_sync_at")

    should_run = force or not last
    if last and not force:
        try:
            should_run = (now - datetime.fromisoformat(last)).total_seconds() >= 1800
        except Exception:
            should_run = True

    if should_run:
        result = sync_bn_forms_to_records()
        st.session_state["_bn_forms_sync_result"] = result
        st.session_state["_bn_forms_sync_at"] = now.isoformat()

    return st.session_state.get("_bn_forms_sync_result", {"imported": 0})


def _bn_previous(machine_id, selected_date, exact_yesterday=False):
    df=load_bn_records()
    if df.empty: return None
    d=df.copy(); d["_date"]=parse_mixed_datetime_series(d["Date"])
    target=pd.Timestamp(selected_date).normalize()
    d=d[d["Machine_ID"].astype(str).eq(str(machine_id))]
    if exact_yesterday:
        d=d[d["_date"].dt.normalize().eq(target-pd.Timedelta(days=1))]
    else:
        d=d[d["_date"].dt.normalize().lt(target)]
    if d.empty:return None
    return d.sort_values(["_date","Updated_At"]).iloc[-1]

def save_bn_record(entry, update_existing=False):
    # Live read: the duplicate check and the row number must reflect the sheet
    # right now (another user or the Forms import may have just added rows).
    ws, df = _load_bn_records_fresh()
    day=pd.Timestamp(entry["Date"]).strftime("%d.%m.%Y")
    if not df.empty:
        # Compare real dates, not text: Sheets may display 05.06.2026 as 5.6.2026.
        record_days = parse_mixed_datetime_series(df["Date"]).dt.normalize()
        mask = record_days.eq(pd.Timestamp(entry["Date"]).normalize()) & df["Machine_ID"].astype(str).str.strip().eq(str(entry["Machine_ID"]).strip())
    else:
        mask = pd.Series(dtype=bool)
    now=datetime.now(ZoneInfo("Europe/Belgrade")).strftime("%d.%m.%Y %H:%M:%S")
    if not df.empty and mask.any():
        if not update_existing:return {"status":"duplicate"}
        idx=df[mask].index[-1]; rownum=int(idx)+2
        created=str(df.loc[idx,"Created_At"] or now)
        values=[str(df.loc[idx,"BN_ID"]),"APP",str(df.loc[idx,"Source_ID"] or _bn_id("APP",day,entry["Machine_ID"])),day,entry["Machine_ID"],entry["Project"],entry["Machine"],entry["BN_Time"],entry.get("Station",""),entry["Entered_By"],entry["Entered_By_Username"],entry["Entered_By_Email"],created,now]
        ws.update(f"A{rownum}:N{rownum}",[_safe_row(values)],value_input_option="USER_ENTERED")
        status="updated"
    else:
        sid=_bn_id("APP",day,entry["Machine_ID"])
        values=[_bn_id("BN",sid),"APP",sid,day,entry["Machine_ID"],entry["Project"],entry["Machine"],entry["BN_Time"],entry.get("Station",""),entry["Entered_By"],entry["Entered_By_Username"],entry["Entered_By_Email"],now,now]
        ws.append_row(_safe_row(values),value_input_option="USER_ENTERED",table_range="A1"); status="created"
    _bn_clear_cache()
    # Deviation e-mails are intentionally batched. The automatic scheduler sends
    # one summary 15 minutes after the latest BN entry, rather than one e-mail
    # for every saved machine.
    return {"status":status}

def add_bn_machine(project,machine,active="YES"):
    master=load_bn_machines(); key=(_bn_norm(project),_bn_norm(machine))
    if key in _bn_machine_lookup(master): return {"status":"exists"}
    nums=[]
    for x in master["Machine_ID"].astype(str):
        m=re.search(r"(\d+)$",x)
        if m: nums.append(int(m.group(1)))
    mid=f"BN-M-{max(nums+[0])+1:04d}"
    get_worksheet(BN_DATABASE_SHEET_ID, BN_MACHINES_SHEET_NAME).append_row(_safe_row([mid,project,machine,active]),value_input_option="USER_ENTERED",table_range="A1")
    _bn_clear_cache(); return {"status":"created","Machine_ID":mid}

def prepare_bn_records_data():
    df=load_bn_records()
    if df.empty:return pd.DataFrame()
    out=pd.DataFrame({"Timestamp":df["Created_At"],"Date":parse_mixed_datetime_series(df["Date"]),"Project":df["Project"],"Machine":df["Machine"],"BN_sec":pd.to_numeric(df["BN_Time"],errors="coerce"),"Station":df["Station"],"Entered_By":df["Entered_By"]})
    return out.dropna(subset=["Date","Project","Machine","BN_sec"])

def send_bn_change_email(change_info):
    recipients = get_notification_recipients("Receive_BN_Email")
    old_bn = normalize_float_value(change_info.get("Old_BN", 0), 0)
    new_bn = normalize_float_value(change_info.get("New_BN", 0), 0)
    diff = new_bn - old_bn
    diff_pct = (diff / old_bn * 100) if old_bn else 0
    subject = f"BN changed: {change_info.get('Project', '')} / {change_info.get('Machine', '')}"
    body = (
        "Existing BN / CT value has been changed.\n\n"
        f"Date: {change_info.get('Date', '')}\n"
        f"Project: {change_info.get('Project', '')}\n"
        f"Process: {change_info.get('Process', '')}\n"
        f"Machine: {change_info.get('Machine', '')}\n"
        f"Old BN: {old_bn:g} sec\n"
        f"New BN: {new_bn:g} sec\n"
        f"Difference: {diff:+.2f} sec / {diff_pct:+.2f}%\n"
        f"Changed by: {change_info.get('Changed_By', '')}\n"
        f"Changed at: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}\n"
    )
    related_id = f"{change_info.get('Date','')}|{change_info.get('Project','')}|{change_info.get('Process','')}|{change_info.get('Machine','')}"
    return send_email_notification("BN_CHANGED", recipients, subject, body, related_id)



def _parse_bn_datetime(value):
    return parse_mixed_datetime(value)


def send_bn_deviation_batch_email(changes, alert_day, latest_entry_at):
    recipients = get_notification_recipients("Receive_BN_Email")
    if not recipients:
        return {"sent": 0, "failed": 0, "skipped": "No BN recipients", "errors": []}

    day_txt = pd.Timestamp(alert_day).strftime("%d.%m.%Y")
    lines = []
    for change in changes:
        diff = float(change["New_BN"]) - float(change["Old_BN"])
        lines.append(
            f"- {change['Project']} / {change['Machine']} / {change.get('Station','')} | "
            f"Yesterday: {float(change['Old_BN']):g} s | Today: {float(change['New_BN']):g} s | "
            f"Difference: {diff:+.2f} s | Entered by: {change.get('Changed_By','')}"
        )

    subject = f"BN deviation summary: {day_txt}"
    body = (
        f"BN values with a deviation greater than +/- {BN_DEVIATION_LIMIT_SEC:g} seconds "
        f"compared with yesterday are listed below.\n\n"
        + "\n".join(lines)
        + f"\n\nLatest BN entry: {latest_entry_at.strftime('%d.%m.%Y %H:%M:%S')}"
        + "\nThis summary was generated 15 minutes after the latest BN entry."
    )
    related_id = f"{day_txt}|{latest_entry_at.strftime('%Y%m%d%H%M%S')}"
    return send_email_notification("BN_DEVIATION_BATCH", recipients, subject, body, related_id)


def run_bn_deviation_batch_check(force=False):
    """Send one BN deviation summary 15 minutes after the latest today's entry."""
    now = datetime.now(ZoneInfo("Europe/Belgrade"))
    today = pd.Timestamp(now.date())
    if today.weekday() >= 5:
        return {"status": "weekend"}

    try:
        records = load_bn_records()
    except Exception as exc:
        return {"status": "load_error", "error": str(exc)}
    if records.empty:
        return {"status": "no_records"}

    work = records.copy()
    work["_date"] = parse_mixed_datetime_series(work["Date"]).dt.normalize()
    work["_updated"] = work["Updated_At"].apply(_parse_bn_datetime)
    work["_created"] = work["Created_At"].apply(_parse_bn_datetime)
    work["_event_at"] = work["_updated"].fillna(work["_created"])
    today_rows = work[work["_date"].eq(today)].copy()
    if today_rows.empty:
        return {"status": "no_today_records"}

    latest_entry_at = today_rows["_event_at"].max()
    if pd.isna(latest_entry_at):
        return {"status": "missing_timestamp"}
    latest_entry_at = latest_entry_at.to_pydatetime()
    if latest_entry_at.tzinfo is None:
        latest_entry_at = latest_entry_at.replace(tzinfo=ZoneInfo("Europe/Belgrade"))

    elapsed = (now - latest_entry_at).total_seconds()
    if not force and elapsed < 15 * 60:
        return {"status": "waiting", "seconds_remaining": int(15 * 60 - elapsed)}

    related_id = f"{today.strftime('%d.%m.%Y')}|{latest_entry_at.strftime('%Y%m%d%H%M%S')}"
    already = _email_log_has_success("BN_DEVIATION_BATCH", related_id)
    if already is None:
        return {"status": "email_log_unavailable"}
    if already:
        return {"status": "already_sent", "related_id": related_id}

    changes = []
    for _, row in today_rows.iterrows():
        previous = _bn_previous(row.get("Machine_ID", ""), today, exact_yesterday=True)
        if previous is None:
            continue
        old_bn = normalize_float_value(previous.get("BN_Time", 0), 0)
        new_bn = normalize_float_value(row.get("BN_Time", 0), 0)
        if abs(new_bn - old_bn) > BN_DEVIATION_LIMIT_SEC:
            changes.append({
                "Project": str(row.get("Project", "")).strip(),
                "Machine": str(row.get("Machine", "")).strip(),
                "Station": str(row.get("Station", "")).strip(),
                "Old_BN": old_bn,
                "New_BN": new_bn,
                "Changed_By": str(row.get("Entered_By", "")).strip(),
            })

    if not changes:
        return {"status": "no_deviations", "date": today.strftime("%d.%m.%Y")}

    result = send_bn_deviation_batch_email(changes, today, latest_entry_at)
    return {
        "status": "sent" if result.get("sent", 0) else "not_sent",
        "date": today.strftime("%d.%m.%Y"),
        "changes": len(changes),
        "email": result,
    }


def send_task_reminder_email(open_tasks_df, alert_day):
    if open_tasks_df is None or open_tasks_df.empty:
        return {"sent": 0, "failed": 0, "skipped": "No open tasks"}
    recipients = get_notification_recipients("Receive_Task_Reminder")
    day_txt = pd.Timestamp(alert_day).strftime("%d.%m.%Y")
    subject = f"Open task reminder: {day_txt}"
    lines = []
    for _, row in open_tasks_df.iterrows():
        lines.append(
            f"- {row.get('Assigned_To','')} | {row.get('Task_Title','')} | "
            f"{row.get('Status','')} | Priority: {row.get('Task_Priority','')}"
        )
    body = (
        f"Open tasks requiring attention on {day_txt}:\n\n"
        + "\n".join(lines)
        + "\n\nPlease update or close these tasks in Lianbo Project Performance Hub."
    )
    return send_email_notification("TASK_REMINDER", recipients, subject, body, day_txt)



def _email_log_has_success(email_type, related_id):
    """Return True when EMAIL_LOG already contains a successful event for this key.

    Returns None when the log cannot be read. Callers then skip sending in this
    round; previously a read error returned False and the same alert was sent
    again on every automation run.
    """
    try:
        ws = _ensure_email_log_sheet()
        with fresh_reads():
            values = ws.get_all_values()
    except Exception:
        return None
    if not values:
        return False
    mapping = _canonical_header_map(values[0], EMAIL_LOG_COLUMNS)
    index_of = {name: index for index, name in mapping.items()}
    type_i, status_i, related_i = index_of.get("Email_Type"), index_of.get("Status"), index_of.get("Related_ID")
    if type_i is None or status_i is None or related_i is None:
        return False
    wanted_type = str(email_type).strip().upper()
    wanted_id = str(related_id).strip()
    wanted_date = _normalize_date_string(wanted_id) if re.fullmatch(r"[\d./\- ]+", wanted_id) else ""
    for row in values[1:]:
        def cell(i):
            return str(row[i]).strip() if i < len(row) else ""
        if cell(type_i).upper() != wanted_type or cell(status_i).upper() not in {"SENT", "SUCCESS", "OK"}:
            continue
        stored = cell(related_i)
        if stored == wanted_id:
            return True
        if wanted_date and _normalize_date_string(stored) == wanted_date:
            return True
    return False


def _previous_workday(value):
    day = pd.Timestamp(value).normalize() - pd.Timedelta(days=1)
    while day.weekday() >= 5:
        day -= pd.Timedelta(days=1)
    return day


def _safe_restore_login_session():
    """Never let a task save/rerun remove the authenticated mobile session."""
    user = _session_user()
    if user:
        st.session_state["authenticated"] = True
        st.session_state["user"] = user


def _combined_technicians_with_activity(target_day):
    """Collect technicians with activity from the single ALL_ACTIVITIES source."""
    target = pd.Timestamp(target_day).normalize()
    found_names, found_ids = set(), set()
    # Never report people as missing from incomplete data: the import of the
    # latest Forms / Work Ticket entries must succeed first.
    sync_result = sync_all_activities(force=True)
    if sync_result.get("status") not in ("ok", "fresh"):
        raise RuntimeError("ALL_ACTIVITIES sync failed: " + "; ".join(map(str, sync_result.get("errors", [])))[:300])
    load_all_activities.clear()
    acts = load_all_activities()
    if not acts.empty:
        dates = parse_mixed_datetime_series(acts["Work_Date"]).dt.normalize()
        rows = acts[dates == target]
        found_names.update(rows["Technician_Name"].dropna().astype(str).str.strip().tolist())
        found_ids.update(rows["Technician_ID"].dropna().astype(str).str.strip().str.upper().tolist())
    return {n for n in found_names if n}, {i for i in found_ids if i}


def run_missing_work_time_check(force=False):
    """Check the previous workday after 11:00 Belgrade time and send one alert only."""
    now = datetime.now(ZoneInfo("Europe/Belgrade"))
    if not force and now.hour < 11:
        return {"status": "before_11"}

    # Do not report every technician as missing until the unified activity
    # database has completed its controlled one-time initialization.
    try:
        activity_status = get_all_activities_status()
        if not activity_status.get("initialized"):
            return {"status": "activity_db_not_initialized"}
    except Exception as exc:
        return {"status": "activity_status_error", "error": str(exc)}

    target_day = _previous_workday(now.date())
    related_id = target_day.strftime("%d.%m.%Y")
    already = _email_log_has_success("MISSING_TIME", related_id)
    if already is None:
        return {"status": "email_log_unavailable", "date": related_id}
    if already:
        return {"status": "already_sent", "date": related_id}

    tech_df, _ = load_technicians_master()
    if tech_df.empty:
        return {"status": "no_technicians"}
    active = tech_df[
        tech_df["Active"].apply(_yes_value)
        & ~tech_df["Supervisor"].apply(_yes_value)
    ].copy()
    try:
        names_with_entry, ids_with_entry = _combined_technicians_with_activity(target_day)
    except Exception as exc:
        return {"status": "activity_load_error", "date": related_id, "error": str(exc)}
    normalized_names = {_normalize_name_key(x) for x in names_with_entry}

    missing_names = []
    for _, row in active.iterrows():
        tech_id = str(row.get("Technician_ID", "")).strip().upper()
        name = str(row.get("Technician_Name", "")).strip()
        if not name:
            continue
        has_entry = (tech_id and tech_id in ids_with_entry) or (_normalize_name_key(name) in normalized_names)
        if not has_entry:
            missing_names.append(name)

    if not missing_names:
        return {"status": "all_complete", "date": related_id}

    # Write first; e-mail is still sent if rows already existed from a manual check.
    log_missing_technician_dates(missing_names, target_day)
    result = send_missing_time_email(missing_names, target_day)
    return {"status": "sent" if result.get("sent", 0) else "not_sent", "date": related_id, "missing": missing_names, "email": result}


def send_bn_missing_email(missing_pairs, alert_day):
    recipients = get_notification_recipients("Receive_BN_Email")
    day_txt = pd.Timestamp(alert_day).strftime("%d.%m.%Y")
    if not recipients:
        return {"sent": 0, "failed": 0, "skipped": "No BN recipients", "errors": []}
    lines = [f"- {project} / {machine}" for project, machine in missing_pairs]
    subject = f"Missing BN alert: {day_txt}"
    body = (
        f"BN entry is missing for {day_txt}.\n\n"
        "Machines without BN entry:\n" + "\n".join(lines)
        + "\n\nThis is an automatic notification from Lianbo Project Performance Hub."
    )
    return send_email_notification("BN_MISSING", recipients, subject, body, day_txt)


def run_missing_bn_check(force=False):
    now=datetime.now(ZoneInfo("Europe/Belgrade")); today=pd.Timestamp(now.date())
    if today.weekday()>=5:return {"status":"weekend"}
    if not force and now.hour<11:return {"status":"before_11"}
    related_id=today.strftime("%d.%m.%Y")
    already = _email_log_has_success("BN_MISSING", related_id)
    if already is None:
        return {"status": "email_log_unavailable", "date": related_id}
    if already:
        return {"status":"already_sent","date":related_id}
    try: sync_bn_forms_to_records(); master=load_bn_machines(); rec=load_bn_records()
    except Exception as exc:return {"status":"load_error","error":str(exc)}
    active=master[master["Active"].apply(_yes_value)]
    expected={(str(r.Project).strip(),str(r.Machine).strip(),str(r.Machine_ID).strip()) for r in active.itertuples()}
    if rec.empty: completed=set()
    else:
        d=parse_mixed_datetime_series(rec["Date"]).dt.normalize()
        completed=set(rec.loc[d.eq(today),"Machine_ID"].astype(str))
    missing=sorted((p,m) for p,m,mid in expected if mid not in completed)
    if not missing:return {"status":"all_complete","date":related_id}
    result=send_bn_missing_email(missing,today)
    return {"status":"sent" if result.get("sent",0) else "not_sent","date":related_id,"missing":missing,"email":result}


def run_open_task_reminder_check(force=False):
    """Send one weekday reminder after 11:00 for every task that is not closed."""
    now = datetime.now(ZoneInfo("Europe/Belgrade"))
    today = pd.Timestamp(now.date())
    if today.weekday() >= 5:
        return {"status": "weekend"}
    if not force and now.hour < 11:
        return {"status": "before_11"}

    related_id = today.strftime("%d.%m.%Y")
    already = _email_log_has_success("TASK_REMINDER", related_id)
    if already is None:
        return {"status": "email_log_unavailable", "date": related_id}
    if already:
        return {"status": "already_sent", "date": related_id}

    tasks_df, errors = load_tasks_data()
    if errors:
        return {"status": "load_error", "errors": errors}
    if tasks_df.empty:
        return {"status": "no_tasks", "date": related_id}

    status = tasks_df["Status"].astype(str).str.strip().str.upper()
    open_tasks = tasks_df[~status.isin(["CLOSED", "COMPLETED"])].copy()
    if open_tasks.empty:
        return {"status": "all_closed", "date": related_id}

    result = send_task_reminder_email(open_tasks, today)
    return {
        "status": "sent" if result.get("sent", 0) else "not_sent",
        "date": related_id,
        "open_tasks": len(open_tasks),
        "email": result,
    }


def run_automatic_notification_checks():
    """Run lightweight checks once per session window; EMAIL_LOG prevents duplicates."""
    now = datetime.now(ZoneInfo("Europe/Belgrade"))
    last = st.session_state.get("automatic_checks_last_run")
    if last:
        try:
            if (now - last).total_seconds() < 600:
                return
        except Exception:
            last = None
    st.session_state["automatic_checks_last_run"] = now
    try:
        st.session_state["missing_work_time_check_result"] = run_missing_work_time_check()
    except Exception as exc:
        st.session_state["missing_work_time_check_result"] = {"status": "error", "error": str(exc)}
    try:
        st.session_state["missing_bn_check_result"] = run_missing_bn_check()
    except Exception as exc:
        st.session_state["missing_bn_check_result"] = {"status": "error", "error": str(exc)}
    try:
        st.session_state["open_task_reminder_result"] = run_open_task_reminder_check()
    except Exception as exc:
        st.session_state["open_task_reminder_result"] = {"status": "error", "error": str(exc)}
    try:
        st.session_state["bn_deviation_batch_result"] = run_bn_deviation_batch_check()
    except Exception as exc:
        st.session_state["bn_deviation_batch_result"] = {"status": "error", "error": str(exc)}
    try:
        st.session_state["weekly_management_email_result"] = run_weekly_management_email()
    except Exception as exc:
        st.session_state["weekly_management_email_result"] = {"status": "error", "error": str(exc)}


def _identity_value(column, value):
    text = str(value or "").strip()
    if column in {"Task_ID", "Activity_ID", "Assigned_Technician_ID"}:
        return text.upper()
    if column == "Assigned_To":
        return _normalize_name_key(text)
    return text.casefold()


def _task_identity(record):
    task_id = str(record.get("Task_ID", "") or "").strip()
    if task_id:
        return {"Task_ID": task_id}
    identity = {
        "Assigned_Technician_ID": record.get("Assigned_Technician_ID", ""),
        "Assigned_To": record.get("Assigned_To", ""),
        "Task_Title": record.get("Task_Title", ""),
    }
    if str(record.get("Created_At", "") or "").strip():
        identity["Created_At"] = record.get("Created_At", "")
    return {key: value for key, value in identity.items() if str(value or "").strip()}


def _activity_identity(record):
    activity_id = str(record.get("Activity_ID", "") or "").strip()
    if activity_id:
        return {"Activity_ID": activity_id}
    fields = [
        "Task_ID", "Assigned_Technician_ID", "Assigned_To", "Task_Title",
        "Start_Date", "Start_Time", "End_Date", "End_Time",
    ]
    return {
        column: record.get(column, "")
        for column in fields
        if str(record.get(column, "") or "").strip()
    }


def _resolve_live_record(records, identity, record_label):
    if not identity:
        raise ValueError(f"{record_label} nema stabilan identitet; upis je zaustavljen radi bezbednosti.")
    matches = [
        record for record in records
        if all(
            _identity_value(column, record.get(column, "")) == _identity_value(column, value)
            for column, value in identity.items()
        )
    ]
    if len(matches) != 1:
        raise ValueError(
            f"{record_label} nije jednoznačno pronađen u najnovijim podacima "
            f"({len(matches)} podudaranja). Osveži stranicu i pokušaj ponovo."
        )
    return matches[0]


def _batch_update_sheet_records(sheet_name, changes, required_columns, *, live_context=None):
    """Resolve stable identities live, then write all requested cells in one API call."""
    if live_context is None:
        live_context = _live_sheet_records(sheet_name, required_columns)
    ws, headers, records = live_context
    batch = []
    resolved_rows = []
    for change in changes:
        live_record = _resolve_live_record(records, change.get("identity", {}), sheet_name)
        resolved_row = int(live_record["_row"])
        resolved_rows.append(resolved_row)
        updates = change.get("updates", {})
        for col_name, value in updates.items():
            col_idx = _find_header_col(headers, col_name)
            if col_idx is not None:
                col_letter = _column_number_to_letter(col_idx)
                batch.append({"range": f"{col_letter}{resolved_row}", "values": [[_gs_safe_value(value)]]})
        live_record.update(updates)
    if batch:
        ws.batch_update(batch, value_input_option="USER_ENTERED")
    return resolved_rows


def _update_sheet_cells(sheet_name, row_number, updates, required_columns, *, identity, live_context=None):
    """Compatibility wrapper for a single identity-verified record update."""
    rows = _batch_update_sheet_records(
        sheet_name,
        [{"identity": identity, "updates": updates}],
        required_columns,
        live_context=live_context,
    )
    return rows[0] if rows else int(row_number)


def _delete_sheet_rows(sheet_name, row_numbers, ws=None):
    """Delete already live-resolved Google Sheet rows in one batch."""
    clean_rows = sorted({int(r) for r in row_numbers if str(r).strip()}, reverse=True)
    if not clean_rows:
        return 0
    ws = ws or _get_kpi_worksheet(sheet_name)
    return _delete_worksheet_rows_batch(ws, clean_rows)


def delete_work_ticket_and_related_activity(task_row):
    """Delete exactly one live-resolved task and only activities linked by Task_ID."""
    migrate_work_ticket_ids()
    task_context = _live_sheet_records(TASKS_SHEET_NAME, TASK_REQUIRED_COLUMNS)
    task_ws, _, live_tasks = task_context
    live_task = _resolve_live_record(live_tasks, _task_identity(task_row), "TASKS task")
    task_id = str(live_task.get("Task_ID", "") or "").strip()

    activity_ws, _, live_activities = _live_sheet_records(
        TASK_ACTIVITY_SHEET_NAME, TASK_ACTIVITY_REQUIRED_COLUMNS
    )
    related = [
        activity for activity in live_activities
        if task_id and str(activity.get("Task_ID", "") or "").strip() == task_id
    ]
    link_key = _task_link_key(live_task)
    skipped_legacy = sum(
        1 for activity in live_activities
        if not str(activity.get("Task_ID", "") or "").strip()
        and _task_link_key(activity) == link_key
    )
    deleted_activities = _delete_sheet_rows(
        TASK_ACTIVITY_SHEET_NAME,
        [activity["_row"] for activity in related],
        ws=activity_ws,
    )
    deleted_tasks = _delete_sheet_rows(
        TASKS_SHEET_NAME, [live_task["_row"]], ws=task_ws
    )
    clear_work_ticket_cache()
    clear_all_activity_sync_state()
    return deleted_tasks, deleted_activities, skipped_legacy


def clear_work_ticket_cache():
    """Clear only Work Ticket caches; do not clear the whole application cache."""
    load_tasks_data.clear()
    load_task_activity_data.clear()


def _parse_task_datetime(start_date_value, time_value):
    d = parse_mixed_datetime(start_date_value)
    t = parse_time_value(time_value)
    if pd.isna(d) or t is None:
        return None
    return datetime.combine(d.date(), t)


def _valid_task_end(start_dt, end_dt):
    """Return a valid end datetime, treating an earlier same-day time as overnight."""
    if start_dt is None or end_dt is None:
        return None
    if end_dt < start_dt and end_dt.date() == start_dt.date():
        end_dt += timedelta(days=1)
    return end_dt if end_dt > start_dt else None


def _status_from_task_dates(task_row):
    """Derive the task master status from TASKS date/time fields.

    TASKS.Status remains the single source of truth for Kanban. This helper is used
    only to repair/normalize legacy rows where start/end fields exist but Status was
    not updated correctly. TASK_ACTIVITY is never used as a status source.
    """
    current_status = str(task_row.get("Status", "") or "").strip()
    current_upper = current_status.upper()
    if current_upper in ["CLOSED", "COMPLETED", "CANCELLED"]:
        return "Completed" if current_upper == "COMPLETED" else current_status

    start_dt = _parse_task_datetime(task_row.get("Start_Date", ""), task_row.get("Start_Time", ""))
    end_date_value = task_row.get("End_Date", "") or task_row.get("Start_Date", "")
    end_dt = _parse_task_datetime(end_date_value, task_row.get("End_Time", ""))

    if _valid_task_end(start_dt, end_dt) is not None:
        return "Completed"
    if start_dt is not None:
        return "In Progress"
    return "Open"


def sync_task_master_statuses(max_updates=50):
    """Repair TASKS.Status before Kanban rendering.

    Fixes cases where a task has start/end times in TASKS but still appears as
    In Progress/Open. This keeps Kanban aligned with TASKS while preserving the
    decision that TASK_ACTIVITY contains history only, not task status.
    """
    try:
        if st.session_state.get("_task_status_sync_done"):
            return 0
        tasks_df, errors = load_tasks_data()
        if errors or tasks_df.empty:
            return 0

        updates_done = 0
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        task_live_context = _live_sheet_records(TASKS_SHEET_NAME, TASK_REQUIRED_COLUMNS)
        for _, task in tasks_df.iterrows():
            desired_status = _status_from_task_dates(task)
            current_status = str(task.get("Status", "") or "Open").strip() or "Open"
            if desired_status.upper() != current_status.upper():
                update_values = {"Status": desired_status}
                if desired_status.upper() == "COMPLETED":
                    if not str(task.get("Closed_By", "") or "").strip():
                        update_values["Closed_By"] = str(task.get("Assigned_To", "") or _current_user_display_name())
                    if not str(task.get("Closed_At", "") or "").strip():
                        # Prefer task end date/time as close timestamp where possible.
                        end_date_value = task.get("End_Date", "") or task.get("Start_Date", "")
                        end_dt = _parse_task_datetime(end_date_value, task.get("End_Time", ""))
                        update_values["Closed_At"] = end_dt.strftime("%Y-%m-%d %H:%M:%S") if end_dt else now_str
                _update_sheet_cells(
                    TASKS_SHEET_NAME,
                    int(task["_row"]),
                    update_values,
                    TASK_REQUIRED_COLUMNS,
                    identity=_task_identity(task),
                    live_context=task_live_context,
                )
                updates_done += 1
                if updates_done >= max_updates:
                    break
        if updates_done:
            clear_work_ticket_cache()
        st.session_state["_task_status_sync_done"] = True
        return updates_done
    except Exception:
        return 0


def _calc_minutes(start_date_value, start_time_value, end_time_value):
    start_dt = _parse_task_datetime(start_date_value, start_time_value)
    end_dt = _parse_task_datetime(start_date_value, end_time_value)
    end_dt = _valid_task_end(start_dt, end_dt)
    if start_dt is None or end_dt is None:
        return 0.0
    return round((end_dt - start_dt).total_seconds() / 60, 2)


def _parse_task_datetime_with_end_date(date_value, time_value):
    return _parse_task_datetime(date_value, time_value)


def _calc_minutes_with_dates(start_date_value, start_time_value, end_date_value, end_time_value):
    start_dt = _parse_task_datetime_with_end_date(start_date_value, start_time_value)
    end_dt = _parse_task_datetime_with_end_date(end_date_value, end_time_value)
    end_dt = _valid_task_end(start_dt, end_dt)
    if start_dt is None or end_dt is None:
        return 0.0
    return round((end_dt - start_dt).total_seconds() / 60, 2)


def _parse_required_date_text(value, field_name):
    """Accept every common way people type a date on a phone or PC.

    23.10.2026, 23.10.2026. (Serbian trailing dot), 23. 10. 2026., 23/10/2026,
    23-10-2026, 23.10.26, 2026-10-23. Earlier only three exact formats were
    accepted, so a trailing dot or a space silently rejected a correct entry.
    """
    txt = str(value or "").strip()
    if not txt:
        return None, f"{field_name} is required."
    parsed = parse_date_value(txt)
    if pd.isna(parsed):
        return None, f"{field_name}: datum '{txt}' nije prepoznat. Primer: 23.10.2026"
    parsed_date = parsed.date()
    if not (date(2020, 1, 1) <= parsed_date <= date.today() + timedelta(days=366)):
        return None, f"{field_name}: datum {parsed_date.strftime('%d.%m.%Y')} je van dozvoljenog opsega."
    return parsed_date, ""


def _parse_optional_date_text(value, field_name):
    txt = str(value or "").strip()
    if not txt:
        return None, ""
    return _parse_required_date_text(txt, field_name)


def _parse_required_time_text(value, field_name):
    """Accept 8:30, 08:30, 8.30, 8,30, 8h30, 830, 8 and 8:30:00."""
    txt = str(value or "").strip().replace(",", ":")
    if not txt:
        return None, f"{field_name} is required."
    parsed = parse_time_value(txt)
    if parsed is None:
        return None, f"{field_name}: vreme '{txt}' nije prepoznato. Primer: 08:30"
    return parsed.replace(second=0, microsecond=0), ""


def _parse_optional_time_text(value, field_name):
    txt = str(value or "").strip()
    if not txt:
        return None, ""
    return _parse_required_time_text(txt, field_name)


def _validate_task_time_input(start_date_text, start_time_text, end_date_text="", end_time_text=""):
    """Validate optional task time entry.

    Rules:
    - Start Time requires Start Date.
    - End Time requires End Date and Start Time.
    - End Date requires End Time and Start Date.
    - End datetime must be after Start datetime.
    """
    errors = []
    sd_txt = str(start_date_text or "").strip()
    st_txt = str(start_time_text or "").strip()
    ed_txt = str(end_date_text or "").strip()
    et_txt = str(end_time_text or "").strip()

    if not any([sd_txt, st_txt, ed_txt, et_txt]):
        return {"has_start": False, "has_end": False, "errors": [], "start_date": None, "start_time": None, "end_date": None, "end_time": None, "calc_min": 0}

    # Only a date without any time is not a work entry (the form pre-fills
    # today's date); treat it as "no time entered" instead of crashing later.
    if sd_txt and not st_txt and not et_txt and not ed_txt:
        return {"has_start": False, "has_end": False, "errors": [], "start_date": None, "start_time": None, "end_date": None, "end_time": None, "calc_min": 0}
    if sd_txt and ed_txt and not st_txt and not et_txt:
        return {"has_start": False, "has_end": False, "errors": [], "start_date": None, "start_time": None, "end_date": None, "end_time": None, "calc_min": 0}

    # People normally type only the end time for work finished the same day.
    # The end date defaults to the start date (the overnight rule below still
    # moves 22:00 -> 02:00 to the next day).
    if et_txt and not ed_txt and sd_txt:
        ed_txt = sd_txt

    if sd_txt and not st_txt:
        errors.append("Start Time is mandatory when Start Date is entered.")
    if st_txt and not sd_txt:
        errors.append("Start Date is mandatory when Start Time is entered.")
    if et_txt and not ed_txt:
        errors.append("End Date is mandatory when End Time is entered.")
    if et_txt and not st_txt:
        errors.append("Start Time is mandatory when End Time is entered.")
    if ed_txt and not et_txt:
        errors.append("End Time is mandatory when End Date is entered.")
    if ed_txt and not sd_txt:
        errors.append("Start Date is mandatory when End Date is entered.")

    start_date = start_time = end_date = end_time = None
    if sd_txt:
        start_date, err = _parse_required_date_text(sd_txt, "Start Date")
        if err: errors.append(err)
    if st_txt:
        start_time, err = _parse_required_time_text(st_txt, "Start Time")
        if err: errors.append(err)
    if ed_txt:
        end_date, err = _parse_required_date_text(ed_txt, "End Date")
        if err: errors.append(err)
    if et_txt:
        end_time, err = _parse_required_time_text(et_txt, "End Time")
        if err: errors.append(err)

    has_start = bool(sd_txt or st_txt)
    has_end = bool(ed_txt or et_txt)
    calc_min = 0
    if not errors and has_start and has_end:
        start_dt = datetime.combine(start_date, start_time)
        end_dt = datetime.combine(end_date, end_time)
        end_dt = _valid_task_end(start_dt, end_dt)
        if end_dt is None:
            errors.append("End Date/Time must be after Start Date/Time.")
        elif (end_dt - start_dt) > timedelta(hours=16):
            errors.append(
                f"Aktivnost traje {round((end_dt - start_dt).total_seconds() / 3600, 1)} h. "
                "Proveri početak i kraj (moguća zamena vremena)."
            )
        else:
            end_date = end_dt.date()
            end_time = end_dt.time().replace(second=0, microsecond=0)
            calc_min = round((end_dt - start_dt).total_seconds() / 60, 2)

    return {"has_start": has_start, "has_end": has_end, "errors": errors, "start_date": start_date, "start_time": start_time, "end_date": end_date, "end_time": end_time, "calc_min": calc_min}


def _task_priority_column(headers):
    for candidate in ["Task_Priority", "Priority", "Task_Duration"]:
        if any(_norm_sheet_col(h) == _norm_sheet_col(candidate) for h in headers):
            return candidate
    return "Task_Duration"


@st.cache_data(ttl=3600)
def get_task_process_options():
    """Return the same work categories used in KPI Process charts/forms.

    Work Tickets uses the KPI work-category list, not OEE process/machine
    process names. This keeps the task assignment dropdown aligned with
    the KPI Process donut chart categories such as Proizvodnja, Proces
    održavanje, Projekti, Kvalitet and Papirologija (Liste).
    """
    fallback = ["Proizvodnja", "Proces održavanje", "Projekti", "Kvalitet", "Papirologija (Liste)"]
    try:
        # Only reads the categories. A full synchronization here made the first
        # Work Tickets page load of every session wait for several Google reads.
        kpi_raw = load_all_activities()
        category_col = "Process" if "Process" in kpi_raw.columns else None
        if category_col is not None:
            opts = kpi_raw[category_col].dropna().astype(str).str.strip().unique().tolist()
            opts = [x for x in opts if x and x.lower() not in ["nan", "none"] and x != PROCESS_DOWNTIME_CATEGORY]
            merged = sorted(set(opts) | set(fallback), key=str.casefold)
            if merged:
                return merged
    except Exception as exc:
        st.session_state["_work_ticket_process_warning"] = f"{type(exc).__name__}: {exc}"
    return fallback


def _normalize_name_key(value):
    """Normalizes technician names for reliable lookup between selectbox and sheet rows.

    Case, diacritics (also đ -> dj), extra spaces and word order are ignored, so
    "Nikolić Bojan" and "bojan nikolic" are the same person.
    """
    return person_name_key(value)


def _get_technician_email_map():
    """Return email map and active technician display names.

    Kept for backwards compatibility with existing code. New code should use
    _get_technician_lookup().
    """
    tech_df, _ = load_technicians_master()
    if tech_df.empty:
        return {}, []
    active_mask = tech_df["Active"].apply(_yes_value)
    tech_df = tech_df[active_mask].copy()
    names = tech_df["Technician_Name"].astype(str).str.strip().tolist()
    email_map = {}
    for _, row in tech_df.iterrows():
        name = str(row.get("Technician_Name", "") or "").strip()
        email = str(row.get("Email", "") or "").strip()
        tech_id = str(row.get("Technician_ID", "") or "").strip().upper()
        if name:
            email_map[name] = email
            email_map[_normalize_name_key(name)] = email
        if tech_id:
            email_map[tech_id] = email
    return email_map, names


def _get_technician_lookup():
    """Build active technician lookup maps.

    Technician_ID is the primary link between Users and Work Tickets.
    Technician_Name remains only the user-visible label and fallback for old tasks.
    """
    tech_df, _ = load_technicians_master()
    empty = {
        "df": pd.DataFrame(),
        "id_to_name": {},
        "id_to_email": {},
        "name_to_id": {},
        "name_to_email": {},
        "options": [],
    }
    if tech_df.empty:
        return empty

    active_mask = tech_df["Active"].apply(_yes_value)
    tech_df = tech_df[active_mask].copy()

    id_to_name, id_to_email, name_to_id, name_to_email, options = {}, {}, {}, {}, []
    for _, row in tech_df.iterrows():
        tech_id = str(row.get("Technician_ID", "") or "").strip().upper()
        name = str(row.get("Technician_Name", "") or "").strip()
        email = str(row.get("Email", "") or "").strip()
        if not name:
            continue
        key = tech_id or name
        options.append(name)
        if tech_id:
            id_to_name[tech_id] = name
            id_to_email[tech_id] = email
        name_to_id[name] = tech_id
        name_to_id[_normalize_name_key(name)] = tech_id
        name_to_email[name] = email
        name_to_email[_normalize_name_key(name)] = email
    return {
        "df": tech_df,
        "id_to_name": id_to_name,
        "id_to_email": id_to_email,
        "name_to_id": name_to_id,
        "name_to_email": name_to_email,
        "options": options,
    }


def _get_current_user_technician_id():
    """Return Technician_ID assigned to the logged-in user in User&Password."""
    return str(_session_user().get("technician_id", "") or "").strip().upper()


def _get_current_user_technician_name():
    """Return current technician display name.

    Primary link: User&Password.Technician_ID -> Technicians.Technician_ID.
    Fallback remains Username/Full_Name for old user sheets.
    """
    try:
        lookup = _get_technician_lookup()
        tech_id = _get_current_user_technician_id()
        if tech_id and tech_id in lookup["id_to_name"]:
            return lookup["id_to_name"][tech_id]

        user = _session_user()
        username = str(user.get("username", "") or "").strip().casefold()
        full_name = str(user.get("full_name", "") or "").strip().casefold()
        tech_df = lookup["df"]
        if tech_df.empty:
            return ""

        if username and "Username" in tech_df.columns:
            match = tech_df[tech_df["Username"].astype(str).str.strip().str.casefold().eq(username)]
            if not match.empty:
                return str(match.iloc[0]["Technician_Name"]).strip()

        if full_name:
            match = tech_df[tech_df["Technician_Name"].astype(str).str.strip().str.casefold().eq(full_name)]
            if not match.empty:
                return str(match.iloc[0]["Technician_Name"]).strip()
    except Exception:
        return ""
    return ""


def _work_ticket_full_access():
    """True for roles that can see and manage all work tickets."""
    role = str(_session_user().get("role", "") or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "", role)
    return normalized in [
        "admin",
        "administrator",
        "projectmanager",
        "manager",
        "processengineer",
        "engineer",
    ]


def _tasks_match_logged_technician(tasks_df):
    """Boolean mask for tasks assigned to the logged technician.

    Uses Assigned_Technician_ID as primary key. Assigned_To name is only a fallback
    so already-created legacy rows remain visible.
    """
    if tasks_df is None or tasks_df.empty:
        return pd.Series([], dtype=bool)
    mask = pd.Series(False, index=tasks_df.index)
    tech_id = _get_current_user_technician_id()
    tech_name = _get_current_user_technician_name()
    if tech_id and "Assigned_Technician_ID" in tasks_df.columns:
        mask = mask | tasks_df["Assigned_Technician_ID"].astype(str).str.strip().str.upper().eq(tech_id)
    if tech_name and "Assigned_To" in tasks_df.columns:
        wanted_name = _normalize_name_key(tech_name)
        mask = mask | tasks_df["Assigned_To"].astype(str).map(_normalize_name_key).eq(wanted_name)
    return mask


def _filter_tasks_for_logged_user(tasks_df):
    """Technicians see only their own tasks; full-access roles see all tasks."""
    if tasks_df is None or tasks_df.empty or _work_ticket_full_access():
        return tasks_df
    return tasks_df[_tasks_match_logged_technician(tasks_df)].copy()


def _can_current_user_modify_task(task_row):
    """User can update/close own task. Full-access roles can modify all tasks."""
    if _work_ticket_full_access():
        return True
    tech_id = _get_current_user_technician_id()
    tech_name = _get_current_user_technician_name()
    task_tech_id = str(task_row.get("Assigned_Technician_ID", "") or "").strip().upper()
    task_assigned = str(task_row.get("Assigned_To", "") or "").strip()
    if tech_id and task_tech_id and tech_id == task_tech_id:
        return True
    if tech_name and task_assigned and _normalize_name_key(tech_name) == _normalize_name_key(task_assigned):
        return True
    return False

# =====================================================
# ADMINISTRATION MODULE - USERS / PASSWORDS / PERMISSIONS
# =====================================================

USER_REQUIRED_COLUMNS = [
    "Username", "Password", "Full_Name", "Role", "Active", "Email", "Technician_ID",
    *USER_ACCESS_COLUMNS,
    *USER_NOTIFICATION_COLUMNS,
]
PERMISSION_DEFAULT_COLUMNS = [
    "Role",
    # Operational modules
    "My_Tasks", "Work_Tickets", "Task",
    "BN_Entry", "BN_Module", "Bottleneck",
    "KPI_Process", "OEE", "Line_Verification",
    # KPI sub-permissions
    "Alerts", "Exports", "Reports",
    # System administration
    "Admin_panel", "Administration", "Settings",
]

def _get_auth_worksheet(possible_names):
    client = get_client()
    ws, _ = open_first_existing_worksheet(client, AUTH_SHEET_ID, possible_names)
    return ws

def _ensure_generic_headers(ws, required_columns):
    values = ws.get_all_values()
    if not values:
        ws.update("A1", [required_columns])
        return required_columns
    headers = [str(h).replace("\ufeff", "").replace("​", "").strip() for h in values[0]]
    changed = False
    norm_headers = [_norm_sheet_col(h) for h in headers]
    for col in required_columns:
        if _norm_sheet_col(col) not in norm_headers:
            headers.append(col)
            norm_headers.append(_norm_sheet_col(col))
            changed = True
    if changed:
        ws.update("A1", [headers])
    return headers

@st.cache_data(ttl=30)
def load_admin_users_data():
    try:
        ws = _get_auth_worksheet(USER_SHEET_NAMES)
        headers = _ensure_generic_headers(ws, USER_REQUIRED_COLUMNS)
        values = ws.get_all_values()
        rows = []
        for idx, row in enumerate(values[1:], start=2):
            item = {headers[i]: (row[i] if i < len(row) else "") for i in range(len(headers))}
            item["_row"] = idx
            rows.append(item)
        df = pd.DataFrame(rows)
        if df.empty:
            df = pd.DataFrame(columns=headers + ["_row"])
        df = clean_columns(df)
        for col in USER_REQUIRED_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        return df, []
    except Exception as e:
        return pd.DataFrame(columns=USER_REQUIRED_COLUMNS + ["_row"]), [f"User admin load error: {type(e).__name__}: {e}"]

@st.cache_data(ttl=30)
def load_admin_permissions_data():
    try:
        ws = _get_auth_worksheet(PERMISSION_SHEET_NAMES)
        headers = _ensure_generic_headers(ws, PERMISSION_DEFAULT_COLUMNS)
        values = ws.get_all_values()
        rows = []
        for idx, row in enumerate(values[1:], start=2):
            item = {headers[i]: (row[i] if i < len(row) else "") for i in range(len(headers))}
            item["_row"] = idx
            rows.append(item)
        df = pd.DataFrame(rows)
        if df.empty:
            df = pd.DataFrame(columns=headers + ["_row"])
        df = clean_columns(df)
        if "Role" not in df.columns:
            df["Role"] = ""
        return df, []
    except Exception as e:
        return pd.DataFrame(columns=PERMISSION_DEFAULT_COLUMNS + ["_row"]), [f"Permission admin load error: {type(e).__name__}: {e}"]

def _yes_no_from_bool(flag):
    return "YES" if bool(flag) else "NO"

def _normalise_yes_no(value):
    return "YES" if str(value).strip().upper() in ["YES", "Y", "DA", "TRUE", "1"] else "NO"

def _normalise_access_override(value):
    parsed = _parse_user_override(value)
    if parsed is None:
        return ""
    return "YES" if parsed else "NO"


@_live_reads
def save_admin_user(username, password, full_name, role, active, email, technician_id, existing_row=None, access_values=None, notification_values=None):
    username = str(username or "").strip()
    full_name = str(full_name or "").strip()
    if not username:
        raise ValueError("Username is required.")
    is_edit = existing_row is not None
    if not is_edit and not str(password or "").strip():
        raise ValueError("Password is required.")
    if not full_name:
        raise ValueError("Full name is required.")
    if not str(role or "").strip():
        raise ValueError("Role is required.")

    ws = _get_auth_worksheet(USER_SHEET_NAMES)
    headers = _ensure_generic_headers(ws, USER_REQUIRED_COLUMNS)
    values = ws.get_all_values()

    username_col = _find_header_col(headers, "Username") or 1
    full_name_col = _find_header_col(headers, "Full_Name") or 3

    target_username = username.casefold()
    target_full_name = full_name.casefold()

    # Resolve an edit against live data by immutable Username.  The cached row
    # number is only an edit-mode signal and is never trusted for writing.
    row_idx = None
    if is_edit:
        username_matches = []
        for idx, row in enumerate(values[1:], start=2):
            row_username = row[username_col - 1] if len(row) >= username_col else ""
            if str(row_username).strip().casefold() == target_username:
                username_matches.append(idx)
        if len(username_matches) != 1:
            raise ValueError(
                f"User '{username}' nije jednoznačno pronađen u najnovijim podacima. Osveži stranicu."
            )
        row_idx = username_matches[0]

    # Duplicate protection:
    # - Add mode: an existing Username or Full_Name is not allowed.
    # - Edit mode: the same row is allowed, but another row with the same Username/Full_Name is blocked.
    for idx, row in enumerate(values[1:], start=2):
        row_username = row[username_col - 1] if len(row) >= username_col else ""
        row_full_name = row[full_name_col - 1] if len(row) >= full_name_col else ""
        same_row = row_idx is not None and int(row_idx) == int(idx)
        if same_row:
            continue
        if str(row_username).strip().casefold() == target_username:
            raise ValueError(f"User with Username '{username}' already exists.")
        if str(row_full_name).strip().casefold() == target_full_name:
            raise ValueError(f"User with Full_Name '{full_name}' already exists.")

    if row_idx is None:
        row_idx = len(values) + 1

    technician_id = str(technician_id or "").strip().upper()
    if technician_id:
        tech_df, _ = load_technicians_master()
        if tech_df.empty or "Technician_ID" not in tech_df.columns:
            raise ValueError("Technicians sheet could not be loaded for Technician_ID validation.")
        valid_ids = set(tech_df["Technician_ID"].astype(str).str.strip().str.upper().tolist())
        if technician_id not in valid_ids:
            raise ValueError(f"Technician_ID '{technician_id}' does not exist in Technicians sheet.")

    row_values = {
        "Username": username,
        "Full_Name": full_name,
        "Role": str(role).strip(),
        "Active": _normalise_yes_no(active),
        "Email": str(email or "").strip(),
        "Technician_ID": technician_id,
    }
    if str(password or "").strip():
        row_values["Password"] = _hash_password(password)
    for col_name, value in (access_values or {}).items():
        if col_name in USER_ACCESS_COLUMNS:
            row_values[col_name] = _normalise_access_override(value)
    for col_name, value in (notification_values or {}).items():
        if col_name in USER_NOTIFICATION_COLUMNS:
            row_values[col_name] = _yes_no_from_bool(value)

    # One batch write instead of one Google API request for every user field.
    existing_values = values[row_idx - 1] if row_idx - 1 < len(values) else []
    output_row = [existing_values[i] if i < len(existing_values) else "" for i in range(len(headers))]
    for col_name, value in row_values.items():
        col_idx = _find_header_col(headers, col_name)
        if col_idx is not None:
            output_row[col_idx - 1] = _gs_safe_value(value)
    end_col = _column_number_to_letter(len(headers))
    ws.update(f"A{row_idx}:{end_col}{row_idx}", [output_row])
    return True

@_live_reads
def save_admin_role_permissions(role, permission_values, existing_row=None):
    role = str(role or "").strip()
    if not role:
        raise ValueError("Role is required.")
    ws = _get_auth_worksheet(PERMISSION_SHEET_NAMES)
    headers = _ensure_generic_headers(ws, PERMISSION_DEFAULT_COLUMNS)
    values = ws.get_all_values()
    wanted = role.casefold()
    row_idx = int(existing_row) if existing_row else None
    if row_idx is None:
        for idx, row in enumerate(values[1:], start=2):
            row_role = row[0] if len(row) >= 1 else ""
            if str(row_role).strip().casefold() == wanted:
                row_idx = idx
                break
    if row_idx is None:
        row_idx = len(values) + 1
    existing_values = values[row_idx - 1] if row_idx - 1 < len(values) else []
    output_row = [existing_values[i] if i < len(existing_values) else "" for i in range(len(headers))]
    role_col = _find_header_col(headers, "Role") or 1
    output_row[role_col - 1] = role
    for col_name, value in permission_values.items():
        col_idx = _find_header_col(headers, col_name)
        if col_idx is not None:
            output_row[col_idx - 1] = _yes_no_from_bool(value)
    end_col = _column_number_to_letter(len(headers))
    ws.update(f"A{row_idx}:{end_col}{row_idx}", [output_row])
    return True

def render_administration_module():
    require_module_access("Administration", ["Admin_panel", "Administration"])
    can_admin_edit = can_edit_module("Administration")
    if not can_admin_edit:
        st.info("Read-only access: možeš da vidiš korisnike i prava, ali ne možeš da ih menjaš.")
    tab_names = ["Users & Passwords", "Role Permissions", "OEE podešavanja"] + (["🔒 IWON"] if can_see_iwon() else [])
    admin_tabs = st.tabs(tab_names)
    user_tab, permission_tab, settings_tab = admin_tabs[0], admin_tabs[1], admin_tabs[2]
    with settings_tab:
        render_oee_settings_admin(can_admin_edit)
    if len(admin_tabs) > 3:
        with admin_tabs[3]:
            render_iwon_admin()
    # IWON targets moved to the private IWON page (OEE module, IWON_USERS only).
    with user_tab:
        users_df, user_errors = load_admin_users_data()
        permissions_df, perm_errors = load_admin_permissions_data()
        if user_errors:
            st.error("; ".join(user_errors))
        if perm_errors:
            st.warning("; ".join(perm_errors))
        roles = sorted([r for r in permissions_df.get("Role", pd.Series(dtype=str)).astype(str).str.strip().unique().tolist() if r])
        if not roles:
            roles = ["admin", "User"]
        mode = st.radio("Mode", ["Edit existing user", "Add new user"], horizontal=True, key="admin_user_mode", label_visibility="collapsed")
        selected_user = ""
        current = pd.Series(dtype=object)
        if mode == "Edit existing user":
            user_options = sorted([u for u in users_df.get("Username", pd.Series(dtype=str)).astype(str).str.strip().tolist() if u])
            if user_options:
                selected_user = st.selectbox("Select user", user_options, key="admin_user_select")
                match = users_df[users_df["Username"].astype(str).str.strip() == selected_user]
                if not match.empty:
                    current = match.iloc[0]
            else:
                st.info("No users found.")
        form_suffix = re.sub(r"[^A-Za-z0-9_]+", "_", f"{mode}_{selected_user}").strip("_") or "new_user"
        with st.form(f"user_admin_form_{form_suffix}", clear_on_submit=False):
            c1, c2, c3 = st.columns(3)
            with c1:
                username = st.text_input("Username", value=str(current.get("Username", "") or ""), disabled=(mode == "Edit existing user"))
                password = st.text_input(
                    "Password",
                    value="",
                    type="password",
                    placeholder="Leave blank to keep current password" if mode == "Edit existing user" else "New password",
                    help="Existing passwords are never displayed. Leave blank during edit to keep the current password.",
                )
            with c2:
                full_name = st.text_input("Full_Name", value=str(current.get("Full_Name", "") or ""))
                current_role = str(current.get("Role", roles[0] if roles else "") or "")
                role_index = roles.index(current_role) if current_role in roles else 0
                role = st.selectbox("Role", roles, index=role_index)
            with c3:
                active_raw = str(current.get("Active", "YES") or "YES").strip().upper()
                active = st.selectbox("Active", ["YES", "NO"], index=0 if active_raw not in ["NO", "N", "NE", "FALSE", "0"] else 1)
                email = st.text_input("Email", value=str(current.get("Email", "") or ""))
                technician_id = st.text_input("Technician_ID", value=str(current.get("Technician_ID", "") or ""), help="Required for technician users who need to see, update and close their own Work Tickets.")

            st.markdown("### Individual tab access")
            st.caption("Role default koristi pravo role. Allowed/Blocked važi samo za ovog korisnika, bez obzira na rolu.")
            access_values = {}
            access_labels = ["Role default", "Allowed", "Blocked"]
            for module_key, module_label in USER_MODULE_ACCESS:
                view_col = f"View_{module_key}"
                edit_col = f"Edit_{module_key}"
                view_raw = str(current.get(view_col, "") or "").strip().upper()
                edit_raw = str(current.get(edit_col, "") or "").strip().upper()
                view_default = 1 if _parse_user_override(view_raw) is True else 2 if _parse_user_override(view_raw) is False else 0
                edit_default = 1 if _parse_user_override(edit_raw) is True else 2 if _parse_user_override(edit_raw) is False else 0
                label_col, view_ui_col, edit_ui_col = st.columns([2, 1, 1])
                with label_col:
                    st.markdown(f"**{module_label}**")
                with view_ui_col:
                    view_choice = st.selectbox("View", access_labels, index=view_default, key=f"user_{form_suffix}_{view_col}")
                with edit_ui_col:
                    edit_choice = st.selectbox("Edit / input", access_labels, index=edit_default, key=f"user_{form_suffix}_{edit_col}")
                access_values[view_col] = "" if view_choice == "Role default" else "YES" if view_choice == "Allowed" else "NO"
                access_values[edit_col] = "" if edit_choice == "Role default" else "YES" if edit_choice == "Allowed" else "NO"

            st.markdown("### Notifications")
            notification_values = {}
            notification_labels = {
                "Receive_Task_Email": "Task assignment/completion e-mails",
                "Receive_Task_Reminder": "Open task reminders",
                "Receive_Missing_Time_Email": "Missing work-time alerts",
                "Receive_BN_Email": "BN alerts and deviations",
            }
            notification_cols = st.columns(2)
            for i, (column_name, label) in enumerate(notification_labels.items()):
                current_flag = _parse_user_override(current.get(column_name, "")) is True
                with notification_cols[i % 2]:
                    notification_values[column_name] = st.checkbox(
                        label, value=current_flag, key=f"user_{form_suffix}_{column_name}"
                    )

            saved = st.form_submit_button("Save User", type="primary", use_container_width=True, disabled=not can_admin_edit)
        if saved:
            try:
                save_admin_user(
                    username, password, full_name, role, active, email, technician_id,
                    current.get("_row", None) if mode == "Edit existing user" and not current.empty else None,
                    access_values=access_values,
                    notification_values=notification_values,
                )
                load_admin_users_data.clear()
                load_users_and_permissions.clear()
                st.success("User saved successfully.")
            except Exception as e:
                st.error("User could not be saved.")
                st.write(e)
        st.markdown("### Current users")
        if not users_df.empty:
            display_users = users_df[[c for c in ["Username", "Full_Name", "Role", "Active", "Email", "Technician_ID", *USER_ACCESS_COLUMNS, *USER_NOTIFICATION_COLUMNS] if c in users_df.columns]].copy()
            st.dataframe(display_users, use_container_width=True)
    with permission_tab:
        permissions_df, perm_errors = load_admin_permissions_data()
        if perm_errors:
            st.error("; ".join(perm_errors))
        permission_headers = PERMISSION_DEFAULT_COLUMNS if permissions_df.empty else [c for c in permissions_df.columns if c not in ["_row", "Role_norm"]]
        permission_cols = [c for c in permission_headers if c != "Role"]
        mode = st.radio("Permission mode", ["Edit existing role", "Add new role"], horizontal=True, key="admin_perm_mode", label_visibility="collapsed")
        selected_role = ""
        current_perm = pd.Series(dtype=object)
        role_options = sorted([r for r in permissions_df.get("Role", pd.Series(dtype=str)).astype(str).str.strip().tolist() if r]) if not permissions_df.empty else []
        if mode == "Edit existing role":
            if role_options:
                selected_role = st.selectbox("Select role", role_options, key="admin_perm_role_select")
                match = permissions_df[permissions_df["Role"].astype(str).str.strip() == selected_role]
                if not match.empty:
                    current_perm = match.iloc[0]
            else:
                st.info("No roles found.")
        role_name_default = selected_role if mode == "Edit existing role" else ""
        st.markdown("### Permissions")
        role_name = st.text_input("Role", value=role_name_default, disabled=(mode == "Edit existing role"), key=f"admin_role_name_{mode}_{selected_role}")
        st.caption("YES = visible and available. NO = completely hidden and blocked for this role.")
        permission_values = {}
        cols = st.columns(3)
        for i, col_name in enumerate(permission_cols):
            current_value = str(current_perm.get(col_name, "NO") if not current_perm.empty else "NO").strip().upper()
            default_flag = current_value in ["YES", "Y", "DA", "TRUE", "1"]
            with cols[i % 3]:
                permission_values[col_name] = st.checkbox(col_name, value=default_flag, key=f"perm_{col_name}_{mode}_{selected_role}")
        if st.button("Save Role Permissions", type="primary", use_container_width=True, key="save_role_permissions", disabled=not can_admin_edit):
            try:
                save_admin_role_permissions(role_name, permission_values, current_perm.get("_row", None) if mode == "Edit existing role" and not current_perm.empty else None)
                load_admin_permissions_data.clear()
                load_users_and_permissions.clear()
                st.success("Role permissions saved successfully.")
            except Exception as e:
                st.error("Permissions could not be saved.")
                st.write(e)
        st.markdown("### Current role permissions")
        if not permissions_df.empty:
            display_perm = permissions_df[[c for c in permissions_df.columns if c != "_row"]].copy()
            st.dataframe(display_perm, use_container_width=True)




def _merge_overlap_segments(segments):
    """Return merged datetime segments so overlap minutes are subtracted once."""
    if not segments:
        return []
    merged = []
    for start_dt, end_dt in sorted(segments, key=lambda item: (item[0], item[1])):
        if not merged or start_dt > merged[-1][1]:
            merged.append([start_dt, end_dt])
        elif end_dt > merged[-1][1]:
            merged[-1][1] = end_dt
    return merged


def _apply_enva_overlap_rules(intervals):
    """Apply ENVA once per merged overlap segment and return copied records."""
    result = [dict(item) for item in intervals]
    result.sort(key=lambda item: (item["start"], item["end"], item.get("row", 0)))
    for current in result:
        overlaps = []
        for later in result:
            if later["start"] <= current["start"]:
                continue
            overlap_start = max(current["start"], later["start"])
            overlap_end = min(current["end"], later["end"])
            if overlap_end > overlap_start:
                overlaps.append((overlap_start, overlap_end))
        merged = _merge_overlap_segments(overlaps)
        overlap_minutes = sum(
            (end_dt - start_dt).total_seconds() / 60 for start_dt, end_dt in merged
        )
        enva_minutes = ENVA_MINUTES * len(merged)
        current["effective"] = max(current["calc"] - overlap_minutes - enva_minutes, 0)
    return result


def recalculate_enva_for_technician_day(assigned_to, start_date_value):
    """Recalculate effective minutes for all completed activities for one technician/day.

    Rule: when a later interval overlaps an earlier interval, reduce the earlier interval by
    overlap minutes + ENVA_MINUTES. The later interval keeps its calculated duration.
    """
    migrate_work_ticket_ids()
    activity_df, errors = load_task_activity_data()
    if errors or activity_df.empty:
        return

    date_norm = parse_mixed_datetime(start_date_value)
    if pd.isna(date_norm):
        return
    date_key = date_norm.strftime("%d.%m.%Y")

    df = activity_df.copy()
    df["_date_key"] = parse_mixed_datetime_series(df["Start_Date"]).dt.strftime("%d.%m.%Y")
    wanted_person = _normalize_name_key(assigned_to)
    mask = (
        df["Assigned_To"].astype(str).map(_normalize_name_key).eq(wanted_person)
        & df["_date_key"].eq(date_key)
    )
    day_df = df[mask].copy()
    if day_df.empty:
        return

    intervals = []
    for _, r in day_df.iterrows():
        end_date_value = r.get("End_Date", "") or r.get("Start_Date", "")
        st_dt = _parse_task_datetime(r.get("Start_Date", ""), r.get("Start_Time", ""))
        en_dt = _parse_task_datetime(end_date_value, r.get("End_Time", ""))
        en_dt = _valid_task_end(st_dt, en_dt)
        if st_dt is None or en_dt is None:
            continue
        calc = (en_dt - st_dt).total_seconds() / 60
        intervals.append({
            "row": int(r["_row"]),
            "record": r.to_dict(),
            "start": st_dt,
            "end": en_dt,
            "calc": calc,
            "effective": calc,
        })

    # Equal-start records have no objective "later" activity. Treating exact
    # duplicates as later previously zeroed an otherwise valid interval.
    intervals = _apply_enva_overlap_rules(intervals)

    activity_live_context = _live_sheet_records(
        TASK_ACTIVITY_SHEET_NAME, TASK_ACTIVITY_REQUIRED_COLUMNS
    )
    activity_changes = [
        {
            "identity": _activity_identity(item["record"]),
            "updates": {
                "Calculated_Duration": round(item["calc"], 2),
                "Effective_Duration": round(item["effective"], 2),
            },
        }
        for item in intervals
    ]
    if activity_changes:
        _batch_update_sheet_records(
            TASK_ACTIVITY_SHEET_NAME,
            activity_changes,
            TASK_ACTIVITY_REQUIRED_COLUMNS,
            live_context=activity_live_context,
        )

    # Refresh only Work Ticket data and update totals by stable Task_ID.
    clear_work_ticket_cache()
    activity_df, _ = load_task_activity_data()
    task_df, _ = load_tasks_data()
    if activity_df.empty or task_df.empty:
        return
    completed = activity_df[
        activity_df["Assigned_To"].astype(str).map(_normalize_name_key).eq(wanted_person)
    ].copy()
    relevant_tasks = task_df[
        task_df["Assigned_To"].astype(str).map(_normalize_name_key).eq(wanted_person)
    ].copy()
    task_changes = []
    for _, task in relevant_tasks.iterrows():
        task_id = str(task.get("Task_ID", "") or "").strip()
        if task_id:
            task_acts = completed[
                completed["Task_ID"].astype(str).str.strip().eq(task_id)
            ].copy()
        else:
            same_link_tasks = relevant_tasks[
                relevant_tasks.apply(lambda row: _task_link_key(row) == _task_link_key(task), axis=1)
            ]
            if len(same_link_tasks) != 1:
                continue
            task_acts = completed[
                completed.apply(lambda row: _task_link_key(row) == _task_link_key(task), axis=1)
            ].copy()
        if task_acts.empty:
            continue
        calc_total = pd.to_numeric(task_acts["Calculated_Duration"], errors="coerce").fillna(0).sum()
        eff_total = pd.to_numeric(task_acts["Effective_Duration"], errors="coerce").fillna(0).sum()
        task_changes.append({
            "identity": _task_identity(task),
            "updates": {
                "Calculated_Duration": round(calc_total, 2),
                "Effective_Duration": round(eff_total, 2),
            },
        })
    if task_changes:
        _batch_update_sheet_records(
            TASKS_SHEET_NAME,
            task_changes,
            TASK_REQUIRED_COLUMNS,
            live_context=_live_sheet_records(TASKS_SHEET_NAME, TASK_REQUIRED_COLUMNS),
        )


def _task_activity_lookup_keys(row):
    """Return ID and name keys so legacy activities without Technician_ID still match."""
    task_id = str(row.get("Task_ID", "") or "").strip()
    tech_id = str(row.get("Assigned_Technician_ID", "") or "").strip().upper()
    assigned = _normalize_name_key(row.get("Assigned_To", ""))
    title = str(row.get("Task_Title", "") or "").strip().casefold()
    keys = []
    if task_id:
        keys.append(f"TASK:{task_id}")
    if tech_id:
        keys.append(f"ID:{tech_id}||{title}")
    if assigned:
        keys.append(f"NAME:{assigned}||{title}")
    return keys


def _build_task_activity_time_bounds(activity_df):
    """Build first-start / last-end lookup for closed-task card fallback.

    This makes historical completed tasks show timestamps immediately even if they
    were closed before v9.4.2, when TASKS did not persist the activity start/end.
    """
    bounds = {}
    if activity_df is None or activity_df.empty:
        return bounds
    for _, row in activity_df.iterrows():
        keys = _task_activity_lookup_keys(row)
        if not keys:
            continue
        start_dt = _parse_task_datetime(row.get("Start_Date", ""), row.get("Start_Time", ""))
        end_date_value = row.get("End_Date", "") or row.get("Start_Date", "")
        end_dt = _parse_task_datetime(end_date_value, row.get("End_Time", ""))
        for key in keys:
            current = bounds.setdefault(key, {"start": None, "end": None})
            if start_dt is not None and (current["start"] is None or start_dt < current["start"]):
                current["start"] = start_dt
            if end_dt is not None and (current["end"] is None or end_dt > current["end"]):
                current["end"] = end_dt
    return bounds


def _format_task_card_datetime(date_value, time_value):
    """Format a task timestamp for compact Kanban display."""
    date_text = ""
    parsed_date = parse_mixed_datetime(date_value)
    if not pd.isna(parsed_date):
        date_text = parsed_date.strftime("%d.%m.%Y")
    time_text = str(time_value or "").strip()
    if time_text:
        parsed_time = pd.to_datetime(time_text, errors="coerce")
        if not pd.isna(parsed_time):
            time_text = parsed_time.strftime("%H:%M")
    return " ".join(x for x in [date_text, time_text] if x).strip()


def render_task_card(task_row, idx_suffix, activity_bounds=None):
    """Display a Work Ticket card without Start/Stop buttons.

    Task card displays assignment and accumulated duration. Time entries are added later through Task Activity.
    Admin users can delete the task regardless of status.
    """
    status = str(task_row.get("Status", "Open") or "Open").strip()
    title = str(task_row.get("Task_Title", "") or "").strip()
    assigned = str(task_row.get("Assigned_To", "") or "").strip()
    assigned_tech_id = str(task_row.get("Assigned_Technician_ID", "") or "").strip()
    priority = str(task_row.get("Task_Duration", task_row.get("Task_Priority", task_row.get("Priority", ""))) or "").strip()
    process = str(task_row.get("Process", "") or "").strip()
    calc = task_row.get("Calculated_Duration", "")
    eff = task_row.get("Effective_Duration", "")
    completed = status.upper() in ["CLOSED", "COMPLETED"]
    started_at = _format_task_card_datetime(task_row.get("Start_Date", ""), task_row.get("Start_Time", ""))
    finished_at = _format_task_card_datetime(task_row.get("End_Date", ""), task_row.get("End_Time", ""))
    if completed and activity_bounds and (not started_at or not finished_at):
        fallback = {}
        for lookup_key in _task_activity_lookup_keys(task_row):
            if lookup_key in activity_bounds:
                fallback = activity_bounds[lookup_key]
                break
        if not started_at and fallback.get("start") is not None:
            started_at = fallback["start"].strftime("%d.%m.%Y %H:%M")
        if not finished_at and fallback.get("end") is not None:
            finished_at = fallback["end"].strftime("%d.%m.%Y %H:%M")
    time_line = ""
    if completed and (started_at or finished_at):
        time_line = (
            '<div class="ticket-line">'
            f'Started: {html.escape(started_at or "—")} · '
            f'Finished: {html.escape(finished_at or "—")}'
            '</div>'
        )
    elif started_at:
        time_line = f'<div class="ticket-line">Početak: <b>{html.escape(started_at)}</b></div>'

    prio_upper = priority.upper()
    prio_color = {"LOW": "#22C55E", "MEDIUM": "#F59E0B", "HIGH": "#F97316", "CRITICAL": "#EF4444"}.get(prio_upper, "#64748B")
    prio_status = {"LOW": "ok", "MEDIUM": "warn", "HIGH": "warn", "CRITICAL": "alarm"}.get(prio_upper, "")
    status_chip = {"OPEN": ("Otvoren", "info"), "IN PROGRESS": ("U toku", "warn"), "COMPLETED": ("Završen", "ok"),
                   "CLOSED": ("Završen", "ok")}.get(status.upper(), (status, ""))

    def _minutes_text(value):
        try:
            minutes = float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return "—"
        if minutes <= 0:
            return "—"
        return f"{int(minutes // 60)} h {int(round(minutes % 60)):02d} min" if minutes >= 60 else f"{int(round(minutes))} min"

    meta = ui.chip(status_chip[0], status_chip[1]) + (ui.chip(priority or "—", prio_status, dot=True) if priority else "") + (ui.chip(process) if process else "")
    st.markdown(
        f'<div class="ticket-card" style="--prio-color:{prio_color}">'
        f'<div class="ticket-title">{html.escape(title)}</div>'
        f'<div class="ticket-meta">{meta}</div>'
        f'<div class="ticket-line">👤 <b>{html.escape(assigned)}</b>{(" · " + html.escape(assigned_tech_id)) if assigned_tech_id else ""}</div>'
        f'<div class="ticket-line">⏱ Trajanje: <b>{_minutes_text(calc)}</b> · efektivno <b>{_minutes_text(eff)}</b></div>'
        f"{time_line}"
        "</div>",
        unsafe_allow_html=True,
    )

    is_admin = str(_session_user().get("role", "")).strip().lower() == "admin"
    if is_admin and can_edit_module("Work Tickets"):
        confirm_key = f"confirm_delete_task_{idx_suffix}"
        confirm_delete = st.checkbox("Confirm delete", key=confirm_key)
        if st.button("🗑️ Delete task", key=f"delete_task_btn_{idx_suffix}", disabled=not confirm_delete, use_container_width=True):
            deleted_tasks, deleted_activities, skipped_legacy = delete_work_ticket_and_related_activity(task_row)
            st.success(f"Task obrisan. Obrisano taskova: {deleted_tasks}, aktivnosti: {deleted_activities}.")
            if skipped_legacy:
                st.warning(
                    f"{skipped_legacy} starih aktivnosti bez jednoznačnog Task_ID nije obrisano radi zaštite podataka."
                )
            st.rerun()



def render_create_my_task_panel():
    """Allow a technician/user without full access to create a task only for himself/herself.

    Create My Task is available directly from Kanban. Assignment fields are hidden and
    resolved from the logged-in user's Technician_ID. Optional time entry controls the
    task master status:
    - no time -> Open
    - start date/time only -> In Progress
    - start + end date/time -> Completed
    """
    if _work_ticket_full_access() or not can_edit_module("Work Tickets"):
        return

    current_tech_id = _get_current_user_technician_id()
    current_tech_name = _get_current_user_technician_name()
    lookup = _get_technician_lookup()
    process_options = get_task_process_options()

    if not current_tech_id or not current_tech_name:
        st.error("Tvoj korisnik nije povezan sa Technician_ID. Admin mora da popuni Technician_ID u User&Password sheet-u.")
        return

    current_email = (
        lookup["id_to_email"].get(str(current_tech_id).strip().upper(), "")
        or str(_session_user().get("email", "") or "").strip()
    )

    st.markdown("### My Tasks")

    if "show_create_my_task_form" not in st.session_state:
        st.session_state["show_create_my_task_form"] = False

    if st.button("＋\nAdd task", key="create_my_task_toggle", help="Create a new task for yourself"):
        st.session_state["show_create_my_task_form"] = not st.session_state["show_create_my_task_form"]

    if st.session_state.get("show_create_my_task_form", False):
        st.caption("Kreiraš task samo za sebe. Assigned To, e-mail i Technician ID aplikacija popunjava automatski.")
        st.info(f"Assigned to: {current_tech_name} ({current_tech_id})")

        start_immediately = st.checkbox(
            "Start immediately / unesi vreme odmah",
            value=bool(st.session_state.get("self_task_start_now", False)),
            key="self_task_start_now",
        )

        _consume_form_reset("create_my_task", [
            "self_task_title", "self_task_description", "self_task_start_time_text",
            "self_task_end_date", "self_task_end_time_text",
        ])
        with st.form("create_my_task_form", clear_on_submit=False):
            process = st.selectbox("Process", process_options, key="self_task_process")
            title = st.text_input("Task Title", key="self_task_title")
            priority = st.selectbox("Priority", ["Low", "Medium", "High", "Critical"], index=1, key="self_task_priority")
            description = st.text_area("Description / Note", value="", key="self_task_description")

            if start_immediately:
                st.caption("Ako uneseš samo početak, task ide u In Progress. Ako uneseš početak i kraj, task se odmah zatvara kao Completed.")
                d1_col, t1_col = st.columns(2)
                with d1_col:
                    start_date_text = st.text_input("Start Date", value=date.today().strftime("%d.%m.%Y"), key="self_task_start_date")
                with t1_col:
                    start_time_text = st.text_input("Start Time", value="08:00", key="self_task_start_time_text", help="Format: HH:MM")
                d2_col, t2_col = st.columns(2)
                with d2_col:
                    end_date_text = st.text_input("End Date", value="", key="self_task_end_date", help="Format: DD.MM.YYYY")
                with t2_col:
                    end_time_text = st.text_input("End Time", value="", key="self_task_end_time_text", help="Format: HH:MM")
            else:
                start_date_text = start_time_text = end_date_text = end_time_text = ""

            submitted = st.form_submit_button("Create My Task", use_container_width=True)

        if submitted:
            if not str(title or "").strip():
                st.error("Task nije kreiran. Task Title je obavezan.")
                return

            time_info = _validate_task_time_input(start_date_text, start_time_text, end_date_text, end_time_text) if start_immediately else {"has_start": False, "has_end": False, "errors": [], "calc_min": 0}
            if time_info.get("errors"):
                st.error("Task nije kreiran. " + " ".join(time_info["errors"]))
                return

            task_title = str(title).strip()
            if str(description or "").strip():
                task_title = f"{task_title} - {str(description).strip()}"
            _create_task_entry(
                assigned_technician_id=current_tech_id,
                assigned_to=current_tech_name,
                assigned_email=current_email,
                process=process,
                task_title=task_title,
                priority=priority,
                time_info=time_info,
                form_name="create_my_task",
            )

def _recent_duplicate_task(assigned_to, task_title, window_seconds=180):
    """True when the same task for the same person was created a moment ago (double tap)."""
    try:
        _, _, live_tasks = _live_sheet_records(TASKS_SHEET_NAME, TASK_REQUIRED_COLUMNS)
    except Exception:
        return False
    wanted_person = _normalize_name_key(assigned_to)
    wanted_title = str(task_title or "").strip().casefold()
    now_dt = datetime.now()
    for record in live_tasks:
        if _normalize_name_key(record.get("Assigned_To", "")) != wanted_person:
            continue
        if str(record.get("Task_Title", "")).strip().casefold() != wanted_title:
            continue
        created = parse_mixed_datetime(record.get("Created_At", ""))
        if pd.notna(created) and abs((now_dt - created.to_pydatetime()).total_seconds()) <= window_seconds:
            return True
    return False


def _create_task_entry(*, assigned_technician_id, assigned_to, assigned_email, process, task_title, priority, time_info, form_name, reset_keys=None):
    """Create a task (and its activity when an end time is given) for both flows.

    The task row is the critical write; any follow-up (activity, ENVA, e-mails)
    that fails is reported as a warning, never as if the task were not saved.
    """
    has_start = bool(time_info.get("has_start"))
    has_end = bool(time_info.get("has_end"))
    calc_min = float(time_info.get("calc_min", 0) or 0)
    start_date_str = time_info["start_date"].strftime("%d.%m.%Y") if has_start else ""
    start_time_str = time_info["start_time"].strftime("%H:%M") if has_start else ""
    end_date_str = time_info["end_date"].strftime("%d.%m.%Y") if has_end else ""
    end_time_str = time_info["end_time"].strftime("%H:%M") if has_end else ""
    task_status = "Completed" if has_end else "In Progress" if has_start else "Open"
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if _recent_duplicate_task(assigned_to, task_title):
        st.info("Isti task je upravo kreiran (dvostruki klik). Nije upisan dva puta.")
        return False

    try:
        headers = _ensure_sheet_headers(_get_kpi_worksheet(TASKS_SHEET_NAME), TASK_REQUIRED_COLUMNS)
        pr_col = _task_priority_column(headers)
    except Exception:
        pr_col = "Task_Priority"

    task_row = {
        "Task_ID": _new_task_id(),
        "Assigned_Technician_ID": assigned_technician_id,
        "Assigned_To": assigned_to,
        "Assigned_Email": assigned_email,
        "Process": process,
        "Task_Title": task_title,
        pr_col: priority,
        "Task_Priority": priority,
        "Status": task_status,
        "Start_Date": start_date_str,
        "Start_Time": start_time_str,
        "End_Date": end_date_str,
        "End_Time": end_time_str,
        "Calculated_Duration": calc_min,
        "Effective_Duration": calc_min,
        "Created_By": _current_user_display_name(),
        "Created_By_Email": _current_user_email(),
        "Created_At": now_str,
        "Closed_By": _current_user_display_name() if task_status == "Completed" else "",
        "Closed_At": now_str if task_status == "Completed" else "",
    }
    try:
        _append_dict_to_sheet(TASKS_SHEET_NAME, task_row, TASK_REQUIRED_COLUMNS)
    except Exception as exc:
        st.error(f"Task NIJE kreiran (Google Sheets greška). Pokušaj ponovo za minut. Detalj: {type(exc).__name__}: {exc}")
        return False

    warnings_after_save = []
    if has_end:
        activity_row = {
            "Activity_ID": _new_activity_id(),
            "Task_ID": task_row["Task_ID"],
            "Assigned_Technician_ID": assigned_technician_id,
            "Assigned_To": assigned_to,
            "Task_Title": task_title,
            "Start_Date": start_date_str,
            "Start_Time": start_time_str,
            "End_Date": end_date_str,
            "End_Time": end_time_str,
            "Calculated_Duration": calc_min,
            "Effective_Duration": calc_min,
        }
        try:
            _append_dict_to_sheet(TASK_ACTIVITY_SHEET_NAME, activity_row, TASK_ACTIVITY_REQUIRED_COLUMNS)
        except Exception as exc:
            warnings_after_save.append(
                f"Vreme rada NIJE upisano ({type(exc).__name__}). Unesi ga u Task Activity za ovaj task."
            )
        else:
            clear_work_ticket_cache()
            try:
                recalculate_enva_for_technician_day(assigned_to, start_date_str)
            except Exception as exc:
                warnings_after_save.append(f"ENVA preračun će se ponoviti kasnije ({type(exc).__name__}).")

    try:
        email_result = send_task_created_email(task_row) or {}
        if task_status == "Completed":
            send_task_completed_email(task_row, completed_by=_current_user_display_name(), completed_at=now_str, duration_min=calc_min)
        if email_result.get("failed", 0) > 0:
            warnings_after_save.append("E-mail nije poslat: " + "; ".join(email_result.get("errors", []))[:300])
    except Exception as exc:
        warnings_after_save.append(f"E-mail nije poslat ({type(exc).__name__}).")

    clear_work_ticket_cache()
    _safe_restore_login_session()
    warning = ("Zadatak JE kreiran. " + " ".join(warnings_after_save)) if warnings_after_save else ""
    _request_form_reset(form_name, "Zadatak je uspešno kreiran.", warning)
    st.rerun()
    return True


def _consume_form_reset(form_name, widget_keys):
    """Clear widget values on the run AFTER a successful save.

    Forms used clear_on_submit=True, which also wiped everything when the entry
    was rejected, so people had to retype and often gave up. Now values are kept
    on error and cleared only after a confirmed save.
    """
    flag = f"_reset_form_{form_name}"
    if st.session_state.pop(flag, False):
        for key in widget_keys:
            st.session_state.pop(key, None)
    message = st.session_state.pop(f"_form_success_{form_name}", None)
    if message:
        st.success(message)
    warning = st.session_state.pop(f"_form_warning_{form_name}", None)
    if warning:
        st.warning(warning)


def _request_form_reset(form_name, success_message, warning_message=""):
    st.session_state[f"_reset_form_{form_name}"] = True
    st.session_state[f"_form_success_{form_name}"] = success_message
    if warning_message:
        st.session_state[f"_form_warning_{form_name}"] = warning_message


def _activity_already_saved(task_id, start_date_str, start_time_str, end_date_str, end_time_str):
    """Protect against a double tap on Save (two identical rows)."""
    try:
        _, _, live_activities = _live_sheet_records(TASK_ACTIVITY_SHEET_NAME, TASK_ACTIVITY_REQUIRED_COLUMNS)
    except Exception:
        return False
    for record in live_activities:
        if str(record.get("Task_ID", "")).strip() != str(task_id).strip():
            continue
        same_start = _parse_task_datetime(record.get("Start_Date", ""), record.get("Start_Time", "")) == _parse_task_datetime(start_date_str, start_time_str)
        end_date_value = record.get("End_Date", "") or record.get("Start_Date", "")
        same_end = _parse_task_datetime(end_date_value, record.get("End_Time", "")) == _parse_task_datetime(end_date_str, end_time_str)
        if same_start and same_end:
            return True
    return False


def _save_task_activity_entry(*, assigned_to, selected_task, selected_task_id, task_title, time_info, close_after, is_admin, technician_lookup):
    """Save one Task Activity row; follow-up steps can never hide a saved entry."""
    start_date_str = time_info["start_date"].strftime("%d.%m.%Y")
    start_time_str = time_info["start_time"].strftime("%H:%M")
    end_date_str = time_info["end_date"].strftime("%d.%m.%Y")
    end_time_str = time_info["end_time"].strftime("%H:%M")
    calc_min = float(time_info.get("calc_min", 0) or 0)
    activity_technician_id = (
        str(selected_task.get("Assigned_Technician_ID", "") or "").strip().upper()
        if selected_task is not None else ""
    ) or technician_lookup["name_to_id"].get(str(assigned_to).strip(), "") or technician_lookup["name_to_id"].get(_normalize_name_key(assigned_to), "") or _get_current_user_technician_id()

    if _activity_already_saved(selected_task_id, start_date_str, start_time_str, end_date_str, end_time_str):
        st.info("Ova aktivnost je već sačuvana (isti task, početak i kraj). Nije upisana dva puta.")
        return False

    activity_row = {
        "Activity_ID": _new_activity_id(),
        "Task_ID": selected_task_id,
        "Assigned_Technician_ID": activity_technician_id,
        "Assigned_To": assigned_to,
        "Task_Title": task_title.strip(),
        "Start_Date": start_date_str,
        "Start_Time": start_time_str,
        "End_Date": end_date_str,
        "End_Time": end_time_str,
        "Calculated_Duration": calc_min,
        "Effective_Duration": calc_min,
    }
    try:
        _append_dict_to_sheet(TASK_ACTIVITY_SHEET_NAME, activity_row, TASK_ACTIVITY_REQUIRED_COLUMNS)
    except Exception as exc:
        st.error(f"Aktivnost NIJE upisana (Google Sheets greška). Pokušaj ponovo za minut. Detalj: {type(exc).__name__}: {exc}")
        return False
    clear_work_ticket_cache()

    warnings_after_save = []
    try:
        recalculate_enva_for_technician_day(assigned_to, start_date_str)
    except Exception as exc:
        warnings_after_save.append(f"ENVA preračun će se ponoviti kasnije ({type(exc).__name__}).")
    clear_work_ticket_cache()

    # TASKS.Status is the single source of truth. TASK_ACTIVITY stores history only.
    try:
        tasks_df_latest, _ = load_tasks_data()
        matching_tasks = tasks_df_latest[tasks_df_latest["Task_ID"].astype(str).str.strip().eq(selected_task_id)]
        if not is_admin:
            matching_tasks = matching_tasks[_tasks_match_logged_technician(matching_tasks)]
        new_status = "Completed" if close_after else "In Progress"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        activity_start_dt = datetime.combine(time_info["start_date"], time_info["start_time"])
        activity_end_dt = datetime.combine(time_info["end_date"], time_info["end_time"])
        task_live_context = _live_sheet_records(TASKS_SHEET_NAME, TASK_REQUIRED_COLUMNS)
        for _, tr in matching_tasks.iterrows():
            if not _can_current_user_modify_task(tr):
                continue
            update_values = {"Status": new_status}
            # Keep the task master start as the earliest recorded start.
            existing_start_dt = _parse_task_datetime(tr.get("Start_Date", ""), tr.get("Start_Time", ""))
            if existing_start_dt is None or activity_start_dt < existing_start_dt:
                update_values["Start_Date"] = activity_start_dt.strftime("%d.%m.%Y")
                update_values["Start_Time"] = activity_start_dt.strftime("%H:%M")
            if close_after:
                # Closing timestamp shown on the Kanban card comes from the actual work entry,
                # not from the moment the Save button happened to be clicked.
                existing_end_date = tr.get("End_Date", "") or tr.get("Start_Date", "")
                existing_end_dt = _parse_task_datetime(existing_end_date, tr.get("End_Time", ""))
                if existing_end_dt is None or activity_end_dt > existing_end_dt:
                    update_values["End_Date"] = activity_end_dt.strftime("%d.%m.%Y")
                    update_values["End_Time"] = activity_end_dt.strftime("%H:%M")
                update_values["Closed_By"] = _current_user_display_name()
                update_values["Closed_At"] = now_str
            _update_sheet_cells(
                TASKS_SHEET_NAME,
                int(tr["_row"]),
                update_values,
                TASK_REQUIRED_COLUMNS,
                identity=_task_identity(tr),
                live_context=task_live_context,
            )
            if close_after:
                tr_dict = tr.to_dict()
                tr_dict.update(update_values)
                try:
                    send_task_completed_email(tr_dict, completed_by=_current_user_display_name(), completed_at=now_str, duration_min=calc_min)
                except Exception as exc:
                    warnings_after_save.append(f"E-mail o završetku nije poslat ({type(exc).__name__}).")
    except Exception as exc:
        warnings_after_save.append(f"Status taska nije osvežen: {type(exc).__name__}: {exc}")
    clear_work_ticket_cache()
    _safe_restore_login_session()
    message = "Aktivnost je upisana. Trajanje i ENVA korekcija su preračunati."
    warning = ("Aktivnost JE sačuvana. " + " ".join(warnings_after_save)) if warnings_after_save else ""
    _request_form_reset("task_activity", message, warning)
    st.rerun()
    return True


def render_work_tickets_module():

    require_module_access("Work Tickets", ["My_Tasks", "Work_Tickets", "Task", "Tasks"])
    can_edit_tickets = can_edit_module("Work Tickets")
    try:
        id_migration = migrate_work_ticket_ids()
        if is_admin_user(_session_user()) and id_migration.get("ambiguous_legacy_activities", 0):
            st.warning(
                f"{id_migration['ambiguous_legacy_activities']} starih aktivnosti nije automatski povezano "
                "jer postoji više taskova istog tehničara sa istim naslovom. Podaci nisu menjani niti brisani."
            )
    except Exception as exc:
        can_edit_tickets = False
        st.error(
            "Zaštitna migracija Task_ID/Activity_ID trenutno nije uspela. Modul je prebačen u read-only "
            f"da ne bi došlo do upisa u pogrešan red: {type(exc).__name__}: {exc}"
        )
    if not can_edit_tickets:
        st.info("Read-only access: taskovi i istorija su vidljivi, ali kreiranje, unos vremena, promene i brisanje nisu dozvoljeni.")

    # Optimized navigation: Streamlit tabs render all tab contents, so they caused
    # unnecessary Google Sheets reads. Radio navigation renders only the selected view.
    can_manage_all_tickets = _work_ticket_full_access() and can_edit_tickets
    available_views = ["Kanban Board", "Task Activity"]
    if can_manage_all_tickets:
        available_views.insert(1, "New Task")
    if st.session_state.get("work_tickets_view") not in available_views:
        st.session_state["work_tickets_view"] = available_views[0]

    view_labels = {"Kanban Board": "🗂 Kanban tabla", "New Task": "➕ Novi zadatak", "Task Activity": "⏱ Unos vremena rada"}
    view = st.radio(
        "Work Tickets view",
        available_views,
        horizontal=True,
        label_visibility="collapsed",
        key="work_tickets_view",
        format_func=lambda option: view_labels.get(option, option),
    )

    if view == "New Task":
        if not can_manage_all_tickets:
            st.warning("New Task je dostupan samo za Admin / Manager / Engineer role.")
            st.stop()
        st.subheader("New Task")
        st.caption("Admin / ovlašćeni korisnik može da dodeli task. Ako se odmah unese vreme, status se automatski određuje.")
        email_map, technician_options = _get_technician_email_map()
        technician_lookup = _get_technician_lookup()
        process_options = get_task_process_options()

        assigned_options = technician_options if technician_options else [""]
        previous_assigned_to = st.session_state.get("new_task_previous_assigned_to", "")
        assigned_to = st.selectbox("Assigned To", assigned_options, key="new_task_assigned_to")
        assigned_technician_id = technician_lookup["name_to_id"].get(str(assigned_to).strip(), "") or technician_lookup["name_to_id"].get(_normalize_name_key(assigned_to), "")
        auto_assigned_email = (
            technician_lookup["id_to_email"].get(str(assigned_technician_id).strip().upper(), "")
            or email_map.get(str(assigned_to).strip(), "")
            or email_map.get(_normalize_name_key(assigned_to), "")
        )
        if (str(assigned_to) != str(previous_assigned_to)) or ("new_task_assigned_email" not in st.session_state):
            st.session_state["new_task_assigned_email"] = auto_assigned_email
            st.session_state["new_task_previous_assigned_to"] = str(assigned_to)

        assigned_email = st.text_input(
            "Assigned Email",
            value=st.session_state.get("new_task_assigned_email", auto_assigned_email),
            key="new_task_assigned_email",
            help="Auto-filled from Technicians sheet. You can type it manually if it is missing."
        ).strip()

        add_activity_now = st.checkbox(
            "Unesi vreme rada odmah",
            value=bool(st.session_state.get("new_task_add_activity_now", False)),
            key="new_task_add_activity_now",
            help="Ako uneseš samo početak, task ide u In Progress. Ako uneseš početak i kraj, task ide u Completed."
        )

        _consume_form_reset("new_task", [
            "new_task_title", "new_task_start_time_text", "new_task_end_date", "new_task_end_time_text",
        ])
        with st.form("new_task_form", clear_on_submit=False):
            process = st.selectbox("Process", process_options, key="new_task_process")
            title = st.text_input("Task Title", key="new_task_title")
            priority = st.selectbox("Priority", ["Low", "Medium", "High", "Critical"], index=1, key="new_task_priority")

            if add_activity_now:
                d1_col, t1_col = st.columns(2)
                with d1_col:
                    new_start_date_text = st.text_input("Start Date", value=date.today().strftime("%d.%m.%Y"), key="new_task_start_date")
                with t1_col:
                    new_start_time_text = st.text_input("Start Time", value="08:00", key="new_task_start_time_text", help="Format: HH:MM")
                d2_col, t2_col = st.columns(2)
                with d2_col:
                    new_end_date_text = st.text_input("End Date", value="", key="new_task_end_date", help="Format: DD.MM.YYYY")
                with t2_col:
                    new_end_time_text = st.text_input("End Time", value="", key="new_task_end_time_text", help="Format: HH:MM")
            else:
                new_start_date_text = new_start_time_text = new_end_date_text = new_end_time_text = ""

            submitted = st.form_submit_button("Create Task", use_container_width=True)

        if submitted:
            if not assigned_to or not str(title or "").strip():
                st.error("Task nije kreiran. Assigned To i Task Title su obavezni.")
            else:
                time_info = _validate_task_time_input(new_start_date_text, new_start_time_text, new_end_date_text, new_end_time_text) if add_activity_now else {"has_start": False, "has_end": False, "errors": [], "calc_min": 0}
                if time_info.get("errors"):
                    st.error("Task nije kreiran. " + " ".join(time_info["errors"]))
                    return

                if not assigned_email:
                    st.warning("Assigned Email je prazan. Task će biti kreiran, ali e-mail notifikacija neće biti poslata za ovaj task.")

                _create_task_entry(
                    assigned_technician_id=assigned_technician_id,
                    assigned_to=assigned_to,
                    assigned_email=assigned_email,
                    process=process,
                    task_title=str(title).strip(),
                    priority=priority,
                    time_info=time_info,
                    form_name="new_task",
                )

    elif view == "Kanban Board":
        st.subheader("Kanban Board")
        if not _work_ticket_full_access() and can_edit_tickets:
            render_create_my_task_panel()
        tasks_df, task_errors = load_tasks_data()
        if task_errors:
            st.error("Ne mogu da učitam TASKS sheet. Ako je Google limit privremeno dostignut, sačekaj oko minut; aplikacija sada automatski usporava i ponavlja zahtev.")
            st.write(task_errors)
            st.stop()

        tasks_df = _filter_tasks_for_logged_user(tasks_df)

        if tasks_df.empty:
            if _work_ticket_full_access():
                st.info("Nema taskova. Kreiraj prvi task u delu New Task.")
            else:
                st.info("Nema taskova dodeljenih tvom korisniku. Možeš da kreiraš svoj task kroz Create My Task na Kanbanu.")
        else:
            # One cached activity read lets historical completed cards show their
            # real first-start and last-end even when old TASKS rows have empty time fields.
            activity_bounds = {}
            try:
                activity_for_cards, _ = load_task_activity_data()
                activity_bounds = _build_task_activity_time_bounds(activity_for_cards)
            except Exception:
                activity_bounds = {}

            status_upper_all = tasks_df["Status"].astype(str).str.strip().str.upper()
            open_count = int(status_upper_all.eq("OPEN").sum())
            progress_count = int(status_upper_all.eq("IN PROGRESS").sum())
            closed_count = int(status_upper_all.isin(["CLOSED", "COMPLETED"]).sum())
            total_minutes = pd.to_numeric(tasks_df["Calculated_Duration"].astype(str).str.replace(",", ".", regex=False), errors="coerce").fillna(0).sum()
            st.markdown(ui.kpi_grid([
                ui.kpi_card("Otvoreni", str(open_count), "", "info", "čekaju početak"),
                ui.kpi_card("U toku", str(progress_count), "", "warn" if progress_count else "neutral", "započeti zadaci"),
                ui.kpi_card("Završeni", str(closed_count), "", "ok", "ukupno"),
                ui.kpi_card("Evidentirano", ui.format_number(total_minutes / 60, 1), "h", "neutral", "zbir trajanja taskova"),
            ]), unsafe_allow_html=True)

            c_open, c_prog, c_closed = st.columns(3)
            columns = [("Open", c_open), ("In Progress", c_prog), ("Closed", c_closed)]
            column_titles = {"Open": ("Otvoreno", "#22D3EE"), "In Progress": ("U toku", "#F59E0B"), "Closed": ("Završeno", "#22C55E")}
            for status_name, col in columns:
                with col:
                    status_upper = tasks_df["Status"].astype(str).str.strip().str.upper()
                    if status_name.upper() == "CLOSED":
                        status_tasks = tasks_df[status_upper.isin(["CLOSED", "COMPLETED"])].copy()
                        # Newest finished first; long history goes into an expander.
                        status_tasks["_sort"] = status_tasks["Closed_At"].map(parse_mixed_datetime)
                        status_tasks = status_tasks.sort_values("_sort", ascending=False, na_position="last")
                    else:
                        status_tasks = tasks_df[status_upper.eq(status_name.upper())].copy()
                    title_text, title_color = column_titles[status_name]
                    st.markdown(
                        f'<div class="kanban-head" style="--kanban-color:{title_color}">'
                        f'<span class="kanban-title">{title_text}</span>'
                        f'<span class="kanban-count">{len(status_tasks)}</span></div>',
                        unsafe_allow_html=True,
                    )
                    if status_tasks.empty:
                        st.caption("Nema zadataka")
                    visible_limit = 12 if status_name == "Closed" else len(status_tasks)
                    for position, (_, task) in enumerate(status_tasks.iterrows()):
                        if position == visible_limit:
                            break
                        render_task_card(task, f"{status_name}_{int(task['_row'])}", activity_bounds=activity_bounds)
                    if len(status_tasks) > visible_limit:
                        with st.expander(f"Starijih završenih: {len(status_tasks) - visible_limit}"):
                            for _, task in status_tasks.iloc[visible_limit:].iterrows():
                                render_task_card(task, f"{status_name}_{int(task['_row'])}", activity_bounds=activity_bounds)

    else:
        st.subheader("Task Activity")
        st.caption("Ovde tehničar unosi stvarno vreme rada na već kreiranom tasku. Jedan task može imati više aktivnosti.")

        tasks_df, task_errors = load_tasks_data()
        if task_errors:
            st.error("Ne mogu da učitam TASKS sheet. Ako je Google limit privremeno dostignut, sačekaj oko minut; aplikacija sada automatski usporava i ponavlja zahtev.")
            st.write(task_errors)
            st.stop()

        email_map, technician_options = _get_technician_email_map()
        technician_lookup = _get_technician_lookup()
        tasks_df = _filter_tasks_for_logged_user(tasks_df)
        if tasks_df.empty:
            if _work_ticket_full_access():
                st.info("Nema kreiranih taskova. Prvo kreiraj task u New Task.")
            else:
                st.info("Nema taskova dodeljenih tvom korisniku.")
        elif not can_edit_tickets:
            st.info("Unos aktivnosti je isključen za ovog korisnika. Istorija aktivnosti je dostupna ispod.")
        else:
            is_admin = _work_ticket_full_access()
            current_user_technician = _get_current_user_technician_name()
            current_user_technician_id = _get_current_user_technician_id()
            if is_admin:
                activity_assigned_options = technician_options if technician_options else sorted(tasks_df["Assigned_To"].dropna().astype(str).unique().tolist())
                activity_assigned_disabled = False
            else:
                activity_assigned_options = [current_user_technician] if current_user_technician else [""]
                activity_assigned_disabled = True
                if not current_user_technician or not current_user_technician_id:
                    st.error("Tvoj korisnik nije povezan sa Technician_ID u User&Password sheet-u. Popuni Technician_ID za ovog korisnika.")

            # Technician and task are chosen OUTSIDE the form. Inside a Streamlit
            # form the task list did not refresh after changing the technician,
            # so the saved activity could be rejected ("Task Title je obavezan")
            # or attached to the wrong task.
            _consume_form_reset("task_activity", ["activity_start_time_text", "activity_end_time_text", "activity_close_after"])
            assigned_to = st.selectbox("Assigned To", activity_assigned_options, key="activity_assigned_to", disabled=activity_assigned_disabled)
            if is_admin:
                wanted_assignee = _normalize_name_key(assigned_to)
                assigned_tasks = tasks_df[
                    tasks_df["Assigned_To"].astype(str).map(_normalize_name_key).eq(wanted_assignee)
                    & ~tasks_df["Status"].astype(str).str.strip().str.upper().isin(["CLOSED", "COMPLETED", "CANCELLED"])
                ].copy()
            else:
                assigned_tasks = tasks_df[
                    _tasks_match_logged_technician(tasks_df)
                    & ~tasks_df["Status"].astype(str).str.strip().str.upper().isin(["CLOSED", "COMPLETED", "CANCELLED"])
                ].copy()
            task_option_map = {
                str(row.get("Task_ID", "") or "").strip(): row
                for _, row in assigned_tasks.iterrows()
                if str(row.get("Task_ID", "") or "").strip()
            }
            task_options = list(task_option_map)
            if not task_options:
                st.info("Nema otvorenih taskova za izabranog tehničara. Kreiraj task ili izaberi drugog tehničara.")
            selected_task_id = st.selectbox(
                "Task Title",
                task_options if task_options else [""],
                key=f"activity_task_id_{_norm_key(assigned_to) or 'none'}",
                format_func=lambda task_id: (
                    f"{str(task_option_map[task_id].get('Task_Title', '')).strip()} "
                    f"· {task_id[-8:]}"
                ) if task_id in task_option_map else "",
            )
            selected_task = task_option_map.get(selected_task_id)
            task_title = str(selected_task.get("Task_Title", "") or "").strip() if selected_task is not None else ""

            with st.form("task_activity_form", clear_on_submit=False):
                d1_col, t1_col = st.columns(2)
                with d1_col:
                    start_date_text = st.text_input("Start Date", value=date.today().strftime("%d.%m.%Y"), key="activity_start_date", help="Npr. 23.10.2026")
                with t1_col:
                    start_time_text = st.text_input("Start Time", value="08:00", key="activity_start_time_text", help="Npr. 08:00 ili 8.00")
                d2_col, t2_col = st.columns(2)
                with d2_col:
                    end_date_text = st.text_input("End Date", value=date.today().strftime("%d.%m.%Y"), key="activity_end_date", help="Prazno = isti dan kao Start Date")
                with t2_col:
                    end_time_text = st.text_input("End Time", value="08:30", key="activity_end_time_text", help="Npr. 08:30")
                close_after = st.checkbox("Close task after this activity", value=False, key="activity_close_after")
                submitted_activity = st.form_submit_button("Save Activity", use_container_width=True)

            if submitted_activity:
                if not assigned_to or not task_title or not selected_task_id:
                    st.error("Aktivnost nije upisana: izaberi tehničara i task.")
                else:
                    time_info = _validate_task_time_input(start_date_text, start_time_text, end_date_text, end_time_text)
                    if time_info.get("errors") or not time_info.get("has_end"):
                        st.error("Aktivnost nije upisana. " + " ".join(time_info.get("errors", []) or ["Start and End Date/Time are mandatory for activity."]))
                    else:
                        _save_task_activity_entry(
                            assigned_to=assigned_to,
                            selected_task=selected_task,
                            selected_task_id=selected_task_id,
                            task_title=task_title,
                            time_info=time_info,
                            close_after=close_after,
                            is_admin=is_admin,
                            technician_lookup=technician_lookup,
                        )

        st.divider()
        st.markdown("### Activity History")
        activity_df, activity_errors = load_task_activity_data()
        if activity_errors:
            st.error("Ne mogu da učitam TASK_ACTIVITY sheet.")
            st.write(activity_errors)
            st.stop()
        if activity_df.empty:
            st.info("Nema aktivnosti.")
        else:
            show = activity_df.drop(columns=["_row"], errors="ignore").copy()
            st.dataframe(show, use_container_width=True)

MODULE_GROUPS = [
    ("Rad", ["Work_Tickets"]),
    ("Analitika", ["Uprava", "KPI_Process", "OEE", "Bottleneck", "Line_Verification"]),
    ("Sistem", ["Administration"]),
]


def render_app_header():
    user = st.session_state.get("user", {}) or {}
    now_text = datetime.now(ZoneInfo("Europe/Belgrade")).strftime("%d.%m.%Y %H:%M")
    chips = [
        ui.chip(f"👤 {user.get('full_name', '')}") if user.get("full_name") else "",
        ui.chip(now_text),
        ui.chip(APP_VERSION, "info"),
    ]
    st.markdown(
        '<div class="app-header">'
        f'<img class="app-logo" src="data:image/png;base64,{APP_LOGO_BASE64}" />'
        '<div class="app-title-wrap">'
        '<div class="app-title">Lianbo Project Performance Hub</div>'
        '<div class="app-subtitle">Project Technology Department · Work Tickets · KPI · OEE · BN · Line Verification</div>'
        "</div>"
        f'<div class="app-header-right">{"".join(chips)}</div>'
        "</div>",
        unsafe_allow_html=True,
    )


def render_page_header(module_name, extra_chips=()):
    """Consistent module title with icon, purpose and context chips."""
    module = get_module_config(module_name) or {}
    st.markdown(
        ui.page_header(module.get("icon", "📊"), module_name, module.get("description", ""), extra_chips),
        unsafe_allow_html=True,
    )

def _query_value(name, default=""):
    try:
        value = st.query_params.get(name, default)
        if isinstance(value, list):
            value = value[0] if value else default
        return str(value or default)
    except Exception:
        return default


def _automation_supplied_token():
    """Prefer a request header; keep the query token only for old schedulers."""
    try:
        headers = st.context.headers
        direct = str(headers.get("X-Automation-Token", "") or "").strip()
        if direct:
            return direct
        authorization = str(headers.get("Authorization", "") or "").strip()
        if authorization.lower().startswith("bearer "):
            return authorization[7:].strip()
    except Exception:
        return _query_value("token").strip()
    return _query_value("token").strip()


def is_automation_request():
    requested = _query_value("automation").strip().lower() in {"1", "true", "yes"}
    if not requested:
        return False
    configured_token = str(_get_secret_value("AUTOMATION_TOKEN", ("automation", "TOKEN"), default="") or "").strip()
    if not configured_token:
        # README: the token is optional. Previously a missing token silently
        # disabled ALL background work (Forms import, alerts), which is why
        # entries looked missing in KPI and alerts were never sent.
        return True
    supplied_token = _automation_supplied_token()
    return hmac.compare_digest(
        configured_token.encode("utf-8"), supplied_token.encode("utf-8")
    )


def _automation_token_configured():
    return bool(str(_get_secret_value("AUTOMATION_TOKEN", ("automation", "TOKEN"), default="") or "").strip())


@st.cache_resource
def _automation_run_state():
    return {"lock": threading.Lock(), "last_run": 0.0}


def _summarize_automation(result):
    """Short, name-free summary for the public automation page."""
    summary = {}
    for key, value in result.items():
        if isinstance(value, dict):
            summary[key] = {k: v for k, v in value.items() if k in {"status", "date", "total_added", "imported", "forms_added", "app_added", "downtime_added", "changes", "open_tasks", "initialized", "row_count"}}
            if "missing" in value:
                summary[key]["missing_count"] = len(value.get("missing") or [])
        else:
            summary[key] = value
    return summary


# Turbo separation: normal users never wait for database synchronization or four
# scheduled notification checks. GitHub Actions calls ?automation=1 in a dedicated session.
if is_automation_request():
    st.markdown("## Lianbo background automation")
    automation_result = {}
    run_state = _automation_run_state()
    # Protection against repeated/abusive calls: at most one run per 4 minutes.
    if time_module.time() - run_state["last_run"] < 240 or not run_state["lock"].acquire(blocking=False):
        st.info("Automation already ran in the last few minutes.")
        st.success("Automation checks completed.")
        st.stop()
    try:
        run_state["last_run"] = time_module.time()
        try:
            activity_status = get_all_activities_status()
            automation_result["activity_status"] = activity_status
            if activity_status.get("initialized"):
                automation_result["activity_sync"] = sync_all_activities(force=True)
        except Exception as exc:
            automation_result["activity_sync"] = {"status": "error", "error": str(exc)}
        try:
            automation_result["bn_forms_sync"] = sync_bn_forms_to_records()
        except Exception as exc:
            automation_result["bn_forms_sync"] = {"status": "error", "error": str(exc)}
        try:
            run_automatic_notification_checks()
            automation_result["missing_work_time"] = st.session_state.get("missing_work_time_check_result", {})
            automation_result["missing_bn"] = st.session_state.get("missing_bn_check_result", {})
            automation_result["open_task_reminder"] = st.session_state.get("open_task_reminder_result", {})
            automation_result["bn_deviation"] = st.session_state.get("bn_deviation_batch_result", {})
            automation_result["weekly_management_email"] = st.session_state.get("weekly_management_email_result", {})
        except Exception as exc:
            automation_result["notifications"] = {"status": "error", "error": str(exc)}
    finally:
        run_state["lock"].release()
    st.json(automation_result if _automation_token_configured() else _summarize_automation(automation_result))
    st.success("Automation checks completed.")
    st.stop()

try:
    _migrate_all_legacy_passwords()
except Exception as exc:
    st.error(
        "Bezbednosna migracija lozinki nije uspela; prijava je privremeno zaustavljena "
        "da lozinke ne bi ostale u običnom tekstu."
    )
    st.caption(f"{type(exc).__name__}: {exc}")
    st.stop()

require_login()
render_app_header()
if OUTDATED_SUPPORT_FILES and is_admin_user(st.session_state.get("user", {})):
    st.warning(
        "Neki pomoćni fajlovi u GitHub repozitorijumu su stari: "
        + ", ".join(OUTDATED_SUPPORT_FILES)
        + ". Aplikacija radi, ali zameni ih verzijom iz najnovijeg paketa (APP_VERSION) za pun izgled i zaštitu podataka."
    )
if getattr(GOOGLE_SHEETS_ENGINE, "recently_served_stale", lambda **_: False)(within_seconds=180):
    st.warning(
        "Google Sheets je trenutno preopterećen; deo prikaza može biti star do nekoliko minuta. "
        "Sačuvani unosi NISU izgubljeni — klikni 'Osveži sve module' za minut."
    )
current_user = st.session_state.get('user', {})
current_permissions = current_user.get('permissions', {})


# ===============================
# SIDEBAR / CONTROL PANEL TOGGLE
# ===============================
if "control_panel_visible" not in st.session_state:
    st.session_state["control_panel_visible"] = True

# Always calculate allowed modules, even when the control panel is hidden.
# A user sees only modules explicitly allowed in Authorisation/Permissions.
allowed_modules = user_allowed_modules(current_permissions, current_user)

if not allowed_modules:
    st.error("Korisnik nema dozvolu ni za jedan modul. Proveri Authorisation tab.")
    st.stop()

migration_report = st.session_state.pop("_all_activities_migration_report", None)
if migration_report:
    if migration_report.get("status") == "ok":
        st.success("ALL_ACTIVITIES je uspešno inicijalizovan.")
        r1, r2, r3, r4, r5 = st.columns(5)
        r1.metric("Forms imported", migration_report.get("forms_added", 0))
        r2.metric("App imported", migration_report.get("app_added", 0))
        r3.metric("Downtime imported", migration_report.get("downtime_added", 0))
        r4.metric("Duplicates skipped", migration_report.get("duplicates_skipped", 0))
        r5.metric("ALL_ACTIVITIES total", migration_report.get("all_total_after", 0))
        if migration_report.get("downtime_ignored_names"):
            st.info(
                "Downtime names outside active app technicians were ignored: "
                + ", ".join(migration_report["downtime_ignored_names"])
            )
        if migration_report.get("errors"):
            st.warning("Migracija je završena uz upozorenja:")
            st.write(migration_report["errors"])
    else:
        st.error("ALL_ACTIVITIES migracija nije uspela.")
        st.write(migration_report.get("errors", []))

if st.session_state.get("selected_module") not in allowed_modules:
    st.session_state["selected_module"] = allowed_modules[0]

# Mobile in-app menu. Hidden on desktop by CSS; visible on phone.
# Important: use buttons, not a hidden selectbox. A hidden selectbox keeps its old
# session value on desktop and can cancel normal sidebar clicks.
st.markdown('<div class="mobile-menu-title">☰ Menu</div>', unsafe_allow_html=True)
for module_name in allowed_modules:
    mobile_label = module_display_label(module_name)
    mobile_active = module_name == st.session_state.get("selected_module")
    if st.button(mobile_label, use_container_width=True, key=f"mobile_nav_{_norm_key(module_name)}",
                 type="primary" if mobile_active else "secondary"):
        st.session_state["selected_module"] = module_name
        st.rerun()

mobile_cols = st.columns(2)
with mobile_cols[0]:
    if st.button("🔄 Osveži", use_container_width=True, key="mobile_refresh_btn"):
        refresh_data()
with mobile_cols[1]:
    if st.button("Logout", use_container_width=True, key="mobile_logout_btn"):
        logout()

# Toggle button. When clicked, the control panel collapses/expands.
sidebar_visible = st.session_state.get("control_panel_visible", True)

if not sidebar_visible:
    st.markdown("""
    <style>
    section[data-testid="stSidebar"] {
        width: 92px !important;
        min-width: 92px !important;
        max-width: 92px !important;
    }
    section[data-testid="stSidebar"] > div:first-child {
        width: 92px !important;
        min-width: 92px !important;
        max-width: 92px !important;
        padding-left: 8px !important;
        padding-right: 8px !important;
    }
    section[data-testid="stSidebar"] button {
        min-width: 54px !important;
        width: 54px !important;
        padding-left: 0 !important;
        padding-right: 0 !important;
        border-radius: 16px !important;
        font-size: 20px !important;
    }
    section[data-testid="stSidebar"] .stButton {
        display: flex !important;
        justify-content: center !important;
    }
    </style>
    """, unsafe_allow_html=True)

if sidebar_visible:
    st.sidebar.markdown(
        '<div class="side-brand"><div class="side-brand-mark">PT</div>'
        '<div class="side-brand-text">Performance Hub<small>Project Technology</small></div></div>',
        unsafe_allow_html=True,
    )
control_button_label = "☰" if not sidebar_visible else "⇤ Sakrij meni"
control_button_help = "Prikaži meni" if not sidebar_visible else "Sakrij bočni meni"
if st.sidebar.button(control_button_label, use_container_width=True, key="toggle_control_panel_btn", help=control_button_help):
    st.session_state["control_panel_visible"] = not st.session_state["control_panel_visible"]
    st.rerun()

if sidebar_visible:
    st.sidebar.markdown(
        '<div class="user-badge">'
        f'<div class="user-avatar">{ui.esc(ui.initials(current_user.get("full_name", "")))}</div>'
        f'<div><div class="user-name">{ui.esc(current_user.get("full_name", ""))}</div>'
        f'<div class="user-role">{ui.esc(current_user.get("role", ""))}</div></div></div>',
        unsafe_allow_html=True,
    )

    # Grouped navigation; the active module is a highlighted (primary) button.
    remaining = list(allowed_modules)
    for group_label, access_keys in MODULE_GROUPS:
        group_modules = [
            m for m in allowed_modules
            if (get_module_config(m) or {}).get("access_key") in access_keys
        ]
        if not group_modules:
            continue
        st.sidebar.markdown(f'<div class="nav-group">{ui.esc(group_label)}</div>', unsafe_allow_html=True)
        for module_name in group_modules:
            remaining.remove(module_name)
            is_active = module_name == st.session_state.get("selected_module")
            if st.sidebar.button(
                module_display_label(module_name),
                use_container_width=True,
                key=f"btn_module_{module_name}",
                type="primary" if is_active else "secondary",
            ):
                st.session_state["selected_module"] = module_name
                st.rerun()
    for module_name in remaining:
        if st.sidebar.button(module_display_label(module_name), use_container_width=True, key=f"btn_module_{module_name}"):
            st.session_state["selected_module"] = module_name
            st.rerun()

    st.sidebar.markdown('<div class="nav-group">Alati</div>', unsafe_allow_html=True)
    if st.sidebar.button(
        "🔄 Osveži sve module",
        use_container_width=True,
        key="refresh_all",
        help="Briše sve data/resource cache-e i ponovo učitava podatke za KPI, Work Tickets, BN, OEE, Bottleneck, Line Verification i Administration.",
    ):
        refresh_data()
    if st.sidebar.button("↪ Odjava", use_container_width=True, key="logout_btn"):
        logout()
    if st.session_state.get("_global_refresh_at"):
        st.sidebar.markdown(
            f'<div class="side-foot">Osveženo: {ui.esc(st.session_state["_global_refresh_at"])}</div>',
            unsafe_allow_html=True,
        )
else:
    st.sidebar.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

if st.session_state.get("_global_refresh_notice"):
    st.toast(st.session_state.pop("_global_refresh_notice"), icon="✅")

selected_module = st.session_state["selected_module"]
current_module_config = get_module_config(selected_module)
if current_module_config:
    render_page_header(selected_module)

# Load KPI data only when KPI module is selected.
# This keeps OEE input fast and prevents unnecessary Google Sheets calls.
df_kpi = None
kpi_missing = []
kpi_load_error = None



# =========================
# OEE V18 CLEAN DASHBOARD HELPERS
# =========================
# v11: Serbian names; the main number first. IWON is private and is not offered here.
OEE_METRIC_OPTIONS = {
    "OEE mašine": "Machine_OEE_CT_%",
    "OEE fabrike (napredno)": "Plant_OEE_CT_%",
    "OEE mašine prema targetu (napredno)": "Machine_OEE_Target_%",
    "OEE fabrike prema targetu (napredno)": "Plant_OEE_Target_%",
}

OEE_METRIC_LABELS = {v: k.replace(" (napredno)", "") for k, v in OEE_METRIC_OPTIONS.items()}
OEE_METRIC_LABELS["IWON_OEE_%"] = "OEE IWON"


def get_oee_breakdown_cols(metric_col):
    if metric_col == "IWON_OEE_%":
        return [("Availability", "Availability"), ("Performance", "Performance"), ("Q-rate", "Quality")]
    if metric_col == "Machine_OEE_CT_%":
        return [
            ("Availability", "Machine_Availability_%"),
            ("Performance CT", "Machine_Performance_CT_%"),
            ("Quality", "Quality_%"),
        ]
    if metric_col == "Plant_OEE_CT_%":
        return [
            ("Availability", "Plant_Availability_%"),
            ("Performance CT", "Plant_Performance_CT_%"),
            ("Quality", "Quality_%"),
        ]
    if metric_col == "Machine_OEE_Target_%":
        return [
            ("Availability", "Machine_Availability_%"),
            ("Performance Target", "Performance_Target_%"),
            ("Quality", "Quality_%"),
        ]
    return [
        ("Availability", "Plant_Availability_%"),
        ("Performance Target", "Performance_Target_%"),
        ("Quality", "Quality_%"),
    ]


def get_oee_green_color(value):
    """Monochrome green scale for OEE KPI cards."""
    try:
        value = float(value)
    except Exception:
        value = 0.0
    if value < 70:
        return "#A8E6A3"
    if value < 80:
        return "#6FD36B"
    if value < 90:
        return "#34C759"
    return "#008F39"


def render_oee_progress_card(label, value, is_main=False, footer=None):
    """Return one compact HTML KPI card.

    Important: the returned HTML must not contain leading 4-space indentation,
    otherwise Streamlit/Markdown can render later cards as a code block.
    """
    try:
        value = float(value)
    except Exception:
        value = 0.0

    display_value = max(0, min(100, value))
    color = get_oee_green_color(display_value)
    main_class = " main" if is_main else ""
    footer_html = f'<div class="oee-card-footer">{footer}</div>' if footer else '<div class="oee-card-footer">&nbsp;</div>'

    return (
        f'<div class="oee-progress-card{main_class}">'
        f'<div class="oee-card-label">{label}</div>'
        f'<div class="oee-card-value">{display_value:.2f}%</div>'
        f'<div class="oee-progress-track">'
        f'<div class="oee-progress-fill" style="width:{display_value:.2f}%; background:{color};"></div>'
        f'</div>'
        f'{footer_html}'
        f'</div>'
    )


def show_oee_single_kpi_and_breakdown(summary_df, metric_col, key_prefix):
    if summary_df.empty:
        st.warning("Nema OEE podataka za izabrane filtere.")
        return

    row = summary_df.iloc[0]
    metric_label = OEE_METRIC_LABELS.get(metric_col, metric_col)
    breakdown = get_oee_breakdown_cols(metric_col)

    cards_html = '<div class="oee-card-row">'
    cards_html += render_oee_progress_card(metric_label, row.get(metric_col, 0), is_main=True, footer="Target: 85.00%")
    for label, col_name in breakdown:
        cards_html += render_oee_progress_card(label, row.get(col_name, 0))
    cards_html += '</div>'

    st.markdown(cards_html, unsafe_allow_html=True)

OEE_CHART_TARGET = 85.0


def get_oee_chart_status_color(value, target=OEE_CHART_TARGET):
    """Traffic-light color shared by every modern OEE chart."""
    try:
        value = float(value)
    except Exception:
        value = 0.0
    if value < 70:
        return "#EF4444"
    if value < float(target):
        return "#F59E0B"
    return "#22C55E"


def modern_oee_chart_title(title):
    """Turn legacy 'trend | period' titles into the cleaner dashboard format."""
    clean = str(title or "OEE chart").strip()
    clean = clean.replace(" trend | ", " Trend — ")
    clean = clean.replace(" Trend | ", " Trend — ")
    clean = clean.replace(" | ", " — ")
    return clean


def add_oee_target_line(fig, show_target=True):
    """Add the common 85% benchmark without covering the latest data point."""
    if not show_target:
        return fig
    fig.add_hline(
        y=OEE_CHART_TARGET,
        line_width=2,
        line_dash="dash",
        line_color="#FBBF24",
        annotation_text=f"TARGET {OEE_CHART_TARGET:.0f}%",
        annotation_position="top left",
        annotation_font=dict(color="#FBBF24", size=11, family="Segoe UI, Inter, Arial"),
        annotation_bgcolor="rgba(58,43,8,0.94)",
        annotation_bordercolor="#FBBF24",
        annotation_borderwidth=1,
        annotation_borderpad=4,
    )
    return fig


def plot_oee_bar(data, x_col, metric_col, title, key):
    if data.empty:
        st.warning("Nema podataka za chart.")
        return
    chart_df = data.copy()
    chart_df[metric_col] = pd.to_numeric(chart_df[metric_col], errors="coerce").fillna(0)
    values = chart_df[metric_col].tolist()
    colors = [get_oee_chart_status_color(value) for value in values]
    y_axis_range = calculate_dynamic_percent_axis(values + [OEE_CHART_TARGET], padding_down=10, hard_min=0, hard_max=100)

    fig = go.Figure(go.Bar(
        x=chart_df[x_col].astype(str).tolist(),
        y=values,
        marker=dict(color=colors, line=dict(color="rgba(255,255,255,0.72)", width=1.3)),
        hovertemplate=f"<b>%{{x}}</b><br>{OEE_METRIC_LABELS.get(metric_col, metric_col)}: %{{y:.2f}}%<extra></extra>",
    ))
    for category, value, color in zip(chart_df[x_col].astype(str).tolist(), values, colors):
        fig.add_annotation(
            x=category, y=value, text=f"<b>{value:.2f}%</b>", showarrow=False,
            yshift=17, bgcolor=color, bordercolor="#FFFFFF", borderwidth=1,
            borderpad=5, font=dict(color="#FFFFFF", size=11),
        )

    add_oee_target_line(
        fig,
        show_target=metric_col in OEE_METRIC_OPTIONS.values() and metric_col != "IWON_OEE_%",
    )
    fig.update_layout(
        title=modern_oee_chart_title(title),
        height=470,
        margin=dict(l=55, r=30, t=90, b=75),
        xaxis=dict(title=None, type="category", showgrid=False),
        yaxis=dict(title="OEE (%)", range=y_axis_range, ticksuffix="%", zeroline=False),
        showlegend=False,
        bargap=0.34,
    )
    fig = style_chart(fig)
    fig.update_layout(margin=dict(l=55, r=30, t=90, b=75))
    st.plotly_chart(fig, use_container_width=True, key=key)


def calculate_dynamic_percent_axis(values, padding_down=10, hard_min=0, hard_max=100):
    """Dynamic Y axis for percent KPI charts.

    Rule requested for OEE dashboard:
    - do not force 0-100 scale
    - start approximately 10 percentage points below the lowest shown value
    - upper limit stays 100%
    """
    numeric = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    if numeric.empty:
        return [0, 100]

    min_val = float(numeric.min())
    y_min = max(hard_min, min_val - padding_down)
    y_max = hard_max

    # If the KPI is very low, keep a readable window.
    if y_max - y_min < 5:
        y_min = max(hard_min, y_max - 10)

    return [y_min, y_max]


def plot_oee_line(data, x_col, metric_col, title, key, x_axis_title="Dan / period"):
    if data.empty:
        st.warning("Nema podataka za chart.")
        return

    chart_df = data.copy()

    # Force chronological/order column before plotting.
    # Plotly categorical axes can otherwise follow sheet/input order.
    if "Chart_X_Order" in chart_df.columns:
        chart_df = chart_df.sort_values("Chart_X_Order").reset_index(drop=True)
    elif "Datum" in chart_df.columns:
        chart_df["Datum"] = parse_oee_date_series(chart_df["Datum"])
        chart_df = chart_df.sort_values("Datum").reset_index(drop=True)

    chart_df[metric_col] = pd.to_numeric(chart_df[metric_col], errors="coerce").fillna(0)
    category_order = chart_df[x_col].astype(str).tolist()
    y_values = chart_df[metric_col].tolist()
    is_oee_metric = metric_col in OEE_METRIC_OPTIONS.values()
    # IWON is itself a planned target and may change by CW, so a fixed 85% line would be misleading.
    show_target = is_oee_metric and metric_col != "IWON_OEE_%"
    axis_values = y_values + ([OEE_CHART_TARGET] if show_target else [])
    y_axis_range = calculate_dynamic_percent_axis(axis_values, padding_down=10, hard_min=0, hard_max=100)
    point_colors = [get_oee_chart_status_color(value) for value in y_values]
    line_color = "#38BDF8"

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=category_order,
        y=y_values,
        mode="lines+markers",
        name=OEE_METRIC_LABELS.get(metric_col, metric_col),
        line=dict(color=line_color, width=4, shape="linear"),
        marker=dict(size=11, color=point_colors, line=dict(width=2, color="#FFFFFF")),
        fill="tozeroy",
        fillcolor="rgba(56,189,248,0.10)",
        hovertemplate=(
            f"<b>{x_axis_title}</b>: %{{x}}<br>"
            f"<b>{OEE_METRIC_LABELS.get(metric_col, metric_col)}</b>: %{{y:.2f}}%"
            "<extra></extra>"
        ),
    ))

    for category, value, color in zip(category_order, y_values, point_colors):
        fig.add_annotation(
            x=category, y=value, text=f"<b>{value:.2f}%</b>", showarrow=False,
            yshift=21, bgcolor=color, bordercolor="#FFFFFF", borderwidth=1,
            borderpad=5, font=dict(color="#FFFFFF", size=11),
        )

    add_oee_target_line(fig, show_target=show_target)

    if len(y_values) >= 2:
        delta = float(y_values[-1]) - float(y_values[0])
        delta_color = "#22C55E" if delta >= 0 else "#EF4444"
        fig.add_annotation(
            x=1, y=1.16, xref="paper", yref="paper", xanchor="right", yanchor="top",
            text=f"PERIOD CHANGE<br><b>{delta:+.2f} pp</b>", showarrow=False,
            align="right", bgcolor="rgba(9,21,37,0.92)", bordercolor=delta_color,
            borderwidth=1, borderpad=7, font=dict(color=delta_color, size=12),
        )

    for label, color in (
        ("Below 70%", "#EF4444"),
        ("70–84.99%", "#F59E0B"),
        ("Target achieved", "#22C55E"),
    ):
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers", name=label,
            marker=dict(size=9, color=color, line=dict(width=1, color="#FFFFFF")),
            hoverinfo="skip",
        ))

    fig.update_layout(
        title=modern_oee_chart_title(title),
        height=500,
        margin=dict(l=55, r=30, t=105, b=90),
        xaxis=dict(
            title=None,
            type="category",
            categoryorder="array",
            categoryarray=category_order,
            showgrid=False,
        ),
        yaxis=dict(
            title="OEE (%)" if is_oee_metric else "%",
            range=y_axis_range,
            ticksuffix="%",
            zeroline=False,
        ),
        showlegend=True,
        legend=dict(
            orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5,
            bgcolor="rgba(0,0,0,0)", font=dict(color="#CBD5E1", size=11),
        ),
    )

    fig = style_chart(fig)
    fig.update_layout(
        margin=dict(l=55, r=30, t=105, b=90),
        legend=dict(
            orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5,
            bgcolor="rgba(0,0,0,0)", font=dict(color="#CBD5E1", size=11),
        ),
    )
    fig.update_xaxes(
        showline=True,
        linewidth=1,
        linecolor="rgba(148, 163, 184, 0.45)",
        tickfont=dict(color="#E5E7EB", size=13),
    )
    fig.update_yaxes(
        showline=True,
        linewidth=1,
        linecolor="rgba(148, 163, 184, 0.45)",
        tickfont=dict(color="#E5E7EB", size=13),
    )


    st.plotly_chart(fig, use_container_width=True, key=key)


def plot_oee_components_bar(metric_values, title, key, show_target=True, selectable=False):
    """Daily tab: one compact bar chart with OEE, Availability, Q-rate and Performance."""
    chart_df = pd.DataFrame(metric_values)
    if chart_df.empty:
        st.warning("Nema podataka za chart.")
        return

    chart_df["Value"] = pd.to_numeric(chart_df["Value"], errors="coerce").fillna(0)
    values = chart_df["Value"].tolist()
    y_axis_range = calculate_dynamic_percent_axis(values + [OEE_CHART_TARGET], padding_down=10, hard_min=0, hard_max=100)
    colors = [get_oee_chart_status_color(value) for value in values]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=chart_df["Metric"].tolist(),
        y=chart_df["Value"].tolist(),
        marker=dict(color=colors, line=dict(color="rgba(255,255,255,0.45)", width=1)),
        hovertemplate="<b>%{x}</b><br>%{y:.2f}%<extra></extra>",
    ))

    for metric, value, color in zip(chart_df["Metric"].tolist(), values, colors):
        fig.add_annotation(
            x=metric,
            y=value,
            text=f"<b>{value:.2f}%</b>",
            showarrow=False,
            yshift=16,
            bgcolor=color,
            bordercolor="#FFFFFF",
            borderwidth=1,
            borderpad=3,
            font=dict(color="#FFFFFF", size=11),
        )

    add_oee_target_line(fig, show_target=show_target)

    fig.update_layout(
        title=modern_oee_chart_title(title),
        height=470,
        margin=dict(l=55, r=30, t=90, b=75),
        xaxis=dict(
            title=None,
            type="category",
            showgrid=False,
        ),
        yaxis=dict(
            title="KPI (%)",
            range=y_axis_range,
            ticksuffix="%",
            zeroline=False,
        ),
        showlegend=False,
    )

    fig = style_chart(fig)
    fig.update_layout(margin=dict(l=55, r=30, t=90, b=75))
    fig.update_xaxes(
        showline=True,
        linewidth=1,
        linecolor="rgba(148, 163, 184, 0.45)",
        tickfont=dict(color="#E5E7EB", size=13),
    )
    fig.update_yaxes(
        showline=True,
        linewidth=1,
        linecolor="rgba(148, 163, 184, 0.45)",
        tickfont=dict(color="#E5E7EB", size=13),
    )

    if selectable:
        fig.update_layout(clickmode="event+select")
        _plotly_selectable(fig, key)
    else:
        st.plotly_chart(fig, use_container_width=True, key=key)

def show_oee_daily_bar_view(period_base, metric_col, machine_filter, period_label, key_prefix, ctx=None):
    """Daily OEE view: KPI cards plus one bar chart with OEE, Availability, Q-rate and Performance."""
    if period_base.empty:
        st.warning(f"Nema OEE podataka za {period_label}.")
        return

    availability_col, performance_col = get_oee_component_columns(metric_col)
    metric_label = OEE_METRIC_LABELS.get(metric_col, metric_col)

    summary = aggregate_oee(period_base.assign(OEE_Total="Total"), ["OEE_Total"])
    if ctx:
        render_oee_manager_summary(period_base, metric_col, ctx)
    else:
        show_oee_single_kpi_and_breakdown(summary, metric_col, key_prefix)

    if summary.empty:
        st.warning("Nema podataka za dnevni chart.")
        return

    row = summary.iloc[0]
    metric_values = [
        {"Metric": "OEE", "Value": row.get(metric_col, 0)},
        {"Metric": "Dostupnost", "Value": row.get(availability_col, 0)},
        {"Metric": "Kvalitet", "Value": row.get("Quality_%", 0)},
        {"Metric": "Performanse", "Value": row.get(performance_col, 0)},
    ]

    metric_key = f"{key_prefix}_drill_metric"
    chart_key = f"{key_prefix}_daily_components_bar"
    points = _oee_chart_points(chart_key)
    signature = repr([(p.get("x"), p.get("point_index")) for p in points])
    if points and st.session_state.get(f"{chart_key}_seen") != signature:
        clicked = OEE_DRILL_FROM_COMPONENT.get(str(points[-1].get("x")))
        if clicked:
            st.session_state[metric_key] = clicked
    st.session_state[f"{chart_key}_seen"] = signature
    if st.session_state.get(metric_key) not in OEE_DRILL_METRICS:
        st.session_state[metric_key] = "oee"

    st.markdown("### Pregled dana")
    plot_oee_components_bar(
        metric_values,
        f"OEE / Dostupnost / Kvalitet / Performanse · {period_label}",
        chart_key,
        selectable=True,
    )
    st.caption("Klikni stubić (OEE, Dostupnost, Kvalitet, Performanse) ili izaberi ispod — detalji se otvaraju odmah.")
    drill_metric = st.radio(
        "Detalji za", OEE_DRILL_METRICS, horizontal=True, key=metric_key,
        format_func=lambda m: OEE_DRILL_LABELS.get(m, m), label_visibility="collapsed",
    )
    render_oee_detail_card(period_base, drill_metric, metric_col, period_label)

    loss_col, shift_col = st.columns(2)
    with loss_col:
        pareto = render_loss_pareto(period_base)
    with shift_col:
        render_oee_shift_compare(period_base, metric_col)
    if ctx and ctx.get("project"):
        render_oee_actions(ctx["project"], ctx["process"], machine_filter, pareto, key_prefix, can_edit_module("OEE"))

    if machine_filter == "Sve" and "Machine" in period_base.columns and period_base["Machine"].nunique() > 0:
        st.markdown("### Poređenje mašina")
        render_oee_machine_compare(period_base, metric_col, period_label, key_prefix)
        machine_oee = aggregate_oee(period_base, ["Project", "Process", "Machine"])
        compare_cols = ["Machine", metric_col, availability_col, performance_col, "Quality_%", "OK_pcs", "NOK_pcs",
                        "Open_Time", "Down_Time", "Organisational_Loss"]
        compare_cols = [c for c in compare_cols if c in machine_oee.columns]
        if not machine_oee.empty:
            st.dataframe(format_oee_percent_columns(machine_oee[compare_cols]), use_container_width=True, hide_index=True)


def _prepare_iwon_trend_labels(trend, trend_x_col):
    """Create chronological chart labels for an already aggregated IWON trend."""
    if trend.empty:
        return trend
    trend = trend.copy()
    if trend_x_col == "Datum" and "Datum" in trend.columns:
        trend["Datum"] = parse_oee_date_series(trend["Datum"])
        trend = trend.sort_values("Datum").reset_index(drop=True)
        trend["Chart_X"] = trend["Datum"].dt.day_name().str[:3] + " " + trend["Datum"].dt.strftime("%d.%m")
        trend["Chart_X_Order"] = trend["Datum"]
        trend["Chart_X_Title"] = "Dan"
    elif trend_x_col == "Week" and "Week" in trend.columns:
        sort_cols = [c for c in ["Godina", "Week"] if c in trend.columns]
        trend = trend.sort_values(sort_cols).reset_index(drop=True)
        trend["Chart_X"] = trend.apply(
            lambda r: f"{int(r['Godina'])}-CW{int(r['Week']):02d}"
            if "Godina" in trend.columns else f"CW{int(r['Week']):02d}",
            axis=1,
        )
        trend["Chart_X_Order"] = range(len(trend))
        trend["Chart_X_Title"] = "Calendar week"
    elif trend_x_col == "Mesec" and "Mesec" in trend.columns:
        year_col = "Calendar_Year" if "Calendar_Year" in trend.columns else "Godina"
        sort_cols = [c for c in [year_col, "Mesec"] if c in trend.columns]
        trend = trend.sort_values(sort_cols).reset_index(drop=True)
        month_map = {
            1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
            7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
        }
        trend["Chart_X"] = trend["Mesec"].astype(int).map(month_map).fillna(trend["Mesec"].astype(str))
        if year_col in trend.columns:
            trend["Chart_X"] = trend["Chart_X"] + " " + trend[year_col].astype(int).astype(str)
        trend["Chart_X_Order"] = range(len(trend))
        trend["Chart_X_Title"] = "Mesec"
    else:
        sort_cols = [c for c in [*trend.columns] if c in [trend_x_col]]
        if sort_cols:
            trend = trend.sort_values(sort_cols).reset_index(drop=True)
        trend["Chart_X"] = trend[trend_x_col].astype(str)
        trend["Chart_X_Order"] = range(len(trend))
        trend["Chart_X_Title"] = str(trend_x_col)
    return trend


def show_iwon_period_view(
    period_base,
    project,
    process,
    machine_filter,
    period_label,
    key_prefix,
    trend_group_cols=None,
    trend_x_col=None,
):
    """Render a daily/date-range/monthly/yearly IWON result from saved weekly scenarios."""
    if period_base.empty:
        st.warning(f"Nema OEE podataka za {period_label}.")
        return

    try:
        saved_iwon = load_oee_iwon_results()
    except Exception as exc:
        st.warning(f"IWON rezultati nisu dostupni: {exc}")
        return

    include_global = machine_filter == "Sve"
    summary, missing = aggregate_iwon_period(
        period_base,
        project,
        process,
        group_cols=[],
        include_global=include_global,
        iwon_data=saved_iwon,
    )
    selected_machine = "GLOBAL" if include_global else str(machine_filter).strip()
    selected_key = selected_machine.casefold()
    selected = summary[summary["Machine"].astype(str).str.strip().str.casefold().eq(selected_key)].copy()

    if selected.empty:
        st.warning(
            "Nema dovoljno sačuvanih weekly IWON rezultata za izabrani period. "
            "U tabu IWON → Plan i prognoza generiši odgovarajuće CW nedelje."
        )
        return

    row = selected.iloc[0]
    covered_cws = int(row.get("Covered_CWs", 0) or 0)
    expected_cws = int(row.get("Expected_CWs", 0) or 0)
    coverage = float(row.get("Coverage_%", 0) or 0)
    if coverage < 99.999:
        missing_selected = missing[
            missing.get("IWON_Machine", pd.Series(index=missing.index, dtype=object))
            .astype(str).str.strip().str.casefold().eq(selected_key)
        ].copy()
        missing_labels = []
        if not missing_selected.empty:
            missing_labels = sorted({
                f"{int(r.Godina)}-CW{int(r.Week):02d}"
                for r in missing_selected[["Godina", "Week"]].drop_duplicates().itertuples(index=False)
                if pd.notna(r.Godina) and pd.notna(r.Week)
            })
        missing_text = f" Nedostaje: {', '.join(missing_labels[:12])}." if missing_labels else ""
        st.warning(
            f"IWON rezultat je privremen: pokriveno je {covered_cws} od {expected_cws} CW perioda "
            f"sa stvarnim OEE unosima.{missing_text} Generiši nedostajuće nedelje u Administration."
        )

    st.caption(
        "Period IWON: weekly Availability je ponderisan Machine Available Time-om, "
        "Performance Machine Run Time-om, a Quality ukupnim komadima; zatim OEE = A × P × Q."
    )
    cards = '<div class="oee-card-row">'
    cards += render_oee_progress_card(
        "OEE IWON", row.get("IWON_OEE_%", 0), is_main=True,
        footer=f"CW coverage: {covered_cws}/{expected_cws}",
    )
    cards += render_oee_progress_card("Availability", row.get("Availability", 0))
    cards += render_oee_progress_card("Performance", row.get("Performance", 0))
    cards += render_oee_progress_card("Q-rate", row.get("Quality", 0))
    cards += '</div>'
    st.markdown(cards, unsafe_allow_html=True)

    st.markdown("### IWON target overview")
    plot_oee_components_bar(
        [
            {"Metric": "OEE", "Value": row.get("IWON_OEE_%", 0)},
            {"Metric": "Availability", "Value": row.get("Availability", 0)},
            {"Metric": "Q-rate", "Value": row.get("Quality", 0)},
            {"Metric": "Performance", "Value": row.get("Performance", 0)},
        ],
        f"OEE IWON | {period_label} | {project} | {process}",
        f"{key_prefix}_components",
        show_target=False,
    )

    if trend_group_cols and trend_x_col:
        trend_all, _ = aggregate_iwon_period(
            period_base,
            project,
            process,
            group_cols=trend_group_cols,
            include_global=include_global,
            iwon_data=saved_iwon,
        )
        trend = trend_all[
            trend_all["Machine"].astype(str).str.strip().str.casefold().eq(selected_key)
        ].copy()
        trend = _prepare_iwon_trend_labels(trend, trend_x_col)
        if not trend.empty:
            st.markdown("### IWON trend")
            chart_x_title = trend["Chart_X_Title"].iloc[0]
            plot_oee_line(
                trend,
                "Chart_X",
                "IWON_OEE_%",
                f"OEE IWON trend | {period_label}",
                f"{key_prefix}_trend",
                chart_x_title,
            )

    if include_global:
        machine_rows = summary[summary["Machine"].astype(str).str.upper().ne("GLOBAL")].copy()
        if not machine_rows.empty:
            st.markdown("### Target per machine")
            machine_rows["Machine_Label"] = machine_rows["Machine"].astype(str)
            if len(machine_rows) > 1:
                plot_oee_bar(
                    machine_rows.sort_values("IWON_OEE_%", ascending=False),
                    "Machine_Label",
                    "IWON_OEE_%",
                    f"OEE IWON per machine | {period_label}",
                    f"{key_prefix}_machine_bar",
                )
            display = machine_rows
        else:
            display = selected
    else:
        display = selected

    display_cols = [
        "Machine", "Availability", "Performance", "Quality", "IWON_OEE_%",
        "Covered_CWs", "Expected_CWs", "Coverage_%",
    ]
    display_cols = [c for c in display_cols if c in display.columns]
    display = display[display_cols].copy()
    for col in ["Availability", "Performance", "Quality", "IWON_OEE_%", "Coverage_%"]:
        if col in display.columns:
            display[col] = pd.to_numeric(display[col], errors="coerce").round(2)
    display = display.rename(columns={
        "IWON_OEE_%": "OEE IWON %",
        "Coverage_%": "CW Coverage %",
        "Covered_CWs": "Covered CWs",
        "Expected_CWs": "Expected CWs",
    })
    st.dataframe(display, use_container_width=True, hide_index=True)


def render_oee_inline_filters(base_df, key_prefix):
    """Main-page OEE filters: Project, Process, Machine, OEE metric.
    OEE analysis is locked to ONE Project + ONE Process.
    Machine can stay "Sve" only to compare all machines inside the selected Project/Process.
    """
    work = base_df.copy()
    c_project, c_process, c_machine, c_metric = st.columns(4)

    with c_project:
        project_options = sorted(work["Project"].dropna().astype(str).unique().tolist()) if "Project" in work.columns else []
        if not project_options:
            st.warning("Nema dostupnih projekata za izabrani period.")
            return work.iloc[0:0], None, None, "Sve", list(OEE_METRIC_OPTIONS.values())[0]
        selected_project = st.selectbox("Projekat", project_options, key=f"{key_prefix}_project")

    if "Project" in work.columns:
        work = work[work["Project"].astype(str) == selected_project]

    with c_process:
        process_options = sorted(work["Process"].dropna().astype(str).unique().tolist()) if "Process" in work.columns else []
        if not process_options:
            st.warning("Nema dostupnih procesa za izabrani projekat/period.")
            return work.iloc[0:0], selected_project, None, "Sve", list(OEE_METRIC_OPTIONS.values())[0]
        selected_process = st.selectbox("Proces", process_options, key=f"{key_prefix}_process")

    if "Process" in work.columns:
        work = work[work["Process"].astype(str) == selected_process]

    with c_machine:
        machine_options = ["Sve"] + sorted(work["Machine"].dropna().astype(str).unique().tolist()) if "Machine" in work.columns else ["Sve"]
        selected_machine = st.selectbox("Mašina", machine_options, key=f"{key_prefix}_machine")

    if selected_machine != "Sve" and "Machine" in work.columns:
        work = work[work["Machine"].astype(str) == selected_machine]

    with c_metric:
        metric_labels = list(OEE_METRIC_OPTIONS.keys())
        if st.session_state.get(f"{key_prefix}_metric") not in metric_labels:
            st.session_state.pop(f"{key_prefix}_metric", None)
        selected_metric_label = st.selectbox(
            "OEE pokazatelj", metric_labels, key=f"{key_prefix}_metric",
            help="OEE mašine je glavni broj. Ostalo je za detaljnu analizu: „fabrike“ računa i organizacione gubitke kao "
                 "gubitak, „prema targetu“ meri performanse prema planiranom broju komada umesto prema CT-u.",
        )
        selected_metric_col = OEE_METRIC_OPTIONS[selected_metric_label]

    return work, selected_project, selected_process, selected_machine, selected_metric_col

def get_oee_component_columns(metric_col):
    """Return the Availability and Performance columns that belong to the selected OEE metric."""
    if metric_col == "IWON_OEE_%":
        return "Availability", "Performance"
    if metric_col == "Machine_OEE_CT_%":
        return "Machine_Availability_%", "Machine_Performance_CT_%"
    if metric_col == "Plant_OEE_CT_%":
        return "Plant_Availability_%", "Plant_Performance_CT_%"
    if metric_col == "Machine_OEE_Target_%":
        return "Machine_Availability_%", "Performance_Target_%"
    if metric_col == "Plant_OEE_Target_%":
        return "Plant_Availability_%", "Performance_Target_%"
    return "Machine_Availability_%", "Machine_Performance_CT_%"


def prepare_oee_trend_df(period_base, trend_group_cols, trend_x_col):
    """Aggregate OEE trend from raw data and prepare a clean chart x-axis.

    The trend is always sorted by real period order. This prevents charts from
    following Google Sheet input order when Monday is entered after Tuesday/Wednesday.
    """
    if period_base.empty:
        return pd.DataFrame()

    work = period_base.copy()
    if "Datum" in work.columns:
        work["Datum"] = parse_oee_date_series(work["Datum"])

    trend = aggregate_oee(work, trend_group_cols)
    if trend.empty:
        return trend

    trend = trend.copy()

    if trend_x_col == "Datum" and "Datum" in trend.columns:
        trend["Datum"] = parse_oee_date_series(trend["Datum"])
        trend = trend.sort_values("Datum").reset_index(drop=True)
        dt = pd.to_datetime(trend["Datum"], errors="coerce")
        trend["Chart_X"] = dt.dt.day_name().str[:3] + " " + dt.dt.strftime("%d.%m")
        trend["Chart_X"] = trend["Chart_X"].fillna(dt.dt.strftime("%d.%m.%Y"))
        trend["Chart_X_Order"] = dt
        trend["Chart_X_Title"] = "Dan"
    elif trend_x_col == "Week" and "Week" in trend.columns:
        sort_cols = [c for c in ["Godina", "Week"] if c in trend.columns]
        trend = trend.sort_values(sort_cols if sort_cols else ["Week"]).reset_index(drop=True)
        trend["Chart_X"] = trend.apply(
            lambda r: f"{int(r['Godina'])}-CW{int(r['Week']):02d}" if "Godina" in trend.columns else f"CW{int(r['Week']):02d}",
            axis=1,
        )
        trend["Chart_X_Order"] = range(len(trend))
        trend["Chart_X_Title"] = "Calendar week"
    elif trend_x_col == "Mesec" and "Mesec" in trend.columns:
        year_col = "Calendar_Year" if "Calendar_Year" in trend.columns else "Godina"
        sort_cols = [c for c in [year_col, "Mesec"] if c in trend.columns]
        trend = trend.sort_values(sort_cols if sort_cols else ["Mesec"]).reset_index(drop=True)
        month_map = {
            1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
            7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"
        }
        trend["Chart_X"] = trend["Mesec"].astype(int).map(month_map).fillna(trend["Mesec"].astype(str))
        if year_col in trend.columns:
            trend["Chart_X"] = trend["Chart_X"] + " " + trend[year_col].astype(int).astype(str)
        trend["Chart_X_Order"] = range(len(trend))
        trend["Chart_X_Title"] = "Mesec"
    else:
        trend = trend.sort_values(trend_group_cols).reset_index(drop=True)
        trend["Chart_X"] = trend[trend_x_col].astype(str)
        trend["Chart_X_Order"] = range(len(trend))
        trend["Chart_X_Title"] = str(trend_x_col)

    return trend


# =========================
# v10.1 OEE DRILL-DOWN: klik na stubić -> detalji perioda
# =========================
OEE_DRILL_METRICS = ["oee", "a", "p", "q"]
OEE_DRILL_LABELS = {"oee": "OEE", "a": "Dostupnost", "p": "Performanse", "q": "Kvalitet"}
OEE_DRILL_FROM_COMPONENT = {"OEE": "oee", "Availability": "a", "Performance": "p", "Q-rate": "q",
                            "Dostupnost": "a", "Performanse": "p", "Kvalitet": "q"}
_SR_WEEKDAYS = ["Pon", "Uto", "Sre", "Čet", "Pet", "Sub", "Ned"]
_SR_MONTHS = ["Jan", "Feb", "Mar", "Apr", "Maj", "Jun", "Jul", "Avg", "Sep", "Okt", "Nov", "Dec"]
OEE_PAGE_FILTER_PREFIX = {
    "Dashboard": "oee_dashboard_inline", "Daily": "oee_daily_inline", "Weekly": "oee_weekly_inline",
    "Monthly": "oee_monthly_inline", "Yearly": "oee_yearly_inline",
}
OEE_PAGE_VIEW_PREFIX = {
    "Dashboard": "oee_dashboard_clean", "Daily": "oee_daily_clean", "Weekly": "oee_weekly_clean",
    "Monthly": "oee_monthly_clean", "Yearly": "oee_yearly_clean",
}
OEE_PAGE_PERIOD_KEY = {
    "Daily": "oee_daily_selected_date", "Weekly": "oee_weekly_selected_week",
    "Monthly": "oee_monthly_selected_month", "Yearly": "oee_yearly_selected_year",
}
OEE_LEVEL_TARGET_PAGE = {"day": "Daily", "week": "Weekly", "month": "Monthly"}
OEE_X_COL_LEVEL = {"Datum": "day", "Week": "week", "Mesec": "month"}
_OEE_COLOR_NEUTRAL = "#94A3B8"
_OEE_COLOR_RUN = "#22D3EE"


def _sr_pct(value, decimals=2):
    try:
        value = float(value)
    except Exception:
        value = 0.0
    return f"{value:.{decimals}f}".replace(".", ",") + " %"


def _sr_num(value):
    """Serbian number format: 1.234 or 1.234,5."""
    try:
        value = float(value)
    except Exception:
        value = 0.0
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}".replace(",", ".")
    return f"{value:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _share(part, whole):
    try:
        part, whole = float(part), float(whole)
    except Exception:
        return 0.0
    if whole <= 0:
        return 0.0
    return max(0.0, min(100.0, part / whole * 100.0))


def oee_drill_value_col(drill_metric, metric_col):
    availability_col, performance_col = get_oee_component_columns(metric_col)
    return {"oee": metric_col, "a": availability_col, "p": performance_col, "q": "Quality_%"}.get(drill_metric, metric_col)


def oee_period_slots(period_base, level):
    """Calendar slots for a chart, including periods without entries.

    level = day   -> full Mon-Sun weeks for short ranges (so one entered day still
                     shows its whole week), every day for ranges up to ~3 months
            week  -> every ISO week between the first and last entry
            month -> all 12 months of the year (or every month between the ends)
    Returns (rows with a _pkey column, list of slot dicts).
    """
    work = period_base.copy()
    if work.empty or "Datum" not in work.columns:
        return work, []
    work["Datum"] = parse_oee_date_series(work["Datum"])
    work = work.dropna(subset=["Datum"])
    if work.empty:
        return work, []
    dates = work["Datum"].dt.normalize()
    if level == "week":
        iso = dates.dt.isocalendar()
        work["_pkey"] = iso["year"].astype(int).astype(str) + "-W" + iso["week"].astype(int).map(lambda w: f"{int(w):02d}")
    elif level == "month":
        work["_pkey"] = dates.dt.strftime("%Y-%m")
    else:
        work["_pkey"] = dates.dt.strftime("%Y-%m-%d")

    first, last = dates.min(), dates.max()
    slots = []
    if level == "week":
        if first.year == last.year and first.month == last.month:
            # Monthly view: show every week of the month, also the ones without entries.
            first = first.replace(day=1)
            last = first + pd.offsets.MonthEnd(0)
        monday = first - pd.Timedelta(days=int(first.weekday()))
        multi_year = int(first.isocalendar()[0]) != int(last.isocalendar()[0])
        while monday <= last:
            iso_year, iso_week = int(monday.isocalendar()[0]), int(monday.isocalendar()[1])
            sunday = monday + pd.Timedelta(days=6)
            slots.append({
                "key": f"{iso_year}-W{iso_week:02d}",
                "label": f"{iso_year}-CW{iso_week:02d}" if multi_year else f"CW{iso_week:02d}",
                "title": f"{iso_year}-CW{iso_week:02d} · {monday.strftime('%d.%m')}–{sunday.strftime('%d.%m.%Y')}",
                "period": (iso_year, iso_week),
            })
            monday += pd.Timedelta(days=7)
    elif level == "month":
        years = sorted(set(int(y) for y in dates.dt.year.tolist()))
        if len(years) == 1:
            months = [pd.Timestamp(years[0], m, 1) for m in range(1, 13)]
        else:
            months = list(pd.date_range(first.replace(day=1), last.replace(day=1), freq="MS"))
        for month in months:
            name = _SR_MONTHS[month.month - 1]
            slots.append({
                "key": month.strftime("%Y-%m"),
                "label": name if len(years) == 1 else f"{name} {month.year}",
                "title": f"{name} {month.year}",
                "period": (int(month.year), int(month.month)),
            })
    else:
        if (last - first).days <= 13:
            start = first - pd.Timedelta(days=int(first.weekday()))
            end = last + pd.Timedelta(days=6 - int(last.weekday()))
        else:
            start, end = first, last
        if (end - start).days <= 93:
            days = list(pd.date_range(start, end, freq="D"))
        else:
            days = [pd.Timestamp(d) for d in sorted(dates.unique())]
        for day in days:
            weekday = _SR_WEEKDAYS[int(day.weekday())]
            slots.append({
                "key": day.strftime("%Y-%m-%d"),
                "label": f"{weekday} {day.strftime('%d.%m')}",
                "title": f"{weekday} {day.strftime('%d.%m.%Y')}",
                "period": day.date(),
            })

    present = set(work["_pkey"].astype(str).unique().tolist())
    known = {slot["key"] for slot in slots}
    for key in sorted(present - known):  # safety net, never drop a period that has data
        slots.append({"key": key, "label": key, "title": key, "period": None})
    labels_seen = set()
    for slot in slots:
        slot["has"] = slot["key"] in present
        if slot["label"] in labels_seen:  # category labels must be unique on the axis
            slot["label"] = slot["title"]
        labels_seen.add(slot["label"])
    return work, slots


def _oee_y_axis(values, show_target):
    candidates = [float(v) for v in values if v is not None]
    if show_target:
        candidates.append(OEE_CHART_TARGET)
    if not candidates:
        return 0, [0, 25, 50, 75, 100]
    low = max(0.0, min(candidates) - 8.0)
    y_min = int(low // 5) * 5
    step = 5 if 100 - y_min <= 30 else (10 if 100 - y_min <= 60 else 20)
    ticks = [v for v in range(0, 101, step) if v >= y_min]
    return y_min, ticks


def build_oee_drill_figure(slots, values, selected_key, title, value_label, show_target, height=380):
    """Trend chart with every calendar slot; one point -> bar, several -> line.

    A transparent full-height column sits behind every slot, so a click anywhere
    in the column selects that period (easier than hitting a small marker).
    """
    labels = [slot["label"] for slot in slots]
    data_values = [values.get(slot["key"]) if slot.get("has") else None for slot in slots]
    present = [v for v in data_values if v is not None]
    y_min, ticks = _oee_y_axis(present, show_target)
    y_top = 107

    fig = go.Figure()
    hover = [
        f"<b>{slot['title']}</b><br>{value_label}: {_sr_pct(v)}" if v is not None else f"<b>{slot['title']}</b><br>nema unosa"
        for slot, v in zip(slots, data_values)
    ]
    fig.add_trace(go.Bar(
        x=labels,
        y=[y_top - y_min] * len(labels),
        base=[y_min] * len(labels),
        width=0.9,
        marker=dict(
            color=["rgba(148,163,184,0.05)" if v is not None else "rgba(148,163,184,0.025)" for v in data_values],
            line=dict(width=0),
        ),
        customdata=[slot["key"] for slot in slots],
        hovertext=hover,
        hovertemplate="%{hovertext}<extra></extra>",
        selected=dict(marker=dict(opacity=1)),
        unselected=dict(marker=dict(opacity=1)),
        showlegend=False,
        name="period",
    ))
    colors = [get_oee_chart_status_color(v) if v is not None else "rgba(0,0,0,0)" for v in data_values]
    texts = [_sr_pct(v) if v is not None else "" for v in data_values]
    if len(present) >= 2:
        fig.add_trace(go.Scatter(
            x=labels,
            y=data_values,
            mode="lines+markers+text",
            connectgaps=False,
            line=dict(color="#38BDF8", width=3),
            marker=dict(size=13, color=colors, line=dict(width=2, color="#0A1120")),
            text=texts,
            textposition="top center",
            textfont=dict(size=11, color="#E6EDF7"),
            customdata=[slot["key"] for slot in slots],
            hoverinfo="skip",
            selected=dict(marker=dict(opacity=1)),
            unselected=dict(marker=dict(opacity=1)),
            showlegend=False,
            name=value_label,
        ))
    else:
        fig.add_trace(go.Bar(
            x=labels,
            y=data_values,
            width=0.5,
            marker=dict(color=colors, line=dict(width=0)),
            text=texts,
            textposition="outside",
            textfont=dict(size=12, color="#E6EDF7"),
            cliponaxis=False,
            customdata=[slot["key"] for slot in slots],
            hoverinfo="skip",
            selected=dict(marker=dict(opacity=1)),
            unselected=dict(marker=dict(opacity=1)),
            showlegend=False,
            name=value_label,
        ))

    keys = [slot["key"] for slot in slots]
    if selected_key in keys:
        index = keys.index(selected_key)
        fig.add_shape(
            type="rect", xref="x", yref="paper", x0=index - 0.47, x1=index + 0.47, y0=0, y1=1,
            fillcolor="rgba(244,63,94,0.10)", line=dict(color="rgba(244,63,94,0.85)", width=1.5), layer="below",
        )
    if show_target:
        fig.add_shape(
            type="line", xref="paper", yref="y", x0=0, x1=1, y0=OEE_CHART_TARGET, y1=OEE_CHART_TARGET,
            line=dict(color="#FBBF24", width=2, dash="dash"),
        )
        fig.add_annotation(
            xref="paper", yref="y", x=1, y=OEE_CHART_TARGET, xanchor="right", yanchor="bottom",
            text=f"cilj {OEE_CHART_TARGET:.0f} %", showarrow=False, font=dict(color="#FBBF24", size=11),
        )

    fig = style_chart(fig)
    fig.update_layout(
        title=dict(text=title),
        height=height,
        barmode="overlay",
        showlegend=False,
        clickmode="event+select",
        margin=dict(l=52, r=20, t=56, b=60 if len(labels) > 12 else 44),
    )
    fig.update_xaxes(type="category", categoryorder="array", categoryarray=labels,
                     tickangle=-45 if len(labels) > 12 else 0)
    fig.update_yaxes(range=[y_min, y_top], tickvals=ticks, ticksuffix=" %", title=None)
    return fig


def plot_oee_ranking(data, label_col, value_col, title, key, selectable=False, extra=None, flags=None):
    """Horizontal ranking: one row per machine, fixed bar thickness.

    The chart height grows with the number of machines (one machine = one
    compact row instead of one bar stretched across the whole screen).
    Returns the clicked label when selectable.
    """
    if data is None or data.empty or value_col not in data.columns:
        st.info("Nema podataka za rang.")
        return None
    chart_df = data.copy()
    chart_df[value_col] = pd.to_numeric(chart_df[value_col], errors="coerce").fillna(0).clip(lower=0, upper=100)
    chart_df = chart_df.sort_values(value_col, ascending=False).reset_index(drop=True)
    raw_labels = chart_df[label_col].astype(str).tolist()
    ranked = [f"#{i + 1}  {label}" for i, label in enumerate(raw_labels)]
    values = chart_df[value_col].tolist()
    count = len(values)
    labels_rev, values_rev, raw_rev = ranked[::-1], values[::-1], raw_labels[::-1]

    fig = go.Figure(go.Bar(
        x=values_rev,
        y=labels_rev,
        orientation="h",
        width=0.62,
        marker=dict(color=[get_oee_chart_status_color(v) for v in values_rev], line=dict(width=0)),
        text=[_sr_pct(v) + (f" · {(extra or {}).get(l, '')}" if (extra or {}).get(l) else "")
              + (" · ⚠ malo podataka" if (flags or {}).get(l) else "") for v, l in zip(values_rev, raw_rev)],
        textposition="outside",
        textfont=dict(size=12, color="#E6EDF7"),
        cliponaxis=False,
        customdata=raw_rev,
        hovertemplate="<b>%{y}</b><br>%{x:.2f} %<extra></extra>",
        showlegend=False,
    ))
    fig.add_shape(
        type="line", xref="x", yref="paper", x0=OEE_CHART_TARGET, x1=OEE_CHART_TARGET, y0=0, y1=1,
        line=dict(color="#FBBF24", width=2, dash="dash"),
    )
    fig.add_annotation(
        xref="x", yref="paper", x=OEE_CHART_TARGET, y=1, yanchor="bottom",
        text=f"cilj {OEE_CHART_TARGET:.0f} %", showarrow=False, font=dict(color="#FBBF24", size=11),
    )
    fig = style_chart(fig)
    fig.update_layout(
        title=dict(text=title),
        height=max(150, 78 + 44 * count),
        margin=dict(l=10, r=230 if extra else 72, t=56, b=30),
        showlegend=False,
        clickmode="event+select",
    )
    fig.update_xaxes(range=[0, 100], dtick=25, ticksuffix=" %", showgrid=True,
                     gridcolor="rgba(148,163,184,0.12)", griddash="dot")
    fig.update_yaxes(type="category", automargin=True, tickfont=dict(size=12, color="#E6EDF7"))
    if not selectable:
        st.plotly_chart(fig, use_container_width=True, key=key)
        return None
    seen_key = f"{key}_seen"
    picked = None
    points = _oee_chart_points(key)
    signature = repr([(p.get("y"), p.get("customdata")) for p in points])
    if points and st.session_state.get(seen_key) != signature:
        point = points[-1]
        custom = point.get("customdata")
        if isinstance(custom, (list, tuple)):
            custom = custom[0] if custom else None
        if custom in raw_labels:
            picked = custom
        else:
            label = str(point.get("y") or "")
            picked = raw_labels[ranked.index(label)] if label in ranked else None
        st.session_state[f"{key}_picked"] = picked
    st.session_state[seen_key] = signature
    _plotly_selectable(fig, key)
    picked = st.session_state.get(f"{key}_picked")
    return picked if picked in raw_labels else None


def _oee_chart_points(chart_key):
    """Points clicked in a selectable plotly chart (works with Streamlit's PlotlyState)."""
    state = st.session_state.get(chart_key) if chart_key in st.session_state else None
    if state is None:
        return []
    try:
        selection = state.get("selection") if isinstance(state, dict) else getattr(state, "selection", None)
        if selection is None:
            return []
        points = selection.get("points") if isinstance(selection, dict) else getattr(selection, "points", None)
    except Exception:
        return []
    result = []
    for point in points or []:
        if isinstance(point, dict):
            result.append(point)
        else:
            result.append({name: getattr(point, name, None) for name in ("x", "y", "customdata", "point_index")})
    return result


def _plotly_selectable(fig, key):
    try:
        return st.plotly_chart(fig, use_container_width=True, key=key, on_select="rerun", selection_mode="points")
    except TypeError:  # very old Streamlit: chart without click
        return st.plotly_chart(fig, use_container_width=True, key=key)


def oee_detail_card_data(rows, drill_metric, metric_col):
    """Numbers for the detail card under a clicked bar (pure function, tested)."""
    if rows is None or rows.empty:
        return None
    agg = aggregate_oee(rows.assign(_OEE_T="T"), ["_OEE_T"])
    if agg.empty:
        return None
    r = agg.iloc[0]
    availability_col, performance_col = get_oee_component_columns(metric_col)
    machine_variant = str(availability_col).startswith("Machine")
    open_time = float(r.get("Open_Time", 0) or 0)
    down = float(r.get("Down_Time", 0) or 0)
    org = float(r.get("Organisational_Loss", 0) or 0)
    run_time = float(r.get("Machine_Run_Time" if machine_variant else "Plant_Run_Time", 0) or 0)
    available = max(open_time - org, 0.0) if machine_variant else open_time
    ok = float(r.get("OK_pcs", 0) or 0)
    nok = float(r.get("NOK_pcs", 0) or 0)
    total = float(r.get("Total_Pcs", 0) or 0)
    target = float(r.get("Target_pcs", 0) or 0)
    ideal = float(r.get("Ideal_Time_min", 0) or 0)
    value = float(r.get(oee_drill_value_col(drill_metric, metric_col), 0) or 0)
    a_val = float(r.get(availability_col, 0) or 0)
    p_val = float(r.get(performance_col, 0) or 0)
    q_val = float(r.get("Quality_%", 0) or 0)

    def tile(label, shown, progress, color, sub):
        return {"label": label, "value": shown, "pw": float(progress), "color": color, "sub": sub}

    segments, formula = [], ""
    if drill_metric == "a":
        tiles = [
            tile("Vreme zastoja", f"{_sr_num(down)} min", _share(down, open_time), ui.COLORS["alarm"],
                 f"{_sr_pct(_share(down, open_time), 1)} otvorenog vremena"),
            tile("Organizacioni gubici", f"{_sr_num(org)} min", _share(org, open_time), ui.COLORS["warn"],
                 f"{_sr_pct(_share(org, open_time), 1)} otvorenog vremena"),
            tile("Radno vreme", f"{_sr_num(run_time)} min", _share(run_time, open_time), _OEE_COLOR_RUN,
                 f"od {_sr_num(open_time)} min otvorenog vremena"),
        ]
        segments = [
            {"label": f"Radno {_sr_num(run_time)} min", "value": run_time, "color": _OEE_COLOR_RUN},
            {"label": f"Zastoj {_sr_num(down)} min", "value": down, "color": ui.COLORS["alarm"]},
            {"label": f"Org. gubici {_sr_num(org)} min", "value": org, "color": ui.COLORS["warn"]},
        ]
        if machine_variant:
            formula = (f"Dostupnost = (otvoreno − zastoj − org. gubici) / (otvoreno − org. gubici) = "
                       f"{_sr_num(run_time)} / {_sr_num(available)} min = {_sr_pct(value)}")
        else:
            formula = f"Dostupnost = (otvoreno − zastoj) / otvoreno = {_sr_num(run_time)} / {_sr_num(open_time)} min = {_sr_pct(value)}"
    elif drill_metric == "p":
        diff = total - target
        tiles = [
            tile("Ukupno komada", _sr_num(total), _share(total, target) if target > 0 else 100.0,
                 get_oee_chart_status_color(value), "OK + NOK"),
            tile("Target komada", _sr_num(target) if target > 0 else "—", 100.0 if target > 0 else 0.0,
                 _OEE_COLOR_NEUTRAL, "plan iz OEE unosa (Target pcs.)"),
            tile("Razlika", (f"+{_sr_num(diff)}" if diff > 0 else _sr_num(diff)) + " kom" if target > 0 else "—",
                 _share(abs(diff), target), ui.COLORS["ok"] if diff >= 0 else ui.COLORS["alarm"],
                 ("target ostvaren" if diff >= 0 else "ispod targeta") if target > 0 else "target nije unet"),
        ]
        if target > 0:
            scale = max(total, target)
            segments = [
                {"label": f"Ukupno {_sr_num(total)} kom", "value": min(total, scale), "color": get_oee_chart_status_color(value)},
                {"label": f"Do targeta {_sr_num(max(target - total, 0))} kom", "value": max(target - total, 0.0),
                 "color": "rgba(148,163,184,0.35)"},
            ]
        if performance_col == "Performance_Target_%":
            formula = f"Performanse = OK / target = {_sr_num(ok)} / {_sr_num(target)} kom = {_sr_pct(value)}"
        else:
            possible = total * run_time / ideal if ideal > 0 else 0.0
            formula = (f"Performanse (CT) = idealno vreme / radno vreme = {_sr_num(round(ideal, 1))} / {_sr_num(run_time)} min "
                       f"= {_sr_pct(value)} · po CT-u moguće ≈ {_sr_num(round(possible))} kom")
    elif drill_metric == "q":
        tiles = [
            tile("OK komada", _sr_num(ok), _share(ok, total), ui.COLORS["ok"], f"{_sr_pct(_share(ok, total))} od ukupno"),
            tile("NOK komada", _sr_num(nok), _share(nok, total), ui.COLORS["alarm"], f"{_sr_pct(_share(nok, total))} od ukupno"),
            tile("Ukupno", _sr_num(total), 100.0 if total > 0 else 0.0, _OEE_COLOR_NEUTRAL, "OK + NOK"),
        ]
        segments = [
            {"label": f"OK {_sr_num(ok)}", "value": ok, "color": ui.COLORS["ok"]},
            {"label": f"NOK {_sr_num(nok)}", "value": nok, "color": ui.COLORS["alarm"]},
        ]
        formula = f"Kvalitet = OK / ukupno = {_sr_num(ok)} / {_sr_num(total)} = {_sr_pct(value)}"
    else:
        tiles = [
            tile("Dostupnost", _sr_pct(a_val), a_val, get_oee_chart_status_color(a_val),
                 f"radno {_sr_num(run_time)} od {_sr_num(available)} min"),
            tile("Performanse", _sr_pct(p_val), p_val, get_oee_chart_status_color(p_val),
                 f"{_sr_num(total)} kom" + (f" · target {_sr_num(target)}" if target > 0 else "")),
            tile("Kvalitet", _sr_pct(q_val), q_val, get_oee_chart_status_color(q_val), f"{_sr_num(ok)} OK · {_sr_num(nok)} NOK"),
        ]
        formula = (f"OEE = Dostupnost × Performanse × Kvalitet = {_sr_pct(a_val)} × {_sr_pct(p_val)} × {_sr_pct(q_val)} "
                   f"= {_sr_pct(value)}")

    impact_title, impact = oee_impact_list(rows, drill_metric, metric_col)
    return {
        "value": value, "tiles": tiles, "segments": segments, "formula": formula,
        "impact_title": impact_title, "impact": impact,
        "raw": {"open": open_time, "down": down, "org": org, "run": run_time, "ok": ok, "nok": nok,
                "total": total, "target": target, "ideal": ideal, "a": a_val, "p": p_val, "q": q_val},
    }


def oee_impact_list(rows, drill_metric, metric_col, limit=3):
    """The machines that pulled the clicked period down the most."""
    if rows is None or rows.empty or "Machine" not in rows.columns or rows["Machine"].nunique() < 2:
        return "", []
    by_machine = aggregate_oee(rows, ["Machine"])
    if by_machine.empty:
        return "", []
    value_col = oee_drill_value_col(drill_metric, metric_col)
    items = []
    if drill_metric == "a":
        by_machine["_loss"] = by_machine["Down_Time"] + by_machine["Organisational_Loss"]
        for _, m in by_machine[by_machine["_loss"] > 0].sort_values("_loss", ascending=False).head(limit).iterrows():
            items.append((str(m["Machine"]), f"{_sr_num(m['Down_Time'])} min zastoja · {_sr_num(m['Organisational_Loss'])} min org. gubitaka",
                          ui.COLORS["alarm"]))
        return "Najviše izgubljenog vremena", items
    if drill_metric == "q":
        for _, m in by_machine[by_machine["NOK_pcs"] > 0].sort_values("NOK_pcs", ascending=False).head(limit).iterrows():
            items.append((str(m["Machine"]), f"{_sr_num(m['NOK_pcs'])} NOK ({_sr_pct(_share(m['NOK_pcs'], m['Total_Pcs']), 1)})",
                          ui.COLORS["alarm"]))
        return "Najviše NOK komada", items
    if drill_metric == "p" and float(by_machine["Target_pcs"].sum()) > 0:
        by_machine["_short"] = by_machine["Target_pcs"] - by_machine["Total_Pcs"]
        for _, m in by_machine[by_machine["_short"] > 0].sort_values("_short", ascending=False).head(limit).iterrows():
            items.append((str(m["Machine"]), f"{_sr_num(m['_short'])} kom ispod targeta", ui.COLORS["warn"]))
        return "Najveći manjak komada", items
    for _, m in by_machine.sort_values(value_col, ascending=True).head(limit).iterrows():
        items.append((str(m["Machine"]), _sr_pct(m[value_col]), get_oee_chart_status_color(m[value_col])))
    return "Najslabije mašine", items


def render_oee_detail_card(rows, drill_metric, metric_col, title):
    data = oee_detail_card_data(rows, drill_metric, metric_col)
    if data is None:
        st.markdown(ui.drill_empty_html(title, "Nema unosa za ovaj period."), unsafe_allow_html=True)
        return None
    entries = len(rows)
    badge = f"{entries} {'unos' if entries == 1 else 'unosa'}"
    header = f"{title} · {OEE_DRILL_LABELS.get(drill_metric, 'OEE')} {_sr_pct(data['value'])}"
    st.markdown(ui.drill_card_html(header, badge, data), unsafe_allow_html=True)
    return data


def _oee_apply_chart_click(chart_key, selection_key, slots):
    """Turn a new click in the chart into the selected period (read before drawing)."""
    points = _oee_chart_points(chart_key)
    signature = repr([(p.get("x"), p.get("customdata")) for p in points])
    seen_key = f"{chart_key}_seen"
    if points and st.session_state.get(seen_key) != signature:
        point = points[-1]
        custom = point.get("customdata")
        if isinstance(custom, (list, tuple)):
            custom = custom[0] if custom else None
        keys = {slot["key"] for slot in slots}
        picked = custom if custom in keys else None
        if picked is None:
            by_label = {slot["label"]: slot["key"] for slot in slots}
            picked = by_label.get(str(point.get("x")))
        if picked:
            st.session_state[selection_key] = picked
    st.session_state[seen_key] = signature


def _oee_filter_values(prefix):
    if not prefix:
        return {}
    return {suffix: st.session_state[f"{prefix}_{suffix}"]
            for suffix in ("project", "process", "machine", "metric") if f"{prefix}_{suffix}" in st.session_state}


def _oee_drill_navigate(target_page, period_value, src_page, crumb_label, drill_metric):
    """Button callback (runs before the next script run, so widget keys may be set)."""
    state = st.session_state
    src_prefix = OEE_PAGE_FILTER_PREFIX.get(src_page)
    filters = _oee_filter_values(src_prefix)
    dst_prefix = OEE_PAGE_FILTER_PREFIX.get(target_page)
    if dst_prefix:
        for suffix, value in filters.items():
            state[f"{dst_prefix}_{suffix}"] = value
    trail = list(state.get("oee_drill_trail") or [])
    if state.get("oee_drill_leaf") != src_page:
        trail = []
    src_period_key = OEE_PAGE_PERIOD_KEY.get(src_page)
    trail.append({
        "label": crumb_label, "page": src_page, "filters": filters,
        "period": state.get(src_period_key) if src_period_key else None,
    })
    state["oee_drill_trail"] = trail[-4:]
    state["oee_drill_leaf"] = target_page
    period_key = OEE_PAGE_PERIOD_KEY.get(target_page)
    if period_key and period_value is not None:
        state[period_key] = period_value
    view_prefix = OEE_PAGE_VIEW_PREFIX.get(target_page)
    if view_prefix:
        state[f"{view_prefix}_drill_metric"] = drill_metric
        state.pop(f"{view_prefix}_drill_sel", None)
    state["oee_page_selector"] = target_page


def _oee_drill_back(index):
    state = st.session_state
    trail = list(state.get("oee_drill_trail") or [])
    if index < 0 or index >= len(trail):
        return
    crumb = trail[index]
    page = crumb.get("page")
    prefix = OEE_PAGE_FILTER_PREFIX.get(page)
    if prefix:
        for suffix, value in (crumb.get("filters") or {}).items():
            state[f"{prefix}_{suffix}"] = value
    period_key = OEE_PAGE_PERIOD_KEY.get(page)
    if period_key and crumb.get("period") is not None:
        state[period_key] = crumb["period"]
    state["oee_drill_trail"] = trail[:index]
    state["oee_drill_leaf"] = page
    state["oee_page_selector"] = page


def render_oee_drill_trail(current_page):
    """Breadcrumb after drilling down: 2026 › 2026-10 › 2026-CW43 › (this page)."""
    trail = st.session_state.get("oee_drill_trail") or []
    if not trail:
        return
    if st.session_state.get("oee_drill_leaf") != current_page:
        st.session_state["oee_drill_trail"] = []
        return
    columns = st.columns([1] * len(trail) + [max(1, 6 - len(trail))])
    for index, crumb in enumerate(trail):
        with columns[index]:
            st.button(f"← {crumb.get('label', '')}", key=f"oee_drill_crumb_{index}", on_click=_oee_drill_back,
                      args=(index,), use_container_width=True)


def _render_oee_sub_period(rows, level, drill_metric, metric_col, slot_title, key_prefix):
    """Inside the clicked period: its weeks (month), its days (week) or its machines (day)."""
    value_col = oee_drill_value_col(drill_metric, metric_col)
    label = OEE_DRILL_LABELS.get(drill_metric, "OEE")
    show_target = drill_metric == "oee"
    if level in ("month", "week"):
        child = "week" if level == "month" else "day"
        sub_work, sub_slots = oee_period_slots(rows, child)
        if not any(slot["has"] for slot in sub_slots):
            return
        sub = aggregate_oee(sub_work, ["_pkey"])
        values = dict(zip(sub["_pkey"].astype(str), pd.to_numeric(sub[value_col], errors="coerce").fillna(0).astype(float)))
        title = ("Nedelje u periodu" if child == "week" else "Dani u nedelji") + f" {slot_title} · {label}"
        fig = build_oee_drill_figure(sub_slots, values, None, title, label, show_target, height=280)
        st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_drill_sub")
    elif "Machine" in rows.columns and rows["Machine"].nunique() > 1:
        by_machine = aggregate_oee(rows, ["Machine"])
        plot_oee_ranking(by_machine, "Machine", value_col, f"Mašine · {slot_title} · {label}", f"{key_prefix}_drill_sub")


def render_oee_drilldown(period_base, metric_col, machine_filter, period_label, level, key_prefix, page_name=None):
    """One trend chart with a metric switch; click a period -> detail card below."""
    work, slots = oee_period_slots(period_base, level)
    if not slots or not any(slot["has"] for slot in slots):
        st.warning("Nema podataka za trend.")
        return
    metric_key = f"{key_prefix}_drill_metric"
    if st.session_state.get(metric_key) not in OEE_DRILL_METRICS:
        st.session_state[metric_key] = "oee"
    drill_metric = st.radio(
        "Pokazatelj na grafikonu", OEE_DRILL_METRICS, horizontal=True, key=metric_key,
        format_func=lambda m: OEE_DRILL_LABELS.get(m, m), label_visibility="collapsed",
    )
    value_col = oee_drill_value_col(drill_metric, metric_col)
    label = OEE_DRILL_LABELS.get(drill_metric, "OEE")
    trend = aggregate_oee(work, ["_pkey"])
    values = dict(zip(trend["_pkey"].astype(str), pd.to_numeric(trend[value_col], errors="coerce").fillna(0).astype(float)))

    selection_key = f"{key_prefix}_drill_sel"
    chart_key = f"{key_prefix}_drill_chart_{drill_metric}"
    _oee_apply_chart_click(chart_key, selection_key, slots)
    keys = [slot["key"] for slot in slots]
    selected = st.session_state.get(selection_key)
    if selected not in keys:
        selected = [slot["key"] for slot in slots if slot["has"]][-1]
        st.session_state[selection_key] = selected
    slot = slots[keys.index(selected)]

    fig = build_oee_drill_figure(
        slots, values, selected, f"{label} · {period_label}", label,
        show_target=(drill_metric == "oee" and metric_col != "IWON_OEE_%"),
    )
    _plotly_selectable(fig, chart_key)
    st.caption("Klikni stubić ili tačku — ispod se otvaraju detalji tog perioda. Siva polja su periodi bez unosa.")

    rows = work[work["_pkey"].astype(str) == selected]
    render_oee_detail_card(rows, drill_metric, metric_col, slot["title"])
    if rows.empty:
        return
    if drill_metric == "a":
        render_loss_pareto(rows, title=f"Uzroci · {slot['title']}", compact=True)
    _render_oee_sub_period(rows, level, drill_metric, metric_col, slot["title"], key_prefix)

    target_page = OEE_LEVEL_TARGET_PAGE.get(level)
    current_page = page_name or st.session_state.get("oee_page_selector")
    if target_page and current_page and target_page != current_page and slot.get("period") is not None:
        crumb = "Dashboard" if current_page == "Dashboard" else period_label
        st.button(
            f"🔎 Otvori detaljnije: {slot['title']}",
            key=f"{key_prefix}_drill_open",
            on_click=_oee_drill_navigate,
            args=(target_page, slot["period"], current_page, crumb, drill_metric),
        )


def render_oee_machine_compare(period_base, metric_col, period_label, key_prefix):
    """Ranking of machines; click a machine -> its detail card."""
    machine_oee = aggregate_oee(period_base, ["Project", "Process", "Machine"])
    if machine_oee.empty:
        st.warning("Nema podataka za poređenje mašina.")
        return
    metric_label = OEE_METRIC_LABELS.get(metric_col, metric_col)
    extra = {str(r["Machine"]): f"{_sr_num(r['Total_Pcs'])} kom · {_sr_num(round(float(r['Machine_Run_Time']) / 60, 1))} h rada"
             for _, r in machine_oee.iterrows()}
    picked = plot_oee_ranking(machine_oee, "Machine", metric_col, f"{metric_label} · rang mašina · {period_label}",
                              f"{key_prefix}_machine_rank", selectable=True, extra=extra,
                              flags=oi.low_volume_flags(machine_oee))
    if picked:
        rows = period_base[period_base["Machine"].astype(str) == picked]
        render_oee_detail_card(rows, "oee", metric_col, f"{picked} · {period_label}")
    else:
        st.caption("Klikni mašinu za njen OEE, dostupnost, performanse i kvalitet.")


def _oee_index_kwargs(key, options):
    """Default to the newest period, but never pass index when the key is already
    set (drill-down navigation sets it) - Streamlit warns about both together."""
    if key in st.session_state and st.session_state.get(key) in list(options):
        return {}
    st.session_state.pop(key, None)
    return {"index": len(options) - 1 if options else 0}


# =========================
# v11: DOWNTIME CAUSES, OEE SETTINGS, PRIVATE IWON ACCESS
# =========================
OEE_EVENTS_SHEET_NAME = "DOWNTIME_EVENTS"
OEE_CAUSES_SHEET_NAME = "DOWNTIME_CAUSES"
OEE_SETTINGS_SHEET_NAME = "OEE_SETTINGS"
OEE_SETTINGS_COLUMNS = ["Setting", "Scope", "Value", "Updated_By", "Updated_At"]
IWON_COMPARE_SHEET_NAME = "IWON_COMPARE"
IWON_HISTORY_SHEET_NAME = "IWON_PLAN_HISTORY"
IWON_CAUSE_SHEET_NAME = "IWON_CAUSE_PLAN"
OEE_ACTION_PREFIX = "[OEE]"
OEE_ACTION_EXTRA_COLUMNS = ["Due_Date", "Source_Ref"]
SETTING_PRICE = "CENA_KOMADA"
SETTING_DESCRIPTION = "OPIS_PROCESA"
SETTING_MGMT_EMAIL = "UPRAVA_EMAIL"
SETTING_MGMT_EMAIL_ON = "UPRAVA_EMAIL_AKTIVNO"
OEE_REFERENCE = 85.0
OEE_GLOSSARY = {
    "OEE": "Ukupna efikasnost opreme: koliko je od vremena kad je linija trebalo da radi stvarno napravljeno dobrih "
           "komada punom brzinom. 100 % = bez zastoja, punom brzinom, bez škarta. OEE = Dostupnost × Performanse × Kvalitet.",
    "Dostupnost": "Deo raspoloživog vremena u kom mašina zaista radi. Smanjuju je kvarovi, podešavanja i čekanje.",
    "Performanse": "Koliko je komada napravljeno u odnosu na ono što je moguće za to radno vreme po zadatom ciklusu (CT). "
                   "Smanjuju je spor rad i kratka zaustavljanja.",
    "Kvalitet": "Deo dobrih (OK) komada od svih napravljenih. Ostatak je škart (NOK).",
    "Organizacioni gubici": "Vreme kad mašina može da radi, ali ne radi zbog organizacije: čeka materijal, nema operatera, sastanak.",
    "CT": "Vreme ciklusa: koliko sekundi treba za jedan komad kad sve radi kako treba.",
    "Referenca 85 %": "Svetski uobičajen nivo dobrog OEE-a za diskretnu proizvodnju; služi samo za poređenje.",
}


def _cell_raw(value):
    """Value for a RAW write: dates as dd.mm.yyyy text, numbers stay numbers."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.strftime("%d.%m.%Y")
    if isinstance(value, date):
        return value.strftime("%d.%m.%Y")
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _open_or_create_tab(sheet_id, name, columns, seed_rows=None):
    """Open a tab; create it (with header and optional seed rows) when missing.

    Only new tabs are ever created - existing tabs are never renamed or deleted.
    """
    spreadsheet = get_spreadsheet(sheet_id)
    try:
        return spreadsheet.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=name, rows=1000, cols=max(len(columns), 12))
        ws.update("A1", [list(columns)] + [[_cell_raw(v) for v in row] for row in (seed_rows or [])],
                  value_input_option="RAW")
        return ws


def _tab_frame(sheet_id, name, columns, seed_rows=None, live=False):
    ws = _open_or_create_tab(sheet_id, name, columns, seed_rows)
    with (fresh_reads() if live else _contextlib.nullcontext()):
        values = ws.get_all_values()
    headers = _ensure_sheet_headers(ws, columns, header_row=values[0] if values else [])
    if values:
        values = [headers] + values[1:]
    return ws, headers, _records_frame_from_values(values, columns)


def _row_for_headers(headers, columns, record):
    mapping = _canonical_header_map(headers, columns)
    by_norm = {_norm_sheet_col(k): v for k, v in record.items()}
    return [_cell_raw(record.get(mapping.get(i, h), by_norm.get(_norm_sheet_col(h), ""))) for i, h in enumerate(headers)]


def _known_width(headers, columns):
    """Number of leading columns that belong to us (user columns to the right stay untouched)."""
    mapping = _canonical_header_map(headers, columns)
    known = set(columns)
    width = 0
    for index in range(len(headers)):
        if mapping.get(index) in known:
            width = index + 1
        else:
            break
    return max(width, 1)


def _append_tab_rows(ws, headers, columns, records):
    rows = [_row_for_headers(headers, columns, r) for r in records]
    if rows:
        ws.append_rows(rows, value_input_option="RAW", table_range="A1")


def _upsert_tab_rows(ws, headers, columns, existing, key_cols, records):
    """Update rows with the same key in place (one batch), append new ones."""
    width = _known_width(headers, columns)
    last_col = _column_number_to_letter(width)

    def key_of(item):
        return tuple(str(_cell_raw(item.get(k, ""))).strip().casefold() for k in key_cols)

    row_by_key = {}
    if existing is not None and not existing.empty:
        for _, row in existing.iterrows():
            row_by_key.setdefault(key_of(row), int(row["_row"]))
    updates, appends = [], []
    for record in records:
        values = _row_for_headers(headers, columns, record)[:width]
        target = row_by_key.get(key_of(record))
        if target:
            updates.append({"range": f"A{target}:{last_col}{target}", "values": [values]})
        else:
            appends.append(values)
    if updates:
        ws.batch_update(updates, value_input_option="RAW")
    if appends:
        ws.append_rows(appends, value_input_option="RAW", table_range="A1")
    return len(updates), len(appends)


# ---------------------------------------------------------------- settings
@st.cache_data(ttl=3600, show_spinner=False)
def load_oee_settings():
    try:
        _, _, df = _tab_frame(OEE_SHEET_ID, OEE_SETTINGS_SHEET_NAME, OEE_SETTINGS_COLUMNS)
    except Exception:
        return {}
    return {(str(r["Setting"]).strip().upper(), str(r["Scope"]).strip().casefold()): str(r["Value"]).strip()
            for _, r in df.iterrows() if str(r["Setting"]).strip()}


def oee_setting(setting, scope="", default=""):
    return load_oee_settings().get((str(setting).upper(), str(scope).strip().casefold()), default)


def save_oee_settings(records):
    """records: list of (setting, scope, value)."""
    ws, headers, df = _tab_frame(OEE_SHEET_ID, OEE_SETTINGS_SHEET_NAME, OEE_SETTINGS_COLUMNS, live=True)
    who = _current_user_display_name()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [{"Setting": str(s).upper(), "Scope": str(sc).strip(), "Value": v, "Updated_By": who, "Updated_At": now}
            for s, sc, v in records]
    _upsert_tab_rows(ws, headers, OEE_SETTINGS_COLUMNS, df, ["Setting", "Scope"], rows)
    load_oee_settings.clear()


def price_per_piece(project):
    raw = str(oee_setting(SETTING_PRICE, project, "") or "").replace(",", ".").strip()
    try:
        value = float(raw)
        return value if value > 0 else None
    except ValueError:
        return None


def process_description(project, process):
    return oee_setting(SETTING_DESCRIPTION, f"{project}|{process}", "")


# ---------------------------------------------------------------- causes & events
@st.cache_data(ttl=3600, show_spinner=False)
def load_downtime_causes():
    seed = [[t, c, l, "YES", i + 1] for i, (t, c, l) in enumerate(oi.DEFAULT_CAUSES)]
    try:
        _, _, df = _tab_frame(OEE_SHEET_ID, OEE_CAUSES_SHEET_NAME, oi.DOWNTIME_CAUSE_COLUMNS, seed_rows=seed)
    except Exception:
        return oi.default_causes_frame()
    return oi.clean_causes(df.drop(columns=["_row"], errors="ignore"))


def save_downtime_causes(edited):
    """Upsert the catalogue; removed causes are switched off (Active = NO), never deleted."""
    ws, headers, df = _tab_frame(OEE_SHEET_ID, OEE_CAUSES_SHEET_NAME, oi.DOWNTIME_CAUSE_COLUMNS, live=True)
    rows = []
    keep = set()
    for index, row in enumerate(edited.to_dict("records")):
        cause = str(row.get("Cause", "") or "").strip()
        if not cause:
            continue
        loss = str(row.get("Loss_Type", "") or "").strip()
        loss = loss if loss in oi.LOSS_TYPES else oi.LOSS_DOWNTIME
        lever = str(row.get("Lever", "") or "").strip().lower()
        lever = lever if lever in (oi.LEVER_FREQUENCY, oi.LEVER_DURATION) else oi.LEVER_DURATION
        active = "NO" if str(row.get("Active", "YES")).strip().upper() in ("NO", "NE", "FALSE", "0") else "YES"
        rows.append({"Loss_Type": loss, "Cause": cause, "Lever": lever, "Active": active, "Sort": index + 1})
        keep.add((loss.casefold(), cause.casefold()))
    for _, row in df.iterrows():
        if (str(row["Loss_Type"]).strip().casefold(), str(row["Cause"]).strip().casefold()) not in keep and str(row["Cause"]).strip():
            rows.append({"Loss_Type": row["Loss_Type"], "Cause": row["Cause"], "Lever": row["Lever"], "Active": "NO",
                         "Sort": row["Sort"]})
    _upsert_tab_rows(ws, headers, oi.DOWNTIME_CAUSE_COLUMNS, df, ["Loss_Type", "Cause"], rows)
    load_downtime_causes.clear()


def cause_options(loss_type=None):
    causes = load_downtime_causes()
    if loss_type:
        causes = causes[causes["Loss_Type"] == loss_type]
    return causes["Cause"].tolist()


@st.cache_data(ttl=300, show_spinner=False)
def load_app_downtime_events():
    try:
        _, _, df = _tab_frame(OEE_SHEET_ID, OEE_EVENTS_SHEET_NAME, oi.DOWNTIME_EVENT_COLUMNS)
    except Exception:
        return oi.normalize_events(None)
    return oi.normalize_events(df)


@st.cache_data(ttl=600, show_spinner=False)
def load_form_downtime_events():
    """Technicians' Google Form for downtime, read-only, mapped to the catalogue."""
    try:
        ws = get_worksheet(PROCESS_DOWNTIME_SHEET_ID, PROCESS_DOWNTIME_SHEET_NAME)
        values = ws.get_all_values()
        if not values:
            return oi.normalize_events(None)
        headers = [str(h).strip() for h in values[0]]
        frame = pd.DataFrame([r + [""] * (len(headers) - len(r)) for r in values[1:]], columns=headers)
        master, _missing = load_oee_master()
        return oi.normalize_events(oi.form_rows_to_events(frame, master, load_downtime_causes()))
    except Exception:
        return oi.normalize_events(None)


def load_all_downtime_events():
    """Downtime reasons entered in the app (OEE input). Forms of other departments are
    not mixed into OEE - the maintenance form is only compared (OEE → Zastoji vs održavanje)."""
    frames = [f for f in (load_app_downtime_events(),) if f is not None and not f.empty]
    if not frames:
        return oi.normalize_events(None)
    events = pd.concat(frames, ignore_index=True)
    return events.drop_duplicates(subset=["Event_ID"], keep="first").reset_index(drop=True)


def _now_local():
    return datetime.now(ZoneInfo("Europe/Belgrade")).replace(tzinfo=None)


def _new_event_id(prefix="DT"):
    return f"{prefix}-{_now_local():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"


def _shift_date(moment):
    """A night shift that runs past midnight belongs to the day it started."""
    return (moment - timedelta(days=1)).date() if moment.time() < time(6, 0) else moment.date()


def save_downtime_events(records):
    ws, headers, _df = _tab_frame(OEE_SHEET_ID, OEE_EVENTS_SHEET_NAME, oi.DOWNTIME_EVENT_COLUMNS, live=True)
    _append_tab_rows(ws, headers, oi.DOWNTIME_EVENT_COLUMNS, records)
    load_app_downtime_events.clear()


def start_downtime_event(project, process, machine, cause="", loss_type=oi.LOSS_DOWNTIME, note=""):
    now = _now_local()
    record = {
        "Event_ID": _new_event_id(), "Datum": _shift_date(now), "Shift": oi.shift_for_time(now.time()),
        "Project": project, "Process": process, "Machine": machine, "Loss_Type": loss_type, "Cause": cause,
        "Minutes": "", "Start_Time": now.strftime("%H:%M"), "End_Time": "", "Status": oi.STATUS_OPEN, "Note": note,
        "Source": oi.SOURCE_PHONE, "Entered_By": _current_user_display_name(),
        "Created_At": now.strftime("%Y-%m-%d %H:%M:%S"), "Updated_At": "",
    }
    save_downtime_events([record])
    return record


def finish_downtime_event(event_id, cause, note=""):
    """Close a running downtime: duration = now - start (across midnight too)."""
    ws, headers, df = _tab_frame(OEE_SHEET_ID, OEE_EVENTS_SHEET_NAME, oi.DOWNTIME_EVENT_COLUMNS, live=True)
    match = df[df["Event_ID"].astype(str).str.strip() == str(event_id).strip()]
    if match.empty:
        raise ValueError("Zastoj nije pronađen (možda ga je neko već završio).")
    row = match.iloc[0].to_dict()
    if str(row.get("Status", "")).strip() != oi.STATUS_OPEN:
        raise ValueError("Ovaj zastoj je već završen.")
    now = _now_local()
    day = oi._parse_date(row.get("Datum"))
    start_text = str(row.get("Start_Time", "") or "00:00")
    hours, minutes = (int(x) for x in re.match(r"^(\d{1,2})[:.](\d{2})", start_text).groups())
    started = datetime.combine(day.date(), time(hours % 24, minutes % 60))
    if started.time() < time(6, 0):
        started += timedelta(days=1)  # night shift: started after midnight of the shift date
    duration = max((now - started).total_seconds() / 60.0, 1.0)
    known = {c.Cause: c.Loss_Type for c in load_downtime_causes().itertuples(index=False)}
    row.update({
        "Cause": cause, "Loss_Type": known.get(cause, oi.LOSS_DOWNTIME), "Minutes": round(duration, 1),
        "End_Time": now.strftime("%H:%M"), "Status": oi.STATUS_DONE,
        "Note": note or row.get("Note", ""), "Updated_At": now.strftime("%Y-%m-%d %H:%M:%S"),
    })
    row.pop("_row", None)
    _upsert_tab_rows(ws, headers, oi.DOWNTIME_EVENT_COLUMNS, df, ["Event_ID"], [row])
    load_app_downtime_events.clear()
    return row


def replace_oee_allocation(day, project, process, machine, shift_label, allocation):
    """Causes typed in the OEE input replace earlier ones of the same shift entry."""
    ws, headers, df = _tab_frame(OEE_SHEET_ID, OEE_EVENTS_SHEET_NAME, oi.DOWNTIME_EVENT_COLUMNS, live=True)
    day = pd.Timestamp(day).normalize()
    code = oi.shift_code(shift_label)
    if not df.empty:
        dates = df["Datum"].map(oi._parse_date)
        old = df[
            (df["Source"].astype(str).str.strip() == oi.SOURCE_OEE) & (dates == day)
            & (df["Project"].astype(str).str.strip() == str(project).strip())
            & (df["Process"].astype(str).str.strip() == str(process).strip())
            & (df["Machine"].astype(str).str.strip() == str(machine).strip())
            & (df["Shift"].map(oi.shift_code) == code)
        ]
        if not old.empty:
            _delete_worksheet_rows_batch(ws, old["_row"].astype(int).tolist())
    now = _now_local().strftime("%Y-%m-%d %H:%M:%S")
    records = [{
        "Event_ID": _new_event_id("OEE"), "Datum": day, "Shift": code, "Project": project, "Process": process,
        "Machine": machine, "Loss_Type": item["Loss_Type"], "Cause": oi.clean_reason(item["Cause"]), "Minutes": item["Minutes"],
        "Start_Time": "", "End_Time": "", "Status": oi.STATUS_DONE, "Note": "", "Source": oi.SOURCE_OEE,
        "Entered_By": _current_user_display_name(), "Created_At": now, "Updated_At": "",
    } for item in allocation]
    if records:
        _append_tab_rows(ws, headers, oi.DOWNTIME_EVENT_COLUMNS, records)
    load_app_downtime_events.clear()


def allocation_editor_frame():
    return pd.DataFrame({"Uzrok": pd.Series([None, None, None], dtype="object"),
                         "Minuta": pd.Series([None, None, None], dtype="float")})


# ---------------------------------------------------------------- IWON access
def iwon_allowed_users():
    raw = _get_secret_value("IWON_USERS", ("iwon", "USERS"), default="")
    if isinstance(raw, (list, tuple)) or (hasattr(raw, "__iter__") and not isinstance(raw, (str, bytes, dict))):
        names = list(raw)
    else:
        names = re.split(r"[,;\s]+", str(raw or ""))
    # Tolerate any notation: ["Stefan"], 'Stefan', Stefan, stefan
    return {str(n).strip().strip("[]'\" ").casefold() for n in names if str(n).strip().strip("[]'\" ")}


def can_see_iwon(user=None):
    """IWON is private: only usernames listed in the IWON_USERS secret.

    The list lives in Streamlit secrets on purpose - nobody can grant himself
    access from inside the application (not even an administrator).
    """
    user = user or _session_user()
    username = str(user.get("username", "") or "").strip().casefold()
    return bool(username) and username in iwon_allowed_users()


# =========================
# v11: OEE FOR MANAGERS (clear without knowing the line)
# =========================
def _status_for_pct(value, reference=OEE_REFERENCE):
    try:
        value = float(value)
    except Exception:
        return "neutral"
    if value >= reference:
        return "ok"
    if value >= 70:
        return "warn"
    return "alarm"


def _oee_filter_scope(df, project=None, process=None, machine=None):
    if df is None or df.empty:
        return df
    out = df
    if project:
        out = out[out["Project"].astype(str) == str(project)]
    if process:
        out = out[out["Process"].astype(str) == str(process)]
    if machine and machine not in ("Sve", "ALL"):
        out = out[out["Machine"].astype(str) == str(machine)]
    return out


def _scope_machines(project, process, machine=None):
    if machine and machine not in ("Sve", "ALL"):
        return [str(machine)]
    try:
        master, _missing = load_oee_master()
        scoped = master[(master["Project"].astype(str) == str(project)) & (master["Process"].astype(str) == str(process))]
        return sorted(scoped["Machine"].astype(str).str.strip().unique().tolist())
    except Exception:
        return []


def oee_period_context(oee_base, period_rows, kind, project, process, machine, start=None, end=None, label=""):
    """Everything the manager summary needs about the period and the one before it."""
    start = pd.Timestamp(start).normalize() if start is not None else None
    end = pd.Timestamp(end).normalize() if end is not None else None
    previous = None
    if oee_base is not None and not oee_base.empty and start is not None and end is not None:
        scope = _oee_filter_scope(oee_base, project, process, machine)
        if kind == "day":
            earlier = scope[scope["Datum"] < start]
            if not earlier.empty:
                last = earlier["Datum"].max().normalize()
                previous = earlier[earlier["Datum"].dt.normalize() == last]
        elif kind == "month":
            prev_end = start - pd.Timedelta(days=1)
            prev_start = prev_end.replace(day=1)
            previous = scope[(scope["Datum"] >= prev_start) & (scope["Datum"] <= prev_end)]
        elif kind == "year":
            previous = scope[scope["Datum"].dt.year == start.year - 1]
        else:
            length = (end - start).days + 1
            previous = scope[(scope["Datum"] >= start - pd.Timedelta(days=length)) & (scope["Datum"] < start)]
        if previous is not None and previous.empty:
            previous = None
    period_names = {"day": "ovog dana", "week": "ove nedelje", "month": "ovog meseca", "year": "ove godine"}
    return {
        "kind": kind, "start": start, "end": end, "label": label, "project": project, "process": process,
        "machine": machine, "previous": previous, "period_name": period_names.get(kind, "u izabranom periodu"),
        "machines": _scope_machines(project, process, machine),
    }


def _top_loss_text(pareto):
    if pareto is None or pareto.empty:
        return None
    named = pareto[pareto["Cause"] != oi.UNCAUSED]
    if named.empty:
        return None
    row = named.iloc[0]
    return f"{row['Cause']} ({_sr_num(row['Minutes'])} min)"


def render_oee_manager_summary(period_base, metric_col, ctx):
    """Sentence + KPI tiles with change + losses + data coverage, above every OEE chart."""
    if period_base is None or period_base.empty:
        return
    project, process = ctx.get("project"), ctx.get("process")
    description = process_description(project, process) if project and process else ""
    if description:
        st.caption(f"{project} · {process} — {description}")
    summary = aggregate_oee_as_weighted_daily(period_base)
    if summary.empty:
        return
    row = summary.iloc[0]
    previous_row = None
    if ctx.get("previous") is not None:
        prev = aggregate_oee_as_weighted_daily(ctx["previous"])
        previous_row = prev.iloc[0] if not prev.empty else None
    availability_col, performance_col = get_oee_component_columns(metric_col)
    value = float(row.get(metric_col, 0) or 0)
    previous_value = float(previous_row.get(metric_col, 0)) if previous_row is not None else None

    events = load_all_downtime_events()
    pareto = oi.loss_pareto(events, period_base)
    cov = None
    if ctx.get("start") is not None and ctx.get("end") is not None:
        cov = oi.coverage(period_base, ctx["start"], ctx["end"], ctx.get("machines"), today=_now_local().date())
    metric_label = OEE_METRIC_LABELS.get(metric_col, "OEE")
    sentence = oi.headline(metric_label, value, previous_value, OEE_REFERENCE, ctx.get("period_name", ""),
                           _top_loss_text(pareto), cov)
    st.markdown(ui.headline_html(sentence, _status_for_pct(value)), unsafe_allow_html=True)

    if cov and cov.get("days_expected"):
        chips = [(f"Uneto {cov['days_entered']} od {cov['days_expected']} radnih dana", "ok" if cov["days_entered"] >= cov["days_expected"] else "warn")]
        if cov.get("machine_days_expected") and len(ctx.get("machines") or []) > 1:
            chips.append((f"{cov['machine_days_entered']} od {cov['machine_days_expected']} mašina-dana",
                          "ok" if cov["machine_days_entered"] >= cov["machine_days_expected"] else "warn"))
        if cov.get("missing_days"):
            chips.append(("Nedostaje: " + ", ".join(f"{_SR_WEEKDAYS[d.weekday()]} {d:%d.%m}" for d in cov["missing_days"][:6])
                          + (" …" if len(cov["missing_days"]) > 6 else ""), "warn"))
        if cov.get("last_day") is not None:
            chips.append((f"Poslednji uneti dan {pd.Timestamp(cov['last_day']):%d.%m.%Y}", "ok"))
        st.markdown(ui.coverage_chips_html(chips), unsafe_allow_html=True)

    def tile(label, column, glossary_key):
        current = float(row.get(column, 0) or 0)
        before = float(previous_row.get(column, 0)) if previous_row is not None else None
        foot, direction = oi.delta_text(current, before)
        return {"label": label, "value": _sr_pct(current, 1), "status": _status_for_pct(current),
                "foot": foot + (" od prethodnog perioda" if direction in ("up", "down") else ""),
                "foot_status": direction, "tooltip": OEE_GLOSSARY.get(glossary_key, "")}

    tiles = [
        tile(metric_label, metric_col, "OEE"),
        tile("Dostupnost", availability_col, "Dostupnost"),
        tile("Performanse", performance_col, "Performanse"),
        tile("Kvalitet", "Quality_%", "Kvalitet"),
    ]
    st.markdown(ui.stat_tiles_html(tiles), unsafe_allow_html=True)

    totals = aggregate_oee(period_base.assign(_T="T"), ["_T"])
    lost = oi.lost_summary(totals.iloc[0] if not totals.empty else {}, price_per_piece(project) if project else None)
    lost_tiles = [
        {"label": "Manje komada od targeta", "value": f"{_sr_num(round(lost['lost_pieces']))} kom",
         "status": "warn" if lost["lost_pieces"] > 0 else "ok",
         "sub": f"{_sr_num(lost['ok'])} OK · target {_sr_num(lost['target'])}"},
        {"label": "Izgubljeno vreme", "value": f"{lost['lost_hours']:.1f} h".replace(".", ","),
         "status": "alarm" if lost["lost_hours"] > 0 else "ok",
         "sub": f"zastoji {lost['down_hours']:.1f} h · org. gubici {lost['org_hours']:.1f} h".replace(".", ","),
         "tooltip": OEE_GLOSSARY["Organizacioni gubici"]},
    ]
    if lost.get("value") is not None:
        lost_tiles.append({"label": "Vrednost gubitka", "value": f"≈ {_sr_num(round(lost['value']))} €", "status": "alarm",
                           "sub": f"{_sr_num(round(lost['lost_pieces']))} kom × {_sr_num(lost['price'])} €/kom"})
    st.markdown(ui.stat_tiles_html(lost_tiles), unsafe_allow_html=True)
    with st.expander("Šta znače pojmovi?"):
        st.markdown("\n".join(f"- **{name}** — {text}" for name, text in OEE_GLOSSARY.items()))


def render_loss_pareto(rows, title="Zašto smo gubili vreme", compact=False):
    events = load_all_downtime_events()
    pareto = oi.loss_pareto(events, rows)
    if pareto.empty:
        if not compact:
            st.info("Za ovaj period nema zastoja ni organizacionih gubitaka.")
        return pareto
    named_minutes = float(pareto.loc[pareto["Cause"] != oi.UNCAUSED, "Minutes"].sum())
    if named_minutes <= 0 and not compact:
        st.info("Za ovaj period još nema unetih uzroka. Uzroci se unose u OEE unosu, ispod polja Zastoj i Organizacioni gubici.")
    top = pareto.head(6 if compact else 10)
    largest = float(top["Minutes"].max()) or 1.0
    colors = {oi.LOSS_DOWNTIME: "#EF4444", oi.LOSS_ORGANISATIONAL: "#F59E0B"}
    items = [{
        "label": r["Cause"], "pct": r["Minutes"] / largest * 100, "color": colors.get(r["Loss_Type"], "#64748B"),
        "value_html": f"<b>{_sr_num(round(r['Minutes'], 1))} min</b> · {_sr_num(round(r['Cum_%']))} %",
    } for _, r in top.iterrows()]
    total = float(pareto["Minutes"].sum())
    note = ("Crveno = zastoj mašine, žuto = organizacioni gubitak, sivo = stari unosi bez uzroka. "
            "Procenat je zbirni (Pareto).")
    st.markdown(ui.bar_rows_html(items, f"{title} · {_sr_num(round(total))} min", "" if compact else note), unsafe_allow_html=True)
    return pareto


def render_oee_shift_compare(period_base, metric_col):
    if period_base is None or period_base.empty or "Shift" not in period_base.columns:
        return
    by_shift = aggregate_oee(period_base.assign(_S=period_base["Shift"].astype(str).str.strip()), ["_S"])
    if by_shift.empty or len(by_shift) < 2 and str(by_shift.iloc[0]["_S"]).lower().startswith("all"):
        return
    order = {"1st": 0, "2nd": 1, "3rd": 2}
    by_shift["_o"] = by_shift["_S"].map(lambda s: order.get(oi.shift_code(s), 9))
    names = {"1st": "1. smena (06–14)", "2nd": "2. smena (14–22)", "3rd": "3. smena (22–06)", "ALL": "Sve smene (zbirni unos)"}
    items = [{
        "label": names.get(oi.shift_code(r["_S"]), r["_S"]), "pct": float(r[metric_col]),
        "color": get_oee_chart_status_color(r[metric_col]),
        "value_html": f"<b>{_sr_pct(r[metric_col], 1)}</b> · {_sr_num(r['Total_Pcs'])} kom",
    } for _, r in by_shift.sort_values("_o").iterrows()]
    st.markdown(ui.bar_rows_html(items, f"{OEE_METRIC_LABELS.get(metric_col, 'OEE')} po smenama"), unsafe_allow_html=True)


def load_oee_actions(project=None, process=None):
    tasks, errors = load_tasks_data()
    if errors or tasks is None or tasks.empty:
        return pd.DataFrame()
    title = tasks["Task_Title"].astype(str)
    ref = tasks["Source_Ref"].astype(str) if "Source_Ref" in tasks.columns else pd.Series("", index=tasks.index)
    actions = tasks[title.str.startswith(OEE_ACTION_PREFIX) | ref.str.startswith("OEE|")].copy()
    if actions.empty:
        return actions
    actions["_ref"] = ref.loc[actions.index]
    parts = actions["_ref"].str.split("|")
    actions["_project"] = parts.map(lambda p: p[1] if len(p) > 1 else "")
    actions["_process"] = parts.map(lambda p: p[2] if len(p) > 2 else "")
    actions["_machine"] = parts.map(lambda p: p[3] if len(p) > 3 else "")
    actions["_cause"] = parts.map(lambda p: p[4] if len(p) > 4 else "")
    if project:
        actions = actions[actions["_project"] == str(project)]
    if process:
        actions = actions[actions["_process"] == str(process)]
    due = actions["Due_Date"] if "Due_Date" in actions.columns else pd.Series("", index=actions.index)
    actions["_due"] = due.map(oi._parse_date)
    status = actions["Status"].astype(str).str.strip()
    actions["_open"] = ~status.str.casefold().isin(["completed", "closed", "done"])
    today = pd.Timestamp(_now_local().date())
    actions["_late"] = actions["_open"] & actions["_due"].notna() & (actions["_due"] < today)
    return actions


def create_oee_action(project, process, machine, cause, title, assigned_to, priority, due_date):
    lookup = _get_technician_lookup()
    tech_id = lookup["name_to_id"].get(str(assigned_to).strip(), "")
    email = lookup["id_to_email"].get(str(tech_id).strip().upper(), "") or lookup["name_to_email"].get(str(assigned_to).strip(), "")
    now = _now_local().strftime("%Y-%m-%d %H:%M:%S")
    clean_title = str(title).strip()
    if not clean_title.startswith(OEE_ACTION_PREFIX):
        clean_title = f"{OEE_ACTION_PREFIX} {clean_title}"
    row = {
        "Task_ID": _new_task_id(), "Assigned_Technician_ID": tech_id, "Assigned_To": assigned_to, "Assigned_Email": email,
        "Process": "Proces održavanje", "Task_Title": clean_title, "Task_Priority": priority, "Status": "Open",
        "Start_Date": "", "Start_Time": "", "End_Date": "", "End_Time": "", "Calculated_Duration": 0,
        "Effective_Duration": 0, "Created_By": _current_user_display_name(), "Created_By_Email": _current_user_email(),
        "Created_At": now, "Closed_By": "", "Closed_At": "",
        "Due_Date": due_date.strftime("%d.%m.%Y") if due_date else "",
        "Source_Ref": f"OEE|{project}|{process}|{machine}|{cause}",
    }
    _append_dict_to_sheet(TASKS_SHEET_NAME, row, list(TASK_REQUIRED_COLUMNS) + OEE_ACTION_EXTRA_COLUMNS)
    load_tasks_data.clear()
    try:
        send_task_created_email(row)
    except Exception:
        pass
    return row


def render_oee_actions(project, process, machine_filter, pareto, key_prefix, can_edit):
    st.markdown("### Akcije za ove gubitke")
    actions = load_oee_actions(project, process)
    if machine_filter not in (None, "Sve", "ALL") and not actions.empty:
        actions = actions[actions["_machine"].isin([str(machine_filter), ""])]
    if actions.empty:
        st.caption("Još nema akcija za ovaj proces.")
    else:
        table = pd.DataFrame({
            "Akcija": actions["Task_Title"].str.replace(OEE_ACTION_PREFIX, "", regex=False).str.strip(),
            "Mašina": actions["_machine"], "Uzrok": actions["_cause"], "Odgovoran": actions["Assigned_To"],
            "Rok": actions["_due"].map(lambda d: d.strftime("%d.%m.%Y") if pd.notna(d) else ""),
            "Status": ["kasni" if late else ("otvoreno" if is_open else "zatvoreno")
                       for late, is_open in zip(actions["_late"], actions["_open"])],
        })
        st.dataframe(table, use_container_width=True, hide_index=True)
    if not can_edit:
        return
    with st.expander("+ Napravi akciju iz gubitka"):
        causes = [c for c in (pareto["Cause"].tolist() if pareto is not None and not pareto.empty else []) if c != oi.UNCAUSED]
        causes = causes + [c for c in cause_options() if c not in causes]
        machines = _scope_machines(project, process, machine_filter)
        technicians = _get_technician_lookup().get("options", [])
        with st.form(f"{key_prefix}_action_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                cause = st.selectbox("Gubitak (uzrok)", causes or ["Ostalo (zastoj)"], key=f"{key_prefix}_action_cause")
            with c2:
                machine = st.selectbox("Mašina", (machines or ["—"]) + ["Cela linija"], key=f"{key_prefix}_action_machine")
            title = st.text_input("Šta treba uraditi", key=f"{key_prefix}_action_title",
                                  placeholder="npr. zameniti senzor prisustva na OP30")
            c3, c4, c5 = st.columns(3)
            with c3:
                assigned = st.selectbox("Odgovoran", technicians or [""], key=f"{key_prefix}_action_owner")
            with c4:
                priority = st.selectbox("Prioritet", ["Low", "Medium", "High", "Critical"], index=2, key=f"{key_prefix}_action_priority")
            with c5:
                due = st.date_input("Rok", value=_now_local().date() + timedelta(days=7), format="DD.MM.YYYY",
                                    key=f"{key_prefix}_action_due")
            submitted = st.form_submit_button("Sačuvaj akciju", use_container_width=True)
        if submitted:
            if not str(title or "").strip() or not assigned:
                st.error("Upiši šta treba uraditi i izaberi odgovornog.")
            else:
                try:
                    create_oee_action(project, process, machine, cause, f"{cause} – {machine}: {str(title).strip()}",
                                      assigned, priority, due)
                    st.success("Akcija je sačuvana u Work Tickets i dodeljena odgovornom.")
                except Exception as exc:
                    st.error(f"Akcija nije sačuvana (Google Sheets): {exc}")


# =========================
# v11: MANAGEMENT PAGE ("Uprava") + WEEKLY E-MAIL
# =========================
def _events_for_rows(events, rows):
    if events is None or events.empty or rows is None or rows.empty:
        return events.iloc[0:0] if events is not None else pd.DataFrame()
    keys = set(zip(pd.to_datetime(rows["Datum"], errors="coerce").dt.normalize(), rows["Machine"].astype(str).str.strip()))
    mask = [(d, str(m).strip()) in keys for d, m in zip(events["Datum"], events["Machine"])]
    return events[pd.Series(mask, index=events.index)]


def _week_rows(df, start):
    dates = pd.to_datetime(df["Datum"], errors="coerce").dt.normalize()
    return df[(dates >= start) & (dates < start + pd.Timedelta(days=7))]


def build_management_summary(oee_df, year, cw, trend_weeks=13):
    """One structure for the management page and the weekly e-mail."""
    start = oi.week_start(year, cw)
    end = start + pd.Timedelta(days=6)
    master, _missing = load_oee_master()
    events = load_all_downtime_events()
    actions = load_oee_actions()
    cards, losses, missing = [], [], []
    scopes = master[["Project", "Process"]].drop_duplicates().sort_values(["Project", "Process"]) if not master.empty else []
    history_start = start - pd.Timedelta(weeks=trend_weeks - 1)
    for project, process in (scopes.itertuples(index=False) if len(scopes) else []):
        scope = _oee_filter_scope(oee_df, project, process)
        if scope is None or scope.empty:
            continue
        recent = scope[(scope["Datum"] >= history_start) & (scope["Datum"] <= end)]
        if recent.empty:
            continue
        week = _week_rows(scope, start)
        previous = _week_rows(scope, start - pd.Timedelta(days=7))
        value = None
        if not week.empty:
            agg = aggregate_oee_as_weighted_daily(week)
            value = float(agg.iloc[0]["Machine_OEE_CT_%"]) if not agg.empty else None
        prev_value = None
        if not previous.empty:
            agg = aggregate_oee_as_weighted_daily(previous)
            prev_value = float(agg.iloc[0]["Machine_OEE_CT_%"]) if not agg.empty else None
        trend = []
        for offset in range(trend_weeks - 1, -1, -1):
            ws_start = start - pd.Timedelta(weeks=offset)
            rows = _week_rows(scope, ws_start)
            if rows.empty:
                trend.append((f"CW{ws_start.isocalendar()[1]:02d}", None))
                continue
            agg = aggregate_oee_as_weighted_daily(rows)
            trend.append((f"CW{ws_start.isocalendar()[1]:02d}", float(agg.iloc[0]["Machine_OEE_CT_%"]) if not agg.empty else None))
        price = price_per_piece(project)
        totals = aggregate_oee(week.assign(_T="T"), ["_T"]) if not week.empty else pd.DataFrame()
        lost = oi.lost_summary(totals.iloc[0] if not totals.empty else {}, price)
        machines = _scope_machines(project, process)
        cov = oi.coverage(week, start, end, machines, today=_now_local().date())
        pareto = oi.loss_pareto(events, week) if not week.empty else pd.DataFrame()
        rate = (lost["target"] / float(totals.iloc[0]["Open_Time"])) if not totals.empty and float(totals.iloc[0]["Open_Time"] or 0) > 0 else 0.0
        week_events = _events_for_rows(events, week)
        for _, loss in (pareto.iterrows() if not pareto.empty else []):
            if loss["Cause"] == oi.UNCAUSED:
                missing.append(f"{project} · {process}: {_sr_num(round(loss['Minutes']))} min gubitaka bez uzroka")
                continue
            by_machine = week_events[week_events["Cause"] == loss["Cause"]].groupby("Machine")["Minutes"].sum()
            machine = str(by_machine.idxmax()) if not by_machine.empty else ""
            losses.append({
                "project": project, "process": process, "cause": loss["Cause"], "machine": machine,
                "minutes": float(loss["Minutes"]), "loss_type": loss["Loss_Type"],
                "value": float(loss["Minutes"]) * rate * price if price and rate else None,
            })
        if cov.get("missing_days"):
            missing.append(f"{project} · {process}: nema unosa za " + ", ".join(
                f"{_SR_WEEKDAYS[d.weekday()]} {d:%d.%m}" for d in cov["missing_days"]))
        cards.append({
            "project": project, "process": process, "description": process_description(project, process),
            "value": value, "previous": prev_value, "trend": trend, "lost": lost, "coverage": cov,
            "top_loss": _top_loss_text(pareto),
        })
    for loss in losses:
        related = actions[
            (actions["_project"] == str(loss["project"])) & (actions["_process"] == str(loss["process"]))
            & (actions["_cause"] == str(loss["cause"]))
        ] if actions is not None and not actions.empty else pd.DataFrame()
        if related.empty:
            loss["action"], loss["action_status"] = "nema akcije", "alarm"
        else:
            open_ones = related[related["_open"]]
            pick = (open_ones if not open_ones.empty else related).iloc[-1]
            due = pick["_due"].strftime("%d.%m") if pd.notna(pick["_due"]) else ""
            state = "kasni" if pick["_late"] else ("otvoreno" if pick["_open"] else "zatvoreno")
            loss["action"] = f"{state} · {pick['Assigned_To']}" + (f" · rok {due}" if due else "")
            loss["action_status"] = "alarm" if pick["_late"] else ("warn" if pick["_open"] else "ok")
    losses.sort(key=lambda item: item["minutes"], reverse=True)
    all_week = _week_rows(oee_df, start) if oee_df is not None and not oee_df.empty else pd.DataFrame()
    overall = None
    overall_prev = None
    if not all_week.empty:
        agg = aggregate_oee_as_weighted_daily(all_week)
        overall = float(agg.iloc[0]["Machine_OEE_CT_%"]) if not agg.empty else None
        prev_all = _week_rows(oee_df, start - pd.Timedelta(days=7))
        if not prev_all.empty:
            agg = aggregate_oee_as_weighted_daily(prev_all)
            overall_prev = float(agg.iloc[0]["Machine_OEE_CT_%"]) if not agg.empty else None
    action_counts = {"open": 0, "late": 0, "closed_week": 0}
    if actions is not None and not actions.empty:
        closed_at = actions["Closed_At"].map(oi._parse_date) if "Closed_At" in actions.columns else pd.Series(pd.NaT, index=actions.index)
        action_counts = {
            "open": int(actions["_open"].sum()), "late": int(actions["_late"].sum()),
            "closed_week": int(((~actions["_open"]) & closed_at.notna() & (closed_at >= start) & (closed_at <= end)).sum()),
        }
    lost_pieces = sum(card["lost"]["lost_pieces"] for card in cards)
    values = [card["lost"]["value"] for card in cards if card["lost"].get("value") is not None]
    return {
        "year": int(year), "cw": int(cw), "start": start, "end": end, "cards": cards, "losses": losses,
        "missing": missing, "overall": overall, "overall_prev": overall_prev, "actions": action_counts,
        "lost_pieces": lost_pieces, "lost_value": sum(values) if values else None,
        "losses_without_action": sum(1 for loss in losses[:5] if loss.get("action_status") == "alarm"),
    }


@st.cache_data(ttl=300, show_spinner="Pripremam pregled…")
def cached_management_summary(year, cw):
    """The management page is opened by many people; the numbers change only with new entries."""
    oee_df, _missing = load_oee_input()
    return build_management_summary(oee_df, year, cw)


def _summary_sentence(summary):
    if summary.get("overall") is None:
        return f"Za CW{summary['cw']:02d} još nema OEE unosa."
    text = f"Fabrika je u CW{summary['cw']:02d} radila sa OEE {summary['overall']:.1f} %".replace(".", ",")
    if summary.get("overall_prev") is not None:
        diff = summary["overall"] - summary["overall_prev"]
        text += (f", {abs(diff):.1f} pp {'bolje' if diff >= 0 else 'slabije'} nego prethodne nedelje").replace(".", ",")
    text += f". Izgubljeno je oko {_sr_num(round(summary['lost_pieces']))} komada"
    if summary.get("lost_value"):
        text += f" (≈ {_sr_num(round(summary['lost_value']))} €)"
    text += "."
    if summary["losses"]:
        top = summary["losses"][0]
        text += f" Najviše je koštalo: {top['cause']} na {top['project']}" + (f" {top['machine']}" if top["machine"] else "") + \
                f" ({_sr_num(round(top['minutes']))} min)."
    if summary.get("losses_without_action"):
        text += f" {summary['losses_without_action']} od 5 najvećih gubitaka nema akciju."
    return text


def _open_oee_week(project, process, year, cw):
    state = st.session_state
    state["selected_module"] = "OEE"
    state["oee_page_selector"] = "Weekly"
    state["oee_weekly_selected_week"] = (int(year), int(cw))
    state["oee_weekly_inline_project"] = project
    state["oee_weekly_inline_process"] = process
    state["oee_weekly_inline_machine"] = "Sve"
    state["oee_drill_trail"] = []


def _sparkline(trend, key):
    labels = [label for label, _ in trend]
    values = [value for _, value in trend]
    fig = go.Figure(go.Scatter(x=labels, y=values, mode="lines+markers", connectgaps=False,
                               line=dict(color="#38BDF8", width=2.5), marker=dict(size=5, color="#38BDF8"),
                               hovertemplate="%{x}: %{y:.1f} %<extra></extra>", showlegend=False))
    fig.add_shape(type="line", xref="paper", yref="y", x0=0, x1=1, y0=OEE_REFERENCE, y1=OEE_REFERENCE,
                  line=dict(color="#FBBF24", width=1, dash="dot"))
    fig = style_chart(fig)
    fig.update_layout(height=110, margin=dict(l=8, r=8, t=6, b=6), showlegend=False)
    fig.update_xaxes(visible=False, type="category")
    fig.update_yaxes(visible=False, range=[40, 100])
    st.plotly_chart(fig, use_container_width=True, key=key)


def render_uprava_module():
    require_module_access("Uprava", ["Uprava", "Management", "Reports", "OEE"])
    try:
        oee_df, oee_missing = load_oee_input()
    except Exception as exc:
        st.error(f"OEE podaci nisu dostupni: {exc}")
        return
    if oee_df is None or oee_df.empty:
        st.info("Još nema OEE unosa.")
        return
    weeks = sorted({(int(y), int(w)) for y, w in zip(oee_df["Godina"], oee_df["Week"])}, reverse=True)
    if st.session_state.get("uprava_week") not in weeks:
        st.session_state["uprava_week"] = weeks[0]
    week = st.selectbox("Nedelja", weeks, key="uprava_week",
                        format_func=lambda x: f"{x[0]}-CW{x[1]:02d} · {oi.week_start(*x):%d.%m}–{oi.week_start(*x) + pd.Timedelta(days=6):%d.%m.%Y}")
    summary = cached_management_summary(week[0], week[1])
    status = _status_for_pct(summary["overall"]) if summary.get("overall") is not None else "neutral"
    st.markdown(ui.headline_html(_summary_sentence(summary), status), unsafe_allow_html=True)

    cards = summary["cards"]
    for start_index in range(0, len(cards), 3):
        columns = st.columns(3)
        for column, card in zip(columns, cards[start_index:start_index + 3]):
            with column:
                value = card["value"]
                delta, direction = oi.delta_text(value, card["previous"]) if value is not None else ("nema unosa", "none")
                cov = card["coverage"]
                lines = []
                lost = card["lost"]
                lost_text = f"Izgubljeno: <b>{_sr_num(round(lost['lost_pieces']))} kom</b>"
                if lost.get("value"):
                    lost_text += f" · ≈ {_sr_num(round(lost['value']))} €"
                lines.append(lost_text)
                if card.get("top_loss"):
                    lines.append(f"Najveći gubitak: <b>{ui.esc(card['top_loss'])}</b>")
                if cov.get("days_expected"):
                    color = "#4ADE80" if cov["days_entered"] >= cov["days_expected"] else "#FBBF24"
                    lines.append(f'<span style="color:{color}">Uneto {cov["days_entered"]} od {cov["days_expected"]} radnih dana</span>')
                st.markdown(ui.mgmt_card_html(
                    card["project"], card["description"] or card["process"],
                    _sr_pct(value, 1) if value is not None else "—", _status_for_pct(value) if value is not None else "",
                    delta + (" od prošle nedelje" if direction in ("up", "down") else ""), direction, lines,
                ), unsafe_allow_html=True)
                _sparkline(card["trend"], f"uprava_spark_{_norm_key(card['project'])}_{_norm_key(card['process'])}")
                st.button("Otvori nedelju →", key=f"uprava_open_{_norm_key(card['project'])}_{_norm_key(card['process'])}",
                          on_click=_open_oee_week, args=(card["project"], card["process"], week[0], week[1]),
                          use_container_width=True)
    if not cards:
        st.info("Za izabranu nedelju nema OEE unosa ni u jednom procesu.")

    st.markdown(f"### 5 najvećih gubitaka · CW{week[1]:02d}")
    if summary["losses"]:
        top = pd.DataFrame([{
            "Uzrok": loss["cause"], "Gde": f"{loss['project']} · {loss['process']}" + (f" · {loss['machine']}" if loss["machine"] else ""),
            "Vreme": f"{_sr_num(round(loss['minutes']))} min",
            "Vrednost": f"≈ {_sr_num(round(loss['value']))} €" if loss.get("value") else "—",
            "Akcija": loss.get("action", ""),
        } for loss in summary["losses"][:5]])
        st.dataframe(top, use_container_width=True, hide_index=True)
    else:
        st.caption("Za ovu nedelju još nema unetih uzroka gubitaka.")

    counts = summary["actions"]
    st.markdown(ui.stat_tiles_html([
        {"label": "Otvorene akcije", "value": str(counts["open"]), "status": "neutral"},
        {"label": "Kasne", "value": str(counts["late"]), "status": "alarm" if counts["late"] else "ok"},
        {"label": "Zatvoreno ove nedelje", "value": str(counts["closed_week"]), "status": "ok"},
    ]), unsafe_allow_html=True)
    if summary["missing"]:
        st.markdown("### Nedostaju unosi")
        st.markdown("\n".join(f"- {line}" for line in summary["missing"]))
        st.caption("Brojevi iznad su tačni koliko i unosi, zato je pokrivenost uvek prikazana.")


def build_management_email(summary):
    subject = f"OEE CW{summary['cw']:02d}"
    if summary.get("overall") is not None:
        subject += f": {summary['overall']:.1f} %".replace(".", ",")
        if summary.get("overall_prev") is not None:
            diff = summary["overall"] - summary["overall_prev"]
            subject += f" ({'+' if diff >= 0 else '−'}{abs(diff):.1f} pp)".replace(".", ",")
    if summary.get("losses_without_action"):
        subject += f" · {summary['losses_without_action']} gubitka bez akcije"
    lines = [f"Nedelja CW{summary['cw']:02d} ({summary['start']:%d.%m} – {summary['end']:%d.%m.%Y})", "",
             _summary_sentence(summary), "", "PROJEKTI"]
    for card in summary["cards"]:
        value = _sr_pct(card["value"], 1) if card["value"] is not None else "nema unosa"
        delta, _direction = oi.delta_text(card["value"], card["previous"]) if card["value"] is not None else ("", "none")
        lost = card["lost"]
        extra = f"izgubljeno {_sr_num(round(lost['lost_pieces']))} kom" + (f" (≈ {_sr_num(round(lost['value']))} €)" if lost.get("value") else "")
        cov = card["coverage"]
        partial = f" · uneto {cov['days_entered']}/{cov['days_expected']} dana" if cov.get("days_expected") and cov["days_entered"] < cov["days_expected"] else ""
        lines.append(f"- {card['project']} · {card['process']}: {value} {delta} · {extra}{partial}")
    lines += ["", "NAJVEĆI GUBICI"]
    for index, loss in enumerate(summary["losses"][:3], start=1):
        lines.append(f"{index}. {loss['cause']} — {loss['project']} {loss['machine']}, {_sr_num(round(loss['minutes']))} min · {loss.get('action', '')}")
    if not summary["losses"]:
        lines.append("Nema unetih uzroka gubitaka.")
    if summary["missing"]:
        lines += ["", "PAŽNJA — NEDOSTAJU UNOSI"] + [f"- {line}" for line in summary["missing"][:8]]
    url = str(_get_secret_value("APP_URL", "STREAMLIT_APP_URL", default="") or "").strip()
    if url:
        lines += ["", f"Pregled u aplikaciji: {url}"]
    lines += ["", "Automatska poruka · Lianbo Project Performance Hub"]
    return subject, "\n".join(lines)


def management_email_recipients():
    raw = oee_setting(SETTING_MGMT_EMAIL, "", "")
    return [r.strip() for r in re.split(r"[,;\s]+", str(raw or "")) if "@" in r]


def run_weekly_management_email(force=False, now=None):
    """Every Monday from 07:00: summary of the previous week, once (EMAIL_LOG)."""
    now = now or _now_local()
    if not force and (now.weekday() != 0 or now.hour < 7):
        return {"status": "not_due"}
    if not force and str(oee_setting(SETTING_MGMT_EMAIL_ON, "", "NO")).strip().upper() not in ("YES", "DA", "TRUE", "1"):
        return {"status": "disabled"}
    recipients = management_email_recipients()
    if not recipients:
        return {"status": "no_recipients"}
    last_week = (now - timedelta(days=7)).date().isocalendar()
    related_id = f"{last_week[0]}-CW{last_week[1]:02d}"
    if not force:
        already = _email_log_has_success("OEE_WEEKLY", related_id)
        if already is None:
            return {"status": "log_unreadable"}
        if already:
            return {"status": "already_sent", "week": related_id}
    oee_df, _missing = load_oee_input()
    if oee_df is None or oee_df.empty:
        return {"status": "no_data"}
    summary = build_management_summary(oee_df, last_week[0], last_week[1])
    subject, body = build_management_email(summary)
    result = send_email_notification("OEE_WEEKLY", recipients, subject, body, related_id)
    return {"status": "sent" if result.get("sent") else "not_sent", "week": related_id, "email": result}


# =========================
# v11: PRIVATE IWON (plan + forecast for any week, refresh actual, comparison)
# =========================
IWON_SCOPE_KEYS = ["Year", "CW", "Project", "Process"]


@st.cache_data(ttl=120, show_spinner=False)
def load_iwon_tab(name):
    columns = {IWON_COMPARE_SHEET_NAME: oi.IWON_COMPARE_COLUMNS, IWON_CAUSE_SHEET_NAME: oi.IWON_CAUSE_COLUMNS,
               IWON_HISTORY_SHEET_NAME: oi.IWON_HISTORY_COLUMNS}[name]
    _, _, df = _tab_frame(OEE_IWON_SHEET_ID, name, columns)
    return df


def _iwon_scope_mask(df, year, project, process, cws=None):
    if df is None or df.empty:
        return pd.Series(dtype=bool)
    mask = (
        (pd.to_numeric(df["Year"], errors="coerce") == int(year))
        & (df["Project"].astype(str).str.strip() == str(project).strip())
        & (df["Process"].astype(str).str.strip() == str(process).strip())
    )
    if cws is not None:
        mask &= pd.to_numeric(df["CW"], errors="coerce").isin([int(c) for c in cws])
    return mask


def _iwon_target_map(year, project, process):
    targets = load_oee_iwon_targets()
    # 'APP-350' in the sheet = 'APP350' in MASTER_DATA (case, spaces and dashes are ignored)
    scoped = targets[
        (targets["Year"] == int(year))
        & (targets["Project"].map(oi._alnum) == oi._alnum(project))
        & (targets["Process"].map(oi._alnum) == oi._alnum(process))
    ]
    return {int(r["CW"]): float(r["Target_OEE"]) for _, r in scoped.iterrows()
            if pd.notna(r.get("CW")) and pd.notna(r.get("Target_OEE")) and float(r["Target_OEE"]) > 0}


def iwon_generate(year, project, process, cws, weeks=10, replace=False, best_quantile=0.2):
    """Generate (or, when asked, replace) the plan for every selected week.

    A week that already has a plan is frozen: it is skipped unless `replace`
    is chosen; then the old plan goes to IWON_PLAN_HISTORY with its version.
    """
    if not can_see_iwon():
        raise PermissionError("IWON je privatan.")
    load_oee_input.clear()
    actual, missing_cols = load_oee_input()
    if missing_cols:
        raise ValueError(f"OEE_INPUT nedostaju kolone: {missing_cols}")
    events = load_all_downtime_events()
    causes = load_downtime_causes()
    targets = _iwon_target_map(year, project, process)
    machines = _scope_machines(project, process)
    now = _now_local().strftime("%Y-%m-%d %H:%M:%S")

    ws_c, headers_c, existing_c = _tab_frame(OEE_IWON_SHEET_ID, IWON_COMPARE_SHEET_NAME, oi.IWON_COMPARE_COLUMNS, live=True)
    ws_k, headers_k, existing_k = _tab_frame(OEE_IWON_SHEET_ID, IWON_CAUSE_SHEET_NAME, oi.IWON_CAUSE_COLUMNS, live=True)
    ws_h, headers_h, _history = _tab_frame(OEE_IWON_SHEET_ID, IWON_HISTORY_SHEET_NAME, oi.IWON_HISTORY_COLUMNS)
    ws_iwon, _ = open_first_existing_worksheet(get_client(), OEE_IWON_SHEET_ID, OEE_IWON_RESULT_SHEET_NAMES)

    report = {"generated": [], "frozen": [], "no_target": [], "notes": {}, "cause_summary": {}}
    delete_compare, delete_causes, new_compare, new_causes, history = [], [], [], [], []
    for cw in sorted({int(c) for c in cws}):
        target = targets.get(cw)
        if target is None:
            report["no_target"].append(cw)
            continue
        scope_mask = _iwon_scope_mask(existing_c, year, project, process, [cw])
        old_rows = existing_c[scope_mask] if len(scope_mask) else pd.DataFrame()
        if not old_rows.empty and not replace:
            report["frozen"].append(cw)
            continue
        version = 1
        if not old_rows.empty:
            version = int(pd.to_numeric(old_rows["Plan_Version"], errors="coerce").fillna(1).max()) + 1
            for _, old in old_rows.iterrows():
                record = {k: old.get(k, "") for k in oi.IWON_COMPARE_COLUMNS}
                record["Replaced_At"] = now
                history.append(record)
            delete_compare += old_rows["_row"].astype(int).tolist()
        cause_mask = _iwon_scope_mask(existing_k, year, project, process, [cw])
        if len(cause_mask) and cause_mask.any():
            delete_causes += existing_k[cause_mask]["_row"].astype(int).tolist()

        out = oi.plan_week(actual, machines, year, cw, project, process, target, aggregate_oee, weeks=weeks,
                           version=version, now=now)
        rows = oi.apply_actuals(out["compare_rows"], oi.actual_for_week(actual, year, cw, project, process, aggregate_oee), now)
        new_compare += rows
        _upsert_iwon_result_rows(ws_iwon, year, cw, project, process, out["iwon_rows"])
        global_row = rows[0]
        plan_causes = oi.cause_plan(events, out["baseline"], global_row["Plan_A"], causes, best_quantile=best_quantile,
                                    weeks=out["weeks_used"] or None)
        for item in plan_causes["items"]:
            new_causes.append({**{k: "" for k in oi.IWON_CAUSE_COLUMNS}, **{
                "Year": int(year), "CW": int(cw), "Project": project, "Process": process,
                **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in item.items()},
                "Generated_At": now,
            }})
        report["generated"].append(cw)
        report["notes"][cw] = out["note"]
        report["cause_summary"][cw] = {
            "needed": plan_causes["needed_min_week"], "missing": plan_causes["missing_min_week"],
            "max_oee": oi.realistic_max_oee(plan_causes["realistic_max_a"], global_row["Forecast_P"], global_row["Forecast_Q"]),
            "items": len(plan_causes["items"]),
        }
    if history:
        _append_tab_rows(ws_h, headers_h, oi.IWON_HISTORY_COLUMNS, history)
    if delete_compare:
        _delete_worksheet_rows_batch(ws_c, delete_compare)
    if new_compare:
        _append_tab_rows(ws_c, headers_c, oi.IWON_COMPARE_COLUMNS, new_compare)
    if delete_causes:
        _delete_worksheet_rows_batch(ws_k, delete_causes)
    if new_causes:
        _append_tab_rows(ws_k, headers_k, oi.IWON_CAUSE_COLUMNS, new_causes)
    load_oee_iwon_results.clear()
    load_iwon_tab.clear()
    return report


def iwon_refresh(year, project, process, cws=None):
    """Pull the real OEE (and causes) into the saved plans; plans themselves never change."""
    if not can_see_iwon():
        raise PermissionError("IWON je privatan.")
    load_oee_input.clear()
    load_app_downtime_events.clear()
    actual, _missing = load_oee_input()
    events = load_all_downtime_events()
    now = _now_local().strftime("%Y-%m-%d %H:%M:%S")
    ws_c, headers_c, existing_c = _tab_frame(OEE_IWON_SHEET_ID, IWON_COMPARE_SHEET_NAME, oi.IWON_COMPARE_COLUMNS, live=True)
    mask = _iwon_scope_mask(existing_c, year, project, process, cws)
    scope = existing_c[mask] if len(mask) else pd.DataFrame()
    report = {"weeks": 0, "with_data": 0}
    if scope.empty:
        return report
    updated = []
    for cw, rows in scope.groupby(pd.to_numeric(scope["CW"], errors="coerce")):
        actuals = oi.actual_for_week(actual, year, int(cw), project, process, aggregate_oee)
        records = [{k: r.get(k, "") for k in oi.IWON_COMPARE_COLUMNS} for _, r in rows.iterrows()]
        updated += oi.apply_actuals(records, actuals, now)
        report["weeks"] += 1
        report["with_data"] += 1 if actuals else 0
    _upsert_tab_rows(ws_c, headers_c, oi.IWON_COMPARE_COLUMNS, existing_c, ["Year", "CW", "Project", "Process", "Machine"], updated)

    ws_k, headers_k, existing_k = _tab_frame(OEE_IWON_SHEET_ID, IWON_CAUSE_SHEET_NAME, oi.IWON_CAUSE_COLUMNS, live=True)
    mask = _iwon_scope_mask(existing_k, year, project, process, cws)
    cause_rows = existing_k[mask] if len(mask) else pd.DataFrame()
    if not cause_rows.empty:
        records = []
        for _, r in cause_rows.iterrows():
            count, average, total = oi.actual_cause_week(events, year, int(float(r["CW"])), r["Machine"], r["Cause"])
            record = {k: r.get(k, "") for k in oi.IWON_CAUSE_COLUMNS}
            record.update({"Actual_Per_Week": count, "Actual_Avg_Min": round(average, 2), "Actual_Min_Week": round(total, 1),
                           "Refreshed_At": now})
            records.append(record)
        _upsert_tab_rows(ws_k, headers_k, oi.IWON_CAUSE_COLUMNS, existing_k,
                         ["Year", "CW", "Project", "Process", "Machine", "Cause"], records)
    load_iwon_tab.clear()
    return report


def _iwon_scope_selectors(prefix, master):
    years = list(range(datetime.now().year - 2, datetime.now().year + 3))
    c1, c2, c3 = st.columns(3)
    with c1:
        if st.session_state.get(f"{prefix}_year") not in years:
            st.session_state[f"{prefix}_year"] = datetime.now().year
        year = st.selectbox("Godina", years, key=f"{prefix}_year")
    with c2:
        projects = sorted(master["Project"].astype(str).unique().tolist())
        project = st.selectbox("Projekat", projects, key=f"{prefix}_project")
    processes = sorted(master[master["Project"].astype(str) == str(project)]["Process"].astype(str).unique().tolist())
    with c3:
        process = st.selectbox("Proces", processes, key=f"{prefix}_process")
    return int(year), project, process


def _num_or_blank(value, decimals=2):
    number = pd.to_numeric(value, errors="coerce")
    return round(float(number), decimals) if pd.notna(number) else None


def render_iwon_admin():
    """Administration → 🔒 IWON: targets, generating plans and refreshing actual data."""
    if not can_see_iwon():
        st.error("Ova stranica nije dostupna.")
        return
    st.caption("🔒 Privatno: vidiš samo ti i korisnici iz IWON liste u secrets. Grafikoni su u OEE → 🔒 IWON.")
    master, master_missing = load_oee_master()
    if master_missing or master.empty:
        st.error("MASTER_DATA nije dostupan.")
        return
    tab_targets, tab_plan, tab_refresh = st.tabs(["Ciljevi", "Plan i prognoza", "Osveži stvarno"])

    with tab_targets:
        if st.button("🔄 Učitaj ciljeve ponovo iz sheet-a", key="iwon_reload_targets"):
            load_iwon_target_sources.clear()
        try:
            sources = load_iwon_target_sources()
        except Exception as exc:
            st.error(f"IWON sheet nije dostupan: {exc}")
            sources = []
        with st.expander("Odakle aplikacija čita ciljeve", expanded=not any(src["info"]["used"] for src in sources)):
            if not sources:
                st.warning("U IWON sheet-u nije pronađen tab sa ciljevima (ni tab iz linka, ni „Admin podešavanja“).")
            for src in sources:
                info = src["info"]
                st.markdown(f"**Tab „{src['title']}“** (gid {src['gid']}) · raspored: {info['format']} · "
                            f"zaglavlje u redu {info['header_row']} · pročitano {info['rows']} redova · "
                            f"**{info['used']} ciljeva**")
                if info["header"]:
                    st.caption("Kolone: " + ", ".join(info["header"][:20]))
                if not src["frame"].empty:
                    summary = src["frame"].groupby(["Year", "Project", "Process"])["CW"].agg(["min", "max", "count"]).reset_index()
                    st.dataframe(pd.DataFrame({
                        "Godina": summary["Year"], "Projekat": summary["Project"], "Proces": summary["Process"],
                        "Nedelje": [f"CW{a:02d}–CW{b:02d}" for a, b in zip(summary["min"], summary["max"])],
                        "Ciljeva": summary["count"],
                    }), use_container_width=True, hide_index=True)
                if info["skipped"]:
                    st.caption("Preskočeno: " + "; ".join(info["skipped"][:6]) + (" …" if len(info["skipped"]) > 6 else ""))
        year, project, process = _iwon_scope_selectors("iwon_t", master)
        existing = _iwon_target_map(year, project, process)
        weeks_count = oi.iso_weeks_in_year(year)
        grid = pd.DataFrame({"CW": list(range(1, weeks_count + 1)),
                             "Target_OEE": [existing.get(cw) for cw in range(1, weeks_count + 1)]})
        editable = iwon_targets_editable() if sources else True
        if not editable:
            st.info("Ciljevi se unose direktno u sheet (tab iz linka). Ovde se samo prikazuju; posle izmene u sheet-u "
                    "klikni „Učitaj ciljeve ponovo“.")
        edited = st.data_editor(
            grid, use_container_width=True, hide_index=True, disabled=["CW"] if editable else True,
            key=f"iwon_grid_{year}_{project}_{process}",
            column_config={"Target_OEE": st.column_config.NumberColumn("Ciljni OEE %", min_value=1.0, max_value=99.0,
                                                                        step=0.5, format="%.2f%%")},
        )
        if editable and st.button("Sačuvaj ciljeve", type="primary", key="iwon_save_targets"):
            who = _current_user_display_name()
            count = save_oee_iwon_target_grid(year, project, process, edited, who)
            st.success(f"Sačuvano: {count} nedeljnih ciljeva.")

    with tab_plan:
        year, project, process = _iwon_scope_selectors("iwon_p", master)
        targets = _iwon_target_map(year, project, process)
        if not targets:
            st.info("Za ovaj projekat i proces još nema ciljeva. Upiši ih u tabu „Ciljevi“.")
        else:
            defined = sorted(targets)
            c1, c2, c3 = st.columns(3)
            with c1:
                first = st.selectbox("Od CW", defined, key="iwon_p_from", format_func=lambda x: f"CW{x:02d}")
            with c2:
                last_options = [cw for cw in defined if cw >= first]
                last = st.selectbox("Do CW", last_options, key="iwon_p_to", format_func=lambda x: f"CW{x:02d}")
            with c3:
                weeks = st.selectbox("Osnova (nedelja sa podacima)", [4, 10, 13], index=1, key="iwon_p_weeks")
            replace = st.checkbox("Zameni već postojeće planove (stari idu u IWON_PLAN_HISTORY)", key="iwon_p_replace")
            st.caption("Plan se pravi i za nedelje bez podataka (i buduće): osnova su poslednje nedelje sa podacima "
                       "pre izabrane nedelje. Već napravljen plan je zamrznut i ne menja se osvežavanjem.")
            if st.button("Generiši plan", type="primary", key="iwon_generate_btn"):
                try:
                    with st.spinner("Pravim plan…"):
                        report = iwon_generate(year, project, process, [cw for cw in defined if first <= cw <= last],
                                               weeks=weeks, replace=replace)
                    if report["generated"]:
                        st.success("Plan napravljen za: " + ", ".join(f"CW{cw:02d}" for cw in report["generated"]))
                        st.dataframe(pd.DataFrame([
                            {"CW": f"CW{cw:02d}", "Osnova": report["notes"][cw],
                             "Potrebno manje zastoja (min/ned)": round(report["cause_summary"][cw]["needed"], 1),
                             "Najviši realan OEE": (round(report["cause_summary"][cw]["max_oee"], 1)
                                                    if report["cause_summary"][cw]["max_oee"] is not None else None),
                             "Uzroka u planu": report["cause_summary"][cw]["items"]}
                            for cw in report["generated"]
                        ]), use_container_width=True, hide_index=True)
                    if report["frozen"]:
                        st.info("Već postoji plan (zamrznut, nije menjan): " + ", ".join(f"CW{cw:02d}" for cw in report["frozen"])
                                + ". Štikliraj „Zameni…“ ako hoćeš novu verziju.")
                except Exception as exc:
                    st.error(f"Plan nije napravljen: {exc}")

    with tab_refresh:
        year, project, process = _iwon_scope_selectors("iwon_c", master)
        st.caption("Povuče stvarni OEE (i zastoje) za nedelje koje već imaju plan i upiše poređenje u tab "
                   f"{IWON_COMPARE_SHEET_NAME}. Sam plan se ne menja.")
        compare = load_iwon_tab(IWON_COMPARE_SHEET_NAME)
        mask = _iwon_scope_mask(compare, year, project, process)
        scope = compare[mask] if len(mask) else pd.DataFrame()
        if st.button("🔄 Osveži stvarno — sve nedelje", key="iwon_refresh_all", type="primary", use_container_width=True):
            try:
                report = iwon_refresh(year, project, process)
                st.success(f"Osveženo {report['weeks']} nedelja; stvarni podaci postoje za {report['with_data']}.")
            except Exception as exc:
                st.error(f"Osvežavanje nije uspelo: {exc}")
        if not scope.empty:
            cw_list = sorted(pd.to_numeric(scope["CW"], errors="coerce").dropna().astype(int).unique().tolist())
            one = st.selectbox("Samo jedna nedelja", cw_list, index=len(cw_list) - 1, key="iwon_c_week",
                               format_func=lambda x: f"CW{x:02d}")
            if st.button("🔄 Osveži izabranu nedelju", key="iwon_refresh_one", use_container_width=True):
                try:
                    iwon_refresh(year, project, process, [one])
                    st.success(f"CW{one:02d} osvežena.")
                except Exception as exc:
                    st.error(f"Osvežavanje nije uspelo: {exc}")
        else:
            st.info("Za ovaj projekat i proces još nema plana. Napravi ga u tabu „Plan i prognoza“.")


def _iwon_saved_scopes(year):
    """(project, process) -> weeks that have a saved plan (OEE_IWON or IWON_COMPARE)."""
    found = {}
    try:
        results = load_oee_iwon_results()
        for _, row in results[results["Year"] == int(year)].iterrows():
            found.setdefault((str(row["Project"]).strip(), str(row["Process"]).strip()), set()).add(int(row["CW"]))
    except Exception:
        pass
    try:
        compare = load_iwon_tab(IWON_COMPARE_SHEET_NAME)
        years = pd.to_numeric(compare["Year"], errors="coerce")
        for _, row in compare[years == int(year)].iterrows():
            cw = pd.to_numeric(row["CW"], errors="coerce")
            if pd.notna(cw):
                found.setdefault((str(row["Project"]).strip(), str(row["Process"]).strip()), set()).add(int(cw))
    except Exception:
        pass
    return found


def render_iwon_view():
    """OEE → 🔒 IWON: charts for the saved plans (only IWON users)."""
    if not can_see_iwon():
        st.error("Ova stranica nije dostupna.")
        st.stop()
    st.caption("🔒 Privatno. Ciljevi, generisanje plana i osvežavanje su u Administration → 🔒 IWON.")
    if st.button("🔄 Učitaj ponovo iz IWON sheet-a", key="iwon_view_reload"):
        load_iwon_target_sources.clear()
        load_oee_iwon_results.clear()
        load_iwon_tab.clear()
    master, master_missing = load_oee_master()
    if master_missing or master.empty:
        st.error("MASTER_DATA nije dostupan.")
        return
    year, project, process = _iwon_scope_selectors("iwon_v", master)
    saved = _iwon_saved_scopes(year)
    key = next((k for k in saved if oi._alnum(k[0]) == oi._alnum(project) and oi._alnum(k[1]) == oi._alnum(process)), None)
    planned_weeks = set(saved.get(key, set())) if key else set()
    try:
        targets = _iwon_target_map(year, project, process)
    except Exception as exc:
        st.error(f"Ciljevi iz IWON sheet-a nisu pročitani: {exc}")
        targets = {}
    weeks = sorted(planned_weeks | set(targets))
    if not weeks:
        st.info(f"Za {project} · {process} u {year}. nema ni cilja ni sačuvanog IWON plana.")
        all_targets = load_oee_iwon_targets()
        all_targets = all_targets[all_targets["Year"] == int(year)]
        if not all_targets.empty:
            summary = all_targets.groupby(["Project", "Process"])["CW"].agg(["min", "max", "count"]).reset_index()
            st.markdown("**Ciljevi u sheet-u postoje za:**\n" + "\n".join(
                f"- {r['Project']} · {r['Process']}: CW{r['min']:02d}–CW{r['max']:02d} ({r['count']} nedelja)"
                for _, r in summary.iterrows()))
            st.caption("Ako se naziv projekta ili procesa u sheet-u razlikuje od MASTER_DATA, ispravi ga u sheet-u.")
        elif saved:
            st.markdown("**Sačuvani planovi postoje za:**\n" + "\n".join(
                f"- {p} · {q}: CW{min(w):02d}–CW{max(w):02d} ({len(w)} nedelja)" for (p, q), w in sorted(saved.items())))
        else:
            st.caption("U ovoj godini aplikacija ne vidi nijedan cilj. Proveri Administration → 🔒 IWON → Ciljevi → "
                       "„Odakle aplikacija čita ciljeve“.")
        return
    missing_plans = sorted(set(targets) - planned_weeks)
    if missing_plans:
        st.info(f"{len(missing_plans)} nedelja ima cilj, ali plan (A/P/Q po mašini) još nije napravljen: "
                + ", ".join(f"CW{w:02d}" for w in missing_plans[:12]) + (" …" if len(missing_plans) > 12 else ""))
        if st.button(f"Napravi plan za tih {len(missing_plans)} nedelja", key="iwon_view_generate", type="primary"):
            try:
                with st.spinner("Pravim plan…"):
                    iwon_generate(year, project, process, missing_plans)
                load_oee_iwon_results.clear()
                st.rerun()
            except Exception as exc:
                st.error(f"Plan nije napravljen: {exc}")

    machines = ["Sve"] + _scope_machines(project, process)
    c1, c2 = st.columns([1, 2])
    with c1:
        if st.session_state.get("iwon_v_week") not in weeks:
            current = _now_local().isocalendar()[1]
            st.session_state["iwon_v_week"] = min(weeks, key=lambda w: (abs(w - current), -w))
        week = st.selectbox("Nedelja", weeks, key="iwon_v_week", format_func=lambda x: f"CW{x:02d}")
    with c2:
        machine = st.selectbox("Mašina", machines, key="iwon_v_machine")
    scope_machine = "GLOBAL" if machine == "Sve" else machine

    # Trend over all planned weeks: target vs forecast vs actual (actual always live from OEE_INPUT).
    actual_df, _missing = load_oee_input()
    results = load_oee_iwon_results()
    results = results[(results["Year"] == int(year))
                      & (results["Project"].map(oi._alnum) == oi._alnum(project))
                      & (results["Process"].map(oi._alnum) == oi._alnum(process))]
    compare = load_iwon_tab(IWON_COMPARE_SHEET_NAME)
    cmask = _iwon_scope_mask(compare, year, project, process)
    compare = compare[cmask] if len(cmask) else pd.DataFrame()
    rows = []
    for cw in weeks:
        target = forecast = None
        plan = results[(results["CW"] == cw) & (results["Machine"].str.casefold() == scope_machine.casefold())]
        if not plan.empty:
            target = float(plan.iloc[0]["OEE"]) if pd.notna(plan.iloc[0]["OEE"]) else None
        if target is None and scope_machine == "GLOBAL":
            target = targets.get(cw)
        if not compare.empty:
            match = compare[(pd.to_numeric(compare["CW"], errors="coerce") == cw)
                            & (compare["Machine"].astype(str).str.casefold() == scope_machine.casefold())]
            if not match.empty:
                forecast = _num_or_blank(match.iloc[0]["Forecast_OEE"])
                if target is None:
                    target = _num_or_blank(match.iloc[0]["Plan_OEE"])
        actual = oi.actual_for_week(actual_df, year, cw, project, process, aggregate_oee).get(scope_machine)
        rows.append({"CW": f"CW{cw:02d}", "Cilj": target, "Prognoza": forecast,
                     "Stvarno": round(actual[3], 2) if actual else None, "Uneto dana": actual[4] if actual else 0})
    trend = pd.DataFrame(rows)
    fig = go.Figure()
    for name, color, dash in (("Cilj", "#FBBF24", "dash"), ("Prognoza", "#A78BFA", "dot"), ("Stvarno", "#22D3EE", "solid")):
        fig.add_trace(go.Scatter(x=trend["CW"].tolist(), y=trend[name].tolist(), mode="lines+markers", name=name,
                                 connectgaps=False, line=dict(color=color, width=3, dash=dash), marker=dict(size=9)))
    fig = style_chart(fig)
    fig.update_layout(title=dict(text=f"IWON · {project} · {process} · {machine} · {year}"), height=380, showlegend=True)
    fig.update_xaxes(type="category")
    fig.update_yaxes(ticksuffix=" %")
    st.plotly_chart(fig, use_container_width=True, key="iwon_view_trend")
    shown = trend.copy()
    shown["Odstupanje (pp)"] = [round(a - t, 2) if a is not None and t is not None else None
                                for a, t in zip(shown["Stvarno"], shown["Cilj"])]
    st.dataframe(shown, use_container_width=True, hide_index=True)

    st.markdown(f"### CW{week:02d} · plan")
    if week in planned_weeks:
        try:
            show_iwon_week_view(year, int(week), project, process, machine)
        except Exception as exc:
            st.warning(str(exc))
    else:
        st.info(f"CW{week:02d} ima cilj {_sr_pct(targets.get(week, 0), 1)}, ali plan po mašini još nije napravljen "
                "(dugme iznad ili Administration → 🔒 IWON → Plan i prognoza).")

    actual_week = oi.actual_for_week(actual_df, year, week, project, process, aggregate_oee)
    week_plan = results[results["CW"] == week]
    if actual_week and not week_plan.empty:
        st.markdown(f"### CW{week:02d} · plan i stvarno po mašini")
        table = []
        for _, plan_row in week_plan.iterrows():
            got = actual_week.get(str(plan_row["Machine"]).strip())
            table.append({
                "Mašina": plan_row["Machine"],
                "Plan A/P/Q": f"{plan_row['Availability']:.1f} / {plan_row['Performance']:.1f} / {plan_row['Quality']:.1f}",
                "Stvarno A/P/Q": f"{got[0]:.1f} / {got[1]:.1f} / {got[2]:.1f}" if got else "—",
                "Cilj %": round(float(plan_row["OEE"]), 2), "Stvarno %": round(got[3], 2) if got else None,
                "Odstupanje (pp)": round(got[3] - float(plan_row["OEE"]), 2) if got else None,
            })
        st.dataframe(pd.DataFrame(table), use_container_width=True, hide_index=True)

    acc = oi.forecast_accuracy(compare) if not compare.empty else {"weeks": 0}
    if acc.get("weeks"):
        st.markdown(ui.stat_tiles_html([
            {"label": "Osveženih nedelja", "value": str(acc["weeks"]), "status": "neutral"},
            {"label": "Prosečna greška prognoze", "value": f"{acc['forecast_mae']:.1f} pp".replace(".", ","), "status": "neutral"},
            {"label": "Prosečno odstupanje od cilja", "value": f"{acc['plan_bias']:+.1f} pp".replace(".", ","),
             "status": "ok" if acc["plan_bias"] >= 0 else "warn",
             "foot": f"cilj dostignut u {acc['plan_hit_weeks']} od {acc['weeks']} nedelja", "foot_status": "flat"},
            {"label": "Najveća greška u", "value": acc["worst_component"], "status": "neutral"},
        ]), unsafe_allow_html=True)

    cause_df = load_iwon_tab(IWON_CAUSE_SHEET_NAME)
    kmask = _iwon_scope_mask(cause_df, year, project, process, [week])
    causes = cause_df[kmask] if len(kmask) else pd.DataFrame()
    if machine != "Sve" and not causes.empty:
        causes = causes[causes["Machine"].astype(str).str.casefold() == machine.casefold()]
    if not causes.empty:
        def fmt(value, decimals=1):
            number = _num_or_blank(value, decimals)
            return "" if number is None else f"{number}".replace(".", ",")

        st.markdown(f"### CW{week:02d} · šta mora da se promeni po uzroku")
        st.dataframe(pd.DataFrame({
            "Razlog": causes["Cause"], "Mašina": causes["Machine"], "Način": causes["Lever"],
            "Sada": [f"{fmt(f)}×/ned · Ø {fmt(a)} min" for f, a in zip(causes["Now_Per_Week"], causes["Now_Avg_Min"])],
            "Najbolje postignuto": [f"{fmt(f)}×/ned · Ø {fmt(a)} min" for f, a in zip(causes["Best_Per_Week"], causes["Best_Avg_Min"])],
            "Potrebno": [f"{fmt(f)}×/ned · Ø {fmt(a)} min" for f, a in zip(causes["Target_Per_Week"], causes["Target_Avg_Min"])],
            "Ocena": causes["Rating"],
            "Stvarno": [f"{fmt(f, 0)}× · Ø {fmt(a)} min" if str(r).strip() else "—"
                        for f, a, r in zip(causes["Actual_Per_Week"], causes["Actual_Avg_Min"], causes["Refreshed_At"])],
        }), use_container_width=True, hide_index=True)
        st.caption("Najbolje postignuto = najbržih 20 % slučajeva i najređa nedelja iz osnove. "
                   "Realno = već se često dešavalo; izazovno = retko; nerealno = brže/ređe nego ikad.")


# =========================
# v11: DOWNTIME REPORT DURING THE SHIFT (phone) + OEE SETTINGS (Administration)
# =========================
def render_oee_settings_admin(can_edit):
    st.markdown("### OEE podešavanja")
    st.caption("Cena komada (za prikaz gubitka u €), opisi procesa za ljude van linije, e-mail uprave i lista uzroka zastoja.")
    try:
        master, _missing = load_oee_master()
    except Exception as exc:
        st.error(f"MASTER_DATA nije dostupan: {exc}")
        return
    settings = load_oee_settings()
    projects = sorted(master["Project"].astype(str).unique().tolist()) if not master.empty else []
    prices = pd.DataFrame({"Projekat": projects,
                           "Cena komada (€)": [pd.to_numeric(str(settings.get((SETTING_PRICE, p.casefold()), "")).replace(",", "."),
                                                             errors="coerce") for p in projects]})
    st.markdown("#### Cena komada po projektu")
    edited_prices = st.data_editor(prices, hide_index=True, use_container_width=True, disabled=["Projekat"],
                                   key="oee_settings_prices")
    scopes = master[["Project", "Process"]].drop_duplicates().sort_values(["Project", "Process"]) if not master.empty else pd.DataFrame()
    descriptions = pd.DataFrame({
        "Projekat": scopes["Project"].astype(str).tolist() if not scopes.empty else [],
        "Proces": scopes["Process"].astype(str).tolist() if not scopes.empty else [],
        "Opis (proizvod, kupac, šta linija radi)": [settings.get((SETTING_DESCRIPTION, f"{p}|{q}".casefold()), "")
                                                    for p, q in scopes.itertuples(index=False)] if not scopes.empty else [],
    })
    st.markdown("#### Opis procesa")
    edited_desc = st.data_editor(descriptions, hide_index=True, use_container_width=True, disabled=["Projekat", "Proces"],
                                 key="oee_settings_descriptions")
    st.markdown("#### Nedeljni e-mail upravi (ponedeljkom od 07:00)")
    emails = st.text_input("Primaoci (odvojeni zarezom)", value=settings.get((SETTING_MGMT_EMAIL, ""), ""), key="oee_settings_emails")
    active = st.checkbox("Šalji automatski", value=str(settings.get((SETTING_MGMT_EMAIL_ON, ""), "NO")).upper() == "YES",
                         key="oee_settings_email_on")
    if st.button("Sačuvaj podešavanja", type="primary", disabled=not can_edit, key="oee_settings_save"):
        records = []
        for _, row in edited_prices.iterrows():
            value = row["Cena komada (€)"]
            records.append((SETTING_PRICE, row["Projekat"], "" if pd.isna(value) else str(value)))
        for _, row in edited_desc.iterrows():
            records.append((SETTING_DESCRIPTION, f"{row['Projekat']}|{row['Proces']}",
                            str(row["Opis (proizvod, kupac, šta linija radi)"] or "")))
        records.append((SETTING_MGMT_EMAIL, "", emails))
        records.append((SETTING_MGMT_EMAIL_ON, "", "YES" if active else "NO"))
        try:
            save_oee_settings(records)
            st.success("Podešavanja su sačuvana.")
        except Exception as exc:
            st.error(f"Podešavanja nisu sačuvana: {exc}")
    if st.button("Pošalji probni e-mail upravi (prošla nedelja)", disabled=not can_edit, key="oee_settings_test_email"):
        result = run_weekly_management_email(force=True)
        if result.get("status") == "sent":
            st.success(f"Poslato za {result.get('week')}.")
        else:
            st.warning(f"E-mail nije poslat: {result}")

    render_machine_map_admin(can_edit)

    st.markdown("#### Uzroci zastoja")
    st.caption("„ređe“ = gubitak se smanjuje tako da se ređe dešava (kvarovi); „kraće“ = da kraće traje (zamene, podešavanja). "
               "Obrisan uzrok se samo isključuje, stari podaci ostaju.")
    causes = load_downtime_causes()[["Loss_Type", "Cause", "Lever", "Active"]]
    edited_causes = st.data_editor(
        causes, num_rows="dynamic", hide_index=True, use_container_width=True, key="oee_settings_causes",
        column_config={
            "Loss_Type": st.column_config.SelectboxColumn("Vrsta", options=oi.LOSS_TYPES, required=True),
            "Cause": st.column_config.TextColumn("Uzrok", required=True),
            "Lever": st.column_config.SelectboxColumn("Kako se smanjuje", options=[oi.LEVER_FREQUENCY, oi.LEVER_DURATION]),
            "Active": st.column_config.SelectboxColumn("Aktivan", options=["YES", "NO"]),
        },
    )
    if st.button("Sačuvaj uzroke", disabled=not can_edit, key="oee_settings_causes_save"):
        try:
            save_downtime_causes(edited_causes)
            st.success("Lista uzroka je sačuvana.")
        except Exception as exc:
            st.error(f"Uzroci nisu sačuvani: {exc}")


# =========================
# v11.3: MAINTENANCE FORM vs DOWNTIME IN OEE (comparison only; OEE is still calculated from the OEE input)
# =========================
MAINT_FORM_TAB_NAMES = ["Form_Responses", "Form Responses"]
MAINT_FORM_TAB_GID = 2121542464
MAINT_MAP_SHEET_NAME = "MAINT_MACHINE_MAP"


@st.cache_data(ttl=600, show_spinner=False)
def load_maintenance_values():
    """All rows of the maintenance downtime form (read-only; the app is a viewer)."""
    spreadsheet = get_spreadsheet(PROCESS_DOWNTIME_SHEET_ID)
    ws = None
    for name in MAINT_FORM_TAB_NAMES:
        try:
            ws = spreadsheet.worksheet(name)
            break
        except gspread.exceptions.WorksheetNotFound:
            continue
    if ws is None and hasattr(spreadsheet, "get_worksheet_by_id"):
        ws = spreadsheet.get_worksheet_by_id(MAINT_FORM_TAB_GID)
    if ws is None:
        raise gspread.exceptions.WorksheetNotFound("Form_Responses")
    return ws.get_all_values()


@st.cache_data(ttl=3600, show_spinner=False)
def load_machine_map():
    try:
        _, _, df = _tab_frame(OEE_SHEET_ID, MAINT_MAP_SHEET_NAME, oi.MAINT_MAP_COLUMNS)
        return df.drop(columns=["_row"], errors="ignore")
    except Exception:
        return pd.DataFrame(columns=oi.MAINT_MAP_COLUMNS)


def save_machine_map(records):
    ws, headers, df = _tab_frame(OEE_SHEET_ID, MAINT_MAP_SHEET_NAME, oi.MAINT_MAP_COLUMNS, live=True)
    who = _current_user_display_name()
    now = _now_local().strftime("%Y-%m-%d %H:%M:%S")
    rows = [{**r, "Updated_By": who, "Updated_At": now} for r in records]
    _upsert_tab_rows(ws, headers, oi.MAINT_MAP_COLUMNS, df, ["Form_Project", "Form_Machine"], rows)
    load_machine_map.clear()


def maintenance_events():
    """(events, mapping, error) - maintenance records mapped to OEE machines."""
    try:
        values = load_maintenance_values()
    except Exception as exc:
        return pd.DataFrame(columns=oi.MAINT_EVENT_COLUMNS), {}, f"{type(exc).__name__}: {exc}"
    master, _missing = load_oee_master()
    mapping = oi.auto_machine_map(oi.maintenance_machine_pairs(values), master, load_machine_map())
    return oi.maintenance_rows_to_events(values, mapping), mapping, None


def _period_bounds(view, value):
    if view == "Dan":
        start = pd.Timestamp(value).normalize()
        return start, start
    if view == "Nedelja":
        start = oi.week_start(*value)
        return start, start + pd.Timedelta(days=6)
    if view == "Mesec":
        start = pd.Timestamp(value[0], value[1], 1)
        return start, start + pd.offsets.MonthEnd(0)
    return pd.Timestamp(int(value), 1, 1), pd.Timestamp(int(value), 12, 31)


def render_downtime_compare_page():
    st.caption("OEE se i dalje računa samo iz OEE unosa. Ova strana poredi zastoje upisane u OEE sa zastojima "
               "koje je održavanje upisalo u svoju formu, za istu mašinu i isti dan (noćna smena posle ponoći "
               "pripada prethodnom danu, isto kao u OEE unosu).")
    events, mapping, error = maintenance_events()
    if error:
        st.error("Forma održavanja nije dostupna. Proveri da je aplikacija (service account) dodata kao Viewer "
                 f"i da tab „Form_Responses“ postoji. Detalj: {error}")
        return
    try:
        oee_df, _missing = load_oee_input()
    except Exception as exc:
        st.error(f"OEE unos nije dostupan: {exc}")
        return
    master, _missing = load_oee_master()

    dates = set()
    if oee_df is not None and not oee_df.empty:
        dates |= set(pd.to_datetime(oee_df["Datum"], errors="coerce").dt.normalize().dropna())
    if not events.empty:
        dates |= set(pd.to_datetime(events["Datum"], errors="coerce").dropna())
    if not dates:
        st.info("Još nema ni OEE unosa ni zapisa održavanja.")
        return
    dates = sorted(dates)

    c_view, c_period, c_planned = st.columns([2, 2, 2])
    with c_view:
        view = st.radio("Prikaz", ["Dan", "Nedelja", "Mesec", "Godina"], index=1, horizontal=True, key="mt_view")
    with c_period:
        if view == "Dan":
            options = [d.date() for d in dates]
            fmt = lambda d: pd.Timestamp(d).strftime("%d.%m.%Y")
        elif view == "Nedelja":
            options = sorted({(int(d.isocalendar()[0]), int(d.isocalendar()[1])) for d in dates})
            fmt = lambda x: f"{x[0]}-CW{x[1]:02d}"
        elif view == "Mesec":
            options = sorted({(d.year, d.month) for d in dates})
            fmt = lambda x: f"{_SR_MONTHS[x[1] - 1]} {x[0]}"
        else:
            options = sorted({d.year for d in dates})
            fmt = str
        key = f"mt_period_{view}"
        if st.session_state.get(key) not in options:
            st.session_state[key] = options[-1]
        period = st.selectbox("Period", options, key=key, format_func=fmt)
    with c_planned:
        st.write("")
        include_planned = st.checkbox("Uračunaj i planirane zastoje održavanja", key="mt_planned")
    start, end = _period_bounds(view, period)

    scopes = master[["Project", "Process", "Machine"]].drop_duplicates().astype(str) if not master.empty else pd.DataFrame()
    c_project, c_process, c_machine = st.columns(3)
    with c_project:
        project = st.selectbox("Projekat", ["Svi"] + sorted(scopes["Project"].unique().tolist()), key="mt_project")
    process_pool = scopes if project == "Svi" else scopes[scopes["Project"] == project]
    with c_process:
        process = st.selectbox("Proces", ["Svi"] + sorted(process_pool["Process"].unique().tolist()), key="mt_process")
    machine_pool = process_pool if process == "Svi" else process_pool[process_pool["Process"] == process]
    with c_machine:
        machine = st.selectbox("Mašina", ["Sve"] + sorted(machine_pool["Machine"].unique().tolist()), key="mt_machine")

    def scope_filter(df):
        if df is None or df.empty:
            return df
        out = df[(pd.to_datetime(df["Datum"], errors="coerce").dt.normalize() >= start)
                 & (pd.to_datetime(df["Datum"], errors="coerce").dt.normalize() <= end)]
        if project != "Svi":
            out = out[out["Project"].astype(str) == project]
        if process != "Svi":
            out = out[out["Process"].astype(str) == process]
        if machine != "Sve":
            out = out[out["Machine"].astype(str) == machine]
        return out

    oee_period = scope_filter(oee_df) if oee_df is not None and not oee_df.empty else pd.DataFrame()
    period_events = events[(events["Datum"] >= start) & (events["Datum"] <= end)] if not events.empty else events
    unmapped = period_events[period_events["Machine"] == ""] if not period_events.empty else period_events
    mapped = scope_filter(period_events[period_events["Machine"] != ""]) if not period_events.empty else period_events
    if unmapped is not None and not unmapped.empty:
        ignored = {k for k, v in mapping.items() if v is None}
        open_ones = unmapped[[(oi._alnum(p), oi._alnum(m)) not in ignored for p, m in zip(unmapped["Form_Project"], unmapped["Form_Machine"])]]
        if not open_ones.empty:
            names = sorted({f"{p} · {m}" for p, m in zip(open_ones["Form_Project"], open_ones["Form_Machine"])})
            st.warning(f"{len(open_ones)} zapisa održavanja ({_sr_num(round(open_ones['Minutes'].sum()))} min) nije povezano sa OEE mašinom: "
                       + ", ".join(names[:8]) + (" …" if len(names) > 8 else "")
                       + ". Poveži ih u Administration → OEE podešavanja → Mašine iz forme održavanja.")

    comparison = oi.compare_downtime(oee_period, mapped, include_planned=include_planned)
    if comparison.empty:
        st.info("Za izabrani period i filtere nema ni OEE zastoja ni zapisa održavanja.")
        return
    days = comparison[(comparison["OEE_Shifts"] > 0) | (comparison["Maint_Count"] > 0)]
    ok_days = int((days["Status"] == "slaže se").sum())
    oee_total, maint_total = float(comparison["OEE_Down"].sum()), float(comparison["Maint_Min"].sum())
    diff_total = oee_total - maint_total
    st.markdown(ui.stat_tiles_html([
        {"label": "Zastoj upisan u OEE", "value": f"{_sr_num(round(oee_total))} min", "status": "neutral",
         "sub": f"organizacioni gubici još {_sr_num(round(comparison['OEE_Org'].sum()))} min"},
        {"label": "Zastoj po formi održavanja", "value": f"{_sr_num(round(maint_total))} min", "status": "neutral",
         "sub": f"{int(comparison['Maint_Count'].sum())} intervencija"
                + ("" if include_planned else f" · planirani {_sr_num(round(comparison['Maint_Planned_Min'].sum()))} min nisu uračunati")},
        {"label": "Razlika (OEE − održavanje)", "value": f"{'+' if diff_total > 0 else ''}{_sr_num(round(diff_total))} min",
         "status": "ok" if abs(diff_total) <= max(5, 0.1 * max(oee_total, maint_total)) else "warn"},
        {"label": "Mašina-dana koja se slažu", "value": f"{ok_days} od {len(days)}",
         "status": "ok" if ok_days == len(days) else ("warn" if ok_days >= len(days) / 2 else "alarm"),
         "sub": "tolerancija 5 min ili 10 %"},
    ]), unsafe_allow_html=True)

    work = comparison.copy()
    if view == "Godina":
        work["_x"] = work["Datum"].dt.month.map(lambda m: _SR_MONTHS[m - 1])
        order = [_SR_MONTHS[m - 1] for m in sorted(work["Datum"].dt.month.unique())]
        x_title = "Mesec"
    elif view == "Dan":
        work["_x"] = work["Machine"].astype(str)
        order = sorted(work["_x"].unique())
        x_title = "Mašina"
    else:
        work["_x"] = work["Datum"].map(lambda d: f"{_SR_WEEKDAYS[d.weekday()]} {d:%d.%m}")
        order = [f"{_SR_WEEKDAYS[d.weekday()]} {d:%d.%m}" for d in sorted(work["Datum"].unique())]
        x_title = "Dan"
    by_x = oi.summarize_comparison(work, ["_x"]).set_index("_x").reindex(order).fillna(0).reset_index()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=by_x["_x"].tolist(), y=by_x["OEE_Down"].tolist(), name="OEE unos", marker=dict(color="#22D3EE"),
                         text=[_sr_num(round(v)) for v in by_x["OEE_Down"]], textposition="outside"))
    fig.add_trace(go.Bar(x=by_x["_x"].tolist(), y=by_x["Maint_Min"].tolist(), name="Forma održavanja", marker=dict(color="#F59E0B"),
                         text=[_sr_num(round(v)) for v in by_x["Maint_Min"]], textposition="outside"))
    fig = style_chart(fig)
    fig.update_layout(title=dict(text=f"Zastoj (min): OEE unos naspram forme održavanja · {fmt(period)}"), barmode="group",
                      height=380, showlegend=True)
    fig.update_xaxes(type="category", title=x_title)
    fig.update_yaxes(title="min")
    st.plotly_chart(fig, use_container_width=True, key="mt_compare_chart")

    st.markdown("### Po mašini")
    per_machine = oi.summarize_comparison(comparison, ["Project", "Process", "Machine"])
    per_machine["Razlika"] = per_machine["Diff"]
    st.dataframe(pd.DataFrame({
        "Projekat": per_machine["Project"], "Proces": per_machine["Process"], "Mašina": per_machine["Machine"],
        "OEE zastoj (min)": per_machine["OEE_Down"].round(0), "Održavanje (min)": per_machine["Maint_Min"].round(0),
        "Razlika OEE − održ. (min)": per_machine["Diff"].round(0), "Intervencija": per_machine["Maint_Count"].astype(int),
        "Dana se slaže": [f"{int(o)} / {int(d)}" for o, d in zip(per_machine["Days_OK"], per_machine["Days"])],
    }).sort_values("Razlika OEE − održ. (min)", key=lambda s: s.abs(), ascending=False),
        use_container_width=True, hide_index=True)

    st.markdown("### Po mašini i danu")
    only_diff = st.checkbox("Prikaži samo dane sa razlikom", value=True, key="mt_only_diff")
    detail = comparison if not only_diff else comparison[comparison["Status"] != "slaže se"]
    st.dataframe(pd.DataFrame({
        "Datum": detail["Datum"].dt.strftime("%d.%m.%Y"), "Mašina": detail["Machine"], "Proces": detail["Process"],
        "OEE zastoj": detail["OEE_Down"].round(0), "Održavanje": detail["Maint_Min"].round(0),
        "Razlika": detail["Diff"].round(0), "Intervencija": detail["Maint_Count"].astype(int), "Status": detail["Status"],
    }), use_container_width=True, hide_index=True)

    choices = [(r["Datum"], r["Project"], r["Process"], r["Machine"]) for _, r in detail.iterrows()]
    if not choices:
        return
    st.markdown("### Detalj jednog dana")
    pick = st.selectbox("Mašina i dan", choices, key="mt_detail",
                        format_func=lambda c: f"{c[0]:%d.%m.%Y} · {c[3]} ({c[2]})")
    day, d_project, d_process, d_machine = pick
    left, right = st.columns(2)
    with left:
        st.markdown("**Upisano u OEE**")
        rows = oee_df[(pd.to_datetime(oee_df["Datum"]).dt.normalize() == day) & (oee_df["Machine"].astype(str) == d_machine)
                      & (oee_df["Process"].astype(str) == d_process)]
        if rows.empty:
            st.caption("Za ovaj dan nema OEE unosa.")
        else:
            st.dataframe(pd.DataFrame({"Smena": rows["Shift"], "Zastoj (min)": rows["Down time"],
                                       "Org. gubici (min)": rows["Organisational loss"], "Upisao": rows["Submitted_By"]}),
                         use_container_width=True, hide_index=True)
        reasons = load_all_downtime_events()
        if not reasons.empty:
            reasons = reasons[(reasons["Datum"] == day) & (reasons["Machine"] == d_machine) & (reasons["Process"] == d_process)]
        if reasons is not None and not reasons.empty:
            st.dataframe(pd.DataFrame({"Smena": reasons["Shift"], "Razlog": reasons["Cause"], "Min": reasons["Minutes"],
                                       "Vrsta": reasons["Loss_Type"]}), use_container_width=True, hide_index=True)
    with right:
        st.markdown("**Upisalo održavanje**")
        records = mapped[(mapped["Datum"] == day) & (mapped["Machine"] == d_machine) & (mapped["Process"] == d_process)]
        if records.empty:
            st.caption("Održavanje za ovaj dan nema zapis.")
        else:
            st.dataframe(pd.DataFrame({
                "Od–do": records["Start_Time"] + "–" + records["End_Time"], "Min": records["Minutes"],
                "Stanica": records["Station"], "Uzrok": records["Category"], "Tip": records["Type"],
                "Razlog": records["Reason"], "Rešenje": records["Solution"], "Upisao": records["Name"],
            }), use_container_width=True, hide_index=True)


def render_machine_map_admin(can_edit):
    st.markdown("#### Mašine iz forme održavanja")
    st.caption("Forma održavanja piše mašine drugačije (npr. „APP-350 · ROTOR L1“). Ovde se jednom poveže svaka "
               "mašina iz forme sa OEE mašinom. Gde je naziv jednoznačan, veza je već predložena.")
    try:
        values = load_maintenance_values()
    except Exception as exc:
        st.warning(f"Forma održavanja nije dostupna: {exc}")
        return
    master, _missing = load_oee_master()
    pairs = oi.maintenance_machine_pairs(values)
    if pairs.empty:
        st.info("U formi održavanja još nema zapisa sa mašinom.")
        return
    mapping = oi.auto_machine_map(pairs, master, load_machine_map())
    options = [oi.MAP_IGNORE] + [f"{p} · {q} · {m}" for p, q, m in
                                 master[["Project", "Process", "Machine"]].drop_duplicates().astype(str).itertuples(index=False)]
    current = []
    for pair in pairs.to_dict("records"):
        target = mapping.get((oi._alnum(pair["Form_Project"]), oi._alnum(pair["Form_Machine"])), "missing")
        if target == "missing":
            label = None
        elif target is None:
            label = oi.MAP_IGNORE
        else:
            label = f"{target[0]} · {target[1]} · {target[2]}"
        current.append({"Projekat u formi": pair["Form_Project"], "Mašina u formi": pair["Form_Machine"],
                        "Zapisa": int(pair["Records"]), "OEE mašina": label})
    edited = st.data_editor(
        pd.DataFrame(current), hide_index=True, use_container_width=True, key="maint_map_editor",
        disabled=["Projekat u formi", "Mašina u formi", "Zapisa"],
        column_config={"OEE mašina": st.column_config.SelectboxColumn("OEE mašina", options=options)},
    )
    missing = int(edited["OEE mašina"].isna().sum()) if "OEE mašina" in edited.columns else 0
    if missing:
        st.caption(f"Bez veze: {missing} mašina iz forme (njihovi zastoji se ne porede).")
    if st.button("Sačuvaj veze mašina", disabled=not can_edit, key="maint_map_save"):
        records = []
        for row in edited.to_dict("records"):
            label = row.get("OEE mašina")
            if not label:
                continue
            if label == oi.MAP_IGNORE:
                records.append({"Form_Project": row["Projekat u formi"], "Form_Machine": row["Mašina u formi"],
                                "OEE_Project": "", "OEE_Process": "", "OEE_Machine": oi.MAP_IGNORE})
            else:
                p, q, m = [part.strip() for part in str(label).split(" · ", 2)]
                records.append({"Form_Project": row["Projekat u formi"], "Form_Machine": row["Mašina u formi"],
                                "OEE_Project": p, "OEE_Process": q, "OEE_Machine": m})
        try:
            save_machine_map(records)
            st.success(f"Sačuvano {len(records)} veza.")
        except Exception as exc:
            st.error(f"Veze nisu sačuvane: {exc}")


def show_oee_clean_view(period_base, metric_col, machine_filter, period_label, trend_group_cols, trend_x_col, key_prefix, page_name=None, ctx=None):
    """Selected Project + selected Process OEE view.

    Machine = Sve:
        - summary is GLOBAL process OEE calculated from summed raw data
        - trend charts show daily/weekly/monthly global process OEE components
        - table shows each machine separately

    Machine = one machine:
        - summary and trend charts show only the selected machine
    """
    if period_base.empty:
        st.warning(f"Nema OEE podataka za {period_label}.")
        return

    metric_label = OEE_METRIC_LABELS.get(metric_col, metric_col)
    availability_col, performance_col = get_oee_component_columns(metric_col)

    # A period is the denominator-weighted average of independently calculated daily KPIs.
    # Over-performance on one day cannot erase a weaker day.
    if ctx:
        render_oee_manager_summary(period_base, metric_col, ctx)
    else:
        summary = aggregate_oee_as_weighted_daily(period_base)
        show_oee_single_kpi_and_breakdown(summary, metric_col, key_prefix)

    raw_performance_col = (
        "Machine_Performance_CT_Raw_%"
        if metric_col == "Machine_OEE_CT_%"
        else "Plant_Performance_CT_Raw_%"
    )
    if metric_col in ("Machine_OEE_CT_%", "Plant_OEE_CT_%") and raw_performance_col in period_base.columns:
        suspicious = period_base[pd.to_numeric(period_base[raw_performance_col], errors="coerce").fillna(0) > 100.0001]
        if not suspicious.empty:
            suspicious_days = sorted(parse_oee_date_series(suspicious["Datum"]).dropna().dt.strftime("%d.%m.%Y").unique().tolist())
            st.warning(
                "CT Performance je pre ograničenja iznad 100% za: " + ", ".join(suspicious_days) +
                ". Proveri da li je CT u MASTER_DATA vreme za jedan komad ili za više komada po ciklusu."
            )

    if machine_filter == "Sve":
        st.caption("Mašina = Sve: OEE perioda je ponderisani prosek dnevnih rezultata celog procesa.")

    st.markdown("### Trend po periodu")
    render_oee_drilldown(
        period_base, metric_col, machine_filter, period_label,
        OEE_X_COL_LEVEL.get(trend_x_col, "day"), key_prefix, page_name,
    )

    loss_col, shift_col = st.columns(2)
    with loss_col:
        pareto = render_loss_pareto(period_base)
    with shift_col:
        render_oee_shift_compare(period_base, metric_col)

    if machine_filter == "Sve":
        st.markdown("### Poređenje mašina")
        render_oee_machine_compare(period_base, metric_col, period_label, key_prefix)

    if ctx and ctx.get("project"):
        render_oee_actions(ctx["project"], ctx["process"], machine_filter, pareto, key_prefix, can_edit_module("OEE"))

    table = aggregate_oee(period_base, ["Project", "Process", "Machine"])
    if not table.empty:
        st.markdown("### Tabela podataka")
        table_cols = [
            "Project", "Process", "Machine",
            metric_col,
            "Machine_Availability_%", "Plant_Availability_%",
            "Machine_Performance_CT_%", "Plant_Performance_CT_%",
            "Performance_Target_%", "Quality_%",
            "Open_Time", "Down_Time", "Organisational_Loss",
            "OK_pcs", "NOK_pcs", "Total_Pcs", "Target_pcs", "Records",
        ]
        table_cols = [c for c in table_cols if c in table.columns]
        st.dataframe(format_oee_percent_columns(table[table_cols]), use_container_width=True)


if selected_module == "Administration":
    render_administration_module()
    st.stop()

if selected_module in ["Work Tickets", "My Tasks"]:
    render_work_tickets_module()

if selected_module == "Uprava":
    render_uprava_module()
    st.stop()

if selected_module == "OEE":
    if not can_view_module("OEE"):
        st.error("Nemaš dozvolu za OEE modul.")
        st.stop()
    can_edit_oee = can_edit_module("OEE")
    if not can_edit_oee:
        st.info("Read-only access: OEE analize su dostupne, ali OEE Input nije dozvoljen za ovog korisnika.")

    try:
        oee_master, master_missing = load_oee_master()
    except Exception as e:
        st.error("Ne mogu da učitam MASTER_DATA tab. Proveri naziv taba, kolone i permission.")
        st.write(e)
        st.stop()

    if master_missing:
        st.error(f"Nedostaju kolone u MASTER_DATA: {master_missing}")
        st.stop()
    if oee_master.empty:
        st.warning("MASTER_DATA nema aktivnih mašina. Proveri kolonu Active = DA.")
        st.stop()

    # OEE input must stay fast. Do not load full OEE_INPUT/dashboard data unless user opens an analysis page.
    oee_df, oee_missing = pd.DataFrame(), []
    st.markdown("""
    <style>
    div[data-testid="stRadio"] > label { display: none !important; }
    div[data-testid="stRadio"] div[role="radiogroup"] {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: wrap !important;
        gap: 0.35rem 0.75rem !important;
        width: 100% !important;
    }
    div[data-testid="stRadio"] div[role="radiogroup"] label {
        width: auto !important;
        min-width: max-content !important;
        white-space: nowrap !important;
        writing-mode: horizontal-tb !important;
        word-break: normal !important;
    }

    /* OEE Input / All shifts: dedicated toggle buttons.
       Selected-state styling is injected from Python using the exact button
       key, so it cannot depend on Streamlit's internal pills HTML. */
    .st-key-oee_shift_toggle_1st button,
    .st-key-oee_shift_toggle_2nd button,
    .st-key-oee_shift_toggle_3rd button {
        min-height: 38px !important;
        width: 100% !important;
        color: #F8FBFF !important;
        -webkit-text-fill-color: #F8FBFF !important;
        background: linear-gradient(180deg, rgba(22, 47, 78, 0.98), rgba(13, 31, 53, 0.98)) !important;
        border: 1px solid rgba(82, 152, 212, 0.75) !important;
        border-radius: 10px !important;
        transition: background 140ms ease, border-color 140ms ease,
                    box-shadow 140ms ease, transform 140ms ease !important;
    }
    @keyframes oee-selected-shift-red-glow {
        0%, 100% {
            box-shadow:
                0 0 0 2px rgba(255, 45, 45, 0.40),
                0 0 11px rgba(255, 0, 0, 0.88),
                0 0 23px rgba(255, 0, 0, 0.60),
                inset 0 1px 0 rgba(255, 255, 255, 0.32);
        }
        50% {
            box-shadow:
                0 0 0 3px rgba(255, 75, 75, 0.55),
                0 0 17px rgba(255, 0, 0, 1),
                0 0 34px rgba(255, 0, 0, 0.82),
                inset 0 1px 0 rgba(255, 255, 255, 0.42);
        }
    }
    </style>
    """, unsafe_allow_html=True)
    oee_pages = ["Dashboard", "Daily", "Weekly", "Monthly", "Yearly", "Machine Ranking", "Raw Data"]
    if can_edit_oee:
        oee_pages.insert(0, "OEE Input")
    oee_pages.insert(oee_pages.index("Raw Data"), "Maintenance")
    if can_see_iwon():
        oee_pages.append("IWON")
    if st.session_state.get("oee_page_selector") not in oee_pages:
        st.session_state["oee_page_selector"] = oee_pages[0]
    oee_page_labels = {
        "OEE Input": "✍️ Unos", "Dashboard": "📊 Dashboard", "Daily": "Dnevno", "Weekly": "Nedeljno",
        "Monthly": "Mesečno", "Yearly": "Godišnje", "Machine Ranking": "🏆 Rang mašina", "Raw Data": "🗂 Podaci",
        "IWON": "🔒 IWON", "Maintenance": "🔧 Zastoji vs održavanje",
    }
    oee_page = st.radio("OEE page", oee_pages, horizontal=True, label_visibility="collapsed", key="oee_page_selector",
                        format_func=lambda page: oee_page_labels.get(page, page))
    render_oee_drill_trail(oee_page)

    if oee_page == "IWON":
        render_iwon_view()
        st.stop()
    if oee_page == "Maintenance":
        st.subheader("Zastoji: OEE unos naspram forme održavanja")
        render_downtime_compare_page()
        st.stop()

    if oee_page == "OEE Input":
        st.subheader("OEE unos")
        st.caption("Jedinstveni ključ je: Datum + Project + Process + Machine + Shift. Pojedinačne smene se sabiraju iz sirovih podataka, pa se dnevni Availability, Performance, Q-rate i OEE računaju za ceo dan.")

        if st.session_state.pop("oee_clear_after_save", False):
            clear_oee_operational_input_fields()

        if "oee_last_success" in st.session_state:
            st.success(st.session_state.pop("oee_last_success"))
        if "_oee_save_notification_warning" in st.session_state:
            st.warning(st.session_state.pop("_oee_save_notification_warning"))

        # IMPORTANT:
        # Project / Process / Machine must be OUTSIDE st.form.
        # Streamlit forms do not refresh dependent dropdowns until submit,
        # so cascading dropdowns inside a form show stale options.
        col_date, col_shift = st.columns(2)
        with col_date:
            selected_date = st.date_input("Datum", format="DD.MM.YYYY", key="oee_selected_date")
        with col_shift:
            selected_shift = st.selectbox("Shift", OEE_SHIFT_OPTIONS, key="oee_shift_selector")

        project_options = sorted(oee_master["Project"].dropna().unique().tolist())
        selected_project = st.selectbox("Project", project_options, key="oee_project_selector")

        process_df = oee_master[oee_master["Project"].astype(str).str.strip() == str(selected_project).strip()].copy()
        process_options = sorted(process_df["Process"].dropna().unique().tolist())
        if not process_options:
            st.error("Nema procesa za izabrani projekat. Proveri MASTER_DATA.")
            st.stop()

        selected_process = st.selectbox(
            "Process",
            process_options,
            key=f"oee_process_selector_{selected_project}"
        )

        machine_df = process_df[process_df["Process"].astype(str).str.strip() == str(selected_process).strip()].copy()
        machine_options = sorted(machine_df["Machine"].dropna().unique().tolist())
        if not machine_options:
            st.error("Nema mašina za izabrani project/process. Proveri MASTER_DATA.")
            st.stop()

        selected_machine = st.selectbox(
            "Machine",
            machine_options,
            key=f"oee_machine_selector_{selected_project}_{selected_process}"
        )

        selected_master_row = machine_df[machine_df["Machine"].astype(str).str.strip() == str(selected_machine).strip()].iloc[0]
        ct = float(selected_master_row["CT"])
        target = float(selected_master_row["Target"])
        shift_min = float(selected_master_row["1 shift"])

        included_shifts = []
        if selected_shift == "All shifts":
            shift_order = ["1st", "2nd", "3rd"]
            state_key = "oee_included_shift_buttons"
            stored_shifts = st.session_state.get(state_key, [])
            if not isinstance(stored_shifts, list):
                stored_shifts = []
            included_shifts = [shift for shift in shift_order if shift in stored_shifts]
            st.session_state[state_key] = included_shifts

            # Style selected buttons using their exact keys. This is driven by
            # Python state and does not rely on undocumented st.pills markup.
            shift_button_keys = {
                "1st": "oee_shift_toggle_1st",
                "2nd": "oee_shift_toggle_2nd",
                "3rd": "oee_shift_toggle_3rd",
            }
            selected_button_selectors = ",\n".join(
                f".st-key-{shift_button_keys[shift]} button"
                for shift in included_shifts
            )
            selected_text_selectors = ",\n".join(
                f".st-key-{shift_button_keys[shift]} button *"
                for shift in included_shifts
            )
            if selected_button_selectors:
                st.markdown(f"""
                <style>
                {selected_button_selectors} {{
                    background: linear-gradient(180deg, #FF3B3B 0%, #C40000 58%, #8F0000 100%) !important;
                    background-color: #D60000 !important;
                    color: #FFFFFF !important;
                    -webkit-text-fill-color: #FFFFFF !important;
                    border: 1px solid #FF6B6B !important;
                    transform: translateY(-1px) !important;
                    box-shadow: 0 0 0 2px rgba(255,45,45,0.46), 0 0 14px rgba(255,0,0,0.96), 0 0 30px rgba(255,0,0,0.74) !important;
                    animation: oee-selected-shift-red-glow 1.35s ease-in-out infinite !important;
                }}
                {selected_text_selectors} {{
                    color: #FFFFFF !important;
                    -webkit-text-fill-color: #FFFFFF !important;
                    font-weight: 850 !important;
                }}
                </style>
                """, unsafe_allow_html=True)

            with st.container(border=True):
                st.caption("Which shifts are included?")
                shift_columns = st.columns(3)
                for shift_index, shift_name in enumerate(shift_order):
                    is_selected = shift_name in included_shifts
                    if shift_columns[shift_index].button(
                        shift_name,
                        key=shift_button_keys[shift_name],
                        type="primary" if is_selected else "secondary",
                        use_container_width=True,
                        help=f"{'Remove' if is_selected else 'Add'} {shift_name} shift",
                    ):
                        updated_shifts = included_shifts.copy()
                        if shift_name in updated_shifts:
                            updated_shifts.remove(shift_name)
                        else:
                            updated_shifts.append(shift_name)
                        st.session_state[state_key] = [
                            shift for shift in shift_order if shift in updated_shifts
                        ]
                        st.rerun()
            number_of_shifts = len(included_shifts)
        else:
            number_of_shifts = 1
            included_shifts = [_oee_included_shifts_text(selected_shift)]

        # v11: downtime already reported during the shift (phone / technicians' form)
        try:
            logged_events = oi.events_for_shift(load_all_downtime_events(), selected_date, selected_project,
                                                selected_process, selected_machine, selected_shift)
        except Exception:
            logged_events = oi.normalize_events(None)
        if not logged_events.empty:
            logged_down = logged_events.loc[logged_events["Loss_Type"] == oi.LOSS_DOWNTIME, "Minutes"].sum()
            logged_org = logged_events.loc[logged_events["Loss_Type"] == oi.LOSS_ORGANISATIONAL, "Minutes"].sum()
            st.info(f"Tokom smene je već prijavljeno {_sr_num(logged_down)} min zastoja i {_sr_num(logged_org)} min "
                    f"organizacionih gubitaka u formi tehničara ({len(logged_events)} prijava). Uračunati su automatski; ispod upiši samo ostatak.")
            st.dataframe(pd.DataFrame({
                "Od–do": logged_events["Start_Time"].astype(str) + "–" + logged_events["End_Time"].astype(str),
                "Uzrok": logged_events["Cause"], "Min": logged_events["Minutes"], "Prijavio": logged_events["Entered_By"],
            }), use_container_width=True, hide_index=True)

        open_time_preview = number_of_shifts * shift_min
        c1, c2, c3 = st.columns(3)
        c1.metric("CT [s]", ct)
        c2.metric("Target komada", round(target * number_of_shifts, 2))
        c3.metric("Otvoreno vreme [min]", round(open_time_preview, 2))

        # No st.form here on purpose: the cause rows must open as soon as minutes are typed.
        # Empty fields (no 0.00): clicking a field selects its value, so typing replaces it.
        col_ok, col_nok, col_dt, col_org = st.columns(4)
        with col_ok:
            ok_pcs = st.number_input("OK komada", min_value=0, value=None, step=1, key="oee_ok", placeholder="0")
        with col_nok:
            nok_pcs = st.number_input("NOK komada", min_value=0, value=None, step=1, key="oee_nok", placeholder="0")
        with col_dt:
            down_time = st.number_input("Zastoj [min]", min_value=0, value=None, step=1, key="oee_down", placeholder="0")
        with col_org:
            org_loss = st.number_input("Organizacioni gubici [min]", min_value=0, value=None, step=1, key="oee_org", placeholder="0")
        ok_pcs, nok_pcs = int(ok_pcs or 0), int(nok_pcs or 0)
        down_time, org_loss = float(down_time or 0), float(org_loss or 0)

        alloc_df = render_oee_cause_rows(down_time, org_loss, logged_events)
        install_select_on_focus()

        total_preview = ok_pcs + nok_pcs
        st.caption(f"CW {pd.to_datetime(selected_date).isocalendar().week} · {_SR_WEEKDAYS[pd.to_datetime(selected_date).weekday()]} · "
                   f"ukupno komada {total_preview}")
        submitted = st.button("💾 Sačuvaj / proveri postojeći zapis", type="primary", use_container_width=True, key="oee_save_btn")

        if submitted:
            if selected_shift == "All shifts" and len(included_shifts) < 2:
                st.error("Za All shifts izaberi najmanje dve smene. Za jednu smenu koristi 1st, 2nd ili 3rd shift direktno.")
            elif open_time_preview <= 0:
                st.error("Open time mora biti veći od 0. Proveri izabranu smenu i vrednost '1 shift' u MASTER_DATA.")
            elif down_time + org_loss > open_time_preview:
                st.error("Zastoj + organizacioni gubici ne smeju biti veći od otvorenog vremena.")
            elif (alloc_check := oi.check_allocation(down_time, org_loss, logged_events, alloc_df, load_downtime_causes()))["errors"]:
                for message in alloc_check["errors"]:
                    st.error(message)
                st.caption("Upisani podaci su ostali — dopuni zastoje i klikni ponovo.")
            else:
                st.session_state["oee_pending_alloc"] = {
                    "date": selected_date, "project": selected_project, "process": selected_process,
                    "machine": selected_machine, "shift": selected_shift, "allocation": alloc_check["allocation"],
                }
                row_values = build_oee_row(
                    selected_date, selected_project, selected_process, selected_machine,
                    ct, target, shift_min, number_of_shifts, ok_pcs, nok_pcs, down_time, org_loss,
                    submitted_by=get_current_oee_submitter(),
                    shift=selected_shift,
                    included_shifts=included_shifts,
                )
                try:
                    ws = get_oee_input_ws()
                    existing = find_oee_existing_record(
                        ws, selected_date, selected_project, selected_process, selected_machine, selected_shift
                    )
                    existing_row = existing["exact_row"]
                    if existing["conflicts"]:
                        conflict_names = ", ".join(sorted({item["shift"] for item in existing["conflicts"]}))
                        st.error(
                            f"Ne može da se kombinuje '{selected_shift}' sa postojećim unosom: {conflict_names}. "
                            "Za isti datum/project/process/machine koristi ili pojedinačne smene, ili jedan All shifts unos."
                        )
                    elif existing_row:
                        st.session_state["oee_pending_row"] = row_values
                        st.session_state["oee_existing_row"] = existing_row
                        st.warning(f"Zapis već postoji za {pd.to_datetime(selected_date).strftime('%d.%m.%Y')} / {selected_project} / {selected_process} / {selected_machine} / {selected_shift}. Klikni UPDATE ako želiš da zameniš postojeći red.")
                    else:
                        save_oee_record(row_values, existing_row=None, ws=ws)
                        _save_pending_oee_allocation()
                        st.session_state["oee_last_success"] = "✅ Novi OEE zapis je sačuvan. Operativna polja su očišćena."
                        st.session_state["oee_clear_after_save"] = True
                        st.rerun()
                except Exception as e:
                    st.error("Nije uspeo upis u OEE_input. Proveri permission service account-a, Sheet ID i naziv taba.")
                    st.write(e)

        if "oee_pending_row" in st.session_state and "oee_existing_row" in st.session_state:
            col_update, col_cancel = st.columns(2)
            with col_update:
                if st.button("✅ UPDATE existing record", use_container_width=True, key="oee_update_existing"):
                    try:
                        pending = st.session_state["oee_pending_row"]
                        # Re-find the row right before writing: rows can move between
                        # the duplicate warning and the click on UPDATE.
                        live_ws = get_oee_input_ws()
                        live = find_oee_existing_record(
                            live_ws, parse_mixed_datetime(pending[0]), pending[3], pending[4], pending[5], pending[16]
                        )
                        target_row = live["exact_row"]
                        if live["conflicts"]:
                            raise ValueError("U međuvremenu je unet konfliktni zapis za drugu smenu. Proveri podatke.")
                        save_oee_record(pending, existing_row=target_row, ws=live_ws)
                        _save_pending_oee_allocation()
                        del st.session_state["oee_pending_row"]
                        del st.session_state["oee_existing_row"]
                        st.session_state["oee_last_success"] = "✅ Postojeći OEE zapis je ažuriran. Operativna polja su očišćena."
                        st.session_state["oee_clear_after_save"] = True
                        st.rerun()
                    except Exception as e:
                        st.error("Update nije uspeo.")
                        st.write(e)
            with col_cancel:
                if st.button("❌ Cancel update", use_container_width=True, key="oee_cancel_update"):
                    st.session_state.pop("oee_pending_alloc", None)
                    del st.session_state["oee_pending_row"]
                    del st.session_state["oee_existing_row"]
                    st.info("Update je otkazan.")

    if oee_page != "OEE Input":
        try:
            oee_df, oee_missing = load_oee_input()
        except Exception as e:
            st.warning("OEE_input još nije učitan ili je prazan. Input forma i dalje može da radi ako tab postoji.")
            st.write(e)
            oee_df, oee_missing = pd.DataFrame(), []

    if oee_df.empty:
        if oee_page == "Dashboard":
            st.info("Još nema OEE podataka u OEE_INPUT.")
        if oee_page == "Daily": st.info("Još nema OEE podataka.")
        if oee_page == "Weekly": st.info("Još nema OEE podataka.")
        if oee_page == "Monthly": st.info("Još nema OEE podataka.")
        if oee_page == "Yearly": st.info("Još nema OEE podataka.")
        if oee_page == "Machine Ranking": st.info("Još nema OEE podataka.")
        if oee_page == "Raw Data": st.info("Još nema OEE podataka.")
    else:
        # Cached OEE data is treated as read-only; avoid duplicating the complete history on every rerun.
        oee_base = oee_df
        if sidebar_visible:
            st.sidebar.header("OEE filteri")
            st.sidebar.caption("OEE filteri su pomereni na samu OEE stranicu, pored datuma/CW/meseca/godine.")

        if oee_base.empty:
            st.warning("Nema OEE podataka za izabrane filtere.")
        else:
            if oee_page == "Dashboard":
                st.subheader("OEE — izabrani period")
                st.caption("OEE se računa za jedan projekat i jedan proces. „Mašina = Sve“ daje OEE celog procesa i poređenje mašina.")
                oee_min = oee_base["Datum"].min().date()
                oee_max = oee_base["Datum"].max().date()
                dashboard_range = st.date_input(
                    "Raspon datuma",
                    value=(oee_min, oee_max),
                    min_value=oee_min,
                    max_value=oee_max,
                    format="DD.MM.YYYY",
                    key="oee_dashboard_date_range_inline",
                )
                dashboard_base = oee_base.copy()
                if isinstance(dashboard_range, tuple) and len(dashboard_range) == 2:
                    dashboard_base = dashboard_base[(dashboard_base["Datum"] >= pd.to_datetime(dashboard_range[0])) & (dashboard_base["Datum"] <= pd.to_datetime(dashboard_range[1]))]
                dashboard_base, dashboard_project, dashboard_process, dashboard_machine_filter, dashboard_metric_col = render_oee_inline_filters(dashboard_base, "oee_dashboard_inline")
                if dashboard_metric_col == "IWON_OEE_%":
                    show_iwon_period_view(
                        dashboard_base,
                        dashboard_project,
                        dashboard_process,
                        dashboard_machine_filter,
                        "Selected period",
                        "iwon_dashboard",
                        ["Godina", "Week"],
                        "Week",
                    )
                else:
                    show_oee_clean_view(
                        dashboard_base,
                        dashboard_metric_col,
                        dashboard_machine_filter,
                        "Selected period",
                        ["Datum"],
                        "Datum",
                        "oee_dashboard_clean",
                        page_name="Dashboard",
                        ctx=oee_period_context(
                            oee_base, dashboard_base, "range", dashboard_project, dashboard_process, dashboard_machine_filter,
                            dashboard_range[0] if isinstance(dashboard_range, tuple) and len(dashboard_range) == 2 else oee_min,
                            dashboard_range[1] if isinstance(dashboard_range, tuple) and len(dashboard_range) == 2 else oee_max,
                            "izabrani period",
                        ),
                    )

            if oee_page == "Daily":
                st.subheader("OEE — dnevno")
                st.caption("OEE se računa za jedan projekat i jedan proces. „Mašina = Sve“ daje OEE celog procesa i poređenje mašina.")

                available_daily_dates = sorted(oee_base["Datum"].dropna().dt.date.unique().tolist())
                col_date, col_rest = st.columns([1, 4])
                with col_date:
                    selected_daily_date = st.selectbox(
                        "Izaberi datum",
                        options=available_daily_dates,
                        **_oee_index_kwargs("oee_daily_selected_date", available_daily_dates),
                        format_func=lambda d: pd.to_datetime(d).strftime("%d.%m.%Y"),
                        key="oee_daily_selected_date",
                    )
                day_oee_base = oee_base[oee_base["Datum"].dt.date == selected_daily_date].copy()
                with col_rest:
                    day_oee_base, daily_project, daily_process, daily_machine_filter, daily_metric_col = render_oee_inline_filters(day_oee_base, "oee_daily_inline")
                date_label = pd.to_datetime(selected_daily_date).strftime("%d.%m.%Y")
                if daily_metric_col == "IWON_OEE_%":
                    show_iwon_period_view(
                        day_oee_base,
                        daily_project,
                        daily_process,
                        daily_machine_filter,
                        date_label,
                        "iwon_daily",
                    )
                else:
                    show_oee_daily_bar_view(
                        day_oee_base,
                        daily_metric_col,
                        daily_machine_filter,
                        date_label,
                        "oee_daily_clean",
                        ctx=oee_period_context(oee_base, day_oee_base, "day", daily_project, daily_process,
                                               daily_machine_filter, selected_daily_date, selected_daily_date, date_label),
                    )

            if oee_page == "Weekly":
                st.subheader("OEE — nedeljno")
                st.caption("OEE se računa za jedan projekat i jedan proces. „Mašina = Sve“ daje OEE celog procesa i poređenje mašina.")

                # Week list is built from recalculated ISO week based on real Datum,
                # not from row order or manually entered CW values.
                week_options_df = oee_base[["Godina", "Week"]].drop_duplicates().sort_values(["Godina", "Week"])
                week_options = [(int(r.Godina), int(r.Week)) for r in week_options_df.itertuples(index=False)]
                col_week, col_rest = st.columns([1, 4])
                with col_week:
                    selected_week = st.selectbox(
                        "Izaberi CW",
                        options=week_options,
                        **_oee_index_kwargs("oee_weekly_selected_week", week_options),
                        format_func=lambda x: f"{x[0]}-CW{str(x[1]).zfill(2)}",
                        key="oee_weekly_selected_week",
                    )
                week_base = oee_base[(oee_base["Godina"] == selected_week[0]) & (oee_base["Week"] == selected_week[1])].copy()
                with col_rest:
                    week_base, weekly_project, weekly_process, weekly_machine_filter, weekly_metric_col = render_oee_inline_filters(week_base, "oee_weekly_inline")
                week_label = f"{selected_week[0]}-CW{str(selected_week[1]).zfill(2)}"
                if weekly_metric_col == "IWON_OEE_%":
                    st.caption(
                        "OEE IWON = sačuvani management target scenario. "
                        "Prikazuju se samo Target OEE / Availability / Performance / Q-rate; "
                        "Actual i Improvement nisu prikazani."
                    )
                    try:
                        # IMPORTANT: Weekly IWON is read-only. It always reads the saved OEE_IWON sheet.
                        # Generation/refresh is performed only from Administration.
                        show_iwon_week_view(
                            selected_week[0], selected_week[1],
                            weekly_project, weekly_process,
                            weekly_machine_filter,
                        )
                    except Exception as e:
                        st.warning(str(e))
                else:
                    show_oee_clean_view(
                        week_base,
                        weekly_metric_col,
                        weekly_machine_filter,
                        week_label,
                        ["Datum"],
                        "Datum",
                        "oee_weekly_clean",
                        page_name="Weekly",
                        ctx=oee_period_context(
                            oee_base, week_base, "week", weekly_project, weekly_process, weekly_machine_filter,
                            oi.week_start(*selected_week), oi.week_start(*selected_week) + pd.Timedelta(days=6), week_label,
                        ),
                    )

            if oee_page == "Monthly":
                st.subheader("OEE — mesečno")
                st.caption("OEE se računa za jedan projekat i jedan proces. „Mašina = Sve“ daje OEE celog procesa i poređenje mašina.")

                month_options_df = oee_base[["Calendar_Year", "Mesec"]].drop_duplicates().sort_values(["Calendar_Year", "Mesec"])
                month_options = [(int(r.Calendar_Year), int(r.Mesec)) for r in month_options_df.itertuples(index=False)]
                col_month, col_rest = st.columns([1, 4])
                with col_month:
                    selected_month_oee = st.selectbox(
                        "Izaberi mesec",
                        options=month_options,
                        **_oee_index_kwargs("oee_monthly_selected_month", month_options),
                        format_func=lambda x: f"{x[0]}-{str(x[1]).zfill(2)}",
                        key="oee_monthly_selected_month",
                    )
                month_base = oee_base[(oee_base["Calendar_Year"] == selected_month_oee[0]) & (oee_base["Mesec"] == selected_month_oee[1])].copy()
                with col_rest:
                    month_base, monthly_project, monthly_process, monthly_machine_filter, monthly_metric_col = render_oee_inline_filters(month_base, "oee_monthly_inline")
                month_label = f"{selected_month_oee[0]}-{str(selected_month_oee[1]).zfill(2)}"
                if monthly_metric_col == "IWON_OEE_%":
                    show_iwon_period_view(
                        month_base,
                        monthly_project,
                        monthly_process,
                        monthly_machine_filter,
                        month_label,
                        "iwon_monthly",
                        ["Godina", "Week"],
                        "Week",
                    )
                else:
                    show_oee_clean_view(
                        month_base,
                        monthly_metric_col,
                        monthly_machine_filter,
                        month_label,
                        ["Godina", "Week"],
                        "Week",
                        "oee_monthly_clean",
                        page_name="Monthly",
                        ctx=oee_period_context(
                            oee_base, month_base, "month", monthly_project, monthly_process, monthly_machine_filter,
                            pd.Timestamp(selected_month_oee[0], selected_month_oee[1], 1),
                            pd.Timestamp(selected_month_oee[0], selected_month_oee[1], 1) + pd.offsets.MonthEnd(0), month_label,
                        ),
                    )

            if oee_page == "Yearly":
                st.subheader("OEE — godišnje")
                st.caption("OEE se računa za jedan projekat i jedan proces. „Mašina = Sve“ daje OEE celog procesa i poređenje mašina.")

                year_options = sorted(oee_base["Calendar_Year"].dropna().astype(int).unique().tolist())
                col_year, col_rest = st.columns([1, 4])
                with col_year:
                    selected_year_oee = st.selectbox(
                        "Izaberi godinu",
                        options=year_options,
                        **_oee_index_kwargs("oee_yearly_selected_year", year_options),
                        key="oee_yearly_selected_year",
                    )
                year_base = oee_base[oee_base["Calendar_Year"] == selected_year_oee].copy()
                with col_rest:
                    year_base, yearly_project, yearly_process, yearly_machine_filter, yearly_metric_col = render_oee_inline_filters(year_base, "oee_yearly_inline")
                year_label = str(selected_year_oee)
                if yearly_metric_col == "IWON_OEE_%":
                    show_iwon_period_view(
                        year_base,
                        yearly_project,
                        yearly_process,
                        yearly_machine_filter,
                        year_label,
                        "iwon_yearly",
                        ["Calendar_Year", "Mesec"],
                        "Mesec",
                    )
                else:
                    show_oee_clean_view(
                        year_base,
                        yearly_metric_col,
                        yearly_machine_filter,
                        year_label,
                        ["Calendar_Year", "Mesec"],
                        "Mesec",
                        "oee_yearly_clean",
                        page_name="Yearly",
                        ctx=oee_period_context(
                            oee_base, year_base, "year", yearly_project, yearly_process, yearly_machine_filter,
                            pd.Timestamp(int(selected_year_oee), 1, 1), pd.Timestamp(int(selected_year_oee), 12, 31), year_label,
                        ),
                    )

            if oee_page == "Machine Ranking":
                st.subheader("Rang mašina")
                st.caption("Filteri: Datum → Project → Process → Machine. Ako je Machine = ALL, prikazuje ranking. Ako izabereš jednu mašinu, prikazuje detalj te mašine.")

                ranking_dates = sorted(oee_base["Datum"].dropna().dt.date.unique().tolist())
                selected_ranking_date = st.selectbox(
                    "Datum",
                    options=ranking_dates,
                    index=len(ranking_dates) - 1 if ranking_dates else 0,
                    format_func=lambda d: pd.to_datetime(d).strftime("%d.%m.%Y"),
                    key="oee_ranking_date_filter",
                )

                ranking_base = oee_base[oee_base["Datum"].dt.date == selected_ranking_date].copy()

                col_rank_project, col_rank_process, col_rank_machine, col_rank_by = st.columns(4)

                with col_rank_project:
                    rank_project_options = ["ALL"] + sorted(ranking_base["Project"].dropna().unique().tolist())
                    selected_rank_project = st.selectbox("Project", rank_project_options, key="oee_ranking_project_filter")

                if selected_rank_project != "ALL":
                    ranking_base = ranking_base[ranking_base["Project"] == selected_rank_project]

                with col_rank_process:
                    rank_process_options = ["ALL"] + sorted(ranking_base["Process"].dropna().unique().tolist())
                    selected_rank_process = st.selectbox("Process", rank_process_options, key="oee_ranking_process_filter")

                if selected_rank_process != "ALL":
                    ranking_base = ranking_base[ranking_base["Process"] == selected_rank_process]

                with col_rank_machine:
                    rank_machine_options = ["ALL"] + sorted(ranking_base["Machine"].dropna().unique().tolist())
                    selected_rank_machine = st.selectbox("Machine", rank_machine_options, key="oee_ranking_machine_filter")

                if selected_rank_machine != "ALL":
                    ranking_base = ranking_base[ranking_base["Machine"] == selected_rank_machine]

                rank_by_map = {
                    "Machine OEE CT": "Machine_OEE_CT_%",
                    "Plant OEE CT": "Plant_OEE_CT_%",
                    "Machine OEE Target": "Machine_OEE_Target_%",
                    "Plant OEE Target": "Plant_OEE_Target_%",
                    "Availability": "Machine_Availability_%",
                    "Performance": "Machine_Performance_CT_%",
                    "Q-rate": "Quality_%",
                }
                with col_rank_by:
                    selected_rank_by_label = st.selectbox("Rank by", list(rank_by_map.keys()), key="oee_ranking_rank_by_filter")
                selected_rank_by_col = rank_by_map[selected_rank_by_label]

                date_label = pd.to_datetime(selected_ranking_date).strftime("%d.%m.%Y")

                if ranking_base.empty:
                    st.warning("Nema OEE podataka za izabrane Machine Ranking filtere.")
                elif selected_rank_machine == "ALL":
                    ranking_oee = aggregate_oee(ranking_base, ["Project", "Process", "Machine"])
                    ranking_oee = ranking_oee.sort_values(selected_rank_by_col, ascending=False).reset_index(drop=True)
                    ranking_oee["Rank"] = range(1, len(ranking_oee) + 1)
                    ranking_oee["Project_Process_Machine"] = (
                        ranking_oee["Project"].astype(str) + " | " +
                        ranking_oee["Process"].astype(str) + " | " +
                        ranking_oee["Machine"].astype(str)
                    )

                    st.markdown(f"### Rang · {selected_rank_by_label} · {date_label}")
                    ranking_oee["Rank_Label"] = (
                        ranking_oee["Project"].astype(str) + " · " + ranking_oee["Process"].astype(str) + " · " + ranking_oee["Machine"].astype(str)
                    )
                    picked_rank = plot_oee_ranking(
                        ranking_oee, "Rank_Label", selected_rank_by_col,
                        f"Rang mašina po {selected_rank_by_label} · {date_label}",
                        "oee_machine_ranking_filtered_chart", selectable=True,
                    )
                    rank_drill_metric = {"Availability": "a", "Performance": "p", "Q-rate": "q"}.get(selected_rank_by_label, "oee")
                    rank_metric_col = selected_rank_by_col if rank_drill_metric == "oee" else "Machine_OEE_CT_%"
                    if picked_rank:
                        picked_row = ranking_oee[ranking_oee["Rank_Label"] == picked_rank].iloc[0]
                        picked_rows = ranking_base[
                            (ranking_base["Project"].astype(str) == str(picked_row["Project"]))
                            & (ranking_base["Process"].astype(str) == str(picked_row["Process"]))
                            & (ranking_base["Machine"].astype(str) == str(picked_row["Machine"]))
                        ]
                        render_oee_detail_card(picked_rows, rank_drill_metric, rank_metric_col, f"{picked_rank} · {date_label}")
                    else:
                        st.caption("Klikni mašinu u rangu — ispod se otvaraju njeni detalji.")

                    table_cols = [
                        "Rank", "Project", "Process", "Machine",
                        "Machine_OEE_CT_%", "Plant_OEE_CT_%",
                        "Machine_OEE_Target_%", "Plant_OEE_Target_%",
                        "Machine_Availability_%", "Machine_Performance_CT_%", "Quality_%",
                        "Open_Time", "Down_Time", "Organisational_Loss",
                        "OK_pcs", "NOK_pcs", "Total_Pcs", "Records",
                    ]
                    table_cols = [c for c in table_cols if c in ranking_oee.columns]
                    st.dataframe(format_oee_percent_columns(ranking_oee[table_cols]), use_container_width=True)

                else:
                    machine_detail = aggregate_oee(ranking_base, ["Project", "Process", "Machine"])
                    detail_row = machine_detail.iloc[0]
                    title = f"{detail_row['Project']} | {detail_row['Process']} | {detail_row['Machine']} | {date_label}"

                    st.markdown(f"### Machine Detail | {title}")
                    d1, d2, d3, d4 = st.columns(4)
                    d1.metric("Machine OEE CT %", round(float(detail_row["Machine_OEE_CT_%"]), 2))
                    d2.metric("Plant OEE CT %", round(float(detail_row["Plant_OEE_CT_%"]), 2))
                    d3.metric("Machine OEE Target %", round(float(detail_row["Machine_OEE_Target_%"]), 2))
                    d4.metric("Plant OEE Target %", round(float(detail_row["Plant_OEE_Target_%"]), 2))

                    show_gauge_row([
                        ("Machine OEE CT", detail_row["Machine_OEE_CT_%"]),
                        ("Plant OEE CT", detail_row["Plant_OEE_CT_%"]),
                        ("Machine OEE Target", detail_row["Machine_OEE_Target_%"]),
                        ("Plant OEE Target", detail_row["Plant_OEE_Target_%"]),
                    ], "oee_machine_detail_filtered_chart")

                    raw_machine_rows = ranking_base.copy()
                    raw_machine_rows["Datum"] = raw_machine_rows["Datum"].dt.strftime("%d.%m.%Y")
                    st.dataframe(format_oee_percent_columns(raw_machine_rows), use_container_width=True)

            if oee_page == "Raw Data":
                st.subheader("Svi OEE unosi")
                raw_show = oee_base.copy()
                raw_show["Datum"] = raw_show["Datum"].dt.strftime("%d.%m.%Y")
                st.dataframe(format_oee_percent_columns(raw_show), use_container_width=True)

if selected_module == "KPI Process":
    can_edit_kpi = can_edit_module("KPI Process")
    try:
        if can_edit_kpi and st.sidebar.button("Sync latest KPI activity", key="kpi_manual_activity_sync"):
            clear_all_activity_sync_state()
            manual_sync = sync_all_activities(force=True)
            if manual_sync.get("status") == "ok":
                st.sidebar.success(
                    "KPI sync završen: "
                    f"{manual_sync.get('total_added', 0)} novih zapisa "
                    f"({manual_sync.get('downtime_added', 0)} zastoja)."
                )
                ignored_names = manual_sync.get("downtime_ignored_names", [])
                if ignored_names:
                    with st.sidebar.expander(
                        f"Ignorisana imena van aplikacije ({len(ignored_names)})"
                    ):
                        st.write(ignored_names)
                if manual_sync.get("errors"):
                    with st.sidebar.expander("Sync upozorenja"):
                        st.write(manual_sync["errors"])
            else:
                st.sidebar.error("KPI sync nije uspeo.")
                st.sidebar.write(manual_sync.get("errors", []))
        activity_status = get_all_activities_status()
        if activity_status.get("initialized"):
            # Entries saved in Forms / Work Tickets / downtime appear in KPI
            # within ~2 minutes (immediately after a Work Ticket save).
            with st.spinner("Osvežavam nove unose..."):
                auto_sync = ensure_activities_synced()
            if auto_sync.get("status") not in (None, "ok", "fresh", "session_cached"):
                st.warning("Automatsko osvežavanje KPI unosa trenutno nije uspelo; prikazani su poslednji sačuvani podaci.")
                if is_admin_user(current_user):
                    with st.expander("Detalji sinhronizacije"):
                        st.write(auto_sync.get("errors", []))
        all_activities_df, df_kpi, kpi_missing = build_kpi_dataset()
        if all_activities_df.empty:
            st.warning("ALL_ACTIVITIES mora prvo da bude inicijalizovan od strane administratora.")
            if is_admin_user(current_user) and can_edit_kpi:
                if st.button("Initialize ALL_ACTIVITIES", key="initialize_all_activities_from_kpi", use_container_width=True):
                    clear_all_activity_sync_state()
                    migration = sync_all_activities(force=True)
                    st.session_state["_all_activities_migration_report"] = migration
                    st.rerun()
            st.stop()
        if df_kpi is not None and int(df_kpi.attrs.get("dropped_rows", 0) or 0) > 0 and is_admin_user(current_user):
            st.caption(f"Napomena: {int(df_kpi.attrs.get('dropped_rows', 0))} zapisa u ALL_ACTIVITIES nema čitljiv datum ili vreme i nisu uračunati.")
    except Exception as e:
        df_kpi = None
        kpi_missing = ["Google API / KPI load error"]
        kpi_load_error = e

    if df_kpi is None:
        st.error("Ne mogu da učitam KPI podatke. Ako je Google limit privremeno dostignut, sačekaj oko minut; aplikacija sada automatski usporava i ponavlja zahtev.")
        if "kpi_load_error" in locals():
            st.write(kpi_load_error)
        st.stop()
    if kpi_missing:
        st.error(f"Nedostaju KPI kolone: {kpi_missing}")
        st.stop()

    df_base = df_kpi.copy()
    st.sidebar.header("KPI filteri")
    min_date = df_base["Radni_dan"].min().date()
    max_date = df_base["Radni_dan"].max().date()
    use_date_range = st.sidebar.checkbox("Koristi raspon datuma", value=False, key="kpi_use_date_range")
    if use_date_range:
        date_range = st.sidebar.date_input("Raspon datuma", value=(min_date, max_date), min_value=min_date, max_value=max_date, format="DD.MM.YYYY", key="kpi_date_range")
        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date = pd.to_datetime(date_range[0])
            end_date = pd.to_datetime(date_range[1])
        else:
            start_date = pd.to_datetime(min_date)
            end_date = pd.to_datetime(max_date)
        df_base = df_base[(df_base["Radni_dan"] >= start_date) & (df_base["Radni_dan"] <= end_date)]

    izvori = ["Svi"] + sorted(df_base["Izvor"].dropna().astype(str).unique().tolist())
    selected_source = st.sidebar.selectbox("Izvor podataka", izvori, key="kpi_source")
    df_for_options = df_base.copy()
    if selected_source != "Svi":
        df_for_options = df_for_options[df_for_options["Izvor"] == selected_source]

    godine = ["Sve"] + sorted(df_for_options["Godina"].dropna().astype(int).unique().tolist())
    selected_year = st.sidebar.selectbox("Godina", godine, key="kpi_year")
    if selected_year != "Sve":
        df_for_options = df_for_options[df_for_options["Godina"] == selected_year]
    meseci = ["Svi"] + sorted(df_for_options["Mesec"].dropna().astype(int).unique().tolist())
    selected_month = st.sidebar.selectbox("Mesec", meseci, key="kpi_month")
    if selected_month != "Svi":
        df_for_options = df_for_options[df_for_options["Mesec"] == selected_month]
    tehnicari = ["Svi"] + sorted(df_for_options["Tehničar/Inženjer"].dropna().unique().tolist())
    selected_tech = st.sidebar.selectbox("Tehničar", tehnicari, key="kpi_tech")
    kategorije = ["Sve"] + sorted(df_for_options["Kategorija rada"].dropna().unique().tolist())
    selected_category = st.sidebar.selectbox("Kategorija rada", kategorije, key="kpi_category")

    df = df_base.copy()
    if selected_source != "Svi": df = df[df["Izvor"] == selected_source]
    if selected_year != "Sve": df = df[df["Godina"] == selected_year]
    if selected_month != "Svi": df = df[df["Mesec"] == selected_month]
    if selected_tech != "Svi": df = df[df["Tehničar/Inženjer"] == selected_tech]
    if selected_category != "Sve": df = df[df["Kategorija rada"] == selected_category]

    df_compare = df_base.copy()
    if selected_source != "Svi": df_compare = df_compare[df_compare["Izvor"] == selected_source]
    if selected_year != "Sve": df_compare = df_compare[df_compare["Godina"] == selected_year]
    if selected_month != "Svi": df_compare = df_compare[df_compare["Mesec"] == selected_month]
    if selected_category != "Sve": df_compare = df_compare[df_compare["Kategorija rada"] == selected_category]

    if df.empty:
        st.warning("Nema KPI podataka za izabrane filtere.")
        st.stop()

    effective_hours = df["Duration_Hours"].sum()
    active_days = df[["Tehničar/Inženjer", "Radni_dan"]].drop_duplicates()
    work_hours = len(active_days) * 8
    activities = len(df)
    utilization = effective_hours / work_hours * 100 if work_hours > 0 else 0
    activities_per_hour = activities / work_hours if work_hours > 0 else 0
    undocumented_time = max(work_hours - effective_hours, 0)
    expected_activities = max(len(active_days) * TARGET_ACTIVITIES_PER_DAY, 1)
    activity_factor = min(activities / expected_activities, 1) * 100
    efficiency = activities_per_hour

    period_min = df["Radni_dan"].min()
    period_max = df["Radni_dan"].max()
    scope_text = f"{period_min.strftime('%d.%m.%Y')} – {period_max.strftime('%d.%m.%Y')}"
    scope_parts = [selected_tech if selected_tech != "Svi" else "svi tehničari"]
    if selected_category != "Sve":
        scope_parts.append(selected_category)
    if selected_source != "Svi":
        scope_parts.append(selected_source)
    target_aph = TARGET_ACTIVITIES_PER_DAY / 8.0
    undocumented_share = (undocumented_time / work_hours * 100) if work_hours > 0 else 0
    kpi_tiles_html = ui.section("Ključni pokazatelji", f"{scope_text} · {', '.join(scope_parts)}") + ui.kpi_grid([
        ui.kpi_card("Efektivni sati", ui.format_number(effective_hours, 1), "h", "info",
                    f"{len(active_days)} radnih dana · {df['Tehničar/Inženjer'].nunique()} tehn."),
        ui.kpi_card("Radni sati", ui.format_number(work_hours, 0), "h", "neutral", "8 h po radnom danu"),
        ui.kpi_card("Iskorišćenost", ui.format_number(utilization, 1), "%", ui.status_for(utilization, 85),
                    "cilj 85 %", progress=utilization),
        ui.kpi_card("Aktivnosti", ui.format_number(activities, 0), "", "info",
                    f"očekivano ≥ {ui.format_number(expected_activities, 0)}"),
        ui.kpi_card("Aktivnosti / sat", ui.format_number(activities_per_hour, 2), "", ui.status_for(activities_per_hour, target_aph),
                    f"cilj {ui.format_number(target_aph, 2)}"),
        ui.kpi_card("Nedokumentovano", ui.format_number(undocumented_time, 1), "h",
                    "ok" if undocumented_share <= 15 else ("warn" if undocumented_share <= 30 else "alarm"),
                    f"{ui.format_number(undocumented_share, 0)} % radnog vremena", progress=undocumented_share),
    ])

    daily = df.groupby("Radni_dan").agg(Effective_Hours=("Duration_Hours", "sum"), Activities=("Duration_Hours", "count"), Technicians=("Tehničar/Inženjer", "nunique")).reset_index()
    daily["Work_Hours"] = daily["Technicians"] * 8
    daily["Utilization_%"] = daily["Effective_Hours"] / daily["Work_Hours"] * 100
    daily["Activities_Per_Hour"] = (daily["Activities"] / daily["Work_Hours"]).fillna(0)
    daily["Efficiency_%"] = daily["Activities_Per_Hour"]
    daily["Undocumented_Time"] = (daily["Work_Hours"] - daily["Effective_Hours"]).clip(lower=0)

    monthly = df.groupby(["Godina", "Mesec"]).agg(Effective_Hours=("Duration_Hours", "sum"), Activities=("Duration_Hours", "count")).reset_index()
    monthly_days = df[["Godina", "Mesec", "Tehničar/Inženjer", "Radni_dan"]].drop_duplicates()
    monthly_work = monthly_days.groupby(["Godina", "Mesec"]).size().reset_index(name="Active_Days")
    monthly = monthly.merge(monthly_work, on=["Godina", "Mesec"], how="left")
    monthly["Work_Hours"] = monthly["Active_Days"] * 8
    monthly["Utilization_%"] = monthly["Effective_Hours"] / monthly["Work_Hours"] * 100
    monthly["Activities_Per_Hour"] = (monthly["Activities"] / monthly["Work_Hours"]).fillna(0)
    monthly["Efficiency_%"] = monthly["Activities_Per_Hour"]
    monthly["Undocumented_Time"] = (monthly["Work_Hours"] - monthly["Effective_Hours"]).clip(lower=0)

    yearly = df.groupby("Godina").agg(Effective_Hours=("Duration_Hours", "sum"), Activities=("Duration_Hours", "count")).reset_index()
    yearly_days = df[["Godina", "Tehničar/Inženjer", "Radni_dan"]].drop_duplicates()
    yearly_work = yearly_days.groupby("Godina").size().reset_index(name="Active_Days")
    yearly = yearly.merge(yearly_work, on="Godina", how="left")
    yearly["Work_Hours"] = yearly["Active_Days"] * 8
    yearly["Utilization_%"] = yearly["Effective_Hours"] / yearly["Work_Hours"] * 100
    yearly["Activities_Per_Hour"] = (yearly["Activities"] / yearly["Work_Hours"]).fillna(0)
    yearly["Efficiency_%"] = yearly["Activities_Per_Hour"]
    yearly["Undocumented_Time"] = (yearly["Work_Hours"] - yearly["Effective_Hours"]).clip(lower=0)

    category = df.groupby("Kategorija rada").agg(Effective_Hours=("Duration_Hours", "sum"), Activities=("Duration_Hours", "count")).reset_index()

    tech_all = df_compare.groupby("Tehničar/Inženjer").agg(Effective_Hours=("Duration_Hours", "sum"), Activities=("Duration_Hours", "count")).reset_index()
    tech_days = df_compare[["Tehničar/Inženjer", "Radni_dan"]].drop_duplicates()
    tech_work = tech_days.groupby("Tehničar/Inženjer").size().reset_index(name="Active_Days")
    tech_all = tech_all.merge(tech_work, on="Tehničar/Inženjer", how="left")
    tech_all["Work_Hours"] = tech_all["Active_Days"] * 8
    tech_all["Utilization_%"] = tech_all["Effective_Hours"] / tech_all["Work_Hours"] * 100
    tech_all["Activities_Per_Hour"] = (tech_all["Activities"] / tech_all["Work_Hours"]).fillna(0)
    tech_all["Efficiency_%"] = tech_all["Activities_Per_Hour"]
    tech_all["Undocumented_Time"] = (tech_all["Work_Hours"] - tech_all["Effective_Hours"]).clip(lower=0)

    pareto = df.groupby("Opis aktivnosti").agg(Total_Hours=("Duration_Hours", "sum"), Count=("Duration_Hours", "count")).reset_index().sort_values("Total_Hours", ascending=False)
    pareto["Cumulative_%"] = pareto["Total_Hours"].cumsum() / pareto["Total_Hours"].sum() * 100 if pareto["Total_Hours"].sum() > 0 else 0

    active_technicians = load_active_technicians()
    default_alert_day = df_base["Radni_dan"].max().date()
    daily_tech_all_base = df_base.groupby(["Radni_dan", "Tehničar/Inženjer"]).agg(Total_Hours=("Duration_Hours", "sum"), Activities=("Duration_Hours", "count")).reset_index()

    # =====================================================
    # DETAIL VIEW DATASET FOR DAILY / MONTHLY / YEARLY TABS
    # =====================================================
    # This base keeps the same year / month / category filters, but lets each overview tab
    # choose "Svi" or one specific technician directly inside the tab.
    df_overview_base = df_base.copy()
    if selected_year != "Sve":
        df_overview_base = df_overview_base[df_overview_base["Godina"] == selected_year]
    if selected_month != "Svi":
        df_overview_base = df_overview_base[df_overview_base["Mesec"] == selected_month]
    if selected_category != "Sve":
        df_overview_base = df_overview_base[df_overview_base["Kategorija rada"] == selected_category]

    overview_tech_options = ["Svi"] + sorted(df_overview_base["Tehničar/Inženjer"].dropna().unique().tolist())
    overview_default_index = overview_tech_options.index(selected_tech) if selected_tech in overview_tech_options else 0

    def filter_overview_by_technician(source_df, technician):
        result = source_df.copy()
        if technician != "Svi":
            result = result[result["Tehničar/Inženjer"] == technician]
        return result

    def build_daily_summary(source_df):
        if source_df.empty:
            return pd.DataFrame(columns=["Radni_dan", "Effective_Hours", "Activities", "Technicians", "Work_Hours", "Utilization_%", "Activity_Factor_%", "Efficiency_%", "Undocumented_Time"])
        result = source_df.groupby("Radni_dan").agg(
            Effective_Hours=("Duration_Hours", "sum"),
            Activities=("Duration_Hours", "count"),
            Technicians=("Tehničar/Inženjer", "nunique"),
        ).reset_index()
        result["Work_Hours"] = result["Technicians"] * 8
        result["Utilization_%"] = result["Effective_Hours"] / result["Work_Hours"] * 100
        result["Activities_Per_Hour"] = (result["Activities"] / result["Work_Hours"]).fillna(0)
        result["Efficiency_%"] = result["Activities_Per_Hour"]
        result["Undocumented_Time"] = (result["Work_Hours"] - result["Effective_Hours"]).clip(lower=0)
        return result

    def build_monthly_summary(source_df):
        if source_df.empty:
            return pd.DataFrame(columns=["Godina", "Mesec", "Effective_Hours", "Activities", "Active_Days", "Work_Hours", "Utilization_%", "Activity_Factor_%", "Efficiency_%", "Undocumented_Time"])
        result = source_df.groupby(["Godina", "Mesec"]).agg(
            Effective_Hours=("Duration_Hours", "sum"),
            Activities=("Duration_Hours", "count"),
        ).reset_index()
        work_days = source_df[["Godina", "Mesec", "Tehničar/Inženjer", "Radni_dan"]].drop_duplicates()
        work = work_days.groupby(["Godina", "Mesec"]).size().reset_index(name="Active_Days")
        result = result.merge(work, on=["Godina", "Mesec"], how="left")
        result["Work_Hours"] = result["Active_Days"] * 8
        result["Utilization_%"] = result["Effective_Hours"] / result["Work_Hours"] * 100
        result["Activities_Per_Hour"] = (result["Activities"] / result["Work_Hours"]).fillna(0)
        result["Efficiency_%"] = result["Activities_Per_Hour"]
        result["Undocumented_Time"] = (result["Work_Hours"] - result["Effective_Hours"]).clip(lower=0)
        return result

    def build_yearly_summary(source_df):
        if source_df.empty:
            return pd.DataFrame(columns=["Godina", "Effective_Hours", "Activities", "Active_Days", "Work_Hours", "Utilization_%", "Activity_Factor_%", "Efficiency_%", "Undocumented_Time"])
        result = source_df.groupby("Godina").agg(
            Effective_Hours=("Duration_Hours", "sum"),
            Activities=("Duration_Hours", "count"),
        ).reset_index()
        work_days = source_df[["Godina", "Tehničar/Inženjer", "Radni_dan"]].drop_duplicates()
        work = work_days.groupby("Godina").size().reset_index(name="Active_Days")
        result = result.merge(work, on="Godina", how="left")
        result["Work_Hours"] = result["Active_Days"] * 8
        result["Utilization_%"] = result["Effective_Hours"] / result["Work_Hours"] * 100
        result["Activities_Per_Hour"] = (result["Activities"] / result["Work_Hours"]).fillna(0)
        result["Efficiency_%"] = result["Activities_Per_Hour"]
        result["Undocumented_Time"] = (result["Work_Hours"] - result["Effective_Hours"]).clip(lower=0)
        return result

    # KPI navigation fix: Streamlit st.tabs renders all tab bodies in the DOM, which became slow and visually stacked with the custom CSS.
    # Use a single persistent radio navigation and render only the selected KPI panel.
    kpi_tab_names = ["Dashboard", "Dnevni pregled", "Mesečni pregled", "Godišnji pregled", "Poređenje tehničara", "Kategorije", "Pareto", "Ranking", "Data Quality", "Technician Evaluation", "Alerts", "Export"]
    if can_edit_kpi:
        kpi_tab_names.insert(9, "Admin Panel")
    if "kpi_selected_tab" not in st.session_state or st.session_state["kpi_selected_tab"] not in kpi_tab_names:
        st.session_state["kpi_selected_tab"] = "Dashboard"

    # Two-level navigation: a few clear sections, then the page inside the
    # section (12 flat buttons were hard to scan, especially on phones).
    KPI_PAGE_LABELS = {
        "Dashboard": "Pregled", "Dnevni pregled": "Dnevno", "Mesečni pregled": "Mesečno", "Godišnji pregled": "Godišnje",
        "Poređenje tehničara": "Poređenje tehničara", "Kategorije": "Kategorije", "Pareto": "Pareto", "Ranking": "Rang lista",
        "Technician Evaluation": "Ocena tehničara", "Alerts": "Alarmi", "Admin Panel": "Tehničari i ciljevi",
        "Data Quality": "Kvalitet podataka", "Export": "Izvoz",
    }
    KPI_SECTIONS = [
        ("📈 Pregled", ["Dashboard", "Dnevni pregled", "Mesečni pregled", "Godišnji pregled"]),
        ("🔍 Analiza", ["Poređenje tehničara", "Kategorije", "Pareto", "Ranking"]),
        ("🧑‍🔧 Tehničari", ["Technician Evaluation", "Alerts", "Admin Panel"]),
        ("🗂 Podaci", ["Data Quality", "Export"]),
    ]
    KPI_SECTIONS = [(label, [p for p in pages if p in kpi_tab_names]) for label, pages in KPI_SECTIONS]
    KPI_SECTIONS = [(label, pages) for label, pages in KPI_SECTIONS if pages]
    section_labels = [label for label, _ in KPI_SECTIONS]
    current_page = st.session_state["kpi_selected_tab"]
    current_section = next((label for label, pages in KPI_SECTIONS if current_page in pages), section_labels[0])
    if st.session_state.get("kpi_section_radio") not in section_labels:
        st.session_state["kpi_section_radio"] = current_section
    chosen_section = st.radio(
        "KPI sekcija", section_labels,
        horizontal=True, label_visibility="collapsed", key="kpi_section_radio",
    )
    section_pages = dict(KPI_SECTIONS)[chosen_section]
    page_key = "kpi_page_radio_" + re.sub(r"[^a-z0-9]+", "_", chosen_section.lower())
    default_page = current_page if current_page in section_pages else section_pages[0]
    if st.session_state.get(page_key) not in section_pages:
        st.session_state[page_key] = default_page
    if len(section_pages) > 1:
        selected_kpi_tab = st.radio(
            "KPI stranica", section_pages,
            format_func=lambda page: KPI_PAGE_LABELS.get(page, page),
            horizontal=True, label_visibility="collapsed", key=page_key,
        )
    else:
        selected_kpi_tab = section_pages[0]
    st.session_state["kpi_selected_tab"] = selected_kpi_tab
    if chosen_section in ("📈 Pregled", "🔍 Analiza"):
        st.markdown(kpi_tiles_html, unsafe_allow_html=True)

    if selected_kpi_tab == 'Dashboard':
        st.markdown(ui.section("Iskorišćenost po danima", "efektivno vs. raspoloživo vreme"), unsafe_allow_html=True)
        fig_dashboard_util = create_line_chart(daily, "Radni_dan", "Utilization_%", "Iskorišćenost po danu", "%", 1, target=85)
        st.plotly_chart(fig_dashboard_util, use_container_width=True, key="kpi_dashboard_utilization")
        fig_dashboard_hours = create_grouped_bar(daily, "Radni_dan", ["Effective_Hours", "Work_Hours", "Undocumented_Time"], "Sati po danu", "h", 1)
        st.plotly_chart(fig_dashboard_hours, use_container_width=True, key="kpi_dashboard_hours")
        st.markdown(ui.section("Struktura rada"), unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            fig_dashboard_category = create_pie_chart(category)
            st.plotly_chart(fig_dashboard_category, use_container_width=True, key="kpi_dashboard_category")
        with col2:
            fig_dashboard_activities = create_grouped_bar(daily, "Radni_dan", ["Activities"], "Broj aktivnosti po danu", "aktivnosti", 0, target=TARGET_ACTIVITIES_PER_DAY * max(int(daily["Technicians"].median()) if not daily.empty else 1, 1))
            st.plotly_chart(fig_dashboard_activities, use_container_width=True, key="kpi_dashboard_activities")

    if selected_kpi_tab == 'Dnevni pregled':
        st.subheader("Dnevni pregled")
        daily_tech_view = st.selectbox(
            "Prikaži dnevni pregled za tehničara",
            options=overview_tech_options,
            index=overview_default_index,
            key="daily_technician_view",
        )
        daily_view_df = filter_overview_by_technician(df_overview_base, daily_tech_view)
        daily_view = build_daily_summary(daily_view_df)
        if daily_view.empty:
            st.warning("Nema dnevnih podataka za izabranog tehničara i filtere.")
        else:
            st.caption(f"Prikaz: {'svi tehničari' if daily_tech_view == 'Svi' else daily_tech_view}")
            fig_daily_efficiency = create_line_chart(daily_view, "Radni_dan", "Efficiency_%", "Aktivnosti po satu – po danu", "aktivnosti/h", 2, target=TARGET_ACTIVITIES_PER_DAY / 8.0)
            st.plotly_chart(fig_daily_efficiency, use_container_width=True, key="kpi_daily_efficiency")
            fig_daily_utilization = create_line_chart(daily_view, "Radni_dan", "Utilization_%", "Iskorišćenost po danu", "%", 1, target=85)
            st.plotly_chart(fig_daily_utilization, use_container_width=True, key="kpi_daily_utilization")
            fig_daily_activities = create_grouped_bar(daily_view, "Radni_dan", ["Activities"], "Broj aktivnosti po danu", "aktivnosti", 0)
            st.plotly_chart(fig_daily_activities, use_container_width=True, key="kpi_daily_activities")
            fig_daily_hours = create_grouped_bar(daily_view, "Radni_dan", ["Effective_Hours", "Work_Hours", "Undocumented_Time"], "Sati po danu", "h", 1)
            st.plotly_chart(fig_daily_hours, use_container_width=True, key="kpi_daily_hours")
            st.dataframe(daily_view, use_container_width=True)

    if selected_kpi_tab == 'Mesečni pregled':
        st.subheader("Mesečni pregled")
        monthly_tech_view = st.selectbox(
            "Prikaži mesečni pregled za tehničara",
            options=overview_tech_options,
            index=overview_default_index,
            key="monthly_technician_view",
        )
        monthly_view_df = filter_overview_by_technician(df_overview_base, monthly_tech_view)
        monthly_view = build_monthly_summary(monthly_view_df)
        if monthly_view.empty:
            st.warning("Nema mesečnih podataka za izabranog tehničara i filtere.")
        else:
            st.caption(f"Prikaz: {'svi tehničari' if monthly_tech_view == 'Svi' else monthly_tech_view}")
            fig_monthly_efficiency = create_line_chart(monthly_view, "Mesec", "Efficiency_%", "Aktivnosti po satu – po mesecu", "aktivnosti/h", 2, target=TARGET_ACTIVITIES_PER_DAY / 8.0)
            st.plotly_chart(fig_monthly_efficiency, use_container_width=True, key="kpi_monthly_efficiency")
            fig_monthly_activities = create_grouped_bar(monthly_view, "Mesec", ["Activities"], "Broj aktivnosti po mesecu", "aktivnosti", 0)
            st.plotly_chart(fig_monthly_activities, use_container_width=True, key="kpi_monthly_activities")
            fig_monthly_hours = create_grouped_bar(monthly_view, "Mesec", ["Effective_Hours", "Work_Hours", "Undocumented_Time"], "Sati po mesecu", "h", 1)
            st.plotly_chart(fig_monthly_hours, use_container_width=True, key="kpi_monthly_hours")
            fig_monthly_utilization = create_line_chart(monthly_view, "Mesec", "Utilization_%", "Iskorišćenost po mesecu", "%", 1, target=85)
            st.plotly_chart(fig_monthly_utilization, use_container_width=True, key="kpi_monthly_utilization")
            st.dataframe(monthly_view, use_container_width=True)

    if selected_kpi_tab == 'Godišnji pregled':
        st.subheader("Godišnji pregled")
        yearly_tech_view = st.selectbox(
            "Prikaži godišnji pregled za tehničara",
            options=overview_tech_options,
            index=overview_default_index,
            key="yearly_technician_view",
        )
        yearly_view_df = filter_overview_by_technician(df_overview_base, yearly_tech_view)
        yearly_view = build_yearly_summary(yearly_view_df)
        if yearly_view.empty:
            st.warning("Nema godišnjih podataka za izabranog tehničara i filtere.")
        else:
            st.caption(f"Prikaz: {'svi tehničari' if yearly_tech_view == 'Svi' else yearly_tech_view}")
            fig_yearly_efficiency = create_line_chart(yearly_view, "Godina", "Efficiency_%", "Aktivnosti po satu – po godini", "aktivnosti/h", 2, target=TARGET_ACTIVITIES_PER_DAY / 8.0)
            st.plotly_chart(fig_yearly_efficiency, use_container_width=True, key="kpi_yearly_efficiency")
            fig_yearly_activities = create_grouped_bar(yearly_view, "Godina", ["Activities"], "Broj aktivnosti po godini", "aktivnosti", 0)
            st.plotly_chart(fig_yearly_activities, use_container_width=True, key="kpi_yearly_activities")
            fig_yearly_hours = create_grouped_bar(yearly_view, "Godina", ["Effective_Hours", "Work_Hours", "Undocumented_Time"], "Sati po godini", "h", 1)
            st.plotly_chart(fig_yearly_hours, use_container_width=True, key="kpi_yearly_hours")
            fig_yearly_utilization = create_line_chart(yearly_view, "Godina", "Utilization_%", "Iskorišćenost po godini", "%", 1, target=85)
            st.plotly_chart(fig_yearly_utilization, use_container_width=True, key="kpi_yearly_utilization")
            st.dataframe(yearly_view, use_container_width=True)

    if selected_kpi_tab == 'Poređenje tehničara':
        st.subheader("Poređenje tehničara")
        available_compare_techs = sorted(tech_all["Tehničar/Inženjer"].dropna().unique().tolist())
        selected_compare_techs = st.multiselect("Tehničari za poređenje", options=available_compare_techs, default=[], key="kpi_selected_compare_techs")
        if selected_compare_techs:
            tech = tech_all[tech_all["Tehničar/Inženjer"].isin(selected_compare_techs)].copy()
            fig_tech_efficiency = create_grouped_bar(tech, "Tehničar/Inženjer", ["Efficiency_%"], "Aktivnosti po satu – po tehničaru", "aktivnosti/h", 2, target=TARGET_ACTIVITIES_PER_DAY / 8.0)
            st.plotly_chart(fig_tech_efficiency, use_container_width=True, key="kpi_tech_efficiency")
            fig_tech_utilization = create_grouped_bar(tech, "Tehničar/Inženjer", ["Utilization_%"], "Iskorišćenost po tehničaru", "%", 1, target=85)
            st.plotly_chart(fig_tech_utilization, use_container_width=True, key="kpi_tech_utilization")
            fig_tech_hours = create_grouped_bar(tech, "Tehničar/Inženjer", ["Effective_Hours", "Work_Hours", "Undocumented_Time"], "Sati po tehničaru", "h", 1)
            st.plotly_chart(fig_tech_hours, use_container_width=True, key="kpi_tech_hours")
            fig_tech_activities = create_grouped_bar(tech, "Tehničar/Inženjer", ["Activities"], "Broj aktivnosti po tehničaru", "aktivnosti", 0)
            st.plotly_chart(fig_tech_activities, use_container_width=True, key="kpi_tech_activities")
            st.dataframe(tech, use_container_width=True)
        else:
            st.warning("Nije izabran nijedan tehničar za poređenje.")

    if selected_kpi_tab == 'Kategorije':
        st.subheader("Kategorije")
        fig_category_pie = create_pie_chart(category)
        st.plotly_chart(fig_category_pie, use_container_width=True, key="kpi_category_pie")
        fig_category_bar = create_grouped_bar(category, "Kategorija rada", ["Effective_Hours"], "Efektivni sati po kategoriji", "h", 1)
        st.plotly_chart(fig_category_bar, use_container_width=True, key="kpi_category_bar")
        st.dataframe(category, use_container_width=True)

    if selected_kpi_tab == 'Pareto':
        st.subheader("Pareto aktivnosti")
        pareto_top = pareto.head(15).copy()
        fig_pareto = create_pareto_chart(pareto_top, "Opis aktivnosti", "Total_Hours", "Cumulative_%", "Pareto: aktivnosti po utrošenom vremenu")
        st.plotly_chart(fig_pareto, use_container_width=True, key="kpi_pareto_hours")
        st.dataframe(pareto, use_container_width=True)

    if selected_kpi_tab == 'Ranking':
        st.subheader("Ranking")
        ranking = tech_all.copy().sort_values("Activities_Per_Hour", ascending=False).reset_index(drop=True)
        ranking["Rank"] = range(1, len(ranking) + 1)
        ranking = ranking.drop(columns=["Efficiency_%"], errors="ignore")
        st.dataframe(ranking, use_container_width=True, hide_index=True)

    if selected_kpi_tab == 'Data Quality':
        st.subheader("Data Quality")
        bad_duration = df[df["Duration_Hours"] > 12]
        zero_duration = df[df["Duration_Hours"] == 0]
        q1, q2, q3 = st.columns(3)
        q1.metric("Broj zapisa", len(df))
        q2.metric("Trajanje > 12h", len(bad_duration))
        q3.metric("Trajanje = 0", len(zero_duration))
        if len(bad_duration) > 0:
            st.warning("Postoje zapisi sa trajanjem većim od 12h.")
            st.dataframe(bad_duration[["Timestamp", "Tehničar/Inženjer", "Kategorija rada", "Opis aktivnosti", "Datum", "Vreme početka", "Vreme završetka aktivnosti", "Duration_Hours"]], use_container_width=True)
        if len(zero_duration) > 0:
            st.warning("Postoje zapisi sa trajanjem 0h.")
            st.dataframe(zero_duration[["Timestamp", "Tehničar/Inženjer", "Kategorija rada", "Opis aktivnosti", "Datum", "Vreme početka", "Vreme završetka aktivnosti", "Duration_Hours"]], use_container_width=True)

    if selected_kpi_tab == 'Admin Panel':
        st.subheader("Admin Panel")
        st.caption("Manage technicians, targets, status, email and photos. The new master source is the Technicians sheet.")

        targets_admin_df, targets_admin_errors = load_technician_targets()
        technicians_admin_df, technicians_admin_errors = load_technicians_master()
        master_admin_techs = sorted(technicians_admin_df["Technician_Name"].dropna().astype(str).str.strip().unique().tolist()) if not technicians_admin_df.empty else []
        target_admin_techs = sorted(targets_admin_df["Technician"].dropna().astype(str).str.strip().unique().tolist()) if not targets_admin_df.empty else []
        all_admin_techs = sorted(list(dict.fromkeys(master_admin_techs + target_admin_techs)))

        st.info("Photo storage: Google Sheet / Technicians / Picture. TECHNICIAN_TARGETS is still updated for Technician Evaluation compatibility.")

        mode = st.radio("Mode", ["Edit existing technician", "Add new technician"], horizontal=True, key="admin_technician_mode")
        selected_admin_technician = ""
        current_row = pd.Series(dtype=object)

        if mode == "Edit existing technician":
            if not all_admin_techs:
                st.warning("No technician found in Technicians or TECHNICIAN_TARGETS.")
            selected_admin_technician = st.selectbox("Select technician", all_admin_techs, key="admin_select_existing_technician") if all_admin_techs else ""
            if selected_admin_technician:
                combined_row = {}
                if not targets_admin_df.empty:
                    target_match = targets_admin_df[targets_admin_df["Technician"].astype(str).str.strip() == str(selected_admin_technician).strip()]
                    if not target_match.empty:
                        combined_row.update(target_match.iloc[0].to_dict())
                if not technicians_admin_df.empty:
                    master_match = technicians_admin_df[technicians_admin_df["Technician_Name"].astype(str).str.strip() == str(selected_admin_technician).strip()]
                    if not master_match.empty:
                        mrow = master_match.iloc[0].to_dict()
                        combined_row.update({
                            "Technician_ID": mrow.get("Technician_ID", ""),
                            "Username": mrow.get("Username", ""),
                            "Department": mrow.get("Department", combined_row.get("Department", "")),
                            "Position": mrow.get("Position", combined_row.get("Position", "")),
                            "Email": mrow.get("Email", ""),
                            "Active": mrow.get("Active", combined_row.get("Active", "YES")),
                            "Picture": mrow.get("Picture", ""),
                            "Receive_Task_Email": mrow.get("Receive_Task_Email", "YES"),
                            "Receive_Task_Reminder": mrow.get("Receive_Task_Reminder", "YES"),
                            "Receive_Missing_Time_Email": mrow.get("Receive_Missing_Time_Email", "YES"),
                            "Receive_BN_Email": mrow.get("Receive_BN_Email", "YES"),
                        })
                current_row = pd.Series(combined_row, dtype=object)
            technician_name_default = selected_admin_technician
        else:
            technician_name_default = ""

        # Important: Streamlit keeps widget state by key. If the same keys are reused,
        # the form can show values from the previously selected technician.
        # This suffix forces a clean widget state whenever technician/mode changes.
        admin_form_key = re.sub(r"[^A-Za-z0-9_]+", "_", f"{mode}_{technician_name_default}").strip("_") or "new"

        st.markdown("### Technician Data")
        a_col, b_col, c_col = st.columns(3)
        with a_col:
            technician_name = st.text_input("Technician", value=technician_name_default, key=f"admin_technician_name_{admin_form_key}", disabled=(mode == "Edit existing technician"))
            username = st.text_input("Username", value=str(current_row.get("Username", "") or ""), key=f"admin_username_{admin_form_key}")
            active_value = st.selectbox(
                "Active",
                ["Yes", "No"],
                index=0 if str(current_row.get("Active", "Yes")).strip().upper() not in ["NO", "N", "NE", "FALSE", "0"] else 1,
                key=f"admin_active_{admin_form_key}",
            )
            period_default = str(current_row.get("Period Type", current_row.get("Period_Type", "Monthly")) or "Monthly").title()
            if period_default not in ["Daily", "Monthly", "Yearly"]:
                period_default = "Monthly"
            period_type = st.selectbox("Period Type", ["Daily", "Monthly", "Yearly"], index=["Daily", "Monthly", "Yearly"].index(period_default), key=f"admin_period_type_{admin_form_key}")
        with b_col:
            target_aph = st.number_input("Target Activities/Hour", min_value=0.0, value=normalize_float_value(current_row.get("Target Activities/Hour", 4), 4.0), step=0.1, key=f"admin_target_aph_{admin_form_key}")
            target_activities = st.number_input("Target Activities", min_value=0.0, value=normalize_float_value(current_row.get("Target Activities", 250), 250.0), step=1.0, key=f"admin_target_activities_{admin_form_key}")
            target_utilization = st.number_input("Target Utilization (%)", min_value=0.0, max_value=100.0, value=normalize_percent_value(current_row.get("Target Utilization", 85), 85.0), step=1.0, key=f"admin_target_utilization_{admin_form_key}")
            receive_task_email = st.selectbox(
                "Receive Task Email",
                ["Yes", "No"],
                index=0 if str(current_row.get("Receive_Task_Email", "Yes")).strip().upper() not in ["NO", "N", "NE", "FALSE", "0"] else 1,
                key=f"admin_receive_task_email_{admin_form_key}",
            )
            receive_task_reminder = st.selectbox(
                "Receive Task Reminder",
                ["Yes", "No"],
                index=0 if str(current_row.get("Receive_Task_Reminder", "Yes")).strip().upper() not in ["NO", "N", "NE", "FALSE", "0"] else 1,
                key=f"admin_receive_task_reminder_{admin_form_key}",
            )
            receive_missing_time_email = st.selectbox(
                "Receive Missing Time Email",
                ["Yes", "No"],
                index=0 if str(current_row.get("Receive_Missing_Time_Email", "Yes")).strip().upper() not in ["NO", "N", "NE", "FALSE", "0"] else 1,
                key=f"admin_receive_missing_time_email_{admin_form_key}",
            )
            receive_bn_email = st.selectbox(
                "Receive BN Email",
                ["Yes", "No"],
                index=0 if str(current_row.get("Receive_BN_Email", "Yes")).strip().upper() not in ["NO", "N", "NE", "FALSE", "0"] else 1,
                key=f"admin_receive_bn_email_{admin_form_key}",
            )
            supervisor = st.selectbox(
                "Supervisor / Alert only",
                ["No", "Yes"],
                index=1 if _yes_value(current_row.get("Supervisor", "No")) else 0,
                key=f"admin_supervisor_{admin_form_key}",
                help="YES: receives selected alerts, but is excluded from missing-time checks and evaluation penalties.",
            )
        with c_col:
            department = st.text_input("Department", value=str(current_row.get("Department", "") or ""), key=f"admin_department_{admin_form_key}")
            position = st.text_input("Position", value=str(current_row.get("Position", "") or ""), key=f"admin_position_{admin_form_key}")
            email = st.text_input("Email", value=str(current_row.get("Email", "") or ""), key=f"admin_email_{admin_form_key}")

        st.markdown("### Technician Picture")
        photo_base64_existing = str(current_row.get("Picture", current_row.get("Photo_Base64", "")) or "").strip()
        if photo_base64_existing:
            show_base64_image(photo_base64_existing, width=160, caption="Current photo")
        st.caption("Picture")
        photo_upload = st.file_uploader(
            "technician_picture_file",
            type=["png", "jpg", "jpeg", "webp"],
            key=f"admin_photo_upload_{admin_form_key}",
            label_visibility="collapsed",
            help="Select a PNG, JPG or WEBP picture",
        )

        if st.button("Save Technician", type="primary", key="admin_save_technician"):
            try:
                if not technician_name.strip():
                    st.error("Technician name is required.")
                else:
                    photo_file_id = ""
                    photo_file_name = ""
                    photo_base64 = ""
                    if photo_upload is not None:
                        photo_base64, photo_file_name = photo_to_base64(photo_upload)
                        photo_file_id = "SHEET_BASE64"

                    save_technician_admin_record(
                        technician=technician_name,
                        active=active_value,
                        period_type=period_type,
                        target_aph=target_aph,
                        target_activities=target_activities,
                        target_utilization=target_utilization,
                        department=department,
                        position=position,
                        username=username,
                        email=email,
                        receive_task_email=receive_task_email,
                        receive_task_reminder=receive_task_reminder,
                        receive_missing_time_email=receive_missing_time_email,
                        receive_bn_email=receive_bn_email,
                        supervisor=supervisor,
                        photo_file_id=photo_file_id,
                        photo_file_name=photo_file_name,
                        photo_base64=photo_base64,
                    )
                    load_technicians_master.clear()
                    load_active_technicians.clear()
                    load_technician_targets.clear()
                    st.success("Technician saved successfully.")
                    if photo_base64:
                        st.info(f"Photo saved in Technicians and TECHNICIAN_TARGETS: {photo_file_name}")
            except Exception as e:
                st.error("Technician could not be saved.")
                st.write(e)

        st.markdown("### Current TECHNICIAN_TARGETS")
        targets_admin_df, targets_admin_errors = load_technician_targets()
        if not targets_admin_df.empty:
            display_targets = targets_admin_df.copy()
            if "Photo_Base64" in display_targets.columns:
                display_targets["Photo_Base64"] = display_targets["Photo_Base64"].apply(lambda x: "Yes" if str(x).strip() else "")
            st.dataframe(display_targets, use_container_width=True)
        elif targets_admin_errors:
            st.warning("; ".join(targets_admin_errors))

    if selected_kpi_tab == 'Technician Evaluation':
        st.subheader("Technician Evaluation")
        st.caption("Individual monthly technician evaluation. One technician must be selected; there is no 'All' option.")

        targets_df, targets_missing = load_technician_targets()
        if targets_missing:
            st.error("Unable to load evaluation targets.")
            st.write(targets_missing)
            st.info("Check that the TECHNICIAN_TARGETS tab exists with these columns: Technician, Active, Period Type, Target Activities/Hour, Target Activities, Target Utilization.")
        else:
            target_techs = sorted(targets_df["Technician"].dropna().unique().tolist())
            eval_tech = st.selectbox(
                "Select technician",
                options=[""] + target_techs,
                format_func=lambda x: "Please select technician" if x == "" else x,
                key="kpi_eval_technician",
            )

            if not eval_tech:
                st.warning("Please select technician.")
            else:
                tech_targets = targets_df[targets_df["Technician"] == eval_tech].copy()
                monthly_targets = tech_targets[tech_targets["Period Type"].str.upper() == "MONTHLY"]
                target_row = monthly_targets.iloc[0] if not monthly_targets.empty else tech_targets.iloc[0]

                required_target_values = ["Target Activities/Hour", "Target Activities", "Target Utilization"]
                if target_row[required_target_values].isna().any():
                    st.error("The selected technician has incomplete targets. Fill Target Activities/Hour, Target Activities, and Target Utilization.")
                else:
                    load_missing_work_time_log.clear()
                    penalty_df = load_missing_entry_penalty_log(eval_tech)
                    eval_monthly_all = build_monthly_evaluation_data(df_compare, eval_tech, target_row, penalty_df)
                    if eval_monthly_all.empty:
                        st.warning("No data is available for the selected technician with the current filters.")
                    else:
                        st.markdown("### Evaluation Filters")
                        filter_col1, filter_col2, filter_col3 = st.columns(3)
                        available_years = sorted(eval_monthly_all["Godina"].dropna().astype(int).unique().tolist())
                        with filter_col1:
                            selected_eval_year = st.selectbox(
                                "Year",
                                options=["All"] + available_years,
                                key="kpi_eval_year_filter",
                            )
                        min_month_date = eval_monthly_all["Month Date"].min().date()
                        max_month_date = eval_monthly_all["Month Date"].max().date()
                        with filter_col2:
                            eval_date_from = st.date_input("From", value=min_month_date, key="kpi_eval_date_from")
                        with filter_col3:
                            eval_date_to = st.date_input("To", value=max_month_date, key="kpi_eval_date_to")

                        eval_monthly = eval_monthly_all.copy()
                        if selected_eval_year != "All":
                            eval_monthly = eval_monthly[eval_monthly["Godina"].astype(int) == int(selected_eval_year)]
                        eval_monthly = eval_monthly[
                            (eval_monthly["Month Date"].dt.date >= eval_date_from)
                            & (eval_monthly["Month Date"].dt.date <= eval_date_to)
                        ].copy()

                        if eval_monthly.empty:
                            st.warning("No evaluation data is available for the selected filter range.")
                        else:
                            latest = eval_monthly.iloc[-1]
                            overall_grade, overall_text = grade_from_score(latest["Overall Score"])

                            profile_photo_base64 = str(target_row.get("Photo_Base64", "") or "").strip()
                            profile_department = str(target_row.get("Department", "") or "").strip()
                            profile_position = str(target_row.get("Position", "") or "").strip()
                            if profile_photo_base64 or profile_department or profile_position:
                                p_col1, p_col2 = st.columns([1, 4])
                                with p_col1:
                                    if profile_photo_base64:
                                        show_base64_image(profile_photo_base64, width=150)
                                with p_col2:
                                    st.markdown(f"### {eval_tech}")
                                    if profile_position:
                                        st.markdown(f"**Position:** {profile_position}")
                                    if profile_department:
                                        st.markdown(f"**Department:** {profile_department}")

                            top1, top2, top3, top4 = st.columns(4)
                            top1.metric("Overall Score", f"{latest['Overall Score']:.1f}/100")
                            top2.metric("Grade", f"{overall_grade} - {overall_text}")
                            top3.metric("Latest Month", latest["Month"])
                            top4.metric("Penalty", f"{(-float(latest['Penalty Points'])) if float(latest['Penalty Points']) else 0.0:.1f}")

                            st.markdown("### Missing Entry Penalty")
                            p1, p2, p3, p4 = st.columns(4)
                            p1.metric("Missing Entries", int(latest["Missing Entries"]))
                            p2.metric("Justified", int(latest["Justified Missing Entries"]))
                            p3.metric("Unjustified", int(latest["Unjustified Missing Entries"]))
                            p4.metric("Penalty Points", f"{(-float(latest['Penalty Points'])) if float(latest['Penalty Points']) else 0.0:.1f}")
                            st.caption("Penalty rule: the first 5 unjustified missing entries per month reduce the score by 0.5 points each; every additional unjustified missing entry reduces it by 1.0 point. Missing entries with a Google Sheets note are treated as justified and ignored.")
                            if str(current_user.get("role", "")).strip().lower() == "admin":
                                with st.expander("Missing penalty diagnostics"):
                                    st.write(st.session_state.get("_missing_penalty_debug", {}))
                                    if st.session_state.get("_missing_penalty_error"):
                                        st.error(st.session_state["_missing_penalty_error"])

                            st.markdown("### Category Evaluation")
                            c_eval_1, c_eval_2, c_eval_3 = st.columns(3)
                            with c_eval_1:
                                show_evaluation_card("Utilization", latest["Utilization Score"])
                            with c_eval_2:
                                show_evaluation_card("Activities/Hour", latest["Activities/Hour Score"])
                            with c_eval_3:
                                show_evaluation_card("Activities Count", latest["Activities Count Score"])

                            st.markdown("### Monthly Overall Trend")
                            overall_chart = eval_monthly.copy()
                            overall_chart["Month Label"] = overall_chart["Month"]
                            fig_overall = create_line_chart(overall_chart, "Month Label", "Overall Score", "Ukupna ocena po mesecu", "poeni", 1, target=80)
                            fig_overall.update_xaxes(type="category", title_text="Month")
                            st.plotly_chart(fig_overall, use_container_width=True, key="kpi_eval_overall_trend")

                            st.markdown("### Category Trend")
                            category_trend = eval_monthly[["Month", "Utilization Score", "Activities/Hour Score", "Activities Count Score"]].copy()
                            category_trend_long = category_trend.melt(id_vars="Month", var_name="Category", value_name="Score")
                            fig_category_trend = px.bar(
                                category_trend_long,
                                x="Month",
                                y="Score",
                                color="Category",
                                barmode="group",
                                text=category_trend_long["Score"].map(lambda x: f"{x:.1f}"),
                                title="Monthly Category Scores",
                            )
                            fig_category_trend.update_traces(textposition="outside", cliponaxis=False)
                            fig_category_trend.update_layout(yaxis_title="Score", xaxis_title="Month", bargap=0.25)
                            fig_category_trend.update_xaxes(type="category", tickangle=0)
                            st.plotly_chart(style_chart(fig_category_trend), use_container_width=True, key="kpi_eval_category_trend")

                            st.markdown("### Strengths / Needs Improvement")
                            category_scores = {
                                "Utilization": latest["Utilization Score"],
                                "Activities/Hour": latest["Activities/Hour Score"],
                                "Activities Count": latest["Activities Count Score"],
                            }
                            strengths = [name for name, score in category_scores.items() if score >= 90]
                            weaknesses = [name for name, score in category_scores.items() if score < 70]
                            s_col, w_col = st.columns(2)
                            with s_col:
                                st.markdown("#### Strengths")
                                if strengths:
                                    for item in strengths:
                                        st.success(item)
                                else:
                                    st.info("No category reached grade A in the latest selected month.")
                            with w_col:
                                st.markdown("#### Needs Improvement")
                                if weaknesses:
                                    for item in weaknesses:
                                        st.warning(item)
                                else:
                                    st.success("No critical category is below 70/100.")

                            show_cols = [
                                "Month", "Raw Overall Score", "Penalty Points", "Overall Score", "Overall Grade",
                                "Missing Entries", "Justified Missing Entries", "Unjustified Missing Entries",
                                "Utilization Score", "Activities/Hour Score", "Activities Count Score", "Activities",
                                "Activities_Per_Hour", "Utilization_%", "Undocumented_Time"
                            ]
                            st.markdown("### Evaluation Data")
                            st.dataframe(eval_monthly[show_cols].round(2), use_container_width=True)

    if selected_kpi_tab == 'Alerts':
        st.subheader("Alerts")
        if not has_permission(current_permissions, "Alerts"):
            st.error("Nemaš dozvolu za Alerts modul.")
            st.stop()
        st.caption("Alert proverava aktivne tehničare iz taba 'Technicians' i upisuje missing datume u 'MISSING_WORK_TIME'. Aktivnosti od 00:00 do 05:59 računaju se za prethodni radni dan.")
        auto_col1, auto_col2, auto_col3 = st.columns(3)
        with auto_col1:
            if st.button("Run missing work-time check now", key="force_missing_work_check", disabled=not can_edit_kpi):
                st.write(run_missing_work_time_check(force=True))
        with auto_col2:
            if st.button("Run missing BN check now", key="force_missing_bn_check", disabled=not can_edit_kpi):
                st.write(run_missing_bn_check(force=True))
        with auto_col3:
            if st.button("Run open-task reminder now", key="force_open_task_reminder", disabled=not can_edit_kpi):
                st.write(run_open_task_reminder_check(force=True))
        alert_day = st.date_input("Izaberi radni dan za proveru", value=default_alert_day, min_value=df_base["Radni_dan"].min().date(), max_value=df_base["Radni_dan"].max().date(), format="DD.MM.YYYY", key="alerts_selected_day")
        alert_day_ts = pd.to_datetime(alert_day)
        if alert_day_ts.weekday() >= 5:
            st.info("Subota i nedelja se ne računaju za missing-entry alert. Datum nije upisan u MISSING_WORK_TIME.")
            missing_alert_df = pd.DataFrame()
        elif not active_technicians:
            st.markdown('<div class="alert-yellow">⚠️ Nije pronađena lista aktivnih tehničara. Proveri tab <b>Technicians</b> u KPI Google Sheet-u.</div>', unsafe_allow_html=True)
            missing_alert_df = pd.DataFrame()
        else:
            day_data = daily_tech_all_base[daily_tech_all_base["Radni_dan"] == alert_day_ts].copy()
            techs_with_input = sorted(day_data["Tehničar/Inženjer"].dropna().astype(str).str.strip().unique().tolist())
            input_keys = {_normalize_name_key(t) for t in techs_with_input}
            missing_technicians = sorted([t for t in active_technicians if _normalize_name_key(t) not in input_keys])
            missing_alert_df = pd.DataFrame({"Radni_dan": [alert_day_ts.strftime("%d.%m.%Y")] * len(missing_technicians), "Tehničar": missing_technicians, "Alert": ["Nema nijedan unos za izabrani dan"] * len(missing_technicians)})
            if missing_technicians:
                st.markdown(f'<div class="alert-red">🚨 <b>Tehničari bez unosa za {alert_day_ts.strftime("%d.%m.%Y")}:</b><br>' + '<br>'.join(['- ' + t for t in missing_technicians]) + '</div>', unsafe_allow_html=True)
                st.dataframe(missing_alert_df, use_container_width=True)
                if st.button("Send alert and log selected date", key="send_selected_missing_alert", disabled=not can_edit_kpi):
                    send_missing_time_email(missing_technicians, alert_day_ts)
                    try:
                        updated_count, skipped_existing = log_missing_technician_dates(missing_technicians, alert_day_ts)
                        if updated_count > 0:
                            st.success(f"Upisano u tab '{MISSING_WORK_TIME_SHEET_NAME}': {updated_count} missing date zapis/a.")
                        elif skipped_existing:
                            st.info("Datum je već ranije upisan za ove tehničare, nema dupliranja.")
                    except Exception as e:
                        st.error("Nije uspeo upis u tab 'MISSING_WORK_TIME'. Proveri permission service account-a i Google Sheet access.")
                        st.write(e)
            else:
                st.markdown(f'<div class="alert-green">✅ Svi aktivni tehničari imaju bar jedan unos za {alert_day_ts.strftime("%d.%m.%Y")}.</div>', unsafe_allow_html=True)
        over_8h_df = daily_tech_all_base[(daily_tech_all_base["Radni_dan"] == alert_day_ts) & (daily_tech_all_base["Total_Hours"] > 8)].copy()
        if not over_8h_df.empty:
            over_8h_show = over_8h_df.copy()
            over_8h_show["Radni_dan"] = over_8h_show["Radni_dan"].dt.strftime("%d.%m.%Y")
            over_8h_show = over_8h_show.rename(columns={"Tehničar/Inženjer": "Tehničar", "Total_Hours": "Ukupno sati", "Activities": "Broj aktivnosti"})
            over_8h_show["Alert"] = "Ukupno vreme unosa je preko 8h"
            st.markdown('<div class="alert-yellow">⚠️ <b>Postoje tehničari sa više od 8h ukupnog unosa za izabrani dan.</b></div>', unsafe_allow_html=True)
            st.dataframe(over_8h_show, use_container_width=True)
        else:
            st.markdown('<div class="alert-green">✅ Nema tehničara sa više od 8h ukupnog unosa za izabrani dan.</div>', unsafe_allow_html=True)
        st.markdown("### Dnevni zbir po tehničaru")
        day_summary = daily_tech_all_base[daily_tech_all_base["Radni_dan"] == alert_day_ts].copy()
        if not day_summary.empty:
            day_summary["Radni_dan"] = day_summary["Radni_dan"].dt.strftime("%d.%m.%Y")
            st.dataframe(day_summary, use_container_width=True)
        else:
            st.warning("Nema nijednog unosa za izabrani radni dan.")

    if selected_kpi_tab == 'Export':
        st.subheader("Export")
        if not has_permission(current_permissions, "Exports"):
            st.error("Nemaš dozvolu za Export.")
            st.stop()
        excel_file = create_excel_report(df, daily, monthly, yearly, category, tech_all, pareto)
        st.download_button(label="📥 Download Excel Report", data=excel_file, file_name="kpi_process_report.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="kpi_download_excel_report")
        st.info("PDF export je privremeno izostavljen iz ove stabilne Alerts verzije. Ako treba, vraćamo ga u sledećem koraku.")

if selected_module == "Line Verification / Dummy":
    require_module_access("Line Verification / Dummy", ["Line_Verification", "Line Verification", "Dummy", "Line_Verification_Dummy"])
    render_line_verification_module()

if selected_module == "Bottleneck":
    require_module_access("Bottleneck", ["BN_Entry", "BN_Module", "Bottleneck", "BN"])
    can_edit_bn = can_edit_module("Bottleneck")
    try:
        sync_result = {"status": "background_managed"}
        if can_edit_bn and st.sidebar.button("Sync latest BN Forms", key="bn_manual_forms_sync"):
            sync_result = maybe_sync_bn_forms(force=True)
        master=load_bn_machines(); df_bn=prepare_bn_records_data()
    except Exception as e:
        st.error("Ne mogu da učitam BN bazu."); st.write(e); st.stop()

    tabs=st.tabs(["BN Entry","BN Dashboard","BN Machines"])
    with tabs[0]:
        if not can_edit_bn:
            st.info("Read-only access: BN Entry je vidljiv, ali unos i update nisu dozvoljeni.")
        active=master[master["Active"].apply(_yes_value)].copy()
        if active.empty:
            st.warning("Nema aktivnih BN mašina u BN_MACHINES.")
            if not master.empty:
                st.caption(
                    "Učitani redovi postoje, ali nijedan nema Active = YES. "
                    "Proveri vrednosti u koloni Active."
                )
                st.dataframe(master, use_container_width=True)
        else:
            projects=sorted(active["Project"].astype(str).unique())
            c1,c2=st.columns(2)
            with c1: entry_date=st.date_input("Date",value=date.today(),format="DD.MM.YYYY",key="bn_entry_date",disabled=not can_edit_bn)
            with c2: project=st.selectbox("Project",projects,key="bn_entry_project",disabled=not can_edit_bn)
            subset=active[active["Project"].astype(str).eq(project)]
            machine=st.selectbox("Machine",sorted(subset["Machine"].astype(str).tolist()),key="bn_entry_machine",disabled=not can_edit_bn)
            row=subset[subset["Machine"].astype(str).eq(machine)].iloc[0]; mid=str(row["Machine_ID"])
            prev=_bn_previous(mid,entry_date,False)
            default=float(prev["BN_Time"]) if prev is not None else 0.0
            if prev is not None: st.info(f'Last BN: {float(prev["BN_Time"]):g} sec | {prev["Date"]}')
            default_station=str(prev["Station"]).strip() if prev is not None and "Station" in prev.index else ""
            station=st.text_input(
                "Station",
                value=default_station,
                placeholder="OP100, OP200...",
                key=f"bn_station_{mid}_{entry_date}",
                disabled=not can_edit_bn,
            )
            bn_time=st.number_input("BN Time (sec)",min_value=0.0,value=default,step=0.1,key=f"bn_value_{mid}_{entry_date}",disabled=not can_edit_bn)
            if st.button("Save BN",key="save_bn_entry",disabled=not can_edit_bn):
                if not station.strip():
                    st.error("Station is mandatory.")
                    st.stop()
                entry={"Date":entry_date,"Machine_ID":mid,"Project":project,"Machine":machine,"BN_Time":bn_time,"Station":station.strip(),"Entered_By":_current_user_display_name(),"Entered_By_Username":str(current_user.get("username", "")),"Entered_By_Email":_current_user_email()}
                res=save_bn_record(entry,False)
                if res["status"]=="duplicate": st.session_state["bn_pending_update"]=entry
                else: st.success("BN successfully saved.")
            if st.session_state.get("bn_pending_update"):
                st.warning("BN already exists for this date and machine.")
                choice=st.radio("Existing entry",["Error / Cancel","Update existing BN"],key="bn_duplicate_choice")
                if st.button("Confirm",key="bn_duplicate_confirm",disabled=not can_edit_bn):
                    if choice.startswith("Update"):
                        save_bn_record(st.session_state["bn_pending_update"],True); st.success("BN successfully updated.")
                    st.session_state.pop("bn_pending_update",None); st.rerun()

    with tabs[1]:
        if df_bn.empty: st.info("No BN records yet.")
        else:
            projects=["All"]+sorted(df_bn["Project"].astype(str).unique())
            project_filter=st.selectbox("Project filter",projects,key="bn_dash_project")
            show=df_bn if project_filter=="All" else df_bn[df_bn["Project"].eq(project_filter)]
            machine_opts=["All"]+sorted(show["Machine"].astype(str).unique())
            machine_filter=st.selectbox("Machine filter",machine_opts,key="bn_dash_machine")
            if machine_filter!="All": show=show[show["Machine"].eq(machine_filter)]
            m1,m2,m3=st.columns(3); m1.metric("Records",len(show)); m2.metric("Average BN",round(show["BN_sec"].mean(),2)); m3.metric("Max BN",round(show["BN_sec"].max(),2))
            trend=show.groupby(["Date","Machine"],as_index=False)["BN_sec"].mean()
            fig=px.line(trend,x="Date",y="BN_sec",color="Machine",markers=True,title="BN Trend")
            st.plotly_chart(style_chart(fig),use_container_width=True)
            display=show[["Date","Project","Machine","Station","BN_sec","Entered_By"]].sort_values("Date",ascending=False).copy(); display["Date"]=display["Date"].dt.strftime("%d.%m.%Y")
            st.dataframe(display,use_container_width=True)

    with tabs[2]:
        st.dataframe(master,use_container_width=True)
        if is_admin_user(current_user) and can_edit_bn:
            st.markdown("### Add BN Machine")
            pcol,mcol=st.columns(2)
            with pcol: new_project=st.text_input("Project",key="bn_new_project")
            with mcol: new_machine=st.text_input("Machine",key="bn_new_machine")
            if st.button("Add machine",key="bn_add_machine"):
                if not new_project.strip() or not new_machine.strip(): st.error("Project and Machine are required.")
                else:
                    res=add_bn_machine(new_project.strip(),new_machine.strip())
                    if res["status"]=="exists": st.warning("Machine already exists.")
                    else: st.success(f'Machine created: {res["Machine_ID"]}'); st.rerun()
        st.caption(f'Forms sync: {sync_result}')
