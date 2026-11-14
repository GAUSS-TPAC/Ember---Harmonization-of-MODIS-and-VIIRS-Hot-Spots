"""Ember pipeline: turn raw FIRMS hotspot CSVs into a monthly grid-cell aggregate.

Stage 1 (this package): raw detections -> cell x month x platform counts.
Stage 2 (notebook 02): calibrate MODIS counts onto a VIIRS-equivalent scale.
"""

__version__ = "0.1.0"
