/* Binance Futures tarzı — Lightweight Charts */
window.TradingCharts = (function () {
  "use strict";

  const BN = {
    bg: "#181a20",
    grid: "rgba(43, 49, 57, 0.65)",
    border: "#2b3139",
    text: "#848e9c",
    textBright: "#eaecef",
    up: "#0ecb81",
    down: "#f6465d",
    gold: "#f0b90b",
    ma7: "#ed4b9b",
    ma25: "#7b61ff",
    ma99: "#f0b90b",
    entry: "#b48cff",
    tp: "#0ecb81",
    sl: "#f6465d",
    equity: "#f0b90b",
  };

  const pool = new Map();

  function LWC() {
    return window.LightweightCharts;
  }

  function priceFormat(price) {
    const p = Number(price) || 1;
    if (p >= 5000) return { type: "price", precision: 2, minMove: 0.01 };
    if (p >= 100) return { type: "price", precision: 3, minMove: 0.001 };
    if (p >= 1) return { type: "price", precision: 4, minMove: 0.0001 };
    if (p >= 0.01) return { type: "price", precision: 5, minMove: 0.00001 };
    return { type: "price", precision: 7, minMove: 0.0000001 };
  }

  function fmtPrice(v, d) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "—";
    return n.toFixed(d != null ? d : 4);
  }

  function parseTime(raw, fallbackSec) {
    if (typeof raw === "number" && raw > 1e9) return Math.floor(raw);
    const n = Number(raw);
    if (Number.isFinite(n) && n > 1e9) return Math.floor(n);
    const ms = Date.parse(String(raw || ""));
    if (!Number.isNaN(ms)) return Math.floor(ms / 1000);
    return fallbackSec;
  }

  function normalizeSeries(p) {
    const entry = Number(p.entry_price);
    const cur = Number(p.current_price);
    const tp = Number(p.tp_target);
    const sl = Number(p.sl_target);
    const rawCandles = (p.chart_candles || [])
      .map((c) => ({
        time: parseTime(c.time, 0),
        open: Number(c.open),
        high: Number(c.high),
        low: Number(c.low),
        close: Number(c.close),
        volume: Number(c.volume || 0),
      }))
      .filter((c) => c.time > 0 && c.close > 0);
    if (rawCandles.length >= 2) {
      const last = rawCandles[rawCandles.length - 1];
      if (cur > 0 && Math.abs(last.close - cur) > 1e-12) {
        rawCandles[rawCandles.length - 1] = {
          ...last,
          close: cur,
          high: Math.max(last.high, cur),
          low: Math.min(last.low, cur),
        };
      }
      return {
        candles: rawCandles.slice(-120),
        prices: rawCandles.map((c) => c.close),
        times: rawCandles.map((c) => c.time),
        entry,
        cur,
        tp,
        sl,
        symbol: String(p.symbol || "—"),
        side: String(p.side || "LONG"),
        klines: true,
      };
    }

    let prices = (p.price_history || []).map(Number).filter((v) => Number.isFinite(v) && v > 0);
    let times = (p.time_history || []).slice(-prices.length);
    if (prices.length < 2 && entry > 0) {
      prices = [entry, cur > 0 ? cur : entry * 1.00012];
      times = [Date.now() - 6000, Date.now()];
    }
    if (
      p.chart_source !== "klines" &&
      cur > 0 &&
      prices.length &&
      Math.abs(prices[prices.length - 1] - cur) > 1e-12
    ) {
      prices.push(cur);
      times.push(Date.now());
    }
    prices = prices.slice(-120);
    times = (times.length >= prices.length ? times : prices.map((_, i) => Date.now() - (prices.length - i) * 2000)).slice(
      0,
      prices.length
    );
    return {
      prices,
      times,
      entry,
      cur,
      tp,
      sl,
      symbol: String(p.symbol || "—"),
      side: String(p.side || "LONG"),
      klines: false,
      candles: [],
    };
  }

  function decimateLine(line, minSec) {
    if (line.length < 3) return line;
    const out = [line[0]];
    let lastT = line[0].time;
    for (let i = 1; i < line.length; i++) {
      const pt = line[i];
      if (i === line.length - 1 || pt.time - lastT >= minSec) {
        out.push(pt);
        lastT = pt.time;
      }
    }
    return out;
  }

  function buildSeries(prices, times) {
    const line = [];
    const candles = [];
    const vols = [];
    const t0 = parseTime(times[0], Math.floor(Date.now() / 1000) - prices.length * 2);

    for (let i = 0; i < prices.length; i++) {
      let t = parseTime(times[i], t0 + i);
      if (line.length && t <= line[line.length - 1].time) t = line[line.length - 1].time + 1;
      const v = prices[i];
      line.push({ time: t, value: v });

      if (i > 0) {
        const o = prices[i - 1];
        const c = v;
        const move = Math.abs(c - o) || o * 0.00004;
        candles.push({
          time: t,
          open: o,
          high: Math.max(o, c),
          low: Math.min(o, c),
          close: c,
        });
        vols.push({
          time: t,
          value: Math.max(move * 120, move),
          color: c >= o ? "rgba(14,203,129,0.45)" : "rgba(246,70,93,0.45)",
        });
      }
    }
    return { line: decimateLine(line, 3), candles, vols };
  }

  function buildKlineVols(candles) {
    return candles.map((c) => ({
      time: c.time,
      value: Math.max(c.volume || 0, 0),
      color: c.close >= c.open ? "rgba(14,203,129,0.55)" : "rgba(246,70,93,0.55)",
    }));
  }

  function closesFromCandles(candles) {
    return candles.map((c) => ({ time: c.time, value: c.close }));
  }

  function buildMa(line, period) {
    const p = Math.max(2, Math.min(period, line.length));
    const out = [];
    for (let i = 0; i < line.length; i++) {
      if (i < p - 1) continue;
      let s = 0;
      for (let j = i - p + 1; j <= i; j++) s += line[j].value;
      out.push({ time: line[i].time, value: s / p });
    }
    return out;
  }

  function lastMa(line, period) {
    const arr = buildMa(line, period);
    return arr.length ? arr[arr.length - 1].value : null;
  }

  function chartOptions(compact) {
    const L = LWC();
    return {
      layout: {
        background: { type: "solid", color: BN.bg },
        textColor: BN.text,
        fontFamily: "'IBM Plex Sans', 'Inter', sans-serif",
        fontSize: compact ? 9 : 11,
      },
      grid: {
        vertLines: { color: BN.grid, style: L.LineStyle.Solid },
        horzLines: { color: BN.grid, style: L.LineStyle.Solid },
      },
      crosshair: {
        mode: L.CrosshairMode.Normal,
        vertLine: {
          color: "rgba(132,142,156,0.45)",
          width: 1,
          style: L.LineStyle.LargeDashed,
          labelBackgroundColor: "#474d57",
        },
        horzLine: {
          color: "rgba(132,142,156,0.45)",
          width: 1,
          style: L.LineStyle.LargeDashed,
          labelBackgroundColor: "#474d57",
        },
      },
      rightPriceScale: {
        borderColor: BN.border,
        scaleMargins: compact ? { top: 0.06, bottom: 0.18 } : { top: 0.06, bottom: 0.24 },
      },
      timeScale: {
        borderColor: BN.border,
        timeVisible: !compact,
        secondsVisible: false,
        fixLeftEdge: false,
        fixRightEdge: false,
        rightOffset: 6,
        barSpacing: compact ? 4 : 7,
      },
      handleScroll: false,
      handleScale: false,
    };
  }

  function mountHost(id) {
    const host = document.getElementById(id);
    if (!host) return null;
    let inner = host.querySelector(".lwc-mount");
    if (!inner) {
      host.innerHTML = "";
      inner = document.createElement("div");
      inner.className = "lwc-mount";
      inner.style.width = "100%";
      inner.style.height = "100%";
      host.appendChild(inner);
    }
    return { host, inner };
  }

  function applySize(rec) {
    if (!rec || !rec.chart || !rec.host) return;
    const w = rec.host.clientWidth;
    const h = rec.host.clientHeight;
    if (w > 0 && h > 0) rec.chart.applyOptions({ width: w, height: h });
  }

  function destroy(id) {
    const rec = pool.get(id);
    if (!rec) return;
    if (rec.ro) rec.ro.disconnect();
    rec.chart.remove();
    pool.delete(id);
    const host = document.getElementById(id);
    if (host) host.innerHTML = "";
  }

  function destroyPrefix(prefix) {
    [...pool.keys()].forEach((k) => {
      if (k.indexOf(prefix) === 0) destroy(k);
    });
  }

  function clearPriceLines(rec) {
    if (!rec || !rec.lines || !rec.main) return;
    rec.lines.forEach((ln) => {
      try {
        rec.main.removePriceLine(ln);
      } catch (_) {}
    });
    rec.lines = [];
  }

  function seriesKey(mode, line, vols, candles) {
    if (mode === "candles" && candles.length) {
      const last = candles[candles.length - 1];
      return "c:" + candles.length + ":" + last.time + ":" + last.close;
    }
    if (!line.length) return "";
    const last = line[line.length - 1];
    return "l:" + line.length + ":" + last.time + ":" + last.value + ":" + (vols.length ? vols[vols.length - 1].value : 0);
  }

  function updateOhlcBar(meta) {
    if (!meta) return;
    const bar = document.getElementById("chart-ohlc-bar");
    if (!bar) return;
    bar.classList.remove("hidden");
    const chgCls = meta.chg >= 0 ? "up" : "down";
    const symEl = document.getElementById("ohlc-symbol");
    if (symEl) {
      symEl.textContent = meta.symbol;
      symEl.className = "ohlc-symbol " + (String(meta.side).toUpperCase() === "SHORT" ? "short" : "long");
    }
    const set = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };
    set("ohlc-o", meta.o);
    set("ohlc-h", meta.h);
    set("ohlc-l", meta.l);
    set("ohlc-c", meta.c);
    const chgEl = document.getElementById("ohlc-chg");
    if (chgEl) {
      chgEl.textContent = (meta.chg >= 0 ? "+" : "") + meta.chg.toFixed(2) + "%";
      chgEl.className = "ohlc-chg " + chgCls;
    }
    set("ma7-val", meta.ma7 != null ? fmtPrice(meta.ma7, meta.decimals) : "—");
    set("ma25-val", meta.ma25 != null ? fmtPrice(meta.ma25, meta.decimals) : "—");
    set("ma99-val", meta.ma99 != null ? fmtPrice(meta.ma99, meta.decimals) : "—");
    set("ohlc-mark", fmtPrice(meta.mark, meta.decimals));
    const markEl = document.getElementById("ohlc-mark");
    if (markEl) markEl.className = "ohlc-mark " + chgCls;
  }

  function hideOhlcBar() {
    const bar = document.getElementById("chart-ohlc-bar");
    if (bar) bar.classList.add("hidden");
  }

  function buildOhlcMeta(p, line, candles) {
    const last = line[line.length - 1];
    const first = line[0];
    const cnd = candles.length ? candles[candles.length - 1] : null;
    const chg = first && last ? ((last.value - first.value) / first.value) * 100 : 0;
    const pf = priceFormat(last.value);
    const d = pf.precision || 4;
    return {
      symbol: String(p.symbol || "—").replace("USDT", "/USDT"),
      side: p.side,
      o: fmtPrice(cnd ? cnd.open : last.value, d),
      h: fmtPrice(cnd ? cnd.high : last.value, d),
      l: fmtPrice(cnd ? cnd.low : last.value, d),
      c: fmtPrice(last.value, d),
      mark: last.value,
      chg,
      decimals: d,
      ma7: lastMa(line, 7),
      ma25: lastMa(line, 25),
      ma99: lastMa(line, 99),
    };
  }

  function createPositionChart(L, mounted, compact, pf, up, useCandles) {
    const chart = L.createChart(mounted.inner, {
      ...chartOptions(compact),
      width: mounted.host.clientWidth,
      height: mounted.host.clientHeight,
    });
    let main;
    if (useCandles) {
      main = chart.addCandlestickSeries({
        upColor: BN.up,
        downColor: BN.down,
        borderUpColor: BN.up,
        borderDownColor: BN.down,
        wickUpColor: BN.up,
        wickDownColor: BN.down,
        priceFormat: pf,
        lastValueVisible: true,
        priceLineVisible: true,
        priceLineColor: up ? BN.up : BN.down,
      });
    } else {
      main = chart.addLineSeries({
        color: BN.gold,
        lineWidth: 1.5,
        priceFormat: pf,
        lastValueVisible: true,
        priceLineVisible: true,
        priceLineColor: up ? BN.up : BN.down,
        crosshairMarkerRadius: 3,
        crosshairMarkerBorderColor: BN.gold,
        crosshairMarkerBackgroundColor: BN.bg,
      });
    }
    const ma7 = chart.addLineSeries({
      color: BN.ma7,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      priceFormat: pf,
    });
    const ma25 = chart.addLineSeries({
      color: BN.ma25,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      priceFormat: pf,
    });
    const ma99 = chart.addLineSeries({
      color: BN.ma99,
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      priceFormat: pf,
    });
    const vol = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
    });
    chart.priceScale("vol").applyOptions({
      scaleMargins: { top: 0.78, bottom: 0 },
      borderVisible: false,
    });
    return {
      host: mounted.host,
      chart,
      main,
      ma7,
      ma25,
      ma99,
      vol,
      lines: [],
      lastKey: "",
      kind: useCandles ? "candles" : "position",
    };
  }

  function plotPosition(id, p, opts) {
    const L = LWC();
    if (!L) return;
    const compact = !!(opts && opts.compact);
    const mounted = mountHost(id);
    if (!mounted) return;

    const norm = normalizeSeries(p);
    const { prices, times, entry, tp, sl, klines, candles: klineCandles } = norm;
    const useCandles = !!(klines && klineCandles.length >= 2);
    let line = [];
    let candles = [];
    let vols = [];
    let maLine = [];
    if (useCandles) {
      candles = klineCandles;
      maLine = closesFromCandles(candles);
      vols = buildKlineVols(candles);
      line = maLine;
    } else {
      const built = buildSeries(prices, times);
      line = built.line;
      candles = built.candles;
      vols = built.vols;
      maLine = line;
    }
    if (!line.length) return;

    const pf = priceFormat(line[line.length - 1].value);
    const up = line.length > 1 && line[line.length - 1].value >= line[line.length - 2].value;
    const key = seriesKey(useCandles ? "candles" : "line", line, vols, candles);

    let rec = pool.get(id);
    const wantKind = useCandles ? "candles" : "position";
    if (rec && rec.kind !== wantKind) {
      destroy(id);
      rec = null;
    }

    if (!rec) {
      rec = createPositionChart(L, mounted, compact, pf, up, useCandles);
      pool.set(id, rec);
      rec.ro = new ResizeObserver(() => applySize(rec));
      rec.ro.observe(mounted.host);
    }

    if (rec.lastKey !== key) {
      if (useCandles) {
        rec.main.setData(candles);
      } else {
        rec.main.applyOptions({
          priceFormat: pf,
          priceLineColor: up ? BN.up : BN.down,
        });
        rec.main.setData(line);
      }
      rec.ma7.setData(buildMa(maLine, 7));
      if (!compact) {
        rec.ma25.setData(buildMa(maLine, 25));
        rec.ma99.setData(buildMa(maLine, Math.min(99, maLine.length)));
      } else {
        rec.ma25.setData([]);
        rec.ma99.setData([]);
      }
      if (vols.length) rec.vol.setData(vols);
      rec.lastKey = key;
    } else if (useCandles && candles.length) {
      rec.main.update(candles[candles.length - 1]);
      const m7 = buildMa(maLine, 7);
      if (m7.length) rec.ma7.update(m7[m7.length - 1]);
    } else if (line.length) {
      const pt = line[line.length - 1];
      rec.main.update(pt);
      const m7 = buildMa(maLine, 7);
      if (m7.length) rec.ma7.update(m7[m7.length - 1]);
    }

    clearPriceLines(rec);
    if (entry > 0) {
      rec.lines.push(
        rec.main.createPriceLine({
          price: entry,
          color: BN.entry,
          lineWidth: 1,
          lineStyle: L.LineStyle.Dotted,
          axisLabelVisible: true,
          title: "Giriş",
        })
      );
    }
    if (tp > 0) {
      rec.lines.push(
        rec.main.createPriceLine({
          price: tp,
          color: BN.tp,
          lineWidth: 2,
          lineStyle: L.LineStyle.Solid,
          axisLabelVisible: true,
          title: "TP",
        })
      );
    }
    if (sl > 0) {
      rec.lines.push(
        rec.main.createPriceLine({
          price: sl,
          color: BN.sl,
          lineWidth: 1,
          lineStyle: L.LineStyle.Dashed,
          axisLabelVisible: true,
          title: "SL",
        })
      );
    }

    if (!compact && id === "chart-hero") {
      updateOhlcBar(buildOhlcMeta(p, line, useCandles ? candles : candles));
    }

    rec.chart.timeScale().scrollToRealTime();
    applySize(rec);
  }

  function buildEquityPoints(d, compact) {
    const eq = (d && d.equity) || [];
    const ts = (d && d.timestamps) || [];
    const cap = d && d.summary && d.summary.current_capital;
    let y = eq.slice();
    let x = ts.length === y.length ? ts.slice() : [];
    if (cap != null && Number.isFinite(Number(cap))) {
      y.push(Number(cap));
      x.push(new Date().toISOString());
    }
    const limit = compact ? 80 : 160;
    if (y.length > limit) {
      y = y.slice(-limit);
      x = x.slice(-limit);
    }
    const points = [];
    const t0 = Math.floor(Date.now() / 1000) - y.length * 3;
    for (let i = 0; i < y.length; i++) {
      let t = parseTime(x[i], t0 + i);
      if (points.length && t <= points[points.length - 1].time) t = points[points.length - 1].time + 1;
      points.push({ time: t, value: Number(y[i]) });
    }
    return points.filter((pt) => Number.isFinite(pt.value));
  }

  function plotEquity(id, d, opts) {
    const L = LWC();
    if (!L) return;
    hideOhlcBar();
    const compact = !!(opts && opts.compact);
    const mounted = mountHost(id);
    if (!mounted) return;

    const points = buildEquityPoints(d, compact);
    if (points.length < 2) return;

    const up = points[points.length - 1].value >= points[points.length - 2].value;
    let rec = pool.get(id);
    if (rec && rec.kind !== "equity") {
      destroy(id);
      rec = null;
    }

    if (!rec) {
      const chart = L.createChart(mounted.inner, {
        ...chartOptions(compact),
        width: mounted.host.clientWidth,
        height: mounted.host.clientHeight,
      });
      const area = chart.addAreaSeries({
        lineColor: BN.gold,
        topColor: "rgba(240, 185, 11, 0.35)",
        bottomColor: "rgba(240, 185, 11, 0.02)",
        lineWidth: compact ? 1.5 : 2,
        priceFormat: { type: "price", precision: 2, minMove: 0.01 },
        lastValueVisible: true,
        priceLineVisible: true,
        priceLineColor: up ? BN.up : BN.down,
      });
      rec = { host: mounted.host, chart, main: area, lines: [], lastKey: "", kind: "equity" };
      pool.set(id, rec);
      rec.ro = new ResizeObserver(() => applySize(rec));
      rec.ro.observe(mounted.host);
    }

    const key = points.length + ":" + points[points.length - 1].value;
    rec.main.applyOptions({ priceLineColor: up ? BN.up : BN.down });
    if (rec.lastKey !== key) {
      rec.main.setData(points);
      rec.lastKey = key;
    } else {
      rec.main.update(points[points.length - 1]);
    }
    rec.chart.timeScale().scrollToRealTime();
    applySize(rec);
  }

  return { plotPosition, plotEquity, destroy, destroyPrefix, hideOhlcBar };
})();
