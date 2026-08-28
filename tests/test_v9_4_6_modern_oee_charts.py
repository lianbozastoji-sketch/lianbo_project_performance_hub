from pathlib import Path
import unittest


SOURCE = (Path(__file__).resolve().parents[1] / "lianbo_project_performance_hub.py").read_text(encoding="utf-8")


class ModernOeeChartTests(unittest.TestCase):
    def test_version_and_target(self):
        self.assertIn('APP_VERSION = "v9.4.8_machine_oee_clean_time"', SOURCE)
        self.assertIn("OEE_CHART_TARGET = 85.0", SOURCE)

    def test_modern_trend_visuals(self):
        self.assertIn('line_color = "#38BDF8"', SOURCE)
        self.assertIn('fill="tozeroy"', SOURCE)
        self.assertIn("PERIOD CHANGE", SOURCE)
        self.assertIn("get_oee_chart_status_color", SOURCE)

    def test_shared_target_and_short_dates(self):
        self.assertGreaterEqual(SOURCE.count("add_oee_target_line("), 4)
        self.assertIn('dt.dt.day_name().str[:3] + " " + dt.dt.strftime("%d.%m")', SOURCE)


if __name__ == "__main__":
    unittest.main()
