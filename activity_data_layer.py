from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from typing import Dict, Iterable, List, Tuple

import pandas as pd

ALL_ACTIVITY_COLUMNS = [
    "Activity_ID", "Source", "Source_ID", "Technician_ID", "Technician_Name",
    "Work_Date", "Start_Time", "End_Time", "Calculated_Duration",
    "Effective_Duration", "Process", "Task_Title", "Task_ID", "Imported_At",
]


def _clean(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def normalize_key(value) -> str:
    text = unicodedata.normalize("NFKD", _clean(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


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


def _date_text(value) -> str:
    dt = pd.to_datetime(value, dayfirst=True, errors="coerce")
    return "" if pd.isna(dt) else dt.strftime("%d.%m.%Y")


def _time_text(value) -> str:
    text = _clean(value).replace(".", ":")
    if not text:
        return ""
    parsed = pd.to_datetime(text, errors="coerce")
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
            name_to_id[normalize_key(name)] = tech_id
            words = name.split()
            if len(words) > 1:
                name_to_id[normalize_key(" ".join(reversed(words)))] = tech_id
        if username and tech_id:
            username_to_id[normalize_key(username)] = tech_id
    return {"name_to_id": name_to_id, "id_to_name": id_to_name, "username_to_id": username_to_id}


def normalize_forms_rows(forms_df: pd.DataFrame, technicians: pd.DataFrame, imported_at: str) -> Tuple[List[dict], List[str]]:
    if forms_df is None or forms_df.empty:
        return [], []
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
        return [], ["Forms missing columns: " + ", ".join(missing)]

    rows: List[dict] = []
    unmapped = set()
    for idx, row in forms_df.iterrows():
        name = _clean(row.get(technician_col, ""))
        tech_id = maps["name_to_id"].get(normalize_key(name), "") or maps["username_to_id"].get(normalize_key(name), "")
        if name and not tech_id:
            unmapped.add(name)
        work_date = _date_text(row.get(date_col, ""))
        start = _time_text(row.get(start_col, ""))
        end = _time_text(row.get(end_col, ""))
        if not all([name, work_date, start, end]):
            continue
        ts = _clean(row.get(timestamp_col, "")) if timestamp_col else ""
        source_id = stable_id("FORM", ts, name, work_date, start, end, row.get(title_col, ""), idx)
        start_dt = pd.to_datetime(f"{work_date} {start}", dayfirst=True, errors="coerce")
        end_dt = pd.to_datetime(f"{work_date} {end}", dayfirst=True, errors="coerce")
        duration = 0.0
        if pd.notna(start_dt) and pd.notna(end_dt):
            if end_dt < start_dt:
                end_dt += pd.Timedelta(days=1)
            duration = round((end_dt - start_dt).total_seconds() / 60, 2)
        rows.append({
            "Activity_ID": stable_id("ACT", source_id), "Source": "FORM", "Source_ID": source_id,
            "Technician_ID": tech_id, "Technician_Name": name, "Work_Date": work_date,
            "Start_Time": start, "End_Time": end, "Calculated_Duration": duration,
            "Effective_Duration": duration, "Process": _clean(row.get(process_col, "")),
            "Task_Title": _clean(row.get(title_col, "")), "Task_ID": "", "Imported_At": imported_at,
        })
    errors = [f"Unmapped Forms technicians: {', '.join(sorted(unmapped))}"] if unmapped else []
    return rows, errors


def normalize_app_rows(activity_df: pd.DataFrame, technicians: pd.DataFrame, imported_at: str) -> Tuple[List[dict], List[str]]:
    if activity_df is None or activity_df.empty:
        return [], []
    maps = build_technician_maps(technicians)
    rows: List[dict] = []
    for idx, row in activity_df.iterrows():
        tech_id = _clean(row.get("Assigned_Technician_ID", "")).upper()
        name = _clean(row.get("Assigned_To", ""))
        if not tech_id:
            tech_id = maps["name_to_id"].get(normalize_key(name), "")
        if not name and tech_id:
            name = maps["id_to_name"].get(tech_id, "")
        work_date = _date_text(row.get("Start_Date", ""))
        start = _time_text(row.get("Start_Time", ""))
        end = _time_text(row.get("End_Time", ""))
        if not all([name, work_date, start]):
            continue
        calc = _number(row.get("Calculated_Duration", 0))
        effective = _number(row.get("Effective_Duration", calc), calc)
        task_title = _clean(row.get("Task_Title", ""))
        task_id = _clean(row.get("Task_ID", ""))
        source_id = stable_id("APP", tech_id, name, task_id, task_title, work_date, start, end, calc, idx)
        rows.append({
            "Activity_ID": stable_id("ACT", source_id), "Source": "APP", "Source_ID": source_id,
            "Technician_ID": tech_id, "Technician_Name": name, "Work_Date": work_date,
            "Start_Time": start, "End_Time": end, "Calculated_Duration": calc,
            "Effective_Duration": effective, "Process": _clean(row.get("Process", "")),
            "Task_Title": task_title, "Task_ID": task_id, "Imported_At": imported_at,
        })
    return rows, []


def rows_to_matrix(rows: List[dict]) -> List[List[object]]:
    return [[row.get(col, "") for col in ALL_ACTIVITY_COLUMNS] for row in rows]


def all_activities_to_kpi_raw(all_df: pd.DataFrame) -> pd.DataFrame:
    """Convert ALL_ACTIVITIES into the legacy KPI input schema.

    Existing KPI calculations stay unchanged while their only data source becomes ALL_ACTIVITIES.
    """
    if all_df is None or all_df.empty:
        return pd.DataFrame(columns=[
            "Timestamp", "Tehničar/Inženjer", "Kategorija rada", "Opis aktivnosti",
            "Datum", "Vreme početka", "Vreme završetka aktivnosti",
        ])
    out = pd.DataFrame()
    out["Timestamp"] = all_df.get("Imported_At", "")
    out["Tehničar/Inženjer"] = all_df.get("Technician_Name", "")
    out["Kategorija rada"] = all_df.get("Process", "")
    out["Opis aktivnosti"] = all_df.get("Task_Title", "")
    out["Datum"] = all_df.get("Work_Date", "")
    out["Vreme početka"] = all_df.get("Start_Time", "")
    out["Vreme završetka aktivnosti"] = all_df.get("End_Time", "")
    return out
