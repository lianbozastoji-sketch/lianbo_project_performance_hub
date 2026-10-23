import ast
import unittest
from pathlib import Path

SOURCE_PATH = Path(__file__).resolve().parents[1] / "lianbo_project_performance_hub.py"
SOURCE_TEXT = SOURCE_PATH.read_text(encoding="utf-8")
SOURCE_TREE = ast.parse(SOURCE_TEXT)


class IwonDiagnosticsTests(unittest.TestCase):
    def test_scope_matching_is_case_insensitive(self):
        self.assertIn('.str.strip().str.casefold() == project_key', SOURCE_TEXT)
        self.assertIn('.str.strip().str.casefold() == process_key', SOURCE_TEXT)

    def test_missing_week_is_not_reported_as_permission_error(self):
        self.assertIn('nema nijedan stvarni OEE unos', SOURCE_TEXT)
        self.assertIn('ima OEE podatke, ali nema podatke za', SOURCE_TEXT)
        self.assertIn('except ValueError as exc:', SOURCE_TEXT)
        self.assertIn('st.warning(str(exc))', SOURCE_TEXT)

    def test_google_errors_are_handled_separately(self):
        self.assertIn('except gspread.exceptions.SpreadsheetNotFound:', SOURCE_TEXT)
        self.assertIn('except gspread.exceptions.APIError as exc:', SOURCE_TEXT)


if __name__ == "__main__":
    unittest.main()
