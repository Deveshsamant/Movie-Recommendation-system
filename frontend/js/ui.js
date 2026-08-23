/* Shared DOM helpers and the Modernist building blocks. */

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

/* Theme-aware colours.
   These go into inline styles and SVG paint attributes, both of which accept
   var(), so they follow the active theme without any re-render. Canvas cannot
   take var() — scenes.js resolves real values through cssVar(). */
export const RED = "var(--color-accent)";
export const INK = "var(--color-text)";
export const MID = "var(--color-neutral-500)";
export const PAPER = "var(--color-bg)";

export const cssVar = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

export const fmt = {
  n: (v, d = 3) => (v === null || v === undefined || Number.isNaN(v) ? "—" : Number(v).toFixed(d)),
  int: (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString()),
  pct: (v, d = 1) => (v === null || v === undefined ? "—" : `${Number(v).toFixed(d)}%`),
  signed: (v, d = 3) => `${Number(v) >= 0 ? "+" : "−"}${Math.abs(Number(v)).toFixed(d)}`,
  clamp: (v) => `${Math.max(0, Math.min(100, v))}%`,
};

export const ICON = {
  play: '<svg class="icon icon--fill" viewBox="0 0 24 24"><polygon points="6 3 20 12 6 21 6 3"/></svg>',
  pause: '<svg class="icon" viewBox="0 0 24 24"><rect x="14" y="4" width="4" height="16"/><rect x="6" y="4" width="4" height="16"/></svg>',
  info: '<svg class="icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>',
  left: '<svg class="icon" viewBox="0 0 24 24"><path d="m15 18-6-6 6-6"/></svg>',
  right: '<svg class="icon" viewBox="0 0 24 24"><path d="m9 18 6-6-6-6"/></svg>',
  arrowL: '<svg class="icon" viewBox="0 0 24 24"><path d="m12 19-7-7 7-7"/><path d="M19 12H5"/></svg>',
  arrowR: '<svg class="icon" viewBox="0 0 24 24"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>',
  close: '<svg class="icon" viewBox="0 0 24 24"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>',
  replay: '<svg class="icon" viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>',
  spark: '<svg class="icon" viewBox="0 0 24 24"><path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z"/></svg>',
};

let toastTimer;
export function toast(message) {
  const node = $("#toast");
  node.textContent = message;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, 2400);
}

/** Poster block: the artwork in full colour, nothing laid over it.
    Titles live underneath so the image is never dimmed or covered. */
export function poster(movie, cls = "film__art") {
  const img = movie.poster
    ? `<img src="${esc(movie.poster)}" alt="${esc(movie.title)}" loading="lazy"
         onerror="this.closest('.${cls}').innerHTML='<span class=\\'ph\\'>${esc(movie.title).replace(/'/g, "")}</span>'" />`
    : `<span class="ph">${esc(movie.title)}</span>`;
  return `<div class="${cls}">${img}</div>`;
}

/** Title + genre line, for use under a poster. */
export const caption = (movie) => `
  <div class="film__t">${esc(movie.title)}</div>
  <div class="film__g">${movie.year || "—"} · ${esc((movie.genres || []).slice(0, 2).join(" · "))}</div>`;

/**
 * One catalogue tile. `badge`/`meter` are score-derived and hide with the toggle.
 */
export function filmCard(movie, opts = {}) {
  const { rank, badge, tone = "accent", why, meter, onClick, ink } = opts;
  const node = el(`
    <article class="film ${ink ? "film--ink" : ""}" tabindex="0">
      ${rank ? `<span class="film__rank">${rank}</span>` : ""}
      ${badge ? `<span class="film__badge film__badge--${tone} score-only">${esc(badge)}</span>` : ""}
      ${poster(movie)}
      <div class="film__body">
        ${caption(movie)}
        ${why ? `<div class="score-only" style="margin-top:9px">
            <div class="film__why">${why}</div>
            <div class="film__meter"><i class="bar-grow" style="width:${fmt.clamp(meter ?? 0)};
              background:${tone === "ink" ? INK : RED}"></i></div>
          </div>` : ""}
        <div class="film__foot">★ ${fmt.n(movie.avg_rating, 1)} ·
          ${fmt.int(movie.n_ratings)} ratings</div>
      </div>
    </article>`);
  if (onClick) {
    node.addEventListener("click", () => onClick(movie));
    node.addEventListener("keydown", (e) => { if (e.key === "Enter") onClick(movie); });
  }
  return node;
}

