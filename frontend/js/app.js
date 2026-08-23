/* App shell: state, routing, the viewer rail and the new-viewer modal. */

import { api } from "./api.js?v=16";
import { $, $$, el, esc, fmt, ICON, toast } from "./ui.js?v=16";
import { closeDrawer } from "./drawer.js?v=16";
import { closeReel } from "./reel.js?v=16";
import * as scenes from "./scenes.js?v=16";
import * as views from "./views.js?v=16";

const state = {
  userId: 1,
  userName: "",
  view: "data",
  cfModel: "item-knn",
  strategy: "weighted",
  alpha: 0.7,
  compareMethod: "hybrid",
  comparePicks: [],
  users: { builtin: [], custom: [] },
  showScores: true,
  reelData: null,
  stopShelf: null,
};

const VIEWS = {
  browse: views.browse,
  data: views.data,
  rate: views.rate,
  content: views.content,
  collab: views.collab,
  hybrid: views.hybrid,
  score: views.score,
  people: views.people,
};

state.go = (view) => navigate(view);
state.openModal = () => openPicker();
state.onRatingsChanged = async (n) => {
  const u = activeUser();
  if (u) u.n_ratings = n;
  state.reelData = null;
  await loadUsers();
};

/* ── boot ─────────────────────────────────────────────────── */
const BOOT = [
  { msg: "Reading 100,836 ratings from MovieLens…", step: null },
  { msg: "Fitting TF-IDF over genres, tags, keywords, cast and crew…", step: "content" },
  { msg: "Measuring who rates like whom — adjusted cosine, then Pearson…", step: "collab" },
  { msg: "Training matrix factorisation by SGD, 50 factors…", step: "collab" },
  { msg: "Blending the two signals and caching everything…", step: "hybrid" },
];

const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

/** The loading screen animates the thing the app is about: a sparse grid
    filling in, with each approach coming online in turn. */
function startBootScene() {
  const host = $("#bootMatrix");
  const cols = Math.max(18, Math.min(48, Math.round(window.innerWidth / 34)));
  const rows = Math.max(10, Math.min(30, Math.round(window.innerHeight / 34)));
  host.style.gridTemplateColumns = `repeat(${cols},1fr)`;
  host.style.gridTemplateRows = `repeat(${rows},1fr)`;

  const total = cols * rows;
  const cells = [];
  for (let i = 0; i < total; i += 1) {
    const cell = document.createElement("i");
    host.append(cell);
    cells.push(cell);
  }

  // deal cells out in a shuffled order so the grid fills organically
  const order = cells.map((_, i) => i);
  for (let i = order.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [order[i], order[j]] = [order[j], order[i]];
  }

  const counter = $("#bootCount");
  let filled = 0;
  let shown = 0;

  if (reducedMotion()) {
    order.slice(0, Math.round(total * 0.17)).forEach((i) => cells[i].classList.add("lo"));
    counter.textContent = fmt.int(100836);
    return () => {};
  }

  const timer = setInterval(() => {
    for (let k = 0; k < 3 && filled < total; k += 1) {
      const cell = cells[order[filled]];
      // 1.7% of the real matrix is filled — here the ratio is exaggerated so
      // the animation reads, but the point (mostly empty) survives
      cell.classList.add(Math.random() < 0.22 ? "hi" : "lo");
      filled += 1;
    }
    shown = Math.min(100836, shown + 1470 + Math.round(Math.random() * 900));
    counter.textContent = fmt.int(shown);
    if (filled >= total) {
      filled = 0;
      cells.forEach((c) => c.classList.remove("hi", "lo"));
    }
  }, 34);

  return () => {
    clearInterval(timer);
    counter.textContent = fmt.int(100836);
  };
}

function bootStep(name, pct, label, done = false) {
  const row = $(`.bstep[data-step="${name}"]`);
  if (!row) return;
  row.classList.toggle("is-live", !done);
  row.classList.toggle("is-done", done);
  $(".bstep__t i", row).style.width = `${pct}%`;
  $(".bstep__s", row).textContent = label;
}

