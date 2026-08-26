import ast
import unittest
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
    namespace = {"pd": pd}
    namespace.update(initial or {})
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE_PATH), "exec"), namespace)
    return namespace


class FakeResultWorksheet:
    def __init__(self, values):
        self.values = [list(r) for r in values]
        self.updated = []
        self.appended = []
        self.cleared_ranges = []
        self.clear_called = False

    def get_all_values(self):
        return [list(r) for r in self.values]

    def update(self, cell_range, values, value_input_option=None):
        self.updated.append((cell_range, values, value_input_option))

    def append_row(self, row, value_input_option=None):
        self.appended.append((row, value_input_option))

    def batch_clear(self, ranges):
        self.cleared_ranges.extend(ranges)

    def clear(self):
        self.clear_called = True
        raise AssertionError("IWON result writer must never clear the whole worksheet")


class IwonCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = load_symbols({
            "_balanced_iwon_components",
            "_upsert_iwon_result_rows",
            "OEE_IWON_RESULT_COLUMNS",
        })

    def test_balanced_components_hit_requested_target(self):
        calc = self.ns["_balanced_iwon_components"]
        a, p, q = calc(80.0, 75.0, 96.0833, 84.0)
        achieved = a * p * q / 10000.0
        self.assertAlmostEqual(achieved, 84.0, places=3)
        self.assertGreaterEqual(a, 80.0)
        self.assertGreaterEqual(p, 75.0)
        self.assertGreaterEqual(q, 96.0833)

    def test_high_target_is_reachable_with_100_percent_component_caps(self):
        calc = self.ns["_balanced_iwon_components"]
        a, p, q = calc(95.0, 95.0, 99.0, 99.0)
        achieved = a * p * q / 10000.0
        self.assertAlmostEqual(achieved, 99.0, places=3)
        self.assertTrue(all(0 <= x <= 100 for x in (a, p, q)))

    def test_result_upsert_never_clears_entire_sheet(self):
        headers = self.ns["OEE_IWON_RESULT_COLUMNS"]
        ws = FakeResultWorksheet([
            headers,
            [2026, 32, "P", "Proc", "GLOBAL", 90, 91, 99, 81, "old"],
            [2026, 31, "P", "Proc", "GLOBAL", 88, 89, 99, 77.5, "keep"],
        ])
        rows = [
            [2026, 32, "P", "Proc", "GLOBAL", 94, 90, 99.3, 84, "new"],
            [2026, 32, "P", "Proc", "M1", 93, 91, 99.2, 84, "new"],
        ]
        self.ns["_upsert_iwon_result_rows"](ws, 2026, 32, "P", "Proc", rows)
        self.assertFalse(ws.clear_called)
        self.assertTrue(any(rng == "A2:J2" for rng, _, _ in ws.updated))
        self.assertEqual(len(ws.appended), 1)
        self.assertEqual(ws.cleared_ranges, [])

    def test_weekly_iwon_branch_does_not_recalculate_or_write(self):
        marker = 'if weekly_metric_col == "IWON_OEE_%":'
        start = SOURCE_TEXT.index(marker)
        end = SOURCE_TEXT.index("                else:\n", start)
        block = SOURCE_TEXT[start:end]
        self.assertIn("show_iwon_week_view", block)
        self.assertNotIn("calculate_and_store_iwon_week(", block)


if __name__ == "__main__":
    unittest.main()
