from pathlib import Path
import unittest


APP = Path(__file__).resolve().parents[1] / "lianbo_project_performance_hub.py"


class TestOeeShiftSelectionStyle(unittest.TestCase):
    def test_selected_oee_shift_has_state_driven_red_glow_css(self):
        source = APP.read_text(encoding="utf-8")

        self.assertIn('APP_VERSION = "v9.4.8_machine_oee_clean_time"', source)
        self.assertIn('state_key = "oee_included_shift_buttons"', source)
        self.assertIn('"1st": "oee_shift_toggle_1st"', source)
        self.assertIn('"2nd": "oee_shift_toggle_2nd"', source)
        self.assertIn('"3rd": "oee_shift_toggle_3rd"', source)
        self.assertIn("selected_button_selectors", source)
        self.assertIn("#FF3B3B", source)
        self.assertIn("oee-selected-shift-red-glow", source)

    def test_shift_buttons_keep_multi_selection_logic(self):
        source = APP.read_text(encoding="utf-8")

        self.assertIn('shift_order = ["1st", "2nd", "3rd"]', source)
        self.assertIn("updated_shifts.append(shift_name)", source)
        self.assertIn("updated_shifts.remove(shift_name)", source)
        self.assertIn("st.rerun()", source)
        self.assertIn("number_of_shifts = len(included_shifts)", source)


if __name__ == "__main__":
    unittest.main()
