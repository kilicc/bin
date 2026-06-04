/* MEGA Canlı dashboard */
(function () {
  "use strict";

  const MODE_ID = "mega";
  const CHARTS_ENABLED = false;
  const FETCH_OPTS = { credentials: "include" };
  const SNAP_FETCH_MS = 20000;
  /* Açık pozisyon mark/uPnL — hafif /api/.../ticks (snapshot değil). */
  const TICK_POLL_MS = 80;
  /* KPI / scan / kapalı — light snapshot; sunucu ~0.34s (ELITE_PANEL_REFRESH). */
  const SNAP_POLL_OPEN_MS = 360;
  const POLL_MS = 800;
  const FULL_POLL_MS = 8000;
  const HERO_TICK_MS = 100;
  const HEARTBEAT_EVERY_N_LIGHT = 6;
  const CONN_POLL_MS = 5000;
  const CONN_FETCH_MS = 12000;
  const PANEL_CONN_FRESH_MS = 3500;
  let pollTick = 0;
  let connTimer = null;
  let lightPollCount = 0;
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
      setTextNode(upnlEl, fmtUpnl(unreal));
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

  function healthItems(p) {
    const hs = p && p.health_status;
    return hs && Array.isArray(hs.items) ? hs.items : [];
  }

  function renderPositionHealth(p) {
    const el = document.getElementById("position-detail");
    if (!el) return;
    const bar = el.querySelector("[data-health-bar]");
    if (!bar) return;
    const items = healthItems(p);
    if (!items.length) {
      bar.innerHTML = "";
      bar.classList.add("hidden");
      return;
    }
    bar.classList.remove("hidden");
    bar.innerHTML = items
      .map(function (it) {
        const ok = !!it.ok;
        return (
          '<div class="mega-health-chip" title="' +
          esc(it.detail || "") +
          '">' +
          '<span class="mega-health-dot ' +
          (ok ? "ok" : "bad") +
          '" aria-hidden="true"></span>' +
          '<span class="mega-health-lbl">' +
          esc(it.label || it.id || "") +
          "</span></div>"
        );
      })
      .join("");
    const summary = el.querySelector("[data-health-summary]");
    if (summary) {
      const allOk = !!(p.health_status && p.health_status.all_ok);
      summary.className = "mega-health-summary " + (allOk ? "ok" : "bad");
      setTextNode(summary, allOk ? "Tüm kontroller OK" : "Dikkat: kırmızı alan var");
    }
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
    renderPositionHealth(p);
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
  function fmtUpnl(n) {
    if (n == null || n === "" || !Number.isFinite(Number(n))) return "—";
    return fmtUsd(n);
  }
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
    const live = isBinanceOpenRow(p);
    const entryNum = Number(
      live && ex.entryPrice != null && ex.entryPrice !== ""
        ? ex.entryPrice
        : ex.entryPrice ?? p.entry_price
    );
    const markNum = Number(
      live && ex.markPrice != null && ex.markPrice !== ""
        ? ex.markPrice
        : ex.markPrice ?? p.current_price
    );
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

  const state = {
    snap: null,
    selectedIdx: 0,
    open: [],
    lastHeroKey: "",
    connLive: null,
    lastHb: null,
  };

  // #region agent log
  function dbg6fe627(hypothesisId, location, message, data) {
    var body = JSON.stringify({
      sessionId: "6fe627",
      hypothesisId: hypothesisId,
      location: location,
      message: message,
      data: data || {},
      timestamp: Date.now(),
    });
    fetch("/api/panel/client-debug", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: body,
    }).catch(function () {});
  }
  // #endregion

  function showFatalBanner(msg) {
    const b = document.getElementById("panel-fatal-banner");
    if (!b) return;
    if (msg) {
      b.textContent = msg;
      b.classList.remove("hidden");
    } else {
      b.classList.add("hidden");
    }
  }

  const MOTOR_PILLS = [
    { id: "fast", label: "Evren", warn: 400, bad: 900, val: (hb) => hb && hb.fast_tick_ms },
    { id: "scan", label: "Scan", warn: 2500, bad: 5500, val: (hb) => hb && hb.motor_eval_ms },
    { id: "pos", label: "Poz", warn: 65, bad: 130, val: (hb) => hb && hb.position_tick_ms },
    {
      id: "exit",
      label: "Exit",
      warn: 80,
      bad: 160,
      val: (hb) => {
        if (!hb || !hb.mega) return null;
        const ev = Number(hb.mega.last_exit_eval_ms);
        const full = Number(hb.mega.last_exit_tick_ms);
        if (Number.isFinite(ev) && ev > 0) return ev;
        return Number.isFinite(full) && full > 0 ? full : null;
      },
      title: (hb) => {
        if (!hb || !hb.mega) return "";
        const ev = hb.mega.last_exit_eval_ms;
        const full = hb.mega.last_exit_tick_ms;
        const settle = hb.mega.last_close_settle_ms;
        if (settle > 0) {
          return `eval ${fmtMotorMs(ev)} · kapanış ${fmtMotorMs(settle)} · toplam ${fmtMotorMs(full)}`;
        }
        return full != null ? `exit tick ${fmtMotorMs(full)}` : "";
      },
    },
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

  function fmtMotorMs(v, opts) {
    if (v == null || v === "") return "—";
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    if (opts && opts.idleZero && n <= 0) return "—";
    if (n >= 1000) return (n / 1000).toFixed(1) + "s";
    if (n > 0 && n < 1) return "<1ms";
    return Math.round(n) + "ms";
  }

  function mergeConn(hb, live) {
    const hc = (hb && hb.connection) || {};
    const lc = live || {};
    let apiOk = null;
    if (lc.fetch_failed && lc.api_ok == null) {
      apiOk = hc.api_ok != null ? !!hc.api_ok : null;
    } else if (lc.api_ok != null) {
      apiOk = !!lc.api_ok;
    } else if (hc.api_ok != null) {
      apiOk = !!hc.api_ok;
    }
    return {
      api_ok: apiOk,
      api_paper: !!(lc.api_paper != null ? lc.api_paper : hc.api_paper),
      auth_error: lc.auth_error != null ? lc.auth_error : hc.auth_error,
      ip_ban: !!(lc.ip_ban != null ? lc.ip_ban : hc.ip_ban),
      last_ok_ago_sec:
        lc.last_ok_ago_sec != null
          ? lc.last_ok_ago_sec
          : hc.last_ok_ago_sec != null
            ? hc.last_ok_ago_sec
            : null,
      stale_sec: lc.stale_sec != null ? lc.stale_sec : hc.stale_sec,
      position_risk_age_sec:
        lc.position_risk_age_sec != null
          ? lc.position_risk_age_sec
          : hc.position_risk_age_sec != null
            ? hc.position_risk_age_sec
            : hb && hb.mega && hb.mega.position_risk_age_sec != null
              ? hb.mega.position_risk_age_sec
              : null,
    };
  }

  function maxAgeMsFromRows(rows) {
    let max = 0;
    (rows || []).forEach((p) => {
      const a = Number(p.exchange_data_age_ms || p.positions_cache_age_ms || 0);
      if (a > max) max = a;
    });
    return max;
  }

  function maxOpenDataAgeMs() {
    return maxAgeMsFromRows(state.open);
  }

  /** Snapshot/tick positionRisk taze ise API pill kopuk gösterme. */
  function enrichPanelConn(conn, openRows) {
    const c = Object.assign({}, conn || {});
    const rows = openRows || [];
    const n = rows.length;
    if (!n) return c;
    const maxAge = maxAgeMsFromRows(rows);
    const upnlOk = rows.every((p) => liveUpnl(p) != null);
    if (!upnlOk || maxAge > PANEL_CONN_FRESH_MS) return c;
    if (c.api_ok !== true) c.api_ok = true;
    if (c.position_risk_age_sec == null || !Number.isFinite(Number(c.position_risk_age_sec))) {
      c.position_risk_age_sec = maxAge / 1000;
    }
    if (c.last_ok_ago_sec == null || !Number.isFinite(Number(c.last_ok_ago_sec))) {
      c.last_ok_ago_sec = maxAge / 1000;
    }
    c._from_panel_rows = true;
    return c;
  }

  function resolvePanelConn(hb, liveConn, openRows) {
    return enrichPanelConn(mergeConn(hb, liveConn), openRows);
  }

  function openRowDataStale(p) {
    if (!p || !isBinanceOpenRow(p)) return false;
    return Number(p.exchange_data_age_ms || p.positions_cache_age_ms || 0) > 1500;
  }

  function openPositionCount() {
    return state.open && state.open.length ? state.open.length : 0;
  }

  /** null = henüz bilinmiyor; false = kopuk/stale */
  function isBinanceApiLive(conn) {
    if (!conn) return null;
    if (conn.ip_ban || conn.auth_error) return false;
    if (conn.api_ok !== true) {
      if (conn.api_ok === false) return false;
      return null;
    }
    const ago = Number(conn.last_ok_ago_sec);
    const stale = Number(conn.stale_sec || 35);
    if (Number.isFinite(ago) && ago > stale) return false;
    const risk = Number(conn.position_risk_age_sec);
    if (openPositionCount() > 0 && Number.isFinite(risk) && risk > 5) return false;
    return true;
  }

  function renderBinanceConn(conn, openRows) {
    const pill = document.getElementById("binance-conn-pill");
    const val = document.getElementById("binance-conn-val");
    if (!pill || !val) return;
    const rows = openRows != null ? openRows : state.open;
    const merged = resolvePanelConn(state.lastHb, conn || state.connLive, rows);
    const live = isBinanceApiLive(merged);
    const rowAge = maxAgeMsFromRows(rows);
    if (live === null) {
      pill.className = "snapshot-lat-pill off";
      setTextNode(val, "—");
      pill.title = "demo-fapi REST — durum bekleniyor";
      return;
    }
    if (!live) {
      pill.className = "snapshot-lat-pill bad";
      setTextNode(val, "—");
      const risk = Number(merged.position_risk_age_sec);
      let why = "kopuk";
      if (merged.auth_error) why = "auth";
      else if (merged.ip_ban) why = "ban";
      else if (rows.length > 0 && Number.isFinite(risk) && risk > 5) {
        why = "posRisk " + Math.round(risk) + "s";
      } else if (rowAge > 5000 && rows.length > 0) {
        why = "veri " + Math.round(rowAge / 1000) + "s";
      }
      pill.title = "Binance veri güvenilmez (" + why + ")";
      return;
    }
    pill.className = "snapshot-lat-pill ok";
    if (rows.length > 0 && rowAge > 0 && rowAge < 2500) {
      setTextNode(val, Math.round(rowAge) + "ms");
      pill.title =
        "demo-fapi positionRisk · panel veri yaşı " + Math.round(rowAge) + "ms";
    } else {
      const ago = merged.last_ok_ago_sec;
      setTextNode(
        val,
        Number.isFinite(Number(ago)) ? Math.round(Number(ago)) + "s" : "OK"
      );
      pill.title =
        "demo-fapi REST · son ping " + (ago != null ? Math.round(Number(ago)) + "s" : "OK");
    }
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

  function renderMotorStrip(hb, conn) {
    const strip = ensureMotorStrip();
    if (!strip) return;
    const apiLive = isBinanceApiLive(resolvePanelConn(state.lastHb, conn, state.open));
    const apiTitle =
      apiLive === false
        ? "Binance API kopuk — süreler geçersiz"
        : apiLive === true
          ? "Motor süreleri (son döngü)"
          : "API durumu bekleniyor";
    strip.title = apiTitle;
    MOTOR_PILLS.forEach((spec) => {
      const pill = strip.querySelector('[data-motor-id="' + spec.id + '"]');
      if (!pill) return;
      let raw = spec.val(hb);
      let tone = "off";
      let text = "—";
      if (apiLive === false) {
        raw = null;
      } else if (apiLive === null && spec.id !== "rest") {
        raw = null;
      } else {
        if (spec.id === "rest" && (raw == null || Number(raw) <= 0)) {
          raw = null;
        }
        if (raw == null || raw === "" || (Number(raw) === 0 && spec.id !== "cache")) {
          text = "—";
          tone = "off";
        } else {
          text = fmtMotorMs(raw, { idleZero: spec.id !== "cache" });
          tone = motorPillTone(raw, spec);
        }
      }
      const valEl = pill.querySelector(".val");
      setTextNode(valEl, text);
      if (typeof spec.title === "function") {
        const tip = spec.title(hb);
        pill.title = tip || spec.label;
      }
      const nextCls = "mega-motor-pill " + tone;
      if (pill.className !== nextCls) pill.className = nextCls;
    });
  }

  const CONN_FAIL_GRACE_MS = 28000;

  function connFetchGraceOk() {
    const c = state.connLive;
    return !!(c && c._fetchedAt && Date.now() - c._fetchedAt < CONN_FAIL_GRACE_MS && c.api_ok);
  }

  async function fetchConnectionLive() {
    try {
      const res = await fetchWithTimeout("/api/connection/live", CONN_FETCH_MS);
      if (!res.ok) {
        if (!connFetchGraceOk()) {
          state.connLive = { fetch_failed: true, _fetchedAt: Date.now() };
        }
        return;
      }
      const data = await res.json();
      state.connLive = {
        api_ok: !!data.api_ok,
        api_paper: !!data.api_paper,
        auth_error: data.auth_error || null,
        ip_ban: !!data.ip_ban,
        last_ok_ago_sec:
          data.last_ok_ago_sec != null ? Number(data.last_ok_ago_sec) : null,
        stale_sec: data.stale_sec != null ? Number(data.stale_sec) : 35,
        position_risk_age_sec:
          data.position_risk_age_sec != null
            ? Number(data.position_risk_age_sec)
            : null,
        api_label: data.api_label || "",
        _fetchedAt: Date.now(),
      };
      renderBinanceConn(state.connLive, state.open);
    } catch (_) {
      if (!connFetchGraceOk()) {
        state.connLive = { fetch_failed: true, _fetchedAt: Date.now() };
      }
    }
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

  function syncPnlCell(td, unreal, p) {
    if (!td) return;
    if (unreal == null || !Number.isFinite(Number(unreal))) {
      setTextNode(td, "—");
      if (td.className !== "cell-num cell-upnl neutral") td.className = "cell-num cell-upnl neutral";
      td.title = "Binance API uPnL yok";
      return;
    }
    const ageMs = Number(p && (p.exchange_data_age_ms || p.positions_cache_age_ms));
    const stale = p && openRowDataStale(p);
    const cls = pnlClass(unreal);
    setTextNode(td, fmtUpnl(unreal));
    td.title = stale
      ? "API uPnL · positionRisk " + Math.round(ageMs / 1000) + "s bayat"
      : "Binance API uPnL";
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
      upnl: fmtUpnl(unreal),
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
      '<div class="mega-health-panel">' +
      '<div class="mega-health-head">' +
      '<span class="mega-health-title">Durum</span>' +
      '<span class="mega-health-summary neutral" data-health-summary>—</span>' +
      "</div>" +
      '<div class="mega-health-bar hidden" data-health-bar></div>' +
      "</div>" +
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
    if (v == null || v === "" || !Number.isFinite(Number(v))) return "neutral";
    const n = Number(v);
    if (n === 0) return "neutral";
    return n > 0 ? "pos" : "neg";
  }

  /** Borsa positionRisk uPnL — motor/mark tahmini yok; yoksa null. */
  function liveUpnl(p) {
    if (!p) return null;
    const ex = p.exchange_display || {};
    if (ex.unRealizedProfit != null && ex.unRealizedProfit !== "") {
      const api = Number(ex.unRealizedProfit);
      if (Number.isFinite(api)) return api;
    }
    if (
      p.exchange_unrealized_pnl != null &&
      p.exchange_unrealized_pnl !== "" &&
      Number.isFinite(Number(p.exchange_unrealized_pnl))
    ) {
      return Number(p.exchange_unrealized_pnl);
    }
    return null;
  }

  function parseApiNum(v) {
    if (v == null || v === "") return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  function binanceMargin(p) {
    if (!p) return null;
    const ex = p.exchange_display || {};
    return (
      parseApiNum(ex.isolatedMargin) ||
      parseApiNum(ex.positionInitialMargin) ||
      parseApiNum(p.margin_used) ||
      (parseApiNum(p.stake_usd) > 0 ? parseApiNum(p.stake_usd) : null)
    );
  }

  function binanceRoiPct(p) {
    if (!p) return null;
    const ex = p.exchange_display || {};
    const pct = parseApiNum(ex.percentage);
    if (pct != null) return pct;
    const api = liveUpnl(p);
    const m = binanceMargin(p);
    if (api != null && m != null && m > 0) return (api / m) * 100;
    return null;
  }

  /** Binance tablo ROI$ ≈ margin × percentage/100 (demo API percentage boşsa margin ROI ≈ uPnL) */
  function binanceRoiUsd(p) {
    const pct = binanceRoiPct(p);
    const m = binanceMargin(p);
    if (pct != null && m != null) return (m * pct) / 100;
    return null;
  }

  function syncRoiCell(td, roiUsd, p) {
    if (!td) return;
    const pct = binanceRoiPct(p);
    if (roiUsd == null || !Number.isFinite(Number(roiUsd))) {
      setTextNode(td, "—");
      if (td.className !== "cell-num cell-upnl-roi neutral") {
        td.className = "cell-num cell-upnl-roi neutral";
      }
      td.title = "Binance ROI $ yok (margin × percentage)";
      return;
    }
    const stale = p && openRowDataStale(p);
    const cls = pnlClass(roiUsd);
    const pctHint =
      pct != null ? " · " + (pct >= 0 ? "+" : "") + pct.toFixed(2) + "%" : "";
    const apiUpnl = liveUpnl(p);
    const roiMismatch =
      apiUpnl != null &&
      Number.isFinite(apiUpnl) &&
      Math.abs(Number(roiUsd) - apiUpnl) > Math.max(0.35, Math.abs(apiUpnl) * 0.03);
    setTextNode(td, fmtUpnl(roiUsd));
    td.title = stale
      ? "Binance tablo ROI$" + pctHint + " · bayat veri"
      : roiMismatch
        ? "ROI$ = marjin×ROE% (API); uPnL sütunu = unRealizedProfit" + pctHint
        : "Binance tablo ROI$ = marjin × ROE%/100" + pctHint;
    const tone = cls === "pos" ? "pos" : cls === "neg" ? "neg" : "neutral";
    const next = "cell-num cell-upnl-roi " + tone;
    if (td.className !== next) td.className = next;
  }

  function aggregateApiUpnl(rows) {
    if (!rows || !rows.length) return { sum: 0, complete: true, missing: 0 };
    let sum = 0;
    let missing = 0;
    for (let i = 0; i < rows.length; i++) {
      const u = liveUpnl(rows[i]);
      if (u == null) missing++;
      else sum += u;
    }
    return { sum, complete: missing === 0, missing };
  }

  function isBinanceOpenRow(p) {
    return (
      p &&
      (p.data_source === "binance" ||
        p.on_exchange ||
        p.exchange_synced ||
        (p.exchange_display && p.exchange_display.unRealizedProfit != null))
    );
  }

  function tpTargetUsd(p) {
    return Number(p.tp_net_target_usd || p.tp_target_usd || 0);
  }

  function tpProgress(p) {
    const target = tpTargetUsd(p);
    const unreal = liveUpnl(p);
    if (target <= 0 || unreal == null) return 0;
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
    const dataAge = Number(p.exchange_data_age_ms || p.positions_cache_age_ms || 0);
    const staleMs = isBinanceOpenRow(p) ? 1200 : 2500;
    const staleHint = dataAge > staleMs ? " · veri " + Math.round(dataAge / 1000) + "s" : "";
    const peakHint =
      peakPct > tpPct + 2 ? " · tepe " + Math.round(peakPct) + "%" : "";
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
      setTextNode(label, fmtUsd(tpUsd) + " · " + tpPct + "%" + peakHint + staleHint);
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
      "<td class='cell-num cell-upnl-roi'></td>" +
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
    const markTd = tr.children[5];
    if (markTd) {
      markTd.title =
        p.price_source === "hub_mark"
          ? "Mark · hub WS" +
            (p.mark_age_ms != null ? " ~" + Math.round(Number(p.mark_age_ms)) + "ms" : "")
          : "Mark · Binance positionRisk";
    }
    syncPnlCell(tr.children[6], liveUpnl(p), p);
    syncRoiCell(tr.children[7], binanceRoiUsd(p), p);
    updateTpCell(tr.children[8], p);
    setTextNode(tr.children[9], dur != null ? fmtDuration(dur) : "—");
  }

  function tpCellHtml(p) {
    const tpUsd = Number(p.tp_net_target_usd || p.tp_target_usd || 0);
    const tpPct = Math.round(tpProgress(p) * 100);
    const peakPct = Number(p.tp_peak_progress_pct || 0);
    const dataAge = Number(p.exchange_data_age_ms || p.positions_cache_age_ms || 0);
    const staleMs = isBinanceOpenRow(p) ? 1200 : 2500;
    const staleHint = dataAge > staleMs ? " · veri " + Math.round(dataAge / 1000) + "s" : "";
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
      staleHint +
      "</span></div></td>"
    );
  }

  function chartsReady() {
    return CHARTS_ENABLED && window.TradingCharts && window.LightweightCharts;
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
    const openRows = snap.open || [];
    const upnlAgg = openRows.length
      ? aggregateApiUpnl(openRows)
      : { sum: 0, complete: true, missing: 0 };
    const openUnreal = upnlAgg.complete ? upnlAgg.sum : 0;
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
    let unrealKpi = null;
    let upnlSubKpi = "Mark · Binance API";
    if (openRows.length) {
      if (upnlAgg.complete) {
        unrealKpi = upnlAgg.sum;
      } else {
        upnlSubKpi =
          "API uPnL eksik · " + upnlAgg.missing + "/" + openRows.length + " pozisyon";
      }
    } else if (
      isLive &&
      wallet.total_unrealized_pnl != null &&
      Number.isFinite(Number(wallet.total_unrealized_pnl))
    ) {
      unrealKpi = Number(wallet.total_unrealized_pnl);
    } else if (!openRows.length) {
      unrealKpi = 0;
    }
    const unrealForEquity =
      unrealKpi != null
        ? unrealKpi
        : wallet.total_unrealized_pnl != null &&
            Number.isFinite(Number(wallet.total_unrealized_pnl))
          ? Number(wallet.total_unrealized_pnl)
          : 0;
    const totalEquityPnl =
      anchor != null && bal != null && Number(anchor) > 0
        ? Number(bal) - Number(anchor)
        : summ.total_pnl != null && Number.isFinite(Number(summ.total_pnl))
          ? Number(summ.total_pnl)
          : sessionPnl + unrealForEquity;
    const sessionPct =
      anchor > 0 && Number.isFinite(sessionPnl)
        ? (sessionPnl / Number(anchor)) * 100
        : null;
    const openN = summ.open_count ?? (snap.open || []).length;
    const closedN = closedDeduped.length || summ.closed_trades || 0;
    const wr = summ.win_rate;
    const maxOpen = scan.max_open ?? scan.slot_base ?? 0;
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
      setTextNode(upnlEl, fmtUpnl(unrealKpi));
      syncToneClass(upnlEl, "mega-kpi-value num-usd", pnlClass(unrealKpi));
    }
    setText("kpi-upnl-sub", upnlSubKpi + " · " + openN + " açık");

    const openEl = document.getElementById("kpi-open");
    const slotsRem =
      scan.slots_remaining != null ? Number(scan.slots_remaining) : null;
    const overCap = Boolean(scan.over_slot_cap) || (openN > maxOpen && maxOpen > 0);
    if (openEl) {
      setTextNode(openEl, openN + " / " + maxOpen);
      syncToneClass(openEl, "mega-kpi-value num-slot", overCap ? "negative" : "neutral");
    }
    const stakePol = scan.stake_policy || "$1000";
    const blockReason = scan.entry_block_reason || "";
    const bootObs = scan.boot_observe || {};
    const bootLabel =
      bootObs.active && bootObs.remaining_sec != null
        ? "gözlem " + Math.ceil(Number(bootObs.remaining_sec)) + "s"
        : "";
    const availUsd =
      summ.available_balance != null
        ? fmtUsd(summ.available_balance)
        : avail != null
          ? fmtUsd(avail)
          : null;
    const slotBudget =
      scan.slot_budget_usd != null ? fmtUsd(scan.slot_budget_usd) : null;
    const kpiSub = [];
    if (availUsd) kpiSub.push("kullanılabilir " + availUsd);
    if (slotBudget) kpiSub.push("slot bütçesi " + slotBudget);
    const deployNew =
      scan.deployable_new_usd != null ? fmtUsd(scan.deployable_new_usd) : null;
    kpiSub.push("tavan " + maxOpen + " poz. · " + stakePol);
    if (deployNew) kpiSub.push("serbest stake " + deployNew);
    if (slotsRem != null) kpiSub.push("yeni açılış " + slotsRem);
    if (bootLabel) kpiSub.push(bootLabel);
    if (overCap) kpiSub.push("limit aşımı — kapatın");
    else if (blockReason) kpiSub.push(blockReason);
    else if (slotsRem === 0) kpiSub.push("MEGA / Flash kapalı");
    setText("kpi-open-sub", kpiSub.join(" · ") + (queue ? " · kuyruk " + queue : ""));
    setText("open-count-pill", openN + " / " + maxOpen);

    const wrEl = document.getElementById("kpi-winrate");
    if (wrEl) {
      setTextNode(wrEl, wr != null ? Number(wr).toFixed(1) + "%" : closedN ? "0.0%" : "—");
      syncToneClass(wrEl, "mega-kpi-value num-pct", "neutral");
    }
    const cMeta = (state.snap && state.snap.closed_meta) || {};
    const closedSub =
      closedN +
      " kapalı" +
      (cMeta.includes_archives ? " · arşiv dahil" : "") +
      (cMeta.truncated ? " · liste kısaltıldı" : "");
    setText("kpi-winrate-sub", closedSub);
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
    if (!CHARTS_ENABLED || !chartsReady() || !p) {
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
    const btc = sc.btc_context || {};
    const trans = regime.transition || {};
    const cd = regime.change_countdown || {};
    const topReject = ((sc.reject_top || [])[0] || {}).reason || "—";
    const regimeLbl = trans.active
      ? (regime.regime || "—") + "+transition"
      : regime.effective_regime || regime.regime || "—";
    let btcRegimeLbl =
      btc.regime_label || (btc.regime ? String(btc.regime) : "—");
    let btcReadyLbl = "Bekle";
    if (btc.ready) {
      btcReadyLbl = btc.bearish ? "SHORT öncelik" : "Giriş açık";
      if (btc.btc_price != null) {
        btcReadyLbl +=
          " · $" +
          Number(btc.btc_price).toLocaleString(undefined, { maximumFractionDigits: 0 });
      }
      if (btc.context_age_sec != null) btcReadyLbl += " · " + btc.context_age_sec + "s";
    } else if (btc.block_reason) {
      btcReadyLbl += " · " + btc.block_reason;
    }
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
    const flashN = (sc.flash_watch || []).length;
    const flashReady = (sc.flash_watch || []).filter((r) => r.ui_tier === "ready").length;
    const casc = btc.btc_cascade || {};
    let cascLbl = casc.phase_label || casc.phase || "—";
    if (casc.vol_spike) cascLbl += " · hacim↑";
    if (casc.book_imbalance != null) cascLbl += " · kitap " + casc.book_imbalance;
    if (btc.btc_1m_wick_drop_pct != null) {
      btcRegimeLbl += " · wick " + btc.btc_1m_wick_drop_pct + "%";
    }
    const macro = btc.btc_macro || {};
    const domLbl =
      macro.btc_dominance != null
        ? Number(macro.btc_dominance).toFixed(1) + "%"
        : "—";
    const fngLbl =
      macro.fng_score != null
        ? macro.fng_score + (macro.fng_label ? " · " + macro.fng_label : "")
        : "—";
    const fundLbl =
      macro.funding_rate_pct != null
        ? Number(macro.funding_rate_pct).toFixed(4) + "%"
        : "—";
    const newsLbl = macro.news_headline
      ? String(macro.news_headline).slice(0, 72)
      : "—";
    const stats = [
      ["BTC rejim", btcRegimeLbl],
      ["BTC dominans", domLbl],
      ["F&G", fngLbl],
      ["BTC funding", fundLbl],
      ["BTC haber", newsLbl],
      ["Makro bias", macro.bias_label || macro.summary || "—"],
      [
        "Makro takvim",
        macro.macro_next_event
          ? String(macro.macro_next_event).slice(0, 48) +
            (macro.macro_next_date ? " · " + macro.macro_next_date : "")
          : macro.fmp_note || (macro.fmp_status === "plan_required" ? "FMP plan gerekli" : "—"),
      ],
      ["BTC şelale", cascLbl],
      (function () {
        const liq = btc.btc_liq || {};
        if (!liq.summary || liq.summary === "—") return ["BTC liq küme", "—"];
        const ls =
          liq.ls_long_pct != null
            ? "L/S " + liq.ls_long_pct + "/" + liq.ls_short_pct + "%"
            : "";
        const oi =
          liq.oi_change_pct != null ? "OI Δ" + liq.oi_change_pct + "%" : "";
        return [
          "BTC liq küme",
          (liq.bias_label || liq.bias || "—") +
            " · " +
            liq.summary +
            (ls ? " · " + ls : "") +
            (oi ? " · " + oi : ""),
        ];
      })(),
      ["BTC motor", btcReadyLbl],
      ["Rejim", regimeLbl],
      ["Değişim", geçişVal],
      ["Flash izle", flashN ? flashN + (flashReady ? " (" + flashReady + " hazır)" : "") : "0"],
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

  function renderFlashWatch(sc) {
    const el = document.getElementById("flash-watch-chips");
    const meta = document.getElementById("flash-watch-meta");
    if (!el) return;
    const rows = (sc && sc.flash_watch) || [];
    const maxOpen = sc && sc.max_open != null ? Number(sc.max_open) : 0;
    const stakePol = (sc && sc.stake_policy) || "$100–700";
    if (meta) {
      setText(
        "flash-watch-meta",
        (maxOpen > 0 ? maxOpen + " açılış · " : "marjin dolu · ") +
          stakePol +
          " · izleme drop ~%0.08 (giriş ~%0.14)"
      );
    }
    if (!rows.length) {
      el.innerHTML =
        '<span class="mega-scan-empty">Flash adayı yok — düşüş+toparlanma bekleniyor (açık semboller hariç)</span>';
      return;
    }
    el.innerHTML = rows
      .slice(0, 16)
      .map((r) => {
        const sym = (r.symbol || "").replace("USDT", "");
        const tier = String(r.ui_tier || "forming");
        const lbl = r.ui_label || tier;
        const drop = r.flash_drop_pct != null ? fmtPct(r.flash_drop_pct) : "";
        const bounce = r.flash_bounce_pct != null ? fmtPct(r.flash_bounce_pct) : "";
        const prog = r.ui_progress_pct != null ? Math.round(r.ui_progress_pct) + "%" : "";
        return (
          '<div class="mega-flash-chip tier-' +
          esc(tier) +
          '" title="' +
          esc(lbl) +
          '">' +
          '<span class="sym">' +
          esc(sym) +
          "</span>" +
          '<span class="lbl">' +
          esc(lbl) +
          "</span>" +
          '<span class="meta">Δ↓' +
          esc(drop) +
          " · Δ↑" +
          esc(bounce) +
          (prog ? " · " + esc(prog) : "") +
          "</span></div>"
        );
      })
      .join("");
  }

  function renderScan(scan) {
    const sc = scan || {};
    renderScanStats(sc);
    renderFlashWatch(sc);
    renderVolChips(sc.volatility || {}, sc.market_regime || {});
    const parts = [
      sc.last_scan_age_sec != null ? "Son tur " + sc.last_scan_age_sec + "s önce" : null,
      sc.eval_last_n != null ? "Eval " + sc.eval_last_n : null,
      sc.candidates_last_n != null ? "Aday " + sc.candidates_last_n : null,
      sc.motor_queue != null ? "Kuyruk " + sc.motor_queue : null,
      sc.reject_total != null ? "Red " + sc.reject_total : null,
      (sc.volatility || {}).enabled ? "Vol scan açık" : null,
      (sc.btc_context || {}).regime_label
        ? "BTC " +
          (sc.btc_context.regime_label || sc.btc_context.regime) +
          (sc.btc_context.ready ? "" : " · giriş kapalı")
        : null,
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
        '<tr><td colspan="10" class="mega-empty-cell">Henüz açık MEGA pozisyon yok</td></tr>';
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

  function closedDisplayLimit() {
    const meta = (state.snap && state.snap.closed_meta) || {};
    const max = Number(meta.max_rows);
    if (Number.isFinite(max) && max > 0) return max;
    return 99999;
  }

  function renderClosed(closed) {
    const body = document.getElementById("closed-body");
    if (!body) return;
    const rows = sortClosedForDisplay(closed).slice(0, closedDisplayLimit());
    const meta = (state.snap && state.snap.closed_meta) || {};
    if (!rows.length) {
      body.innerHTML =
        '<tr><td colspan="22" class="mega-empty-cell">Kapalı işlem kaydı yok</td></tr>';
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
        const archTag = c._archive || c.archive_source ? " · arşiv" : "";
        const phantomTag = c.panel_hide ? " · gizli" : "";
        const reason = String(c.exit_reason || "—") + archTag + phantomTag;
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
    if (!CHARTS_ENABLED || !openList || !openList.length) return openList || [];
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
    if (!CHARTS_ENABLED) return false;
    if (forceFull === true) return true;
    return Date.now() - lastFullPollTs >= FULL_POLL_MS;
  }

  function setPanelApiStatus(snap, latMs, statusMsg) {
    const el = document.getElementById("panel-api-status");
    if (!el) return;
    const apiLive = isBinanceApiLive(
      resolvePanelConn(state.lastHb, state.connLive, snap && snap.open ? snap.open : state.open)
    );
    if (statusMsg) {
      el.className = "mega-api-status warn";
      el.textContent = statusMsg;
      return;
    }
    if (apiLive === false) {
      el.className = "mega-api-status warn";
      const c = state.connLive || {};
      const rowAge = maxOpenDataAgeMs();
      const risk = Number(c.position_risk_age_sec);
      let detail = "Binance API kopuk";
      if (c.auth_error) detail = "Binance auth hatası";
      else if (c.ip_ban) detail = "Binance IP ban";
      else if (openPositionCount() > 0 && Number.isFinite(risk) && risk > 5) {
        detail = "positionRisk bayat (" + Math.round(risk) + "s)";
      }
      el.textContent = detail + " · uPnL/TP — · motor süreleri —";
      return;
    }
    if (!snap || !snap.ok) {
      el.className = "mega-api-status warn";
      el.textContent = "Snapshot alınamadı";
      return;
    }
    const n = (snap.open || []).length;
    const es = snap.exchange_sync || {};
    const riskMs = maxAgeMsFromRows(snap && snap.open ? snap.open : state.open);
    const parts = [
      n + " açık panel",
      es.exchange_n != null ? es.exchange_n + " borsa" : null,
      snap.live ? "demo-fapi canlı" : "paper",
      riskMs > 0 && n > 0 ? "positionRisk ~" + Math.round(riskMs) + "ms" : null,
      latMs != null ? "snap " + latMs + "ms" : null,
    ].filter(Boolean);
    let extra = "";
    if (es.mismatch) {
      extra =
        " · UYARI kitap≠borsa" +
        (es.only_exchange && es.only_exchange.length
          ? " borsada: " + es.only_exchange.join(", ")
          : "") +
        (es.only_book && es.only_book.length
          ? " eski kitap: " + es.only_book.join(", ")
          : "");
      el.className = "mega-api-status warn";
    } else if (es.synced) {
      extra = " · borsa ile senkronlandı";
      el.className = "mega-api-status ok";
    } else {
      el.className = "mega-api-status ok";
    }
    el.textContent = parts.join(" · ") + extra;
  }

  function hideLoadingOverlay() {
    const overlay = document.getElementById("loading-overlay");
    if (overlay) overlay.classList.add("hidden");
  }

  function showLoadingAuthHint() {
    const cap = document.querySelector("#loading-overlay .loader-caption");
    if (cap) {
      cap.textContent =
        "Giriş gerekli (nginx 9086): kullanıcı x · şifre x369 — iptal ederseniz panel boş kalır";
    }
  }

  async function fetchWithTimeout(url, ms) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), ms);
    try {
      return await fetch(url, { ...FETCH_OPTS, signal: ctrl.signal });
    } finally {
      clearTimeout(timer);
    }
  }

  function snapshotErrorMessage(status) {
    if (status === 401 || status === 403) {
      return "Panel girişi gerekli — kullanıcı: x · şifre: x369 (port 9086)";
    }
    if (status === 502 || status === 503) {
      return "Bot yeniden başlıyor (HTTP " + status + ") — 20–40 sn sonra yenileyin";
    }
    if (status === 504) {
      return "Snapshot zaman aşımı (nginx 504) — bot meşgul, biraz bekleyin";
    }
    if (status > 0) {
      return "Snapshot API hata HTTP " + status;
    }
    return "Ağ hatası — 9086 erişimi ve giriş (x/x369) kontrol edin";
  }

  async function runMegaFetch(forceFull) {
    const t0 = performance.now();
    let snap = null;
    let hb = null;
    let statusMsg = null;
    const full = wantFullSnapshot(forceFull);
    if (full) lastFullPollTs = Date.now();
    pollTick += 1;
    try {
      const snapUrl =
        "/api/paper/" + MODE_ID + "/snapshot?light=" + (full ? "0" : "1");
      const snapRes = await fetchWithTimeout(snapUrl, SNAP_FETCH_MS);
      if (snapRes.ok) {
        try {
          snap = await snapRes.json();
        } catch (parseErr) {
          statusMsg = "Snapshot JSON okunamadı — sayfayı yenileyin";
        }
      } else {
        if (snapRes.status === 401 || snapRes.status === 403) {
          showLoadingAuthHint();
        }
        statusMsg = snapshotErrorMessage(snapRes.status);
      }
      if (!statusMsg) {
        const hbEvery =
          (state.open && state.open.length) > 0 ? 1 : HEARTBEAT_EVERY_N_LIGHT;
        const wantHb = full || lightPollCount++ % hbEvery === 0;
        if (wantHb) {
          try {
            const hbRes = await fetchWithTimeout("/api/heartbeat", 4000);
            if (hbRes.ok) hb = await hbRes.json();
          } catch (_) {
            /* snapshot öncelikli */
          }
        }
      }
      const lat = Math.round(performance.now() - t0);
      setSnapshotLatency(lat);
      state.lastHb = hb;
      state.snap = snap;

      if (snap && snap.ok) {
        try {
          const openUi =
            snap.open && snap.open.length
              ? mergeHybridCharts(snap.open.slice())
              : snap.open || [];
          renderKpis(snap);
          renderScan(snap.scan);
          renderOpenTable(openUi);
          renderClosed(dedupeClosedRows(snap.closed || []));
          schedulePoll(openUi.length > 0);
          const conn = resolvePanelConn(hb, state.connLive, state.open);
          renderMotorStrip(hb, conn);
          renderBinanceConn(conn, state.open);
        } catch (renderErr) {
          statusMsg =
            "Panel render: " +
            (renderErr && renderErr.message ? renderErr.message : renderErr);
        }
      } else {
        const conn = resolvePanelConn(hb, state.connLive, state.open);
        renderMotorStrip(hb, conn);
        renderBinanceConn(conn, state.open);
      }
      if (snap && snap.ok === false) {
        statusMsg =
          "Snapshot hata: " + (snap.error || "ok=false") + " — sayfayı yenileyin";
      } else if (!snap && !statusMsg) {
        statusMsg = "Snapshot boş yanıt — sunucu meşgul olabilir";
      }
      if (statusMsg) {
        setText("kpi-balance-sub", statusMsg);
        showFatalBanner(statusMsg);
      } else {
        showFatalBanner("");
      }
      setPanelApiStatus(snap, lat, statusMsg);
      const ts = (snap && snap.ts) || new Date().toISOString();
      setText("footer-ts", String(ts).slice(0, 19).replace("T", " "));
    } catch (err) {
      const aborted = err && err.name === "AbortError";
      const errMsg = aborted
        ? "Snapshot " + Math.round(SNAP_FETCH_MS / 1000) + "s zaman aşımı — bot yoğun veya restart"
        : snapshotErrorMessage(0) + (err && err.message ? " (" + err.message + ")" : "");
      setText("kpi-balance-sub", errMsg);
      setPanelApiStatus(null, null, errMsg);
    } finally {
      hideLoadingOverlay();
    }
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
      const res = await fetch("/api/logs/process?" + params.toString(), FETCH_OPTS);
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

  const controlState = { state: "RUNNING", timer: null };

  function appendControlLog(line) {
    const view = document.getElementById("mega-log-view");
    if (!view) return;
    const ts = new Date().toLocaleTimeString("tr-TR", { hour12: false });
    const span = document.createElement("span");
    span.className = "mega-log-line mega-log-control";
    span.textContent = "[" + ts + "] [CONTROL] " + line;
    if (view.querySelector(".mega-log-empty")) view.innerHTML = "";
    view.appendChild(span);
    view.appendChild(document.createTextNode("\n"));
    const wrap = document.getElementById("mega-log-view-wrap");
    if (wrap && document.getElementById("mega-log-autoscroll")?.checked) {
      wrap.scrollTop = wrap.scrollHeight;
    }
  }

  function applyControlUi(st) {
    if (!st) return;
    controlState.state = st.state || "RUNNING";
    const pauseBtn = document.getElementById("btn-pause");
    const startBtn = document.getElementById("btn-start");
    const wipeBtn = document.getElementById("btn-wipe-data");
    const label = document.getElementById("control-state-label");
    const badge = document.getElementById("badge-control");
    const hint = document.getElementById("control-pause-hint");
    if (label) label.textContent = controlState.state;
    if (badge) badge.textContent = controlState.state;
    const pausing = controlState.state === "PAUSING";
    if (pauseBtn) {
      pauseBtn.disabled = controlState.state !== "RUNNING";
      pauseBtn.classList.toggle("is-pulsing", pausing);
      pauseBtn.textContent = pausing ? "Durduruluyor…" : "Durdur";
    }
    if (startBtn) startBtn.disabled = controlState.state !== "PAUSED";
    if (wipeBtn) wipeBtn.disabled = controlState.state === "RESTARTING";
    if (hint) {
      if (pausing) {
        hint.textContent =
          "Zararda " + (st.pending_losers || 0) + " pozisyon breakeven bekliyor";
      } else if (st.pause_warn) {
        hint.textContent = "Pause süresi uzadı";
      } else {
        hint.textContent = "";
      }
    }
  }

  async function fetchControlStatus() {
    try {
      const r = await fetch("/api/mega/control/status", FETCH_OPTS);
      if (!r.ok) return;
      applyControlUi(await r.json());
    } catch (_) {}
  }

  function bindControlButtons() {
    const pauseBtn = document.getElementById("btn-pause");
    const startBtn = document.getElementById("btn-start");
    const wipeBtn = document.getElementById("btn-wipe-data");
    if (pauseBtn) {
      pauseBtn.addEventListener("click", async () => {
        appendControlLog("durdur istendi");
        try {
          const r = await fetch("/api/mega/control/pause", {
            method: "POST",
            ...FETCH_OPTS,
          });
          applyControlUi(await r.json());
        } catch (e) {
          appendControlLog("durdur hata: " + e);
        }
      });
    }
    if (startBtn) {
      startBtn.addEventListener("click", async () => {
        appendControlLog("başlat istendi");
        try {
          const r = await fetch("/api/mega/control/start", {
            method: "POST",
            ...FETCH_OPTS,
          });
          applyControlUi(await r.json());
          fetchMega(true);
        } catch (e) {
          appendControlLog("başlat hata: " + e);
        }
      });
    }
    if (wipeBtn) {
      wipeBtn.addEventListener("click", async () => {
        const msg =
          "Borsadaki açık pozisyonlar kapatılır, açık/kapalı kayıtlar arşivlenip silinir, oturum $5000 anchor ile sıfırlanır. Motor PAUSED kalır. Emin misiniz?";
        if (!confirm(msg)) return;
        appendControlLog("veri silme istendi");
        wipeBtn.disabled = true;
        try {
          const r = await fetch("/api/mega/data/reset", {
            method: "POST",
            ...FETCH_OPTS,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              reason: "panel_wipe",
              capital: 5000,
              close_exchange: true,
            }),
          });
          const j = await r.json();
          if (!r.ok) throw new Error(j.detail || r.statusText);
          applyControlUi(j);
          appendControlLog(
            "sıfırlandı anchor=$" +
              (j.reset && j.reset.wallet_anchor != null ? j.reset.wallet_anchor : "5000")
          );
          fetchMega(true);
        } catch (e) {
          appendControlLog("veri silme hata: " + e);
          wipeBtn.disabled = false;
        }
      });
    }
    fetchControlStatus();
    controlState.timer = setInterval(fetchControlStatus, 2000);
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
      const durCell = tr.children[9];
      if (!durCell) return;
      const d = positionAgeSec(row);
      setTextNode(durCell, d != null ? fmtDuration(d) : "—");
    });
  }

  function refreshOpenUpnlKpi(audit) {
    if (!state.open || !state.open.length) return;
    const agg = aggregateApiUpnl(state.open);
    const upnlEl = document.getElementById("kpi-upnl");
    if (upnlEl) {
      setTextNode(upnlEl, agg.complete ? fmtUpnl(agg.sum) : "—");
      syncToneClass(
        upnlEl,
        "mega-kpi-value num-usd",
        agg.complete ? pnlClass(agg.sum) : "neutral"
      );
    }
    let sub = agg.complete
      ? "Binance API · " + state.open.length + " açık"
      : "API uPnL eksik · " + agg.missing + "/" + state.open.length;
    const a = audit || state.upnlAudit;
    const cacheMs =
      state.lastTickCacheAgeMs != null
        ? state.lastTickCacheAgeMs
        : Math.min.apply(
            null,
            state.open.map((p) =>
              Number(p.exchange_data_age_ms || p.positions_cache_age_ms || 99999)
            )
          );
    if (Number.isFinite(cacheMs) && cacheMs < 90000) {
      sub += " · risk " + Math.round(cacheMs) + "ms";
    }
    if (a && a.wallet_unrealized != null && agg.complete) {
      const d = Number(a.delta);
      if (!a.ok && Math.abs(d) >= 1.0) {
        sub +=
          " · cüzdan " +
          fmtUpnl(a.wallet_unrealized) +
          " (Δ" +
          (d >= 0 ? "+" : "") +
          d.toFixed(2) +
          ")";
      }
    }
    setText("kpi-upnl-sub", sub);
  }

  function mergeTickIntoOpen(tick) {
    if (!tick || !tick.symbol) return null;
    let idx = state.open.findIndex(
      (p) => Number(p.id) === Number(tick.id) && tick.id != null
    );
    if (idx < 0) idx = state.open.findIndex((p) => p.symbol === tick.symbol);
    if (idx < 0) return null;
    const exIn =
      tick.exchange_display && typeof tick.exchange_display === "object"
        ? tick.exchange_display
        : null;
    const apiFromTick =
      exIn && exIn.unRealizedProfit != null && exIn.unRealizedProfit !== ""
        ? Number(exIn.unRealizedProfit)
        : tick.exchange_unrealized_pnl != null &&
            Number.isFinite(Number(tick.exchange_unrealized_pnl))
          ? Number(tick.exchange_unrealized_pnl)
          : null;
    if (apiFromTick == null || !Number.isFinite(apiFromTick)) {
      return null;
    }
    const merged = Object.assign({}, state.open[idx], tick);
    if (tick.positions_cache_age_ms != null) {
      merged.positions_cache_age_ms = tick.positions_cache_age_ms;
    }
    if (tick.exchange_data_age_ms != null) {
      merged.exchange_data_age_ms = tick.exchange_data_age_ms;
    }
    const ex = Object.assign({}, state.open[idx].exchange_display || {}, exIn || {});
    ex.unRealizedProfit = String(apiFromTick);
    if (exIn) {
      if (exIn.percentage != null && exIn.percentage !== "") ex.percentage = exIn.percentage;
      if (exIn.isolatedMargin != null && exIn.isolatedMargin !== "") {
        ex.isolatedMargin = exIn.isolatedMargin;
      }
      if (exIn.positionInitialMargin != null && exIn.positionInitialMargin !== "") {
        ex.positionInitialMargin = exIn.positionInitialMargin;
      }
    }
    if (exIn && exIn.markPrice != null && exIn.markPrice !== "") {
      ex.markPrice = exIn.markPrice;
    } else if (tick.mark_price != null || tick.current_price != null) {
      ex.markPrice = String(tick.mark_price ?? tick.current_price);
    }
    merged.exchange_display = ex;
    merged.exchange_unrealized_pnl = apiFromTick;
    merged.unrealized_pnl = apiFromTick;
    merged.upnl_missing = false;
    if (tick.mark_price != null || tick.current_price != null) {
      merged.mark_price = tick.mark_price ?? tick.current_price;
      merged.current_price = merged.mark_price;
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
    renderBinanceConn(state.connLive, state.open);
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
      const res = await fetch("/api/paper/" + MODE_ID + "/ticks", FETCH_OPTS);
      if (!res.ok) return;
      const data = await res.json();
      if (data && data.upnl_audit) state.upnlAudit = data.upnl_audit;
      if (data && data.positions_cache_age_ms != null) {
        state.lastTickCacheAgeMs = data.positions_cache_age_ms;
      }
      if (data && data.ok && data.open && data.open.length) {
        applyTickRows(data.open);
        refreshOpenUpnlKpi(data.upnl_audit);
      }
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

  function startConnPoll() {
    if (connTimer) clearInterval(connTimer);
    fetchConnectionLive();
    connTimer = setInterval(fetchConnectionLive, CONN_POLL_MS);
  }

  async function init() {
    try {
      bindActions();
      bindControlButtons();
      bindOpenTable();
      bindLiveLogControls();
      ensureMotorStrip();
      if (global.EliteConnectionBanner && global.EliteConnectionBanner.start) {
        global.EliteConnectionBanner.start();
      }
      startConnPoll();
      tickClock();
      setInterval(tickClock, 1000);
      setInterval(tickHeroLive, HERO_TICK_MS);
      const overlayFailsafe = setTimeout(hideLoadingOverlay, 8000);
      try {
        await fetchMega(false);
      } finally {
        clearTimeout(overlayFailsafe);
        hideLoadingOverlay();
      }
    } catch (initErr) {
      const msg =
        "Panel başlatma hatası: " +
        (initErr && initErr.message ? initErr.message : initErr);
      showFatalBanner(msg);
      setText("kpi-balance-sub", msg);
      hideLoadingOverlay();
    }
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
