"""In-memory Google Sheets used by the simulation.

Behaviour copied from the real service where it matters for data integrity:
* USER_ENTERED turns dates/times into Sheets values and shows them back in a
  locale format (here a Serbian-like "5.6.2026" / "8:30:00"), text starting
  with = + - @ becomes a formula error unless prefixed with an apostrophe;
* append with table_range anchors at column A;
* optional quota simulation raising HTTP 429.
"""
from __future__ import annotations

import re
import threading
from typing import Any

from . import exceptions  # noqa: F401
from .exceptions import APIError, WorksheetNotFound, SpreadsheetNotFound, GSpreadException  # noqa: F401

QUOTA = {"fail_every": 0, "counter": 0, "reads": 0, "writes": 0}
_LOCK = threading.RLock()


def _quota_tick(kind: str) -> None:
    with _LOCK:
        QUOTA[kind] += 1
        QUOTA["counter"] += 1
        every = QUOTA["fail_every"]
        if every and QUOTA["counter"] % every == 0:
            raise APIError("APIError: [429]: Quota exceeded for quota metric 'Read requests'")


def _col_to_index(letters: str) -> int:
    value = 0
    for ch in letters.upper():
        value = value * 26 + (ord(ch) - 64)
    return value - 1


def _parse_a1(a1: str):
    """Return (r1, c1, r2, c2) zero-based inclusive; None = open."""
    a1 = a1.split("!")[-1]
    parts = a1.split(":")

    def cell(text):
        m = re.fullmatch(r"([A-Za-z]*)(\d*)", text)
        letters, digits = m.group(1), m.group(2)
        col = _col_to_index(letters) if letters else None
        row = int(digits) - 1 if digits else None
        return row, col

    r1, c1 = cell(parts[0])
    if len(parts) == 1:
        return r1, c1, r1, c1
    r2, c2 = cell(parts[1])
    return r1, c1, r2, c2


_DATE_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")
_NUM_RE = re.compile(r"^-?\d+(?:\.\d+)?$")


def user_entered(value: Any) -> Any:
    """Emulate how Google Sheets stores and then displays a USER_ENTERED value."""
    if not isinstance(value, str):
        return value
    text = value
    if text.startswith("'"):
        return text[1:]
    if text and text[0] in "=+-@" and not _NUM_RE.match(text):
        return "#ERROR!"
    m = _DATE_RE.match(text)
    if m:
        return f"{int(m.group(1))}.{int(m.group(2))}.{m.group(3)}"
    m = _TIME_RE.match(text)
    if m:
        return f"{int(m.group(1))}:{m.group(2)}:{m.group(3) or '00'}"
    if _NUM_RE.match(text):
        return float(text) if "." in text else int(text)
    return text


