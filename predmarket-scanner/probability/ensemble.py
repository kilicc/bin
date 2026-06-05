"""Stacking ensemble — birden fazla estimator çıktısının ağırlıklı blend'i.

Mantık: bir estimator hatalıdır, bağımsız hata kaynakları birleştirilince
ortalama hata düşer (Condorcet jury / bias-variance tradeoff). Doğru ağırlıklar
validation set'te öğrenilir.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

# Estimator signature: (market, current_price, history) -> (p, conf)
EstFn = Callable


@dataclass
class StackingEnsemble:
    estimators: list[tuple[str, EstFn]]
    weights: list[float] = field(default_factory=list)

    def __post_init__(self):
        if not self.weights:
            self.weights = [1.0 / len(self.estimators)] * len(self.estimators)

    def predict(self, market, price, history) -> tuple[float, float]:
        preds = []
        confs = []
        for (name, est), w in zip(self.estimators, self.weights):
            try:
                p, c = est(market, price, history)
            except Exception:
                p, c = price, 0.0
            preds.append(p)
            confs.append(c)
        # Weighted average; confidence: average of constituents
        s = sum(self.weights)
        if s <= 0:
            return price, 0.0
        p_blend = sum(p * w for p, w in zip(preds, self.weights)) / s
        c_blend = sum(c * w for c, w in zip(confs, self.weights)) / s
        return max(0.01, min(0.99, p_blend)), max(0.0, min(1.0, c_blend))

    def fit_weights(self, predictions_per_est: list[list[float]], outcomes: list[bool],
                    iters: int = 200, lr: float = 0.02) -> None:
        """Validation set üzerinde ağırlıkları optimize et (Brier minimize)."""
        if not predictions_per_est or not outcomes:
            return
        n_est = len(predictions_per_est)
        n_sample = len(outcomes)
        if any(len(p) != n_sample for p in predictions_per_est):
            return

        # Softmax-parameterized weights to keep them positive and sum=1
        z = [0.0] * n_est
        for _ in range(iters):
            # softmax
            ez = [math.exp(zi) for zi in z]
            s = sum(ez)
            w = [e / s for e in ez]
            # gradient of Brier wrt z
            grads = [0.0] * n_est
            for i in range(n_sample):
                yhat = sum(predictions_per_est[k][i] * w[k] for k in range(n_est))
                err = yhat - (1.0 if outcomes[i] else 0.0)
                for k in range(n_est):
                    # d yhat / d z_k = w_k * (preds[k][i] - yhat)
                    dyhat_dzk = w[k] * (predictions_per_est[k][i] - yhat)
                    grads[k] += 2 * err * dyhat_dzk
            for k in range(n_est):
                z[k] -= lr * grads[k] / n_sample
        ez = [math.exp(zi) for zi in z]
        s = sum(ez)
        self.weights = [e / s for e in ez]
