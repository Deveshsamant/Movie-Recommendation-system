/* The eight views, rebuilt to the Modernist canvas design. */

import { api } from "./api.js?v=16";
import {
  $, $$, el, esc, fmt, RED, INK, ICON,
  poster, caption, filmCard, emptyState, loading, toast,
  mathRow, mathTotal, radar, convergence, sankey, parallel, venn,
} from "./ui.js?v=16";
import { openDrawer } from "./drawer.js?v=16";
import { openReel } from "./reel.js?v=16";
import * as scenes from "./scenes.js?v=16";

const head = (kicker, kickerCls, title, lede) => `
  <span class="kicker ${kickerCls}">${esc(kicker)}</span>
  <h1 class="display">${esc(title)}</h1>
  <p class="lede">${lede}</p>`;

const cell = (value, label, sub = "") =>
  `<div class="cell"><b>${value}</b><span>${esc(label)}</span>${sub ? `<small>${esc(sub)}</small>` : ""}</div>`;

const segs = (items, active) => items
  .map(([id, label]) => `<button data-k="${id}" class="${id === active ? "is-on" : ""}">${label}</button>`)
  .join("");

/* ═════════════════════════ 0 · BROWSE ═════════════════════ */
export async function browse(host, state) {
  host.classList.add("view--flush");
  host.innerHTML = "";
  host.append(loading("Assembling the shelves"));

  const data = await api.browse(state.userId, state.alpha);
  host.innerHTML = "";
  if (data.empty) {
    host.classList.remove("view--flush");
    host.append(emptyState("Nothing to browse yet", data.message, "Rate some films",
      () => state.go("rate")));
    return;
  }
  state.reelData = data.reel;

  const hero = data.hero;
  const wrap = el(`<div></div>`);

  /* billboard */
  wrap.append(el(`
    <div class="billboard">
      <div class="billboard__l">
        <div style="display:flex;width:fit-content">
          <span class="kicker kicker--accent">◆ Hybrid pick</span>
          <span class="kicker kicker--ink">No. 1 for you</span>
        </div>
        <h1>${esc(hero.title)}</h1>
        <div class="billboard__rule"></div>
        <p>${esc(heroBlurb(hero))}</p>
        <div class="billboard__stats score-only">
          <div><b>${fmt.n(hero.cf_rating, 2)}</b><span>CF predicted</span></div>
          <div><b>${fmt.n(hero.content_raw, 3)}</b><span>content cos θ</span></div>
          <div><b>★ ${fmt.n(hero.avg_rating, 1)}</b><span>${fmt.int(hero.n_ratings)} ratings</span></div>
        </div>
        <div style="display:flex;flex-wrap:wrap;margin-top:26px">
          <button class="btn btn--primary" id="playHero" style="padding:14px 22px">${ICON.play}Play</button>
          <button class="btn btn--ghost" id="whyHero" style="padding:14px 22px">${ICON.info}Why this?</button>
        </div>
      </div>
      <div class="billboard__r">
        ${hero.backdrop || hero.poster
          ? `<img src="${esc(hero.backdrop || hero.poster)}" alt="" />` : ""}
        <i></i>
      </div>
    </div>`));

  $("#playHero", wrap).addEventListener("click", () => openReel(state, 0));
  $("#whyHero", wrap).addEventListener("click", () => openDrawer(hero, state, "hybrid"));

  /* 3D shelf */
  const shelf = el(`
    <div>
      <div style="display:flex;align-items:flex-end;justify-content:space-between;gap:20px;
        flex-wrap:wrap;padding:30px var(--pad) 12px">
        <div>
          <div class="shelf-h__k" style="color:var(--color-accent-700)">Featured shelf · 3D</div>
          <h2 style="font-family:var(--font-heading);font-size:24px;font-weight:800;
            letter-spacing:-.035em;margin-top:7px">Tonight's hybrid shortlist</h2>
          <p class="sub">The ten films the blend ranks highest, on a rotating shelf.
            Use the arrows or click a card off to the side to bring it forward.</p>
        </div>
        <div style="display:flex">
          <button class="btn btn--icon" data-dir="-1" aria-label="Previous film">${ICON.arrowL}</button>
          <button class="btn btn--icon" data-dir="1" aria-label="Next film">${ICON.arrowR}</button>
        </div>
      </div>
      <div class="stage" id="stage"></div>
    </div>`);
  wrap.append(shelf);

  /* algorithm rails */
  data.rails.forEach((r) => {
    if (!r.films.length) return;
    const tone = r.tone === "collaborative" ? INK : RED;
    const strip = el(`
      <div style="padding:30px 0 0">
        <div class="shelf-h">
          <div>
            <div class="shelf-h__k" style="color:${tone === INK ? "var(--color-text)" : "var(--color-accent-700)"}">${esc(r.kicker)}</div>
            <h2>${esc(r.title)}</h2>
          </div>
          <div style="display:flex">
            <button class="btn btn--icon" data-d="-1" aria-label="Scroll left">${ICON.left}</button>
            <button class="btn btn--icon" data-d="1" aria-label="Scroll right">${ICON.right}</button>
          </div>
        </div>
        <div class="railstrip"></div>
      </div>`);
    const track = $(".railstrip", strip);
    r.films.forEach((f) => track.append(tile(f, tone, state)));
    $$("[data-d]", strip).forEach((b) => b.addEventListener("click", () => {
      track.scrollBy({ left: Number(b.dataset.d) * 660, behavior: "smooth" });
    }));
    wrap.append(strip);
  });

  /* top ten */
  const top = el(`
    <div>
      <div style="padding:30px var(--pad) 12px;border-bottom:var(--rule)">
        <div class="shelf-h__k" style="color:var(--color-accent-700)">Across all 610 viewers</div>
        <h2 style="font-family:var(--font-heading);font-size:21px;font-weight:800;
          letter-spacing:-.03em;margin-top:6px">Top 10 this week</h2>
      </div>
      <div class="railstrip"></div>
    </div>`);
  const topTrack = $(".railstrip", top);
  data.top_ten.forEach((f) => {
    const node = el(`
      <div class="toprow">
        <span class="toprow__n">${f.rank}</span>
        <span class="toprow__t">
          <b>${esc(f.title)}</b>
          <small>${fmt.int(f.n)} ratings</small>
        </span>
      </div>`);
    node.addEventListener("click", () => openDrawer(f, state));
    topTrack.append(node);
  });
  wrap.append(top);

  wrap.append(el(`
    <div class="band">
      <div class="band__k">Every row above is a different algorithm</div>
      <p>A streaming front page is just three recommenders arguing, arranged into shelves.</p>
      <button class="btn btn--ghost" data-go="score">See which one wins${ICON.arrowR}</button>
    </div>`));
  $("[data-go]", wrap).addEventListener("click", () => state.go("score"));

  host.append(wrap);

  /* The rotating shelf.
     Cards are built ONCE; spinning only rewrites their transform. Rebuilding
     the DOM each turn (as the first cut did) destroys the elements mid-
     transition, so nothing ever animates. */
  const stage = $("#stage", host);
  const list = data.reel;
  let spot = 0;

  const cards = list.map((f, idx) => {
    const card = el(`
      <div class="card3d">
        <div class="card3d__inner">
          ${poster(f, "card3d__art")}
          <span class="card3d__top"></span>
          <span class="card3d__rank">#${f.rank}</span>
          <div class="card3d__cap">
            <div class="card3d__t">${esc(f.title)}</div>
            <div class="card3d__g">${esc((f.genres || []).slice(0, 2).join(" · "))}</div>
          </div>
        </div>
      </div>`);
    card.addEventListener("click", () => {
      const d = offset(idx);
      if (d === 0) openDrawer(f, state, "about");
      else { spot += d; place(); }
    });
    stage.append(card);
    return card;
  });
  stage.insertAdjacentHTML("beforeend", '<div class="stage__cap" id="stageCap"></div>');

  function offset(idx) {
    let d = idx - (((spot % list.length) + list.length) % list.length);
    if (d > list.length / 2) d -= list.length;
    if (d < -list.length / 2) d += list.length;
    return d;
  }

  function place() {
    cards.forEach((card, idx) => {
      const d = offset(idx);
      const a = Math.abs(d);
      const vis = a <= 2;
      card.style.transform = `translateX(${d * 148}px) rotateY(${-d * 26}deg) `
        + `translateZ(${-a * 190}px) scale(${1 - a * 0.06})`;
      card.style.opacity = vis ? String(1 - a * 0.24) : "0";
      card.style.zIndex = String(20 - a);
      card.style.pointerEvents = vis ? "auto" : "none";
      card.style.cursor = a === 0 ? "pointer" : "pointer";
      $(".card3d__inner", card).style.boxShadow = a === 0 ? "var(--shadow-lg)" : "none";
    });
    const cur = list[((spot % list.length) + list.length) % list.length];
    const cap = $("#stageCap", stage);
    if (cap) cap.textContent = `${cur.title} · rank ${cur.rank} of ${list.length}`;
  }
  place();

  $$("[data-dir]", shelf).forEach((b) => b.addEventListener("click", () => {
    spot += Number(b.dataset.dir);
    place();
  }));

  state.stopShelf?.();
  if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const timer = setInterval(() => {
      if (state.view !== "browse" || document.querySelector(".drawer, .reel")) return;
      if (stage.matches(":hover")) return;
      spot += 1;
      place();
    }, 5200);
    state.stopShelf = () => clearInterval(timer);
  }
}

