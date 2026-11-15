"""One visual identity for the whole app.

Part 3 drew everything with matplotlib defaults, which meant every page had its
own accidental look: different blues, different fonts, a white plot background
sitting on Streamlit's own. Part 4 replaces all of it with Plotly, and the
point of this module is that the replacement is a *decision* made once rather
than a style repeated in nine files.

The palette is built around water, since that is what the project is about:
deep blue for stored water, teal for flow, amber for the things that are
unusual - outliers, anomalies, forecasts. Amber is deliberately the only warm
colour, so anything warm on a plot means "look here".

Everything is registered as a Plotly template named "ind320" and set as the
default, so a plain `px.line(...)` already comes out themed and a page only has
to call `apply()` when it wants the axis titles tidied as well.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

# --- The palette -----------------------------------------------------------

DEEP = "#14425f"       # stored water, the main series
WATER = "#1b7fa8"      # second series
TEAL = "#2aa198"       # third series, flows
SKY = "#7fc4dd"        # fourth series, light fill
SLATE = "#5c7a8a"      # fifth series, muted
AMBER = "#e08a1e"      # the exception: outliers, anomalies, forecasts
RUST = "#b4471f"       # the hard exception: limits exceeded, errors
INK = "#1d2a33"        # text
PAPER = "#f7fafc"      # plot background
GRID = "#d9e3ea"       # grid lines

# The order Plotly walks through when a plot has several series. Deep first, so
# a single-series plot is the project's main blue.
COLORWAY = [DEEP, TEAL, AMBER, SKY, SLATE, WATER, RUST]

# Continuous scale for the map. Light where reservoirs are empty, deep where
# they are full, which is the way round people expect for water.
FILL_SCALE = [
    [0.0, "#f2f8fb"],
    [0.25, SKY],
    [0.5, WATER],
    [0.75, DEEP],
    [1.0, "#0b2a3d"],
]

# Diverging scale, for anything centred on zero: correlation, week-on-week
# change. Rust for negative, blue for positive, pale in the middle.
DIVERGING = [
    [0.0, RUST],
    [0.25, "#dd9a7a"],
    [0.5, "#f2f0ec"],
    [0.75, SKY],
    [1.0, DEEP],
]

TEMPLATE_NAME = "ind320"


def _template() -> go.layout.Template:
    """Build the Plotly template.

    Kept as a function rather than a literal so the colours above are the only
    place a value is written down.
    """
    return go.layout.Template(
        layout=dict(
            colorway=COLORWAY,
            font=dict(
                family="Source Sans Pro, -apple-system, Segoe UI, sans-serif",
                size=13,
                color=INK,
            ),
            # The title sits in the figure's own top margin (yref defaults to
            # "container"), above the legend, which sits just above the plot
            # area. Without pinning the title here the two land on the same
            # line and overlap as soon as a plot has more than one series.
            title=dict(font=dict(size=17, color=INK), x=0.01, xanchor="left",
                       y=0.97, yanchor="top"),
            paper_bgcolor="rgba(0,0,0,0)",   # let the Streamlit page show through
            plot_bgcolor=PAPER,
            colorscale=dict(sequential=FILL_SCALE, diverging=DIVERGING),
            xaxis=dict(
                gridcolor=GRID, linecolor=GRID, zerolinecolor=GRID,
                ticks="outside", tickcolor=GRID, automargin=True,
            ),
            yaxis=dict(
                gridcolor=GRID, linecolor=GRID, zerolinecolor=GRID,
                ticks="outside", tickcolor=GRID, automargin=True,
            ),
            legend=dict(
                orientation="h", yanchor="bottom", y=1.02,
                xanchor="left", x=0, title_text="",
            ),
            # Tall top margin: it has to hold the title and the horizontal
            # legend stacked, not just the title.
            margin=dict(l=60, r=20, t=85, b=50),
            hovermode="x unified",
            hoverlabel=dict(bgcolor="white", font_size=12),
        )
    )


def install() -> None:
    """Register the template and make it the default.

    Called once from the app entry point and once at the top of the notebook.
    Safe to call twice - registering the same name again just overwrites it.
    """
    pio.templates[TEMPLATE_NAME] = _template()
    pio.templates.default = TEMPLATE_NAME


def apply(fig: go.Figure, title: str = "", x: str = "", y: str = "",
          height: int = 420, legend: bool = True) -> go.Figure:
    """Finish a figure: titles, height, and the shared legend placement.

    Plotly's own defaults put the legend on the right, which eats a third of
    the width on a wide Streamlit layout. Here it goes above the plot instead,
    horizontally, where it costs one line.
    """
    fig.update_layout(
        title=title or None,
        xaxis_title=x or None,
        yaxis_title=y or None,
        height=height,
        showlegend=legend,
        # plotly.express names the legend after the column it melted on, which
        # is almost always "variable" and never tells the reader anything.
        legend_title_text="",
    )
    return fig


def percent_axis(fig: go.Figure, axis: str = "y") -> go.Figure:
    """Format an axis as percentages.

    Fill level is a share between 0 and 1 everywhere in the data, but nobody
    reads reservoir levels as 0.734 - they read them as 73 %.
    """
    fig.update_layout(**{f"{axis}axis": dict(tickformat=".0%")})
    return fig
