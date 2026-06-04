# MEGA 9007 — Canlıya geçiş

9007 varsayılan **paper/sim** modundadır (`MEGA_LIVE_ORDERS=0`, `MEGA_SIM_ENABLED=1`).

## Başlatma

```bash
cd predmarket-scanner
./scripts/elite_9007_process_ctl.sh restart
```

Panel: http://127.0.0.1:9007/paper

## 9007 ayrı API (9006 ile paylaşılmaz)

`.env`:

```
MEGA_9007_BINANCE_API_KEY=...
MEGA_9007_BINANCE_API_SECRET=...
MEGA_9007_BINANCE_FUTURES_TESTNET=1
MEGA_9007_BINANCE_FUTURES_DEMO=1
```

9007 yalnızca `MEGA_9007_*` kullanır. Veri sıfırlama:

`python scripts/reset_mega_9007_data.py --reason "..." --yes`

## Canlı emre geçiş (ileride)

1. Admin panel → `MEGA_LIVE_ORDERS=1`, `MEGA_SIM_ENABLED=0`
2. `.env` içinde `MEGA_9007_BINANCE_API_KEY` / secret doğrula
3. **Restart gerekli** — desk’ten Restart veya `elite_9007_process_ctl.sh restart`
4. Sim ile canlı arasında fill/slippage farkı vardır; küçük stake ile doğrula

## Veri izolasyonu

- 9007 verisi: `data/mega_9007/`
- 9006 ve 9005 verilerine restart dokunmaz

## Admin şifre

- Varsayılan: `x369` (hash; düz metin kodda yok)
- Production: `ADMIN_PANEL_PASSWORD` veya `ADMIN_PANEL_PASSWORD_HASH` env

## Lab

- `/lab` — chat, motor sandbox, counterfactual sim
- LLM: `OPENAI_API_KEY` + `LAB_LLM_PROVIDER=openai`; yedek `OLLAMA_HOST`
