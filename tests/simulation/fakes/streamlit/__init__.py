"""Minimal, deterministic Streamlit replacement used only by the simulation.

It executes the real application script exactly like Streamlit does (top to
bottom on every interaction), keeps session_state between runs, honours
st.rerun()/st.stop(), caches with st.cache_data/st.cache_resource across
reruns and records everything that is shown, so tests can assert on errors,
warnings and success messages.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import functools
import hashlib
import types
from typing import Any

__version__ = "1.46.1-sim"


class StopException(BaseException):
    pass


class RerunException(BaseException):
    pass


class StreamlitAPIException(Exception):
    pass


# --------------------------------------------------------------------------
# Harness state
# --------------------------------------------------------------------------
class SessionState(dict):
    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def __setattr__(self, key, value):
        self[key] = value

    def __setitem__(self, key, value):
        # Real Streamlit: a widget's key cannot be changed after the widget was
        # created in the same run (only before it, or inside a callback).
        if key in HARNESS.instantiated and not HARNESS.in_callback:
            raise StreamlitAPIException(
                f"st.session_state.{key} cannot be modified after the widget with key {key} is instantiated."
            )
        dict.__setitem__(self, key, value)

    def __delattr__(self, item):
        self.pop(item, None)


class _Harness:
    def __init__(self) -> None:
        self.reset_browser()
        self.secrets: dict = {}
        self.headers: dict = {}
        self.query: dict = {}

    def reset_browser(self) -> None:
        self.session_state = SessionState()
        self.label_values: dict = {}
        self.clicks: set = set()
        self.log: list = []
        self.widgets_seen: list = []
        self.instantiated: set = set()
        self.widget_keys: set = set()
        self.keys_this_run: set = set()
        self.in_callback = False
        self.figures: dict = {}

    # ------------------------------------------------------------- helpers
    def record(self, kind: str, *payload: Any) -> None:
        text = " ".join(str(p) for p in payload)
        self.log.append((kind, text))

    def messages(self, kind: str) -> list:
        return [text for k, text in self.log if k == kind]


HARNESS = _Harness()


class _Secrets(dict):
    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc


class _QueryParams:
    def get(self, name, default=None):
        return HARNESS.query.get(name, default)

    def __contains__(self, name):
        return name in HARNESS.query

    def __getitem__(self, name):
        return HARNESS.query[name]

    def to_dict(self):
        return dict(HARNESS.query)


class _Context:
    @property
    def headers(self):
        return HARNESS.headers


def __getattr__(name):  # module-level dynamic attributes
    if name == "session_state":
        return HARNESS.session_state
    if name == "secrets":
        return _Secrets(HARNESS.secrets)
    raise AttributeError(name)


query_params = _QueryParams()
context = _Context()


# --------------------------------------------------------------------------
# Caching (persists across reruns, keyed by function location)
# --------------------------------------------------------------------------
_CACHE_REGISTRY: dict = {}


def _make_cache_decorator(kind: str):
    def decorator(func=None, **_kwargs):
        def wrap(f):
            location = f"{kind}:{f.__module__}:{f.__qualname__}:{f.__code__.co_firstlineno}"
            store = _CACHE_REGISTRY.setdefault(location, {})

            @functools.wraps(f)
            def wrapper(*args, **kwargs):
                key_parts = []
                for index, arg in enumerate(args):
                    names = f.__code__.co_varnames
                    if index < len(names) and names[index].startswith("_"):
                        continue
                    key_parts.append(repr(arg))
                for name in sorted(kwargs):
                    if not name.startswith("_"):
                        key_parts.append(f"{name}={kwargs[name]!r}")
                key = hashlib.sha1("|".join(key_parts).encode()).hexdigest()
                if key in store:
                    value = store[key]
                else:
                    value = f(*args, **kwargs)
                    store[key] = value
                if kind == "data":
                    import copy
                    try:
                        import pickle
                        return pickle.loads(pickle.dumps(value))
                    except Exception:
                        return copy.deepcopy(value)
                return value

            wrapper.clear = store.clear  # type: ignore[attr-defined]
            return wrapper

        if func is not None and callable(func):
            return wrap(func)
        return wrap

    def clear_all():
        for location, store in _CACHE_REGISTRY.items():
            if location.startswith(kind + ":"):
                store.clear()

    decorator.clear = clear_all  # type: ignore[attr-defined]
    return decorator


cache_data = _make_cache_decorator("data")
cache_resource = _make_cache_decorator("resource")


def reset_all_caches():
    for store in _CACHE_REGISTRY.values():
        store.clear()


# --------------------------------------------------------------------------
# Elements
# --------------------------------------------------------------------------
class DeltaGenerator:
    def __init__(self, name: str = "main", form: str | None = None) -> None:
        self._name = name
        self._form = form

    # context manager support (columns, tabs, expander, form, sidebar ...)
    def __enter__(self):
        global _ACTIVE_FORM
        if self._form:
            _ACTIVE_FORM = self._form
        return self

    def __exit__(self, *exc):
        global _ACTIVE_FORM
        if self._form:
            _ACTIVE_FORM = None
        return False

    # ---------------------------------------------------------- display
    def markdown(self, body="", *args, **kwargs):
        HARNESS.record("markdown", str(body)[:6000])

    def write(self, *args, **kwargs):
        HARNESS.record("write", *[str(a)[:500] for a in args])

    def caption(self, body="", *args, **kwargs):
        HARNESS.record("caption", body)

    def title(self, body="", *a, **k):
        HARNESS.record("title", body)

    def header(self, body="", *a, **k):
        HARNESS.record("header", body)

    def subheader(self, body="", *a, **k):
        HARNESS.record("subheader", body)

    def text(self, body="", *a, **k):
        HARNESS.record("text", body)

    def code(self, body="", *a, **k):
        HARNESS.record("code", body)

    def error(self, body="", *a, **k):
        HARNESS.record("error", body)

    def warning(self, body="", *a, **k):
        HARNESS.record("warning", body)

    def info(self, body="", *a, **k):
        HARNESS.record("info", body)

    def success(self, body="", *a, **k):
        HARNESS.record("success", body)

    def exception(self, exc, *a, **k):
        HARNESS.record("exception", repr(exc))

    def toast(self, body="", *a, **k):
        HARNESS.record("toast", body)

    def json(self, body=None, *a, **k):
        HARNESS.record("json", body)

    def metric(self, label, value=None, *a, **k):
        HARNESS.record("metric", label, value)

    def dataframe(self, data=None, *a, **k):
        HARNESS.record("dataframe", getattr(data, "shape", ""))

    def table(self, data=None, *a, **k):
        HARNESS.record("table", getattr(data, "shape", ""))

    def plotly_chart(self, fig=None, *a, **k):
        key = k.get("key", "")
        HARNESS.record("chart", key)
        if key:
            _register_key(key)
            HARNESS.figures[key] = fig
        if k.get("on_select") not in (None, "ignore"):
            if not key:
                raise StreamlitAPIException("on_select needs a key in this harness")
            state = HARNESS.session_state
            if key not in state:
                dict.__setitem__(state, key, {"selection": {"points": [], "point_indices": [], "box": [], "lasso": []}})
            HARNESS.instantiated.add(key)
            HARNESS.widget_keys.add(key)
            return state[key]
        return None

    def image(self, *a, **k):
        HARNESS.record("image", "")

    def divider(self, *a, **k):
        pass

    def progress(self, *a, **k):
        return self

    def empty(self):
        return DeltaGenerator("empty")

    def container(self, *a, **k):
        return DeltaGenerator("container")

    def expander(self, label="", *a, **k):
        HARNESS.record("expander", label)
        return DeltaGenerator("expander")

    def popover(self, *a, **k):
        return DeltaGenerator("popover")

    def spinner(self, *a, **k):
        return DeltaGenerator("spinner")

    def columns(self, spec, *a, **k):
        count = spec if isinstance(spec, int) else len(spec)
        return [DeltaGenerator(f"col{i}") for i in range(count)]

    def tabs(self, labels, *a, **k):
        return [DeltaGenerator(f"tab:{label}") for label in labels]

    def form(self, key, *a, **k):
        return DeltaGenerator(f"form:{key}", form=key)

    # ---------------------------------------------------------- widgets
    def _value(self, label, key, default):
        HARNESS.widgets_seen.append((label, key))
        state = HARNESS.session_state
        if key is not None:
            _register_key(key)
        try:
            if key is not None and key in state:
                return state[key]
            for candidate in (key, label):
                if candidate is not None and candidate in HARNESS.label_values:
                    value = HARNESS.label_values[candidate]
                    if key is not None:
                        dict.__setitem__(state, key, value)
                    return value
            if key is not None:
                dict.__setitem__(state, key, default)
            return default
        finally:
            if key is not None:
                HARNESS.instantiated.add(key)
                HARNESS.widget_keys.add(key)

    def button(self, label, key=None, *a, disabled=False, on_click=None, args=None, kwargs=None, **k):
        if key is not None:
            _register_key(key)
        clicked = (key in HARNESS.clicks or label in HARNESS.clicks) and not disabled
        if clicked:
            HARNESS.clicks.discard(key)
            HARNESS.clicks.discard(label)
            if on_click is not None:
                # Streamlit runs the callback before the next script run.
                HARNESS.in_callback = True
                try:
                    on_click(*(args or ()), **(kwargs or {}))
                finally:
                    HARNESS.in_callback = False
                raise RerunException()
        return clicked

    def form_submit_button(self, label="Submit", *a, disabled=False, **k):
        return self.button(label, key=f"submit:{_ACTIVE_FORM}:{label}", disabled=disabled)

    def download_button(self, label, *a, **k):
        return False

    def link_button(self, *a, **k):
        return False

    def checkbox(self, label, value=False, key=None, *a, disabled=False, **k):
        return bool(self._value(label, key, value))

    def toggle(self, label, value=False, key=None, *a, **k):
        return bool(self._value(label, key, value))

    def text_input(self, label, value="", key=None, *a, **k):
        result = self._value(label, key, value)
        return "" if result is None else str(result)

    def text_area(self, label, value="", key=None, *a, **k):
        result = self._value(label, key, value)
        return "" if result is None else str(result)

    def number_input(self, label, min_value=None, max_value=None, value=0, step=None, key=None, *a, **k):
        if value == "min":
            value = min_value
        return self._value(label, key, value)

    def date_input(self, label, value=None, min_value=None, max_value=None, key=None, *a, **k):
        if value is None:
            value = _dt.date.today()
        return self._value(label, key, value)

    def time_input(self, label, value=None, key=None, *a, **k):
        return self._value(label, key, value or _dt.time(8, 0))

    def selectbox(self, label, options, index=0, format_func=str, key=None, *a, disabled=False, **k):
        options = list(options)
        if not options:
            return None
        default = options[index] if index is not None and 0 <= index < len(options) else None
        chosen = self._value(label, key, default)
        if chosen not in options:
            chosen = default
            if key is not None:
                dict.__setitem__(HARNESS.session_state, key, chosen)
        for option in options:  # exercise format_func like Streamlit does
            format_func(option)
        return chosen

    def radio(self, label, options, index=0, format_func=str, key=None, *a, **k):
        return self.selectbox(label, options, index=index, format_func=format_func, key=key)

    def multiselect(self, label, options, default=None, key=None, *a, **k):
        chosen = self._value(label, key, list(default or []))
        return [c for c in chosen if c in list(options)]

    def slider(self, label, min_value=None, max_value=None, value=None, key=None, *a, **k):
        return self._value(label, key, value)

    def file_uploader(self, label, *a, key=None, **k):
        return self._value(label, key, None)

    def data_editor(self, data, *a, key=None, **k):
        return self._value(None, key, data)


def _register_key(key):
    if key in HARNESS.keys_this_run:
        raise StreamlitAPIException(f"DuplicateWidgetID: There are multiple widgets with the same key='{key}'.")
    HARNESS.keys_this_run.add(key)


_ACTIVE_FORM: str | None = None
_main = DeltaGenerator("main")
sidebar = DeltaGenerator("sidebar")

for _name in dir(DeltaGenerator):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_main, _name)


def set_page_config(*a, **k):
    pass


def stop():
    raise StopException()


def rerun(*a, **k):
    raise RerunException()


def experimental_rerun():
    raise RerunException()


components = types.SimpleNamespace(v1=types.SimpleNamespace(html=lambda *a, **k: None))


def _column(kind):
    def make(label=None, **kwargs):
        if kind == "select" and "options" in kwargs and not isinstance(kwargs["options"], (list, tuple)):
            raise StreamlitAPIException("SelectboxColumn options must be a list")
        return {"kind": kind, "label": label, **kwargs}
    return make


column_config = types.SimpleNamespace(
    SelectboxColumn=_column("select"), NumberColumn=_column("number"), TextColumn=_column("text"),
    CheckboxColumn=_column("checkbox"), DateColumn=_column("date"),
)


# --------------------------------------------------------------------------
# Script runner
# --------------------------------------------------------------------------
_CODE_CACHE: dict = {}
LAST_GLOBALS: dict = {}


def _cleanup_widget_state():
    """Like Streamlit: state of widgets that were not rendered in a finished run is dropped."""
    for key in list(HARNESS.widget_keys - HARNESS.instantiated):
        HARNESS.session_state.pop(key, None)
        HARNESS.widget_keys.discard(key)


def run_script(path: str, max_reruns: int = 8) -> dict:
    """Execute the app like Streamlit does; follow st.rerun() automatically."""
    import traceback

    if path not in _CODE_CACHE:
        with open(path, encoding="utf-8") as handle:
            _CODE_CACHE[path] = compile(handle.read(), path, "exec")
    code = _CODE_CACHE[path]
    reruns = 0
    while True:
        HARNESS.widgets_seen = []
        HARNESS.instantiated = set()
        HARNESS.keys_this_run = set()
        namespace = {"__name__": "__main__", "__file__": path}
        LAST_GLOBALS.clear()
        try:
            exec(code, namespace)
            status = {"status": "completed", "reruns": reruns}
            _cleanup_widget_state()
        except StopException:
            status = {"status": "stopped", "reruns": reruns}
            _cleanup_widget_state()
        except RerunException:
            reruns += 1
            if reruns > max_reruns:
                LAST_GLOBALS.update(namespace)
                HARNESS.instantiated = set()
                return {"status": "rerun_loop", "reruns": reruns}
            continue
        except Exception as exc:  # an uncaught exception = red error box in Streamlit
            HARNESS.record("uncaught", f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
            status = {"status": "exception", "error": exc, "reruns": reruns}
        LAST_GLOBALS.update(namespace)
        HARNESS.instantiated = set()  # between runs the "user" may change any widget
        return status
