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

import functools

import pandas as pd
import streamlit as st

from modules import nve, storage

# The reservoir data update once a week, so an hour-long cache is plenty and
# saves the app from re-downloading 4 MB on every click.
CACHE_SECONDS = 3600


def guarded(source: str):
    """Wrap a loader so an unreachable source stops the page politely.

    Applied *outside* st.cache_data, so the cache still works normally and only
    a call that actually goes out to the network can be intercepted. Every page
    that calls one of these loaders is covered without a single try/except of
    its own - which is the point, because the one page that forgot the
    try/except would be the one that crashes.

    `safe` is defined at the bottom of this file; the lookup happens when the
    loader is called, not when it is decorated, so the order does not matter.
    """
    def wrap(loader):
        @functools.wraps(loader)
        def inner(*args, **kwargs):
            return safe(loader, *args, source=source, **kwargs)
        return inner
    return wrap


# --- Reservoirs, straight from the NVE API ---------------------------------

@guarded("NVE")
@st.cache_data(ttl=CACHE_SECONDS, show_spinner="Downloading from NVE...")
def load_reservoirs(first_year: int, last_year: int) -> pd.DataFrame:
    """Download the reservoir statistics for a range of years.

    The years are part of the cache key, which is what makes the interval
    control in the sidebar a real download control: change the interval and
    Streamlit calls the API again instead of reusing the old result.
    """
    return nve.fetch_reservoirs(first_year=first_year, last_year=last_year)


@guarded("NVE")
@st.cache_data(ttl=CACHE_SECONDS)
def load_areas() -> pd.DataFrame:
    """The area definitions from the API, used for the labels in the app."""
    return nve.fetch_areas()


@guarded("NVE")
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


@guarded("MongoDB")
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


@guarded("MongoDB")
@st.cache_data(ttl=CACHE_SECONDS)
def flow_years() -> list[int]:
    """Which years are in MongoDB, newest first."""
    return sorted(_flow_collection().distinct("year"), reverse=True)


@guarded("MongoDB")
@st.cache_data(ttl=CACHE_SECONDS)
def flow_countries() -> list[str]:
    """Which connections are in MongoDB."""
    return sorted(_flow_collection().distinct("country"))


# --- Shared sidebar --------------------------------------------------------

def reservoir_controls(with_area: bool = False) -> tuple:
    """Draw the controls the pages share, and remember the choices.

    The choices are kept in st.session_state under keys of my own and handed
    back to the widgets as explicit defaults. Giving the widgets a `key` and
    letting Streamlit remember them does not survive moving between pages:
    widget state belongs to the page that drew it, so the range slider comes
    back as a single-value one and unpacking it fails.

    with_area adds a selector for one specific area within the chosen type.
    The weather page needs it, because Open-Meteo is asked for one region at a
    time, and the task wants that choice tied to the reservoir selector rather
    than being a separate control of its own.
    """
    oldest, newest = available_years()
    years = list(range(oldest, newest + 1))
    area_codes = list(nve.AREA_TYPES)

    remembered_type = st.session_state.get("chosen_area_type", area_codes[0])
    remembered_range = st.session_state.get("chosen_years", (newest - 4, newest))

    if remembered_type not in area_codes:
        remembered_type = area_codes[0]
    if (
        not isinstance(remembered_range, tuple)
        or len(remembered_range) != 2
        or not all(year in years for year in remembered_range)
    ):
        remembered_range = (newest - 4, newest)

    with st.sidebar:
        st.markdown("### Data selection")

        area_type = st.radio(
            "Area type",
            options=area_codes,
            index=area_codes.index(remembered_type),
            format_func=lambda code: nve.AREA_TYPES[code],
            help="Norway as a whole, the five price areas, or the watercourse areas",
        )

        first_year, last_year = st.select_slider(
            "Download interval",
            options=years,
            value=remembered_range,
            help="Only these years are downloaded from the API",
        )

        st.caption(
            f"Downloading {last_year - first_year + 1} of "
            f"{len(years)} available years ({oldest}-{newest})."
        )

        area_number = None
        if with_area:
            data = load_reservoirs(first_year, last_year)
            numbers = nve.area_numbers(data, area_type)
            areas = load_areas()
            remembered_number = st.session_state.get("chosen_area_number")
            index = numbers.index(remembered_number) if remembered_number in numbers else 0
            area_number = st.selectbox(
                "Area",
                options=numbers,
                index=index,
                format_func=lambda n: area_label(areas, area_type, n),
                help="Which single area the weather is downloaded for",
            )
            st.session_state["chosen_area_number"] = area_number

    st.session_state["chosen_area_type"] = area_type
    st.session_state["chosen_years"] = (first_year, last_year)

    if with_area:
        return area_type, first_year, last_year, area_number
    return area_type, first_year, last_year


