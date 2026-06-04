# Yeni Google Cloud Hesabı — Domain Olmadan Kurulum (Seçenek B)

Statik IP + port **9085 / 9086 / 9087** ile panel. Domain ve SSL gerekmez.

Tüm komutlar Mac Terminal’de, proje klasöründen çalıştırılır:

```bash
cd /Users/pro/Downloads/binancex/predmarket-scanner
```

---

## BÖLÜM 1 — Google Cloud hesabı (ilk kez, ~15 dk)

### Adım 1.1 — Hesap aç

1. https://console.cloud.google.com adresine git
2. Google hesabınla giriş yap
3. **Terms of Service** kabul et
4. **Free trial** veya faturalandırma ekle (Compute Engine için kredi kartı gerekir — VM ~150–250$/ay)

### Adım 1.2 — Yeni proje oluştur

1. Console üst bar → proje seçici → **New Project**
2. Project name: `binancex-trading` (istediğin isim)
3. **Create**
4. Proje ID’yi not al (ör. `binancex-trading-123456`) — buna `GCP_PROJECT` diyeceğiz

### Adım 1.3 — Mac’e gcloud kur

```bash
brew install google-cloud-sdk
```

### Adım 1.4 — Giriş yap

```bash
gcloud auth login
gcloud auth application-default login
```

Tarayıcı açılır → Google hesabını seç → izin ver.

### Adım 1.5 — Projeyi seç

```bash
export GCP_PROJECT=binancex-trading-123456   # kendi proje ID’n
gcloud config set project "$GCP_PROJECT"
```

Doğrula:

```bash
gcloud config get-value project
```

---

## BÖLÜM 2 — GCP altyapısı (~10 dk)

### Adım 2.1 — Otomatik kurulum (API, bucket, statik IP, firewall)

```bash
cd /Users/pro/Downloads/binancex/predmarket-scanner

export GCP_PROJECT=binancex-trading-123456
export GCS_BACKUP_BUCKET="${GCP_PROJECT}-binancex-backups"

bash deploy/gcp_project_setup.sh
```

**Çıktıda `Statik IP: x.x.x.x` satırını kopyala ve kaydet.** Binance’te buna ihtiyacın var.

```bash
export STATIC_IP=$(gcloud compute addresses describe elite-full-ip \
  --region=asia-northeast1 --format='get(address)')
echo "Statik IP: $STATIC_IP"
```

---

## BÖLÜM 3 — VM oluştur (~5 dk)

### Adım 3.1 — Sunucuyu aç

```bash
export GCP_PROJECT=binancex-trading-123456
export GCP_SA_EMAIL=binancex-bot@${GCP_PROJECT}.iam.gserviceaccount.com

bash deploy/gcp_create_vm_full.sh
```

VM adı: `elite-full-mainnet`  
Bölge: Tokyo (`asia-northeast1`)  
Makine: `c3-highcpu-8`

### Adım 3.2 — SSH anahtarını ekle (bağlanamazsan)

Mac’te anahtarın yoksa:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
cat ~/.ssh/id_ed25519.pub
```

Console → **Compute Engine** → **Metadata** → **SSH Keys** → **Edit** → satır ekle:

```
KULLANICI_ADIN:ssh-ed25519 AAAA... KULLANICI_ADIN@email.com
```

Başındaki `KULLANICI_ADIN:` zorunlu. Detay: [GCP_SSH_FIX.md](GCP_SSH_FIX.md)

### Adım 3.3 — SSH test

```bash
ssh ubuntu@${STATIC_IP}
```

Bağlanamazsan Console’dan VM satırında **SSH** butonuna tıkla (tarayıcı terminali).

---

## BÖLÜM 4 — Kod + sunucu hazırlığı (~20 dk)

### Adım 4.1 — Kodu sunucuya gönder

Mac’te (proje klasöründe):

```bash
export STATIC_IP=$(gcloud compute addresses describe elite-full-ip \
  --region=asia-northeast1 --format='get(address)')