function heroBlurb(hero) {
  if (hero.lead === "collaborative") {
    return `Nobody described this film to the model. It surfaced because viewers whose ratings look like `
      + `yours put it at ${fmt.n(hero.cf_rating, 2)} of 5 — while your own taste vector scored it only `
      + `${fmt.n(hero.content_raw, 3)}. This is collaborative filtering finding something metadata never would.`;
  }
  return `The crowd is thin here, so what carried this pick is description: it scores `
    + `${fmt.n(hero.content_raw, 3)} against your taste vector on genre, keyword and crew overlap. `
    + `Collaborative filtering alone would never have surfaced it.`;
}

function tile(f, tone, state) {
  const isCollab = tone === INK;
  const badge = isCollab ? `★ ${fmt.n(f.score, 1)}` : fmt.n(f.score, 3);
  const pct = isCollab ? (f.score / 5) * 100 : (f.score / 0.55) * 100;
  const node = el(`
    <article class="tile" tabindex="0">
      ${poster(f, "tile__art")}
      <div class="tile__body">
        <div class="tile__t">${esc(f.title)}</div>
        <div class="tile__g">${f.year || "—"} · ${esc((f.genres || []).slice(0, 2).join(" · "))}</div>
        <div class="tile-reveal" style="font-size:11px;color:var(--color-neutral-700);
          line-height:1.4;margin-top:8px">${esc(f.reason || "")}</div>
        <div class="film__meter score-only" style="margin-top:9px">
          <i class="bar-grow" style="width:${fmt.clamp(pct)};background:${tone}"></i></div>
      </div>
    </article>`);
  $(".tile__art", node).insertAdjacentHTML("beforeend",
    `<span class="tile__stripe" style="background:${tone}"></span>
     <span class="tile__badge score-only" style="background:${tone};
       color:${isCollab ? "var(--color-bg)" : "#fff"}">${badge}</span>`);
  node.addEventListener("click", () => openDrawer(f, state));
  return node;
}

