"""The map: choose an area by clicking it, and see a value painted on the country.

This page is the app's main selector. Everywhere else the area is chosen from a
dropdown, which works but tells you nothing - "VASS 2" is not a place anyone can
picture. Here the areas are the shapes they actually are, and the choice you
make follows you to the other pages through `st.session_state`.

**Why folium and not Plotly.** Every plot in this app is Plotly, and the first
version of this page was too: a `go.Choroplethmap` with
`st.plotly_chart(..., on_select="rerun")`. The map drew correctly, but the
selection event came back empty on every click - Streamlit's Plotly selection
works on traces with real data points, and a choropleth's "points" are polygons
it does not treat that way. Since the task is specifically that *a click inside
an area* must change that area's outline, the map moved to folium, whose
`st_folium` hands back the whole GeoJSON feature that was clicked. The plots
stayed Plotly.

Three layers are stacked:

* **Outlines and fill** - one `GeoJson` layer, styled per feature. The fill is
  transparent so the coastline and the place names underneath stay readable; an
  opaque choropleth of Norway is just a blue blob.
* **Selection** - a second `GeoJson` layer holding only the clicked area, drawn
  with a thick amber outline on top of the first.
* **The basemap** - CartoDB Positron, which is quiet enough that the data is
  what you notice.

The weather colouring needs one Open-Meteo download per area, which is slow
enough that it sits behind a button rather than running on every rerun.
"""

import branca.colormap as cm
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from modules import geo, nve, theme
from utils import (
    area_label,
    available_years,
    daily_weather,
    load_areas,
    load_reservoirs,
    load_weather,
)

st.title(":material/map: Map")

AREA_TYPES = list(nve.AREA_TYPES)

# --- What to show ----------------------------------------------------------

remembered = st.session_state.get("chosen_area_type", "EL")
if remembered not in AREA_TYPES:
    remembered = "EL"

top_left, top_right = st.columns([2, 3])

with top_left:
    area_type = st.radio(
        "Area type",
        options=AREA_TYPES,
        index=AREA_TYPES.index(remembered),
        format_func=lambda code: nve.AREA_TYPES[code],
        help="Which set of polygons to draw. The choice is shared with every other page.",
    )
    if area_type != st.session_state.get("chosen_area_type"):
        # Switching from price areas to watercourse areas makes the remembered
        # number meaningless - NO4 and watercourse area 4 are not the same place,
        # and watercourse area 4 does not exist.
        st.session_state.pop("chosen_area_number", None)
    st.session_state["chosen_area_type"] = area_type

with top_right:
    colour_by = st.selectbox(
        "Colour the areas by",
        options=["Area identity", "Reservoir filling", "Temperature", "Precipitation"],
        help=(
            "Area identity gives each area its own colour. The other three paint a "
            "measured value onto the shapes, using the time you choose below."
        ),
    )

geojson, shapes = geo.area_geojson(area_type)
areas = load_areas()
numbers = list(shapes["area_number"])
labels = {n: area_label(areas, area_type, n) for n in numbers}

if area_type == "NO" and colour_by != "Area identity":
    st.info(
        "Norway as a whole is one shape, so a value painted on it is just one "
        "number. Switch to the price areas or the watercourse areas to compare."
    )

# --- The value to paint ----------------------------------------------------

values: pd.Series = pd.Series(dtype=float)
units = ""
caption = ""
palette = [theme.FILL_SCALE[i][1] for i in range(len(theme.FILL_SCALE))]

if colour_by == "Reservoir filling":
    oldest, newest = available_years()
    year = st.select_slider(
        "Year", options=list(range(oldest, newest + 1)), value=newest,
        help="Reservoir statistics are weekly, so the next control picks the week",
    )
    data = load_reservoirs(year, year)
    weeks = sorted(nve.one_area(data, area_type, numbers[0]).index.unique())
    if weeks:
        week = st.select_slider(
            "Week ending", options=weeks, value=weeks[-1],
            format_func=lambda d: f"{d:%d %b %Y}",
        )
        collected = {}
        for n in numbers:
            one = nve.one_area(data, area_type, n)["fill_level"]
            if week in one.index:
                collected[n] = float(one.loc[week])
        values = pd.Series(collected)
        units = "Fill level"
        caption = f"Reservoir filling in the week ending {week:%d %B %Y}."

elif colour_by in ("Temperature", "Precipitation"):
    oldest, newest = available_years()
    year = st.select_slider(
        "Year", options=list(range(oldest, newest + 1)), value=newest - 1,
        key="map_weather_year",
    )
    months = st.select_slider(
        "Period",
        options=list(range(1, 13)),
        value=(6, 8),
        format_func=lambda m: pd.Timestamp(2000, m, 1).strftime("%b"),
        help="Temperature is averaged over these months, precipitation is summed",
    )
    points = st.select_slider(
        "Sample points per area", options=[50, 100, 200], value=50,
        help="Each point becomes an ERA5 grid cell to download. Fewer points, faster map.",
    )

    cache_key = f"map_weather_{area_type}_{colour_by}_{year}_{months}_{points}"
    if st.button(
        f"Download {colour_by.lower()} for {len(numbers)} area(s)",
        type="primary", icon=":material/download:",
    ):
        collected = {}
        progress = st.progress(0.0, text="Starting...")
        for i, n in enumerate(numbers, start=1):
            progress.progress((i - 1) / len(numbers), text=f"Downloading {labels[n]}...")
            daily = daily_weather(load_weather(area_type, n, year, points))
            window = daily[(daily.index.month >= months[0]) & (daily.index.month <= months[1])]
            collected[n] = float(
                window["temperature"].mean()
                if colour_by == "Temperature"
                else window["precipitation"].sum()
            )
        progress.empty()
        st.session_state[cache_key] = collected

    if cache_key in st.session_state:
        values = pd.Series(st.session_state[cache_key]).dropna()
        first = pd.Timestamp(2000, months[0], 1).strftime("%B")
        last = pd.Timestamp(2000, months[1], 1).strftime("%B")
        if colour_by == "Temperature":
            units = "Mean temperature (°C)"
            palette = [theme.DIVERGING[i][1] for i in range(len(theme.DIVERGING))]
            caption = f"Mean temperature, {first} to {last} {year}."
        else:
            units = "Total precipitation (mm)"
            caption = f"Total precipitation, {first} to {last} {year}."
    else:
        st.caption(
            "Nothing downloaded for this combination yet - press the button. "
            "Results are cached, so the same settings come back instantly."
        )

