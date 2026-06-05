# Whale Copy & Multi-Agent Consensus — Tweet 3'ün Mimari Karşılığı

Üçüncü tweet üç ekstra katman ekliyor: **smart-money tracking**, **multi-agent
consensus**, **early exit before settlement**. Bunları modüller halinde projeye
bağladık.

## Önce gerçeklik kontrolü

| Tweet | Gerçek |
|---|---|
| "$200 → $14,300 in 27 days" | Compounded günlük ~%16. Kelly disiplinli, sermayesi büyürken bile sürdürülemez. **Sayı uydurma veya cherry-pick.** |
| "271 trades, 74% WR, Sharpe 2.47" | Küçük sample, geriye dönük seçilmiş pencere; istatistiksel gürültü. |
| "I haven't touched it in 27 days. Copytrade here: t.me/..." | **Affiliate scheme sinyali.** Telegram bot link = ya pump-grup ya da referral copytrading. Linke gitme. |
| "Claude found 47 wallets / cloned them" | Teknik olarak yapılabilir (Polymarket Polygon'da public). Ama **survivor bias** ciddi sorun. |
| "Top 20 made more than bottom 13k combined" | Plausible (Pareto). `core/wallet_scoring.pareto_concentration` ile kendi verinde ölçebilirsin. |
| "3 agents, 2 agree = full, 1 alone = half" | Mantıklı (Condorcet jury theorem). `core/consensus.py` aynı kuralı uygular. |
| "91% whale early exit, 73% max profit captured" | Eğer doğruysa, exit policy bu davranışı taklit etmeli; `core/exit_policy.py` capture_pct=0.85 default'u bu. |

## Bağlanan modüller

```
markets/wallets.py            # On-chain trade veri tipi + aggregation
core/wallet_scoring.py        # 100+ trade, >%70 WR, ROI eşikli ranking
core/whale_tracker.py         # Top-N adres listesi, yeni "open" trade polling
core/consensus.py             # 3-agent oylama; full/half size kararı
core/exit_policy.py           # capture %85 + 3x vol spike + pre-settlement buffer
```

## Uçtan uca entegrasyon (pseudo-code)

```python
from core.wallet_scoring import rank_wallets, RankingCriteria
from core.whale_tracker import WhaleTracker
from core.consensus import AgentVote, Vote, decide
from core.exit_policy import ExitConfig, should_exit

# 1) Offline phase — geçmiş 90 gün veriyle
stats = aggregate_stats(historical_trades, resolved_outcomes)
top = rank_wallets(stats.values(), RankingCriteria())
watch = {s.wallet for s in top}

# 2) Online phase — sürekli polling
tracker = WhaleTracker(watch_list=watch, fetcher=my_subgraph_poll)
while True:
    for entry in tracker.poll():
        votes = [
            AgentVote("arbitrage",   arb_check(entry.market_id),    confidence=0.6),
            AgentVote("convergence", signal_estimator_vote(entry),  confidence=0.5),
            AgentVote("whale_copy",  Vote.BUY_YES if entry.side=="YES" else Vote.BUY_NO, 0.7),
        ]
        d = decide(votes)
        if d.is_trade():
            # Kelly × d.size_multiplier × position cap
            ...

# 3) Exit loop
for pos in open_positions:
    snap = build_snapshot(pos)
    exit_now, reason = should_exit(snap, ExitConfig())
    if exit_now:
        close(pos, reason=reason)
```

## Riskler (bu mimariye özel)

- **Front-running ironisi:** Sen whale'i kopyalarken senin gibi 50 bot da kopyalıyor. Whale girince fiyat zaten kayar; sen ikinci dalga.
- **Whale spoofing:** Bir adres senin tracker'a girmek için kasten 100 trade yapıp %70 WR sergileyebilir, sonra senin parana karşı pozisyon açar (adverse selection).
- **Wash trading:** Aynı kişinin 10 cüzdanı; biri kazansın diye diğerleri kaybeder. Tracker'ın gözünde 1 dahi.
- **Settlement oracle riski:** Polymarket UMA-based; dispute olabilir, exit even %85 capture varken bile riskli.
- **MEV / sandwich:** Polygon ucuz ama MEV var; whale TX'ini görüp önüne geçen botlar var.