bash deploy/gcp_sync_code.sh ubuntu@${STATIC_IP}
```

SSH kullanıcı adın farklıysa (`ubuntu` yerine) onu yaz.

### Adım 4.2 — Bootstrap (Python, nginx port modu, systemd)

Panel şifresi sorulacak — **not al** (kullanıcı: `elite`).

```bash
ssh ubuntu@${STATIC_IP} \
  "PANEL_MODE=ports GCP_PROJECT=${GCP_PROJECT} GCS_BACKUP_BUCKET=${GCP_PROJECT}-binancex-backups bash -s" \
  < deploy/gcp_bootstrap_full.sh
```

Bu adım:
- Python venv + paketler kurar
- nginx’i **9085 → 9005**, **9086 → 9006**, **9087 → 9007** yapar
- 3 bot + supervisor systemd kayıtlarını ekler

---

## BÖLÜM 5 — `.env` ve Binance API (~20 dk)

### Adım 5.1 — Mac’te `.env` dosyası

`predmarket-scanner/.env` oluştur veya düzenle:

```bash
# 9005 BERSERK2 mainnet
BINANCE_FUTURES_API_KEY=...
BINANCE_FUTURES_API_SECRET=...

# 9006 MEGA mainnet
MEGA_BINANCE_API_KEY=...
MEGA_BINANCE_API_SECRET=...

# 9007 MEGA + Lab mainnet
MEGA_9007_BINANCE_API_KEY=...
MEGA_9007_BINANCE_API_SECRET=...

# GCP + güvenlik
GCP_PROJECT=binancex-trading-123456
GCS_BACKUP_BUCKET=binancex-trading-123456-binancex-backups
ADMIN_PANEL_PASSWORD=guclu_admin_sifren
```

### Adım 5.2 — Binance’te 3 mainnet API key

Her key için: Binance → **API Management** → Futures API

| Kontrol | Değer |
|---------|--------|
| Enable Futures | Açık |
| Withdraw | Kapalı |
| IP whitelist | `$STATIC_IP` (Adım 2.1’deki IP) |

3 ayrı key: 9005, 9006, 9007.

Detay: [BINANCE_API_KEYS_CHECKLIST.md](BINANCE_API_KEYS_CHECKLIST.md)

---

## BÖLÜM 6 — Veri taşıma + cutover (~15 dk)

**Mac’teki botlar durur.** Kısa kesinti normal.

```bash
cd /Users/pro/Downloads/binancex/predmarket-scanner

bash deploy/gcp_migrate_data_full.sh ubuntu@${STATIC_IP}
```

Script:
- Mac botlarını durdurur
- 9005 DB snapshot alır
- Veriyi sunucuya rsync eder
- `.env` kopyalar

Sunucuda izin:

```bash
ssh ubuntu@${STATIC_IP} "chmod 600 /opt/binancex/predmarket-scanner/.env"
```

Venv eksikse (bootstrap hata verdiyse):

```bash
ssh ubuntu@${STATIC_IP} << 'EOF'
cd /opt/binancex/predmarket-scanner
python3.11 -m venv .venv
.venv/bin/pip install -U pip wheel
.venv/bin/pip install -r requirements.txt
EOF
```

---

## BÖLÜM 7 — Botları başlat (~5 dk)

```bash
ssh ubuntu@${STATIC_IP} \
  "sudo systemctl start \
     binance-elite-9005-mainnet \
     binance-elite-9006-mainnet \
     binance-elite-9007-mainnet \
     elite-full-supervisor"
```

Durum:

```bash
ssh ubuntu@${STATIC_IP} \
  "sudo systemctl status binance-elite-9005-mainnet binance-elite-9007-mainnet --no-pager"
```

Hata varsa log:

```bash
ssh ubuntu@${STATIC_IP} "tail -30 /opt/binancex/predmarket-scanner/logs/binance_elite_mega_9007_mainnet.log"
```

---

## BÖLÜM 8 — Panel erişimi (domain yok)

Tarayıcıda (bootstrap’ta verdiğin **elite** şifresi ile):

| URL | Ne |
|-----|-----|
| `http://STATIK_IP:9085/` | BERSERK2 panel |
| `http://STATIK_IP:9086/paper` | MEGA 9006 |
| `http://STATIK_IP:9087/paper` | MEGA 9007 desk |
| `http://STATIK_IP:9087/admin` | Admin (ayrı şifre: `ADMIN_PANEL_PASSWORD`) |
| `http://STATIK_IP:9087/lab` | Eğitim Lab (Vertex Gemini) |