export function filmGrid(movies, opts = {}) {
  const grid = el('<div class="films"></div>');
  movies.forEach((m, i) => grid.append(filmCard(m, { ...opts, rank: opts.ranked ? i + 1 : null,
    badge: opts.badgeOf ? opts.badgeOf(m) : null,
    why: opts.whyOf ? opts.whyOf(m) : null,
    meter: opts.meterOf ? opts.meterOf(m) : null })));
  return grid;
}

export function emptyState(title, body, actionLabel, onAction) {
  const node = el(`
    <div class="empty">
      <h3>${esc(title)}</h3>
      <p>${esc(body)}</p>
      ${actionLabel ? `<button class="btn btn--primary">${esc(actionLabel)}</button>` : ""}
    </div>`);
  if (onAction) $("button", node)?.addEventListener("click", onAction);
  return node;
}

export const loading = (label = "Working…") =>
  el(`<div class="loading"><span class="spin"></span> ${esc(label)}</div>`);

/* ── maths rows ───────────────────────────────────────────── */
export function mathRow({ label, meta, kind, math, pct, color = RED, delay = 0 }) {
  return `
    <div class="mrow" style="animation-delay:${delay}s">
      <span class="mrow__l">
        <b>${esc(label)}</b>
        ${meta ? `<small>${esc(meta)}</small>` : ""}
      </span>
      ${kind ? `<span class="mrow__k">${esc(kind)}</span>` : ""}
      <span class="mrow__bar"><i style="width:${fmt.clamp(pct)};background:${color};
        animation-delay:${delay}s"></i></span>
      <span class="mrow__v">${math}</span>
    </div>`;
}

export const mathTotal = (label, value, color = RED) => `
  <div class="mtotal"><span>${esc(label)}</span><b style="color:${color}">${value}</b></div>`;

/* ── charts (hand-rolled SVG) ─────────────────────────────── */
export function radar(rows, size = 260) {
  if (!rows.length) return "";
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 46;
  const n = rows.length;
  const pt = (i, sc) => {
    const a = (Math.PI * 2 * i) / n - Math.PI / 2;
    return [cx + Math.cos(a) * r * sc, cy + Math.sin(a) * r * sc];
  };
  const web = "var(--color-neutral-300)";
  const rings = [0.25, 0.5, 0.75, 1]
    .map((sc) => `<polygon points="${rows.map((_, j) => pt(j, sc).map((v) => v.toFixed(1)).join(",")).join(" ")}"
      fill="none" stroke="${web}" stroke-width="1"></polygon>`)
    .join("");
  const spokes = rows
    .map((_, i) => {
      const [x2, y2] = pt(i, 1);
      return `<line x1="${cx}" y1="${cy}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"
        stroke="${web}" stroke-width="1"></line>`;
    })
    .join("");
  const shape = rows
    .map((g, i) => pt(i, Math.max(0.08, (g.avg - 1) / 4)).map((v) => v.toFixed(1)).join(","))
    .join(" ");
  const labels = rows
    .map((g, i) => {
      const [x, y] = pt(i, 1.24);
      return `<text x="${x.toFixed(1)}" y="${y.toFixed(1)}" text-anchor="middle"
        dominant-baseline="middle" font-size="9.5" font-weight="700"
        fill="var(--color-neutral-600)" letter-spacing="0.06em">${esc(g.genre.slice(0, 10).toUpperCase())}</text>`;
    })
    .join("");
  return `<svg viewBox="0 0 ${size} ${size}" role="img" aria-label="Genre affinity radar"
    style="width:100%;max-width:300px;height:auto;display:block;margin-top:14px">
    ${rings}${spokes}
    <polygon points="${shape}" fill="color-mix(in srgb,var(--color-accent) 22%,transparent)" stroke="${RED}" stroke-width="2"></polygon>
    ${labels}
  </svg>`;
}

/** Animated convergence line for SGD training. */
export function convergence(values) {
  if (!values?.length) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values
    .map((v, i) => `${(16 + (i / (values.length - 1)) * 308).toFixed(1)},${(108 - ((v - min) / span) * 88).toFixed(1)}`)
    .join(" ");
  return `<svg viewBox="0 0 340 130" role="img" aria-label="Training convergence"
    style="width:100%;height:auto;display:block;margin-top:12px">
    <line x1="16" y1="108" x2="324" y2="108" stroke="${INK}" stroke-width="2"></line>
    <polyline points="${pts}" fill="none" stroke="${RED}" stroke-width="2.5"
      stroke-dasharray="900" stroke-dashoffset="900">
      <animate attributeName="stroke-dashoffset" from="900" to="0" dur="1.6s" fill="freeze"></animate>
    </polyline>
    <text x="16" y="14" font-size="9.5" font-weight="700" fill="var(--color-neutral-600)"
      letter-spacing="0.08em">RMSE ${max.toFixed(3)} → ${min.toFixed(3)}</text>
    <text x="324" y="124" text-anchor="end" font-size="9" font-weight="700"
      fill="var(--color-neutral-500)" letter-spacing="0.08em">${values.length} EPOCHS</text>
  </svg>`;
}

