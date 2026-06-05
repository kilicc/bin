(function (global) {
  "use strict";

  var NAV = [
    { href: "/paper", label: "Desk", icon: "📊", key: "paper" },
    { href: "/lab", label: "Eğitim Lab", icon: "🧪", key: "lab" },
    { href: "/develop", label: "Develop", icon: "🛠", key: "develop" },
    { href: "/ops", label: "İzleme", icon: "📡", key: "ops" },
    { href: "/admin", label: "Yönetim", icon: "⚙", key: "admin" },
  ];

  var DESK_PORTS = { 9085: "9005", 9086: "9006", 9087: "9007" };

  function activeKey() {
    var p = (location.pathname || "/").replace(/\/$/, "") || "/";
    if (p === "/" || p === "/paper") return "paper";
    if (p.indexOf("/lab") === 0) return "lab";
    if (p.indexOf("/develop") === 0) return "develop";
    if (p.indexOf("/ops") === 0) return "ops";
    if (p.indexOf("/admin") === 0) return "admin";
    return "";
  }

  function deskHref() {
    var port = String(location.port || "");
    if (port === "9085") return "http://" + location.hostname + ":9085/";
    if (port === "9086") return "http://" + location.hostname + ":9086/paper";
    return "/paper";
  }

  function renderNav(host) {
    if (!host) return;
    var cur = activeKey();
    host.innerHTML = NAV.map(function (item) {
      var cls = item.key === cur ? ' class="active"' : "";
      var href = item.key === "paper" ? deskHref() : item.href;
      return (
        '<a href="' +
        href +
        '"' +
        cls +
        '><span class="hub-nav-icon">' +
        item.icon +
        "</span>" +
        item.label +
        "</a>"
      );
    }).join("");
  }

  global.EliteControlNav = { render: renderNav, activeKey: activeKey, deskPorts: DESK_PORTS };
})(window);
