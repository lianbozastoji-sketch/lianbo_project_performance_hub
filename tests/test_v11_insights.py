"""v11: downtime causes, manager view numbers and private IWON planning."""
import datetime as dt
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import oee_insights as oi  # noqa: E402
from test_v9_3_logic import load_symbols  # noqa: E402

NS = load_symbols({"aggregate_oee"}, initial={"pd": pd})
aggregate = NS["aggregate_oee"]


def oee_row(day, machine, open_t=440, down=0, org=0, ok=100, nok=0, target=100, ct=60, project="P1", process="Proc"):
    return {"Datum": pd.Timestamp(day), "Project": project, "Process": process, "Machine": machine,
            "Open time": open_t, "Down time": down, "Organisational loss": org, "OK pcs.": ok, "NOK pcs.": nok,
            "Total Pcs": ok + nok, "Target pcs.": target, "Ideal_Time_min": (ok + nok) * ct / 60, "Shift": "All shifts"}


def event(day, machine, cause, minutes, loss=oi.LOSS_DOWNTIME, source=oi.SOURCE_PHONE, process="Proc"):
    return {"Event_ID": f"{day}{machine}{cause}{minutes}", "Datum": day, "Shift": "1st", "Project": "P1", "Process": process,
            "Machine": machine, "Loss_Type": loss, "Cause": cause, "Minutes": minutes, "Status": oi.STATUS_DONE,
            "Source": source}


class CauseTests(unittest.TestCase):
    def test_catalogue_defaults_and_cleaning(self):
        causes = oi.clean_causes(pd.DataFrame([{"Loss_Type": "x", "Cause": "Novi uzrok", "Lever": "??", "Active": "YES", "Sort": 1},
                                               {"Loss_Type": oi.LOSS_DOWNTIME, "Cause": "Stari", "Active": "NE"}]))
        self.assertEqual(causes["Cause"].tolist(), ["Novi uzrok"])
        self.assertEqual(causes["Loss_Type"].iloc[0], oi.LOSS_DOWNTIME)
        self.assertGreater(len(oi.clean_causes(None)), 10)

    def test_shift_from_time(self):
        self.assertEqual([oi.shift_for_time(t) for t in ("06:00", "13:59", "14:00", "21:59", "22:00", "05:59")],
                         ["1st", "1st", "2nd", "2nd", "3rd", "3rd"])
        self.assertEqual(oi.shift_code("2nd shift (14:00-22:00)"), "2nd")
        self.assertEqual(oi.shift_code("All shifts"), "ALL")

    def test_allocation_must_match_entered_minutes(self):
        logged = oi.normalize_events(pd.DataFrame([event("22.10.2026", "M1", "Električni kvar", 15)]))
        rows = pd.DataFrame([{"Uzrok": "Mašinski kvar", "Minuta": 10}, {"Uzrok": "Čekanje materijala", "Minuta": 10}])
        ok = oi.check_allocation(25, 10, logged, rows)
        self.assertEqual(ok["errors"], [])
        self.assertEqual((ok["down_sum"], ok["org_sum"]), (25, 10))
        short = oi.check_allocation(30, 10, logged, rows)
        self.assertTrue(any("nedostaje za 5" in e for e in short["errors"]), short["errors"])
        too_much = oi.check_allocation(20, 10, logged, rows)
        self.assertTrue(any("više" in e for e in too_much["errors"]))
        unknown = oi.check_allocation(25, 10, logged, pd.DataFrame([{"Uzrok": "xx", "Minuta": 10}]))
        self.assertTrue(any("Nepoznat" in e for e in unknown["errors"]))

    def test_form_rows_become_events(self):
        form = pd.DataFrame([
            {"Timestamp": "22.10.2026 10:50:00", "IME": "Marko", "Projekat": "P1", "DATUM PROBLEMA": "22.10.2026",
             "POČETAK ZASTOJA": "10:15:00", "ZAVRŠETAK ZASTOJA": "10:45:00", "VREME ZASTOJA": "0:30:00",
             "UZROK ZASTOJA": "Senzor prisustva", "MESTO ZASTOJA": "M1"},
            {"Timestamp": "22.10.2026 11:50:00", "IME": "Pera", "Projekat": "P1", "DATUM PROBLEMA": "22.10.2026",
             "POČETAK ZASTOJA": "23:00", "ZAVRŠETAK ZASTOJA": "00:20", "VREME ZASTOJA": "",
             "UZROK ZASTOJA": "čekanje materijala", "MESTO ZASTOJA": "m1"},
            {"Timestamp": "x", "IME": "Pera", "Projekat": "P1", "DATUM PROBLEMA": "22.10.2026",
             "POČETAK ZASTOJA": "10:00", "ZAVRŠETAK ZASTOJA": "10:20", "UZROK ZASTOJA": "?", "MESTO ZASTOJA": "Cela linija"},
        ])
        master = pd.DataFrame([{"Project": "P1", "Process": "Proc", "Machine": "M1"}])
        events = oi.form_rows_to_events(form, master)
        self.assertEqual(len(events), 2)
        self.assertEqual(events["Cause"].tolist(), ["Zamena senzora / dela", "Čekanje materijala"])
        self.assertEqual(events["Minutes"].tolist(), [30.0, 80.0])
        self.assertEqual(events["Shift"].tolist(), ["1st", "3rd"])
        self.assertEqual(events["Loss_Type"].tolist(), [oi.LOSS_DOWNTIME, oi.LOSS_ORGANISATIONAL])

    def test_pareto_with_uncaused_remainder(self):
        rows = pd.DataFrame([oee_row("2026-10-19", "M1", down=60, org=10), oee_row("2026-10-20", "M2", down=40)])
        events = oi.normalize_events(pd.DataFrame([
            event("19.10.2026", "M1", "Električni kvar", 45), event("19.10.2026", "M1", "Čekanje materijala", 10, oi.LOSS_ORGANISATIONAL),
            event("21.10.2026", "M1", "Električni kvar", 99),  # another day: not part of these rows
        ]))
        pareto = oi.loss_pareto(events, rows)
        self.assertEqual(pareto["Cause"].tolist(), ["Bez uzroka (stari unos)", "Električni kvar", "Čekanje materijala"])
        self.assertEqual(pareto["Minutes"].tolist(), [55.0, 45.0, 10.0])
        self.assertAlmostEqual(pareto["Cum_%"].iloc[-1], 100.0)


