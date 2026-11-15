import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data" / "processed"
PARQUET_PATHS = {
    "grid_monthly": DATA_DIR / "grid_monthly.parquet",
    "calibration": DATA_DIR / "calibration.parquet",
    "validation": DATA_DIR / "validation.parquet",
}

DATA_MODE = os.environ.get("DATA_MODE", "mock")
if DATA_MODE not in {"mock", "real"}:
    raise ValueError(
        f"Invalid DATA_MODE={DATA_MODE!r}; set DATA_MODE to 'mock' or 'real'."
    )


def get_data_mode() -> str:
    mode = os.environ.get("DATA_MODE", DATA_MODE)
    if mode not in {"mock", "real"}:
        raise ValueError(
            f"Invalid DATA_MODE={mode!r}; set DATA_MODE to 'mock' or 'real'."
        )
    return mode
