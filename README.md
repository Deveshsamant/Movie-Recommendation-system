# Movie Recommendation System

**Content-based · Collaborative · Hybrid — all three built on the same data, with the arithmetic
behind every recommendation shown on screen.**

Most recommender demos hand you a list and ask you to trust it. This one shows its working: every
score can be expanded into the exact terms, neighbours or latent factors that produced it, and the
three approaches are kept visibly separate so you can watch them disagree.

![Browse](docs/screenshots/01-browse.png)

---

## Contents

- [Quick start](#quick-start)
- [The data — every number](#the-data--every-number)
- [The TMDB API key](#the-tmdb-api-key)
- [Algorithms](#algorithms)
- [Measured results](#measured-results)
- [The interface](#the-interface)
- [Project layout](#project-layout)
- [Configuration](#configuration)
- [Licence and credits](#licence-and-credits)

---

## Quick start

```bash
git clone https://github.com/Deveshsamant/Movie-Recommendation-system.git
cd Movie-Recommendation-system
pip install -r requirements.txt
```

Add a TMDB key so posters load (see [below](#the-tmdb-api-key) — the app runs without one, just
without artwork):

```bash
cp config.example.json config.json
```

Then run it:

```bash
python run.py
```

Open <http://localhost:8000>.

**First run** downloads MovieLens (~1 MB) and trains every model — about **two minutes**. Everything
is cached to `cache/`, so later starts take **1–2 seconds**.

Requires **Python 3.9+**. Dependencies: FastAPI, uvicorn, pandas, numpy, scipy, scikit-learn,
requests. No Node, no build step — the front end is plain ES modules.

---

## The data — every number

The dataset is **MovieLens `ml-latest-small`** from GroupLens Research at the University of
Minnesota. It downloads automatically on first run from `files.grouplens.org`; it is **not**
committed to this repo.

| Quantity | Value |
|---|---|
| Viewers (users) | **610** |
| Films | **9,724** |
| Ratings | **100,836** |
| Matrix cells | 610 × 9,724 = **5,931,640** |
| Cells actually filled | **1.7%** — the other **98.3%** is what the models guess |
| Rating scale | **0.5 – 5.0** in half-star steps |
| Mean rating | **3.502** |
| Genres | **19** |
| Ratings per viewer | minimum **20**, median **70**, maximum **2,698** |
| Community tags | **3,683** |

### Train / test split

| | |
|---|---|
| Training ratings | **80,672** (80%) |
| Held-out ratings | **20,164** (20%) |
| Method | **per-user temporal holdout** — the newest 20% of *each* viewer's history |
| Counts as a hit | held-out rating **≥ 4.0** |

The split is temporal, not random, on purpose. A random split lets the model see a viewer's future
while predicting their past, which flatters every number in the results table. Expect these RMSEs to
look slightly worse than published random-split figures — they are measuring a harder question.

### Metadata scale

| | |
|---|---|
| Distinct terms in the content model | **21,789** |
| Non-zero term weights | **190,614** |
| Average terms per film | **19.6** (5.0 on MovieLens genres and tags alone) |
| Films enriched from TMDB | **9,700 of 9,724** (99.75%) |

---

## The TMDB API key

Posters, synopses, cast, directors and keywords come from **[TMDB](https://www.themoviedb.org/)**.
That metadata is not decoration — the keywords, cast and crew are literally part of the vector the
content-based model scores against, which is what takes it from 5.0 to 19.6 terms per film.

**No key is committed to this repository.** `config.json` is in `.gitignore`. Get your own free key
from [TMDB → Settings → API](https://www.themoviedb.org/settings/api), then either:

```bash
cp config.example.json config.json      # paste your key into "tmdb_api_key"
```

or set an environment variable and skip the file entirely:

```bash
export TMDB_API_KEY=your_key_here       # Windows: set TMDB_API_KEY=your_key_here
```

Without a key the app still runs end to end — every algorithm, metric and explanation works. You
just get title placeholder cards instead of posters.

### If TMDB looks unreachable

Several ISPs — notably a number in India — DNS-poison `api.themoviedb.org` while leaving the image
CDN reachable. The client handles this automatically, trying three routes in order:

1. `api.themoviedb.org` (normal)
2. `api.tmdb.org` (the legacy alias, usually not blocked)
3. the real IP, resolved over **DNS-over-HTTPS**, connected with pinned SNI and full certificate
   verification

Whichever route works is remembered for a day and shown in the sidebar. If all three fail, the app
degrades to placeholder cards rather than breaking.

**A note on dead IDs.** MovieLens' `links.csv` was generated years ago, so **106** of its TMDB IDs
now return 404 — entries have been merged or re-issued, and miniseries such as *Roots* and
*Generation War* were never in the movie namespace at all. When an ID fails, the client searches
TMDB by title and year across both `/movie` and `/tv`. That recovered **91 of the 106**; the
remaining **15** get a deliberate placeholder card. To re-run the repair:

```bash
python backend/enrich.py --repair
```

---

## Algorithms

### 1 · Content-based filtering

Reads *down a column* — what a film **is**, never what anyone thought of it.

Each film becomes a bag of weighted terms, then TF-IDF with sublinear term frequency, L2-normalised
so cosine similarity reduces to a plain dot product.

| Term source | Weight |
|---|---|
| Genres | ×3 |
| Community tags | ×2 |
| TMDB keywords | ×2 |
| Director | ×2 |
| Cast (top 6) | ×1 |
| Decade, title words | ×1 |

Your profile is a **Rocchio vector**: films rated above your personal mean pull the profile toward
them, films below push it away, weighted by `(rᵢ − mean) / sd`.

```
profile = normalise( Σᵢ (rᵢ − mean_u)/sd_u × vᵢ )
score(j) = cos(profile, vⱼ) = Σₜ profile[t] × tfidf_j[t]
```

Because that is a dot product, each shared term's contribution is an exact number that sums to the
score — which is what the explanation panel shows.

### 2 · Collaborative filtering

Reads *across rows* — who rated what, ignoring entirely what a film is about. Three models:

**Item-based kNN** (Sarwar et al., 2001) — adjusted-cosine similarity. Ratings are mean-centred per
user first, which cancels the "this person rates everything a 4" effect. Similarities are shrunk
toward zero by co-rater count so a similarity backed by 3 people cannot outrank one backed by 300.

```
sim'(i,j) = sim(i,j) × n_common / (n_common + λ)          k = 40, λ = 25
r̂(u,i)   = mean_u + Σⱼ sim(i,j)(r_uj − mean_u) / Σⱼ |sim(i,j)|
```

Stored similarities: **386,434** (top 40 neighbours per film).

**User-based kNN** (Resnick et al., GroupLens 1994) — Pearson correlation over a fixed neighbourhood
of the k=40 most similar viewers, same shrinkage.

**Matrix factorisation — BiasSVD** (Funk / Koren 2009), written from scratch in NumPy and trained by
mini-batch SGD with L2 regularisation and a decaying learning rate.

```
r̂(u,i) = μ + b_u + b_i + p_u · q_i
```

| Hyper-parameter | Value |
|---|---|
| Latent factors | **50** |
| Epochs | **30** |
| Learning rate | **0.007** (decayed) |
| L2 regularisation | **0.02** |
| Seed | 42 |
| Final train RMSE | 0.664 |

Chosen by sweep over `n_factors ∈ {20, 50, 100} × reg ∈ {0.02, 0.05, 0.10} × epochs ∈ {20, 30, 60}`.
Past 30 epochs it overfits — training RMSE keeps falling while test RMSE rises.

A **brand-new viewer** is served by **fold-in**: item factors stay frozen and only `p_u`, `b_u` are
solved, as a closed-form ridge regression alternated with the bias update. No retraining.

```
p = (Qᵣᵀ Qᵣ + λI)⁻¹ Qᵣᵀ e      where e = r − μ − b_u − b_i
```

### 3 · Hybrid

Four strategies from Burke's (2002) taxonomy:

| Strategy | What it does |
|---|---|
| **Weighted** | min–max normalise both signals to [0,1], blend by α |
| **Switching** | pick a model per viewer based on how much evidence exists |
| **Rank fusion** | reciprocal rank fusion — ignores score scales entirely |
| **Cascade** | collaborative shortlists candidates, content re-ranks inside it |

```
score = α · norm(CF) + (1 − α) · norm(content)         α = 0.70
```

α = 0.70 was chosen by sweeping α ∈ {0, 0.3, 0.5, 0.7, 0.85, 1.0} against NDCG@10. Below 8 ratings
the switching hybrid falls back to content, because collaborative evidence is too thin to trust.

### One deliberate design decision

**Ranking and rating prediction use different scoring rules**, and the app is explicit about it.

Ranking a top-N list by predicted rating is a well-known trap: clipping to 5.0 creates hundreds of
exact ties, and dividing by the sum of similarities lets an item supported by one weak neighbour tie
with genuinely strong picks. Fixing this moved item-kNN's Prec@10 from **0.002 to 0.084** — a 38×
difference from one modelling choice.

So each model exposes both:

- `rank_all` — raw evidence strength, used to order the list
- `score_all` — the clipped, normalised rating a person would recognise

Both paths are verified to produce identical numbers where they overlap, so the maths shown on
screen is always the maths the ranking actually used.

---

## Measured results

Every model retrained on the same 80% split, scored on ratings it has never seen. `k = 10`.

| Model | RMSE ↓ | MAE ↓ | Prec@10 ↑ | NDCG@10 ↑ | Hit rate ↑ | Coverage | Novelty |
|---|---|---|---|---|---|---|---|
| Bias baseline | 0.9044 | 0.6995 | 0.0446 | 0.0535 | 0.2652 | 0.7% | 2.38 |
| Content-based (TF-IDF) | 0.9293 | 0.7119 | 0.0228 | 0.0282 | 0.1841 | **18.4%** | **6.84** |
| Item-based kNN | 0.9376 | 0.7016 | 0.0840 | 0.1104 | 0.4139 | 6.0% | 2.53 |
| User-based kNN | 0.9396 | 0.7148 | 0.0828 | 0.1081 | **0.4544** | 2.7% | 2.05 |
| Matrix factorisation (SVD) | 0.8893 | 0.6830 | 0.0285 | 0.0329 | 0.2027 | 2.2% | 4.12 |
| **Hybrid (content + item-kNN)** | 0.8933 | 0.6729 | **0.0904** | **0.1167** | 0.4307 | 6.5% | 2.61 |
| **Hybrid (content + SVD)** | **0.8683** | **0.6650** | 0.0346 | 0.0426 | 0.2196 | 2.5% | 4.04 |

![Scoreboard](docs/screenshots/05-scoreboard.png)

**Three things worth reading out of that table:**

1. **The hybrid beats both of its own parents.** Content + item-kNN scores **0.0904** Prec@10
   against **0.0840** for item-kNN alone and **0.0228** for content alone. That is the entire
   argument for hybrid recommenders, measured rather than asserted.

2. **Rating accuracy and ranking quality are different problems.** SVD has the best RMSE of any
   single model yet ranks worse than item-kNN — which in turn predicts ratings worse than the
   trivial bias baseline. Optimising one does not give you the other.

3. **Accuracy is not the only axis.** The content model loses almost every accuracy column but has
   **8× the catalogue coverage** and by far the highest novelty. It is the only model reaching past
   the blockbusters — and the only one that works on a viewer's very first rating.

### What each metric means

| Metric | Question it answers |
|---|---|
| **RMSE / MAE** | When it predicted 4.2, how close was the real rating? |
| **Precision@10** | Of the 10 films shown, how many did the viewer go on to rate ≥ 4? |
| **Recall@10** | Of everything they went on to love, how much did the top 10 catch? |
| **NDCG@10** | Like precision, but rewards putting the good films *higher* |
| **Hit rate** | Fraction of viewers who got at least one good film in their top 10 |
| **Coverage** | Share of the 9,724-film catalogue ever recommended to anyone |
| **Novelty** | Mean −log₂(popularity) — higher means digging into the long tail |

---

## The interface

Eight views. Light and dark, following your OS until you pick a side.

| View | What it shows |
|---|---|
| **Browse** | A streaming front page where every shelf is a different algorithm |
| **The data** | The rating matrix itself, and why 98.3% empty is the whole problem |
| **Rate films** | Search the catalogue and build your own profile |
| **Content-based** | Your taste vector, genre radar, and picks with per-term maths |
| **Collaborative** | Item-kNN, user-kNN and SVD, each with its own visualisation |
| **Hybrid** | The α slider, an alluvial diagram, and the blended ranking |
| **Scoreboard** | Seven models across seven metrics |
| **Compare viewers** | The same algorithm run across several people at once |

### Browse

Every row is a different recommender, arranged as a streaming front page: a billboard hero, a
rotating 3D shelf of the hybrid top ten, one rail per approach — including a long-tail rail that
**only** content-based filtering can reach — and a Top 10.

![Browse shelves](docs/screenshots/02-browse-shelves.png)

**Play** opens a reel: the hybrid top ten as an auto-advancing slideshow. Each slide carries the
TMDB synopsis and genres, names which approach carried that pick and why, and shows all three scores
side by side.

![Play reel](docs/screenshots/06-reel.png)

### Explaining a single pick

Click any poster. The drawer opens on **Info** — synopsis, director, full cast, TMDB rating, runtime,
keywords — with three more tabs breaking that same pick down under each approach: term by term,
neighbour by neighbour, factor by factor.

![Film drawer](docs/screenshots/07-drawer.png)

### Two visualisations that carry real structure

**The 50-dimensional space it invented** *(Collaborative → Matrix factorisation)* — the item factor
matrix **Q** (9,724 × 50) projected to 3D by PCA. Drag to orbit, scroll to zoom. Films you rated are
red, and your own vector **p_u** is drawn into the same space. Nobody labelled these axes; the
factorisation built them purely to compress the rating matrix, yet they land on recognisable
clusters.

![Latent factor space](docs/screenshots/04-latent-space.png)

**The neighbourhood, in orbit** *(Collaborative → Item-based kNN)* — the target film at the centre,
each film you rated orbiting at radius `1 − similarity`, its size the weight it carries. The sum of
those weighted deviations *is* the prediction.

### Cold start, watchable

Create your own viewer and rate films one at a time. Content-based filtering works from your **first**
rating; collaborative filtering needs roughly **3**; below **8** the hybrid falls back to content and
says so. The sidebar meter tracks it.

![Rate films](docs/screenshots/03-rate.png)

### Show scores & maths

A global toggle. Off hides every score, badge and derivation for clean browsing; on reveals the full
arithmetic everywhere.

---

## Project layout

```
config.example.json    copy to config.json and add your TMDB key
run.py                 launcher
backend/
  app.py               FastAPI routes
  engine.py            builds and holds every model
  dataset.py           MovieLens download, indexing, temporal split
  content_based.py     TF-IDF + Rocchio profiles + exact score decomposition
  collaborative.py     ItemKNN, UserKNN, BiasSVD, bias baseline
  hybrid.py            the four blending strategies
  evaluate.py          RMSE/MAE, Prec/Recall/MAP/NDCG, coverage, novelty, diversity
  tmdb.py              poster client: route failover, title-search recovery, disk cache
  enrich.py            background metadata warmer (--repair retries dead IDs)
frontend/              no build step — plain ES modules
  css/app.css          design system, light + dark
  js/app.js            shell: state, routing, sidebar, new-viewer modal
  js/views.js          the eight views
  js/scenes.js         canvas 3D — factor cloud and neighbourhood orbits
  js/drawer.js         per-film explanation drawer
  js/reel.js           the play reel
  js/ui.js             shared primitives and hand-rolled SVG charts
design/                the source Claude Design canvas
data/                  MovieLens (downloaded, gitignored)
cache/                 trained models, metrics, TMDB metadata, your viewers (gitignored)
```

Two sets of collaborative models are kept: **serving** models trained on all 100,836 ratings, and
**evaluation** models trained on the 80% split only — so nothing is ever scored on data it trained
on.

---

## Configuration

Everything lives in `config.json` (copied from `config.example.json`).

| Key | Default | Notes |
|---|---|---|
| `tmdb_api_key` | `""` | yours; or use the `TMDB_API_KEY` env var |
| `posters_enabled` | `true` | auto-disabled if no key is found |
| `dataset` | `ml-latest-small` | also accepts `ml-25m` — downloads and trains automatically, much longer first run |
| `port` | `8000` | |
| `svd.n_factors` | `50` | |
| `svd.n_epochs` | `30` | past this it overfits |
| `svd.lr` / `svd.reg` | `0.007` / `0.02` | |
| `knn.k_neighbors` | `40` | |
| `knn.shrinkage` | `25` | significance shrinkage λ |
| `hybrid.alpha` | `0.7` | 0 = pure content, 1 = pure collaborative |
| `hybrid.cold_start_threshold` | `8` | below this, switching falls back to content |

Delete `cache/` to force a full retrain. Note that also deletes `custom_users.json` — the viewers
you built yourself.

---

## Licence and credits

Released under the **[MIT License](LICENSE)**.

**Data** — [MovieLens](https://grouplens.org/datasets/movielens/) `ml-latest-small`, GroupLens
Research, University of Minnesota. Downloaded at runtime, not redistributed here.

**Metadata and posters** — [TMDB](https://www.themoviedb.org/). This product uses the TMDB API but
is not endorsed or certified by TMDB.

**Papers the models come from**

- Sarwar, Karypis, Konstan & Riedl (2001) — *Item-Based Collaborative Filtering Recommendation
  Algorithms*
- Resnick, Iacovou, Suchak, Bergstrom & Riedl (1994) — *GroupLens: An Open Architecture for
  Collaborative Filtering of Netnews*
- Koren, Bell & Volinsky (2009) — *Matrix Factorization Techniques for Recommender Systems*
- Deshpande & Karypis (2004) — *Item-Based Top-N Recommendation Algorithms*
- Burke (2002) — *Hybrid Recommender Systems: Survey and Experiments*

Built by **[Devesh Samant](https://github.com/Deveshsamant)**.
