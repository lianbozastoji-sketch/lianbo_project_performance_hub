"""v9.9 regression tests for the "entry looks missing" bugs and the Sheets engine."""
import contextlib
import datetime as dt
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from activity_data_layer import (  # noqa: E402
    all_activities_to_kpi_raw,
    detect_slash_date_order,
    normalize_forms_rows_detailed,
    parse_date_value,
    parse_time_value,
    person_name_key,
)
from test_v9_3_logic import load_symbols  # noqa: E402


class DateTimeParsingTests(unittest.TestCase):
    def test_all_common_date_spellings(self):
        expected = dt.date(2026, 10, 23)
        for text in ["23.10.2026", "23.10.2026.", "23. 10. 2026.", "23/10/2026", "23-10-2026",
                     "23.10.26", "2026-10-23", "23.10.2026 08:30:00", 46318]:
            with self.subTest(text=text):
                self.assertEqual(parse_date_value(text).date(), expected)

    def test_day_month_never_swapped_for_dots(self):
        self.assertEqual(parse_date_value("05.06.2026").date(), dt.date(2026, 6, 5))

    def test_us_slash_column_detected(self):
        self.assertEqual(detect_slash_date_order(["10/23/2026 7:00:00", "6/5/2026"]), "mdy")
        self.assertIsNone(detect_slash_date_order(["23/10/2026", "5/6/2026"]))
        self.assertEqual(parse_date_value("6/5/2026", "mdy").date(), dt.date(2026, 6, 5))

    def test_time_spellings(self):
        for text, expected in [("8:30", dt.time(8, 30)), ("08:30:00", dt.time(8, 30)), ("8.30", dt.time(8, 30)),
                               ("8h30", dt.time(8, 30)), ("830", dt.time(8, 30)), ("8", dt.time(8, 0)),
                               ("8:30 PM", dt.time(20, 30)), (0.5, dt.time(12, 0))]:
            with self.subTest(text=text):
                self.assertEqual(parse_time_value(text), expected)
        self.assertIsNone(parse_time_value("25:99"))
        self.assertIsNone(parse_time_value("23.10.2026"))

    def test_person_key_ignores_order_case_and_diacritics(self):
        self.assertEqual(person_name_key("Nikolić Bojan"), person_name_key("bojan  NIKOLIC"))
        self.assertEqual(person_name_key("Đorđe Đorđević"), person_name_key("Djordje Djordjevic"))


class FormsImportTests(unittest.TestCase):
    def test_identity_is_stable_and_names_are_mapped(self):
        forms = pd.DataFrame([
            {"Timestamp": "22.10.2026 9:00:00", "Tehničar/Inženjer": "Djordjevic Djordje", "Kategorija rada": "Kvalitet",
             "Opis aktivnosti": "Kontrola", "Datum": "22.10.2026", "Vreme početka": "8:00:00", "Vreme završetka aktivnosti": "9:30"},
            {"Timestamp": "22.10.2026 9:10:00", "Tehničar/Inženjer": "X", "Kategorija rada": "Kvalitet",
             "Opis aktivnosti": "Bez kraja", "Datum": "22.10.2026", "Vreme početka": "8:00", "Vreme završetka aktivnosti": ""},
        ])
        technicians = pd.DataFrame([{"Technician_ID": "TECH-000002", "Technician_Name": "Đorđe Đorđević", "Username": "djordje"}])
        rows, errors, info = normalize_forms_rows_detailed(forms, technicians, "now")
        rows_again, _, _ = normalize_forms_rows_detailed(forms, technicians, "later")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Technician_ID"], "TECH-000002")
        self.assertEqual(rows[0]["Calculated_Duration"], 90.0)
        self.assertEqual(rows[0]["Source_ID"], rows_again[0]["Source_ID"])
        self.assertEqual(info["skipped_rows"], 1)
        kpi = all_activities_to_kpi_raw(pd.DataFrame(rows), technicians)
        self.assertEqual(kpi["Tehničar/Inženjer"].tolist(), ["Đorđe Đorđević"])


class AppLogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = load_symbols({
            "_validate_task_time_input", "_parse_required_date_text", "_parse_required_time_text",
            "_valid_task_end", "_sheet_safe_text", "_NUMBER_TEXT_RE", "_canonical_header_map", "_norm_sheet_col",
            "_clean_header_cell", "_records_frame_from_values", "prepare_kpi_data", "parse_time_series",
            "parse_mixed_datetime_series", "clean_columns", "PROCESS_DOWNTIME_SOURCE",
        }, initial={
            "re": __import__("re"), "datetime": dt.datetime, "date": dt.date, "time": dt.time,
            "timedelta": dt.timedelta, "parse_date_value": parse_date_value, "parse_time_value": parse_time_value,
        })

    def test_trailing_dot_date_and_missing_end_date_are_accepted(self):
        info = self.ns["_validate_task_time_input"]("23.10.2026.", "8.30", "", "10")
        self.assertEqual(info["errors"], [])
        self.assertTrue(info["has_end"])
        self.assertEqual(info["calc_min"], 90.0)

    def test_overnight_and_suspicious_duration(self):
        overnight = self.ns["_validate_task_time_input"]("23.10.2026", "22:00", "", "02:00")
        self.assertEqual(overnight["calc_min"], 240.0)
        swapped = self.ns["_validate_task_time_input"]("23.10.2026", "10:00", "23.10.2026", "09:00")
        self.assertTrue(swapped["errors"])

    def test_start_date_without_time_does_not_crash(self):
        info = self.ns["_validate_task_time_input"]("23.10.2026", "", "", "")
        self.assertFalse(info["has_start"])
        self.assertEqual(info["errors"], [])

    def test_formula_guard(self):
        safe = self.ns["_sheet_safe_text"]
        self.assertEqual(safe("-podesiti senzor"), "'-podesiti senzor")
        self.assertEqual(safe("=SUM(A1)"), "'=SUM(A1)")
        self.assertEqual(safe("-5"), "-5")
        self.assertEqual(safe("Normalan tekst"), "Normalan tekst")

    def test_header_spelling_variants_map_to_one_column(self):
        mapping = self.ns["_canonical_header_map"](["Task_ID", "Assigned To", "", "Status", "status"], ["Assigned_To", "Status", "Task_ID"])
        self.assertEqual(mapping, {0: "Task_ID", 1: "Assigned_To", 3: "Status"})
        frame = self.ns["_records_frame_from_values"](
            [["Task_ID", "Assigned To", "Status"], ["T1", "Bojan", "Open"], ["", "", ""], ["T2", "Ana", "Closed"]],
            ["Task_ID", "Assigned_To", "Status"],
        )
        self.assertEqual(frame["_row"].tolist(), [2, 4])
        self.assertEqual(frame["Assigned_To"].tolist(), ["Bojan", "Ana"])

    def test_kpi_keeps_rows_with_mixed_time_formats(self):
        raw = pd.DataFrame([
            {"Timestamp": "22.10.2026 10:00:00", "Tehničar/Inženjer": "A", "Kategorija rada": "K", "Opis aktivnosti": "x",
             "Datum": "22.10.2026", "Vreme početka": "08:30", "Vreme završetka aktivnosti": "09:00"},
            {"Timestamp": "22.10.2026 10:00:00", "Tehničar/Inženjer": "A", "Kategorija rada": "K", "Opis aktivnosti": "y",
             "Datum": "22.10.2026", "Vreme početka": "9:15:00", "Vreme završetka aktivnosti": "10:45:00"},
            {"Timestamp": "22.10.2026 10:00:00", "Tehničar/Inženjer": "A", "Kategorija rada": "K", "Opis aktivnosti": "z",
             "Datum": "22. 10. 2026.", "Vreme početka": "11.00", "Vreme završetka aktivnosti": "11.30"},
        ])
        df, missing = self.ns["prepare_kpi_data"](raw)
        self.assertEqual(missing, [])
        self.assertEqual(len(df), 3)
        self.assertAlmostEqual(df["Duration_Hours"].sum(), 0.5 + 1.5 + 0.5)


class EngineTests(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT / "tests" / "simulation" / "fakes"))
        import importlib
        self.engine_module = importlib.import_module("core.google_sheets_engine")

    def test_fresh_read_bypasses_cache_and_stale_is_never_returned_to_fresh_reads(self):
        engine = self.engine_module.GoogleSheetsEngine(ttl_seconds=60)
        engine._read_limiter.max_calls = 10**6

        class WS:
            spreadsheet_id, id, title = "s", 1, "t"

        state = {"value": 1, "fail": False}

        def original(ws):
            if state["fail"]:
                raise RuntimeError("APIError: [429]: Quota exceeded")
            return [[state["value"]]]

        import time as time_module
        saved_sleep = time_module.sleep
        time_module.sleep = lambda *_: None
        try:
            ws = WS()
            self.assertEqual(engine.cached_read("get_all_values", original, ws), [[1]])
            state["value"] = 2
            self.assertEqual(engine.cached_read("get_all_values", original, ws), [[1]])  # cached
            with engine.fresh_reads():
                self.assertEqual(engine.cached_read("get_all_values", original, ws), [[2]])
            state["fail"] = True
            with engine.fresh_reads():
                with self.assertRaises(RuntimeError):
                    engine.cached_read("get_all_values", original, ws)
        finally:
            time_module.sleep = saved_sleep


if __name__ == "__main__":
    unittest.main()
