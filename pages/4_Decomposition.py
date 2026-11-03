"""Page 5: pulling the reservoir series apart.

Two ways of asking what rhythms are in the data, as two tabs:

  STL          splits it into a seasonal shape, a trend and a remainder
  Spectrogram  shows which rhythms are present and when
"""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from modules import nve, quality
from utils import area_label, load_areas, load_reservoirs, reservoir_controls

st.set_page_config(page_title="Decomposition - IND320", page_icon="🔍", layout="wide")

st.title("🔍 Decomposition")

area_type, first_year, last_year, area_number = reservoir_controls(with_area=True)

data = load_reservoirs(first_year, last_year)
areas = load_areas()
name = area_label(areas, area_type, area_number)
series = nve.one_area(data, area_type, area_number)["fill_level"]

if len(series) < 120:
    st.warning(
        f"Only {len(series)} weekly measurements in this interval. Both methods "
        "need a few years to say anything - widen the download interval in the sidebar."
    )
    st.stop()

st.caption(f"{len(series)} weekly measurements for **{name}**, {first_year}-{last_year}.")

stl_tab, spectrogram_tab = st.tabs(["STL", "Spectrogram"])

# --- STL -------------------------------------------------------------------
with stl_tab:
    st.markdown(
        "STL separates a repeating seasonal shape from a slow trend and whatever "
        "is left. Unlike a fixed filter it lets the seasonal shape drift from year "
        "to year, which suits reservoirs: the rhythm is the same every year, but "
        "wet and dry years shift it around."
    )

    first, second, third = st.columns(3)
    period = first.number_input("Period (weeks)", 4, 104, 52, step=1,
                                help="Length of one cycle; 52 for weekly data")
    seasonal = second.select_slider("Seasonal smoother", options=[7, 9, 11, 13, 15, 21, 25], value=7,
                                    help="Longer means the seasonal shape changes more slowly")
    robust = third.toggle("Robust", value=True,
                          help="Downweights odd weeks so one of them cannot drag the trend")

    result = quality.stl_decomposition(series, period=int(period), seasonal=int(seasonal), robust=robust)

    fig, axes = plt.subplots(4, 1, figsize=(12, 9), sharex=True)
    for axis, (values, label) in zip(axes, [
        (series, "Fill level"), (result.trend, "Trend"),
        (result.seasonal, "Seasonal"), (result.resid, "Remainder"),
    ]):
        axis.plot(series.index, values, linewidth=1.0, color="#4a6fa5")
        axis.set_ylabel(label, fontsize=9)
        axis.grid(alpha=0.3)
    axes[3].axhline(0, color="#c0392b", linewidth=0.8)
    axes[0].set_title(f"STL decomposition of {name}")
    axes[3].set_xlabel("Date")
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

    strength = 1 - result.resid.var() / (result.seasonal + result.resid).var()
    left, middle, right = st.columns(3)
    left.metric("Seasonal strength", f"{strength:.3f}",
                help="1 means the seasonal shape explains everything that is not trend")
    middle.metric("Remainder sd", f"{result.resid.std():.4f}")
    right.metric("Trend range", f"{result.trend.max() - result.trend.min():.3f}")

# --- Spectrogram -----------------------------------------------------------
with spectrogram_tab:
    st.markdown(
        "A single transform over the whole series says which rhythms exist but not "
        "when. A spectrogram cuts the series into overlapping windows and transforms "
        "each one, so a rhythm that comes and goes shows up as a patch instead of "
        "being smeared over the whole picture."
    )

    first, second = st.columns(2)
    window = first.select_slider("Window (weeks)", options=[52, 78, 104, 156, 208], value=104,
                                 help="Longer resolves frequency better and time worse")
    overlap = second.slider("Overlap (weeks)", 0, int(window) - 1, int(window) // 2,
                            help="How much neighbouring windows share")

    result = quality.spectrogram(series, window=int(window), overlap=int(overlap))

    # Periods read better than frequencies, and the zero frequency is the mean
    # rather than a rhythm, so it is dropped.
    frequencies = result["frequencies"][1:]
    power = result["power"][1:]
    times = [series.index[0] + pd.Timedelta(weeks=t) for t in result["times"]]

    fig, ax = plt.subplots(figsize=(12, 5))
    mesh = ax.pcolormesh(times, 1 / frequencies, 10 * np.log10(power + 1e-12),
                         shading="auto", cmap="magma")
    ax.set_yscale("log")
    ax.set_ylabel("Period (weeks)")
    ax.set_xlabel("Date")
    ax.set_title(f"{name}: spectrogram")
    ax.axhline(52, color="white", linestyle="--", linewidth=1)
    ax.text(times[0], 55, "one year", color="white", fontsize=9)
    fig.colorbar(mesh, ax=ax, label="Power (dB)")
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

    st.caption(
        f"{len(frequencies)} frequencies × {len(result['times'])} time windows. "
        "The bright band at the one-year line staying bright across the picture "
        "means the yearly cycle is there the whole time, not only in some years."
    )

with st.expander("Where these numbers come from"):
    st.markdown(
        "Reservoir filling from the [NVE Magasinstatistikk API](https://biapi.nve.no/"
        "magasinstatistikk/swagger/index.html), downloaded directly for the interval "
        "chosen in the sidebar. STL is `statsmodels.tsa.seasonal.STL` and the "
        "spectrogram is `scipy.signal.spectrogram`."
    )
