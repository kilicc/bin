(function () {
  "use strict";

  window.EliteAdminGate = {
    init: function (opts) {
      const gateId = opts.gateId || "login-gate";
      const appId = opts.appId || "app-root";
      const onReady = opts.onReady || function () {};

      function $(id) {
        return document.getElementById(id);
      }

      async function api(path, body) {
        const r = await fetch(path, {
          method: body ? "POST" : "GET",
          credentials: "same-origin",
          headers: body ? { "Content-Type": "application/json" } : undefined,
          body: body ? JSON.stringify(body) : undefined,
        });
        if (!r.ok) throw new Error(String(r.status));
        return r.json();
      }

      async function checkAuth() {
        try {
          const st = await api("/api/admin/auth/status");
          if (st.authenticated) showApp();
        } catch (_) {}
      }

      function showApp() {
        $(gateId)?.classList.add("hidden");
        $(appId)?.classList.remove("hidden");
        onReady();
      }

      $("btn-admin-login")?.addEventListener("click", async function () {
        try {
          await api("/api/admin/login", { password: $("admin-password")?.value || "" });
          showApp();
        } catch (_) {
          alert("Şifre hatalı");
        }
      });

      $("admin-password")?.addEventListener("keydown", function (e) {
        if (e.key === "Enter") $("btn-admin-login")?.click();
      });

      checkAuth();
    },
  };
})();