/* ═════════════════════════ 1 · THE DATA ═══════════════════ */
export async function data(host, state) {
  host.innerHTML = head("The raw material", "kicker--outline",
    "Every recommendation starts as a very empty grid",
    `MovieLens 100K — <b>610 viewers</b>, <b>9,724 films</b>, and only <b>100,836 ratings</b> between
     them. That is 1.7% of the grid filled in. Everything the three approaches do is an educated guess
     about the other 98.3%.`) + `<div id="dBody"></div>`;

  const body = $("#dBody", host);
  body.append(loading("Reading the matrix"));

  const [status, matrix] = await Promise.all([api.status(), api.matrix(state.userId)]);
  state.status = status;
  const d = status.dataset;
  body.innerHTML = `
    <div class="cells">
      ${cell(fmt.int(d.n_users), "viewers")}
      ${cell(fmt.int(d.n_items), "films")}
      ${cell(fmt.int(d.n_ratings), "ratings")}
      ${cell(`${d.density}%`, "of grid filled", "98.3% is unknown")}
      ${cell(fmt.n(d.mean_rating, 2), "mean rating", "on a 0.5–5 scale")}
      ${cell(fmt.int(status.content.n_terms), "content terms",
        `${fmt.int(status.content.tmdb_enriched)} TMDB-enriched`)}
    </div>

    <div class="sec-h"><div>
      <h2 class="h2">The densest corner that exists</h2>
      <p class="sub">The ${matrix.users.length} busiest viewers against the ${matrix.items.length}
        most-rated films — ${matrix.density}% filled here, against ${matrix.full_density}% across the
        whole grid. Every gap is something a model has to guess.</p>
    </div></div>
    <div style="overflow:auto;border:2px solid var(--color-divider);border-top:0;
      background:var(--color-neutral-100);padding:11px" id="heat"></div>

    <h2 class="h2" style="margin-top:38px;padding-bottom:12px;border-bottom:var(--rule)">
      Three ways to fill in the blanks</h2>
    <div class="three-up">
      ${approach(RED, "Content-based",
        "Reads <b>down a column</b> — describes each film by its genres, tags, keywords, cast and crew, then finds films whose descriptions match what you already liked.",
        "it can only ever hand you more of the same. It cannot surprise you, because it does not know that anyone else exists.")}
      ${approach(INK, "Collaborative",
        "Reads <b>across rows</b> — ignores what a film <i>is</i> entirely, and asks only who else rated it the same way you did. This is how genuine surprises get found.",
        "a viewer or film is new. With no ratings there is no row and no column, so there is nothing to compare. That is cold start.")}
      ${approach("linear-gradient(135deg,var(--color-accent) 50%,var(--color-text) 50%)", "Hybrid",
        "Uses <b>both</b> — the collaborative signal for discovery, the content signal for coverage and for the cases collaborative filtering cannot reach.",
        "rarely — but it inherits the cost of both, and the blend weight has to be tuned.")}
    </div>`;

  const cellFor = (v) => {
    if (!v) return '<span style="display:block;width:17px;height:17px;background:var(--color-neutral-200)"></span>';
    const t = (v - 0.5) / 4.5;
    const bg = t > 0.66 ? RED
      : t > 0.33 ? "var(--color-accent-500)"
        : "color-mix(in srgb,var(--color-text) 55%,transparent)";
    return `<span style="display:block;width:17px;height:17px;background:${bg}" title="${v}"></span>`;
  };
  $("#heat", body).innerHTML = `<table style="border-collapse:separate;border-spacing:2px">
    ${matrix.values.map((row, i) => `
      <tr>
        <th style="font-size:9.5px;color:${matrix.users[i].highlight ? RED : "var(--color-neutral-600)"};
          font-weight:700;text-align:right;padding-right:7px;white-space:nowrap;position:sticky;left:0;
          background:var(--color-neutral-100)">user ${matrix.users[i].userId}</th>
        ${row.map((v) => `<td>${cellFor(v)}</td>`).join("")}
      </tr>`).join("")}
  </table>`;
}

const approach = (swatch, name, works, fails) => `
  <div>
    <div class="swatch" style="background:${swatch}"></div>
    <div class="h3">${esc(name)}</div>
    <p style="font-size:12.5px;color:var(--color-neutral-700);margin-top:9px;line-height:1.55">${works}</p>
    <p style="font-size:12.5px;color:var(--color-neutral-600);margin-top:11px;line-height:1.55">
      <b style="color:var(--color-accent-700)">Breaks when:</b> ${fails}</p>
  </div>`;

