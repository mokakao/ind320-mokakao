"""The front page: where you are, and where to go next.

Part 3's front page was a table of every page in the app. With ten pages that
stops being useful, so this one does two things instead: it says what the
reservoirs are doing right now, and it points at the three places where the
actual work happens. The full list still exists - it is the sidebar.
"""

import streamlit as st

from modules import nve, theme
from utils import available_years, load_reservoirs

st.title("💧 Norwegian reservoirs and cross-border power")
st.caption("IND320 project work, part 4 - machine learning and visualisation")

st.markdown(
    """
Four sources about Norwegian hydropower: how full the reservoirs are
(NVE Magasinstatistikk), how much power crosses the cables to Denmark, Germany
and England (ENTSO-E), what the weather has been doing over each region
(Open-Meteo ERA5), and what the krone is worth (Norges Bank).
"""
)

# A short, cheap summary: only the most recent years are downloaded for this,
# so the front page stays quick even on a cold start.
_, newest = available_years()
recent = load_reservoirs(newest - 1, newest)
norway = nve.one_area(recent, "NO", 0)

left, middle, right = st.columns(3)
left.metric("Latest fill level", f"{norway['fill_level'].iloc[-1]:.1%}")
middle.metric(
    "Stored energy",
    f"{norway['stored_TWh'].iloc[-1]:.1f} TWh",
    help=f"out of a capacity of {norway['capacity_TWh'].iloc[-1]:.1f} TWh",
)
right.metric("Change last week", f"{norway['fill_level_change'].iloc[-1]:+.2%}")

st.caption(
    f"Norway as a whole, week ending {norway.index[-1]:%d %B %Y}. "
    "Source: NVE Magasinstatistikk API."
)

st.divider()

st.markdown("### Start here")

one, two, three = st.columns(3)

with one:
    st.markdown(f"##### :material/map: **Map**")
    st.write(
        "Pick an area by clicking it. The choice follows you to every other "
        "page, so the weather, the outliers and the forecast all refer to the "
        "same place."
    )
    st.page_link("views/map.py", label="Open the map", icon=":material/arrow_forward:")

with two:
    st.markdown(f"##### :material/scatter_plot: **Analysis**")
    st.write(
        "Unusual rainfall and temperature, the seasonal shape of the filling, "
        "and how weather and reservoir levels move together."
    )
    st.page_link("views/outliers.py", label="Outliers and anomalies",
                 icon=":material/arrow_forward:")
    st.page_link("views/correlation.py", label="Weather against filling",
                 icon=":material/arrow_forward:")

with three:
    st.markdown(f"##### :material/trending_up: **Forecast**")
    st.write(
        "An online SARIMAX model from the River framework, predicting the "
        "coming months' filling from history and selected weather."
    )
    st.page_link("views/forecast.py", label="Run a forecast",
                 icon=":material/arrow_forward:")

st.divider()

selected_type = st.session_state.get("chosen_area_type")
selected_number = st.session_state.get("chosen_area_number")
if selected_type:
    st.info(
        f"Current selection: **{nve.AREA_TYPES.get(selected_type, selected_type)}**"
        + (f", area {selected_number}" if selected_number is not None else "")
        + ". Change it on the map or in the sidebar."
    )
else:
    st.info(
        "Nothing selected yet. The map is the quickest way to choose an area; "
        "the sidebar controls do the same job on the pages that need them."
    )