def area_label(areas: pd.DataFrame, area_type: str, area_number: int) -> str:
    """Pretty name for one area, for example 'NO 2' instead of 'EL 2'."""
    match = areas[(areas["area_type"] == area_type) & (areas["area_number"] == area_number)]
    return match["name"].iloc[0] if len(match) else f"{area_type} {area_number}"


# --- Weather, from Open-Meteo ----------------------------------------------

@guarded("Open-Meteo")
@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def load_weather(area_type: str, area_number: int, year: int, n_points: int) -> pd.DataFrame:
    """Hourly ERA5 weather averaged over one area, for one year.

    Cached on every argument, so the slow part only runs when something
    actually changes. The point count is a control rather than a constant:
    the notebook uses a thousand points per region, but a Streamlit page that
    takes several minutes to answer is not a page anyone will use, and a
    couple of hundred points already land in enough grid cells to give
    essentially the same average.
    """
    from modules import regions, weather

    shapes = area_polygon(area_type, area_number)

    points = regions.sample_points(shapes, n=n_points)
    cells = regions.to_era5_grid(points)

    hourly = weather.fetch(cells, f"{year}-01-01", last_day_of(year))
    return weather.regional_average(hourly)


def last_day_of(year: int) -> str:
    """The last date the ERA5 archive will answer for, inside a given year.

    The archive stops at yesterday: asking for 31 December of the current year
    comes back as `400 Parameter 'end_date' is out of allowed range`. So the
    current year is cut short at yesterday and every earlier year runs to its
    real end.
    """
    yesterday = pd.Timestamp.today().normalize() - pd.Timedelta(days=1)
    return min(pd.Timestamp(f"{year}-12-31"), yesterday).strftime("%Y-%m-%d")


def daily_weather(hourly: pd.DataFrame) -> pd.DataFrame:
    """Collapse the hourly weather into one row per day.

    Hourly rainfall is mostly zeros with occasional spikes, which is hard to
    read and hard to do statistics on. Daily is the natural unit - but not with
    the same arithmetic for every variable: rain and snow are *amounts* and have
    to be summed, temperature and wind are *states* and have to be averaged.
    That mapping lives in weather.DAILY_RULES so the pages and the notebook
    cannot disagree about it.

    Columns that are missing from an older cached download are skipped rather
    than raising, so a result cached before snowfall was added still renders.
    """
    from modules import weather

    indexed = hourly.set_index("time")
    columns = {}
    for key, (api_name, how, _unit, _label) in weather.DAILY_RULES.items():
        if api_name not in indexed.columns:
            continue
        resampled = indexed[api_name].resample("D")
        columns[key] = resampled.sum() if how == "sum" else resampled.mean()
    return pd.DataFrame(columns)


def area_polygon(area_type: str, area_number: int):
    """The polygon for one area, whichever kind of area it is.

    Shared by the weather page and the loader so the map and the download can
    never disagree about which shape they mean.
    """
    from modules import regions

    if area_type == "EL":
        shapes = regions.load_price_areas()
        return shapes[shapes["area"] == f"NO{area_number}"]
    if area_type == "VASS":
        shapes = regions.load_nve_regions(merge_to_vass=True)
        return shapes[shapes["area"] == f"VASS{area_number}"]
    # Norway as a whole: one dissolved polygon, so the sampling stays even
    # instead of giving the small southern areas three times the density of
    # the large northern one.
    return regions.load_country()


# --- Exchange rates, from Norges Bank --------------------------------------

