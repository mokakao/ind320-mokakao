"""Forecasting reservoir filling with River's online SNARIMAX.

Part 4 asks for a forecast of the coming months' filling for one region. The
input is the weekly Magasinstatistikk fill level from modules.nve: one row per
ISO week, a share of capacity. So "the coming three months" is about 13 steps,
and everything in here counts in weeks rather than months.

Three things surprised me while building this.

The seasonal orders are cheap. I expected m=52 on weekly data to be unusable,
because that is what a yearly cycle costs in a textbook seasonal ARIMA. River's
SNARIMAX does not build m features - it builds sp features and picks the lags
m, 2m, ... So m=52 with sp=2 is two extra columns, and a full fit over 312
weeks takes about 0.02 seconds. Seasonality is also where all the accuracy is:
in a 24-origin backtest on NO1 at a 13-week horizon, m=1 gives MAE 0.141 and
the seasonal orders give 0.055.

River's default regressor blows up. SNARIMAX defaults to
StandardScaler | LinearRegression, and that LinearRegression defaults to SGD at
lr=0.01, which sits right at the edge of stability for this series. With p=8,
q=4 and a long history the weights diverge and the forecast comes back as 1e145
- no exception, just nonsense in the chart. That is why learning_rate defaults
to 0.005 here, and why the result is clipped to the physical range of a fill
level. A reservoir is never negative, and 1.0 is "full", though the data does
nudge past it: the observed maximum for NO1 since 1995 is 1.0200.

m=52 is an approximation and drifts. The rows are ISO weeks, and an ISO year
has 52 or 53 of them, so "52 steps back" is not always exactly one year back.
It is close enough for an online model that keeps re-learning from recent data,
but it is wrong to call it exact.

The quantile intervals (forecast_with_intervals) work but are conservative; the
honest numbers are in that function's docstring.
"""

import time

import numpy as np
import pandas as pd
from river import linear_model, optim, preprocessing, time_series

# A fill level is a share of capacity, so anything outside this range is not a
# reservoir. Clipping to it is what stops a diverged fit from reaching the app.
FILL_RANGE = (0.0, 1.05)

# Clipping on its own does not mean the fit failed - a winter forecast that
# undershoots to -0.02 is a rounding nuisance, not a broken model. Ten times a
# full reservoir is the line where the only possible explanation is diverged
# SGD weights, and that is worth reporting separately.
DIVERGENCE_BOUND = 10.0

# Picked by running evaluate_settings over 64 order/history combinations on NO1
# with a 24-origin rolling backtest at a 13-week horizon. This was the best
# (MAE 0.0553, RMSE 0.0798); the worst seasonal one was 0.0995.
DEFAULT_ORDER = {"p": 8, "d": 1, "q": 2, "m": 52, "sp": 2, "sd": 1, "sq": 2}
DEFAULT_HISTORY_WEEKS = 312
DEFAULT_HORIZON = 13
DEFAULT_LEARNING_RATE = 0.005


def _as_series(series: pd.DataFrame | pd.Series, column: str) -> pd.Series:
    """Reduce the caller's input to one clean, sorted, gap-free float series."""
    long_format = (
        "this is still the long format with every area stacked on top of each "
        "other, so the series would be nine regions spliced together. Pick one "
        "region first, for example nve.one_area(df, 'EL', 1)."
    )

    if isinstance(series, pd.DataFrame):
        # Straight out of fetch_reservoirs the frame has a RangeIndex, so the
        # duplicate-index check below never fires and the mistake would go
        # through silently. These two columns only exist in the long format.
        if {"area_type", "area_number"} & set(series.columns):
            raise ValueError(long_format)
        if column not in series.columns:
            raise ValueError(
                f"no column {column!r} in the frame; it has {list(series.columns)}"
            )
        values = series[column]
    else:
        values = series

    if values.index.has_duplicates:
        raise ValueError(long_format)

    # NaN would poison the model silently: learn_one happily accepts it and
    # every weight downstream becomes NaN.
    return values.astype(float).sort_index().dropna()


def required_weeks(p: int, d: int, q: int, m: int, sp: int, sd: int, sq: int) -> int:
    """How many observations SNARIMAX needs before it can learn anything.

    The differencer refuses to work until it has d + m*sd past values, and the
    lag features are only complete once the longest lag is reachable. Below
    this, a fit does not fail - it just trains on far fewer rows than asked
    for, which is worth catching rather than discovering in a flat forecast.
    """
    warm_up = d + m * sd
    longest_lag = max(p, q, m * sp, m * sq)
    return warm_up + longest_lag + 1


