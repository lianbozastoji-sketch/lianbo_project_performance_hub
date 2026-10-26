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
    if state and "kpi_selected_tab" in state:
        # emulate the user clicking the KPI page: reset the two-level nav widgets
        for key in [k for k in H.session_state if k == "kpi_section_radio" or k.startswith("kpi_page_radio_")]:
            H.session_state.pop(key, None)
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
        check(f"KPI navigation opened '{tab}'", H.session_state.get("kpi_selected_tab") == tab, H.session_state.get("kpi_selected_tab"))
        expected_chart = {"Pareto": "kpi_pareto_hours", "Kategorije": "kpi_category_pie", "Dashboard": "kpi_dashboard_hours"}.get(tab)
        if expected_chart:
            check(f"KPI '{tab}' shows its chart", expected_chart in H.messages("chart"), H.messages("chart"))


def scenario_oee():
    login("admin", "admin123")
    base = {"selected_module": "OEE", "oee_page_selector": "OEE Input"}
    run(state=base)
    H.session_state.update({"oee_selected_date": PREV, "oee_shift_selector": "1st shift (06:00-14:00)",
                            "oee_project_selector": "APP350", "oee_ok": 800, "oee_nok": 20, "oee_down": 30.0, "oee_org": 10.0})
    run(state=base)
    check("Downtime reported in the technicians' form is pulled into the OEE input",
          any("već prijavljeno 30 min zastoja" in m for m in H.messages("info")), H.messages("info"))
    outcome = run(clicks=["submit:oee_input_form:💾 Save / Check existing record"], state=base)
    _, data = rows(OEE, "OEE_input")
    check("Save is refused while 10 min of org. loss have no cause",
          len(data) == 0 and any("Org. gubici: uzrok nedostaje za 10" in m for m in H.messages("error")), H.messages("error"))
    H.session_state["oee_alloc_editor"] = pd.DataFrame([{"Uzrok": "Čekanje materijala", "Minuta": 10}])
    outcome = run(clicks=["submit:oee_input_form:💾 Save / Check existing record"], state=base)
    no_crash("OEE input saves", outcome)
    _, data = rows(OEE, "OEE_input")
    check("OEE row written", len(data) == 1, data)
    _, events = rows(OEE, "DOWNTIME_EVENTS")
    check("Causes from the OEE input are stored", [(e[7], float(e[8]), e[13]) for e in events] == [("Čekanje materijala", 10.0, "OEE_UNOS")],
          events)
    H.session_state.update({"oee_ok": 810, "oee_nok": 10, "oee_down": 35.0, "oee_org": 5.0})
    H.session_state["oee_alloc_editor"] = pd.DataFrame([{"Uzrok": "Mašinski kvar", "Minuta": 5}, {"Uzrok": "Nema operatera", "Minuta": 5}])
    run(clicks=["submit:oee_input_form:💾 Save / Check existing record"], state=base)
    check("Duplicate OEE entry detected", "oee_pending_row" in H.session_state, H.messages("warning") + H.messages("error"))
    outcome = run(clicks=["oee_update_existing"], state=base)
    no_crash("OEE update", outcome)
    _, data = rows(OEE, "OEE_input")
    check("OEE update replaced the row (no duplicate)", len(data) == 1 and str(data[0][9]) in ("810", "810.0"), data)
    _, events = rows(OEE, "DOWNTIME_EVENTS")
    check("Updating the shift replaces its causes (no double counting)",
          sorted((e[7], float(e[8])) for e in events) == [("Mašinski kvar", 5.0), ("Nema operatera", 5.0)], events)
    for page in ["Dashboard", "Daily", "Weekly", "Monthly", "Yearly", "Machine Ranking", "Raw Data"]:
        no_crash(f"OEE page '{page}' renders", run(state={"selected_module": "OEE", "oee_page_selector": page}))


