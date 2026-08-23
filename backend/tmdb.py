"""TMDB client with automatic route failover, disk cache and graceful degradation.

Some ISPs (notably several in India) DNS-poison ``api.themoviedb.org`` while
leaving the image CDN and the legacy ``api.tmdb.org`` alias reachable. This
client probes the available routes once, remembers the winner, and keeps working
even when every route fails - callers simply get ``None`` posters.
"""
from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests

from config import CACHE_DIR, CONFIG

IMAGE_BASE = "https://image.tmdb.org/t/p/"
POSTER_SIZE = "w342"
BACKDROP_SIZE = "w780"

_CACHE_PATH = CACHE_DIR / "tmdb_cache.json"
_ROUTE_PATH = CACHE_DIR / "tmdb_route.json"

_LOCK = threading.RLock()
_MEM: dict[str, dict] = {}
_DIRTY = False
_ROUTE: dict[str, Any] | None = None


# --------------------------------------------------------------------------- #
# cache
# --------------------------------------------------------------------------- #
def _load_cache() -> None:
    global _MEM
    if _CACHE_PATH.exists():
        try:
            _MEM = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
            return
        except Exception:
            pass
    _MEM = {}


def flush_cache() -> None:
    global _DIRTY
    with _LOCK:
        if not _DIRTY:
            return
        tmp = _CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(_MEM), encoding="utf-8")
        tmp.replace(_CACHE_PATH)
        _DIRTY = False


_load_cache()


# --------------------------------------------------------------------------- #
# routing
# --------------------------------------------------------------------------- #
def _doh_resolve(host: str) -> list[str]:
    """Resolve a hostname through DNS-over-HTTPS, bypassing a poisoned resolver."""
    providers = (
        ("https://cloudflare-dns.com/dns-query", {"name": host, "type": "A"}),
        ("https://dns.google/resolve", {"name": host, "type": "A"}),
    )
    for url, params in providers:
        try:
            resp = requests.get(
                url, params=params, headers={"accept": "application/dns-json"}, timeout=8
            )
            answers = resp.json().get("Answer", [])
            ips = [a["data"] for a in answers if a.get("type") == 1]
            if ips:
                return ips
        except Exception:
            continue
    return []


def _candidate_routes() -> list[dict]:
    routes: list[dict] = [
        {"kind": "host", "host": "api.themoviedb.org"},
        {"kind": "host", "host": "api.tmdb.org"},
    ]
    for ip in _doh_resolve("api.themoviedb.org")[:2]:
        routes.append({"kind": "ip", "host": "api.themoviedb.org", "ip": ip})
    return routes


def _request(route: dict, path: str, params: dict, timeout: float) -> dict | None:
    """Perform one GET against a specific route. Returns parsed JSON or None."""
    query = dict(params)
    query["api_key"] = CONFIG.get("tmdb_api_key", "")

    if route["kind"] == "host":
        url = "https://" + route["host"] + "/3" + path
        resp = requests.get(url, params=query, timeout=timeout)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (401, 404):
            return {"__status__": resp.status_code}
        return None

    # Direct-IP route: keep full TLS verification by pinning SNI to the real host.
    import certifi
    import urllib3

    pool = urllib3.HTTPSConnectionPool(
        route["ip"],
        port=443,
        server_hostname=route["host"],
        assert_hostname=route["host"],
        cert_reqs="CERT_REQUIRED",
        ca_certs=certifi.where(),
        timeout=urllib3.Timeout(connect=timeout, read=timeout),
        retries=False,
    )
    resp = pool.request(
        "GET",
        "/3" + path,
        fields=query,
        headers={"Host": route["host"], "Accept": "application/json"},
    )
    if resp.status in (401, 404):
        return {"__status__": resp.status}
    if resp.status != 200:
        return None
    return json.loads(resp.data.decode("utf-8"))


