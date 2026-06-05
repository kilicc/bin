# GCP Full Stack Mainnet Runbook

9005 BERSERK2 + 9006 MEGA + 9007 MEGA (Admin + Eğitim Lab) — Tokyo GCE.

## Hızlı başlangıç

```bash
export GCP_PROJECT=your-project-id

# 0) Proje hazırlığı (API, SA, bucket, statik IP)
bash deploy/gcp_project_setup.sh

# 1) VM (c3-highcpu-8, 100GB data disk)
bash deploy/gcp_create_vm_full.sh

# 2) Kod
STATIC_IP=$(gcloud compute addresses describe elite-full-ip --region=asia-northeast1 --format='get(address)')
bash deploy/gcp_sync_code.sh ubuntu@${STATIC_IP}

# 3) Bootstrap
ssh ubuntu@${STATIC_IP} \
  'GCP_PROJECT='"${GCP_PROJECT}"' GCS_BACKUP_BUCKET='"${GCP_PROJECT}"'-binancex-backups \
   PANEL_DOMAIN_9005=9005.example.com PANEL_DOMAIN_9006=mega6.example.com PANEL_DOMAIN_9007=mega7.example.com bash -s' \
  < deploy/gcp_bootstrap_full.sh

# 4) .env (3 API key) — deploy/BINANCE_API_KEYS_CHECKLIST.md
bash deploy/gcp_secret_manager.sh push   # opsiyonel
bash deploy/gcp_migrate_data_full.sh ubuntu@${STATIC_IP}

# 5) TLS
ssh ubuntu@${STATIC_IP} \
  'sudo certbot --nginx -d 9005.example.com -d mega6.example.com -d mega7.example.com'

# 6) Başlat
ssh ubuntu@${STATIC_IP} \
  'sudo systemctl start binance-elite-9005-mainnet binance-elite-9006-mainnet binance-elite-9007-mainnet elite-full-supervisor'

# 7) Doğrula
PANEL_AUTH=elite:YOUR_PASS bash scripts/gcp_go_live_check.sh https://mega7.example.com

# 8) Monitoring
bash deploy/gcp_monitoring_setup.sh
```

## Panel URL'leri

| URL | İçerik |
|-----|--------|
| `https://9005.example.com/` | BERSERK2 9005 |
| `https://mega6.example.com/paper` | MEGA 9006 |
| `https://mega7.example.com/paper` | MEGA 9007 desk |
| `https://mega7.example.com/admin` | Yönetim paneli |
| `https://mega7.example.com/lab` | Eğitim Lab (Vertex Gemini) |

## Eğitim Lab AI (Vertex)

9007 mainnet senaryo: `LAB_LLM_PROVIDER=vertex`, `LAB_LLM_MODEL=gemini-2.5-flash`

VM service account `roles/aiplatform.user` gerekir (`gcp_project_setup.sh`).

## Veri koruma

9005 DB, lessons, proposals silinmez — `deploy/gcp_migrate_data_full.sh` cutover öncesi snapshot alır.
Detay: `DATA_PRESERVATION_9005.md`

## Sorun giderme

- SSH: `deploy/GCP_SSH_FIX.md`
- Sudo: `deploy/GCP_SSH_FIX.md`
- Lab LLM: `curl http://127.0.0.1:9007/api/health/strip` → llm.ok
- Loglar: `logs/binance_elite_*_mainnet.log`, `journalctl -u binance-elite-9007-mainnet`