/* ═════════════════════════ 2 · RATE ═══════════════════════ */
export async function rate(host, state) {
  host.innerHTML = head("Your profile", "kicker--outline",
    "Rate films, and watch all three approaches wake up",
    `Content-based filtering starts working from your very first rating; collaborative filtering needs
     enough overlap with other viewers before it has anything to say. That gap is the cold-start
     problem, and you can watch it close.`) + `
    <div id="rReady"></div>
    <div class="searchbar">
      <input type="text" id="rSearch" aria-label="Search the catalogue"
        placeholder="Search the catalogue — try &quot;nolan&quot;, &quot;ghibli&quot;, &quot;heist&quot;…" />
      <button id="rSpread">${ICON.spark}Suggest a spread</button>
    </div>
    <div id="rResults"></div>
    <div id="rMine"></div>`;

  const ready = $("#rReady", host);
  const results = $("#rResults", host);
  const mine = $("#rMine", host);

  const first = await api.ratings(state.userId);
  const editable = first.editable;
  const rateMap = new Map(first.items.map((m) => [m.movieId, m.your_rating]));

  function drawReady(r) {
    const pill = (on, label, hint) => `
      <div class="cell" style="${on ? `background:var(--color-accent-100)` : ""}">
        <b style="font-size:17px;color:${on ? RED : "var(--color-neutral-500)"}">${on ? "● live" : "○ waiting"}</b>
        <span>${esc(label)}</span><small>${esc(hint)}</small>
      </div>`;
    ready.innerHTML = `<div class="cells">
      ${cell(r.n_ratings, "your ratings", r.message)}
      ${pill(r.content, "Content-based", "needs 1 rating")}
      ${pill(r.collaborative, "Collaborative", "needs ~3 ratings")}
      ${pill(r.hybrid_uses_cf, "Hybrid uses CF", `switches at ${r.cold_start_threshold}`)}
    </div>`;
  }
  drawReady(first.readiness);

  if (!editable) {
    ready.insertAdjacentHTML("afterbegin", `
      <div class="note" style="margin-top:22px">
        <b>This is a MovieLens viewer, so their ratings are fixed.</b>
        <p>Their ${fmt.int(first.n_ratings)} ratings are real research data and cannot be edited —
          but you can create your own viewer and rate anything you like.</p>
      </div>`);
    $("#rSearch", host).disabled = true;
    $("#rSpread", host).disabled = true;
  }

  function card(f) {
    const cur = rateMap.get(f.movieId) ?? 0;
    return `
      <div class="film" data-card="${f.movieId}">
        ${poster(f)}
        <div class="film__body" style="padding-bottom:4px">${caption(f)}</div>
        <div class="stars" data-rate="${f.movieId}">
          ${[1, 2, 3, 4, 5].map((s) => `<span class="star ${s <= cur ? "is-on" : ""}" data-s="${s}">★</span>`).join("")}
          <span class="star star--clear" data-s="0" style="${cur ? "" : "visibility:hidden"}">✕</span>
        </div>
        <div class="film__foot" style="padding:8px 14px 12px">★ ${fmt.n(f.avg_rating, 1)} ·
          ${fmt.int(f.n_ratings)} ratings</div>
      </div>`;
  }

  async function applyRating(movieId, value) {
    if (!editable) return;
    try {
      const res = await api.rate(state.userId, movieId, value);
      if (value === null) rateMap.delete(movieId); else rateMap.set(movieId, value);
      drawReady(res.readiness);
      api.clearCache();
      state.onRatingsChanged?.(res.n_ratings);
      refresh(movieId);
      await drawMine();
      toast(value === null ? "Rating removed" : `Rated ${value} ★`);
    } catch (err) {
      toast(`Could not save: ${err.message}`);
    }
  }

  function refresh(movieId) {
    $$(`[data-rate="${movieId}"]`, host).forEach((row) => {
      const cur = rateMap.get(Number(movieId)) ?? 0;
      $$(".star", row).forEach((s) => {
        const v = Number(s.dataset.s);
        if (v === 0) s.style.visibility = cur ? "visible" : "hidden";
        else s.classList.toggle("is-on", v <= cur);
      });
    });
  }

  host.addEventListener("click", (e) => {
    const star = e.target.closest(".star");
    if (!star) return;
    const movieId = Number(star.closest("[data-rate]").dataset.rate);
    const v = Number(star.dataset.s);
    applyRating(movieId, v === 0 ? null : v);
  });

  let timer;
  const search = $("#rSearch", host);
  search.addEventListener("input", () => {
    clearTimeout(timer);
    const q = search.value.trim();
    if (!q) { results.innerHTML = ""; return; }
    timer = setTimeout(async () => {
      results.innerHTML = '<div class="loading"><span class="spin"></span> Searching…</div>';
      try {
        const found = await api.search(q);
        results.innerHTML = found.results.length
          ? `<div class="sec-h"><div><h2 class="h2">Results for “${esc(q)}”</h2>
               <p class="sub">Click a star to rate.</p></div></div>
             <div class="films">${found.results.map(card).join("")}</div>`
          : `<div class="loading">Nothing in the catalogue matches “${esc(q)}”.</div>`;
      } catch (err) {
        results.innerHTML = `<div class="loading">Search failed: ${esc(err.message)}</div>`;
      }
    }, 260);
  });

  $("#rSpread", host).addEventListener("click", async () => {
    results.innerHTML = '<div class="loading"><span class="spin"></span> Picking a spread across genres…</div>';
    const spread = await api.sampler(24, Math.floor(Math.random() * 10000));
    results.innerHTML = `<div class="sec-h"><div><h2 class="h2">A spread across genres</h2>
        <p class="sub">Well-known films, two per genre.</p></div></div>
      <div class="films">${spread.results.map(card).join("")}</div>`;
  });

  async function drawMine(prefetched) {
    const d = prefetched || (await api.ratings(state.userId));
    rateMap.clear();
    d.items.forEach((m) => rateMap.set(m.movieId, m.your_rating));
    mine.innerHTML = `
      <div class="sec-h">
        <div><h2 class="h2">${editable ? "Films you have rated" : "This viewer's ratings"}</h2>
          <p class="sub">${fmt.int(d.n_ratings)} in total${d.n_ratings > d.items.length
            ? `, showing their ${d.items.length} highest-rated` : ""}.</p></div>
        ${d.n_ratings ? `<button class="btn btn--primary" id="rGo">See recommendations ${ICON.arrowR}</button>` : ""}
      </div>
      ${d.n_ratings
        ? `<div class="films">${d.items.map(card).join("")}</div>`
        : `<div class="empty"><h3>No ratings yet</h3>
             <p>Search above, or hit “Suggest a spread” for a mix across genres.</p></div>`}`;
    $("#rGo", mine)?.addEventListener("click", () => state.go("content"));
  }
  await drawMine(first);
}

/* ═════════════════════════ 3 · CONTENT ════════════════════ */
export async function content(host, state) {
  host.innerHTML = head("Approach 1 · Content-based", "kicker--accent",
    "It only ever read the film, never the crowd",
    `Each film becomes a bag of weighted terms — genres ×3, community tags ×2, TMDB keywords ×2,
     director ×2, cast. Your ratings collapse into a single <b>taste vector</b>, and every unseen film
     is scored by cosine similarity against it. No other viewer is consulted at any point.`)
    + `<div id="cBody"></div>`;

  const body = $("#cBody", host);
  body.append(loading("Scoring the catalogue"));

  const d = await api.content(state.userId, 18);
  body.innerHTML = "";
  if (d.empty) {
    body.append(emptyState("No taste profile yet", d.message, "Rate some films", () => state.go("rate")));
    return;
  }

  const terms = d.profile_terms.slice(0, 10);
  const maxTerm = Math.max(...terms.map((t) => t.weight), 1e-6);
  body.innerHTML = `
    <div class="hgrid">
      <div>
        <div class="h3">Your taste vector</div>
        <p class="sub">The strongest dimensions of the profile, built from ${fmt.int(d.n_ratings)}
          ratings. Weight is how far a term sticks out after TF-IDF and L2 normalisation.</p>
        <div class="score-only" style="margin-top:16px">
          <div class="formula"><b>profile</b> = normalise( Σᵢ (rᵢ − mean)/sd × vᵢ )</div>
          ${terms.map((t, i) => mathRow({
            label: t.term, kind: t.kind, math: fmt.n(t.weight, 4),
            pct: (t.weight / maxTerm) * 100, color: RED, delay: i * 0.04,
          })).join("")}
        </div>
      </div>
      <div>
        <div class="h3">Genre affinity</div>
        <p class="sub">Your average rating per genre — the human-readable shadow of the vector beside it.</p>
        ${radar(d.genre_profile.slice(0, 8))}
      </div>
    </div>

    <div class="sec-h">
      <div><h2 class="h2">What content-based filtering picks</h2>
        <p class="sub">Click any film to see the exact terms that produced its score.</p></div>
      <span class="kicker kicker--outline score-only">cos θ shown top-right</span>
    </div>
    <div class="films" id="cFilms"></div>

    <div class="note">
      <b>The ceiling of this approach.</b>
      <p>The list is a mirror of what you already rated. That is not a bug, it is the definition.
        Measured catalogue coverage is <b>18.4%</b> — 8× every other model — and novelty <b>6.84</b>,
        the highest here. But Prec@10 is <b>0.0228</b>, the weakest of the three. Cold start, though,
        is a non-issue: it works from your first rating.</p>
    </div>`;

  const grid = $("#cFilms", body);
  d.items.forEach((f, i) => {
    const why = f.explanation?.because_of?.[0];
    grid.append(filmCard(f, {
      rank: i + 1, tone: "accent", badge: fmt.n(f.score, 3),
      why: why ? `because you rated <b>${esc(why.title)}</b> ${fmt.n(why.your_rating, 1)}` : "",
      meter: f.score * 180,
      onClick: (m) => openDrawer(m, state),
    }));
  });
}

