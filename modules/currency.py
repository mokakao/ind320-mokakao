"""Exchange rates from the Norges Bank SDMX API.

Krafteksport is paid for in euro and dollars, so the export figures from
ENTSO-E only turn into kroner once there is a rate to multiply them by. This
module fetches EUR/NOK and USD/NOK from Norges Bank.

The API is SDMX, which is a standard built for statistical agencies rather
than for convenience, and four things about it were not obvious:

**csv, not JSON.** ``format=sdmx-json`` returns the observations under
positional keys - a series called ``"0:0:0:0"`` holding ``{"0": ["11.3529"]}``
- and the only way to learn that the first ``0`` means EUR and the second
means 2 January is to walk ``structure.dimensions.series`` and
``structure.observation`` and match by position. ``format=csv`` returns one
flat row per observation with every piece of metadata spelled out on the row.
For two currencies there is no reason to decode the nested version.

Two traps in the csv, though. ``locale`` has to be pinned to ``en``, because
``locale=no`` returns a decimal comma (``11,7173``) that pandas reads as text.
And the value column uses a thousands separator, so CHF comes back as
``1,140.68`` - one such row turns the whole column into strings. Hence
``thousands=","`` in the parser.

**The rate is not always per unit.** ``UNIT_MULT`` is 0 ("Units") for EUR,
USD and GBP but 2 ("Hundreds") for JPY, SEK, DKK and CHF: 100 Swedish kronor
cost 95.16 NOK, not one. The two currencies this project needs are both
per-unit, which is exactly why the trap is easy to walk into later - so the
value is divided by ``10 ** UNIT_MULT`` on the way in and every number this
module returns is NOK for one unit of the foreign currency.

**The gaps are not just weekends.** Frequency ``B`` is Norwegian business
days. 2025 returned 251 dates where the calendar has 261 weekdays: Good
Friday, Easter Monday, 1 and 17 May, Ascension and Whit Monday are missing
too. So a caller cannot rebuild the series with ``pd.bdate_range`` either,
because that counts 1 May as a working day. A caller who needs a value for
every calendar day should reindex onto calendar days and forward-fill, which
is what ``to_daily`` does: the last rate Norges Bank fixed stays in force
until the next fixing, so carrying it forward is the economically correct
reading of a Saturday. Never interpolate - that invents a rate on a day no
rate existed, and backward-filling would use tomorrow's news to price today.

**The dates carry no time zone.** ``TIME_PERIOD`` is a plain calendar date,
and the ``COLLECTION`` attribute says the rates are collected at "ECB
concertation time 14:15 CET". So each row is the rate observed around 14:15
Central European Time on that Norwegian calendar date. The index is therefore
a naive ``DatetimeIndex`` of dates in Norwegian local time, deliberately left
naive: localising it to Europe/Oslo would stamp every observation midnight,
implying a time of day the number does not have.
"""

import io

import pandas as pd
import requests

BASE_URL = "https://data.norges-bank.no/api/data/EXR"

# The project needs these two. Read but never mutated, so sharing the list
# between calls is safe.
DEFAULT_CURRENCIES = ["EUR", "USD"]

# Dimension order of the series key: FREQ.BASE_CUR.QUOTE_CUR.TENOR. Leaving a
# dimension empty means "all of it", which is how available_currencies asks
# for every currency at once.
FREQUENCY_DAILY = "B"      # Norwegian business days; A and M also exist
QUOTE_CURRENCY = "NOK"     # the price is always in kroner
TENOR_SPOT = "SP"          # spot, the only tenor published for EXR

# EXR also carries two trade-weighted indices under what looks like a currency
# code. They are index levels, not prices, so they are no use to a conversion.
NON_CURRENCY_CODES = {"TWI", "I44"}


def _fetch_csv(base_currencies: list[str], **params: str) -> pd.DataFrame:
    """Run one query against the EXR dataflow and parse the csv response.

    Several currencies go into a single request joined by ``+``, which is the
    SDMX way of saying "these values of this dimension" and keeps the whole
    download to one round trip.

    raise_for_status matters more here than usual: when no requested code
    exists the API answers 404 with an XML error document in the body, and
    without this it would reach the csv parser and fail with something
    unrecognisable. Note the asymmetry - ``EUR+ZZZ`` returns 200 and quietly
    gives back EUR alone, so a typo in one of several codes never raises. That
    is why fetch_rates reindexes the columns afterwards.
    """
    key = f"{FREQUENCY_DAILY}.{'+'.join(base_currencies)}.{QUOTE_CURRENCY}.{TENOR_SPOT}"
    response = requests.get(
        f"{BASE_URL}/{key}",
        params={"format": "csv", "locale": "en", **params},
        timeout=60,
    )
    response.raise_for_status()

    # utf-8-sig rather than utf-8 because the API will prepend a byte order
    # mark if anyone ever adds bom=include, and utf-8-sig reads both.
    text = response.content.decode("utf-8-sig")
    return pd.read_csv(io.StringIO(text), sep=";", thousands=",")


