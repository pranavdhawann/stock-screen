"""OHLCV CSV loader."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED = ("Open", "High", "Low", "Close", "Volume")


def load_ohlcv(csv_path: str | Path, date_col: str | None = "Date") -> pd.DataFrame:
    """Load an OHLCV CSV, normalize column casing, and set a sorted datetime index."""
    df = pd.read_csv(csv_path)
    df.columns = [c.strip() for c in df.columns]

    if date_col and date_col in df.columns:
        df[date_col] = pd.to_datetime(df[date_col], utc=True, errors="coerce")
        df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()

    # Title-case the OHLCV columns so downstream code can rely on them.
    rename = {c: c.title() for c in df.columns if c.title() in REQUIRED}
    df = df.rename(columns=rename)

    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"{csv_path}: missing required columns {missing}")

    return df[list(REQUIRED)].astype(float)