/** Alluvial: content candidates left, collaborative right, flowing into the blend. */
export function sankey(rows) {
  if (!rows.length) return "";
  const body = rows
    .map((f, i) => {
      const y = 40 + i * 21;
      const mid = y + 6.5;
      const total = f.blend || 1;
      const cShare = f.content_part / total;
      const fShare = f.cf_part / total;
      const cW = Math.max(3, cShare * 190);
      const fW = Math.max(3, fShare * 190);
      return `<g>
        <rect x="${(200 - cW).toFixed(1)}" y="${y}" width="${cW.toFixed(1)}" height="13"
          fill="${RED}" opacity="0.85"></rect>
        <rect x="700" y="${y}" width="${fW.toFixed(1)}" height="13" fill="${INK}" opacity="0.85"></rect>
        <path d="M200 ${mid} C 320 ${mid}, 340 ${mid}, 430 ${mid}" stroke="${RED}"
          stroke-width="${Math.max(1.2, cShare * 13).toFixed(2)}" fill="none" opacity="0.42"></path>
        <path d="M700 ${mid} C 600 ${mid}, 560 ${mid}, 470 ${mid}" stroke="${INK}"
          stroke-width="${Math.max(1.2, fShare * 13).toFixed(2)}" fill="none" opacity="0.42"></path>
        <rect x="430" y="${y}" width="40" height="13"
          fill="${f.cf_part > f.content_part ? INK : RED}"></rect>
        <text x="486" y="${y + 10.5}" font-size="10.5" font-weight="600"
          fill="${INK}">${esc(f.title.slice(0, 34))}</text>
      </g>`;
    })
    .join("");
  return `<svg viewBox="0 0 900 ${60 + rows.length * 21}" role="img"
    aria-label="Where the blended list comes from" style="width:100%;height:auto;display:block">
    <text x="8" y="18" font-size="10" font-weight="800" fill="var(--color-neutral-600)"
      letter-spacing="0.12em">CONTENT CANDIDATES</text>
    <text x="430" y="18" font-size="10" font-weight="800" fill="var(--color-neutral-600)"
      letter-spacing="0.12em">BLEND</text>
    <text x="700" y="18" font-size="10" font-weight="800" fill="var(--color-neutral-600)"
      letter-spacing="0.12em">COLLABORATIVE</text>
    ${body}
  </svg>`;
}

