"""End-to-end simulation of Lianbo Project Performance Hub.

Runs the real application script against an in-memory Google Sheets and a
deterministic Streamlit replacement, simulating real users (admin and
technicians) on desktop/phone: login, Work Tickets, KPI, OEE, BN, Line
Verification, Administration, background automation, Google quota errors.

Usage:  python tests/simulation/run_simulation.py [--legacy-pandas]
Exit code 0 = every check passed.
"""
from __future__ import annotations

import datetime as dt
import os
import smtplib
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.environ.get("SIM_APP_DIR") or os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(HERE, "fakes"))
sys.path.insert(1, APP_DIR)
os.chdir(APP_DIR)

import pandas as pd  # noqa: E402

if "--legacy-pandas" in sys.argv:
    # Production runs pandas 2.2 (object dtype for text); mimic it on pandas 3.
    try:
        pd.set_option("future.infer_string", False)
    except Exception:
        pass

import gspread  # noqa: E402  (fake)
import streamlit as st  # noqa: E402  (fake)
import extra_streamlit_components as stx  # noqa: E402  (fake)
from core import google_sheets_engine as engine_module  # noqa: E402

APP = os.path.join(APP_DIR, "lianbo_project_performance_hub.py")
H = st.HARNESS

# Retries/back-off must not slow the simulation down; quotas are simulated.
time.sleep = lambda *_a, **_k: None
if hasattr(engine_module._ENGINE, "_read_limiter"):
    engine_module._ENGINE._read_limiter.max_calls = 10**9
    engine_module._ENGINE._write_limiter.max_calls = 10**9

SENT_MAIL: list = []


class FakeSMTP:
    def __init__(self, host, port, timeout=None):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        SENT_MAIL.append({"to": msg["To"], "subject": msg["Subject"], "body": msg.get_content()})

    def quit(self):
        pass

    def close(self):
        pass


smtplib.SMTP = FakeSMTP
smtplib.SMTP_SSL = FakeSMTP

RESULTS: list = []


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition), detail))
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name}" + (f"  -> {detail}" if detail and not condition else ""))


# ---------------------------------------------------------------------------
# Fixture: every Google Sheet the application uses
# ---------------------------------------------------------------------------
KPI = "1f-mLNXA-oPlc-Q9z8vAh7RKzvblZvdYSLT0sq6aAgJY"
ALL = "1Iclk5l5XGil-c-TDJ08WIhkA3Pk0q-kqcBrMxm09i9M"
DOWN = "1HdC357shptB8qWvaKzRqZ925mikdv7yui1mLiw2bujs"
OEE = "15_eNq1q7zJIgQ7wQEaEAR1s-VjNp-Kub1dSv4mz5XRo"
IWON = "1Q2V7VZlSfDH3ZAb80j5hoprDkaWyRuS9COV7wzDqVnw"
BNF = "18g4FPWu7SWET0bKFS6XZuabhxUrm0sZy1K_j2aetFwE"
BND = "1dxsLQkIXYFC6YjNqqX1YTiFZk6DoqzeKh00UXHgrmfE"
LV = "1jhc_JfbjPLWT9QRfIqDeVeIirKWJrWQBexFMtLc573c"
AUTH = "1os2824HIUTJkbCkiskM3s5gXdv0zOEL0VUL1CrC6O_s"

TODAY = dt.date.today()


def workday_before(day):
    day = day - dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day


PREV = workday_before(TODAY)
PREV_TXT = PREV.strftime("%d.%m.%Y")
TODAY_TXT = TODAY.strftime("%d.%m.%Y")

TECH_HEADERS = ["Technician_ID", "Technician_Name", "Username", "Position", "Department", "Email", "Active", "Picture",
                "Receive_Task_Email", "Receive_Task_Reminder", "Receive_Missing_Time_Email", "Receive_BN_Email", "Supervisor"]


