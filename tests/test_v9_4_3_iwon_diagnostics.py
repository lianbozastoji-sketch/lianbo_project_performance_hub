import ast
import sys
import unittest
from pathlib import Path

import pandas as pd

SOURCE_PATH = Path(__file__).resolve().parents[1] / "lianbo_project_performance_hub.py"
SOURCE_TEXT = SOURCE_PATH.read_text(encoding="utf-8")
SOURCE_TREE = ast.parse(SOURCE_TEXT)
sys.path.insert(0, str(SOURCE_PATH.parent))


def _function_source(name):
    for node in ast.walk(SOURCE_TREE):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(SOURCE_TEXT, node)
    return ""


class IwonDiagnosticsTests(unittest.TestCase):
    def test_scope_matching_is_case_insensitive(self):
        self.assertIn('.str.strip().str.casefold() == project_key', SOURCE_TEXT)
        self.assertIn('.str.strip().str.casefold() == process_key', SOURCE_TEXT)

    def test_week_without_data_still_gets_a_plan(self):
        # v11: IWON is generated for any week (also future ones); no "missing data" error any more.
        import oee_insights as oi

        out = oi.plan_week(pd.DataFrame(), ["M1"], 2026, 50, "P", "Proc", 80, lambda df, cols: pd.DataFrame())
        self.assertAlmostEqual(out["compare_rows"][0]["Plan_OEE"], 80, delta=0.01)

    def test_google_errors_are_reported_not_crashing(self):
        module = _function_source("render_iwon_module")
        self.assertIn('st.error(f"Plan nije napravljen: {exc}")', module)
        self.assertIn('st.error(f"Osvežavanje nije uspelo: {exc}")', module)

    def test_iwon_is_private(self):
        module = _function_source("render_iwon_module")
        self.assertIn("if not can_see_iwon():", module)
        self.assertNotIn("OEE IWON Targets", _function_source("render_administration_module"))
        self.assertNotIn('"OEE IWON":', SOURCE_TEXT.split("OEE_METRIC_LABELS = ")[0].split("OEE_METRIC_OPTIONS = {")[-1])


if __name__ == "__main__":
    unittest.main()
