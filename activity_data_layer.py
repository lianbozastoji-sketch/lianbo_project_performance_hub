from __future__ import annotations

import hashlib
import re
import warnings
import unicodedata
from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

ALL_ACTIVITY_COLUMNS = [
    "Activity_ID", "Source", "Source_ID", "Technician_ID", "Technician_Name",
    "Work_Date", "Start_Time", "End_Time", "Calculated_Duration",
    "Effective_Duration", "Process", "Task_Title", "Task_ID", "Imported_At",
]

_SHEETS_EPOCH = datetime(1899, 12, 30)


def _clean(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).replace("﻿", "").replace("​", "").strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _fold(text: str) -> str:
    """Lower-case ASCII fold that keeps Serbian letters recognisable (đ -> dj)."""
    text = _clean(text).replace("Đ", "Dj").replace("đ", "dj")
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()


def normalize_key(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", _fold(value))


def person_name_key(value) -> str:
    """Canonical person key, independent of case, diacritics and word order.

    "Nikolić Bojan", "Bojan Nikolic" and "BOJAN  NIKOLIĆ" give the same key, so
    an entry is never treated as missing because of how the name was typed.
    """
    tokens = re.findall(r"[a-z0-9]+", _fold(value))
    return " ".join(sorted(tokens))


def find_column(columns: Iterable[str], aliases: Iterable[str]) -> str | None:
    normalized = {normalize_key(c): c for c in columns}
    for alias in aliases:
        key = normalize_key(alias)
        if key in normalized:
            return normalized[key]
    return None


def stable_id(prefix: str, *parts) -> str:
    payload = "|".join(_clean(x) for x in parts)
    return f"{prefix}-{hashlib.sha1(payload.encode('utf-8')).hexdigest()[:20]}"


# --------------------------------------------------------------------------
# Robust, locale-independent date/time parsing
# --------------------------------------------------------------------------
_DATE_RE = re.compile(r"^(\d{1,4})\s*[./\-]\s*(\d{1,2})\s*[./\-]\s*(\d{2,4})\.?(?:\s*[T ,]\s*(.*))?$")


def _safe_date(year: int, month: int, day: int) -> Optional[date]:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _apply_clock(day_value: date, clock_text: str) -> pd.Timestamp:
    seconds = _time_seconds(clock_text) if clock_text else None
    base = datetime.combine(day_value, time(0, 0))
    if seconds is not None:
        base += timedelta(seconds=seconds)
    return pd.Timestamp(base)


def parse_date_value(value, order: Optional[str] = None):
    """Parse a date from Google Sheets / user input without swapping day and month.

    Supported: 23.10.2026, 23.10.2026., 23. 10. 2026., 23/10/2026, 23-10-2026,
    23.10.26, 2026-10-23, 2026/10/23, Google serial numbers, datetime objects,
    and the same values followed by a clock time.

    ``order`` may be "dmy" or "mdy" for slash dates whose column was detected as
    US format; dots are always European day-month-year.
    """
    if value is None:
        return pd.NaT
    if isinstance(value, pd.Timestamp):
        return value
    if isinstance(value, datetime):
        return pd.Timestamp(value)
    if isinstance(value, date):
        return pd.Timestamp(datetime.combine(value, time(0, 0)))
    if isinstance(value, bool):
        return pd.NaT
    if isinstance(value, (int, float)):
        number = float(value)
        if 20_000 <= number <= 100_000:
            return pd.Timestamp(_SHEETS_EPOCH + timedelta(days=number))
        return pd.NaT

    text = _clean(value)
    if not text:
        return pd.NaT
    numeric = text.replace(",", ".")
    if re.fullmatch(r"\d{5}(?:\.\d+)?", numeric):
        return parse_date_value(float(numeric))

    match = _DATE_RE.match(text)
    if match:
        a, b, c, clock = match.group(1), match.group(2), match.group(3), (match.group(4) or "").strip()
        separator = re.search(r"[./\-]", text).group(0)
        if len(a) == 4:  # ISO year-month-day
            parsed = _safe_date(int(a), int(b), int(c))
        else:
            year = int(c)
            if len(c) == 2:
                year += 2000
            first, second = int(a), int(b)
            if separator == "/" and order == "mdy":
                parsed = _safe_date(year, first, second) or _safe_date(year, second, first)
            else:
                parsed = _safe_date(year, second, first)
                if parsed is None and separator in "/-":
                    parsed = _safe_date(year, first, second)
        if parsed is None:
            return pd.NaT
        return _apply_clock(parsed, clock)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return pd.to_datetime(text, errors="coerce")
    except Exception:
        return pd.NaT


def detect_slash_date_order(values: Iterable) -> Optional[str]:
    """Return "mdy" when a column clearly uses US month/day/year slash dates."""
    dmy = mdy = False
    for value in values:
        match = re.match(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2,4})", _clean(value))
        if not match:
            continue
        first, second = int(match.group(1)), int(match.group(2))
        if first > 12:
            dmy = True
        elif second > 12:
            mdy = True
    if mdy and not dmy:
        return "mdy"
    return None


