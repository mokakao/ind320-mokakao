"""Reservoir data from the NVE Magasinstatistikk API.

Part 1 of this project read a local CSV file. Part 2 drops that file and goes
straight to the API instead, so the app always shows whatever NVE published
last Wednesday.

Endpoints live under
https://biapi.nve.no/magasinstatistikk/api/Magasinstatistikk/ and none of them
take parameters - HentOffentligData simply returns the whole history (about
15 000 rows, 4 MB). That matters for the "download interval" control in the
app: there is no way to ask the API for a date range, so the interval is
applied right after the call, and the download itself is cached per interval.
"""

import pandas as pd
import requests

BASE_URL = "https://biapi.nve.no/magasinstatistikk/api/Magasinstatistikk"

# Same mapping as in part 1. The API returns the exact column names that were
# in the CSV, so nothing here had to change when the source was swapped.
COLUMN_NAMES = {
    "dato_Id": "date",
    "omrType": "area_type",
    "omrnr": "area_number",
    "iso_aar": "iso_year",
    "iso_uke": "iso_week",
    "fyllingsgrad": "fill_level",                 # share of capacity, 0-1
    "kapasitet_TWh": "capacity_TWh",              # max storage, TWh
    "fylling_TWh": "stored_TWh",                  # energy stored, TWh
    "neste_Publiseringsdato": "next_publication_date",
    "fyllingsgrad_forrige_uke": "fill_level_previous_week",
    "endring_fyllingsgrad": "fill_level_change",
}

# The numeric series worth plotting. The rest are labels and bookkeeping.
VALUE_COLUMNS = [
    "fill_level",
    "fill_level_previous_week",
    "fill_level_change",
    "capacity_TWh",
    "stored_TWh",
]

# Human-readable names for the three area types, used in the radio buttons.
AREA_TYPES = {
    "NO": "Norway as a whole",
    "EL": "Electricity price areas (NO1-NO5)",
    "VASS": "Watercourse areas",
}


def _get(endpoint: str) -> list[dict]:
    """GET one endpoint and return the decoded JSON.

    raise_for_status turns a 404 or a 500 into an exception instead of letting
    a half-broken response slip through into a DataFrame.
    """
    response = requests.get(f"{BASE_URL}/{endpoint}", timeout=60)
    response.raise_for_status()
    return response.json()


def fetch_areas() -> pd.DataFrame:
    """The areas the API covers, as one row per area.

    The response is nested: one object with the keys land, elspot and vassdrag,
    each holding a list of areas. Flattening it makes it easy to show as a
    table, and it answers the part of the task that asks which areas of Norway
    the API covers.

    Worth knowing: this endpoint lists four watercourse areas, but VASS4 has no
    rows in the measurement data. Only nine of the ten areas carry data.
    """
    raw = _get("HentOmr%C3%A5der")[0]
    rows = [area for group in raw.values() for area in group]
    areas = pd.DataFrame(rows)
    return areas.rename(
        columns={
            "navn": "name",
            "navn_langt": "long_name",
            "beskrivelse": "description",
            "omrType": "area_type",
            "omrnr": "area_number",
        }
    )


def fetch_reservoirs(first_year: int | None = None, last_year: int | None = None) -> pd.DataFrame:
    """Download the weekly reservoir statistics.

    Returns the long format: one row per area per week, with English column
    names, a real datetime column and sorted chronologically. Part 1 taught me
    the hard way that the rows arrive in no particular order - plotting before
    sorting gives a tangle of lines jumping back and forth in time.

    first_year/last_year trim the result to a range of ISO years. The API has
    no date parameters, so this happens after the download, but it is what the
    app's interval control is wired to.
    """
    df = pd.DataFrame(_get("HentOffentligData")).rename(columns=COLUMN_NAMES)

    df["date"] = pd.to_datetime(df["date"])

    # next_publication_date is 0001-01-01 on most rows, which pandas cannot
    # parse as a normal timestamp. It is a placeholder, not a date, so the
    # column is parsed leniently and the junk becomes NaT.
    df["next_publication_date"] = pd.to_datetime(
        df["next_publication_date"], errors="coerce"
    )

    if first_year is not None:
        df = df[df["iso_year"] >= first_year]
    if last_year is not None:
        df = df[df["iso_year"] <= last_year]

    return df.sort_values(["area_type", "area_number", "date"]).reset_index(drop=True)


def one_area(df: pd.DataFrame, area_type: str = "NO", area_number: int = 0) -> pd.DataFrame:
    """Pick a single area and return it indexed by date.

    The file holds nine areas stacked on top of each other, so every column is
    a mix of nine places until one of them is picked out. After this, each
    column is one clean series over time.
    """
    one = df[(df["area_type"] == area_type) & (df["area_number"] == area_number)]
    return one.set_index("date")[VALUE_COLUMNS].sort_index()


def area_numbers(df: pd.DataFrame, area_type: str) -> list[int]:
    """The area numbers that actually have data for a given area type."""
    return sorted(df.loc[df["area_type"] == area_type, "area_number"].unique())


def wide(df: pd.DataFrame, area_type: str, column: str = "fill_level") -> pd.DataFrame:
    """One column per area number, indexed by date.

    This is the shape matplotlib and st.line_chart want when the radio button
    asks for "all the areas of this type" - for example the fill level of NO1
    to NO5 as five lines in the same plot.
    """
    subset = df[df["area_type"] == area_type]
    return subset.pivot_table(index="date", columns="area_number", values=column).sort_index()