/* ═════════════════════════ 4 · COLLABORATIVE ══════════════ */
export async function collab(host, state) {
  host.innerHTML = head("Approach 2 · Collaborative", "kicker--ink",
    "It never once looked at what a film is about",
    `No genres, no cast, no keywords — only the pattern of who rated what. Films become similar because
     the same people liked them. This is where genuine surprises come from, and it is also why a
     brand-new film is invisible to it.`) + `
    <div class="seg" id="cfSeg" style="margin-top:24px">
      ${segs([["item-knn", "Item-based kNN"], ["user-knn", "User-based kNN"], ["svd", "Matrix factorisation"]],
        state.cfModel)}
    </div>
    <div id="fBody"></div>`;

  $("#cfSeg", host).addEventListener("click", (e) => {
    const b = e.target.closest("[data-k]");
    if (!b) return;
    state.cfModel = b.dataset.k;
    collab(host, state);
  });

  const body = $("#fBody", host);
  body.append(loading("Consulting the crowd"));

  const d = await api.collaborative(state.userId, state.cfModel, 18);
  body.innerHTML = "";
  if (d.empty) {
    body.append(emptyState("Nothing to compare yet", d.message, "Rate some films", () => state.go("rate")));
    return;
  }

  const m = d.method;
  body.insertAdjacentHTML("beforeend", `
    <div class="panel">
      <div class="h3">${esc(m.name)}</div>
      <div class="score-only" style="margin-top:12px;font-family:var(--mono);font-size:12.5px;
        line-height:2;overflow-x:auto">
        <div><b>predict</b> : ${esc(m.formula)}</div>
        ${m.rank_formula ? `<div style="color:var(--color-neutral-600)">
          <b style="color:var(--color-text)">rank</b> : ${esc(m.rank_formula)}</div>` : ""}
      </div>
      <p class="sub" style="margin-top:12px">
        ${Object.entries(m.params || {}).map(([k, v]) => `<b>${esc(k)}</b> ${esc(v)}`).join(" · ")}
        ${m.fold_in ? ` · <b>folded in</b> b<sub>u</sub> ${fmt.n(m.fold_in.b_u, 3)},
          ‖p<sub>u</sub>‖ ${fmt.n(m.fold_in.p_u_norm, 3)}` : ""}
      </p>
    </div>`);

  if (state.cfModel === "svd") await svdSection(body, state, m);
  if (state.cfModel === "item-knn") await orbitSection(body, state, d);
  if (state.cfModel === "user-knn") await neighbourSection(body, state);

  body.insertAdjacentHTML("beforeend", `
    <div class="sec-h"><div>
      <h2 class="h2">What collaborative filtering picks</h2>
      <p class="sub">Ranked by evidence strength; the badge is the predicted rating.</p>
    </div></div>
    <div class="films" id="fFilms"></div>`);

  const grid = $("#fFilms", body);
  d.items.forEach((f, i) => {
    const nb = f.explanation?.neighbours?.[0];
    const why = nb
      ? (nb.title
        ? `similar to <b>${esc(nb.title)}</b>, which you rated ${fmt.n(nb.your_rating, 1)}`
        : `user ${nb.userId} (sim ${fmt.n(nb.similarity, 2)}) rated it ${fmt.n(nb.their_rating, 1)}`)
      : "no neighbour in your history — the model falls back to your mean";
    grid.append(filmCard(f, {
      rank: i + 1, tone: "ink", ink: true, badge: `★ ${fmt.n(f.predicted_rating, 1)}`,
      why, meter: (f.predicted_rating / 5) * 100,
      onClick: (mv) => openDrawer(mv, state),
    }));
  });
}

async function svdSection(body, state, meta) {
  const holder = el(`
    <div>
      <div class="sec-h">
        <div>
          <h2 class="h2">The 50-dimensional space it invented</h2>
          <p class="sub">Every film is a point in the item matrix <b>Q</b> (9,724 × 50), projected to
            three dimensions by PCA. Nobody labelled these axes — the factorisation built them purely
            to compress the rating matrix, yet they land on recognisable clusters. Red points are films
            you rated; the red line is your own vector <b>p<sub>u</sub></b>. Drag to orbit, scroll to zoom.</p>
        </div>
        <div class="seg" id="cloudSeg">
          ${segs([["all", "All films"], ["mine", "Mine only"]], "all")}
        </div>
      </div>
      <div class="scene">
        <canvas id="cvCloud" style="height:480px"></canvas>
        <div class="scene__tip" id="cloudTip"></div>
        <div class="scene__cap" id="cloudCap">PC1 · PC2 · PC3 — one finger orbits, two zoom</div>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));
        border-left:2px solid var(--color-divider);border-right:2px solid var(--color-divider);
        border-bottom:2px solid var(--color-divider)">
        <div style="padding:20px 22px;border-right:var(--hair)">
          <div class="h3" style="font-size:14px">Training convergence</div>
          <p class="sub">Train RMSE over ${meta.training?.length ?? 30} epochs of mini-batch SGD.</p>
          ${convergence((meta.training || []).map((h) => h.train_rmse))}
        </div>
        <div style="padding:20px 22px">
          <div class="h3" style="font-size:14px">Fold-in for a new viewer</div>
          <p class="sub">Item factors stay frozen; only p<sub>u</sub> and b<sub>u</sub> are solved,
            as closed-form ridge regression.</p>
          <div class="score-only" id="foldBox" style="margin-top:14px;font-family:var(--mono);
            font-size:12px;line-height:2.1"></div>
        </div>
      </div>
    </div>`);
  body.append(holder);

  const space = await api.space(state.userId);
  $("#cloudCap", holder).textContent =
    `PC1 ${(space.explained[0] * 100).toFixed(1)}% · PC2 ${(space.explained[1] * 100).toFixed(1)}%`
    + ` · PC3 ${(space.explained[2] * 100).toFixed(1)}% — drag to orbit, scroll to zoom`;
  $("#foldBox", holder).innerHTML = [
    ["μ — global mean", fmt.n(meta.mu, 3)],
    ["b<sub>u</sub> — viewer bias", meta.fold_in ? fmt.signed(meta.fold_in.b_u, 3) : "from training"],
    ["‖p<sub>u</sub>‖", meta.fold_in ? fmt.n(meta.fold_in.p_u_norm, 3) : "learned"],
    ["factors", String(space.n_factors)],
  ].map(([k, v], i, arr) => `<div style="display:flex;justify-content:space-between;
      ${i < arr.length - 1 ? "border-bottom:var(--hair)" : ""}"><span>${k}</span><b>${v}</b></div>`).join("");

  scenes.mount("cvCloud", "cloud", space, { tipId: "cloudTip" });
  $("#cloudSeg", holder).addEventListener("click", (e) => {
    const b = e.target.closest("[data-k]");
    if (!b) return;
    $$("#cloudSeg button", holder).forEach((x) => x.classList.toggle("is-on", x === b));
    scenes.setFilter("cvCloud", b.dataset.k);
  });
}

