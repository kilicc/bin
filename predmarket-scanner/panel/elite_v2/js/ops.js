(function () {
  "use strict";

  let timer = null;

  function $(id) {
    return document.getElementById(id);
  }

  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function fmtNum(v, digits) {
    if (v == null || v === "" || Number.isNaN(Number(v))) return "—";
    return Number(v).toFixed(digits == null ? 1 : digits);
  }

  async function api(path) {
    const r = await fetch(path, { credentials: "same-origin" });
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  }

  function statRow(lbl, val, cls) {
    return (
      '<div class="hub-stat-row"><span class="hub-stat-lbl">' +
      esc(lbl) +
      '</span><span class="hub-stat-val ' +
      (cls || "") +
      '">' +
      esc(val) +
      "</span></div>"
    );
  }

  function summaryCard(title, ok, body) {
    return (
      '<div class="hub-card ' +
      (ok ? "ok" : "bad") +
      '"><h3>' +
      esc(title) +
      "</h3>" +
      body +
      "</div>"
    );
  }

  function perfSection(title, rows) {
    if (!rows) return "";
    return (
      '<div class="ops-detail-block"><div class="ops-detail-title">' +
      esc(title) +
      "</div>" +
      rows +
      "</div>"
    );
  }

  function botCard(b) {
    const meta = b.meta || {};
    const perf = b.perf || {};
    const reachable = b.reachable;
    const healthOk = b.health_ok;
    const paper = b.api_paper;
    const liveOrders = !!meta.live_orders;
    const bt = b.bookticker || {};
    const mw = b.mark_ws || {};
    const wsOk = !!bt.ok;

    let badge, badgeCls;
    if (!reachable) {
      badge = "KAPALI";
      badgeCls = "bad";
    } else if (healthOk) {
      badge = liveOrders ? "CANLI" : "ÇALIŞIYOR";
      badgeCls = "ok";
    } else if (liveOrders && paper) {
      badge = "PAPER";
      badgeCls = "warn";
    } else {
      badge = "UYARI";
      badgeCls = "warn";
    }

    const barPct = reachable ? (healthOk ? 100 : wsOk ? 55 : 25) : 8;
    const barCls = healthOk ? "ok" : reachable ? "warn" : "bad";

    let rows = statRow("Rol", (meta.name || "?") + " · port " + b.port, "");
    rows += statRow(
      "Process ping",
      reachable ? fmtNum(b.ping_ms, 1) + " ms" : "Hayır",
      b.ping_ms != null && b.ping_ms <= 80 ? "ok" : b.ping_ms != null && b.ping_ms <= 200 ? "warn" : reachable ? "bad" : "bad"
    );
    if (b.conn_ms != null) {
      rows += statRow("Conn özeti", fmtNum(b.conn_ms, 1) + " ms", b.conn_ms <= 400 ? "ok" : "warn");
    }
    rows += statRow(
      "Binance REST",
      b.binance_rest_label || (b.api_ok ? "Bağlı" : "Kopuk"),
      b.binance_rest_class || (b.api_ok ? "ok" : meta.rest_expected === false ? "ok" : "bad")
    );
    if (liveOrders) {
      rows += statRow("Mod", paper ? "Paper fallback" : "Canlı emir", paper ? "warn" : "ok");
    } else {
      rows += statRow("Mod", "Paper / sim (tasarım)", "ok");
    }
    rows += statRow("Uç nokta", b.api_label || "—", "");
    if (b.auth_error && liveOrders) {
      rows += statRow("Auth", String(b.auth_error).slice(0, 90), "bad");
    }

    var btLag = bt.lag_ms != null ? bt.lag_ms + " ms" : "—";
    rows += statRow(
      "BookTicker WS",
      bt.ok ? "OK · " + (bt.coins || 0) + " coin · lag " + btLag : "Kopuk",
      bt.ok ? "ok" : "bad"
    );
    if (mw.health) {
      rows += statRow(
        "Mark WS",
        (mw.health || "—") + (mw.lag_ms != null ? " · lag " + mw.lag_ms + " ms" : ""),
        mw.health === "ok" ? "ok" : "warn"
      );
    }
    rows += statRow(
      "Açık poz.",
      String(b.open_positions != null ? b.open_positions : perf.live_open != null ? perf.live_open : "—") +
        (perf.live_max_open != null ? " / max " + perf.live_max_open : ""),
      ""
    );

    if (perf.session_pnl != null || perf.equity != null) {
      rows += statRow(
        "Oturum PnL",
        perf.session_pnl != null ? "$" + fmtNum(perf.session_pnl, 2) : "—",
        perf.session_pnl > 0 ? "ok" : perf.session_pnl < 0 ? "bad" : ""
      );
      if (perf.equity != null) rows += statRow("Equity", "$" + fmtNum(perf.equity, 2), "");
      if (perf.closed_trades != null) rows += statRow("Kapalı", String(perf.closed_trades), "");
    }

    var motorRows =
      statRow("Motor eval", perf.motor_eval_ms != null ? perf.motor_eval_ms + " ms" : "—", perf.motor_eval_ms <= 300 ? "ok" : "warn") +
      statRow("Motor aralık", perf.motor_interval_ms != null ? perf.motor_interval_ms + " ms" : "—", "") +
      statRow("Son motor", perf.motor_ago_sec != null ? perf.motor_ago_sec + " s önce" : "—", perf.motor_ago_sec != null && perf.motor_ago_sec < 3 ? "ok" : "warn") +
      statRow("Pozisyon tick", perf.position_tick_ms != null ? perf.position_tick_ms + " ms" : "—", "") +
      statRow("Kuyruk", perf.motor_queue != null ? String(perf.motor_queue) : "—", "") +
      statRow("Thread", (perf.threads_alive || 0) + "/" + (perf.threads_total || 0), perf.threads_alive === perf.threads_total ? "ok" : "warn");
    if (perf.reject_top) motorRows += statRow("Red (top)", perf.reject_top, "warn");
    if (perf.orders_opened != null) motorRows += statRow("Açılan", String(perf.orders_opened), "");

    var syncRows =
      statRow("REST coin", perf.rest_coins != null ? String(perf.rest_coins) : "—", "") +
      statRow("REST yaş", perf.rest_age_ms != null ? perf.rest_age_ms + " ms" : "—", "") +
      statRow("Exchange poll", perf.exchange_poll_ms != null ? perf.exchange_poll_ms + " ms" : "—", "");
    if (perf.exchange_api_ema_ms != null) {
      syncRows += statRow("Borsa API EMA", perf.exchange_api_ema_ms + " ms", "");
    }
    if (perf.mega_rest_worker != null) {
      syncRows += statRow("MEGA REST worker", perf.mega_rest_worker ? "Aktif" : "Kapalı", perf.mega_rest_worker ? "ok" : "bad");
    }
    if (perf.mega_close_sync_ago != null) {
      syncRows += statRow("Close sync", perf.mega_close_sync_ago + " s önce", "");
    }

    var hs = b.health_strip || {};
    var megaApi = hs.mega_api || {};
    var ctrl = hs.control || {};
    var extra = "";
    if (b.port === 9007) {
      extra =
        perfSection("Motor", motorRows) +
        perfSection("Sync / REST", syncRows) +
        perfSection(
          "9007 kontrol",
          statRow("Motor state", ctrl.state || "—", ctrl.state === "RUNNING" ? "ok" : "warn") +
            statRow("Outage", megaApi.outage_active ? "Evet · recovery bekliyor" : "Hayır", megaApi.outage_active ? "warn" : "ok") +
            statRow("Fresh start", megaApi.fresh_start_on_recovery ? "Açık" : "Kapalı", "")
        );
    } else {
      extra = perfSection("Motor / tarama", motorRows) + perfSection("Veri", syncRows);
    }

    var deskPort = b.port === 9005 ? ":9085" : b.port === 9006 ? ":9086/paper" : ":9087/paper";
    var deskHost = location.hostname || "127.0.0.1";
    var links =
      '<div class="ops-bot-links">' +
      '<a href="http://' + deskHost + deskPort + '" target="_blank" rel="noopener">Desk</a>' +
      '<a href="/develop">Develop</a>' +
      '<a href="/lab">Lab</a>' +
      "</div>";

    return (
      '<div class="hub-card hub-card-glow ops-bot-card ' +
      (healthOk ? "ok" : reachable ? "warn" : "bad") +
      '">' +
      '<span class="hub-badge ' +
      badgeCls +
      '">' +
      badge +
      "</span>" +
      "<h3>Bot " +
      b.port +
      "</h3>" +
      '<div class="ops-bot-bar"><div class="ops-bot-bar-fill ' +
      barCls +
      '" style="width:' +
      barPct +
      '%"></div></div>' +
      rows +
      extra +
      links +
      "</div>"
    );
  }

  function alertCard(a) {
    const cls = a.level === "critical" ? "bad" : "warn";
    return (
      '<div class="hub-card ' +
      cls +
      '"><h3>' +
      esc(a.title) +
      "</h3><p style='margin:0;font-size:0.82rem;color:var(--hub-muted)'>" +
      esc(a.detail) +
      "</p></div>"
    );
  }

  function llmCard(title, data, ok) {
    if (!data) data = {};
    let rows = "";
    if (data.provider) rows += statRow("Sağlayıcı", data.provider, "");
    if (data.latency_ms != null) rows += statRow("Gecikme", data.latency_ms + " ms", data.ok ? "ok" : "bad");
    rows += statRow("Durum", data.ok ? "OK" : data.skipped ? "Atlandı" : "Hata", data.ok ? "ok" : "bad");
    if (data.error) rows += statRow("Hata", String(data.error).slice(0, 100), "bad");
    return summaryCard(title, ok, rows);
  }

  function render(data) {
    var pl = data.probe_latency || {};
    var probeNote = "";
    if (pl.ping_ms_max != null) {
      probeNote = " · probe " + fmtNum(data.probe_total_ms, 0) + " ms (ping max " + fmtNum(pl.ping_ms_max, 1) + " ms)";
    }
    $("ops-ts").textContent = "Son güncelleme: " + new Date().toLocaleTimeString("tr-TR") + probeNote;

    const bots = data.bots || [];
    const liveCount = bots.filter(function (b) {
      return b.health_ok;
    }).length;
    const llmOk = (data.llm && data.llm.primary && data.llm.primary.ok) || false;
    const alerts = data.connection_alerts || [];

    $("ops-summary").innerHTML =
      summaryCard(
        "Botlar",
        liveCount >= 1,
        statRow("Sağlıklı", liveCount + " / 3", liveCount === 3 ? "ok" : liveCount ? "warn" : "bad") +
          statRow("Ping max", pl.ping_ms_max != null ? pl.ping_ms_max + " ms" : "—", pl.ping_ms_max <= 80 ? "ok" : "warn") +
          statRow("Conn max", pl.conn_ms_max != null ? pl.conn_ms_max + " ms" : "—", pl.conn_ms_max <= 500 ? "ok" : "warn")
      ) +
      summaryCard(
        "LLM",
        llmOk,
        statRow("Primary", llmOk ? "OK" : "—", llmOk ? "ok" : "bad")
      ) +
      summaryCard(
        "Lab KB",
        !!(data.knowledge && data.knowledge.bootstrapped),
        statRow("Bootstrap", data.knowledge && data.knowledge.bootstrapped ? "Tamam" : "Eksik", data.knowledge && data.knowledge.bootstrapped ? "ok" : "warn") +
          statRow("Dersler", String((data.knowledge && data.knowledge.lessons_count) || 0), "")
      );

    const alertHost = $("ops-alerts");
    if (alerts.length) {
      alertHost.innerHTML = alerts.map(alertCard).join("");
    } else {
      alertHost.innerHTML =
        '<div class="hub-card ok"><h3>Tüm bağlantılar normal</h3><p style="margin:0;font-size:0.82rem;color:var(--hub-muted)">Kritik uyarı yok. Binance koparsa üst bant otomatik kırmızı olur.</p></div>';
    }

    $("ops-bots").innerHTML = bots.map(botCard).join("");

    const llm = data.llm || {};
    $("ops-llm").innerHTML =
      llmCard("Primary · " + ((llm.configured || {}).LAB_LLM_PROVIDER || "?"), llm.primary, (llm.primary || {}).ok) +
      llmCard("Fallback · " + ((llm.configured || {}).LAB_LLM_FALLBACK || "—"), llm.fallback, (llm.fallback || {}).ok);

    const k = data.knowledge || {};
    $("ops-knowledge").innerHTML =
      statRow("Bootstrap", k.bootstrapped ? "Evet · " + (k.bootstrap_ts || "") : "Hayır", k.bootstrapped ? "ok" : "warn") +
      statRow("Sys doküman", (k.sys_documents || []).length + " dosya", "") +
      statRow("Dersler", String(k.lessons_count || 0), "") +
      statRow("Oturumlar", String(k.sessions_count || 0), "");

    const strip = data.health_strip || {};
    const ctrl = strip.control || {};
    const cs = strip.close_sync || {};
    const ps = strip.position_sync || {};
    const megaApi = strip.mega_api || {};
    $("ops-strip").innerHTML =
      statRow("Control", (ctrl.state || "—") + " · motor " + (ctrl.motor_active ? "aktif" : "kapalı"), ctrl.state === "RUNNING" ? "ok" : "warn") +
      statRow("Close sync", cs.alive ? (cs.last_run_ago_sec != null ? cs.last_run_ago_sec + " s önce" : "OK") : "—", cs.alive ? "ok" : "bad") +
      statRow("Position sync", ps.alive ? (ps.last_run_ago_sec != null ? ps.last_run_ago_sec + " s önce" : "OK") : "—", ps.alive ? "ok" : "bad") +
      statRow("MEGA outage", megaApi.outage_active ? "Aktif" : "Yok", megaApi.outage_active ? "warn" : "ok") +
      statRow("Recovery", megaApi.recovery_enabled ? "Açık" : "Kapalı", megaApi.recovery_enabled ? "ok" : "warn");
  }

  async function refresh() {
    const fresh = $("ops-fresh-llm")?.checked ? "1" : "0";
    const data = await api("/api/ops/dashboard?fresh=" + fresh);
    render(data);
  }

  function schedule() {
    if (timer) clearInterval(timer);
    if ($("ops-auto")?.checked) timer = setInterval(refresh, 8000);
  }

  function bind() {
    $("btn-ops-refresh")?.addEventListener("click", function () {
      refresh().catch(function (e) {
        alert(e.message);
      });
    });
    $("ops-auto")?.addEventListener("change", schedule);
    schedule();
    refresh().catch(function () {});
  }

  EliteAdminGate.init({
    appId: "app-root",
    onReady: bind,
  });
})();