def _regressor(learning_rate: float, l2: float, quantile: float | None):
    """The online regression model inside SNARIMAX.

    Scaling first matters more than it looks: the lag features are differenced
    fill levels, tiny numbers, while an exogenous temperature column is tens of
    degrees, and plain SGD on that mix converges badly.
    """
    return preprocessing.StandardScaler() | linear_model.LinearRegression(
        optimizer=optim.SGD(learning_rate),
        loss=optim.losses.Quantile(quantile) if quantile is not None else None,
        l2=l2,
    )


def _future_index(index: pd.Index, horizon: int) -> pd.Index:
    """Continue the index by horizon steps.

    The spacing is taken from the data rather than assumed to be 7 days, so
    this still does something sensible if a region is ever published monthly.
    The median ignores the odd gap where NVE skipped a week.
    """
    if isinstance(index, pd.DatetimeIndex):
        step = index.to_series().diff().median()
        return pd.DatetimeIndex(
            [index[-1] + step * k for k in range(1, horizon + 1)], name=index.name
        )
    return pd.Index([index[-1] + k for k in range(1, horizon + 1)], name=index.name)


def _check_numeric(frame: pd.DataFrame) -> pd.DataFrame:
    not_numeric = [c for c in frame.columns if not pd.api.types.is_numeric_dtype(frame[c])]
    if not_numeric:
        raise ValueError(f"exogenous columns must be numeric; these are not: {not_numeric}")
    return frame


def forecast(
    series: pd.DataFrame | pd.Series,
    horizon: int = DEFAULT_HORIZON,
    p: int = DEFAULT_ORDER["p"],
    d: int = DEFAULT_ORDER["d"],
    q: int = DEFAULT_ORDER["q"],
    m: int = DEFAULT_ORDER["m"],
    sp: int = DEFAULT_ORDER["sp"],
    sd: int = DEFAULT_ORDER["sd"],
    sq: int = DEFAULT_ORDER["sq"],
    history_weeks: int | None = DEFAULT_HISTORY_WEEKS,
    exogenous: pd.DataFrame | None = None,
    future_exogenous: pd.DataFrame | None = None,
    column: str = "fill_level",
    learning_rate: float = DEFAULT_LEARNING_RATE,
    l2: float = 0.0,
    quantile: float | None = None,
    clip: tuple[float, float] | None = FILL_RANGE,
) -> pd.DataFrame:
    """Predict the coming weeks' filling for one region.

    series is one region's history, either the frame from nve.one_area or a
    bare Series. p/d/q are the plain orders, m/sp/sd/sq the seasonal ones, and
    on weekly data a yearly cycle is m=52.

    history_weeks is how much of the tail to train on; None uses everything.
    Shorter is not worse here - 312 weeks (six years) beat 1040 in the
    backtest, because SGD keeps adapting and the older rows mostly get
    overwritten anyway.

    exogenous is an optional frame of extra regressors on the same index, say
    temperature and precipitation from modules.weather. Training is restricted
    to the dates present in both, so a weather series that starts later simply
    shortens the usable history. future_exogenous supplies those columns for
    the forecast weeks; whatever is missing is carried forward from the last
    training row, which is a weak assumption for weather and a reasonable one
    for a price or a currency.

    quantile swaps the squared loss for river.optim.losses.Quantile, which is
    how forecast_with_intervals gets its bands. Use that function instead of
    calling this one three times.

    Returns one row per forecast week, indexed by date, with a single
    "forecast" column. Three diagnostics ride along in .attrs: "fit_seconds",
    "clipped" (how many values had to be pulled back into the physical range,
    which is routine - a deep-winter forecast often undershoots a little past
    zero) and "diverged" (whether any raw value was non-finite or past
    DIVERGENCE_BOUND, which is not routine and means the orders or the learning
    rate have to come down).
    """
    if horizon < 1:
        raise ValueError("horizon must be at least one week")
    # Without this, history_weeks=0 would slice y.iloc[-0:] and quietly train
    # on everything, which is the opposite of what asking for zero means.
    if history_weeks is not None and history_weeks < 1:
        raise ValueError("history_weeks must be at least one week, or None for all of it")

    y = _as_series(series, column)

    exo = None
    if exogenous is not None:
        exo = _check_numeric(exogenous.sort_index())
        shared = y.index.intersection(exo.index)
        if len(shared) == 0:
            raise ValueError("the exogenous frame shares no dates with the series")
        y = y.loc[shared]
        exo = exo.loc[shared]

    train = y if history_weeks is None else y.iloc[-history_weeks:]
    needed = required_weeks(p, d, q, m, sp, sd, sq)
    if len(train) < needed:
        raise ValueError(
            f"these orders need {needed} observations before the model learns "
            f"anything, but the training window is {len(train)} weeks. Either "
            f"raise history_weeks or lower sp/sd/sq."
        )

    model = time_series.SNARIMAX(
        p=p, d=d, q=q, m=m, sp=sp, sd=sd, sq=sq,
        regressor=_regressor(learning_rate, l2, quantile),
    )

    train_exo = None if exo is None else exo.loc[train.index]
    started = time.perf_counter()
    for position, value in enumerate(train.to_numpy()):
        x = None if train_exo is None else train_exo.iloc[position].to_dict()
        model.learn_one(float(value), x=x)
    fit_seconds = time.perf_counter() - started

    future = _future_index(train.index, horizon)

    xs = None
    if exo is not None:
        wanted = exo.columns
        known = pd.DataFrame(index=future, columns=wanted, dtype=float)
        if future_exogenous is not None:
            supplied = _check_numeric(future_exogenous)
            overlap = [c for c in wanted if c in supplied.columns]
            known[overlap] = supplied.reindex(future)[overlap]
        # Anything still unknown is held at its last observed value.
        known = known.fillna(train_exo.iloc[-1])
        xs = [row.to_dict() for _, row in known.iterrows()]

    predicted = np.asarray(model.forecast(horizon=horizon, xs=xs), dtype=float)

    finite = np.isfinite(predicted)
    diverged = bool(
        (~finite).any() or (np.abs(predicted[finite]) > DIVERGENCE_BOUND).any()
    )

    clipped = 0
    if clip is not None:
        low, high = clip
        # Non-finite values come from a diverged fit, and nan_to_num sends them
        # to the nearest bound instead of leaving NaN in the chart.
        predicted = np.nan_to_num(predicted, nan=low, posinf=high, neginf=low)
        inside = np.clip(predicted, low, high)
        clipped = int((inside != predicted).sum())
        predicted = inside

    result = pd.DataFrame({"forecast": predicted}, index=future)
    result.attrs["fit_seconds"] = fit_seconds
    result.attrs["clipped"] = clipped
    result.attrs["diverged"] = diverged
    return result


