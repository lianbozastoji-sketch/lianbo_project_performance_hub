import ast
import re
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

SOURCE_PATH = Path(__file__).resolve().parents[1] / "lianbo_project_performance_hub.py"
SOURCE_TEXT = SOURCE_PATH.read_text(encoding="utf-8")
SOURCE_TREE = ast.parse(SOURCE_TEXT)


def load_symbols(names, initial=None):
    nodes = []
    for node in SOURCE_TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            nodes.append(node)
        elif isinstance(node, ast.Assign):
            assigned = {target.id for target in node.targets if isinstance(target, ast.Name)}
            if assigned & names:
                nodes.append(node)
    namespace = {"pd": pd, "re": re, "datetime": datetime}
    namespace.update(initial or {})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE_PATH), "exec"), namespace)
    return namespace


class OeeAllShiftSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = load_symbols({"_oee_included_shifts_text", "build_oee_row"}, initial={"get_current_oee_submitter": lambda: "Tester"})

    def test_two_selected_shifts_drive_open_time_and_target(self):
        row = self.ns["build_oee_row"](
            "2026-08-26", "APP350", "Inspection Rotor", "RL 1",
            30, 1000, 480, 2, 1600, 100, 30, 10,
            "Tester", "All shifts", ["1st", "3rd"],
        )
        self.assertEqual(row[7], 960.0)
        self.assertEqual(row[8], 2.0)
        self.assertEqual(row[14], 2000.0)
        self.assertEqual(row[17], "1st | 3rd")

    def test_old_shift_count_input_removed_and_multi_pills_added(self):
        self.assertNotIn("How many shifts are included?", SOURCE_TEXT)
        self.assertIn('st.pills(', SOURCE_TEXT)
        self.assertIn('selection_mode="multi"', SOURCE_TEXT)
        self.assertIn('["1st", "2nd", "3rd"]', SOURCE_TEXT)


class WorkTicketTimestampTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = load_symbols({"_format_task_card_datetime"})

    def test_card_timestamp_format(self):
        formatted = self.ns["_format_task_card_datetime"]("26.08.2026", "08:05")
        self.assertEqual(formatted, "26.08.2026 08:05")

    def test_completed_card_and_close_flow_include_start_and_end(self):
        self.assertIn("Started: {started_at", SOURCE_TEXT)
        self.assertIn("Finished: {finished_at", SOURCE_TEXT)
        self.assertIn('update_values["Start_Date"] = activity_start_dt.strftime("%d.%m.%Y")', SOURCE_TEXT)
        self.assertIn('update_values["End_Date"] = activity_end_dt.strftime("%d.%m.%Y")', SOURCE_TEXT)
        self.assertIn("_build_task_activity_time_bounds", SOURCE_TEXT)


if __name__ == "__main__":
    unittest.main()