/** Parallel coordinates: one line per model across every metric, up = better. */
export function parallel(rows, hoverKey = null) {
  const axes = [
    ["RMSE", "rmse", true], ["MAE", "mae", true], ["Prec@10", "precision", false],
    ["NDCG", "ndcg", false], ["Hit rate", "hit_rate", false],
    ["Coverage", "coverage", false], ["Novelty", "novelty", false],
  ];
  const x = (i) => 60 + (i / (axes.length - 1)) * 780;
  const ranges = axes.map(([, k]) => [
    Math.min(...rows.map((r) => r[k] ?? 0)),
    Math.max(...rows.map((r) => r[k] ?? 0)),
  ]);
  const y = (v, i) => {
    const [lo, hi] = ranges[i];
    let t = ((v ?? 0) - lo) / (hi - lo || 1);
    if (axes[i][2]) t = 1 - t;   // lower is better, so invert
    return 254 - t * 208;
  };
  const famColor = (fam) =>
    fam === "hybrid" ? RED
      : fam === "content" ? "var(--color-accent-500)"
        : fam === "collaborative" ? INK : MID;

  const axisMarks = axes
    .map(([label], i) => `<g>
      <line x1="${x(i).toFixed(1)}" y1="34" x2="${x(i).toFixed(1)}" y2="254" stroke="${INK}" stroke-width="2"></line>
      <text x="${x(i).toFixed(1)}" y="274" text-anchor="middle" font-size="9.5" font-weight="800"
        fill="var(--color-neutral-600)" letter-spacing="0.09em">${label.toUpperCase()}</text>
    </g>`)
    .join("");
  const lines = rows
    .map((r, ri) => {
      const d = axes.map(([, k], i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(r[k], i).toFixed(1)}`).join(" ");
      const dim = hoverKey && hoverKey !== r.model;
      return `<path data-line="${esc(r.model)}" d="${d}" fill="none" stroke="${famColor(r.family)}"
        stroke-width="${r.family === "hybrid" ? 3 : 2}" opacity="${dim ? 0.12 : 0.9}"
        stroke-dasharray="2600" stroke-dashoffset="2600" style="transition:opacity .2s">
        <animate attributeName="stroke-dashoffset" from="2600" to="0" dur="1.1s"
          begin="${(ri * 0.09).toFixed(2)}s" fill="freeze"></animate>
      </path>`;
    })
    .join("");
  return `<svg viewBox="0 0 900 300" role="img" aria-label="Seven models across seven metrics"
    style="width:100%;height:auto;display:block">
    <text x="60" y="20" font-size="9.5" font-weight="800" fill="var(--color-neutral-600)"
      letter-spacing="0.1em">UP IS BETTER ON EVERY AXIS · RMSE AND MAE INVERTED</text>
    ${axisMarks}${lines}
  </svg>`;
}

/** Three-way overlap of viewers' top-N lists.
 *
 * Geometry note: the circles are laid out on an equilateral triangle and the
 * viewBox is sized from `cy ± r` so nothing can be clipped, with the label band
 * kept clear of both the header and the strokes. The whole thing is capped by a
 * fixed-height wrapper so it never dominates the page.
 */
export function venn(sets) {
  const R = 92;
  const A = { cx: 328, cy: 150 };
  const B = { cx: 432, cy: 150 };
  const C = { cx: 380, cy: 230 };
  const skin = [
    { fill: "color-mix(in srgb,var(--color-accent) 22%,transparent)", stroke: RED },
    { fill: "color-mix(in srgb,var(--color-text) 15%,transparent)", stroke: INK },
    { fill: "color-mix(in srgb,var(--color-accent) 11%,transparent)", stroke: MID },
  ];

  const use = sets.slice(0, 3);
  const ids = use.map((s) => new Set(s.ids));
  const only = (i) => [...ids[i]].filter((v) => ids.every((s, j) => j === i || !s.has(v))).length;
  const pair = (a, b) =>
    [...ids[a]].filter((v) => ids[b].has(v) && ids.every((s, j) => j === a || j === b || !s.has(v))).length;
  const all = ids.length === 3 ? [...ids[0]].filter((v) => ids[1].has(v) && ids[2].has(v)).length : 0;

  const three = use.length === 3;
  const pos = three ? [A, B, C] : [{ cx: 328, cy: 180 }, { cx: 432, cy: 180 }];
  // label anchors sit outside every stroke: two above, one clear below
  const anchors = three
    ? [{ x: 196, y: 92 }, { x: 564, y: 92 }, { x: 380, y: 350 }]
    : [{ x: 196, y: 122 }, { x: 564, y: 122 }];

  const circles = pos
    .map((p, i) => `<circle cx="${p.cx}" cy="${p.cy}" r="${R}" fill="${skin[i].fill}"
      stroke="${skin[i].stroke}" stroke-width="2"></circle>`)
    .join("");

  const labels = use
    .map((s, i) => `<text x="${anchors[i].x}" y="${anchors[i].y}" text-anchor="middle"
      font-size="11" font-weight="800" fill="${skin[i].stroke}"
      letter-spacing="0.1em">${esc(s.name.toUpperCase().slice(0, 15))}</text>`)
    .join("");

  const counts = three
    ? [[275, 135, only(0)], [485, 135, only(1)], [380, 285, only(2)],
       [380, 128, pair(0, 1)], [322, 212, pair(0, 2)], [438, 212, pair(1, 2)], [380, 180, all]]
    : [[278, 186, only(0)], [482, 186, only(1)], [380, 186, pair(0, 1)]];

  const nums = counts
    .map(([x, y, n]) => `<text x="${x}" y="${y}" text-anchor="middle" font-size="18"
      font-weight="800" fill="${INK}">${n}</text>`)
    .join("");

  return `<div style="height:clamp(300px,46vh,400px)">
    <svg viewBox="0 0 760 372" preserveAspectRatio="xMidYMid meet" role="img"
      aria-label="Overlap between viewers' lists" style="width:100%;height:100%;display:block">
      <text x="20" y="24" font-size="9.5" font-weight="800" fill="var(--color-neutral-600)"
        letter-spacing="0.1em">TOP LISTS · ${all} FILM${all === 1 ? "" : "S"} SHARED BY ALL</text>
      ${circles}${nums}${labels}
    </svg>
  </div>`;
}
