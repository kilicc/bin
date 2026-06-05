(function (global) {
  "use strict";

  function renderContext(host) {
    if (!host) return;
    host.innerHTML =
      '<span class="hub-ctx-pill"><span class="hub-ctx-dot pulse"></span>Hub yükleniyor…</span>';
    fetch("/api/connection/alerts", { credentials: "same-origin" })
      .then(function (r) {
        return r.json();
      })
      .then(function (d) {
        var alerts = d.alerts || [];
        var crit = alerts.some(function (a) {
          return a.level === "critical";
        });
        var warn = !crit && alerts.some(function (a) {
          return a.level === "warn";
        });
        var pills = ['<span class="hub-ctx-pill">Control Hub · :9087</span>'];
        if (crit) {
          pills.push('<span class="hub-ctx-pill bad">⛔ Binance / API uyarı</span>');
        } else if (warn) {
          pills.push('<span class="hub-ctx-pill warn">⚠ Bağlantı uyarısı</span>');
        } else {
          pills.push('<span class="hub-ctx-pill ok">✓ Bağlantı normal</span>');
        }
        pills.push(
          '<span class="hub-ctx-pill muted">' +
            new Date().toLocaleTimeString("tr-TR") +
            "</span>"
        );
        host.innerHTML = pills.join("");
      })
      .catch(function () {
        host.innerHTML =
          '<span class="hub-ctx-pill">Control Hub · :9087</span>' +
          '<span class="hub-ctx-pill muted">' +
          new Date().toLocaleTimeString("tr-TR") +
          "</span>";
      });
  }

  function init() {
    var host = document.getElementById("hub-context-strip");
    renderContext(host);
    setInterval(function () {
      renderContext(document.getElementById("hub-context-strip"));
    }, 30000);
  }

  global.EliteHubContext = { render: renderContext, init: init };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