def build_store():
    gspread.reset_store()
    S = gspread.STORE

    def book(key):
        S[key] = gspread.Spreadsheet(key)
        return S[key]

    kpi = book(KPI)
    kpi.add("Form Responses 1", [
        ["Timestamp", "Tehničar/Inženjer", "Kategorija rada", "Opis aktivnosti", "Datum", "Vreme početka", "Vreme završetka aktivnosti"],
        # reversed name, H:MM:SS times
        [f"{PREV_TXT} 9:05:11", "Nikolić Bojan", "Proizvodnja", "Podešavanje linije", PREV_TXT, "7:00:00", "8:15:00"],
        # Đ written as Dj, HH:MM times
        [f"{PREV_TXT} 11:00:02", "Djordje Djordjevic", "Kvalitet", "Kontrola", PREV_TXT, "08:30", "10:00"],
        # date typed with spaces and trailing dot
        [f"{PREV_TXT} 12:00:00", "Đorđe Đorđević", "Projekti", "Sastanak", PREV.strftime("%d. %m. %Y."), "10:15", "11:00"],
        # incomplete row (no end time) must be reported, not crash
        [f"{PREV_TXT} 12:30:00", "Bojan Nikolić", "Proizvodnja", "Bez kraja", PREV_TXT, "12:00", ""],
    ])
    kpi.add("Technicians", [TECH_HEADERS,
        ["TECH-000001", "Bojan Nikolić", "bojan", "Tehničar", "Projekti", "bojan@example.com", "YES", "", "YES", "YES", "YES", "YES", "NO"],
        ["TECH-000002", "Đorđe Đorđević", "djordje", "Tehničar", "Projekti", "djordje@example.com", "YES", "", "YES", "YES", "YES", "YES", "NO"],
        ["TECH-000003", "Marko Marković", "marko", "Tehničar", "Projekti", "marko@example.com", "YES", "", "YES", "YES", "YES", "YES", "NO"],
        ["TECH-000004", "Ana Anić", "ana", "Supervisor", "Projekti", "ana@example.com", "YES", "", "YES", "YES", "YES", "YES", "YES"],
    ])
    kpi.add("Aktivni Tehničari", [["Tehničar", "Aktivan"], ["Bojan Nikolić", "DA"]])
    # Legacy header spelling on purpose: "Assigned To" / "Task Title" with spaces.
    kpi.add("TASKS", [["Task_ID", "Assigned_Technician_ID", "Assigned To", "Assigned_Email", "Process", "Task Title",
                       "Task_Priority", "Status", "Start_Date", "Start_Time", "End_Date", "End_Time",
                       "Calculated_Duration", "Effective_Duration", "Created_By", "Created_By_Email", "Created_At",
                       "Closed_By", "Closed_At"]])
    kpi.add("TASK_ACTIVITY", [["Activity_ID", "Task_ID", "Assigned_Technician_ID", "Assigned_To", "Task_Title",
                               "Start_Date", "Start_Time", "End_Date", "End_Time", "Calculated_Duration", "Effective_Duration"]])
    kpi.add("TECHNICIAN_TARGETS", [
        ["Technician", "Active", "Period_Type", "Target Activities/Hour", "Target Activities", "Target Utilization"],
        ["Bojan Nikolić", "YES", "Monthly", "0.5", "60", "85%"],
        ["Ivan Ivić", "YES", "Monthly", "0.5", "60", "85%"],
    ])
    kpi.add("MISSING_WORK_TIME", [["Timestamp", "Technician_ID", "Technician_Name", "Missing_Date", "Note"]])
    kpi.add("EMAIL_LOG", [["Timestamp", "Email_Type", "Recipient", "Subject", "Status", "Related_ID", "Error_Message"]])

    book(ALL).add("all_activities", [[
        "Activity_ID", "Source", "Source_ID", "Technician_ID", "Technician_Name", "Work_Date", "Start_Time", "End_Time",
        "Calculated_Duration", "Effective_Duration", "Process", "Task_Title", "Task_ID", "Imported_At"]])

    book(DOWN).add("Form Responses 1", [
        ["Timestamp", "IME", "Projekat", "DATUM PROBLEMA", "POČETAK ZASTOJA", "ZAVRŠETAK ZASTOJA", "VREME ZASTOJA", "UZROK ZASTOJA", "MESTO ZASTOJA"],
        [f"{PREV_TXT} 10:50:00", "Markovic Marko", "APP350", PREV_TXT, "10:15:00", "10:45:00", "0:30:00", "Senzor", "RL 1"],
        [f"{PREV_TXT} 11:50:00", "Pera Perić", "APP350", PREV_TXT, "11:00:00", "11:20:00", "0:20:00", "Spoljni", "RL 2"],
    ])

    oee = book(OEE)
    oee.add("MASTER_DATA", [["Project", "Process", "Machine", "CT", "Target", "Active", "1 shift"],
                            ["APP350", "Inspection Rotor", "RL 1", "30", "900", "DA", "480"],
                            ["APP350", "Inspection Rotor", "RL 2", "28", "950", "DA", "480"]])
    oee.add("OEE_input", [["Datum", "CW", "Dan", "Project", "Process", "Machine", "CT_s", "Open time", "Number of shifts",
                           "OK pcs.", "NOK pcs.", "Total Pcs", "Down time", "Organisational loss", "Target pcs.",
                           "Submitted_By", "Shift", "Included_Shifts"]])
    iw = book(IWON)
    iw.add("Admin podešavanja", [["Year", "CW", "Project", "Process", "Target_OEE", "Updated_By", "Updated_At"]])
    iw.add("OEE_IWON", [["Year", "CW", "Project", "Process", "Machine", "Availability", "Performance", "Quality", "OEE", "Calculated_At"]])

    book(BNF).add("Form Responses 1", [
        ["Timestamp", "Project", "Date", "Bottleneck time (seconds)", "Station", "Machine selection APP350"],
        [f"{PREV_TXT} 07:10:00", "APP350", PREV_TXT, "12,5", "OP100", "Line 1"],
    ])
    bnd = book(BND)
    bnd.add("BN_MACHINES", [["Machine_ID", "Project", "Machine", "Active"], ["BN-M-0001", "APP350", "Line 1", "YES"],
                            ["BN-M-0002", "APP350", "Line 2", "YES"]])
    bnd.add("BN_RECORDS", [["BN_ID", "Source", "Source_ID", "Date", "Machine_ID", "Project", "Machine", "BN_Time", "Station",
                            "Entered_By", "Entered_By_Username", "Entered_By_Email", "Created_At", "Updated_At"]])

    book(LV).add("Form_Responses", [
        ["Timestamp", "Proverio", "Projekat", "Mašina", "Dummy komadi", "Da li je linija detektovala komade", "Detektovan problem"],
        ["05.06.2026 08:00:00", "Bojan", "APP350", "RL 1", "3", "DA", ""],
        ["15.06.2026 09:00:00", "Bojan", "APP350", "RL 1", "3", "NE", "Senzor"],
    ])

    auth = book(AUTH)
    auth.add("User&Password", [["Username", "Password", "Full_Name", "Role", "Active", "Email", "Technician_ID"],
                               ["admin", "admin123", "Admin Adminović", "admin", "YES", "admin@example.com", ""],
                               ["bojan", "b123", "Bojan Nikolić", "User", "YES", "bojan@example.com", "TECH-000001"],
                               ["djordje", "d123", "Đorđe Đorđević", "User", "YES", "djordje@example.com", "TECH-000002"]])
    auth.add("Autorisation1", [["Role", "My_Tasks", "Work_Tickets", "Task", "BN_Entry", "BN_Module", "Bottleneck", "KPI_Process",
                                "OEE", "Line_Verification", "Alerts", "Exports", "Reports", "Admin_panel", "Administration", "Settings"],
                               ["admin"] + ["YES"] * 15,
                               ["User", "YES", "YES", "YES", "YES", "YES", "YES", "YES", "YES", "YES", "NO", "NO", "NO", "NO", "NO", "NO"]])


