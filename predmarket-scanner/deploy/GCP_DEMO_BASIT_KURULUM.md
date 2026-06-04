# Google Cloud — Elite 9005 DEMO Kurulum (En Basit Yol)

Şimdilik **demo.binance** (demo-fapi.binance.com). Mainnet’e geçiş hazır ama sonra yapılır.

---

## Adım 1 — Google Cloud’da sunucu aç (5 dk)

1. [Google Cloud Console](https://console.cloud.google.com) → sol menü **Compute Engine** → **VM instances**
2. **CREATE INSTANCE**
3. Şu ayarları seç:

| Alan | Değer |
|------|--------|
| Name | `elite-9005-demo` |
| Region | **asia-northeast1** (Tokyo — Binance’e yakın) |
| Zone | `asia-northeast1-a` |
| Machine type | **e2-standard-2** (2 vCPU, 8 GB — başlangıç için yeterli) |
| Boot disk | Ubuntu **22.04 LTS**, 30 GB |
| Firewall | ✅ Allow HTTP traffic, ✅ Allow HTTPS traffic |

4. **Advanced options** → **Networking** → **Network interfaces**:
   - **External IPv4**: **Ephemeral** (sonra Reserve static IP yapabilirsin)

5. **CREATE**

6. Sunucu satırında **External IP**’yi kopyala (ör. `34.104.243.96`)

7. **SSH key (Metadata):** Compute Engine → **Metadata** → **SSH Keys** → **Edit** → tam satır:
   ```
   rushpaybusiness:ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOO8Hd52sXSMmukFUY94QkD3Z9X0wrIw9lnNcX3kQe/E rushpaybusiness@gmail.com
   ```
   Başındaki `rushpaybusiness:` zorunlu. Detay: [`GCP_SSH_FIX.md`](GCP_SSH_FIX.md)

---

## Adım 2 — SSH ile bağlan

Mac Terminal (**`ubuntu` değil**):

```bash
ssh -i ~/.ssh/id_ed25519 rushpaybusiness@34.104.243.96
```

En kolay alternatif: GCP Console → VM → **SSH** butonu (tarayıcı, şifre yok).

İlk bağlantıda fingerprint sorarsa `yes` yaz.

---

## Adım 3 — Mac’ten kodu yükle

**Yeni bir Terminal penceresi** (Mac’te, sunucuda değil):

```bash
cd /Users/pro/Downloads/binancex/predmarket-scanner
bash deploy/gcp_upload_from_mac.sh rushpaybusiness@34.104.243.96
```

`SUNUCU_IP` yerine Adım 1’deki IP’yi yaz.

Bu komut:
- Tüm bot kodunu yükler
- `.env` (API anahtarların) kopyalar
- `data/` (işlem geçmişi) kopyalar

---

## Adım 4 — Sunucuda tek komut kurulum

SSH penceresinde (sunucuda):

```bash
cd /opt/binancex/predmarket-scanner
sudo bash deploy/gcp_demo_bootstrap.sh
```

Script soracak:
- **Panel şifresi** → tarayıcıdan panele girerken kullanacaksın

Kurulum bitince bot **demo modda** otomatik başlar.

---

## Adım 5 — Mac’teki botu kapat

Aynı hesapta **iki bot çalışmasın** (çift emir riski):

```bash
cd /Users/pro/Downloads/binancex/predmarket-scanner
./scripts/elite_9005_process_ctl.sh stop
```

---

## Adım 6 — Paneli aç

Tarayıcı:

```
http://SUNUCU_IP/
```

- Kullanıcı: `elite` (veya bootstrap’ta girdiğin isim)
- Şifre: Adım 4’te belirlediğin

---

## Adım 7 — Binance Demo API IP whitelist

1. [Binance Demo](https://demo.binance.com) → API Management
2. API key’inde **IP whitelist** → sunucu IP’sini ekle:
   ```bash
   curl ifconfig.me   # sunucuda çalıştır
   ```

---

## Günlük komutlar (sunucuda)

```bash
# Durum
systemctl status binance-elite-9005-demo

# Log
tail -f /opt/binancex/predmarket-scanner/logs/binance_elite_8300_9005.log

# Yeniden başlat
sudo systemctl restart binance-elite-9005-demo

# Panel nginx
sudo systemctl reload nginx
```

---

## Kod güncelleme (Mac’ten değişiklik sonrası)

```bash
bash deploy/gcp_upload_from_mac.sh rushpaybusiness@34.104.243.96
ssh ubuntu@SUNUCU_IP 'sudo systemctl restart binance-elite-9005-demo'
```

---

## İleride mainnet’e geçiş

Demo stabil olduktan sonra:

1. Binance **mainnet** API key + IP whitelist
2. `.env` içinde mainnet anahtarları
3. `sudo systemctl stop binance-elite-9005-demo`
4. `sudo bash deploy/gcp_bootstrap.sh` + mainnet launcher

Detay: [`GCP_MAINNET_RUNBOOK.md`](GCP_MAINNET_RUNBOOK.md)

---

## Sorun giderme

| Sorun | Çözüm |
|-------|--------|
| SSH bağlanamıyorum | GCP Console → VM → SSH butonu (tarayıcıdan) |
| Panel 401 | Yanlış şifre — `sudo htpasswd /etc/nginx/.htpasswd_elite elite` |
| Bot API hatası -2015 | Binance IP whitelist’e sunucu IP ekle |
| `Permission denied` rsync | `ssh ubuntu@IP` önce çalışıyor mu kontrol et |

---

## Maliyet tahmini

- `e2-standard-2` Tokyo ≈ **$50–70/ay**
- Durdurmak için: VM’yi **STOP** et (disk ücreti devam eder, compute durur)
