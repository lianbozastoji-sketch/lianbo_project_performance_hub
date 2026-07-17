"""Process-wide Google Sheets read cache, rate limiter and 429 recovery.

This module transparently wraps gspread worksheet read/write methods. It is
designed for Streamlit, where every widget interaction reruns the application
and can otherwise produce many identical Google Sheets API requests.
"""

from __future__ import annotations

import copy
import functools
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import gspread


@dataclass
class _CacheEntry:
    value: Any
    stored_at: float


class GoogleSheetsEngine:
    def __init__(
        self,
        *,
        ttl_seconds: int = 180,
        stale_seconds: int = 1800,
        min_request_interval: float = 1.10,
    ) -> None:
        self.ttl_seconds = max(int(ttl_seconds), 1)
        self.stale_seconds = max(int(stale_seconds), self.ttl_seconds)
        self.min_request_interval = max(float(min_request_interval), 0.0)
        self._cache: dict[tuple[Any, ...], _CacheEntry] = {}
        self._cache_lock = threading.RLock()
        self._request_lock = threading.RLock()
        self._last_request_at = 0.0
        self._installed = False
        self._originals: dict[str, Callable[..., Any]] = {}

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

    def _key(
        self,
        method_name: str,
        worksheet: Any,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> tuple[Any, ...]:
        return (
            method_name,
            *self._worksheet_identity(worksheet),
            self._freeze(args),
            self._freeze(kwargs),
        )

    def _copy(self, value: Any) -> Any:
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

    def _throttle(self) -> None:
        with self._request_lock:
            now = time.monotonic()
            wait = self.min_request_interval - (now - self._last_request_at)
            if wait > 0:
                time.sleep(wait)
            self._last_request_at = time.monotonic()

    def cached_read(
        self,
        method_name: str,
        original: Callable[..., Any],
        worksheet: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        key = self._key(method_name, worksheet, args, kwargs)
        fresh = self._get_cached(key, self.ttl_seconds)
        if fresh is not None:
            return fresh

        last_error: BaseException | None = None
        for delay in (0, 2, 5, 10, 20):
            if delay:
                time.sleep(delay)
            try:
                self._throttle()
                value = original(worksheet, *args, **kwargs)
                self._store(key, value)
                return self._copy(value)
            except BaseException as exc:
                last_error = exc
                if not self._is_quota_error(exc):
                    raise
                stale = self._get_cached(key, self.stale_seconds)
                if stale is not None:
                    return stale

        if last_error is not None:
            raise last_error
        raise RuntimeError("Google Sheets read failed without an exception.")

    def invalidate_worksheet(self, worksheet: Any) -> None:
        identity = self._worksheet_identity(worksheet)
        with self._cache_lock:
            keys = [
                key
                for key in self._cache
                if len(key) >= 4 and tuple(key[1:4]) == identity
            ]
            for key in keys:
                self._cache.pop(key, None)

    def clear(self) -> None:
        with self._cache_lock:
            self._cache.clear()

    def diagnostics(self) -> dict[str, Any]:
        with self._cache_lock:
            count = len(self._cache)
        return {
            "cached_reads": count,
            "ttl_seconds": self.ttl_seconds,
            "stale_seconds": self.stale_seconds,
            "min_request_interval": self.min_request_interval,
            "installed": self._installed,
        }

    def install(self) -> None:
        if self._installed:
            return

        worksheet_cls = gspread.Worksheet

        for method_name in (
            "get_all_values",
            "get_all_records",
            "get",
            "row_values",
            "col_values",
            "batch_get",
        ):
            original = getattr(worksheet_cls, method_name, None)
            if original is None:
                continue
            self._originals[method_name] = original

            def make_read_wrapper(name: str, original_method: Callable[..., Any]):
                @functools.wraps(original_method)
                def wrapper(worksheet: Any, *args: Any, **kwargs: Any):
                    return self.cached_read(
                        name,
                        original_method,
                        worksheet,
                        *args,
                        **kwargs,
                    )
                return wrapper

            setattr(
                worksheet_cls,
                method_name,
                make_read_wrapper(method_name, original),
            )

        for method_name in (
            "append_row",
            "append_rows",
            "update",
            "batch_update",
            "update_cell",
            "update_cells",
            "insert_row",
            "insert_rows",
            "delete_rows",
            "clear",
            "resize",
            "add_rows",
        ):
            original = getattr(worksheet_cls, method_name, None)
            if original is None:
                continue
            self._originals[method_name] = original

            def make_write_wrapper(original_method: Callable[..., Any]):
                @functools.wraps(original_method)
                def wrapper(worksheet: Any, *args: Any, **kwargs: Any):
                    self.invalidate_worksheet(worksheet)
                    result = original_method(worksheet, *args, **kwargs)
                    self.invalidate_worksheet(worksheet)
                    return result
                return wrapper

            setattr(worksheet_cls, method_name, make_write_wrapper(original))

        self._installed = True


_ENGINE = GoogleSheetsEngine()


def install_google_sheets_engine() -> GoogleSheetsEngine:
    _ENGINE.install()
    return _ENGINE


def clear_google_sheets_read_cache() -> None:
    _ENGINE.clear()


def google_sheets_engine_diagnostics() -> dict[str, Any]:
    return _ENGINE.diagnostics()
