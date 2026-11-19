# Timezones across the four data sources

Four sources feed this dashboard, and not one of them hands over a timestamp that says what
timezone it is in. Every single one is a naive string. That is the whole problem: nothing fails,
nothing raises, and a join on the label looks perfectly healthy while being an hour out.

What follows is what the data actually say, checked against the live APIs on 15 November 2026,
not against documentation.

---

## NVE Magasinstatistikk

`GET https://biapi.nve.no/magasinstatistikk/api/Magasinstatistikk/HentOffentligData` returned
14 958 rows. One row, raw, before anything touches it:

```json
{
  "dato_Id": "2020-11-15",
  "omrType": "EL",
  "omrnr": 1,
  "iso_aar": 2020,
  "iso_uke": 46,
  "fyllingsgrad": 0.97436064,
  "neste_Publiseringsdato": "2020-11-25T13:00:00"
}
```

`dato_Id` is a bare date. No time, no `Z`, no offset — and that holds for the whole dataset: zero
of the 14 958 values contain a `Z` or a `+hh:mm`. After `pd.to_datetime` the column is
`datetime64[us]` with `.dt.tz` of `None`, so it is naive midnight.

The useful discovery is which day of the week it is. Every one of the 14 958 dates is a **Sunday**
(`dt.dayofweek` is 6 for all of them, `isocalendar().weekday` is 7 for all of them), and `iso_uke`
always equals `date.isocalendar().week`:

```
2026-10-11 -> iso 2026 41 7 | column iso_year 2026 iso_week 41
2026-11-08 -> iso 2026 45 7 | column iso_year 2026 iso_week 45
```

So the date is the **last** day of the ISO week being reported, not the first. A row dated
2026-11-08 describes Monday 2 November through Sunday 8 November. Consecutive dates for NO/0 are
1661 steps of exactly 7 days with no exceptions, which is what you expect from a date-only series:
DST cannot disturb it because there is no clock in it.

`neste_Publiseringsdato` is a naive local wall clock — `"2020-11-25T13:00:00"`, always 13:00, and
3591 of the 3636 real stamps fall on a Wednesday. That is NVE's publishing routine, Wednesday
afternoon Norwegian time, and it is the only place in this source where a time of day appears at
all. It is metadata about publication, not about measurement.

One side finding worth acting on: the other 11 322 rows carry the placeholder
`"0001-01-01T00:00:00"`, and on pandas 3.0.5 that parses to `Timestamp('1-01-01 00:00:00')`, not
`NaT` — the NaT count across the whole column is 0. `modules/nve.py` says in its docstring that
the junk becomes NaT, which was true on pandas 2 but is not any more. A year-1 timestamp sitting in
a datetime column will trip over any `tz_localize` applied to it later.

**Verdict: naive date, Norwegian calendar, labelled with the Sunday that closes the ISO week.**

---

## ENTSO-E cross-border flows

This one cannot be re-downloaded without the token and the half-hour wait, so part of it is read
out of the code and marked as inferred. The parts that are observed come from the real cached
download in `data/crossborder_flows.parquet`.

**Inferred, from entsoe-py 0.8.1.** `query_crossborder_flows` ends with
`ts = ts.tz_convert(area_from.tz)` and its docstring says "Result will be in the timezone of the
origin country". So the series arrives **timezone-aware**, in the zone of whichever area was named
first in the call. The zones the library attaches:

```
NO_2   tz=Europe/Oslo
DK_1   tz=Europe/Copenhagen
DE_LU  tz=Europe/Berlin
GB     tz=Europe/London
```

The six series in `entsoe_flows.CONNECTIONS` therefore arrive in four different timezones. The
three `export` series are Europe/Oslo. The Denmark and Germany `import` series are
Copenhagen/Berlin, which share Oslo's offset, so they happen to be harmless. The **England import
series arrives in Europe/London, one hour behind the other five all year round.**

`download()` gets this right, and it is the only line keeping it right:

```python
flows["timestamp"] = pd.to_datetime(flows["timestamp"], utc=True).dt.tz_localize(None)
```

`utc=True` converts each series to UTC *before* the zone is dropped. A bare `.dt.tz_localize(None)`
would have stored the North Sea Link import an hour away from everything else.

**Observed, in the parquet.** 394 980 rows, `timestamp` is `datetime64[us]` with `.dt.tz` of
`None`, spanning `2024-10-12 22:00:00` to `2026-10-12 21:45:00`.

