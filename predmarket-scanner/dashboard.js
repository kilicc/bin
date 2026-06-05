/* Elite Pro V2 — live dashboard */
(function () {
  "use strict";

  const POLL_LIVE_MS = 300;
  const POLL_CONN_MS = 500;
  const POLL_MONITOR_MS = 2000;
  const POLL_FEED_MS = 2500;

  const $ = (sel) => document.querySelector(sel);
  const fmtUsd = (n) => {
    const v = Number(n);
    if (!Number.isFinite(v)) return "—";
    const sign = v < 0 ? "-" : "";
    return sign + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  };
  const fmtPct = (n) => {
    const v = Number(n);
    if (!Number.isFinite(v)) return "—";
    return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
  };
  const fmtNum = (n, d = 0) => {
    const v = Number(n);
    if (!Number.isFinite(v)) return "—";
    return v.toLocaleString("en-US", { maximumFractionDigits: d });
  };
  const fmtUsdPrec = (n, d = 4) => {
    const v = Number(n);
    if (!Number.isFinite(v)) return "—";
    const sign = v < 0 ? "-" : "";
    return sign + "$" + Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: d });
  };
  const fmtDuration = (sec) => {
    const s = Number(sec);
    if (!Number.isFinite(s) || s < 0) return "—";
    if (s < 60) return Math.round(s) + "s";
    const m = Math.floor(s / 60);
    const r = Math.round(s % 60);
    if (m < 60) return m + "m " + r + "s";
    const h = Math.floor(m / 60);
    return h + "h " + (m % 60) + "m";
  };
  const fmtTime = (t) => {
    if (!t) return "—";
    const s = String(t);
    if (s.length >= 19) return s.slice(0, 19).replace("T", " ");
    return s;
  };
  const fmtTrEntryRow = (row) => {
    const u = window.ClosedTradeUtils;
    return u ? u.fmtTrEntry(row) : fmtTime(row.entry_time || row.opened_at_iso || row.entry_time_str);
  };
  const fmtTrExitRow = (row) => {
    const u = window.ClosedTradeUtils;
    return u ? u.fmtTrExit(row) : fmtTime(row.exit_time || row.exit_time_str || row.exit_time_iso);
  };
  const esc = (s) =>
    String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/"/g, "&quot;");
  const shortId = (id) => {
    const s = String(id || "");
    if (!s) return "—";
    return s.length > 10 ? s.slice(-10) : s;
  };

  const state = {
    live: null,
    conn: null,
    monitor: null,
    feed: null,
    prev: {},
    equitySmooth: [],
    pollLatency: 0,
    chartView: "carousel",
    heroIndex: 0,
    heroSymbol: "",
    heroRotateAt: 0,
    viewLocked: false,
    lastOpenCount: 0,
  };

  let rejectChart = null;

  function chartsReady() {
    return window.TradingCharts && window.LightweightCharts;
  }

  function plotPositionChart(targetId, p, opts) {
    if (!chartsReady()) return;
    window.TradingCharts.plotPosition(targetId, p, opts);
  }

  function plotEquityChart(targetId, d, opts) {
    if (!chartsReady()) return;
    window.TradingCharts.plotEquity(targetId, d, opts);
  }

  function renderEquityStrip(d) {
    plotEquityChart("chart-equity-strip", d, { compact: true });
  }

  function getOpenPositions(d) {
    const open = (d && d.positions && d.positions.open) || (d && d.strip_open_positions) || [];
    return open.slice().sort((a, b) => tpProgress(b) - tpProgress(a));
  }

  function positionKey(p) {
    return String((p && p.symbol) || "") + "|" + String((p && p.id) || "");
  }

  function resolveHeroIndex(open) {
    if (!open.length) return 0;
    if (state.heroSymbol) {
      const idx = open.findIndex((p) => positionKey(p) === state.heroSymbol);
      if (idx >= 0) return idx;
    }
    const idx = Math.min(state.heroIndex, open.length - 1);
    state.heroSymbol = positionKey(open[Math.max(0, idx)]);
    return Math.max(0, idx);
  }

  function selectHeroPosition(open, idx) {
    state.heroIndex = Math.max(0, Math.min(idx, open.length - 1));
    state.heroSymbol = positionKey(open[state.heroIndex]);
    state.heroRotateAt = Date.now();
  }

  function tpProgress(p) {
    const entry = Number(p.entry_price);
    const cur = Number(p.current_price);
    const tp = Number(p.tp_target);
    if (!entry || !cur || !tp || entry === tp) return 0;
    const side = String(p.side || "LONG").toUpperCase();
    let num = side === "SHORT" ? entry - cur : cur - entry;
    let den = side === "SHORT" ? entry - tp : tp - entry;
    if (Math.abs(den) < 1e-12) return 0;
    return Math.max(0, Math.min(1.35, num / den));
  }

  function netPnl(p) {
    return Number(p.mark_unrealized_pnl ?? p.unrealized_pnl ?? 0);
  }

  function setText(id, text) {
    const el = document.getElementById(id);
    if (el && el.textContent !== text) el.textContent = text;
  }

  function animateKpi(id, value, formatter, cls) {
    const el = document.getElementById(id);
    if (!el) return;
    const prev = state.prev[id];
    const next = formatter(value);
    if (el.textContent !== next) {
      el.textContent = next;
      el.className = "kpi-value " + (cls || "neutral");
      if (prev !== undefined && prev !== value) {
        const card = el.closest(".kpi");
        if (card) {
          card.classList.remove("flash-up", "flash-down");
          void card.offsetWidth;
          card.classList.add(Number(value) >= Number(prev) ? "flash-up" : "flash-down");
        }
      }
    }
    state.prev[id] = value;
  }

  function statusClass(ok, warn) {
    if (ok) return "ok";
    if (warn) return "warn";
    return "bad";
  }

  function renderHeader(d) {
    const mode = d.execution_label || d.execution_mode || d.mode || "—";
    setText("badge-mode", mode.toUpperCase());
    setText("badge-view", (d.view_label || d.view_mode || "LIVE").toUpperCase());
    const live = d.live_orders || d.api_connected;
    const badgeLive = $("#badge-live");
    if (badgeLive) {
      badgeLive.textContent = live ? "CANLI EMİR" : "OFFLINE";
      badgeLive.className = "badge " + (live ? "live" : "");
    }
    setText("display-note", d.display_note || "");
  }

  function renderConnection(conn) {
    if (!conn) return;
    const cards = [
      {
        id: "conn-api",
        ok: conn.api_ok,
        title: conn.api_label && conn.api_label.startsWith("MEGA") ? "MEGA API" : "Demo API",
        value: conn.api_ok ? "BAĞLI" : "KOPUK",
        sub: conn.auth_error ? String(conn.auth_error).slice(0, 60) : (conn.api_label || "demo-fapi.binance.com"),
      },
      {
        id: "conn-mark",
        ok: conn.mark_ws && conn.mark_ws.health === "ok",
        warn: conn.mark_ws && conn.mark_ws.health === "stale",
        title: "Mark WS",
        value: (conn.mark_ws && conn.mark_ws.source) || "—",
        sub: `lag ${fmtNum(conn.mark_ws && conn.mark_ws.lag_ms, 0)}ms · ${fmtNum(conn.mark_ws && conn.mark_ws.coins, 0)} coin`,
      },
      {
        id: "conn-book",
        ok: conn.bookticker && conn.bookticker.ok,
        title: "BookTicker",
        value: conn.bookticker && conn.bookticker.ok ? "AKTİF" : "STALE",
        sub: `lag ${fmtNum(conn.bookticker && conn.bookticker.lag_ms, 0)}ms · ${fmtNum(conn.bookticker && conn.bookticker.coins, 0)} coin`,
      },
      {
        id: "conn-rest",
        ok: conn.rest && (conn.rest.coins || 0) >= 5,
        title: "REST Fiyat",
        value: fmtNum(conn.rest && conn.rest.coins, 0) + " sembol",
        sub: `age ${fmtNum(conn.rest && conn.rest.age_ms, 0)}ms · açık ${fmtNum(conn.open_positions, 0)}`,
      },
    ];
    cards.forEach((c) => {
      const el = document.getElementById(c.id);
      if (!el) return;
      el.className = "conn-card " + statusClass(c.ok, c.warn);
      el.innerHTML =
        `<div class="conn-label"><span class="status-dot ${statusClass(c.ok, c.warn)}"></span>${c.title}</div>` +
        `<div class="conn-value">${c.value}</div>` +
        `<div class="conn-sub">${c.sub}</div>`;
    });
  }

  function closedNetSum(d, s) {
    if (s && s.realized_pnl != null && Number.isFinite(Number(s.realized_pnl))) {
      return Number(s.realized_pnl);
    }
    const closed = (d.positions && d.positions.closed) || d.strip_recent_closed || [];
    return closed.reduce((acc, t) => {
      const n = Number(t.wallet_pnl ?? t.final_pnl ?? t.net_pnl ?? t.pnl_usd ?? 0);
      return acc + (Number.isFinite(n) ? n : 0);
    }, 0);
  }

  function numUsd(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  function pickCapital(s, ms, d) {
    const live = !!(d && d.live_orders);
    if (live) {
      return (
        numUsd(s.exchange_margin_balance) ??
        numUsd(s.current_capital) ??
        numUsd(s.equity) ??
        numUsd(ms.current_capital)
      );
    }
    return (
      numUsd(s.current_capital) ??
      numUsd(s.session_total_balance) ??
      numUsd(s.equity) ??
      numUsd(s.available_capital) ??
      numUsd(s.starting_capital) ??
      numUsd(s.session_anchor) ??
      numUsd(ms.current_capital)
    );
  }

  function pickAvail(s, ms, d, cap, start) {
    const live = !!(d && d.live_orders);
    if (live) {
      return (
        numUsd(s.exchange_available_balance) ??
        numUsd(s.available_capital) ??
        numUsd(s.available_balance) ??
        numUsd(ms.exchange_balance)
      );
    }
    return (
      numUsd(s.available_capital) ??
      numUsd(s.session_available_est) ??
      numUsd(s.available_balance) ??
      (cap != null && start != null ? cap : null)
    );
  }

  function renderKpis(d, mon) {
    const s = d.summary || {};
    const ms = mon && mon.summary ? mon.summary : {};
    const motor =
      (d.elite && d.elite.motor_pipeline) ||
      (mon && mon.motor) ||
      (mon && mon.elite && mon.elite.motor_pipeline) ||
      {};
    const scan = d.mega_scan || (mon && mon.mega_scan) || {};
    const execMode = motor.execution_mode || d.execution_mode || "berserk2";
    const maxOpen = motor.max_open ?? ms.max_open ?? (execMode === "mega" ? 4 : 10);

    const start = s.starting_capital ?? s.session_anchor ?? ms.starting_capital ?? ms.session_anchor;
    const cap = pickCapital(s, ms, d);
    const avail = pickAvail(s, ms, d, cap, start);

    const upnl = s.unrealized_pnl ?? s.exchange_unrealized_pnl ?? ms.unrealized_pnl ?? 0;
    const sessionPnl = closedNetSum(d, s);
    const totalEquityPnl =
      cap != null && start != null && Number(start) > 0
        ? Number(cap) - Number(start)
        : s.total_pnl != null && Number.isFinite(Number(s.total_pnl))
          ? Number(s.total_pnl)
          : sessionPnl + Number(upnl || 0);

    const sessionPct =
      start > 0 && Number.isFinite(sessionPnl)
        ? (sessionPnl / Number(start)) * 100
        : null;
    const open = s.open_trades ?? ms.open_positions ?? (d.positions && d.positions.open && d.positions.open.length) ?? 0;
    const closedN = s.closed_trades ?? ms.closed_trades ?? 0;
    const wr = s.win_rate;
    const queue = motor.queue_len ?? motor.queue ?? 0;
    const realized = sessionPnl;

    animateKpi("kpi-balance", cap, fmtUsd, "neutral");
    animateKpi("kpi-pnl", sessionPnl, fmtUsd, Number(sessionPnl) >= 0 ? "up" : "down");
    animateKpi("kpi-upnl", upnl, fmtUsd, Number(upnl) >= 0 ? "up" : "down");
    animateKpi("kpi-open", open, (v) => String(v) + " / " + maxOpen, "neutral");
    animateKpi("kpi-winrate", wr, (v) => (Number.isFinite(Number(v)) ? Number(v).toFixed(1) + "%" : "—"), "neutral");
    animateKpi("kpi-queue", queue, (v) => String(v), queue > 0 ? "up" : "neutral");

    const balSub = [];
    if (start) balSub.push("Başlangıç " + fmtUsd(start));
    if (avail != null && Number.isFinite(Number(avail))) balSub.push("Kullanılabilir " + fmtUsd(avail));
    const walletBal = numUsd(s.exchange_wallet_balance);
    if (walletBal != null && walletBal > 0 && d.live_orders) {
      balSub.push("Cüzdan " + fmtUsd(walletBal));
    }
    setText("kpi-balance-sub", balSub.join(" · ") || "Binance demo API");

    const pnlSub = [];
    if (sessionPct != null) pnlSub.push(fmtPct(sessionPct));
    pnlSub.push("Realize " + fmtUsd(realized));
    if (
      Number.isFinite(totalEquityPnl) &&
      Math.abs(totalEquityPnl - sessionPnl) > 0.05
    ) {
      pnlSub.push("Toplam " + fmtUsd(totalEquityPnl) + " (açık dahil)");
    }
    setText("kpi-pnl-sub", pnlSub.join(" · ") || "Kapalı işlemler toplamı");

    setText(
      "kpi-upnl-sub",
      "Mark uPnL · " +
        open +
        " açık" +
        (scan.candidates_recent != null ? " · " + scan.candidates_recent + " aday" : "")
    );
    setText(
      "kpi-open-sub",
      execMode +
        " motor · max " +
        maxOpen +
        (motor.orders_opened ? " · " + motor.orders_opened + " emir" : "")
    );
    setText("kpi-winrate-sub", closedN + " kapalı" + (s.win_count != null ? " · " + s.win_count + " kâr" : ""));
    const qSub = [];
    if (motor.reject_top_txt) qSub.push(motor.reject_top_txt);
    if (scan.last_scan_age_sec != null) qSub.push("Tur " + scan.last_scan_age_sec + "s");
    if (scan.scanned_recent != null) qSub.push("Tarama " + scan.scanned_recent);
    setText("kpi-queue-sub", qSub.join(" · ").slice(0, 72) || "Motor sinyal kuyruğu");
  }

  function renderEquityChart(d) {
    renderHeroTheater(d);
  }

  function renderHeroTheater(d) {
    if (!chartsReady()) return;
    const open = getOpenPositions(d);
    const heroEl = document.getElementById("chart-hero");
    const stripEl = document.getElementById("chart-equity-strip");
    const gridEl = document.getElementById("hero-grid");
    const thumbsEl = document.getElementById("hero-thumbs");
    const theater = document.querySelector(".hero-theater");
    if (!heroEl) return;

    if (
      open.length &&
      !state.viewLocked &&
      state.chartView === "equity" &&
      state.lastOpenCount === 0
    ) {
      state.chartView = "carousel";
      document.querySelectorAll(".view-btn").forEach((b) =>
        b.classList.toggle("active", b.dataset.view === "carousel")
      );
    }
    state.lastOpenCount = open.length;

    state.heroIndex = resolveHeroIndex(open);

    setText("hero-index", open.length ? state.heroIndex + 1 + " / " + open.length : "—");

    const showStrip = state.chartView === "combo" && open.length > 0;
    if (stripEl) stripEl.classList.toggle("hidden", !showStrip);
    if (theater) theater.classList.toggle("equity-live", !open.length || state.chartView === "equity");
    heroEl.classList.toggle("compact", showStrip);
    if (showStrip) renderEquityStrip(d);

    if (state.chartView === "equity" || !open.length) {
      if (gridEl) gridEl.classList.add("hidden");
      if (window.TradingCharts) {
        window.TradingCharts.destroyPrefix("hero-grid-");
        window.TradingCharts.hideOhlcBar();
      }
      heroEl.classList.remove("hidden");
      plotEquityChart("chart-hero", d, { compact: false });
      setText(
        "hero-subtitle",
        open.length
          ? "Equity · " + open.length + " pozisyon — Grid/Karma ile gezin"
          : "Session equity — canlı akış"
      );
      setText("hero-upnl", fmtUsd(d.summary && d.summary.unrealized_pnl));
      setText("hero-tp-pct", "—");
      setText("hero-tp-usd", "—");
      const bar = document.getElementById("hero-tp-bar");
      if (bar) {
        bar.style.width = "0%";
        bar.classList.remove("hot");
      }
      if (thumbsEl) {
        thumbsEl.innerHTML = open.length
          ? open
              .map(
                (p, i) =>
                  `<div class="hero-thumb" data-i="${i}"><div class="sym">${p.symbol}</div><div class="pnl">${fmtUsd(netPnl(p))}</div></div>`
              )
              .join("")
          : '<span style="color:var(--dim);font-size:11px">Pozisyon açılınca TP sıralı çipler burada</span>';
      }
      return;
    }

    if (state.chartView === "grid") {
      heroEl.classList.add("hidden");
      if (gridEl) {
        gridEl.classList.remove("hidden");
        if (window.TradingCharts) window.TradingCharts.destroyPrefix("hero-grid-");
        const cells = open.slice(0, 6);
        gridEl.innerHTML = cells
          .map(
            (p, i) =>
              `<div class="hero-grid-cell"><div class="hero-grid-label">${p.symbol} · ${(p.side || "").toUpperCase()} · TP ${Math.round(tpProgress(p) * 100)}%</div><div id="hero-grid-${i}" class="hero-grid-chart"></div></div>`
          )
          .join("");
        cells.forEach((p, i) => {
          plotPositionChart("hero-grid-" + i, p, { compact: true });
        });
      }
      renderHeroThumbs(open);
      const p0 = open[0];
      if (p0) updateHeroMeta(p0);
      setText("hero-subtitle", open.length + " pozisyon · grid (TP yakınlığı, en fazla 6)");
      return;
    }

    heroEl.classList.remove("hidden");
    if (gridEl) gridEl.classList.add("hidden");
    const p = open[state.heroIndex] || open[0];
    if (!p) return;
    updateHeroMeta(p);
    setText(
      "hero-subtitle",
      `${p.symbol} · ${String(p.side || "").toUpperCase()} · TP hedefine %${Math.round(tpProgress(p) * 100)}` +
        (state.chartView === "combo" ? " · üstte equity şeridi" : "")
    );
    plotPositionChart("chart-hero", p, { compact: false });
    renderHeroThumbs(open);
  }

  function updateHeroMeta(p) {
    const prog = tpProgress(p);
    const pnl = netPnl(p);
    const upnlEl = document.getElementById("hero-upnl");
    if (upnlEl) {
      upnlEl.textContent = fmtUsd(pnl);
      upnlEl.className = "val " + (pnl >= 0 ? "up" : "down");
    }
    setText("hero-tp-pct", Math.round(prog * 100) + "%");
    setText("hero-tp-usd", fmtUsd(p.tp_target_usd || p.tp_net_target_usd));
    const bar = document.getElementById("hero-tp-bar");
    if (bar) {
      bar.style.width = Math.min(100, prog * 100) + "%";
      bar.classList.toggle("hot", prog >= 0.75);
    }
  }

  function renderHeroThumbs(open) {
    const thumbsEl = document.getElementById("hero-thumbs");
    if (!thumbsEl) return;
    thumbsEl.innerHTML = open
      .map((p, i) => {
        const prog = tpProgress(p);
        const pnl = netPnl(p);
        return (
          `<div class="hero-thumb ${i === state.heroIndex ? "active" : ""}" data-i="${i}">` +
          `<div class="sym">${p.symbol}</div>` +
          `<div class="side ${String(p.side || "").toLowerCase()}">${String(p.side || "").toUpperCase()}</div>` +
          `<div class="pnl ${pnl >= 0 ? "up" : "down"}">${fmtUsd(pnl)}</div>` +
          `<div class="tp-mini"><i style="width:${Math.min(100, prog * 100)}%"></i></div></div>`
        );
      })
      .join("");
    thumbsEl.querySelectorAll(".hero-thumb").forEach((el) => {
      el.addEventListener("click", () => {
        selectHeroPosition(open, Number(el.getAttribute("data-i")) || 0);
        if (state.live) renderHeroTheater(state.live);
      });
    });
  }

  function renderRejectLegend(top, colors) {
    const legend = $("#reject-legend");
    if (!legend) return;
    const rows = top.slice(0, 4);
    if (!rows.length) {
      legend.innerHTML = '<li class="reject-legend-empty">Red yok</li>';
      return;
    }
    legend.innerHTML = rows
      .map((r, i) => {
        const raw = String(r.reason || r.label || "?").replace(/_/g, " ");
        const lbl = raw.length > 16 ? raw.slice(0, 15) + "…" : raw;
        const cnt = fmtNum(r.count || 0, 0);
        const col = colors[i % colors.length];
        return (
          `<li title="${esc(raw)}">` +
          `<span class="dot" style="background:${col}"></span>` +
          `<span class="lbl">${esc(lbl)}</span>` +
          `<span class="cnt">${cnt}</span></li>`
        );
      })
      .join("");
  }

  function renderRejectChart(d) {
    const motor = (d.elite && d.elite.motor_pipeline) || {};
    const top = motor.reject_top || [];
    const ctx = document.getElementById("chart-rejects");
    if (!ctx || typeof Chart === "undefined") return;

    setText("reject-total", motor.reject_total != null ? fmtNum(motor.reject_total, 0) + " red" : "—");

    const colors = ["#00d4ff", "#a78bfa", "#fbbf24", "#ff4466"];

    if (!top.length) {
      if (rejectChart) {
        rejectChart.destroy();
        rejectChart = null;
      }
      renderRejectLegend([], colors);
      return;
    }

    const labels = top.slice(0, 4).map((r) => String(r.reason || r.label || "?"));
    const data = top.slice(0, 4).map((r) => r.count || 0);
    renderRejectLegend(top, colors);

    if (rejectChart) rejectChart.destroy();
    rejectChart = new Chart(ctx, {
      type: "doughnut",
      data: {
        labels,
        datasets: [{ data, backgroundColor: colors, borderWidth: 0, hoverOffset: 2 }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "68%",
        layout: { padding: 0 },
        plugins: {
          legend: { display: false },
          tooltip: {
            titleFont: { size: 10 },
            bodyFont: { size: 10 },
            callbacks: {
              title: (items) => {
                const i = items[0] && items[0].dataIndex;
                const full = top[i] && (top[i].reason || top[i].label);
                return full ? String(full).replace(/_/g, " ") : "";
              },
            },
          },
        },
      },
    });
  }

  function renderPositions(d) {
    const wrap = $("#positions-grid");
    if (!wrap) return;
    const open = getOpenPositions(d);
    if (!open.length) {
      wrap.innerHTML =
        '<div class="empty-state" style="grid-column:1/-1"><div class="icon">◎</div><p>Açık pozisyon yok</p><p style="margin-top:8px;font-size:11px">Motor giriş arıyor — üstteki canlı alanda equity akışı görünür</p></div>';
      return;
    }
    wrap.innerHTML = '<div class="pos-strip">' +
      open
        .map((p, i) => {
          const prog = Math.round(tpProgress(p) * 100);
          const pnl = netPnl(p);
          return (
            `<div class="pos-strip-card" data-i="${i}">` +
            `<div style="display:flex;justify-content:space-between;align-items:center">` +
            `<strong style="font-family:var(--mono)">${p.symbol}</strong>` +
            `<span class="${pnl >= 0 ? "pnl-pos" : "pnl-neg"}">${fmtUsd(pnl)}</span></div>` +
            `<div style="font-size:10px;color:var(--muted);margin-top:6px">TP ${prog}% · ${fmtUsd(p.tp_target_usd)}</div></div>`
          );
        })
        .join("") +
      "</div>";
    wrap.querySelectorAll(".pos-strip-card").forEach((el) => {
      el.addEventListener("click", () => {
        selectHeroPosition(open, Number(el.getAttribute("data-i")) || 0);
        state.chartView = state.chartView === "grid" ? "grid" : "carousel";
        state.viewLocked = false;
        document.querySelectorAll(".view-btn").forEach((b) =>
          b.classList.toggle("active", b.dataset.view === state.chartView)
        );
        if (state.live) renderHeroTheater(state.live);
      });
    });
  }

  function renderSignals(d) {
    const track = $("#signal-track");
    if (!track) return;
    const sigs = [
      ...(d.approaching_signals || []),
      ...(d.signals || []),
      ...(d.approaching_reversal_signals || []),
    ].slice(0, 24);
    if (!sigs.length) {
      track.innerHTML = '<span style="color:var(--dim);font-size:12px">Aktif sinyal yok — motor bekliyor</span>';
      return;
    }
    track.innerHTML = sigs
      .map((s) => {
        const side = (s.type || s.side || "LONG").toUpperCase();
        const sym = s.symbol || "?";
        const chg = s.change != null ? fmtPct(s.change) : "";
        return `<div class="signal-chip ${side.toLowerCase()}"><span class="sym">${sym}</span> ${side} ${chg}</div>`;
      })
      .join("");
  }

  function renderHeat(d, feed) {
    const grid = $("#heat-grid");
    if (!grid) return;
    const deltas = d.price_deltas || {};
    const prices = d.watchlist_prices || {};
    const sample = (feed && feed.sample_prices) || {};
    const keys = new Set([...Object.keys(deltas), ...Object.keys(prices), ...Object.keys(sample)]);
    if (!keys.size) {
      grid.innerHTML = '<div style="color:var(--dim);font-size:11px;padding:12px">Fiyat akışı yükleniyor…</div>';
      return;
    }
    const arr = [...keys].slice(0, 45).map((coin) => {
      const chg = deltas[coin];
      const px = prices[coin] ?? sample[coin];
      let bg = "rgba(255,255,255,0.04)";
      if (chg != null) {
        if (chg > 0.05) bg = "rgba(0, 255, 136, 0.2)";
        else if (chg > 0) bg = "rgba(0, 255, 136, 0.08)";
        else if (chg < -0.05) bg = "rgba(255, 68, 102, 0.2)";
        else if (chg < 0) bg = "rgba(255, 68, 102, 0.08)";
      }
      return (
        `<div class="heat-cell" style="background:${bg}">` +
        `<span class="coin">${coin}</span>` +
        `<span class="chg">${chg != null ? fmtPct(chg) : fmtNum(px, 2)}</span></div>`
      );
    });
    grid.innerHTML = arr.join("");
  }

  function renderClosed(d) {
    const tbody = $("#closed-body");
    if (!tbody) return;
    let closed = (d.positions && d.positions.closed) || d.strip_recent_closed || [];
    const u = window.ClosedTradeUtils;
    if (u) closed = u.sortClosedByExitDesc(closed);
    if (!closed.length) {
      tbody.innerHTML =
        '<tr><td colspan="26" style="text-align:center;color:var(--dim);padding:24px">Henüz kapalı işlem yok</td></tr>';
      return;
    }
    tbody.innerHTML = closed
      .slice(0, 200)
      .map((t) => {
        const wallet = t.wallet_pnl ?? t.final_pnl ?? t.net_pnl ?? t.pnl_usd ?? 0;
        const net = t.net_pnl ?? wallet;
        const gross = t.pnl_usd ?? t.exchange_realized_pnl ?? net;
        const cls = Number(wallet) >= 0 ? "pnl-pos" : "pnl-neg";
        const entryFee = Number(t.entry_fee || 0);
        const exitFee = Number(t.exit_fee || 0);
        const totalFees = Number(t.total_fees || entryFee + exitFee);
        const tax = Number(t.tax || 0);
        const exchPnl = t.exchange_realized_pnl;
        const dataSrc = t.data_source || t.fee_source || t.pnl_source || "—";
        const side = String(t.side || "").toUpperCase();
        const sideCls = side === "LONG" ? "pnl-pos" : side === "SHORT" ? "pnl-neg" : "";
        return (
          "<tr data-closed-id=\"" +
          esc(t.id) +
          "\">" +
          `<td class="col-sticky-left"><strong>${esc(t.symbol || "—")}</strong>` +
          `<span class="closed-id-sub">#${esc(t.id || "—")}</span></td>` +
          `<td class="${sideCls}">${esc(side || "—")}</td>` +
          `<td>${fmtNum(t.leverage, 0)}x</td>` +
          `<td>${fmtUsd(t.stake_usd)}</td>` +
          `<td>${fmtTrEntryRow(t)}</td>` +
          `<td>${fmtTrExitRow(t)}</td>` +
          `<td>${fmtDuration(t.duration)}</td>` +
          `<td>${fmtNum(t.entry_price, 4)}</td>` +
          `<td>${fmtNum(t.exit_price, 4)}</td>` +
          `<td>${fmtNum(t.signal_fill_px, 4)}</td>` +
          `<td>${fmtUsdPrec(gross)}</td>` +
          `<td class="${cls}">${fmtUsdPrec(net)}</td>` +
          `<td class="${cls}">${fmtUsdPrec(wallet)}</td>` +
          `<td>${exchPnl != null ? fmtUsdPrec(exchPnl) : "—"}</td>` +
          `<td>${fmtUsdPrec(tax)}</td>` +
          `<td>${fmtUsdPrec(entryFee)}</td>` +
          `<td>${fmtUsdPrec(exitFee)}</td>` +
          `<td>${fmtUsdPrec(totalFees)}</td>` +
          `<td>${t.order_ack_ms != null ? fmtNum(t.order_ack_ms, 0) : "—"}</td>` +
          `<td>${t.settle_ms != null ? fmtNum(t.settle_ms, 0) : "—"}</td>` +
          `<td>${t.total_close_ms != null ? fmtNum(t.total_close_ms, 0) : "—"}</td>` +
          `<td><span class="closed-order-id" title="${esc(t.exchange_order_id)}">${esc(shortId(t.exchange_order_id))}</span></td>` +
          `<td><span class="closed-order-id" title="${esc(t.exchange_close_order_id)}">${esc(shortId(t.exchange_close_order_id))}</span></td>` +
          `<td>${esc(dataSrc)}</td>` +
          `<td>${esc(t.exit_reason || "—")}</td>` +
          `<td class="col-sticky-right"><button type="button" class="closed-del-btn" data-delete-closed="${esc(t.id)}" data-symbol="${esc(t.symbol)}" data-exit-time="${esc(t.exit_time)}">Sil</button></td>` +
          "</tr>"
        );
      })
      .join("");
  }

  async function deleteClosedTrade(btn) {
    const id = btn.getAttribute("data-delete-closed");
    const symbol = btn.getAttribute("data-symbol") || "";
    const exitTime = btn.getAttribute("data-exit-time") || "";
    if (!id) return;
    const label = symbol ? `${symbol} #${id}` : `#${id}`;
    if (!window.confirm(`${label} kaydını listeden silmek istiyor musunuz?\n\nKayıt arşivlenir; win-rate ve realized PnL yeniden hesaplanır.`)) {
      return;
    }
    btn.disabled = true;
    btn.textContent = "…";
    try {
      const r = await fetch("/api/closed/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: Number(id), symbol, exit_time: exitTime }),
      });
      const j = await r.json();
      if (!j.ok) {
        window.alert(j.error || "Silme başarısız");
        btn.disabled = false;
        btn.textContent = "Sil";
        return;
      }
      if (j.snapshot) {
        state.live = j.snapshot;
        renderAll();
      } else {
        await pollLive();
      }
    } catch (err) {
      window.alert(String(err && err.message ? err.message : err));
      btn.disabled = false;
      btn.textContent = "Sil";
    }
  }

  function renderHealth(d, mon) {
    const grid = $("#health-grid");
    if (!grid) return;
    const loops = (d.system_health && d.system_health.loops) || [];
    const rs = (mon && mon.read_speed) || {};
    const items = [];

    loops.forEach((l) => {
      items.push({
        name: l.name || l.label || "?",
        val: l.interval_ms != null ? l.interval_ms + "ms" : l.status || "—",
        sub: l.detail || l.last_ago_ms != null ? "ago " + l.last_ago_ms + "ms" : "",
        cls: l.ok === false ? "bad" : l.warn ? "warn" : "ok",
      });
    });

    if (rs.mark_ws_lag_ms != null) {
      items.push({ name: "Mark lag", val: rs.mark_ws_lag_ms + "ms", sub: "WS", cls: rs.mark_ws_lag_ms < 200 ? "ok" : "warn" });
    }
    if (rs.book_lag_ms != null) {
      items.push({ name: "Book lag", val: rs.book_lag_ms + "ms", sub: "bookTicker", cls: rs.book_lag_ms < 300 ? "ok" : "warn" });
    }
    if (rs.exchange_position_poll_ms != null) {
      items.push({
        name: "positionRisk",
        val: rs.exchange_position_poll_ms + "ms",
        sub: "poll",
        cls: rs.exchange_position_poll_ms < 800 ? "ok" : "warn",
      });
    }

    if (!items.length) {
      grid.innerHTML = '<div style="color:var(--dim);font-size:11px">Health verisi bekleniyor…</div>';
      return;
    }

    grid.innerHTML = items
      .map(
        (h) =>
          `<div class="health-card ${h.cls}">` +
          `<div class="health-name">${h.name}</div>` +
          `<div class="health-val">${h.val}</div>` +
          `<div class="health-sub">${h.sub}</div></div>`
      )
      .join("");
  }

  function renderScanner(d, mon) {
    const el = $("#scanner-meta");
    if (!el) return;
    const sc = d.scanner_status || {};
    const motor = (d.elite && d.elite.motor_pipeline) || (mon && mon.motor) || {};
    el.textContent = [
      "Poll " + fmtNum(sc.exchange_poll_ms, 0) + "ms",
      "Cache " + fmtNum(sc.exchange_cache_age_ms, 0) + "ms",
      "Kuyruk +" + fmtNum(motor.queue_added, 0),
      "Red " + fmtNum(motor.reject_total, 0),
      "Pass " + fmtNum(motor.motor_pass_pct, 1) + "%",
    ].join(" · ");
  }

  function renderAll() {
    const d = state.live || {};
    renderHeader(d);
    renderConnection(state.conn);
    renderKpis(d, state.monitor);
    renderEquityChart(d);
    renderRejectChart(d);
    renderPositions(d);
    renderSignals(d);
    renderHeat(d, state.feed);
    renderClosed(d);
    renderHealth(d, state.monitor);
    renderScanner(d, state.monitor);

    const latEl = $("#poll-latency");
    if (latEl) {
      latEl.textContent = state.pollLatency + "ms";
      latEl.className = "lat-pill " + (state.pollLatency < 600 ? "" : state.pollLatency < 1200 ? "warn" : "bad");
    }
    setText("footer-ts", d.ts ? new Date(d.ts).toLocaleTimeString("tr-TR") : "—");
  }

  async function fetchJson(url, timeoutMs) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs || 4000);
    const t0 = performance.now();
    try {
      const r = await fetch(url, { signal: ctrl.signal, cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      return await r.json();
    } finally {
      clearTimeout(t);
      state.pollLatency = Math.round(performance.now() - t0);
    }
  }

  async function mergePaperSnapshot(base) {
    if (base && base.live_orders) return base;
    const mode =
      (base && base.execution_mode) ||
      (base && base.view_mode) ||
      "berserk2";
    try {
      const paper = await fetchJson("/api/paper/" + mode + "/snapshot?light=0", 3500);
      if (!paper || !paper.ok) return base;
      const merged = Object.assign({}, base || {});
      merged.positions = {
        open: paper.open || [],
        closed: paper.closed || [],
      };
      merged.summary = Object.assign({}, (base && base.summary) || {}, paper.summary || {});
      merged.display_source = "mode_book";
      merged.open_positions_source = "mode_book";
      merged.execution_mode = mode;
      return merged;
    } catch (_) {
      return base;
    }
  }

  async function pollLive() {
    try {
      state.live = await fetchJson("/api/live?light=0", 3500);
    } catch (e) {
      try {
        state.live = await fetchJson("/api/live", 2500);
      } catch (_) {}
    }
    state.live = await mergePaperSnapshot(state.live);
    renderAll();
  }

  async function pollConn() {
    try {
      state.conn = await fetchJson("/api/connection/live", 2000);
      renderConnection(state.conn);
    } catch (_) {}
  }

  async function pollMonitor() {
    try {
      state.monitor = await fetchJson("/api/monitor/snapshot", 2500);
      renderHealth(state.live, state.monitor);
      renderScanner(state.live, state.monitor);
      renderKpis(state.live, state.monitor);
    } catch (_) {}
  }

  async function pollFeed() {
    try {
      state.feed = await fetchJson("/api/price-feed/status", 2000);
      renderHeat(state.live, state.feed);
    } catch (_) {}
  }

  function tickClock() {
    const el = $("#live-clock");
    if (el) el.textContent = new Date().toLocaleTimeString("tr-TR", { hour12: false });
  }

  function bindActions() {
    document.querySelectorAll(".view-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.chartView = btn.dataset.view || "carousel";
        state.viewLocked = state.chartView === "equity";
        document.querySelectorAll(".view-btn").forEach((b) => b.classList.toggle("active", b === btn));
        state.heroRotateAt = Date.now();
        if (state.live) renderHeroTheater(state.live);
      });
    });
    const prev = $("#hero-prev");
    const next = $("#hero-next");
    if (prev) {
      prev.addEventListener("click", () => {
        const open = getOpenPositions(state.live);
        if (!open.length) return;
        const cur = resolveHeroIndex(open);
        selectHeroPosition(open, (cur - 1 + open.length) % open.length);
        if (state.live) renderHeroTheater(state.live);
      });
    }
    if (next) {
      next.addEventListener("click", () => {
        const open = getOpenPositions(state.live);
        if (!open.length) return;
        const cur = resolveHeroIndex(open);
        selectHeroPosition(open, (cur + 1) % open.length);
        if (state.live) renderHeroTheater(state.live);
      });
    }
    const btnReconnect = $("#btn-reconnect");
    if (btnReconnect) {
      btnReconnect.addEventListener("click", async () => {
        btnReconnect.disabled = true;
        try {
          await fetch("/api/price-feed/reconnect", { method: "POST" });
        } catch (_) {}
        btnReconnect.disabled = false;
      });
    }
    const btnRefresh = $("#btn-refresh");
    if (btnRefresh) {
      btnRefresh.addEventListener("click", () => {
        pollLive();
        pollConn();
      });
    }
    const closedBody = $("#closed-body");
    if (closedBody) {
      closedBody.addEventListener("click", (ev) => {
        const btn = ev.target.closest("[data-delete-closed]");
        if (!btn) return;
        ev.preventDefault();
        deleteClosedTrade(btn);
      });
    }
  }

  async function init() {
    tickClock();
    setInterval(tickClock, 1000);
    bindActions();
    await pollLive();
    await pollConn();
    pollMonitor();
    pollFeed();
    setInterval(pollLive, POLL_LIVE_MS);
    setInterval(pollConn, POLL_CONN_MS);
    setInterval(pollMonitor, POLL_MONITOR_MS);
    setInterval(pollFeed, POLL_FEED_MS);
    const overlay = $("#loading-overlay");
    if (overlay) overlay.classList.add("hidden");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
