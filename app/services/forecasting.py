from __future__ import annotations

import logging
import sys
from datetime import timedelta
from pathlib import Path
from threading import RLock
from warnings import catch_warnings, simplefilter

import numpy as np
import pandas as pd
import torch
from sklearn.preprocessing import StandardScaler

from app.config import get_company_name, get_currency, is_indian_stock
from app.services.stock_data import fetch_ohlcv_history

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
LSTM_ROOT = ROOT / "lstm"
CHECKPOINT_PATH = LSTM_ROOT / "model.pt"

if str(LSTM_ROOT) not in sys.path:
    sys.path.insert(0, str(LSTM_ROOT))

from src.models import LSTMForecaster  # noqa: E402
from src.preprocessing import build_features  # noqa: E402

_artifacts = None
_lock = RLock()
SAFE_CHECKPOINT_GLOBALS = [
    StandardScaler,
    (np.core.multiarray.scalar, "numpy._core.multiarray.scalar"),
    (np.core.multiarray._reconstruct, "numpy._core.multiarray._reconstruct"),
    np.dtype,
    type(np.dtype("float64")),
    np.ndarray,
]


def _load_artifacts():
    global _artifacts
    with _lock:
        if _artifacts is not None:
            return _artifacts
        if not CHECKPOINT_PATH.exists():
            raise FileNotFoundError(f"Forecast checkpoint not found at {CHECKPOINT_PATH}")

        with catch_warnings():
            simplefilter("ignore")
            with torch.serialization.safe_globals(SAFE_CHECKPOINT_GLOBALS):
                ckpt = torch.load(CHECKPOINT_PATH, map_location="cpu", weights_only=True)

        bound = ckpt["model_cfg"].get("output_bound")
        model = LSTMForecaster(
            n_features=int(ckpt["n_features"]),
            horizon=int(ckpt["horizon"]),
            hidden1=int(ckpt["model_cfg"]["hidden1"]),
            hidden2=int(ckpt["model_cfg"]["hidden2"]),
            dropout=float(ckpt["model_cfg"]["dropout"]),
            output_bound=None if bound is None else float(bound),
        )
        model.load_state_dict(ckpt["model_state"])
        model.eval()
        _artifacts = (ckpt, model)
        return _artifacts


def _business_dates(anchor: pd.Timestamp, horizon: int) -> list[str]:
    dates = []
    current = anchor
    while len(dates) < horizon:
        current = current + timedelta(days=1)
        if current.weekday() < 5:
            dates.append(current.date().isoformat())
    return dates


@torch.no_grad()
def _run_model(window_feats: np.ndarray, ckpt: dict, model: LSTMForecaster) -> np.ndarray:
    x = ckpt["feat_scaler"].transform(window_feats).astype(np.float32)
    pred_scaled = model(torch.from_numpy(x).unsqueeze(0)).squeeze(0).cpu().numpy()
    return ckpt["target_scaler"].inverse_transform(pred_scaled.reshape(1, -1)).ravel()


def _scenario_rows(
    dates: list[str],
    prices: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
) -> list[dict]:
    return [
        {
            "date": date,
            "predicted_close": round(float(price), 2),
            "lower": round(float(lo), 2),
            "upper": round(float(hi), 2),
        }
        for date, price, lo, hi in zip(dates, prices, lower, upper, strict=True)
    ]


