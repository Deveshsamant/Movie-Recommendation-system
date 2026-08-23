/* Play reel — the hybrid top ten as an auto-advancing slideshow.
   Each slide names which approach carried that pick, and shows the split. */

import { api } from "./api.js?v=16";
import { $, $$, el, esc, fmt, RED, PAPER, ICON } from "./ui.js?v=16";

const SLIDE_MS = 3600;
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

let timer = null;
let node = null;

export function closeReel() {
  clearTimeout(timer);
  timer = null;
  node?.remove();
  node = null;
  document.removeEventListener("keydown", onKey);
}

function onKey(e) {
  if (!node) return;
  if (e.key === "Escape") closeReel();
  if (e.key === "ArrowRight") step(1);
  if (e.key === "ArrowLeft") step(-1);
}

let films = [];
let idx = 0;
let playing = true;
let render = () => {};

function step(d) {
  clearTimeout(timer);
  playing = false;
  idx = Math.max(0, Math.min(films.length, idx + d));
  render();
}

function arm() {
  clearTimeout(timer);
  if (reduced() || !playing) return;
  timer = setTimeout(() => {
    if (idx + 1 > films.length) { playing = false; render(); return; }
    idx += 1;
    render();
    arm();
  }, SLIDE_MS);
}

export async function openReel(state, start = 0) {
  let list = state.reelData;
  if (!list?.length) {
    const d = await api.browse(state.userId, state.alpha);
    if (d.empty) return;
    list = d.reel;
    state.reelData = list;
  }
  films = list;
  idx = start;
  playing = !reduced();

  closeReel();
  node = el('<div class="reel"></div>');
  document.getElementById("overlays").append(node);
  document.addEventListener("keydown", onKey);

  render = () => draw(state);
  render();
  arm();
}

function verdictOf(f) {
  const lo = Math.min(f.cf_part, f.content_part);
  const hi = Math.max(f.cf_part, f.content_part) || 1;
  if (lo / hi > 0.7) return { key: "both", text: "◆ Both models agree" };
  return f.cf_part > f.content_part
    ? { key: "cf", text: "◉ Collaborative filtering led this pick" }
    : { key: "content", text: "◈ Content-based filtering led this pick" };
}

function reasonOf(f, verdict) {
  if (verdict.key === "both") {
    return `Rare unanimity: viewers who rate like you predict ${fmt.n(f.cf_rating, 2)}, and your own `
      + `taste vector scores it ${fmt.n(f.content_raw, 3)} on genre and keyword overlap. When both `
      + `approaches converge, the blend barely has to choose.`;
  }
  if (verdict.key === "cf") {
    return `Nobody described this film to the model. It surfaced because viewers with your rating `
      + `pattern rated it highly — predicted ${fmt.n(f.cf_rating, 2)} of 5. Content-based filtering `
      + `ranked it far lower, at ${fmt.n(f.content_raw, 3)}.`;
  }
  return `The crowd is thin here — only ${fmt.int(f.n_ratings)} ratings. What carried it is `
    + `description: ${esc((f.genres || []).slice(0, 2).join(" and ").toLowerCase())}, matched against `
    + `the terms you rated highest. Collaborative filtering alone would never have shown you this.`;
}

