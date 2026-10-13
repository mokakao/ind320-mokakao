"""Cross-border power flows between Norway and its neighbours (ENTSO-E).

The ENTSO-E Transparency Platform publishes the physical flow on every
interconnector in Europe. This module pulls the three cables Liland pointed at
in the lecture - Denmark, Germany and England - in both directions, for the
last two years.

All three run out of price area NO2 (southwest Norway), which is also why NO2
usually has the most expensive power: it is the area wired to the continent.

A note on size: the data arrive in 15-minute resolution, so two years of one
direction is about 70 000 points and takes roughly four minutes to download.
Six series is half an hour, so the result is cached on disk and the download
only runs when the cache is missing.
"""

import pathlib

import pandas as pd

# Area codes as entsoe-py spells them (underscores, not dashes).
NORWAY = "NO_2"

# The neighbours, with the name of the cable so the plots can say something
# more useful than "DK_1".
CONNECTIONS = {
    "DK_1": ("Denmark", "Skagerrak"),
    "DE_LU": ("Germany", "NordLink"),
    "GB": ("England", "North Sea Link"),
}

# Country name -> cable name, so the app can label a plot without knowing
# the ENTSO-E area codes.
CONNECTIONS_BY_COUNTRY = {country: cable for country, cable in CONNECTIONS.values()}

CACHE_FILE = pathlib.Path(__file__).resolve().parents[1] / "data" / "crossborder_flows.parquet"


def _client(token: str):
    """Build the ENTSO-E client.

    The import sits inside the function on purpose. The deployed app reads
    everything from MongoDB and never calls ENTSO-E, so entsoe-py does not have
    to be installed on Streamlit Cloud - only in the local environment the
    notebook runs in.
    """
    from entsoe import EntsoePandasClient

    return EntsoePandasClient(api_key=token)


def download(token: str, years: int = 2) -> pd.DataFrame:
    """Download both directions of every connection and stack them.

    Returns the long format, which is what goes into Cassandra:

        timestamp | country | direction | mw

    direction is "export" when power leaves Norway and "import" when it comes
    in. query_crossborder_flows(a, b) gives the flow from a to b, so export is
    simply the call with Norway first.
    """
    client = _client(token)
    end = pd.Timestamp.now(tz="Europe/Oslo").normalize()
    start = end - pd.DateOffset(years=years)

    frames = []
    for code, (country, _cable) in CONNECTIONS.items():
        for direction, (source, target) in {
            "export": (NORWAY, code),
            "import": (code, NORWAY),
        }.items():
            series = client.query_crossborder_flows(source, target, start=start, end=end)
            frames.append(
                pd.DataFrame(
                    {
                        "timestamp": series.index,
                        "country": country,
                        "direction": direction,
                        "mw": series.to_numpy(dtype="float64"),
                    }
                )
            )

    flows = pd.concat(frames, ignore_index=True)

    # Cassandra has no notion of a local time zone, and mixing offsets is a
    # good way to get an off-by-one-hour bug in October. Everything is stored
    # as naive UTC and converted back only when it is shown.
    flows["timestamp"] = pd.to_datetime(flows["timestamp"], utc=True).dt.tz_localize(None)

    return flows.sort_values(["country", "direction", "timestamp"]).reset_index(drop=True)


def load_or_download(token: str, years: int = 2, refresh: bool = False) -> pd.DataFrame:
    """Use the cached parquet file if it exists, otherwise download and save it."""
    if CACHE_FILE.exists() and not refresh:
        return pd.read_parquet(CACHE_FILE)

    flows = download(token, years=years)
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    flows.to_parquet(CACHE_FILE, index=False)
    return flows


def to_hourly(flows: pd.DataFrame) -> pd.DataFrame:
    """Average the 15-minute values into hourly ones.

    This is the "trimming" step before MongoDB. Two years of quarter-hourly
    data for six series is about 420 000 rows, which is more than the free
    MongoDB tier should be asked to carry, and far more detail than a dashboard
    plot can show. Hourly keeps every shape worth seeing at a quarter of the
    size.

    An hourly mean of megawatts is still megawatts, so one hour of it is also
    the energy in MWh - which is what makes the yearly sums in the pie chart
    meaningful.
    """
    hourly = (
        flows.set_index("timestamp")
        .groupby(["country", "direction"])["mw"]
        .resample("h")
        .mean()
        .reset_index()
    )
    hourly["year"] = hourly["timestamp"].dt.year
    hourly["month"] = hourly["timestamp"].dt.month
    return hourly.dropna(subset=["mw"]).reset_index(drop=True)
