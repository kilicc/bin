"""Bayesian + Calibration + Ensemble smoke tests.
Çalıştır: python tests/test_self_improve.py
"""
from __future__ import annotations

import sys, os, importlib.util, types, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(modname, relpath):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    spec = importlib.util.spec_from_file_location(modname, os.path.join(here, relpath))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


def test_bayesian_posterior_converges():
    """Posterior gerçek olasılığa yakınsamalı."""
    bayes = _load("probability.bayesian_d", "probability/bayesian.py")
    rng = random.Random(7)
    scorer = bayes.BayesianWalletScorer(prior_alpha=2.0, prior_beta=2.0)
    true_p = 0.70
    for _ in range(500):
        won = rng.random() < true_p
        scorer.observe("w1", won)
    post = scorer.posteriors["w1"]
    # Mean yakın true_p
    assert abs(post.mean - true_p) < 0.05, f"mean={post.mean}"
    # CI lower bound true_p'ın altında ama makul yakın
    lb = post.credible_lower(0.05)
    assert lb < true_p and lb > 0.60, f"lb={lb}"
    print(f"test_bayesian_posterior_converges OK (mean={post.mean:.3f}, lb={lb:.3f})")


def test_bayesian_small_sample_skeptical():
    """Küçük sample → posterior LB düşük olmalı (Wilson gibi)."""
    bayes = _load("probability.bayesian_d2", "probability/bayesian.py")
    scorer = bayes.BayesianWalletScorer(prior_alpha=2.0, prior_beta=2.0)
    # 5 trade, hepsi win → naive WR %100; posterior LB çok daha düşük
    for _ in range(5):
        scorer.observe("luck", won=True)
    lb = scorer.score("luck", quantile=0.05)
    assert lb < 0.85, f"expected skeptical lb<0.85, got {lb}"
    print(f"test_bayesian_small_sample_skeptical OK (lb={lb:.3f} for 5/5 wins)")


def test_isotonic_corrects_overconfidence():
    """Overconfident estimator → kalibrasyon sonrası daha iyi Brier."""
    cal = _load("probability.calibration_d", "probability/calibration.py")
    rng = random.Random(11)
    # Sentetik: model 0.8 dediğinde gerçek 0.6, model 0.3 dediğinde gerçek 0.5
    preds, outs = [], []
    for _ in range(500):
        true_p = 0.6
        preds.append(0.8)
        outs.append(rng.random() < true_p)
        preds.append(0.3)
        outs.append(rng.random() < 0.5)
    iso = cal.IsotonicCalibrator()
    iso.fit(preds, outs)
    # 0.8 input → calibrated should be closer to 0.6
    calibrated_high = iso.transform(0.8)
    assert 0.5 < calibrated_high < 0.75, f"calibrated_high={calibrated_high}"
    # Monotonic check
    samples = [iso.transform(x) for x in [0.1, 0.3, 0.5, 0.7, 0.9]]
    assert all(samples[i] <= samples[i+1] for i in range(4)), f"not monotone: {samples}"
    print(f"test_isotonic_corrects_overconfidence OK (0.8→{calibrated_high:.3f}, "
          f"monotone={samples})")


def test_platt_calibrator_runs():
    cal = _load("probability.calibration_d2", "probability/calibration.py")
    rng = random.Random(3)
    preds = [rng.random() for _ in range(200)]
    outs = [p > 0.5 + rng.gauss(0, 0.1) for p in preds]
    platt = cal.PlattCalibrator()
    platt.fit(preds, outs, iters=100, lr=0.05)
    y = platt.transform(0.5)
    assert 0.0 < y < 1.0
    print(f"test_platt_calibrator_runs OK (p=0.5 → {y:.3f})")


def test_ensemble_weights_normalize():
    ens = _load("probability.ensemble_d", "probability/ensemble.py")
    # 2 estimator, equal weights initially
    e1 = lambda m, p, h: (0.6, 0.8)
    e2 = lambda m, p, h: (0.4, 0.5)
    se = ens.StackingEnsemble([("a", e1), ("b", e2)])
    # Equal weights default
    p, c = se.predict(None, None, [])
    assert abs(p - 0.5) < 1e-6, f"p={p}"
    # Fit weights to prefer estimator 'a' (which predicts 0.6 when truth is 1)
    preds_per_est = [[0.6] * 100, [0.4] * 100]
    outcomes = [True] * 100
    se.fit_weights(preds_per_est, outcomes)
    # Weight on 'a' should be > weight on 'b'
    assert se.weights[0] > se.weights[1], f"weights={se.weights}"
    assert abs(sum(se.weights) - 1.0) < 1e-6
    print(f"test_ensemble_weights_normalize OK (weights={[round(w,3) for w in se.weights]})")


if __name__ == "__main__":
    test_bayesian_posterior_converges()
    test_bayesian_small_sample_skeptical()
    test_isotonic_corrects_overconfidence()
    test_platt_calibrator_runs()
    test_ensemble_weights_normalize()
    print("\nALL SELF-IMPROVE TESTS PASSED")
