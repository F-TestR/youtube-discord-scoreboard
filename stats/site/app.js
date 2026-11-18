/* PIRACY social stats: renders data.json, refreshes itself every few minutes. */
(function () {
  "use strict";
  const C = window.Charts;
  const $ = (s, r = document) => r.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const full = (v) => (v === null || v === undefined || isNaN(v)) ? "—" : Math.round(v).toLocaleString("en-GB");
  const short = C.short;
  const signed = (v) => (v === null || v === undefined) ? "—" : (Math.round(v) === 0 ? "±0" : (v > 0 ? "+" : "−") + Math.abs(Math.round(v)).toLocaleString("en-GB"));
  const pct = (v, d = 1) => (v === null || v === undefined) ? "—" : (v * 100).toFixed(d) + "%";
  const T = (s) => new Date(s).getTime();
  const clean = (t) => (String(t || "").replace(/#[\w]+/g, "").replace(/\s+/g, " ").trim() || "Untitled");
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const APPS = {
    youtube: { name: "YouTube Shorts", short: "Shorts", color: "#FF7266", follow: "subscribers",
      icon: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13l11-6.5z"/></svg>' },
    tiktok: { name: "TikTok", short: "TikTok", color: "#8BE3F5", follow: "followers",
      icon: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M14 3h3c.3 2.2 1.7 3.6 4 3.9V10c-1.6 0-3-.5-4-1.2V15a6 6 0 1 1-6-6v3.2a2.8 2.8 0 1 0 3 2.8z"/></svg>' },
    instagram: { name: "Instagram Reels", short: "Reels", color: "#D08CF0", follow: "followers",
      icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><rect x="4" y="4" width="16" height="16" rx="5"/><circle cx="12" cy="12" r="3.6"/><circle cx="17" cy="7" r="1" fill="currentColor"/></svg>' },
    discord: { name: "Discord", short: "Discord", color: "#9AA7FF", follow: "members",
      icon: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-7l-5 4v-4H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2z"/></svg>' },
  };
  const PLATS = ["youtube", "tiktok", "instagram"];
  const VIEW_STEPS = [100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 250000, 500000, 1e6, 2.5e6, 5e6, 1e7];
  const FOLLOW_STEPS = [10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 250000, 1e6];
  const TAGS = { OBSERVED: ["From our numbers", ""], EARLY: ["Early signal", "early"], WATCH: ["Worth a look", "watch"] };

  let D = null, page = "overview", chartApp = null, range = 30, logScale = false;
  const vf = { q: "", app: "all", sort: "newest", removed: false };

  const badge = (pl, label) => {
    const a = APPS[pl];
    return `<span class="plat-badge"><i style="background:${a.color};color:#0B1F27">${a.icon}</i>${esc(label || a.short)}</span>`;
  };
  const ago = (iso) => {
    if (!iso) return "never";
    const m = Math.round((Date.now() - T(iso)) / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m} minute${m === 1 ? "" : "s"} ago`;
    const h = Math.round(m / 60);
    if (h < 48) return `${h} hour${h === 1 ? "" : "s"} ago`;
    return `${Math.round(h / 24)} days ago`;
  };
  const ageShort = (iso) => {
    const h = (Date.now() - T(iso)) / 36e5;
    if (h < 1) return "just now";
    if (h < 48) return `${Math.round(h)} h old`;
    return `${Math.round(h / 24)} days old`;
  };
  const dayName = (iso) => new Date(iso).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
  const dateTime = (iso) => new Date(iso).toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const live = () => D.posts.filter((p) => p.status === "live");
  const status = (pl) => (D.status[pl] || {}).status || "not_connected";

  // ------------------------------------------------------------ loading
  async function load(first) {
    try {
      const r = await fetch(`data.json?t=${Date.now()}`, { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      const data = await r.json();
      const changed = !D || data.generated !== D.generated;
      D = data;
      if (changed) {
        render(first);
        if (!first) toast("Fresh numbers just came in");
        else if (location.hash.startsWith("#video=")) openVideo(decodeURIComponent(location.hash.slice(7)));
      }
      freshness();
    } catch (e) {
      $("#fresh-text").textContent = "Couldn't load the numbers. Trying again shortly.";
    }
  }
  function freshness() {
    if (!D) return;
    const mins = (Date.now() - T(D.generated)) / 60000;
    const next = Math.max(0, Math.round((T(D.next_run) - Date.now()) / 60000));
    const late = mins > (D.run_every_h || 1) * 60 * 2.5;
    $(".pulse").classList.toggle("stale", late);
    $("#fresh-text").textContent = `Updated ${ago(D.generated)}` +
      (late ? " · the next update is running late" : next > 1 ? ` · next update in about ${next} minutes` : " · next update any minute now");
  }
  function toast(msg) {
    const t = $("#toast"); t.textContent = msg; t.hidden = false;
    clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 3600);
  }

  // ------------------------------------------------------------ routing
  function route() {
    const h = location.hash.replace(/^#/, "");
    if (h.startsWith("video=")) {
      if (!document.querySelector(".page:not([hidden])")) show("videos");
      openVideo(decodeURIComponent(h.slice(6)));
      return;
    }
    const [p, q] = h.split("?");
    if (q) { const app = new URLSearchParams(q).get("app"); if (app) vf.app = app; }
    show(["overview", "videos", "analytics", "research", "trends", "status"].includes(p) ? p : "overview");
  }
  function show(p) {
    page = p;
    document.body.classList.toggle("inner", p !== "overview");
    document.querySelectorAll(".page").forEach((s) => (s.hidden = s.dataset.page !== p));
    document.querySelectorAll(".tabs a").forEach((a) => a.setAttribute("aria-selected", a.dataset.page === p ? "true" : "false"));
    if (D) renderPage(p);
  }
  function render(first) {
    $("#repo-link").href = D.repo || "#";
    const bad = PLATS.concat(["discord"]).some((pl) => ["error", "stale"].includes(status(pl)));
    $("#status-dot").hidden = !bad;
    renderPage(page, first);
    sail(first);
  }
  function renderPage(p, first) {
    ({ overview: overview, videos: videos, analytics: analytics, research: researchPage, trends: trends, status: statusPage }[p])(first);
  }

  // ------------------------------------------------------------ hero ship: sails toward the next milestone
  function sail(first) {
    const g = (D.progress || []).find((x) => x.platform === "youtube" && x.kind === "views") || (D.progress || [])[0];
    const f = g ? g.pct : 0.1;
    const ship = $("#ship");
    const go = () => (ship.style.left = `${36 + Math.min(Math.max(f, 0.03), 0.97) * 52}%`);
    if (first && !reduce) setTimeout(go, 350); else go();
  }

  // ------------------------------------------------------------ overview
  function mainApp() {
    const s = D.summary.platforms;
    return PLATS.filter((pl) => s[pl] && s[pl].posts && !s[pl].typed).sort((a, b) => (s[b].total_views || 0) - (s[a].total_views || 0))[0];
  }
  function overview(first) {
    const s = D.summary.platforms, el = $("#page-overview");
    const m = mainApp();
    let lead, sub;
    if (m && s[m].gain_24h !== null && s[m].gain_24h !== undefined) {
      lead = `<span class="num" data-count="${Math.round(s[m].gain_24h)}">${signed(s[m].gain_24h)}</span> views on ${APPS[m].name} in the last day.`;
      const prev = s[m].gain_prev_24h;
      sub = prev !== null && prev !== undefined ? `The day before it was ${signed(prev)}. ${full(s[m].total_views)} views across ${s[m].posts} live ${s[m].posts === 1 ? "post" : "posts"} so far.` :
        `${full(s[m].total_views)} views across ${s[m].posts} live ${s[m].posts === 1 ? "post" : "posts"} so far.`;
    } else if (m) {
      lead = `<span class="num" data-count="${Math.round(s[m].total_views || 0)}">${full(s[m].total_views)}</span> views on ${APPS[m].name} so far.`;
      sub = "Daily gains appear once there's a full day of readings.";
    } else {
      lead = "Waiting for the first numbers.";
      sub = "Connect an app on the Status page and they'll show up within the hour.";
    }
    el.innerHTML = `
      <div><h2 class="lead">${lead}</h2><p class="lead-sub">${esc(sub)}</p></div>
      <div class="ledger" role="table" aria-label="Each app at a glance">${PLATS.concat(["discord"]).map(ledgerRow).join("")}</div>
      <div class="two">
        <article class="log" aria-labelledby="log-h"><h2 id="log-h">Ship's log</h2>
          <p class="date">${esc(new Date(D.generated).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" }))}</p>
          <ul>${(D.insights || []).map(logItem).join("") || "<li>Nothing to report yet.</li>"}</ul></article>
        <article class="panel chart-panel" aria-labelledby="ch-h">
          <div class="section-head"><div><h2 id="ch-h">Total views over time</h2><p class="small muted">Views on posts that are still up. Dashed lines mark new uploads.</p></div>
          <div class="app-switch" id="ov-switch"></div></div>
          <div id="ov-chart"></div></article>
      </div>
      ${treasure()}
      <div><div class="section-head"><h2>Top of the week</h2><p>Most views gained in the last 7 days</p></div><div class="podium">${podium()}</div></div>
      <div><div class="section-head"><h2>Latest uploads</h2><a href="#videos">See every video</a></div><div class="grid-cards">${live().slice(0, 4).map(card).join("") || '<p class="empty-note">No uploads yet.</p>'}</div></div>`;
    // sparklines
    PLATS.forEach((pl) => { const h = $(`#spark-${pl}`); if (h) C.spark(h, (D.series[pl] || []).slice(-56).map((p) => [T(p[0]), p[1]]), APPS[pl].color); });
    const dh = $("#spark-discord"); if (dh) C.spark(dh, (D.followers.discord || []).map((p) => [T(p[0]), p[1]]), APPS.discord.color);
    // chart with app switch
    const have = PLATS.filter((pl) => (D.series[pl] || []).some((p) => p[1] !== null) && !s[pl].typed);
    if (!chartApp || !have.includes(chartApp)) chartApp = have[0];
    $("#ov-switch").innerHTML = have.map((pl) => `<button type="button" data-app="${pl}" aria-pressed="${pl === chartApp}">${APPS[pl].short}</button>`).join("");
    $("#ov-switch").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; chartApp = b.dataset.app; overviewChart(); $("#ov-switch").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x.dataset.app === chartApp)); };
    overviewChart();
    drawRoutes();
    el.querySelectorAll("[data-video]").forEach((c) => c.addEventListener("click", (e) => { e.preventDefault(); location.hash = "video=" + encodeURIComponent(c.dataset.video); }));
    if (first) countUp(el.querySelector("[data-count]"));
  }
  function overviewChart() {
    const host = $("#ov-chart");
    if (!chartApp) { host.innerHTML = '<p class="chart-empty">The chart starts once an app is connected.</p>'; return; }
    const ser = (D.series[chartApp] || []).map((p) => [T(p[0]), p[1]]);
    const ups = live().filter((p) => p.platform === chartApp).map((p) => ({ x: T(p.posted), label: "new", color: "#E7B24C" }));
    C.line(host, { series: [{ name: APPS[chartApp].name, color: APPS[chartApp].color, data: ser, area: true }], height: 280, markers: ups,
      label: `${APPS[chartApp].name} total views over time`, yMin: 0 });
  }
  function ledgerRow(pl) {
    const a = APPS[pl];
    if (pl === "discord") {
      const d = D.summary.discord || {};
      const st = status("discord");
      return `<div class="app-row${d.members ? "" : " off"}" role="row">
        <div class="app-name" role="cell"><span class="app-badge" style="background:${a.color};color:#0B1F27">${a.icon}</span><div><b>Discord</b><small>${chipFor(st)}</small></div></div>
        <div class="stat" role="cell"><div class="v big">${full(d.members)}</div><div class="k">members</div></div>
        <div class="stat" role="cell"><div class="v ${d.members_7d > 0 ? "up" : ""}">${d.members_7d === null || d.members_7d === undefined ? "—" : signed(d.members_7d)}</div><div class="k">this week</div></div>
        <div class="stat" role="cell"><div class="v">${d.first !== undefined ? full(d.first) : "—"}</div><div class="k">${d.first_ts ? "on " + esc(dayName(d.first_ts)) : "at the start"}</div></div>
        <div class="stat" role="cell"><div class="v">${(D.status.discord && D.status.discord.account && D.status.discord.account.online) ? full(D.status.discord.account.online) : "—"}</div><div class="k">online now</div></div>
        <div class="spark" id="spark-discord" role="cell"></div></div>`;
    }
    const s = D.summary.platforms[pl] || {}, st = status(pl);
    const off = !s.posts;
    const acc = (D.status[pl] || {}).account || {};
    if (off) {
      return `<div class="app-row off" role="row">
        <div class="app-name" role="cell"><span class="app-badge" style="background:${a.color};color:#0B1F27">${a.icon}</span><div><b>${a.name}</b><small>${chipFor(st)}</small></div></div>
        <div class="stat" role="cell" style="grid-column: span 4"><span class="muted">${st === "not_connected" ? "Not connected yet. " : esc((D.status[pl] || {}).message || "") + " "}</span><a class="connect-cta" href="#status">How to connect it</a></div>
        <div class="spark" role="cell"></div></div>`;
    }
    const g = s.gain_24h;
    return `<div class="app-row" role="row">
      <div class="app-name" role="cell"><span class="app-badge" style="background:${a.color};color:#0B1F27">${a.icon}</span><div><b>${a.name}</b><small>${chipFor(st)}</small></div></div>
      <div class="stat" role="cell"><div class="v big ${g > 0 ? "up" : ""}">${s.typed ? "—" : signed(g)}</div><div class="k">${s.typed ? "typed in by hand" : "last 24 hours"}</div></div>
      <div class="stat" role="cell"><div class="v">${full(s.total_views)}</div><div class="k">total views</div></div>
      <div class="stat" role="cell"><div class="v">${full(s.followers ?? acc.followers)}</div><div class="k">${a.follow}</div></div>
      <div class="stat" role="cell"><div class="v">${full(s.posts)}</div><div class="k">${s.posts === 1 ? "post" : "posts"}${s.last_post ? ", newest " + esc(ago(s.last_post)) : ""}</div></div>
      <div class="spark" id="spark-${pl}" role="cell"></div></div>`;
  }
  function chipFor(st) {
    const m = { ok: ["ok", "Live"], typed: ["typed", "Typed in"], error: ["err", "Not answering"], stale: ["err", "Last good numbers"], not_connected: ["off", "Not connected"] }[st] || ["off", st];
    return `<span class="chip ${m[0]}">${m[1]}</span>`;
  }
  function logItem(n) {
    const t = TAGS[n.tag] || [n.tag, ""];
    const link = n.post ? ` <a href="#video=${encodeURIComponent(n.post)}">Open</a>` : "";
    return `<li class="${t[1]}">${esc(n.text)}<span class="tag ${t[1]}">${t[0]}</span>${link}</li>`;
  }
  function countUp(node) {
    if (!node || reduce) return;
    const end = +node.dataset.count, startT = performance.now(), dur = 1400;
    const sign = node.textContent.trim().startsWith("+");
    const step = (now) => {
      const f = Math.min((now - startT) / dur, 1), v = Math.round(end * (1 - Math.pow(1 - f, 3)));
      node.textContent = (sign && v > 0 ? "+" : "") + v.toLocaleString("en-GB");
      if (f < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // ------------------------------------------------------------ treasure map
  function treasure() {
    const prog = D.progress || [];
    if (!prog.length) return "";
    const routes = prog.map((g, gi) => {
      const what = g.kind === "views" ? `total views on ${APPS[g.platform].short}` : g.platform === "discord" ? "Discord members" : `${APPS[g.platform].follow} on ${APPS[g.platform].short}`;
      return `<div class="route"><div class="route-name">${full(g.value)} ${esc(what)}<small>${Math.round(g.pct * 100)}% of the way to ${full(g.next)}</small></div>
        <div class="route-svg" data-route="${gi}" role="img" aria-label="${full(g.value)} of ${full(g.next)} ${esc(what)}"></div></div>`;
    }).join("");
    const reached = (D.milestones || []).slice().reverse().slice(0, 12)
      .map((m) => `<span><b>${m.before ? "by " : ""}${esc(dayName(m.ts))}</b>${esc(m.label)}</span>`).join("");
    return `<article class="map" aria-labelledby="map-h"><h2 id="map-h">The treasure map</h2>
      <p class="map-sub">Gold coins are milestones you've passed. Each X is the next one to reach.</p>
      <div class="routes">${routes}</div>${reached ? `<div class="logbook">${reached}</div>` : ""}</article>`;
  }
  function drawRoutes() {
    document.querySelectorAll("[data-route]").forEach((host) => {
      const g = D.progress[+host.dataset.route];
      const steps = g.kind === "views" ? VIEW_STEPS : FOLLOW_STEPS;
      const i = steps.indexOf(g.next);
      const seq = steps.slice(Math.max(0, i - 2), i + 2);
      const W = Math.max(host.clientWidth, 240), H = 76, n = seq.length;
      const xs = seq.map((_, k) => 30 + (k * (W - 60)) / Math.max(n - 1, 1));
      const ys = seq.map((_, k) => (k % 2 ? 24 : 50));
      let d = `M${xs[0]},${ys[0]}`;
      for (let k = 1; k < n; k++) { const mx = (xs[k - 1] + xs[k]) / 2; d += ` C${mx},${ys[k - 1]} ${mx},${ys[k]} ${xs[k]},${ys[k]}`; }
      const ni = seq.indexOf(g.next);
      const pos = ni > 0 ? xs[ni - 1] + (xs[ni] - xs[ni - 1]) * g.pct : xs[0];
      const marks = seq.map((v, k) => {
        const reached = v <= g.value;
        const lab = `<text x="${xs[k]}" y="${ys[k] + (k % 2 ? -12 : 26)}" text-anchor="middle">${short(v)}</text>`;
        return reached ? `<circle class="reached" cx="${xs[k]}" cy="${ys[k]}" r="9"/>${lab}`
          : `<path class="x" d="M${xs[k] - 7},${ys[k] - 7}L${xs[k] + 7},${ys[k] + 7}M${xs[k] + 7},${ys[k] - 7}L${xs[k] - 7},${ys[k] + 7}"/>${lab}`;
      }).join("");
      host.innerHTML = `<svg class="route-svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-hidden="true">
          <path class="path" d="${d}"/>
          <clipPath id="clip-${g.platform}-${g.kind}"><rect x="0" y="0" width="${pos}" height="${H}"/></clipPath>
          <path class="done" d="${d}" clip-path="url(#clip-${g.platform}-${g.kind})"/>${marks}
          <g transform="translate(${pos - 14},${(ys[Math.max(ni, 1)] + ys[Math.max(ni - 1, 0)]) / 2 - 30})"><path d="M14 2v24" stroke="#2B2118" stroke-width="2"/><path d="M15 4c9 3 10 13 1 17z" fill="#F7EEDA" stroke="#2B2118" stroke-width="1.5"/><path d="M2 26h26l-4 7H6z" fill="#3B2A1E"/></g>
        </svg>`;
    });
  }

  // ------------------------------------------------------------ cards
  function thumbImg(p) {
    return p.thumb ? `<img src="${esc(p.thumb)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<div class="noimg">${esc(APPS[p.platform].short)}</div>`;
  }
  function vsChip(p) {
    if (!p.vs_usual) return "";
    const r = p.vs_usual.ratio, cls = r >= 1.15 ? "up" : r <= 0.85 ? "down" : "muted";
    return `<span class="vs ${cls}">${r.toFixed(1)}× your usual at ${p.vs_usual.hours} h</span>`;
  }
  function card(p) {
    const m = p.metrics || {};
    return `<a class="card${p.status !== "live" ? " gone" : ""}" href="#video=${encodeURIComponent(p.id)}" data-video="${esc(p.id)}">
      <div class="thumb">${thumbImg(p)}<span class="plat">${badge(p.platform)}</span><span class="age">${p.status === "live" ? ageShort(p.posted) : "removed"}</span></div>
      <div class="body"><div class="title">${esc(clean(p.title))}</div>
        <div class="nums"><span><b>${full(m.views)}</b> views</span>${p.gain_24h ? `<span class="up">${signed(p.gain_24h)} today</span>` : ""}<span>${full(m.likes)} likes</span></div>
        ${vsChip(p)}${p.source === "typed" ? '<span class="small muted">Typed in by hand</span>' : ""}</div></a>`;
  }
  function podium() {
    const rows = live().filter((p) => p.metrics && p.metrics.views !== undefined)
      .sort((a, b) => ((b.gain_7d ?? -1) - (a.gain_7d ?? -1)) || ((b.metrics.views || 0) - (a.metrics.views || 0))).slice(0, 3);
    if (!rows.length) return '<p class="empty-note">Nothing on the podium yet.</p>';
    return rows.map((p, i) => `<a class="prize" href="#video=${encodeURIComponent(p.id)}" data-video="${esc(p.id)}">
      <div class="thumb">${thumbImg(p)}<span class="medal${i ? " m" + (i + 1) : ""}" aria-label="Place ${i + 1}">${i + 1}</span></div>
      <div class="t">${esc(clean(p.title))}</div>
      <div class="n"><b>${p.gain_7d !== null && p.gain_7d !== undefined ? signed(p.gain_7d) : full(p.metrics.views)}</b> ${p.gain_7d !== null && p.gain_7d !== undefined ? "this week" : "views"} · ${badge(p.platform)}</div></a>`).join("");
  }

  // ------------------------------------------------------------ videos page
  function videos() {
    const el = $("#page-videos");
    if (!el.dataset.ready) {
      el.innerHTML = `<div class="section-head"><div><h2>Every video</h2><p>Tap one for its growth curve, readings and copies on other apps.</p></div></div>
        <div class="toolbar">
          <label class="search"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#8FB3B0" stroke-width="2.4" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>
            <span class="sr" hidden>Search</span><input id="vq" type="search" placeholder="Search titles" aria-label="Search titles"></label>
          <div class="app-switch" id="vapp" role="group" aria-label="App"></div>
          <label><span class="sr" hidden>Sort</span><select id="vsort" aria-label="Sort by">
            <option value="newest">Newest first</option><option value="views">Most views</option><option value="today">Most views today</option>
            <option value="start">Fastest 24-hour start</option><option value="usual">Best against your usual</option></select></label>
          <label class="toggle"><input type="checkbox" id="vremoved"> Show removed videos</label>
        </div><div class="grid-cards" id="vgrid"></div>`;
      el.dataset.ready = "1";
      $("#vq").addEventListener("input", (e) => { vf.q = e.target.value.toLowerCase(); videoGrid(); });
      $("#vsort").addEventListener("change", (e) => { vf.sort = e.target.value; videoGrid(); });
      $("#vremoved").addEventListener("change", (e) => { vf.removed = e.target.checked; videoGrid(); });
      $("#vapp").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; vf.app = b.dataset.app; videoGrid(); });
    }
    $("#vsort").value = vf.sort;
    videoGrid();
  }
  function videoGrid() {
    const apps = ["all"].concat(PLATS.filter((pl) => D.posts.some((p) => p.platform === pl)));
    $("#vapp").innerHTML = apps.map((a) => `<button type="button" data-app="${a}" aria-pressed="${vf.app === a}">${a === "all" ? "All apps" : APPS[a].short}</button>`).join("");
    let rows = D.posts.filter((p) => (vf.removed || p.status === "live") && (vf.app === "all" || p.platform === vf.app) &&
      (!vf.q || (p.title || "").toLowerCase().includes(vf.q)));
    const key = { newest: (p) => T(p.posted), views: (p) => p.metrics.views || 0, today: (p) => p.gain_24h || 0,
      start: (p) => (p.curve && p.curve["24"]) || -1, usual: (p) => (p.vs_usual ? p.vs_usual.ratio : -1) }[vf.sort];
    rows = rows.slice().sort((a, b) => key(b) - key(a));
    $("#vgrid").innerHTML = rows.map(card).join("") || '<p class="empty-note">No videos match that.</p>';
    $("#vgrid").querySelectorAll("[data-video]").forEach((c) => c.addEventListener("click", (e) => { e.preventDefault(); location.hash = "video=" + encodeURIComponent(c.dataset.video); }));
  }

  // ------------------------------------------------------------ one video
  function openVideo(id) {
    const p = D && D.posts.find((x) => x.id === id);
    if (!p) return;
    const m = p.metrics || {}, a = APPS[p.platform];
    const metrics = [["Views", full(m.views)], ["Today", p.gain_24h !== null && p.gain_24h !== undefined ? signed(p.gain_24h) : "—"],
      ["Likes", full(m.likes)], ["Comments", full(m.comments)], ["Shares", m.shares !== undefined ? full(m.shares) : null],
      ["Saves", m.saves !== undefined ? full(m.saves) : null], ["Engagement", p.engagement !== null ? pct(p.engagement) : null],
      ["Average watch", m.avg_view_s !== undefined ? m.avg_view_s.toFixed(1) + " s" : null],
      ["Watched on average", m.avg_pct !== undefined ? pct(m.avg_pct, 0) : null],
      ["Subscribers gained", m.subs_gained !== undefined ? full(m.subs_gained) : null], ["Reach", m.reach !== undefined ? full(m.reach) : null],
      ["Full watches", m.full_watch_pct !== undefined ? pct(m.full_watch_pct) : null]].filter((x) => x[1] !== null);
    const copies = p.video ? D.posts.filter((x) => x.video === p.video && x.id !== p.id) : [];
    const usualNote = p.vs_usual ? `${p.vs_usual.ratio.toFixed(1)}× your usual at ${p.vs_usual.hours} hours (the middle of ${p.vs_usual.n} other ${a.short} posts).`
      : `"Your usual" appears once there are 3 other ${a.short} posts to compare with.`;
    $("#vd").innerHTML = `<button class="close" type="button" aria-label="Close">×</button>
      <div class="vd-top"><div class="thumb">${thumbImg(p)}</div>
        <div><h2 id="vd-title">${esc(clean(p.title))}</h2>
          <p class="meta">${badge(p.platform)} Posted ${esc(dateTime(p.posted))}${p.duration_s ? `, ${Math.round(p.duration_s)} seconds long` : ""}${p.video ? `. Clip ${esc(p.video)}${p.format ? ", " + esc(p.format) : ""}` : ""}.</p>
          <p class="meta">${esc(usualNote)}</p>
          <p style="margin-top:12px">${p.url ? `<a class="btn" href="${esc(p.url)}" target="_blank" rel="noopener">Watch on ${esc(a.short)}</a>` : ""}</p></div></div>
      <div class="metric-grid">${metrics.map((x) => `<div class="metric"><div class="v">${x[1]}</div><div class="k">${x[0]}</div></div>`).join("")}</div>
      <div><div class="section-head"><h3>Views by hours since posting</h3><div class="legend"><span><i style="background:${a.color}"></i>This video</span>${Object.keys(p.usual || {}).length ? '<span><i style="background:#8FB3B0"></i>Your usual</span>' : ""}</div></div><div id="vd-chart"></div></div>
      ${copies.length ? `<div><h3>The same clip on other apps</h3><div class="copies">${copies.map((c) => `<a class="btn ghost" href="#video=${encodeURIComponent(c.id)}">${APPS[c.platform].short}: ${full(c.metrics.views)} views</a>`).join("")}</div></div>` : ""}
      ${p.source === "typed" ? '<p class="muted small">These numbers were typed in by hand, so they show one moment rather than a live count.</p>' : ""}`;
    const dlg = $("#video-dialog");
    if (!dlg.open) dlg.showModal();
    $("#vd .close").onclick = () => dlg.close();
    const t0 = T(p.posted);
    const raw = (p.history || []).map((h) => [(T(h[0]) - t0) / 36e5, h[1]]);
    const pts = (raw.length && raw[0][0] <= 3 ? [[0, 0]] : []).concat(raw);
    const u = Object.entries(p.usual || {}).map(([h, v]) => [+h, v.median]).sort((a1, b1) => a1[0] - b1[0]);
    const band = Object.entries(p.usual || {}).filter(([, v]) => v.lo !== undefined).map(([h, v]) => [+h, v.lo, v.hi]).sort((a1, b1) => a1[0] - b1[0]);
    const maxH = Math.max(48, ...pts.map((x) => x[0]));
    const series = [{ name: "This video", color: a.color, data: pts, dots: pts.length < 12, endLabel: full(m.views) }];
    if (u.length) series.push({ name: "Your usual", color: "#8FB3B0", data: [[0, 0]].concat(u.filter((x) => x[0] <= maxH)), dash: "6 5", endDot: false });
    requestAnimationFrame(() => C.line($("#vd-chart"), { series, x: "num", height: 250, xMin: 0, xMax: Math.min(maxH, 24 * 30),
      xTicks: [0, 6, 12, 24, 48, 72, 168, 336, 720].filter((h) => h <= maxH), xFmt: (h) => h < 72 ? `${h} h` : `${Math.round(h / 24)} d`,
      xTip: (h) => `${h < 48 ? h.toFixed(1) + " hours" : (h / 24).toFixed(1) + " days"} after posting`,
      band: band.length ? { data: band.filter((x) => x[0] <= maxH), color: "#8FB3B0" } : null, label: "Views by hours since posting" }));
  }
  $("#video-dialog").addEventListener("close", () => { if (location.hash.startsWith("#video=")) history.replaceState(null, "", "#" + (page || "videos")); });
  $("#video-dialog").addEventListener("click", (e) => { if (e.target.id === "video-dialog") e.target.close(); });

  // ------------------------------------------------------------ analytics
  function analytics() {
    const el = $("#page-analytics"), s = D.summary.platforms;
    const apps = PLATS.filter((pl) => s[pl] && s[pl].posts && !s[pl].typed);
    el.innerHTML = `<div class="section-head"><div><h2>Analytics</h2><p>Each app on its own scale, because each counts views differently.</p></div>
      <div class="range" role="group" aria-label="Time range">${[[7, "7 days"], [30, "30 days"], [90, "90 days"], [3650, "Everything"]].map(([d, l]) => `<button type="button" data-d="${d}" aria-pressed="${range === d}">${l}</button>`).join("")}</div></div>
      <article class="panel"><h3>Views gained each day</h3><p class="small muted">Grey dashes mark days without a full set of readings.</p><div id="an-daily"></div></article>
      <div class="multi">${apps.map((pl) => `<article class="panel"><h3>${APPS[pl].name}: total views</h3><div id="an-tot-${pl}"></div></article>`).join("")}
        ${Object.keys(D.followers || {}).filter((pl) => (D.followers[pl] || []).length > 1).map((pl) => `<article class="panel"><h3>${APPS[pl].name}: ${APPS[pl].follow}</h3><div id="an-f-${pl}"></div></article>`).join("")}</div>
      <article class="panel"><div class="section-head"><div><h3>The race: every post's first days</h3><p class="small muted">Views by hours since posting, so new and old posts compare fairly.</p></div>
        <label class="toggle"><input type="checkbox" id="an-log" ${logScale ? "checked" : ""}> Log scale</label></div><div id="an-race"></div><div class="legend" id="an-race-leg"></div></article>
      <article class="panel"><h3>App by app</h3><div class="table-wrap"><table><thead><tr><th>App</th><th class="r">Live posts</th><th class="r">Total views</th><th class="r">Views per post</th><th class="r">Middle 24-hour views</th><th class="r">Engagement</th><th class="r">Followers</th></tr></thead>
        <tbody>${PLATS.filter((pl) => s[pl] && s[pl].posts).map((pl) => tableRow(pl)).join("")}</tbody></table></div>
        <p class="small muted" style="margin-top:10px">Engagement is likes, comments and shares (plus saves on Reels) divided by views. YouTube doesn't make shares public, so Shorts look lower unless YouTube Analytics is connected.</p></article>
      <article class="panel"><h3>When we post</h3><p class="small muted">Each square is a day; brighter means more uploads. The last 12 weeks.</p><div class="cal" id="an-cal"></div></article>`;
    el.querySelector(".range").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; range = +b.dataset.d; analytics(); };
    $("#an-log").onchange = (e) => { logScale = e.target.checked; race(); };
    const cutoff = Date.now() - range * 864e5;
    const days = [...new Set(apps.flatMap((pl) => (s[pl].daily || []).map((d) => d[0])))].sort().filter((d) => T(d) >= cutoff - 864e5);
    C.bars($("#an-daily"), { categories: days, series: apps.map((pl) => { const m = Object.fromEntries(s[pl].daily || []); return { name: APPS[pl].name, color: APPS[pl].color, values: days.map((d) => m[d] ?? null) }; }),
      catFmt: (d) => new Date(d).toLocaleDateString("en-GB", { day: "numeric", month: "short" }), catTip: (d) => dayName(d), label: "Views gained each day" });
    apps.forEach((pl) => C.line($(`#an-tot-${pl}`), { series: [{ name: APPS[pl].name, color: APPS[pl].color, area: true, data: (D.series[pl] || []).map((p) => [T(p[0]), p[1]]).filter((p) => p[0] >= cutoff) }], height: 220, label: `${APPS[pl].name} total views` }));
    Object.keys(D.followers || {}).forEach((pl) => { const h = $(`#an-f-${pl}`); if (h) C.line(h, { series: [{ name: APPS[pl].name, color: APPS[pl].color, data: D.followers[pl].map((p) => [T(p[0]), p[1]]).filter((p) => p[0] >= cutoff), dots: true }], height: 220, yMin: undefined, label: `${APPS[pl].name} ${APPS[pl].follow}` }); });
    race();
    calendar();
  }
  function tableRow(pl) {
    const s = D.summary.platforms[pl], a = APPS[pl];
    const day1 = live().filter((p) => p.platform === pl && p.curve && p.curve["24"] !== undefined).map((p) => p.curve["24"]).sort((x, y) => x - y);
    const med = day1.length ? day1[Math.floor((day1.length - 1) / 2)] : null;
    return `<tr><td>${badge(pl, a.name)}</td><td class="r">${full(s.posts)}</td><td class="r">${full(s.total_views)}</td>
      <td class="r">${s.posts ? full(s.total_views / s.posts) : "—"}</td><td class="r">${med === null ? "—" : full(med) + ` <span class="muted small">(${day1.length})</span>`}</td>
      <td class="r">${pct(s.engagement)}</td><td class="r">${full(s.followers)}</td></tr>`;
  }
  function race() {
    const posts = live().filter((p) => (p.history || []).length && p.source !== "typed");
    const series = posts.map((p, i) => {
      const t0 = T(p.posted);
      const pts = p.history.map((h) => [(T(h[0]) - t0) / 36e5, h[1]]).filter((x) => x[0] <= 168);
      const anchor = pts.length && pts[0][0] <= 3 ? [[0, logScale ? 1 : 0]] : [];   // no made-up line from 0 when tracking began late
      return { name: clean(p.title).slice(0, 40), color: APPS[p.platform].color, width: 2, data: anchor.concat(pts), endDot: true, dots: !anchor.length && pts.length < 4 };
    });
    C.line($("#an-race"), { series, x: "num", height: 300, xMin: 0, xMax: 168, xTicks: [0, 12, 24, 48, 72, 120, 168],
      xFmt: (h) => h < 72 ? `${h} h` : `${h / 24} d`, xTip: (h) => `${h.toFixed(1)} hours after posting`, logY: logScale, label: "Views by hours since posting for every post", empty: "The race starts once a post has a few readings." });
    $("#an-race-leg").innerHTML = PLATS.filter((pl) => posts.some((p) => p.platform === pl)).map((pl) => `<span><i style="background:${APPS[pl].color}"></i>${APPS[pl].name}</span>`).join("");
  }
  function calendar() {
    const counts = {};
    D.posts.forEach((p) => { const d = new Date(p.posted).toISOString().slice(0, 10); counts[d] = (counts[d] || 0) + 1; });
    const end = new Date(); end.setHours(0, 0, 0, 0);
    const start = new Date(end); start.setDate(start.getDate() - 83 - ((start.getDay() + 6) % 7));
    let html = "";
    for (let d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) {
      const k = d.toISOString().slice(0, 10), n = counts[k] || 0;
      html += `<i class="${n >= 3 ? "l3" : n === 2 ? "l2" : n === 1 ? "l1" : ""}" title="${esc(dayName(k))}: ${n} upload${n === 1 ? "" : "s"}"></i>`;
    }
    $("#an-cal").innerHTML = html;
  }

  // ------------------------------------------------------------ research
  function researchPage() {
    const r = D.research || {}, sc = r.scan || {};
    const el = $("#page-research");
    const TAGN = { "OFFICIAL": ["Platform says", ""], "CASE STUDY": ["Case study", "case"], "MYTH": ["Myth check", "myth"],
      "OBSERVED ELSEWHERE": ["Seen in other devs' Shorts", ""], "OBSERVED IN ACCOUNT": ["From our numbers", ""], "METHOD": ["Method", ""] };
    el.innerHTML = `<div><h2>What's working for other Roblox devs</h2>
        <p class="lead-sub">${sc.scanned ? `The fastest-growing of ${full(sc.scanned)} Roblox dev Shorts from the last ${sc.days} days, found by searching YouTube each day and ranked by views per day.` : "The daily YouTube scan hasn't run yet."}</p></div>
      ${(sc.stats || []).length ? `<div class="tiles">${sc.stats.map((t) => `<div class="tile"><div class="v">${esc(t.value)}</div><div class="k">${esc(t.label)}</div><div class="d">${esc(t.detail)}</div></div>`).join("")}</div>` : ""}
      <article class="panel"><div class="section-head"><h3>Fastest-growing this week</h3><p class="small">Patterns, not proof: use them as ideas to test.</p></div>
        <div class="scan-list">${(sc.top || []).map((v) => `<a class="scan-item" href="${esc(v.url)}" target="_blank" rel="noopener">
          <div class="thumb"><img src="${esc(v.thumb)}" alt="" loading="lazy" referrerpolicy="no-referrer"></div>
          <div><div class="t">${esc(clean(v.title))}${v.new ? '<span class="new">New</span>' : ""}</div><div class="c">${esc(v.channel)}, ${v.duration_s} seconds, ${full(v.views)} views</div></div>
          <div class="pd">${short(v.per_day)}<small>views a day</small></div></a>`).join("") || '<p class="empty-note">Nothing found yet.</p>'}</div></article>
      ${(sc.pirate || []).length ? `<article class="panel"><h3>Pirates and the sea</h3><p class="small muted">Recent Shorts in the scan with ships, sea or pirates in the title.</p><div class="scan-list">${sc.pirate.map((v) => `<a class="scan-item" href="${esc(v.url)}" target="_blank" rel="noopener"><div class="thumb"><img src="https://i.ytimg.com/vi/${esc(v.id)}/hqdefault.jpg" alt="" loading="lazy"></div><div><div class="t">${esc(clean(v.title))}</div><div class="c">${esc(v.channel)}, ${full(v.views)} views</div></div><div class="pd">${short(v.per_day)}<small>views a day</small></div></a>`).join("")}</div></article>` : ""}
      <div><div class="section-head"><div><h2>The bounty board</h2><p>Tests worth running next, each tied to evidence.</p></div></div>
        <div class="bounty">${(r.experiments || []).map((x) => `<article class="poster"><span class="tag">${esc((TAGN[x.tag] || [x.tag])[0])}</span><h3>${esc(x.title)}</h3>
          <p class="why">${esc(x.evidence)}</p><dl><dt>Try</dt><dd>${esc(x.test)}</dd><dt>Measure</dt><dd>${esc(x.measure)}</dd></dl></article>`).join("")}</div></div>
      <div><div class="section-head"><div><h2>Field guide</h2><p>What the platforms and other developers have actually said, with how strong the evidence is.</p></div></div>
        <div class="guide">${(r.guide || []).map((g) => { const t = TAGN[g.tag] || [g.tag, ""]; return `<details><summary>${esc(g.title)}<span class="tag ${t[1]}">${esc(t[0])}</span></summary>
          <div class="g-body"><p>${esc(g.text)}</p><p class="do"><b>For PIRACY:</b> ${esc(g.do)}</p><p class="small muted">${g.url ? `<a href="${esc(g.url)}" target="_blank" rel="noopener">${esc(g.source)}</a>` : esc(g.source)}, checked ${esc(g.checked)}</p></div></details>`; }).join("")}</div></div>`;
  }

  // ------------------------------------------------------------ Roblox trends (from the trend bot)
  function trends() {
    const t = (D.research || {}).trends || {}, rows = t.rows || [];
    const max = Math.max(1, ...rows.map((r) => r.score || 0));
    $("#page-trends").innerHTML = `<div class="section-head"><div><h2>Roblox right now</h2>
        <p>The trend bot's live board${t.fetched ? `, read ${esc(ago(t.fetched))}` : ""}. Games with a sea or pirate theme are flagged.</p></div>
        ${t.site ? `<a class="btn ghost" href="${esc(t.site)}" target="_blank" rel="noopener">Open the full trend dashboard</a>` : ""}</div>
      ${rows.length ? `<article class="panel"><div class="table-wrap"><table><thead><tr><th>Game</th><th class="r">Players</th><th>Trend score</th><th class="r">vs last week</th><th>Why it's on the board</th></tr></thead><tbody>
        ${rows.slice(0, 25).map((r) => `<tr><td>${r.url ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.name)}</a>` : esc(r.name)}${r.sea ? '<span class="sea-flag">Sea theme</span>' : ""}</td>
          <td class="r">${full(r.players)}</td><td><span class="score-bar" style="width:${Math.round(((r.score || 0) / max) * 90)}px"></span>${r.score ?? "—"}</td>
          <td class="r">${r.growth ? "×" + r.growth.toFixed(1) : "—"}</td><td class="reason">${esc(r.reasons)}</td></tr>`).join("")}</tbody></table></div></article>`
        : '<p class="empty-note">The trend bot\'s board couldn\'t be read this time.</p>'}`;
  }

  // ------------------------------------------------------------ status + connecting apps
  function statusPage() {
    const c = D.connect || {};
    const redirect = c.redirect || "";
    const repo = c.repo || D.repo || "";
    const secrets = repo ? `${repo}/settings/secrets/actions` : "#";
    const ttUrl = c.tiktok_client_key ? `https://www.tiktok.com/v2/auth/authorize/?client_key=${encodeURIComponent(c.tiktok_client_key)}&scope=${encodeURIComponent("user.info.basic,user.info.stats,video.list")}&response_type=code&redirect_uri=${encodeURIComponent(redirect)}&state=tiktok` : null;
    const gUrl = c.google_client_id ? `https://accounts.google.com/o/oauth2/v2/auth?client_id=${encodeURIComponent(c.google_client_id)}&redirect_uri=${encodeURIComponent(redirect)}&response_type=code&access_type=offline&prompt=consent&scope=${encodeURIComponent("https://www.googleapis.com/auth/yt-analytics.readonly https://www.googleapis.com/auth/youtube.readonly")}&state=google` : null;
    const cardFor = (key, title, icon, steps, btn) => {
      const s = D.status[key] || { status: "not_connected" };
      const vault = s.vault || {};
      const exp = (s.account && s.account.token_expires) || vault.refresh_expires_at || vault.expires;
      return `<article class="status-card"><h3>${icon}${esc(title)} ${chipFor(s.status)}</h3>
        <p class="msg">${esc(s.message || "")}</p>
        ${s.last_ok ? `<p class="small muted">Last good reading ${esc(ago(s.last_ok))}.</p>` : ""}
        ${exp ? `<p class="small muted">Sign-in renews itself; it can't lapse before ${esc(dayName(exp))} even if runs stop.</p>` : ""}
        ${steps ? `<details ${s.status === "ok" ? "" : "open"}><summary>${s.status === "ok" ? "How this was connected" : "How to connect it"}</summary><ol>${steps.map((x) => `<li>${x}</li>`).join("")}</ol></details>` : ""}
        ${btn || ""}</article>`;
    };
    const ic = (pl) => `<span class="app-badge" style="background:${APPS[pl].color};color:#0B1F27;width:30px;height:30px">${APPS[pl].icon}</span>`;
    const code = (t) => `<code style="background:#0A1B22;padding:1px 6px;border-radius:5px">${esc(t)}</code>`;
    const runs = (D.runs || []).map((r) => {
      const v = Object.values(r.statuses || {});
      const cls = r.ok === false ? "bad" : v.includes("error") || v.includes("stale") ? "meh" : "";
      return `<i class="${cls}" title="${esc(dateTime(r.ts))}: ${r.ok === false ? "something failed" : "all good"}"></i>`;
    }).join("");
    $("#page-status").innerHTML = `<div><h2>Status</h2><p class="lead-sub">Which apps are connected and updating. The bot runs every hour; if an app stops answering, its last good numbers stay up and Discord gets a heads-up after three misses in a row.</p></div>
      <div class="status-grid">
        ${cardFor("youtube", "YouTube Shorts", ic("youtube"), null)}
        ${cardFor("youtube_analytics", "YouTube Analytics", ic("youtube"), [
          `In <a href="https://console.cloud.google.com/apis/library/youtubeanalytics.googleapis.com" target="_blank" rel="noopener">Google Cloud</a> (the same project as your YouTube key), turn on the <b>YouTube Analytics API</b>.`,
          `On the <b>OAuth consent screen</b>, choose External, add your email as a test user, then press <b>Publish app</b>. Without publishing, Google signs the bot out every 7 days.`,
          `Under <b>Credentials</b>, create an <b>OAuth client ID</b> of type Web application. Add this as an authorised redirect URI: ${code(redirect)}`,
          `Add its two values as <a href="${esc(secrets)}" target="_blank" rel="noopener">GitHub secrets</a> named ${code("GOOGLE_CLIENT_ID")} and ${code("GOOGLE_CLIENT_SECRET")}.`,
          `After the next hourly run, press <b>Connect YouTube Analytics</b> here and sign in with the channel's Google account. Google will say it hasn't verified the app: it's your own, so choose Advanced, then continue.`],
          gUrl ? `<a class="btn" href="${esc(gUrl)}">Connect YouTube Analytics</a>` : "")}
        ${cardFor("tiktok", "TikTok", ic("tiktok"), [
          `At <a href="https://developers.tiktok.com/apps" target="_blank" rel="noopener">TikTok for Developers</a>, sign in and connect an app (an individual developer account is fine).`,
          `Switch it to <b>Sandbox</b> and create a sandbox. Add <b>Login Kit</b> with the scopes ${code("user.info.basic")}, ${code("user.info.stats")} and ${code("video.list")}, and this redirect URI: ${code(redirect)}`,
          `Under <b>Target users</b>, add the PIRACY TikTok account.`,
          `Add the app's <b>Client key</b> and <b>Client secret</b> as <a href="${esc(secrets)}" target="_blank" rel="noopener">GitHub secrets</a> named ${code("TIKTOK_CLIENT_KEY")} and ${code("TIKTOK_CLIENT_SECRET")}.`,
          `After the next hourly run, press <b>Connect TikTok</b> here, sign in as PIRACY and follow the page you land on.`],
          ttUrl ? `<a class="btn" href="${esc(ttUrl)}">Connect TikTok</a>` : "")}
        ${cardFor("instagram", "Instagram Reels", ic("instagram"), [
          `In the Instagram app: Settings, then <b>Account type and tools</b>, then switch PIRACY to a <b>Creator</b> account (free; you keep your posts and music).`,
          `At <a href="https://developers.facebook.com/apps" target="_blank" rel="noopener">Meta for Developers</a>, create an app with the Instagram use case. Under <b>API setup with Instagram login</b>, add the PIRACY account and generate an access token.`,
          `Add it as a <a href="${esc(secrets)}" target="_blank" rel="noopener">GitHub secret</a> named ${code("INSTAGRAM_TOKEN")}. The bot renews it every week by itself after that.`])}
        ${cardFor("discord", "Discord", ic("discord"), null)}
      </div>
      <article class="panel"><h3>${(D.runs || []).length ? `The last ${(D.runs || []).length} runs` : "Runs"}</h3>${(D.runs || []).length ? "" : '<p class="muted">No runs logged yet.</p>'}<p class="small muted">Green is all good, amber means an app didn't answer, red means something failed.</p><div class="runs" style="margin-top:12px">${runs}</div></article>
      <article class="panel"><h3>Good to know</h3><ul class="small" style="margin:8px 0 0;padding-left:20px;display:grid;gap:6px;color:#CFE0DD">
        <li>Each app counts views its own way, so this site never adds them together.</li>
        <li>A missing number stays blank. It's never filled in as zero.</li>
        <li>YouTube rounds public subscriber counts for larger channels.</li>
        <li>Numbers typed in by hand show one moment, not a live count. Connecting the app replaces them.</li>
        <li>Comparisons switch on gradually: "your usual" after 3 posts on an app, format comparisons after 5 of each.</li></ul></article>`;
  }

  // ------------------------------------------------------------ start
  window.addEventListener("hashchange", route);
  let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => D && renderPage(page), 250); });
  route();
  load(true);
  setInterval(() => load(false), 5 * 60 * 1000);
  setInterval(freshness, 30 * 1000);
})();