class ManagerViewTests(unittest.TestCase):
    def test_coverage_counts_workdays_and_machines(self):
        rows = pd.DataFrame([oee_row("2026-10-19", "M1"), oee_row("2026-10-19", "M2"), oee_row("2026-10-20", "M1")])
        info = oi.coverage(rows, "2026-10-19", "2026-10-25", ["M1", "M2"], today="2026-10-26")
        self.assertEqual((info["days_entered"], info["days_expected"]), (2, 5))
        self.assertEqual((info["machine_days_entered"], info["machine_days_expected"]), (3, 10))
        self.assertEqual([d.day for d in info["missing_days"]], [21, 22, 23])
        partial = oi.coverage(rows, "2026-10-19", "2026-10-25", ["M1", "M2"], today="2026-10-20")
        self.assertEqual(partial["days_expected"], 2)

    def test_lost_summary_and_value(self):
        agg = aggregate(pd.DataFrame([oee_row("2026-10-19", "M1", down=90, org=30, ok=80, target=100)]).assign(T="T"), ["T"]).iloc[0]
        lost = oi.lost_summary(agg, 8)
        self.assertEqual(lost["lost_pieces"], 20)
        self.assertEqual(lost["lost_hours"], 2.0)
        self.assertEqual(lost["value"], 160)
        self.assertIsNone(oi.lost_summary(agg, None)["value"])

    def test_headline_and_delta(self):
        text = oi.headline("OEE", 87.4, 84.3, 85, "ove nedelje", "Električni kvar na RL 2 (95 min)",
                           {"days_expected": 5, "days_entered": 3, "complete": False})
        self.assertIn("OEE ove nedelje je 87,4 %", text)
        self.assertIn("2,4 pp iznad reference od 85,0 %", text)
        self.assertIn("3,1 pp bolje", text)
        self.assertIn("uneto je 3 od 5", text)
        self.assertEqual(oi.delta_text(80, 82.5)[0], "↓ −2,5 pp")


