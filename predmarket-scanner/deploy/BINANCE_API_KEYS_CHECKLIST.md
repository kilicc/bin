# Binance Mainnet API Key Checklist (GCP Full Stack)

3 ayrı mainnet API key — hepsi GCP statik IP whitelist.

Statik IP öğren:
```bash
gcloud compute addresses describe elite-full-ip --region=asia-northeast1 --format='get(address)'
```

## 9005 BERSERK2

`.env`:
```
BINANCE_FUTURES_API_KEY=...
BINANCE_FUTURES_API_SECRET=...
BINANCE_FUTURES_DEMO=0
BINANCE_FUTURES_TESTNET=0
BN_FUT_MODE=live
```

## 9006 MEGA

`.env`:
```
MEGA_BINANCE_API_KEY=...
MEGA_BINANCE_API_SECRET=...
```

## 9007 MEGA + Admin + Lab

`.env`:
```
MEGA_9007_BINANCE_API_KEY=...
MEGA_9007_BINANCE_API_SECRET=...
ADMIN_PANEL_PASSWORD=...   # production şifre
GCP_PROJECT=your-project-id
```

## Binance API Management (her key için)

- [ ] Enable Futures açık
- [ ] Withdraw kapalı
- [ ] IP whitelist → GCP statik IP
- [ ] Sunucuda `chmod 600 .env`
- [ ] Secret Manager: `bash deploy/gcp_secret_manager.sh push`

## İlk gün mainnet

- Düşük stake (`ELITE_MIN_STAKE_USD`, `ELITE_MAX_STAKE_USD`)
- `./scripts/gcp_go_live_check.sh https://mega7.example.com`