function draw(state) {
  const isEnd = idx >= films.length;
  const f = films[Math.min(idx, films.length - 1)];
  const verdict = verdictOf(f);
  const total = (f.cf_part + f.content_part) || 1;

  const ticks = Array.from({ length: films.length + 1 }, (_, k) => {
    const bg = k < idx ? PAPER : "rgba(243,242,242,.25)";
    const fill = k === idx && playing && !reduced()
      ? `display:block;height:100%;background:${PAPER};animation:tickAcross ${SLIDE_MS}ms linear both`
      : k === idx ? `display:block;height:100%;width:100%;background:${RED}` : "display:none";
    return `<button data-tick="${k}" aria-label="Go to slide ${k + 1}" style="background:${bg}">
      <i style="${fill}"></i></button>`;
  }).join("");

  const cfLed = films.filter((x) => x.cf_part > x.content_part).length;

  node.innerHTML = `
    <div class="reel__top">
      <span class="kicker kicker--accent">Now playing</span>
      <span class="k">${isEnd ? "The tally" : `${esc(state.userName || "You")} · hybrid blend α ${state.alpha.toFixed(2)}`}</span>
      <span style="flex:1"></span>
      <button class="reel__x" id="reelX" aria-label="Close slideshow">${ICON.close}</button>
    </div>

    <div class="reel__ticks" id="reelTicks">${ticks}</div>

    <div class="reel__body">
      ${isEnd ? endSlide(cfLed, state) : filmSlide(f, verdict, total)}
    </div>

    <div class="reel__foot">
      <button class="btn btn--icon" id="reelPrev" aria-label="Previous slide">${ICON.left}</button>
      <button class="btn btn--icon" id="reelPlay" aria-label="Play or pause">
        ${playing ? ICON.pause : ICON.play}</button>
      <button class="btn btn--icon" id="reelNext" aria-label="Next slide">${ICON.right}</button>
      <span style="flex:1"></span>
      <span class="reel__count">${Math.min(idx + 1, films.length)} / ${films.length}</span>
    </div>`;

  $("#reelX", node).addEventListener("click", closeReel);
  $("#reelPrev", node).addEventListener("click", () => step(-1));
  $("#reelNext", node).addEventListener("click", () => step(1));
  $("#reelPlay", node).addEventListener("click", () => {
    if (playing) { playing = false; clearTimeout(timer); }
    else { playing = true; if (idx >= films.length) idx = 0; arm(); }
    render();
  });
  $("#reelTicks", node).addEventListener("click", (e) => {
    const b = e.target.closest("[data-tick]");
    if (!b) return;
    clearTimeout(timer);
    playing = false;
    idx = Number(b.dataset.tick);
    render();
  });
  $("#reelReplay", node)?.addEventListener("click", () => { idx = 0; playing = true; render(); arm(); });
  $("#reelBack", node)?.addEventListener("click", closeReel);
}

function filmSlide(f, verdict, total) {
  // Each bar is scaled against its own natural range so the three are readable
  // side by side: cosine lives in [0,1], a predicted rating in [0.5,5].
  const contentPct = Math.min(100, (f.content_raw / 0.55) * 100);
  const cfPct = Math.min(100, (f.cf_rating / 5) * 100);
  const hybridPct = Math.min(100, f.score * 100);

  const bar = (label, colour, pct, value, delay) => `
    <div class="reel__bar">
      <b style="color:${colour}">${label}</b>
      <span class="t"><i style="background:${colour};width:${pct}%;
        animation-delay:${delay}"></i></span>
      <span class="v">${value}</span>
    </div>`;

  return `
    <div class="reel__art">
      ${f.poster ? `<img src="${esc(f.poster)}" alt="${esc(f.title)}" />` : '<span class="plate"></span>'}
      <span class="reel__num ${f.poster ? "reel__num--over" : ""}">${String(f.rank).padStart(2, "0")}</span>
      <i class="rule"></i>
    </div>
    <div class="reel__side">
      <span class="reel__verdict">${esc(verdict.text)}</span>
      <h2 class="reel__title">${esc(f.title)}</h2>
      <span class="reel__meta">${f.year || "—"} · ★ ${fmt.n(f.avg_rating, 1)}
        from ${fmt.int(f.n_ratings)} ratings${f.runtime ? ` · ${f.runtime} min` : ""}</span>

      <div class="reel__genres">
        ${(f.genres || []).map((g) => `<span>${esc(g)}</span>`).join("")}
      </div>

      ${f.overview
        ? `<p class="reel__synopsis">${esc(f.overview)}</p>`
        : ""}

      <p class="reel__reason">${reasonOf(f, verdict)}</p>

      <div class="reel__bars score-only">
        ${bar("◈ Content", RED, contentPct, fmt.n(f.content_raw, 3), ".42s")}
        ${bar("◉ Collaborative", PAPER, cfPct, `★ ${fmt.n(f.cf_rating, 2)}`, ".56s")}
        ${bar("◆ Hybrid blend", "var(--color-accent-400)", hybridPct, fmt.n(f.score, 4), ".70s")}
      </div>
    </div>`;
}

function endSlide(cfLed, state) {
  return `
    <div class="reel__end">
      <span class="reel__verdict">That was your ten</span>
      <h2>Three algorithms, ten films, and not one of them agreed on the order.</h2>
      <div class="reel__endstats">
        <div><b>${cfLed}</b><span>led by collaborative</span></div>
        <div><b>${films.length - cfLed}</b><span>led by content</span></div>
        <div><b>${state.alpha.toFixed(2)}</b><span>blend weight α</span></div>
      </div>
      <div style="display:flex;margin-top:30px">
        <button class="btn btn--primary" id="reelReplay" style="padding:14px 22px">
          ${ICON.replay}Play again</button>
        <button class="btn btn--ghost" id="reelBack" style="padding:14px 22px">Back to browsing</button>
      </div>
    </div>`;
}