`STATIK_IP` yerine Adım 2.1’deki IP.

Örnek: `http://34.104.243.96:9087/paper`

### Go-live kontrol (sunucuda)

```bash
ssh ubuntu@${STATIC_IP}
cd /opt/binancex/predmarket-scanner
bash scripts/gcp_go_live_check.sh
```

`GO-LIVE: PASS` görmelisin.

---

## BÖLÜM 9 — Güvenlik (hemen yap)

### Adım 9.1 — Firewall’u kendi IP’ne kısıtla

Mac’te IP’ni öğren:

```bash
curl -s ifconfig.me
echo
```

Sadece senin IP’nden panele izin (ör. `88.123.45.67`):

```bash
export MY_IP=88.123.45.67

gcloud compute firewall-rules update elite-full-allow-web \
  --source-ranges=${MY_IP}/32

gcloud compute firewall-rules update elite-full-panel-ports \
  --source-ranges=${MY_IP}/32 2>/dev/null || true
```

IP değişince (mobil internet vb.) kuralı güncelle.

### Adım 9.2 — Admin şifresi

Varsayılan admin şifresi kullanma — `.env` içinde `ADMIN_PANEL_PASSWORD` güçlü olsun.

---

## BÖLÜM 10 — Yedekleme test (~5 dk)

```bash
ssh ubuntu@${STATIC_IP} \
  "cd /opt/binancex/predmarket-scanner && \
   GCP_PROJECT=${GCP_PROJECT} GCS_BACKUP_BUCKET=${GCP_PROJECT}-binancex-backups \
   bash deploy/gcp_backup_cron.sh"
```

---

## Sorun giderme

| Sorun | Ne yap |
|-------|--------|
| `gcloud: command not found` | `brew install google-cloud-sdk` |
| Billing required | Console → Billing → hesap bağla |
| SSH timeout | Metadata’ya SSH key ekle, [GCP_SSH_FIX.md](GCP_SSH_FIX.md) |
| Panel açılmıyor | Firewall 9085–9087 açık mı? `sudo ufw status` |
| Binance -2015 | API key IP whitelist → statik IP |
| Lab LLM fail | `.env`’de `GCP_PROJECT` var mı? 9007 restart |

---

## Komut özeti (kopyala-yapıştır)

```bash
cd /Users/pro/Downloads/binancex/predmarket-scanner
export GCP_PROJECT=binancex-trading-123456
export GCS_BACKUP_BUCKET="${GCP_PROJECT}-binancex-backups"

gcloud auth login
gcloud config set project "$GCP_PROJECT"

bash deploy/gcp_project_setup.sh
export STATIC_IP=$(gcloud compute addresses describe elite-full-ip --region=asia-northeast1 --format='get(address)')

export GCP_SA_EMAIL=binancex-bot@${GCP_PROJECT}.iam.gserviceaccount.com
bash deploy/gcp_create_vm_full.sh

bash deploy/gcp_sync_code.sh ubuntu@${STATIC_IP}

ssh ubuntu@${STATIC_IP} "PANEL_MODE=ports GCP_PROJECT=${GCP_PROJECT} GCS_BACKUP_BUCKET=${GCS_BACKUP_BUCKET} bash -s" < deploy/gcp_bootstrap_full.sh

# .env hazırla, Binance 3 key whitelist → $STATIC_IP

bash deploy/gcp_migrate_data_full.sh ubuntu@${STATIC_IP}

ssh ubuntu@${STATIC_IP} "sudo systemctl start binance-elite-9005-mainnet binance-elite-9006-mainnet binance-elite-9007-mainnet elite-full-supervisor"

echo "Panel: http://${STATIC_IP}:9087/paper"
```

---

**Sıradaki adımın:** Bölüm 1’den başla — `gcloud auth login` ve proje oluştur. Proje ID’ni aldığında Adım 2.1’deki `gcp_project_setup.sh` komutunu çalıştır.
