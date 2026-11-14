"""Command line entry point: python -m ember_pipeline aggregate ..."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .aggregate import aggregate_paths
from .grid import Grid


def _expand(inputs: list[str]) -> list[Path]:
    paths: list[Path] = []
    for item in inputs:
        p = Path(item)
        if p.is_dir():
            paths.extend(sorted(q for q in p.rglob("*") if q.suffix.lower() in {".csv", ".zip", ".gz"}))
        else:
            paths.append(p)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ember_pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    agg = sub.add_parser("aggregate", help="raw FIRMS CSV/zip -> cell x month parquet")
    agg.add_argument("inputs", nargs="+", help="CSV, CSV.GZ, ZIP files or directories")
    agg.add_argument("--out", required=True, help="output .parquet (or .csv) path")
    agg.add_argument("--res", type=float, default=0.1, help="grid resolution in degrees")
    agg.add_argument("--chunksize", type=int, default=1_000_000)

    args = parser.parse_args(argv)
    if args.command == "aggregate":
        start = time.time()
        grid = Grid(args.res)
        log = lambda name: print(f"  {name}", file=sys.stderr, flush=True)
        result = aggregate_paths(_expand(args.inputs), grid, args.chunksize, on_file=log)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.suffix.lower() == ".csv":
            result.to_csv(out, index=False)
        else:
            result.to_parquet(out, index=False)
        print(f"{len(result)} rows -> {out} ({time.time() - start:.1f}s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
