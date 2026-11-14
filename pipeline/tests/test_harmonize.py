import unittest

import numpy as np
import pandas as pd

from ember_pipeline.harmonize import (HarmonizationConfig, apply_factors, fit_factors, harmonize,
                                      pivot_platforms, validate)


def build_monthly(ratio=4.0, years=range(2000, 2026), cells=((4.0, 11.0), (4.1, 11.0)), modis_per_month=10):
    """Deterministic MODIS/VIIRS counts with an exact ratio on the overlap years."""
    rows = []
    for lat, lon in cells:
        for year in years:
            for month in range(1, 13):
                if (year, month) >= (2000, 11):
                    rows.append(("MODIS_Terra", lat, lon, year, month, modis_per_month // 2))
                if (year, month) >= (2002, 7):
                    rows.append(("MODIS_Aqua", lat, lon, year, month, modis_per_month - modis_per_month // 2))
                if 2012 <= year <= 2025:
                    rows.append(("VIIRS_SNPP", lat, lon, year, month, int(modis_per_month * ratio)))
    df = pd.DataFrame(rows, columns=["platform", "lat_cell", "lon_cell", "year", "month", "n"])
    df["country"] = "T"
    df["n_day"] = df["n"]
    df["n_night"] = 0
    df["frp_sum"] = df["n"] * 5.0
    return df


class FitTests(unittest.TestCase):
    def test_recovers_exact_ratio_at_cell_level(self):
        factors = fit_factors(build_monthly(ratio=4.0))
        self.assertTrue(np.allclose(factors["k_MODIS"], 4.0))
        self.assertTrue((factors["level_MODIS"] == "cell").all())
        self.assertTrue(np.allclose(factors["k_MODIS_Terra"], 8.0))  # Terra alone is half of MODIS

    def test_sparse_cell_falls_back_to_block_then_global(self):
        monthly = build_monthly(ratio=4.0, modis_per_month=1, cells=((4.0, 11.0),))
        cfg = HarmonizationConfig(min_platform_count=10_000)
        factors = fit_factors(monthly, cfg)
        self.assertEqual(factors["level_MODIS"].iloc[0], "global")
        self.assertAlmostEqual(factors["k_MODIS"].iloc[0], 4.0)


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.monthly = build_monthly(ratio=4.0)
        self.harm, self.factors = harmonize(self.monthly)

    def test_sources_follow_coverage(self):
        src = self.harm.set_index(["lat_cell", "lon_cell", "year", "month"])["source"]
        self.assertEqual(src[(4.0, 11.0, 2001, 3)], "MODIS_Terra")
        self.assertEqual(src[(4.0, 11.0, 2005, 3)], "MODIS")
        self.assertEqual(src[(4.0, 11.0, 2015, 3)], "VIIRS_SNPP")

    def test_scaled_modis_matches_viirs_level(self):
        h = self.harm.set_index(["lat_cell", "lon_cell", "year", "month"])
        self.assertAlmostEqual(h.loc[(4.0, 11.0, 2005, 3), "n_harm"], 40.0)
        self.assertAlmostEqual(h.loc[(4.0, 11.0, 2001, 3), "n_harm"], 40.0)
        self.assertEqual(h.loc[(4.0, 11.0, 2015, 3), "n_harm"], 40)

    def test_band_contains_estimate(self):
        self.assertTrue((self.harm["n_low"] <= self.harm["n_harm"]).all())
        self.assertTrue((self.harm["n_high"] >= self.harm["n_harm"]).all())


class ValidateTests(unittest.TestCase):
    def test_harmonized_beats_raw_on_held_out_years(self):
        report = validate(build_monthly(ratio=4.0), fit_years=(2012, 2018), test_years=(2019, 2025))
        self.assertAlmostEqual(report["harmonized"]["bias_ratio"], 1.0, places=6)
        self.assertAlmostEqual(report["raw"]["bias_ratio"], 0.25, places=6)
        self.assertLess(report["harmonized"]["mae"], report["raw"]["mae"])


class PivotTests(unittest.TestCase):
    def test_missing_platform_columns_are_added(self):
        wide = pivot_platforms(build_monthly(years=range(2020, 2021)))
        for col in ("VIIRS_NOAA20", "VIIRS_NOAA21"):
            self.assertIn(col, wide.columns)
            self.assertEqual(wide[col].sum(), 0)


if __name__ == "__main__":
    unittest.main()