That start time is the proof the stored numbers are UTC. `download()` asks for
`end = pd.Timestamp.now(tz="Europe/Oslo").normalize()`, i.e. midnight Oslo on 13 October, and
midnight Oslo on 2024-10-13 is `2024-10-12 22:00:00+00:00`. A series that begins at 22:00 the
previous evening is a UTC series, not an Oslo one.

Two more checks on the same file:

- 0 duplicated timestamps anywhere in it.
- The window 2025-10-26 00:00 to 03:00 holds exactly 13 quarter-hours. On a Norwegian wall clock
  that autumn-switch window holds 17, because 02:00–03:00 happens twice. UTC again.

Unrelated to timezones but in the same file and worth knowing before resampling it: the resolution
changes partway through. Last hourly step `2025-04-08 00:00:00`, first 15-minute step
`2025-04-08 00:15:00`. Anything that assumes one step size across the whole series is wrong.

**Inferred, downstream.** `storage.write_flows` re-attaches UTC with `.dt.tz_localize("UTC")`
before handing rows to Spark — the comment there about 42 rows vanishing into the repeated 02:00
hour is exactly this problem caught once already. Spark runs with
`spark.sql.session.timeZone = UTC`, and Cassandra's `timestamp` type is epoch milliseconds, so the
instants survive. `hourly_from_spark` then does `pd.to_datetime(...)` on the collected rows, which
drops the zone again, and `write_hourly_to_mongo` inserts those naive values.

That last hop can be checked offline, without Atlas, because the encoding is local. BSON has one
datetime type, epoch milliseconds:

```
naive      in -> 2026-07-15 12:00:00
           decoded (default tz_aware=False): 2026-07-15 12:00:00  tzinfo=None
aware UTC  in -> 2026-07-15 12:00:00+00:00
           decoded (default tz_aware=False): 2026-07-15 12:00:00  tzinfo=None
same wire bytes for naive and aware? True
```

A naive datetime is encoded as if it were UTC, and `mongo_collection()` does not pass `tz_aware`,
so it comes back naive and unchanged. The naive-UTC convention therefore survives the round trip —
but nothing in the database records that it is the convention. Had the same wall clock been tagged
Europe/Oslo it would have landed two hours earlier (`2026-07-15 10:00:00+00:00`), in the same
column, indistinguishable afterwards.

**Verdict: naive UTC on disk and in MongoDB, by convention only, after a correct conversion from
four different source zones.**

---

## Open-Meteo ERA5 archive

This is where the real surprise is.

The labels are bare local wall clock with no zone marker of any kind — `'2026-03-26T00:00'`,
no `Z`, no `+01:00`. You cannot tell from the string which zone it is; only the response envelope
says. With no `timezone` parameter at all:

```
meta: {"utc_offset_seconds": 0, "timezone": "GMT", "timezone_abbreviation": "GMT", ...}
first: ['2026-03-28T00:00', '2026-03-28T01:00', '2026-03-28T02:00']
```

So the default is already UTC, and the `"timezone": "UTC"` that `modules/weather.py` sends returns
a byte-identical response. It is belt-and-braces, not a correction.

Now ask for Norwegian local time instead, across four seasons:

```
2026-01-15: utc_offset_seconds= 3600  abbrev=GMT+1
2026-04-15: utc_offset_seconds= 3600  abbrev=GMT+1
2026-07-01: utc_offset_seconds= 3600  abbrev=GMT+1
2026-10-01: utc_offset_seconds= 3600  abbrev=GMT+1
```

`+1` in July. The IANA database on this machine (tzdata 2026c) says Oslo is CEST, `+02:00`, on
2026-07-01. **The archive endpoint applies the standard-time offset all year and never applies
summer time.** `timezone=auto` behaves identically, since it resolves to Europe/Oslo.

Proof that it is a fixed offset rather than a zone the server got slightly wrong: pull
`2026-03-26` to `2026-04-02`, a range that crosses the 29 March switch, twice — once as UTC, once
as Europe/Oslo — and look for the lag between them.

```
lag 1h over all 191 overlapping hours: identical=True  mismatches=0
lag 2h over all 190 overlapping hours: identical=False mismatches=174
```

One constant lag fits the entire range. If DST were being applied the lag would change from 1 to 2
partway through. It does not.

