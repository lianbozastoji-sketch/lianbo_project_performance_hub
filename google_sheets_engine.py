"""Process-wide Google Sheets read cache, quota-aware rate limiter and 429 recovery.

This module transparently wraps gspread worksheet read/write methods. It is
designed for Streamlit, where every widget interaction reruns the application
and can otherwise produce many identical Google Sheets API requests.

v9.9 changes
------------
* Sliding-window limiter that follows the real Google quota (60 read and 60
  write requests per minute for one service account) instead of a fixed
  0.35 s sleep before every request. Bursts are now fast; only a request that
  would exceed the quota waits.
* ``fresh_reads()`` context manager. Code that must see the live sheet
  (duplicate checks, row-number resolution before a write, synchronization)
  bypasses the cache and never receives stale data.
* Stale data is returned only after every retry has failed, and the event is
  recorded so the UI can warn the user instead of silently hiding new rows.
"""

from __future__ import annotations

import collections
import contextlib
import copy
import functools
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterator

import gspread


@dataclass
class _CacheEntry:
    value: Any
    stored_at: float


class _SlidingWindowLimiter:
    """Allow at most ``max_calls`` per ``window`` seconds, process wide."""

    def __init__(self, max_calls: int, window: float = 60.0, min_interval: float = 0.05) -> None:
        self.max_calls = max(int(max_calls), 1)
        self.window = float(window)
        self.min_interval = max(float(min_interval), 0.0)
        self._calls: collections.deque[float] = collections.deque()
        self._lock = threading.Lock()
        self._last = 0.0

    def acquire(self) -> float:
        """Block until a call is allowed. Returns the time spent waiting."""
        waited = 0.0
        while True:
            with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= self.window:
                    self._calls.popleft()
                gap = self.min_interval - (now - self._last)
                if len(self._calls) < self.max_calls and gap <= 0:
                    self._calls.append(now)
                    self._last = now
                    return waited
                if len(self._calls) >= self.max_calls:
                    sleep_for = self.window - (now - self._calls[0]) + 0.01
                else:
                    sleep_for = gap
            sleep_for = max(min(sleep_for, 5.0), 0.01)
            time.sleep(sleep_for)
            waited += sleep_for

    def usage(self) -> int:
        with self._lock:
            now = time.monotonic()
            while self._calls and now - self._calls[0] >= self.window:
                self._calls.popleft()
            return len(self._calls)


