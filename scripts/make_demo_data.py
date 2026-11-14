"""Build data/processed/{hotspots_monthly,harmonized_monthly}.parquet from synthetic data.

Usage: PYTHONPATH=pipeline python scripts/make_demo_data.py [--bbox S W N E] [--seed 0]
Replace with the Kaggle outputs once the global dataset is processed.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

from ember_pipeline.harmonize import harmonize, validate  # noqa: E402
from ember_pipeline.synth import synthetic_monthly  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bbox", nargs=4, type=float, default=[3.0, 9.0, 8.0, 15.0], metavar=("S", "W", "N", "E"))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", default=str(ROOT / "data" / "processed"))
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    monthly = synthetic_monthly(bbox=tuple(args.bbox), seed=args.seed)
    print(f"synthetic monthly: {len(monthly):,} rows ({time.time()-t0:.0f}s)")
    monthly.to_parquet(out / "hotspots_monthly.parquet", index=False)

    harmonized, factors = harmonize(monthly)
    harmonized.to_parquet(out / "harmonized_monthly.parquet", index=False)
    factors.to_parquet(out / "calibration_factors.parquet", index=False)
    print(f"harmonized: {len(harmonized):,} rows; factor levels: {factors['level_MODIS'].value_counts().to_dict()}")
    report = validate(monthly, fit_years=(2012, 2018), test_years=(2019, 2025))
    print("validation 2019-2025 | raw bias %.2f -> harmonized bias %.2f | MAE %.1f -> %.1f | r %.3f -> %.3f" % (
        report["raw"]["bias_ratio"], report["harmonized"]["bias_ratio"], report["raw"]["mae"],
        report["harmonized"]["mae"], report["raw"]["pearson_r"], report["harmonized"]["pearson_r"]))
    print(f"done in {time.time()-t0:.0f}s -> {out}")


if __name__ == "__main__":
    main()
