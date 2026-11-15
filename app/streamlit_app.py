from datetime import date
import math
from pathlib import Path
import sys

import altair as alt
import folium
import streamlit as st
from streamlit_folium import st_folium

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.area import (
    Area,
    area_area_km2,
    area_bounds,
    calendar_filename,
    area_polygon,
    area_refusal_message,
    normalize_area,
)
from app.data import (
    get_calendar,
    get_data_month_range,
    get_latest_anomaly,
    get_seasonal_profile,
    open_database,
)
from app.ui import render_data_mode_banner


MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
CAMEROON_BOUNDS = (2.0, 13.0, 8.5, 16.2)


def _set_area(area: Area | None, reset_drawings: bool = True) -> None:
    st.session_state["active_area"] = normalize_area(area) if area is not None else None
    st.session_state["area_revision"] = st.session_state.get("area_revision", 0) + 1
    if reset_drawings:
        st.session_state["map_generation"] = st.session_state.get("map_generation", 0) + 1


def _sync_area_inputs() -> None:
    revision = st.session_state.get("area_revision", 0)
    if st.session_state.get("controls_revision") == revision:
        return
    active_area = st.session_state.get("active_area")
    min_lat, max_lat, min_lon, max_lon = (
        area_bounds(active_area) if active_area is not None else CAMEROON_BOUNDS
    )
    st.session_state["input_min_lat"] = min_lat
    st.session_state["input_max_lat"] = max_lat
    st.session_state["input_min_lon"] = min_lon
    st.session_state["input_max_lon"] = max_lon
    st.session_state["controls_revision"] = revision


def _drawing_coordinates(drawings: object) -> tuple[tuple[float, float], ...] | None:
    if isinstance(drawings, dict) and drawings.get("type") == "FeatureCollection":
        features = drawings.get("features", [])
    elif isinstance(drawings, list):
        features = drawings
    elif isinstance(drawings, dict) and "geometry" in drawings:
        features = [drawings]
    else:
        return None
    if not features:
        return None
    geometry = features[-1].get("geometry", {})
    if geometry.get("type") != "Polygon":
        return None
    ring = geometry.get("coordinates", [[]])[0]
    if len(ring) < 4:
        return None
    return tuple((float(lat), float(lon)) for lon, lat in ring)


st.set_page_config(page_title="Burning Activity Calendar", page_icon="🔥", layout="wide")
render_data_mode_banner()
st.title("Burning Activity Calendar")
st.caption("MODIS-equivalent hotspots | Harmonized monthly activity")
method_page = st.Page(
    str(Path(__file__).resolve().parent / "pages" / "1_Method.py"),
    title="Method and validation",
)
st.page_link(method_page, label="Method and validation")

connection = open_database()
try:
    with st.spinner("Loading data coverage..."):
        data_month_range = get_data_month_range(connection)
except Exception as error:
    st.error(f"Could not load data: {error}")
    if st.button("Retry"):
        st.rerun()
    st.stop()

if data_month_range is None:
    st.error("The data file contains no year-month records.")
    st.stop()

data_start, data_end = data_month_range
data_years = list(range(data_start.year, data_end.year + 1))
st.session_state.setdefault("active_area", None)
st.session_state.setdefault("area_revision", 0)
st.session_state.setdefault("map_generation", 0)
_sync_area_inputs()

with st.sidebar:
    st.header("Area and period")
    st.caption("Draw a rectangle or polygon, or enter bounding coordinates.")
    if st.button("Try Cameroon", type="secondary"):
        _set_area(CAMEROON_BOUNDS)
        st.rerun()
    if st.button("Clear area"):
        _set_area(None)
        st.rerun()

    st.subheader("Coordinate box")
    first_row = st.columns(2)
    min_lat_input = first_row[0].number_input(
        "South latitude", min_value=-90.0, max_value=90.0,
        step=0.1, key="input_min_lat",
    )
    max_lat_input = first_row[1].number_input(
        "North latitude", min_value=-90.0, max_value=90.0,
        step=0.1, key="input_max_lat",
    )
    second_row = st.columns(2)
    min_lon_input = second_row[0].number_input(
        "West longitude", min_value=-180.0, max_value=180.0,
        step=0.1, key="input_min_lon",
    )
    max_lon_input = second_row[1].number_input(
        "East longitude", min_value=-180.0, max_value=180.0,
        step=0.1, key="input_max_lon",
    )
    if st.button("Use coordinate box"):
        if min_lat_input < max_lat_input and min_lon_input < max_lon_input:
            _set_area((min_lat_input, max_lat_input, min_lon_input, max_lon_input))
            st.rerun()
        else:
            st.error("Enter south/west values smaller than north/east values.")

    start_year = st.selectbox("Start year", data_years, index=0, key="start_year")
    start_min = data_start.month if start_year == data_start.year else 1
    start_max = data_end.month if start_year == data_end.year else 12
    start_month = st.selectbox(
        "Start month", range(start_min, start_max + 1),
        format_func=lambda month: MONTH_NAMES[month - 1], key="start_month_number",
    )
    end_year = st.selectbox(
        "End year", data_years, index=len(data_years) - 1, key="end_year"
    )
    end_min = data_start.month if end_year == data_start.year else 1
    end_max = data_end.month if end_year == data_end.year else 12
    end_month = st.selectbox(
        "End month", range(end_min, end_max + 1), index=end_max - end_min,
        format_func=lambda month: MONTH_NAMES[month - 1], key="end_month_number",
    )

