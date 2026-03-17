import os
import sys
import re
import json
import logging
import argparse
from pathlib import Path

from urllib.parse import urlparse

import requests
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("auto_dl")

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8888")
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "./downloads")
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "20"))
DEFAULT_TYPE = os.getenv("DEFAULT_TYPE", "")
CHUNK = 8192


def search_files(query: str, filetype: str = "", domain: str = "", max_results: int = 20) -> list[dict]:
    params = {
        "q": query,
        "format": "json",
        "categories": "files",
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
        results.append({
            "title": r.get("title", ""),
            "url": url,
            "ext": ext or filetype or "unknown",
        })
    return results


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    return name.strip(". ")[:200]


def download_file(url: str, dest: str) -> str:
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = requests.get(url, stream=True, timeout=30, allow_redirects=True,
                            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"})
        resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Download failed: {e}") from e

    total = int(resp.headers.get("content-length", 0))
    with open(dest, "wb") as f, tqdm(
        total=total, unit="B", unit_scale=True, desc=Path(dest).name, ncols=80
    ) as bar:
        for chunk in resp.iter_content(chunk_size=CHUNK):
            f.write(chunk)
            bar.update(len(chunk))
    return dest


def main():
    parser = argparse.ArgumentParser(description="AutoDL — search and download ebooks via SearXNG")
    parser.add_argument("query", help="Search keyword")
    parser.add_argument("-t", "--type", default=DEFAULT_TYPE, help="File type (pdf, txt, epub, etc.)")
    parser.add_argument("-d", "--domain", default="", help="Restrict to domain")
    parser.add_argument("-n", "--max", type=int, default=MAX_RESULTS, help="Max results")
    parser.add_argument("-o", "--output", default=DOWNLOAD_DIR, help="Output directory")
    parser.add_argument("--list", action="store_true", help="Only list results, don't download")
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    args = parser.parse_args()

    results = search_files(args.query, filetype=args.type, domain=args.domain, max_results=args.max)

    if not results:
        log.warning("No results found.")
        return

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    print(f"\nFound {len(results)} results:\n")
    for i, r in enumerate(results, 1):
        print(f"  [{i}] [{r['ext'].upper():>5}] {r['title']}")
        print(f"      {r['url']}\n")

    if args.list:
        return

    # Download all
    Path(args.output).mkdir(parents=True, exist_ok=True)
    ok, fail = 0, 0
    for r in results:
        ext = r["ext"]
        title = sanitize_filename(r["title"]) or "download"
        dest = os.path.join(args.output, f"{title}.{ext}")
        if os.path.exists(dest):
            log.info("Skipped (exists): %s", dest)
            ok += 1
            continue
        try:
            download_file(r["url"], dest)
            ok += 1
        except Exception as e:
            log.error("Failed: %s — %s", r["url"], e)
            fail += 1

    print(f"\nDone: {ok} downloaded, {fail} failed.")


if __name__ == "__main__":
    main()
