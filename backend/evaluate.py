"""Offline evaluation: how good are these recommendations, really?

Two very different questions get answered here, because a model can be excellent
at one and poor at the other:

  1. Rating accuracy - if it predicts 4.2, was the real rating close?
     Measured with RMSE and MAE on a held-out temporal split.

  2. Ranking quality - are the items it puts at the top actually the ones the
     user went on to like? Measured with Precision@K, Recall@K, MAP@K and NDCG@K,
     treating a held-out rating of >= 4.0 as "relevant".

Accuracy is not the whole story either, so coverage, novelty and intra-list
diversity are reported too - a model that recommends the same 20 blockbusters to
everyone can score well on precision while being useless in production.
"""
from __future__ import annotations

import time

import numpy as np

RELEVANT_AT = 4.0


# --------------------------------------------------------------------------- #
# rating accuracy
# --------------------------------------------------------------------------- #
def rating_accuracy(model_scores, data, sample_users=None) -> dict:
    """RMSE / MAE over every held-out (user, item, rating) triple."""
    errors = []
    users = sample_users if sample_users is not None else list(data.test_by_user.keys())
    for user_id in users:
        held = data.test_by_user.get(int(user_id))
        if not held:
            continue
        u = data.user_pos.get(int(user_id))
        if u is None:
            continue
        preds = model_scores(u)
        for movie_id, actual in held.items():
            pos = data.item_pos.get(int(movie_id))
            if pos is None:
                continue
            errors.append(preds[pos] - actual)
    if not errors:
        return {"rmse": None, "mae": None, "n": 0}
    err = np.asarray(errors)
    return {
        "rmse": round(float(np.sqrt((err ** 2).mean())), 4),
        "mae": round(float(np.abs(err).mean()), 4),
        "n": int(len(err)),
    }


# --------------------------------------------------------------------------- #
# ranking quality
# --------------------------------------------------------------------------- #
def _dcg(gains: np.ndarray) -> float:
    return float((gains / np.log2(np.arange(2, len(gains) + 2))).sum())


def ranking_quality(model_scores, data, k: int = 10, content=None, sample_users=None) -> dict:
    """Precision / Recall / MAP / NDCG at k, plus coverage, novelty, diversity."""
    train = data.train
    popularity = np.asarray((train > 0).sum(axis=0)).ravel()
    pop_prob = np.maximum(popularity, 1) / max(1, data.n_users)
    self_info = -np.log2(pop_prob)  # rarer item -> higher novelty

    precisions, recalls, ndcgs, maps, hits = [], [], [], [], []
    recommended_items: set = set()
    novelty_acc, diversity_acc, n_lists = 0.0, 0.0, 0

    users = sample_users if sample_users is not None else list(data.test_by_user.keys())
    for user_id in users:
        held = data.test_by_user.get(int(user_id))
        if not held:
            continue
        u = data.user_pos.get(int(user_id))
        if u is None:
            continue
        relevant = {
            data.item_pos[int(m)]
            for m, r in held.items()
            if r >= RELEVANT_AT and int(m) in data.item_pos
        }
        if not relevant:
            continue

        scores = np.asarray(model_scores(u), dtype=np.float64).copy()
        seen = train.indices[train.indptr[u] : train.indptr[u + 1]]
        scores[seen] = -np.inf  # never recommend something already in the training set
        top = np.argpartition(-scores, k)[:k]
        top = top[np.argsort(-scores[top])]

        gains = np.array([1.0 if p in relevant else 0.0 for p in top])
        n_hit = int(gains.sum())
        precisions.append(n_hit / k)
        recalls.append(n_hit / len(relevant))
        hits.append(1.0 if n_hit > 0 else 0.0)

        ideal = np.ones(min(k, len(relevant)))
        idcg = _dcg(ideal)
        ndcgs.append(_dcg(gains) / idcg if idcg > 0 else 0.0)

        if n_hit:
            cum = np.cumsum(gains)
            precs = cum / np.arange(1, k + 1)
            maps.append(float((precs * gains).sum() / min(len(relevant), k)))
        else:
            maps.append(0.0)

        recommended_items.update(int(p) for p in top)
        novelty_acc += float(self_info[top].mean())
        if content is not None and len(top) > 1:
            vecs = content.V[top]
            sims = np.asarray((vecs @ vecs.T).todense())
            n = len(top)
            off = (sims.sum() - np.trace(sims)) / (n * (n - 1))
            diversity_acc += 1.0 - float(off)
        n_lists += 1

    if n_lists == 0:
        return {}
    return {
        "k": k,
        "precision": round(float(np.mean(precisions)), 4),
        "recall": round(float(np.mean(recalls)), 4),
        "map": round(float(np.mean(maps)), 4),
        "ndcg": round(float(np.mean(ndcgs)), 4),
        "hit_rate": round(float(np.mean(hits)), 4),
        "coverage": round(len(recommended_items) / data.n_items * 100, 2),
        "novelty": round(novelty_acc / n_lists, 3),
        "diversity": round(diversity_acc / n_lists, 4) if content is not None else None,
        "n_users": n_lists,
    }


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def build_scorers(data, engine):
    """A scorer maps a user row index to a score for every item.

    All models are evaluated on the *training* split only, then scored against
    the held-out ratings they never saw.
    """
    content = engine.content_eval
    item_knn = engine.item_knn_eval
    user_knn = engine.user_knn_eval
    svd = engine.svd_eval
    baseline = engine.baseline_eval
    train = data.train

    def content_scorer(u):
        lo, hi = train.indptr[u], train.indptr[u + 1]
        rated = {
            int(data.item_ids[p]): float(v)
            for p, v in zip(train.indices[lo:hi], train.data[lo:hi])
        }
        profile = content.build_profile(rated)
        vec = profile.get("vector")
        if vec is None:
            return np.zeros(data.n_items)
        return np.asarray(content.V @ vec, dtype=np.float64)

    def content_rating_scorer(u):
        """Content similarity mapped onto the rating scale so RMSE is meaningful.

        Cosine lives in [0, 1] and knows nothing about how generously this user
        rates, so it is rescaled around the user's own mean and spread.
        """
        sims = content_scorer(u)
        lo, hi = train.indptr[u], train.indptr[u + 1]
        vals = train.data[lo:hi]
        if len(vals) == 0:
            return np.full(data.n_items, 3.5)
        mean, std = float(vals.mean()), float(vals.std())
        rated_sims = sims[train.indices[lo:hi]]
        s_mean = float(rated_sims.mean()) if len(rated_sims) else 0.0
        s_std = float(rated_sims.std()) or 1.0
        z = (sims - s_mean) / s_std
        return np.clip(mean + z * max(std, 0.4), 0.5, 5.0)

    return {
        "baseline": {
            "rank": lambda u: baseline.rank_all(u),
            "rate": lambda u: baseline.score_all(u),
            "family": "baseline",
            "label": "Bias baseline",
        },
        "content": {
            "rank": content_scorer,
            "rate": content_rating_scorer,
            "family": "content",
            "label": "Content-based (TF-IDF)",
        },
        "item-knn": {
            "rank": lambda u: item_knn.rank_all(u=u),
            "rate": lambda u: item_knn.score_all(u=u)[0],
            "family": "collaborative",
            "label": "Item-based kNN",
        },
        "user-knn": {
            "rank": lambda u: user_knn.rank_all(u=u),
            "rate": lambda u: user_knn.score_all(u=u)[0],
            "family": "collaborative",
            "label": "User-based kNN",
        },
        "svd": {
            "rank": lambda u: svd.rank_all(u=u),
            "rate": lambda u: svd.score_all(u=u)[0],
            "family": "collaborative",
            "label": "Matrix factorisation (SVD)",
        },
        "hybrid": {
            "rank": lambda u: _hybrid_scorer(engine, data, u, "item-knn"),
            "rate": lambda u: _hybrid_rating_scorer(engine, data, u, content_rating_scorer, "item-knn"),
            "family": "hybrid",
            "label": "Hybrid (content + item-kNN)",
        },
        "hybrid-svd": {
            "rank": lambda u: _hybrid_scorer(engine, data, u, "svd"),
            "rate": lambda u: _hybrid_rating_scorer(engine, data, u, content_rating_scorer, "svd"),
            "family": "hybrid",
            "label": "Hybrid (content + SVD)",
        },
    }


