"""Forecasting reservoir filling with River's online SARIMAX.

The model is `river.time_series.SNARIMAX`, wrapped in `modules/forecast.py`.
River is an *online* library: the model sees one observation at a time and
updates as it goes, rather than being fitted once to a block of data. That suits
this project, where the underlying series grows by one row every Wednesday.

Everything the assignment asks to be selectable is a control here: the
non-seasonal orders, the seasonal orders, the period, the learning rate, how
much history to train on, how far ahead to forecast, and which exogenous series
to include. The defaults are not arbitrary - they are the configuration that won
a rolling-origin backtest over 24 origins, which is reproduced under "Test the
settings" below and written up in the notebook.

Two things worth knowing before turning the knobs:

* **Seasonality is where the accuracy is.** Dropping it (m = 1) more than
  doubles the error, from 0.055 to 0.137 mean absolute error. It costs almost
  nothing to keep: River builds features at lags m, 2m, ..., not m features, so
  a yearly period on weekly data is two extra columns and a fit in milliseconds.
* **The learning rate is a cliff, not a dial.** River's own default of 0.01 sits
  at the edge of stability for this series; with a long history and high orders
  the weights diverge and the forecast comes back as 1e145 with no error raised.
  The slider below stops short of it, and a diverged fit is reported rather than
  drawn.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from modules import forecast as fc
from modules import nve, theme, weather
from utils import (
    area_label,
    available_years,
    load_areas,
    load_reservoirs,
    weekly_from_daily,
)

st.title(":material/trending_up: Forecast")

areas = load_areas()
oldest, newest = available_years()

# --- Which area ------------------------------------------------------------
# Follows the map. The assignment asks for the training timeframe to be synced
# with the map's time frame, so both the area and the year range come from
# session state, with controls here to change them.

area_type = st.session_state.get("chosen_area_type", "NO")
area_number = st.session_state.get("chosen_area_number")

data = load_reservoirs(oldest, newest)
numbers = nve.area_numbers(data, area_type)
if area_number not in numbers:
    area_number = numbers[0] if numbers else None

if area_number is None:
    st.warning("No reservoir data for the area type chosen on the map.")
    st.stop()

chooser, info = st.columns([2, 3])
with chooser:
    area_number = st.selectbox(
        "Area", options=numbers,
        index=numbers.index(area_number),
        format_func=lambda n: area_label(areas, area_type, n),
        help="Set on the Map page; changing it here changes it everywhere.",
    )
    st.session_state["chosen_area_number"] = area_number
with info:
    st.caption(
        f"Area type **{nve.AREA_TYPES[area_type]}**, chosen on the Map page. "
        "The forecast, the map and the analysis pages all work on the same area."
    )

series = nve.one_area(data, area_type, area_number)["fill_level"].dropna()

# --- Model controls --------------------------------------------------------

with st.sidebar:
    st.markdown("### Model")
    horizon = st.slider("Horizon (weeks)", 4, 52, fc.DEFAULT_HORIZON,
                        help="How far ahead to predict. 13 weeks is about three months.")
    history = st.select_slider(
        "Training history (weeks)",
        options=[158, 208, 260, 312, 416, 520, 780, 1040, len(series)],
        value=312 if len(series) > 312 else len(series),
        help="How many of the most recent weeks the model trains on",
    )

    st.markdown("**Non-seasonal orders**")
    one, two, three = st.columns(3)
    p = one.number_input("p", 0, 20, fc.DEFAULT_ORDER["p"], help="Autoregressive terms")
    d = two.number_input("d", 0, 2, fc.DEFAULT_ORDER["d"], help="Differencing")
    q = three.number_input("q", 0, 10, fc.DEFAULT_ORDER["q"], help="Moving-average terms")

    st.markdown("**Seasonal orders**")
    four, five, six = st.columns(3)
    sp = four.number_input("sp", 0, 5, fc.DEFAULT_ORDER["sp"])
    sd = five.number_input("sd", 0, 2, fc.DEFAULT_ORDER["sd"])
    sq = six.number_input("sq", 0, 5, fc.DEFAULT_ORDER["sq"])
    m = st.select_slider(
        "Period m (weeks)", options=[1, 4, 13, 26, 52],
        value=fc.DEFAULT_ORDER["m"],
        help="52 is one year on weekly data. m = 1 turns seasonality off entirely.",
    )

    learning_rate = st.select_slider(
        "Learning rate", options=[0.001, 0.0025, 0.005, 0.0075],
        value=fc.DEFAULT_LEARNING_RATE,
        help="River's own default is 0.01, which diverges on this series. The slider stops below it.",
    )

    intervals = st.toggle(
        "Prediction interval", value=True,
        help="Fits two extra models with a quantile loss to get a band around the forecast",
    )

if m == 1:
    st.warning(
        "Seasonality is off (m = 1). In the backtest that more than doubled the "
        "error, from 0.055 to 0.137. Worth seeing once; not worth keeping.",
        icon=":material/warning:",
    )

# --- Exogenous variables ----------------------------------------------------

exogenous = None
weekly_weather = None
daily = st.session_state.get("weather_daily")
weather_request = st.session_state.get("weather_request")

with st.expander("Exogenous variables", expanded=False):
    if daily is None:
        st.caption(
            "None available. Download weather on the **Weather** page and the "
            "properties appear here as optional regressors."
        )
    else:
        weekly_weather = weekly_from_daily(daily)
        same_area = weather_request[:2] == (area_type, area_number) if weather_request else False
        if not same_area:
            st.caption(
                f"The downloaded weather is for **{st.session_state.get('weather_label', '?')}**, "
                "which is not the area selected above. Using it anyway would correlate "
                "one region's weather with another's reservoirs."
            )
        chosen = st.multiselect(
            "Weather series to include",
            options=[k for k in weekly_weather.columns],
            format_func=weather.label,
            default=[],
            disabled=not same_area,
            help="Aligned on the same weekly index as the reservoir series",
        )
        if chosen:
            exogenous = weekly_weather[chosen]
            st.caption(
                f"{len(exogenous)} weekly rows, overlapping the reservoir series on "
                f"{len(exogenous.index.intersection(series.index))} of them. Future values "
                "are carried forward from the last observation, since nobody knows next "
                "month's weather either."
            )
        st.caption(
            "In the backtest, adding weather made the forecast slightly *worse* "
            "(0.062 against 0.055) even though a backtest hands the model perfect "
            "foresight about its own regressors. Treat them as an experiment."
        )

# --- Run --------------------------------------------------------------------

needed = fc.required_weeks(p=int(p), d=int(d), q=int(q), m=int(m),
                           sp=int(sp), sd=int(sd), sq=int(sq))
if history < needed:
    st.error(
        f"These orders need at least {needed} observations before the model learns "
        f"anything, and the history is set to {history}. Raise the history or lower "
        "the orders.",
        icon=":material/error:",
    )
    st.stop()

options = dict(
    horizon=int(horizon), p=int(p), d=int(d), q=int(q), m=int(m),
    sp=int(sp), sd=int(sd), sq=int(sq),
    history_weeks=int(history), learning_rate=float(learning_rate),
    exogenous=exogenous,
)

try:
    with st.spinner("Fitting..."):
        if intervals:
            predicted = fc.forecast_with_intervals(series, **options)
        else:
            predicted = fc.forecast(series, **options)
except ValueError as error:
    st.error(str(error), icon=":material/error:")
    st.stop()

if predicted.attrs.get("diverged"):
    st.error(
        "The fit diverged - the weights grew without bound and the output is not a "
        "forecast. Lower the learning rate or the orders.",
        icon=":material/error:",
    )

# --- The animated plot ------------------------------------------------------

st.markdown("### Forecast")

# Show two years of history behind the forecast. All of it would compress the
# part that matters into the right-hand centimetre.
recent = series.tail(104)
has_band = "lower" in predicted.columns

# The animation walks the forecast forward one week per frame. A forecast is a
# sequence of increasingly uncertain guesses, and watching it extend makes that
# visible in a way a finished line does not - the band, in particular, opens up
# as the frames advance.
frames = []
for step in range(1, len(predicted) + 1):
    part = predicted.iloc[:step]
    traces = [
        go.Scatter(x=part.index, y=part["forecast"], mode="lines+markers",
                   line=dict(color=theme.AMBER, width=2.4),
                   marker=dict(size=5, color=theme.AMBER)),
    ]
    if has_band:
        traces.append(go.Scatter(
            x=list(part.index) + list(part.index[::-1]),
            y=list(part["upper"]) + list(part["lower"][::-1]),
            fill="toself", fillcolor="rgba(224,138,30,0.16)",
            line=dict(width=0), hoverinfo="skip",
        ))
    frames.append(go.Frame(data=traces, name=str(step),
                           traces=[1, 2] if has_band else [1]))

figure = go.Figure()
figure.add_trace(go.Scatter(
    x=recent.index, y=recent, mode="lines", name="observed",
    line=dict(color=theme.DEEP, width=1.6),
))
figure.add_trace(go.Scatter(
    x=predicted.index[:1], y=predicted["forecast"].iloc[:1], mode="lines+markers",
    name="forecast", line=dict(color=theme.AMBER, width=2.4),
    marker=dict(size=5, color=theme.AMBER),
))
if has_band:
    figure.add_trace(go.Scatter(
        x=list(predicted.index[:1]) + list(predicted.index[:1]),
        y=list(predicted["upper"].iloc[:1]) + list(predicted["lower"].iloc[:1]),
        fill="toself", fillcolor="rgba(224,138,30,0.16)",
        line=dict(width=0), name="10-90 % interval", hoverinfo="skip",
    ))
figure.frames = frames

figure.update_layout(
    updatemenus=[dict(
        type="buttons", direction="left", x=0.0, y=1.14, xanchor="left", yanchor="top",
        showactive=False,
        buttons=[
            dict(label="▶ Play", method="animate",
                 args=[None, dict(frame=dict(duration=220, redraw=True),
                                  fromcurrent=True, transition=dict(duration=0))]),
            dict(label="❚❚ Pause", method="animate",
                 args=[[None], dict(frame=dict(duration=0, redraw=False),
                                    mode="immediate")]),
        ],
    )],
    sliders=[dict(
        active=len(frames) - 1,
        x=0.16, y=1.14, len=0.84, xanchor="left", yanchor="top",
        currentvalue=dict(prefix="Week ahead: ", font=dict(size=12)),
        steps=[dict(method="animate", label=str(i + 1),
                    args=[[str(i + 1)], dict(mode="immediate",
                                             frame=dict(duration=0, redraw=True),
                                             transition=dict(duration=0))])
               for i in range(len(frames))],
    )],
)
theme.apply(
    figure,
    title=f"{area_label(areas, area_type, area_number)}: {horizon} weeks ahead",
    x="Week ending", y="Fill level", height=520,
)
theme.percent_axis(figure)
figure.update_layout(margin=dict(t=150))
# Land on the finished forecast rather than on frame 1, so the page is useful
# before anyone presses play.
figure.data[1].x, figure.data[1].y = predicted.index, predicted["forecast"]
if has_band:
    figure.data[2].x = list(predicted.index) + list(predicted.index[::-1])
    figure.data[2].y = list(predicted["upper"]) + list(predicted["lower"][::-1])

st.plotly_chart(figure, width="stretch")

a, b, c, d_ = st.columns(4)
a.metric("Last observed", f"{series.iloc[-1]:.1%}")
b.metric(f"In {horizon} weeks", f"{predicted['forecast'].iloc[-1]:.1%}",
         delta=f"{predicted['forecast'].iloc[-1] - series.iloc[-1]:+.1%}")
c.metric("Fit time", f"{predicted.attrs.get('fit_seconds', 0) * 1000:.0f} ms")
d_.metric("Values clipped", predicted.attrs.get("clipped", 0),
          help="Raw predictions pushed back inside 0-105 % of capacity. Routine, not an error.")

if has_band:
    st.caption(
        "The band is a 10-90 % quantile interval, fitted with "
        "`river.optim.losses.Quantile`. It is honest for the first four to six "
        "weeks and then stops being useful: measured against 24 backtest origins "
        "it covers 83 % of outcomes in week one and 100 % from week eight, where "
        "it spans almost the whole 0-100 % range. Each step feeds its own biased "
        "prediction back in as a lag, so the two edge models drift apart a little "
        "further every week."
    )

with st.expander("The numbers behind the forecast"):
    st.dataframe(
        predicted.assign(**{c: predicted[c].map("{:.1%}".format) for c in predicted.columns}),
        width="stretch",
    )

# --- Backtest ---------------------------------------------------------------

st.divider()
st.markdown("### Test the settings")
st.markdown(
    "A rolling-origin backtest: step back through the series, forecast from each "
    "origin, and compare against what actually happened. This is how the defaults "
    "above were chosen, and it is the only way to tell whether a change to the "
    "orders helped or just looked different."
)

origins = st.select_slider("Origins to test", options=[6, 12, 24], value=12,
                           help="More origins is a steadier estimate and a longer wait")

if st.button("Run the comparison", icon=":material/play_arrow:", type="primary"):
    configurations = [
        {"label": "current settings", "p": int(p), "d": int(d), "q": int(q), "m": int(m),
         "sp": int(sp), "sd": int(sd), "sq": int(sq), "history_weeks": int(history),
         "learning_rate": float(learning_rate)},
        {"label": "project defaults", **fc.DEFAULT_ORDER,
         "history_weeks": fc.DEFAULT_HISTORY_WEEKS},
        {"label": "no seasonality (m=1)", **{**fc.DEFAULT_ORDER, "m": 1},
         "history_weeks": fc.DEFAULT_HISTORY_WEEKS},
        {"label": "seasonal AR only", **{**fc.DEFAULT_ORDER, "sp": 1, "sd": 0, "sq": 0},
         "history_weeks": fc.DEFAULT_HISTORY_WEEKS},
        {"label": "all history", **fc.DEFAULT_ORDER, "history_weeks": None},
    ]
    with st.spinner(f"Fitting {len(configurations)} configurations at {origins} origins..."):
        table = fc.evaluate_settings(
            series, configurations, horizon=int(horizon), origins=int(origins)
        )
    st.session_state["forecast_backtest"] = table

if "forecast_backtest" in st.session_state:
    table = st.session_state["forecast_backtest"]
    st.dataframe(
        table[["label", "mae", "rmse", "mae_first_week", "mae_last_week",
               "fit_seconds", "clipped", "status"]],
        hide_index=True, width="stretch",
        column_config={
            "label": st.column_config.TextColumn("Configuration", width="medium"),
            "mae": st.column_config.NumberColumn("MAE", format="%.4f"),
            "rmse": st.column_config.NumberColumn("RMSE", format="%.4f"),
            "mae_first_week": st.column_config.NumberColumn("MAE week 1", format="%.4f"),
            "mae_last_week": st.column_config.NumberColumn("MAE last week", format="%.4f"),
            "fit_seconds": st.column_config.NumberColumn("Fit (s)", format="%.4f"),
        },
    )
    best = table.dropna(subset=["mae"])
    if not best.empty:
        bars = go.Figure(go.Bar(
            x=best["mae"], y=best["label"], orientation="h",
            marker=dict(color=[theme.AMBER if i == 0 else theme.SKY
                               for i in range(len(best))], line_width=0),
            hovertemplate="%{y}<br>MAE %{x:.4f}<extra></extra>",
        ))
        theme.apply(bars, title="Mean absolute error, lower is better",
                    x="MAE", y="", height=60 + 42 * len(best), legend=False)
        st.plotly_chart(bars, width="stretch")
        st.caption(
            f"Sorted best first. The error is in fill-level units, so an MAE of "
            f"{best['mae'].iloc[0]:.4f} means the forecast is on average "
            f"{best['mae'].iloc[0]:.1%} of capacity away from what happened."
        )
