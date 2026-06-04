"""Isotonic calibration — model tahminini gerçek frekansa eşle.

Model 70% diyor ama gerçek 60% ise model overconfident; isotonic regression
bu sistematik sapmayı düzeltir. Post-hoc bir iyileştirme; estimator'a hiç
dokunmadan accuracy yükseltir (eğer monotonic miscalibration varsa).

Stdlib-only PAV (Pool Adjacent Violators) algoritması.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IsotonicCalibrator:
    """Bir tahmin → gerçek olasılık eşlemesi öğrenir (monotonic non-decreasing)."""
    x_bins: list[float] = field(default_factory=list)   # tahmin değerleri (sorted)
    y_bins: list[float] = field(default_factory=list)   # gerçek frekanslar (sorted by x)

    def fit(self, predictions: list[float], outcomes: list[bool]) -> None:
        if len(predictions) != len(outcomes) or not predictions:
            self.x_bins = []
            self.y_bins = []
            return
        paired = sorted(zip(predictions, outcomes), key=lambda p: p[0])
        xs = [p for p, _ in paired]
        ys = [1.0 if o else 0.0 for _, o in paired]
        # PAV
        n = len(ys)
        weights = [1.0] * n
        values = list(ys)
        i = 0
        while i < n - 1:
            if values[i] > values[i + 1]:
                # Pool
                new_v = (values[i] * weights[i] + values[i + 1] * weights[i + 1]) / \
                        (weights[i] + weights[i + 1])
                new_w = weights[i] + weights[i + 1]
                values[i] = new_v
                weights[i] = new_w
                del values[i + 1]
                del weights[i + 1]
                # Yeniden xs'i de düşür
                # average x for the pool
                # (basit: ilk x'i koru)
                del xs[i + 1]
                n -= 1
                if i > 0:
                    i -= 1
            else:
                i += 1
        self.x_bins = xs
        self.y_bins = values

    def transform(self, p: float) -> float:
        """Verilen tahmin için kalibre edilmiş olasılık."""
        if not self.x_bins:
            return p
        if p <= self.x_bins[0]:
            return self.y_bins[0]
        if p >= self.x_bins[-1]:
            return self.y_bins[-1]
        # Binary search → linear interp
        lo, hi = 0, len(self.x_bins) - 1
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if self.x_bins[mid] <= p:
                lo = mid
            else:
                hi = mid
        x0, x1 = self.x_bins[lo], self.x_bins[hi]
        y0, y1 = self.y_bins[lo], self.y_bins[hi]
        if x1 == x0:
            return y0
        return y0 + (y1 - y0) * (p - x0) / (x1 - x0)


@dataclass
class PlattCalibrator:
    """Sigmoid kalibrasyon (logistic regression on raw predictions)."""
    a: float = 1.0
    b: float = 0.0

    def fit(self, predictions: list[float], outcomes: list[bool], iters: int = 200, lr: float = 0.05) -> None:
        # Logit-link, simple SGD
        import math
        if not predictions:
            return
        x = [math.log(max(1e-6, min(1 - 1e-6, p)) / (1 - max(1e-6, min(1 - 1e-6, p)))) for p in predictions]
        y = [1.0 if o else 0.0 for o in outcomes]
        a, b = 1.0, 0.0
        for _ in range(iters):
            ga = 0.0
            gb = 0.0
            for xi, yi in zip(x, y):
                z = a * xi + b
                p = 1.0 / (1.0 + math.exp(-z))
                ga += (p - yi) * xi
                gb += (p - yi)
            a -= lr * ga / len(x)
            b -= lr * gb / len(x)
        self.a = a
        self.b = b

    def transform(self, p: float) -> float:
        import math
        p = max(1e-6, min(1 - 1e-6, p))
        x = math.log(p / (1 - p))
        z = self.a * x + self.b
        return 1.0 / (1.0 + math.exp(-z))
