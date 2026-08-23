"""FastAPI application: one endpoint per idea the UI needs to show.

Every recommendation endpoint returns both the ranked list *and* the arithmetic
behind it, so the front-end never has to invent an explanation.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import enrich
import tmdb
from config import CONFIG, FRONTEND_DIR
from engine import Engine

app = FastAPI(title="Movie Recommender System - Content, Collaborative & Hybrid", version="1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


def _register_numpy_encoders() -> None:
    """Teach FastAPI's encoder about numpy scalars.

    Every handler casts to native Python already, but one stray np.float64 would
    otherwise turn into a 500 at serialisation time. This is the safety net.
    """
    try:
        from fastapi import encoders

        extra = {
            np.integer: int, np.floating: float, np.bool_: bool,
            np.ndarray: lambda a: a.tolist(),
        }
        encoders.ENCODERS_BY_TYPE.update(extra)
        encoders.encoders_by_class_tuples = encoders.generate_encoders_by_class_tuples(
            encoders.ENCODERS_BY_TYPE
        )
    except Exception:
        pass


_register_numpy_encoders()

ENGINE: Engine | None = None


def eng() -> Engine:
    if ENGINE is None:
        raise HTTPException(503, "engine still starting")
    return ENGINE


@app.on_event("startup")
def _startup() -> None:
    global ENGINE
    ENGINE = Engine(verbose=True)
    if CONFIG.get("posters_enabled", True):
        ENGINE.start_enrichment()
    ENGINE.warm_evaluation()


# --------------------------------------------------------------------------- #
# meta
# --------------------------------------------------------------------------- #
@app.get("/api/status")
def status():
    return eng().status()


@app.post("/api/enrich/start")
def enrich_start():
    started = eng().start_enrichment()
    return {"started": started, "status": enrich.status()}


@app.get("/api/enrich/status")
def enrich_status():
    return enrich.status()


@app.post("/api/content/rebuild")
def content_rebuild():
    return eng().rebuild_content()


# --------------------------------------------------------------------------- #
# users
# --------------------------------------------------------------------------- #
class NewUser(BaseModel):
    name: str = ""
    ratings: dict = {}


class RatingIn(BaseModel):
    movieId: int
    rating: float | None = None


@app.get("/api/users")
def list_users(limit: int = 80):
    return eng().list_users(limit=limit)


@app.post("/api/users")
def create_user(payload: NewUser):
    return eng().create_custom_user(payload.name, payload.ratings)


@app.delete("/api/users/{user_id}")
def delete_user(user_id: int):
    return {"deleted": eng().delete_custom_user(user_id)}


@app.post("/api/users/{user_id}/ratings")
def set_rating(user_id: int, payload: RatingIn):
    e = eng()
    try:
        user = e.set_custom_rating(user_id, payload.movieId, payload.rating)
    except KeyError:
        raise HTTPException(404, "only viewers you created can be re-rated")
    return {
        "userId": user["userId"],
        "n_ratings": len(user["ratings"]),
        "readiness": _readiness(e, len(user["ratings"])),
    }


class RenameIn(BaseModel):
    name: str


@app.patch("/api/users/{user_id}")
def rename_user(user_id: int, payload: RenameIn):
    try:
        user = eng().rename_custom_user(user_id, payload.name.strip())
    except KeyError:
        raise HTTPException(404, "custom user not found")
    return {"userId": user["userId"], "name": user["name"]}


def _readiness(e: Engine, n: int) -> dict:
    """What each approach can actually do with this many ratings."""
    threshold = e.cfg["hybrid"]["cold_start_threshold"]
    return {
        "n_ratings": n,
        "cold_start_threshold": threshold,
        "content": n >= 1,
        "collaborative": n >= 3,
        "hybrid_uses_cf": n >= threshold,
        "message": (
            "Rate a film to switch content-based filtering on."
            if n < 1
            else "Content-based filtering is working. Collaborative filtering needs a few more."
            if n < 3
            else "Both approaches are running, but the hybrid still falls back to content below %d." % threshold
            if n < threshold
            else "All three approaches have enough to work with."
        ),
    }


@app.get("/api/users/{user_id}/ratings")
def list_ratings(user_id: int, limit: int = 60):
    """A viewer's ratings, highest first.

    Capped by default: the busiest MovieLens viewer has 2,698 ratings, and
    hydrating a poster for every one of them costs six seconds for a grid nobody
    scrolls to the bottom of.
    """
    e = eng()
    rated = e.rated_map(user_id)
    if not rated and not e.is_custom(user_id):
        raise HTTPException(404, "user not found")
    ordered = sorted(rated.items(), key=lambda kv: -kv[1])[: max(1, min(limit, 300))]
    e.hydrate_posters([m for m, _ in ordered])
    return {
        "userId": int(user_id),
        "editable": e.is_custom(user_id),
        "n_ratings": len(rated),
        "readiness": _readiness(e, len(rated)),
        "items": [e.movie_card(m, {"your_rating": r}) for m, r in ordered],
    }


@app.get("/api/users/{user_id}")
def user_detail(user_id: int, top: int = 12):
    e = eng()
    rated = e.rated_map(user_id)
    if not rated and not e.is_custom(user_id):
        raise HTTPException(404, "user not found")

    ordered = sorted(rated.items(), key=lambda kv: -kv[1])[:top]
    e.hydrate_posters([m for m, _ in ordered])
    values = list(rated.values())
    name = (
        e.custom_users[int(user_id)]["name"]
        if e.is_custom(user_id) and int(user_id) in e.custom_users
        else "MovieLens user %d" % int(user_id)
    )
    return {
        "userId": int(user_id),
        "name": name,
        "custom": e.is_custom(user_id),
        "n_ratings": len(rated),
        "avg_rating": round(float(np.mean(values)), 2) if values else 0.0,
        "rating_spread": round(float(np.std(values)), 2) if values else 0.0,
        "genre_profile": e.content.genre_profile(rated),
        "top_rated": [
            e.movie_card(m, {"your_rating": r}) for m, r in ordered
        ],
        "histogram": _histogram(values),
    }


def _histogram(values: list) -> list:
    buckets = [0] * 10
    for v in values:
        idx = min(9, max(0, int(round(float(v) * 2)) - 1))
        buckets[idx] += 1
    return [{"rating": round((i + 1) * 0.5, 1), "count": c} for i, c in enumerate(buckets)]


# --------------------------------------------------------------------------- #
# catalogue
# --------------------------------------------------------------------------- #
@app.get("/api/movies/search")
def search(q: str = Query(..., min_length=1), limit: int = 20):
    """Matches title first, then cast, director, keywords, tags and genres."""
    e = eng()
    ids = e.search(q, limit=limit)
    e.hydrate_posters(ids)
    return {"query": q, "results": [e.movie_card(m) for m in ids]}


@app.get("/api/movies/popular")
def popular(limit: int = 24, min_ratings: int = 40, genre: str | None = None):
    e = eng()
    movies = e.data.movies
    subset = movies[movies["n_ratings"] >= min_ratings]
    if genre:
        subset = subset[subset["genre_list"].map(lambda g: genre in g)]
    subset = subset.sort_values(["n_ratings", "avg_rating"], ascending=False).head(limit)
    ids = [int(m) for m in subset["movieId"]]
    e.hydrate_posters(ids)
    return {"results": [e.movie_card(m) for m in ids]}


@app.get("/api/movies/sampler")
def sampler(limit: int = 30, seed: int = 0):
    """A spread of well-known films across genres, for rating a new profile."""
    e = eng()
    movies = e.data.movies[e.data.movies["n_ratings"] >= 50]
    rng = np.random.default_rng(seed)
    picked: list = []
    seen: set = set()
    for genre in e.data.all_genres:
        pool = movies[movies["genre_list"].map(lambda g, x=genre: x in g)]
        pool = pool.sort_values("n_ratings", ascending=False).head(30)
        if pool.empty:
            continue
        for movie_id in rng.permutation(pool["movieId"].values)[:2]:
            if int(movie_id) not in seen:
                seen.add(int(movie_id))
                picked.append(int(movie_id))
    picked = picked[:limit]
    e.hydrate_posters(picked)
    return {"results": [e.movie_card(m) for m in picked]}


@app.get("/api/movies/{movie_id}")
def movie_detail(movie_id: int):
    """Full record for the info popup - overview, cast, director, TMDB rating.

    Goes through hydrate_posters so a dead MovieLens tmdbId still resolves via
    the title search rather than returning a bare catalogue row.
    """
    e = eng()
    if int(movie_id) not in e.data.item_pos:
        raise HTTPException(404, "movie not found")
    e.hydrate_posters([int(movie_id)])
    card = e.movie_card(movie_id)

    meta = tmdb.cached_only(e.data.movies.at[int(movie_id), "tmdbId"])
    if meta:
        card["cast"] = meta.get("cast", [])[:8]
        card["directors"] = meta.get("directors", [])
        card["keywords"] = meta.get("keywords", [])[:10]
        card["tagline"] = meta.get("tagline", "")
        card["release_date"] = meta.get("release_date", "")
        card["vote_count"] = meta.get("vote_count")
        card["tmdb_genres"] = meta.get("tmdb_genres", [])
    return card


@app.get("/api/genres")
def genres():
    return {"genres": eng().data.all_genres}


# --------------------------------------------------------------------------- #
# 1. content-based
# --------------------------------------------------------------------------- #
@app.get("/api/recommend/content")
def recommend_content(user_id: int, n: int = 12):
    e = eng()
    rated = e.rated_map(user_id)
    if not rated:
        return {"items": [], "empty": True,
                "message": "Rate a few movies first - content filtering needs a taste profile."}

    profile = e.content.build_profile(rated)
    result = e.content.recommend(rated, n=n, profile=profile)
    e.hydrate_posters([it["movieId"] for it in result["items"]])

    items = []
    for it in result["items"]:
        why = e.content.explain_recommendation(profile, it["movieId"])
        items.append(
            e.movie_card(
                it["movieId"],
                {"score": round(it["score"], 4), "explanation": why},
            )
        )
    return {
        "items": items,
        "profile_terms": result["profile_terms"],
        "genre_profile": e.content.genre_profile(rated),
        "n_ratings": len(rated),
        "method": {
            "name": "Content-based filtering",
            "vector_space": e.content.stats(),
            "formula": "score(j) = cos(profile, v_j) = sum_t profile[t] * tfidf_j[t]",
            "profile_formula": "profile = normalise( sum_i (r_i - mean_u)/sd_u * v_i )",
        },
    }


@app.get("/api/explain/content")
def explain_content(user_id: int, movie_id: int):
    e = eng()
    rated = e.rated_map(user_id)
    profile = e.content.build_profile(rated)
    why = e.content.explain_recommendation(profile, movie_id, top_n=8)
    for src in why.get("because_of", []):
        src.update(e.movie_card(src["movieId"]))
    return {"movie": e.movie_card(movie_id), "explanation": why}


@app.get("/api/similar/{movie_id}")
def similar(movie_id: int, method: str = "content", n: int = 12):
    e = eng()
    if int(movie_id) not in e.data.item_pos:
        raise HTTPException(404, "movie not found")

    if method == "content":
        raw = e.content.similar_to_movie(movie_id, n=n)
        pairs = [(r["movieId"], r["score"]) for r in raw]
    else:
        pos = e.data.item_pos[int(movie_id)]
        pairs = [
            (int(e.data.item_ids[p]), s) for p, s in e.item_knn.similar_items(pos, n=n)
        ]

    e.hydrate_posters([m for m, _ in pairs])
    items = []
    for other_id, score in pairs:
        extra = {"score": round(float(score), 4)}
        if method == "content":
            extra["explanation"] = e.content.explain_pair(movie_id, other_id)
        items.append(e.movie_card(other_id, extra))
    return {"seed": e.movie_card(movie_id), "method": method, "items": items}


# --------------------------------------------------------------------------- #
# 2. collaborative
# --------------------------------------------------------------------------- #
def _cf_model(e: Engine, name: str):
    return {"item-knn": e.item_knn, "user-knn": e.user_knn, "svd": e.svd}.get(name, e.item_knn)


@app.get("/api/recommend/collaborative")
def recommend_collaborative(user_id: int, model: str = "item-knn", n: int = 12):
    e = eng()
    rated_pos = e.rated_by_pos(user_id)
    if not rated_pos:
        return {"items": [], "empty": True,
                "message": "Rate a few movies first - collaborative filtering needs ratings to compare."}

    u = e.user_row(user_id)
    fold = None
    if model == "svd":
        if u is not None:
            rows = e.svd.recommend(u=u, n=n)
        else:
            p, b = e.svd.fold_in(rated_pos)
            fold = {"b_u": round(float(b), 4), "p_u_norm": round(float(np.linalg.norm(p)), 4),
                    "n_factors": e.svd.n_factors}
            rows = e.svd.recommend(p=p, b=b, n=n, seen=set(rated_pos.keys()))
    else:
        mdl = _cf_model(e, model)
        rows = mdl.recommend(u=u, ratings=None if u is not None else rated_pos, n=n)

    movie_ids = [int(e.data.item_ids[pos]) for pos, *_ in rows]
    e.hydrate_posters(movie_ids)

    items = []
    for (pos, pred, rank_score, support), movie_id in zip(rows, movie_ids):
        why = _explain_cf(e, user_id, pos, model, rated_pos, u)
        items.append(
            e.movie_card(
                movie_id,
                {
                    "score": round(float(rank_score), 4),
                    "predicted_rating": round(float(pred), 2),
                    "support": round(float(support), 3),
                    "explanation": why,
                },
            )
        )

    meta = _cf_meta(e, model)
    if fold:
        meta["fold_in"] = fold
    return {"items": items, "model": model, "method": meta, "n_ratings": len(rated_pos)}


def _explain_cf(e: Engine, user_id: int, pos: int, model: str, rated_pos: dict, u):
    if model == "svd":
        if u is not None:
            _, why = e.svd.predict_one(pos, u=u, explain=True)
        else:
            p, b = e.svd.fold_in(rated_pos)
            _, why = e.svd.predict_one(pos, p=p, b=b, explain=True)
        return why

    mdl = _cf_model(e, model)
    _, why = mdl.predict_one(pos, u=u, ratings=None if u is not None else rated_pos, explain=True)
    for nb in why.get("neighbours", []):
        if "item_pos" in nb:
            movie_id = int(e.data.item_ids[nb["item_pos"]])
            nb["movieId"] = movie_id
            nb["title"] = e.data.title(movie_id)
        if "user_pos" in nb:
            nb["userId"] = int(e.data.user_ids[nb["user_pos"]])
    return why


def _cf_meta(e: Engine, model: str) -> dict:
    if model == "svd":
        return {
            "name": "Matrix factorisation (BiasSVD)",
            "formula": "r_hat(u,i) = mu + b_u + b_i + p_u . q_i",
            "params": {
                "n_factors": e.svd.n_factors, "n_epochs": e.svd.n_epochs,
                "lr": e.svd.lr, "reg": e.svd.reg,
            },
            "mu": round(e.svd.mu, 4),
            "training": e.svd.history,
            "note": "Ranked on the unclipped score; the predicted rating is the clipped value.",
        }
    if model == "user-knn":
        return {
            "name": "User-based kNN (Pearson)",
            "formula": "r_hat(u,i) = mean_u + sum_v sim(u,v)(r_vi - mean_v) / sum_v |sim(u,v)|",
            "rank_formula": "rank(u,i) = sum_v sim(u,v) * (r_vi - mean_v)",
            "params": {"k": e.user_knn.k, "shrinkage": e.user_knn.shrinkage},
        }
    return {
        "name": "Item-based kNN (adjusted cosine)",
        "formula": "r_hat(u,i) = mean_u + sum_j sim(i,j)(r_uj - mean_u) / sum_j |sim(i,j)|",
        "rank_formula": "rank(u,i) = sum_j sim(i,j) * (r_uj - mean_u)",
        "params": {"k": e.item_knn.k, "shrinkage": e.item_knn.shrinkage,
                   "stored_similarities": int(e.item_knn.S.nnz)},
    }


@app.get("/api/explain/collaborative")
def explain_collaborative(user_id: int, movie_id: int, model: str = "item-knn"):
    e = eng()
    pos = e.data.item_pos.get(int(movie_id))
    if pos is None:
        raise HTTPException(404, "movie not found")
    rated_pos = e.rated_by_pos(user_id)
    u = e.user_row(user_id)
    why = _explain_cf(e, user_id, pos, model, rated_pos, u)
    return {"movie": e.movie_card(movie_id), "model": model, "explanation": why,
            "method": _cf_meta(e, model)}


@app.get("/api/neighbours")
def neighbours(user_id: int, n: int = 10):
    """Which other users look most like this one, and what they loved."""
    e = eng()
    u = e.user_row(user_id)
    rated_pos = e.rated_by_pos(user_id)
    if not rated_pos:
        return {"neighbours": []}

    rows = e.user_knn.similar_users(u=u, ratings=None if u is not None else rated_pos, n=n)
    mine = set(rated_pos.keys())
    out = []
    for row in rows:
        v = row["user_pos"]
        R = e.data.R
        lo, hi = R.indptr[v], R.indptr[v + 1]
        their = {int(p): float(val) for p, val in zip(R.indices[lo:hi], R.data[lo:hi])}
        loved = sorted(
            [(p, r) for p, r in their.items() if r >= 4.5 and p not in mine],
            key=lambda x: -x[1],
        )[:4]
        movie_ids = [int(e.data.item_ids[p]) for p, _ in loved]
        e.hydrate_posters(movie_ids)
        row["userId"] = int(e.data.user_ids[v])
        row["shared"] = len(mine & set(their.keys()))
        row["loved"] = [
            e.movie_card(m, {"their_rating": r}) for m, (_, r) in zip(movie_ids, loved)
        ]
        out.append(row)
    return {"neighbours": out, "your_ratings": len(mine)}


@app.get("/api/svd/space")
def svd_space(user_id: int, max_points: int = 1600):
    """PCA projection of the learned item factors, for the 3D point cloud."""
    return eng().factor_space_payload(user_id, max_points=max_points)


@app.get("/api/svd/factors")
def svd_factors(k: int = 0, n: int = 8):
    """The two poles of one latent factor - what the model discovered by itself."""
    e = eng()
    if k < 0 or k >= e.svd.n_factors:
        raise HTTPException(400, "factor out of range")
    column = e.svd.Q[:, k]
    popular = e.data.movies["n_ratings"].values >= 25
    masked = np.where(popular, column, np.nan)
    high = np.argsort(-np.nan_to_num(masked, nan=-1e9))[:n]
    low = np.argsort(np.nan_to_num(masked, nan=1e9))[:n]
    ids = [int(e.data.item_ids[p]) for p in list(high) + list(low)]
    e.hydrate_posters(ids)
    return {
        "factor": k,
        "n_factors": e.svd.n_factors,
        "positive": [
            e.movie_card(int(e.data.item_ids[p]), {"loading": round(float(column[p]), 4)})
            for p in high
        ],
        "negative": [
            e.movie_card(int(e.data.item_ids[p]), {"loading": round(float(column[p]), 4)})
            for p in low
        ],
    }


# --------------------------------------------------------------------------- #
# 3. hybrid
# --------------------------------------------------------------------------- #
@app.get("/api/recommend/hybrid")
def recommend_hybrid(user_id: int, n: int = 12, strategy: str = "weighted",
                     cf_model: str = "item-knn", alpha: float | None = None):
    e = eng()
    rated_pos = e.rated_by_pos(user_id)
    if not rated_pos:
        return {"items": [], "empty": True,
                "message": "Rate a few movies first - the hybrid needs something to blend."}

    u = e.user_row(user_id)
    result = e.hybrid.recommend(u, rated_pos, n=n, strategy=strategy, cf_model=cf_model, alpha=alpha)
    e.hydrate_posters([it["movieId"] for it in result["items"]])

    trace = {k: v for k, v in result["trace"].items() if not isinstance(v, np.ndarray)}
    items = []
    for it in result["items"]:
        items.append(
            e.movie_card(
                it["movieId"],
                {
                    "score": round(it["score"], 4),
                    "content_raw": round(it["content_raw"], 4),
                    "content_norm": round(it["content_norm"], 4),
                    "cf_raw": round(it["cf_raw"], 4),
                    "cf_norm": round(it["cf_norm"], 4),
                    "predicted_rating": round(it["cf_rating"], 2),
                    "content_part": round(it["content_part"], 4),
                    "cf_part": round(it["cf_part"], 4),
                    "lead": "collaborative" if it["cf_part"] >= it["content_part"] else "content",
                },
            )
        )
    return {
        "items": items,
        "trace": trace,
        "method": {
            "name": "Hybrid - %s" % strategy,
            "formula": _hybrid_formula(strategy),
            "strategies": list(e.hybrid.__class__.__module__ and ["weighted", "switching", "rank", "cascade"]),
        },
        "n_ratings": len(rated_pos),
    }


def _hybrid_formula(strategy: str) -> str:
    return {
        "weighted": "score = alpha * norm(CF) + (1 - alpha) * norm(content)",
        "switching": "score = content if n_ratings < threshold else CF",
        "rank": "score = alpha / (60 + rank_CF) + (1 - alpha) / (60 + rank_content)",
        "cascade": "CF selects the candidate pool, content re-ranks inside it",
    }.get(strategy, "")


@app.get("/api/hybrid/alpha-sweep")
def alpha_sweep(user_id: int, cf_model: str = "item-knn", n: int = 8):
    e = eng()
    rated_pos = e.rated_by_pos(user_id)
    if not rated_pos:
        return {"sweep": []}
    u = e.user_row(user_id)
    sweep = e.hybrid.alpha_sweep(u, rated_pos, cf_model=cf_model, n=n)
    for step in sweep:
        e.hydrate_posters([it["movieId"] for it in step["items"]])
        step["items"] = [
            e.movie_card(it["movieId"], {"score": it["score"]}) for it in step["items"]
        ]
    return {"sweep": sweep, "cf_model": cf_model}


@app.get("/api/hybrid/compare")
def hybrid_compare(user_id: int, n: int = 10, cf_model: str = "item-knn"):
    e = eng()
    rated_pos = e.rated_by_pos(user_id)
    if not rated_pos:
        return {"lists": {}, "overlap": {}}
    u = e.user_row(user_id)
    result = e.hybrid.compare_sources(u, rated_pos, n=n, cf_model=cf_model)
    all_ids = {m for lst in result["lists"].values() for m in lst}
    e.hydrate_posters(list(all_ids))
    cards = {int(m): e.movie_card(int(m)) for m in all_ids}
    return {
        "lists": {
            label: [cards[int(m)] for m in ids] for label, ids in result["lists"].items()
        },
        "overlap": result["overlap"],
        "cf_model": cf_model,
    }


# --------------------------------------------------------------------------- #
# comparison across users + evaluation
# --------------------------------------------------------------------------- #
@app.get("/api/compare/users")
def compare_users(user_ids: str, method: str = "hybrid", n: int = 6):
    """Same algorithm, several users - shows personalisation is real."""
    e = eng()
    ids = [int(x) for x in user_ids.split(",") if x.strip()]
    columns = []
    for user_id in ids[:4]:
        rated_pos = e.rated_by_pos(user_id)
        if not rated_pos:
            continue
        u = e.user_row(user_id)
        if method == "content":
            rated = e.rated_map(user_id)
            rows = [(it["movieId"], it["score"]) for it in e.content.recommend(rated, n=n)["items"]]
        elif method == "collaborative":
            raw = e.item_knn.recommend(u=u, ratings=None if u is not None else rated_pos, n=n)
            rows = [(int(e.data.item_ids[p]), s) for p, _, s, _ in raw]
        else:
            res = e.hybrid.recommend(u, rated_pos, n=n, strategy="weighted", cf_model="item-knn")
            rows = [(it["movieId"], it["score"]) for it in res["items"]]

        e.hydrate_posters([m for m, _ in rows])
        name = (
            e.custom_users[int(user_id)]["name"]
            if e.is_custom(user_id) and int(user_id) in e.custom_users
            else "User %d" % int(user_id)
        )
        columns.append(
            {
                "userId": int(user_id),
                "name": name,
                "n_ratings": len(rated_pos),
                "top_genres": e.content.genre_profile(e.rated_map(user_id))[:3],
                "items": [e.movie_card(m, {"score": round(float(s), 4)}) for m, s in rows],
            }
        )

    all_lists = [{it["movieId"] for it in c["items"]} for c in columns]
    shared = set.intersection(*all_lists) if len(all_lists) > 1 else set()
    return {"columns": columns, "method": method, "shared": sorted(shared)}


@app.get("/api/evaluation")
def evaluation(k: int = 10, force: bool = False):
    return eng().evaluation(k=k, force=force)


# --------------------------------------------------------------------------- #
# browse - the streaming front page, one shelf per algorithm
# --------------------------------------------------------------------------- #
@app.get("/api/browse")
def browse(user_id: int, alpha: float | None = None):
    e = eng()
    rated_pos = e.rated_by_pos(user_id)
    if not rated_pos:
        return {"empty": True,
                "message": "Rate a few films first - every shelf here is a recommender."}

    u = e.user_row(user_id)
    alpha = e.cfg["hybrid"]["alpha"] if alpha is None else float(alpha)
    hyb = e.hybrid.recommend(u, rated_pos, n=10, strategy="weighted",
                             cf_model="item-knn", alpha=alpha)
    items = hyb["items"]
    if not items:
        return {"empty": True, "message": "Not enough signal yet - rate a few more films."}

    rated_map = e.rated_map(user_id)
    content = e.content.recommend(rated_map, n=12)["items"]
    collab = e.item_knn.recommend(u=u, ratings=None if u is not None else rated_pos, n=12)

    # long tail: what only the content model can reach, minus anything the
    # main content shelf already shows
    pop = e.data.movies["n_ratings"]
    shown = {it["movieId"] for it in content}
    cold = [
        it for it in e.content.recommend(rated_map, n=120)["items"]
        if int(pop.get(it["movieId"], 0)) <= 12 and it["movieId"] not in shown
    ][:12]

    top_pos = np.argsort(-np.asarray((e.data.R > 0).sum(axis=0)).ravel())[:10]
    top_ids = [int(e.data.item_ids[p]) for p in top_pos]

    all_ids = (
        [it["movieId"] for it in items]
        + [it["movieId"] for it in content]
        + [int(e.data.item_ids[p]) for p, *_ in collab]
        + [it["movieId"] for it in cold]
        + top_ids
    )
    e.hydrate_posters(list(dict.fromkeys(all_ids)))

    def lead_of(it):
        return "collaborative" if it["cf_part"] >= it["content_part"] else "content"

    hero_item = items[0]
    hero = e.movie_card(
        hero_item["movieId"],
        {
            "content_raw": round(hero_item["content_raw"], 4),
            "cf_rating": round(hero_item["cf_rating"], 2),
            "score": round(hero_item["score"], 4),
            "lead": lead_of(hero_item),
        },
    )

    def shelf(pairs, mode):
        out = []
        for movie_id, score, reason in pairs:
            card = e.movie_card(int(movie_id), {"score": round(float(score), 4), "reason": reason,
                                                "mode": mode})
            out.append(card)
        return out

    content_rows = [
        (it["movieId"], it["score"],
         "Shares terms with what you rated highest")
        for it in content
    ]
    collab_rows = [
        (int(e.data.item_ids[p]), pred,
         "Rated alike by viewers nearest you")
        for p, pred, _rank, _sup in collab
    ]
    cold_rows = [
        (it["movieId"], it["score"],
         "Only %d ratings - matched on description alone"
         % int(pop.get(it["movieId"], 0)))
        for it in cold
    ]

    return {
        "hero": hero,
        "alpha": alpha,
        "rails": [
            {"key": "content", "kicker": "Content-based - reads the film",
             "title": "Because of what you rated highest", "tone": "content",
             "films": shelf(content_rows, "content")},
            {"key": "collab", "kicker": "Collaborative - reads the crowd",
             "title": "Viewers who rate like you also loved", "tone": "collaborative",
             "films": shelf(collab_rows, "collab")},
            {"key": "cold", "kicker": "The long tail - collaborative filtering is blind here",
             "title": "Almost nobody has rated these", "tone": "content",
             "films": shelf(cold_rows, "cold")},
        ],
        "top_ten": [
            e.movie_card(m, {"rank": i + 1,
                             "n": int(e.data.movies.at[m, "n_ratings"])})
            for i, m in enumerate(top_ids)
        ],
        "reel": [
            e.movie_card(
                it["movieId"],
                {
                    "rank": i + 1,
                    "score": round(it["score"], 4),
                    "content_raw": round(it["content_raw"], 4),
                    "content_norm": round(it["content_norm"], 4),
                    "cf_raw": round(it["cf_raw"], 4),
                    "cf_norm": round(it["cf_norm"], 4),
                    "cf_rating": round(it["cf_rating"], 2),
                    "content_part": round(it["content_part"], 4),
                    "cf_part": round(it["cf_part"], 4),
                    "lead": lead_of(it),
                },
            )
            for i, it in enumerate(items)
        ],
    }


@app.get("/api/matrix")
def matrix(user_id: int | None = None, users: int = 26, items: int = 40):
    """A corner of the rating matrix - the thing every CF model actually sees."""
    e = eng()
    R = e.data.R
    top_items = np.argsort(-np.asarray((R > 0).sum(axis=0)).ravel())[:items]
    counts = np.diff(R.indptr)
    top_users = np.argsort(-counts)[:users].tolist()
    if user_id is not None and not e.is_custom(user_id):
        u = e.user_row(user_id)
        if u is not None and u not in top_users:
            top_users = [u] + top_users[: users - 1]

    sub = R[np.array(top_users)][:, top_items].toarray()
    return {
        "users": [
            {"userId": int(e.data.user_ids[u]), "pos": int(u), "highlight": (
                user_id is not None and int(e.data.user_ids[u]) == int(user_id))}
            for u in top_users
        ],
        "items": [
            {"movieId": int(e.data.item_ids[i]), "title": e.data.title(int(e.data.item_ids[i]))}
            for i in top_items
        ],
        "values": [[round(float(v), 1) for v in row] for row in sub],
        "density": round(float((sub > 0).mean() * 100), 1),
        "full_density": round(R.nnz / (R.shape[0] * R.shape[1]) * 100, 2),
    }


# --------------------------------------------------------------------------- #
# static front-end
# --------------------------------------------------------------------------- #
@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.exception_handler(404)
def not_found(request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "not found"}, status_code=404)
    return FileResponse(FRONTEND_DIR / "index.html")


@app.middleware("http")
async def no_cache_static(request, call_next):
    """Make the browser revalidate front-end assets.

    ES modules import each other by bare path, so bumping a ?v= on the entry
    point does nothing for its imports - the browser happily serves a stale
    ui.js against a fresh app.js. ETags keep revalidation cheap.
    """
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/") or path == "/" or path.endswith(".html"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