class GoogleSheetsEngine:
    def __init__(
        self,
        *,
        ttl_seconds: int = 60,
        stale_seconds: int = 900,
        reads_per_minute: int = 55,
        writes_per_minute: int = 55,
    ) -> None:
        self.ttl_seconds = max(int(ttl_seconds), 1)
        self.stale_seconds = max(int(stale_seconds), self.ttl_seconds)
        self._cache: dict[tuple[Any, ...], _CacheEntry] = {}
        self._cache_lock = threading.RLock()
        self._read_limiter = _SlidingWindowLimiter(reads_per_minute)
        self._write_limiter = _SlidingWindowLimiter(writes_per_minute)
        self._local = threading.local()
        self._installed = False
        self._originals: dict[str, Callable[..., Any]] = {}
        self._stats_lock = threading.Lock()
        self.stats = {
            "api_reads": 0,
            "api_writes": 0,
            "cache_hits": 0,
            "quota_retries": 0,
            "stale_served": 0,
            "last_stale_at": 0.0,
        }

    # ------------------------------------------------------------------ helpers
    def _bump(self, key: str, amount: int = 1) -> None:
        with self._stats_lock:
            self.stats[key] = self.stats.get(key, 0) + amount

    @staticmethod
    def _is_quota_error(exc: BaseException) -> bool:
        message = str(exc).lower()
        return (
            "429" in message
            or "quota exceeded" in message
            or "rate limit" in message
            or "resource_exhausted" in message
        )

    @staticmethod
    def _is_transient_error(exc: BaseException) -> bool:
        message = str(exc).lower()
        return any(code in message for code in ("500", "502", "503", "504", "internal error", "backend error", "timed out", "connection reset"))

    @staticmethod
    def _worksheet_identity(worksheet: Any) -> tuple[str, str, str]:
        spreadsheet_id = str(
            getattr(worksheet, "spreadsheet_id", "")
            or getattr(getattr(worksheet, "spreadsheet", None), "id", "")
            or ""
        )
        worksheet_id = str(getattr(worksheet, "id", "") or "")
        title = str(getattr(worksheet, "title", "") or "")
        return spreadsheet_id, worksheet_id, title

    @staticmethod
    def _freeze(value: Any) -> Any:
        if isinstance(value, dict):
            return tuple(sorted((str(k), GoogleSheetsEngine._freeze(v)) for k, v in value.items()))
        if isinstance(value, (list, tuple)):
            return tuple(GoogleSheetsEngine._freeze(v) for v in value)
        if isinstance(value, set):
            return tuple(sorted(GoogleSheetsEngine._freeze(v) for v in value))
        try:
            hash(value)
            return value
        except Exception:
            return repr(value)

    def _key(self, method_name: str, worksheet: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[Any, ...]:
        return (method_name, *self._worksheet_identity(worksheet), self._freeze(args), self._freeze(kwargs))

    @staticmethod
    def _copy(value: Any) -> Any:
        # Lists of lists are the common case; a nested list copy is much faster
        # than deepcopy for large worksheets.
        if isinstance(value, list):
            return [list(row) if isinstance(row, list) else (dict(row) if isinstance(row, dict) else row) for row in value]
        try:
            return copy.deepcopy(value)
        except Exception:
            return value

    def _get_cached(self, key: tuple[Any, ...], max_age: float) -> Any | None:
        now = time.monotonic()
        with self._cache_lock:
            entry = self._cache.get(key)
            if entry is None or now - entry.stored_at > max_age:
                return None
            return self._copy(entry.value)

    def _store(self, key: tuple[Any, ...], value: Any) -> None:
        with self._cache_lock:
            self._cache[key] = _CacheEntry(self._copy(value), time.monotonic())
            if len(self._cache) > 2000:
                oldest = sorted(self._cache.items(), key=lambda item: item[1].stored_at)[:500]
                for old_key, _ in oldest:
                    self._cache.pop(old_key, None)

    # ------------------------------------------------------------- fresh reads
    @property
    def bypass_cache(self) -> bool:
        return getattr(self._local, "fresh_depth", 0) > 0

    @contextlib.contextmanager
    def fresh_reads(self) -> Iterator[None]:
        """Inside this block every worksheet read goes to Google (no cache, no stale)."""
        self._local.fresh_depth = getattr(self._local, "fresh_depth", 0) + 1
        try:
            yield
        finally:
            self._local.fresh_depth -= 1

    # -------------------------------------------------------------- read path
    @contextlib.contextmanager
    def _nested(self, kind: str) -> Iterator[bool]:
        """Detect gspread methods calling other wrapped methods internally.

        ``get_all_records`` calls ``get_all_values`` which calls ``get_values``
        and ``get``; ``append_row`` calls ``append_rows``. Only the outermost
        call is cached/limited, otherwise one API request would be counted
        several times against the quota.
        """
        attr = f"depth_{kind}"
        depth = getattr(self._local, attr, 0)
        setattr(self._local, attr, depth + 1)
        try:
            yield depth > 0
        finally:
            setattr(self._local, attr, depth)

    def cached_read(self, method_name: str, original: Callable[..., Any], worksheet: Any, *args: Any, **kwargs: Any) -> Any:
        with self._nested("read") as is_inner:
            if is_inner:
                return original(worksheet, *args, **kwargs)
            return self._cached_read_outer(method_name, original, worksheet, *args, **kwargs)

    def _cached_read_outer(self, method_name: str, original: Callable[..., Any], worksheet: Any, *args: Any, **kwargs: Any) -> Any:
        key = self._key(method_name, worksheet, args, kwargs)
        fresh_required = self.bypass_cache
        if not fresh_required:
            cached = self._get_cached(key, self.ttl_seconds)
            if cached is not None:
                self._bump("cache_hits")
                return cached

        last_error: BaseException | None = None
        for attempt, delay in enumerate((0, 2, 4, 8, 16)):
            if delay:
                time.sleep(delay)
            try:
                self._read_limiter.acquire()
                self._bump("api_reads")
                value = original(worksheet, *args, **kwargs)
                self._store(key, value)
                return self._copy(value)
            except BaseException as exc:  # noqa: BLE001 - re-raised below
                last_error = exc
                if not (self._is_quota_error(exc) or self._is_transient_error(exc)):
                    raise
                self._bump("quota_retries")

        # Every retry failed. A normal page view may show older data, but the
        # event is recorded so the UI can say so. Fresh reads never get stale data.
        if not fresh_required:
            stale = self._get_cached(key, self.stale_seconds)
            if stale is not None:
                self._bump("stale_served")
                with self._stats_lock:
                    self.stats["last_stale_at"] = time.time()
                return stale
        if last_error is not None:
            raise last_error
        raise RuntimeError("Google Sheets read failed without an exception.")

    # ------------------------------------------------------------- write path
    def guarded_write(self, original: Callable[..., Any], worksheet: Any, *args: Any, **kwargs: Any) -> Any:
        with self._nested("write") as is_inner:
            if is_inner:
                return original(worksheet, *args, **kwargs)
            return self._guarded_write_outer(original, worksheet, *args, **kwargs)

    def _guarded_write_outer(self, original: Callable[..., Any], worksheet: Any, *args: Any, **kwargs: Any) -> Any:
        self.invalidate_worksheet(worksheet)
        last_error: BaseException | None = None
        for delay in (0, 3, 8, 15):
            if delay:
                time.sleep(delay)
            try:
                self._write_limiter.acquire()
                self._bump("api_writes")
                result = original(worksheet, *args, **kwargs)
                self.invalidate_worksheet(worksheet)
                return result
            except BaseException as exc:  # noqa: BLE001
                last_error = exc
                # Only a quota refusal is retried: Google did not apply the
                # request, so retrying cannot create a duplicate row.
                if not self._is_quota_error(exc):
                    self.invalidate_worksheet(worksheet)
                    raise
                self._bump("quota_retries")
        self.invalidate_worksheet(worksheet)
        if last_error is not None:
            raise last_error
        raise RuntimeError("Google Sheets write failed without an exception.")

    def invalidate_worksheet(self, worksheet: Any) -> None:
        identity = self._worksheet_identity(worksheet)
        with self._cache_lock:
            keys = [key for key in self._cache if len(key) >= 4 and tuple(key[1:4]) == identity]
            for key in keys:
                self._cache.pop(key, None)

    def clear(self) -> None:
        with self._cache_lock:
            self._cache.clear()

    def recently_served_stale(self, within_seconds: float = 300) -> bool:
        with self._stats_lock:
            last = float(self.stats.get("last_stale_at", 0.0) or 0.0)
        return bool(last) and (time.time() - last) <= within_seconds

    def diagnostics(self) -> dict[str, Any]:
        with self._cache_lock:
            count = len(self._cache)
        with self._stats_lock:
            stats = dict(self.stats)
        return {
            "cached_reads": count,
            "ttl_seconds": self.ttl_seconds,
            "stale_seconds": self.stale_seconds,
            "reads_last_minute": self._read_limiter.usage(),
            "writes_last_minute": self._write_limiter.usage(),
            "installed": self._installed,
            **stats,
        }

    def install(self) -> None:
        if self._installed:
            return

        worksheet_cls = gspread.Worksheet

        for method_name in ("get_all_values", "get_all_records", "get", "get_values", "row_values", "col_values", "batch_get"):
            original = getattr(worksheet_cls, method_name, None)
            if original is None:
                continue
            self._originals[method_name] = original

            def make_read_wrapper(name: str, original_method: Callable[..., Any]):
                @functools.wraps(original_method)
                def wrapper(worksheet: Any, *args: Any, **kwargs: Any):
                    return self.cached_read(name, original_method, worksheet, *args, **kwargs)
                return wrapper

            setattr(worksheet_cls, method_name, make_read_wrapper(method_name, original))

        for method_name in (
            "append_row", "append_rows", "update", "batch_update", "update_cell", "update_cells",
            "insert_row", "insert_rows", "delete_rows", "clear", "batch_clear", "resize", "add_rows",
        ):
            original = getattr(worksheet_cls, method_name, None)
            if original is None:
                continue
            self._originals[method_name] = original

            def make_write_wrapper(original_method: Callable[..., Any]):
                @functools.wraps(original_method)
                def wrapper(worksheet: Any, *args: Any, **kwargs: Any):
                    return self.guarded_write(original_method, worksheet, *args, **kwargs)
                return wrapper

            setattr(worksheet_cls, method_name, make_write_wrapper(original))

        # Spreadsheet-level structural writes (row deletion, add worksheet, ...)
        # must also invalidate every cached read of that spreadsheet.
        spreadsheet_cls = getattr(gspread, "Spreadsheet", None)
        if spreadsheet_cls is not None:
            for method_name in ("batch_update", "values_batch_update", "values_clear", "values_update", "values_append"):
                original = getattr(spreadsheet_cls, method_name, None)
                if original is None:
                    continue
                self._originals[f"Spreadsheet.{method_name}"] = original

                def make_sheet_write_wrapper(original_method: Callable[..., Any]):
                    @functools.wraps(original_method)
                    def wrapper(spreadsheet: Any, *args: Any, **kwargs: Any):
                        # Worksheet writes already pass the limiter and call these
                        # methods internally, so only cache invalidation happens here.
                        try:
                            return original_method(spreadsheet, *args, **kwargs)
                        finally:
                            self.invalidate_spreadsheet(getattr(spreadsheet, "id", ""))
                    return wrapper

                setattr(spreadsheet_cls, method_name, make_sheet_write_wrapper(original))

        self._installed = True

    def invalidate_spreadsheet(self, spreadsheet_id: str) -> None:
        spreadsheet_id = str(spreadsheet_id or "")
        with self._cache_lock:
            keys = [key for key in self._cache if len(key) >= 2 and (not spreadsheet_id or key[1] == spreadsheet_id)]
            for key in keys:
                self._cache.pop(key, None)


_ENGINE = GoogleSheetsEngine()


def install_google_sheets_engine() -> GoogleSheetsEngine:
    _ENGINE.install()
    return _ENGINE


def clear_google_sheets_read_cache() -> None:
    _ENGINE.clear()


def fresh_reads():
    """Context manager: bypass the read cache for live, mutation-safe reads."""
    return _ENGINE.fresh_reads()


def google_sheets_engine_diagnostics() -> dict[str, Any]:
    return _ENGINE.diagnostics()
