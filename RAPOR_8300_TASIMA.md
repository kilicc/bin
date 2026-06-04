# 8300 Sistem Taşıma Raporu

**Tarih:** 2026-05-20  
**Kaynak:** `/Users/macbook/Downloads/testtt/predmarket-scanner`  
**Hedef:** `/Users/macbook/Desktop/binancex/predmarket-scanner`  
**Profil:** Plan B — Elite APEX Paper Compound (port **8300**)

---

## Özet

Çalışan 8300 sisteminin **tam çalışır kopyası** `binancex/predmarket-scanner` altına alındı. Veritabanı ve kritik runtime dosyaları kaynakla **birebir aynı** (SHA-256 doğrulandı). Python sanal ortamı (`.venv`) dahil edildi; yeni makinede ek kurulum gerekmez.

**Dahil edilmedi (bilinçli):** `data/backups/` (~548 MB eski snapshot’lar) — 8300 çalışması için gerekli değil.

**Toplam boyut:** ~816 MB (venv + kod + veri + loglar).

---

## Klasör yapısı

```
/Users/macbook/Desktop/binancex/
├── RAPOR_8300_TASIMA.md          ← bu dosya
├── BASLAT_8300.sh                ← tek komut başlatıcı
└── predmarket-scanner/           ← tam proje kopyası
    ├── run_elite_apex_2x_8300.sh
    ├── scenarios/elite_apex_2x_24h_paper_compound.env
    ├── data/elite_apex_2x_24h_8300.db
    ├── data/scanner_heartbeat_elite_apex_2x_24h_8300.json
    ├── data/scan_stats_elite_apex_2x_24h_8300.json
    ├── data/elite_success_formula.pkl
    ├── .env
    ├── .venv/
    ├── elite_trader/             ← scanner, db, runtime_status, stale_tp
    ├── dashboard.py
    ├── static/index.html
    └── 8300_RETURN_PLANI_NOT.md  ← not: env’e uygulanmamış dönüş planı
```

---

## 8300 — çalıştırma

```bash
cd /Users/macbook/Desktop/binancex/predmarket-scanner

# Durum
./run_elite_apex_2x_8300.sh --status

# Arka planda başlat (önerilen)
./run_elite_apex_2x_8300.sh --bg

# Durdur
./run_elite_apex_2x_8300.sh --stop

# DB sıfırlayıp sıfırdan (DİKKAT: tüm paper geçmişi silinir)
./run_elite_apex_2x_8300.sh --fresh --bg
```

**Panel:** http://127.0.0.1:8300/  
**Loglar:** `logs/elite_apex_2x_8300.scanner.log`, `logs/elite_apex_2x_8300.dash.log`

Üst klasörden: `/Users/macbook/Desktop/binancex/BASLAT_8300.sh`

---

## Port çakışması

Aynı anda **kaynak** (`testtt`) ve **binancex** kopyasında 8300 çalıştırmayın — port ve DB dosyası çakışır.

- Kaynakta çalışıyorsa: önce `testtt` tarafında `./run_elite_apex_2x_8300.sh --stop`
- Sonra binancex’te başlatın.

8200 (Plan A) ayrı porttur; 8300 ile karışmaz.

---

## Ortam profili (Plan B)

Dosya: `scenarios/elite_apex_2x_24h_paper_compound.env`

| Ayar | Değer |
|------|--------|
| Port | 8300 |
| DB | `data/elite_apex_2x_24h_8300.db` |
| Canlı işlem | **Kapalı** (`DISABLE_LIVE_TRADING=1`) |
| Başlangıç bakiye (env) | $22,000 |
| Min stake | $1,000 |
| Max stake | 0 (= WR/Kelly ölçekli, üst sınır yok) |
| Aktif sermaye | Bakiye × 50% |
| TP | 0.7% stake × 85% tetik |
| SL | 2.5% stake |
| STALE-TP | 3 dk |
| Cooldown | 8 dk |
| Hedge | Kapalı |
| Max açık | 14 |

Detaylı port karşılaştırması: `AYARLAR_TUM_PORTLAR.md`

---

## Bütünlük doğrulama (SHA-256)

| Dosya | Hash (kaynak = hedef) |
|-------|------------------------|
| `data/elite_apex_2x_24h_8300.db` | `67efd392718f2003e0b88e4af61cc3aa36488c5caf584b8877b86ba075ef513d` |
| `scenarios/elite_apex_2x_24h_paper_compound.env` | `e6b61531209d5c88b9b401805ead88ee2fdc7444339f01f2f3fe6a8f102d4d6a` |
| `run_elite_apex_2x_8300.sh` | `3a55547f4346c898bf84b7875776b177fda2cb3b9a5933c5d70d9ae24a96f50f` |

Kod (SL düzeltmesi, canlı dashboard, heartbeat): `elite_trader/db.py`, `scanner.py`, `runtime_status.py`, `dashboard.py`, `static/index.html` — kaynak ile **aynı hash**.

---

## Veritabanı

- **Dosya boyutu:** 430,080 byte  
- **positions:** 467 kayıt (kopya anındaki paper geçmişi)

---

## Güvenlik

- `.env` kopyalandı (API anahtarları). `binancex` klasörünü paylaşmayın / git’e koymayın.
- 8300 yalnızca **paper**; Polymarket’te gerçek emir göndermez.

---

## İlgili dokümanlar (kopyada)

- `8300_RETURN_PLANI_NOT.md` — dönüş hedefi notu (env’e uygulanmadı)
- `AYARLAR_TUM_PORTLAR.md`
- `SOHBET_REFERANS.md`
- `GERI_YUKLEME_PROJE.md`, `KURULUM_YENI_CURSOR_PROJESI.md`

---

## Cursor’da açma

1. **File → Open Folder** → `/Users/macbook/Desktop/binancex/predmarket-scanner`
2. Terminal: `./run_elite_apex_2x_8300.sh --bg`
3. Tarayıcı: http://127.0.0.1:8300/

---

*Rapor otomatik oluşturuldu — taşıma: rsync, backups hariç, venv dahil.*
