"""The recommender engine: loads data, trains every model, serves explanations.

Two sets of collaborative models are kept:

  * serving models, trained on all 100k ratings - used for recommendations
  * evaluation models, trained on the 80% training split only - used for the
    metrics page, so nothing is ever scored on data it was trained on

Content-based item vectors depend on metadata alone, so a single content model
serves both roles.
"""
from __future__ import annotations

import json
import threading
import time

import numpy as np
import pandas as pd

import collaborative as cf
import content_based
import dataset
import enrich
import evaluate
import tmdb
from config import CACHE_DIR, CONFIG
from hybrid import HybridRecommender

CUSTOM_USER_BASE = 900000


class Engine:
    """Everything the API needs, built once at startup."""

    def __init__(self, verbose: bool = True):
        self.cfg = CONFIG
        self.lock = threading.RLock()
        self.custom_users: dict = {}
        self._next_custom = CUSTOM_USER_BASE
        self.build_log: list = []
        self._build(verbose)

    # ---------------------------------------------------------------- startup
    def _step(self, label, fn, verbose):
        t0 = time.time()
        result = fn()
        elapsed = round(time.time() - t0, 2)
        self.build_log.append({"step": label, "seconds": elapsed})
        if verbose:
            print("  [%5.2fs] %s" % (elapsed, label), flush=True)
        return result

    def _build(self, verbose: bool) -> None:
        if verbose:
            print("Building recommender engine...", flush=True)
        knn_cfg, svd_cfg = self.cfg["knn"], self.cfg["svd"]
        k, shrink = knn_cfg["k_neighbors"], knn_cfg["shrinkage"]

        self.data = self._step("load MovieLens", dataset.load, verbose)
        self.content = self._step(
            "content model (TF-IDF)", lambda: content_based.ContentBasedRecommender(self.data), verbose
        )
        self.content_eval = self.content

        self.item_knn = self._step(
            "item-kNN (full)", lambda: cf.ItemKNN.cached(self.data.R, k, shrink, "full"), verbose
        )
        self.user_knn = self._step("user-kNN (full)", lambda: cf.UserKNN(self.data.R, k, shrink), verbose)
        self.svd = self._step(
            "SVD (full)", lambda: cf.cached_svd(self.data.R, svd_cfg, "full", verbose), verbose
        )
        self.baseline = self._step("bias baseline (full)", lambda: cf.Baseline(self.data.R), verbose)

        self.item_knn_eval = self._step(
            "item-kNN (train split)", lambda: cf.ItemKNN.cached(self.data.train, k, shrink, "train"), verbose
        )
        self.user_knn_eval = self._step(
            "user-kNN (train split)", lambda: cf.UserKNN(self.data.train, k, shrink), verbose
        )
        self.svd_eval = self._step(
            "SVD (train split)", lambda: cf.cached_svd(self.data.train, svd_cfg, "train", verbose), verbose
        )
        self.baseline_eval = self._step(
            "bias baseline (train split)", lambda: cf.Baseline(self.data.train), verbose
        )

        self.hybrid = HybridRecommender(
            self.data, self.content, self.item_knn, self.user_knn, self.svd, self.cfg["hybrid"]
        )
        self._eval_cache: dict = {}
        self._load_custom_users()
        self._step("search index", self.build_search_index, verbose)
        self.ready_at = time.time()
        if verbose:
            print("Engine ready.", flush=True)

    # ------------------------------------------------------------------ users
    CUSTOM_PATH = CACHE_DIR / "custom_users.json"

    def is_custom(self, user_id: int) -> bool:
        return int(user_id) >= CUSTOM_USER_BASE

    def _load_custom_users(self) -> None:
        """Viewers you build yourself live on disk, so they survive a restart."""
        if not self.CUSTOM_PATH.exists():
            return
        try:
            blob = json.loads(self.CUSTOM_PATH.read_text(encoding="utf-8"))
        except Exception:
            return
        for record in blob.get("users", []):
            try:
                user_id = int(record["userId"])
            except (KeyError, TypeError, ValueError):
                continue
            self.custom_users[user_id] = {
                "userId": user_id,
                "name": record.get("name") or "Guest",
                "ratings": {int(m): float(r) for m, r in (record.get("ratings") or {}).items()},
                "created_at": record.get("created_at", time.time()),
            }
        if self.custom_users:
            self._next_custom = max(self.custom_users) + 1

    def _save_custom_users(self) -> None:
        try:
            payload = {
                "users": [
                    {
                        "userId": u["userId"],
                        "name": u["name"],
                        "ratings": {str(m): r for m, r in u["ratings"].items()},
                        "created_at": u["created_at"],
                    }
                    for u in self.custom_users.values()
                ]
            }
            tmp = self.CUSTOM_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
            tmp.replace(self.CUSTOM_PATH)
        except Exception:
            pass

    def create_custom_user(self, name: str, ratings: dict | None = None) -> dict:
        with self.lock:
            user_id = self._next_custom
            self._next_custom += 1
            self.custom_users[user_id] = {
                "userId": user_id,
                "name": name or ("Guest %d" % (user_id - CUSTOM_USER_BASE + 1)),
                "ratings": {int(m): float(r) for m, r in (ratings or {}).items()},
                "created_at": time.time(),
            }
            self._save_custom_users()
            return self.custom_users[user_id]

    def set_custom_rating(self, user_id: int, movie_id: int, rating: float | None) -> dict:
        with self.lock:
            user = self.custom_users.get(int(user_id))
            if user is None:
                raise KeyError("unknown custom user")
            if rating is None:
                user["ratings"].pop(int(movie_id), None)
            else:
                user["ratings"][int(movie_id)] = float(rating)
            self._save_custom_users()
            return user

    def rename_custom_user(self, user_id: int, name: str) -> dict:
        with self.lock:
            user = self.custom_users.get(int(user_id))
            if user is None:
                raise KeyError("unknown custom user")
            user["name"] = name or user["name"]
            self._save_custom_users()
            return user

    def delete_custom_user(self, user_id: int) -> bool:
        with self.lock:
            gone = self.custom_users.pop(int(user_id), None) is not None
            if gone:
                self._save_custom_users()
            return gone

    def rated_map(self, user_id: int) -> dict:
        """movieId -> rating, for either a MovieLens user or a custom one."""
        user_id = int(user_id)
        if self.is_custom(user_id):
            user = self.custom_users.get(user_id)
            return dict(user["ratings"]) if user else {}
        u = self.data.user_pos.get(user_id)
        if u is None:
            return {}
        R = self.data.R
        lo, hi = R.indptr[u], R.indptr[u + 1]
        return {
            int(self.data.item_ids[p]): float(v)
            for p, v in zip(R.indices[lo:hi], R.data[lo:hi])
        }

    def rated_by_pos(self, user_id: int) -> dict:
        """item position -> rating."""
        out = {}
        for movie_id, rating in self.rated_map(user_id).items():
            pos = self.data.item_pos.get(int(movie_id))
            if pos is not None:
                out[pos] = float(rating)
        return out

    def user_row(self, user_id: int):
        """Row index into the training matrices, or None for a custom user."""
        return None if self.is_custom(user_id) else self.data.user_pos.get(int(user_id))

    def list_users(self, limit: int = 80) -> dict:
        counts = np.diff(self.data.R.indptr)
        means = np.asarray(
            [
                self.data.R.data[self.data.R.indptr[i] : self.data.R.indptr[i + 1]].mean()
                if counts[i] else 0.0
                for i in range(self.data.n_users)
            ]
        )
        order = np.argsort(-counts)
        builtin = []
        for i in order[:limit]:
            builtin.append(
                {
                    "userId": int(self.data.user_ids[i]),
                    "name": "MovieLens user %d" % int(self.data.user_ids[i]),
                    "n_ratings": int(counts[i]),
                    "avg_rating": round(float(means[i]), 2),
                    "custom": False,
                    "top_genres": self._top_genres_for(i),
                }
            )
        custom = [
            {
                "userId": u["userId"],
                "name": u["name"],
                "n_ratings": len(u["ratings"]),
                "avg_rating": round(float(np.mean(list(u["ratings"].values()))), 2)
                if u["ratings"] else 0.0,
                "custom": True,
                "top_genres": [],
            }
            for u in self.custom_users.values()
        ]
        return {"builtin": builtin, "custom": custom}

    def _top_genres_for(self, u: int, n: int = 3) -> list:
        R = self.data.R
        lo, hi = R.indptr[u], R.indptr[u + 1]
        counts: dict = {}
        for pos, val in zip(R.indices[lo:hi], R.data[lo:hi]):
            if val < 3.5:
                continue
            for g in self.data.movies.at[int(self.data.item_ids[pos]), "genre_list"]:
                counts[g] = counts.get(g, 0) + 1
        return [g for g, _ in sorted(counts.items(), key=lambda x: -x[1])[:n]]

    # ------------------------------------------------------------- decoration
    def movie_card(self, movie_id: int, extra: dict | None = None) -> dict:
        movie_id = int(movie_id)
        try:
            row = self.data.movies.loc[movie_id]
        except KeyError:
            return {"movieId": movie_id, "title": "Unknown", **(extra or {})}
        meta = tmdb.cached_only(row.get("tmdbId"))
        card = {
            "movieId": movie_id,
            "title": str(row["clean_title"]),
            "full_title": str(row["title"]),
            "year": int(row["year"]) if row["year"] == row["year"] else None,
            "genres": list(row["genre_list"]),
            "tags": list(row["tags"])[:6],
            "n_ratings": int(row["n_ratings"]),
            "avg_rating": round(float(row["avg_rating"]), 2),
            "tmdbId": int(row["tmdbId"]) if row["tmdbId"] == row["tmdbId"] else None,
        }
        if meta:
            card.update(
                {
                    "poster": meta.get("poster"),
                    "backdrop": meta.get("backdrop"),
                    "overview": meta.get("overview"),
                    "runtime": meta.get("runtime"),
                    "tmdb_score": meta.get("vote_average"),
                    "cast": meta.get("cast", [])[:4],
                    "directors": meta.get("directors", []),
                    "keywords": meta.get("keywords", [])[:6],
                }
            )
        if extra:
            card.update(extra)
        return card

    def _tmdb_lookup(self, movie_id: int):
        """(tmdbId, title, year) - the title/year let TMDB be searched by name
        when the MovieLens id is dead."""
        try:
            row = self.data.movies.loc[int(movie_id)]
        except KeyError:
            return None
        tmdb_id = row["tmdbId"]
        year = row["year"]
        return (
            tmdb_id if tmdb_id == tmdb_id else None,
            str(row["clean_title"]),
            int(year) if year == year else None,
        )

    def hydrate_posters(self, movie_ids: list, retry_missing: bool = True) -> None:
        """Fetch any missing posters for a result set, in parallel."""
        if not self.cfg.get("posters_enabled", True):
            return
        wanted = []
        for movie_id in movie_ids:
            lookup = self._tmdb_lookup(movie_id)
            if lookup is None:
                continue
            tmdb_id, title, year = lookup
            if tmdb_id is not None and tmdb.cached_only(tmdb_id) is not None:
                continue
            wanted.append((tmdb_id, title, year))
        if wanted:
            tmdb.fetch_many(wanted, workers=16, retry_missing=retry_missing)

    # ------------------------------------------------------------- evaluation
    def _eval_path(self, key: str):
        cfg = self.cfg
        tag = "%d_%d_%s_%s_%s_%s" % (
            self.data.train.nnz, self.content.V.nnz,
            cfg["svd"]["n_factors"], cfg["svd"]["n_epochs"],
            cfg["knn"]["k_neighbors"], cfg["hybrid"]["alpha"],
        )
        return CACHE_DIR / ("eval_%s_%s.json" % (key, tag))

    def evaluation(self, k: int = 10, models=None, force: bool = False) -> dict:
        """Scoring six models over 610 viewers takes ~60s, so it is cached to
        disk and keyed by everything that could change the answer."""
        key = "k%d_%s" % (k, ",".join(sorted(models)) if models else "all")
        with self.lock:
            if not force and key in self._eval_cache:
                return self._eval_cache[key]

        path = self._eval_path(key)
        if not force and path.exists():
            try:
                result = json.loads(path.read_text(encoding="utf-8"))
                with self.lock:
                    self._eval_cache[key] = result
                return result
            except Exception:
                pass

        result = evaluate.run_full(self, k=k, models=models)
        with self.lock:
            self._eval_cache[key] = result
        try:
            path.write_text(json.dumps(result), encoding="utf-8")
        except Exception:
            pass
        return result

    def warm_evaluation(self) -> None:
        """Compute the scoreboard in the background so the page opens instantly."""
        def work():
            try:
                self.evaluation(k=10)
            except Exception:
                pass

        threading.Thread(target=work, daemon=True, name="eval-warm").start()

    # ------------------------------------------------------------- enrichment
    def start_enrichment(self) -> bool:
        def rebuild(done, total):
            # Refresh the content model as TMDB data lands, at a few checkpoints.
            if done and done % 1000 == 0:
                try:
                    fresh = content_based.ContentBasedRecommender(self.data)
                    with self.lock:
                        self.content = fresh
                        self.content_eval = fresh
                        self.hybrid.content = fresh
                        self._eval_cache.clear()
                except Exception:
                    pass

        return enrich.start(self.data, workers=24, on_progress=rebuild)

    def rebuild_content(self) -> dict:
        fresh = content_based.ContentBasedRecommender(self.data)
        with self.lock:
            self.content = fresh
            self.content_eval = fresh
            self.hybrid.content = fresh
            self._eval_cache.clear()
        self.build_search_index()
        return fresh.stats()

    # ------------------------------------------------------- latent factor space
    def factor_space(self) -> dict:
        """Project the 50-dimensional item matrix Q down to 3D with PCA.

        The SVD invents these axes purely to compress ratings - nobody labels
        them - yet the projection lands on recognisable clusters. Computed once
        and cached, since it never changes for a fixed model.
        """
        cached = getattr(self, "_factor_space", None)
        if cached is not None:
            return cached

        Q = self.svd.Q
        centred = Q - Q.mean(axis=0, keepdims=True)
        # Right singular vectors of the centred matrix are the principal axes.
        _, sing, vt = np.linalg.svd(centred, full_matrices=False)
        basis = vt[:3].T                     # (n_factors, 3)
        coords = centred @ basis             # (n_items, 3)

        span = np.abs(coords).max() or 1.0
        coords = coords / span               # normalise into roughly [-1, 1]

        total = float((sing ** 2).sum()) or 1.0
        explained = [round(float(s ** 2 / total), 4) for s in sing[:3]]

        popularity = self.data.movies["n_ratings"].to_numpy(dtype=np.float64)
        pop_norm = popularity / max(1.0, popularity.max())

        self._factor_space = {
            "basis": basis,
            "coords": coords,
            "explained": explained,
            "pop": pop_norm,
        }
        return self._factor_space

    def factor_space_payload(self, user_id: int, max_points: int = 1600) -> dict:
        """Point cloud for the front-end, with the viewer's own vector projected
        into the same space so p_u can be drawn against the films."""
        space = self.factor_space()
        coords, pop = space["coords"], space["pop"]

        rated_pos = set(self.rated_by_pos(user_id).keys())
        order = np.argsort(-self.data.movies["n_ratings"].to_numpy())

        # A viewer with 2,698 ratings would otherwise blow past the cap on their
        # own, so their films get at most half the budget - most-rated first.
        mine_budget = max_points // 2
        mine = [int(p) for p in order if int(p) in rated_pos][:mine_budget]
        keep: list = list(mine)
        mine_set = set(mine)
        for pos in order:
            if len(keep) >= max_points:
                break
            if int(pos) not in mine_set and int(pos) not in rated_pos:
                keep.append(int(pos))

        points = []
        for pos in keep:
            movie_id = int(self.data.item_ids[pos])
            points.append(
                {
                    "x": round(float(coords[pos, 0]), 4),
                    "y": round(float(coords[pos, 1]), 4),
                    "z": round(float(coords[pos, 2]), 4),
                    "mine": pos in rated_pos,
                    "pop": round(float(pop[pos]), 4),
                    "title": self.data.title(movie_id),
                    "movieId": movie_id,
                }
            )

        u = self.user_row(user_id)
        if u is not None:
            p = self.svd.P[u]
        else:
            p, _ = self.svd.fold_in(self.rated_by_pos(user_id))
        centred_p = p - self.svd.Q.mean(axis=0)
        pu = centred_p @ space["basis"]
        scale = float(np.abs(coords).max()) or 1.0
        norm = float(np.linalg.norm(pu)) or 1.0
        pu = pu / norm * 0.9 * scale

        return {
            "points": points,
            "user_vector": {
                "x": round(float(pu[0]), 4),
                "y": round(float(pu[1]), 4),
                "z": round(float(pu[2]), 4),
            },
            "explained": space["explained"],
            "n_factors": int(self.svd.n_factors),
            "n_rated": len(rated_pos),
        }

    # ------------------------------------------------------------------ search
    def build_search_index(self) -> None:
        """One lowercase haystack per film: title, tags, cast, crew, keywords.

        Without this, searching is title-only and "nolan", "ghibli" or "heist"
        find nothing - even though that metadata is already cached.
        """
        blobs = []
        for row in self.data.movies.itertuples():
            parts = [str(row.clean_title), " ".join(row.genre_list), " ".join(row.tags[:12])]
            meta = tmdb.cached_only(row.tmdbId)
            if meta:
                parts.append(" ".join(meta.get("cast", [])[:6]))
                parts.append(" ".join(meta.get("directors", [])))
                parts.append(" ".join(meta.get("keywords", [])[:12]))
                parts.append(" ".join(meta.get("tmdb_genres", [])))
            blobs.append(" ".join(parts).lower())
        with self.lock:
            self.search_blob = pd.Series(blobs, index=self.data.movies.index)

    def search(self, query: str, limit: int = 20) -> list:
        """Title matches first, then anything matching the wider metadata."""
        needle = (query or "").strip().lower()
        if not needle:
            return []
        movies = self.data.movies
        titles = movies["clean_title"].str.lower()

        exact = titles == needle
        starts = titles.str.startswith(needle) & ~exact
        contains = titles.str.contains(needle, regex=False, na=False) & ~starts & ~exact

        blob = getattr(self, "search_blob", None)
        wider = (
            blob.str.contains(needle, regex=False, na=False) & ~contains & ~starts & ~exact
            if blob is not None
            else None
        )

        out: list = []
        seen: set = set()
        buckets = [exact, starts, contains] + ([wider] if wider is not None else [])
        for mask in buckets:
            hits = movies[mask].sort_values(["n_ratings", "avg_rating"], ascending=False)
            for movie_id in hits["movieId"]:
                if int(movie_id) in seen:
                    continue
                seen.add(int(movie_id))
                out.append(int(movie_id))
                if len(out) >= limit:
                    return out
        return out

    # ------------------------------------------------------------------ meta
    def status(self) -> dict:
        return {
            "dataset": self.data.stats(),
            "content": self.content.stats(),
            "models": {
                "item_knn": {"k": self.item_knn.k, "shrinkage": self.item_knn.shrinkage,
                             "stored_similarities": int(self.item_knn.S.nnz)},
                "user_knn": {"k": self.user_knn.k, "shrinkage": self.user_knn.shrinkage},
                "svd": {
                    "n_factors": self.svd.n_factors,
                    "n_epochs": self.svd.n_epochs,
                    "lr": self.svd.lr,
                    "reg": self.svd.reg,
                    "final_train_rmse": self.svd.history[-1]["train_rmse"] if self.svd.history else None,
                    "history": self.svd.history,
                },
                "hybrid": self.cfg["hybrid"],
            },
            "tmdb": tmdb.route_status(),
            "enrichment": enrich.status(),
            "build_log": self.build_log,
        }
