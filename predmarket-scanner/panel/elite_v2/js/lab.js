(function () {
  "use strict";
  let sessionId = "";
  let lastAssistant = "";

  function $(id) {
    return document.getElementById(id);
  }

  function bubble(role, text) {
    const el = document.createElement("div");
    el.className = "lab-bubble " + role;
    el.textContent = text;
    return el;
  }

  function log(role, text) {
    const host = $("lab-chat-log");
    if (!host) return;
    host.appendChild(bubble(role, text));
    host.scrollTop = host.scrollHeight;
    if (role === "assistant") lastAssistant = text;
  }

  async function loadSessions() {
    const r = await fetch("/api/lab/sessions", { credentials: "same-origin" });
    const j = await r.json();
    const host = $("lab-sessions");
    host.innerHTML = (j.sessions || [])
      .map(function (s) {
        return (
          '<div class="lab-session-item' +
          (s.id === sessionId ? " active" : "") +
          '" data-id="' +
          s.id +
          '">' +
          (s.id || "").slice(0, 8) +
          "…</div>"
        );
      })
      .join("");
    host.querySelectorAll(".lab-session-item").forEach(function (el) {
      el.addEventListener("click", function () {
        sessionId = el.dataset.id;
        loadSessions();
      });
    });
  }

  async function loadLessons() {
    const r = await fetch("/api/lab/lessons?limit=30", { credentials: "same-origin" });
    const j = await r.json();
    $("lab-lessons").innerHTML = (j.lessons || [])
      .slice()
      .reverse()
      .map(function (L) {
        return '<div class="lab-lesson">' + (L.text || "") + "</div>";
      })
      .join("");
  }

  async function loadDocuments() {
    const r = await fetch("/api/lab/documents", { credentials: "same-origin" });
    const j = await r.json();
    $("lab-documents").innerHTML = (j.documents || [])
      .map(function (d) {
        return "<div class='muted'>" + d.name + " (" + d.bytes + " B)</div>";
      })
      .join("") || "<span class='muted'>Henüz yok</span>";
  }

  async function fetchHealth() {
    try {
      const r = await fetch("/api/health/strip");
      const data = await r.json();
      const strip = $("health-strip");
      if (!strip) return;
      const lab = data.lab || {};
      const llm = data.llm || {};
      strip.innerHTML =
        '<div class="mega-health-pill ok"><span class="lbl">Lab</span><span class="val">' +
        (lab.inflight || 0) +
        " inflight</span></div>" +
        '<div class="mega-health-pill ' +
        (llm.ok ? "ok" : "slow") +
        '"><span class="lbl">LLM</span><span class="val">' +
        (lab.last_latency_ms ? lab.last_latency_ms + "ms" : llm.ok ? "OK" : "—") +
        "</span></div>";
    } catch (_) {}
  }

  async function fetchSim() {
    try {
      const r = await fetch("/api/lab/sim/counterfactual");
      $("lab-sim-out").textContent = JSON.stringify(await r.json(), null, 2);
    } catch (_) {}
  }

  async function checkRollbackBanner() {
    try {
      const r = await fetch("/api/checkpoints/recent?limit=3");
      const j = await r.json();
      const cp = (j.checkpoints || []).find(function (c) {
        return (c.event_type || "") === "rollback";
      });
      if (cp) {
        $("lab-banner").classList.remove("hidden");
        $("lab-banner").textContent = "Checkpoint geri yüklendi: " + (cp.label || cp.file);
      }
    } catch (_) {}
  }

  $("btn-lab-send")?.addEventListener("click", async function () {
    const msg = $("lab-message").value.trim();
    if (!msg) return;
    log("user", msg);
    const r = await fetch("/api/lab/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ session_id: sessionId, message: msg }),
    });
    const j = await r.json();
    if (j.session_id) sessionId = j.session_id;
    if (j.ok) log("assistant", j.text || "");
    else log("error", j.error || "LLM hatası");
    $("lab-message").value = "";
    loadSessions();
    loadLessons();
  });

  $("btn-new-session")?.addEventListener("click", function () {
    sessionId = "";
    $("lab-chat-log").innerHTML = "";
    loadSessions();
  });

  $("btn-save-lesson")?.addEventListener("click", async function () {
    if (!lastAssistant) return;
    await fetch("/api/lab/lessons", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ text: lastAssistant, session_id: sessionId }),
    });
    loadLessons();
  });

  $("btn-export")?.addEventListener("click", async function () {
    const url = "/api/lab/export" + (sessionId ? "?session_id=" + encodeURIComponent(sessionId) : "");
    const r = await fetch(url, { credentials: "same-origin" });
    const j = await r.json();
    if (j.data_b64) {
      const a = document.createElement("a");
      a.href = "data:application/zip;base64," + j.data_b64;
      a.download = "lab_export.zip";
      a.click();
    }
  });

  document.querySelectorAll("[data-motor]").forEach(function (btn) {
    btn.addEventListener("click", async function () {
      const r = await fetch("/api/lab/motor/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ motor: btn.dataset.motor }),
      });
      $("motor-out").textContent = JSON.stringify(await r.json(), null, 2);
    });
  });

  $("btn-lab-ingest")?.addEventListener("click", async function () {
    const text = $("lab-doc-text").value;
    const r = await fetch("/api/lab/documents/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ kind: "text", text: text, name: "paste.txt" }),
    });
    const j = await r.json();
    $("lab-ingest-status").textContent = j.ok ? "Kaydedildi: " + j.path : j.error || "Hata";
    loadDocuments();
  });

  function ingestFile(file) {
    const reader = new FileReader();
    reader.onload = async function () {
      const b64 = reader.result.split(",")[1];
      const kind = file.type || (file.name.endsWith(".pdf") ? "application/pdf" : "text/plain");
      const body =
        kind === "application/pdf"
          ? { kind: "pdf", data_b64: b64, name: file.name }
          : kind.startsWith("image/")
            ? { kind: kind, data_b64: b64, name: file.name, prompt: "Bu grafikte ne görüyorsun?" }
            : { kind: "text", text: atob(b64), name: file.name };
      const r = await fetch("/api/lab/documents/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(body),
      });
      const j = await r.json();
      $("lab-ingest-status").textContent = j.ok
        ? "Kaydedildi: " + (j.path || "") + (j.analysis ? " — vision OK" : "")
        : j.error || "Hata";
      loadDocuments();
    };
    reader.readAsDataURL(file);
  }

  $("lab-file")?.addEventListener("change", function (e) {
    const f = e.target.files && e.target.files[0];
    if (f) ingestFile(f);
  });

  const dz = $("lab-dropzone");
  if (dz) {
    ["dragenter", "dragover"].forEach(function (ev) {
      dz.addEventListener(ev, function (e) {
        e.preventDefault();
        dz.classList.add("dragover");
      });
    });
    ["dragleave", "drop"].forEach(function (ev) {
      dz.addEventListener(ev, function (e) {
        e.preventDefault();
        dz.classList.remove("dragover");
        if (ev === "drop" && e.dataTransfer.files[0]) ingestFile(e.dataTransfer.files[0]);
      });
    });
  }

  loadSessions();
  loadLessons();
  loadDocuments();
  fetchHealth();
  fetchSim();
  checkRollbackBanner();
  setInterval(fetchHealth, 8000);
  setInterval(fetchSim, 15000);
})();