OEE_DRILL_ROWS = [
    # Datum, Machine, CT_s, open, down, org, ok, nok, target
    ("19.10.2026", "RL 1", 30, 440, 30, 10, 700, 20, 760),
    ("19.10.2026", "RL 2", 28, 440, 60, 0, 650, 30, 800),
    ("20.10.2026", "RL 1", 30, 440, 15, 0, 800, 10, 850),
    ("22.10.2026", "RL 1", 30, 440, 0, 0, 159, 8, 167),
    ("14.10.2026", "RL 1", 30, 440, 20, 5, 780, 12, 830),
    ("15.09.2026", "RL 1", 30, 440, 40, 0, 700, 50, 840),
]


def _click_chart(key, x, customdata=None, y=None):
    point = {"x": x, "y": y, "point_index": 0, "curve_number": 0}
    if customdata is not None:
        point["customdata"] = customdata
    H.session_state.update({key: {"selection": {"points": [point], "point_indices": [0], "box": [], "lasso": []}}})


def _drill_cards():
    return [m for m in H.messages("markdown") if 'class="drill-card"' in m]


def scenario_oee_drilldown():
    global run
    base_run = run
    seen_alerts = []

    def run(*args, **kwargs):  # noqa: F811  (collect every error/warning shown on OEE pages)
        outcome = base_run(*args, **kwargs)
        seen_alerts.extend(("error", m) for m in H.messages("error"))
        seen_alerts.extend(("warning", m) for m in H.messages("warning"))
        return outcome

    try:
        _scenario_oee_drilldown_body()
    finally:
        run = base_run
    check("No error or warning shown on any OEE page during drill-down", not seen_alerts, seen_alerts[:6])


