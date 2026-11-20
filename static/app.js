"use strict";

(() => {
  const RANGE_SECS = { "24h": 86400, "30d": 30 * 86400, "90d": 90 * 86400 };
  const CURRENT_EVERY = 30_000;
  const HISTORY_EVERY = 5 * 60_000;
  const SVG_NS = "http://www.w3.org/2000/svg";

  const $ = (id) => document.getElementById(id);
  const state = {
    unit: loadPref("unit", "F"),
    range: "24h",
    current: null,      // {ts, temp_c, humidity, fresh}
    currentError: false,
    history: null,      // API response
    lastFetchOk: 0,
  };

  // ---- preferences ------------------------------------------------------

  function loadPref(key, fallback) {
    try { return localStorage.getItem("pi-temp:" + key) || fallback; } catch { return fallback; }
  }
  function savePref(key, value) {
    try { localStorage.setItem("pi-temp:" + key, value); } catch { /* private mode */ }
  }

  // ---- units and formatting ---------------------------------------------

  const toUnit = (c) => (state.unit === "F" ? c * 9 / 5 + 32 : c);
  const fmtTemp = (c) => toUnit(c).toFixed(1);
  const deg = () => "°" + state.unit;

  const timeFmt = new Intl.DateTimeFormat(undefined, { hour: "numeric", minute: "2-digit" });
  const hourFmt = new Intl.DateTimeFormat(undefined, { hour: "numeric" });
  const dayFmt = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
  const monthFmt = new Intl.DateTimeFormat(undefined, { month: "short" });
  const weekdayFmt = new Intl.DateTimeFormat(undefined, {
    weekday: "short", month: "short", day: "numeric",
  });

  function ago(seconds) {
    const s = Math.max(0, Math.round(seconds));
    if (s < 10) return "just now";
    if (s < 60) return `${s} seconds ago`;
    const m = Math.round(s / 60);
    if (m < 60) return m === 1 ? "1 minute ago" : `${m} minutes ago`;
    const h = Math.round(m / 60);
    return h === 1 ? "1 hour ago" : `${h} hours ago`;
  }

  // ---- temperature colour -------------------------------------------------
  // Ice blue when cold, cyan when comfortable, amber when warm, coral when hot.

  const COLOR_STOPS = [
    [14, [95, 184, 255]],
    [19, [143, 227, 255]],
    [22.5, [190, 240, 222]],
    [26, [255, 180, 92]],
    [30, [255, 122, 92]],
  ];

  function tempColor(c) {
    const s = COLOR_STOPS;
    if (c <= s[0][0]) return rgb(s[0][1]);
    for (let i = 1; i < s.length; i++) {
      if (c <= s[i][0]) {
        const t = (c - s[i - 1][0]) / (s[i][0] - s[i - 1][0]);
        return rgb(s[i - 1][1].map((v, k) => v + (s[i][1][k] - v) * t));
      }
    }
    return rgb(s[s.length - 1][1]);
  }
  const rgb = (a) => `rgb(${a.map((v) => Math.round(v)).join(",")})`;

  // ---- data -----------------------------------------------------------------

  async function fetchCurrent() {
    try {
      const resp = await fetch("/api/current", { cache: "no-store" });
      const data = await resp.json();
      state.current = data.ts ? data : null;
      state.currentError = false;
      state.lastFetchOk = Date.now();
    } catch {
      state.currentError = true;
    }
    renderNow();
    renderStatus();
  }

  async function fetchHistory() {
    const range = state.range;
    try {
      const resp = await fetch(`/api/history?range=${range}`, { cache: "no-store" });
      if (!resp.ok) throw new Error(resp.statusText);
      const data = await resp.json();
      if (range !== state.range) return; // user switched while loading
      state.history = data;
    } catch {
      if (!state.history || state.history.range !== range) state.history = null;
    }
    renderChart();
    renderRangeNote();
  }

  // ---- current readings -------------------------------------------------

  function renderNow() {
    const c = state.current;
    $("temp-unit").textContent = deg();
    if (!c) {
      $("temp").textContent = "--";
      $("hum").textContent = "--";
      return;
    }
    $("temp").textContent = fmtTemp(c.temp_c);
    $("hum").textContent = Math.round(c.humidity);
    document.documentElement.style.setProperty("--temp", tempColor(c.temp_c));
  }

  function renderStatus() {
    const el = $("status");
    const text = $("status-text");
    const c = state.current;
    if (state.currentError) {
      el.dataset.state = "down";
      text.textContent = "Can't reach the Pi. Trying again every 30 seconds.";
    } else if (!c) {
      el.dataset.state = "stale";
      text.textContent = "No readings yet. The first one arrives within a minute of the Pi starting.";
    } else {
      const age = Date.now() / 1000 - c.ts;
      if (c.fresh && age < 300) {
        el.dataset.state = "live";
        text.textContent = `Updated ${ago(age)}`;
      } else {
        el.dataset.state = "stale";
        text.textContent = `No new reading since ${ago(age)}. Check the sensor wiring.`;
      }
    }
  }

  function renderRangeNote() {
    const note = $("range-note");
    const h = state.history;
    if (!h || !h.points.length) { note.innerHTML = "&nbsp;"; return; }
    const hourly = h.range !== "24h";
    let lo = null, hi = null;
    for (const p of h.points) {
      const vLo = hourly ? p[2] : p[1];
      const vHi = hourly ? p[3] : p[1];
      if (!lo || vLo < lo[1]) lo = [p[0], vLo];
      if (!hi || vHi > hi[1]) hi = [p[0], vHi];
    }
    const when = (ts) => (hourly ? "on " + dayFmt.format(ts * 1000) : "at " + timeFmt.format(ts * 1000));
    const label = { "24h": "Past 24 hours", "30d": "Past 30 days", "90d": "Past 90 days" }[h.range];
    note.textContent =
      `${label}: low ${fmtTemp(lo[1])}° ${when(lo[0])}, high ${fmtTemp(hi[1])}° ${when(hi[0])}`;
  }

  // ---- chart ----------------------------------------------------------------

  let geom = null; // kept for hover lookups

  function el(name, attrs, parent) {
    const node = document.createElementNS(SVG_NS, name);
    for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
    if (parent) parent.appendChild(node);
    return node;
  }

  function niceStep(span, target) {
    const raw = span / target;
    const mag = 10 ** Math.floor(Math.log10(raw));
    const n = raw / mag;
    return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * mag;
  }

  function extent(values, minSpan) {
    let lo = Math.min(...values), hi = Math.max(...values);
    const span = Math.max(hi - lo, minSpan);
    const mid = (lo + hi) / 2;
    lo = mid - span * 0.6;
    hi = mid + span * 0.6;
    return [lo, hi];
  }

  function splitOnGaps(points, maxGap) {
    const segs = [];
    let cur = [];
    for (const p of points) {
      if (cur.length && p[0] - cur[cur.length - 1][0] > maxGap) { segs.push(cur); cur = []; }
      cur.push(p);
    }
    if (cur.length) segs.push(cur);
    return segs;
  }

  // The sensor reports in 0.1 °C / 0.1 % steps, so raw per-minute lines look
  // like staircases. For drawing only, average each point with its neighbours
  // (within a segment, so gaps aren't bridged). Hover still shows raw values.
  function smooth(seg, radius) {
    if (seg.length < 3) return seg;
    return seg.map((p, i) => {
      const a = Math.max(0, i - radius), b = Math.min(seg.length - 1, i + radius);
      let t = 0, h = 0;
      for (let k = a; k <= b; k++) { t += seg[k][1]; h += seg[k][2]; }
      const n = b - a + 1;
      return [p[0], t / n, h / n];
    });
  }

  // 30/90-day views: hourly points would show every daily swing and bury the
  // trend, so group them into local days: [noon, tAvg, tMin, tMax, hAvg, hMin, hMax].
  function toDaily(hourlyPts) {
    const days = new Map();
    for (const p of hourlyPts) {
      const d = new Date(p[0] * 1000);
      d.setHours(12, 0, 0, 0);
      const key = d.getTime() / 1000;
      if (!days.has(key)) days.set(key, []);
      days.get(key).push(p);
    }
    const all = [...days.entries()].sort((a, b) => a[0] - b[0]);
    // A partial day (today, the first day, either side of an outage) has a
    // skewed average, so leave it out unless there's nothing else to show.
    const full = all.filter(([, ps]) => ps.length >= 18);
    return full.map(([noon, ps]) => {
      const mean = (i) => ps.reduce((s, p) => s + p[i], 0) / ps.length;
      return [noon, mean(1), Math.min(...ps.map((p) => p[2])), Math.max(...ps.map((p) => p[3])),
              mean(4), Math.min(...ps.map((p) => p[5])), Math.max(...ps.map((p) => p[6]))];
    });
  }

  function linePath(seg, x, y, idx) {
    return seg.map((p, i) => `${i ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[idx]).toFixed(1)}`).join("");
  }

  // Smooth curve through the points (Catmull-Rom as cubic Béziers), for the
  // sparse daily views.
  function curvePath(seg, x, y, idx, cont) {
    const P = seg.map((p) => [x(p[0]), y(p[idx])]);
    if (P.length < 3) return (cont ? "L" : "M") + P.map((q) => q.map((v) => v.toFixed(1)).join(",")).join("L");
    let d = `${cont ? "L" : "M"}${P[0][0].toFixed(1)},${P[0][1].toFixed(1)}`;
    for (let i = 0; i < P.length - 1; i++) {
      const p0 = P[i - 1] || P[i], p1 = P[i], p2 = P[i + 1], p3 = P[i + 2] || p2;
      const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
      const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
      d += `C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
    }
    return d;
  }

  function timeTicks(t0, t1, range, narrow) {
    const ticks = [];
    const d = new Date(t0 * 1000);
    if (range === "24h") {
      const step = narrow ? 6 : 3;
      d.setMinutes(0, 0, 0);
      d.setHours(Math.ceil(d.getHours() / step) * step);
      while (d.getTime() / 1000 <= t1) {
        ticks.push([d.getTime() / 1000, hourFmt.format(d)]);
        d.setHours(d.getHours() + step);
      }
    } else if (range === "30d") {
      d.setHours(0, 0, 0, 0);
      d.setDate(d.getDate() + 1);
      while (d.getTime() / 1000 <= t1) {
        if (d.getDay() === 1) ticks.push([d.getTime() / 1000, dayFmt.format(d)]);
        d.setDate(d.getDate() + 1);
      }
    } else {
      d.setHours(0, 0, 0, 0);
      d.setDate(1);
      d.setMonth(d.getMonth() + 1);
      while (d.getTime() / 1000 <= t1) {
        ticks.push([d.getTime() / 1000, monthFmt.format(d)]);
        d.setMonth(d.getMonth() + 1);
      }
    }
    return ticks;
  }

  function renderChart() {
    const svg = $("chart-svg");
    const box = $("chart");
    const empty = $("chart-empty");
    svg.replaceChildren();
    $("readout").hidden = true;
    geom = null;

    const h = state.history;
    if (!h || !h.points.length) {
      empty.hidden = false;
      empty.textContent = h
        ? "No readings for this range yet. They'll fill in as the Pi records one a minute."
        : "Couldn't load the history. It will retry in a few minutes.";
      return;
    }
    empty.hidden = true;

    const W = box.clientWidth, H = box.clientHeight;
    const narrow = W < 480;
    const pad = { l: 38, r: narrow ? 30 : 38, t: 10, b: 26 };
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);

    const hourly = h.range !== "24h"; // true means "daily points" from here on
    const pts = hourly ? toDaily(h.points) : h.points;
    if (pts.length < 2) {
      empty.hidden = false;
      empty.textContent = hourly
        ? "This view shows one point per full day, so it fills in after a couple of days of readings."
        : "Collecting readings. The line starts after a few minutes.";
      return;
    }
    const TI = 1, HI = hourly ? 4 : 2; // indexes of temp and humidity (avg)
    const t1 = h.now, t0 = t1 - RANGE_SECS[h.range];

    const tempVals = hourly ? pts.flatMap((p) => [p[2], p[3]]) : pts.map((p) => p[1]);
    const humVals = pts.map((p) => p[HI]);
    const [tLo, tHi] = extent(tempVals.map(toUnit), state.unit === "F" ? 4 : 2.5);
    const [hLo, hHi] = extent(humVals, 12);

    const x = (ts) => pad.l + ((ts - t0) / (t1 - t0)) * (W - pad.l - pad.r);
    const yT = (c) => pad.t + (1 - (toUnit(c) - tLo) / (tHi - tLo)) * (H - pad.t - pad.b);
    const yH = (v) => pad.t + (1 - (v - hLo) / (hHi - hLo)) * (H - pad.t - pad.b);
    const bottom = H - pad.b;

    // defs: colour follows the temperature scale, so the line's colour at any
    // height is the colour of that temperature.
    const defs = el("defs", {}, svg);
    const fromUnit = (v) => (state.unit === "F" ? (v - 32) * 5 / 9 : v);
    const grad = el("linearGradient", { id: "tempStroke", gradientUnits: "userSpaceOnUse",
      x1: 0, x2: 0, y1: pad.t, y2: bottom }, defs);
    const fill = el("linearGradient", { id: "tempFill", gradientUnits: "userSpaceOnUse",
      x1: 0, x2: 0, y1: pad.t, y2: bottom }, defs);
    for (let i = 0; i <= 8; i++) {
      const f = i / 8;
      const color = tempColor(fromUnit(tHi - f * (tHi - tLo)));
      el("stop", { offset: f, "stop-color": color }, grad);
      el("stop", { offset: f, "stop-color": color, "stop-opacity": (0.32 * (1 - f) ** 1.6).toFixed(3) }, fill);
    }
    const glow = el("filter", { id: "glow", x: "-5%", y: "-20%", width: "110%", height: "140%" }, defs);
    el("feGaussianBlur", { stdDeviation: 3.5, result: "b" }, glow);
    const merge = el("feMerge", {}, glow);
    el("feMergeNode", { in: "b" }, merge);
    el("feMergeNode", { in: "SourceGraphic" }, merge);

    // grid and axes
    const axis = el("g", { class: "axis" }, svg);
    const tStep = niceStep(tHi - tLo, narrow ? 3 : 4);
    for (let v = Math.ceil(tLo / tStep) * tStep; v <= tHi; v += tStep) {
      const yy = pad.t + (1 - (v - tLo) / (tHi - tLo)) * (H - pad.t - pad.b);
      el("line", { class: "gridline", x1: pad.l, x2: W - pad.r, y1: yy, y2: yy }, axis);
      el("text", { class: "temp-tick", x: pad.l - 8, y: yy + 4, "text-anchor": "end" }, axis)
        .textContent = `${+v.toFixed(1)}°`;
    }
    const hStep = niceStep(hHi - hLo, narrow ? 3 : 4);
    for (let v = Math.ceil(hLo / hStep) * hStep; v <= hHi; v += hStep) {
      el("text", { x: W - pad.r + 8, y: yH(v) + 4 }, axis).textContent = `${Math.round(v)}%`;
    }
    for (const [ts, label] of timeTicks(t0, t1, h.range, narrow)) {
      const xx = x(ts);
      if (xx < pad.l + 12 || xx > W - pad.r - 12) continue;
      el("text", { x: xx, y: H - 6, "text-anchor": "middle" }, axis).textContent = label;
    }

    let segs = splitOnGaps(pts, hourly ? 86400 * 1.5 : 60 * 3.5);
    if (!hourly) segs = segs.map((s) => smooth(s, 4));
    const path = hourly ? curvePath : linePath;

    // daily low–high band
    if (hourly) {
      for (const seg of segs) {
        const top = curvePath(seg, x, yT, 3);
        const back = curvePath(seg.slice().reverse(), x, yT, 2, true);
        el("path", { d: top + back + "Z", fill: "url(#tempStroke)", opacity: 0.16 }, svg);
      }
    }

    // humidity, quiet
    for (const seg of segs) {
      el("path", { d: path(seg, x, yH, HI), fill: "none", stroke: "var(--hum)",
        "stroke-width": 1.4, "stroke-dasharray": "4 3", opacity: 0.85,
        "stroke-linejoin": "round" }, svg);
    }

    // temperature: fill, then glowing line
    for (const seg of segs) {
      const d = path(seg, x, yT, TI);
      const first = x(seg[0][0]).toFixed(1), last = x(seg[seg.length - 1][0]).toFixed(1);
      el("path", { d: `${d}L${last},${bottom}L${first},${bottom}Z`, fill: "url(#tempFill)" }, svg);
      el("path", { d, fill: "none", stroke: "url(#tempStroke)", "stroke-width": 2.4,
        "stroke-linejoin": "round", "stroke-linecap": "round", filter: "url(#glow)" }, svg);
    }

    // hover layer
    const hover = el("g", { opacity: 0 }, svg);
    const vline = el("line", { y1: pad.t, y2: bottom, stroke: "rgba(230,235,247,.25)", "stroke-width": 1 }, hover);
    const tdot = el("circle", { r: 4.5, fill: "var(--night-0)", "stroke-width": 2 }, hover);
    const hdot = el("circle", { r: 3, fill: "var(--hum)" }, hover);

    geom = { pts, x, yT, yH, hourly, TI, HI, W, pad, hover, vline, tdot, hdot, t0, t1 };
  }

  function nearest(pts, ts) {
    let lo = 0, hi = pts.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (pts[mid][0] < ts) lo = mid; else hi = mid;
    }
    return Math.abs(pts[lo][0] - ts) <= Math.abs(pts[hi][0] - ts) ? pts[lo] : pts[hi];
  }

  function onPointer(ev) {
    if (!geom) return;
    const g = geom;
    const rect = $("chart").getBoundingClientRect();
    const px = ev.clientX - rect.left;
    if (px < g.pad.l || px > g.W - g.pad.r) return hideReadout();
    const ts = g.t0 + ((px - g.pad.l) / (g.W - g.pad.l - g.pad.r)) * (g.t1 - g.t0);
    const p = nearest(g.pts, ts);
    const xx = g.x(p[0]);
    const temp = p[g.TI];

    g.hover.setAttribute("opacity", 1);
    g.vline.setAttribute("x1", xx); g.vline.setAttribute("x2", xx);
    g.tdot.setAttribute("cx", xx); g.tdot.setAttribute("cy", g.yT(temp));
    g.tdot.setAttribute("stroke", tempColor(temp));
    g.hdot.setAttribute("cx", xx); g.hdot.setAttribute("cy", g.yH(p[g.HI]));

    const r = $("readout");
    const when = g.hourly
      ? weekdayFmt.format(p[0] * 1000)
      : timeFmt.format(p[0] * 1000);
    let html = `<span class="when">${when}</span>` +
      `<b class="t">${fmtTemp(temp)}${deg()}</b><b class="h">${Math.round(p[g.HI])}%</b>`;
    if (g.hourly) {
      html += `<span class="span">Daily average. Low ${fmtTemp(p[2])}°, high ${fmtTemp(p[3])}°</span>`;
    }
    r.innerHTML = html;
    r.hidden = false;
    const half = r.offsetWidth / 2;
    r.style.left = Math.min(Math.max(xx, half), g.W - half) + "px";
  }

  function hideReadout() {
    $("readout").hidden = true;
    if (geom) geom.hover.setAttribute("opacity", 0);
  }

  // ---- controls ---------------------------------------------------------------

  function setPressed(groupSel, attr, value) {
    document.querySelectorAll(`${groupSel} button`).forEach((b) => {
      b.setAttribute("aria-pressed", String(b.dataset[attr] === value));
    });
  }

  document.querySelectorAll(".ranges button").forEach((b) => {
    b.addEventListener("click", () => {
      if (state.range === b.dataset.range) return;
      state.range = b.dataset.range;
      setPressed(".ranges", "range", state.range);
      fetchHistory();
    });
  });

  document.querySelectorAll(".units button").forEach((b) => {
    b.addEventListener("click", () => {
      state.unit = b.dataset.unit;
      savePref("unit", state.unit);
      setPressed(".units", "unit", state.unit);
      renderNow();
      renderRangeNote();
      renderChart();
    });
  });

  const chartBox = $("chart");
  chartBox.addEventListener("pointermove", onPointer);
  chartBox.addEventListener("pointerdown", onPointer);
  chartBox.addEventListener("pointerleave", hideReadout);

  let resizeTimer;
  new ResizeObserver(() => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(renderChart, 120);
  }).observe(chartBox);

  // ---- start ----------------------------------------------------------------

  setPressed(".units", "unit", state.unit);
  fetchCurrent();
  fetchHistory();
  setInterval(fetchCurrent, CURRENT_EVERY);
  setInterval(() => { if (state.range === "24h") fetchHistory(); }, HISTORY_EVERY);
  setInterval(renderStatus, 5_000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) { fetchCurrent(); fetchHistory(); }
  });
})();
