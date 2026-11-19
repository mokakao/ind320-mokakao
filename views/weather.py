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

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from modules import regions, theme, weather as weather_module
from utils import (area_label, area_polygon, daily_weather, load_areas,
                   load_weather, reservoir_controls)

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
    shapes = area_polygon(area_type, area_number)

    cells = regions.to_era5_grid(regions.sample_points(shapes, n=n_points))
    batches = -(-len(cells) // 60)

    st.caption(
        f"{n_points} random points fall into **{len(cells)} ERA5 grid cells** "
        f"({1 - len(cells)/n_points:.0%} fewer requests). "
        f"That is {batches} batch{'es' if batches != 1 else ''}, "
        f"roughly {batches * 45} seconds."
    )

    fetch = st.button("Download weather", type="primary")

with right:
    st.markdown("### The area")
    # The outline is drawn as a filled scatter path rather than a map layer:
    # this is a diagram of where the requests go, not a map you navigate, and a
    # basemap underneath would only compete with the dots.
    figure = go.Figure()
    for polygon in shapes.geometry:
        pieces = polygon.geoms if polygon.geom_type == "MultiPolygon" else [polygon]
        for piece in pieces:
            lon, lat = piece.exterior.xy
            figure.add_trace(go.Scatter(
                x=list(lon), y=list(lat), mode="lines", fill="toself",
                fillcolor="rgba(127,196,221,0.35)",
                line=dict(color=theme.DEEP, width=1),
                hoverinfo="skip", showlegend=False,
            ))
    figure.add_trace(go.Scatter(
        x=cells["lon"], y=cells["lat"], mode="markers", showlegend=False,
        marker=dict(size=cells["weight"] * 1.6 + 4, color=theme.AMBER, opacity=0.75,
                    line=dict(color="white", width=0.6)),
        customdata=cells["weight"],
        hovertemplate="%{y:.2f} N, %{x:.2f} E<br>%{customdata} sampled points<extra></extra>",
    ))
    figure.update_layout(
        title=f"{name}: {len(cells)} grid cells", height=430,
        margin=dict(l=10, r=10, t=45, b=10),
        xaxis=dict(visible=False),
        # Equal aspect, or Norway comes out squashed sideways.
        yaxis=dict(visible=False, scaleanchor="x", scaleratio=2.0),
    )
    st.plotly_chart(figure, width="stretch")
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

summary = st.columns(len(daily.columns))
for column, key in zip(summary, daily.columns):
    api_name, how, unit, label_text = weather_module.DAILY_RULES[key]
    value = daily[key].sum() if how == "sum" else daily[key].mean()
    column.metric(label_text, f"{value:,.1f} {unit}".replace(",", " "),
                  help="Total over the year" if how == "sum" else "Average over the year")

# One row per property, sharing the date axis. Amounts are drawn as bars and
# states as lines - a line through daily rainfall suggests it rained
# continuously between the spikes, which is exactly the wrong impression.
keys = list(daily.columns)
figure = make_subplots(rows=len(keys), cols=1, shared_xaxes=True, vertical_spacing=0.045)
for row, key in enumerate(keys, start=1):
    api_name, how, unit, label_text = weather_module.DAILY_RULES[key]
    colour = theme.COLORWAY[(row - 1) % len(theme.COLORWAY)]
    if how == "sum":
        trace = go.Bar(x=daily.index, y=daily[key], name=label_text,
                       marker=dict(color=colour, line_width=0))
    else:
        trace = go.Scatter(x=daily.index, y=daily[key], mode="lines", name=label_text,
                           line=dict(color=colour, width=1.1))
    figure.add_trace(trace, row=row, col=1)
    figure.update_yaxes(title_text=f"{unit}", title_font_size=11, row=row, col=1)
figure.update_xaxes(title_text="Date", row=len(keys), col=1)
figure.update_layout(
    height=200 * len(keys), showlegend=False, hovermode="x unified",
    title=f"Daily weather, {st.session_state['weather_label']}", bargap=0,
)
st.plotly_chart(figure, width="stretch")

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