async function orbitSection(body, state, d) {
  const top = d.items[0];
  const nb = (top?.explanation?.neighbours || []).slice(0, 8);
  body.insertAdjacentHTML("beforeend", `
    <div>
      <div class="sec-h"><div>
        <h2 class="h2">The neighbourhood, in orbit</h2>
        <p class="sub"><b>${esc(top?.title || "The top pick")}</b> sits at the centre. Each film you
          rated orbits at a radius of <b>1 − similarity</b>, and its size is the weight it carries in
          the prediction. The sum of those weighted deviations <i>is</i> the recommendation.</p>
      </div></div>
      <div class="scene">
        <canvas id="cvOrbit" style="height:430px"></canvas>
        <div class="scene__cap">radius = 1 − sim · mass = |sim × dev|</div>
      </div>
    </div>`);
  scenes.mount("cvOrbit", "orbit", { neighbours: nb });
}

async function neighbourSection(body, state) {
  const holder = el(`<div>
    <div class="sec-h"><div>
      <h2 class="h2">Your nearest neighbours</h2>
      <p class="sub">Viewers whose rating pattern most resembles yours, after significance shrinkage.
        Their favourites become your recommendations.</p>
    </div></div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr))" id="nbGrid"></div>
  </div>`);
  body.append(holder);
  const n = await api.neighbours(state.userId, 6);
  const max = Math.max(...n.neighbours.map((x) => x.similarity), 1e-6);
  $("#nbGrid", holder).innerHTML = n.neighbours.map((x) => `
    <div style="padding:18px 20px;border-right:var(--hair);border-bottom:var(--rule)">
      <div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px">
        <b class="h3">User ${x.userId}</b>
        <span class="mono score-only" style="font-size:12px;color:var(--color-accent-700);
          font-weight:700">sim ${fmt.n(x.similarity, 3)}</span>
      </div>
      <p class="sub">${x.co_rated ?? x.shared ?? 0} films in common · ${fmt.int(x.n_ratings)} ratings
        · mean ${fmt.n(x.mean, 1)}</p>
      <div class="film__meter score-only" style="height:8px;margin-top:11px">
        <i class="bar-grow" style="width:${fmt.clamp((x.similarity / max) * 100)};background:${INK}"></i></div>
      <div style="font-size:11px;color:var(--color-neutral-600);margin-top:9px;line-height:1.45">
        loved: ${esc((x.loved || []).map((f) => f.title).join(" · ")) || "—"}</div>
    </div>`).join("");
}

