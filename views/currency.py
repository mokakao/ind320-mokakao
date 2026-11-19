"""Exchange rates from Norges Bank.

New in part 4, and the fourth source in the project. It belongs here because
Norwegian hydropower is sold across borders: the cables on the Power flow page
carry electricity priced in euro, so what a full reservoir is worth in kroner
depends on the exchange rate as much as on the water.

Two details about this source that the plots have to respect:

* **Norges Bank does not publish every day.** No weekends, and no Norwegian
  public holidays either - 2025 had 261 weekdays and only 251 fixings. The raw
  series therefore has gaps that are not missing data, they are days on which
  no rate existed. The "carry forward" toggle below fills them the only honest
  way: the last rate fixed stays in force until the next one.
* **Rates are quoted per unit of foreign currency**, after `modules.currency`
  divides out the `UNIT_MULT` field. Norges Bank quotes 24 of its 39 currencies
  per hundred units, so a raw SEK figure of 95.16 is 0.9516 kroner per krona.
  EUR and USD are both quoted per unit, which is exactly why the bug would have
  gone unnoticed in this project.
"""

import datetime as dt

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from modules import currency, theme
from utils import load_rates

st.title(":material/currency_exchange: Currency")

st.markdown(
    "Daily exchange rates against the krone, from the "
    "[Norges Bank API](https://data.norges-bank.no/). "
    "Euro and dollar are shown by default; the others are there because the "
    "same function fetches any of them."
)

# --- Controls --------------------------------------------------------------

today = dt.date.today()
left, middle, right = st.columns([2, 2, 2])

with left:
    years_back = st.select_slider(
        "History", options=[1, 2, 3, 5, 10, 20], value=3,
        format_func=lambda y: f"{y} year" if y == 1 else f"{y} years",
    )
with middle:
    chosen = st.multiselect(
        "Currencies", options=["EUR", "USD", "GBP", "SEK", "DKK", "CHF", "JPY"],
        default=["EUR", "USD"],
        help="Norges Bank publishes 39; these are the ones most relevant to Norwegian power trade.",
    )
with right:
    carry = st.toggle(
        "Carry rates forward", value=True,
        help="Fill weekends and holidays with the last rate fixed, instead of leaving gaps",
    )

if not chosen:
    st.info("Pick at least one currency.")
    st.stop()

start = (today - dt.timedelta(days=365 * years_back + 10)).isoformat()
rates = load_rates(start, today.isoformat(), tuple(chosen))

if rates.empty:
    st.warning("Norges Bank returned nothing for that range.")
    st.stop()

shown = currency.to_daily(rates, end=today.isoformat()) if carry else rates

# --- Where it stands now ---------------------------------------------------

latest = rates.dropna(how="all").iloc[-1]
latest_date = rates.dropna(how="all").index[-1]
year_ago = rates.loc[:latest_date - pd.Timedelta(days=365)]

columns = st.columns(len(chosen))
for column, code in zip(columns, chosen):
    value = latest.get(code)
    if pd.isna(value):
        column.metric(code, "-")
        continue
    change = None
    if not year_ago.empty and code in year_ago and not pd.isna(year_ago[code].iloc[-1]):
        change = (value - year_ago[code].iloc[-1]) / year_ago[code].iloc[-1]
    column.metric(
        f"{code}/NOK", f"{value:.4f}",
        delta=f"{change:+.1%} in a year" if change is not None else None,
        delta_color="inverse",   # a rising number means a weaker krone
        help="Kroner for one unit of the currency",
    )

st.caption(
    f"Last fixing {latest_date:%A %d %B %Y}. A rising rate means the krone is "
    "weaker, which is why the year-on-year arrow is inverted here."
)

# --- The series ------------------------------------------------------------

absolute, indexed = st.tabs(["Rates", "Indexed"])

with absolute:
    figure = px.line(shown)
    theme.apply(figure, title="Kroner per unit", x="Date", y="NOK", height=430)
    figure.update_xaxes(rangeslider=dict(visible=True, thickness=0.06))
    st.plotly_chart(figure, width="stretch")

    if not carry:
        gaps = len(pd.date_range(shown.index[0], shown.index[-1])) - len(shown)
        st.caption(
            f"{len(shown)} fixings across {len(pd.date_range(shown.index[0], shown.index[-1]))} "
            f"calendar days - {gaps} days with no rate at all."
        )

with indexed:
    st.markdown(
        "Currencies quoted per unit are not comparable in kroner - a euro is "
        "worth about eleven kroner and a yen about seven øre, so on one axis "
        "the yen is a flat line at the bottom. Setting each series to 100 at "
        "the start of the period compares the *movements* instead."
    )
    base = shown.apply(lambda s: s / s.dropna().iloc[0] * 100 if s.notna().any() else s)
    figure = px.line(base)
    theme.apply(figure, title="Indexed to 100 at the start of the period",
                x="Date", y="Index", height=430)
    figure.add_hline(y=100, line=dict(color=theme.SLATE, width=1, dash="dot"))
    st.plotly_chart(figure, width="stretch")

# --- What the API actually returns ------------------------------------------

with st.expander("What the API returns, and the two traps in it"):
    st.markdown(
        """
The request is a single SDMX URL, with the series key `FREQ.BASE.QUOTE.TENOR`:

```
https://data.norges-bank.no/api/data/EXR/B.EUR+USD.NOK.SP
    ?startPeriod=...&endPeriod=...&format=csv&locale=en
```

`format=csv` rather than the JSON, because the SDMX-JSON nests observations
under positional keys - a series called `"0:0:0:0"` holding `{"0": ["11.3529"]}`
- and you have to walk the `structure` block to learn that the first `0` means
EUR and the inner one means 2 January. The CSV spells every dimension out on
every row.

Two things in that CSV will bite anyone who writes this quickly:

1. **`locale` must be pinned to `en`.** The default Norwegian locale returns a
   decimal comma, `11,7173`, which pandas reads as text.
2. **The value column uses a comma thousands separator.** A Swiss franc arrives
   as `"1,140.68"`, and one such row turns the whole column into strings. EUR
   and USD never trigger it, so it only appears the day someone adds CHF.

`FREQ=B` is business daily. There is no `FREQ=D`; asking for one returns an
empty result rather than an error.
"""
    )

with st.expander("All 39 currencies Norges Bank publishes"):
    if st.button("Fetch the list", icon=":material/list:"):
        table = currency.available_currencies()
        st.dataframe(
            table.sort_values("currency"), hide_index=True, width="stretch",
            column_config={
                "units": st.column_config.NumberColumn(
                    "Quoted per", help="1 or 100 units of the foreign currency"
                ),
                "rate": st.column_config.NumberColumn("NOK per unit", format="%.4f"),
            },
        )
        st.caption(
            "The rows do not share a date: each series is asked for its own last "
            "observation, so a retired currency keeps its final fixing. BGN ends "
            "at 31 December 2025, the day before Bulgaria adopted the euro."
        )
