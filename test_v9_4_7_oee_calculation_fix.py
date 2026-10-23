import re
import unittest

import pandas as pd

from test_v9_3_logic import load_symbols


class OeeCalculationFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ns = load_symbols(
            {"calculate_oee_metrics", "aggregate_oee"},
            initial={"pd": pd},
        )

    def test_machine_availability_includes_organisational_loss(self):
        raw = pd.DataFrame([{
            "Machine": "M1", "Open time": 480, "Down time": 30,
            "Organisational loss": 50, "OK pcs.": 700, "NOK pcs.": 0,
            "Total Pcs": 700, "Target pcs.": 800, "CT_s": 30,
        }])
        result = self.ns["calculate_oee_metrics"](raw).iloc[0]
        self.assertAlmostEqual(result["Machine_Availability_%"], 400 / 430 * 100, places=5)

    def test_aggregated_machine_availability_uses_summed_losses(self):
        raw = pd.DataFrame([
            {"Machine": "M1", "Open time": 480, "Down time": 30, "Organisational loss": 50, "OK pcs.": 700, "NOK pcs.": 0, "Total Pcs": 700, "Target pcs.": 800, "CT_s": 30},
            {"Machine": "M1", "Open time": 480, "Down time": 20, "Organisational loss": 40, "OK pcs.": 720, "NOK pcs.": 0, "Total Pcs": 720, "Target pcs.": 800, "CT_s": 30},
        ])
        calculated = self.ns["calculate_oee_metrics"](raw)
        result = self.ns["aggregate_oee"](calculated.assign(Period="CW35"), ["Period"]).iloc[0]
        self.assertAlmostEqual(result["Machine_Availability_%"], 820 / 870 * 100, places=5)


if __name__ == "__main__":
    unittest.main()
