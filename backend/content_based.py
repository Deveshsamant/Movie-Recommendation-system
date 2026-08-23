"""Content-based filtering: TF-IDF over movie metadata + cosine similarity.

The model answers "what is this movie *about*, and what else is about the same
thing" using only item metadata - it never looks at what other users did. Every
score it returns is accompanied by an exact decomposition, because cosine
similarity of L2-normalised vectors is just a dot product:

    sim(a, b) = sum_t  tfidf_a[t] * tfidf_b[t]

so each shared term's contribution is a real number that sums to the score.
"""
from __future__ import annotations

import re

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize

import tmdb

# Repetition is how you weight a term inside a bag-of-words document.
GENRE_WEIGHT = 3
TAG_WEIGHT = 2
KEYWORD_WEIGHT = 2
DIRECTOR_WEIGHT = 2
CAST_WEIGHT = 1

_TOKEN_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _TOKEN_RE.sub("_", str(text).lower().strip()).strip("_")


class ContentBasedRecommender:
    """TF-IDF item profiles + Rocchio user profiles."""

    def __init__(self, data):
        self.data = data
        self.movie_ids = np.array(data.movies["movieId"].values)
        self.pos = {int(m): i for i, m in enumerate(self.movie_ids)}
        self.documents = self._build_documents()
        self.vectorizer = TfidfVectorizer(
            analyzer="word",
            token_pattern=r"[^ ]+",
            sublinear_tf=True,
            min_df=2,
            max_df=0.6,
        )
        matrix = self.vectorizer.fit_transform(self.documents)
        self.V = normalize(matrix)  # L2 rows -> dot product == cosine
        self.terms = np.array(self.vectorizer.get_feature_names_out())
        self.enriched = sum(1 for d in self._enrich_flags if d)

    # ------------------------------------------------------------- documents
    def _build_documents(self) -> list:
        docs: list = []
        flags: list = []
        for row in self.data.movies.itertuples():
            tokens: list = []
            for genre in row.genre_list:
                tokens += [("g_" + _slug(genre))] * GENRE_WEIGHT
            for tag in row.tags:
                tokens += [("t_" + _slug(tag))] * TAG_WEIGHT

            meta = tmdb.cached_only(row.tmdbId)
            if meta:
                flags.append(True)
                for kw in meta.get("keywords", []):
                    tokens += [("k_" + _slug(kw))] * KEYWORD_WEIGHT
                for director in meta.get("directors", []):
                    tokens += [("d_" + _slug(director))] * DIRECTOR_WEIGHT
                for actor in meta.get("cast", [])[:6]:
                    tokens += [("c_" + _slug(actor))] * CAST_WEIGHT
            else:
                flags.append(False)

            if row.year and not np.isnan(float(row.year)):
                tokens.append("decade_" + str(int(row.year) // 10 * 10) + "s")
            for word in _slug(row.clean_title).split("_"):
                if len(word) > 3:
                    tokens.append("w_" + word)
            docs.append(" ".join(tokens) if tokens else "unknown")
        self._enrich_flags = flags
        return docs

    # ------------------------------------------------------------- utilities
    def _vec(self, movie_id: int):
        return self.V[self.pos[int(movie_id)]]

    @staticmethod
    def _pretty(term: str) -> dict:
        prefix, _, rest = term.partition("_")
        kinds = {
            "g": "genre",
            "t": "tag",
            "k": "keyword",
            "d": "director",
            "c": "cast",
            "w": "title word",
            "decade": "decade",
        }
        if term.startswith("decade_"):
            return {"label": rest, "kind": "decade"}
        return {"label": rest.replace("_", " "), "kind": kinds.get(prefix, "term")}

    def explain_pair(self, movie_a: int, movie_b: int, top_n: int = 8) -> dict:
        """Exact per-term breakdown of cosine(a, b)."""
        va, vb = self._vec(movie_a), self._vec(movie_b)
        a = va.toarray().ravel()
        b = vb.toarray().ravel()
        products = a * b
        idx = np.argsort(-products)[:top_n]
        parts = []
        for i in idx:
            if products[i] <= 0:
                break
            info = self._pretty(self.terms[i])
            parts.append(
                {
                    "term": info["label"],
                    "kind": info["kind"],
                    "weight_a": round(float(a[i]), 4),
                    "weight_b": round(float(b[i]), 4),
                    "contribution": round(float(products[i]), 4),
                }
            )
        total = float(products.sum())
        covered = sum(p["contribution"] for p in parts)
        return {
            "score": round(total, 4),
            "terms": parts,
            "explained_share": round(covered / total, 3) if total > 0 else 0.0,
        }

    # ------------------------------------------------------- item -> item
    def similar_to_movie(self, movie_id: int, n: int = 12, exclude: set | None = None) -> list:
        if int(movie_id) not in self.pos:
            return []
        sims = (self.V @ self._vec(movie_id).T).toarray().ravel()
        sims[self.pos[int(movie_id)]] = -1.0
        if exclude:
            for m in exclude:
                if int(m) in self.pos:
                    sims[self.pos[int(m)]] = -1.0
        order = np.argsort(-sims)[:n]
        return [
            {"movieId": int(self.movie_ids[i]), "score": float(sims[i])}
            for i in order
            if sims[i] > 0
        ]

    # ------------------------------------------------------- user profile
    def build_profile(self, rated: dict) -> dict:
        """Rocchio profile: a taste vector built from the user's own ratings.

        Items rated above the user's personal mean pull the profile toward them,
        items below it push away. Weight w_i = r_ui - mean_u.
        """
        pairs = [(int(m), float(r)) for m, r in rated.items() if int(m) in self.pos]
        if not pairs:
            return {"vector": None, "components": [], "mean": 0.0}

        mean = float(np.mean([r for _, r in pairs]))
        # A user who rated everything identically gets a positive-only profile.
        spread = max(1e-6, float(np.std([r for _, r in pairs])))
        components = []
        rows, weights = [], []
        for movie_id, rating in pairs:
            weight = (rating - mean) / spread if spread > 1e-6 else 1.0
            if abs(weight) < 1e-9:
                weight = 0.15  # neutral ratings still carry a little signal
            rows.append(self.pos[movie_id])
            weights.append(weight)
            components.append({"movieId": movie_id, "rating": rating, "weight": weight})

        w = np.asarray(weights, dtype=np.float64)
        profile = (self.V[rows].T @ w).T  # 1 x n_terms
        profile = np.asarray(profile).ravel()
        norm = np.linalg.norm(profile)
        if norm > 0:
            profile = profile / norm
        return {"vector": profile, "components": components, "mean": mean, "norm": float(norm)}

    def top_profile_terms(self, profile: dict, top_n: int = 12) -> list:
        vec = profile.get("vector")
        if vec is None:
            return []
        idx = np.argsort(-vec)[:top_n]
        out = []
        for i in idx:
            if vec[i] <= 0:
                break
            info = self._pretty(self.terms[i])
            out.append({"term": info["label"], "kind": info["kind"], "weight": round(float(vec[i]), 4)})
        return out

    def recommend(self, rated: dict, n: int = 12, profile: dict | None = None) -> dict:
        """Score every unseen movie against the user's taste vector."""
        profile = profile or self.build_profile(rated)
        vec = profile.get("vector")
        if vec is None:
            return {"items": [], "profile_terms": [], "profile": profile}

        scores = self.V @ vec  # cosine, since both sides are L2-normalised
        for movie_id in rated:
            if int(movie_id) in self.pos:
                scores[self.pos[int(movie_id)]] = -1.0

        order = np.argsort(-scores)[: n * 3]
        items = []
        for i in order:
            if scores[i] <= 0:
                continue
            items.append({"movieId": int(self.movie_ids[i]), "score": float(scores[i])})
            if len(items) >= n:
                break
        return {"items": items, "profile_terms": self.top_profile_terms(profile), "profile": profile}

    def explain_recommendation(self, profile: dict, movie_id: int, top_n: int = 5) -> dict:
        """Attribute one recommendation back to the movies that caused it.

        profile = (1/||p||) * sum_i w_i * v_i, so
        score(j) = sum_i (w_i / ||p||) * (v_i . v_j)  -  an exact split.
        """
        if int(movie_id) not in self.pos:
            return {"score": 0.0, "because_of": [], "terms": []}

        target = self._vec(movie_id)
        norm = profile.get("norm") or 1.0
        components = profile["components"]

        # One sparse matmul for every source film at once. Looping here instead
        # costs ~12s for a viewer with a few thousand ratings.
        rows = [self.pos[c["movieId"]] for c in components]
        sims = np.asarray((self.V[rows] @ target.T).todense()).ravel()
        weights = np.array([c["weight"] for c in components], dtype=np.float64)
        contribs = weights * sims / norm

        order = np.argsort(-contribs)
        top = []
        for i in order[: top_n * 3]:
            if sims[i] <= 0 or len(top) >= top_n:
                break
            comp = components[i]
            top.append(
                {
                    "movieId": comp["movieId"],
                    "title": self.data.title(comp["movieId"]),
                    "your_rating": comp["rating"],
                    "profile_weight": round(float(comp["weight"]), 3),
                    "similarity": round(float(sims[i]), 4),
                    "contribution": round(float(contribs[i]), 5),
                }
            )
        n_sources = int((sims > 0).sum())

        vec = profile["vector"]
        tvec = target.toarray().ravel()
        products = vec * tvec
        idx = np.argsort(-products)[:top_n]
        terms = []
        for i in idx:
            if products[i] <= 0:
                break
            info = self._pretty(self.terms[i])
            terms.append(
                {
                    "term": info["label"],
                    "kind": info["kind"],
                    "profile_weight": round(float(vec[i]), 4),
                    "movie_weight": round(float(tvec[i]), 4),
                    "contribution": round(float(products[i]), 4),
                }
            )

        return {
            "score": round(float(products.sum()), 4),
            "because_of": top,
            "terms": terms,
            "n_sources": n_sources,
        }

    def genre_profile(self, rated: dict) -> list:
        """Average rating per genre - the human-readable version of the profile."""
        buckets: dict = {}
        for movie_id, rating in rated.items():
            try:
                genres = self.data.movies.at[int(movie_id), "genre_list"]
            except KeyError:
                continue
            for genre in genres:
                buckets.setdefault(genre, []).append(float(rating))
        rows = [
            {"genre": g, "count": len(v), "avg": round(float(np.mean(v)), 2)}
            for g, v in buckets.items()
        ]
        rows.sort(key=lambda r: (-r["count"], -r["avg"]))
        return rows[:12]

    def stats(self) -> dict:
        return {
            "n_items": int(self.V.shape[0]),
            "n_terms": int(self.V.shape[1]),
            "nnz": int(self.V.nnz),
            "avg_terms_per_movie": round(self.V.nnz / max(1, self.V.shape[0]), 1),
            "tmdb_enriched": int(self.enriched),
        }
