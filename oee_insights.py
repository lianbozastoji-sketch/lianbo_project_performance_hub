"""OEE insights for Lianbo Project Performance Hub (v11).

Pure pandas logic, no Streamlit and no Google calls, so every number can be
tested directly:

* downtime causes  - catalogue, events, allocation check, Pareto
* manager view     - data coverage, comparison with the previous period,
                     lost pieces / hours / value, one-sentence summary
* IWON (private)   - plan and forecast for any week from a rolling baseline,
                     per-cause targets that stay realistic, plan vs actual

The OEE aggregation itself lives in the main app (``aggregate_oee``); functions
that need it receive it as the ``aggregate`` argument.
"""
from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime, time, timedelta

import pandas as pd

# ---------------------------------------------------------------------------
# Downtime causes
# ---------------------------------------------------------------------------
LOSS_DOWNTIME = "Zastoj"
LOSS_ORGANISATIONAL = "Organizacioni gubitak"
LOSS_TYPES = [LOSS_DOWNTIME, LOSS_ORGANISATIONAL]
LEVER_FREQUENCY = "ređe"
LEVER_DURATION = "kraće"
UNCAUSED = "Bez uzroka (stari unos)"

DOWNTIME_CAUSE_COLUMNS = ["Loss_Type", "Cause", "Lever", "Active", "Sort"]
DEFAULT_CAUSES = [
    (LOSS_DOWNTIME, "Mašinski kvar", LEVER_FREQUENCY),
    (LOSS_DOWNTIME, "Električni kvar", LEVER_FREQUENCY),
    (LOSS_DOWNTIME, "Pneumatika / hidraulika", LEVER_FREQUENCY),
    (LOSS_DOWNTIME, "Softver / PLC", LEVER_FREQUENCY),
    (LOSS_DOWNTIME, "Alat / pribor", LEVER_DURATION),
    (LOSS_DOWNTIME, "Zamena senzora / dela", LEVER_DURATION),
    (LOSS_DOWNTIME, "Podešavanje / promena tipa", LEVER_DURATION),
    (LOSS_DOWNTIME, "Problem kvaliteta", LEVER_FREQUENCY),
    (LOSS_DOWNTIME, "Ostalo (zastoj)", LEVER_DURATION),
    (LOSS_ORGANISATIONAL, "Čekanje materijala", LEVER_FREQUENCY),
    (LOSS_ORGANISATIONAL, "Nema operatera", LEVER_FREQUENCY),
    (LOSS_ORGANISATIONAL, "Sastanak / obuka", LEVER_DURATION),
    (LOSS_ORGANISATIONAL, "Planirano održavanje", LEVER_DURATION),
    (LOSS_ORGANISATIONAL, "Nema naloga", LEVER_FREQUENCY),
    (LOSS_ORGANISATIONAL, "Ostalo (organizacija)", LEVER_DURATION),
]

DOWNTIME_EVENT_COLUMNS = [
    "Event_ID", "Datum", "Shift", "Project", "Process", "Machine", "Loss_Type", "Cause", "Minutes",
    "Start_Time", "End_Time", "Status", "Note", "Source", "Entered_By", "Created_At", "Updated_At",
]
SOURCE_PHONE = "PRIJAVA"
SOURCE_OEE = "OEE_UNOS"
SOURCE_FORM = "FORMA"
STATUS_OPEN = "U TOKU"
STATUS_DONE = "ZAVRŠEN"


def default_causes_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [{"Loss_Type": t, "Cause": c, "Lever": l, "Active": "YES", "Sort": i + 1} for i, (t, c, l) in enumerate(DEFAULT_CAUSES)],
        columns=DOWNTIME_CAUSE_COLUMNS,
    )


def _fold(text) -> str:
    text = unicodedata.normalize("NFKD", str(text or "")).replace("đ", "dj").replace("Đ", "Dj")
    return re.sub(r"[^a-z0-9]+", " ", "".join(ch for ch in text if not unicodedata.combining(ch)).lower()).strip()


def clean_causes(causes_df: pd.DataFrame | None) -> pd.DataFrame:
    """Active causes from the catalogue sheet; the default list when empty."""
    if causes_df is None or causes_df.empty or "Cause" not in causes_df.columns:
        return default_causes_frame()
    df = causes_df.copy()
    for col in DOWNTIME_CAUSE_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df["Cause"] = df["Cause"].astype(str).str.strip()
    df["Loss_Type"] = df["Loss_Type"].astype(str).str.strip()
    df.loc[~df["Loss_Type"].isin(LOSS_TYPES), "Loss_Type"] = LOSS_DOWNTIME
    df["Lever"] = df["Lever"].astype(str).str.strip().str.lower()
    df.loc[~df["Lever"].isin([LEVER_FREQUENCY, LEVER_DURATION]), "Lever"] = LEVER_DURATION
    active = df["Active"].astype(str).str.strip().str.upper()
    df = df[(df["Cause"] != "") & ~active.isin(["NO", "NE", "FALSE", "0"])]
    df["Sort"] = pd.to_numeric(df["Sort"], errors="coerce").fillna(999)
    df = df.drop_duplicates(subset=["Loss_Type", "Cause"]).sort_values(["Loss_Type", "Sort", "Cause"])
    return df[DOWNTIME_CAUSE_COLUMNS].reset_index(drop=True) if not df.empty else default_causes_frame()


def cause_lever_map(causes_df: pd.DataFrame) -> dict:
    return {(row.Loss_Type, row.Cause): row.Lever for row in clean_causes(causes_df).itertuples(index=False)}


def shift_for_time(value) -> str:
    """06-14 = 1st, 14-22 = 2nd, 22-06 = 3rd (night shift belongs to the start date)."""
    if isinstance(value, datetime):
        value = value.time()
    if not isinstance(value, time):
        text = str(value or "").strip()
        match = re.match(r"^(\d{1,2})[:.](\d{2})", text)
        if not match:
            return ""
        value = time(int(match.group(1)) % 24, int(match.group(2)) % 60)
    hour = value.hour
    if 6 <= hour < 14:
        return "1st"
    if 14 <= hour < 22:
        return "2nd"
    return "3rd"


