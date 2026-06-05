# Paper panel + canlı işlem (paralel)

Demo panel **http://127.0.0.1:8000** her zaman `data/paper.db` kullanır. Canlı emirler ayrı süreçte `data/live.db` yazar.

## Terminal 1 — demo + öğrenme (değiştirme)

```bash
cd predmarket-scanner
chmod +x run_paper_stack.sh
./run_paper_stack.sh
```

Veya iki süreç:

```bash
./.venv/bin/python dashboard.py          # :8000
./.venv/bin/python momentum_scanner.py   # paper.db, self_improver
```

## Terminal 2 — gerçek bakiye, max $2/pozisyon

```bash
chmod +x run_live_scanner.sh
./run_live_scanner.sh
```

`live.scanner.env` içinde:

- `MAX_POSITION_USD=2`
- `POLYMARKET_LIVE_TRADING=1` + onay cümlesi
- `POLYMARKET_LEARN_READONLY=1` — paper `learning_state.pkl` okunur, canlı kapanışlar pkl'yi bozmaz
- `LIVE_USE_WALLET_BALANCE=1` — Kelly için CLOB USDC bakiyesi

## Panel (tek sayfa)

**http://127.0.0.1:8000**

- Üst KPI + grafikler → **Paper demo** (`paper.db`, $20 equity)
- Kırmızı çerçeveli **「Canlı işlemler (Polymarket CLOB)」** bölümü → gerçek USDC, `live.db` açık/kapalı işlemler
- **Paper Open Positions** → demo pozisyonlar (eskisi gibi)

```bash
./.venv/bin/python dashboard.py    # veya run_paper_stack.sh
./run_live_scanner.sh              # canlı emirler (ayrı terminal)
```

İsteğe bağlı tam ekran canlı panel: `./run_live_dashboard.sh` → http://127.0.0.1:8002

## Çıkış kuralı (canlı)

`live.scanner.env`: stake'in **%2**'si kâr → TP, **%2**'si zarar → SL. EXP / STALE / MAX_HOLD kapalı.

## Güvenlik

- Ana `.env` dosyasına `POLYMARKET_LIVE_TRADING=1` **yazma** — yanlışlıkla paper tarayıcıyı canlı yapar.
- İki `momentum_scanner` aynı DB'ye yazmasın.
