"""Regression tests for the lstm/ package restructuring.

These guard against reintroducing the fragile sys.path hack that used to
live in app/services/forecasting.py and app/services/indicators.py, which
mutated sys.path at import time and imported the LSTM code under the
generic top-level name `src` (shadowable by any other `src` package on
sys.path).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_sys_path_hack_is_gone_from_forecasting_and_indicators():
    forecasting_src = read("app/services/forecasting.py")
    indicators_src = read("app/services/indicators.py")

    for src in (forecasting_src, indicators_src):
        assert "sys.path.insert" not in src
        assert "sys.path" not in src
        assert "noqa: E402" not in src
        assert "from src." not in src
        assert "import src" not in src


def test_lstm_is_an_importable_package():
    import lstm

    assert (Path(lstm.__file__).parent).name == "lstm"


def test_forecaster_and_feature_builder_import_as_absolute_imports():
    from lstm.src.models import LSTMForecaster
    from lstm.src.preprocessing import build_features

    assert LSTMForecaster.__name__ == "LSTMForecaster"
    assert callable(build_features)


def test_forecasting_module_uses_absolute_lstm_imports():
    from app.services import forecasting

    assert forecasting.LSTMForecaster.__name__ == "LSTMForecaster"
    assert forecasting.build_features.__module__ == "lstm.src.preprocessing.features"
    assert forecasting.CHECKPOINT_PATH == ROOT / "lstm" / "model.pt"


def test_indicators_module_uses_absolute_lstm_imports():
    from app.services import indicators

    assert indicators.build_features.__module__ == "lstm.src.preprocessing.features"


def _synthetic_history(rows: int = 140) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    index = pd.date_range("2025-01-01", periods=rows, freq="B", tz="UTC")
    close = 100.0 + np.cumsum(rng.normal(0, 1, size=rows))
    close = np.clip(close, 10, None)
    open_ = close + rng.normal(0, 0.3, size=rows)
    high = np.maximum(open_, close) + np.abs(rng.normal(0.5, 0.2, size=rows))
    low = np.minimum(open_, close) - np.abs(rng.normal(0.5, 0.2, size=rows))
    volume = rng.integers(1_000_000, 5_000_000, size=rows).astype(float)

    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=index,
    )


def test_real_checkpoint_loads_via_package_import():
    """The checkpoint at lstm/model.pt must still load through the restricted
    torch.load path now that the sys.path hack is gone."""
    from app.services import forecasting

    forecasting._artifacts = None  # ensure a fresh load, not a cached one from another test
    ckpt, model = forecasting._load_artifacts()

    assert "lookback" in ckpt
    assert "horizon" in ckpt
    assert model.__class__.__name__ == "LSTMForecaster"


def test_generate_forecast_end_to_end_without_network_calls(monkeypatch):
    """Exercise the full forecast pipeline (checkpoint load, feature build,
    model inference) while stubbing the network fetch of OHLCV history."""
    from app.services import forecasting

    history = _synthetic_history()

    def fake_fetch(symbol, range_period="6mo", interval="1d"):
        return history

    monkeypatch.setattr(forecasting, "fetch_ohlcv_history", fake_fetch)

    result = forecasting.generate_forecast("AAPL")

    assert result["symbol"] == "AAPL"
    assert len(result["predictions"]) == result["horizon"]
    assert "confidence_bands" in result


def test_forecast_raises_without_real_network_access(monkeypatch):
    """Guardrail: if fetch_ohlcv_history is not stubbed by a test, calling it
    for real would hit the network; make sure the service still surfaces a
    clean error rather than crashing when history is empty."""
    from app.services import forecasting

    monkeypatch.setattr(
        forecasting,
        "fetch_ohlcv_history",
        lambda *_args, **_kwargs: pd.DataFrame(),
    )

    with pytest.raises(ValueError):
        forecasting.generate_forecast("AAPL")
