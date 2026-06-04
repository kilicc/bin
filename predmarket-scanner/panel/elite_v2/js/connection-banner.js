(function (global) {
  "use strict";

  var POLL_MS = 5000;
  var timer = null;
  var lastSeverity = "ok";

  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function fmtTime() {
    return new Date().toLocaleTimeString("tr-TR");
  }

  function pillClass(severity) {
    if (severity === "critical") return "bad";
    if (severity === "warn") return "warn";
    return "ok";
  }

  function pipelineHint(data) {
    var pl = (data && data.pipeline) || {};
    var alerts = (data && data.alerts) || [];
    var codes = {};
    alerts.forEach(function (a) {
      if (a && a.code) codes[a.code] = a;
    });
    if (codes.hub_feed_down || codes.hub_feed_stale) return "Hub kopuk";
    if (codes.scan_ticks_missing || codes.fast_tick_stale) return "Tarama durdu";
    if (codes.mega_paused || codes.mega_entries_off) return "Giriş kapalı";
    if (pl.symbols_with_ticks != null && pl.watchlist_total) {
      return pl.symbols_with_ticks + "/" + pl.watchlist_total + " tick";
    }
    return "";
  }

  function pillLabel(data) {
    var b = (data && data.binance) || {};
    var ph = pipelineHint(data);
    if ((data && data.severity) === "critical") {
      if (ph) return ph;
      if (b.ip_ban_active) return "Binance IP banlı";
      if (b.auth_error) return "Binance auth hatası";
      return "Açılış engelli";
    }
    if ((data && data.severity) === "warn") {
      if (ph) return ph;
      if (b.api_paper) return "Paper mod";
      return "Bağlantı uyarısı";
    }
    if (ph) return ph;
    return "Binance bağlı · " + (b.endpoint || "mainnet").replace(" (mainnet)", "");
  }

  function renderBar(data) {
    var bar = document.getElementById("conn-alert-bar");
    if (!bar) return;

    var sev = (data && data.severity) || "ok";
    var alerts = (data && data.alerts) || [];

    if (sev === "ok" || !alerts.length) {
      bar.classList.remove("visible");
      bar.innerHTML = "";
      lastSeverity = "ok";
      return;
    }

    bar.classList.add("visible");
    var innerClass = sev === "critical" ? "critical" : "warn";
    var icon = sev === "critical" ? "⛔" : "⚠️";
    var primary = alerts[0];

    var listHtml = "";
    if (alerts.length > 1) {
      listHtml =
        '<ul class="conn-alert-list">' +
        alerts
          .slice(1, 5)
          .map(function (a) {
            return "<li><strong>" + esc(a.title) + ":</strong> " + esc(a.detail) + "</li>";
          })
          .join("") +
        "</ul>";
    }

    bar.innerHTML =
      '<div class="conn-alert-inner ' +
      innerClass +
      '">' +
      '<span class="conn-alert-icon">' +
      icon +
      "</span>" +
      '<div class="conn-alert-body">' +
      '<p class="conn-alert-title">' +
      esc(primary.title) +
      "</p>" +
      '<p class="conn-alert-detail">' +
      esc(primary.detail) +
      "</p>" +
      listHtml +
      "</div>" +
      '<span class="conn-alert-ts">' +
      fmtTime() +
      "</span>" +
      "</div>";

    if (sev !== lastSeverity && sev === "critical") {
      try {
        document.title = "⛔ " + (document.title.replace(/^⛔ /, "") || "MEGA");
      } catch (_) {}
    } else if (lastSeverity === "critical" && sev === "ok") {
      try {
        document.title = document.title.replace(/^⛔ /, "");
      } catch (_) {}
    }
    lastSeverity = sev;
  }

  function renderPill(data) {
    var pill = document.getElementById("hub-conn-pill");
    if (!pill) return;
    var sev = (data && data.severity) || "ok";
    pill.className = "hub-conn-pill " + pillClass(sev);
    pill.textContent = pillLabel(data);
    pill.title = ((data && data.alerts) || [])
      .map(function (a) {
        return a.title + ": " + a.detail;
      })
      .join("\n");
  }

  async function poll() {
    try {
      var r = await fetch("/api/connection/alerts", {
        cache: "no-store",
        credentials: "include",
      });
      if (!r.ok) {
        var st = r.status;
        var hint =
          st === 502 || st === 503
            ? "nginx → bot (127.0.0.1:9006) kapalı veya yeniden başlıyor — deploy/restart sonrası ~30sn bekleyin"
            : st === 401 || st === 403
              ? "nginx girişi gerekli (9086: kullanıcı x, şifre x369)"
              : "HTTP " + st;
        throw new Error(hint);
      }
      var data = await r.json();
      renderBar(data);
      renderPill(data);
    } catch (e) {
      var msg = e && e.message ? String(e.message) : String(e);
      var fail = {
        severity: "critical",
        alerts: [
          {
            title: "Panel ↔ bot (/api/connection/alerts)",
            detail: msg + " — Binance API değil; yerel MEGA bot (port 9006) veya nginx proxy.",
          },
        ],
        binance: { api_ok: false },
      };
      renderBar(fail);
      renderPill(fail);
    }
  }

  function start() {
    if (timer) clearInterval(timer);
    poll();
    timer = setInterval(poll, POLL_MS);
  }

  global.EliteConnectionBanner = { start: start, poll: poll };
})(window);
