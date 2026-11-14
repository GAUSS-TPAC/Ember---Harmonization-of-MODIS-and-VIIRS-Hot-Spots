import unittest

import pandas as pd

from ember_api import analytics


def series_fixture():
    rows = []
    for year in range(2010, 2020):
        for month in range(1, 13):
            base = {1: 100, 2: 80, 12: 60}.get(month, 5)
            rows.append({"year": year, "month": month, "n_harm": base * (3 if year == 2019 and month == 1 else 1),
                         "n_low": base * 0.8, "n_high": base * 1.2, "n_modis": 0, "n_viirs": 0, "source": "VIIRS_SNPP"})
    return pd.DataFrame(rows)


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.series = series_fixture()

    def test_calendar_shape(self):
        cal = analytics.calendar(self.series)
        self.assertEqual(len(cal["years"]), 10)
        self.assertEqual(cal["values"][0][0], 100.0)

    def test_anomaly_flags_exceptional_month(self):
        a = analytics.anomaly(self.series, 2019, 1)
        self.assertEqual(a["label"], "exceptionally high")
        self.assertEqual(a["ratio"], 3.0)
        normal = analytics.anomaly(self.series, 2015, 1)
        self.assertEqual(normal["label"], "near normal")

    def test_season_detects_dec_feb(self):
        s = analytics.season(analytics.climatology(self.series))
        self.assertEqual(s["peak"], 1)
        self.assertIn(s["onset"], (12, 1))
        self.assertIn(s["end"], (1, 2))

    def test_complete_series_fills_gaps(self):
        partial = self.series[self.series["year"] == 2015].iloc[:3]
        full = analytics.complete_series(partial, (2015, 1), (2015, 12))
        self.assertEqual(len(full), 12)
        self.assertEqual(full["n_harm"].iloc[-1], 0)

    def test_ranking(self):
        top = analytics.yearly_ranking(self.series, top=1)
        self.assertEqual(top[0]["year"], 2019)


if __name__ == "__main__":
    unittest.main()