def _time_seconds(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.hour * 3600 + value.minute * 60 + value.second
    if isinstance(value, time):
        return value.hour * 3600 + value.minute * 60 + value.second
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        fraction = float(value) % 1
        return int(round(fraction * 86400)) % 86400
    text = _clean(value).lower()
    if not text:
        return None
    date_match = _DATE_RE.match(text)
    if date_match and (len(date_match.group(3)) == 4 or len(date_match.group(1)) == 4):
        # "23.10.2026 08:30:00" -> use only the clock part, never "23.10" as 23:10.
        text = (date_match.group(4) or "").strip()
        if not text:
            return None
    if re.fullmatch(r"0?\.\d+", text.replace(",", ".")):
        return int(round(float(text.replace(",", ".")) * 86400)) % 86400
    match = re.search(r"(?<!\d)(\d{1,2})\s*[:.h]\s*(\d{2})(?:\s*[:.]\s*(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?", text)
    if match:
        hour, minute, second = int(match.group(1)), int(match.group(2)), int(match.group(3) or 0)
        suffix = (match.group(4) or "").replace(".", "")
    else:
        match = re.fullmatch(r"(\d{1,2})(\d{2})?\s*h?\s*(am|pm)?", text)
        if not match:
            return None
        hour, minute, second = int(match.group(1)), int(match.group(2) or 0), 0
        suffix = match.group(3) or ""
    if suffix == "pm" and hour < 12:
        hour += 12
    if suffix == "am" and hour == 12:
        hour = 0
    if hour == 24 and minute == 0:
        hour = 0
    if not (0 <= hour < 24 and 0 <= minute < 60 and 0 <= second < 60):
        return None
    return hour * 3600 + minute * 60 + second


def parse_time_value(value) -> Optional[time]:
    """Parse 8:30, 08:30:00, 8.30, 8h30, 830, 8:30 PM or a Sheets day fraction."""
    seconds = _time_seconds(value)
    if seconds is None:
        return None
    return time(seconds // 3600, (seconds % 3600) // 60, seconds % 60)


def _date_text(value, order: Optional[str] = None) -> str:
    dt = parse_date_value(value, order)
    return "" if pd.isna(dt) else dt.strftime("%d.%m.%Y")


def _time_text(value) -> str:
    parsed = parse_time_value(value)
    if parsed is None:
        return ""
    return parsed.strftime("%H:%M")


# Legacy parsers are used ONLY to rebuild the identity (Source_ID) of rows that
# were imported by earlier versions, so already imported activities never
# look new and are never duplicated.
def _legacy_parse_mixed_datetime(value):
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value)
    text = _clean(value)
    if not text:
        return pd.NaT
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return _legacy_parse_text(text)


def _legacy_parse_text(text):
    try:
        if re.match(r"^\d{4}-\d{1,2}-\d{1,2}(?:[T\s].*)?$", text):
            return pd.to_datetime(text, yearfirst=True, dayfirst=False, errors="coerce")
        if re.match(r"^\d{1,2}[./]\d{1,2}[./]\d{4}(?:[T\s].*)?$", text):
            return pd.to_datetime(text, yearfirst=False, dayfirst=True, errors="coerce")
        return pd.to_datetime(text, errors="coerce")
    except Exception:
        return pd.NaT


def _legacy_date_text(value) -> str:
    dt = _legacy_parse_mixed_datetime(value)
    return "" if pd.isna(dt) else dt.strftime("%d.%m.%Y")


def _legacy_time_text(value) -> str:
    text = _clean(value).replace(".", ":")
    if not text:
        return ""
    try:
        parsed = pd.to_datetime(text, errors="coerce")
    except Exception:
        parsed = pd.NaT
    if pd.isna(parsed):
        return text
    return parsed.strftime("%H:%M")


def _number(value, default=0.0) -> float:
    text = _clean(value).replace(",", ".")
    try:
        return round(float(text), 2)
    except Exception:
        return float(default)


def build_technician_maps(technicians: pd.DataFrame) -> Dict[str, Dict[str, str]]:
    name_to_id: Dict[str, str] = {}
    id_to_name: Dict[str, str] = {}
    username_to_id: Dict[str, str] = {}
    if technicians is None or technicians.empty:
        return {"name_to_id": name_to_id, "id_to_name": id_to_name, "username_to_id": username_to_id}
    for _, row in technicians.iterrows():
        tech_id = _clean(row.get("Technician_ID", "")).upper()
        name = _clean(row.get("Technician_Name", ""))
        username = _clean(row.get("Username", ""))
        if tech_id:
            id_to_name[tech_id] = name
        if name and tech_id:
            name_to_id[person_name_key(name)] = tech_id
        if username and tech_id:
            username_to_id[person_name_key(username)] = tech_id
    return {"name_to_id": name_to_id, "id_to_name": id_to_name, "username_to_id": username_to_id}


def _lookup_technician_id(maps: Dict[str, Dict[str, str]], name: str) -> str:
    key = person_name_key(name)
    return maps["name_to_id"].get(key, "") or maps["username_to_id"].get(key, "")


def normalize_forms_rows(forms_df: pd.DataFrame, technicians: pd.DataFrame, imported_at: str) -> Tuple[List[dict], List[str]]:
    rows, errors, _ = normalize_forms_rows_detailed(forms_df, technicians, imported_at)
    return rows, errors


def normalize_forms_rows_detailed(forms_df: pd.DataFrame, technicians: pd.DataFrame, imported_at: str):
    """Return (rows, errors, info). ``info`` reports skipped rows and the date order."""
    info = {"source_rows": 0, "skipped_rows": 0, "skipped_examples": [], "date_order": "dmy"}
    if forms_df is None or forms_df.empty:
        return [], [], info
    info["source_rows"] = int(len(forms_df))
    maps = build_technician_maps(technicians)
    cols = forms_df.columns
    timestamp_col = find_column(cols, ["Timestamp", "Vremenska oznaka"])
    technician_col = find_column(cols, ["Tehničar/Inženjer", "Tehnicar/Inzenjer", "Tehničar", "Technician"])
    process_col = find_column(cols, ["Kategorija rada", "Process", "Proces"])
    title_col = find_column(cols, ["Opis aktivnosti", "Task Title", "Aktivnost"])
    date_col = find_column(cols, ["Datum", "Date", "Work Date"])
    start_col = find_column(cols, ["Vreme početka", "Start Time", "Vreme pocetka"])
    end_col = find_column(cols, ["Vreme završetka aktivnosti", "End Time", "Vreme zavrsetka aktivnosti"])
    missing = [name for name, col in [
        ("Technician", technician_col), ("Process", process_col), ("Task_Title", title_col),
        ("Work_Date", date_col), ("Start_Time", start_col), ("End_Time", end_col),
    ] if col is None]
    if missing:
        return [], ["Forms missing columns: " + ", ".join(missing)], info

    order_sample = list(forms_df[date_col].tolist())
    if timestamp_col is not None:
        order_sample += list(forms_df[timestamp_col].tolist())
    date_order = detect_slash_date_order(order_sample)
    info["date_order"] = date_order or "dmy"

    rows: List[dict] = []
    unmapped = set()
    for position, (_, row) in enumerate(forms_df.iterrows(), start=2):
        name = _clean(row.get(technician_col, ""))
        tech_id = _lookup_technician_id(maps, name)
        if name and not tech_id:
            unmapped.add(name)
        raw_date = row.get(date_col, "")
        raw_start = row.get(start_col, "")
        raw_end = row.get(end_col, "")
        work_date = _date_text(raw_date, date_order)
        start = _time_text(raw_start)
        end = _time_text(raw_end)
        if not all([name, work_date, start, end]):
            info["skipped_rows"] += 1
            if len(info["skipped_examples"]) < 10:
                info["skipped_examples"].append(
                    f"row {position}: name={name!r} date={_clean(raw_date)!r} start={_clean(raw_start)!r} end={_clean(raw_end)!r}"
                )
            continue
        ts = _clean(row.get(timestamp_col, "")) if timestamp_col else ""
        # Identity uses the legacy text representation, so rows imported by an
        # earlier version are recognised and never duplicated.
        source_id = stable_id(
            "FORM", ts, name, _legacy_date_text(raw_date), _legacy_time_text(raw_start),
            _legacy_time_text(raw_end), row.get(title_col, ""),
        )
        start_t = parse_time_value(raw_start)
        end_t = parse_time_value(raw_end)
        start_s = start_t.hour * 3600 + start_t.minute * 60
        end_s = end_t.hour * 3600 + end_t.minute * 60
        if end_s < start_s:
            end_s += 86400
        duration = round((end_s - start_s) / 60, 2)
        rows.append({
            "Activity_ID": stable_id("ACT", source_id), "Source": "FORM", "Source_ID": source_id,
            "Technician_ID": tech_id, "Technician_Name": name, "Work_Date": work_date,
            "Start_Time": start, "End_Time": end, "Calculated_Duration": duration,
            "Effective_Duration": duration, "Process": _clean(row.get(process_col, "")),
            "Task_Title": _clean(row.get(title_col, "")), "Task_ID": "", "Imported_At": imported_at,
        })
    errors = [f"Unmapped Forms technicians: {', '.join(sorted(unmapped))}"] if unmapped else []
    return rows, errors, info


def normalize_app_rows(activity_df: pd.DataFrame, technicians: pd.DataFrame, imported_at: str) -> Tuple[List[dict], List[str]]:
    if activity_df is None or activity_df.empty:
        return [], []
    maps = build_technician_maps(technicians)
    rows: List[dict] = []
    skipped = 0
    for _, row in activity_df.iterrows():
        tech_id = _clean(row.get("Assigned_Technician_ID", "")).upper()
        name = _clean(row.get("Assigned_To", ""))
        if not tech_id:
            tech_id = _lookup_technician_id(maps, name)
        if not name and tech_id:
            name = maps["id_to_name"].get(tech_id, "")
        work_date = _date_text(row.get("Start_Date", ""))
        start = _time_text(row.get("Start_Time", ""))
        end = _time_text(row.get("End_Time", ""))
        if not all([name, work_date, start]):
            skipped += 1
            continue
        calc = _number(row.get("Calculated_Duration", 0))
        effective = _number(row.get("Effective_Duration", calc), calc)
        task_title = _clean(row.get("Task_Title", ""))
        task_id = _clean(row.get("Task_ID", ""))
        activity_id = _clean(row.get("Activity_ID", ""))
        source_id = (
            stable_id("APP", activity_id)
            if activity_id
            else stable_id("APP", tech_id, name, task_id, task_title, work_date, start, end, calc)
        )
        rows.append({
            "Activity_ID": activity_id or stable_id("ACT", source_id), "Source": "APP", "Source_ID": source_id,
            "Technician_ID": tech_id, "Technician_Name": name, "Work_Date": work_date,
            "Start_Time": start, "End_Time": end, "Calculated_Duration": calc,
            "Effective_Duration": effective, "Process": _clean(row.get("Process", "")),
            "Task_Title": task_title, "Task_ID": task_id, "Imported_At": imported_at,
        })
    errors = [f"Work Ticket activities skipped (missing name/date/start): {skipped}"] if skipped else []
    return rows, errors


def rows_to_matrix(rows: List[dict]) -> List[List[object]]:
    return [[row.get(col, "") for col in ALL_ACTIVITY_COLUMNS] for row in rows]


def all_activities_to_kpi_raw(all_df: pd.DataFrame, technicians: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Convert ALL_ACTIVITIES into the legacy KPI input schema.

    When the technician master is supplied, every row with a known
    Technician_ID is shown under the official master name. A person who typed
    the name differently in Google Forms is therefore not split into two
    people and their entries are not "missing" from evaluation.
    """
    columns = [
        "Timestamp", "Tehničar/Inženjer", "Kategorija rada", "Opis aktivnosti",
        "Datum", "Vreme početka", "Vreme završetka aktivnosti",
    ]
    if all_df is None or all_df.empty:
        return pd.DataFrame(columns=columns)
    names = all_df.get("Technician_Name", pd.Series("", index=all_df.index)).astype(str)
    if technicians is not None and not technicians.empty:
        maps = build_technician_maps(technicians)
        ids = all_df.get("Technician_ID", pd.Series("", index=all_df.index)).astype(str).str.strip().str.upper()
        by_id = ids.map(maps["id_to_name"]).fillna("")
        by_name = names.map(lambda n: maps["id_to_name"].get(_lookup_technician_id(maps, n), ""))
        canonical = by_id.where(by_id.str.strip() != "", by_name)
        names = canonical.where(canonical.str.strip() != "", names)
    out = pd.DataFrame(index=all_df.index)
    out["Timestamp"] = all_df.get("Imported_At", "")
    out["Tehničar/Inženjer"] = names.str.strip()
    out["Kategorija rada"] = all_df.get("Process", "")
    out["Opis aktivnosti"] = all_df.get("Task_Title", "")
    out["Datum"] = all_df.get("Work_Date", "")
    out["Vreme početka"] = all_df.get("Start_Time", "")
    out["Vreme završetka aktivnosti"] = all_df.get("End_Time", "")
    return out[columns]