class IwonTests(unittest.TestCase):
    def setUp(self):
        rows = []
        for week in range(32, 42):  # 10 weeks of history, then nothing
            monday = pd.Timestamp(dt.date.fromisocalendar(2026, week, 1))
            for offset in range(5):
                rows.append(oee_row(monday + pd.Timedelta(days=offset), "M1", down=44, ok=360, nok=4, target=400))
                rows.append(oee_row(monday + pd.Timedelta(days=offset), "M2", down=22, ok=380, nok=10, target=400))
        self.actual = pd.DataFrame(rows)

    def test_plan_for_future_week_without_data(self):
        out = oi.plan_week(self.actual, ["M1", "M2", "M3"], 2026, 50, "P1", "Proc", 85, aggregate, weeks=10)
        machines = [r["Machine"] for r in out["compare_rows"]]
        self.assertEqual(machines, ["GLOBAL", "M1", "M2", "M3"])
        self.assertEqual(out["weeks_used"], 10)
        self.assertIn("10 nedelja sa podacima pre CW50 (CW32–CW41)", out["note"])
        for row in out["compare_rows"]:
            self.assertAlmostEqual(row["Plan_OEE"], 85, delta=0.01)
            self.assertLessEqual(max(row["Plan_A"], row["Plan_P"], row["Plan_Q"]), 100)
        m3 = next(r for r in out["compare_rows"] if r["Machine"] == "M3")
        glob = out["compare_rows"][0]
        self.assertEqual((m3["Forecast_A"], m3["Forecast_P"]), (glob["Forecast_A"], glob["Forecast_P"]))
        self.assertEqual(len(out["iwon_rows"][0]), 10)  # OEE_IWON keeps its A:J layout

    def test_plan_uses_weeks_right_before(self):
        out = oi.plan_week(self.actual, ["M1"], 2026, 42, "P1", "Proc", 85, aggregate, weeks=4)
        self.assertEqual(out["weeks_used"], 4)
        self.assertIn("4 nedelja sa podacima pre CW42 (CW38–CW41)", out["note"])

    def test_week_before_all_data_uses_latest_weeks(self):
        out = oi.plan_week(self.actual, ["M1"], 2026, 10, "P1", "Proc", 85, aggregate, weeks=3)
        self.assertEqual(out["weeks_used"], 3)
        self.assertIn("poslednje 3 nedelje", out["note"])

    def test_no_data_at_all_splits_target_evenly(self):
        out = oi.plan_week(pd.DataFrame(), ["M1"], 2026, 5, "P1", "Proc", 72.9, aggregate)
        row = out["compare_rows"][0]
        self.assertAlmostEqual(row["Plan_A"], 90.0, delta=0.01)
        self.assertAlmostEqual(row["Plan_OEE"], 72.9, delta=0.01)

    def test_refresh_fills_actual_and_deviation(self):
        out = oi.plan_week(self.actual, ["M1", "M2"], 2026, 41, "P1", "Proc", 85, aggregate, weeks=4)
        actuals = oi.actual_for_week(self.actual, 2026, 41, "P1", "Proc", aggregate)
        rows = oi.apply_actuals(out["compare_rows"], actuals)
        glob = rows[0]
        self.assertEqual(glob["Coverage_Days"], 5)
        self.assertAlmostEqual(glob["Dev_Plan_OEE"], glob["Actual_OEE"] - glob["Plan_OEE"], places=3)
        empty = oi.apply_actuals(oi.plan_week(self.actual, ["M1"], 2026, 50, "P1", "Proc", 85, aggregate)["compare_rows"],
                                 oi.actual_for_week(self.actual, 2026, 50, "P1", "Proc", aggregate))
        self.assertEqual(empty[0]["Actual_OEE"], "")
        acc = oi.forecast_accuracy(pd.DataFrame(rows))
        self.assertEqual(acc["weeks"], 1)

    def test_cause_targets_stay_realistic(self):
        # M1: sensor change 6x per week, mostly 8 min, fastest ones 2-3 min
        events = []
        durations = [8, 8, 9, 7, 2.5, 3, 8, 10, 8, 2.8]
        rows = []
        for week in range(32, 42):
            monday = pd.Timestamp(dt.date.fromisocalendar(2026, week, 1))
            for offset in range(5):
                rows.append(oee_row(monday + pd.Timedelta(days=offset), "M1", down=12, ok=360, target=400))
            for i in range(6):
                day = monday + pd.Timedelta(days=i % 5)
                events.append(event(day.strftime("%d.%m.%Y"), "M1", "Zamena senzora / dela", durations[(week + i) % 10]))
        base = pd.DataFrame(rows)
        ev = oi.normalize_events(pd.DataFrame(events))
        now_a = aggregate(base.assign(T="T"), ["T"]).iloc[0]["Machine_Availability_%"]
        plan = oi.cause_plan(ev, base, now_a + 0.5)
        item = plan["items"][0]
        self.assertEqual(item["Cause"], "Zamena senzora / dela")
        self.assertEqual(item["Lever"], oi.LEVER_DURATION)
        self.assertGreaterEqual(item["Target_Avg_Min"], item["Best_Avg_Min"] - 1e-6)
        self.assertIn(item["Rating"], (oi.RATING_OK, oi.RATING_HARD))
        self.assertAlmostEqual(plan["needed_min_week"], item["Reduction_Min_Week"] + plan["missing_min_week"], places=6)
        hard = oi.cause_plan(ev, base, 99.9)
        self.assertEqual(hard["items"][0]["Rating"], oi.RATING_UNREALISTIC)
        self.assertGreater(hard["missing_min_week"], 0)
        self.assertLess(plan["realistic_max_a"], 100)


if __name__ == "__main__":
    unittest.main()
