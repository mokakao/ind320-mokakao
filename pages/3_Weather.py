"""Page 4: weather for the selected area, downloaded from Open-Meteo.

This page is both the download control and the first look at the result. The
task asks whether downloading should have a page of its own or be hidden away;
I kept it visible, because the download is the slow part of the whole app and
hiding a thirty-second wait behind another page only makes it confusing. Here
you can see what is being fetched, how many grid cells it turned into, and
press the button when you mean it.

Which area is fetched follows the selector in the sidebar, the same one the
reservoir pages use, so the weather and the reservoir levels always refer to
the same place.
"""

import matplotlib.pyplot as plt
import streamlit as st

from modules import nve, regions
from utils import area_label, daily_weather, load_areas, load_weather, reservoir_controls

st.set_page_config(page_title="Weather - IND320", page_icon="🌦️", layout="wide")

st.title("🌦️ Weather")

area_type, first_year, last_year, area_number = reservoir_controls(with_area=True)
areas = load_areas()
name = area_label(areas, area_type, area_number)

st.markdown(
    f"Hourly ERA5 reanalysis for **{name}**, averaged over the area. "
    "The area follows the selector in the sidebar, so it always matches the "
    "reservoir data on the other pages."
)

left, right = st.columns([2, 3], gap="large")

with left:
    st.markdown("### Download")

    year = st.selectbox(
        "Year",
        options=list(range(last_year, first_year - 1, -1)),
        help="One year at a time; ERA5 is hourly, so a year is already 8760 values per cell",
    )
    n_points = st.select_slider(
        "Random points in the area",
        options=[50, 100, 200, 500, 1000],
        value=100,
        help="More points cover the area better but take longer to download",
    )

    # Show the cost before anyone pays it. The points are cheap to generate;
    # it is the API call that takes time.
    if area_type == "EL":
        shapes = regions.load_price_areas()
        shapes = shapes[shapes["area"] == f"NO{area_number}"]
    else:
        shapes = regions.load_nve_regions(merge_to_vass=True)
        if area_type == "VASS":
            shapes = shapes[shapes["area"] == f"VASS{area_number}"]

    cells = regions.to_era5_grid(regions.sample_points(shapes, n=n_points))
    batches = -(-len(cells) // 60)

    st.caption(
        f"{n_points} random points fall into **{len(cells)} ERA5 grid cells** "
        f"({1 - len(cells)/n_points:.0%} fewer requests). "
        f"That is {batches} batch{'es' if batches != 1 else ''}, "
        f"roughly {batches * 25} seconds."
    )

    fetch = st.button("Download weather", type="primary")

with right:
    st.markdown("### The area")
    fig, ax = plt.subplots(figsize=(4.5, 5.5))
    shapes.plot(ax=ax, color="#dce7f2", edgecolor="#4a6fa5")
    ax.scatter(cells["lon"], cells["lat"], s=cells["weight"] * 3,
               color="#e67e22", alpha=0.7, edgecolor="white", linewidth=0.3)
    ax.set_title(f"{name}: {len(cells)} grid cells", fontsize=10)
    ax.set_axis_off()
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)
    st.caption("Dot size is how many of the sampled points fell in that cell, which is the weight used when averaging.")

# --- The result ------------------------------------------------------------
if fetch:
    st.session_state["weather_request"] = (area_type, area_number, year, n_points)

request = st.session_state.get("weather_request")

if not request:
    st.info("Press **Download weather** to fetch the data for this area.")
    st.stop()

with st.spinner(f"Downloading {request[2]} from Open-Meteo..."):
    hourly = load_weather(*request)

daily = daily_weather(hourly)
st.session_state["weather_daily"] = daily
st.session_state["weather_label"] = f"{area_label(areas, request[0], request[1])} {request[2]}"

st.success(
    f"{len(hourly):,} hours for {st.session_state['weather_label']}. "
    "The other analysis pages read this.".replace(",", " ")
)

top, bottom = st.columns(2)
top.metric("Mean temperature", f"{daily['temperature'].mean():.1f} °C")
bottom.metric("Total precipitation", f"{daily['precipitation'].sum():.0f} mm")

fig, (upper, lower) = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
upper.plot(daily.index, daily["temperature"], linewidth=1, color="#c0392b")
upper.set_ylabel("°C")
upper.set_title(f"Daily mean temperature, {st.session_state['weather_label']}")
upper.grid(alpha=0.3)

lower.bar(daily.index, daily["precipitation"], width=1.0, color="#2b7bba")
lower.set_ylabel("mm/day")
lower.set_xlabel("Date")
lower.set_title("Daily precipitation")
lower.grid(alpha=0.3)

fig.tight_layout()
st.pyplot(fig)
plt.close(fig)

with st.expander("Where these numbers come from"):
    st.markdown(
        """
**Source:** [Open-Meteo](https://open-meteo.com/en/docs), hourly ERA5
reanalysis. ERA5 is a weather model run over the past and corrected against
what was actually observed, which is how there can be a temperature for a
coordinate where nobody ever stood with a thermometer.

**The route:** the area polygon comes from a shapefile exported from
[NVE Atlas](https://atlas.nve.no). Random points are scattered inside it in
the metric projection, so the spacing stays even instead of crowding towards
the north. ERA5 has a grid of about 25 km, so the points are snapped to that
grid and the duplicates dropped - each cell is then weighted by how many
points fell in it, which gives the same average from far fewer requests.

**Limits worth knowing:** the coordinates travel in the URL, and a few hundred
of them make it long enough that the server answers `414 Request-URI Too
Large`. There is also a per-minute quota counting volume rather than calls. So
the download goes in batches of 60 with a pause between them.
"""
    )
