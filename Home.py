"""Entry point: the theme, the menu, and nothing else.

Up to part 3 this file was the front page, and Streamlit built the menu by
listing the files in `pages/`. That gave a flat list in filename order, which
is why the pages were called `1_Reservoirs`, `2_Power_flow` and so on - the
numbers existed only to force an order.

Part 4 has ten pages, and a flat list of ten is not a menu anyone reads. So the
pages moved to `views/` (a plain folder, not one Streamlit treats specially)
and the menu is built explicitly with `st.navigation`, grouped by what the page
is *for*:

    Start      where you choose what to look at
    Data       one page per source: reservoirs, power, weather, currency
    Analysis   what we do to the data: outliers, decomposition, correlation,
               forecast
    Info       sources and limitations

The grouping is by task rather than by data source, because that is the order
the work actually happens in: pick an area on the map, look at the raw series,
then analyse it. The numeric filename prefixes are gone, since order is now
decided here instead of by the alphabet.

`st.set_page_config` may only be called once per app, and it has to be in this
file - the pages themselves must not call it any more.
"""

import streamlit as st

from modules import theme

st.set_page_config(
    page_title="Norwegian reservoirs - IND320",
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Registers the Plotly template and makes it the default, so every page can
# build a plain figure and still get the project's colours.
theme.install()

PAGES = {
    "Start": [
        st.Page("views/home.py", title="Home", icon=":material/home:", default=True),
        st.Page("views/map.py", title="Map", icon=":material/map:"),
    ],
    "Data": [
        st.Page("views/reservoirs.py", title="Reservoirs", icon=":material/water_drop:"),
        st.Page("views/power_flow.py", title="Power flow", icon=":material/bolt:"),
        st.Page("views/weather.py", title="Weather", icon=":material/rainy:"),
        st.Page("views/currency.py", title="Currency", icon=":material/currency_exchange:"),
    ],
    "Analysis": [
        st.Page("views/outliers.py", title="Outliers", icon=":material/scatter_plot:"),
        st.Page("views/decomposition.py", title="Decomposition",
                icon=":material/stacked_line_chart:"),
        st.Page("views/correlation.py", title="Correlation", icon=":material/compare_arrows:"),
        st.Page("views/forecast.py", title="Forecast", icon=":material/trending_up:"),
    ],
    "Info": [
        st.Page("views/about.py", title="About", icon=":material/info:"),
    ],
}

page = st.navigation(PAGES)

# Which group the current page belongs to, so the sidebar can say so. Streamlit
# renders the group headings but does not mark which one is active, and with
# four groups that is a real question when you land on a page from a link.
GROUP_OF = {p.title: group for group, pages in PAGES.items() for p in pages}
GROUP_COLOUR = {
    "Start": theme.DEEP,
    "Data": theme.TEAL,
    "Analysis": theme.AMBER,
    "Info": theme.SLATE,
}
group = GROUP_OF.get(page.title, "Start")

st.sidebar.markdown(
    f"""
    <div style="border-left:4px solid {GROUP_COLOUR[group]};padding:0.35rem 0 0.35rem 0.6rem;
                margin-bottom:0.75rem;">
      <div style="font-size:0.72rem;letter-spacing:0.08em;text-transform:uppercase;
                  color:{theme.SLATE};">{group}</div>
      <div style="font-size:1.0rem;font-weight:600;color:{theme.INK};">{page.title}</div>
    </div>
    """,
    unsafe_allow_html=True,
)

page.run()

st.sidebar.divider()
st.sidebar.caption(
    "IND320 - Data to decision, autumn 2026. Reservoir levels from NVE, "
    "cross-border flows from ENTSO-E, weather from Open-Meteo and exchange "
    "rates from Norges Bank."
)
