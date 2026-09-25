"""Shared data loading for the IND320 Streamlit app.

The raw file (data/reservoirs.csv) is the weekly Norwegian hydropower reservoir
statistics published by NVE. It is in *long* format: one row per area per week,
with Norwegian column names. Every page of the app needs the same cleaned,
*wide* version of that data, so the loading lives here and is imported by the
pages.
"""

import pandas as pd
import streamlit as st

# Path to the raw data file, relative to the repository root.
DATA_FILE = "data/reservoirs.csv"

# Norwegian -> English column names. The assignment asks for headers that are
# "English and understandable", and the course wants the whole project in
# English so that any student can read anyone else's project.
COLUMN_NAMES = {
    "dato_Id": "date",
    "omrType": "area_type",
    "omrnr": "area_number",
    "iso_aar": "iso_year",
    "iso_uke": "iso_week",
    "fyllingsgrad": "fill_level",                       # share of capacity, 0-1
    "kapasitet_TWh": "capacity_TWh",                    # max storage, TWh
    "fylling_TWh": "stored_TWh",                        # energy stored, TWh
    "neste_Publiseringsdato": "next_publication_date",
    "fyllingsgrad_forrige_uke": "fill_level_previous_week",
    "endring_fyllingsgrad": "fill_level_change",        # change since last week
}

# The five numeric series we present. They are deliberately on different scales
# (a share between 0 and 1, TWh in the tens, and a weekly change near zero),
# which is what makes the "plot all columns together" task interesting.
VALUE_COLUMNS = [
    "fill_level",
    "fill_level_previous_week",
    "fill_level_change",
    "capacity_TWh",
    "stored_TWh",
]


@st.cache_data
def load_data(area_type: str = "NO", area_number: int = 0) -> pd.DataFrame:
    """Read the CSV and return one tidy time series table.

    Streamlit reruns the whole script on every interaction, so reading and
    cleaning a 15 000-row file would happen on every click. @st.cache_data makes
    Streamlit store the result and reuse it until the arguments change.

    The raw file holds nine areas: five electricity price areas (EL1-EL5), three
    watercourse areas (VASS1-VASS3) and the whole country (NO, area 0). We keep
    one of them so that each remaining column is a single, comparable series.

    Returns a DataFrame indexed by date, with one column per measurement.
    """
    df = pd.read_csv(DATA_FILE)
    df = df.rename(columns=COLUMN_NAMES)

    # Keep one area (default: the whole of Norway).
    df = df[(df["area_type"] == area_type) & (df["area_number"] == area_number)]

    # The rows in the raw file are NOT in chronological order, so any plot made
    # before sorting would be a tangle of lines going back and forth in time.
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").set_index("date")

    return df[VALUE_COLUMNS]


def month_labels(df: pd.DataFrame) -> list[str]:
    """All months present in the data, as sorted 'YYYY-MM' strings.

    Used by the month selection slider. Strings are easier to show in a slider
    than timestamps, and sorting them alphabetically also sorts them by time.
    """
    return sorted(df.index.to_period("M").astype(str).unique())


def filter_months(df: pd.DataFrame, first_month: str, last_month: str) -> pd.DataFrame:
    """Return the rows that fall inside the chosen range of months."""
    months = df.index.to_period("M").astype(str)
    return df[(months >= first_month) & (months <= last_month)]
