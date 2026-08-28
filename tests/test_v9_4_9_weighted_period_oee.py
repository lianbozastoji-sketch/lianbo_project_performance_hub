import unittest

import pandas as pd

from test_v9_3_logic import load_symbols


class WeightedPeriodOeeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = load_symbols(
            {"calculate_oee_metrics", "aggregate_oee", "aggregate_oee_as_weighted_daily"},
            initial={"pd": pd, "parse_oee_date_series": lambda s: pd.to_datetime(s)},
        )

    def test_equal_time_days_use_daily_oee_average(self):
        raw = pd.DataFrame([
            {"Datum": "2026-08-24", "Machine": "M", "Open time": 100, "Down time": 0, "Organisational loss": 0, "OK pcs.": 200, "NOK pcs.": 0, "Total Pcs": 200, "Target pcs.": 100, "CT_s": 60},
            {"Datum": "2026-08-25", "Machine": "M", "Open time": 100, "Down time": 0, "Organisational loss": 0, "OK pcs.": 90, "NOK pcs.": 0, "Total Pcs": 90, "Target pcs.": 100, "CT_s": 60},
        ])
        calculated = self.ns["calculate_oee_metrics"](raw)
        result = self.ns["aggregate_oee_as_weighted_daily"](calculated).iloc[0]
        self.assertAlmostEqual(result["Machine_OEE_CT_%"], 95.0, places=5)

    def test_raw_performance_above_100_is_preserved_for_warning(self):
        raw = pd.DataFrame([{"Datum": "2026-08-24", "Machine": "M", "Open time": 100, "Down time": 0, "Organisational loss": 0, "OK pcs.": 200, "NOK pcs.": 0, "Total Pcs": 200, "Target pcs.": 100, "CT_s": 60}])
        result = self.ns["calculate_oee_metrics"](raw).iloc[0]
        self.assertEqual(result["Machine_Performance_CT_%"], 100)
        self.assertEqual(result["Machine_Performance_CT_Raw_%"], 200)


if __name__ == "__main__":
    unittest.main()
