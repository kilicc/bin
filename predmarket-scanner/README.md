# Prediction Market Edge Scanner

Üç tweet'in (mispricing scanner, ops fix guide, whale-copy) **gerçek mantığının** tersine mühendisliği ve çalışan iskeleti. Pazarlama numaralarını ayrıştırıp altta yatan teknikleri modüler kod halinde verir.

> **Önemli uyarı:** Tweetlerdeki rakamlar (%81 WR / $200→$14,300 in 27 gün / Sharpe 2.47) büyük ihtimalle pazarlama veya cherry-pick. Altta yatan kavramlar (prediction market mispricing arbitrajı, smart-money copy, multi-agent consensus) **gerçek quant teknikleridir** ama asıl alfa "true probability" tahmin modelinin kalitesinden gelir, sihirli bir LLM çağrısından değil. Bu repo doğru mimariyi kurar; "para basma" garantisi vermez. Kendi paranı koymadan önce paper trading'de aylarca test et.

**Dokümanlar:**
- `README.md` (bu dosya) — genel plan, kurulum, yol haritası
- `EXECUTION.md` — Tweet 2'nin operasyonel fix guide karşılığı (latency, reconciliation, order tipleri)
- `WHALE_COPY.md` — Tweet 3'ün wallet ranking + consensus + early exit mimarisi

---

## 1. Tweet'in iddiası vs. gerçek

| Tweet diyor ki | Gerçek |
|---|---|
| "Sadece fiyat sapması >%6 olan kontratları al" | Doğru kavram: **Edge = TrueProb − MarketPrice**. Eşik tutmak için Kelly kriteri kullanılır. |
| "Claude + 5 GitHub kütüphanesi = scanner" | Scanner kolay kısım. Asıl iş "true probability" tahmini — her piyasa türü için ayrı model. |
| "7-19c entry, %60-90 true prob" | Bu fiyat aralığında likidite zayıf, slippage ve adverse selection ciddi. |
| "$2k → $8,191, 99 trade, Sharpe 2.30" | 99 trade ile Sharpe 2.30 istatistiksel olarak gürültü; çok küçük sample. |
| "$25/ay setup" | Doğru, infra ucuz. Pahalı olan **veri** (polls, weather feeds, options chain). |
| "True probability'i Claude verir" | Hayır. LLM kalibrasyonu kötüdür; gerçek tahmin için domain-specific model gerekir. |

## 2. Altta yatan strateji (gerçek hali)

**Prediction market** = binary olay kontratları (Polymarket, Kalshi, PredictIt, Manifold). Bir kontrat olay olursa $1, olmazsa $0 öder. Piyasa fiyatı (örn. 0.13) ≈ piyasanın tahmin ettiği olasılık.

**Edge stratejisi:**
1. Her aktif piyasa için bir **TrueProb tahmini** üret (kendi modelinden).
2. **Edge = TrueProb − MarketPrice** hesapla.
3. |Edge| > eşik (örn. 0.06) ise sinyal.
4. **Kelly fraction** ile pozisyon boyutu belirle: `f = (p·b − q) / b` (p=true prob, q=1−p, b=odds).
5. Risk yönetimi: max pozisyon, fractional Kelly (0.25x), portföy korelasyon limiti.
6. Likidite ve slippage filtresi: min order book derinliği, min günlük hacim.
7. Çık: olay sonucu beklenir veya fiyat true prob'a yaklaştığında early exit.

**Asıl alfanın geldiği yer (model tipine göre):**
- **Seçim/anket piyasaları:** 538 / Silver Bulletin tarzı poll aggregation + fundamentals.
- **Hava/afet:** NOAA GFS/ECMWF ensemble forecasts.
- **Kripto fiyat eşikleri:** Black-Scholes / options-implied volatility, perpetual funding.
- **Spor:** ELO/Glicko, injury reports, model ensembles.
- **Haber/jeopolitik:** zor; profesyonel forecaster (Metaculus, GJOpen) konsensüsü + Bayesian güncelleme.

## 3. Mimari

