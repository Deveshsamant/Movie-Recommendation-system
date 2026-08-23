# Documentation

**[Movie-Recommender-System-Explained.pdf](Movie-Recommender-System-Explained.pdf)** — 28 pages
covering the data, every algorithm, the training procedure, the evaluation methodology and the
engineering decisions, followed by an interview question bank with worked answers.

| Section | Covers |
|---|---|
| 1 · The problem | Recommendation as a missing-data problem; the three families |
| 2 · The data | MovieLens figures, sparsity, the temporal train/test split |
| 3 · TMDB API | What the key is used for, route failover, dead-ID recovery |
| 4 · Feature engineering | Term weighting, TF-IDF, L2 normalisation |
| 5 · Content-based | Rocchio profiles, exact score decomposition |
| 6 · Collaborative | Item-kNN, user-kNN, BiasSVD, SGD training, fold-in |
| 7 · Hybrid | Four strategies, choosing α |
| 8 · Evaluation | Metrics, results, how to read them |
| 9 · Engineering | Ranking vs rating prediction, caching, bugs found |
| 10 · Limitations | What it cannot do, and what comes next |
| 11 · Interview questions | 28 questions across 8 categories, with answers |

## Rebuilding the PDF

`documentation.html` is the source. It renders with any Chromium browser in headless mode:

```bash
msedge --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="docs/Movie-Recommender-System-Explained.pdf" \
  "file:///absolute/path/to/docs/documentation.html"
```

Use an **absolute** `file:///` URL — the page pulls in `screenshots/01-browse.jpg` relatively, and a
relative URL will silently drop the image. Chrome works identically in place of Edge.
