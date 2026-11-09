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
    """Daily precipitation totals and mean temperature.

    Hourly rainfall is mostly zeros with occasional spikes, which is hard to
    read and hard to do statistics on. Daily totals are the natural unit.
    """
    indexed = hourly.set_index("time")
    return pd.DataFrame(
        {
            "precipitation": indexed["precipitation"].resample("D").sum(),
            "temperature": indexed["temperature_2m"].resample("D").mean(),
        }
    )


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
