"""Page 6: finding the points that do not belong.

Two tabs, two different questions:

  Outliers / SPC   is this point far from where the season says it should be?
  Anomalies / LOF  is this point in a sparser neighbourhood than its neighbours?

Both run on the weather downloaded on the Weather page, so that has to be
fetched first.
"""

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st

from modules import quality

st.set_page_config(page_title="Outliers - IND320", page_icon="📍", layout="wide")

st.title("📍 Outliers and anomalies")

daily = st.session_state.get("weather_daily")
label = st.session_state.get("weather_label", "")

if daily is None:
    st.info(
        "No weather downloaded yet. Open the **Weather** page, pick an area and a "
        "year, and press Download — then come back here."
    )
    st.stop()

st.caption(f"Running on **{label}**, {len(daily)} days.")

spc_tab, lof_tab = st.tabs(["Outliers (SPC)", "Anomalies (LOF)"])

# --- Statistical process control -------------------------------------------
with spc_tab:
    st.markdown(
        "A year of weather is dominated by the seasons, so a fixed limit is useless: "
        "20 mm of rain in October is ordinary and the same in February is not. The "
        "seasonal shape is filtered out with a discrete cosine transform, robust "
        "limits are placed around what is left, and then the limits are transformed "
        "back so they bend along with the season. What you see below is the real "
        "measurements — the filtered series is only the route to the limits."
    )

    first, second = st.columns(2)
    cutoff = first.slider("DCT cut-off", 1, 40, 8,
                          help="How many coefficients count as 'seasonal'. Lower keeps less of the shape")
    sigmas = second.slider("Standard deviations", 1.0, 5.0, 3.0, step=0.5,
                           help="How far from the season a point has to be before it counts")

    result = quality.spc_outliers(daily["precipitation"], cutoff=int(cutoff), sigmas=float(sigmas))
    outliers = result["outliers"]

    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(daily.index, daily["precipitation"], linewidth=0.9, color="#4a6fa5",
            label="daily precipitation")
    ax.plot(result["upper"].index, result["upper"], color="#c0392b", linewidth=1.2,
            linestyle="--", label=f"±{sigmas:g}σ around the season")
    ax.plot(result["lower"].index, result["lower"], color="#c0392b", linewidth=1.2, linestyle="--")
    ax.scatter(daily.index[outliers], daily["precipitation"][outliers], s=38,
               color="#e67e22", zorder=5, edgecolor="white", linewidth=0.6,
               label=f"outliers ({int(outliers.sum())})")
    ax.set_ylabel("mm/day")
    ax.set_xlabel("Date")
    ax.set_title(f"Precipitation with seasonally adjusted control limits, {label}")
    ax.legend(fontsize="small", loc="upper left")
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

    summary = result["summary"]
    a, b, c, d = st.columns(4)
    a.metric("Outliers", summary["n_outliers"])
    b.metric("Share of days", f"{summary['share']:.1%}")
    c.metric("Limit width", f"{summary['limit_width']:.1f} mm")
    d.metric("Largest deviation", f"{summary['largest']:.1f} mm")

    with st.expander("The days that were flagged"):
        flagged = daily.loc[outliers, ["precipitation", "temperature"]].copy()
        flagged["above the upper limit"] = (
            daily["precipitation"][outliers] > result["upper"][outliers]
        )
        st.dataframe(flagged.sort_values("precipitation", ascending=False), width="stretch")

# --- Local Outlier Factor ---------------------------------------------------
with lof_tab:
    st.markdown(
        "LOF asks a different question: not whether a point is extreme, but whether "
        "it sits in a sparser neighbourhood than its own neighbours do. Each day is "
        "described by two numbers, the temperature and the change from the day "
        "before. With the value alone LOF would just pick out the hottest and coldest "
        "days, which the control limits already do; adding the change makes it flag "
        "abrupt swings too."
    )

    first, second = st.columns(2)
    proportion = first.slider("Proportion of anomalies", 0.5, 10.0, 1.0, step=0.5,
                              format="%.1f%%",
                              help="How many of the days should be flagged") / 100
    neighbours = second.slider("Neighbours", 5, 60, 20,
                               help="How large a neighbourhood each day is compared against")

    result = quality.lof_anomalies(daily["temperature"], proportion=proportion,
                                   neighbours=int(neighbours))
    anomalies = result["anomalies"]

    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.plot(daily.index, daily["temperature"], linewidth=1.0, color="#4a6fa5",
            label="daily mean temperature")
    ax.scatter(daily.index[anomalies], daily["temperature"][anomalies], s=46,
               color="#8e44ad", zorder=5, edgecolor="white", linewidth=0.6,
               label=f"anomalies ({int(anomalies.sum())})")
    ax.set_ylabel("°C")
    ax.set_xlabel("Date")
    ax.set_title(f"Temperature with Local Outlier Factor anomalies, {label}")
    ax.legend(fontsize="small", loc="upper left")
    ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

    summary = result["summary"]
    a, b, c = st.columns(3)
    a.metric("Anomalies", summary["n_anomalies"])
    b.metric("Score threshold", f"{summary['threshold']:.2f}")
    c.metric("Highest score", f"{summary['max_score']:.2f}")

    with st.expander("The days that were flagged"):
        flagged = daily.loc[anomalies, ["temperature", "precipitation"]].copy()
        flagged["LOF score"] = result["scores"][anomalies].round(2)
        flagged["change from day before"] = (
            daily["temperature"].diff()[anomalies].round(2)
        )
        st.dataframe(flagged.sort_values("LOF score", ascending=False), width="stretch")

with st.expander("Where these numbers come from"):
    st.markdown(
        """
Both tabs run on the daily weather downloaded on the **Weather** page: hourly
ERA5 from [Open-Meteo](https://open-meteo.com/en/docs), averaged over the
selected area and then resampled to daily precipitation totals and daily mean
temperature.

The control limits use the median absolute deviation rather than the standard
deviation. A handful of extreme values would otherwise widen the limits enough
to hide themselves, which is the opposite of what the limits are for.
"""
    )