start_month = date(start_year, start_month, 1)
end_month = date(end_year, end_month, 1)
active_area = st.session_state.get("active_area")

map_center = (7.5, 12.35)
map_zoom = 6
if active_area is not None:
    min_lat, max_lat, min_lon, max_lon = area_bounds(active_area)
    map_center = ((min_lat + max_lat) / 2, (min_lon + max_lon) / 2)

map_view = folium.Map(location=map_center, zoom_start=map_zoom, control_scale=True)
if active_area is not None:
    folium.GeoJson(
        area_polygon(active_area).__geo_interface__,
        name="Selected area",
        style_function=lambda _: {"color": "#d1495b", "weight": 3, "fillOpacity": 0.12},
    ).add_to(map_view)
folium.plugins.Draw(
    export=False,
    draw_options={
        "polyline": False,
        "polygon": {"allowIntersection": False, "showArea": True},
        "rectangle": True,
        "circle": False,
        "circlemarker": False,
        "marker": False,
    },
    edit_options={"edit": False, "remove": False},
).add_to(map_view)
map_output = st_folium(
    map_view,
    height=470,
    key=f"area_map_{st.session_state['map_generation']}",
    returned_objects=["all_drawings"],
)
new_coordinates = _drawing_coordinates(map_output.get("all_drawings"))
if new_coordinates is not None:
    normalized_drawing = normalize_area(new_coordinates)
    if normalized_drawing != active_area:
        _set_area(normalized_drawing)
        st.rerun()

if active_area is None:
    st.info("Select an area on the map or enter coordinates. Try Cameroon to begin.")
else:
    estimate = area_area_km2(active_area)
    st.caption(f"Selected area: approximately {estimate:,.0f} km²")
st.caption("Area estimate is approximate (equirectangular).")

if active_area is None:
    connection.close()
    st.stop()

refusal_message = area_refusal_message(active_area)
if refusal_message:
    st.error(refusal_message)
    connection.close()
    st.stop()
if start_month > end_month:
    st.error("Start month must not be after end month.")
    connection.close()
    st.stop()

loading = st.empty()
loading.markdown(
    '<div style="height:1.2rem;background:#e2e8f0;border-radius:4px;'
    'margin:0.6rem 0;animation:pulse 1.2s ease-in-out infinite"></div>',
    unsafe_allow_html=True,
)
try:
    with st.spinner("Loading harmonized monthly data..."):
        calendar = get_calendar(connection, active_area, start_month, end_month)
        seasonal = get_seasonal_profile(connection, active_area, start_month, end_month)
        anomaly = get_latest_anomaly(connection, active_area, start_month, end_month)
except Exception as error:
    loading.empty()
    st.error(f"Could not load data: {error}")
    if st.button("Retry"):
        st.rerun()
    connection.close()
    st.stop()
loading.empty()
connection.close()

if calendar.empty or calendar["count"].sum() == 0:
    st.info("No fires in this area for the selected period.")

calendar["month_name"] = calendar["month"].map(
    {index + 1: name[:3] for index, name in enumerate(MONTH_NAMES)}
)
calendar["status"] = calendar.apply(
    lambda row: ", ".join(
        status
        for status, enabled in (
            ("provisional", row["provisional"]),
            ("Terra-only", row["terra_only"]),
        )
        if enabled
    ) or "complete",
    axis=1,
)
calendar["provisional_mark"] = calendar["provisional"].map({True: "P", False: ""})