/* ═════════════════════════ 5 · HYBRID ═════════════════════ */
export async function hybrid(host, state) {
  host.innerHTML = `
    <div style="display:inline-flex;margin-bottom:16px">
      <span class="kicker kicker--accent">Approach 3</span>
      <span class="kicker kicker--ink">Hybrid</span>
    </div>
    <h1 class="display" style="margin-top:0">Each one covers the other's blind spot</h1>
    <p class="lede">Content-based filtering cannot surprise you; collaborative filtering cannot start.
      Blending them beats both — <b>Precision@10 of 0.0904</b> against 0.0840 for the best single
      collaborative model and 0.0228 for content alone.</p>

    <div class="seg" id="hStrat" style="margin-top:24px">
      ${segs([["weighted", "Weighted"], ["switching", "Switching"], ["rank", "Rank fusion"],
        ["cascade", "Cascade"]], state.strategy)}
    </div>

    <div class="panel" id="alphaPanel">
      <div style="display:flex;justify-content:space-between;align-items:baseline;gap:16px;flex-wrap:wrap">
        <span style="font-size:11px;letter-spacing:.14em;text-transform:uppercase;font-weight:800;
          color:var(--color-accent)">◈ Content</span>
        <span class="mono" style="font-size:19px;font-weight:700">α = <span id="aLabel">${state.alpha.toFixed(2)}</span></span>
        <span style="font-size:11px;letter-spacing:.14em;text-transform:uppercase;font-weight:800">Collaborative ◉</span>
      </div>
      <div class="alpha-wrap">
        <span class="alpha-track">
          <i id="aLeft" style="background:${RED};width:${state.alpha * 100}%"></i>
          <i style="background:${INK};flex:1"></i>
        </span>
        <input class="alpha" type="range" min="0" max="100" value="${Math.round(state.alpha * 100)}"
          id="aRange" aria-label="Blend weight alpha" />
      </div>
      <p class="mono" style="font-size:12.5px;color:var(--color-neutral-600);margin-top:14px"
        id="hFormula"></p>
      <p style="font-size:12.5px;color:var(--color-neutral-700);margin-top:8px;max-width:80ch"
        id="hNote"></p>
    </div>
    <div id="hBody"></div>`;

  $("#hStrat", host).addEventListener("click", (e) => {
    const b = e.target.closest("[data-k]");
    if (!b) return;
    state.strategy = b.dataset.k;
    hybrid(host, state);
  });
  const showAlpha = state.strategy === "weighted" || state.strategy === "rank";
  $("#alphaPanel", host).style.display = showAlpha ? "" : "none";

  const body = $("#hBody", host);
  let prevOrder = [];

  const range = $("#aRange", host);
  let debounce;
  range.addEventListener("input", (e) => {
    state.alpha = Number(e.target.value) / 100;
    $("#aLabel", host).textContent = state.alpha.toFixed(2);
    $("#aLeft", host).style.width = `${state.alpha * 100}%`;
    clearTimeout(debounce);
    debounce = setTimeout(draw, 200);
  });

  async function draw() {
    if (!body.childElementCount) body.append(loading("Blending"));
    const d = await api.hybrid(state.userId, {
      n: 10, strategy: state.strategy, cf_model: "item-knn", alpha: state.alpha,
    });
    if (d.empty) {
      body.innerHTML = "";
      body.append(emptyState("Nothing to blend yet", d.message, "Rate some films", () => state.go("rate")));
      return;
    }
    $("#hFormula", host).textContent = d.method.formula;
    $("#hNote", host).textContent = d.trace.reason || "";

    /* FLIP: record positions before replacing the list */
    const before = new Map();
    $$("[data-flip]", body).forEach((n) => before.set(n.dataset.flip, n.getBoundingClientRect().top));

    const moved = d.items.filter((f, i) => {
      const was = prevOrder.indexOf(f.movieId);
      return was >= 0 && was !== i;
    }).length;

    body.innerHTML = `
      <div class="sec-h">
        <div><h2 class="h2">Watch the ranking turn over</h2>
          <p class="sub">Drag α and the films physically slide up and down. If the two models agreed,
            nothing would move.</p></div>
        <span style="font-size:11px;color:var(--color-neutral-600)" class="score-only">
          ${moved ? `${moved} film${moved === 1 ? "" : "s"} moved` : "order held"}</span>
      </div>
      <div id="hList" style="border-bottom:var(--rule)"></div>

      <div class="sec-h"><div>
        <h2 class="h2">Where the blended list comes from</h2>
        <p class="sub">Content candidates on the left, collaborative on the right, flowing into the blend.</p>
      </div></div>
      <div class="chartbox score-only">${sankey(d.items)}</div>
      <div id="hOverlap" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
        border-left:2px solid var(--color-divider)"></div>`;

    const list = $("#hList", body);
    d.items.forEach((f, i) => {
      const was = prevOrder.indexOf(f.movieId);
      const move = was < 0 ? 0 : was - i;
      const total = (f.cf_part + f.content_part) || 1;
      const row = el(`
        <div class="hrow ${i === 0 ? "is-top" : ""}" data-flip="${f.movieId}">
          <span class="hrow__n">${i + 1}</span>
          <span class="hrow__m" style="color:${move > 0 ? RED : move < 0 ? "var(--color-neutral-500)" : "var(--color-neutral-300)"}">
            ${move > 0 ? "▲" : move < 0 ? "▼" : "·"}</span>
          <span class="hrow__t">
            <b>${esc(f.title)}</b>
            <small>${f.year || "—"} · ${esc((f.genres || []).slice(0, 2).join(" · "))}</small>
          </span>
          <span class="score-only" style="display:flex;align-items:center;gap:12px;flex:none">
            <span class="hrow__split">
              <i style="background:${RED};width:${(f.content_part / total) * 100}%"></i>
              <i style="background:${INK};width:${(f.cf_part / total) * 100}%"></i>
            </span>
            <span class="hrow__v">${fmt.n(f.score, 4)}</span>
          </span>
        </div>`);
      row.addEventListener("click", () => openDrawer(f, state));
      list.append(row);
    });

    /* FLIP: animate from the old position to the new one */
    if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
      $$("[data-flip]", list).forEach((n) => {
        const was = before.get(n.dataset.flip);
        if (was == null) return;
        const dy = was - n.getBoundingClientRect().top;
        if (!dy) return;
        n.animate([{ transform: `translateY(${dy}px)` }, { transform: "none" }],
          { duration: 380, easing: "cubic-bezier(.2,.8,.3,1)" });
      });
    }
    prevOrder = d.items.map((f) => f.movieId);

    const cmp = await api.hybridCompare(state.userId, "item-knn");
    const o = cmp.overlap || {};
    $("#hOverlap", body).innerHTML =
      cell(o.hybrid_from_both ?? 0, "picked by both")
      + cell(o.hybrid_from_cf_only ?? 0, "collaborative only")
      + cell(o.hybrid_from_content_only ?? 0, "content only")
      + cell(o.hybrid_from_neither ?? 0, "new in the blend");
  }

  await draw();
}

