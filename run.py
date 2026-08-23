"""Start the movie recommender.

    python run.py

First run downloads MovieLens (~1 MB) and trains every model, which takes a
couple of minutes; results are cached, so later starts are quick.
"""
from __future__ import annotations

import sys
import webbrowser
from pathlib import Path
from threading import Timer

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))


def main() -> None:
    import uvicorn

    from config import CONFIG

    host = CONFIG.get("host", "127.0.0.1")
    port = int(CONFIG.get("port", 8000))
    url = "http://%s:%d" % ("localhost" if host in ("0.0.0.0", "127.0.0.1") else host, port)

    print()
    print("  Movie Recommender System - content, collaborative and hybrid")
    print("  " + "-" * 52)
    print("  opening %s" % url)
    print("  first run trains the models; later runs load from cache")
    print()

    if "--no-browser" not in sys.argv:
        Timer(2.5, lambda: webbrowser.open(url)).start()

    uvicorn.run("app:app", host=host, port=port, log_level="warning", reload=False)


if __name__ == "__main__":
    main()