def _tidy(raw: pd.DataFrame) -> pd.DataFrame:
    """Turn the raw csv rows into long format with rates per single unit.

    Returns date / currency / rate, where rate is NOK for one unit of the
    currency regardless of how Norges Bank chose to quote it.
    """
    tidy = pd.DataFrame(
        {
            "date": pd.to_datetime(raw["TIME_PERIOD"]),
            "currency": raw["BASE_CUR"],
            # UNIT_MULT is the power of ten the quote is scaled by: 0 for a
            # per-unit quote, 2 when the price is for 100 units.
            "rate": raw["OBS_VALUE"] / 10.0 ** raw["UNIT_MULT"],
        }
    )
    return tidy.sort_values(["currency", "date"]).reset_index(drop=True)


def fetch_rates(
    start: str,
    end: str,
    currencies: list[str] = DEFAULT_CURRENCIES,
) -> pd.DataFrame:
    """Download daily exchange rates against the krone.

    start and end are ISO dates, ``"2024-01-01"``. Both ends are inclusive.

    Returns one column per currency indexed by observation date: the index is
    naive and holds Norwegian calendar dates, and each value is the number of
    kroner one unit of that currency cost at 14:15 CET that day. Only days
    Norges Bank published are present, so the index skips weekends and
    Norwegian public holidays - see ``to_daily`` to fill those in.

    The column order follows the currencies argument rather than whatever
    order the API happened to return the series in, so a caller plotting
    ``["EUR", "USD"]`` gets EUR first.
    """
    raw = _fetch_csv(list(currencies), startPeriod=start, endPeriod=end)
    tidy = _tidy(raw)

    wide = tidy.pivot(index="date", columns="currency", values="rate")
    wide.columns.name = None

    # Reindex rather than subset, so a currency the API returned nothing for
    # shows up as an all-NaN column instead of vanishing. A misspelled code
    # among valid ones comes back 200 with that series simply absent, so
    # without this the caller would get fewer columns than it asked for and
    # only notice further down.
    return wide.reindex(columns=list(currencies)).sort_index()


def fetch_latest(currencies: list[str] = DEFAULT_CURRENCIES, days: int = 1) -> pd.DataFrame:
    """The most recent published rates, without having to guess a date range.

    Useful because "today" is often not a publishing day - asking for a range
    ending on a Sunday returns nothing for Sunday, and the app would rather
    show Friday's rate than an empty table. days is the number of published
    observations to return, counting backwards, not calendar days.
    """
    raw = _fetch_csv(list(currencies), lastNObservations=str(days))
    tidy = _tidy(raw)

    wide = tidy.pivot(index="date", columns="currency", values="rate")
    wide.columns.name = None
    return wide.reindex(columns=list(currencies)).sort_index()


def to_daily(rates: pd.DataFrame, end: str | None = None) -> pd.DataFrame:
    """Reindex onto every calendar day and carry the last rate forward.

    This is the answer to the weekend problem. Joining exchange rates onto an
    hourly or daily series of power flows needs a value on Saturdays, and the
    rate that applied on Saturday is the one fixed on Friday, because no new
    one was set.

    end extends the result past the last observation, for when the rates have
    to cover a period that runs to today but Norges Bank has not published for
    the last day or two yet.

    The first row cannot be filled from anything earlier, so if the requested
    range begins on a weekend those leading days stay NaN. Fetching a few days
    before the range of interest avoids that.
    """
    last = pd.Timestamp(end) if end is not None else rates.index.max()
    calendar = pd.date_range(rates.index.min(), last, freq="D")
    return rates.reindex(calendar).ffill()


def available_currencies() -> pd.DataFrame:
    """Every currency EXR publishes, with its name and how it is quoted.

    One row per currency: code, name, units (1 or 100, the number of units the
    published quote covers) and the latest rate per single unit. Handy for a
    dropdown, and it documents itself - the units column is where the per-100
    currencies become visible. 39 currencies as of November 2026, 24 of them
    quoted per 100.

    The date column is per row, not shared: lastNObservations counts back
    within each series separately, so a retired currency keeps its final date.
    BGN stops at 2025-12-31, the day before Bulgaria adopted the euro.

    The two trade-weighted indices are dropped; they share the shape of a
    currency series but are index levels rather than prices.
    """
    raw = _fetch_csv([], lastNObservations="1")
    table = pd.DataFrame(
        {
            "currency": raw["BASE_CUR"],
            "name": raw["Base Currency"],
            "units": 10 ** raw["UNIT_MULT"],
            "rate": raw["OBS_VALUE"] / 10.0 ** raw["UNIT_MULT"],
            "date": pd.to_datetime(raw["TIME_PERIOD"]),
        }
    )
    table = table[~table["currency"].isin(NON_CURRENCY_CODES)]
    return table.sort_values("currency").reset_index(drop=True)
