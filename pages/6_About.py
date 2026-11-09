"""Last page: notes on the data, the pipeline and what is coming next.

It keeps sliding down the menu as pages are added in front of it, which is
where documentation belongs.
"""

import streamlit as st

from modules import nve, storage
from utils import load_areas

st.set_page_config(page_title="About - IND320", page_icon="ℹ️", layout="wide")

st.title("ℹ️ About the data and the project")

st.markdown(
    """
### Three data sources

**Reservoir levels** come from NVE's *Magasinstatistikk* API. It publishes how
full the Norwegian hydropower reservoirs are, one measurement per area per
week, going back to 1995. New figures arrive every Wednesday.

Part 1 of this project read a CSV copy of that data. Part 2 deleted the file
and calls the API directly, so the app is never out of date.

**Cross-border power flow** comes from the ENTSO-E Transparency Platform, which
reports the physical flow on every interconnector in Europe every 15 minutes.
The app covers the three cables out of price area NO2: Skagerrak to Denmark,
NordLink to Germany and North Sea Link to England.

**Weather** comes from Open-Meteo's ERA5 reanalysis, which can answer for any
coordinate because it is a model corrected against observations rather than a
set of measurements. To ask for the weather *in* a region, the region's
polygon is read from a shapefile exported by hand from
[NVE Atlas](https://atlas.nve.no), random points are scattered inside it, and
those points are snapped to the ERA5 grid so each cell is only requested once.

### How the two fit together

Reservoirs fill up with rain and snowmelt and empty when the power is used or
sold. The flow data show how much is actually being sold abroad. Later parts of
the project will use weather on top of this to say something about which way
the reservoir levels are heading.

### The pipeline

| Step | Where it runs | What it holds |
| --- | --- | --- |
| ENTSO-E API | notebook | 15-minute values, two years |
| Cassandra | local Docker container | the raw values, untouched |
| Spark | locally | picks columns, averages to hourly |
| MongoDB Atlas | cloud | the hourly values the app reads |
| Open-Meteo | the app | hourly ERA5 weather per region |
| Streamlit | cloud | this app |

The detour through Cassandra and Spark is there because the deployed app cannot
reach a database running on my laptop. Whatever the app needs has to end up
somewhere online, and the raw data are too big and too detailed to put there as
they are.

### Areas in the data
"""
)

areas = load_areas()
st.dataframe(
    areas[["area_type", "area_number", "name", "long_name", "description"]],
    hide_index=True,
    width="stretch",
)

st.info(
    "The API lists four watercourse areas, but VASS4 has no measurements - only "
    "nine of the ten areas carry data."
)

st.markdown(
    f"""
### Column names

The API returns Norwegian names. They are renamed on the way in:

{chr(10).join(f"* `{no}` → `{en}`" for no, en in nve.COLUMN_NAMES.items())}

### Finding what does not belong

Part 3 added two ways of spotting odd values, and they answer different
questions.

**Control limits** ask whether a point is far from where the season says it
should be. The seasonal shape is filtered out with a discrete cosine
transform, robust limits are set around what is left, and the limits are then
transformed back so they bend with the season. That last step matters: a
flattened series is not something anyone can read, so the plot shows the real
measurements with curved limits.

**The Local Outlier Factor** asks whether a point sits in a sparser
neighbourhood than its neighbours. Each day is described by its value and its
change from the day before, so it catches abrupt swings and not only extremes.

**STL and the spectrogram** are the other direction: instead of single odd
points they describe the structure. STL splits the reservoir filling into a
seasonal shape that drifts, a trend and a remainder; the spectrogram shows
that the yearly cycle is present throughout rather than coming and going.

### What is coming

* **Part 4:** forecasting, machine learning and the finished visualisations.

### Credentials

Nothing secret is stored in the repository. The MongoDB connection string and
the ENTSO-E token live in `.streamlit/secrets.toml`, which is in `.gitignore`,
and are pasted into the app's own secrets page on Streamlit Cloud.
"""
)

st.caption(
    f"Reading from MongoDB collection `{storage.MONGO_DB}.{storage.MONGO_COLLECTION}`."
)