def _scenario_oee_drilldown_body():
    from plotly import _dummy as plotly_fake
    problems_before = len(plotly_fake.PROBLEMS)
    ws = sheet(OEE, "OEE_input")
    existing = ws.get_all_values()
    if len(existing) > 1:  # start from a clean OEE sheet (independent of today's date)
        ws.delete_rows(2, len(existing))
    ws.append_rows([
        [d, "", "", "APP350", "Inspection Rotor", m, ct, op, 1, ok, nok, ok + nok, down, org, target, "sim", "All shifts", ""]
        for d, m, ct, op, down, org, ok, nok, target in OEE_DRILL_ROWS
    ])
    g = app()
    g["load_oee_input"].clear()
    login("admin", "admin123")
    df = app()["load_oee_input"]()[0]
    df = df[df["Datum"] >= pd.Timestamp(2026, 9, 1)]
    df = df[df["Datum"] <= pd.Timestamp(2026, 10, 31)]
    g = app()

    # --- calendar slots ------------------------------------------------------
    week = df[(df["Godina"] == 2026) & (df["Week"] == 43)]
    _, slots = g["oee_period_slots"](week, "day")
    check("Weekly chart shows the whole CW (Mon-Sun) incl. days without entries",
          [x["label"] for x in slots] == ["Pon 19.10", "Uto 20.10", "Sre 21.10", "Čet 22.10", "Pet 23.10", "Sub 24.10", "Ned 25.10"]
          and [x["has"] for x in slots] == [True, True, False, True, False, False, False], [(x["label"], x["has"]) for x in slots])
    october = df[df["Mesec"] == 10]
    _, slots = g["oee_period_slots"](october, "week")
    check("Monthly chart shows every week of the month", [x["label"] for x in slots] == ["CW40", "CW41", "CW42", "CW43", "CW44"],
          [x["label"] for x in slots])
    _, slots = g["oee_period_slots"](df, "month")
    check("Yearly chart shows all 12 months", len(slots) == 12 and [x["has"] for x in slots][8:10] == [True, True],
          [(x["label"], x["has"]) for x in slots])

    # --- card numbers (checked against hand calculation) ---------------------
    day = df[df["Datum"] == pd.Timestamp(2026, 10, 19)]
    card = g["oee_detail_card_data"](day, "a", "Machine_OEE_CT_%")
    raw = card["raw"]
    expected_a = (880 - 90 - 10) / (880 - 10) * 100
    check("Availability card: downtime 90 min, org. loss 10 min, run 780 min",
          (raw["down"], raw["org"], raw["run"]) == (90, 10, 780) and abs(card["value"] - expected_a) < 1e-6, raw)
    check("Availability card names the machine with most lost time first",
          [m for m, _, _ in card["impact"]][:2] == ["RL 2", "RL 1"], card["impact"])
    card_q = g["oee_detail_card_data"](day, "q", "Machine_OEE_CT_%")
    check("Quality card: OK 1350, NOK 50, total 1400",
          (card_q["raw"]["ok"], card_q["raw"]["nok"], card_q["raw"]["total"]) == (1350, 50, 1400)
          and abs(card_q["value"] - 1350 / 1400 * 100) < 1e-6 and card_q["impact"][0][0] == "RL 2", card_q["raw"])
    card_p = g["oee_detail_card_data"](day, "p", "Machine_OEE_CT_%")
    ideal = 720 * 30 / 60 + 680 * 28 / 60
    check("Performance card: total 1400 vs target 1560 (-160), CT performance = ideal/run",
          card_p["tiles"][0]["value"] == "1.400" and card_p["tiles"][1]["value"] == "1.560"
          and card_p["tiles"][2]["value"] == "-160 kom" and abs(card_p["value"] - ideal / 780 * 100) < 1e-6, card_p["tiles"])
    card_o = g["oee_detail_card_data"](day, "oee", "Machine_OEE_CT_%")
    check("OEE card = A x P x Q", abs(card_o["value"] - card_o["raw"]["a"] * card_o["raw"]["p"] * card_o["raw"]["q"] / 10000) < 1e-6,
          card_o["raw"])
    card_pt = g["oee_detail_card_data"](day, "p", "Machine_OEE_Target_%")
    check("Target variant: performance = OK / target", abs(card_pt["value"] - 1350 / 1560 * 100) < 1e-6, card_pt["formula"])

    # --- Weekly page: click a day -> card -> drill into Daily -> back --------
    weekly = {"selected_module": "OEE", "oee_page_selector": "Weekly", "oee_weekly_selected_week": (2026, 43)}
    outcome = run(state=weekly)
    no_crash("Weekly OEE with drill-down renders", outcome)
    fig = H.figures.get("oee_weekly_clean_drill_chart_oee")
    check("Weekly trend is a line when several days have data", fig is not None and fig.data[1].kind == "Scatter",
          getattr(fig, "data", None))
    check("Default card = latest day with data (Čet 22.10)", any("Čet 22.10.2026" in m for m in _drill_cards()), _drill_cards())
    _click_chart("oee_weekly_clean_drill_chart_oee", "Uto 20.10", "2026-10-20")
    no_crash("Click on a day", run(state={"selected_module": "OEE"}))
    check("Click selects the day", H.session_state.get("oee_weekly_clean_drill_sel") == "2026-10-20",
          H.session_state.get("oee_weekly_clean_drill_sel"))
    check("Card for the clicked day is shown", any("Uto 20.10.2026 · OEE" in m for m in _drill_cards()), _drill_cards())
    H.session_state.update({"oee_weekly_clean_drill_metric": "a"})
    no_crash("Switch chart to Availability", run(state={"selected_module": "OEE"}))
    check("Availability card for the selected day", any("Uto 20.10.2026 · Dostupnost" in m for m in _drill_cards()), _drill_cards())
    outcome = run(clicks=["oee_weekly_clean_drill_open"], state={"selected_module": "OEE"})
    no_crash("Drill down from week to day", outcome)
    check("Drill-down opens the Daily page for that day",
          H.session_state.get("oee_page_selector") == "Daily"
          and H.session_state.get("oee_daily_selected_date") == dt.date(2026, 10, 20), 
          (H.session_state.get("oee_page_selector"), H.session_state.get("oee_daily_selected_date")))
    check("Drill-down keeps the chosen metric", H.session_state.get("oee_daily_clean_drill_metric") == "a")
    check("Daily page shows the availability card", any("Dostupnost" in m for m in _drill_cards()), _drill_cards())
    check("Breadcrumb remembers the week", [c["label"] for c in H.session_state.get("oee_drill_trail", [])] == ["2026-CW43"],
          H.session_state.get("oee_drill_trail"))
    _click_chart("oee_daily_clean_daily_components_bar", "Q-rate")
    no_crash("Click Q-rate bar on Daily", run(state={"selected_module": "OEE"}))
    check("Clicking the Q-rate bar opens the quality card", H.session_state.get("oee_daily_clean_drill_metric") == "q"
          and any("Kvalitet" in m for m in _drill_cards()), _drill_cards())
    outcome = run(clicks=["oee_drill_crumb_0"], state={"selected_module": "OEE"})
    no_crash("Breadcrumb back to the week", outcome)
    check("Back returns to the same CW", H.session_state.get("oee_page_selector") == "Weekly"
          and H.session_state.get("oee_weekly_selected_week") == (2026, 43), H.session_state.get("oee_weekly_selected_week"))

    # --- one day with data -> bar instead of a lonely point ------------------
    no_crash("CW42 (one day) renders", run(state={**weekly, "oee_weekly_selected_week": (2026, 42)}))
    fig = H.figures.get("oee_weekly_clean_drill_chart_oee")
    check("Single day is drawn as a bar, not a lonely point", fig is not None and fig.data[1].kind == "Bar")

    # --- Yearly -> Monthly -> Weekly ----------------------------------------
    yearly = {"selected_module": "OEE", "oee_page_selector": "Yearly", "oee_yearly_selected_year": 2026}
    no_crash("Yearly OEE renders", run(state=yearly))
    _click_chart("oee_yearly_clean_drill_chart_oee", "Sep", "2026-09")
    no_crash("Click September", run(state={"selected_module": "OEE"}))
    check("Card for September", any("Sep 2026 · OEE" in m for m in _drill_cards()), _drill_cards())
    no_crash("Drill year -> month", run(clicks=["oee_yearly_clean_drill_open"], state={"selected_module": "OEE"}))
    check("Monthly page opened for 2026-09", H.session_state.get("oee_page_selector") == "Monthly"
          and H.session_state.get("oee_monthly_selected_month") == (2026, 9), H.session_state.get("oee_monthly_selected_month"))
    H.session_state.update({"oee_monthly_selected_month": (2026, 10)})
    no_crash("Monthly October", run(state={"selected_module": "OEE"}))
    _click_chart("oee_monthly_clean_drill_chart_oee", "CW43", "2026-W43")
    no_crash("Click CW43", run(state={"selected_module": "OEE"}))
    check("Sub-chart shows the days of the clicked week", "oee_monthly_clean_drill_sub" in H.messages("chart"), H.messages("chart"))
    no_crash("Drill month -> week", run(clicks=["oee_monthly_clean_drill_open"], state={"selected_module": "OEE"}))
    check("Weekly page opened for CW43", H.session_state.get("oee_page_selector") == "Weekly"
          and H.session_state.get("oee_weekly_selected_week") == (2026, 43))
    check("Breadcrumb: year -> month", [c["label"] for c in H.session_state.get("oee_drill_trail", [])] == ["2026", "2026-10"],
          H.session_state.get("oee_drill_trail"))
    no_crash("Manual page change clears breadcrumb", run(state={"selected_module": "OEE", "oee_page_selector": "Raw Data"}))
    check("Breadcrumb cleared after manual navigation", not H.session_state.get("oee_drill_trail"))

    # --- Machine ranking -----------------------------------------------------
    ranking = {"selected_module": "OEE", "oee_page_selector": "Machine Ranking", "oee_ranking_date_filter": dt.date(2026, 10, 19)}
    no_crash("Machine Ranking renders", run(state=ranking))
    fig = H.figures.get("oee_machine_ranking_filtered_chart")
    check("Ranking is horizontal and its height follows the machine count",
          fig is not None and fig.data[0].get("orientation") == "h" and fig.layout.get("height") == 78 + 44 * 2,
          getattr(fig, "layout", None))
    label = "APP350 · Inspection Rotor · RL 2"
    _click_chart("oee_machine_ranking_filtered_chart", None, label, y="#2  " + label)
    no_crash("Click a machine in the ranking", run(state={"selected_module": "OEE"}))
    check("Ranking click opens that machine's card", any("RL 2 · 19.10.2026" in m for m in _drill_cards()), _drill_cards())
    no_crash("Dashboard renders", run(state={"selected_module": "OEE", "oee_page_selector": "Dashboard"}))
    for page in ["Daily", "Weekly", "Monthly", "Yearly"]:
        no_crash(f"OEE '{page}' with Machine=RL 1 renders",
                 run(state={"selected_module": "OEE", "oee_page_selector": page,
                            f"oee_{page.lower()}_inline_machine": "RL 1"}))
    check("Every OEE chart property is valid plotly", len(plotly_fake.PROBLEMS) == problems_before,
          plotly_fake.PROBLEMS[problems_before:][:10])