def forecast_with_intervals(
    series: pd.DataFrame | pd.Series,
    horizon: int = DEFAULT_HORIZON,
    lower_quantile: float = 0.1,
    upper_quantile: float = 0.9,
    **options,
) -> pd.DataFrame:
    """Forecast plus a quantile band, the bonus task.

    Fits three SNARIMAX models on the same orders and history, differing only
    in their loss: squared error for the middle line, and
    river.optim.losses.Quantile at lower_quantile and upper_quantile for the
    edges. options takes any keyword of forecast().

    Returns lower / forecast / upper, indexed by forecast date.

    How well it actually works, measured on NO1 over 24 rolling origins with
    the default orders and a 10-90 band: 94.9 per cent of the true values land
    inside, against a nominal 80. So the band is honest in the sense that it
    does not miss, but it is too wide, and it gets worse with distance - 83 per
    cent coverage in week 1, then 100 per cent from week 8 on, where the band
    has grown to cover 0.95 of the 0-1 range and says nothing useful. The cause
    is the recursion: each step feeds its own biased prediction back in as a
    lag, so a 10th-percentile model drifts down a little further every week.
    Read the first four to six weeks and treat the far end as decoration.

    The three fits are independent, so the quantiles can in principle cross.
    They did not in testing, but the bounds are sorted on the way out anyway.
    """
    middle = forecast(series, horizon=horizon, **options)
    low = forecast(series, horizon=horizon, quantile=lower_quantile, **options)
    high = forecast(series, horizon=horizon, quantile=upper_quantile, **options)

    lower = np.minimum(low["forecast"].to_numpy(), high["forecast"].to_numpy())
    upper = np.maximum(low["forecast"].to_numpy(), high["forecast"].to_numpy())

    result = pd.DataFrame(
        {"lower": lower, "forecast": middle["forecast"].to_numpy(), "upper": upper},
        index=middle.index,
    )
    result.attrs["fit_seconds"] = sum(
        f.attrs["fit_seconds"] for f in (middle, low, high)
    )
    result.attrs["clipped"] = sum(f.attrs["clipped"] for f in (middle, low, high))
    result.attrs["diverged"] = any(f.attrs["diverged"] for f in (middle, low, high))
    return result