def shift_code(shift_label) -> str:
    """'1st shift (06:00-14:00)' -> '1st'; 'All shifts' -> 'ALL'."""
    text = str(shift_label or "").strip().lower()
    for code in ("1st", "2nd", "3rd"):
        if text.startswith(code):
            return code
    return "ALL" if text.startswith("all") else text


def _parse_date(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return pd.NaT
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return pd.Timestamp(value).normalize()
    text = str(value).strip().rstrip(".")
    if not text:
        return pd.NaT
    match = re.match(r"^(\d{1,2})[./\- ]+(\d{1,2})[./\- ]+(\d{2,4})", text)
    if match:
        day, month, year = (int(g) for g in match.groups())
        year = year + 2000 if year < 100 else year
        try:
            return pd.Timestamp(year, month, day)
        except ValueError:
            return pd.NaT
    try:
        return pd.Timestamp(text).normalize()
    except Exception:
        return pd.NaT


def normalize_events(events_df: pd.DataFrame | None) -> pd.DataFrame:
    """Clean DOWNTIME_EVENTS rows: real dates, numeric minutes, known loss types."""
    if events_df is None or events_df.empty:
        return pd.DataFrame(columns=DOWNTIME_EVENT_COLUMNS)
    df = events_df.copy()
    for col in DOWNTIME_EVENT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df["Datum"] = df["Datum"].map(_parse_date)
    df = df.dropna(subset=["Datum"])
    df["Minutes"] = pd.to_numeric(
        df["Minutes"].astype(str).str.replace(",", ".", regex=False).str.strip(), errors="coerce"
    ).fillna(0.0)
    for col in ("Project", "Process", "Machine", "Cause", "Loss_Type", "Shift", "Source", "Status"):
        df[col] = df[col].astype(str).str.strip()
    df.loc[~df["Loss_Type"].isin(LOSS_TYPES), "Loss_Type"] = LOSS_DOWNTIME
    df.loc[df["Cause"] == "", "Cause"] = "Ostalo (zastoj)"
    df["Shift"] = df["Shift"].map(shift_code)
    return df.reset_index(drop=True)


def match_cause(text, causes_df: pd.DataFrame | None = None) -> tuple[str, str]:
    """Map a free-text reason (Google Form) to the catalogue; unknown -> Ostalo."""
    folded = _fold(text)
    causes = clean_causes(causes_df)
    for row in causes.itertuples(index=False):
        if _fold(row.Cause) and _fold(row.Cause) == folded:
            return row.Loss_Type, row.Cause
    keywords = [
        (("senzor", "sensor"), "Zamena senzora / dela"),
        (("elektr", "kabl", "osigur", "napaj"), "Električni kvar"),
        (("pneumat", "hidraul", "vazduh", "cilind"), "Pneumatika / hidraulika"),
        (("plc", "softver", "program", "robot"), "Softver / PLC"),
        (("alat", "pribor", "gnezd"), "Alat / pribor"),
        (("podes", "promena tipa", "tip ", "changeover"), "Podešavanje / promena tipa"),
        (("materijal", "komponent", "logist"), "Čekanje materijala"),
        (("operater", "radnik", "ljudi"), "Nema operatera"),
        (("kvalitet", "nok", "skart", "škart"), "Problem kvaliteta"),
        (("mehan", "lezaj", "ležaj", "motor", "remen", "kvar"), "Mašinski kvar"),
    ]
    known = {row.Cause: row.Loss_Type for row in causes.itertuples(index=False)}
    for words, cause in keywords:
        if any(_fold(word) in folded for word in words) and cause in known:
            return known[cause], cause
    return LOSS_DOWNTIME, "Ostalo (zastoj)" if "Ostalo (zastoj)" in known else next(iter(known), "Ostalo (zastoj)")


def _minutes_between(start_text, end_text) -> float:
    def to_minutes(text):
        match = re.match(r"^\s*(\d{1,2})[:.](\d{2})", str(text or ""))
        return int(match.group(1)) * 60 + int(match.group(2)) if match else None

    start, end = to_minutes(start_text), to_minutes(end_text)
    if start is None or end is None:
        return 0.0
    if end < start:
        end += 24 * 60
    return float(end - start)


def form_rows_to_events(form_df: pd.DataFrame | None, master_df: pd.DataFrame | None,
                        causes_df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Rows of the technicians' Google Form for downtime -> downtime events.

    The form has free text for the reason and the place; the machine is matched
    against MASTER_DATA (Project + Machine) to find its process.
    """
    if form_df is None or form_df.empty:
        return pd.DataFrame(columns=DOWNTIME_EVENT_COLUMNS)

    def find(candidates):
        folded = {_fold(c): c for c in form_df.columns}
        for name in candidates:
            if _fold(name) in folded:
                return folded[_fold(name)]
        for name in candidates:
            for key, original in folded.items():
                if _fold(name) and _fold(name) in key:
                    return original
        return None

    col_date = find(["DATUM PROBLEMA", "Datum"])
    col_start = find(["POČETAK ZASTOJA", "Pocetak"])
    col_end = find(["ZAVRŠETAK ZASTOJA", "Zavrsetak"])
    col_minutes = find(["VREME ZASTOJA", "Trajanje"])
    col_cause = find(["UZROK ZASTOJA", "Uzrok"])
    col_place = find(["MESTO ZASTOJA", "Mašina", "Masina"])
    col_project = find(["Projekat", "Project"])
    col_name = find(["IME", "Tehničar", "Ime"])
    col_ts = find(["Timestamp"])
    if col_date is None or col_place is None:
        return pd.DataFrame(columns=DOWNTIME_EVENT_COLUMNS)

    lookup = {}
    if master_df is not None and not master_df.empty:
        for row in master_df.itertuples(index=False):
            project = str(getattr(row, "Project", "")).strip()
            machine = str(getattr(row, "Machine", "")).strip()
            lookup.setdefault((_fold(project), _fold(machine)), (project, str(getattr(row, "Process", "")).strip(), machine))
            lookup.setdefault(("", _fold(machine)), (project, str(getattr(row, "Process", "")).strip(), machine))

    events = []
    for index, row in form_df.reset_index(drop=True).iterrows():
        day = _parse_date(row.get(col_date))
        if pd.isna(day):
            continue
        start_text = str(row.get(col_start, "") or "")[:5] if col_start else ""
        end_text = str(row.get(col_end, "") or "")[:5] if col_end else ""
        minutes = _minutes_between(start_text, end_text)
        if minutes <= 0 and col_minutes:
            raw = str(row.get(col_minutes, "") or "")
            match = re.match(r"^\s*(\d+):(\d{2})(?::(\d{2}))?", raw)
            if match:
                minutes = int(match.group(1)) * 60 + int(match.group(2))
            else:
                minutes = float(pd.to_numeric(raw.replace(",", "."), errors="coerce") or 0)
        if minutes <= 0:
            continue
        project_text = str(row.get(col_project, "") or "").strip() if col_project else ""
        place = str(row.get(col_place, "") or "").strip()
        found = lookup.get((_fold(project_text), _fold(place))) or lookup.get(("", _fold(place)))
        if not found:
            continue  # place is not a machine of MASTER_DATA (e.g. a whole line); skipped
        loss_type, cause = match_cause(row.get(col_cause, "") if col_cause else "", causes_df)
        identity = f"{day:%Y%m%d}|{found[2]}|{start_text}|{end_text}|{row.get(col_ts, index) if col_ts else index}"
        events.append({
            "Event_ID": "FORM-" + re.sub(r"[^0-9A-Za-z]+", "", identity)[:40],
            "Datum": day,
            "Shift": shift_for_time(start_text),
            "Project": found[0], "Process": found[1], "Machine": found[2],
            "Loss_Type": loss_type, "Cause": cause, "Minutes": float(minutes),
            "Start_Time": start_text, "End_Time": end_text, "Status": STATUS_DONE,
            "Note": str(row.get(col_cause, "") or "").strip() if col_cause else "",
            "Source": SOURCE_FORM,
            "Entered_By": str(row.get(col_name, "") or "").strip() if col_name else "",
            "Created_At": "", "Updated_At": "",
        })
    return pd.DataFrame(events, columns=DOWNTIME_EVENT_COLUMNS)


def events_for_shift(events: pd.DataFrame, day, project, process, machine, shift_label) -> pd.DataFrame:
    """Logged events (phone + form) that belong to one OEE input (date/machine/shift)."""
    if events is None or events.empty:
        return pd.DataFrame(columns=DOWNTIME_EVENT_COLUMNS)
    day = _parse_date(day)
    df = events[
        (events["Datum"] == day)
        & (events["Project"].astype(str).str.strip() == str(project).strip())
        & (events["Process"].astype(str).str.strip() == str(process).strip())
        & (events["Machine"].astype(str).str.strip() == str(machine).strip())
        & (events["Source"] != SOURCE_OEE)
        & (events["Status"] != STATUS_OPEN)
    ]
    code = shift_code(shift_label)
    if code in ("1st", "2nd", "3rd"):
        df = df[df["Shift"] == code]
    return df


def check_allocation(down_time, org_loss, logged: pd.DataFrame, rows: pd.DataFrame | None,
                     causes_df: pd.DataFrame | None = None) -> dict:
    """Do the causes cover exactly the entered downtime and organisational loss?

    rows: the user's allocation table with columns Uzrok (cause) and Minuta.
    Returns sums, the cleaned allocation rows and a list of errors (empty = OK).
    """
    known = {row.Cause: row.Loss_Type for row in clean_causes(causes_df).itertuples(index=False)}
    alloc = []
    errors = []
    if rows is not None and not rows.empty:
        for row in rows.to_dict("records"):
            cause = str(row.get("Uzrok", "") or "").strip()
            minutes = pd.to_numeric(str(row.get("Minuta", "") or "").replace(",", "."), errors="coerce")
            if not cause and (pd.isna(minutes) or minutes == 0):
                continue
            if not cause:
                errors.append(f"Izaberi razlog za red sa {_num(minutes)} min.")
                continue
            if cause not in known:
                errors.append(f"Nepoznat uzrok: '{cause or '—'}'. Izaberi iz liste.")
                continue
            if pd.isna(minutes) or minutes <= 0:
                errors.append(f"Uzrok '{cause}' nema minute.")
                continue
            alloc.append({"Loss_Type": known[cause], "Cause": cause, "Minutes": float(minutes)})
    logged = logged if logged is not None else pd.DataFrame(columns=DOWNTIME_EVENT_COLUMNS)
    logged_down = float(logged.loc[logged["Loss_Type"] == LOSS_DOWNTIME, "Minutes"].sum()) if not logged.empty else 0.0
    logged_org = float(logged.loc[logged["Loss_Type"] == LOSS_ORGANISATIONAL, "Minutes"].sum()) if not logged.empty else 0.0
    alloc_down = sum(a["Minutes"] for a in alloc if a["Loss_Type"] == LOSS_DOWNTIME)
    alloc_org = sum(a["Minutes"] for a in alloc if a["Loss_Type"] == LOSS_ORGANISATIONAL)
    down_sum, org_sum = logged_down + alloc_down, logged_org + alloc_org
    down_time, org_loss = float(down_time or 0), float(org_loss or 0)
    if abs(down_sum - down_time) > 0.01:
        if down_sum < down_time:
            errors.append(f"Zastoj: uzrok nedostaje za {_num(down_time - down_sum)} min (upisano {_num(down_time)}, raspoređeno {_num(down_sum)}).")
        else:
            errors.append(f"Zastoj: uzroci imaju {_num(down_sum - down_time)} min više nego upisano vreme zastoja ({_num(down_time)}).")
    if abs(org_sum - org_loss) > 0.01:
        if org_sum < org_loss:
            errors.append(f"Org. gubici: uzrok nedostaje za {_num(org_loss - org_sum)} min (upisano {_num(org_loss)}, raspoređeno {_num(org_sum)}).")
        else:
            errors.append(f"Org. gubici: uzroci imaju {_num(org_sum - org_loss)} min više nego upisano ({_num(org_loss)}).")
    return {
        "errors": errors, "allocation": alloc,
        "logged_down": logged_down, "logged_org": logged_org,
        "down_sum": down_sum, "org_sum": org_sum,
    }


def _num(value) -> str:
    value = float(value or 0)
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}".replace(",", ".")
    return f"{value:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def loss_pareto(events: pd.DataFrame, oee_rows: pd.DataFrame, include_org=True) -> pd.DataFrame:
    """Minutes per cause for the rows of a period (plus 'without cause' remainder).

    Events are limited to the machines/dates present in the OEE rows, so the
    Pareto always describes the same production the OEE number describes.
    """
    columns = ["Cause", "Loss_Type", "Minutes", "Events", "Share_%", "Cum_%"]
    if oee_rows is None or oee_rows.empty:
        return pd.DataFrame(columns=columns)
    rows = oee_rows.copy()
    rows["_d"] = pd.to_datetime(rows["Datum"], errors="coerce").dt.normalize()
    keys = set(zip(rows["_d"], rows["Machine"].astype(str).str.strip(), rows["Process"].astype(str).str.strip()))
    down_total = float(pd.to_numeric(rows["Down time"], errors="coerce").fillna(0).sum())
    org_total = float(pd.to_numeric(rows["Organisational loss"], errors="coerce").fillna(0).sum()) if include_org else 0.0

    ev = events if events is not None else pd.DataFrame(columns=DOWNTIME_EVENT_COLUMNS)
    if not ev.empty:
        mask = [
            (d, str(m).strip(), str(p).strip()) in keys
            for d, m, p in zip(ev["Datum"], ev["Machine"], ev["Process"])
        ]
        ev = ev[pd.Series(mask, index=ev.index)] if len(ev) else ev
        ev = ev[ev["Status"] != STATUS_OPEN]
        if not include_org:
            ev = ev[ev["Loss_Type"] == LOSS_DOWNTIME]
    grouped = (
        ev.groupby(["Cause", "Loss_Type"], dropna=False)["Minutes"].agg(["sum", "count"]).reset_index()
        if not ev.empty else pd.DataFrame(columns=["Cause", "Loss_Type", "sum", "count"])
    )
    grouped = grouped.rename(columns={"sum": "Minutes", "count": "Events"})
    caused_down = float(grouped.loc[grouped["Loss_Type"] == LOSS_DOWNTIME, "Minutes"].sum()) if not grouped.empty else 0.0
    caused_org = float(grouped.loc[grouped["Loss_Type"] == LOSS_ORGANISATIONAL, "Minutes"].sum()) if not grouped.empty else 0.0
    remainder = max(down_total - caused_down, 0.0) + max(org_total - caused_org, 0.0)
    if remainder > 0.01:
        grouped = pd.concat([grouped, pd.DataFrame([{"Cause": UNCAUSED, "Loss_Type": "", "Minutes": remainder, "Events": 0}])],
                            ignore_index=True)
    if grouped.empty:
        return pd.DataFrame(columns=columns)
    grouped["Minutes"] = pd.to_numeric(grouped["Minutes"], errors="coerce").fillna(0.0)
    grouped = grouped[grouped["Minutes"] > 0].sort_values("Minutes", ascending=False).reset_index(drop=True)
    total = float(grouped["Minutes"].sum())
    grouped["Share_%"] = grouped["Minutes"] / total * 100 if total else 0.0
    grouped["Cum_%"] = grouped["Share_%"].cumsum()
    return grouped[columns]


# ---------------------------------------------------------------------------
# Manager view
# ---------------------------------------------------------------------------
def workdays(start, end, until=None) -> list:
    """Mon-Fri dates between start and end (inclusive), never after `until`."""
    start, end = _parse_date(start), _parse_date(end)
    if until is not None:
        end = min(end, _parse_date(until))
    if pd.isna(start) or pd.isna(end) or end < start:
        return []
    return [d for d in pd.date_range(start, end, freq="D") if d.weekday() < 5]


def coverage(rows: pd.DataFrame, period_start, period_end, machines, today=None) -> dict:
    """How complete are the entries of a period (shown next to every number)."""
    today = _parse_date(today or date.today())
    expected_days = workdays(period_start, period_end, until=today)
    entered_days = set()
    machine_days = set()
    last_day = None
    if rows is not None and not rows.empty:
        dates = pd.to_datetime(rows["Datum"], errors="coerce").dt.normalize()
        entered_days = {d for d in dates.dropna().unique()}
        machine_days = {(d, str(m).strip()) for d, m in zip(dates, rows["Machine"]) if pd.notna(d)}
        last_day = max(entered_days) if entered_days else None
    entered_days = {pd.Timestamp(d) for d in entered_days}
    expected_set = set(expected_days)
    machines = [str(m).strip() for m in (machines or []) if str(m).strip()]
    expected_machine_days = len(expected_set) * max(len(machines), 1)
    filled_machine_days = len({(d, m) for d, m in machine_days if d in expected_set and (not machines or m in machines)})
    missing = sorted(expected_set - entered_days)
    return {
        "days_expected": len(expected_set),
        "days_entered": len(expected_set & entered_days),
        "machine_days_expected": expected_machine_days,
        "machine_days_entered": filled_machine_days,
        "missing_days": missing,
        "last_day": last_day,
        "complete": bool(expected_set) and not missing and filled_machine_days >= expected_machine_days,
        "share": (filled_machine_days / expected_machine_days * 100) if expected_machine_days else 0.0,
    }


def lost_summary(agg_row, price_per_piece=None) -> dict:
    """Pieces below target, lost hours and their value for one aggregated row."""
    def value(name):
        try:
            return float(agg_row.get(name, 0) or 0)
        except Exception:
            return 0.0

    target, ok, total = value("Target_pcs"), value("OK_pcs"), value("Total_Pcs")
    down, org = value("Down_Time"), value("Organisational_Loss")
    lost_pieces = max(target - ok, 0.0) if target > 0 else 0.0
    price = None
    try:
        price = float(price_per_piece) if price_per_piece not in (None, "") else None
    except Exception:
        price = None
    return {
        "target": target, "ok": ok, "total": total,
        "lost_pieces": lost_pieces,
        "lost_hours": (down + org) / 60.0,
        "down_hours": down / 60.0, "org_hours": org / 60.0,
        "value": lost_pieces * price if price and price > 0 else None,
        "price": price if price and price > 0 else None,
    }


def delta_text(current, previous, unit=" pp", decimals=1) -> tuple[str, str]:
    """('↑ +3,1 pp', 'up'|'down'|'flat'|'none')."""
    if previous is None or current is None or (isinstance(previous, float) and math.isnan(previous)):
        return "nema prethodnog perioda", "none"
    diff = float(current) - float(previous)
    if abs(diff) < 0.05:
        return "bez promene", "flat"
    arrow = "↑" if diff > 0 else "↓"
    sign = "+" if diff > 0 else "−"
    return f"{arrow} {sign}{abs(diff):.{decimals}f}".replace(".", ",") + unit, "up" if diff > 0 else "down"


def headline(metric_label, value, previous, reference, period_name, top_loss=None, coverage_info=None) -> str:
    """One plain sentence a manager understands without knowing the line."""
    def pct(v):
        return f"{float(v):.1f}".replace(".", ",") + " %"

    parts = [f"{metric_label} {period_name} je {pct(value)}"]
    gap = float(value) - float(reference)
    if abs(gap) < 0.05:
        parts.append(f"tačno na referenci od {pct(reference)}")
    else:
        parts.append(f"{abs(gap):.1f}".replace(".", ",") + f" pp {'iznad' if gap > 0 else 'ispod'} reference od {pct(reference)}")
    sentence = parts[0] + " — " + parts[1]
    if previous is not None:
        diff = float(value) - float(previous)
        if abs(diff) < 0.05:
            sentence += ", isto kao u prethodnom periodu"
        else:
            sentence += f", {abs(diff):.1f}".replace(".", ",") + f" pp {'bolje' if diff > 0 else 'slabije'} nego u prethodnom periodu"
    sentence += "."
    if top_loss:
        sentence += f" Najveći gubitak: {top_loss}."
    if coverage_info and coverage_info.get("days_expected") and not coverage_info.get("complete"):
        sentence += (f" Pažnja: uneto je {coverage_info['days_entered']} od {coverage_info['days_expected']} radnih dana,"
                     " pa je rezultat delimičan.")
    return sentence


def low_volume_flags(by_machine: pd.DataFrame, share=0.25) -> dict:
    """Machines with much less production than the others (their % is less reliable)."""
    if by_machine is None or by_machine.empty or "Total_Pcs" not in by_machine.columns:
        return {}
    totals = pd.to_numeric(by_machine["Total_Pcs"], errors="coerce").fillna(0)
    median = float(totals.median()) if len(totals) else 0.0
    flags = {}
    for machine, total, records in zip(by_machine["Machine"], totals, by_machine.get("Records", pd.Series([2] * len(totals)))):
        flags[str(machine)] = bool(len(totals) > 1 and (total < median * share or int(records or 0) < 2 and total < median))
    return flags


# ---------------------------------------------------------------------------
# IWON (private planning)
# ---------------------------------------------------------------------------
IWON_COMPARE_COLUMNS = [
    "Year", "CW", "Project", "Process", "Machine", "Target_OEE",
    "Plan_A", "Plan_P", "Plan_Q", "Plan_OEE",
    "Forecast_A", "Forecast_P", "Forecast_Q", "Forecast_OEE",
    "Baseline_Weeks", "Baseline_Note", "Plan_Version", "Plan_Generated_At",
    "Actual_A", "Actual_P", "Actual_Q", "Actual_OEE",
    "Dev_Plan_OEE", "Dev_Forecast_OEE", "Dev_A", "Dev_P", "Dev_Q",
    "Coverage_Days", "Refreshed_At",
]
IWON_HISTORY_COLUMNS = IWON_COMPARE_COLUMNS + ["Replaced_At"]
IWON_CAUSE_COLUMNS = [
    "Year", "CW", "Project", "Process", "Machine", "Loss_Type", "Cause", "Lever",
    "Now_Per_Week", "Now_Avg_Min", "Now_Min_Week", "Best_Per_Week", "Best_Avg_Min",
    "Target_Per_Week", "Target_Avg_Min", "Target_Min_Week", "Reduction_Min_Week", "Rating",
    "Actual_Per_Week", "Actual_Avg_Min", "Actual_Min_Week", "Generated_At", "Refreshed_At",
]
RATING_OK = "realno"
RATING_HARD = "izazovno"
RATING_UNREALISTIC = "nerealno"
RATING_SAME = "bez promene"


def week_start(year, cw) -> pd.Timestamp:
    return pd.Timestamp(date.fromisocalendar(int(year), int(cw), 1))


def iso_weeks_in_year(year) -> int:
    return date(int(year), 12, 28).isocalendar()[1]


def balanced_components(actual_a, actual_p, actual_q, target_oee):
    """A/P/Q whose product equals the target (same rule as the original IWON)."""
    vals = [min(100.0, max(float(v or 0), 0.01)) for v in (actual_a, actual_p, actual_q)]
    target = max(0.0, min(float(target_oee), 99.0))
    if target <= 0:
        return 0.0, 0.0, 0.0
    current = vals[0] * vals[1] * vals[2] / 10000.0
    if current >= target:
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


def baseline_window(actual: pd.DataFrame, year, cw, weeks=10) -> tuple[pd.DataFrame, str, int]:
    """Rows used as the starting point for a week's plan/forecast.

    1. the last `weeks` ISO weeks with data before the planned week;
    2. none there (e.g. a week far back) -> the latest `weeks` weeks with data;
    3. no OEE data at all -> empty (the plan then splits the target evenly).
    Returns (rows, note, number_of_weeks_with_data).
    """
    if actual is None or actual.empty:
        return pd.DataFrame(), "nema OEE podataka — cilj je podeljen ravnomerno na A, P i Q", 0
    data = actual.copy()
    data["_ws"] = pd.to_datetime(data["Datum"], errors="coerce").dt.normalize()
    data["_ws"] = data["_ws"] - pd.to_timedelta(data["_ws"].dt.weekday, unit="D")
    start = week_start(year, cw)
    before = sorted(w for w in data["_ws"].dropna().unique() if pd.Timestamp(w) < start)[-int(weeks):]
    if before:
        window = data[data["_ws"].isin(before)]
        first, last = pd.Timestamp(before[0]), pd.Timestamp(before[-1])
        return (window.drop(columns=["_ws"]),
                f"{len(before)} nedelja sa podacima pre CW{int(cw):02d} "
                f"(CW{first.isocalendar()[1]:02d}–CW{last.isocalendar()[1]:02d})", len(before))
    latest = sorted(data["_ws"].dropna().unique())[-int(weeks):]
    window = data[data["_ws"].isin(latest)]
    if window.empty:
        return pd.DataFrame(), "nema OEE podataka — cilj je podeljen ravnomerno na A, P i Q", 0
    first, last = pd.Timestamp(min(latest)), pd.Timestamp(max(latest))
    return (window.drop(columns=["_ws"]),
            f"nema podataka pre ove nedelje — korišćene poslednje {len(latest)} nedelje sa podacima "
            f"(CW{first.isocalendar()[1]:02d}–CW{last.isocalendar()[1]:02d} {last.isocalendar()[0]})",
            len(latest))


def plan_week(actual: pd.DataFrame, machines, year, cw, project, process, target_oee, aggregate,
              weeks=10, version=1, now=None) -> dict:
    """IWON plan + forecast for one week, with or without data for that week.

    * forecast = the baseline A/P/Q (what happens if nothing changes)
    * plan     = baseline raised/lowered to the target with the balanced rule
    Every machine of MASTER_DATA gets a row; a machine without history uses the
    process-level (GLOBAL) baseline.
    """
    now = now or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    scope = pd.DataFrame()
    if actual is not None and not actual.empty:
        scope = actual[
            (actual["Project"].astype(str).str.strip().str.casefold() == str(project).strip().casefold())
            & (actual["Process"].astype(str).str.strip().str.casefold() == str(process).strip().casefold())
        ]
    base, note, used = baseline_window(scope, year, cw, weeks)
    target = float(target_oee)
    if not (0 < target <= 99):
        raise ValueError("IWON Target OEE mora biti između 0 i 99 %.")

    def components(frame):
        if frame is None or frame.empty:
            return None
        agg = aggregate(frame.assign(_IWON="G"), ["_IWON"])
        if agg.empty:
            return None
        r = agg.iloc[0]
        return (float(r.get("Machine_Availability_%", 0) or 0), float(r.get("Machine_Performance_CT_%", 0) or 0),
                float(r.get("Quality_%", 0) or 0))

    even = round((target / 100.0) ** (1.0 / 3.0) * 100.0, 4)
    global_base = components(base) or (even, even, even)
    names = ["GLOBAL"] + sorted({str(m).strip() for m in (machines or []) if str(m).strip()} | (
        set(base["Machine"].astype(str).str.strip()) if base is not None and not base.empty else set()))
    rows, iwon_rows = [], []
    for machine in names:
        if machine == "GLOBAL":
            comp = global_base
        else:
            own = base[base["Machine"].astype(str).str.strip() == machine] if base is not None and not base.empty else None
            comp = components(own) or global_base
        plan = balanced_components(comp[0], comp[1], comp[2], target)
        forecast_oee = comp[0] * comp[1] * comp[2] / 10000.0
        row = {
            "Year": int(year), "CW": int(cw), "Project": str(project), "Process": str(process), "Machine": machine,
            "Target_OEE": round(target, 4),
            "Plan_A": plan[0], "Plan_P": plan[1], "Plan_Q": plan[2],
            "Plan_OEE": round(plan[0] * plan[1] * plan[2] / 10000.0, 4),
            "Forecast_A": round(comp[0], 4), "Forecast_P": round(comp[1], 4), "Forecast_Q": round(comp[2], 4),
            "Forecast_OEE": round(forecast_oee, 4),
            "Baseline_Weeks": int(used), "Baseline_Note": note,
            "Plan_Version": int(version), "Plan_Generated_At": now,
        }
        for col in IWON_COMPARE_COLUMNS:
            row.setdefault(col, "")
        rows.append(row)
        iwon_rows.append([int(year), int(cw), str(project), str(process), machine, plan[0], plan[1], plan[2], round(target, 4), now])
    return {"compare_rows": rows, "iwon_rows": iwon_rows, "baseline": base, "note": note, "weeks_used": used}


def actual_for_week(actual: pd.DataFrame, year, cw, project, process, aggregate) -> dict:
    """{machine: (A, P, Q, OEE, days)} for one week incl. GLOBAL; empty when no data."""
    if actual is None or actual.empty:
        return {}
    start = week_start(year, cw)
    dates = pd.to_datetime(actual["Datum"], errors="coerce").dt.normalize()
    rows = actual[
        (dates >= start) & (dates < start + pd.Timedelta(days=7))
        & (actual["Project"].astype(str).str.strip().str.casefold() == str(project).strip().casefold())
        & (actual["Process"].astype(str).str.strip().str.casefold() == str(process).strip().casefold())
    ]
    if rows.empty:
        return {}
    result = {}

    def put(name, frame):
        agg = aggregate(frame.assign(_IWON="G"), ["_IWON"])
        if agg.empty:
            return
        r = agg.iloc[0]
        a, p, q = (float(r.get(c, 0) or 0) for c in ("Machine_Availability_%", "Machine_Performance_CT_%", "Quality_%"))
        days = pd.to_datetime(frame["Datum"], errors="coerce").dt.normalize().nunique()
        result[name] = (a, p, q, float(r.get("Machine_OEE_CT_%", a * p * q / 10000.0) or 0), int(days))

    put("GLOBAL", rows)
    for machine, frame in rows.groupby(rows["Machine"].astype(str).str.strip()):
        put(machine, frame)
    return result


def apply_actuals(compare_rows: list, actuals: dict, now=None) -> list:
    """Fill actual values and deviations (actual − plan / forecast) into plan rows."""
    now = now or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    out = []
    for row in compare_rows:
        row = dict(row)
        found = actuals.get(str(row.get("Machine", "")).strip())
        row["Refreshed_At"] = now
        if found:
            a, p, q, oee, days = found

            def dev(actual_value, planned):
                try:
                    return round(float(actual_value) - float(planned), 4)
                except Exception:
                    return ""

            row.update({
                "Actual_A": round(a, 4), "Actual_P": round(p, 4), "Actual_Q": round(q, 4), "Actual_OEE": round(oee, 4),
                "Dev_Plan_OEE": dev(oee, row.get("Plan_OEE")), "Dev_Forecast_OEE": dev(oee, row.get("Forecast_OEE")),
                "Dev_A": dev(a, row.get("Plan_A")), "Dev_P": dev(p, row.get("Plan_P")), "Dev_Q": dev(q, row.get("Plan_Q")),
                "Coverage_Days": days,
            })
        else:
            for col in ("Actual_A", "Actual_P", "Actual_Q", "Actual_OEE", "Dev_Plan_OEE", "Dev_Forecast_OEE",
                        "Dev_A", "Dev_P", "Dev_Q"):
                row[col] = ""
            row["Coverage_Days"] = 0
        out.append(row)
    return out


def forecast_accuracy(compare_df: pd.DataFrame, machine="GLOBAL") -> dict:
    """How far actual OEE was from the forecast and from the plan (refreshed weeks)."""
    if compare_df is None or compare_df.empty:
        return {"weeks": 0}
    df = compare_df[compare_df["Machine"].astype(str).str.strip() == machine].copy()
    for col in ("Dev_Forecast_OEE", "Dev_Plan_OEE", "Dev_A", "Dev_P", "Dev_Q"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Dev_Forecast_OEE"])
    if df.empty:
        return {"weeks": 0}
    comps = {"Dostupnost": df["Dev_A"].abs().mean(), "Performanse": df["Dev_P"].abs().mean(), "Kvalitet": df["Dev_Q"].abs().mean()}
    worst = max(comps, key=lambda k: (comps[k] if pd.notna(comps[k]) else -1))
    return {
        "weeks": int(len(df)),
        "forecast_mae": float(df["Dev_Forecast_OEE"].abs().mean()),
        "forecast_bias": float(df["Dev_Forecast_OEE"].mean()),
        "plan_mae": float(df["Dev_Plan_OEE"].abs().mean()),
        "plan_bias": float(df["Dev_Plan_OEE"].mean()),
        "plan_hit_weeks": int((df["Dev_Plan_OEE"] >= -0.05).sum()),
        "worst_component": worst,
    }


def _quantile(values, q):
    values = sorted(float(v) for v in values if pd.notna(v))
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    pos = (len(values) - 1) * q
    low, high = int(math.floor(pos)), int(math.ceil(pos))
    return values[low] + (values[high] - values[low]) * (pos - low)


def cause_plan(events: pd.DataFrame, baseline_rows: pd.DataFrame, plan_availability, causes_df=None,
               best_quantile=0.2, weeks=None) -> dict:
    """Per-cause targets that make the plan's availability reachable.

    * now     = per week: how often, average duration, minutes
    * best    = already achieved: duration of the fastest `best_quantile` of the
                events, weekly count at the same quantile
    * needed  = minutes of downtime that must disappear per week for the planned
                availability (Machine availability = run / (open - org. loss))
    The reduction is taken from the largest realistic potential first (Pareto),
    never past the best already achieved; only what is still missing after that
    is spread proportionally and rated 'nerealno'.
    """
    empty = {"items": [], "needed_min_week": 0.0, "realistic_max_a": None, "uncaused_min_week": 0.0,
             "available_min_week": 0.0, "downtime_min_week": 0.0, "weeks": 0, "missing_min_week": 0.0}
    if baseline_rows is None or baseline_rows.empty:
        return empty
    rows = baseline_rows.copy()
    rows["_d"] = pd.to_datetime(rows["Datum"], errors="coerce").dt.normalize()
    rows["_ws"] = rows["_d"] - pd.to_timedelta(rows["_d"].dt.weekday, unit="D")
    n_weeks = int(weeks or rows["_ws"].nunique() or 1)
    open_t = pd.to_numeric(rows["Open time"], errors="coerce").fillna(0)
    org = pd.to_numeric(rows["Organisational loss"], errors="coerce").fillna(0)
    down = pd.to_numeric(rows["Down time"], errors="coerce").fillna(0)
    available = float((open_t - org).clip(lower=0).sum()) / n_weeks
    downtime = float(down.sum()) / n_weeks
    allowed = available * (1 - float(plan_availability) / 100.0)
    needed = max(downtime - allowed, 0.0)

    keys = set(zip(rows["_d"], rows["Machine"].astype(str).str.strip()))
    ev = events if events is not None else pd.DataFrame(columns=DOWNTIME_EVENT_COLUMNS)
    if not ev.empty:
        ev = ev[[(d, str(m).strip()) in keys for d, m in zip(ev["Datum"], ev["Machine"])]]
        ev = ev[(ev["Loss_Type"] == LOSS_DOWNTIME) & (ev["Status"] != STATUS_OPEN) & (ev["Minutes"] > 0)]
    levers = cause_lever_map(causes_df)
    week_list = sorted(rows["_ws"].dropna().unique())
    items = []
    if not ev.empty:
        ev = ev.copy()
        ev["_ws"] = ev["Datum"] - pd.to_timedelta(ev["Datum"].dt.weekday, unit="D")
        for (machine, cause), frame in ev.groupby([ev["Machine"].astype(str).str.strip(), "Cause"]):
            durations = frame["Minutes"].tolist()
            counts = [int((frame["_ws"] == w).sum()) for w in week_list] or [len(frame)]
            per_week = len(frame) / n_weeks
            avg = float(sum(durations) / len(durations))
            best_dur = _quantile(durations, best_quantile) if len(durations) >= 3 else avg
            best_freq = _quantile(counts, best_quantile) if len(counts) >= 3 else per_week
            lever = levers.get((LOSS_DOWNTIME, cause), LEVER_DURATION)
            if lever == LEVER_FREQUENCY:
                potential = max(per_week - best_freq, 0.0) * avg
            else:
                potential = per_week * max(avg - best_dur, 0.0)
            items.append({
                "Machine": machine, "Loss_Type": LOSS_DOWNTIME, "Cause": cause, "Lever": lever,
                "Now_Per_Week": per_week, "Now_Avg_Min": avg, "Now_Min_Week": per_week * avg,
                "Best_Per_Week": best_freq, "Best_Avg_Min": best_dur,
                "_median_dur": _quantile(durations, 0.5), "_median_freq": _quantile(counts, 0.5),
                "_potential": potential, "_take": 0.0,
            })
    caused = sum(item["Now_Min_Week"] for item in items)
    uncaused = max(downtime - caused, 0.0)

    remaining = needed
    for item in sorted(items, key=lambda i: i["_potential"], reverse=True):
        if remaining <= 1e-9:
            break
        take = min(item["_potential"], remaining)
        item["_take"] += take
        remaining -= take
    missing = max(remaining, 0.0)
    if missing > 1e-9 and items:
        # Not reachable with what was already achieved: spread the rest proportionally.
        pool = sum(max(i["Now_Min_Week"] - i["_take"], 0.0) for i in items)
        for item in items:
            share = max(item["Now_Min_Week"] - item["_take"], 0.0) / pool if pool else 0.0
            item["_take"] += min(missing * share, max(item["Now_Min_Week"] - item["_take"], 0.0))

    for item in items:
        take = item["_take"]
        if item["Lever"] == LEVER_FREQUENCY:
            target_freq = max(item["Now_Per_Week"] - (take / item["Now_Avg_Min"] if item["Now_Avg_Min"] else 0.0), 0.0)
            target_dur = item["Now_Avg_Min"]
            if take <= 1e-9:
                rating = RATING_SAME
            elif target_freq >= (item["_median_freq"] if item["_median_freq"] is not None else item["Now_Per_Week"]) - 1e-9:
                rating = RATING_OK
            elif target_freq >= item["Best_Per_Week"] - 1e-6:
                rating = RATING_HARD
            else:
                rating = RATING_UNREALISTIC
        else:
            target_freq = item["Now_Per_Week"]
            target_dur = max(item["Now_Avg_Min"] - (take / item["Now_Per_Week"] if item["Now_Per_Week"] else 0.0), 0.0)
            if take <= 1e-9:
                rating = RATING_SAME
            elif target_dur >= (item["_median_dur"] if item["_median_dur"] is not None else item["Now_Avg_Min"]) - 1e-9:
                rating = RATING_OK
            elif target_dur >= item["Best_Avg_Min"] - 1e-6:
                rating = RATING_HARD
            else:
                rating = RATING_UNREALISTIC
        item.update({
            "Target_Per_Week": target_freq, "Target_Avg_Min": target_dur,
            "Target_Min_Week": target_freq * target_dur, "Reduction_Min_Week": take, "Rating": rating,
        })
    best_downtime = uncaused + sum(i["Now_Min_Week"] - i["_potential"] for i in items)
    realistic_max_a = ((available - best_downtime) / available * 100.0) if available > 0 else None
    for item in items:
        for key in [k for k in item if k.startswith("_")]:
            item.pop(key)
    items.sort(key=lambda i: (i["Reduction_Min_Week"], i["Now_Min_Week"]), reverse=True)
    return {
        "items": items, "needed_min_week": needed, "realistic_max_a": realistic_max_a,
        "uncaused_min_week": uncaused, "available_min_week": available, "downtime_min_week": downtime,
        "weeks": n_weeks, "missing_min_week": missing if items else needed,
    }


def realistic_max_oee(realistic_max_a, forecast_p, forecast_q):
    if realistic_max_a is None:
        return None
    return max(min(realistic_max_a, 100.0), 0.0) * float(forecast_p) * float(forecast_q) / 10000.0


def actual_cause_week(events: pd.DataFrame, year, cw, machine, cause) -> tuple:
    """(count, avg min, total min) of one machine+cause in one ISO week."""
    if events is None or events.empty:
        return 0, 0.0, 0.0
    start = week_start(year, cw)
    frame = events[
        (events["Datum"] >= start) & (events["Datum"] < start + pd.Timedelta(days=7))
        & (events["Machine"].astype(str).str.strip() == str(machine).strip())
        & (events["Cause"] == cause) & (events["Status"] != STATUS_OPEN)
    ]
    if frame.empty:
        return 0, 0.0, 0.0
    total = float(frame["Minutes"].sum())
    return int(len(frame)), total / len(frame), total
