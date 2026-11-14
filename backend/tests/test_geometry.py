import unittest

import numpy as np

from ember_api.geometry import bbox_of, bbox_ring, points_in_ring, rings_of


class GeometryTests(unittest.TestCase):
    def test_square(self):
        ring = bbox_ring(0, 0, 1, 1)
        inside = points_in_ring(np.array([0.5, 1.5, 0.0001]), np.array([0.5, 0.5, 0.0001]), ring)
        self.assertEqual(inside.tolist(), [True, False, True])
        self.assertEqual(bbox_of(ring), (0.0, 0.0, 1.0, 1.0))

    def test_triangle_and_multipolygon(self):
        tri = [[0, 0], [2, 0], [0, 2], [0, 0]]
        self.assertEqual(points_in_ring(np.array([0.5, 1.5]), np.array([0.5, 1.5]), tri).tolist(), [True, False])
        geom = {"type": "MultiPolygon", "coordinates": [[tri], [bbox_ring(5, 5, 6, 6)]]}
        self.assertEqual(len(rings_of(geom)), 2)
        with self.assertRaises(ValueError):
            rings_of({"type": "Point", "coordinates": [0, 0]})


if __name__ == "__main__":
    unittest.main()
