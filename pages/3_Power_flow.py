"""Page 4: cross-border power flow, read from MongoDB.

Two columns side by side, as the task asks for:

  * left  - pick a cable and a year, and see how much power went each way
  * right - pick any set of months, and see the flow over time

Everything on this page comes from MongoDB, not from the API. The notebook
downloads from ENTSO-E, stores the raw 15-minute values in Cassandra, averages
them to hourly with Spark and writes the result here. The deployed app has no
Cassandra of its own, which is the whole reason for that detour.
"""

import calendar

import matplotlib.pyplot as plt
import streamlit as st

from modules import entsoe_flows
from utils import flow_countries, flow_years, load_flows

st.set_page_config(page_title="Power flow - IND320", page_icon="🔌", layout="wide")

st.title("🔌 Cross-border power flow")

years = flow_years()
countries = flow_countries()

if not years:
    st.error(
        "No flow data in MongoDB yet. Run the notebook for part 2 first - it "
        "downloads from ENTSO-E and fills the database."
    )
    st.stop()

left, right = st.columns(2, gap="large")

# --- Left: how much went each way, for one cable and one year --------------
with left:
    st.markdown("### Exchange over a year")

    country = st.radio("Connection", options=countries, horizontal=True)
    # A different control from the radio button, as the task asks for.
    year = st.selectbox("Year", options=years)

    flows = load_flows(year)
    chosen = flows[flows["country"] == country]

    if chosen.empty:
        st.warning("Nothing stored for that combination.")
    else:
        # The values are hourly averages in MW, so one hour of it is that many
        # MWh. Summing the hours of a year therefore gives the energy, and
        # dividing by a million puts it in TWh, which is the unit the reservoir
        # data use as well.
        totals = chosen.groupby("direction")["mw"].sum() / 1_000_000
        totals = totals.reindex(["export", "import"]).fillna(0)

        fig, ax = plt.subplots(figsize=(5, 5))
        ax.pie(
            totals,
            labels=["Out of Norway", "Into Norway"],
            # Pie charts are hard to read by area, so the share is written on
            # each slice instead of being left to the eye.
            autopct="%1.1f%%",
            startangle=90,
            colors=["#2b7bba", "#f0a202"],
            wedgeprops={"edgecolor": "white"},
        )
        ax.set_title(f"{country} ({entsoe_flows.CONNECTIONS_BY_COUNTRY[country]}), {year}")
        ax.axis("equal")
        st.pyplot(fig)
        plt.close(fig)

        net = totals["export"] - totals["import"]
        st.metric(
            "Net export",
            f"{net:,.2f} TWh".replace(",", " "),
            help="Out of Norway minus into Norway over the whole year",
        )
        st.caption(
            f"Out: {totals['export']:.2f} TWh · In: {totals['import']:.2f} TWh"
        )

# --- Right: the flow over a chosen set of months ---------------------------
with right:
    st.markdown("### Flow over time")

    month_names = {number: calendar.month_abbr[number] for number in range(1, 13)}
    available = sorted(load_flows(year)["month"].unique())

    # st.pills allows several months at once, so the plot can show January and
    # July together without everything in between.
    months = st.pills(
        "Months",
        options=available,
        format_func=lambda number: month_names[number],
        selection_mode="multi",
        default=available[:1],
    )

    if not months:
        st.info("Pick at least one month.")
    else:
        selection = load_flows(year)
        selection = selection[selection["month"].isin(months)]

        fig, ax = plt.subplots(figsize=(7, 5))
        # One line per cable and direction, so six lines when all three cables
        # have data. Imports are dashed so the pairs are easy to tell apart.
        for (name, direction), group in selection.groupby(["country", "direction"]):
            ax.plot(
                group["timestamp"],
                group["mw"],
                label=f"{name} {direction}",
                linewidth=0.9,
                alpha=0.85,
                linestyle="-" if direction == "export" else "--",
            )

        ax.set_xlabel("Time")
        ax.set_ylabel("Flow (MW, hourly average)")
        ax.set_title(f"{', '.join(month_names[m] for m in months)} {year}")
        ax.grid(alpha=0.3)
        ax.legend(fontsize="x-small", ncol=2)
        fig.autofmt_xdate()
        fig.tight_layout()

        st.pyplot(fig)
        plt.close(fig)

        st.caption(f"{len(selection):,} hourly values shown.".replace(",", " "))

# --- Where the numbers come from -------------------------------------------
with st.expander("Where these data come from"):
    st.markdown(
        """
**Source:** the [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/),
dataset *cross-border physical flows*. Access needs a free account and a
security token, which is kept in the app's secrets and never in the repository.

**The three connections**

| Cable | Between | Area |
| --- | --- | --- |
| Skagerrak | Norway and Denmark | NO2 - DK1 |
| NordLink | Norway and Germany | NO2 - DE/LU |
| North Sea Link | Norway and England | NO2 - GB |

All three run out of price area NO2 in southwest Norway, which is part of why
power there is often the most expensive in the country.

**The route the data took**

ENTSO-E publishes the physical flow every 15 minutes. The notebook downloads
two years of it, stores the raw values in a local Cassandra database, uses
Spark to average them into hourly values, and writes those to MongoDB. This
page reads the hourly values from MongoDB - about 105 000 documents, a quarter
of the raw size.

A positive value means power actually moved that way during the hour. The two
directions are reported separately, so both can be above zero within the same
hour.
"""
    )