def _alerts():
    return [("error", m) for m in H.messages("error")] + [("uncaught", m[:300]) for m in H.messages("uncaught")]


def scenario_v11_downtime_report():
    login("admin", "admin123")
    base = {"selected_module": "OEE", "oee_page_selector": "Downtime"}
    no_crash("Downtime report page renders", run(state=base))
    before = len(rows(OEE, "DOWNTIME_EVENTS")[1])
    no_crash("Start downtime", run(clicks=["dt_start"], state=base))
    head, data = rows(OEE, "DOWNTIME_EVENTS")
    running = [r for r in data if r[head.index("Status")] == "U TOKU"]
    check("Running downtime stored immediately (not lost if the phone is closed)", len(data) == before + 1 and len(running) == 1, data[-1:])
    event_id = running[0][0] if running else ""
    H.session_state[f"dt_cause_{event_id}"] = "Električni kvar"
    no_crash("Stop downtime with cause", run(clicks=[f"dt_stop_{event_id}"], state={"selected_module": "OEE"}))
    head, data = rows(OEE, "DOWNTIME_EVENTS")
    done = [r for r in data if r[0] == event_id]
    check("Stopped downtime has cause, end time and minutes",
          done and done[0][head.index("Status")] == "ZAVRŠEN" and done[0][head.index("Cause")] == "Električni kvar"
          and float(done[0][head.index("Minutes")]) >= 1, done)
    H.session_state.update({"dt_manual_start": "8:10", "dt_manual_end": "8.25", "dt_manual_cause": "Zamena senzora / dela"})
    no_crash("Manual downtime entry", run(clicks=["submit:dt_manual_form:Sačuvaj zastoj"], state={"selected_module": "OEE"}))
    head, data = rows(OEE, "DOWNTIME_EVENTS")
    check("Manual downtime saved with 15 min", any(r[head.index("Cause")] == "Zamena senzora / dela" and float(r[head.index("Minutes")]) == 15
                                                   for r in data), data[-2:])
    check("No errors on the downtime page", not _alerts(), _alerts())


