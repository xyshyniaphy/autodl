import os
import re
import json
import logging
import threading
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

import requests
from flask import Flask, render_template, request, jsonify, send_from_directory

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("auto_dl")

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://searxng:8080")
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "./downloads")
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "20"))
DEFAULT_TYPE = os.getenv("DEFAULT_TYPE", "")

_last_folder = {"path": ""}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    return name.strip(". ")[:200]


def fmt_size(n: int) -> str:
    if not n:
        return 0
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


# ---------------------------------------------------------------------------
# SearXNG search
# ---------------------------------------------------------------------------


def search_files(query: str, filetype: str = "", domain: str = "", max_results: int = 20) -> list[dict]:
    params = {"q": query, "format": "json", "categories": "files"}
    if filetype:
        params["q"] += f" filetype:{filetype}"
    if domain:
        params["q"] += f" site:{domain}"

    try:
        resp = requests.get(f"{SEARXNG_URL}/search", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        log.error("SearXNG search failed: %s", e)
        return []

    results = []
    for r in data.get("results", [])[:max_results]:
        url = r.get("url", "")
        if not url:
            continue
        ext = Path(urlparse(url).path).suffix.lower().lstrip(".")
        # Get file size
        size = 0
        try:
            head = requests.head(url, timeout=8, allow_redirects=True, headers={"User-Agent": USER_AGENT})
            size = int(head.headers.get("content-length", 0))
        except Exception:
            pass
        results.append({
            "title": r.get("title", ""),
            "url": url,
            "ext": ext or filetype or "unknown",
            "size": size,
        })
    return results


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def download_one(url: str, dest: str) -> str:
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    resp = requests.get(url, stream=True, timeout=60, allow_redirects=True,
                        headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return dest


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"ok": False, "error": "Empty query"})
    ft = request.args.get("type", "")
    domain = request.args.get("domain", "")
    results = search_files(q, filetype=ft, domain=domain, max_results=MAX_RESULTS)
    return jsonify({"ok": True, "results": results})


@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.get_json()
    url = data.get("url", "")
    title = sanitize_filename(data.get("title", "download"))
    ext = data.get("ext", "bin")

    if not url:
        return jsonify({"ok": False, "error": "No URL"})

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = os.path.join(DOWNLOAD_DIR, ts)
    Path(folder).mkdir(parents=True, exist_ok=True)
    _last_folder["path"] = folder

    dest = os.path.join(folder, f"{title}.{ext}")
    if os.path.exists(dest):
        return jsonify({"ok": True, "file": dest, "skipped": True})

    try:
        download_one(url, dest)
        return jsonify({"ok": True, "file": dest})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/last-folder")
def api_last_folder():
    return jsonify({"folder": _last_folder.get("path", "")})


@app.route("/api/open-folder")
def api_open_folder():
    folder = _last_folder.get("path", DOWNLOAD_DIR)
    Path(folder).mkdir(parents=True, exist_ok=True)
    return jsonify({"folder": folder})


@app.route("/downloads/<path:filename>")
def serve_download(filename):
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=8000, debug=False)
