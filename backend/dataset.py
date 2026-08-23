"""MovieLens loading, indexing and the rating matrix every model shares.

Downloads the dataset on first run, then builds:
  * a tidy movie catalogue (title / year / genres / tags / tmdbId)
  * integer index maps between MovieLens ids and matrix positions
  * a sparse user x item rating matrix
  * a reproducible per-user holdout split used by the evaluation page
"""
from __future__ import annotations

import io
import re
import urllib.request
import zipfile
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix

from config import CONFIG, DATA_DIR

DATASET_URLS = {
    "ml-latest-small": "https://files.grouplens.org/datasets/movielens/ml-latest-small.zip",
    "ml-25m": "https://files.grouplens.org/datasets/movielens/ml-25m.zip",
}

_YEAR_RE = re.compile(r"\((\d{4})\)\s*$")


def ensure_dataset(name: str) -> "pd.DataFrame":
    """Download + extract the MovieLens archive if it is not on disk yet."""
    folder = DATA_DIR / name
    if not (folder / "ratings.csv").exists():
        url = DATASET_URLS.get(name)
        if url is None:
            raise ValueError("Unknown dataset: " + name)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            blob = resp.read()
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            zf.extractall(DATA_DIR)
    return folder


def _split_year(title: str) -> tuple[str, int | None]:
    match = _YEAR_RE.search(title or "")
    if not match:
        return (title or "").strip(), None
    return _YEAR_RE.sub("", title).strip(), int(match.group(1))


@dataclass
class MovieData:
    """Everything the recommenders and the API need, loaded once."""

    movies: pd.DataFrame
    ratings: pd.DataFrame
    user_ids: np.ndarray
    item_ids: np.ndarray
    user_pos: dict = field(repr=False, default_factory=dict)
    item_pos: dict = field(repr=False, default_factory=dict)
    R: csr_matrix = None
    train: csr_matrix = None
    test_by_user: dict = field(repr=False, default_factory=dict)

    # ---------------------------------------------------------------- helpers
    @property
    def n_users(self) -> int:
        return len(self.user_ids)

    @property
    def n_items(self) -> int:
        return len(self.item_ids)

    def item_row(self, movie_id: int) -> dict:
        return self.movies.loc[movie_id].to_dict()

    def title(self, movie_id: int) -> str:
        try:
            return str(self.movies.at[movie_id, "title"])
        except KeyError:
            return "movie " + str(movie_id)

    def user_ratings(self, user_id: int) -> pd.DataFrame:
        return self.ratings[self.ratings["userId"] == user_id]

    def stats(self) -> dict:
        density = len(self.ratings) / float(self.n_users * self.n_items)
        return {
            "dataset": CONFIG.get("dataset"),
            "n_users": int(self.n_users),
            "n_items": int(self.n_items),
            "n_ratings": int(len(self.ratings)),
            "density": round(density * 100, 3),
            "mean_rating": round(float(self.ratings["rating"].mean()), 3),
            "rating_scale": [0.5, 5.0],
            "n_genres": int(len(self.all_genres)),
        }

    @property
    def all_genres(self) -> list:
        seen: set = set()
        for row in self.movies["genre_list"]:
            seen.update(row)
        return sorted(seen)


def load() -> MovieData:
    name = CONFIG.get("dataset", "ml-latest-small")
    folder = ensure_dataset(name)

    ratings = pd.read_csv(folder / "ratings.csv")
    movies = pd.read_csv(folder / "movies.csv")
    links = pd.read_csv(folder / "links.csv")
    try:
        tags = pd.read_csv(folder / "tags.csv")
    except FileNotFoundError:
        tags = pd.DataFrame(columns=["userId", "movieId", "tag", "timestamp"])

    # keep only movies that actually carry a rating: nothing can be learned about the rest
    rated = set(ratings["movieId"].unique())
    movies = movies[movies["movieId"].isin(rated)].copy()

    parsed = movies["title"].map(_split_year)
    movies["clean_title"] = [p[0] for p in parsed]
    movies["year"] = [p[1] for p in parsed]
    movies["genre_list"] = movies["genres"].fillna("").map(
        lambda g: [x for x in g.split("|") if x and x != "(no genres listed)"]
    )

    movies = movies.merge(links[["movieId", "tmdbId", "imdbId"]], on="movieId", how="left")

    tags["tag"] = tags["tag"].astype(str).str.lower().str.strip()
    tag_map = tags.groupby("movieId")["tag"].apply(lambda s: list(s)[:30]).to_dict()
    movies["tags"] = movies["movieId"].map(lambda m: tag_map.get(m, []))

    agg = ratings.groupby("movieId")["rating"].agg(["count", "mean"])
    movies = movies.merge(
        agg.rename(columns={"count": "n_ratings", "mean": "avg_rating"}),
        left_on="movieId",
        right_index=True,
        how="left",
    )
    movies["n_ratings"] = movies["n_ratings"].fillna(0).astype(int)
    movies["avg_rating"] = movies["avg_rating"].fillna(0.0)
    movies = movies.set_index("movieId", drop=False).sort_index()

    user_ids = np.sort(ratings["userId"].unique())
    item_ids = np.array(movies["movieId"].values)
    user_pos = {int(u): i for i, u in enumerate(user_ids)}
    item_pos = {int(m): i for i, m in enumerate(item_ids)}

    rows = ratings["userId"].map(user_pos).to_numpy()
    cols = ratings["movieId"].map(item_pos).to_numpy()
    vals = ratings["rating"].to_numpy(dtype=np.float32)
    R = csr_matrix((vals, (rows, cols)), shape=(len(user_ids), len(item_ids)))

    data = MovieData(
        movies=movies,
        ratings=ratings,
        user_ids=user_ids,
        item_ids=item_ids,
        user_pos=user_pos,
        item_pos=item_pos,
        R=R,
    )
    data.train, data.test_by_user = _holdout_split(data, ratings)
    return data


def _holdout_split(data: MovieData, ratings: pd.DataFrame, test_frac: float = 0.2, seed: int = 42):
    """Per-user temporal holdout: newest ~20% of each user's ratings become the test set.

    A temporal split is the honest one for recommenders - a random split lets the
    model peek at a user's future taste when predicting their past.
    """
    rng = np.random.default_rng(seed)
    ordered = ratings.sort_values(["userId", "timestamp"], kind="mergesort")
    test_rows: list = []
    test_by_user: dict = {}

    for user_id, group in ordered.groupby("userId", sort=False):
        n = len(group)
        n_test = int(round(n * test_frac))
        n_test = max(1, min(n_test, n - 5)) if n > 6 else 0
        if n_test <= 0:
            continue
        held = group.iloc[n - n_test :]
        test_rows.append(held)
        test_by_user[int(user_id)] = {
            int(m): float(r) for m, r in zip(held["movieId"], held["rating"])
        }

    test_df = pd.concat(test_rows) if test_rows else ratings.iloc[0:0]
    test_keys = set(zip(test_df["userId"], test_df["movieId"]))
    mask = [
        (u, m) not in test_keys for u, m in zip(ratings["userId"], ratings["movieId"])
    ]
    train_df = ratings[mask]

    rows = train_df["userId"].map(data.user_pos).to_numpy()
    cols = train_df["movieId"].map(data.item_pos).to_numpy()
    vals = train_df["rating"].to_numpy(dtype=np.float32)
    train = csr_matrix((vals, (rows, cols)), shape=(data.n_users, data.n_items))
    _ = rng  # split is fully deterministic; rng kept for future sampling variants
    return train, test_by_user
