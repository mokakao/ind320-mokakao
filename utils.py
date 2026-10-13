"""Shared data loading and sidebar controls for the Streamlit app.

Streamlit reruns the whole script every time anything is clicked, so anything
slow has to be cached or the app becomes unusable. Two different decorators do
that job here:

  * @st.cache_data   for values - the data frames. Streamlit stores a copy per
                     set of arguments.
  * @st.cache_resource for things that must not be copied, like a database
                     connection. One MongoClient is shared by the whole app.

In part 1 this file read a CSV. It now talks to the NVE API and to MongoDB
instead; the CSV is gone.
"""

import pandas as pd
import streamlit as st

from modules import nve, storage

# The reservoir data update once a week, so an hour-long cache is plenty and
# saves the app from re-downloading 4 MB on every click.
CACHE_SECONDS = 3600


# --- Reservoirs, straight from the NVE API ---------------------------------

@st.cache_data(ttl=CACHE_SECONDS, show_spinner="Downloading from NVE...")
def load_reservoirs(first_year: int, last_year: int) -> pd.DataFrame:
    """Download the reservoir statistics for a range of years.

    The years are part of the cache key, which is what makes the interval
    control in the sidebar a real download control: change the interval and
    Streamlit calls the API again instead of reusing the old result.
    """
    return nve.fetch_reservoirs(first_year=first_year, last_year=last_year)


@st.cache_data(ttl=CACHE_SECONDS)
def load_areas() -> pd.DataFrame:
    """The area definitions from the API, used for the labels in the app."""
    return nve.fetch_areas()


@st.cache_data(ttl=CACHE_SECONDS)
def available_years() -> tuple[int, int]:
    """First and last ISO year the API has data for.

    Needed before the slider is drawn, and the slider is what decides how much
    gets downloaded - so this one small call happens first and is cached.
    """
    years = nve.fetch_reservoirs()["iso_year"]
    return int(years.min()), int(years.max())


# --- Cross-border flows, from MongoDB --------------------------------------

@st.cache_resource(show_spinner=False)
def _flow_collection():
    """One MongoDB connection for the whole app.

    st.secrets reads .streamlit/secrets.toml locally and the pasted secrets on
    Streamlit Cloud, so the same line works in both places and the password
    never goes near GitHub.
    """
    return storage.mongo_collection(st.secrets["mongo_uri"])


@st.cache_data(ttl=CACHE_SECONDS, show_spinner="Reading from MongoDB...")
def load_flows(year: int) -> pd.DataFrame:
    """Hourly cross-border flows for one year.

    Only one year is fetched at a time. MongoDB's free tier has a transfer
    limit per week, and the pages never show more than a year at once, so
    there is no reason to pull everything.
    """
    rows = list(
        _flow_collection().find(
            {"year": int(year)},
            {"_id": 0, "timestamp": 1, "country": 1, "direction": 1, "mw": 1, "month": 1},
        )
    )
    if not rows:
        return pd.DataFrame(columns=["timestamp", "country", "direction", "mw", "month"])

    flows = pd.DataFrame(rows)
    flows["timestamp"] = pd.to_datetime(flows["timestamp"])
    return flows.sort_values("timestamp").reset_index(drop=True)


@st.cache_data(ttl=CACHE_SECONDS)
def flow_years() -> list[int]:
    """Which years are in MongoDB, newest first."""
    return sorted(_flow_collection().distinct("year"), reverse=True)


@st.cache_data(ttl=CACHE_SECONDS)
def flow_countries() -> list[str]:
    """Which connections are in MongoDB."""
    return sorted(_flow_collection().distinct("country"))


# --- Shared sidebar --------------------------------------------------------

def reservoir_controls() -> tuple[str, int, int]:
    """Draw the controls both reservoir pages use, and remember the choices.

    The widgets are given keys, so Streamlit keeps their values in
    st.session_state. That means the area type and the interval picked on the
    table page are still set when you move to the plot page - without it, every
    page would start over from the default, which is annoying to use.
    """
    oldest, newest = available_years()
    years = list(range(oldest, newest + 1))

    with st.sidebar:
        st.markdown("### Data selection")

        area_type = st.radio(
            "Area type",
            options=list(nve.AREA_TYPES),
            format_func=lambda code: nve.AREA_TYPES[code],
            key="area_type",
            help="Norway as a whole, the five price areas, or the watercourse areas",
        )

        # The default is set in session_state rather than passed as `value`.
        # Giving a widget both a key and a default value makes Streamlit warn
        # that the two could disagree, and the first run would fight the
        # remembered choice.
        if "year_range" not in st.session_state:
            st.session_state["year_range"] = (newest - 4, newest)

        first_year, last_year = st.select_slider(
            "Download interval",
            options=years,
            key="year_range",
            help="Only these years are downloaded from the API",
        )

        st.caption(
            f"Downloading {last_year - first_year + 1} of "
            f"{len(years)} available years ({oldest}-{newest})."
        )

    return area_type, first_year, last_year


def area_label(areas: pd.DataFrame, area_type: str, area_number: int) -> str:
    """Pretty name for one area, for example 'NO 2' instead of 'EL 2'."""
    match = areas[(areas["area_type"] == area_type) & (areas["area_number"] == area_number)]
    return match["name"].iloc[0] if len(match) else f"{area_type} {area_number}"