The convenient side of this is that the grid stays regular: `2026-03-29` returns 24 labels and
`2026-10-25` returns 24 labels even with `timezone=Europe/Oslo`, so there are no duplicate and no
missing labels. The inconvenient side is that one of those labels is `2026-03-29T02:00`, an hour
that does not exist on a Norwegian clock. The "local time" this API offers is simply the wrong hour
in summer.

What it costs, concretely — the same two days pulled twice and joined on the naive label:

```
                     temp[UTC]  temp[Europe/Oslo]  difference
2026-07-01 00:00:00        3.9                4.1         0.2
2026-07-01 01:00:00        3.4                3.9         0.5
2026-07-01 02:00:00        3.2                3.4         0.2
2026-07-01 03:00:00        3.2                3.2         0.0
2026-07-01 04:00:00        3.6                3.2        -0.4
2026-07-01 05:00:00        4.3                3.6        -0.7
2026-07-01 06:00:00        5.9                4.3        -1.6
2026-07-01 07:00:00        6.6                5.9        -0.7

mean |difference| 0.49 degC   max 1.6 degC
Oslo series shifted back 1 label == UTC series? True
```

Half a degree of mean error and 1.6 degrees at the morning ramp, at one grid cell on a quiet summer
day, purely from the label. Nothing in the output hints at it.

`weather.py` then does `pd.to_datetime(hourly["time"])`, giving `datetime64[us]` with `tz: None`,
and the `utc_offset_seconds` from the envelope is discarded. That is safe only because the request
asked for UTC. Confirmed in the real cache `data/no3_2024_hourly.parquet`: 8784 unique hours for
2024, every step exactly 1 h, 24 hours on both 2024-03-31 and 2024-10-27 — no 23- or 25-hour day,
so UTC it is.

**Verdict: naive UTC, and the local-time option on this endpoint is a fixed +1 that is wrong from
late March to late October. Keep asking for UTC.**

---

## Norges Bank

`GET https://data.norges-bank.no/api/data/EXR/B.EUR.NOK.SP?startPeriod=2026-10-20&endPeriod=2026-11-02&format=sdmx-json`

```
2026-10-20 -> 10.5245
2026-10-21 -> 10.512
2026-10-22 -> 10.488
2026-10-23 -> 10.4665
2026-10-26 -> 10.4545
2026-10-27 -> 10.3885
2026-10-28 -> 10.3475
2026-10-29 -> 10.3315
2026-10-30 -> 10.312
2026-11-02 -> 10.3775
```

Bare dates again. The SDMX envelope does spell each period out as an interval, still with no
offset:

```json
{ "start": "2026-10-23T00:00:00", "end": "2026-10-23T23:59:59", "id": "2026-10-23" }
```

That interval is misleading, and the CSV flavour of the same query says why. It carries a
`COLLECTION` attribute the JSON hides:

```
...;COLLECTION;Collection Indicator;TIME_PERIOD;OBS_VALUE
...;C;ECB concertation time 14:15 CET;2026-10-26;10.4545
```

The rate is a **single snapshot at 14:15 Central European Time**, not an average over the day. The
date is a filing label, not the interval the SDMX structure claims.

One honest ambiguity remains, and the data cannot settle it: the attribute says "CET" literally,
but the ECB concertation follows the Frankfurt clock, which is CEST in summer. Read strictly as
`+01:00` the instant is 13:15 UTC year-round; read as Frankfurt/Oslo wall clock it is 13:15 UTC in
winter and 12:15 UTC in summer. Nothing in any response carries an offset to decide it. For a daily
FX rate joined to hourly power data an hour either way is immaterial, but it is an hour of real
uncertainty rather than rounding, and it should be stated rather than quietly resolved.

`FREQ` is `B`, business days, and the holes are the bigger practical issue. Across those 14
calendar days there are 10 observations; `2026-10-24`, `2026-10-25`, `2026-10-31` and `2026-11-01`
have no rate at all — two weekends. Reindexed onto the 336 hours of the window, 10 hours match and
326 are NaN until something fills them.

`meta.prepared` is `"2026-11-15T17:26:42"` — naive as well, for completeness.

**Verdict: naive date standing in for a 14:15 CET snapshot, business days only.**

---

## Where a join on a common index silently goes wrong

All four sources produce naive timestamps, so pandas will join any pair of them without a murmur.
Six specific ways that bites:

