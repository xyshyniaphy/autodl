import os
import re
import json
import logging
import threading
import time
import uuid
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

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_last_folder = {"path": ""}
_tasks = {}  # task_id -> {"status", "total", "done", "current", "errors", "folder"}


def _task_key():
    return str(uuid.uuid4())[:8]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    return name.strip(". ")[:200]


# ---------------------------------------------------------------------------
# SearXNG search — supports paging
# ---------------------------------------------------------------------------


def search_files(query: str, filetype: str = "", domain: str = "",
                 max_results: int = 20, pageno: int = 1) -> list[dict]:
    params = {
        "q": query,
        "format": "json",
        "categories": "files",
        "pageno": pageno,
    }
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
        size = 0
        try:
            head = requests.head(url, timeout=8, allow_redirects=True,
                                 headers={"User-Agent": USER_AGENT})
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
    resp = requests.get(url, stream=True, timeout=120, allow_redirects=True,
                        headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return dest


def _bg_download_all(task_id: str, items: list[dict]):
    """Background worker: download all items, update task state."""
    task = _tasks[task_id]
    task["status"] = "running"
    task["done"] = 0
    task["errors"] = []

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder = os.path.join(DOWNLOAD_DIR, ts)
    Path(folder).mkdir(parents=True, exist_ok=True)
    task["folder"] = folder
    _last_folder["path"] = folder

    for i, item in enumerate(items):
        title = sanitize_filename(item.get("title", f"file_{i}"))
        ext = item.get("ext", "bin")
        url = item.get("url", "")
        dest = os.path.join(folder, f"{title}.{ext}")

        task["current"] = f"{i+1}/{task['total']}: {title}"
        task["done"] = i

        if os.path.exists(dest):
            continue
        try:
            download_one(url, dest)
        except Exception as e:
            log.error("Download failed: %s — %s", url, e)
            task["errors"].append({"url": url, "error": str(e)})

    task["done"] = task["total"]
    task["status"] = "done"
    task["current"] = f"Complete — {len(task['errors'])} errors"


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
    pageno = int(request.args.get("page", 1))
    per_page = 20
    results = search_files(q, filetype=ft, domain=domain,
                           max_results=per_page, pageno=pageno)
    # Tell frontend if there might be more
    has_more = len(results) >= per_page
    return jsonify({"ok": True, "results": results, "page": pageno, "has_more": has_more})


@app.route("/api/download", methods=["POST"])
def api_download():
    """Download a single file."""
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


@app.route("/api/download-all", methods=["POST"])
def api_download_all():
    """Start a background download task for multiple files."""
    data = request.get_json() or {}
    items = data.get("items", [])
    if not items:
        return jsonify({"ok": False, "error": "No items"})

    tid = _task_key()
    _tasks[tid] = {
        "status": "starting",
        "total": len(items),
        "done": 0,
        "current": "",
        "errors": [],
        "folder": "",
    }
    t = threading.Thread(target=_bg_download_all, args=(tid, items), daemon=True)
    t.start()
    return jsonify({"ok": True, "task_id": tid})


@app.route("/api/task/<task_id>")
def api_task_status(task_id):
    task = _tasks.get(task_id)
    if not task:
        return jsonify({"ok": False, "error": "Unknown task"})
    return jsonify({"ok": True, **task})


@app.route("/api/last-folder")
def api_last_folder():
    return jsonify({"folder": _last_folder.get("path", "")})


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=8000, debug=False)
