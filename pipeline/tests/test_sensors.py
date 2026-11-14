import unittest

import pandas as pd

from ember_pipeline.sensors import SchemaError, normalize, platform_of, quality_mask


def raw(**overrides):
    base = {
        "latitude": [4.0, 4.1, 4.2, 4.3],
        "longitude": [11.0, 11.1, 11.2, 11.3],
        "acq_date": ["2020-01-05"] * 4,
        "satellite": ["Terra", "Aqua", "N", "1"],
        "instrument": ["MODIS", "MODIS", "VIIRS", "VIIRS"],
        "confidence": [85, 20, "n", "l"],
        "frp": [10.0, 5.0, 3.0, 1.0],
        "daynight": ["D", "N", "D", "N"],
        "type": [0, 0, 0, 0],
    }
    base.update(overrides)
    return pd.DataFrame(base)


class PlatformTests(unittest.TestCase):
    def test_archive_and_nrt_codes_map_to_same_platform(self):
        df = pd.DataFrame({"instrument": ["MODIS", "MODIS", "VIIRS", "VIIRS"],
                           "satellite": ["Terra", "T", "N20", "1"]})
        got = platform_of(df["instrument"], df["satellite"]).tolist()
        self.assertEqual(got, ["MODIS_Terra", "MODIS_Terra", "VIIRS_NOAA20", "VIIRS_NOAA20"])


class QualityTests(unittest.TestCase):
    def test_low_confidence_rows_are_dropped_per_instrument_rule(self):
        self.assertEqual(quality_mask(raw()).tolist(), [True, False, True, False])

    def test_non_vegetation_types_are_dropped_but_missing_type_is_kept(self):
        df = raw(confidence=[85, 85, "h", "h"], type=[0, 2, 3, None])
        self.assertEqual(quality_mask(df).tolist(), [True, False, False, True])

    def test_frame_without_type_column_keeps_confident_rows(self):
        df = raw().drop(columns=["type"])
        self.assertEqual(quality_mask(df).tolist(), [True, False, True, False])


class NormalizeTests(unittest.TestCase):
    def test_output_has_contract_columns_only(self):
        out = normalize(raw())
        self.assertEqual(list(out.columns), ["platform", "latitude", "longitude", "acq_date", "frp", "is_day"])
        self.assertEqual(out["platform"].tolist(), ["MODIS_Terra", "VIIRS_SNPP"])
        self.assertEqual(out["is_day"].tolist(), [True, True])

    def test_missing_column_fails_fast(self):
        with self.assertRaises(SchemaError):
            normalize(raw().drop(columns=["frp"]))

    def test_unknown_satellite_fails_fast(self):
        with self.assertRaises(SchemaError):
            normalize(raw(satellite=["Terra", "Aqua", "N", "XYZ"], confidence=[85, 85, "h", "h"]))


if __name__ == "__main__":
    unittest.main()
