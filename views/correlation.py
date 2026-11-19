"""Sliding window correlation: when does the weather match the reservoirs?

A single correlation between rainfall and reservoir filling over a whole year
is close to useless, because both follow the season - you get a large number
that tells you only that Norway has winters. The question worth asking is
*when* the two move together, and that is what a sliding window answers: one
correlation per window position, so a relationship that exists in the autumn
and not in February shows up as a hump rather than being averaged away.

The page is the notebook exercise from the lectures turned into controls:
window length and lag are the two things worth turning, so they are the two
sliders. Lag is the interesting one. Rain does not reach a reservoir the day it
falls, and snow does not reach it until the melt, so if there is a delay the
correlation at lag 0 understates it and the lag scan at the bottom should find
a peak away from zero.

Weekly, not daily, because the reservoir statistics are weekly: NVE publishes
one row per ISO week dated the Sunday that ends it, so the daily weather is
summed or averaged onto the same Sundays before anything is correlated.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from modules import nve, quality, theme, weather
from utils import area_label, load_areas, load_reservoirs, weekly_from_daily

st.title(":material/compare_arrows: Correlation")

daily = st.session_state.get("weather_daily")
request = st.session_state.get("weather_request")
label = st.session_state.get("weather_label", "")

if daily is None or request is None:
    st.info(
        "No weather downloaded yet. Open the **Weather** page, pick an area and a "
        "year, and press Download - then come back here."
    )
    st.stop()

area_type, area_number, year, _points = request
areas = load_areas()

weekly = weekly_from_daily(daily)
reservoirs = nve.one_area(load_reservoirs(year, year), area_type, area_number)

if reservoirs.empty:
    st.warning(
        f"The weather is downloaded for {label}, but NVE has no reservoir rows for "
        f"that area in {year}. Pick a different area on the Weather page."
    )
    st.stop()

# --- Controls --------------------------------------------------------------

available = [key for key in weather.DAILY_RULES if key in weekly.columns]
reservoir_columns = [c for c in nve.VALUE_COLUMNS if c in reservoirs.columns]

first, second, third, fourth = st.columns(4)

weather_key = first.selectbox(
    "Weather property", options=available,
    index=available.index("precipitation") if "precipitation" in available else 0,
    format_func=weather.label,
)
reservoir_key = second.selectbox(
    "Reservoir variable", options=reservoir_columns,
    index=reservoir_columns.index("fill_level_change")
    if "fill_level_change" in reservoir_columns else 0,
    help=(
        "fill_level_change is usually the more honest choice: the level itself "
        "drifts with the season whatever the weather does, while the weekly "
        "change is what the weather actually moves."
    ),
)
window = third.slider("Window (weeks)", 4, 26, 8,
                      help="How many weeks each local correlation is computed over")
lag = fourth.slider("Lag (weeks)", -8, 12, 0,
                    help="Positive: today's weather against the reservoir this many weeks later")

weather_series = weekly[weather_key]
reservoir_series = reservoirs[reservoir_key]

try:
    result = quality.sliding_window_correlation(
        weather_series, reservoir_series, window=int(window), lag=int(lag)
    )
except ValueError as error:
    st.warning(str(error))
    st.stop()

st.caption(
    f"**{weather.label(weather_key)}** against **{reservoir_key}** for "
    f"{area_label(areas, area_type, area_number)}, {year}. "
    f"{result['summary']['n_windows']} windows of {window} weeks"
    + (f", lagged {lag} week{'s' if abs(lag) != 1 else ''}." if lag else ", no lag.")
)

# --- The three panels ------------------------------------------------------

correlation = result["correlation"]
summary = result["summary"]

figure = make_subplots(
    rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.05,
    subplot_titles=(
        weather.label(weather_key),
        reservoir_key,
        f"Sliding window correlation, {window}-week window",
    ),
)
figure.add_trace(
    go.Scatter(x=result["first"].index, y=result["first"], mode="lines",
               name=weather.label(weather_key), line=dict(color=theme.TEAL, width=1.3)),
    row=1, col=1,
)
figure.add_trace(
    go.Scatter(x=result["second"].index, y=result["second"], mode="lines",
               name=reservoir_key, line=dict(color=theme.DEEP, width=1.3)),
    row=2, col=1,
)
# The correlation panel is coloured by sign, because "positive or negative"
# is the first thing you want from it and a single-colour line makes you read
# the axis to find out.
figure.add_trace(
    go.Scatter(
        x=correlation.index, y=correlation, mode="lines",
        name="correlation", line=dict(color=theme.AMBER, width=1.6),
        fill="tozeroy", fillcolor="rgba(224,138,30,0.18)",
    ),
    row=3, col=1,
)
figure.add_hline(y=0, line=dict(color=theme.SLATE, width=1, dash="dot"), row=3, col=1)
figure.update_yaxes(title_text=weather.unit(weather_key), row=1, col=1)
figure.update_yaxes(title_text=reservoir_key, row=2, col=1)
figure.update_yaxes(title_text="r", range=[-1.05, 1.05], row=3, col=1)
figure.update_xaxes(title_text="Week ending", row=3, col=1)
figure.update_layout(height=700, showlegend=False, hovermode="x unified")
st.plotly_chart(figure, width="stretch")

a, b, c, d = st.columns(4)
a.metric("Overall correlation", f"{summary['overall']:+.2f}",
         help="One number for the whole year - the thing the sliding window exists to improve on")
b.metric("Strongest window", f"{summary['strongest']:+.2f}",
         help=f"Week ending {summary['strongest_at']:%d %b}" if "strongest_at" in summary else None)
c.metric("Weakest window", f"{summary['weakest']:+.2f}",
         help=f"Week ending {summary['weakest_at']:%d %b}" if "weakest_at" in summary else None)
d.metric("Share positive", f"{summary['share_positive']:.0%}")

if summary["strongest"] - summary["weakest"] > 1.0:
    st.info(
        f"The local correlation runs from {summary['weakest']:+.2f} to "
        f"{summary['strongest']:+.2f} over the year, while the single number for "
        f"the whole period is {summary['overall']:+.2f}. That spread is the point "
        "of the method: the relationship is not one number, and averaging it into "
        "one throws away most of what is there.",
        icon=":material/insights:",
    )

# --- Which lag is best ------------------------------------------------------

st.divider()
st.markdown("### How long is the delay?")
st.markdown(
    "The same correlation computed over the whole period at every lag. A peak "
    "away from zero is an estimate of how long the weather takes to show up in "
    "the reservoirs - a few weeks for rain, potentially months for snow."
)

scan = quality.best_lag(weather_series, reservoir_series, range(-8, 13))
peak = scan.loc[scan["correlation"].abs().idxmax()]

bars = go.Figure(
    go.Bar(
        x=scan["lag"], y=scan["correlation"],
        marker=dict(
            color=[theme.AMBER if lag_value == peak["lag"] else theme.SKY
                   for lag_value in scan["lag"]],
            line=dict(width=0),
        ),
        hovertemplate="Lag %{x} weeks<br>r = %{y:+.3f}<extra></extra>",
    )
)
bars.add_hline(y=0, line=dict(color=theme.SLATE, width=1))
theme.apply(bars, title="Correlation at each lag", x="Lag (weeks)",
            y="Correlation", height=340, legend=False)
st.plotly_chart(bars, width="stretch")

st.caption(
    f"Strongest at a lag of **{int(peak['lag'])} week"
    f"{'s' if abs(int(peak['lag'])) != 1 else ''}**, where r = {peak['correlation']:+.3f}. "
    "One year of weekly data is about fifty points, so treat a small difference "
    "between neighbouring lags as noise rather than a finding."
)

with st.expander("Why weekly, and what gets lost"):
    st.markdown(
        """
The reservoir statistics are weekly and the weather is hourly, so one of them
has to move. Aggregating the weather upwards is the safe direction -
interpolating fifty reservoir readings into three hundred and sixty-five would
invent data that NVE never published.

Precipitation and snowfall are **summed** over the week and temperature and
wind **averaged**, because a weekly average of daily rainfall totals is not a
quantity of water, it is a quantity of water divided by seven.

NVE dates each week with the Sunday that ends it - the newest row at the time
of writing is 2026-11-08, a Sunday - so the weather is resampled with `W-SUN`
and the two indexes line up without an offset.

What is lost: a cloudburst on a Tuesday and steady drizzle all week look the
same after summing. For a reservoir, which integrates whatever arrives, that is
mostly the right simplification.
"""
    )
