"""Progressive TMDB enrichment.

The app is fully usable the moment it starts (MovieLens genres + tags are enough
for a working content model). This warmer runs in the background and folds in
TMDB keywords / cast / directors in popularity order, so the movies people
actually see get richer first. Progress is persisted, so it resumes.
"""
from __future__ import annotations

import threading
import time

import tmdb

_STATE = {
    "running": False,
    "done": 0,
    "total": 0,
    "started_at": None,
    "finished_at": None,
    "rate": 0.0,
}
_LOCK = threading.Lock()
_STOP = threading.Event()


def status() -> dict:
    with _LOCK:
        state = dict(_STATE)
    state["cached"] = tmdb.cache_size()
    remaining = max(0, state["total"] - state["done"])
    state["eta_seconds"] = int(remaining / state["rate"]) if state["rate"] > 0.05 else None
    return state


def _worker(targets: list, workers: int, on_progress, retry_missing: bool) -> None:
    started = time.time()
    with _LOCK:
        _STATE.update(
            {"running": True, "done": 0, "total": len(targets), "started_at": started,
             "finished_at": None, "rate": 0.0}
        )

    batch = 40
    for start in range(0, len(targets), batch):
        if _STOP.is_set():
            break
        chunk = targets[start : start + batch]
        try:
            tmdb.fetch_many(chunk, workers=workers, retry_missing=retry_missing)
        except Exception:
            pass
        done = min(start + batch, len(targets))
        elapsed = max(1e-6, time.time() - started)
        with _LOCK:
            _STATE["done"] = done
            _STATE["rate"] = done / elapsed
        if on_progress:
            try:
                on_progress(done, len(tmdb_ids))
            except Exception:
                pass

    tmdb.flush_cache()
    with _LOCK:
        _STATE["running"] = False
        _STATE["finished_at"] = time.time()


def start(data, workers: int = 24, on_progress=None, retry_missing: bool = False) -> bool:
    """Kick off enrichment for every uncached film, most-rated first.

    ``retry_missing`` also revisits films previously marked missing, this time
    searching TMDB by title - MovieLens ids for miniseries and re-issued entries
    are frequently dead.
    """
    with _LOCK:
        if _STATE["running"]:
            return False
    _STOP.clear()

    ordered = data.movies.sort_values("n_ratings", ascending=False)
    pending = []
    for row in ordered.itertuples():
        tmdb_id = row.tmdbId if row.tmdbId == row.tmdbId else None
        cached = tmdb.cached_only(tmdb_id) if tmdb_id is not None else None
        if cached is not None:
            continue
        if not retry_missing and tmdb_id is not None and tmdb.is_known_missing(tmdb_id):
            continue
        year = int(row.year) if row.year == row.year else None
        pending.append((tmdb_id, str(row.clean_title), year))

    if not pending:
        with _LOCK:
            _STATE.update({"done": 0, "total": 0, "finished_at": time.time()})
        return False

    thread = threading.Thread(
        target=_worker,
        args=(pending, workers, on_progress, retry_missing),
        daemon=True,
        name="tmdb-enrich",
    )
    thread.start()
    return True


def stop() -> None:
    _STOP.set()


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    import dataset

    data = dataset.load()
    print("route:", tmdb.route_status())
    repair = "--repair" in sys.argv  # retry dead ids via TMDB title search
    start(
        data, workers=24, retry_missing=repair,
        on_progress=lambda d, t: print("  %d/%d" % (d, t), flush=True),
    )
    while status()["running"]:
        time.sleep(5)
    print("done:", status(), "| cached:", tmdb.cache_size(), "| missing:", tmdb.missing_count())