def sheet(key, name):
    return gspread.STORE[key]._sheets[name]


def rows(key, name):
    values = sheet(key, name).get_all_values()
    return values[0], values[1:]


SECRETS = {
    "gcp_service_account": {"type": "service_account", "private_key": "x"},
    "REMEMBER_ME_SECRET": "simulation-secret",
    "email": {"SMTP_HOST": "smtp.example.com", "SMTP_PORT": 587, "SMTP_USER": "hub@example.com",
              "SMTP_PASSWORD": "x", "EMAIL_SENDER": "hub@example.com", "EMAIL_ENABLED": "YES"},
}


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------
def new_browser():
    H.reset_browser()
    H.query = {}
    H.headers = {}
    stx.COOKIES.clear()


def run(clicks=(), values=None, state=None):
    H.log = []
    H.clicks = set(clicks)
    H.label_values = dict(values or {})
    for key, value in (state or {}).items():
        H.session_state[key] = value
    result = st.run_script(APP)
    uncaught = H.messages("uncaught")
    return result, uncaught


def login(username, password):
    new_browser()
    run()  # login page
    result, uncaught = run(clicks=["submit:login_form:Login"], values={"Username": username, "Password": password})
    return result, uncaught


def app():
    return st.LAST_GLOBALS


def no_crash(name, outcome):
    result, uncaught = outcome
    check(name, not uncaught and result["status"] in ("completed", "stopped"),
          (uncaught[0][:1500] if uncaught else result))


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
def scenario_login_and_password_migration():
    outcome = login("admin", "admin123")
    no_crash("Admin login works", outcome)
    check("Admin is authenticated", H.session_state.get("authenticated") is True)
    header, data = rows(AUTH, "User&Password")
    check("Legacy plaintext passwords were hashed", all(r[1].startswith("pbkdf2_sha256$") for r in data))
    outcome = login("admin", "wrong")
    check("Wrong password rejected", not H.session_state.get("authenticated") and any("Pogrešan" in m for m in H.messages("error")))