V11_EVENTS = [
    # Datum, Machine, Cause, Loss type, minutes
    ("19.10.2026", "RL 2", "Električni kvar", "Zastoj", 45),
    ("19.10.2026", "RL 2", "Mašinski kvar", "Zastoj", 15),
    ("19.10.2026", "RL 1", "Čekanje materijala", "Organizacioni gubitak", 10),
    ("19.10.2026", "RL 1", "Zamena senzora / dela", "Zastoj", 30),
    ("14.10.2026", "RL 1", "Zamena senzora / dela", "Zastoj", 8),
    ("14.10.2026", "RL 1", "Zamena senzora / dela", "Zastoj", 2.5),
    ("14.10.2026", "RL 1", "Zamena senzora / dela", "Zastoj", 9),
    ("15.09.2026", "RL 1", "Zamena senzora / dela", "Zastoj", 8),
    ("15.09.2026", "RL 1", "Zamena senzora / dela", "Zastoj", 3),
    ("15.09.2026", "RL 1", "Električni kvar", "Zastoj", 37),
]


def scenario_v11_manager_view():
    login("admin", "admin123")
    g = app()
    ws = sheet(OEE, "DOWNTIME_EVENTS")
    head = ws.get_all_values()[0]
    for i, (day, machine, cause, loss, minutes) in enumerate(V11_EVENTS):
        record = {"Event_ID": f"SIM-{i}", "Datum": day, "Shift": "1st", "Project": "APP350", "Process": "Inspection Rotor",
                  "Machine": machine, "Loss_Type": loss, "Cause": cause, "Minutes": minutes, "Status": "ZAVRŠEN", "Source": "PRIJAVA"}
        ws.append_rows([[record.get(h, "") for h in head]])
    g["load_app_downtime_events"].clear()
    g["save_oee_settings"]([("CENA_KOMADA", "APP350", "8"), ("OPIS_PROCESA", "APP350|Inspection Rotor", "Završna kontrola rotora")])
    weekly = {"selected_module": "OEE", "oee_page_selector": "Weekly", "oee_weekly_selected_week": (2026, 43)}
    no_crash("Weekly page with manager summary", run(state=weekly))
    md = " ".join(H.messages("markdown"))
    check("Summary sentence for managers", "OEE mašine ove nedelje je" in md
          and ("bolje nego u prethodnom periodu" in md or "slabije nego u prethodnom periodu" in md),
          [m[:200] for m in H.messages("markdown") if "hl-box" in m])
    check("Data coverage is visible (3 of 5 workdays)", "Uneto 3 od 5 radnih dana" in md and "Nedostaje: Sre 21.10, Pet 23.10" in md)
    check("Tiles show change vs previous week", "od prethodnog perioda" in md)
    check("Lost pieces, hours and value (price from settings)", "Manje komada od targeta" in md and "Vrednost gubitka" in md and "€" in md)
    check("Process description for people far from the line", "Završna kontrola rotora" in " ".join(H.messages("caption")))
    check("Pareto of causes", "Zašto smo gubili vreme" in md and "Električni kvar" in md and "Bez uzroka" in md)
    check("Machine ranking shows volume", any("kom ·" in str(t) for t in (H.figures.get("oee_weekly_clean_machine_rank").data[0].get("text") or [])))
    check("Glossary available", "Šta znače pojmovi?" in H.messages("expander"), H.messages("expander"))
    H.session_state.update({"oee_weekly_clean_drill_metric": "a"})
    _click_chart("oee_weekly_clean_drill_chart_a", "Pon 19.10", "2026-10-19")
    no_crash("Availability card with causes of the clicked day", run(state={"selected_module": "OEE"}))
    check("Clicked day lists its causes", any("Uzroci · Pon 19.10.2026" in m for m in H.messages("markdown")))
    H.session_state.update({"oee_weekly_clean_action_cause": "Električni kvar", "oee_weekly_clean_action_machine": "RL 2",
                            "oee_weekly_clean_action_title": "zameniti napojni kabl", "oee_weekly_clean_action_owner": "Bojan Nikolić"})
    no_crash("Create action from a loss", run(clicks=["submit:oee_weekly_clean_action_form:Sačuvaj akciju"], state={"selected_module": "OEE"}))
    head, data = rows(KPI, "TASKS")
    action = [r for r in data if str(r[head.index("Task Title") if "Task Title" in head else head.index("Task_Title")]).startswith("[OEE]")]
    check("Action saved in Work Tickets with link to the loss",
          action and "OEE|APP350|Inspection Rotor|RL 2|Električni kvar" in action[0], action)
    no_crash("Action list renders", run(state={"selected_module": "OEE"}))
    actions = app()["load_oee_actions"]("APP350", "Inspection Rotor")
    check("Action visible next to the losses", len(actions) == 1 and actions.iloc[0]["_machine"] == "RL 2"
          and actions.iloc[0]["_cause"] == "Električni kvar" and bool(actions.iloc[0]["_open"]), actions.to_dict("records")[:1])
    check("No errors on the manager view", not _alerts(), _alerts())