async function boot() {
  const began = performance.now();
  const stopScene = startBootScene();

  let i = 0;
  const t = setInterval(() => {
    i = Math.min(i + 1, BOOT.length - 1);
    $("#bootMsg").textContent = BOOT[i].msg;
    if (BOOT[i].step) bootStep(BOOT[i].step, 55 + i * 8, "training");
  }, 2200);

  for (let n = 0; n < 400; n += 1) {
    try { state.status = await api.status(); break; }
    catch { await new Promise((r) => setTimeout(r, 1200)); }
  }

  // A warm start answers in ~200ms, which would flash the whole scene past.
  // Hold it long enough to actually be seen, then finish.
  const MIN_MS = reducedMotion() ? 0 : 2100;
  const left = MIN_MS - (performance.now() - began);
  if (left > 0) {
    bootStep("content", 78, "training");
    await new Promise((r) => setTimeout(r, left * 0.5));
    bootStep("collab", 82, "training");
    await new Promise((r) => setTimeout(r, left * 0.5));
  }

  clearInterval(t);
  stopScene();

  $("#bootMsg").textContent = "All three models are up.";
  ["content", "collab", "hybrid"].forEach((s, n) =>
    setTimeout(() => bootStep(s, 100, "ready", true), n * 130));

  await loadUsers();
  await new Promise((r) => setTimeout(r, reducedMotion() ? 0 : 620));

  $("#boot").classList.add("is-gone");
  setTimeout(() => { $("#boot").hidden = true; }, 520);
  $("#shell").hidden = false;

  renderTmdb();
  wire();
  navigate("browse");
  pollEnrichment();
}

const DB_ICON = '<svg class="icon" viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="9" ry="3"/>'
  + '<path d="M3 5v14a9 3 0 0 0 18 0V5"/><path d="M3 12a9 3 0 0 0 18 0"/></svg>';

function renderTmdb() {
  const t = state.status?.tmdb || {};
  const node = $("#tmdbStatus");
  node.className = `tmdb ${t.available ? "" : "is-bad"}`;
  node.innerHTML = t.available
    ? `${DB_ICON}<span>TMDB · ${esc(t.route)}<br>
        <span id="enrichLine"><b>${fmt.int(t.cached_titles)}</b> / <b>9,724</b> films enriched</span></span>`
    : `${DB_ICON}<span>Posters unavailable<br>${esc(t.reason || "no route to TMDB")}</span>`;
}

async function pollEnrichment() {
  const tick = async () => {
    try {
      const s = await api.enrichStatus();
      const line = $("#enrichLine");
      if (line) {
        line.innerHTML = s.running
          ? `enriching <b>${fmt.int(s.done)}</b>/<b>${fmt.int(s.total)}</b>…`
          : `<b>${fmt.int(s.cached)}</b> / <b>9,724</b> films enriched`;
      }
      if (s.running) setTimeout(tick, 6000);
    } catch { /* server busy */ }
  };
  setTimeout(tick, 4000);
}

/* ── users ────────────────────────────────────────────────── */
async function loadUsers() {
  state.users = await api.users();
  const all = [...state.users.custom, ...state.users.builtin];
  if (!all.some((u) => u.userId === state.userId)) {
    state.userId = all[0]?.userId ?? 1;
  }
  renderUser();
  renderUserList();
}

const activeUser = () =>
  [...state.users.custom, ...state.users.builtin].find((u) => u.userId === state.userId);

function renderUser() {
  const u = activeUser();
  if (!u) return;
  state.userName = u.name;
  $("#userName").textContent = u.name;
  $("#userStats").textContent = `${fmt.int(u.n_ratings)} ratings · mean ${fmt.n(u.avg_rating, 1)}`;
  $("#userAvatar").textContent = u.custom ? (u.name[0] || "?").toUpperCase() : String(u.userId);
  renderStrength(u.n_ratings);
}

/** Ten ticks toward a workable profile — the point at which all three
    approaches have something to go on. */
function renderStrength(n) {
  const TARGET = 10;
  const filled = Math.min(TARGET, n);
  $("#strengthN").innerHTML = `<em>${fmt.int(filled)}</em>/${TARGET}`;
  $("#strengthBar").innerHTML = Array.from({ length: TARGET },
    (_, i) => `<i class="${i < filled ? "on" : ""}"></i>`).join("");
  $("#strengthNote").textContent = n < 1
    ? "Rate a film to switch content-based filtering on."
    : n < 3 ? "Content-based is live. Collaborative needs a few more."
      : n < 8 ? "Both live — the hybrid still falls back to content below 8."
        : "All three approaches have enough to work with.";
}