@guarded("Norges Bank")
@st.cache_data(ttl=CACHE_SECONDS, show_spinner="Asking Norges Bank...")
def load_rates(start: str, end: str, currencies: tuple[str, ...] = ("EUR", "USD")) -> pd.DataFrame:
    """Daily exchange rates for a date range.

    The currencies arrive as a tuple rather than a list because Streamlit hashes
    the arguments to build the cache key, and a list is not hashable.
    """
    from modules import currency

    return currency.fetch_rates(start, end, list(currencies))


# --- Putting weekly and daily series on the same index ----------------------

def weekly_from_daily(daily: pd.DataFrame) -> pd.DataFrame:
    """Resample daily weather to the weeks the reservoir statistics use.

    NVE publishes one row per ISO week, dated the Sunday that ends it - the
    newest row as I write this is 2026-11-08, a Sunday. pandas' plain "W" rule
    happens to mean "W-SUN", so the two line up without any offset, but the
    rule is spelled out below rather than relied on silently.

    Amounts are summed and states averaged, the same split as daily_weather
    uses, so a weekly precipitation figure is millimetres that week rather than
    a meaningless average of daily totals.
    """
    from modules import weather

    columns = {}
    for key in daily.columns:
        if key not in weather.DAILY_RULES:
            continue
        how = weather.DAILY_RULES[key][1]
        resampled = daily[key].resample("W-SUN")
        columns[key] = resampled.sum() if how == "sum" else resampled.mean()
    return pd.DataFrame(columns)


# --- When a source is not there --------------------------------------------
#
# This is the bonus task from the assignment list, and it earned its place the
# hard way: while part 4 was being built, biapi.nve.no stopped answering for a
# couple of minutes, and every page that touched it came up as a red
# `requests.exceptions.ReadTimeout` traceback with forty lines of Streamlit
# internals under it. Correct, and useless to anybody who is not the author.
#
# Two layers deal with it. Lower down, modules/nve.py now retries a timeout
# three times, because one timeout from that host usually means nothing. Up
# here, anything that still fails is turned into a sentence that says which
# source is missing, whether the fault is likely to be ours, and what to do
# about it - plus a button that clears the cache and tries again.

# Imported lazily inside the function: pymongo is a heavy import and the
# currency and weather pages have no reason to pay for it.
_SOURCE_HELP = {
    "NVE": (
        "the reservoir statistics",
        "biapi.nve.no is slow or down. It is a public API with no status page "
        "and no key, so there is nothing to check - it usually comes back "
        "within a few minutes.",
    ),
    "MongoDB": (
        "the stored cross-border flows",
        "The database did not answer. On Streamlit Cloud this is usually the "
        "free tier pausing a cluster that has been idle, which takes a moment "
        "to wake.",
    ),
    "Open-Meteo": (
        "the weather archive",
        "Open-Meteo refused or timed out. The usual cause is the per-minute "
        "volume limit - wait a minute, or ask for fewer sample points.",
    ),
    "Norges Bank": (
        "the exchange rates",
        "data.norges-bank.no did not answer.",
    ),
}


def safe(loader, *args, source: str = "NVE", **kwargs):
    """Call a loader, and stop the page politely if the source is unreachable.

    Returns whatever the loader returns. If it raises a network or database
    error, the page gets an explanation and a retry button instead of a
    traceback, and then stops - `st.stop()` ends the script run cleanly, so
    nothing below it tries to work with data that never arrived.

    Programming errors are deliberately *not* caught. A KeyError in my own code
    should still show its traceback; hiding it behind "the source is down"
    would be worse than the crash.
    """
    import requests

    try:
        return loader(*args, **kwargs)
    except Exception as error:                       # noqa: BLE001 - narrowed below
        network = isinstance(error, (requests.RequestException, TimeoutError, OSError))
        if not network and type(error).__module__.split(".")[0] != "pymongo":
            raise

        what, why = _SOURCE_HELP.get(source, (source, ""))
        st.error(
            f"**Could not reach {source}.** This page needs {what}.\n\n{why}",
            icon=":material/cloud_off:",
        )
        with st.expander("The underlying error"):
            st.code(f"{type(error).__name__}: {error}")
        if st.button("Try again", icon=":material/refresh:", key=f"retry_{source}"):
            st.cache_data.clear()
            st.rerun()
        st.stop()
