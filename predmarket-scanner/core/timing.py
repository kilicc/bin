"""Latency instrumentation — her hot-path adımını ölç, p50/p95/p99 rapor et.

Tweet'in "0.5ms internal, 6-8ms RT to CLOB" hedefi için ölçüm olmadan iyileşme yok.
Bu modül threadsafe değil; tek event loop ya da process içinde kullan.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from contextlib import contextmanager
from statistics import median
from typing import Deque, Dict


class LatencyTracker:
    def __init__(self, window: int = 1024):
        self._samples: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=window))

    @contextmanager
    def measure(self, label: str):
        t0 = time.perf_counter_ns()
        try:
            yield
        finally:
            dt_ms = (time.perf_counter_ns() - t0) / 1_000_000.0
            self._samples[label].append(dt_ms)

    def record(self, label: str, ms: float) -> None:
        self._samples[label].append(ms)

    def percentile(self, label: str, p: float) -> float:
        data = sorted(self._samples.get(label, ()))
        if not data:
            return float("nan")
        k = max(0, min(len(data) - 1, int(round(p / 100.0 * (len(data) - 1)))))
        return data[k]

    def report(self) -> dict[str, dict[str, float]]:
        out = {}
        for label, samples in self._samples.items():
            if not samples:
                continue
            data = list(samples)
            out[label] = {
                "n": len(data),
                "p50": median(data),
                "p95": self.percentile(label, 95),
                "p99": self.percentile(label, 99),
                "max": max(data),
            }
        return out


# Global default — istersen başka instance kur
tracker = LatencyTracker()