def scenario_initialize_all_activities():
    login("admin", "admin123")
    outcome = run(state={"selected_module": "KPI Process"})
    check("KPI asks for ALL_ACTIVITIES initialization", any("inicijalizovan" in m for m in H.messages("warning")), H.messages("warning"))
    outcome = run(clicks=["initialize_all_activities_from_kpi"], state={"selected_module": "KPI Process"})
    no_crash("ALL_ACTIVITIES initialization", outcome)
    _, data = rows(ALL, "all_activities")
    sources = [r[1] for r in data]
    check("Forms rows imported (incl. reversed name / spaced date)", sources.count("FORM") == 3, sources)
    check("Downtime of app technician imported, external person ignored", sources.count("DOWNTIME") == 1, sources)
    tech_ids = {r[4]: r[3] for r in data}
    check("Reversed and Dj-spelled names mapped to Technician_ID",
          tech_ids.get("Nikolić Bojan") == "TECH-000001" and tech_ids.get("Djordje Djordjevic") == "TECH-000002", tech_ids)


def scenario_technician_self_task():
    login("bojan", "b123")
    base_state = {"selected_module": "My Tasks", "work_tickets_view": "Kanban Board", "show_create_my_task_form": True,
                  "self_task_start_now": True}
    run(state=base_state)
    values = {"self_task_title": "Zamena senzora", "self_task_description": "", "self_task_start_date": f"{TODAY_TXT}.",
              "self_task_start_time_text": "8.30", "self_task_end_date": "", "self_task_end_time_text": "10"}
    for key, value in values.items():
        H.session_state[key] = value
    outcome = run(clicks=["submit:create_my_task_form:Create My Task"], state=base_state)
    no_crash("Technician creates own task with trailing-dot date and 8.30 time", outcome)
    check("Success message shown", any("uspešno kreiran" in m for m in H.messages("success")), H.log[-15:])
    header, data = rows(KPI, "TASKS")
    check("Task row saved", len(data) == 1, data)
    if data:
        task = dict(zip(header, data[0]))
        check("Task saved under legacy header 'Assigned To'", task.get("Assigned To") == "Bojan Nikolić", task)
        check("Task completed with 90 min", task.get("Status") == "Completed" and float(task.get("Calculated_Duration") or 0) == 90.0, task)
    _, acts = rows(KPI, "TASK_ACTIVITY")
    check("Activity row saved", len(acts) == 1, acts)
    check("Form fields cleared after success", H.session_state.get("self_task_title", "") in ("", None))

    # Double tap on the button: same title again within seconds
    for key, value in values.items():
        H.session_state[key] = value
    run(clicks=["submit:create_my_task_form:Create My Task"], state=base_state)
    _, data = rows(KPI, "TASKS")
    check("Double submit does not create a duplicate task", len(data) == 1, len(data))

    # Rejected entry keeps the typed text (no retyping on phone)
    H.session_state.update({"self_task_title": "Pogrešno vreme", "self_task_start_date": TODAY_TXT,
                            "self_task_start_time_text": "25:99", "self_task_end_time_text": "10:00"})
    run(clicks=["submit:create_my_task_form:Create My Task"], state=base_state)
    check("Invalid time gives a clear error", any("nije prepoznato" in m for m in H.messages("error")), H.messages("error"))
    check("Typed title kept after an error", H.session_state.get("self_task_title") == "Pogrešno vreme")