function renderUserList(filter = "") {
  const needle = filter.toLowerCase();
  const match = (u) => !needle || u.name.toLowerCase().includes(needle);
  const row = (u, custom) => `
    <button class="uitem ${u.userId === state.userId ? "is-on" : ""} ${custom ? "is-custom" : ""}"
      data-u="${u.userId}">
      <span class="uitem__av">${custom ? esc((u.name[0] || "?").toUpperCase()) : u.userId}</span>
      <span class="uitem__t">
        <b>${esc(u.name.replace("MovieLens ", ""))}</b>
        <small>${fmt.int(u.n_ratings)} ratings${(u.top_genres || []).length
          ? ` · ${esc(u.top_genres.slice(0, 2).join(", "))}` : ""}</small>
      </span>
      ${custom ? `<span class="uitem__del" data-del="${u.userId}" title="Delete">✕</span>` : ""}
    </button>`;
  const html = [
    ...state.users.custom.filter(match).map((u) => row(u, true)),
    ...state.users.builtin.filter(match).map((u) => row(u, false)),
  ].join("");
  $("#userList").innerHTML = html || '<div class="loading" style="padding:14px">No match.</div>';
}

/* ── routing ──────────────────────────────────────────────── */
async function navigate(view) {
  state.view = view;
  closeDrawer();
  closeReel();
  state.stopShelf?.();
  state.stopShelf = null;
  scenes.unmountAll();

  $$("#nav .navitem").forEach((b) => b.classList.toggle("is-on", b.dataset.view === view));
  const host = $("#view");
  host.className = "view";
  host.innerHTML = "";
  $("#main").scrollTop = 0;
  try {
    await VIEWS[view](host, state);
  } catch (err) {
    host.innerHTML = `<div class="empty"><h3>Could not load this view</h3>
      <p>${esc(err.message)}</p></div>`;
  }
}

/* ── wiring ───────────────────────────────────────────────── */
function wire() {
  $("#nav").addEventListener("click", (e) => {
    const b = e.target.closest("[data-view]");
    if (b) navigate(b.dataset.view);
  });

  const btn = $("#userBtn");
  const panel = $("#userPanel");
  btn.addEventListener("click", () => {
    const open = panel.hidden;
    panel.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
    if (open) $("#userFilter").focus();
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#userBtn, #userPanel")) {
      panel.hidden = true;
      btn.setAttribute("aria-expanded", "false");
    }
  });
  $("#userFilter").addEventListener("input", (e) => renderUserList(e.target.value));

  $("#userList").addEventListener("click", async (e) => {
    const del = e.target.closest("[data-del]");
    if (del) {
      e.stopPropagation();
      await api.deleteUser(Number(del.dataset.del));
      api.clearCache();
      if (state.userId === Number(del.dataset.del)) state.userId = 1;
      await loadUsers();
      toast("Viewer deleted");
      navigate(state.view);
      return;
    }
    const b = e.target.closest("[data-u]");
    if (!b) return;
    state.userId = Number(b.dataset.u);
    state.comparePicks = [];
    state.reelData = null;
    panel.hidden = true;
    $("#userBtn").setAttribute("aria-expanded", "false");
    renderUser();
    renderUserList();
    navigate(state.view);
  });

  $("#newUserBtn").addEventListener("click", openPicker);

  const setScores = (on) => {
    state.showScores = on;
    document.documentElement.dataset.scores = on ? "on" : "off";
    $("#scoreToggle").setAttribute("aria-pressed", String(on));
    $("#scoreToggleSm").textContent = on ? "Hide scores" : "Show scores";
  };
  $("#scoreToggle").addEventListener("click", () => {
    setScores(!state.showScores);
    toast(state.showScores ? "Scores and maths shown" : "Scores and maths hidden");
  });
  $("#scoreToggleSm").addEventListener("click", () => setScores(!state.showScores));
  setScores(true);

  wireTheme();
}

/* ── theme ────────────────────────────────────────────────── */
/** `persist` is false for the initial sync, so merely loading the page does
    not count as choosing a theme and stop the OS preference being followed. */
function applyTheme(name, persist = true) {
  document.documentElement.dataset.theme = name;
  if (persist) {
    try { localStorage.setItem("mrs-theme", name); } catch { /* private mode */ }
  }
  $$("[data-theme-set]").forEach((b) =>
    b.classList.toggle("is-on", b.dataset.themeSet === name));
  $("#themeToggleSm").textContent = name === "dark" ? "Light" : "Dark";
  // canvases are painted, not styled — they need the new palette pushed in
  scenes.refreshPalette();
}

function wireTheme() {
  $("#themes").addEventListener("click", (e) => {
    const b = e.target.closest("[data-theme-set]");
    if (b) applyTheme(b.dataset.themeSet);
  });
  $("#themeToggleSm").addEventListener("click", () =>
    applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark"));

  // follow the OS, but only until the viewer picks for themselves
  let chosen = false;
  try { chosen = !!localStorage.getItem("mrs-theme"); } catch { /* ignore */ }
  if (!chosen) {
    matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
      applyTheme(e.matches ? "dark" : "light", false);
    });
  }
  applyTheme(document.documentElement.dataset.theme || "light", false);
}