def get_route(force: bool = False) -> dict:
    """Find (once) a working route to the TMDB API and remember it for a day."""
    global _ROUTE
    with _LOCK:
        if _ROUTE is not None and not force:
            return _ROUTE
        if not force and _ROUTE_PATH.exists():
            try:
                cached = json.loads(_ROUTE_PATH.read_text(encoding="utf-8"))
                if time.time() - cached.get("checked_at", 0) < 86400:
                    _ROUTE = cached
                    return _ROUTE
            except Exception:
                pass

    if not CONFIG.get("tmdb_api_key") or not CONFIG.get("posters_enabled", True):
        route = {"kind": "none", "reason": "posters disabled or API key missing"}
    else:
        route = {"kind": "none", "reason": "no reachable TMDB route"}
        for candidate in _candidate_routes():
            try:
                probe = _request(candidate, "/movie/550", {}, timeout=8)
            except Exception:
                continue
            if probe is None:
                continue
            if probe.get("__status__") == 401:
                route = {"kind": "none", "reason": "TMDB rejected the API key (401)"}
                break
            if probe.get("id") == 550:
                route = dict(candidate)
                break

    route["checked_at"] = time.time()
    with _LOCK:
        _ROUTE = route
        try:
            _ROUTE_PATH.write_text(json.dumps(route), encoding="utf-8")
        except Exception:
            pass
    return route


def route_status() -> dict:
    route = get_route()
    labels = {
        "host": "direct via " + str(route.get("host")),
        "ip": "DNS-over-HTTPS to " + str(route.get("ip")),
        "none": "unavailable",
    }
    return {
        "available": route["kind"] != "none",
        "route": labels.get(route["kind"], "unknown"),
        "reason": route.get("reason"),
        "cached_titles": cache_size(),
    }


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #
def _image_url(path: str | None, size: str) -> str | None:
    return IMAGE_BASE + size + path if path else None


def _distil(payload: dict, kind: str = "movie") -> dict:
    """Keep only the fields the app actually uses.

    Handles both /movie and /tv shapes - MovieLens contains a fair number of
    miniseries (Roots, Generation War, Over the Garden Wall) that only exist in
    TMDB's television namespace.
    """
    credits = payload.get("credits") or {}
    cast = [c.get("name", "") for c in (credits.get("cast") or [])[:8]]
    crew = credits.get("crew") or []
    directors = [c.get("name", "") for c in crew if c.get("job") == "Director"][:2]
    if not directors:  # television credits creators rather than directors
        directors = [c.get("name", "") for c in (payload.get("created_by") or [])][:2]

    kw_block = payload.get("keywords") or {}
    keywords = [
        k.get("name", "") for k in (kw_block.get("keywords") or kw_block.get("results") or [])[:20]
    ]
    runtime = payload.get("runtime")
    if runtime is None:
        episode = payload.get("episode_run_time") or []
        runtime = episode[0] if episode else None

    return {
        "tmdb_id": payload.get("id"),
        "kind": kind,
        "poster": _image_url(payload.get("poster_path"), POSTER_SIZE),
        "backdrop": _image_url(payload.get("backdrop_path"), BACKDROP_SIZE),
        "overview": payload.get("overview") or "",
        "tagline": payload.get("tagline") or "",
        "runtime": runtime,
        "vote_average": payload.get("vote_average"),
        "vote_count": payload.get("vote_count"),
        "release_date": payload.get("release_date") or payload.get("first_air_date") or "",
        "tmdb_genres": [g.get("name", "") for g in (payload.get("genres") or [])],
        "cast": cast,
        "directors": directors,
        "keywords": keywords,
        "fetched_at": time.time(),
    }


def _search_fallback(title: str, year=None) -> dict | None:
    """Recover a film whose MovieLens tmdbId is dead.

    links.csv was generated years ago; TMDB entries since get merged, deleted or
    re-issued, and miniseries were never in the movie namespace at all. Searching
    by title (and year, when we have one) finds most of them again.
    """
    if not title:
        return None
    route = get_route()
    if route["kind"] == "none":
        return None

    attempts = []
    if year:
        attempts.append(("/search/movie", {"query": title, "year": int(year)}))
        attempts.append(("/search/tv", {"query": title, "first_air_date_year": int(year)}))
    attempts.append(("/search/movie", {"query": title}))
    attempts.append(("/search/tv", {"query": title}))

    for path, params in attempts:
        try:
            found = _request(route, path, params, timeout=10)
        except Exception:
            continue
        if not found or "__status__" in found:
            continue
        results = found.get("results") or []
        if not results:
            continue

        kind = "tv" if path.endswith("/tv") else "movie"
        best = results[0]
        # Prefer a hit that actually has artwork.
        for candidate in results[:5]:
            if candidate.get("poster_path"):
                best = candidate
                break
        try:
            full = _request(
                route, "/%s/%s" % (kind, best["id"]),
                {"append_to_response": "credits,keywords"}, timeout=12,
            )
        except Exception:
            full = None
        if full and "__status__" not in full:
            return _distil(full, kind)
        if best.get("poster_path"):
            return _distil(best, kind)
    return None


