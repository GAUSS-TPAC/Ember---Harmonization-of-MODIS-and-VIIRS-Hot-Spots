import unittest

import numpy as np

from ember_pipeline.grid import Grid


class GridTests(unittest.TestCase):
    def test_points_snap_to_south_west_corner(self):
        lat, lon = Grid(0.1).snap(np.array([4.07, -0.01, 89.99]), np.array([11.23, -179.99, 179.99]))
        self.assertEqual(lat.tolist(), [4.0, -0.1, 89.9])
        self.assertEqual(lon.tolist(), [11.2, -180.0, 179.9])

    def test_coarser_grid(self):
        lat, lon = Grid(0.25).snap(np.array([4.07]), np.array([11.23]))
        self.assertEqual((lat[0], lon[0]), (4.0, 11.0))

    def test_invalid_resolution_rejected(self):
        with self.assertRaises(ValueError):
            Grid(0)


if __name__ == "__main__":
    unittest.main()