def scenario_v11_uprava_and_email():
    login("bojan", "b123")
    no_crash("Uprava page for a normal user with OEE access", run(state={"selected_module": "Uprava", "uprava_week": (2026, 43)}))
    md = " ".join(H.messages("markdown"))
    check("Uprava: one sentence for the whole factory", "Fabrika je u CW43 radila sa OEE" in md, md[:300])
    check("Uprava: project card + 13-week trend", "mg-card" in md and any(k.startswith("uprava_spark_") for k in H.messages("chart")))
    check("Uprava: top losses with action status", any("(" in m for m in H.messages("dataframe")))
    no_crash("Open the week from Uprava", run(clicks=["uprava_open_app350_inspection_rotor"], state={"selected_module": "Uprava"}))
    check("Card button opens OEE weekly for that project", H.session_state.get("selected_module") == "OEE"
          and H.session_state.get("oee_weekly_selected_week") == (2026, 43), H.session_state.get("selected_module"))
    check("No errors on Uprava", not _alerts(), _alerts())
    g = app()
    g["save_oee_settings"]([("UPRAVA_EMAIL", "", "uprava@example.com, direktor@example.com"), ("UPRAVA_EMAIL_AKTIVNO", "", "YES")])
    before = len(SENT_MAIL)
    result = g["run_weekly_management_email"](now=dt.datetime(2026, 10, 26, 7, 30))
    mails = SENT_MAIL[before:]
    check("Weekly e-mail on Monday 07:30 to both recipients", result.get("status") == "sent" and len(mails) == 2, result)
    check("E-mail subject and body are plain and complete",
          mails and mails[0]["subject"].startswith("OEE CW43") and "NAJVEĆI GUBICI" in mails[0]["body"] and "IWON" not in mails[0]["body"],
          mails[:1])
    again = g["run_weekly_management_email"](now=dt.datetime(2026, 10, 26, 9, 0))
    check("E-mail is not sent twice for the same week", again.get("status") == "already_sent", again)
    check("No e-mail on other days", g["run_weekly_management_email"](now=dt.datetime(2026, 10, 27, 9, 0)).get("status") == "not_due")