def _norm(values: np.ndarray) -> np.ndarray:
    lo, hi = float(values.min()), float(values.max())
    if hi - lo < 1e-12:
        return np.full_like(values, 0.5)
    return (values - lo) / (hi - lo)


def _content_vector(engine, data, u):
    train = data.train
    lo, hi = train.indptr[u], train.indptr[u + 1]
    rated = {
        int(data.item_ids[p]): float(v) for p, v in zip(train.indices[lo:hi], train.data[lo:hi])
    }
    profile = engine.content_eval.build_profile(rated)
    vec = profile.get("vector")
    if vec is None:
        return np.zeros(data.n_items)
    return np.asarray(engine.content_eval.V @ vec, dtype=np.float64)


def _cf_eval(engine, u, cf_model: str):
    if cf_model == "svd":
        return engine.svd_eval.rank_all(u=u), engine.svd_eval.score_all(u=u)[0]
    if cf_model == "user-knn":
        return engine.user_knn_eval.rank_all(u=u), engine.user_knn_eval.score_all(u=u)[0]
    return engine.item_knn_eval.rank_all(u=u), engine.item_knn_eval.score_all(u=u)[0]


def _hybrid_scorer(engine, data, u, cf_model: str = "item-knn"):
    content = _content_vector(engine, data, u)
    cf_rank, _ = _cf_eval(engine, u, cf_model)
    alpha = engine.cfg["hybrid"]["alpha"]
    return alpha * _norm(cf_rank) + (1 - alpha) * _norm(content)


def _hybrid_rating_scorer(engine, data, u, content_rating_scorer, cf_model: str = "item-knn"):
    alpha = engine.cfg["hybrid"]["alpha"]
    _, cf_rating = _cf_eval(engine, u, cf_model)
    return alpha * cf_rating + (1 - alpha) * content_rating_scorer(u)


def run_full(engine, k: int = 10, models=None) -> dict:
    """Evaluate every model on the same split and return one comparable table."""
    data = engine.data
    scorers = build_scorers(data, engine)
    chosen = models or list(scorers.keys())

    rows = []
    started = time.time()
    for name in chosen:
        spec = scorers.get(name)
        if spec is None:
            continue
        t0 = time.time()
        acc = rating_accuracy(spec["rate"], data)
        rank = ranking_quality(spec["rank"], data, k=k, content=engine.content_eval)
        rows.append(
            {
                "model": name,
                "label": spec["label"],
                "family": spec["family"],
                **acc,
                **rank,
                "seconds": round(time.time() - t0, 2),
            }
        )
    return {
        "k": k,
        "rows": rows,
        "split": {
            "train_ratings": int(data.train.nnz),
            "test_ratings": int(sum(len(v) for v in data.test_by_user.values())),
            "method": "per-user temporal holdout (newest 20% of each user's ratings)",
            "relevance_threshold": RELEVANT_AT,
        },
        "total_seconds": round(time.time() - started, 2),
    }
