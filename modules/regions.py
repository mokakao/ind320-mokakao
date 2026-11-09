"""The map regions behind the weather data.

Open-Meteo only understands coordinates, not Norwegian administrative areas,
so to ask "what was the weather in NO3 last year" we first have to know where
NO3 actually is. The shapefiles come from NVE Atlas (Kartlag -> Administrative
områder -> NVE_Region, and Nettanlegg -> Nettområder -> Budområder), exported
as shapefiles and committed here because there is no API to fetch them from.

Two sets of regions, because the reservoir statistics use both:

  Budområder   NO 1 - NO 5   the electricity price areas
  NVE_Region   RS RØ RV RM RN   NVE's own regions, which follow watercourses

The reservoir data only has three watercourse areas (VASS1-3) while NVE has
five regions, so the two eastern ones and the two northern ones are merged.
That mapping is spelled out in the assignment text.
"""

import pathlib

import geopandas as gpd
import numpy as np

SHAPE_DIR = pathlib.Path(__file__).resolve().parents[1] / "data" / "shapefiles"

# The shapefiles are in UTM33 (metres). Open-Meteo wants degrees, and areas are
# only meaningful in metres, so both projections get used.
METRIC = "EPSG:25833"
DEGREES = "EPSG:4326"

# VASS area in the reservoir statistics -> NVE regions that make it up.
VASS_TO_NVE = {
    1: ["RS", "RØ"],   # south-east
    2: ["RV"],         # west
    3: ["RM", "RN"],   # middle and north
}

# ERA5 is a grid with roughly 0.25 degree spacing. Sampling a thousand random
# points inside a region gives far fewer distinct grid cells than that, so
# rounding to the grid and dropping duplicates cuts the download a lot without
# changing the average.
ERA5_STEP = 0.25


def load_price_areas() -> gpd.GeoDataFrame:
    """The five electricity price areas, as NO1 ... NO5.

    Returned in degrees rather than the UTM33 the shapefile ships in. Open-Meteo
    wants degrees, and so does any plot that also shows the sampled points -
    drawing a polygon in metres on the same axes as points in degrees puts them
    in two different worlds, with the points collapsing into a dot somewhere off
    the coast. Sampling converts back to metres internally where it matters.
    """
    areas = gpd.read_file(SHAPE_DIR / "Budomrader.shp").to_crs(DEGREES)
    # The column holds "NO 1" with a space; the API data and the rest of the
    # project use "NO1", so the space goes.
    areas["area"] = areas["budomr"].str.replace(" ", "", regex=False)
    return areas[["area", "geometry"]].sort_values("area").reset_index(drop=True)


def load_nve_regions(merge_to_vass: bool = False) -> gpd.GeoDataFrame:
    """NVE's own regions, optionally merged into the three VASS areas.

    With merge_to_vass the five regions become the three the reservoir
    statistics actually report on, by dissolving the pairs into one polygon
    each.
    """
    regions = gpd.read_file(SHAPE_DIR / "NVE_Region.shp").to_crs(DEGREES)
    regions = regions.rename(columns={"REGION": "region", "REGIONNAVN": "name"})

    if not merge_to_vass:
        return regions[["region", "name", "geometry"]].reset_index(drop=True)

    lookup = {code: f"VASS{vass}" for vass, codes in VASS_TO_NVE.items() for code in codes}
    regions["area"] = regions["region"].map(lookup)
    merged = regions.dissolve(by="area").reset_index()
    return merged[["area", "geometry"]].sort_values("area").reset_index(drop=True)


def sample_points(areas: gpd.GeoDataFrame, n: int = 1000, seed: int = 320) -> gpd.GeoDataFrame:
    """Scatter n random points inside each area.

    Points are drawn uniformly over the bounding box and the ones that miss the
    polygon are thrown away, repeating until there are enough. Doing it in the
    metric projection keeps the spacing even - sampling in degrees would crowd
    the points together in the north, where lines of longitude converge.
    """
    rng = np.random.default_rng(seed)
    metric = areas.to_crs(METRIC)
    label = "area" if "area" in areas.columns else "region"

    rows = []
    for _, row in metric.iterrows():
        polygon = row.geometry
        minx, miny, maxx, maxy = polygon.bounds
        inside = []
        while len(inside) < n:
            # Oversample: a region is rarely more than half its bounding box.
            batch = rng.uniform([minx, miny], [maxx, maxy], size=(3 * n, 2))
            points = gpd.points_from_xy(batch[:, 0], batch[:, 1])
            inside.extend(p for p in points[polygon.contains(points)])
        rows.extend({label: row[label], "geometry": p} for p in inside[:n])

    sampled = gpd.GeoDataFrame(rows, crs=METRIC).to_crs(DEGREES)
    sampled["lat"] = sampled.geometry.y.round(4)
    sampled["lon"] = sampled.geometry.x.round(4)
    return sampled.reset_index(drop=True)


def to_era5_grid(points: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Snap the points to the ERA5 grid and drop the duplicates.

    Several hundred random points inside one region usually land in a few dozen
    grid cells. Asking Open-Meteo for the same cell many times returns the same
    numbers and wastes the request quota, so each cell is kept once together
    with how many sampled points fell in it. That count is the weight to use
    when averaging, so the result is the same as if every point had been
    downloaded.
    """
    label = "area" if "area" in points.columns else "region"
    snapped = points.copy()
    snapped["lat"] = (snapped["lat"] / ERA5_STEP).round() * ERA5_STEP
    snapped["lon"] = (snapped["lon"] / ERA5_STEP).round() * ERA5_STEP

    grouped = (
        snapped.groupby([label, "lat", "lon"]).size().rename("weight").reset_index()
    )
    return grouped
