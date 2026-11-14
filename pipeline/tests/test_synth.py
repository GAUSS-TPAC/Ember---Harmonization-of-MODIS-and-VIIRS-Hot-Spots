import unittest

from ember_pipeline.aggregate import OUTPUT_COLUMNS
from ember_pipeline.harmonize import harmonize
from ember_pipeline.synth import synthetic_monthly


class SynthTests(unittest.TestCase):
    def test_contract_and_sensor_gap(self):
        df = synthetic_monthly(bbox=(4.0, 11.0, 4.5, 11.5), years=(2010, 2014), seed=1)
        self.assertEqual(list(df.columns), OUTPUT_COLUMNS)
        by = df.groupby("platform")["n"].sum()
        self.assertGreater(by["VIIRS_SNPP"], 3 * (by["MODIS_Terra"] + by["MODIS_Aqua"]) / 5 * 3)

    def test_harmonization_runs_end_to_end(self):
        df = synthetic_monthly(bbox=(4.0, 11.0, 4.5, 11.5), years=(2008, 2016), seed=2)
        harm, factors = harmonize(df)
        self.assertFalse(harm["n_harm"].isna().any())
        self.assertTrue(set(harm["source"]) >= {"MODIS", "VIIRS_SNPP"})


if __name__ == "__main__":
    unittest.main()
