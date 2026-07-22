"""LSTM forecasting package.

Making this a proper package (rather than relying on a sys.path hack that
inserted ``lstm/`` itself onto ``sys.path`` under the generic name ``src``)
lets consumers do plain absolute imports such as::

    from lstm.src.models import LSTMForecaster
    from lstm.src.preprocessing import build_features
"""
