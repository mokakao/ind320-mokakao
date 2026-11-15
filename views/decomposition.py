"""Page 5: pulling the reservoir series apart.

Two ways of asking what rhythms are in the data, as two tabs:

  STL          splits it into a seasonal shape, a trend and a remainder
  Spectrogram  shows which rhythms are present and when
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from modules import nve, quality, theme
from utils import area_label, load_areas, load_reservoirs, reservoir_controls

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

    panels = [
        (series, "Fill level", theme.DEEP),
        (result.trend, "Trend", theme.WATER),
        (result.seasonal, "Seasonal", theme.TEAL),
        (result.resid, "Remainder", theme.SLATE),
    ]
    figure = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.035)
    for row, (values, label, colour) in enumerate(panels, start=1):
        figure.add_trace(
            go.Scatter(x=series.index, y=values, name=label, mode="lines",
                       line=dict(width=1.2, color=colour)),
            row=row, col=1,
        )
        figure.update_yaxes(title_text=label, title_font_size=11, row=row, col=1)
    # Zero line on the remainder: the eye needs somewhere to judge "too far off"
    # from, and a remainder panel without it is just a wiggle.
    figure.add_hline(y=0, line=dict(color=theme.RUST, width=0.9), row=4, col=1)
    figure.update_xaxes(title_text="Date", row=4, col=1)
    figure.update_layout(
        height=720, showlegend=False, title=f"STL decomposition of {name}",
        hovermode="x unified",
    )
    st.plotly_chart(figure, width="stretch")

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

    periods = 1 / frequencies
    decibels = 10 * np.log10(power + 1e-12)

    figure = go.Figure(
        go.Heatmap(
            x=times,
            y=periods,
            z=decibels,
            colorscale="Magma",
            colorbar=dict(title="Power (dB)", thickness=14),
            hovertemplate="%{x|%b %Y}<br>Period: %{y:.0f} weeks<br>%{z:.1f} dB<extra></extra>",
        )
    )
    # A log scale on the period axis: the interesting rhythms span one year
    # down to a couple of months, and on a linear axis everything short is
    # squashed into the bottom centimetre.
    # Shapes on a log axis are positioned in log space, not data space. Passing
    # y=52 puts the line at 10**52 and drags the autorange up to 10**54, which
    # squashes the whole spectrogram into a sliver at the bottom. The range is
    # pinned as well, so the plot cannot be rescaled by one stray value.
    figure.update_yaxes(
        type="log", title_text="Period (weeks)",
        range=[np.log10(periods.min()), np.log10(periods.max())],
    )
    figure.add_hline(
        y=np.log10(52), line=dict(color="white", width=1, dash="dash"),
        annotation_text="one year", annotation_position="top left",
        annotation_font_color="white",
    )
    figure.update_layout(
        height=480, title=f"{name}: spectrogram", xaxis_title="Date", hovermode="closest",
    )
    st.plotly_chart(figure, width="stretch")

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
