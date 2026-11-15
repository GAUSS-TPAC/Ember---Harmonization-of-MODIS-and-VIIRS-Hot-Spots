import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "pipeline"))

from ember_pipeline.harmonize import harmonize  # noqa: E402
from ember_pipeline.synth import synthetic_monthly  # noqa: E402
from ember_api.main import create_app  # noqa: E402
from ember_api.store import HarmonizedStore  # noqa: E402


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        monthly = synthetic_monthly(bbox=(4.0, 11.0, 4.5, 11.5), years=(2008, 2020), seed=3)
        harmonized, _ = harmonize(monthly)
        cls.client = TestClient(create_app(HarmonizedStore(harmonized)))

    def test_health_and_coverage(self):
        self.assertEqual(self.client.get("/api/health").json()["status"], "ok")
        cov = self.client.get("/api/coverage").json()
        self.assertEqual(cov["first"][:4], "2008")

    def test_analyze_bbox(self):
        body = {"bbox": {"south": 4.0, "west": 11.0, "north": 4.3, "east": 11.3},
                "start": "2008-01", "end": "2020-12", "target": "2019-01"}
        r = self.client.post("/api/analyze", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertEqual(len(data["series"]), 13 * 12)
        self.assertEqual(data["anomaly"]["year"], 2019)
        self.assertGreater(data["area"]["cells"], 0)
        self.assertIn(data["season"]["peak"], (12, 1, 2))

    def test_analyze_polygon_and_csv(self):
        poly = {"type": "Polygon", "coordinates": [[[11.0, 4.0], [11.4, 4.0], [11.2, 4.4], [11.0, 4.0]]]}
        r = self.client.post("/api/analyze", json={"geometry": poly, "start": "2015-01", "end": "2015-12"})
        self.assertEqual(r.status_code, 200)
        csv = self.client.post("/api/export.csv", json={"geometry": poly, "start": "2015-01", "end": "2015-12"})
        self.assertEqual(csv.status_code, 200)
        self.assertTrue(csv.text.startswith("year,month,n_harm"))

    def test_validation_errors(self):
        self.assertEqual(self.client.post("/api/analyze", json={"start": "2015-01", "end": "2015-12"}).status_code, 422)
        self.assertEqual(self.client.post("/api/analyze", json={"bbox": {"south": 4, "west": 11, "north": 5, "east": 12},
                                                                 "start": "2016-01", "end": "2015-12"}).status_code, 422)

    def test_recent_hotspots_without_key_is_503(self):
        r = self.client.get("/api/hotspots/recent.csv", params={"south": 4, "west": 11, "north": 5, "east": 12})
        self.assertEqual(r.status_code, 503)


if __name__ == "__main__":
    unittest.main()


class SortedStoreTests(unittest.TestCase):
    def test_sorted_and_unsorted_selection_agree(self):
        monthly = synthetic_monthly(bbox=(4.0, 11.0, 4.6, 11.6), years=(2012, 2014), seed=9)
        harmonized, _ = harmonize(monthly)
        shuffled = HarmonizedStore(harmonized.sample(frac=1.0, random_state=0))
        ordered = HarmonizedStore(harmonized.sort_values(["lat_cell", "lon_cell"]))
        self.assertTrue(ordered._lat_sorted)
        self.assertFalse(shuffled._lat_sorted)
        poly = {"type": "Polygon", "coordinates": [[[11.1, 4.1], [11.45, 4.15], [11.3, 4.5], [11.1, 4.1]]]}
        a, b = shuffled.select(poly)["n_harm"].sum(), ordered.select(poly)["n_harm"].sum()
        self.assertAlmostEqual(a, b, places=3)
        self.assertGreater(a, 0)


class LazyStoreTests(unittest.TestCase):
    def test_lazy_matches_in_memory(self):
        import tempfile
        from ember_api.store import LazyHarmonizedStore
        monthly = synthetic_monthly(bbox=(4.0, 11.0, 4.6, 11.6), years=(2012, 2014), seed=11)
        harmonized, _ = harmonize(monthly)
        harmonized = harmonized.sort_values(["lat_cell", "lon_cell", "year", "month"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.parquet"
            harmonized.to_parquet(path, index=False, row_group_size=500)
            lazy, mem = LazyHarmonizedStore(path), HarmonizedStore(harmonized)
            poly = {"type": "Polygon", "coordinates": [[[11.1, 4.1], [11.45, 4.15], [11.3, 4.5], [11.1, 4.1]]]}
            for rng in ((None, None), ((2013, 3), (2014, 6))):
                a = lazy.select(poly, *rng)["n_harm"].sum()
                b = mem.select(poly, *rng)["n_harm"].sum()
                self.assertAlmostEqual(a, b, places=3)
            self.assertEqual(lazy.coverage().first, mem.coverage().first)
            self.assertEqual(lazy.coverage().last, mem.coverage().last)