def scenario_admin_task_and_activity():
    login("admin", "admin123")
    base = {"selected_module": "Work Tickets", "work_tickets_view": "New Task"}
    run(state=base)
    H.session_state.update({"new_task_assigned_to": "Đorđe Đorđević", "new_task_title": "-podesiti senzor",
                            "new_task_process": "Kvalitet"})
    outcome = run(clicks=["submit:new_task_form:Create Task"], state=base)
    no_crash("Admin creates task", outcome)
    header, data = rows(KPI, "TASKS")
    titles = [dict(zip(header, r)).get("Task Title") for r in data]
    check("Text starting with '-' saved as text, not #ERROR!", "-podesiti senzor" in titles, titles)
    new_task = [dict(zip(header, r)) for r in data if dict(zip(header, r)).get("Task Title") == "-podesiti senzor"]
    check("Delegated task is Open", new_task and new_task[0]["Status"] == "Open", new_task)
    check("Task e-mail sent to assignee", any(m["to"] == "djordje@example.com" for m in SENT_MAIL))

    # Admin enters an activity, changing the technician first (dependent dropdown)
    base = {"selected_module": "Work Tickets", "work_tickets_view": "Task Activity", "activity_assigned_to": "Bojan Nikolić"}
    run(state=base)
    H.session_state["activity_assigned_to"] = "Đorđe Đorđević"
    run(state={"activity_assigned_to": "Đorđe Đorđević"})
    task_key = [k for k in H.session_state if k.startswith("activity_task_id_")]
    chosen = H.session_state.get("activity_task_id_" + "djordje_djordjevic".replace(" ", "_"))
    H.session_state.update({"activity_start_date": PREV_TXT, "activity_start_time_text": "13:00",
                            "activity_end_date": PREV_TXT, "activity_end_time_text": "14:30", "activity_close_after": True})
    outcome = run(clicks=["submit:task_activity_form:Save Activity"])
    no_crash("Admin saves activity after switching technician", outcome)
    check("Activity success message", any("Aktivnost je upisana" in m for m in H.messages("success")), H.log[-12:])
    _, acts = rows(KPI, "TASK_ACTIVITY")
    check("Activity row appended for Đorđe", any(r[3] == "Đorđe Đorđević" for r in acts), acts)
    header, data = rows(KPI, "TASKS")
    task = [dict(zip(header, r)) for r in data if dict(zip(header, r)).get("Task Title") == "-podesiti senzor"][0]
    check("Task closed with real start/end", task["Status"] == "Completed" and task["Start_Time"] and task["End_Time"], task)
    check("Completion mail to creator and assignee",
          any(m["subject"].startswith("Task completed") and m["to"] in ("admin@example.com", "djordje@example.com") for m in SENT_MAIL))
    # Same activity again -> blocked as duplicate
    H.session_state.update({"activity_start_date": PREV_TXT, "activity_start_time_text": "13:00",
                            "activity_end_date": PREV_TXT, "activity_end_time_text": "14:30"})
    open_task_left = [dict(zip(header, r)) for r in data if dict(zip(header, r)).get("Status") != "Completed"]
    if not open_task_left:
        check("No open task left for duplicate test (expected)", True)


def scenario_kpi_sees_everything():
    login("admin", "admin123")
    outcome = run(state={"selected_module": "KPI Process", "kpi_selected_tab": "Dashboard", "kpi_selected_tab_radio": "Dashboard"})
    no_crash("KPI dashboard renders", outcome)
    _, data = rows(ALL, "all_activities")
    sources = [r[1] for r in data]
    check("Work Ticket activities auto-imported into KPI (no manual sync)", sources.count("APP") == 2, sources)
    built = app()["build_kpi_dataset"]()
    df = built[1]
    names = set(df["Tehničar/Inženjer"].unique())
    check("KPI shows official names only (no split people)", names == {"Bojan Nikolić", "Đorđe Đorđević", "Marko Marković"}, names)
    check("No KPI row lost to mixed time formats", len(df) == len(data) and int(df.attrs.get("dropped_rows", 0)) == 0,
          (len(df), len(data), df.attrs))
    downtime = df[df["Izvor"] == "Zastoji tehničara"]
    check("Downtime uses confirmed 30 min", len(downtime) == 1 and abs(downtime["Duration_Hours"].iloc[0] - 0.5) < 1e-9)

    # Second sync must not duplicate anything
    g = app()
    g["mark_activity_sync_needed"]()
    run(state={"selected_module": "KPI Process"})
    _, data2 = rows(ALL, "all_activities")
    check("Repeated sync adds no duplicates", len(data2) == len(data), (len(data), len(data2)))

    for tab in ["Dashboard", "Dnevni pregled", "Mesečni pregled", "Godišnji pregled", "Poređenje tehničara", "Kategorije",
                "Pareto", "Ranking", "Data Quality", "Admin Panel", "Technician Evaluation", "Alerts", "Export"]:
        state = {"selected_module": "KPI Process", "kpi_selected_tab": tab, "kpi_selected_tab_radio": tab}
        values = {"kpi_eval_technician": "Bojan Nikolić", "daily_technician_view": "Bojan Nikolić",
                  "kpi_selected_compare_techs": ["Bojan Nikolić", "Đorđe Đorđević"]}
        no_crash(f"KPI tab '{tab}' renders", run(state=state, values=values))


