(function () {
  "use strict";
  let schema = { fields: [] };
  let values = { runtime_env: {}, profiles: {} };
  let draft = {};
  let profileDraft = {};
  let selectedKey = null;
  let activeTab = "env";
  let activeGroup = "mega";
  let activeMode = "mega";
  let selectedCheckpoint = null;
  let pendingRestart = false;

  function $(id) {
    return document.getElementById(id);
  }

  async function api(path, opts) {
    const r = await fetch(path, Object.assign({ credentials: "same-origin" }, opts || {}));
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  }

  function bindTabs() {
    $("admin-tabs")?.querySelectorAll("button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        activeTab = btn.dataset.tab;
        $("admin-tabs").querySelectorAll("button").forEach(function (b) {
          b.classList.toggle("active", b === btn);
        });
        renderTab();
      });
    });
    $("btn-preview")?.addEventListener("click", runPreview);
    $("btn-checkpoint")?.addEventListener("click", createCheckpoint);
    $("btn-rollback")?.addEventListener("click", function () {
      $("rollback-modal").classList.remove("hidden");
    });
    $("btn-rollback-cancel")?.addEventListener("click", function () {
      $("rollback-modal").classList.add("hidden");
    });
    $("btn-rollback-confirm")?.addEventListener("click", confirmRollback);
    $("admin-search")?.addEventListener("input", function () {
      renderFields(activeGroup);
    });
  }

  async function loadAll() {
    schema = await api("/api/admin/settings/schema");
    values = await api("/api/admin/settings/values");
    draft = Object.assign({}, values.runtime_env || {});
    profileDraft = Object.assign({}, (values.profiles || {}).mega || {});
    renderTab();
  }

  function renderTab() {
    const isEnv = activeTab === "env";
    const isProfiles = activeTab === "profiles";
    const isCp = activeTab === "checkpoints";
    const isLab = activeTab === "lab";
    $("admin-nav").classList.toggle("hidden", isCp);
    $("admin-search").classList.toggle("hidden", !isEnv && !isLab);
    $("admin-fields").classList.toggle("hidden", isCp);
    $("checkpoint-panel").classList.toggle("hidden", !isCp);
    $("btn-apply").style.display = isCp ? "none" : "";
    $("btn-preview").style.display = isCp ? "none" : "";
    if (isCp) {
      loadCheckpoints();
      return;
    }
    if (isLab) {
      activeGroup = "lab";
      renderNav(["lab"]);
      renderFields("lab");
      return;
    }
    if (isProfiles) {
      renderProfileNav();
      renderProfileFields();
      return;
    }
    renderNav(schema.groups || ["mega", "elite"]);
    renderFields(activeGroup);
  }

  function renderNav(groups) {
    const nav = $("admin-nav");
    nav.innerHTML = groups
      .map(function (g) {
        return (
          '<button type="button" data-group="' +
          g +
          '"' +
          (g === activeGroup ? ' class="active"' : "") +
          ">" +
          g.toUpperCase() +
          "</button>"
        );
      })
      .join("");
    nav.querySelectorAll("button").forEach(function (btn) {
      btn.addEventListener("click", function () {
        activeGroup = btn.dataset.group;
        nav.querySelectorAll("button").forEach(function (b) {
          b.classList.toggle("active", b === btn);
        });
        renderFields(activeGroup);
      });
    });
  }

  function renderProfileNav() {
    const nav = $("admin-nav");
    nav.innerHTML = ["mega", "evrim"]
      .map(function (m) {
        return (
          '<button type="button" data-mode="' +
          m +
          '"' +
          (m === activeMode ? ' class="active"' : "") +
          ">" +
          m.toUpperCase() +
          "</button>"
        );
      })
      .join("");
    nav.querySelectorAll("button").forEach(function (btn) {
      btn.addEventListener("click", async function () {
        activeMode = btn.dataset.mode;
        profileDraft = Object.assign({}, (values.profiles || {})[activeMode] || {});
        nav.querySelectorAll("button").forEach(function (b) {
          b.classList.toggle("active", b === btn);
        });
        renderProfileFields();
      });
    });
  }

  function fieldFilter(f) {
    const q = ($("admin-search")?.value || "").trim().toLowerCase();
    if (!q) return true;
    return (f.key + " " + (f.label || "")).toLowerCase().indexOf(q) >= 0;
  }

  function renderFieldControl(f, v) {
    if (f.type === "bool") {
      const on = String(v) === "1" || String(v).toLowerCase() === "true";
      return (
        '<button type="button" class="admin-toggle' +
        (on ? " on" : "") +
        '" data-key="' +
        f.key +
        '" data-bool="1"></button>'
      );
    }
    if ((f.type === "int" || f.type === "float") && f.min != null && f.max != null) {
      const step = f.step || (f.type === "int" ? 1 : 0.01);
      return (
        '<div class="admin-field-row"><input type="range" data-key="' +
        f.key +
        '" min="' +
        f.min +
        '" max="' +
        f.max +
        '" step="' +
        step +
        '" value="' +
        v +
        '" /><input type="number" data-key-num="' +
        f.key +
        '" value="' +
        v +
        '" style="width:5rem" /></div>'
      );
    }
    if (f.type === "enum" && f.options) {
      return (
        "<select data-key=\"" +
        f.key +
        '">' +
        f.options
          .map(function (o) {
            return (
              '<option value="' +
              o +
              '"' +
              (String(v) === String(o) ? " selected" : "") +
              ">" +
              o +
              "</option>"
            );
          })
          .join("") +
        "</select>"
      );
    }
    return (
      '<input data-key="' +
      f.key +
      '" value="' +
      String(v).replace(/"/g, "&quot;") +
      '" />'
    );
  }

  function renderFields(group) {
    const host = $("admin-fields");
    const fields = (schema.fields || []).filter(function (f) {
      return f.group === group && f.scope === "env" && fieldFilter(f);
    });
    host.innerHTML = fields
      .map(function (f) {
        const v = draft[f.key] != null ? draft[f.key] : "";
        return (
          '<div class="admin-field" data-key="' +
          f.key +
          '"><label>' +
          f.label +
          " <code>" +
          f.key +
          "</code>" +
          (f.requires_restart ? ' <span class="badge">restart</span>' : "") +
          "</label>" +
          renderFieldControl(f, v) +
          "</div>"
        );
      })
      .join("");
    bindFieldEvents(host, draft);
  }

  function renderProfileFields() {
    const host = $("admin-fields");
    const fields = (schema.fields || []).filter(function (f) {
      return f.scope === "profile" && f.profile_mode_id === activeMode;
    });
    host.innerHTML = fields
      .map(function (f) {
        const v = profileDraft[f.key] != null ? profileDraft[f.key] : f.default != null ? f.default : "";
        return (
          '<div class="admin-field" data-key="' +
          f.key +
          '"><label>' +
          f.label +
          "</label>" +
          renderFieldControl(f, v) +
          "</div>"
        );
      })
      .join("");
    bindFieldEvents(host, profileDraft);
  }

  function bindFieldEvents(host, target) {
    host.querySelectorAll(".admin-toggle").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const on = btn.classList.toggle("on");
        target[btn.dataset.key] = on ? "1" : "0";
        updateDiff();
      });
      btn.addEventListener("focus", function () {
        selectedKey = btn.dataset.key;
        loadImpact(selectedKey);
      });
    });
    host.querySelectorAll("[data-key]").forEach(function (el) {
      if (el.classList.contains("admin-toggle")) return;
      el.addEventListener("focus", function () {
        selectedKey = el.dataset.key;
        loadImpact(selectedKey);
      });
      el.addEventListener("change", function () {
        target[el.dataset.key] = el.value;
        const num = host.querySelector('[data-key-num="' + el.dataset.key + '"]');
        const range = host.querySelector('[data-key="' + el.dataset.key + '"][type="range"]');
        if (num && el.type === "range") num.value = el.value;
        if (range && el.dataset.keyNum) range.value = el.value;
        updateDiff();
      });
      el.addEventListener("input", function () {
        if (el.dataset.keyNum) target[el.dataset.keyNum] = el.value;
        else target[el.dataset.key] = el.value;
        updateDiff();
      });
    });
  }

  async function loadImpact(key) {
    const j = await api("/api/admin/settings/impact?key=" + encodeURIComponent(key));
    $("impact-text").textContent = (j.edges || [])
      .map(function (e) {
        return e.from + " → " + e.to + ": " + e.note;
      })
      .join("\n") || "Bağlı etki kaydı yok";
    $("depends-list").innerHTML = (j.depends_on || [])
      .map(function (d) {
        return "<li><code>" + d + "</code></li>";
      })
      .join("");
  }

  function currentPatch() {
    if (activeTab === "profiles") {
      const base = (values.profiles || {})[activeMode] || {};
      const patch = {};
      Object.keys(profileDraft).forEach(function (k) {
        if (String(profileDraft[k]) !== String(base[k])) patch[k] = profileDraft[k];
      });
      return patch;
    }
    const patch = {};
    Object.keys(draft).forEach(function (k) {
      if (String(draft[k]) !== String((values.runtime_env || {})[k])) patch[k] = draft[k];
    });
    return patch;
  }

  function renderDiffLines(diff) {
    if (!diff || !diff.length) return "Değişiklik yok";
    return diff
      .map(function (d) {
        return "· " + d.key + ": " + d.before + " → " + d.after;
      })
      .join("\n");
  }

  async function updateDiff() {
    const patch = currentPatch();
    if (!Object.keys(patch).length) {
      $("diff-panel").textContent = "Değişiklik yok";
      $("restart-banner").classList.add("hidden");
      return;
    }
    try {
      const j =
        activeTab === "profiles"
          ? await api("/api/admin/profiles/preview", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ mode_id: activeMode, patch: patch }),
            })
          : await api("/api/admin/settings/preview", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ patch: patch }),
            });
      $("diff-panel").textContent = renderDiffLines(j.diff);
      pendingRestart = !!j.requires_restart;
      $("restart-banner").classList.toggle("hidden", !pendingRestart);
    } catch (_) {
      $("diff-panel").textContent = Object.keys(patch).join(", ");
    }
  }

  async function runPreview() {
    await updateDiff();
  }

  async function loadCheckpoints() {
    const j = await api("/api/checkpoints/recent?limit=20");
    const list = $("checkpoint-list");
    list.innerHTML = (j.checkpoints || [])
      .map(function (cp) {
        return (
          '<div class="admin-checkpoint-item" data-file="' +
          cp.file +
          '"><strong>' +
          (cp.label || cp.file) +
          "</strong><br><span class='muted'>" +
          (cp.created_at || "") +
          "</span></div>"
        );
      })
      .join("");
    list.querySelectorAll(".admin-checkpoint-item").forEach(function (el) {
      el.addEventListener("click", function () {
        selectedCheckpoint = el.dataset.file;
        list.querySelectorAll(".admin-checkpoint-item").forEach(function (x) {
          x.classList.toggle("selected", x === el);
        });
        $("btn-rollback").disabled = !selectedCheckpoint;
        loadCheckpointPreview(selectedCheckpoint);
      });
    });
  }

  async function loadCheckpointPreview(file) {
    const j = await api("/api/checkpoints/" + encodeURIComponent(file));
    $("checkpoint-preview").textContent = j.content ? j.content.slice(0, 8000) : j.error || "";
  }

  async function confirmRollback() {
    if (!selectedCheckpoint) return;
    const scopes = [];
    $("rollback-modal").querySelectorAll('input[name="scope"]:checked').forEach(function (cb) {
      scopes.push(cb.value);
    });
    const r = await fetch("/api/checkpoints/" + encodeURIComponent(selectedCheckpoint) + "/rollback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        scopes: scopes,
        confirm: true,
        reason: $("rollback-reason").value,
      }),
    });
    const j = await r.json();
    $("rollback-modal").classList.add("hidden");
    $("apply-status").textContent = j.ok
      ? "Geri alındı: " + (j.restored || []).join(", ")
      : (j.errors || [j.error]).join(", ");
    loadAll();
  }

  async function createCheckpoint() {
    $("apply-status").textContent = "Checkpoint oluşturuluyor…";
    try {
      const r = await fetch("/api/checkpoints/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ label: "Admin manuel checkpoint" }),
      });
      const j = await r.json();
      $("apply-status").textContent = j.ok ? "CP: " + (j.file || j.entry?.file) : j.error || "Hata";
    } catch (e) {
      $("apply-status").textContent = String(e);
    }
  }

  $("btn-apply")?.addEventListener("click", async function () {
    const patch = currentPatch();
    if (!Object.keys(patch).length) {
      $("apply-status").textContent = "Değişiklik yok";
      return;
    }
    const url =
      activeTab === "profiles"
        ? "/api/admin/profiles/" + encodeURIComponent(activeMode)
        : "/api/admin/settings";
    const r = await fetch(url, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ patch: patch }),
    });
    const j = await r.json();
    $("apply-status").textContent = j.ok
      ? j.requires_restart
        ? "Uygulandı — restart gerekli"
        : "Uygulandı"
      : (j.errors || []).join(", ");
    if (j.ok) loadAll();
  });

  EliteAdminGate.init({
    gateId: "login-gate",
    appId: "admin-app",
    onReady: function () {
      bindTabs();
      loadAll();
    },
  });
})();
