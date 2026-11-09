"""Page 2: the reservoir data, as a table and as plots.

Part 2 had these on two separate pages. They answer the same question with the
same controls, so they are now two tabs on one page, which leaves room in the
menu for the three new analysis pages without the sidebar turning into a list
of eight things.
"""

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from modules import nve
from utils import area_label, load_areas, load_reservoirs, reservoir_controls

st.set_page_config(page_title="Reservoirs - IND320", page_icon="💧", layout="wide")

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

    fig, ax = plt.subplots(figsize=(11, 4.5))

    if column == "All series (scaled)":
        # The five series use wildly different units - capacity is around
        # 87 TWh, fill level is between 0 and 1 - so on one axis you would see
        # two lines and three flat ones. Scaling loses the units but keeps the
        # shapes comparable.
        number = numbers[0]
        one = nve.one_area(data, area_type, number)
        for name in one.columns:
            low, high = one[name].min(), one[name].max()
            scaled = (one[name] - low) / (high - low) if high > low else one[name] * 0 + 0.5
            ax.plot(one.index, scaled, label=name, linewidth=1.5)
        ax.set_ylabel("Scaled value (0-1)")
        ax.set_title(f"All series for {area_label(areas, area_type, number)}, scaled")
        st.info(
            "The series use different units, so they are scaled to 0-1 over the "
            "period. Only the first area of the type is shown - pick a single "
            "series to compare the areas against each other."
        )
    else:
        wide = nve.wide(data, area_type, column)
        for number in wide.columns:
            ax.plot(wide.index, wide[number],
                    label=area_label(areas, area_type, number), linewidth=1.5)
        unit = "TWh" if column.endswith("TWh") else "Share of capacity"
        ax.set_ylabel(f"{column} ({unit})")
        ax.set_title(f"{column} per area")

    ax.set_xlabel("Date")
    ax.grid(alpha=0.3)
    ax.legend(fontsize="small", ncol=2, loc="best")
    fig.autofmt_xdate()
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)