def evaluate_settings(
    series: pd.DataFrame | pd.Series,
    configurations: list[dict],
    horizon: int = DEFAULT_HORIZON,
    origins: int = 12,
    step: int | None = None,
    exogenous: pd.DataFrame | None = None,
    column: str = "fill_level",
    intervals: bool = False,
    lower_quantile: float = 0.1,
    upper_quantile: float = 0.9,
) -> pd.DataFrame:
    """Backtest several settings against each other and return the errors.

    Each configuration is a dict of forecast() keywords, optionally with a
    "label" to name the row. Evaluation is rolling origin: the series is cut
    short, the model is fitted on what is left, the next horizon weeks are
    predicted and compared with what really happened, and the cut moves back by
    step weeks (default: the horizon, so the test windows do not overlap).

    Returns one row per configuration sorted by MAE, with mae, rmse, the MAE of
    the first and last forecast week separately, the mean seconds per fit, how
    many predictions were clipped, and a status column. A configuration that
    cannot run - too little history for its seasonal orders - gets its error
    recorded in the status instead of raising, so one bad entry in a sweep does
    not take the whole sweep down. A status of "diverged at n of m origins"
    means SGD blew up in those windows: the MAE on that row is meaningless,
    held finite only by the clipping, and the row should be read as a failure
    rather than as a score.

    With intervals=True each row also gets the share of true values inside the
    quantile band. Note that this costs three fits per origin instead of one.

    One caveat about exogenous columns here: the backtest hands the model the
    real future values of those columns, because in a backtest they are
    already known. That is perfect foresight, which no live forecast has, so an
    exogenous configuration will look better in this table than it will in the
    app.
    """
    y = _as_series(series, column)
    step = horizon if step is None else step
    rows = []

    for number, configuration in enumerate(configurations, start=1):
        options = {k: v for k, v in configuration.items() if k != "label"}
        label = configuration.get("label", f"config {number}")

        errors: list[np.ndarray] = []
        inside: list[np.ndarray] = []
        seconds: list[float] = []
        clipped = 0
        diverged = 0
        status = "ok"

        for k in range(origins):
            end = len(y) - horizon - k * step
            if end < 1:
                break
            past, truth = y.iloc[:end], y.iloc[end : end + horizon]

            try:
                if intervals:
                    predicted = forecast_with_intervals(
                        past,
                        horizon=horizon,
                        lower_quantile=lower_quantile,
                        upper_quantile=upper_quantile,
                        exogenous=exogenous,
                        future_exogenous=exogenous,
                        **options,
                    )
                    inside.append(
                        (truth.to_numpy() >= predicted["lower"].to_numpy())
                        & (truth.to_numpy() <= predicted["upper"].to_numpy())
                    )
                else:
                    predicted = forecast(
                        past,
                        horizon=horizon,
                        exogenous=exogenous,
                        future_exogenous=exogenous,
                        **options,
                    )
            except ValueError as problem:
                status = str(problem).split(".")[0]
                break

            errors.append(np.abs(predicted["forecast"].to_numpy() - truth.to_numpy()))
            seconds.append(predicted.attrs["fit_seconds"])
            clipped += predicted.attrs["clipped"]
            diverged += int(predicted.attrs["diverged"])

        # Report the orders that were actually used, defaults included, so the
        # table reads on its own without looking up what was left out.
        row = {"label": label, **{k: options.get(k, v) for k, v in DEFAULT_ORDER.items()}}
        row["history_weeks"] = options.get("history_weeks", DEFAULT_HISTORY_WEEKS)
        row["origins"] = len(errors)

        if errors:
            stacked = np.vstack(errors)
            row["mae"] = float(stacked.mean())
            row["rmse"] = float(np.sqrt((stacked**2).mean()))
            row["mae_first_week"] = float(stacked[:, 0].mean())
            row["mae_last_week"] = float(stacked[:, -1].mean())
            row["fit_seconds"] = float(np.mean(seconds))
            row["clipped"] = clipped
            if diverged:
                status = f"diverged at {diverged} of {len(errors)} origins"
        else:
            row["mae"] = row["rmse"] = np.nan
            row["mae_first_week"] = row["mae_last_week"] = np.nan
            row["fit_seconds"] = np.nan
            row["clipped"] = 0

        if intervals and inside:
            row["coverage"] = float(np.vstack(inside).mean())

        row["status"] = status
        rows.append(row)

    return pd.DataFrame(rows).sort_values("mae").reset_index(drop=True)
