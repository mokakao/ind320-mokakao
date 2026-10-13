"""Page 2: the reservoir data as a table, one row per area.

Part 1 of the project had one row per column of the CSV. The updated task asks
for the radio button to drive the table as well, so the rows are now the area
numbers of whichever area type is selected - NO1 to NO5 for the price areas,
VASS1 to VASS3 for the watercourses, and a single row for Norway as a whole.

The small chart in each row is st.column_config.LineChartColumn, which turns a
list of numbers in a cell into a sparkline.
"""

import pandas as pd
import streamlit as st

from modules import nve
from utils import area_label, load_areas, load_reservoirs, reservoir_controls

st.set_page_config(page_title="Reservoir table - IND320", page_icon="📋", layout="wide")

st.title("📋 Reservoir table")

area_type, first_year, last_year = reservoir_controls()

data = load_reservoirs(first_year, last_year)
areas = load_areas()
numbers = nve.area_numbers(data, area_type)

if not numbers:
    st.warning("No data for this area type in the chosen interval.")
    st.stop()

# Which series the sparkline and the summary numbers describe. Keeping this on
# the page rather than in the sidebar makes it clear that it only affects the
# table, while the sidebar controls affect every page.
series = st.selectbox(
    "Series shown in the chart",
    options=nve.VALUE_COLUMNS,
    help="The sparkline and the summary columns both follow this choice",
)

st.markdown(f"#### {nve.AREA_TYPES[area_type]}, {first_year}-{last_year}")

rows = []
for number in numbers:
    one = nve.one_area(data, area_type, number)[series]
    rows.append(
        {
            "Area": area_label(areas, area_type, number),
            "Trend": one.tolist(),
            "Latest": one.iloc[-1],
            "Mean": one.mean(),
            "Min": one.min(),
            "Max": one.max(),
        }
    )

table = pd.DataFrame(rows)

st.dataframe(
    table,
    hide_index=True,
    width="stretch",
    column_config={
        "Area": st.column_config.TextColumn("Area", width="small"),
        # Each row is scaled on its own, so the shapes are comparable even when
        # the areas differ a lot in size.
        "Trend": st.column_config.LineChartColumn(
            f"{series}, {first_year}-{last_year}",
            width="large",
            help="One point per weekly measurement in the downloaded interval",
        ),
        "Latest": st.column_config.NumberColumn(format="%.3f"),
        "Mean": st.column_config.NumberColumn(format="%.3f"),
        "Min": st.column_config.NumberColumn(format="%.3f"),
        "Max": st.column_config.NumberColumn(format="%.3f"),
    },
)

st.caption(
    "fill_level is a share of capacity (0-1), capacity_TWh and stored_TWh are "
    "energy in TWh, and fill_level_change is the change since the previous week."
)

with st.expander("What the areas mean"):
    st.dataframe(
        areas[areas["area_type"] == area_type][
            ["name", "long_name", "description"]
        ],
        hide_index=True,
        width="stretch",
    )

with st.expander("Show the raw rows behind the table"):
    st.dataframe(data[data["area_type"] == area_type], width="stretch")
