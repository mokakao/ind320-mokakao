"""Page 3 of the app: a plot with a column selector and a month selector.

Required elements:
  * a plot with a header, axis titles and other relevant formatting,
  * st.selectbox to choose a single column or all columns together,
  * st.select_slider to choose a subset of the months, starting at the first.
"""

import matplotlib.pyplot as plt
import streamlit as st

from utils import filter_months, load_data, month_labels

st.set_page_config(page_title="Plots - IND320", page_icon="📈", layout="wide")

st.title("📈 Plots")

data = load_data()
months = month_labels(data)

# --- User input ------------------------------------------------------------
# Both widgets are placed in the sidebar so the plot gets the full width.
with st.sidebar:
    st.markdown("### Plot settings")

    # "All columns together" is put first so it is not hidden at the bottom.
    column_choice = st.selectbox(
        "Column to plot",
        options=["All columns"] + list(data.columns),
        help="Choose one series, or all of them together",
    )

    # A select_slider over month labels. Passing a tuple as `value` makes it a
    # range slider; the default is the first month at both ends, as required.
    first_month, last_month = st.select_slider(
        "Months to show",
        options=months,
        value=(months[0], months[0]),
        help="Drag the two handles to widen the period",
    )

# --- Data for the chosen period -------------------------------------------
selection = filter_months(data, first_month, last_month)

if selection.empty:
    st.warning("No data in the selected period.")
    st.stop()

period_text = (
    first_month if first_month == last_month else f"{first_month} to {last_month}"
)
st.markdown(f"#### Norwegian reservoirs, {period_text}")

# --- Plot ------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(11, 4.5))

if column_choice == "All columns":
    # The series are on very different scales: a share between 0 and 1, tens of
    # TWh, and a weekly change close to zero. Drawing them raw on one axis would
    # flatten everything except the TWh columns, so each series is scaled to
    # 0-1 over the selected period. The shapes stay comparable; the units do not.
    scaled = selection.copy()
    for column in scaled.columns:
        low, high = scaled[column].min(), scaled[column].max()
        # A constant series (for example capacity within one month) would give
        # a division by zero, so it is drawn as a flat line at 0.5 instead.
        scaled[column] = (
            (scaled[column] - low) / (high - low) if high > low else 0.5
        )
    for column in scaled.columns:
        ax.plot(scaled.index, scaled[column], label=column, linewidth=1.6)
    ax.set_ylabel("Scaled value (0-1 within the period)")
    ax.set_title("All series, scaled to a common range")
    ax.legend(loc="upper left", fontsize="small", ncol=2)
    st.info(
        "The series have different units, so they are scaled to 0-1 within the "
        "selected period. Pick a single column to see the real values."
    )
else:
    ax.plot(
        selection.index,
        selection[column_choice],
        color="#1f77b4",
        linewidth=1.8,
    )
    # Units differ between the series, so the y-axis label follows the choice.
    unit = "TWh" if column_choice.endswith("TWh") else "Share of capacity"
    ax.set_ylabel(f"{column_choice} ({unit})")
    ax.set_title(f"{column_choice} over time")

ax.set_xlabel("Date")
ax.grid(alpha=0.3)
fig.autofmt_xdate()          # slanted date labels so they do not overlap
fig.tight_layout()

st.pyplot(fig)

st.caption(
    f"{len(selection)} weekly measurements shown. "
    "Source: NVE reservoir statistics."
)
