# Yeni Cursor Projesi Olarak Kurulum

Bu belge, `PROJECT_FULL_SNAPSHOT_*` yedeğini **başka bir klasörde sıfırdan** Cursor projesi açmak içindir.

---

## Önemli: Mevcut yedek ne içeriyor?

| Var | Yok (ayrıca gerekir) |
|-----|----------------------|
| Tüm ayarlar (`.env`, `scenarios/`) | Tam Python kaynak ağacı (sadece `elite_trader/` + 2 dosya yedekte) |
| Tüm DB ve `.pkl` modeller | `.venv` (yeniden oluşturulur) |
| Elite modülleri (snapshot `code/`) | `static/`, `markets/`, `self_improver.py` vb. |

**Sonuç:** Yedek tek başına çalışan proje değildir. Yeni Cursor projesi için **tam kaynak kopyası + yedek üzerine veri/ayar** yöntemi kullanın (aşağıda).

---

## Yöntem A — Önerilen (tam proje kopyası + snapshot)

### 1) Kaynak projeyi yeni klasöre kopyala

```bash
# Eski proje (bu makinedeki mevcut kurulum)
SRC=/Users/macbook/Downloads/testtt/predmarket-scanner

# Yeni Cursor workspace klasörü (istediğin yolu yaz)
DEST=~/Projects/predmarket-elite-cursor

rsync -a \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '.git' \
  --exclude 'data/backups' \
  "$SRC/" "$DEST/"
```

### 2) Snapshot’tan ayar ve veriyi yükle

```bash
SNAP=/Users/macbook/Downloads/testtt/predmarket-scanner/data/backups/PROJECT_FULL_SNAPSHOT_20260518T233742Z

cd "$DEST"
./scripts/restore_snapshot_overlay.sh "$SNAP"
```

### 3) Sanal ortam ve bağımlılıklar

```bash
cd "$DEST"
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

### 4) Cursor’da aç

1. Cursor → **File → Open Folder**
2. `$DEST` klasörünü seç (ör. `~/Projects/predmarket-elite-cursor`)
3. Yeni sohbet aç; bağlam için `SOHBET_REFERANS.md` ve `AYARLAR_TUM_PORTLAR.md` dosyalarını @ ile ekle

### 5) Port 8200 başlat

```bash
cd "$DEST"
./run_elite_apex_2x_8200.sh --bg
open http://127.0.0.1:8200/
```

---

## Yöntem B — Sadece yedek klasörün varsa

1. Bu repodan veya USB’den **tüm** `predmarket-scanner` klasörünü kopyala (Yöntem A adım 1).
2. Sonra Yöntem A adım 2–5.

Yedekteki `code/` tek başına yetmez; `momentum_scanner.py`, `self_improver.py`, `markets/`, `static/` gerekir.

---

## Yöntem C — Taşınabilir zip (bir sonraki yedekten)

```bash
cd /Users/macbook/Downloads/testtt/predmarket-scanner
./scripts/export_portable_cursor_bundle.sh
```

Çıktı: `data/backups/PORTABLE_CURSOR_BUNDLE_*.zip` — kaynak + snapshot bir arada (`.venv` hariç).

Yeni makinede:

```bash
unzip PORTABLE_CURSOR_BUNDLE_*.zip -d ~/Projects/
cd ~/Projects/predmarket-scanner   # zip içindeki kök adına göre
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./run_elite_apex_2x_8200.sh --bg
```

---

## Cursor’a özel notlar

| Konu | Ne yapmalı |
|------|------------|
| Workspace kökü | `predmarket-scanner` (içinde `run_elite_apex_2x_8200.sh` olan klasör) |
| Terminal cwd | Her zaman bu kök; `testtt` üst klasöründen script çalışmaz |
| Sohbet geçmişi | Otomatik taşınmaz; `SOHBET_REFERANS.md` + transcript export |
| `.env` | `config/dotenv_root.env` → kök `.env`; API anahtarlarını kontrol et |
| Port çakışması | Eski projede 8200 açıksa yeni projede port değiştir veya eskiyi durdur |

---

## Port değiştirmek (eski proje hâlâ 8200’deyse)

`scenarios/elite_apex_2x_24h.env`:

```env
DASHBOARD_PORT=8201
```

`run_elite_apex_2x_8200.sh` içindeki `PORT=8200` satırını da `8201` yap veya yeni bir `run_elite_apex_2x_8201.sh` kopyası oluştur.

---

## Doğrulama listesi

- [ ] `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8200/` → `200`
- [ ] `sqlite3 data/elite_apex_2x_24h.db "SELECT COUNT(*) FROM positions"` → kayıt var
- [ ] Panelde PnL / kapalı işlemler görünüyor
- [ ] `tail -f logs/elite_apex_2x_8200.scanner.log` akıyor

---

*İlgili dosyalar: `GERI_YUKLEME_PROJE.md`, `scripts/restore_snapshot_overlay.sh`, `scripts/export_portable_cursor_bundle.sh`*
