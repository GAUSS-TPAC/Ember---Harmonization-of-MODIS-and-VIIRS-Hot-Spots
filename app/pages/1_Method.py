from pathlib import Path
import sys

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.config import get_data_mode
from app.data import get_validation_table
from app.ui import render_data_mode_banner


st.set_page_config(page_title="Method | Burning Activity Calendar", layout="wide")
st.session_state["controls_revision"] = -1
render_data_mode_banner()
st.title("Method")
main_page = st.Page(
    str(Path(__file__).resolve().parents[1] / "streamlit_app.py"),
    title="Burning Activity Calendar",
)
st.page_link(main_page, label="Back to Burning Activity Calendar")

st.header("Harmonization steps")
st.markdown(
    """
1. **Filter detections.** Keep MODIS detections with confidence at least 30, and VIIRS detections with confidence `n` or `h`; keep fire type 0 only.
2. **Choose the VIIRS reference.** Use Suomi-NPP (S-NPP) VIIRS as the reference sensor.
3. **Grid detections.** Assign detections to 0.1-degree cells and UTC dates, counting each cell, day, and sensor.
4. **Aggregate by month.** Sum daily counts into cell-month totals for each sensor.
5. **Calibrate the overlap.** From 2012 onward, calculate one MODIS-to-VIIRS ratio for each 1-degree block and calendar month. If a block-month has fewer than 50 VIIRS detections, use the wider-region ratio.
6. **Build the harmonized series.** Before 2012, use observed MODIS counts. From 2012 onward, use MODIS where available. After MODIS ends, estimate MODIS-equivalent counts from VIIRS and the calibration ratio.
7. **Validate.** Hold out two overlap years, predict MODIS counts from VIIRS, and report correlation and mean absolute percentage error by month.
"""
)
st.code(
    "N_modis_estimated(cell, month) = k(block, calendar month) x N_viirs(cell, month)",
    language="text",
)

st.header("Validation")
try:
    validation = get_validation_table()
except Exception as error:
    st.error(f"Could not load validation results: {error}")
    if st.button("Retry"):
        st.rerun()
    st.stop()

if not validation.empty:
    if get_data_mode() == "mock":
        st.caption("PLACEHOLDER values from synthetic data. Not a real validation result.")
    st.dataframe(validation, hide_index=True, use_container_width=True)
    st.write(
        "Here, r describes how closely predicted and observed counts move together "
        "(closer to 1 is stronger agreement); MAPE is the average prediction error "
        "as a percentage (lower is better)."
    )
else:
    st.info("No validation results are available.")

st.header("Limitations")
st.markdown(
    """
- VIIRS detects some small or cool fires that MODIS misses.
- The sensors pass over at different local times.
- A single calibration ratio assumes the relationship between sensors stays stable over the years.
"""
)

st.header("Data citation")
st.write("NASA FIRMS MODIS and VIIRS S-NPP active fire products.")
st.warning("TODO: add the exact data citation text supplied by the data provider.")