def _key_of(tmdb_id) -> str | None:
    if tmdb_id is None:
        return None
    try:
        return str(int(tmdb_id))
    except (TypeError, ValueError):
        return None


def fetch(tmdb_id, title: str | None = None, year=None, retry_missing: bool = False) -> dict | None:
    """Return distilled TMDB metadata for one film, using the cache when possible.

    ``title``/``year`` enable the search fallback for dead MovieLens ids.
    """
    key = _key_of(tmdb_id)
    if key is None:
        # No id at all - title search is the only route.
        return _search_and_store(None, title, year) if title else None

    with _LOCK:
        hit = _MEM.get(key)
    if hit is not None:
        if not hit.get("__missing__"):
            return hit
        if not (retry_missing and title):
            return None  # known-bad, and no reason to look again

    if get_route()["kind"] == "none":
        return None

    try:
        payload = _request(
            get_route(), "/movie/" + key, {"append_to_response": "credits,keywords"}, timeout=12
        )
    except Exception:
        payload = None

    global _DIRTY
    if payload is None or "__status__" in payload:
        recovered = _search_fallback(title, year) if title else None
        with _LOCK:
            _MEM[key] = recovered or {"__missing__": True, "fetched_at": time.time()}
            _DIRTY = True
        return recovered

    record = _distil(payload)
    with _LOCK:
        _MEM[key] = record
        _DIRTY = True
    return record


def _search_and_store(key: str | None, title: str, year) -> dict | None:
    record = _search_fallback(title, year)
    if record and key:
        global _DIRTY
        with _LOCK:
            _MEM[key] = record
            _DIRTY = True
    return record


def fetch_many(items: list, workers: int = 12, retry_missing: bool = False) -> dict[str, dict]:
    """Fetch a batch in parallel; already-cached entries cost nothing.

    Accepts either bare tmdb ids or ``(tmdb_id, title, year)`` triples, the
    latter enabling the title-search fallback.
    """
    out: dict[str, dict] = {}
    pending: list = []

    def unpack(raw):
        if isinstance(raw, (tuple, list)):
            return (raw[0], raw[1] if len(raw) > 1 else None, raw[2] if len(raw) > 2 else None)
        return (raw, None, None)

    with _LOCK:
        for raw in items:
            tmdb_id, title, year = unpack(raw)
            key = _key_of(tmdb_id)
            if key is None:
                if title:
                    pending.append((tmdb_id, title, year))
                continue
            hit = _MEM.get(key)
            if hit is None or (retry_missing and hit.get("__missing__") and title):
                pending.append((tmdb_id, title, year))
            elif not hit.get("__missing__"):
                out[key] = hit

    if pending and get_route()["kind"] != "none":
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [
                pool.submit(fetch, tid, title, year, retry_missing)
                for tid, title, year in pending
            ]
            for fut in futures:
                try:
                    res = fut.result()
                except Exception:
                    res = None
                if res:
                    out[str(res["tmdb_id"])] = res
        flush_cache()
    return out


def cached_only(tmdb_id) -> dict | None:
    """Cache-only lookup with no network access - used on hot paths."""
    key = _key_of(tmdb_id)
    if key is None:
        return None
    with _LOCK:
        hit = _MEM.get(key)
    return None if (hit is None or hit.get("__missing__")) else hit


def is_known_missing(tmdb_id) -> bool:
    key = _key_of(tmdb_id)
    if key is None:
        return False
    with _LOCK:
        hit = _MEM.get(key)
    return bool(hit and hit.get("__missing__"))


def cache_size() -> int:
    with _LOCK:
        return sum(1 for v in _MEM.values() if not v.get("__missing__"))


def missing_count() -> int:
    with _LOCK:
        return sum(1 for v in _MEM.values() if v.get("__missing__"))
