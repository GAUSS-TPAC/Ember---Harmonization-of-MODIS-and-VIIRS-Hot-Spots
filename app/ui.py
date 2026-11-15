import streamlit as st

from app.config import get_data_mode


DEMO_BANNER = (
    "DEMO DATA: synthetic values, not real fire observations. "
    "Validation numbers shown are placeholders."
)


def render_data_mode_banner() -> None:
    if get_data_mode() == "mock":
        st.warning(DEMO_BANNER, icon="⚠️")
