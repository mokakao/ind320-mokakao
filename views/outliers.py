"""Finding the points that do not belong.

Two tabs, two different questions:

  Outliers / SPC   is this point far from where the season says it should be?
  Anomalies / LOF  is this point in a sparser neighbourhood than its neighbours?

Both run on the weather downloaded on the Weather page, so that has to be
fetched first.

Part 4 added a weather property selector to both. In part 3 the SPC tab was
hard-wired to precipitation and the LOF tab to temperature, which hid something
worth seeing: the two methods behave very differently depending on what you
feed them. Precipitation is skewed and bounded below by zero, so its control
limits flag only upward excursions; temperature is roughly symmetric, so it
flags both. Being able to switch the property makes that an observation rather
than an accident of which tab you are on.
"""

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from modules import quality, theme, weather

st.title(":material/scatter_plot: Outliers and anomalies")

daily = st.session_state.get("weather_daily")
label = st.session_state.get("weather_label", "")

if daily is None:
    st.info(
        "No weather downloaded yet. Open the **Weather** page, pick an area and a "
        "year, and press Download - then come back here."
    )
    st.stop()

available = [key for key in weather.DAILY_RULES if key in daily.columns]
default_index = available.index(weather.DEFAULT_PROPERTY) if weather.DEFAULT_PROPERTY in available else 0

st.caption(f"Running on **{label}**, {len(daily)} days.")

spc_tab, lof_tab = st.tabs(["Outliers (SPC)", "Anomalies (LOF)"])


def flagged_table(mask, chosen: str, extra: dict | None = None):
    """The flagged days, with the chosen property first and the rest after."""
    others = [c for c in daily.columns if c != chosen]
    table = daily.loc[mask, [chosen] + others].copy()
    for name, values in (extra or {}).items():
        table[name] = values
    return table


# --- Statistical process control -------------------------------------------
with spc_tab:
    st.markdown(
        "A year of weather is dominated by the seasons, so a fixed limit is useless: "
        "20 mm of rain in October is ordinary and the same in February is not. The "
        "seasonal shape is filtered out with a discrete cosine transform, robust "
        "limits are placed around what is left, and then the limits are transformed "
        "back so they bend along with the season. What you see below is the real "
        "measurements - the filtered series is only the route to the limits."
    )

    first, second, third = st.columns(3)
    spc_property = first.selectbox(
        "Weather property", options=available, index=default_index,
        format_func=weather.label, key="spc_property",
        help="Which measurement the control limits are placed around",
    )
    cutoff = second.slider("DCT cut-off", 1, 40, 8,
                           help="How many coefficients count as 'seasonal'. Lower keeps less of the shape")
    sigmas = third.slider("Standard deviations", 1.0, 5.0, 3.0, step=0.5,
                          help="How far from the season a point has to be before it counts")

    series = daily[spc_property]
    unit = weather.unit(spc_property)
    result = quality.spc_outliers(series, cutoff=int(cutoff), sigmas=float(sigmas))
    outliers = result["outliers"]

    figure = go.Figure()
    figure.add_trace(go.Scatter(
        x=result["upper"].index, y=result["upper"], mode="lines", name=f"+{sigmas:g}σ",
        line=dict(color=theme.RUST, width=1.1, dash="dash"),
    ))
    figure.add_trace(go.Scatter(
        x=result["lower"].index, y=result["lower"], mode="lines", name=f"-{sigmas:g}σ",
        line=dict(color=theme.RUST, width=1.1, dash="dash"),
        # Fill between the limits, so "inside the limits" is a region you can
        # see rather than two lines you have to mentally join up.
        fill="tonexty", fillcolor="rgba(180,71,31,0.06)",
    ))
    figure.add_trace(go.Scatter(
        x=series.index, y=series, mode="lines", name=weather.label(spc_property),
        line=dict(color=theme.DEEP, width=1.0),
    ))
    figure.add_trace(go.Scatter(
        x=series.index[outliers], y=series[outliers], mode="markers",
        name=f"outliers ({int(outliers.sum())})",
        marker=dict(color=theme.AMBER, size=8, line=dict(color="white", width=1)),
    ))
    theme.apply(
        figure,
        title=f"{weather.label(spc_property)} with seasonally adjusted control limits, {label}",
        x="Date", y=f"{weather.label(spc_property)} ({unit})", height=460,
    )
    st.plotly_chart(figure, width="stretch")

    summary = result["summary"]
    a, b, c, d = st.columns(4)
    a.metric("Outliers", summary["n_outliers"])
    b.metric("Share of days", f"{summary['share']:.1%}")
    c.metric("Limit width", f"{summary['limit_width']:.1f} {unit}")
    d.metric("Largest deviation", f"{summary['largest']:.1f} {unit}")

    above = int((series[outliers] > result["upper"][outliers]).sum())
    below = int(outliers.sum()) - above
    if outliers.sum() and (above == 0 or below == 0):
        st.caption(
            f"Every flagged day is on the same side of the limits "
            f"({'above' if below == 0 else 'below'}). That is what a skewed, "
            "one-sided variable looks like: precipitation cannot go below zero, "
            "so the only way to be unusual is to be large. Switch to temperature "
            "to see a property that is unusual in both directions."
        )

    with st.expander("The days that were flagged"):
        st.dataframe(
            flagged_table(
                outliers, spc_property,
                {"above the upper limit": series[outliers] > result["upper"][outliers]},
            ).sort_values(spc_property, ascending=False),
            width="stretch",
        )