/* ── new viewer ───────────────────────────────────────────── */
const picks = new Map();
let modal = null;

function closePicker() {
  modal?.remove();
  modal = null;
}

async function openPicker() {
  picks.clear();
  closePicker();
  modal = el(`
    <div class="modal">
      <div class="modal__box" role="dialog" aria-modal="true">
        <div class="modal__head">
          <div>
            <h2>Build a viewer from scratch</h2>
            <p>Rate a handful of films. Watch content-based filtering work immediately, and
              collaborative filtering struggle until you have enough ratings — that is the cold-start
              problem, live.</p>
          </div>
          <button class="btn btn--icon" id="mClose" aria-label="Close">${ICON.close}</button>
        </div>
        <div class="modal__mid">
          <input type="text" id="mName" placeholder="Name this viewer" aria-label="Viewer name" />
          <div class="modal__count"><b id="mCount">0</b> rated · <span id="mHint">rate below, or
            create an empty viewer and search the full catalogue</span></div>
        </div>
        <div class="modal__body"><div class="pickgrid" id="mGrid"></div></div>
        <div class="modal__foot">
          <button class="btn btn--ghost" id="mCancel">Cancel</button>
          <button class="btn btn--primary" id="mCreate">Create empty &amp; rate later</button>
        </div>
      </div>
    </div>`);
  document.getElementById("overlays").append(modal);

  $("#mClose", modal).addEventListener("click", closePicker);
  $("#mCancel", modal).addEventListener("click", closePicker);
  $("#mCreate", modal).addEventListener("click", createUser);
  modal.addEventListener("click", (e) => { if (e.target === modal) closePicker(); });

  const grid = $("#mGrid", modal);
  grid.innerHTML = '<div class="loading" style="padding:20px"><span class="spin"></span> Loading films…</div>';
  let data;
  try {
    data = await api.sampler(30, Math.floor(Math.random() * 10000));
  } catch (err) {
    grid.innerHTML = `<div class="empty" style="grid-column:1/-1"><h3>Could not reach the server</h3>
      <p>${esc(err.message)}</p><button class="btn btn--primary" id="mRetry">Try again</button></div>`;
    $("#mRetry", grid)?.addEventListener("click", openPicker);
    return;
  }

  grid.innerHTML = data.results.map((f) => `
    <div class="pick" data-rate="${f.movieId}">
      <div class="pick__art">
        ${f.poster ? `<img src="${esc(f.poster)}" alt="${esc(f.title)}" loading="lazy" />` : ""}
      </div>
      <div class="pick__t">${esc(f.title)}</div>
      <div class="stars">
        ${[1, 2, 3, 4, 5].map((s) => `<span class="star" data-s="${s}">★</span>`).join("")}
      </div>
    </div>`).join("");

  grid.addEventListener("click", (e) => {
    const star = e.target.closest(".star");
    if (!star) return;
    const card = star.closest(".pick");
    const value = Number(star.dataset.s);
    picks.set(Number(card.dataset.rate), value);
    card.classList.add("is-rated");
    $$(".star", card).forEach((s) => s.classList.toggle("is-on", Number(s.dataset.s) <= value));
    $("#mCount", modal).textContent = String(picks.size);
    $("#mCreate", modal).textContent = `Create viewer (${picks.size})`;
    $("#mHint", modal).textContent = picks.size < 5
      ? "rate at least 5 for decent results"
      : picks.size < 8
        ? "good — collaborative filtering switches on at 8"
        : "plenty; every model has enough to work with";
  });
}

async function createUser() {
  const name = $("#mName", modal).value.trim() || "Guest";
  const btn = $("#mCreate", modal);
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> Creating…';
  try {
    const user = await api.createUser(name, Object.fromEntries([...picks.entries()]));
    api.clearCache();
    await loadUsers();
    state.userId = user.userId;
    state.comparePicks = [];
    state.reelData = null;
    renderUser();
    renderUserList();
    closePicker();
    toast(`${name} created with ${picks.size} rating${picks.size === 1 ? "" : "s"}`);
    navigate(picks.size >= 5 ? "browse" : "rate");
  } catch (err) {
    toast(`Could not create viewer: ${err.message}`);
    btn.disabled = false;
    btn.textContent = "Create viewer";
  }
}

boot();