def scenario_oee():
    login("admin", "admin123")
    base = {"selected_module": "OEE", "oee_page_selector": "OEE Input"}
    run(state=base)
    H.session_state.update({"oee_selected_date": PREV, "oee_shift_selector": "1st shift (06:00-14:00)",
                            "oee_project_selector": "APP350", "oee_ok": 800, "oee_nok": 20, "oee_down": 30.0, "oee_org": 10.0})
    outcome = run(clicks=["submit:oee_input_form:💾 Save / Check existing record"], state=base)
    no_crash("OEE input saves", outcome)
    _, data = rows(OEE, "OEE_input")
    check("OEE row written", len(data) == 1, data)
    H.session_state.update({"oee_ok": 810, "oee_nok": 10, "oee_down": 20.0, "oee_org": 5.0})
    run(clicks=["submit:oee_input_form:💾 Save / Check existing record"], state=base)
    check("Duplicate OEE entry detected", "oee_pending_row" in H.session_state, H.messages("warning"))
    outcome = run(clicks=["oee_update_existing"], state=base)
    no_crash("OEE update", outcome)
    _, data = rows(OEE, "OEE_input")
    check("OEE update replaced the row (no duplicate)", len(data) == 1 and str(data[0][9]) in ("810", "810.0"), data)
    for page in ["Dashboard", "Daily", "Weekly", "Monthly", "Yearly", "Machine Ranking", "Raw Data"]:
        no_crash(f"OEE page '{page}' renders", run(state={"selected_module": "OEE", "oee_page_selector": page}))


def scenario_bn():
    login("bojan", "b123")
    base = {"selected_module": "Bottleneck"}
    run(state=base)
    H.session_state.update({"bn_entry_date": TODAY, "bn_entry_project": "APP350", "bn_entry_machine": "Line 1"})
    run(state=base)
    key = [k for k in H.session_state if k.startswith("bn_station_")]
    for k in key:
        H.session_state[k] = "OP100"
    for k in [k for k in H.session_state if k.startswith("bn_value_")]:
        H.session_state[k] = 14.0
    outcome = run(clicks=["save_bn_entry"], state=base)
    no_crash("BN save", outcome)
    check("BN saved", any("successfully saved" in m for m in H.messages("success")), H.log[-10:])
    run(clicks=["save_bn_entry"], state=base)
    check("BN duplicate detected (date compared as a real date)", "bn_pending_update" in H.session_state)
    run(clicks=["bn_duplicate_confirm"], state={**base, "bn_duplicate_choice": "Update existing BN"})
    _, data = rows(BND, "BN_RECORDS")
    app_rows = [r for r in data if r[1] == "APP"]
    check("BN update kept one row", len(app_rows) == 1, data)
    result = app()["sync_bn_forms_to_records"]()
    _, data = rows(BND, "BN_RECORDS")
    form_rows = [r for r in data if r[1] == "FORM"]
    check("BN Forms row with decimal comma imported", len(form_rows) == 1 and float(form_rows[0][7]) == 12.5, (result, form_rows))
    app()["sync_bn_forms_to_records"]()
    _, data = rows(BND, "BN_RECORDS")
    check("BN Forms sync is idempotent", len([r for r in data if r[1] == "FORM"]) == 1)
    for tab_state in [{}]:
        no_crash("BN module renders", run(state=base))


def scenario_line_verification_and_admin():
    login("admin", "admin123")
    outcome = run(state={"selected_module": "Line Verification / Dummy"})
    no_crash("Line Verification renders", outcome)
    df, _ = app()["prepare_line_verification_data"](app()["load_line_verification_raw"]()[0])
    check("Line Verification keeps both dates (05.06 and 15.06)",
          sorted(df["Date"].dt.strftime("%d.%m").tolist()) == ["05.06", "15.06"], df["Date"].tolist())
    no_crash("Administration renders", run(state={"selected_module": "Administration"}))


def scenario_automation_and_missing_time():
    # New technician without any entry for the previous workday
    sheet(KPI, "Technicians").values.append(
        ["TECH-000005", "Ivan Ivić", "ivan", "Tehničar", "Projekti", "ivan@example.com", "YES", "", "YES", "YES", "YES", "YES", "NO"])
    st.reset_all_caches()
    engine_module.clear_google_sheets_read_cache()
    new_browser()
    H.query = {"automation": "1"}
    outcome = run()
    no_crash("Automation route runs without AUTOMATION_TOKEN", outcome)
    check("Automation reports completion", any("Automation checks completed" in m for m in H.messages("success")))
    g = app()
    mails_before = len(SENT_MAIL)
    result = g["run_missing_work_time_check"](force=True)
    check("Missing-time check flags only the technician without entries",
          result.get("missing") == ["Ivan Ivić"], result)
    _, missing_rows = rows(KPI, "MISSING_WORK_TIME")
    check("Missing date logged once", len(missing_rows) == 1 and missing_rows[0][2] == "Ivan Ivić", missing_rows)
    check("Missing-time e-mail sent", len(SENT_MAIL) > mails_before)
    again = g["run_missing_work_time_check"](force=True)
    _, missing_rows = rows(KPI, "MISSING_WORK_TIME")
    check("Second run does not resend or duplicate", again.get("status") == "already_sent" and len(missing_rows) == 1, again)
    check("Supervisor never reported missing", "Ana Anić" not in (result.get("missing") or []))
    reminder = g["run_open_task_reminder_check"](force=True)
    check("Open-task reminder check runs", reminder.get("status") in ("sent", "all_closed", "weekend", "no_tasks", "not_sent"), reminder)
    bn = g["run_missing_bn_check"](force=True)
    check("Missing BN check runs", bn.get("status") in ("sent", "all_complete", "weekend", "not_sent"), bn)

    # Evaluation shows the penalty for Ivan
    login("admin", "admin123")
    penalty = app()["load_missing_entry_penalty_log"]("Ivan Ivić")
    check("Evaluation penalty counts the missing day", not penalty.empty and int(penalty["Unjustified Missing Entries"].sum()) == 1, penalty.to_dict("records"))

    # Token configured in Streamlit but not supplied -> login page (protected)
    SECRETS["AUTOMATION_TOKEN"] = "tok"
    H.secrets = SECRETS
    new_browser()
    H.query = {"automation": "1"}
    run()
    check("With AUTOMATION_TOKEN configured, a request without it is rejected",
          not any("Automation checks completed" in m for m in H.messages("success")))
    SECRETS.pop("AUTOMATION_TOKEN")