**1. ERA5 pulled as local time, against the stored flows.** If `weather.py` were ever changed to
`timezone=Europe/Oslo`, the weather would sit one hour late against the flows *all year* — not one
hour in winter and two in summer, because Open-Meteo's offset is fixed. In winter it is the correct
Norwegian clock and still an hour off UTC; in summer it is neither one nor the other. Observed cost
at one cell: 0.49 degC mean, 1.6 degC peak.

**2. Naive UTC against a true Europe/Oslo series.** Anything built with `tz_localize("Europe/Oslo")`
and then flattened meets the flows one hour away in winter and two in summer:

```
winter: '2026-01-15 12:00' as UTC minus the same string as Oslo = 0 days 01:00:00
summer: '2026-07-15 12:00' as UTC minus the same string as Oslo = 0 days 02:00:00
```

The gap *changes size* at the two switch dates, so no constant shift repairs a mixed series. A join
that looks one hour out in January is two hours out in July, which is exactly the kind of bug that
gets diagnosed as "the model is bad in summer".

**3. England against the other five cables, inside ENTSO-E.** Europe/London is an hour behind
Europe/Oslo in both seasons:

```
2026-01-15: London 12:00  Oslo 13:00
2026-07-15: London 13:00  Oslo 14:00
```

If the `utc=True` ever comes off the conversion in `download()`, the North Sea Link import lands an
hour from its own export series and the net balance on that cable is wrong for every hour of the
two years. This is the one that would survive review, because five of six series would still agree
with each other.

**4. Any DST-aware index against the regular grid the rest of the project assumes.** On an Oslo
wall clock the week ending 2026-03-29 is **167 hours** and the week ending 2026-10-25 is **169
hours**; on UTC both are 168, and no week in the range deviates. So a weekly mean on a local clock
divides by a different number of hours twice a year. Worse, an hourly `Europe/Oslo` index has a
duplicated label (02:00 twice on 25 October) and a missing one (02:00 absent on 29 March), which
breaks `reindex`, breaks any `set_index` that assumes uniqueness, and drops or doubles a row
without complaint. Part 3's DCT filter and the LOF detector both assume an evenly spaced series.
A local-time index is not one.

**5. NVE weekly against hourly data — the quietest failure of the six.** NVE labels each week with
the Sunday that ends it, and `pandas.resample("W")` also labels on Sunday, so the two label sets
match exactly:

```
resample('W') labels: ['2026-01-04', '2026-01-11', '2026-01-18', '2026-01-25', '2026-02-01']
NVE 2026 dates:       ['2026-01-04 Sunday', '2026-01-11 Sunday', '2026-01-18 Sunday', ...]
every NVE date is a resample('W') label? True
```

They are not the same weeks. `resample("W")` defaults to `closed="right", label="right"`, so the
bin labelled 2026-01-11 covers Sunday 2026-01-04 01:00 through Sunday 2026-01-11 00:00 — shifted a
full day early, with the 23 hours of Sunday that NVE counts sitting in the *next* bin. Both sides
hold 168 hours, both agree on the label, and only the contents disagree. Nothing anywhere looks
wrong.

**6. Norges Bank against anything hourly.** Four of fourteen calendar days have no rate; a plain
`reindex` onto hourly leaves 326 of 336 hours empty. `ffill` fills them, but carrying Friday's rate
through to Monday morning is a modelling choice, not a timezone fix, and it should be visible in
the code rather than buried in a chained call.

---

## What to do

**Convention: every timestamp is timezone-aware UTC from the moment it is parsed until the moment
it is drawn.** Convert to Europe/Oslo in the app layer only, for axis labels and tooltips, never in
a module that returns data.

Why UTC rather than Europe/Oslo:

- Three of the four sources already are UTC or can be asked for it, and both parquet caches,
  Cassandra and MongoDB already hold UTC instants. Choosing Oslo would mean rewriting stored data,
  not just readers.
- UTC has no 23- or 25-hour day, so the hourly index stays complete, unique and evenly spaced. That
  is a precondition for the DCT filter and the LOF detector from part 3, and for `resample` and
  `reindex` not to quietly drop or double a row twice a year.
- Open-Meteo's archive API cannot return a correct Norwegian clock at all — its Europe/Oslo is a
  fixed `+1`. UTC is the only honest option on that source, which settles it for the others.

