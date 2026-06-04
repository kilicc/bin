# GCP Mainnet Taşıma — Operasyon Runbook

Elite 9005 botunu Google Cloud Compute Engine üzerinde mainnet (`fapi.binance.com`) olarak çalıştırma rehberi.

## Hızlı başlangıç

```bash
# 1) GCP VM (Tokyo)
export GCP_PROJECT=your-project-id
bash deploy/gcp_create_vm.sh

# 2) Kod gönder
bash deploy/gcp_sync_code.sh ubuntu@STATIC_IP

# 3) Sunucuda bootstrap
ssh ubuntu@STATIC_IP 'PANEL_DOMAIN=panel.example.com bash -s' < deploy/gcp_bootstrap.sh

# 4) .env + veri taşı (Mac'ten — bot durur)
bash deploy/gcp_migrate_data.sh ubuntu@STATIC_IP

# 5) TLS
ssh ubuntu@STATIC_IP 'sudo certbot --nginx -d panel.example.com'

# 6) Başlat
ssh ubuntu@STATIC_IP 'sudo systemctl start binance-elite-9005-mainnet elite-9005-supervisor'

# 7) Doğrula
PANEL_AUTH=elite:YOUR_PASS bash scripts/gcp_go_live_check.sh https://panel.example.com
```

## Binance API key checklist (mainnet)

Binance Futures → API Management:

- [ ] **Yeni mainnet API key** oluştur (demo key kullanma)
- [ ] **Enable Futures** açık
- [ ] **Withdraw** kapalı
- [ ] **IP whitelist** → GCP statik IP (`gcloud compute addresses describe elite-9005-ip --region=asia-northeast1`)
- [ ] `.env` sunucuda:
  ```
  BINANCE_FUTURES_API_KEY=...
  BINANCE_FUTURES_API_SECRET=...
  BINANCE_FUTURES_DEMO=0
  BINANCE_FUTURES_TESTNET=0
  BN_FUT_MODE=live
  ```
- [ ] `chmod 600 .env`
- [ ] İlk gün stake düşük tut (`ELITE_MIN_STAKE_USD` mainnet senaryoda)

## Mimari

- Bot: `127.0.0.1:9005` (`ELITE_BIND_HOST=127.0.0.1`)
- Dış erişim: nginx `:443` + basic auth
- Süreç: `systemd` → `binance-elite-9005-mainnet.service`
- İkinci katman: `elite-9005-supervisor.service` (heartbeat + API restart)

## Cutover güvenliği

1. Mac bot **mutlaka durdur** (`elite_9005_process_ctl.sh stop`)
2. Aynı Binance hesabında çift bot **çift emir** riski
3. DB snapshot: `data/pre_gcp_cutover_*.db` otomatik alınır

## Performans

```bash
bash scripts/gcp_latency_probe.sh
```

Hedef: `fapi.binance.com` total < 300ms (Tokyo VM'de genelde 150–250ms).

## Yedekleme

```bash
# Sunucuda cron (bootstrap kurar)
export GCS_BACKUP_BUCKET=your-backup-bucket
bash deploy/gcp_backup_cron.sh
```

## Sorun giderme

| Belirti | Çözüm |
|---------|--------|
| API -2015 / IP | Binance whitelist → statik IP |
| Panel 401 | nginx htpasswd: `sudo htpasswd /etc/nginx/.htpasswd_elite elite` |
| Bot çöker | `journalctl -u binance-elite-9005-mainnet -f` |
| Supervisor loop | `logs/elite_9005_supervisor.log` |

## Dosya referansları

| Dosya | Amaç |
|-------|------|
| `scenarios/binance_elite_8300_9005_mainnet.env` | Mainnet tuning |
| `binance_elite_pro_9005_mainnet.py` | Launcher |
| `run_binance_elite_9005_mainnet.sh` | Manuel start |
| `scripts/elite_9005_mainnet_process_ctl.sh` | stop/start/restart |
| `deploy/gcp_create_vm.sh` | GCE VM + disk + IP |
| `deploy/gcp_bootstrap.sh` | OS paketleri + systemd + nginx |
| `deploy/gcp_migrate_data.sh` | Veri cutover |

Veri koruma: [`DATA_PRESERVATION_9005.md`](../DATA_PRESERVATION_9005.md)
