# predmarket-scanner — sunucu tam yedek (9008 LIVE)

**Kaynak:** GCP `elite-full-mainnet` (`34.146.107.66`)  
**Path:** `/opt/binancex/predmarket-scanner`  
**Tarih:** 2026-06-05  
**Servis:** `binance-elite-9008-live` → port **9008**, panel nginx **9086**

## Paket içeriği

| Bölüm | Açıklama |
|-------|----------|
| `predmarket-scanner/` | Sunucudaki tam uygulama (kod, `.venv`, `data/`, `logs/`, senaryolar) |
| `predmarket-scanner/deploy/` | systemd + nginx (canlı kopyalar) |
| `etc/` | Sunucudaki orijinal systemd/nginx path yapısı |

## Hariç tutulanlar (bilerek)

- `data/deleted_archives/` (~20 GB arşiv — sunucuda duruyor, yedekte yok)
- `*.tgz` kaynak arşivleri (zip dışında)

## Canlı yapılandırma

- **Entry:** `run_binance_elite_mega_9008_live.sh` → `binance_elite_pro_9008_live.py`
- **Env:** `scenarios/binance_elite_mega_9008_live.env`
- **MEGA veri:** `data/mega_9008/` (open/closed/session)
- **Panel:** `panel/elite_v2/` → nginx `9086` → `127.0.0.1:9008`
- **API:** `https://demo-fapi.binance.com` (demo futures)

## Geri yükleme (sunucu)

```bash
# Kod + venv
sudo rsync -a predmarket-scanner/ /opt/binancex/predmarket-scanner/
sudo chown -R pro:pro /opt/binancex/predmarket-scanner

# systemd
sudo cp predmarket-scanner/deploy/binance-elite-9008-live.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now binance-elite-9008-live

# nginx
sudo cp predmarket-scanner/deploy/elite-full-ports.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## Güvenlik

`predmarket-scanner/.env` ve senaryo env dosyalarında **API anahtarları** vardır.  
Git branch'te `.env` gönderilmez; tam anahtarlar yalnızca local zip'te.