And **aware, not naive**. Naive is what let the England series, a local ERA5 pull and NVE's Sunday
all look joinable when they are not. An aware index makes pandas refuse the join instead of
returning a shifted one.

One line per source, with the values observed above:

```python
# NVE: a Norwegian calendar date at midnight
df["date"] = pd.to_datetime(df["date"]).dt.tz_localize("Europe/Oslo").dt.tz_convert("UTC")
#   '2026-01-04' -> '2026-01-04 00:00:00+01:00' -> '2026-01-03 23:00:00+00:00'

# ENTSO-E, from the parquet cache or MongoDB: already UTC, so just say so
flows["timestamp"] = flows["timestamp"].dt.tz_localize("UTC")
#   '2024-10-12 22:00:00' -> '2024-10-12 22:00:00+00:00'

# Open-Meteo: keep timezone=UTC in the request, then label what comes back
frame["time"] = pd.to_datetime(hourly["time"]).tz_localize("UTC")
#   '2026-07-01T12:00' -> '2026-07-01 12:00:00+00:00'

# Norges Bank: a date plus the ECB concertation time on the Frankfurt clock
idx = pd.to_datetime(rates.index).tz_localize("Europe/Oslo") + pd.Timedelta(hours=14, minutes=15)
rates.index = idx.tz_convert("UTC")
#   '2026-10-20' -> '2026-10-20 14:15:00+02:00' -> '2026-10-20 12:15:00+00:00'
```

Two places where UTC alone is not enough:

**Weekly aggregation against NVE has to happen on the Norwegian calendar**, because that is what
NVE's week is. Convert to Oslo, bin the true ISO week, then relabel with NVE's Sunday:

```python
weekly = (series.tz_convert("Europe/Oslo")
                .resample("W-MON", closed="left", label="left").mean())
weekly.index = weekly.index + pd.Timedelta(days=6)   # Monday label -> NVE's Sunday
```

This reproduces all 45 of NVE's 2026 dates, and every bin holds 168 hours except the two DST weeks
— 167 ending 29 March, 169 ending 25 October — which is right, those weeks really are that long in
Norway. `resample("W")` with its defaults gives the same labels and the wrong bins.
`groupby` on `index.isocalendar()` says the same thing and is harder to get wrong:

```python
iso = series.index.tz_convert("Europe/Oslo").isocalendar()
series.groupby([iso["year"].to_numpy(), iso["week"].to_numpy()]).mean()
```

**Norges Bank should be aligned with `merge_asof(..., direction="backward")`**, not
`reindex().ffill()`. Both carry Friday's rate into Monday, but `merge_asof` leaves the decision
visible in the code and lets a tolerance cap how stale a rate may get.

Finally, a small cleanup that belongs with this work: `modules/nve.py` claims the
`0001-01-01T00:00:00` publication placeholder becomes `NaT`. On pandas 3.0.5 it parses to
`Timestamp('1-01-01 00:00:00')` and the NaT count is 0, so the placeholder should be replaced
explicitly rather than left to `errors="coerce"`. As it stands, applying the `tz_localize` above to
that column would trip over a year-1 timestamp.

---

## How this was checked

- NVE: `HentOffentligData`, 14 958 rows, raw JSON inspected before and after `pd.to_datetime`;
  weekday and ISO-week agreement checked on all rows.
- ENTSO-E: `modules/entsoe_flows.py`, `modules/storage.py` and entsoe-py 0.8.1 source read for the
  conversion and the `Area` timezone table; `data/crossborder_flows.parquet` (394 980 real rows)
  inspected for dtype, range, duplicates and the autumn switch; the BSON layer tested offline with
  pymongo 4.17.0. Cassandra and MongoDB Atlas were not reachable, so everything past
  `write_flows` is inference from the code plus the local BSON test.
- Open-Meteo: eight live calls to `archive-api.open-meteo.com/v1/archive` at 60.5N 7.5E with
  `timezone` unset, `UTC`, `Europe/Oslo` and `auto`, across January, March/April, July and October
  2026; offsets compared against tzdata 2026c; `data/no3_2024_hourly.parquet` checked for
  23/25-hour days.
- Norges Bank: live `EXR/B.EUR.NOK.SP` queries for 2026-10-20 to 2026-11-02 in both `sdmx-json`
  and `csv`, the latter being where the `COLLECTION` attribute appears.
- pandas 3.0.5, Python 3.12, `/Users/moa/Desktop/ind320/kurs/.venv`.
