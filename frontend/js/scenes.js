/* Canvas 3D: the latent-factor point cloud and the kNN neighbourhood orbits.
   Hand-rolled projection — no library, so nothing has to be fetched. */

import { cssVar } from "./ui.js?v=16";

const reduced = typeof matchMedia === "function"
  && matchMedia("(prefers-reduced-motion: reduce)").matches;

/* Canvas takes no var(), so the palette is resolved from the live tokens and
   re-read whenever the theme changes. */
let pal = null;
function palette() {
  if (!pal) {
    pal = {
      red: cssVar("--color-accent") || "#ec3013",
      ink: cssVar("--color-text") || "#201e1d",
      paper: cssVar("--color-bg") || "#f3f2f2",
      web: cssVar("--color-neutral-300") || "#d7d3d3",
      faint: cssVar("--color-neutral-400") || "#bab6b6",
    };
  }
  return pal;
}
export function refreshPalette() {
  pal = null;
  palette();
  scenes.forEach((s) => { if (s.cv.isConnected) paint(s, performance.now()); });
}

const scenes = new Map();
let raf = null;

/** Rotate by (rx, ry) then apply a weak perspective divide. */
function project(p, s, scale) {
  const cy = Math.cos(s.ry);
  const sy = Math.sin(s.ry);
  const cx = Math.cos(s.rx);
  const sx = Math.sin(s.rx);
  const x1 = p.x * cy - p.z * sy;
  const z1 = p.x * sy + p.z * cy;
  const y2 = p.y * cx - z1 * sx;
  const z2 = p.y * sx + z1 * cx;
  const d = 6.2 / (6.2 + z2);
  return { x: s.w / 2 + x1 * scale * d * s.zoom, y: s.h / 2 + y2 * scale * d * s.zoom, d, z: z2 };
}

function bindPointer(s) {
  const cv = s.cv;
  cv.onpointerdown = (e) => {
    s.drag = { x: e.clientX, y: e.clientY };
    cv.setPointerCapture(e.pointerId);
    cv.style.cursor = "grabbing";
  };
  cv.onpointerup = () => { s.drag = null; cv.style.cursor = "grab"; };
  cv.onpointermove = (e) => {
    if (s.drag) {
      s.ry += (e.clientX - s.drag.x) * 0.006;
      s.rx = Math.max(-0.2, Math.min(1.3, s.rx + (e.clientY - s.drag.y) * 0.004));
      s.drag = { x: e.clientX, y: e.clientY };
    }
    const r = cv.getBoundingClientRect();
    s.mx = e.clientX - r.left;
    s.my = e.clientY - r.top;
  };
  cv.onpointerleave = () => { s.mx = null; s.drag = null; };
  cv.onwheel = (e) => {
    e.preventDefault();
    s.zoom = Math.max(0.5, Math.min(3, s.zoom * (e.deltaY > 0 ? 0.92 : 1.08)));
  };
  // two-finger pinch on touch
  let pinch = null;
  cv.ontouchstart = (e) => {
    if (e.touches.length === 2) {
      pinch = Math.hypot(e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY);
    }
  };
  cv.ontouchmove = (e) => {
    if (e.touches.length === 2 && pinch) {
      e.preventDefault();
      const d = Math.hypot(e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY);
      s.zoom = Math.max(0.5, Math.min(3, s.zoom * (d / pinch)));
      pinch = d;
    }
  };
  cv.ontouchend = () => { pinch = null; };
}

function size(s) {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const r = s.cv.getBoundingClientRect();
  s.cv.width = Math.max(1, r.width * dpr);
  s.cv.height = Math.max(1, r.height * dpr);
  s.w = r.width;
  s.h = r.height;
  s.dpr = dpr;
}

function clear(s) {
  s.ctx.setTransform(s.dpr, 0, 0, s.dpr, 0, 0);
  s.ctx.clearRect(0, 0, s.w, s.h);
}