def _risk_metrics(
    feature_frame: pd.DataFrame,
    feature_names: list[str],
    lookback: int,
    horizon: int,
    last_close: float,
    dates: list[str],
    pred_prices: np.ndarray,
    ckpt: dict,
    model: LSTMForecaster,
) -> dict:
    target = feature_frame["log_return"].to_numpy(dtype=float) if "log_return" in feature_frame else np.array([])
    matrix = feature_frame[feature_names].to_numpy(dtype=float)
    residuals = []

    first_idx = max(lookback, len(feature_frame) - 30)
    for idx in range(first_idx, len(feature_frame)):
        window = matrix[idx - lookback:idx]
        if len(window) != lookback:
            continue
        forecast_returns = _run_model(window, ckpt, model)
        if len(forecast_returns) and idx < len(target):
            residuals.append(float(target[idx] - forecast_returns[0]))

    residual_array = np.asarray(residuals, dtype=float)
    residual_array = residual_array[np.isfinite(residual_array)]
    if residual_array.size:
        sigma = float(np.std(residual_array))
        mae_log = float(np.mean(np.abs(residual_array)))
    else:
        step_returns = np.diff(np.log(np.maximum(pred_prices, 0.01)))
        sigma = float(np.std(step_returns)) if step_returns.size else 0.01
        mae_log = sigma

    sigma = max(sigma, 0.005)
    backtest_mae = round(float(last_close * mae_log), 2)
    confidence_lower = pred_prices * np.exp(-sigma)
    confidence_upper = pred_prices * np.exp(sigma)
    bull_prices = pred_prices * np.exp(sigma * 1.5)
    bear_prices = pred_prices * np.exp(-sigma * 1.5)

    return {
        "backtest_mae": backtest_mae,
        "risk_sigma": round(sigma, 4),
        "confidence_bands": _scenario_rows(dates, pred_prices, confidence_lower, confidence_upper),
        "bull_case": [
            {"date": date, "predicted_close": round(float(price), 2)}
            for date, price in zip(dates, bull_prices, strict=True)
        ],
        "bear_case": [
            {"date": date, "predicted_close": round(float(price), 2)}
            for date, price in zip(dates, bear_prices, strict=True)
        ],
    }


def generate_forecast(symbol: str) -> dict:
    symbol = (symbol or "").upper().strip()
    if not symbol:
        raise ValueError("Symbol is required")

    ckpt, model = _load_artifacts()
    lookback = int(ckpt["lookback"])
    horizon = int(ckpt["horizon"])
    feature_names = list(ckpt["feature_names"])

    history = fetch_ohlcv_history(symbol, range_period="6mo", interval="1d")
    if history is None or history.empty:
        raise ValueError(f"Unable to fetch enough OHLCV history for {symbol}")

    features = build_features(history)
    missing = [name for name in feature_names if name not in features.columns]
    if missing:
        raise ValueError(f"Forecast features missing columns: {missing}")

    if len(features) < lookback:
        raise ValueError(f"Need at least {lookback} engineered rows for {symbol}")

    window = features[feature_names].to_numpy()[-lookback:]
    pred_log_returns = _run_model(window, ckpt, model)

    aligned_history = history.loc[features.index]
    last_close = float(aligned_history["Close"].iloc[-1])
    anchor_date = pd.to_datetime(features.index[-1]).tz_localize(None)
    pred_prices = last_close * np.exp(np.cumsum(pred_log_returns))
    dates = _business_dates(anchor_date, horizon)

    predictions = []
    previous = last_close
    for idx, (date, price) in enumerate(zip(dates, pred_prices, strict=True), start=1):
        price = float(price)
        move_pct = ((price - previous) / previous) * 100 if previous else 0.0
        predictions.append(
            {
                "step": idx,
                "date": date,
                "predicted_close": round(price, 2),
                "predicted_return_pct": round(move_pct, 2),
            }
        )
        previous = price

    risk = _risk_metrics(
        feature_frame=features,
        feature_names=feature_names,
        lookback=lookback,
        horizon=horizon,
        last_close=last_close,
        dates=dates,
        pred_prices=pred_prices,
        ckpt=ckpt,
        model=model,
    )

    return {
        "symbol": symbol,
        "company_name": get_company_name(symbol),
        "market": "IN" if is_indian_stock(symbol) else "US",
        "currency": get_currency(symbol),
        "lookback_days": lookback,
        "horizon": horizon,
        "last_close": round(last_close, 2),
        "as_of": anchor_date.date().isoformat(),
        "predictions": predictions,
        **risk,
    }
