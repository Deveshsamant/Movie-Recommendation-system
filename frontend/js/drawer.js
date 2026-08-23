/* Film drawer: the same pick explained under all three approaches. */

import { api } from "./api.js?v=16";
import { $, $$, el, esc, fmt, RED, INK, ICON, mathRow, mathTotal } from "./ui.js?v=16";

export function closeDrawer() {
  $$(".drawer, .scrim").forEach((n) => n.remove());
  document.removeEventListener("keydown", onKey);
}

function onKey(e) {
  if (e.key === "Escape") closeDrawer();
}

export async function openDrawer(movie, state, initialTab = "about") {
  closeDrawer();

  const scrim = el('<div class="scrim"></div>');
  scrim.addEventListener("click", closeDrawer);

  const node = el(`
    <aside class="drawer" role="dialog" aria-modal="true">
      <div class="drawer__head">
        <div class="drawer__hero">
          ${movie.backdrop || movie.poster
            ? `<img src="${esc(movie.backdrop || movie.poster)}" alt="" /><span class="scrim2"></span>` : ""}
          <i></i>
          <button class="drawer__x" aria-label="Close">${ICON.close}</button>
          <h2 class="drawer__title">${esc(movie.title)}</h2>
          <p class="drawer__meta">${movie.year || ""} ·
            ${esc((movie.genres || []).join(" · "))}${movie.runtime ? ` · ${movie.runtime} min` : ""}</p>
        </div>
        <div class="drawer__tabs">
          <button data-t="about">Info</button>
          <button data-t="content">◈ Content</button>
          <button data-t="collaborative">◉ Collab</button>
          <button data-t="hybrid">◆ Hybrid</button>
        </div>
      </div>
      <div class="drawer__body" id="drawerPane"></div>
    </aside>`);

  $(".drawer__x", node).addEventListener("click", closeDrawer);
  document.getElementById("overlays").append(scrim, node);
  document.addEventListener("keydown", onKey);

  const tabs = $$(".drawer__tabs button", node);
  const pane = $("#drawerPane", node);

  const select = (tab) => {
    tabs.forEach((b) => b.classList.toggle("is-on", b.dataset.t === tab));
    render(tab);
  };
  tabs.forEach((b) => b.addEventListener("click", () => select(b.dataset.t)));

  async function render(tab) {
    pane.innerHTML = '<div class="loading"><span class="spin"></span> Working out the arithmetic</div>';
    try {
      if (tab === "about") pane.innerHTML = await aboutPane(movie, node);
      else if (tab === "content") pane.innerHTML = await contentPane(movie, state);
      else if (tab === "collaborative") pane.innerHTML = await collabPane(movie, state);
      else pane.innerHTML = await hybridPane(movie, state);
    } catch (err) {
      pane.innerHTML = `<div class="loading">${esc(err.message)}</div>`;
    }
  }

  select(initialTab);
}

const shell = (title, blurb, formula, rows, totalLabel, total, totalColor) => `
  <div class="h3">${title}</div>
  <p class="sub" style="margin-top:7px;line-height:1.6">${blurb}</p>
  <div class="score-only" style="margin-top:18px">
    <div class="formula">${esc(formula)}</div>
    ${rows}
    ${mathTotal(totalLabel, total, totalColor)}
  </div>`;

