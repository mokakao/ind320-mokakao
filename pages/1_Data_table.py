"""Page 2 of the app: the imported data as a table.

The assignment asks for a table with one row per column of the imported data,
where each row shows a small line chart of the first month of that series.
That means the table is the *transpose* of the raw data: the series become
rows, and the values of the first month become a list inside one cell.
"""

import pandas as pd
import streamlit as st

from utils import load_data, month_labels

st.set_page_config(page_title="Data table - IND320", page_icon="📋", layout="wide")

st.title("📋 Data table")
st.write(
    "One row per series in the data set. The chart in each row shows the "
    "first month of that series, and the numbers summarise the whole period."
)

data = load_data()

# The first month in the data, e.g. "1995-01".
first_month = month_labels(data)[0]

# Rows whose date falls inside that first month. The reservoir data is weekly,
# so a month holds four or five measurements.
months = data.index.to_period("M").astype(str)
first_month_rows = data[months == first_month]

# Build one table row per column of the imported data. The "First month" cell
# holds a *list* of numbers, which is what LineChartColumn draws as a line.
table = pd.DataFrame(
    {
        "Series": data.columns,
        "First month": [first_month_rows[col].tolist() for col in data.columns],
        "Mean": [data[col].mean() for col in data.columns],
        "Min": [data[col].min() for col in data.columns],
        "Max": [data[col].max() for col in data.columns],
    }
)

st.markdown(f"#### First month in the data: **{first_month}**")

st.dataframe(
    table,
    hide_index=True,
    width="stretch",
    column_config={
        "Series": st.column_config.TextColumn("Series", width="medium"),
        # LineChartColumn turns the list in each cell into a small line chart.
        # Each row is scaled on its own, which matters here because the series
        # have very different ranges.
        "First month": st.column_config.LineChartColumn(
            f"First month ({first_month})",
            width="medium",
            help="One point per weekly measurement in the first month",
        ),
        "Mean": st.column_config.NumberColumn("Mean", format="%.3f"),
        "Min": st.column_config.NumberColumn("Min", format="%.3f"),
        "Max": st.column_config.NumberColumn("Max", format="%.3f"),
    },
)

st.caption(
    "fill_level is a share of capacity (0-1), capacity_TWh and stored_TWh are "
    "energy in TWh, and fill_level_change is the change since the previous week."
)

# The raw rows behind the table, hidden in an expander so the page stays clean.
with st.expander("Show the underlying rows of the first month"):
    st.dataframe(first_month_rows, width="stretch")
