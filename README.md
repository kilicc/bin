# bin

Binance Futures Elite / MEGA trading stack (`predmarket-scanner`).

## Kurulum

```bash
cd predmarket-scanner
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

API anahtarları: `predmarket-scanner/.env` ve `scenarios/.env.mega_*` (git dışı — örnek: `scenarios/.env.mega_9006.example`).

## MEGA 9006

- Senaryo: `predmarket-scanner/scenarios/binance_elite_mega_9006_mainnet.env`
- Checkpoint: `predmarket-scanner/docs/MEGA_SYSTEM_BOT_CHECKPOINT.md`
- GCP deploy: `predmarket-scanner/deploy/gcp_9006_restore_chat_checkpoint.sh`

## Not

`data/`, `*.db` ve `.env` dosyaları güvenlik ve boyut nedeniyle repoya dahil değildir.
