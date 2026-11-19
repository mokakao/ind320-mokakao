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

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from modules import entsoe_flows, theme
from utils import flow_countries, flow_years, load_flows

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

        figure = go.Figure(
            go.Pie(
                labels=["Out of Norway", "Into Norway"],
                values=list(totals),
                # Pie charts are hard to read by area, so the share and the
                # value are written on each slice instead of being left to the
                # eye. Plotly also gives the exact TWh on hover.
                textinfo="label+percent",
                hovertemplate="%{label}<br>%{value:.2f} TWh<extra></extra>",
                marker=dict(colors=[theme.WATER, theme.AMBER],
                            line=dict(color="white", width=2)),
                sort=False,
                hole=0.35,
            )
        )
        figure.update_layout(
            title=f"{country} ({entsoe_flows.CONNECTIONS_BY_COUNTRY[country]}), {year}",
            height=380, margin=dict(l=10, r=10, t=50, b=10), showlegend=False,
        )
        st.plotly_chart(figure, width="stretch")

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

        figure = go.Figure()
        # One line per cable and direction, so six lines when all three cables
        # have data. Imports are dashed so the pairs are easy to tell apart.
        for i, ((name, direction), group) in enumerate(
            selection.groupby(["country", "direction"])
        ):
            figure.add_trace(go.Scatter(
                x=group["timestamp"], y=group["mw"], mode="lines",
                name=f"{name} {direction}",
                line=dict(
                    width=1.0,
                    color=theme.COLORWAY[i % len(theme.COLORWAY)],
                    dash="solid" if direction == "export" else "dash",
                ),
            ))
        theme.apply(
            figure,
            title=f"{', '.join(month_names[m] for m in months)} {year}",
            x="Time", y="Flow (MW, hourly average)", height=430,
        )
        # Six overlapping hourly series is a lot of ink; a range slider lets you
        # zoom into a week without reloading anything.
        figure.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
        st.plotly_chart(figure, width="stretch")

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
