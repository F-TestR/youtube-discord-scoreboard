/* Small SVG charts: lines/areas over time, bars, sparklines, with hover/tap tooltips. No libraries. */
(function () {
  const NS = "http://www.w3.org/2000/svg";
  const el = (tag, attrs, parent) => {
    const n = document.createElementNS(NS, tag);
    for (const k in attrs || {}) if (attrs[k] !== undefined && attrs[k] !== null) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  };
  const short = (v) => {
    if (v === null || v === undefined || isNaN(v)) return "—";
    const a = Math.abs(v);
    if (a >= 1e6) return (v / 1e6).toFixed(a >= 1e7 ? 0 : 1).replace(/\.0$/, "") + "M";
    if (a >= 1e3) return (v / 1e3).toFixed(a >= 1e4 ? 0 : 1).replace(/\.0$/, "") + "K";
    return Math.round(v).toString();
  };
  const full = (v) => (v === null || v === undefined || isNaN(v)) ? "—" : Math.round(v).toLocaleString("en-GB");
  const niceMax = (v) => {
    if (!(v > 0)) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    for (const m of [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) if (m * p >= v) return m * p;
    return 10 * p;
  };
  const niceStep = (raw) => {
    if (!(raw > 0)) return 1;
    const p = Math.pow(10, Math.floor(Math.log10(raw)));
    for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= raw) return m * p;
    return 10 * p;
  };
  const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function tipBox(host) {
    let t = host.querySelector(".chart-tip");
    if (!t) { t = document.createElement("div"); t.className = "chart-tip"; t.hidden = true; host.appendChild(t); }
    return t;
  }

  /* opts: series [{name, color, data:[[x,y]], area, dash}], height, x: "time"|"num", yFmt, xFmt, xTip,
     markers [{x, label, color}], band {data:[[x,lo,hi]], color}, yMin, logY, label (aria) */
  function line(host, opts) {
    host.innerHTML = "";
    host.classList.add("chart");
    const W = Math.max(host.clientWidth || 600, 260), H = opts.height || 260;
    const pad = { l: 46, r: 16, t: 14, b: 30 };
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": opts.label || "chart" }, host);
    const all = opts.series.flatMap((s) => s.data.filter((d) => d[1] !== null && d[1] !== undefined));
    if (!all.length) { host.innerHTML = `<p class="chart-empty">${opts.empty || "No numbers for this yet."}</p>`; return; }
    let xs = all.map((d) => d[0]);
    if (opts.band) xs = xs.concat(opts.band.data.map((d) => d[0]));
    const x0 = opts.xMin ?? Math.min(...xs), x1 = opts.xMax ?? Math.max(...xs);
    let ys = all.map((d) => d[1]);
    if (opts.band) ys = ys.concat(opts.band.data.map((d) => d[2]));
    const yMin = opts.logY ? 1 : (opts.yMin ?? 0);
    const step = niceStep((Math.max(...ys) * 1.04 - yMin) / 4);
    const yMax = opts.logY ? niceMax(Math.max(...ys) * 1.05) : yMin + Math.max(Math.ceil((Math.max(...ys) * 1.04 - yMin) / step), 1) * step;
    const X = (v) => pad.l + ((v - x0) / Math.max(x1 - x0, 1)) * (W - pad.l - pad.r);
    const Y = opts.logY
      ? (v) => pad.t + (1 - Math.log10(Math.max(v, 1)) / Math.log10(yMax)) * (H - pad.t - pad.b)
      : (v) => pad.t + (1 - (v - yMin) / (yMax - yMin)) * (H - pad.t - pad.b);
    const grid = el("g", { class: "grid" }, svg);
    const ticks = [];
    if (opts.logY) [1, 10, 100, 1e3, 1e4, 1e5, 1e6].filter((v) => v <= yMax).forEach((v) => ticks.push(v));
    else for (let v = yMin; v <= yMax + step / 2; v += step) ticks.push(v);
    ticks.forEach((v) => {
      el("line", { x1: pad.l, x2: W - pad.r, y1: Y(v), y2: Y(v) }, grid);
      el("text", { x: pad.l - 8, y: Y(v) + 4, "text-anchor": "end", class: "tick" }, grid).textContent = (opts.yFmt || short)(v);
    });
    const xt = opts.x === "num" ? (opts.xTicks || []) : timeTicks(x0, x1, W);
    xt.forEach((v) => {
      el("text", { x: X(v), y: H - 8, "text-anchor": "middle", class: "tick" }, grid).textContent = (opts.xFmt || dayFmt)(v);
    });
    if (opts.band) {
      const b = opts.band.data;
      const d = b.map((p, i) => `${i ? "L" : "M"}${X(p[0])},${Y(p[2])}`).join("") +
        b.slice().reverse().map((p) => `L${X(p[0])},${Y(p[1])}`).join("") + "Z";
      el("path", { d, fill: opts.band.color || "#8FB3B0", "fill-opacity": 0.16, stroke: "none" }, svg);
    }
    const merged = [];
    (opts.markers || []).slice().sort((a, b) => a.x - b.x).forEach((m) => {
      const last = merged[merged.length - 1];
      if (last && Math.abs(X(m.x) - X(last.x)) < 40) { last.n = (last.n || 1) + 1; last.label = `${last.n} new`; }
      else merged.push({ ...m });
    });
    merged.forEach((m) => {
      if (m.x < x0 || m.x > x1) return;
      const g = el("g", { class: "marker" }, svg);
      el("line", { x1: X(m.x), x2: X(m.x), y1: pad.t, y2: H - pad.b, stroke: m.color || "#E7B24C", "stroke-dasharray": "3 4" }, g);
      el("text", { x: X(m.x) + 4, y: pad.t + 10, class: "marker-label", fill: m.color || "#E7B24C" }, g).textContent = m.label || "";
    });
    const paths = [];
    opts.series.forEach((s) => {
      const segs = [];
      let cur = [];
      s.data.forEach((p) => { if (p[1] === null || p[1] === undefined) { if (cur.length) segs.push(cur); cur = []; } else cur.push(p); });
      if (cur.length) segs.push(cur);
      segs.forEach((seg) => {
        const d = seg.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
        if (s.area && seg.length > 1) {
          el("path", { d: d + `L${X(seg[seg.length - 1][0])},${Y(yMin)}L${X(seg[0][0])},${Y(yMin)}Z`, fill: s.color, "fill-opacity": 0.13 }, svg);
        }
        const path = el("path", { d, fill: "none", stroke: s.color, "stroke-width": s.width || 2.4, "stroke-linejoin": "round",
          "stroke-linecap": "round", "stroke-dasharray": s.dash || null, class: "series-line", "data-name": s.name }, svg);
        paths.push(path);
        if (seg.length === 1 || s.dots) seg.forEach((p) => el("circle", { cx: X(p[0]), cy: Y(p[1]), r: 3.2, fill: s.color }, svg));
      });
      const last = s.data.filter((p) => p[1] !== null && p[1] !== undefined).slice(-1)[0];
      if (last && s.endDot !== false) el("circle", { cx: X(last[0]), cy: Y(last[1]), r: 4.2, fill: s.color, stroke: "#0B1F27", "stroke-width": 2 }, svg);
      if (last && s.endLabel) {
        el("text", { x: Math.min(X(last[0]) + 7, W - pad.r), y: Y(last[1]) + 4, class: "end-label", fill: s.color,
          "text-anchor": X(last[0]) > W - 120 ? "end" : "start" }, svg).textContent = s.endLabel;
      }
    });
    if (!reduce && opts.animate !== false) {
      paths.forEach((p) => {
        const len = p.getTotalLength();
        p.style.strokeDasharray = p.getAttribute("stroke-dasharray") ? null : `${len} ${len}`;
        if (!p.getAttribute("stroke-dasharray")) {
          p.style.strokeDashoffset = len;
          p.getBoundingClientRect();
          p.style.transition = "stroke-dashoffset 900ms cubic-bezier(.3,.7,.2,1)";
          requestAnimationFrame(() => (p.style.strokeDashoffset = 0));
        }
      });
    }
    // tooltip
    const rule = el("line", { y1: pad.t, y2: H - pad.b, class: "rule", visibility: "hidden" }, svg);
    const tip = tipBox(host);
    const xsAll = [...new Set(opts.series.flatMap((s) => s.data.map((d) => d[0])))].sort((a, b) => a - b);
    const near = (arr, x) => {
      let best = null, bd = Infinity;
      arr.forEach((p) => { if (p[1] === null || p[1] === undefined) return; const d = Math.abs(p[0] - x); if (d < bd) { bd = d; best = p; } });
      return best;
    };
    const move = (ev) => {
      const r = svg.getBoundingClientRect();
      const px = ((ev.clientX - r.left) / r.width) * W;
      const xv = x0 + ((px - pad.l) / (W - pad.l - pad.r)) * (x1 - x0);
      const xn = near(xsAll.map((x) => [x, 0]), xv);
      if (!xn) return;
      rule.setAttribute("x1", X(xn[0])); rule.setAttribute("x2", X(xn[0])); rule.setAttribute("visibility", "visible");
      const rows = opts.series.map((s) => {
        const p = near(s.data, xn[0]);
        if (!p || Math.abs(p[0] - xn[0]) > (x1 - x0) / 25) return "";
        return `<div><i style="background:${s.color}"></i>${s.name}<b>${(opts.tipFmt || full)(p[1])}</b></div>`;
      }).join("");
      if (!rows) { tip.hidden = true; return; }
      tip.innerHTML = `<div class="tip-head">${(opts.xTip || tipTime)(xn[0])}</div>${rows}`;
      tip.hidden = false;
      const hx = (X(xn[0]) / W) * r.width;
      tip.style.left = Math.min(Math.max(hx + 12, 0), r.width - tip.offsetWidth - 4) + "px";
      tip.style.top = "8px";
    };
    svg.addEventListener("pointermove", move);
    svg.addEventListener("pointerdown", move);
    svg.addEventListener("pointerleave", () => { tip.hidden = true; rule.setAttribute("visibility", "hidden"); });
  }

  /* bars: categories [labels], series [{name,color,values}], grouped */
  function bars(host, opts) {
    host.innerHTML = "";
    host.classList.add("chart");
    const W = Math.max(host.clientWidth || 600, 260), H = opts.height || 240;
    const pad = { l: 46, r: 10, t: 16, b: 30 };
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": opts.label || "bar chart" }, host);
    const vals = opts.series.flatMap((s) => s.values.filter((v) => v !== null && v !== undefined));
    if (!vals.length) { host.innerHTML = `<p class="chart-empty">${opts.empty || "No numbers for this yet."}</p>`; return; }
    const yMax = niceMax(Math.max(...vals, 1) * 1.08);
    const Y = (v) => pad.t + (1 - v / yMax) * (H - pad.t - pad.b);
    const grid = el("g", { class: "grid" }, svg);
    [0, 0.5, 1].forEach((f) => {
      el("line", { x1: pad.l, x2: W - pad.r, y1: Y(f * yMax), y2: Y(f * yMax) }, grid);
      el("text", { x: pad.l - 8, y: Y(f * yMax) + 4, "text-anchor": "end", class: "tick" }, grid).textContent = short(f * yMax);
    });
    const n = opts.categories.length, slot = (W - pad.l - pad.r) / Math.max(n, 1);
    const k = opts.series.length, bw = Math.min(28, (slot * 0.74) / k);
    const every = Math.ceil(n / Math.max(Math.floor((W - 60) / 56), 1));
    const tip = tipBox(host);
    opts.categories.forEach((c, i) => {
      const cx = pad.l + slot * (i + 0.5);
      if (i % every === 0 || i === n - 1) el("text", { x: cx, y: H - 8, "text-anchor": "middle", class: "tick" }, grid).textContent = (opts.catFmt || ((s) => s))(c);
      opts.series.forEach((s, j) => {
        const v = s.values[i];
        if (v === null || v === undefined) {
          el("rect", { x: cx - (k * bw) / 2 + j * bw + 1, y: Y(0) - 2, width: bw - 2, height: 2, class: "bar-missing" }, svg);
          return;
        }
        const r = el("rect", { x: cx - (k * bw) / 2 + j * bw + 1, y: Y(Math.max(v, 0)), width: bw - 2,
          height: Math.max(Y(0) - Y(Math.max(v, 0)), 1), rx: 3, fill: s.color, class: "bar" }, svg);
        r.addEventListener("pointerenter", () => {
          tip.innerHTML = `<div class="tip-head">${(opts.catTip || ((s) => s))(c)}</div><div><i style="background:${s.color}"></i>${s.name}<b>${full(v)}</b></div>`;
          tip.hidden = false;
          const b = svg.getBoundingClientRect();
          tip.style.left = Math.min((cx / W) * b.width + 8, b.width - 160) + "px";
          tip.style.top = "6px";
        });
        r.addEventListener("pointerleave", () => (tip.hidden = true));
      });
    });
  }

  function spark(host, data, color, opts) {
    host.innerHTML = "";
    const pts = data.filter((d) => d[1] !== null && d[1] !== undefined);
    const W = opts?.width || 140, H = opts?.height || 38;
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: H, "aria-hidden": "true", preserveAspectRatio: "none" }, host);
    if (pts.length < 2) return;
    const x0 = pts[0][0], x1 = pts[pts.length - 1][0];
    const ys = pts.map((p) => p[1]); const lo = Math.min(...ys), hi = Math.max(...ys);
    const X = (v) => 2 + ((v - x0) / Math.max(x1 - x0, 1)) * (W - 6);
    const Y = (v) => H - 3 - ((v - lo) / Math.max(hi - lo, 1)) * (H - 8);
    const d = pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join("");
    el("path", { d: d + `L${X(x1)},${H}L${X(x0)},${H}Z`, fill: color, "fill-opacity": 0.14 }, svg);
    el("path", { d, fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "vector-effect": "non-scaling-stroke" }, svg);
  }

  function timeTicks(x0, x1, W) {
    const days = (x1 - x0) / 864e5;
    const target = Math.max(Math.floor((W - 80) / 90), 2);
    const stepDays = [1, 2, 3, 7, 14, 30, 61, 91].find((s) => days / s <= target) || 182;
    const out = [];
    const d = new Date(x0); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() + 1);
    while (d.getTime() <= x1) { out.push(d.getTime()); d.setDate(d.getDate() + stepDays); }
    return out;
  }
  const dayFmt = (v) => new Date(v).toLocaleDateString("en-GB", { weekday: "short", day: "numeric" });
  const tipTime = (v) => new Date(v).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

  window.Charts = { line, bars, spark, short, full };
})();
