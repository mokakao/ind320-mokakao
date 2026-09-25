"""Front page of the IND320 project app.

Streamlit builds the sidebar menu automatically from the files in the pages/
folder, so this file is both the home page and the entry point that Streamlit
Cloud runs. Each page lives in its own .py file, as required by the assignment.
"""

import streamlit as st

from utils import load_data

# set_page_config must be the first Streamlit call in the script.
st.set_page_config(
    page_title="IND320 - Reservoir dashboard",
    page_icon="💧",
    layout="wide",
)

st.title("💧 Norwegian hydropower reservoirs")
st.subheader("IND320 project work, part 1 - dashboard basics")

st.markdown(
    """
This app is the first part of the IND320 project. It reads the weekly reservoir
statistics published by NVE and shows them in a small dashboard.

**Use the menu in the sidebar to move between the pages:**

| Page | Content |
| --- | --- |
| **Home** | This page: background and a short data summary |
| **Data table** | One row per series, with a line chart of the first month |
| **Plots** | A plot with a column selector and a month selector |
| **About** | Notes on the data source and the project |
"""
)

# Load the data once here as well, so the front page can show that the file is
# readable and give the reader a sense of what the data covers. The result is
# cached, so the other pages reuse it instead of reading the file again.
data = load_data()

st.markdown("### The data at a glance")

# st.columns places elements side by side instead of stacked vertically.
left, middle, right = st.columns(3)
left.metric("Weeks of data", f"{len(data):,}".replace(",", " "))
middle.metric(
    "Period",
    f"{data.index.min():%b %Y} - {data.index.max():%b %Y}",
)
right.metric("Latest fill level", f"{data['fill_level'].iloc[-1]:.1%}")

st.caption(
    "Source: NVE reservoir statistics (D2Dbook/data/reservoirs.csv). "
    "The figures on this page cover Norway as a whole."
)

with st.sidebar:
    st.markdown("### About this app")
    st.write(
        "IND320 - Data to decision, autumn 2026. "
        "Weekly reservoir fill levels for Norway."
    )
