"""Shapefiles turned into GeoJSON, ready for an interactive map.

Part 3 used the NVE Atlas shapefiles only as a way of finding coordinates to
ask Open-Meteo about: the polygons never left geopandas. Part 4 puts them on
screen, and that changes what matters about them.

Two things had to be solved.

**Size.** The NVE region outlines follow the real coastline, fjords and all.
Handed to a browser unchanged, the five price areas come to several megabytes
of coordinates, and every rerun ships them again. They are simplified in the
metric projection first - a tolerance in metres is a distance you can reason
about, while a tolerance in degrees means something different in Finnmark than
it does in Agder. At 750 m the fjords are still recognisably fjords and the
payload drops by more than an order of magnitude.

**Identity.** The map has to tell the rest of the app which area was clicked,
and the rest of the app speaks in the numbers the reservoir statistics use
(EL 1-5, VASS 1-3, NO as a whole). So each feature carries that number as its
GeoJSON `id`, and the click handler never has to parse a label.
"""

from __future__ import annotations

import json

import geopandas as gpd

from modules import regions

# Simplification tolerance in metres, applied in UTM33 before converting to
# degrees. Chosen by eye: 750 m keeps Sognefjorden and Vestfjorden readable
# while cutting the GeoJSON from megabytes to a couple of hundred kilobytes.
SIMPLIFY_METRES = 750

# Human names for the areas, so the map tooltip says something better than
# "VASS2". The price areas are commonly known by their regions.
EL_NAMES = {
    1: "NO1 Oslo / south-east",
    2: "NO2 Kristiansand / south",
    3: "NO3 Trondheim / middle",
    4: "NO4 Tromsø / north",
    5: "NO5 Bergen / west",
}
VASS_NAMES = {
    1: "Watercourse area 1 - south-east",
    2: "Watercourse area 2 - west",
    3: "Watercourse area 3 - middle and north",
}


def load_area_shapes(area_type: str) -> gpd.GeoDataFrame:
    """Polygons for one area type, numbered the way the reservoir data numbers them.

    Returns columns `area_number`, `name` and `geometry` in degrees. The number
    is what ties a shape to a row of reservoir statistics, and it is the only
    thing the rest of the app needs to carry around.
    """
    if area_type == "EL":
        shapes = regions.load_price_areas().copy()
        shapes["area_number"] = shapes["area"].str.removeprefix("NO").astype(int)
        shapes["name"] = shapes["area_number"].map(EL_NAMES)
    elif area_type == "VASS":
        shapes = regions.load_nve_regions(merge_to_vass=True).copy()
        shapes["area_number"] = shapes["area"].str.removeprefix("VASS").astype(int)
        shapes["name"] = shapes["area_number"].map(VASS_NAMES)
    else:
        # Norway as a whole is area number 0 in the reservoir statistics.
        shapes = regions.load_country().copy()
        shapes["area_number"] = 0
        shapes["name"] = "Norway"

    return shapes[["area_number", "name", "geometry"]].sort_values(
        "area_number"
    ).reset_index(drop=True)


def simplify(shapes: gpd.GeoDataFrame, metres: int = SIMPLIFY_METRES) -> gpd.GeoDataFrame:
    """Drop coastline detail, measuring the tolerance in metres.

    geopandas will happily simplify a layer that is in degrees, but then the
    tolerance is in degrees too, and a degree of longitude is 62 km at the
    south coast and 36 km at Nordkapp. Projecting to UTM33 first means one
    tolerance that behaves the same the length of the country.

    preserve_topology keeps the polygons valid, which matters because an
    invalid ring renders as a black smear rather than an error.
    """
    simplified = shapes.copy()
    metric = simplified.to_crs(regions.METRIC)
    metric["geometry"] = metric.geometry.simplify(metres, preserve_topology=True)
    simplified["geometry"] = metric.to_crs(regions.DEGREES).geometry
    return simplified


def to_geojson(shapes: gpd.GeoDataFrame) -> dict:
    """GeoJSON with `area_number` as the feature id.

    Plotly matches a choropleth's `locations` against the feature id, so making
    the id the area number means the data frame can be indexed by the same
    number the API uses, with no lookup table in between.
    """
    frame = shapes.copy()
    frame["id"] = frame["area_number"].astype(int)
    return json.loads(frame.set_index("id").to_json())


def area_geojson(area_type: str, metres: int = SIMPLIFY_METRES) -> tuple[dict, gpd.GeoDataFrame]:
    """The GeoJSON and the frame behind it, for one area type.

    Both are returned because the map needs the GeoJSON for the outlines and
    the frame for the names and the centre points.
    """
    shapes = simplify(load_area_shapes(area_type), metres)
    return to_geojson(shapes), shapes


def centre(shapes: gpd.GeoDataFrame) -> dict[str, float]:
    """A sensible starting centre and zoom for the map.

    Taken from the bounding box of whatever is being shown, so selecting the
    price areas and selecting the whole country both start framed rather than
    somewhere in the North Sea.
    """
    minx, miny, maxx, maxy = shapes.total_bounds
    span = max(maxx - minx, maxy - miny)
    # Rough fit: Norway end to end is about 13 degrees of latitude and sits
    # comfortably at zoom 3.2; a single price area is a third of that.
    zoom = 3.3 if span > 10 else 4.2 if span > 5 else 5.0
    # Cast off numpy's float64: Plotly accepts it, but it leaks into st.session_state
    # and then into anything that tries to serialise the selection.
    return {"lat": float((miny + maxy) / 2), "lon": float((minx + maxx) / 2), "zoom": zoom}