async function contentPane(movie, state) {
  const [d, similar] = await Promise.all([
    api.explainContent(state.userId, movie.movieId),
    api.similar(movie.movieId, "content", 6),
  ]);
  const why = d.explanation;
  const sources = (why.because_of || []).slice(0, 5);
  const maxC = Math.max(...sources.map((s) => s.contribution), 1e-6);

  const rows = sources.length
    ? sources.map((s, i) => mathRow({
        label: s.title,
        meta: `you rated ${fmt.n(s.your_rating, 1)} · similarity ${fmt.n(s.similarity, 3)}`,
        math: `${fmt.signed(s.profile_weight, 2)} × ${fmt.n(s.similarity, 3)} = <b style="color:${RED}">${fmt.n(s.contribution, 4)}</b>`,
        pct: (s.contribution / maxC) * 100, color: RED, delay: i * 0.05,
      })).join("")
    : '<div class="loading">This film shares no terms with your profile.</div>';

  const terms = (why.terms || []).slice(0, 6);
  const maxT = Math.max(...terms.map((t) => t.contribution), 1e-6);
  const termRows = terms.map((t, i) => mathRow({
    label: t.term, kind: t.kind,
    math: `${fmt.n(t.profile_weight, 3)} × ${fmt.n(t.movie_weight, 3)} = <b style="color:${RED}">${fmt.n(t.contribution, 4)}</b>`,
    pct: (t.contribution / maxT) * 100, color: RED, delay: i * 0.04,
  })).join("");

  return shell(
    "◈ Why content-based filtering picked this",
    "Your profile is a weighted sum of everything you rated, so the score splits cleanly back across "
      + "those films. These are the ones that pulled hardest.",
    "score = Σₜ profile[t] × tfidf_movie[t]",
    rows,
    `total from ${why.n_sources || 0} of your ratings`,
    fmt.n(why.score, 4), RED
  ) + `
    <div class="h3" style="margin-top:26px">Term-by-term overlap</div>
    <p class="sub" style="margin-top:7px">Cosine similarity is a dot product, so every shared term
      contributes an exact amount.</p>
    <div class="score-only" style="margin-top:14px">${termRows || '<div class="loading">No shared terms.</div>'}</div>

    <div class="h3" style="margin-top:26px">Nearest films by description alone</div>
    <p class="sub" style="margin-top:7px">Pure metadata similarity — no ratings involved.</p>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(88px,1fr));margin-top:12px;
      border-top:var(--rule);border-left:var(--rule)">
      ${similar.items.map((f) => `
        <div style="border-right:var(--rule);border-bottom:var(--rule)">
          <div style="position:relative;aspect-ratio:2/3;background:var(--color-neutral-200);overflow:hidden">
            ${f.poster ? `<img src="${esc(f.poster)}" alt="" loading="lazy"
              style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover" />` : ""}
          </div>
          <div style="padding:7px 8px">
            <div style="font-size:10.5px;font-weight:700;line-height:1.2">${esc(f.title)}</div>
            <div class="mono score-only" style="font-size:10px;color:${RED}">${fmt.n(f.score, 3)}</div>
          </div>
        </div>`).join("")}
    </div>`;
}

