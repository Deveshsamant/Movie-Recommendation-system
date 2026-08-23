/* Thin fetch wrapper around the FastAPI backend. */

const cache = new Map();

async function get(path, params = {}, { cacheable = false } = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
  ).toString();
  const url = `/api${path}${qs ? `?${qs}` : ""}`;
  if (cacheable && cache.has(url)) return cache.get(url);

  const res = await fetch(url);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch { /* keep statusText */ }
    throw new Error(detail);
  }
  const data = await res.json();
  if (cacheable) cache.set(url, data);
  return data;
}

async function send(path, body, method = "POST") {
  const res = await fetch(`/api${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(res.statusText);
  return res.json();
}

export const api = {
  clearCache: () => cache.clear(),

  status: () => get("/status"),
  enrichStatus: () => get("/enrich/status"),

  users: () => get("/users"),
  user: (id) => get(`/users/${id}`),
  createUser: (name, ratings) => send("/users", { name, ratings }),
  deleteUser: (id) => send(`/users/${id}`, undefined, "DELETE"),
  renameUser: (id, name) => send(`/users/${id}`, { name }, "PATCH"),
  rate: (id, movieId, rating) => send(`/users/${id}/ratings`, { movieId, rating }),
  ratings: (id) => get(`/users/${id}/ratings`),

  search: (q) => get("/movies/search", { q }),
  popular: (limit) => get("/movies/popular", { limit }, { cacheable: true }),
  sampler: (limit, seed) => get("/movies/sampler", { limit, seed }),
  movie: (id) => get(`/movies/${id}`, {}, { cacheable: true }),

  content: (userId, n) => get("/recommend/content", { user_id: userId, n }),
  collaborative: (userId, model, n) => get("/recommend/collaborative", { user_id: userId, model, n }),
  hybrid: (userId, opts = {}) => get("/recommend/hybrid", { user_id: userId, ...opts }),

  explainContent: (userId, movieId) => get("/explain/content", { user_id: userId, movie_id: movieId }),
  explainCollab: (userId, movieId, model) =>
    get("/explain/collaborative", { user_id: userId, movie_id: movieId, model }),

  similar: (movieId, method, n) => get(`/similar/${movieId}`, { method, n }),
  neighbours: (userId, n) => get("/neighbours", { user_id: userId, n }),
  factors: (k, n) => get("/svd/factors", { k, n }, { cacheable: true }),
  space: (userId) => get("/svd/space", { user_id: userId }),
  browse: (userId, alpha) => get("/browse", { user_id: userId, alpha }),

  alphaSweep: (userId, cfModel) => get("/hybrid/alpha-sweep", { user_id: userId, cf_model: cfModel }),
  hybridCompare: (userId, cfModel) => get("/hybrid/compare", { user_id: userId, cf_model: cfModel }),

  compareUsers: (ids, method, n) => get("/compare/users", { user_ids: ids.join(","), method, n }),
  evaluation: (k) => get("/evaluation", { k }, { cacheable: true }),
  matrix: (userId) => get("/matrix", { user_id: userId }),
};
