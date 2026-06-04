(function () {
  "use strict";

  function $(id) {
    return document.getElementById(id);
  }

  async function api(path, opts) {
    const r = await fetch(path, Object.assign({ credentials: "same-origin" }, opts || {}));
    const j = await r.json().catch(function () {
      return { ok: false, error: "invalid json" };
    });
    if (!r.ok) throw new Error(j.detail || j.error || String(r.status));
    return j;
  }

  async function loadStatus() {
    const j = await api("/api/develop/status");
    $("dev-status").textContent = JSON.stringify(j, null, 2);
    if (j.scenario) $("scenario-out").textContent = JSON.stringify(j.scenario, null, 2);
  }

  async function loadProposals() {
    const st = $("proposal-filter").value;
    const q = st ? "?status=" + encodeURIComponent(st) : "";
    const j = await api("/api/develop/proposals" + q);
    const host = $("proposal-list");
    host.innerHTML = (j.proposals || [])
      .map(function (p) {
        const id = p.id || "";
        const pending = (p.status || "") === "pending";
        return (
          '<div class="proposal-row">' +
          '<div><strong>' +
          (p.title || id) +
          "</strong> <span class='muted'>" +
          (p.status || "") +
          "</span></div>" +
          "<div class='muted'>" +
          (p.rationale || "").slice(0, 200) +
          "</div>" +
          (pending
            ? '<div class="dev-row">' +
              '<button type="button" class="btn mega-btn-primary" data-approve="' +
              id +
              '">Onayla</button>' +
              '<button type="button" class="btn" data-reject="' +
              id +
              '">Red</button>' +
              "</div>"
            : "") +
          "</div>"
        );
      })
      .join("") || "<span class='muted'>Öneri yok</span>";
    host.querySelectorAll("[data-approve]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        await api("/api/learner/proposals/" + encodeURIComponent(btn.dataset.approve) + "/approve", {
          method: "POST",
        });
        loadProposals();
      });
    });
    host.querySelectorAll("[data-reject]").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        await api("/api/learner/proposals/" + encodeURIComponent(btn.dataset.reject) + "/reject", {
          method: "POST",
        });
        loadProposals();
      });
    });
  }

  function bind() {
    $("btn-refresh-status")?.addEventListener("click", function () {
      loadStatus().catch(function (e) {
        alert(e.message);
      });
    });
    $("btn-bootstrap")?.addEventListener("click", async function () {
      const j = await api("/api/develop/knowledge/bootstrap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force: false }),
      });
      $("bootstrap-msg").textContent = JSON.stringify(j);
      loadStatus();
    });
    $("btn-bootstrap-force")?.addEventListener("click", async function () {
      const j = await api("/api/develop/knowledge/bootstrap", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force: true }),
      });
      $("bootstrap-msg").textContent = JSON.stringify(j);
      loadStatus();
    });
    $("btn-self-check")?.addEventListener("click", async function () {
      $("self-check-out").textContent = "…";
      const j = await api("/api/develop/checks");
      $("self-check-out").textContent = JSON.stringify(j, null, 2);
    });
    $("btn-restart-ctl")?.addEventListener("click", async function () {
      if (!confirm("9007 ctl restart?")) return;
      const j = await api("/api/develop/restart", { method: "POST" });
      $("restart-msg").textContent = JSON.stringify(j);
    });
    $("btn-restart-systemd")?.addEventListener("click", async function () {
      if (!confirm("systemd restart (GCP)?")) return;
      const j = await api("/api/develop/systemd-restart", { method: "POST" });
      $("restart-msg").textContent = JSON.stringify(j);
    });
    $("btn-load-proposals")?.addEventListener("click", loadProposals);
    $("btn-tail-log")?.addEventListener("click", async function () {
      const j = await api("/api/logs/process?tail=80");
      $("log-out").textContent = (j.lines || []).join("\n") || j.error || "boş";
    });
  }

  EliteAdminGate.init({
    appId: "app-root",
    onReady: function () {
      bind();
      loadStatus().catch(function () {});
      loadProposals().catch(function () {});
    },
  });
})();
