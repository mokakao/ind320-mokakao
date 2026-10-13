"""Front page of the IND320 project app.

Streamlit builds the sidebar menu from the files in pages/, so this file is both
the landing page and the entry point Streamlit Cloud runs.
"""

import streamlit as st

from modules import nve
from utils import available_years, load_reservoirs

st.set_page_config(
    page_title="IND320 - Reservoirs and power flow",
    page_icon="💧",
    layout="wide",
)

st.title("💧 Norwegian reservoirs and cross-border power")
st.subheader("IND320 project work, part 2 - data sources")

st.markdown(
    """
This app pulls two live data sources together: how full the Norwegian
hydropower reservoirs are, and how much power is flowing across the cables to
Denmark, Germany and England.

**Use the menu in the sidebar:**

| Page | Content |
| --- | --- |
| **Home** | This page |
| **Reservoir table** | One row per area, with a sparkline per series |
| **Reservoir plots** | The same data as lines, one per area |
| **Power flow** | Exchange with the neighbours, from MongoDB |
| **About** | The data sources and how the pipeline fits together |

Nothing here reads a file. The reservoir pages call NVE's API directly, and the
power flow page reads a MongoDB database filled by the notebook.
"""
)

# A short, cheap summary: only the most recent years are downloaded for this,
# so the front page stays quick even on a cold start.
_, newest = available_years()
recent = load_reservoirs(newest - 1, newest)
norway = nve.one_area(recent, "NO", 0)

st.markdown("### Right now")

left, middle, right = st.columns(3)
left.metric("Latest fill level", f"{norway['fill_level'].iloc[-1]:.1%}")
middle.metric(
    "Stored energy",
    f"{norway['stored_TWh'].iloc[-1]:.1f} TWh",
    help=f"out of a capacity of {norway['capacity_TWh'].iloc[-1]:.1f} TWh",
)
right.metric(
    "Change last week",
    f"{norway['fill_level_change'].iloc[-1]:+.2%}",
)

st.caption(
    f"Norway as a whole, week ending {norway.index[-1]:%d %B %Y}. "
    "Source: NVE Magasinstatistikk API."
)

with st.sidebar:
    st.markdown("### About this app")
    st.write(
        "IND320 - Data to decision, autumn 2026. Reservoir levels from NVE and "
        "cross-border flows from ENTSO-E."
    )