st.subheader("Burning activity calendar")
heatmap = (
    alt.Chart(calendar)
    .mark_rect(stroke="white", strokeWidth=1)
    .encode(
        x=alt.X(
            "month_name:N",
            sort=[name[:3] for name in MONTH_NAMES],
            title="Month",
        ),
        y=alt.Y("year:O", sort="descending", title="Year"),
        color=alt.Color(
            "count:Q", scale=alt.Scale(scheme="viridis"),
            title="MODIS-equivalent hotspots",
        ),
        tooltip=[
            alt.Tooltip("year:O", title="Year"),
            alt.Tooltip("month_name:N", title="Month"),
            alt.Tooltip("count:Q", title="MODIS-equivalent hotspots", format=",.2f"),
            alt.Tooltip("source:N", title="Source"),
            alt.Tooltip("status:N", title="Status"),
        ],
    )
    .properties(height=max(240, min(780, len(calendar["year"].unique()) * 20)))
)
marks = (
    alt.Chart(calendar)
    .mark_text(fontSize=9, fontWeight="bold", color="white")
    .encode(
        x=alt.X("month_name:N", sort=[name[:3] for name in MONTH_NAMES]),
        y=alt.Y("year:O", sort="descending"),
        text=alt.Text("provisional_mark:N"),
    )
)
st.altair_chart(heatmap + marks, use_container_width=True)
st.caption("P = provisional. Terra-only: January 2000 to June 2002; both statuses are also shown on hover.")

peak_month = int(seasonal.iloc[0]["peak_month"])
seasonal["month_name"] = seasonal["month"].map(
    {index + 1: name[:3] for index, name in enumerate(MONTH_NAMES)}
)
seasonal_chart = (
    alt.Chart(seasonal)
    .mark_area(opacity=0.24, color="#00798c")
    .encode(
        x=alt.X("month_name:N", sort=[name[:3] for name in MONTH_NAMES], title="Month"),
        y=alt.Y("p25:Q", title="MODIS-equivalent hotspots"),
        y2=alt.Y2("p75:Q"),
        tooltip=["month_name:N", "median:Q", "p25:Q", "p75:Q"],
    )
)
seasonal_line = (
    alt.Chart(seasonal)
    .mark_line(point=True, color="#d1495b", strokeWidth=3)
    .encode(
        x=alt.X("month_name:N", sort=[name[:3] for name in MONTH_NAMES]),
        y=alt.Y("median:Q"),
        tooltip=["month_name:N", "median:Q"],
    )
)
st.subheader(f"Seasonal profile | Peak month: {MONTH_NAMES[peak_month - 1]}")
st.altair_chart(seasonal_chart + seasonal_line, use_container_width=True)

st.download_button(
    "Download calendar CSV",
    data=calendar.drop(columns=["month_name", "status", "provisional_mark"]).to_csv(index=False),
    file_name=calendar_filename(active_area, start_month, end_month),
    mime="text/csv",
)

st.subheader("Latest complete month")
if anomaly is None:
    st.info("No complete month is available before the current calendar month.")
else:
    month_label = date(anomaly["year"], anomaly["month"], 1).strftime("%B %Y")
    provisional_label = "Provisional" if anomaly["provisional"] else "Not provisional"
    anomaly_colors = {
        "below normal": ("#fff1f2", "#9f1239"),
        "normal": ("#ecfdf5", "#166534"),
        "above normal": ("#fff7ed", "#9a3412"),
        "extreme": ("#7f1d1d", "#ffffff"),
        "no baseline": ("#f1f5f9", "#334155"),
    }
    background, foreground = anomaly_colors[anomaly["label"]]
    st.markdown(
        f'<div role="status" style="display:inline-block;padding:0.45rem 0.8rem;'
        f'background:{background};color:{foreground};font-weight:700;">'
        f'{anomaly["label"].capitalize()}</div>',
        unsafe_allow_html=True,
    )
    st.write(f"**{month_label}** · {provisional_label}")
    st.metric("MODIS-equivalent hotspots", f"{anomaly['count']:,.1f}")
    st.metric("Historical median, same month", f"{anomaly['median']:,.1f}")
    st.write(
        f"Ratio: {anomaly['ratio']:.2f}"
        if anomaly["ratio"] is not None
        else "Ratio: unavailable (no baseline)"
    )
    st.write(
        f"Percentile: {anomaly['percentile']:.0%}"
        if anomaly["percentile"] is not None
        else "Percentile: unavailable"
    )
    st.caption(
        f"Compared with {anomaly['baseline_years']} other baseline year(s); tested year excluded."
    )