def scenario_google_quota_errors():
    gspread.QUOTA["fail_every"] = 5  # every 5th Google call returns HTTP 429
    try:
        login("bojan", "b123")
        no_crash("Work Tickets under Google 429 errors", run(state={"selected_module": "My Tasks", "work_tickets_view": "Kanban Board"}))
        login("admin", "admin123")
        no_crash("KPI under Google 429 errors", run(state={"selected_module": "KPI Process", "kpi_selected_tab": "Dashboard", "kpi_selected_tab_radio": "Dashboard"}))
        no_crash("OEE under Google 429 errors", run(state={"selected_module": "OEE", "oee_page_selector": "Dashboard"}))
    finally:
        gspread.QUOTA["fail_every"] = 0


def scenario_every_work_ticket_view():
    for user, password, module in (("admin", "admin123", "Work Tickets"), ("djordje", "d123", "My Tasks")):
        login(user, password)
        for view in ["Kanban Board", "New Task", "Task Activity"]:
            outcome = run(state={"selected_module": module, "work_tickets_view": view})
            no_crash(f"{user}: Work Tickets '{view}' renders", outcome)


def scenario_global_refresh():
    login("admin", "admin123")
    outcome = run(clicks=["refresh_all"], state={"selected_module": "KPI Process"})
    no_crash("Global refresh keeps the user logged in", outcome)
    check("Still authenticated after refresh", H.session_state.get("authenticated") is True)


def scenario_admin_writes_and_delete():
    login("admin", "admin123")
    base = {"selected_module": "KPI Process", "kpi_selected_tab": "Admin Panel", "kpi_selected_tab_radio": "Admin Panel",
            "admin_technician_mode": "Add new technician"}
    run(state=base)
    form_key = "Add_new_technician"
    H.session_state.update({f"admin_technician_name_{form_key}": "Nikola Novi", f"admin_email_{form_key}": "nikola@example.com"})
    outcome = run(clicks=["admin_save_technician"], state=base)
    no_crash("Admin Panel adds a technician", outcome)
    header, data = rows(KPI, "Technicians")
    check("New technician saved with an ID", any(r[1] == "Nikola Novi" and r[0].startswith("TECH-") for r in data), data[-1:])

    base = {"selected_module": "Administration", "admin_user_mode": "Add new user"}
    run(state=base)
    form_suffix = "Add_new_user"
    values = {"Username": "nikola", "Password": "n123", "Full_Name": "Nikola Novi", "Technician_ID": "TECH-000006", "Email": "nikola@example.com"}
    outcome = run(clicks=[f"submit:user_admin_form_{form_suffix}:Save User"], state=base, values=values)
    no_crash("Administration adds a user", outcome)
    header, data = rows(AUTH, "User&Password")
    added = [r for r in data if r[0] == "nikola"]
    check("New user saved with hashed password", added and added[0][1].startswith("pbkdf2_sha256$"), added)

    # Delete a task (admin) removes the task and only its own activities
    login("admin", "admin123")
    header, data = rows(KPI, "TASKS")
    before_tasks = len(data)
    task_id = dict(zip(header, data[0]))["Task_ID"]
    _, acts_before = rows(KPI, "TASK_ACTIVITY")
    state = {"selected_module": "Work Tickets", "work_tickets_view": "Kanban Board"}
    run(state=state)
    delete_keys = [k for k, _ in [(w[1], w[0]) for w in H.widgets_seen] if k and k.startswith("confirm_delete_task_")]
    if delete_keys:
        H.session_state[delete_keys[0]] = True
        suffix = delete_keys[0].replace("confirm_delete_task_", "")
        outcome = run(clicks=[f"delete_task_btn_{suffix}"], state=state)
        no_crash("Admin deletes a task", outcome)
        _, data_after = rows(KPI, "TASKS")
        check("Exactly one task deleted", len(data_after) == before_tasks - 1, (before_tasks, len(data_after)))


