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

# 100 locations for a year worked in testing and took about half a minute; 200
# tripped the per-minute limit. 60 leaves room for the limit to be stricter on
# a busy day.
BATCH_SIZE = 60
PAUSE_SECONDS = 12

VARIABLES = ["temperature_2m", "precipitation"]


def _one_batch(coords: pd.DataFrame, start: str, end: str, variables: list[str]) -> list[dict]:
    """Ask for one batch of coordinates and return the raw JSON per location."""
    response = requests.get(
        ARCHIVE_URL,
        params={
            "latitude": ",".join(str(v) for v in coords["lat"]),
            "longitude": ",".join(str(v) for v in coords["lon"]),
            "start_date": start,
            "end_date": end,
            "hourly": ",".join(variables),
            "timezone": "UTC",
        },
        timeout=300,
    )
    response.raise_for_status()
    payload = response.json()
    # A single coordinate comes back as one object, several as a list.
    return payload if isinstance(payload, list) else [payload]


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
