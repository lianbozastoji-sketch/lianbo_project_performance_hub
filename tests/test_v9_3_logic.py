import ast
import re
import unittest
from pathlib import Path

import pandas as pd


SOURCE_PATH = Path(__file__).resolve().parents[1] / "lianbo_project_performance_hub.py"
SOURCE_TREE = ast.parse(SOURCE_PATH.read_text(encoding="utf-8"))


def load_symbols(names, initial=None):
    nodes = []
    for node in SOURCE_TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            nodes.append(node)
        elif isinstance(node, ast.Assign):
            assigned = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if assigned & names:
                nodes.append(node)
    namespace = {"pd": pd}
    namespace.update(initial or {})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE_PATH), "exec"), namespace)
    return namespace


class FakeWorksheet:
    def __init__(self, columns):
        self.columns = columns

    def batch_get(self, ranges):
        return self.columns


class HeaderWorksheet:
    def __init__(self, values):
        self.values = values
        self.updates = []

    def get_all_values(self):
        return self.values

    def update(self, cell_range, values):
        self.updates.append((cell_range, values))


class OeeShiftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = load_symbols({
            "build_oee_row",
            "calculate_oee_metrics",
            "aggregate_oee",
            "find_oee_existing_record",
            "ensure_oee_input_columns",
            "OEE_INPUT_COLUMNS",
        }, initial={"re": re, "_column_number_to_letter": lambda value: chr(64 + value)})

    def test_individual_and_all_shift_open_time(self):
        build = self.ns["build_oee_row"]
        one = build("2026-08-18", "P", "Proc", "M", 30, 1000, 480, 1, 900, 100, 30, 10, "Tester", "1st shift (06:00-14:00)")
        all_three = build("2026-08-18", "P", "Proc", "M", 30, 1000, 480, 3, 2700, 300, 90, 30, "Tester", "All shifts")
        self.assertEqual(one[7], 480)
        self.assertEqual(one[14], 1000)
        self.assertEqual(one[16], "1st shift (06:00-14:00)")
        self.assertEqual(all_three[7], 1440)
        self.assertEqual(all_three[14], 3000)

    def test_daily_oee_is_calculated_from_summed_raw_shift_data(self):
        raw = pd.DataFrame([
            {"Machine": "M", "Open time": 480, "Down time": 30, "Organisational loss": 10, "OK pcs.": 900, "NOK pcs.": 100, "Total Pcs": 1000, "Target pcs.": 1000, "CT_s": 30},
            {"Machine": "M", "Open time": 480, "Down time": 60, "Organisational loss": 20, "OK pcs.": 800, "NOK pcs.": 200, "Total Pcs": 1000, "Target pcs.": 1000, "CT_s": 30},
        ])
        calculated = self.ns["calculate_oee_metrics"](raw)
        daily = self.ns["aggregate_oee"](calculated.assign(Day="2026-08-18"), ["Day"]).iloc[0]
        self.assertEqual(daily["Open_Time"], 960)
        self.assertEqual(daily["OK_pcs"], 1700)
        self.assertAlmostEqual(daily["Plant_Availability_%"], 90.625, places=3)
        self.assertAlmostEqual(daily["Quality_%"], 85.0, places=3)
        self.assertAlmostEqual(daily["Plant_OEE_CT_%"], 77.03125, places=3)

    def test_duplicate_rules_allow_individual_shifts_but_block_all_shift_mix(self):
        columns = [
            [["Datum"], ["18.08.2026"], ["18.08.2026"]],
            [["Project"], ["P"], ["P"]],
            [["Process"], ["Proc"], ["Proc"]],
            [["Machine"], ["M"], ["M"]],
            [["Shift"], ["1st shift (06:00-14:00)"], ["2nd shift (14:00-22:00)"]],
        ]
        ws = FakeWorksheet(columns)
        find = self.ns["find_oee_existing_record"]
        second = find(ws, "2026-08-18", "P", "Proc", "M", "2nd shift (14:00-22:00)")
        third = find(ws, "2026-08-18", "P", "Proc", "M", "3rd shift (22:00-06:00)")
        combined = find(ws, "2026-08-18", "P", "Proc", "M", "All shifts")
        self.assertEqual(second["exact_row"], 3)
        self.assertEqual(third["conflicts"], [])
        self.assertEqual(len(combined["conflicts"]), 2)

    def test_legacy_oee_header_gets_shift_column_without_row_rewrite(self):
        legacy_headers = self.ns["OEE_INPUT_COLUMNS"][:-1]
        ws = HeaderWorksheet([legacy_headers, ["18.08.2026", "34", "Tuesday"]])
        returned = self.ns["ensure_oee_input_columns"](ws)
        self.assertEqual(returned[-1], "Shift")
        self.assertEqual(len(ws.updates), 1)
        self.assertEqual(ws.updates[0][0], "A1:Q1")
        self.assertEqual(ws.values[1], ["18.08.2026", "34", "Tuesday"])


class UserPermissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = load_symbols({
            "MODULE_REGISTRY",
            "_norm_key",
            "has_permission",
            "build_permission_dict",
            "_parse_user_override",
            "build_effective_permission_dict",
        })

    def test_user_override_wins_over_role(self):
        permissions = pd.DataFrame([{"Role": "User", "Role_norm": "user", "OEE": "YES", "KPI_Process": "NO"}])
        user = {
            "Role": "User",
            "View_OEE": "NO",
            "Edit_OEE": "YES",
            "View_KPI_Process": "YES",
            "Edit_KPI_Process": "YES",
        }
        effective = self.ns["build_effective_permission_dict"](permissions, user)
        self.assertFalse(effective["view_oee"])
        self.assertFalse(effective["edit_oee"])
        self.assertTrue(effective["view_kpi_process"])
        self.assertTrue(effective["edit_kpi_process"])

    def test_edit_allowed_also_grants_view_when_view_is_role_default(self):
        permissions = pd.DataFrame([{"Role": "User", "Role_norm": "user", "OEE": "NO"}])
        effective = self.ns["build_effective_permission_dict"](permissions, {"Role": "User", "Edit_OEE": "YES"})
        self.assertTrue(effective["view_oee"])
        self.assertTrue(effective["edit_oee"])


if __name__ == "__main__":
    unittest.main()