async function collabPane(movie, state) {
  const model = state.cfModel;
  const d = await api.explainCollab(state.userId, movie.movieId, model);
  const why = d.explanation;

  if (model === "svd") {
    const f = (why.factors || []).slice(0, 6);
    const maxF = Math.max(...f.map((x) => Math.abs(x.product)), 1e-6);
    const rows = [
      mathRow({ label: "μ — global mean", math: `<b>${fmt.n(why.mu, 3)}</b>`, pct: 100, color: INK }),
      mathRow({ label: "b_u — this viewer's bias", math: `<b>${fmt.signed(why.b_u, 3)}</b>`,
        pct: Math.abs(why.b_u) * 100, color: INK }),
      mathRow({ label: "b_i — this film's bias", math: `<b>${fmt.signed(why.b_i, 3)}</b>`,
        pct: Math.abs(why.b_i) * 100, color: INK }),
    ].join("") + f.map((x, i) => mathRow({
      label: `latent factor ${x.k}`,
      math: `${fmt.signed(x.p_u, 3)} × ${fmt.signed(x.q_i, 3)} = <b style="color:${x.product >= 0 ? INK : RED}">${fmt.signed(x.product, 4)}</b>`,
      pct: (Math.abs(x.product) / maxF) * 100, color: x.product >= 0 ? INK : RED, delay: i * 0.04,
    })).join("");
    return shell("◉ Matrix factorisation",
      "You and the film are both points in a 50-dimensional space the model invented. The prediction "
        + "is their dot product, plus the biases.",
      "r̂ = μ + b_u + b_i + p_u·q_i", rows,
      why.clipped ? "predicted (clipped to 5.0)" : "predicted rating",
      fmt.n(Math.min(5, Math.max(0.5, why.raw)), 2), INK);
  }

  const nb = why.neighbours || [];
  if (!nb.length) {
    return shell("◉ " + d.method.name,
      "No neighbour of this film appears in your history, so the model has nothing to work from and "
        + "falls back to your mean. This is exactly the sparsity problem collaborative filtering suffers.",
      d.method.formula, "", "fallback", fmt.n(why.user_mean, 2), INK);
  }
  const maxT = Math.max(...nb.map((n) => Math.abs(n.term)), 1e-6);
  const rows = nb.map((n, i) => mathRow({
    label: n.title || `User ${n.userId}`,
    meta: n.title ? `you rated ${fmt.n(n.your_rating, 1)}`
      : `rated ${fmt.n(n.their_rating, 1)} (mean ${fmt.n(n.their_mean, 1)})`,
    math: `${fmt.n(n.similarity, 3)} × ${fmt.signed(n.deviation, 2)} = <b style="color:${n.term >= 0 ? INK : RED}">${fmt.signed(n.term, 3)}</b>`,
    pct: (Math.abs(n.term) / maxT) * 100, color: n.term >= 0 ? INK : RED, delay: i * 0.05,
  })).join("");
  const pred = why.user_mean + (why.denominator ? why.numerator / why.denominator : 0);

  return shell("◉ " + d.method.name,
    state.cfModel === "item-knn"
      ? "Films you already rated that behave most like this one across the whole crowd. None of this "
        + "uses genre — similarity here means <i>rated alike</i>."
      : "Viewers whose rating pattern matches yours, and what they made of this film.",
    d.method.formula, rows,
    `${why.k_used} neighbour${why.k_used === 1 ? "" : "s"} used`,
    fmt.n(Math.min(5, Math.max(0.5, pred)), 2), INK);
}

async function hybridPane(movie, state) {
  const d = await api.hybrid(state.userId, {
    n: 60, strategy: state.strategy, cf_model: "item-knn", alpha: state.alpha,
  });
  const f = (d.items || []).find((i) => i.movieId === movie.movieId);
  if (!f) {
    return `<div class="note" style="margin-top:0">
      <b>Not in the current blend.</b>
      <p>This film is outside the hybrid top 60 for this viewer at α = ${state.alpha.toFixed(2)}.
        Try moving α on the Hybrid page.</p></div>`;
  }
  const total = (f.cf_part + f.content_part) || 1;
  const alpha = d.trace.effective_alpha ?? d.trace.alpha;
  const rows = [
    mathRow({
      label: "collaborative signal", meta: `raw ${fmt.n(f.cf_raw, 3)}`,
      math: `${fmt.n(alpha, 2)} × ${fmt.n(f.cf_norm, 3)} = <b style="color:${INK}">${fmt.n(f.cf_part, 4)}</b>`,
      pct: (f.cf_part / total) * 100, color: INK,
    }),
    mathRow({
      label: "content signal", meta: `raw ${fmt.n(f.content_raw, 3)} cosine`,
      math: `${fmt.n(1 - alpha, 2)} × ${fmt.n(f.content_norm, 3)} = <b style="color:${RED}">${fmt.n(f.content_part, 4)}</b>`,
      pct: (f.content_part / total) * 100, color: RED,
    }),
  ].join("");

  return shell("◆ How the blend scored it",
    "Both signals are min–max normalised to [0,1] first, otherwise a cosine similarity and a rating "
      + "prediction could not be added together.",
    "score = α·norm(CF) + (1−α)·norm(content)", rows,
    "blended score", fmt.n(f.score, 4), f.cf_part > f.content_part ? INK : RED)
    + `<div class="note" style="margin-top:22px">
        <b>${f.lead === "content" ? "Content" : "Collaborative"} filtering is carrying this pick.</b>
        <p>Content contributed ${fmt.n(f.content_part, 4)} of the ${fmt.n(f.score, 4)} total;
          collaborative contributed ${fmt.n(f.cf_part, 4)}.</p>
      </div>`;
}