/* ── latent factor cloud ──────────────────────────────────── */
function drawCloud(s) {
  if (!s.w) return;
  clear(s);
  const { ctx } = s;
  const P = palette();
  const mineOnly = s.filter === "mine";
  const pts = s.data.points
    .filter((p) => !mineOnly || p.mine)
    .map((p) => ({ p, q: project(p, s, 150) }))
    .sort((a, b) => b.q.z - a.q.z);

  let hover = null;
  let best = 1e9;
  pts.forEach(({ p, q }) => {
    const r = Math.max(0.7, (1.1 + p.pop * 2.6) * q.d * s.zoom);
    ctx.beginPath();
    ctx.arc(q.x, q.y, r, 0, Math.PI * 2);
    ctx.globalAlpha = p.mine ? 1 : 0.14 + q.d * 0.42;
    ctx.fillStyle = p.mine ? P.red : P.ink;
    ctx.fill();
    ctx.globalAlpha = 1;
    if (s.mx != null) {
      const d2 = (q.x - s.mx) ** 2 + (q.y - s.my) ** 2;
      if (d2 < 90 && d2 < best) { best = d2; hover = { p, q }; }
    }
  });

  // the viewer's own taste vector, drawn into the same space
  const v = s.data.user_vector;
  if (v) {
    const o = project({ x: 0, y: 0, z: 0 }, s, 150);
    const u = project(v, s, 150);
    ctx.strokeStyle = P.red;
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    ctx.moveTo(o.x, o.y);
    ctx.lineTo(u.x, u.y);
    ctx.stroke();
    ctx.fillStyle = P.red;
    ctx.beginPath();
    ctx.arc(u.x, u.y, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.font = '700 11px Archivo, sans-serif';
    ctx.fillText("pu", u.x + 9, u.y + 4);
  }

  const tip = s.tip;
  if (tip) {
    if (hover) {
      tip.style.display = "block";
      tip.style.left = `${Math.min(hover.q.x + 12, s.w - 230)}px`;
      tip.style.top = `${hover.q.y + 12}px`;
      tip.textContent = hover.p.title + (hover.p.mine ? " · you rated this" : "");
    } else {
      tip.style.display = "none";
    }
  }
}

/* ── item-kNN neighbourhood orbits ────────────────────────── */
function drawOrbit(s, t) {
  if (!s.w) return;
  clear(s);
  const { ctx } = s;
  const P = palette();
  const nb = s.data.neighbours || [];
  const c = project({ x: 0, y: 0, z: 0 }, s, 130);

  nb.forEach((n, i) => {
    const R = (1 - n.similarity) * 2.6;
    ctx.strokeStyle = P.web;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let a = 0; a <= 64; a += 1) {
      const th = (a / 64) * Math.PI * 2;
      const q = project({ x: Math.cos(th) * R, y: 0, z: Math.sin(th) * R }, s, 130);
      if (a) ctx.lineTo(q.x, q.y); else ctx.moveTo(q.x, q.y);
    }
    ctx.stroke();

    const th = (reduced ? 0 : t * 0.00016) * (1.4 - n.similarity) + (i / nb.length) * Math.PI * 2;
    const q = project({ x: Math.cos(th) * R, y: 0, z: Math.sin(th) * R }, s, 130);
    const mass = Math.abs(n.term);
    const r = Math.max(4, mass * 26 * q.d * s.zoom);

    ctx.strokeStyle = P.faint;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(c.x, c.y);
    ctx.lineTo(q.x, q.y);
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(q.x, q.y, r, 0, Math.PI * 2);
    ctx.fillStyle = n.term >= 0 ? P.red : P.faint;
    ctx.fill();

    ctx.fillStyle = P.ink;
    ctx.font = '600 10.5px Archivo, sans-serif';
    ctx.fillText(String(n.title || "").slice(0, 28), q.x + r + 6, q.y + 3.5);
  });

  ctx.fillStyle = P.ink;
  ctx.beginPath();
  ctx.arc(c.x, c.y, 15, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = P.paper;
  ctx.font = '800 10px Archivo, sans-serif';
  ctx.textAlign = "center";
  ctx.fillText("target", c.x, c.y + 3.5);
  ctx.textAlign = "left";
}

/* ── loop ─────────────────────────────────────────────────── */
function paint(s, t) {
  if (!s.cv.isConnected) return;
  if (s.kind === "cloud") drawCloud(s);
  else drawOrbit(s, t || 0);
}

function tick(t) {
  raf = requestAnimationFrame(tick);
  const spin = reduced ? 0 : 0.00013;
  scenes.forEach((s) => {
    if (!s.cv.isConnected) return;
    if (!s.drag) s.ry += spin * (s.kind === "cloud" ? 11 : 9);
    paint(s, t);
  });
}

export function mount(id, kind, data, opts = {}) {
  const cv = document.getElementById(id);
  if (!cv) return null;
  const s = {
    cv, ctx: cv.getContext("2d"), kind, data,
    rx: 0.35, ry: 0.6, zoom: 1, drag: null,
    tip: opts.tipId ? document.getElementById(opts.tipId) : null,
    filter: opts.filter || "all",
  };
  scenes.set(id, s);
  bindPointer(s);
  size(s);
  // Paint once straight away: requestAnimationFrame does not fire while the
  // page is hidden or backgrounded, and a blank box is worse than a still one.
  paint(s, performance.now());
  if (!raf) raf = requestAnimationFrame(tick);
  return s;
}

export function setFilter(id, filter) {
  const s = scenes.get(id);
  if (!s) return;
  s.filter = filter;
  paint(s, performance.now());
}

export function unmountAll() {
  scenes.clear();
  if (raf) { cancelAnimationFrame(raf); raf = null; }
}

export function resizeAll() {
  scenes.forEach((s) => {
    if (!s.cv.isConnected) return;
    size(s);
    paint(s, performance.now());
  });
}

window.addEventListener("resize", resizeAll);