class Worksheet:
    _next_id = 1

    def __init__(self, spreadsheet: "Spreadsheet", title: str, values=None):
        self.spreadsheet = spreadsheet
        self.title = title
        self.id = Worksheet._next_id
        Worksheet._next_id += 1
        self.values: list[list[Any]] = [list(r) for r in (values or [])]

    @property
    def spreadsheet_id(self):
        return self.spreadsheet.id

    # ---------------------------------------------------------- helpers
    def _display(self, v):
        return "" if v is None else (str(v) if not isinstance(v, str) else v)

    def _grid(self):
        width = max((len(r) for r in self.values), default=0)
        rows = [list(r) + [""] * (width - len(r)) for r in self.values]
        while rows and not any(str(c).strip() for c in rows[-1]):
            rows.pop()
        return rows

    def _ensure(self, row, col):
        while len(self.values) <= row:
            self.values.append([])
        r = self.values[row]
        while len(r) <= col:
            r.append("")

    def _store(self, value, value_input_option):
        if value_input_option == "USER_ENTERED":
            return user_entered(value)
        return value

    # ---------------------------------------------------------- reads
    def get_all_values(self, *a, **k):
        _quota_tick("reads")
        return [[self._display(c) for c in r] for r in self._grid()]

    def get_values(self, *a, **k):
        return self.get_all_values()

    def get_all_records(self, *a, **k):
        _quota_tick("reads")
        grid = self._grid()
        if not grid:
            return []
        headers = [str(h) for h in grid[0]]
        out = []
        for row in grid[1:]:
            record = {}
            for h, v in zip(headers, row):
                if isinstance(v, str) and _NUM_RE.match(v.strip() or "x"):
                    v = float(v) if "." in v else int(v)
                record[h] = v
            out.append(record)
        return out

    def row_values(self, row, *a, **k):
        _quota_tick("reads")
        grid = self._grid()
        if row - 1 >= len(grid):
            return []
        r = [self._display(c) for c in grid[row - 1]]
        while r and r[-1] == "":
            r.pop()
        return r

    def col_values(self, col, *a, **k):
        _quota_tick("reads")
        out = [self._display(r[col - 1]) if col - 1 < len(r) else "" for r in self._grid()]
        while out and out[-1] == "":
            out.pop()
        return out

    def get(self, a1="", *a, value_render_option=None, **k):
        _quota_tick("reads")
        r1, c1, r2, c2 = _parse_a1(a1)
        grid = self._grid()
        r1 = 0 if r1 is None else r1
        r2 = len(grid) - 1 if r2 is None else r2
        out = []
        for ri in range(r1, min(r2, len(grid) - 1) + 1):
            row = grid[ri]
            cc1 = 0 if c1 is None else c1
            cc2 = len(row) - 1 if c2 is None else c2
            cells = []
            for ci in range(cc1, cc2 + 1):
                v = row[ci] if ci < len(row) else ""
                if value_render_option != "UNFORMATTED_VALUE":
                    v = self._display(v)
                cells.append(v)
            while cells and cells[-1] in ("", None):
                cells.pop()
            out.append(cells)
        while out and not out[-1]:
            out.pop()
        return out

    def batch_get(self, ranges, *a, **k):
        return [self.get(r) for r in ranges]

    # ---------------------------------------------------------- writes
    def update(self, range_name=None, values=None, *a, value_input_option="RAW", **k):
        _quota_tick("writes")
        if isinstance(range_name, list) and values is None:
            range_name, values = "A1", range_name
        r1, c1, _, _ = _parse_a1(range_name or "A1")
        r1 = r1 or 0
        c1 = c1 or 0
        for ri, row in enumerate(values or []):
            for ci, v in enumerate(row):
                self._ensure(r1 + ri, c1 + ci)
                self.values[r1 + ri][c1 + ci] = self._store(v, value_input_option)
        return {"updatedRange": range_name}

    def update_cell(self, row, col, value):
        _quota_tick("writes")
        self._ensure(row - 1, col - 1)
        self.values[row - 1][col - 1] = value

    def batch_update(self, data, *a, value_input_option="RAW", **k):
        for item in data:
            self.update(item["range"], item["values"], value_input_option=value_input_option)
        return {}

    def append_row(self, values, value_input_option="RAW", table_range=None, **k):
        return self.append_rows([values], value_input_option=value_input_option, table_range=table_range)

    def append_rows(self, rows, value_input_option="RAW", table_range=None, **k):
        _quota_tick("writes")
        grid = self._grid()
        start = len(grid)
        # Real Google behaviour without an anchor: a table that does not start in
        # column A makes appends land in shifted columns. Anchoring avoids it.
        offset = 0
        if table_range is None and grid:
            first_cols = [next((i for i, c in enumerate(r) if str(c).strip()), 0) for r in grid[-3:]]
            offset = min(first_cols) if first_cols else 0
        for i, row in enumerate(rows):
            for j, v in enumerate(row):
                self._ensure(start + i, offset + j)
                self.values[start + i][offset + j] = self._store(v, value_input_option)
        return {"updates": {"updatedRange": f"A{start + 1}"}}

    def batch_clear(self, ranges):
        _quota_tick("writes")
        for rng in ranges:
            r1, c1, r2, c2 = _parse_a1(rng)
            for ri in range((r1 or 0), (r2 if r2 is not None else len(self.values) - 1) + 1):
                if ri < len(self.values):
                    for ci in range(c1 or 0, (c2 if c2 is not None else len(self.values[ri]) - 1) + 1):
                        if ci < len(self.values[ri]):
                            self.values[ri][ci] = ""

    def clear(self):
        _quota_tick("writes")
        self.values = []

    def delete_rows(self, start, end=None):
        _quota_tick("writes")
        end = end or start
        del self.values[start - 1:end]


class Spreadsheet:
    def __init__(self, key: str):
        self.id = key
        self._sheets: dict[str, Worksheet] = {}

    def add(self, title, values=None):
        ws = Worksheet(self, title, values)
        self._sheets[title] = ws
        return ws

    def worksheet(self, title):
        _quota_tick("reads")
        if title not in self._sheets:
            raise WorksheetNotFound(title)
        return self._sheets[title]

    def worksheets(self):
        _quota_tick("reads")
        return list(self._sheets.values())

    def add_worksheet(self, title, rows=1000, cols=26, **k):
        _quota_tick("writes")
        if title in self._sheets:
            raise APIError(f"A sheet with the name \"{title}\" already exists.")
        return self.add(title)

    def batch_update(self, body):
        _quota_tick("writes")
        for request in body.get("requests", []):
            dim = request.get("deleteDimension")
            if dim:
                rng = dim["range"]
                ws = next(w for w in self._sheets.values() if w.id == rng["sheetId"])
                del ws.values[rng["startIndex"]:rng["endIndex"]]
        return {}

    def values_batch_update(self, *a, **k):
        return {}


class Client:
    def __init__(self, store):
        self.store = store

    def open_by_key(self, key):
        _quota_tick("reads")
        if key not in self.store:
            raise SpreadsheetNotFound(key)
        return self.store[key]


STORE: dict[str, Spreadsheet] = {}


def authorize(creds):
    return Client(STORE)


def reset_store():
    STORE.clear()
    QUOTA.update({"fail_every": 0, "counter": 0, "reads": 0, "writes": 0})