# --- Local Outlier Factor ---------------------------------------------------
with lof_tab:
    st.markdown(
        "LOF asks a different question: not whether a point is extreme, but whether "
        "it sits in a sparser neighbourhood than its own neighbours do. Each day is "
        "described by two numbers, the value and the change from the day before. "
        "With the value alone LOF would just pick out the largest and smallest days, "
        "which the control limits already do; adding the change makes it flag abrupt "
        "swings too."
    )

    first, second, third = st.columns(3)
    lof_property = first.selectbox(
        "Weather property", options=available, index=default_index,
        format_func=weather.label, key="lof_property",
        help="Which measurement the neighbourhoods are built from",
    )
    proportion = second.slider("Proportion of anomalies", 0.5, 10.0, 1.0, step=0.5,
                               format="%.1f%%",
                               help="How many of the days should be flagged") / 100
    neighbours = third.slider("Neighbours", 5, 60, 20,
                              help="How large a neighbourhood each day is compared against")

    series = daily[lof_property]
    unit = weather.unit(lof_property)
    result = quality.lof_anomalies(series, proportion=proportion, neighbours=int(neighbours))
    anomalies = result["anomalies"]

    figure = go.Figure()
    figure.add_trace(go.Scatter(
        x=series.index, y=series, mode="lines", name=weather.label(lof_property),
        line=dict(color=theme.DEEP, width=1.1),
    ))
    figure.add_trace(go.Scatter(
        x=series.index[anomalies], y=series[anomalies], mode="markers",
        name=f"anomalies ({int(anomalies.sum())})",
        marker=dict(color=theme.AMBER, size=9, line=dict(color="white", width=1)),
        customdata=np.round(result["scores"][anomalies], 2),
        hovertemplate="%{x|%d %b %Y}<br>%{y:.2f} " + unit + "<br>LOF score %{customdata}<extra></extra>",
    ))
    theme.apply(
        figure,
        title=f"{weather.label(lof_property)} with Local Outlier Factor anomalies, {label}",
        x="Date", y=f"{weather.label(lof_property)} ({unit})", height=460,
    )
    st.plotly_chart(figure, width="stretch")

    summary = result["summary"]
    a, b, c = st.columns(3)
    a.metric("Anomalies", summary["n_anomalies"])
    b.metric("Score threshold", f"{summary['threshold']:.2f}")
    c.metric("Highest score", f"{summary['max_score']:.2f}")

    st.caption(
        "LOF always flags the share you ask for, whatever the data looks like - "
        "it ranks the days and cuts at the proportion. SPC can return nothing at "
        "all if nothing crosses the limits. That is the real difference between "
        "the two tabs, and it is worth knowing before trusting either count."
    )

    with st.expander("The days that were flagged"):
        st.dataframe(
            flagged_table(
                anomalies, lof_property,
                {
                    "LOF score": result["scores"][anomalies].round(2),
                    "change from day before": series.diff()[anomalies].round(2),
                },
            ).sort_values("LOF score", ascending=False),
            width="stretch",
        )

with st.expander("Where these numbers come from"):
    st.markdown(
        """
Both tabs run on the daily weather downloaded on the **Weather** page: hourly
ERA5 from [Open-Meteo](https://open-meteo.com/en/docs), averaged over the
selected area and then resampled to daily values - summed for precipitation and
snowfall, averaged for temperature and wind.

The control limits use the median absolute deviation rather than the standard
deviation. A handful of extreme values would otherwise widen the limits enough
to hide themselves, which is the opposite of what the limits are for.
"""
    )
