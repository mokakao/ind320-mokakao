"""Page 3: plots of the reservoir data, one line per area.

The radio button in the sidebar picks the area type, and every area number of
that type gets its own line. Picking "Norway as a whole" therefore gives a
single line, while the price areas give five.
"""

import matplotlib.pyplot as plt
import streamlit as st

from modules import nve
from utils import area_label, load_areas, load_reservoirs, reservoir_controls

st.set_page_config(page_title="Reservoir plots - IND320", page_icon="📈", layout="wide")

st.title("📈 Reservoir plots")

area_type, first_year, last_year = reservoir_controls()

data = load_reservoirs(first_year, last_year)
areas = load_areas()

column = st.selectbox(
    "Series to plot",
    options=["All series (scaled)"] + nve.VALUE_COLUMNS,
    help="One series for every area, or all series at once for a single area",
)

st.markdown(f"#### {nve.AREA_TYPES[area_type]}, {first_year}-{last_year}")

fig, ax = plt.subplots(figsize=(11, 4.5))

if column == "All series (scaled)":
    # All five series on one axis only works if they are scaled first: capacity
    # is around 87 TWh, fill level is between 0 and 1, and the weekly change is
    # almost zero. Raw, you would see two lines and three flat ones along the
    # bottom. Scaling loses the units but keeps the shapes comparable.
    number = nve.area_numbers(data, area_type)[0]
    one = nve.one_area(data, area_type, number)

    for name in one.columns:
        low, high = one[name].min(), one[name].max()
        # A series that never changes would divide by zero, so it is drawn flat
        # in the middle instead.
        scaled = (one[name] - low) / (high - low) if high > low else one[name] * 0 + 0.5
        ax.plot(one.index, scaled, label=name, linewidth=1.5)

    ax.set_ylabel("Scaled value (0-1)")
    ax.set_title(f"All series for {area_label(areas, area_type, number)}, scaled")
    st.info(
        "The series use different units, so they are scaled to 0-1 over the "
        "period. Only the first area of the type is shown here - pick a single "
        "series to compare the areas against each other."
    )
else:
    table = nve.wide(data, area_type, column)
    for number in table.columns:
        ax.plot(table.index, table[number], label=area_label(areas, area_type, number), linewidth=1.5)

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

st.caption(
    f"{len(data[data['area_type'] == area_type]):,} weekly measurements in the "
    "downloaded interval. Source: NVE Magasinstatistikk API."
    .replace(",", " ")
)
