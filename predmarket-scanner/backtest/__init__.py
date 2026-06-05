"""Backtest harness.

Modüller:
  synthetic   — Bilinen true-prob ile sentetik 100 günlük piyasa evreni
  metrics     — Brier, log-loss, hit rate, calibration, Sharpe
  engine      — Walk-forward backtest replay
  optimizer   — Grid search over signal weights
"""
