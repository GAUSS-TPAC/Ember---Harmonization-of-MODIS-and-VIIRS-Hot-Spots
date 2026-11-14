import io
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from ember_pipeline.aggregate import (OUTPUT_COLUMNS, aggregate_csv, aggregate_frame,
                                      aggregate_paths, country_from_name, merge_partials)
from ember_pipeline.grid import Grid

CSV = """latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,confidence,version,bright_t31,frp,daynight,type
4.01,11.01,330,1,1,2020-01-05,1030,Terra,MODIS,80,6.1,300,10.0,D,0
4.05,11.09,330,1,1,2020-01-20,2230,Terra,MODIS,50,6.1,300,4.0,N,0
4.05,11.09,330,1,1,2020-01-20,2230,Terra,MODIS,10,6.1,300,4.0,N,0
4.05,11.09,330,1,1,2020-02-01,1030,Aqua,MODIS,90,6.1,300,7.0,D,0
4.15,11.09,330,1,1,2020-01-05,1030,Terra,MODIS,80,6.1,300,2.0,D,2
"""


class AggregateFrameTests(unittest.TestCase):
    def setUp(self):
        self.raw = pd.read_csv(io.StringIO(CSV))

    def test_counts_per_cell_month_platform(self):
        out = aggregate_frame(self.raw, Grid(0.1), "Cameroon")
        self.assertEqual(list(out.columns), OUTPUT_COLUMNS)
        rows = {(r.platform, r.year, r.month): (r.n, r.n_day, r.n_night, r.frp_sum)
                for r in out.itertuples()}
        self.assertEqual(rows[("MODIS_Terra", 2020, 1)], (2, 1, 1, 14.0))
        self.assertEqual(rows[("MODIS_Aqua", 2020, 2)], (1, 1, 0, 7.0))
        self.assertEqual(len(out), 2)  # low confidence and type 2 rows excluded

    def test_chunked_read_equals_single_read(self):
        whole = aggregate_csv(io.StringIO(CSV), Grid(0.1), "Cameroon", chunksize=1_000)
        chunked = aggregate_csv(io.StringIO(CSV), Grid(0.1), "Cameroon", chunksize=2)
        pd.testing.assert_frame_equal(whole, chunked)

    def test_merge_partials_sums_counts(self):
        a = aggregate_frame(self.raw, Grid(0.1), "Cameroon")
        merged = merge_partials([a, a])
        self.assertEqual(merged["n"].sum(), 2 * a["n"].sum())
        self.assertEqual(merged["frp_sum"].sum(), 2 * a["frp_sum"].sum())

    def test_empty_input(self):
        self.assertTrue(merge_partials([]).empty)


class FileTests(unittest.TestCase):
    def test_country_from_name(self):
        self.assertEqual(country_from_name("modis/modis_2020_Cameroon.csv"), "Cameroon")
        self.assertEqual(country_from_name("viirs-snpp_2019_Central_African_Republic.csv"),
                         "Central_African_Republic")
        self.assertEqual(country_from_name("modis_2026_world.csv.gz"), "world")

    def test_zip_and_csv_inputs(self):
        with TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "modis_2020_Cameroon.csv").write_text(CSV)
            with zipfile.ZipFile(tmp / "modis_2020_all_countries.zip", "w") as z:
                z.writestr("modis_2020_Chad.csv", CSV)
                z.writestr("readme.txt", "ignored")
            out = aggregate_paths([tmp / "modis_2020_Cameroon.csv", tmp / "modis_2020_all_countries.zip"], Grid(0.1))
            self.assertEqual(sorted(out["country"].unique()), ["Cameroon", "Chad"])
            self.assertEqual(out["n"].sum(), 6)


if __name__ == "__main__":
    unittest.main()
