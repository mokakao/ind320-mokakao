"""Page 2: the reservoir data, as a table and as plots.

Part 2 had these on two separate pages. They answer the same question with the
same controls, so they are now two tabs on one page, which leaves room in the
menu for the three new analysis pages without the sidebar turning into a list
of eight things.
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from modules import nve, theme
from utils import area_label, load_areas, load_reservoirs, reservoir_controls

st.title("💧 Reservoirs")

area_type, first_year, last_year = reservoir_controls()

data = load_reservoirs(first_year, last_year)
areas = load_areas()
numbers = nve.area_numbers(data, area_type)

if not numbers:
    st.warning("No data for this area type in the chosen interval.")
    st.stop()

st.markdown(f"#### {nve.AREA_TYPES[area_type]}, {first_year}-{last_year}")

table_tab, plot_tab = st.tabs(["Table", "Plots"])

with table_tab:
    series = st.selectbox(
        "Series shown in the chart",
        options=nve.VALUE_COLUMNS,
        help="The sparkline and the summary columns both follow this choice",
        key="table_series",
    )

    rows = []
    for number in numbers:
        one = nve.one_area(data, area_type, number)[series]
        rows.append({
            "Area": area_label(areas, area_type, number),
            "Trend": one.tolist(),
            "Latest": one.iloc[-1],
            "Mean": one.mean(),
            "Min": one.min(),
            "Max": one.max(),
        })

    st.dataframe(
        pd.DataFrame(rows),
        hide_index=True,
        width="stretch",
        column_config={
            "Area": st.column_config.TextColumn("Area", width="small"),
            "Trend": st.column_config.LineChartColumn(
                f"{series}, {first_year}-{last_year}", width="large",
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
            areas[areas["area_type"] == area_type][["name", "long_name", "description"]],
            hide_index=True, width="stretch",
        )

with plot_tab:
    column = st.selectbox(
        "Series to plot",
        options=["All series (scaled)"] + nve.VALUE_COLUMNS,
        help="One series for every area, or all series at once for a single area",
        key="plot_series",
    )

    if column == "All series (scaled)":
        # The five series use wildly different units - capacity is around
        # 87 TWh, fill level is between 0 and 1 - so on one axis you would see
        # two lines and three flat ones. Scaling loses the units but keeps the
        # shapes comparable.
        number = numbers[0]
        one = nve.one_area(data, area_type, number)
        scaled = one.apply(
            lambda s: (s - s.min()) / (s.max() - s.min()) if s.max() > s.min()
            else s * 0 + 0.5
        )
        figure = px.line(scaled, labels={"value": "Scaled value (0-1)", "index": "Date"})
        theme.apply(
            figure,
            title=f"All series for {area_label(areas, area_type, number)}, scaled",
            x="Date", y="Scaled value (0-1)",
        )
        st.info(
            "The series use different units, so they are scaled to 0-1 over the "
            "period. Only the first area of the type is shown - pick a single "
            "series to compare the areas against each other."
        )
    else:
        wide = nve.wide(data, area_type, column)
        named = wide.rename(columns={n: area_label(areas, area_type, n) for n in wide.columns})
        unit = "TWh" if column.endswith("TWh") else "Share of capacity"
        figure = px.line(named)
        theme.apply(figure, title=f"{column} per area", x="Date", y=f"{column} ({unit})")
        if not column.endswith("TWh"):
            # fill_level and fill_level_change are shares, and nobody reads a
            # reservoir as 0.734 full.
            theme.percent_axis(figure)

    # Plotly's unified hover is what makes this better than the old static
    # version: one tooltip listing every area at the week you point at, which
    # is exactly the comparison the page exists for.
    st.plotly_chart(figure, width="stretch")
