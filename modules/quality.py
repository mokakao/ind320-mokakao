"""Data quality: finding the points that do not belong.

Four tools, and the first one is the only one with a trick to it.

A year of weather is dominated by the seasons. Comparing a July day against
the yearly average says nothing useful - of course July is warm. So the
seasonal shape is filtered out first, the limits are worked out on what is
left, and then the limits are put back on the original scale. That last step
is the one worth getting right: the plot should show the real measurements
with limits that bend along with the seasons, not a flattened series nobody
recognises.
"""

import numpy as np
import pandas as pd
from scipy.fft import dct, idct
from scipy.signal import spectrogram as _spectrogram
from sklearn.neighbors import LocalOutlierFactor
from statsmodels.tsa.seasonal import STL

# A normal distribution's standard deviation is about 1.4826 times the median
# absolute deviation. Using the MAD instead of the usual standard deviation
# means a few wild values cannot inflate the limits and hide themselves.
MAD_TO_SIGMA = 1.4826


def split_frequencies(values: np.ndarray, cutoff: int = 8) -> tuple[np.ndarray, np.ndarray]:
    """Split a series into its slow and fast parts with a DCT.

    The discrete cosine transform rewrites the series as a sum of cosines, from
    the slowest (the yearly shape) to the fastest (hour-to-hour noise). Keeping
    only the first `cutoff` coefficients and transforming back gives the slow
    part; the rest is what is left over.

    cutoff is in coefficients, not days: 1 is the mean, 2 is a single half
    wave over the year, and so on. Around 8 keeps the seasonal shape and a
    couple of broad swings, which is usually what you want.
    """
    coefficients = dct(values, norm="ortho")

    slow_coefficients = coefficients.copy()
    slow_coefficients[cutoff:] = 0
    slow = idct(slow_coefficients, norm="ortho")

    return slow, values - slow


def spc_outliers(
    series: pd.Series,
    cutoff: int = 8,
    sigmas: float = 3.0,
) -> dict:
    """Statistical process control limits that follow the season.

    The series is split into a slow seasonal part and the fast variation left
    over - the assignment calls the latter SATV. Robust statistics over the
    whole year give flat limits around the fast part, and adding the slow part
    back turns those flat lines into curves that track the original data.

    A point is an outlier when it falls outside the curves, which is the same
    as its fast part falling outside the flat limits - the curves are just the
    readable way to show it.

    Returns the original series, the two limit curves, the outlier mask and a
    short summary.
    """
    values = series.to_numpy(dtype=float)
    slow, fast = split_frequencies(values, cutoff=cutoff)

    centre = np.median(fast)
    spread = MAD_TO_SIGMA * np.median(np.abs(fast - centre))

    # Guard against a flat series, where the spread collapses to zero and
    # every point would be flagged.
    if spread == 0:
        spread = fast.std() or 1.0

    lower_flat = centre - sigmas * spread
    upper_flat = centre + sigmas * spread

    # Back to the original scale: the limits bend with the season.
    lower = slow + lower_flat
    upper = slow + upper_flat

    outliers = (values < lower) | (values > upper)

    return {
        "series": series,
        "seasonal": pd.Series(slow, index=series.index),
        "satv": pd.Series(fast, index=series.index),
        "lower": pd.Series(lower, index=series.index),
        "upper": pd.Series(upper, index=series.index),
        "outliers": pd.Series(outliers, index=series.index),
        "summary": {
            "cutoff": cutoff,
            "sigmas": sigmas,
            "n_outliers": int(outliers.sum()),
            "share": float(outliers.mean()),
            "limit_width": float(upper_flat - lower_flat),
            "largest": float(np.abs(fast[outliers]).max()) if outliers.any() else 0.0,
        },
    }


def lof_anomalies(series: pd.Series, proportion: float = 0.01, neighbours: int = 20) -> dict:
    """Local Outlier Factor on a time series.

    LOF compares how crowded a point's neighbourhood is with how crowded its
    neighbours' neighbourhoods are, so it finds points that are unusual
    *locally* rather than just extreme.

    Each hour is described by two numbers: the value itself and how much it
    changed from the hour before. Using only the value would reduce LOF to
    picking out the highest and lowest readings, which is what the SPC limits
    already do. Adding the change makes it flag sudden jumps as well, which is
    the kind of thing "anomaly" is supposed to mean.
    """
    values = series.to_numpy(dtype=float)
    change = np.diff(values, prepend=values[0])

    # Standardise so neither column dominates the distance purely by its unit.
    features = np.column_stack([values, change])
    features = (features - features.mean(axis=0)) / (features.std(axis=0) + 1e-12)

    model = LocalOutlierFactor(n_neighbors=neighbours, contamination=proportion)
    labels = model.fit_predict(features)
    scores = -model.negative_outlier_factor_

    anomalies = pd.Series(labels == -1, index=series.index)

    return {
        "series": series,
        "anomalies": anomalies,
        "scores": pd.Series(scores, index=series.index),
        "summary": {
            "proportion": proportion,
            "neighbours": neighbours,
            "n_anomalies": int(anomalies.sum()),
            "threshold": float(np.quantile(scores, 1 - proportion)),
            "max_score": float(scores.max()),
        },
    }


def stl_decomposition(
    series: pd.Series,
    period: int = 52,
    seasonal: int = 7,
    trend: int | None = None,
    robust: bool = True,
):
    """Seasonal-Trend decomposition using LOESS.

    STL pulls a series apart into a repeating seasonal shape, a slow trend and
    the remainder. Unlike the DCT split above it lets the seasonal shape change
    gradually from year to year, which suits reservoir levels: the yearly
    rhythm is the same but wet and dry years shift it around.

    period is the length of one cycle in samples - 52 for weekly data. seasonal
    and trend are the LOESS window lengths and must be odd; trend defaults to
    whatever statsmodels considers sensible. robust downweights outlying points
    so a single strange week cannot drag the trend with it.
    """
    return STL(series, period=period, seasonal=seasonal, trend=trend, robust=robust).fit()


def spectrogram(series: pd.Series, window: int = 104, overlap: int | None = None) -> dict:
    """How the frequency content changes through the series.

    A single DCT over the whole year says which rhythms are present but not
    when. A spectrogram cuts the series into overlapping windows and transforms
    each one, so a rhythm that only appears in some years shows up as a patch
    rather than being smeared across the whole picture.

    window is the number of samples in each slice and overlap how many they
    share; a bigger window resolves frequency better and time worse.
    """
    overlap = window // 2 if overlap is None else overlap
    window = min(window, len(series))
    overlap = min(overlap, window - 1)

    frequencies, times, power = _spectrogram(
        series.to_numpy(dtype=float) - series.mean(),
        nperseg=window,
        noverlap=overlap,
    )
    return {"frequencies": frequencies, "times": times, "power": power,
            "window": window, "overlap": overlap}