# --- Colours ---------------------------------------------------------------

selected = st.session_state.get("chosen_area_number")
categorical = values.empty

if categorical:
    # One colour per area, straight from the project colourway.
    colour_of = {
        n: theme.COLORWAY[i % len(theme.COLORWAY)] for i, n in enumerate(numbers)
    }
    legend = None
else:
    low, high = float(values.min()), float(values.max())
    if high == low:                      # one area, or every area identical
        high = low + 1e-9
    legend = cm.LinearColormap(palette, vmin=low, vmax=high, caption=units)
    colour_of = {n: legend(values[n]) for n in values.index}


def style(feature: dict) -> dict:
    """Fill and outline for one area.

    folium calls this once per feature. The number lives in the feature's own
    properties, put there by `geo.to_geojson`, so no lookup table is needed.
    """
    number = int(feature["properties"]["area_number"])
    return {
        "fillColor": colour_of.get(number, "#cccccc"),
        "color": theme.DEEP,
        "weight": 1.2,
        "fillOpacity": 0.45 if categorical else 0.6,
    }


def highlight(_feature: dict) -> dict:
    """What hovering looks like: a heavier outline, no colour change."""
    return {"weight": 3, "color": theme.INK, "fillOpacity": 0.7}


# --- The map ---------------------------------------------------------------

view = geo.centre(shapes)
# Basemap: plain OpenStreetMap. The obvious choice for something this quiet
# would be CartoDB Positron, but both the folium shorthand and CARTO's own CDN
# now answer without a key by sending a 2 kB placeholder tile stamped
# "API KEY REQUIRED" - with HTTP 200, so nothing errors, the map just comes up
# covered in watermarks. OSM's tiles are busier but free and unmetered, so the
# fill opacity below is kept low enough to read the coastline through it.
fmap = folium.Map(
    location=[view["lat"], view["lon"]],
    zoom_start=int(view["zoom"]) + 1,
    tiles="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attr="&copy; OpenStreetMap contributors",
    control_scale=True,
    # Without this, scrolling the page while the pointer happens to be over the
    # map zooms the map instead, and the page stays put. The +/- buttons and
    # double-click still zoom, so nothing is lost.
    scrollWheelZoom=False,
)

tooltip_fields = ["name"]
tooltip_aliases = ["Area:"]
feature_frame = shapes.copy()
feature_frame["value"] = feature_frame["area_number"].map(values).round(2)
if not categorical:
    tooltip_fields.append("value")
    tooltip_aliases.append(f"{units}:")

folium.GeoJson(
    geo.to_geojson(feature_frame),
    name="areas",
    style_function=style,
    highlight_function=highlight,
    tooltip=folium.GeoJsonTooltip(fields=tooltip_fields, aliases=tooltip_aliases),
).add_to(fmap)

# The selected area on top: no new fill, just an outline you cannot miss.
if selected in numbers:
    chosen = feature_frame[feature_frame["area_number"] == selected]
    folium.GeoJson(
        geo.to_geojson(chosen),
        name="selected",
        style_function=lambda _f: {
            "fillColor": theme.AMBER,
            "color": theme.AMBER,
            "weight": 4.5,
            "fillOpacity": 0.15,
        },
        tooltip=None,
    ).add_to(fmap)

if legend is not None:
    legend.add_to(fmap)

# returned_objects keeps Streamlit from rerunning the whole script every time
# the map is panned or zoomed - only a click on a feature matters here.
event = st_folium(
    fmap,
    key=f"area_map_{area_type}",
    height=560,
    width=None,
    returned_objects=["last_active_drawing"],
)

# --- The click -------------------------------------------------------------

drawing = (event or {}).get("last_active_drawing")
if drawing:
    clicked = (drawing.get("properties") or {}).get("area_number")
    if clicked is not None and int(clicked) != selected:
        st.session_state["chosen_area_number"] = int(clicked)
        st.rerun()

if caption:
    st.caption(caption)

if selected in numbers:
    st.success(
        f"Selected: **{labels[selected]}**. Every other page now works on this area.",
        icon=":material/check_circle:",
    )
else:
    st.info("Click an area to select it.", icon=":material/touch_app:")

with st.expander("Where the shapes come from"):
    st.markdown(
        f"""
Outlines are the NVE Atlas shapefiles from part 3, converted to GeoJSON here
rather than re-exported: `Budomrader.shp` for the price areas and
`NVE_Region.shp` for the watercourse areas, with NVE's five regions dissolved
into the three the reservoir statistics report on.

The coastline is simplified to a **{geo.SIMPLIFY_METRES} m** tolerance, measured
in UTM33 so it means the same distance everywhere in the country. That is what
keeps the payload at tens of kilobytes instead of several megabytes - the
browser receives the whole outline again on every rerun.
"""
    )