```
predmarket-scanner/
├── config.py                  # Eşikler, API endpoints, çalışma modu
├── main.py                    # CLI: scan-once / loop / report / resolve / mark
├── markets/
│   ├── base.py                # Market & Outcome veri tipleri
│   ├── polymarket.py          # Gamma API read-only client (auth gerekmez)
│   └── wallets.py             # On-chain trade & wallet aggregation (Tweet 3)
├── probability/
│   ├── base.py                # ProbabilityEstimator interface
│   ├── heuristic.py           # Baseline (market = true) — sanity sıfırı
│   ├── signal_estimator.py    # CLOB + spot + time + DoW kompozit (Tweet 2)
│   └── llm_claude.py          # Claude API tahmini (DEMO; baseline değil)
├── core/
│   ├── edge.py                # Edge, EV, Kelly hesapları (Tweet 1)
│   ├── scanner.py             # Ana tarama döngüsü
│   ├── signals.py             # 4 baseline sinyal (Tweet 2)
│   ├── timing.py              # Latency tracker (Tweet 2)
│   ├── reconciler.py          # 30s state reconciliation (Tweet 2)
│   ├── wallet_scoring.py      # Smart-money ranking (Tweet 3)
│   ├── whale_tracker.py       # Watch-list polling (Tweet 3)
│   ├── consensus.py           # 3-agent oylama (Tweet 3)
│   └── exit_policy.py         # Pre-settlement exit (Tweet 3)
├── portfolio/
│   └── paper.py               # SQLite paper book — gerçek para YOK
├── tests/
│   ├── test_edge_math.py      # Kelly/EV/signals/timing/reconciler
│   └── test_whale_logic.py    # Ranking/consensus/exit/tracker
├── data/                      # SQLite + CSV log'ları
├── requirements.txt
└── .env.example
```

## 4. Kurulum

```bash
cd predmarket-scanner
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# .env içine ANTHROPIC_API_KEY ekle (Claude probability estimator için)
python main.py scan --paper --limit 50
```

`--paper` mode'u **zorunlu varsayılan**. Gerçek emir göndermek için ayrıca live broker entegrasyonu yazılmalı (Polymarket için CLOB API + EVM cüzdan; Kalshi için authenticated REST). Bu repo buraya gelmez — kasten.

## 5. Yol haritası (kendi alfanı kurmak için)

1. **Hafta 1-2:** Paper mode'da 200+ market topla, true prob'u LLM yerine basit heuristik ile yap, kalibrasyon eğrisi çiz (Brier score).
2. **Hafta 3-4:** Bir kategori seç (örn. kripto fiyat eşikleri). O kategoriye özel model yaz (örn. log-normal projeksiyon + funding rate).
3. **Hafta 5-8:** Backtesting altyapısı kur. Gerçek geçmiş market verisini al, model olsa böyle dönerdi simülasyonu yap.
4. **Hafta 9+:** Sadece kalibrasyon eğrisi düzgün, Brier skoru baseline'ı yenen, 100+ trade'lik backtest'i pozitif olan modelle küçük real money'ye geç. Hala fractional Kelly.

## 6. Riskler

- **Adverse selection:** Eğer 13c'den alabiliyorsan, neden satan biri var? Bilgi asimetrisi olabilir.
- **Likidite:** Küçük cap piyasalarda emir kitabı sığ; %6 edge sandığın slippage ile yenir.
- **Düzenleme:** Polymarket ABD'de kısıtlı; Kalshi regülasyonlu ama ABD-içi sınırları var. Bulunduğun ülkedeki yasalara bak.
- **Smart contract risk:** Polymarket on-chain; cüzdan/contract hatası fonu silebilir.
- **Model riski:** "True probability"n yanlışsa, edge bir illüzyon.
- **Operasyonel:** API rate limit, network downtime, oracle resolution disputes.

## 7. Bu kod ne YAPMAZ

- Senin için para basmaz.
- Gerçek emir göndermez (kasten; paper trading'de kal).
- Sihirli LLM tahminine güvenmez (kod örnek olarak Claude estimator içerir, baseline'dan iyi değildir).
- 3 ayda %409 vaat etmez.
