"""Hybrid recommenders: four ways to combine content and collaborative signals.

The two families fail in opposite directions. Content-based filtering knows
what a movie *is* but never discovers anything outside your existing taste;
collaborative filtering finds genuine surprises but is helpless on a new user or
a new film. Hybrids exist to cover each other's blind spots.

Strategies implemented (Burke, 2002 taxonomy):
  weighted  - normalise both scores, blend linearly with a tunable alpha
  switching - pick a model per user based on how much evidence exists
  rank      - reciprocal rank fusion; ignores score scales entirely
  cascade   - collaborative proposes a candidate set, content re-ranks it
"""
from __future__ import annotations

import numpy as np

STRATEGIES = ("weighted", "switching", "rank", "cascade")


def minmax(values: np.ndarray) -> tuple:
    """Scale to [0, 1]. Returns the scaled array plus the bounds used, so the
    UI can show exactly how a raw score became a normalised one."""
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        return np.zeros_like(values), 0.0, 1.0
    lo, hi = float(finite.min()), float(finite.max())
    if hi - lo < 1e-12:
        return np.full_like(values, 0.5), lo, hi
    return (values - lo) / (hi - lo), lo, hi


class HybridRecommender:
    """Combines a ContentBasedRecommender with the collaborative models."""

    def __init__(self, data, content, item_knn, user_knn, svd, cfg: dict):
        self.data = data
        self.content = content
        self.item_knn = item_knn
        self.user_knn = user_knn
        self.svd = svd
        self.alpha = float(cfg.get("alpha", 0.55))
        self.cold_threshold = int(cfg.get("cold_start_threshold", 8))
        self.n_items = data.n_items

    # ------------------------------------------------------------------ parts
    def _content_scores(self, rated_by_pos: dict, profile=None) -> np.ndarray:
        """Cosine of every item against the user's content profile."""
        rated_ids = {int(self.data.item_ids[p]): r for p, r in rated_by_pos.items()}
        profile = profile or self.content.build_profile(rated_ids)
        vec = profile.get("vector")
        if vec is None:
            return np.zeros(self.n_items), profile
        return np.asarray(self.content.V @ vec, dtype=np.float64), profile

    def _cf_scores(self, u, rated_by_pos, cf_model: str):
        """Ranking signal and predicted rating from the chosen collaborative model.

        These are deliberately two different numbers: ranking uses the raw
        evidence strength, while the predicted rating is the normalised, clipped
        value a user would recognise. Blending happens on the ranking signal.
        """
        if cf_model == "svd":
            if u is not None:
                return self.svd.rank_all(u=u), self.svd.score_all(u=u)[0], np.ones(self.n_items)
            p, b = self.svd.fold_in(rated_by_pos)
            return self.svd.rank_all(p=p, b=b), self.svd.score_all(p=p, b=b)[0], np.ones(self.n_items)

        model = self.user_knn if cf_model == "user-knn" else self.item_knn
        ratings = None if u is not None else rated_by_pos
        rank = model.rank_all(u=u, ratings=ratings)
        preds, support = model.score_all(u=u, ratings=ratings)
        return rank, preds, support

    # --------------------------------------------------------------- strategy
    def recommend(self, u, rated_by_pos: dict, n: int = 12, strategy: str = "weighted",
                  cf_model: str = "svd", alpha: float | None = None) -> dict:
        alpha = self.alpha if alpha is None else float(alpha)
        seen = list(rated_by_pos.keys())
        n_ratings = len(rated_by_pos)

        content_raw, profile = self._content_scores(rated_by_pos)
        cf_raw, cf_rating, support = self._cf_scores(u, rated_by_pos, cf_model)

        content_norm, c_lo, c_hi = minmax(content_raw)
        cf_norm, f_lo, f_hi = minmax(cf_raw)

        trace = {
            "strategy": strategy,
            "cf_model": cf_model,
            "alpha": alpha,
            "n_ratings": n_ratings,
            "content_range": [round(c_lo, 4), round(c_hi, 4)],
            "cf_range": [round(f_lo, 4), round(f_hi, 4)],
        }

        if strategy == "switching":
            cold = n_ratings < self.cold_threshold
            chosen = "content" if cold else "collaborative"
            blended = content_norm if cold else cf_norm
            effective_alpha = 0.0 if cold else 1.0
            trace.update(
                {
                    "switched_to": chosen,
                    "cold_start": cold,
                    "threshold": self.cold_threshold,
                    "reason": (
                        "only %d ratings (< %d) - collaborative evidence is too thin, "
                        "falling back to metadata" % (n_ratings, self.cold_threshold)
                        if cold
                        else "%d ratings (>= %d) - enough overlap with other users to trust "
                        "collaborative signal" % (n_ratings, self.cold_threshold)
                    ),
                }
            )
        elif strategy == "rank":
            k_rrf = 60.0
            c_rank = np.empty(self.n_items)
            f_rank = np.empty(self.n_items)
            c_rank[np.argsort(-content_raw)] = np.arange(self.n_items)
            f_rank[np.argsort(-cf_raw)] = np.arange(self.n_items)
            blended = alpha * (1.0 / (k_rrf + f_rank)) + (1 - alpha) * (1.0 / (k_rrf + c_rank))
            blended = blended / blended.max() if blended.max() > 0 else blended
            effective_alpha = alpha
            trace.update({"k_rrf": k_rrf, "content_rank": c_rank, "cf_rank": f_rank})
        elif strategy == "cascade":
            pool_size = max(n * 12, 150)
            cf_masked = cf_raw.copy()
            cf_masked[seen] = -1e9
            pool = np.argsort(-cf_masked)[:pool_size]
            blended = np.full(self.n_items, -1e9)
            blended[pool] = content_norm[pool]
            effective_alpha = 0.0
            trace.update(
                {
                    "pool_size": int(pool_size),
                    "reason": "collaborative filtering shortlisted %d candidates; content "
                    "similarity then re-ranked them" % pool_size,
                }
            )
        else:  # weighted
            blended = alpha * cf_norm + (1 - alpha) * content_norm
            effective_alpha = alpha

        scores = blended.copy()
        if seen:
            scores[seen] = -1e9
        # an item nobody comparable has rated cannot be scored collaboratively
        if strategy in ("weighted", "rank") and support is not None:
            scores[support < 1e-9] -= 0.0  # keep it, content still carries it

        order = np.argsort(-scores)[:n]
        items = []
        for pos in order:
            if scores[pos] <= -1e8:
                continue
            items.append(
                {
                    "pos": int(pos),
                    "movieId": int(self.data.item_ids[pos]),
                    "score": float(scores[pos]),
                    "content_raw": float(content_raw[pos]),
                    "content_norm": float(content_norm[pos]),
                    "cf_raw": float(cf_raw[pos]),
                    "cf_norm": float(cf_norm[pos]),
                    "cf_rating": float(cf_rating[pos]),
                    "content_part": float((1 - effective_alpha) * content_norm[pos]),
                    "cf_part": float(effective_alpha * cf_norm[pos]),
                }
            )
        trace["effective_alpha"] = effective_alpha
        return {"items": items, "trace": trace, "profile": profile,
                "content_raw": content_raw, "cf_raw": cf_raw, "cf_rating": cf_rating}

    def alpha_sweep(self, u, rated_by_pos: dict, cf_model: str = "svd", n: int = 10) -> list:
        """How the top-N list churns as alpha slides from pure content to pure CF.

        This is the clearest way to see that the two models genuinely disagree:
        if they agreed, the list would not change.
        """
        content_raw, _ = self._content_scores(rated_by_pos)
        cf_raw, _, _ = self._cf_scores(u, rated_by_pos, cf_model)
        content_norm, _, _ = minmax(content_raw)
        cf_norm, _, _ = minmax(cf_raw)
        seen = list(rated_by_pos.keys())

        out = []
        for alpha in [0.0, 0.25, 0.5, 0.75, 1.0]:
            blended = alpha * cf_norm + (1 - alpha) * content_norm
            if seen:
                blended[seen] = -1e9
            order = np.argsort(-blended)[:n]
            out.append(
                {
                    "alpha": alpha,
                    "items": [
                        {
                            "movieId": int(self.data.item_ids[p]),
                            "title": self.data.title(int(self.data.item_ids[p])),
                            "score": round(float(blended[p]), 4),
                        }
                        for p in order
                    ],
                }
            )
        return out

    def compare_sources(self, u, rated_by_pos: dict, n: int = 10, cf_model: str = "svd") -> dict:
        """Top-N from content alone, CF alone and the hybrid, plus their overlap."""
        content_raw, _ = self._content_scores(rated_by_pos)
        cf_raw, _, _ = self._cf_scores(u, rated_by_pos, cf_model)
        content_norm, _, _ = minmax(content_raw)
        cf_norm, _, _ = minmax(cf_raw)
        blended = self.alpha * cf_norm + (1 - self.alpha) * content_norm

        seen = list(rated_by_pos.keys())
        lists = {}
        for label, arr in (("content", content_raw), ("collaborative", cf_raw), ("hybrid", blended)):
            vals = arr.astype(np.float64).copy()
            if seen:
                vals[seen] = -1e9
            order = np.argsort(-vals)[:n]
            lists[label] = [int(self.data.item_ids[p]) for p in order]

        c, f, h = set(lists["content"]), set(lists["collaborative"]), set(lists["hybrid"])
        return {
            "lists": lists,
            "overlap": {
                "content_vs_cf": len(c & f),
                "hybrid_from_content_only": len(h & c - f),
                "hybrid_from_cf_only": len(h & f - c),
                "hybrid_from_both": len(h & c & f),
                "hybrid_from_neither": len(h - c - f),
            },
        }