/* ═════════════════════════ 6 · SCOREBOARD ═════════════════ */
export async function score(host, state) {
  host.innerHTML = head("Analysis · Scoreboard", "kicker--outline",
    "Which one is best? It depends what you ask",
    `Every model is retrained on the same <b>80% training split</b> and scored on ratings it has never
     seen — the newest 20% of each viewer's history. A temporal split, not a random one: predicting a
     viewer's past from their future would be cheating.`) + `<div id="eBody"></div>`;

  const body = $("#eBody", host);
  body.append(loading("Scoring seven models across 610 viewers"));

  const d = await api.evaluation(10);
  const rows = d.rows;
  const best = (k, lower) => (lower ? Math.min : Math.max)(...rows.map((r) => r[k] ?? 0));
  const bests = {
    rmse: best("rmse", true), mae: best("mae", true), precision: best("precision"),
    ndcg: best("ndcg"), hit_rate: best("hit_rate"), coverage: best("coverage"), novelty: best("novelty"),
  };
  const td = (r, k, dgt = 4, suffix = "") => {
    const v = r[k];
    if (v === null || v === undefined) return "<td>—</td>";
    const isBest = Math.abs(v - bests[k]) < 1e-9;
    return `<td class="${isBest ? "best" : ""}">${Number(v).toFixed(dgt)}${suffix}</td>`;
  };
  const swatch = (fam) => fam === "hybrid" ? RED
    : fam === "content" ? "var(--color-accent-500)" : fam === "collaborative" ? INK : "var(--color-neutral-500)";

  body.innerHTML = `
    <div class="sec-h" style="margin-top:28px"><div>
      <h2 class="h2">Seven models, seven metrics</h2>
      <p class="sub">Each line is one model crossing all seven axes, normalised so up is always better.
        Crossing lines are trade-offs: no model wins everywhere. Hover a table row to isolate its line.</p>
    </div></div>
    <div class="chartbox score-only" id="parBox">${parallel(rows)}</div>
    <div class="tablewrap">
      <table class="tbl">
        <thead><tr>
          <th>Model</th><th>RMSE ↓</th><th>MAE ↓</th><th>Prec@10 ↑</th><th>NDCG@10 ↑</th>
          <th>Hit rate ↑</th><th>Coverage</th><th>Novelty</th>
        </tr></thead>
        <tbody id="evalBody">
          ${rows.map((r) => `
            <tr data-model="${esc(r.model)}">
              <td><span class="name"><i style="background:${swatch(r.family)}"></i>${esc(r.label)}</span></td>
              ${td(r, "rmse")}${td(r, "mae")}${td(r, "precision")}${td(r, "ndcg")}${td(r, "hit_rate")}
              <td>${fmt.n(r.coverage, 1)}%</td><td>${fmt.n(r.novelty, 2)}</td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>

    <div class="bandred">
      <div class="bandred__k">Read the table sideways, not down</div>
      <h3>The hybrid beats both of its own parents. That is the whole argument.</h3>
      <p>Content + item-kNN scores <b>0.0904</b> Prec@10 against 0.0840 for item-kNN alone and 0.0228
        for content alone. SVD has the best RMSE of any single model yet ranks worse than item-kNN,
        which in turn predicts ratings worse than the trivial bias baseline. Optimising one does not
        give you the other.</p>
    </div>`;

  const box = $("#parBox", body);
  $("#evalBody", body).addEventListener("mouseover", (e) => {
    const tr = e.target.closest("[data-model]");
    if (tr) box.innerHTML = parallel(rows, tr.dataset.model);
  });
  $("#evalBody", body).addEventListener("mouseleave", () => { box.innerHTML = parallel(rows); });
}

/* ═════════════════════════ 7 · PEOPLE ═════════════════════ */
export async function people(host, state) {
  host.innerHTML = head("Analysis · Compare viewers", "kicker--outline",
    "Same algorithm, different people, different films",
    `Personalisation is easy to claim and easy to fake. Run one algorithm across several viewers at
     once and the differences — or the lack of them — become obvious.`) + `
    <div class="seg" id="pSeg" style="margin-top:24px">
      ${segs([["content", "◈ Content"], ["collaborative", "◉ Collaborative"], ["hybrid", "◆ Hybrid"]],
        state.compareMethod)}
    </div>
    <div style="margin-top:16px" id="pPick"></div>
    <div id="pBody"></div>`;

  $("#pSeg", host).addEventListener("click", (e) => {
    const b = e.target.closest("[data-k]");
    if (!b) return;
    state.compareMethod = b.dataset.k;
    people(host, state);
  });

  const users = await api.users();
  const pool = [...users.custom, ...users.builtin.slice(0, 10)];
  if (!state.comparePicks.length) state.comparePicks = pool.slice(0, 3).map((u) => u.userId);

  const pick = $("#pPick", host);
  pick.innerHTML = `<div style="display:flex;flex-wrap:wrap;gap:0">
    ${pool.map((u) => `<button class="btn ${state.comparePicks.includes(u.userId) ? "btn--primary" : "btn--ghost"}"
      data-u="${u.userId}" style="margin:0 -2px -2px 0">${esc(u.name.replace("MovieLens ", ""))}</button>`).join("")}
  </div>`;
  pick.addEventListener("click", (e) => {
    const b = e.target.closest("[data-u]");
    if (!b) return;
    const id = Number(b.dataset.u);
    const at = state.comparePicks.indexOf(id);
    if (at >= 0) state.comparePicks.splice(at, 1);
    else if (state.comparePicks.length < 4) state.comparePicks.push(id);
    else { toast("Four viewers is the maximum"); return; }
    people(host, state);
  });

  const body = $("#pBody", host);
  if (state.comparePicks.length < 2) {
    body.append(emptyState("Pick at least two viewers",
      "Select viewers above to compare their recommendations side by side."));
    return;
  }
  body.append(loading("Running the model for each viewer"));

  const d = await api.compareUsers(state.comparePicks, state.compareMethod, 6);
  const shared = new Set(d.shared || []);
  const sets = d.columns.map((c) => ({ name: c.name, ids: c.items.map((f) => f.movieId) }));

  body.innerHTML = `
    <div class="sec-h"><div>
      <h2 class="h2">Where the lists overlap</h2>
      <p class="sub">The intersections are the broadly-loved classics that survive any taste profile;
        the outer lobes are the personalisation actually doing something.</p>
    </div></div>
    <div class="chartbox">${venn(sets)}</div>
    <div class="three-up" style="margin-top:30px;border-top:var(--rule)">
      ${d.columns.map((c) => `
        <div>
          <div class="h3" style="font-size:16px">${esc(c.name)}</div>
          <p class="sub">${fmt.int(c.n_ratings)} ratings ·
            ${esc(c.top_genres.map((g) => g.genre).join(", ") || "no dominant genre")}</p>
          <div style="margin-top:14px">
            ${c.items.map((f, i) => `
              <div style="display:flex;align-items:center;gap:10px;padding:9px 0;border-top:var(--hair)">
                <span class="mono" style="width:16px;flex:none;font-size:11px;
                  color:var(--color-neutral-500)">${i + 1}</span>
                <span style="flex:1;min-width:0;font-size:12.5px;font-weight:600;white-space:nowrap;
                  overflow:hidden;text-overflow:ellipsis;${shared.has(f.movieId)
                    ? `color:${RED};font-weight:800` : ""}">${esc(f.title)}</span>
                <span class="mono score-only" style="font-size:11px;color:var(--color-neutral-600)">
                  ${fmt.n(f.score, 3)}</span>
              </div>`).join("")}
          </div>
        </div>`).join("")}
    </div>`;
}
