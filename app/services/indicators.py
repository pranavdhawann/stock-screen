from __future__ import annotations

import math
from typing import Any

import pandas as pd

from lstm.src.preprocessing import build_features


def _clean(value: Any):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, 4)


def compute_indicators(history: pd.DataFrame) -> dict:
    if history is None or history.empty:
        return {"indicators": [], "latest": {}}

    features = build_features(history)
    if features.empty:
        return {"indicators": [], "latest": {}}

    close = history["Close"].astype(float)
    sma_20 = close.rolling(20, min_periods=1).mean()
    ema_20 = close.ewm(span=20, adjust=False).mean()
    std_20 = close.rolling(20, min_periods=2).std().fillna(0.0)
    bb_upper_20 = sma_20 + (2.0 * std_20)
    bb_lower_20 = sma_20 - (2.0 * std_20)

    aligned = history.loc[features.index]
    rows = []
    for idx, row in features.iterrows():
        macd = _clean(row.get("macd"))
        macd_signal = _clean(row.get("macd_signal"))
        macd_histogram = None
        if macd is not None and macd_signal is not None:
            macd_histogram = round(macd - macd_signal, 4)

        rows.append(
            {
                "date": pd.to_datetime(idx).date().isoformat(),
                "timestamp": int(pd.to_datetime(idx).timestamp() * 1000),
                "open": _clean(aligned.at[idx, "Open"]),
                "high": _clean(aligned.at[idx, "High"]),
                "low": _clean(aligned.at[idx, "Low"]),
                "close": _clean(aligned.at[idx, "Close"]),
                "volume": int(aligned.at[idx, "Volume"]),
                "sma_20": _clean(sma_20.at[idx]),
                "ema_20": _clean(ema_20.at[idx]),
                "rsi_14": _clean(row.get("rsi_14")),
                "macd": macd,
                "macd_signal": macd_signal,
                "macd_histogram": macd_histogram,
                "bb_upper_20": _clean(bb_upper_20.at[idx]),
                "bb_lower_20": _clean(bb_lower_20.at[idx]),
                "bb_width_20": _clean(row.get("bb_width_20")),
                "atr_14": _clean(row.get("atr_14")),
                "volume_ratio": _clean(row.get("volume_ratio")),
            }
        )

    latest = rows[-1] if rows else {}
    return {"indicators": rows, "latest": latest}
