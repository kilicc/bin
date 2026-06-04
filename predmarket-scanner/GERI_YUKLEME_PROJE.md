# Predmarket Elite — Tam Geri Yükleme Kılavuzu

Bu belge, `PROJECT_FULL_SNAPSHOT_*` yedeğinden **aynı ayarlar, veriler ve kod** ile sisteme dönmeniz içindir.

---

## 1. Yedekte ne var?

| Klasör | İçerik |
|--------|--------|
| `config/scenarios/` | Tüm port `.env` dosyaları (8200 APEX dahil) |
| `config/dotenv_root.env` | Kök `.env` kopyası |
| `config/run_scripts/` | `run_elite_*.sh`, reset/backup scriptleri |
| `data/dbs/` | Tüm SQLite trade veritabanları |
| `data/pkl/` | Formül, kalibrasyon, whale modelleri |
| `data/scan_stats/` | Tarama red istatistikleri |
| `code/elite_trader/` | Elite tarayıcı Python modülleri |
| `code/dashboard.py` | Panel |
| `logs/` | Son log dosyaları |
| `reports/` | Attribution raporları |
| `db_summaries.txt` | Yedek anındaki açık/kapalı/PnL özeti |
| `MANIFEST.sha256` | Dosya bütünlük kontrolü |
| `AYARLAR_TUM_PORTLAR.md` | Port bazlı ayar tablosu |
| `SOHBET_REFERANS.md` | Cursor sohbet / karar özeti |

---

## 2. Yeni yedek almak

```bash
cd /Users/macbook/Downloads/testtt/predmarket-scanner
chmod +x scripts/backup_full_project_snapshot.sh
./scripts/backup_full_project_snapshot.sh
```

Çıktı: `data/backups/PROJECT_FULL_SNAPSHOT_YYYYMMDDTHHMMSSZ/`

**Önemli:** Yedeği proje dışına da kopyalayın (iCloud, USB, başka disk):

```bash
cp -a data/backups/PROJECT_FULL_SNAPSHOT_* ~/Desktop/predmarket_yedek/
```

---

## 3. Tam geri yükleme (önerilen sıra)

### Adım A — Çalışan süreçleri durdur

```bash
cd /Users/macbook/Downloads/testtt/predmarket-scanner

# Tüm elite portlar
for port in 8150 8160 8170 8180 8190 8200 8210; do
  lsof -ti :$port 2>/dev/null | xargs kill 2>/dev/null || true
done
./run_elite_apex_2x_8200.sh --stop 2>/dev/null || true
./run_elite_formula_restart_8160.sh --stop 2>/dev/null || true
pkill -f "elite_trader.scanner" 2>/dev/null || true
sleep 2
```

### Adım B — Yedek klasörünü seçin

```bash
SNAP=data/backups/PROJECT_FULL_SNAPSHOT_20260519T023000Z   # kendi klasör adınız
ls "$SNAP/GERI_YUKLEME_PROJE.md"    # dosya var mı kontrol
```

### Adım C — Ayarları geri yükle

```bash
cp -a "$SNAP/config/scenarios/"* scenarios/
cp -a "$SNAP/config/dotenv_root.env" .env
cp -a "$SNAP/config/run_scripts/"run_elite*.sh .
chmod +x run_elite*.sh
```

### Adım D — Veritabanları ve modeller

```bash
cp -a "$SNAP/data/dbs/"* data/
cp -a "$SNAP/data/pkl/"* data/
cp -a "$SNAP/data/scan_stats/"* data/ 2>/dev/null || true
cp -a "$SNAP/reports/"* data/reports/ 2>/dev/null || true
```

### Adım E — Kod (elite mantığı)

```bash
cp -a "$SNAP/code/elite_trader/"* elite_trader/
cp -a "$SNAP/code/dashboard.py" dashboard.py
cp -a "$SNAP/code/momentum_scanner.py" momentum_scanner.py 2>/dev/null || true
```

### Adım F — Bütünlük kontrolü (isteğe bağlı)

```bash
cd "$SNAP" && shasum -a 256 -c MANIFEST.sha256
```

### Adım G — Port 8200 (APEX) başlat

```bash
cd /Users/macbook/Downloads/testtt/predmarket-scanner
./run_elite_apex_2x_8200.sh --bg
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8200/
```

Panel: **http://127.0.0.1:8200/**

Diğer portlar:

| Port | Komut |
|------|--------|
| 8150 CAL | `./run_elite_cal_primary_stack.sh` |
| 8160 800h | `./run_elite_formula_restart_8160.sh` |
| 8170 velocity | `./run_elite_velocity_stack.sh` |
| 8180 global 2x | `./run_elite_global_2x_stack.sh` |
| 8190 fresh | `./run_elite_formula_fresh_8190.sh` |

---

## 4. Sadece 8200 (APEX) geri yükleme

Tam projeye dokunmadan yalnızca APEX:

```bash
SNAP=data/backups/PROJECT_FULL_SNAPSHOT_XXXXX   # veya apex_8200_* küçük yedek

cp -a "$SNAP/config/scenarios/elite_apex_2x_24h.env" scenarios/
cp -a "$SNAP/data/dbs/elite_apex_2x_24h.db" data/
cp -a "$SNAP/data/pkl/elite_success_formula.pkl" data/ 2>/dev/null || true

./run_elite_apex_2x_8200.sh --stop
./run_elite_apex_2x_8200.sh --bg
```

---

## 5. Sıfırdan $22k (veriyi silmeden yedekten önce)

Yedek aldıktan sonra sıfırlamak isterseniz:

```bash
./scripts/reset_all_ports_22k.sh
```

Bu, mevcut DB’leri `data/backups/reset_*` altına taşır ve boş DB oluşturur. **Geri dönmek için** önce Adım 3’teki `data/dbs/` kopyasını yapın.

---

## 6. Cursor sohbeti

Kod ve ayarlar bu yedekte; **sohbet metni** Cursor sunucusundadır.

- Sohbet özeti: yedekteki `SOHBET_REFERANS.md`
- Tam transcript (varsa):  
  `~/.cursor/projects/Users-macbook-Downloads-testtt/agent-transcripts/6fcc18d6-3e6b-47cb-8313-bfb4da1becde/`

Cursor’da sohbeti dışa aktarın (chat menüsü → export) ve yedek klasörüne `SOHBET_EXPORT.md` olarak kaydedin.

---

## 7. Güvenlik

`dotenv_root.env` içinde API anahtarları olabilir. Yedeği **şifreli disk** veya güvenli konumda tutun; halka açık repoya commit etmeyin.

---

## 8. Sorun giderme

| Sorun | Çözüm |
|-------|--------|
| Panel açılmıyor | `cd predmarket-scanner` sonra `./run_elite_apex_2x_8200.sh --bg` |
| Port meşgul | `./run_elite_apex_2x_8200.sh --stop && sleep 2 && ./run_elite_apex_2x_8200.sh --bg` |
| Yanlış DB | `scenarios/elite_apex_2x_24h.env` içinde `PAPER_DB_PATH=data/elite_apex_2x_24h.db` |
| Eski PnL yok | `data/elite_apex_2x_24h.db` yedekten kopyalandı mı kontrol edin |

---

*Son güncelleme: bu sohbet kapsamında oluşturulan tam snapshot süreci.*
