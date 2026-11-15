from typing import Optional, Tuple


def classify_anomaly(count: float, median: float) -> Tuple[Optional[float], str]:
    """Return the count-to-median ratio and its SPEC-defined label."""
    if median == 0:
        return None, "no baseline"

    ratio = count / median
    if ratio < 0.5:
        label = "below normal"
    elif ratio <= 1.5:
        label = "normal"
    elif ratio <= 3:
        label = "above normal"
    else:
        label = "extreme"
    return ratio, label