"""Historical weather from Open-Meteo's ERA5 reanalysis.

ERA5 is a reanalysis, not a set of measurements: a weather model run backwards
over the past and corrected against whatever was observed at the time. That is
what makes it possible to ask for the weather at an arbitrary coordinate in
2024 even though nobody had a thermometer there.

No API key is needed. The limits that do bite are on size: the coordinates go
into the URL, and a few hundred of them make it long enough that the server
answers 414 Request-URI Too Large. There is also a per-minute quota that counts
the volume of data rather than the number of calls - 100 locations for a year
is about 25 MB and most of a minute's allowance. So the download goes in
batches with a pause between them.
"""

import time

import pandas as pd
import requests

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# The per-minute limit counts the *volume* of data, not the number of calls, so
# the batch size depends on how many variables are being asked for. Part 3
# fetched two variables and 60 cells per batch was comfortable. Part 4 fetches
# four, which doubles the payload per cell, and the same 60 came straight back
# as 429 Too Many Requests on the first real download. Halved, with a longer
# pause: slower, but a download that finishes beats one that does not.
BATCH_SIZE = 30
PAUSE_SECONDS = 20

# A 429 is not a failure, it is the server saying "later". Waiting and asking
# again is the correct response, and it costs a minute rather than the whole
# download.
RATE_LIMIT_ATTEMPTS = 3
RATE_LIMIT_WAIT = 65

VARIABLES = ["temperature_2m", "precipitation", "snowfall", "wind_speed_10m"]

# How each hourly variable becomes a daily number, and what to call it.
#
# Part 3 downloaded temperature and precipitation only, because that was all the
# outlier task needed. Part 4 asks for a *choice* of weather property on several
# pages, and two options is not a choice worth building a selector for. Snowfall
# earns its place on hydrological grounds - in Norway winter precipitation does
# not reach the reservoirs until it melts, so snow and rain are different events
# with the same number attached. Wind is there because it is the one property
# that plausibly correlates with nothing, which makes it a useful control when
# reading the correlation page.
#
# The cost is real: four variables is roughly twice the download of two, against
# a per-minute quota that counts volume. Hence the modest point counts offered in
# the app.
#
#   key -> (API name, how to resample to daily, unit, label)
DAILY_RULES = {
    "temperature": ("temperature_2m", "mean", "°C", "Mean temperature"),
    "precipitation": ("precipitation", "sum", "mm", "Precipitation"),
    "snowfall": ("snowfall", "sum", "cm", "Snowfall"),
    "wind_speed": ("wind_speed_10m", "mean", "m/s", "Mean wind speed"),
}

# Default for anything that asks "which property?" - the assignment says the
# seasonally adjusted plots should open on temperature.
DEFAULT_PROPERTY = "temperature"


def unit(key: str) -> str:
    """The unit for one daily property, for axis labels."""
    return DAILY_RULES[key][2]


def label(key: str) -> str:
    """The human name for one daily property."""
    return DAILY_RULES[key][3]


def _one_batch(coords: pd.DataFrame, start: str, end: str, variables: list[str]) -> list[dict]:
    """Ask for one batch of coordinates and return the raw JSON per location.

    Retries on 429. Everything else - a 400 for a date the archive does not
    have, a 414 for too many coordinates in the URL - is a mistake in the
    request that will fail identically on a second try, so it is raised at once.
    """
    params = {
        "latitude": ",".join(str(v) for v in coords["lat"]),
        "longitude": ",".join(str(v) for v in coords["lon"]),
        "start_date": start,
        "end_date": end,
        "hourly": ",".join(variables),
        "timezone": "UTC",
        # Open-Meteo answers in km/h unless told otherwise, which is easy to
        # miss because the number still looks plausible: a mean of 13 reads
        # fine as a wind speed right up until you notice it would be a gale.
        "wind_speed_unit": "ms",
    }

    for attempt in range(RATE_LIMIT_ATTEMPTS):
        response = requests.get(ARCHIVE_URL, params=params, timeout=300)
        if response.status_code == 429 and attempt < RATE_LIMIT_ATTEMPTS - 1:
            time.sleep(RATE_LIMIT_WAIT)
            continue
        response.raise_for_status()
        payload = response.json()
        # A single coordinate comes back as one object, several as a list.
        return payload if isinstance(payload, list) else [payload]

    response.raise_for_status()
    return []


def fetch(
    coords: pd.DataFrame,
    start: str,
    end: str,
    variables: list[str] | None = None,
    progress=None,
) -> pd.DataFrame:
    """Download hourly ERA5 data for a set of grid cells.

    coords needs lat, lon and weight, as produced by regions.to_era5_grid.
    The weight is how many of the originally sampled points fell in that cell,
    and it is carried through so the average can be weighted correctly.

    Returns one row per cell per hour.
    """
    variables = variables or VARIABLES
    frames = []

    batches = [coords.iloc[i : i + BATCH_SIZE] for i in range(0, len(coords), BATCH_SIZE)]
    for number, batch in enumerate(batches, start=1):
        if progress:
            progress(number, len(batches))

        for location, (_, row) in zip(_one_batch(batch, start, end, variables), batch.iterrows()):
            hourly = location["hourly"]
            frame = pd.DataFrame({"time": pd.to_datetime(hourly["time"])})
            for name in variables:
                frame[name] = hourly[name]
            frame["lat"] = row["lat"]
            frame["lon"] = row["lon"]
            frame["weight"] = row["weight"]
            frames.append(frame)

        # Be polite, and stay inside the per-minute quota.
        if number < len(batches):
            time.sleep(PAUSE_SECONDS)

    return pd.concat(frames, ignore_index=True)


def regional_average(hourly: pd.DataFrame, variables: list[str] | None = None) -> pd.DataFrame:
    """Collapse the grid cells into one weighted average series per hour.

    Weighting by how many sampled points fell in each cell gives the same
    answer as downloading every one of the thousand points, because the cells
    that cover more of the region carry proportionally more of them.
    """
    variables = variables or VARIABLES
    weighted = hourly.copy()
    for name in variables:
        weighted[name] = weighted[name] * weighted["weight"]

    summed = weighted.groupby("time")[variables + ["weight"]].sum()
    for name in variables:
        summed[name] = summed[name] / summed["weight"]

    return summed.drop(columns="weight").reset_index()
