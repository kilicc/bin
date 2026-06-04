# Berserk Mod — Tam Çalışma Profili

Ultra-aggressive **micro-scalp** modu. Varsayılan **paper**; `active_futures_mode == "berserk"` iken Binance Futures live route açılabilir.

## Canlı emir

```
if mode_id == "berserk" and active_futures_mode == "berserk":
    route = BINANCE_FUTURES_LIVE_ENGINE  # risk + Berserk filtreleri geçmeli
else:
    route = PAPER_ENGINE
```

Motor seçimi strateji profilini değiştirmez; yalnızca canlı kapı erişimini belirler.

## Hedef profil (aktif)

| Alan | Değer |
|------|-------|
| `entry_min_strength` | Weak |
| `entry_block_weak` | false |
| `berserk_min_move_pct` | 0.09 |
| `min_edge` / `min_formula_score` | 0.04 / 0.46 |
| `market_cooldown_min` | 0.02 (paper + live simülasyon) |
| `tp_stake_pct` / `sl_stake_pct` | 0.0042 / 0.0024 |
| `tp_trigger_frac` | 0.99 |
| `stale_min_age_min` | 0.15 (~9 sn) |
| `spread_policy` | dynamic_micro (max 0.12%) |
| `max_open` | 14 |
| `active_capital_pct` | 0.70 |
| `min_stake_usd` | 120 (paper öncelikli) |
| `sl_em_veto_count` | 0 |

## Weak sinyal

Hard veto yok. Koşullar: düşük spread, volume/orderbook uyumu, pozitif expected_net → stake × **0.45**.

## Spread (dynamic_micro)

| spread | risk_level | Etki |
|--------|------------|------|
| ≤0.06% | none | — |
| 0.06–0.10% | low | score -4, stake ×0.70 |
| 0.10–0.12% | medium | score -9, stake ×0.45, limit-only |
| >0.12% | extreme | **veto** |

## Market intelligence (soft)

flow/orderbook/volume/cross/news → skor ± ve stake çarpanı (hard veto değil).

## Öğrenme

Her **100** paper kapanışta `data/berserk_learning_suggestions.json` — profil **otomatik değişmez**. Panel + Evrim cross-mode okur.

## Dashboard

Görünüm Berserk iken `#berserkHealthStrip`: route, trades/min, WR, PF, fee/gross, strength dağılımı, öneriler.

## Dosyalar

- `elite_trader/mode_engines/berserk_engine.py`
- `elite_trader/mode_engines/berserk_scoring.py`
- `elite_trader/berserk_cooldown.py`
- `elite_trader/berserk_learning.py`
- `elite_trader/berserk_metrics.py`
- `data/mode_profiles.json` → `modes.berserk`

## Testler

`pytest tests/test_berserk_mode.py`
