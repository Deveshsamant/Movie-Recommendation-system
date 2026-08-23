"""Collaborative filtering: neighbourhood models + matrix factorisation.

Three models, all trained on the same user x item matrix and all able to show
their arithmetic:

  * ItemKNN  - adjusted-cosine item neighbourhoods (Sarwar et al., 2001)
  * UserKNN  - Pearson user neighbourhoods (Resnick et al., GroupLens 1994)
  * BiasSVD  - biased matrix factorisation trained by SGD (Funk / Koren 2009)

None of them look at movie metadata: everything comes from the rating pattern.

Design note: each model exposes a vectorised ``score_all`` and a single-item
``explain`` path, and the two are guaranteed to produce the same number. A tool
that shows one calculation while ranking by another would be teaching a lie.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from scipy import sparse
from scipy.sparse import csr_matrix, diags

from config import CACHE_DIR

RATING_MIN, RATING_MAX = 0.5, 5.0


def _row_means(R: csr_matrix) -> np.ndarray:
    counts = np.diff(R.indptr)
    sums = np.add.reduceat(R.data, R.indptr[:-1]) if R.nnz else np.zeros(R.shape[0])
    sums = np.where(counts > 0, sums, 0.0)
    return np.divide(sums, np.maximum(counts, 1))


def _centre_rows(R: csr_matrix, means: np.ndarray) -> csr_matrix:
    out = R.copy().astype(np.float64)
    counts = np.diff(R.indptr)
    out.data = out.data - np.repeat(means, counts)
    return out


# --------------------------------------------------------------------------- #
# shared baseline
# --------------------------------------------------------------------------- #
class Baseline:
    """r_hat = mu + b_u + b_i, fitted by alternating ridge updates.

    Biases explain a surprising amount on their own: some users rate generously,
    some movies are simply better liked. The other models learn the residual.
    """

    name = "baseline"

    def __init__(self, R: csr_matrix, reg_u: float = 10.0, reg_i: float = 12.0, n_iter: int = 15):
        self.n_users, self.n_items = R.shape
        coo = R.tocoo()
        self.mu = float(coo.data.mean()) if coo.nnz else 3.5
        self.bu = np.zeros(self.n_users)
        self.bi = np.zeros(self.n_items)

        rows, cols, vals = coo.row, coo.col, coo.data
        n_u = np.bincount(rows, minlength=self.n_users)
        n_i = np.bincount(cols, minlength=self.n_items)
        for _ in range(n_iter):
            resid = vals - self.mu - self.bu[rows]
            self.bi = np.bincount(cols, weights=resid, minlength=self.n_items) / (n_i + reg_i)
            resid = vals - self.mu - self.bi[cols]
            self.bu = np.bincount(rows, weights=resid, minlength=self.n_users) / (n_u + reg_u)

    def predict_one(self, u: int, i: int) -> float:
        return float(np.clip(self.mu + self.bu[u] + self.bi[i], RATING_MIN, RATING_MAX))

    def score_all(self, u: int) -> np.ndarray:
        return np.clip(self.mu + self.bu[u] + self.bi, RATING_MIN, RATING_MAX)

    def rank_all(self, u: int) -> np.ndarray:
        return np.asarray(self.mu + self.bu[u] + self.bi, dtype=np.float64)


# --------------------------------------------------------------------------- #
# item-based kNN
# --------------------------------------------------------------------------- #
class ItemKNN:
    """Adjusted-cosine item similarity with significance shrinkage.

    Ratings are centred per user before the cosine, which cancels the "this user
    rates everything a 4" effect. Similarities backed by few co-raters are shrunk
    toward zero:  sim' = sim * n_common / (n_common + lambda).

    Prediction for user u, item i, using the k stored neighbours of i that u rated:

        r_hat(u,i) = mean_u + sum_j sim(i,j) * (r_uj - mean_u) / sum_j |sim(i,j)|
    """

    name = "item-knn"

    def __init__(self, R: csr_matrix, k: int = 40, shrinkage: float = 25.0, S=None):
        self.R = R.tocsr()
        self.k = k
        self.shrinkage = shrinkage
        self.n_users, self.n_items = R.shape
        self.user_mean = _row_means(self.R)
        self.S = S if S is not None else self._build_similarity()
        self.S_abs = abs(self.S)

    def _build_similarity(self) -> csr_matrix:
        centred = _centre_rows(self.R, self.user_mean)
        norms = np.sqrt(np.asarray(centred.multiply(centred).sum(axis=0))).ravel()
        norms = np.maximum(norms, 1e-9)
        Cn = csr_matrix(centred @ diags(1.0 / norms))  # unit-norm columns
        binary = csr_matrix((self.R > 0).astype(np.float32))

        rows, cols, vals = [], [], []
        block = 512
        CnT = csr_matrix(Cn.T)
        binT = csr_matrix(binary.T)
        for start in range(0, self.n_items, block):
            stop = min(start + block, self.n_items)
            sims = np.asarray((CnT[start:stop] @ Cn).todense())
            common = np.asarray((binT[start:stop] @ binary).todense())
            sims *= common / (common + self.shrinkage)
            for r, i in enumerate(range(start, stop)):
                sims[r, i] = 0.0
            sims[sims <= 0] = 0.0
            take = min(self.k, self.n_items - 1)
            idx = np.argpartition(-sims, take - 1, axis=1)[:, :take]
            rr = np.arange(sims.shape[0])[:, None]
            keep = sims[rr, idx]
            nz = keep > 0
            for r in range(sims.shape[0]):
                sel = idx[r][nz[r]]
                rows.extend([start + r] * len(sel))
                cols.extend(sel.tolist())
                vals.extend(keep[r][nz[r]].tolist())
        return csr_matrix(
            (np.array(vals, dtype=np.float64), (rows, cols)),
            shape=(self.n_items, self.n_items),
        )

    # ----------------------------------------------------------------- scoring
    def _profile(self, u: int | None, ratings: dict | None):
        if ratings is not None:
            items = np.array([int(i) for i in ratings], dtype=np.int64)
            vals = np.array([float(ratings[i]) for i in ratings], dtype=np.float64)
        else:
            lo, hi = self.R.indptr[u], self.R.indptr[u + 1]
            items = self.R.indices[lo:hi].astype(np.int64)
            vals = self.R.data[lo:hi].astype(np.float64)
        mean = float(vals.mean()) if len(vals) else float(self.mu_global())
        dev = np.zeros(self.n_items)
        mask = np.zeros(self.n_items)
        dev[items] = vals - mean
        mask[items] = 1.0
        return items, vals, mean, dev, mask

    def mu_global(self) -> float:
        return float(self.R.data.mean()) if self.R.nnz else 3.5

    def score_all(self, u: int | None = None, ratings: dict | None = None):
        """Predicted rating for every item, plus the neighbour support behind it."""
        _, _, mean, dev, mask = self._profile(u, ratings)
        numer = self.S @ dev
        denom = self.S_abs @ mask
        preds = np.where(denom > 1e-9, mean + numer / np.maximum(denom, 1e-9), mean)
        return np.clip(preds, RATING_MIN, RATING_MAX), denom

    def rank_all(self, u: int | None = None, ratings: dict | None = None):
        """Top-N ranking score: the *un-normalised* similarity-weighted sum.

        Ranking and rating prediction are different jobs. Dividing by the sum of
        similarities - which rating prediction must do - lets an item supported by
        one weak neighbour reach 5.0 and tie with genuinely strong picks. Keeping
        the raw sum keeps the *strength of the evidence* inside the score. This is
        the classic top-N formulation of Deshpande & Karypis (2004).
        """
        _, _, _, dev, _ = self._profile(u, ratings)
        return np.asarray(self.S @ dev, dtype=np.float64)

    def predict_one(self, target: int, u: int | None = None, ratings: dict | None = None,
                    explain: bool = False):
        items, vals, mean, dev, mask = self._profile(u, ratings)
        lo, hi = self.S.indptr[target], self.S.indptr[target + 1]
        nb_idx = self.S.indices[lo:hi]
        nb_sim = self.S.data[lo:hi]
        rated = mask[nb_idx] > 0
        nb_idx, nb_sim = nb_idx[rated], nb_sim[rated]

        if len(nb_idx) == 0:
            empty = {"neighbours": [], "numerator": 0.0, "denominator": 0.0,
                     "user_mean": round(mean, 3), "k_used": 0}
            return (float(np.clip(mean, RATING_MIN, RATING_MAX)), empty) if explain else float(mean)

        devs = dev[nb_idx]
        numer = float((nb_sim * devs).sum())
        denom = float(np.abs(nb_sim).sum())
        raw = mean + numer / denom if denom > 0 else mean
        pred = float(np.clip(raw, RATING_MIN, RATING_MAX))
        if not explain:
            return pred

        neighbours = [
            {
                "item_pos": int(nb_idx[n]),
                "similarity": round(float(nb_sim[n]), 4),
                "your_rating": round(float(devs[n] + mean), 2),
                "deviation": round(float(devs[n]), 3),
                "term": round(float(nb_sim[n] * devs[n]), 4),
            }
            for n in range(len(nb_idx))
        ]
        neighbours.sort(key=lambda x: -abs(x["term"]))
        return pred, {
            "neighbours": neighbours[:8],
            "numerator": round(numer, 4),
            "denominator": round(denom, 4),
            "user_mean": round(mean, 3),
            "k_used": int(len(nb_idx)),
            "raw": round(raw, 4),
        }

    def recommend(self, u=None, ratings=None, n=12):
        """Rank by evidence strength, but report the predicted rating alongside."""
        rank = self.rank_all(u, ratings)
        preds, denom = self.score_all(u, ratings)
        seen = set()
        if ratings is not None:
            seen = {int(i) for i in ratings}
        elif u is not None:
            seen = set(self.R.indices[self.R.indptr[u] : self.R.indptr[u + 1]].tolist())
        scores = rank.copy()
        if seen:
            scores[list(seen)] = -np.inf
        order = np.argsort(-scores)[:n]
        return [
            (int(i), float(preds[i]), float(rank[i]), float(denom[i]))
            for i in order
            if np.isfinite(scores[i])
        ]

    def similar_items(self, item_pos: int, n: int = 12):
        lo, hi = self.S.indptr[item_pos], self.S.indptr[item_pos + 1]
        idx, sim = self.S.indices[lo:hi], self.S.data[lo:hi]
        order = np.argsort(-sim)[:n]
        return [(int(idx[o]), float(sim[o])) for o in order]

    def save(self, path: Path) -> None:
        sparse.save_npz(path, self.S.tocsr())

    @classmethod
    def cached(cls, R: csr_matrix, k: int, shrinkage: float, tag: str):
        key = "itemknn_%s_%d_%d_%d_%d_%d.npz" % (tag, R.shape[0], R.shape[1], R.nnz, k, int(shrinkage))
        path = CACHE_DIR / key
        if path.exists():
            try:
                return cls(R, k=k, shrinkage=shrinkage, S=sparse.load_npz(path).tocsr())
            except Exception:
                pass
        model = cls(R, k=k, shrinkage=shrinkage)
        try:
            model.save(path)
        except Exception:
            pass
        return model


# --------------------------------------------------------------------------- #
# user-based kNN
# --------------------------------------------------------------------------- #
class UserKNN:
    """Pearson-correlation user neighbourhoods with significance shrinkage.

    A fixed neighbourhood of the k most similar users is chosen once per user;
    every prediction then uses whichever of those neighbours rated the item:

        r_hat(u,i) = mean_u + sum_v sim(u,v) * (r_vi - mean_v) / sum_v |sim(u,v)|
    """

    name = "user-knn"

    def __init__(self, R: csr_matrix, k: int = 40, shrinkage: float = 25.0):
        self.R = R.tocsr()
        self.k = k
        self.shrinkage = shrinkage
        self.n_users, self.n_items = R.shape
        self.user_mean = _row_means(self.R)

        self.C = _centre_rows(self.R, self.user_mean)
        norms = np.sqrt(np.asarray(self.C.multiply(self.C).sum(axis=1))).ravel()
        self.norms = np.maximum(norms, 1e-9)
        Cn = diags(1.0 / self.norms) @ self.C

        self.S = np.asarray((Cn @ Cn.T).todense())
        self.binary = csr_matrix((self.R > 0).astype(np.float32))
        common = np.asarray((self.binary @ self.binary.T).todense())
        self.S *= common / (common + self.shrinkage)
        np.fill_diagonal(self.S, 0.0)
        self.common = common

    def _neighbourhood(self, sims: np.ndarray):
        order = np.argsort(-sims)[: self.k]
        order = order[sims[order] > 0]
        return order, sims[order]

    def _sims_for(self, u: int | None, ratings: dict | None):
        if ratings is None:
            return self.S[u], float(self.user_mean[u])
        items = np.array([int(i) for i in ratings], dtype=np.int64)
        vals = np.array([float(ratings[i]) for i in ratings], dtype=np.float64)
        mean = float(vals.mean()) if len(vals) else 3.5
        vec = np.zeros(self.n_items)
        vec[items] = vals - mean
        norm = max(float(np.linalg.norm(vec)), 1e-9)
        sims = np.asarray(self.C @ vec).ravel() / (self.norms * norm)
        mask = np.zeros(self.n_items, dtype=np.float32)
        mask[items] = 1.0
        common = np.asarray(self.binary @ mask).ravel()
        sims = sims * (common / (common + self.shrinkage))
        return sims, mean

    def score_all(self, u: int | None = None, ratings: dict | None = None):
        sims, mean = self._sims_for(u, ratings)
        nb, weights = self._neighbourhood(sims)
        if len(nb) == 0:
            return np.full(self.n_items, mean), np.zeros(self.n_items)
        sub = self.R[nb].toarray()
        rated = (sub > 0).astype(np.float64)
        dev = np.where(sub > 0, sub - self.user_mean[nb][:, None], 0.0)
        numer = weights @ dev
        denom = np.abs(weights) @ rated
        preds = np.where(denom > 1e-9, mean + numer / np.maximum(denom, 1e-9), mean)
        return np.clip(preds, RATING_MIN, RATING_MAX), denom

    def rank_all(self, u: int | None = None, ratings: dict | None = None):
        """Un-normalised neighbour-weighted sum - see ItemKNN.rank_all."""
        sims, _ = self._sims_for(u, ratings)
        nb, weights = self._neighbourhood(sims)
        if len(nb) == 0:
            return np.zeros(self.n_items)
        sub = self.R[nb].toarray()
        dev = np.where(sub > 0, sub - self.user_mean[nb][:, None], 0.0)
        return np.asarray(weights @ dev, dtype=np.float64)

    def predict_one(self, target: int, u: int | None = None, ratings: dict | None = None,
                    explain: bool = False):
        sims, mean = self._sims_for(u, ratings)
        nb, weights = self._neighbourhood(sims)
        column = self.R[:, target].toarray().ravel()
        keep = column[nb] > 0
        nb, weights = nb[keep], weights[keep]

        if len(nb) == 0:
            empty = {"neighbours": [], "numerator": 0.0, "denominator": 0.0,
                     "user_mean": round(mean, 3), "k_used": 0,
                     "n_raters": int((column > 0).sum())}
            return (float(np.clip(mean, RATING_MIN, RATING_MAX)), empty) if explain else float(mean)

        devs = column[nb] - self.user_mean[nb]
        numer = float((weights * devs).sum())
        denom = float(np.abs(weights).sum())
        raw = mean + numer / denom if denom > 0 else mean
        pred = float(np.clip(raw, RATING_MIN, RATING_MAX))
        if not explain:
            return pred

        neighbours = [
            {
                "user_pos": int(nb[n]),
                "similarity": round(float(weights[n]), 4),
                "their_rating": round(float(column[nb[n]]), 2),
                "their_mean": round(float(self.user_mean[nb[n]]), 2),
                "deviation": round(float(devs[n]), 3),
                "co_rated": int(self.common[u, nb[n]]) if u is not None else None,
                "term": round(float(weights[n] * devs[n]), 4),
            }
            for n in range(len(nb))
        ]
        neighbours.sort(key=lambda x: -abs(x["term"]))
        return pred, {
            "neighbours": neighbours[:8],
            "numerator": round(numer, 4),
            "denominator": round(denom, 4),
            "user_mean": round(mean, 3),
            "k_used": int(len(nb)),
            "n_raters": int((column > 0).sum()),
            "raw": round(raw, 4),
        }

    def recommend(self, u=None, ratings=None, n=12):
        rank = self.rank_all(u, ratings)
        preds, denom = self.score_all(u, ratings)
        if ratings is not None:
            seen = {int(i) for i in ratings}
        else:
            seen = set(self.R.indices[self.R.indptr[u] : self.R.indptr[u + 1]].tolist())
        scores = rank.copy()
        if seen:
            scores[list(seen)] = -np.inf
        order = np.argsort(-scores)[:n]
        return [
            (int(i), float(preds[i]), float(rank[i]), float(denom[i]))
            for i in order
            if np.isfinite(scores[i])
        ]

    def similar_users(self, u: int | None = None, ratings: dict | None = None, n: int = 10):
        sims, _ = self._sims_for(u, ratings)
        order = np.argsort(-sims)[:n]
        out = []
        for i in order:
            if sims[i] <= 0:
                continue
            co = int(self.common[u, i]) if u is not None else None
            out.append(
                {
                    "user_pos": int(i),
                    "similarity": round(float(sims[i]), 4),
                    "co_rated": co,
                    "n_ratings": int(np.diff(self.R.indptr)[i]),
                    "mean": round(float(self.user_mean[i]), 2),
                }
            )
        return out


# --------------------------------------------------------------------------- #
# biased matrix factorisation
# --------------------------------------------------------------------------- #
class BiasSVD:
    """r_hat = mu + b_u + b_i + p_u . q_i, trained by mini-batch SGD.

    The model family that won the Netflix Prize. Every user and movie gets a
    vector of latent factors discovered from the ratings alone; their dot product
    measures how well the movie's mix lines up with the user's taste. Training
    minimises squared error with L2 regularisation on all learned parameters.
    """

    name = "svd"

    def __init__(self, R: csr_matrix, n_factors=64, n_epochs=40, lr=0.007, reg=0.05,
                 seed=42, batch=4096, verbose=False):
        self.R = R.tocsr()
        self.n_users, self.n_items = R.shape
        self.n_factors = n_factors
        self.n_epochs = n_epochs
        self.lr = lr
        self.reg = reg
        self.seed = seed
        self.batch = batch
        self.history: list = []
        self._fit(verbose)

    def _fit(self, verbose: bool) -> None:
        rng = np.random.default_rng(self.seed)
        coo = self.R.tocoo()
        rows, cols = coo.row.astype(np.int64), coo.col.astype(np.int64)
        vals = coo.data.astype(np.float64)
        n = len(vals)

        self.mu = float(vals.mean())
        self.bu = np.zeros(self.n_users)
        self.bi = np.zeros(self.n_items)
        self.P = rng.normal(0, 0.05, (self.n_users, self.n_factors))
        self.Q = rng.normal(0, 0.05, (self.n_items, self.n_factors))

        started = time.time()
        for epoch in range(self.n_epochs):
            order = rng.permutation(n)
            lr = self.lr / (1.0 + 0.03 * epoch)  # decay: refine, do not oscillate
            sq_err = 0.0
            for start in range(0, n, self.batch):
                idx = order[start : start + self.batch]
                u, i, r = rows[idx], cols[idx], vals[idx]
                pu, qi = self.P[u], self.Q[i]
                pred = self.mu + self.bu[u] + self.bi[i] + np.einsum("ij,ij->i", pu, qi)
                err = r - pred
                sq_err += float((err ** 2).sum())
                np.add.at(self.bu, u, lr * (err - self.reg * self.bu[u]))
                np.add.at(self.bi, i, lr * (err - self.reg * self.bi[i]))
                np.add.at(self.P, u, lr * (err[:, None] * qi - self.reg * pu))
                np.add.at(self.Q, i, lr * (err[:, None] * pu - self.reg * qi))

            self.history.append({"epoch": epoch + 1, "train_rmse": round(float(np.sqrt(sq_err / n)), 4)})
            if verbose:
                print("  epoch %2d  train RMSE %.4f" % (epoch + 1, self.history[-1]["train_rmse"]), flush=True)
        self.train_seconds = round(time.time() - started, 2)

    # ------------------------------------------------------------- inference
    def _explain(self, p, b, i, dot, raw, pred):
        contributions = p * self.Q[i]
        order = np.argsort(-np.abs(contributions))[:8]
        return {
            "mu": round(float(self.mu), 4),
            "b_u": round(float(b), 4),
            "b_i": round(float(self.bi[i]), 4),
            "dot": round(float(dot), 4),
            "raw": round(float(raw), 4),
            # bool() matters: a numpy bool_ is not JSON-serialisable
            "clipped": bool(abs(float(raw) - float(pred)) > 1e-9),
            "n_factors": int(self.n_factors),
            "factors": [
                {
                    "k": int(f),
                    "p_u": round(float(p[f]), 4),
                    "q_i": round(float(self.Q[i, f]), 4),
                    "product": round(float(contributions[f]), 4),
                }
                for f in order
            ],
        }

    def predict_one(self, target: int, u: int | None = None, p=None, b=None, explain: bool = False):
        if p is None:
            p, b = self.P[u], self.bu[u]
        dot = float(p @ self.Q[target])
        raw = self.mu + b + self.bi[target] + dot
        pred = float(np.clip(raw, RATING_MIN, RATING_MAX))
        if not explain:
            return pred
        return pred, self._explain(p, b, target, dot, raw, pred)

    def score_all(self, u: int | None = None, p=None, b=None):
        if p is None:
            p, b = self.P[u], self.bu[u]
        preds = np.clip(self.mu + b + self.bi + self.Q @ p, RATING_MIN, RATING_MAX)
        return preds, np.ones(self.n_items)

    def rank_all(self, u: int | None = None, p=None, b=None):
        """Unclipped score. Clipping at 5.0 creates hundreds of exact ties, and a
        tie is resolved by array order - which is not a ranking at all."""
        if p is None:
            p, b = self.P[u], self.bu[u]
        return np.asarray(self.mu + b + self.bi + self.Q @ p, dtype=np.float64)

    def recommend(self, u=None, p=None, b=None, n=12, seen: set | None = None):
        preds, _ = self.score_all(u, p, b)
        rank = self.rank_all(u, p, b)
        if seen is None and u is not None:
            seen = set(self.R.indices[self.R.indptr[u] : self.R.indptr[u + 1]].tolist())
        scores = rank.copy()
        if seen:
            scores[list(seen)] = -np.inf
        order = np.argsort(-scores)[:n]
        return [
            (int(i), float(preds[i]), float(rank[i]), 1.0)
            for i in order
            if np.isfinite(scores[i])
        ]

    # ------------------------------------------------------------- fold-in
    def fold_in(self, ratings: dict, n_iter: int = 8):
        """Learn p_u and b_u for a brand-new user without retraining.

        Item factors stay frozen, so this is a small ridge regression solved in
        closed form and alternated with the user-bias update:

            p = (Qr' Qr + lambda I)^-1  Qr' e,   e = r - mu - b_u - b_i
        """
        items = np.array([int(i) for i in ratings], dtype=np.int64)
        vals = np.array([float(ratings[i]) for i in ratings], dtype=np.float64)
        if len(items) == 0:
            return np.zeros(self.n_factors), 0.0

        Qr = self.Q[items]
        reg = max(self.reg, 0.02) * len(items)
        A = Qr.T @ Qr + reg * np.eye(self.n_factors)
        p = np.zeros(self.n_factors)
        b = 0.0
        for _ in range(n_iter):
            b = float(np.mean(vals - self.mu - self.bi[items] - Qr @ p))
            e = vals - self.mu - b - self.bi[items]
            p = np.linalg.solve(A, Qr.T @ e)
        return p, b

    # ------------------------------------------------------------- persistence
    def save(self, path: Path) -> None:
        np.savez_compressed(
            path, mu=self.mu, bu=self.bu, bi=self.bi, P=self.P, Q=self.Q,
            history=np.array([h["train_rmse"] for h in self.history]),
            meta=np.array([self.n_factors, self.n_epochs, self.lr, self.reg, self.seed]),
        )

    @classmethod
    def load(cls, path: Path, R: csr_matrix):
        blob = np.load(path)
        obj = cls.__new__(cls)
        obj.R = R.tocsr()
        obj.n_users, obj.n_items = R.shape
        obj.mu = float(blob["mu"])
        obj.bu, obj.bi = blob["bu"], blob["bi"]
        obj.P, obj.Q = blob["P"], blob["Q"]
        meta = blob["meta"]
        obj.n_factors, obj.n_epochs = int(meta[0]), int(meta[1])
        obj.lr, obj.reg, obj.seed = float(meta[2]), float(meta[3]), int(meta[4])
        obj.batch = 4096
        obj.history = [{"epoch": n + 1, "train_rmse": float(v)} for n, v in enumerate(blob["history"])]
        obj.train_seconds = 0.0
        return obj


def cached_svd(R: csr_matrix, params: dict, tag: str, verbose: bool = False) -> BiasSVD:
    """Train once, reuse afterwards - keyed by matrix shape and hyper-parameters."""
    key = "svd_%s_%d_%d_%d_%s_%s.npz" % (
        tag, R.shape[0], R.shape[1], R.nnz, params.get("n_factors"), params.get("n_epochs"),
    )
    path = CACHE_DIR / key
    if path.exists():
        try:
            return BiasSVD.load(path, R)
        except Exception:
            pass
    model = BiasSVD(
        R,
        n_factors=params.get("n_factors", 64),
        n_epochs=params.get("n_epochs", 40),
        lr=params.get("lr", 0.007),
        reg=params.get("reg", 0.05),
        seed=params.get("seed", 42),
        verbose=verbose,
    )
    try:
        model.save(path)
    except Exception:
        pass
    return model
