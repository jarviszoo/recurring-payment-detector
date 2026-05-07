"""
Phase 3: ML-based expected-amount predictor.

Uses three GradientBoostingRegressors (median + 10th/90th quantile) trained on
synthetic subscription data.  Falls back to median-based prediction when not
enough history is available or the model's confidence is low.
"""

import numpy as np
from sklearn.ensemble import GradientBoostingRegressor

from feature_extractor import extract
from models import Transaction, PredictionResult
from synthetic_training import generate

# Minimum prior charges before trusting the ML predictor
ML_MIN_OBSERVATIONS = 3
# Confidence score below which we fall back to the median predictor
ML_MIN_CONFIDENCE = 0.50


class MLPredictor:
    def __init__(self):
        self._median_model: GradientBoostingRegressor | None = None
        self._lower_model:  GradientBoostingRegressor | None = None
        self._upper_model:  GradientBoostingRegressor | None = None
        self.trained = False

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, n_synthetic: int = 2000) -> None:
        """Train on synthetic data. Called once at startup."""
        X, y = generate(n_synthetic)

        self._median_model = GradientBoostingRegressor(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            loss="squared_error", random_state=0,
        )
        self._lower_model = GradientBoostingRegressor(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            loss="quantile", alpha=0.10, random_state=1,
        )
        self._upper_model = GradientBoostingRegressor(
            n_estimators=200, max_depth=4, learning_rate=0.05,
            loss="quantile", alpha=0.90, random_state=2,
        )

        self._median_model.fit(X, y)
        self._lower_model.fit(X, y)
        self._upper_model.fit(X, y)
        self.trained = True

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(
        self,
        history: list[Transaction],
        billing_cycle_days: int,
        category: str,
        days_since_last: int = 30,
    ) -> PredictionResult:
        """
        Predict the expected next amount.
        Falls back to median when there's insufficient history or low confidence.
        """
        amounts = [t.amount for t in sorted(history, key=lambda t: t.date)]
        n = len(amounts)

        if not self.trained or n < ML_MIN_OBSERVATIONS:
            return self._median_fallback(amounts)

        feat = extract(amounts, billing_cycle_days, category, days_since_last).reshape(1, -1)

        expected = float(self._median_model.predict(feat)[0])
        lower    = float(self._lower_model.predict(feat)[0])
        upper    = float(self._upper_model.predict(feat)[0])

        # Ensure ordering (quantile models can cross)
        lower = min(lower, expected)
        upper = max(upper, expected)

        # Confidence: narrower interval relative to expected → higher confidence
        interval_pct = (upper - lower) / expected if expected > 0 else 1.0
        confidence = max(0.0, min(1.0, 1.0 - interval_pct))

        if confidence < ML_MIN_CONFIDENCE:
            return self._median_fallback(amounts)

        return PredictionResult(
            expected=round(max(expected, 0.01), 2),
            lower_bound=round(max(lower, 0.01), 2),
            upper_bound=round(upper, 2),
            confidence=round(confidence, 3),
            method="ml",
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _median_fallback(amounts: list[float]) -> PredictionResult:
        s = sorted(amounts)
        n = len(s)
        mid = n // 2
        med = s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2
        std = float(np.std(amounts)) if n > 1 else med * 0.05
        return PredictionResult(
            expected=round(med, 2),
            lower_bound=round(max(med - 1.5 * std, 0.01), 2),
            upper_bound=round(med + 1.5 * std, 2),
            confidence=0.0,
            method="median",
        )


# Module-level singleton trained once on import
_predictor = MLPredictor()


def get_predictor() -> MLPredictor:
    if not _predictor.trained:
        _predictor.train()
    return _predictor
