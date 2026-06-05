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

  function botCard(b) {
    const reachable = b.reachable;
    const apiOk = b.api_ok;
    const paper = b.api_paper;
    const bt = (b.bookticker || {}).ok;
    const ok = reachable && apiOk && !paper && bt;
    const badge = ok ? "ok" : reachable ? "warn" : "bad";
    const badgeTxt = ok ? "CANLI" : paper ? "PAPER" : reachable ? "UYARI" : "KAPALI";
    const barPct = reachable ? (apiOk ? (paper ? 55 : 100) : 35) : 8;
    const barCls = ok ? "ok" : reachable ? "warn" : "bad";

    let rows = statRow("Erişim", reachable ? "Evet · " + (b.latency_ms || "?") + " ms" : "Hayır", reachable ? "ok" : "bad");
    rows += statRow("Binance API", apiOk ? "Bağlı" : "Kopuk", apiOk ? "ok" : "bad");
    rows += statRow("Mod", paper ? "Paper / sim" : "Mainnet live", paper ? "warn" : "ok");
    rows += statRow("Uç nokta", b.api_label || "—", "");
    if (b.auth_error) {
      rows += statRow("Auth hata", String(b.auth_error).slice(0, 80), "bad");
    }
    rows += statRow("Fiyat WS", bt ? "OK · " + ((b.bookticker || {}).coins || 0) + " coin" : "Kopuk", bt ? "ok" : "bad");
    rows += statRow("Açık poz.", String(b.open_positions != null ? b.open_positions : "—"), "");

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
      (ok ? "ok" : "bad") +
      '">' +
      '<span class="hub-badge ' +
      badge +
      '">' +
      badgeTxt +
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
    $("ops-ts").textContent = "Son güncelleme: " + new Date().toLocaleTimeString("tr-TR");

    const bots = data.bots || [];
    const liveCount = bots.filter(function (b) {
      return b.reachable && b.api_ok && !b.api_paper;
    }).length;
    const llmOk = (data.llm && data.llm.primary && data.llm.primary.ok) || false;
    const alerts = data.connection_alerts || [];

    $("ops-summary").innerHTML =
      summaryCard(
        "Botlar",
        liveCount >= 1,
        statRow("Canlı bağlı", liveCount + " / 3", liveCount === 3 ? "ok" : liveCount ? "warn" : "bad")
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
    const llmS = strip.llm || {};
    const labS = strip.lab || {};
    $("ops-strip").innerHTML =
      statRow("Mark WS", (strip.mark_ws && strip.mark_ws.health) || "—", strip.mark_ws && strip.mark_ws.health === "ok" ? "ok" : "warn") +
      statRow("BookTicker lag", strip.bookticker && strip.bookticker.lag_ms != null ? strip.bookticker.lag_ms + " ms" : "—", "") +
      statRow("LLM strip", llmS.ok ? "OK" : "—", llmS.ok ? "ok" : "bad") +
      statRow("Lab inflight", String(labS.inflight || 0), "");
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
