# Design prompt — 3D / motion / creative data-viz redesign

Copy everything below the line into Claude Code, run from inside
`E:\Movie Recomendation System`.

---

## The brief

You are redesigning the front-end of an existing, working recommender-system lab. The backend and
all the algorithms are finished and correct — **do not change them**. This is a visual and
interaction redesign only.

### What the app is

A teaching tool that builds three families of movie recommender on MovieLens 100K (610 viewers,
9,724 films, 100,836 ratings) and shows the exact arithmetic behind every recommendation:

- **Content-based** — TF-IDF over genres/tags/TMDB keywords/cast/crew, cosine similarity against a
  Rocchio taste vector.
- **Collaborative** — item-kNN (adjusted cosine), user-kNN (Pearson), and BiasSVD
  (`r̂ = μ + b_u + b_i + p_u·q_i`) with 50 latent factors.
- **Hybrid** — weighted / switching / rank-fusion / cascade blending of the two.

Seven views: `overview` (rating matrix), `ratings` (search & rate), `content`, `collaborative`,
`hybrid`, `evaluate` (metrics table), `people` (compare viewers).

### Current stack — keep it

- `frontend/` is **plain ES modules, no build step**. `index.html`, `css/app.css`,
  `js/{app,api,ui,views,drawer}.js`. Served by FastAPI at `/static`.
- Read `frontend/js/api.js` for the full API surface, and `backend/app.py` for response shapes.
  Every endpoint already returns the numbers you need — do not invent data.
- Dark theme, three accent hues that must survive: content `#f7a53b`, collaborative `#3ddbd9`,
  hybrid `#a78bfa`.

Keep the no-build-step property. If you need a 3D library, vendor it into `frontend/js/vendor/`
as an ES module rather than adding a bundler or a CDN `<script>` tag — the app must work on a
network that blocks third-party hosts.

## Hard constraints — breaking any of these is a failed redesign

1. **The maths must stay correct and stay visible.** Every score shown must be the score the backend
   actually returned. Never round in a way that changes meaning, never fabricate a value to make an
   animation smoother.
2. **The `Show scores & maths` toggle must keep working.** It flips `data-scores` on `<html>`;
   everything numeric carries `.score-only`. New visualisations must respect it — a chart made of
   scores is a score.
3. **No horizontal page scroll at any width.** The current CSS uses `minmax(0,1fr)` and
   `min-width:0` on grid items specifically to stop wide tables stretching the shell. Keep that.
4. **Respect `prefers-reduced-motion`.** Every animation needs a reduced-motion path that still
   communicates the same information. Motion is not allowed to be the only channel.
5. **Keep it fast.** Views currently render in well under a second. Target 60fps; never block the
   main thread on a render.

## What to build

### 1. Real 3D where 3D means something

Use 3D where it carries information, not as decoration. Three genuinely earn it:

**Latent factor space (`collaborative` view).** The SVD learns a 50-dimensional item space —
`engine.svd.Q` is a 9724×50 matrix. Project it to 3D with PCA and render every film as a point you
can orbit, zoom and hover. Highlight the active viewer's rated films, and draw their `p_u` vector
into the same space so you can *see* why the dot product ranks what it ranks. Clusters here are real
— the model discovers genre-ish structure with no metadata at all, and that is the single most
convincing thing this app can show.

You will need a new endpoint for this. Add `GET /api/svd/space` to `backend/app.py` returning the
PCA-projected coordinates plus title/genre/popularity per point, and the projected user vector.
Compute the PCA once at engine build and cache it. This is the one backend addition you may make.

**Rating matrix (`overview` view).** Currently a flat 26×40 heatmap. Make it a 3D height-field
where bar height is the rating and gaps are visibly, physically empty — the 98.3% sparsity should
feel like a mostly-empty city block. Let it rotate slowly, and let the user tilt it.

**Neighbourhood orbits (`collaborative` view).** For item-kNN, put the target film at the centre and
its k neighbours in orbit, orbital radius mapped to `1 − similarity`. The prediction is a weighted
sum over those neighbours; show the weights as the visual mass of each orbiting body.

Everything else should stay 2D. Resist 3D pie charts, extruded bar charts, and rotating cards that
exist only to rotate.

### 2. Motion that explains

- **Shared-element transitions between views.** A film poster clicked in a grid should travel into
  the drawer rather than the drawer appearing over it. Use the View Transitions API where available,
  FLIP as the fallback.
- **The α slider on the `hybrid` view is the centrepiece.** Right now dragging it re-renders a list.
  It should *morph*: films should physically slide up and down the ranking as α moves from pure
  content to pure collaborative, so you watch the two models disagree in real time. FLIP-animate the
  reorder. This is the clearest possible demonstration of what a hybrid does.
- **Score bars should count up** from zero on first paint, with the number tweening alongside.
- **The maths panels should assemble term by term** — stagger each row of a TF-IDF decomposition or
  a kNN neighbour sum by ~40ms so the reader's eye follows the summation.
- **Skeletons should morph into content**, not swap.

### 3. Creative data visualisation, per view

Replace the current plain bars and table with something worth looking at:

| View | Now | Make it |
|---|---|---|
| `overview` | flat heatmap | 3D sparsity field; a "fill in the blanks" animation showing what each approach guesses |
| `content` | radar + bar rows | a force-directed term cloud where your taste vector's strongest dimensions attract the films they explain |
| `collaborative` | sparkline + rows | the 3D factor space above, plus an animated SGD convergence curve that redraws epoch by epoch |
| `hybrid` | split bars | a Sankey or alluvial diagram: content candidates on the left, collaborative on the right, flowing into the blended ranking |
| `evaluate` | HTML table | keep the table (it is precise and scannable) but add a parallel-coordinates plot above it, one line per model across all seven metrics, so the trade-offs are visible as crossing lines |
| `people` | poster columns | a set-overlap / Venn-style view of whose recommendations intersect |

Write the charts yourself in SVG or WebGL. Do not pull in a charting library — the existing hand-
rolled SVG helpers in `js/ui.js` are the pattern to follow.

### 4. Responsive

Currently breaks at 1080px (sidebar becomes a top bar) and 560px. Improve it:

- The 3D scenes need a genuine touch story: one finger orbits, two fingers zoom. On very small
  screens or low-power devices, fall back to the 2D version rather than shipping a janky canvas.
- The sidebar should become a proper bottom tab bar on phones, not a wrapped row.
- Test at 375px, 768px, 1280px and 1920px. Confirm zero horizontal overflow at each.

## How to work

1. Read `frontend/js/views.js` and `frontend/css/app.css` first. Read `README.md` for what each
   number means — you will be labelling these charts and the labels have to be right.
2. Start the app with the `movie-recommender` config in `.claude/launch.json` and keep it running.
3. Redesign one view at a time, verifying each in the browser before moving on: check the console
   for errors, confirm no horizontal overflow, and screenshot the result.
4. Bump the `?v=` query on the CSS and JS links in `index.html` whenever you change them — the
   browser caches them aggressively and stale assets have bitten this project before.
5. When all seven views are done, do a final pass at all four widths plus reduced-motion.

Show me each view as you finish it rather than saving everything for the end.