/** The film itself, straight from TMDB: synopsis, cast, director, rating. */
async function aboutPane(movie, node) {
  let f = movie;
  try {
    f = await api.movie(movie.movieId);   // full record, with the title-search fallback
  } catch { /* fall back to the card we already have */ }

  // upgrade the drawer hero now that we may have a backdrop
  if (f.backdrop || f.poster) {
    const hero = $(".drawer__hero", node);
    if (hero && !$("img", hero)) {
      hero.insertAdjacentHTML("afterbegin",
        `<img src="${esc(f.backdrop || f.poster)}" alt="" /><span class="scrim2"></span>`);
    }
  }

  const people = (label, list) => (list && list.length
    ? `<div style="display:flex;gap:12px;padding:11px 0;border-bottom:var(--hair)">
         <span style="width:78px;flex:none;font-size:9.5px;letter-spacing:.14em;
           text-transform:uppercase;font-weight:800;color:var(--color-neutral-600)">${esc(label)}</span>
         <span style="flex:1;font-size:12.5px;font-weight:600">${esc(list.join(" · "))}</span>
       </div>`
    : "");

  return `
    <div style="display:flex;gap:16px">
      ${f.poster ? `<img src="${esc(f.poster)}" alt="" style="width:104px;flex:none;
        border:2px solid var(--color-divider);display:block" />` : ""}
      <div style="flex:1;min-width:0">
        <div class="h3" style="font-size:17px">${esc(f.full_title || f.title)}</div>
        ${f.tagline ? `<p style="font-size:12px;font-style:italic;color:var(--color-accent-700);
          margin-top:6px">“${esc(f.tagline)}”</p>` : ""}
        <div style="display:flex;flex-wrap:wrap;gap:0;margin-top:10px">
          ${(f.genres || []).map((g) => `<span class="kicker kicker--outline"
            style="margin:0 -2px -2px 0;font-size:9px">${esc(g)}</span>`).join("")}
        </div>
      </div>
    </div>

    <div class="cells" style="margin-top:18px;border-left:var(--rule)">
      ${f.tmdb_score ? `<div class="cell"><b>${fmt.n(f.tmdb_score, 1)}</b><span>TMDB rating</span>
        <small>${fmt.int(f.vote_count || 0)} votes</small></div>` : ""}
      <div class="cell"><b>${fmt.n(f.avg_rating, 2)}</b><span>MovieLens mean</span>
        <small>${fmt.int(f.n_ratings)} ratings</small></div>
      ${f.runtime ? `<div class="cell"><b>${f.runtime}</b><span>minutes</span></div>` : ""}
      ${f.year ? `<div class="cell"><b>${f.year}</b><span>released</span>
        <small>${esc(f.release_date || "")}</small></div>` : ""}
    </div>

    ${f.overview
      ? `<div style="margin-top:20px">
           <div style="font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;font-weight:800;
             color:var(--color-neutral-600);padding-bottom:8px;border-bottom:var(--rule)">Synopsis</div>
           <p style="font-size:13.5px;line-height:1.62;margin-top:11px">${esc(f.overview)}</p>
         </div>`
      : '<p class="sub" style="margin-top:18px">No synopsis on TMDB for this title.</p>'}

    <div style="margin-top:20px">
      ${people("Director", f.directors)}
      ${people("Cast", (f.cast || []).slice(0, 8))}
      ${people("Genres", f.tmdb_genres && f.tmdb_genres.length ? f.tmdb_genres : f.genres)}
    </div>

    ${f.keywords?.length
      ? `<div style="margin-top:18px">
           <div style="font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;font-weight:800;
             color:var(--color-neutral-600);margin-bottom:9px">TMDB keywords</div>
           <div style="display:flex;flex-wrap:wrap;gap:0">
             ${f.keywords.map((k) => `<span class="kicker kicker--outline"
               style="margin:0 -2px -2px 0;font-size:9px">${esc(k)}</span>`).join("")}
           </div>
           <p class="sub" style="margin-top:10px">These keywords are not decoration — they are
             literally part of the vector the content-based model scores against.</p>
         </div>`
      : ""}`;
}