def scenario_parallel_sync_no_duplicates():
    import threading
    login("admin", "admin123")
    g = app()
    sheet(KPI, "Form Responses 1").values.append(
        [f"{PREV_TXT} 15:00:00", "Bojan Nikolić", "Proizvodnja", "Paralelno", PREV_TXT, "14:00", "15:00"])
    engine_module.clear_google_sheets_read_cache()
    _, before = rows(ALL, "all_activities")
    errors = []

    def worker():
        try:
            g["sync_all_activities"](force=True)
        except BaseException as exc:  # session_state is shared in the fake, that is fine here
            errors.append(repr(exc))

    g["mark_activity_sync_needed"]()
    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    _, after = rows(ALL, "all_activities")
    source_ids = [r[2] for r in after]
    check("Parallel syncs add the new entry exactly once", len(after) == len(before) + 1 and len(source_ids) == len(set(source_ids)),
          (len(before), len(after), errors))


def scenario_us_locale_forms_repair():
    """Forms sheet in US locale: rows imported by the OLD version with swapped dates are repaired in place."""
    import activity_data_layer as adl
    login("admin", "admin123")
    form = sheet(KPI, "Form Responses 1")
    us_row = ["10/23/2026 9:00:00", "Marko Marković", "Proizvodnja", "US datum", "10/5/2026", "8:00:00", "9:00:00"]
    form.values.append(us_row)
    legacy_sid = adl.stable_id("FORM", us_row[0], us_row[1], adl._legacy_date_text(us_row[4]),
                               adl._legacy_time_text(us_row[5]), adl._legacy_time_text(us_row[6]), us_row[3])
    sheet(ALL, "all_activities").values.append(
        [adl.stable_id("ACT", legacy_sid), "FORM", legacy_sid, "TECH-000003", "Marko Marković", "10.05.2026",
         "08:00", "09:00", 60, 60, "Proizvodnja", "US datum", "", "old"])
    engine_module.clear_google_sheets_read_cache()
    _, before = rows(ALL, "all_activities")
    app()["mark_activity_sync_needed"]()
    result = app()["sync_all_activities"](force=True)
    _, after = rows(ALL, "all_activities")
    fixed = [r for r in after if r[2] == legacy_sid]
    check("US-locale Forms detected", result.get("forms_date_order") == "mdy", result.get("forms_date_order"))
    check("Old swapped date repaired in place (no duplicate)",
          len(fixed) == 1 and app()["_normalize_date_string"](fixed[0][5]) == "05.10.2026" and len(after) == len(before),
          (fixed, len(before), len(after)))
    form.values.remove(us_row)


def scenario_remember_me():
    login("bojan", "b123")
    cookie = dict(stx.COOKIES)
    check("Remember-me cookie created", bool(cookie))
    H.reset_browser()
    stx.COOKIES.update(cookie)
    outcome = run()
    if not H.session_state.get("authenticated"):
        outcome = run()
    check("Remember me restores the session", H.session_state.get("authenticated") is True)


def main():
    H.secrets = SECRETS
    build_store()
    st.reset_all_caches()
    scenarios = [
        scenario_login_and_password_migration,
        scenario_initialize_all_activities,
        scenario_technician_self_task,
        scenario_admin_task_and_activity,
        scenario_kpi_sees_everything,
        scenario_oee,
        scenario_bn,
        scenario_line_verification_and_admin,
        scenario_every_work_ticket_view,
        scenario_automation_and_missing_time,
        scenario_admin_writes_and_delete,
        scenario_parallel_sync_no_duplicates,
        scenario_us_locale_forms_repair,
        scenario_remember_me,
        scenario_google_quota_errors,
        scenario_global_refresh,
    ]
    started = time.perf_counter()
    for scenario in scenarios:
        print(f"\n=== {scenario.__name__} ===")
        try:
            scenario()
        except Exception as exc:  # a crash in the harness is also a failure
            check(f"{scenario.__name__} completed", False, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed in {time.perf_counter() - started:.1f}s; "
          f"Google calls: reads={gspread.QUOTA['reads']} writes={gspread.QUOTA['writes']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
