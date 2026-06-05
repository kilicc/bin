/* MEGA Canlı dashboard */
(function () {
  "use strict";

  const MODE_ID = "mega";
  const POLL_MS = 900;
  const TICK_POLL_MS = 150;
  const SNAP_POLL_OPEN_MS = 1800;
  const FULL_POLL_MS = 8000;
  const HERO_TICK_MS = 500;
  let pollTick = 0;
  let pollTimer = null;
  let tickTimer = null;
  let tickInflight = false;
  let lastFullPollTs = 0;
  let snapshotInflight = false;
  let snapshotPending = null;
  const hybridChartCache = new Map();

  function positionAgeSec(p) {
    if (p.duration_sec != null && Number.isFinite(Number(p.duration_sec))) {
      return Number(p.duration_sec);
    }
    const et = Number(p.entry_time || 0);
    if (et > 0) return Math.max(0, Date.now() / 1000 - et);
    return null;
  }

  function renderPositionHero(p) {
    const hero = document.getElementById("position-hero");
    const hint = document.getElementById("chart-hint");
    if (!hero) return;
    if (!p) {
      hero.classList.add("hidden");
      if (hint) hint.classList.remove("hidden");
      return;
    }
    hero.classList.remove("hidden");
    if (hint) hint.classList.add("hidden");

    const sym = (p.symbol || "").replace("USDT", "");
    const side = String(p.side || "LONG").toUpperCase();
    const unreal = liveUpnl(p);
    const tpPct = Math.round(tpProgress(p) * 100);
    const dur = positionAgeSec(p);

    setText("hero-symbol", sym);
    const sideEl = document.getElementById("hero-side");
    if (sideEl) {
      setTextNode(sideEl, side);
      syncSideClass(sideEl, side);
    }
    const upnlEl = document.getElementById("hero-upnl");
    if (upnlEl) {
      setTextNode(upnlEl, fmtUsd(unreal));
      syncToneClass(upnlEl, "val", pnlClass(unreal));
    }
    setText("hero-tp-pct", tpPct + "%");
    setText(
      "hero-tp-usd",
      fmtUsd(p.tp_net_target_usd || p.tp_target_usd)
    );
    setText("hero-duration", dur != null ? fmtDuration(dur) : "—");
    const bar = document.getElementById("hero-tp-bar");
    if (bar) bar.style.width = tpPct + "%";
  }

  function renderPositionDetail(p) {
    const el = document.getElementById("position-detail");
    if (!el) return;
    if (!p) {
      el.classList.add("hidden");
      return;
    }
    ensurePositionDetail();
    el.classList.remove("hidden");
    const vals = detailValues(p);
    DETAIL_FIELDS.forEach((key) => {
      const node = el.querySelector('[data-df="' + key + '"]');
      if (!node) return;
      setTextNode(node, vals[key]);
      if (key === "upnl") syncToneClass(node, "val", vals._upnlTone);
    });
  }

  function fmtNum(n, dec) {
    const v = Number(n);
    if (!Number.isFinite(v)) return "—";
    return v.toLocaleString("en-US", {
      minimumFractionDigits: dec || 0,
      maximumFractionDigits: dec || 4,
    });
  }

  const fmtUsd = (n) => {
    const v = Number(n);
    if (!Number.isFinite(v)) return "—";
    const sign = v < 0 ? "-" : "";
    return sign + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  function numUsd(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  const fmtPx = (n) => {
    const v = Number(n);
    if (!Number.isFinite(v)) return "—";
    if (v >= 1000) return v.toFixed(2);
    if (v >= 1) return v.toFixed(4);
    return v.toFixed(6);
  };

  function priceDecimalsFor(v) {
    const n = Number(v);
    if (!Number.isFinite(n) || n <= 0) return 4;
    if (n >= 1000) return 2;
    if (n >= 1) return 4;
    return 6;
  }

  function fmtPxFixed(n, decimals) {
    const v = Number(n);
    if (!Number.isFinite(v)) return "—";
    return v.toFixed(decimals);
  }

  function openRowPriceDecimals(p) {
    const ex = p.exchange_display || {};
    const ref = Number(
      ex.entryPrice ?? p.entry_price ?? ex.markPrice ?? p.current_price ?? 0
    );
    return priceDecimalsFor(ref);
  }

  function openRowPrices(p, pxDec) {
    const ex = p.exchange_display || {};
    const entryNum = Number(ex.entryPrice ?? p.entry_price);
    const markNum = Number(ex.markPrice ?? p.current_price);
    return {
      entry: fmtPxFixed(entryNum, pxDec),
      mark: fmtPxFixed(markNum, pxDec),
    };
  }
  const fmtPct = (n) => {
    const v = Number(n);
    if (!Number.isFinite(v)) return "—";
    return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
  };
  const fmtDuration = (sec) => {
    const s = Number(sec);
    if (!Number.isFinite(s) || s < 0) return "—";
    if (s < 60) return Math.round(s) + "s";
    const m = Math.floor(s / 60);
    const r = Math.round(s % 60);
    if (m < 60) return m + "m " + r + "s";
    return Math.floor(m / 60) + "h " + (m % 60) + "m";
  };
  const esc = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;");

  const state = { snap: null, selectedIdx: 0, open: [], lastHeroKey: "" };

  const MOTOR_PILLS = [
    { id: "fast", label: "Evren", warn: 400, bad: 900, val: (hb) => hb && hb.fast_tick_ms },
    { id: "scan", label: "Scan", warn: 2500, bad: 5500, val: (hb) => hb && hb.motor_eval_ms },
    { id: "pos", label: "Poz", warn: 65, bad: 130, val: (hb) => hb && hb.position_tick_ms },
    { id: "exit", label: "Exit", warn: 80, bad: 160, val: (hb) => hb && hb.mega && hb.mega.last_exit_tick_ms },
    {
      id: "psync",
      label: "Pos↻",
      warn: 120,
      bad: 320,
      val: (hb) => hb && hb.mega && hb.mega.position_sync && hb.mega.position_sync.last_duration_ms,
    },
    {
      id: "csync",
      label: "Close↻",
      warn: 900,
      bad: 2200,
      val: (hb) => hb && hb.mega && hb.mega.close_sync && hb.mega.close_sync.last_duration_ms,
    },
    {
      id: "tpv",
      label: "TP⇄",
      warn: 1400,
      bad: 3200,
      val: (hb) => hb && hb.mega && hb.mega.last_tp_verify_ms,
    },
    {
      id: "hub",
      label: "Hub",
      warn: 180,
      bad: 450,
      val: (hb) =>
        hb && hb.mega && hb.mega.async_hub && hb.mega.async_hub.cache && hb.mega.async_hub.cache.lag_ms,
    },
    { id: "cache", label: "Cache", warn: 150, bad: 450, val: (hb) => hb && hb.mega && hb.mega.cache_age_ms },
    {
      id: "mark",
      label: "Mark",
      warn: 320,
      bad: 900,
      val: (hb) => hb && hb.price_feed && hb.price_feed.mark_ws && hb.price_feed.mark_ws.lag_ms,
    },
    {
      id: "book",
      label: "Book",
      warn: 450,
      bad: 1100,
      val: (hb) => hb && hb.price_feed && hb.price_feed.fast_feed && hb.price_feed.fast_feed.lag_ms,
    },
    {
      id: "rest",
      label: "REST",
      warn: 500,
      bad: 1300,
      val: (hb) => {
        if (!hb) return null;
        const n = Number(hb.exchange_poll_ms || hb.exchange_api_ema_ms);
        return Number.isFinite(n) && n > 0 ? n : null;
      },
    },
  ];

  function fmtMotorMs(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    if (n >= 1000) return (n / 1000).toFixed(1) + "s";
    return Math.round(n) + "ms";
  }

  function motorPillTone(v, spec) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "off";
    if (n >= spec.bad) return "bad";
    if (n >= spec.warn) return "slow";
    return "ok";
  }

  function ensureMotorStrip() {
    const strip = document.getElementById("motor-timing-strip");
    if (!strip || strip.dataset.ready === "1") return strip;
    strip.innerHTML = MOTOR_PILLS.map(
      (p) =>
        '<div class="mega-motor-pill off" data-motor-id="' +
        p.id +
        '"><span class="lbl">' +
        esc(p.label) +
        '</span><span class="val">—</span></div>'
    ).join("");
    strip.dataset.ready = "1";
    return strip;
  }

  function renderMotorStrip(hb) {
    const strip = ensureMotorStrip();
    if (!strip) return;
    MOTOR_PILLS.forEach((spec) => {
      const pill = strip.querySelector('[data-motor-id="' + spec.id + '"]');
      if (!pill) return;
      const raw = spec.val(hb);
      const tone = motorPillTone(raw, spec);
      const valEl = pill.querySelector(".val");
      setTextNode(valEl, fmtMotorMs(raw));
      const nextCls = "mega-motor-pill " + tone;
      if (pill.className !== nextCls) pill.className = nextCls;
    });
  }

  const DETAIL_FIELDS = [
    "symbol",
    "size",
    "entry",
    "mark",
    "breakEven",
    "notional",
    "margin",
    "upnl",
    "netTp",
    "feeRt",
    "entryFee",
    "fillNet",
    "duration",
    "apiAge",
    "source",
  ];

  function setText(id, text) {
    const el = document.getElementById(id);
    if (el && el.textContent !== text) el.textContent = text;
  }

  function setTextNode(el, text) {
    if (el && el.textContent !== text) el.textContent = text;
  }

  function syncToneClass(el, base, tone) {
    if (!el) return;
    const next = base + " " + (tone || "neutral");
    if (el.className !== next) el.className = next;
  }

  function syncSideClass(el, side) {
    if (!el) return;
    const next = "mega-hero-side " + String(side || "long").toLowerCase();
    if (el.className !== next) el.className = next;
  }

  function syncRowSelected(tr, selected) {
    if (!tr) return;
    const next = "open-row" + (selected ? " selected" : "");
    if (tr.className !== next) tr.className = next;
  }

  function syncPnlCell(td, unreal) {
    if (!td) return;
    const cls = pnlClass(unreal);
    setTextNode(td, fmtUsd(unreal));
    const tone = cls === "pos" ? "pos" : cls === "neg" ? "neg" : "neutral";
    const next = "cell-num cell-upnl " + tone;
    if (td.className !== next) td.className = next;
  }

  function openRowKey(p, i) {
    return String(p.id != null ? p.id : p.symbol || i);
  }

  function detailValues(p) {
    const ex = p.exchange_display || {};
    const sym = (p.symbol || "").replace("USDT", "");
    const side = String(p.side || "LONG").toUpperCase();
    const dur = positionAgeSec(p);
    const ageMs = p.exchange_data_age_ms;
    const unreal = liveUpnl(p);
    return {
      symbol: sym + " · " + side,
      size: ex.positionAmt || fmtNum(p.size, 4),
      entry: fmtPxFixed(ex.entryPrice ?? p.entry_price, priceDecimalsFor(ex.entryPrice ?? p.entry_price)),
      mark: fmtPxFixed(ex.markPrice ?? p.current_price, priceDecimalsFor(ex.markPrice ?? p.current_price)),
      breakEven: fmtPxFixed(ex.breakEvenPrice ?? p.break_even_price, priceDecimalsFor(ex.breakEvenPrice ?? p.break_even_price)),
      notional: ex.notional || fmtUsd(p.position_value),
      margin: ex.isolatedMargin || ex.positionInitialMargin || fmtUsd(p.margin_used || p.stake_usd),
      upnl: fmtUsd(unreal),
      netTp: fmtUsd(p.tp_net_target_usd || p.tp_target_usd),
      feeRt: fmtUsd(p.round_trip_fee_est_usd),
      entryFee: p.entry_fee != null ? fmtUsd(p.entry_fee) : "—",
      fillNet: p.fill_net_est != null ? fmtUsd(p.fill_net_est) : "—",
      duration: dur != null ? fmtDuration(dur) : "—",
      apiAge:
        p.positions_cache_age_ms != null
          ? p.positions_cache_age_ms + "ms"
          : ageMs != null
            ? ageMs + "ms"
            : "—",
      source: p.data_source || "binance",
      _upnlTone: pnlClass(unreal),
    };
  }

  function ensurePositionDetail() {
    const el = document.getElementById("position-detail");
    if (!el || el.querySelector("[data-detail-grid]")) return;
    const labels = [
      "Sembol",
      "Miktar",
      "Giriş",
      "Mark",
      "Break-even",
      "Notional",
      "Margin",
      "uPnL",
      "Net TP",
      "Fee (RT)",
      "Giriş fee",
      "Fill net",
      "Süre",
      "API yaş",
      "Kaynak",
    ];
    el.innerHTML =
      '<div class="mega-detail-grid" data-detail-grid>' +
      labels
        .map(
          (lbl, i) =>
            '<div class="mega-detail-item"><span class="lbl">' +
            esc(lbl) +
            '</span><span class="val" data-df="' +
            DETAIL_FIELDS[i] +
            '">—</span></div>'
        )
        .join("") +
      "</div>";
  }

  const statusLabel = {
    scan: "Taranıyor",
    candidate: "Aday",
    reject: "Red",
    opened: "Açıldı",
    skip: "Atlandı",
  };

  function statusClass(st) {
    if (st === "opened" || st === "candidate") return "ok";
    if (st === "reject") return "bad";
    if (st === "skip") return "warn";
    return "neutral";
  }

  function pnlClass(v) {
    const n = Number(v);
    if (!Number.isFinite(n) || n === 0) return "neutral";
    return n > 0 ? "pos" : "neg";
  }

  function liveUpnl(p) {
    if (!p) return 0;
    const motor = Number(p.unrealized_pnl);
    if (Number.isFinite(motor)) return motor;
    if (p.exchange_unrealized_pnl != null && Number.isFinite(Number(p.exchange_unrealized_pnl))) {
      return Number(p.exchange_unrealized_pnl);
    }
    const ex = p.exchange_display || {};
    if (ex.unRealizedProfit != null && ex.unRealizedProfit !== "") {
      return Number(ex.unRealizedProfit);
    }
    return 0;
  }

  function tpTargetUsd(p) {
    return Number(p.tp_net_target_usd || p.tp_target_usd || 0);
  }

  function tpProgress(p) {
    const target = tpTargetUsd(p);
    const unreal = liveUpnl(p);
    if (target <= 0) return 0;
    if (unreal <= 0) return 0;
    if (p.tp_progress_pct != null && Number.isFinite(Number(p.tp_progress_pct))) {
      return Math.max(0, Math.min(1, Number(p.tp_progress_pct) / 100));
    }
    return Math.max(0, Math.min(1, unreal / target));
  }

  function updateTpCell(td, p) {
    if (!td) return;
    const tpUsd = Number(p.tp_net_target_usd || p.tp_target_usd || 0);
    const tpPct = Math.round(tpProgress(p) * 100);
    const peakPct = Number(p.tp_peak_progress_pct || 0);
    const peakHint = peakPct > tpPct + 2 ? " · tepe " + Math.round(peakPct) + "%" : "";
    let fill = td.querySelector(".mega-tp-mini-fill");
    let label = td.querySelector(".mega-tp-mini-label");
    if (!fill || !label) {
      td.innerHTML =
        '<div class="mega-tp-mini">' +
        '<div class="mega-tp-mini-track"><div class="mega-tp-mini-fill"></div></div>' +
        '<span class="mega-tp-mini-label"></span></div>';
      fill = td.querySelector(".mega-tp-mini-fill");
      label = td.querySelector(".mega-tp-mini-label");
    }
    if (fill) fill.style.width = tpPct + "%";
    if (label) {
      setTextNode(label, fmtUsd(tpUsd) + " · " + tpPct + "%" + peakHint);
    }
  }

  function createOpenRow(p, i, selected) {
    const sym = (p.symbol || "").replace("USDT", "");
    const side = String(p.side || "LONG").toUpperCase();
    const sideCls = side === "SHORT" ? "side-short" : "side-long";
    const tr = document.createElement("tr");
    tr.className = "open-row" + (selected ? " selected" : "");
    tr.dataset.idx = String(i);
    tr.dataset.rowKey = openRowKey(p, i);
    tr.dataset.pxDec = String(openRowPriceDecimals(p));
    tr.innerHTML =
      "<td><strong></strong></td>" +
      '<td class="' +
      sideCls +
      '"></td>' +
      "<td class='cell-num cell-lev'></td>" +
      "<td class='cell-num cell-stake'></td>" +
      "<td class='cell-num cell-px'></td>" +
      "<td class='cell-num cell-px'></td>" +
      "<td class='cell-num cell-upnl'></td>" +
      "<td class='mega-tp-cell'></td>" +
      "<td class='cell-num cell-dur'></td>";
    tr.children[0].querySelector("strong").textContent = sym;
    tr.children[1].textContent = side;
    updateOpenRow(tr, p, i, selected);
    return tr;
  }

  function updateOpenRow(tr, p, i, selected) {
    if (!tr) return;
    tr.dataset.idx = String(i);
    syncRowSelected(tr, selected);
    const side = String(p.side || "LONG").toUpperCase();
    const sideCls = side === "SHORT" ? "side-short" : "side-long";
    const sideTd = tr.children[1];
    if (sideTd) {
      sideTd.textContent = side;
      if (sideTd.className !== sideCls) sideTd.className = sideCls;
    }
    const lev = Number(p.leverage || 2);
    const stake = Number(p.stake_usd || 0);
    const pxDec = Number(tr.dataset.pxDec) || openRowPriceDecimals(p);
    tr.dataset.pxDec = String(pxDec);
    const prices = openRowPrices(p, pxDec);
    const dur = positionAgeSec(p);
    setTextNode(tr.children[2], lev + "x");
    setTextNode(tr.children[3], fmtUsd(stake));
    setTextNode(tr.children[4], prices.entry);
    setTextNode(tr.children[5], prices.mark);
    syncPnlCell(tr.children[6], liveUpnl(p));
    updateTpCell(tr.children[7], p);
    setTextNode(tr.children[8], dur != null ? fmtDuration(dur) : "—");
  }

  function tpCellHtml(p) {
    const tpUsd = Number(p.tp_net_target_usd || p.tp_target_usd || 0);
    const tpPct = Math.round(tpProgress(p) * 100);
    const peakPct = Number(p.tp_peak_progress_pct || 0);
    const peakHint =
      peakPct > tpPct + 2 ? " · tepe " + Math.round(peakPct) + "%" : "";
    return (
      '<td class="mega-tp-cell">' +
      '<div class="mega-tp-mini">' +
      '<div class="mega-tp-mini-track"><div class="mega-tp-mini-fill" style="width:' +
      tpPct +
      '%"></div></div>' +
      '<span class="mega-tp-mini-label">' +
      fmtUsd(tpUsd) +
      " · " +
      tpPct +
      "%" +
      peakHint +
      "</span></div></td>"
    );
  }

  function chartsReady() {
    return window.TradingCharts && window.LightweightCharts;
  }

  function renderKpis(snap) {
    const summ = (snap && snap.summary) || {};
    const wallet = (snap && snap.wallet) || {};
    const scan = (snap && snap.scan) || {};
    const isLive = !!(snap && snap.live && !snap.paper_sim);
    const isPaperSim = !!(snap && (snap.paper_sim || (!isLive && !wallet.total_wallet_balance)));

    const anchor = summ.session_anchor ?? summ.starting_capital;
    const closedDeduped = dedupeClosedRows(snap.closed || []);
    let sessionPnl = closedDeduped.reduce((acc, c) => {
      const n = Number(c.final_pnl ?? c.wallet_pnl ?? c.net_pnl ?? c.pnl_usd ?? 0);
      return acc + (Number.isFinite(n) ? n : 0);
    }, 0);
    if (!closedDeduped.length && summ.realized_pnl != null && Number.isFinite(Number(summ.realized_pnl))) {
      sessionPnl = Number(summ.realized_pnl);
    }
    const openUnreal = (snap.open || []).reduce(
      (acc, p) => acc + Number(p.unrealized_pnl ?? p.exchange_unrealized_pnl ?? 0),
      0
    );
    let bookBal =
      numUsd(summ.current_capital) ??
      numUsd(summ.equity) ??
      numUsd(summ.balance);
    const walletBal =
      numUsd(wallet.total_margin_balance) ??
      numUsd(wallet.total_wallet_balance) ??
      numUsd(wallet.usdt_balance);
    if (isPaperSim && anchor && closedDeduped.length) {
      const computedBal = Number(anchor) + sessionPnl + openUnreal;
      if (Number.isFinite(computedBal) && computedBal > 0) {
        bookBal = computedBal;
      }
    }
    const bal =
      bookBal != null && bookBal > 0
        ? bookBal
        : walletBal != null && walletBal > 0
          ? walletBal
          : anchor;
    const margin = bal;
    const avail =
      numUsd(summ.available_capital) ??
      numUsd(summ.available_balance) ??
      numUsd(wallet.available_balance) ??
      numUsd(wallet.usdt_available) ??
      bal;
    const unreal = wallet.total_unrealized_pnl ?? summ.unrealized_pnl;
    const totalEquityPnl =
      anchor != null && bal != null && Number(anchor) > 0
        ? Number(bal) - Number(anchor)
        : summ.total_pnl != null && Number.isFinite(Number(summ.total_pnl))
          ? Number(summ.total_pnl)
          : sessionPnl + Number(unreal || 0);
    const sessionPct =
      anchor > 0 && Number.isFinite(sessionPnl)
        ? (sessionPnl / Number(anchor)) * 100
        : null;
    const openN = summ.open_count ?? (snap.open || []).length;
    const closedN = closedDeduped.length || summ.closed_trades || 0;
    const wr = summ.win_rate;
    const maxOpen = scan.max_open ?? 4;
    const queue = scan.motor_queue ?? 0;

    const balEl = document.getElementById("kpi-balance");
    if (balEl) {
      setTextNode(balEl, fmtUsd(margin || bal));
      syncToneClass(balEl, "mega-kpi-value num-usd", "neutral");
    }
    const balSub = [];
    if (anchor) balSub.push("Anchor " + fmtUsd(anchor));
    if (avail != null) balSub.push("Kullanılabilir " + fmtUsd(avail));
    if (wallet.api_base) balSub.push(String(wallet.api_base).replace("https://", ""));
    setText("kpi-balance-sub", balSub.join(" · ") || (isLive ? "Binance API" : "Paper kitap"));

    const pnlEl = document.getElementById("kpi-pnl");
    if (pnlEl) {
      setTextNode(pnlEl, fmtUsd(sessionPnl));
      syncToneClass(pnlEl, "mega-kpi-value num-usd", pnlClass(sessionPnl));
    }
    const pnlSub = [];
    if (sessionPct != null) pnlSub.push(fmtPct(sessionPct));
    pnlSub.push("Realize " + fmtUsd(sessionPnl));
    if (
      Number.isFinite(totalEquityPnl) &&
      Math.abs(totalEquityPnl - sessionPnl) > 0.05
    ) {
      pnlSub.push("Toplam " + fmtUsd(totalEquityPnl) + " (açık dahil)");
    }
    setText("kpi-pnl-sub", pnlSub.join(" · ") || "Kapalı işlemler toplamı");

    const upnlEl = document.getElementById("kpi-upnl");
    if (upnlEl) {
      setTextNode(upnlEl, fmtUsd(unreal));
      syncToneClass(upnlEl, "mega-kpi-value num-usd", pnlClass(unreal));
    }
    setText("kpi-upnl-sub", "Mark · " + openN + " açık pozisyon");

    const openEl = document.getElementById("kpi-open");
    if (openEl) {
      setTextNode(openEl, openN + " / " + maxOpen);
      syncToneClass(openEl, "mega-kpi-value num-slot", "neutral");
    }
    setText("kpi-open-sub", "MEGA motor · stake $500–$1500" + (queue ? " · kuyruk " + queue : ""));
    setText("open-count-pill", openN + " / " + maxOpen);

    const wrEl = document.getElementById("kpi-winrate");
    if (wrEl) {
      setTextNode(wrEl, wr != null ? Number(wr).toFixed(1) + "%" : closedN ? "0.0%" : "—");
      syncToneClass(wrEl, "mega-kpi-value num-pct", "neutral");
    }
    setText("kpi-winrate-sub", closedN + " kapalı · oturum kayıtları");
    setText("closed-count-pill", String(closedN));

    const stakeEl = document.getElementById("kpi-stake");
    if (stakeEl) {
      setTextNode(stakeEl, queue + " kuyruk");
      syncToneClass(stakeEl, "mega-kpi-value num-queue", "neutral");
    }
    const stakeSub = [];
    if (scan.last_scan_age_sec != null) stakeSub.push("Tur " + scan.last_scan_age_sec + "s önce");
    if (scan.candidates_recent != null) stakeSub.push(scan.candidates_recent + " aday");
    if (scan.reject_total != null) stakeSub.push(scan.reject_total + " red");
    setText("kpi-stake-sub", stakeSub.join(" · ") || "Berserk2 tarama → MEGA kapı");

    const liveBadge = document.getElementById("badge-live");
    if (liveBadge) {
      liveBadge.textContent = isLive ? "CANLI" : "BAĞLANIYOR";
      liveBadge.classList.toggle("live", isLive);
      liveBadge.classList.toggle("pending", !isLive);
    }

    const note = document.getElementById("display-note");
    if (note && isLive && anchor) {
      note.textContent =
        "MEGA demo · anchor " + fmtUsd(anchor) + " · margin " + fmtUsd(margin || bal);
    }
  }

  function renderHeroChart(p) {
    if (!chartsReady() || !p) {
      if (window.TradingCharts) window.TradingCharts.hideOhlcBar();
      return;
    }
    window.TradingCharts.plotPosition("chart-hero", p, { compact: false });
  }

  function regimeCountdownLabel(regime) {
    const rg = regime || {};
    const cd = rg.change_countdown || {};
    if (!rg.enabled) return "—";
    if (cd.kind === "locked") {
      return cd.remaining_label || rg.open_count + "/" + rg.max_open + " kilit";
    }
    if (cd.kind === "transition_active") {
      return "Seek aktif";
    }
    const tail = cd.detail ? " · " + cd.detail : "";
    return (cd.remaining_label || "—") + tail;
  }

  function renderVolChips(vol, regime) {
    const el = document.getElementById("vol-chips");
    const meta = document.getElementById("vol-meta");
    const v = vol || {};
    const rg = regime || {};
    const cd = rg.change_countdown || {};
    const rgName = rg.effective_regime || rg.regime || "—";
    if (meta) {
      const age = v.age_sec != null ? v.age_sec + "s önce" : "—";
      const uni = v.scan_universe_n != null ? v.scan_universe_n + " coin" : "—";
      let cdTxt = "";
      if (cd.kind === "locked") {
        cdTxt = " · rejim kilitli " + (cd.remaining_label || "");
      } else if (cd.kind === "transition_active") {
        cdTxt = " · seek aktif";
      } else if (cd.remaining_sec != null && cd.remaining_sec > 0) {
        cdTxt =
          " · değişim ~" +
          Math.round(cd.remaining_sec) +
          "s" +
          (cd.target_regime ? " → " + cd.target_regime : "");
      }
      meta.textContent =
        rgName + cdTxt + " · " + uni + " · " + (v.hot || []).length + " hot · " + age;
    }
    if (!el) return;
    const coins = [].concat(v.hot || []).concat(v.warm || []).concat(v.cold || []);
    if (!v.enabled || !coins.length) {
      el.innerHTML =
        '<span class="mega-scan-empty">Volatilite taraması bekleniyor…</span>';
      return;
    }
    el.innerHTML = coins
      .map((c) => {
        const tier = String(c.tier || "warm");
        const sym = esc((c.symbol || "").replace("USDT", ""));
        const ch = Number(c.change_pct ?? c.change);
        const chTxt = Number.isFinite(ch)
          ? (Math.abs(ch) < 0.01 ? ch.toFixed(4) : ch.toFixed(3)) + "%"
          : "";
        const vr = Number(c.vol_ratio);
        const vrTxt = Number.isFinite(vr) && vr > 1.01 ? " vol×" + vr.toFixed(2) : "";
        return (
          '<div class="mega-vol-chip ' +
          tier +
          '"><span class="sym">' +
          sym +
          "</span> " +
          chTxt +
          vrTxt +
          ' <span class="tier">' +
          tier +
          " #" +
          esc(String(c.rank || "?")) +
          "</span></div>"
        );
      })
      .join("");
  }

  function renderScanStats(scan) {
    const el = document.getElementById("scan-stats");
    if (!el) return;
    const sc = scan || {};
    const vol = sc.volatility || {};
    const regime = sc.market_regime || {};
    const trans = regime.transition || {};
    const cd = regime.change_countdown || {};
    const topReject = ((sc.reject_top || [])[0] || {}).reason || "—";
    const regimeLbl = trans.active
      ? (regime.regime || "—") + "+transition"
      : regime.effective_regime || regime.regime || "—";
    let geçişVal = regimeCountdownLabel(regime);
    if (cd.kind === "classification") {
      geçişVal = cd.remaining_label + " · " + (cd.detail || "");
    } else if (cd.kind === "transition" && cd.remaining_sec != null) {
      geçişVal =
        "Seek ~" +
        Math.round(cd.remaining_sec) +
        "s · idle " +
        Math.round(regime.idle_open_sec || 0) +
        "/" +
        Math.round(regime.idle_open_threshold_sec || 300) +
        "s";
    } else if (trans.active) {
      geçişVal = "açık " + (trans.reason || "") + " · " + Math.round(trans.since_sec || 0) + "s";
    }
    const stats = [
      ["Rejim", regimeLbl],
      ["Değişim", geçişVal],
      ["Vol hot", (vol.hot || []).length || "—"],
      ["Vol warm", (vol.warm || []).length || "—"],
      ["Son tur", sc.last_scan_age_sec != null ? sc.last_scan_age_sec + "s" : "—"],
      ["Aday", sc.candidates_recent ?? sc.candidates_last_n ?? "—"],
      ["Red", sc.reject_total ?? "—"],
      ["Top red", topReject.replace(/^mega_/, "")],
    ];
    const existing = el.querySelectorAll(".mega-scan-stat");
    if (existing.length !== stats.length) {
      el.innerHTML = stats
        .map(
          ([lbl, val]) =>
            '<div class="mega-scan-stat"><span class="lbl">' +
            esc(lbl) +
            '</span><span class="val">' +
            esc(String(val)) +
            "</span></div>"
        )
        .join("");
      return;
    }
    stats.forEach(([lbl, val], i) => {
      const box = existing[i];
      if (!box) return;
      const valEl = box.querySelector(".val");
      const lblEl = box.querySelector(".lbl");
      if (lblEl && lblEl.textContent !== lbl) lblEl.textContent = lbl;
      if (valEl) setTextNode(valEl, String(val));
    });
  }

  function renderScan(scan) {
    const sc = scan || {};
    renderScanStats(sc);
    renderVolChips(sc.volatility || {}, sc.market_regime || {});
    const parts = [
      sc.last_scan_age_sec != null ? "Son tur " + sc.last_scan_age_sec + "s önce" : null,
      sc.eval_last_n != null ? "Eval " + sc.eval_last_n : null,
      sc.candidates_last_n != null ? "Aday " + sc.candidates_last_n : null,
      sc.motor_queue != null ? "Kuyruk " + sc.motor_queue : null,
      sc.reject_total != null ? "Red " + sc.reject_total : null,
      (sc.volatility || {}).enabled ? "Vol scan açık" : null,
      (sc.market_regime || {}).regime
        ? "Rejim " +
          ((sc.market_regime.transition || {}).active
            ? sc.market_regime.regime + "+transition"
            : sc.market_regime.effective_regime || sc.market_regime.regime) +
          (sc.market_regime.change_countdown &&
          sc.market_regime.change_countdown.remaining_sec != null &&
          sc.market_regime.change_countdown.kind !== "locked" &&
          sc.market_regime.change_countdown.kind !== "transition_active"
            ? " · değişim ~" +
              Math.round(sc.market_regime.change_countdown.remaining_sec) +
              "s"
            : sc.market_regime.change_countdown &&
                sc.market_regime.change_countdown.kind === "locked"
              ? " · kilit " +
                (sc.market_regime.change_countdown.remaining_label || "")
              : "")
        : null,
    ].filter(Boolean);
    setText("scan-meta", parts.join(" · ") || "Volatilite + Berserk2 → MEGA giriş kapısı");

    const chips = document.getElementById("scan-chips");
    if (!chips) return;
    const pool = []
      .concat(sc.candidates || [])
      .concat(
        (sc.watching || []).map((w) => ({
          ...w,
          status: "watch",
          ui_label: w.ui_label || "Kuyruk",
        }))
      );
    const uniq = [];
    const seen = new Set();
    for (const row of pool) {
      const k = (row.symbol || "") + ":" + (row.side || row.type || "");
      if (seen.has(k)) continue;
      seen.add(k);
      uniq.push(row);
      if (uniq.length >= 14) break;
    }
    if (!uniq.length) {
      chips.innerHTML = '<span class="mega-scan-empty">Aktif aday yok — motor taraması bekleniyor</span>';
    } else {
      chips.innerHTML = uniq
        .map((r) => {
          const sym = esc((r.symbol || "").replace("USDT", ""));
          const side = String(r.side || r.type || "LONG").toUpperCase();
          const ch = Number(r.change);
          const chTxt = Number.isFinite(ch) ? (ch >= 0 ? "+" : "") + ch.toFixed(2) + "%" : "";
          const tag = r.status === "watch" ? r.ui_label || "Kuyruk" : statusLabel[r.status] || "Aday";
          return (
            '<div class="mega-signal-chip ' +
            side.toLowerCase() +
            '">' +
            '<span class="sym">' +
            sym +
            "</span> " +
            side +
            " " +
            chTxt +
            ' <span class="tag">' +
            esc(tag) +
            "</span></div>"
          );
        })
        .join("");
    }

    const body = document.getElementById("scan-body");
    if (!body) return;
    let feed = (sc.feed || []).slice(0, 50);
    if (!feed.length && sc.reject_buffer && sc.reject_buffer.last_20_rejects) {
      feed = sc.reject_buffer.last_20_rejects.map((r) => ({
        time: (r.timestamp || "").slice(11, 19),
        symbol: r.symbol,
        side: r.strength || "—",
        change: null,
        mega_score: r.score,
        status: "reject",
        reason: r.reason,
      }));
    }
    if (!feed.length) {
      body.innerHTML = '<tr><td colspan="7" class="mega-empty-cell">Henüz tarama kaydı yok</td></tr>';
      return;
    }
    body.innerHTML = feed
      .map((r) => {
        const st = r.status || "scan";
        const side = String(r.side || "LONG").toUpperCase();
        const sideCls = side === "SHORT" ? "side-short" : "side-long";
        const ch = Number(r.change);
        const score =
          r.mega_score != null
            ? Number(r.mega_score).toFixed(0)
            : r.strength
              ? esc(r.strength)
              : "—";
        const noteParts = [];
        if (r.vol_tier && r.vol_tier !== "off" && r.vol_tier !== "cold") {
          noteParts.push("vol:" + r.vol_tier);
        }
        if (r.reason) noteParts.push(r.reason);
        const note = noteParts.join(" · ") || "—";
        return (
          "<tr>" +
          "<td class='mono'>" +
          esc(r.time || "—") +
          "</td>" +
          "<td><strong>" +
          esc((r.symbol || "").replace("USDT", "")) +
          "</strong></td>" +
          '<td class="' +
          sideCls +
          '">' +
          side +
          "</td>" +
          "<td>" +
          (Number.isFinite(ch) ? (ch >= 0 ? "+" : "") + ch.toFixed(2) + "%" : "—") +
          "</td>" +
          "<td>" +
          score +
          "</td>" +
          '<td><span class="mega-status ' +
          statusClass(st) +
          '">' +
          esc(statusLabel[st] || st) +
          "</span></td>" +
          "<td>" +
          esc(note) +
          "</td>" +
          "</tr>"
        );
      })
      .join("");
  }

  function renderOpenTable(openList) {
    const body = document.getElementById("open-body");
    if (!body) return;
    const rows = openList || [];
    state.open = rows;
    if (!rows.length) {
      state.lastHeroKey = "";
      body.innerHTML =
        '<tr><td colspan="9" class="mega-empty-cell">Henüz açık MEGA pozisyon yok</td></tr>';
      renderHeroChart(null);
      renderPositionDetail(null);
      renderPositionHero(null);
      return;
    }
    if (state.selectedIdx >= rows.length) state.selectedIdx = 0;

    const keys = rows.map((p, i) => openRowKey(p, i));
    const existing = Array.from(body.querySelectorAll("tr.open-row"));
    const existingKeys = existing.map((tr) => tr.dataset.rowKey || "");
    const structureChanged =
      keys.length !== existingKeys.length || keys.some((k, i) => k !== existingKeys[i]);

    if (structureChanged) {
      body.innerHTML = "";
      rows.forEach((p, i) => {
        body.appendChild(createOpenRow(p, i, i === state.selectedIdx));
      });
    } else {
      rows.forEach((p, i) => updateOpenRow(existing[i], p, i, i === state.selectedIdx));
    }

    const selected = rows[state.selectedIdx];
    const heroKey = openRowKey(selected, state.selectedIdx);
    if (state.lastHeroKey !== heroKey) {
      state.lastHeroKey = heroKey;
      renderHeroChart(selected);
    }
    renderPositionDetail(selected);
    renderPositionHero(selected);
  }

  function bindOpenTable() {
    const body = document.getElementById("open-body");
    if (!body || body.dataset.megaBound === "1") return;
    body.dataset.megaBound = "1";
    body.addEventListener("click", (ev) => {
      const tr = ev.target.closest("tr.open-row");
      if (!tr) return;
      const idx = Number(tr.dataset.idx);
      if (!Number.isFinite(idx)) return;
      state.selectedIdx = idx;
      Array.from(body.querySelectorAll("tr.open-row")).forEach((row, i) => {
        syncRowSelected(row, i === state.selectedIdx);
      });
      const selected = state.open[state.selectedIdx];
      const heroKey = selected ? openRowKey(selected, state.selectedIdx) : "";
      if (heroKey && state.lastHeroKey !== heroKey) {
        state.lastHeroKey = heroKey;
        renderHeroChart(selected);
      }
      renderPositionDetail(selected);
      renderPositionHero(selected);
    });
  }

  function closedExitTs(c) {
    const u = window.ClosedTradeUtils;
    if (u) return u.closedExitTs(c);
    const raw = Number(c.exit_time);
    if (Number.isFinite(raw) && raw > 0) return raw > 1e12 ? raw / 1000 : raw;
    const s = String(c.exit_time_str || c.exit_time_iso || "").trim();
    if (!s) return null;
    const t = Date.parse(s.replace(" ", "T") + (s.includes("Z") || s.includes("+") ? "" : "Z"));
    return Number.isFinite(t) ? t / 1000 : null;
  }

  function closedSameTrade(a, b) {
    if (String(a.symbol || "") !== String(b.symbol || "")) return false;
    if (String(a.side || "").toUpperCase() !== String(b.side || "").toUpperCase()) return false;
    const oidA = String(a.exchange_close_order_id || "").trim();
    const oidB = String(b.exchange_close_order_id || "").trim();
    if (oidA && oidB && oidA !== oidB) return false;
    const idA = Number(a.id);
    const idB = Number(b.id);
    if (idA > 0 && idA === idB) return true;
    const ta = closedExitTs(a);
    const tb = closedExitTs(b);
    if (ta != null && tb != null && Math.abs(ta - tb) > 180) return false;
    const netA = Math.round(Number(a.final_pnl ?? a.net_pnl ?? 0) * 100) / 100;
    const netB = Math.round(Number(b.final_pnl ?? b.net_pnl ?? 0) * 100) / 100;
    if (Math.abs(netA - netB) > 0.25) return false;
    const entryA = Number(a.entry_price || 0);
    const entryB = Number(b.entry_price || 0);
    if (entryA > 0 && entryB > 0 && Math.abs(entryA - entryB) / Math.max(entryA, entryB) > 0.004) {
      return false;
    }
    const exitA = Number(a.exit_price || 0);
    const exitB = Number(b.exit_price || 0);
    if (exitA > 0 && exitB > 0 && Math.abs(exitA - exitB) / Math.max(exitA, exitB) > 0.004) {
      return false;
    }
    return true;
  }

  function closedRowScore(c) {
    let score = 0;
    if (!c.backfilled && c.sync_source !== "exchange_userTrades") score += 100;
    if (Number(c.duration_sec || c.duration || 0) > 1) score += 50;
    if (c.opened_at_iso || c.entry_time) score += 20;
    if (String(c.exchange_close_order_id || "").trim()) score += 15;
    return score;
  }

  function mergeClosedRows(a, b) {
    const pickA = closedRowScore(a) >= closedRowScore(b);
    const primary = { ...(pickA ? a : b) };
    const secondary = pickA ? b : a;
    if (!primary.exchange_close_order_id && secondary.exchange_close_order_id) {
      primary.exchange_close_order_id = secondary.exchange_close_order_id;
    }
    return primary;
  }

  function dedupeClosedRows(closed) {
    const rows = Array.isArray(closed) ? closed.slice() : [];
    if (rows.length < 2) return rows;
    const kept = [];
    const used = new Array(rows.length).fill(false);
    for (let i = 0; i < rows.length; i++) {
      if (used[i]) continue;
      let merged = rows[i];
      used[i] = true;
      for (let j = i + 1; j < rows.length; j++) {
        if (used[j]) continue;
        if (closedSameTrade(merged, rows[j])) {
          merged = mergeClosedRows(merged, rows[j]);
          used[j] = true;
        }
      }
      kept.push(merged);
    }
    return kept;
  }

  function fmtClosedDt(c, field) {
    const u = window.ClosedTradeUtils;
    if (u) {
      if (field === "entry_time_str" || field === "opened_at_iso") {
        return u.fmtTrEntry(c);
      }
      if (field === "exit_time_str" || field === "exit_time_iso") {
        return u.fmtTrExit(c);
      }
    }
    const raw = c[field];
    if (!raw) return "—";
    const s = String(raw).trim();
    if (!s) return "—";
    if (/^\d+(\.\d+)?$/.test(s)) {
      const n = Number(s);
      const ms = n > 1e12 ? n : n * 1000;
      const d = new Date(ms);
      if (!Number.isNaN(d.getTime())) {
        return d.toISOString().slice(0, 19).replace("T", " ");
      }
    }
    return s.length > 19 ? s.slice(0, 19) : s;
  }

  function sortClosedForDisplay(closed) {
    const u = window.ClosedTradeUtils;
    const rows = dedupeClosedRows(closed || []);
    return u ? u.sortClosedByExitDesc(rows) : rows.slice().reverse();
  }

  function closedSourceLabel(c) {
    if (c.sim) return "SIM";
    if (c.fee_source === "binance_api" || c.exchange_settled) return "API";
    if (c.data_source) return String(c.data_source);
    if (c.signal_source) return String(c.signal_source);
    return "local";
  }

  function renderClosed(closed) {
    const body = document.getElementById("closed-body");
    if (!body) return;
    const rows = sortClosedForDisplay(closed).slice(0, 120);
    if (!rows.length) {
      body.innerHTML =
        '<tr><td colspan="22" class="mega-empty-cell">Bu oturumda kapanan işlem yok</td></tr>';
      return;
    }
    body.innerHTML = rows
      .map((c, idx) => {
        const net = Number(c.final_pnl ?? c.net_pnl ?? c.wallet_pnl ?? c.pnl_usd ?? 0);
        const gross = Number(c.pnl_usd ?? c.pnl_gross_usd ?? c.exchange_realized_pnl ?? net);
        const fees = Number(c.total_fees ?? 0);
        const stake = Number(c.stake_usd || 0);
        const netPct = Number(c.net_pnl_pct ?? (stake > 0 ? (net / stake) * 100 : 0));
        const grossPct = Number(c.pnl_pct ?? (stake > 0 ? (gross / stake) * 100 : 0));
        const entryPx = Number(c.entry_price || 0);
        const exitPx = Number(c.exit_price || 0);
        const size = Number(c.size || 0);
        const dur =
          c.duration_sec != null
            ? fmtDuration(c.duration_sec)
            : c.duration != null
              ? fmtDuration(c.duration)
              : c.hold_sec != null
                ? fmtDuration(c.hold_sec)
                : "—";
        const side = String(c.side || "LONG").toUpperCase();
        const sideCls = side === "SHORT" ? "side-short" : "side-long";
        const tpUsd = c.tp_net_target_usd ?? c.tp_target_usd;
        const maxU = c.max_unreal_seen;
        const minU = c.min_unreal_seen;
        const src = closedSourceLabel(c);
        const reason = String(c.exit_reason || "—");
        const rowNum = rows.length - idx;
        return (
          "<tr>" +
          "<td class='mono muted'>" + rowNum + "</td>" +
          "<td><strong>" + esc((c.symbol || "").replace("USDT", "")) + "</strong></td>" +
          '<td class="' + sideCls + '">' + esc(side) + "</td>" +
          "<td class='mono cell-num'>" + esc(c.leverage) + "x</td>" +
          "<td class='mono cell-num'>" + (size > 0 ? size.toPrecision(5) : "—") + "</td>" +
          "<td class='mono cell-num'>" + fmtUsd(c.stake_usd) + "</td>" +
          "<td class='mono cell-num'>" + (entryPx > 0 ? entryPx.toPrecision(6) : "—") + "</td>" +
          "<td class='mono cell-num'>" + (exitPx > 0 ? exitPx.toPrecision(6) : "—") + "</td>" +
          '<td class="cell-num ' + pnlClass(gross) + '">' + fmtUsd(gross) + "</td>" +
          '<td class="cell-num ' + pnlClass(grossPct) + '">' + fmtPct(grossPct) + "</td>" +
          "<td class='mono cell-num muted'>" + fmtUsd(fees) + "</td>" +
          '<td class="cell-num ' + pnlClass(net) + '">' + fmtUsd(net) + "</td>" +
          '<td class="cell-num ' + pnlClass(netPct) + '">' + fmtPct(netPct) + "</td>" +
          "<td class='mono cell-num'>" + (tpUsd != null ? fmtUsd(tpUsd) : "—") + "</td>" +
          "<td class='mono cell-num pos'>" + (maxU != null ? fmtUsd(maxU) : "—") + "</td>" +
          "<td class='mono cell-num neg'>" + (minU != null ? fmtUsd(minU) : "—") + "</td>" +
          "<td class='mono muted'>" + esc(c.signal_strength || c.signal_source || "—") + "</td>" +
          "<td class='mono muted'>" + esc(src) + "</td>" +
          "<td class='cell-reason' title='" + esc(reason) + "'>" + esc(reason) + "</td>" +
          "<td class='cell-dt'>" + esc(fmtClosedDt(c, "entry_time_str") || fmtClosedDt(c, "opened_at_iso")) + "</td>" +
          "<td class='cell-dt'>" + esc(fmtClosedDt(c, "exit_time_str") || fmtClosedDt(c, "exit_time_iso")) + "</td>" +
          "<td class='mono cell-num muted' title='Süre'>" + dur + "</td>" +
          "</tr>"
        );
      })
      .join("");
  }

  function setSnapshotLatency(ms) {
    const wrap = document.getElementById("snapshot-latency");
    const valEl = document.getElementById("poll-latency");
    if (!valEl) return;
    const n = Number(ms);
    const text = Number.isFinite(n) ? Math.round(n) + "ms" : "—";
    setTextNode(valEl, text);
    if (!wrap) return;
    let tone = "ok";
    if (Number.isFinite(n)) {
      if (n >= 2500) tone = "bad";
      else if (n >= 900) tone = "slow";
    } else {
      tone = "off";
    }
    const next = "snapshot-lat-pill " + tone;
    if (wrap.className !== next) wrap.className = next;
  }

  function mergeHybridCharts(openList) {
    if (!openList || !openList.length) return openList || [];
    return openList.map((p) => {
      const sym = String(p.symbol || "");
      const candles = p.chart_candles;
      const hasKlines =
        p.chart_source === "klines" && Array.isArray(candles) && candles.length > 0;
      if (hasKlines) {
        hybridChartCache.set(sym, {
          chart_candles: candles,
          chart_source: p.chart_source,
          price_history: p.price_history,
          time_history: p.time_history,
        });
        return p;
      }
      const cached = hybridChartCache.get(sym);
      if (!cached || !cached.chart_candles || !cached.chart_candles.length) return p;
      const mark = Number(p.current_price || 0);
      const merged = cached.chart_candles.map((c) => Object.assign({}, c));
      if (mark > 0 && merged.length) {
        const last = merged[merged.length - 1];
        last.close = mark;
        last.high = Math.max(Number(last.high), mark);
        last.low = Math.min(Number(last.low), mark);
      }
      return Object.assign({}, p, {
        chart_candles: merged,
        chart_source: "klines",
        price_history: merged.map((c) => Number(c.close)),
        time_history: cached.time_history,
      });
    });
  }

  function wantFullSnapshot(forceFull) {
    if (forceFull === true) return true;
    return Date.now() - lastFullPollTs >= FULL_POLL_MS;
  }

  async function runMegaFetch(forceFull) {
    const t0 = performance.now();
    let snap = null;
    let hb = null;
    const full = wantFullSnapshot(forceFull);
    if (full) lastFullPollTs = Date.now();
    pollTick += 1;
    try {
      const [snapRes, hbRes] = await Promise.all([
        fetch("/api/paper/" + MODE_ID + "/snapshot?light=" + (full ? "0" : "1")),
        fetch("/api/heartbeat"),
      ]);
      if (snapRes.ok) snap = await snapRes.json();
      else if (snapRes.status === 401 || snapRes.status === 403) {
        setText(
          "kpi-balance-sub",
          "Panel girişi gerekli — tarayıcıda kullanıcı: x  şifre: x369"
        );
      } else if (!snapRes.ok) {
        setText("kpi-balance-sub", "API hata " + snapRes.status + " — sayfayı yenileyin");
      }
      if (hbRes.ok) hb = await hbRes.json();
    } catch (_) {
      setText("kpi-balance-sub", "API yanıt vermedi — sunucu meşgul olabilir");
    }
    const lat = Math.round(performance.now() - t0);
    setSnapshotLatency(lat);
    renderMotorStrip(hb);

    state.snap = snap;
    if (snap && snap.ok) {
      if (snap.open && snap.open.length) snap.open = mergeHybridCharts(snap.open);
      renderKpis(snap);
      renderScan(snap.scan);
      renderOpenTable(snap.open);
      renderClosed(dedupeClosedRows(snap.closed || []));
      schedulePoll((snap.open || []).length > 0);
    } else if (!snap) {
      setText("kpi-balance-sub", "API yanıt vermedi — sunucu meşgul olabilir");
    }
    const ts = (snap && snap.ts) || new Date().toISOString();
    setText("footer-ts", String(ts).slice(0, 19).replace("T", " "));
    const overlay = document.getElementById("loading-overlay");
    if (overlay) overlay.classList.add("hidden");
  }

  async function fetchMega(forceFull) {
    if (snapshotInflight) {
      snapshotPending = {
        forceFull: !!(forceFull || (snapshotPending && snapshotPending.forceFull)),
      };
      return;
    }
    snapshotInflight = true;
    try {
      await runMegaFetch(forceFull);
    } finally {
      snapshotInflight = false;
      const pending = snapshotPending;
      snapshotPending = null;
      if (pending) await fetchMega(pending.forceFull);
    }
  }

  function tickClock() {
    const el = document.getElementById("live-clock");
    if (el) el.textContent = new Date().toTimeString().slice(0, 8);
  }

  const LOG_POLL_MS = 1500;
  const LOG_TAIL_LINES = 180;
  const LOG_MAX_DOM_LINES = 800;
  const logState = {
    offset: 0,
    paused: false,
    inflight: false,
    lineCount: 0,
    timer: null,
    userScrolledUp: false,
  };

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function logLineClass(line) {
    const s = String(line);
    if (/ERROR|Traceback|Exception|CRITICAL/i.test(s)) return "log-err";
    if (/⚠|WARN|WARNING|STALL|blocked|reject/i.test(s)) return "log-warn";
    if (/✅|✓|filled|FILLED|success/i.test(s)) return "log-ok";
    if (/\bMEGA\b|\[MEGA\]|mega_/i.test(s)) return "log-mega";
    if (/INFO:|DEBUG:/i.test(s)) return "log-info";
    return "";
  }

  function getLogViewWrap() {
    return document.getElementById("mega-log-view-wrap");
  }

  function getLogView() {
    return document.getElementById("mega-log-view");
  }

  function updateLogCount() {
    const el = document.getElementById("mega-log-count");
    if (el) el.textContent = logState.lineCount + " satır";
  }

  function trimLogDom(view) {
    while (view.childElementCount > LOG_MAX_DOM_LINES) {
      view.removeChild(view.firstElementChild);
    }
    logState.lineCount = view.childElementCount;
    updateLogCount();
  }

  function appendLogLines(lines, opts) {
    const view = getLogView();
    const wrap = getLogViewWrap();
    if (!view || !lines || !lines.length) return;
    const reset = opts && opts.reset;
    if (reset) {
      view.innerHTML = "";
      logState.lineCount = 0;
    }
    const autoScroll =
      !logState.userScrolledUp &&
      document.getElementById("mega-log-autoscroll")?.checked !== false;
    const wasAtBottom =
      wrap &&
      wrap.scrollTop + wrap.clientHeight >= wrap.scrollHeight - 48;
    lines.forEach((line) => {
      const text = String(line).trim();
      if (!text) return;
      const row = document.createElement("span");
      row.className = "mega-log-line " + logLineClass(text);
      row.textContent = text;
      view.appendChild(row);
    });
    trimLogDom(view);
    if (wrap && autoScroll && (wasAtBottom || reset)) {
      wrap.scrollTop = wrap.scrollHeight;
    }
  }

  function setLogPath(name) {
    const el = document.getElementById("mega-log-path");
    if (el && name) el.textContent = name;
  }

  async function fetchProcessLogs() {
    if (logState.paused || logState.inflight) return;
    logState.inflight = true;
    try {
      const params = new URLSearchParams();
      if (logState.offset > 0) {
        params.set("offset", String(logState.offset));
      } else {
        params.set("tail", String(LOG_TAIL_LINES));
      }
      const res = await fetch("/api/logs/process?" + params.toString());
      if (!res.ok) return;
      const data = await res.json();
      if (!data || !data.ok) {
        if (data && data.error) setLogPath(data.path || "log yok");
        return;
      }
      setLogPath(data.path || "—");
      if (data.reset) {
        appendLogLines(data.lines || [], { reset: true });
        logState.offset = data.offset || 0;
        return;
      }
      if (data.lines && data.lines.length) {
        appendLogLines(data.lines, { reset: false });
      }
      if (typeof data.offset === "number") {
        logState.offset = data.offset;
      }
    } catch (_err) {
      /* ignore transient network errors */
    } finally {
      logState.inflight = false;
    }
  }

  function bindLiveLogControls() {
    const pauseBtn = document.getElementById("mega-log-pause");
    const clearBtn = document.getElementById("mega-log-clear");
    const wrap = getLogViewWrap();
    if (pauseBtn) {
      pauseBtn.addEventListener("click", () => {
        logState.paused = !logState.paused;
        pauseBtn.textContent = logState.paused ? "Devam" : "Duraklat";
        pauseBtn.classList.toggle("is-paused", logState.paused);
        if (!logState.paused) fetchProcessLogs();
      });
    }
    if (clearBtn) {
      clearBtn.addEventListener("click", () => {
        const view = getLogView();
        if (view) {
          view.innerHTML =
            '<span class="mega-log-empty">Görünüm temizlendi — yeni satırlar akışa devam eder</span>';
        }
        logState.lineCount = 0;
        updateLogCount();
      });
    }
    if (wrap) {
      wrap.addEventListener("scroll", () => {
        logState.userScrolledUp =
          wrap.scrollTop + wrap.clientHeight < wrap.scrollHeight - 48;
      });
    }
    const auto = document.getElementById("mega-log-autoscroll");
    if (auto) {
      auto.addEventListener("change", () => {
        if (auto.checked) {
          logState.userScrolledUp = false;
          wrap.scrollTop = wrap.scrollHeight;
        }
      });
    }
  }

  function startLiveLogPoll() {
    if (logState.timer) clearInterval(logState.timer);
    fetchProcessLogs();
    logState.timer = setInterval(fetchProcessLogs, LOG_POLL_MS);
  }

  function bindActions() {
    const btn = document.getElementById("btn-refresh");
    if (btn) btn.addEventListener("click", () => fetchMega(true));
  }

  function tickHeroLive() {
    if (!state.open || !state.open.length) return;
    const selected = state.open[state.selectedIdx];
    if (selected) {
      const dur = positionAgeSec(selected);
      if (dur != null) setText("hero-duration", fmtDuration(dur));
    }
    const body = document.getElementById("open-body");
    if (!body) return;
    Array.from(body.querySelectorAll("tr.open-row")).forEach((tr, i) => {
      const row = state.open[i];
      if (!row) return;
      const durCell = tr.children[8];
      if (!durCell) return;
      const d = positionAgeSec(row);
      setTextNode(durCell, d != null ? fmtDuration(d) : "—");
    });
  }

  function refreshOpenUpnlKpi() {
    if (!state.open || !state.open.length) return;
    const unreal = state.open.reduce((acc, p) => acc + liveUpnl(p), 0);
    const upnlEl = document.getElementById("kpi-upnl");
    if (upnlEl) {
      setTextNode(upnlEl, fmtUsd(unreal));
      syncToneClass(upnlEl, "mega-kpi-value num-usd", pnlClass(unreal));
    }
    setText("kpi-upnl-sub", "Mark · " + state.open.length + " açık pozisyon");
  }

  function mergeTickIntoOpen(tick) {
    if (!tick || !tick.symbol) return null;
    let idx = state.open.findIndex(
      (p) => Number(p.id) === Number(tick.id) && tick.id != null
    );
    if (idx < 0) idx = state.open.findIndex((p) => p.symbol === tick.symbol);
    if (idx < 0) return null;
    const merged = Object.assign({}, state.open[idx], tick);
    if (tick.current_price != null || tick.mark_price != null || tick.unrealized_pnl != null) {
      const ex = Object.assign({}, merged.exchange_display || {});
      if (tick.mark_price != null || tick.current_price != null) {
        ex.markPrice = tick.mark_price ?? tick.current_price;
      }
      if (tick.unrealized_pnl != null) {
        ex.unRealizedProfit = tick.unrealized_pnl;
      }
      merged.exchange_display = ex;
      if (tick.exchange_unrealized_pnl != null) {
        merged.exchange_unrealized_pnl = tick.exchange_unrealized_pnl;
      }
    }
    state.open[idx] = merged;
    return { merged, idx };
  }

  function applyTickRows(ticks) {
    const body = document.getElementById("open-body");
    if (!body || !ticks || !ticks.length || !state.open.length) return;
    const existing = Array.from(body.querySelectorAll("tr.open-row"));
    let heroDirty = false;
    ticks.forEach((tick) => {
      const hit = mergeTickIntoOpen(tick);
      if (!hit) return;
      const tr = existing[hit.idx];
      if (tr) updateOpenRow(tr, hit.merged, hit.idx, hit.idx === state.selectedIdx);
      if (hit.idx === state.selectedIdx) heroDirty = true;
    });
    refreshOpenUpnlKpi();
    if (heroDirty) {
      const selected = state.open[state.selectedIdx];
      renderPositionHero(selected);
      renderPositionDetail(selected);
    }
  }

  async function fetchTicks() {
    if (tickInflight || !state.open || !state.open.length) return;
    tickInflight = true;
    try {
      const res = await fetch("/api/paper/" + MODE_ID + "/ticks");
      if (!res.ok) return;
      const data = await res.json();
      if (data && data.ok && data.open && data.open.length) applyTickRows(data.open);
    } catch (_) {
      /* next tick */
    } finally {
      tickInflight = false;
    }
  }

  function schedulePoll(hasOpen) {
    if (pollTimer) clearInterval(pollTimer);
    if (tickTimer) clearInterval(tickTimer);
    tickTimer = null;
    if (hasOpen) {
      fetchTicks();
      tickTimer = setInterval(fetchTicks, TICK_POLL_MS);
      pollTimer = setInterval(() => fetchMega(false), SNAP_POLL_OPEN_MS);
    } else {
      pollTimer = setInterval(() => fetchMega(false), POLL_MS);
    }
  }

  async function init() {
    bindActions();
    bindOpenTable();
    bindLiveLogControls();
    ensureMotorStrip();
    tickClock();
    setInterval(tickClock, 1000);
    setInterval(tickHeroLive, HERO_TICK_MS);
    await fetchMega(true);
    schedulePoll((state.open || []).length > 0);
    startLiveLogPoll();
    window.addEventListener("resize", () => {
      if (state.open.length) {
        renderHeroChart(state.open[state.selectedIdx]);
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