def scenario_v11_iwon_private():
    login("admin", "admin123")
    H.secrets.pop("IWON_USERS", None)
    g = app()
    check("IWON is not an OEE metric for anyone", "IWON_OEE_%" not in g["OEE_METRIC_OPTIONS"].values())
    no_crash("Admin without IWON access", run(state={"selected_module": "OEE", "oee_page_selector": "IWON"}))
    check("Admin without IWON_USERS cannot open IWON", H.session_state.get("oee_page_selector") != "IWON"
          and not any("IWON" in m for m in H.messages("caption")), H.session_state.get("oee_page_selector"))
    no_crash("Administration without IWON", run(state={"selected_module": "Administration"}))
    check("Administration has no IWON section", not any("IWON" in m for m in H.messages("markdown") + H.messages("caption")))

    H.secrets["IWON_USERS"] = ["admin"]
    targets = pd.DataFrame({"CW": list(range(1, 54)), "Target_OEE": [85.0 if 43 <= cw <= 50 else None for cw in range(1, 54)]})
    g["save_oee_iwon_target_grid"](2026, "APP350", "Inspection Rotor", targets, "admin")
    iwon = {"selected_module": "OEE", "oee_page_selector": "IWON", "iwon_p_year": 2026, "iwon_p_project": "APP350",
            "iwon_p_process": "Inspection Rotor", "iwon_p_from": 43, "iwon_p_to": 50, "iwon_p_weeks": 10}
    no_crash("IWON page for an allowed user", run(state=iwon))
    no_crash("Generate IWON CW43-CW50 (also future weeks)", run(clicks=["iwon_generate_btn"], state=iwon))
    head, data = rows(IWON, "IWON_COMPARE")
    weeks = sorted({int(r[head.index("CW")]) for r in data})
    check("Plan exists for every week, with or without data", weeks == list(range(43, 51)), weeks)
    future = [r for r in data if int(r[head.index("CW")]) == 50 and r[head.index("Machine")] == "GLOBAL"]
    check("Future week: plan + forecast, no actual yet", future and future[0][head.index("Actual_OEE")] == ""
          and abs(float(future[0][head.index("Plan_OEE")]) - 85) < 0.05 and future[0][head.index("Forecast_OEE")] != "", future)
    _, iwon_rows = rows(IWON, "OEE_IWON")
    check("OEE_IWON keeps its A:J layout for the existing comparison", len(iwon_rows) >= 8 * 3 and all(len(r) >= 10 for r in iwon_rows))
    count_before = len(data)
    no_crash("Generate again without replace", run(clicks=["iwon_generate_btn"], state=iwon))
    head, data = rows(IWON, "IWON_COMPARE")
    check("Existing plans are frozen (not changed)", len(data) == count_before and any("zamrznut" in m for m in H.messages("info")))
    no_crash("Generate with replace", run(clicks=["iwon_generate_btn"], state={**iwon, "iwon_p_replace": True, "iwon_p_from": 43, "iwon_p_to": 43}))
    _, history = rows(IWON, "IWON_PLAN_HISTORY")
    head, data = rows(IWON, "IWON_COMPARE")
    v2 = [r for r in data if int(r[head.index("CW")]) == 43]
    check("Replaced plan goes to history, new version 2", len(history) == 3 and all(str(r[head.index("Plan_Version")]) == "2" for r in v2), history[:1])
    compare = {"selected_module": "OEE", "oee_page_selector": "IWON", "iwon_c_year": 2026, "iwon_c_project": "APP350",
               "iwon_c_process": "Inspection Rotor"}
    no_crash("Refresh actual", run(clicks=["iwon_refresh_all"], state=compare))
    head, data = rows(IWON, "IWON_COMPARE")
    cw43 = [r for r in data if int(r[head.index("CW")]) == 43 and r[head.index("Machine")] == "GLOBAL"][0]
    check("Refresh fills actual and deviation for weeks with data", cw43[head.index("Actual_OEE")] != "" and cw43[head.index("Dev_Plan_OEE")] != "", cw43)
    check("Refresh never changes the frozen plan", str(cw43[head.index("Plan_Version")]) == "2")
    head, causes = rows(IWON, "IWON_CAUSE_PLAN")
    sensor = [r for r in causes if r[head.index("Cause")] == "Zamena senzora / dela" and int(r[head.index("CW")]) == 44]
    check("Per-cause targets from real downtime (sensor change: shorter)", sensor and sensor[0][head.index("Lever")] == "kraće"
          and sensor[0][head.index("Rating")] in ("realno", "izazovno", "nerealno", "bez promene"), causes[:2])
    no_crash("Comparison tab renders", run(state=compare))
    check("Comparison chart shown", "iwon_compare_chart" in H.messages("chart"))
    check("No errors on IWON", not _alerts(), _alerts())

    login("bojan", "b123")
    no_crash("Other user", run(state={"selected_module": "OEE", "oee_page_selector": "IWON"}))
    check("Other users never see IWON", H.session_state.get("oee_page_selector") != "IWON")
    for page in ["Weekly", "Dashboard", "Machine Ranking"]:
        run(state={"selected_module": "OEE", "oee_page_selector": page})
        visible = " ".join(H.messages("markdown") + H.messages("caption") + H.messages("subheader"))
        check(f"No IWON on OEE '{page}'", "IWON" not in visible)
    run(state={"selected_module": "Uprava"})
    check("No IWON on Uprava", "IWON" not in " ".join(H.messages("markdown") + H.messages("caption")))
    H.secrets.pop("IWON_USERS", None)


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
        scenario_oee_drilldown,
        scenario_v11_downtime_report,
        scenario_v11_manager_view,
        scenario_v11_uprava_and_email,
        scenario_v11_iwon_private,
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
    from plotly import _dummy as plotly_fake
    print("\n=== chart properties (all modules) ===")
    check("Every chart in every module uses valid plotly properties", not plotly_fake.PROBLEMS,
          sorted(set(plotly_fake.PROBLEMS))[:15])
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed in {time.perf_counter() - started:.1f}s; "
          f"Google calls: reads={gspread.QUOTA['reads']} writes={gspread.QUOTA['writes']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
