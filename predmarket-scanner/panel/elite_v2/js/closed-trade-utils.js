/* Kapalı işlem — çıkış sıralama + Europe/Istanbul gösterim */
(function (global) {
  "use strict";

  const TR_TZ = "Europe/Istanbul";
  const trDateTimeFmt = new Intl.DateTimeFormat("tr-TR", {
    timeZone: TR_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });

  function parseTsFromValue(raw) {
    if (raw == null || raw === "") return null;
    const s = String(raw).trim();
    if (!s) return null;
    if (/^\d+(\.\d+)?$/.test(s)) {
      const n = Number(s);
      if (!Number.isFinite(n) || n <= 0) return null;
      const ms = n > 1e12 ? n : n * 1000;
      return ms / 1000;
    }
    const iso = s.includes("T") ? s : s.replace(" ", "T");
    const t = Date.parse(iso + (iso.includes("Z") || iso.includes("+") ? "" : "Z"));
    return Number.isFinite(t) ? t / 1000 : null;
  }

  function closedExitTs(c) {
    const fields = ["exit_time", "exit_time_iso", "exit_time_str", "closed_at_iso"];
    for (let i = 0; i < fields.length; i++) {
      const ts = parseTsFromValue(c[fields[i]]);
      if (ts != null) return ts;
    }
    return null;
  }

  function closedEntryTs(c) {
    const fields = ["entry_time", "opened_at_iso", "entry_time_str"];
    for (let i = 0; i < fields.length; i++) {
      const ts = parseTsFromValue(c[fields[i]]);
      if (ts != null) return ts;
    }
    const ms = Number(c.exchange_update_ms || 0);
    if (Number.isFinite(ms) && ms > 0) {
      return ms > 1e12 ? ms / 1000 : ms;
    }
    return null;
  }

  function fmtTrFromTs(sec) {
    if (sec == null || !Number.isFinite(sec)) return "—";
    return trDateTimeFmt.format(new Date(sec * 1000));
  }

  function fmtTrExit(c) {
    return fmtTrFromTs(closedExitTs(c));
  }

  function fmtTrEntry(c) {
    return fmtTrFromTs(closedEntryTs(c));
  }

  function sortClosedByExitDesc(rows) {
    return (Array.isArray(rows) ? rows.slice() : []).sort(function (a, b) {
      const ta = closedExitTs(a);
      const tb = closedExitTs(b);
      if (ta == null && tb == null) return 0;
      if (ta == null) return 1;
      if (tb == null) return -1;
      if (tb !== ta) return tb - ta;
      return Number(b.id || 0) - Number(a.id || 0);
    });
  }

  global.ClosedTradeUtils = {
    closedExitTs: closedExitTs,
    closedEntryTs: closedEntryTs,
    fmtTrExit: fmtTrExit,
    fmtTrEntry: fmtTrEntry,
    fmtTrFromTs: fmtTrFromTs,
    sortClosedByExitDesc: sortClosedByExitDesc,
  };
})(typeof window !== "undefined" ? window : globalThis);
