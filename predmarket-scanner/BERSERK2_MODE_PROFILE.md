# BERSERK2 modu

Odaklı micro-scalp: **günün en hareketli 10 USDT perpetual** + **BTC 5m rejim** ile yön/stake ayarı.

## Panel

- **Görünüm** → `BERSERK2`: top10 listesi, BTC rejim, paper metrikleri.
- **Canlı motor** → `BERSERK2`: `BINANCE_LIVE_ORDERS=1` iken berserk gibi live emir (Weak strength kabul).

## Davranış

| Özellik | Açıklama |
|---------|----------|
| Evren | Dinamik top-10 (`berserk2_movers.py`), ~15s yenileme |
| Hızlı tarama | Görünüm/motor **BERSERK2** iken fast-tick: 10 coin ~180ms bütçe (motor thread atlanır) |
| Motor | BERSERK2 aktifken klasik motor **çalışmaz** — 46s BTC klines blokajı önlendi |
| BTC | Yumuşak veto: ters trendde stake düşer, çoğu zaman giriş devam |
| Giriş ölçekleri | `berserk2_min_score` ~26, edge/formula kapalı, cooldown ~0.36sn |
| TP | Küçük net TP hedefi; `berserk_expected_net_negative` gevşek override |
| Çıkış | `berserk_exit` — kısa grace, hızlı SPIKE-QUICK |
| Paper | Paralel evrende berserk'ten **ayrı cooldown** |

## Red sebepleri

- `berserk2_not_top_mover` — sembol o an top-10 dışında
- `berserk2_btc_long_vs_down` — BTC düşüş trendinde LONG
- `berserk2_btc_short_vs_up` — BTC yükseliş trendinde SHORT

## Stabilite (9005)

`scenarios/binance_elite_8300_9005.env`:

- `ELITE_ENABLED_MODES=berserk2` — evrim/hunter/berserk paper motoru çalışmaz
- `ELITE_DEFAULT_EXECUTION_MODE=berserk2` — canlı motor + panel varsayılan
- `BERSERK2_PAPER_ONLY=0` — demo-fapi **canlı emir** (Weak strength kabul)
- `BERSERK2_MOMENTUM_TIER1/2/3_PCT` — top10 sırasına göre giriş eşiği (sıcak coin daha düşük)
- `BN_FUT_HUB_LITE=1` + `BN_FUT_MARK_WS_ALL=0` — 712 coin mark WS kapalı; RAM düşer
- `ELITE_PANEL_REFRESH_SEC=0.5` — snapshot yükü azalır
- `BINANCE_SCAN_ALL_PERPETUALS=0` — 527 coin tarama patlaması önlenir
- `ELITE_DEMO_TRADE_FULL_WATCHLIST=0`

Supervisor: 2 dk içinde 3+ restart → 120s bekleme (`elite_9005_supervisor.sh`).

## Profil

`data/mode_profiles.json` → `modes.berserk2` (builtin ile birleşir).

Anahtarlar: `berserk2_top_n`, `berserk2_chop_score_boost`, `max_open: 10`, `same_symbol_max_open: 2`.
