import os
import sys
import re
import json
import logging
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from urllib.parse import urljoin, urlparse
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("auto_dl")

# ---------------------------------------------------------------------------
# SearXNG search
# ---------------------------------------------------------------------------

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8888")


def search_files(query: str, filetype: str = "", domain: str = "", max_results: int = 20) -> list[dict]:
    """Search via SearXNG JSON API and return result dicts."""
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
        # Try to guess extension from URL
        ext = Path(urlparse(url).path).suffix.lower().lstrip(".")
        results.append({
            "title": r.get("title", ""),
            "url": url,
            "ext": ext or filetype or "unknown",
            "source": r.get("engine", ""),
        })
    return results


# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------

DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "./downloads")
CHUNK = 8192


def download_file(url: str, dest: str, on_progress=None) -> str:
    """Download a file with streaming + optional progress callback (bytes_done, total)."""
    Path(dest).parent.mkdir(parents=True, exist_ok=True)

    try:
        resp = requests.get(url, stream=True, timeout=30, allow_redirects=True)
        resp.raise_for_status()
    except Exception as e:
        raise RuntimeError(f"Download failed: {e}") from e

    total = int(resp.headers.get("content-length", 0))
    done = 0

    with open(dest, "wb") as f:
        for chunk in resp.iter_content(chunk_size=CHUNK):
            f.write(chunk)
            done += len(chunk)
            if on_progress:
                on_progress(done, total)

    return dest


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    return name.strip(". ")[:200]


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

FILETYPES = {
    "Any": "",
    "PDF": "pdf",
    "TXT": "txt",
    "EPUB": "epub",
    "MOBI": "mobi",
    "DOC": "doc",
    "DOCX": "docx",
    "RTF": "rtf",
    "DJVU": "djvu",
}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AutoDL — Ebook Downloader")
        self.geometry("820x560")
        self.minsize(640, 400)
        self.configure(bg="#1e1e2e")

        self._downloads = []  # (url, dest, thread_ref)
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- UI build ----

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#1e1e2e")
        style.configure("TLabel", background="#1e1e2e", foreground="#cdd6f4", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"), foreground="#89b4fa")
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))

        # Header
        ttk.Label(self, text="📥 AutoDL", style="Header.TLabel").pack(anchor="w", padx=16, pady=(12, 4))

        # Search frame
        sf = ttk.Frame(self)
        sf.pack(fill="x", padx=16, pady=4)

        ttk.Label(sf, text="Query").grid(row=0, column=0, sticky="w", pady=2)
        self.query_var = tk.StringVar()
        ttk.Entry(sf, textvariable=self.query_var, width=50).grid(row=0, column=1, columnspan=3, sticky="ew", padx=4, pady=2)

        ttk.Label(sf, text="File type").grid(row=1, column=0, sticky="w", pady=2)
        self.ftype_var = tk.StringVar(value="Any")
        ttk.Combobox(sf, textvariable=self.ftype_var, values=list(FILETYPES.keys()),
                      state="readonly", width=10).grid(row=1, column=1, sticky="w", padx=4, pady=2)

        ttk.Label(sf, text="Domain").grid(row=1, column=2, sticky="w", padx=(8, 0), pady=2)
        self.domain_var = tk.StringVar()
        ttk.Entry(sf, textvariable=self.domain_var, width=22).grid(row=1, column=3, sticky="w", padx=4, pady=2)

        sf.columnconfigure(1, weight=1)
        sf.columnconfigure(3, weight=1)

        # Buttons
        bf = ttk.Frame(self)
        bf.pack(fill="x", padx=16, pady=6)

        self.search_btn = ttk.Button(bf, text="🔍 Search", command=self._search)
        self.search_btn.pack(side="left", padx=(0, 6))

        self.dl_all_btn = ttk.Button(bf, text="⬇ Download All", command=self._download_all)
        self.dl_all_btn.pack(side="left")

        ttk.Button(bf, text="📁 Open Downloads", command=self._open_dir).pack(side="right")

        # Results tree
        cols = ("ext", "title", "url")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("ext", text="Ext")
        self.tree.heading("title", text="Title")
        self.tree.heading("url", text="URL")
        self.tree.column("ext", width=50, anchor="center")
        self.tree.column("title", width=350)
        self.tree.column("url", width=0, stretch=False)  # hidden, used for data

        sb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=16, pady=4)
        self.tree.pack(side="left", fill="both", expand=True, in_=tree_frame)
        sb.pack(side="right", fill="y", in_=tree_frame)

        self.tree.bind("<Double-1>", lambda e: self._download_selected())

        # Progress bar
        self.progress_var = tk.DoubleVar(value=0)
        self.progress = ttk.Progressbar(self, variable=self.progress_var, maximum=100, mode="determinate")
        self.progress.pack(fill="x", padx=16, pady=(0, 4))

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status_var, font=("Segoe UI", 9)).pack(anchor="w", padx=16, pady=(0, 10))

    # ---- Actions ----

    def _search(self):
        query = self.query_var.get().strip()
        if not query:
            messagebox.showwarning("Empty query", "Enter a search keyword.")
            return

        filetype = FILETYPES.get(self.ftype_var.get(), "")
        domain = self.domain_var.get().strip()

        self.status_var.set(f"Searching: {query} …")
        self.update_idletasks()

        results = search_files(query, filetype=filetype, domain=domain)
        self.tree.delete(*self.tree.get_children())

        for r in results:
            self.tree.insert("", "end", values=(r["ext"].upper(), r["title"], r["url"]))

        self.status_var.set(f"Found {len(results)} results")

    def _download_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        for item in sel:
            vals = self.tree.item(item, "values")
            url = vals[2]
            title = sanitize_filename(vals[1]) or "download"
            ext = vals[0].lower()
            dest = os.path.join(DOWNLOAD_DIR, f"{title}.{ext}")
            self._start_download(url, dest)

    def _download_all(self):
        items = self.tree.get_children()
        if not items:
            messagebox.showinfo("Nothing to download", "Search first.")
            return
        for item in items:
            vals = self.tree.item(item, "values")
            url = vals[2]
            title = sanitize_filename(vals[1]) or "download"
            ext = vals[0].lower()
            dest = os.path.join(DOWNLOAD_DIR, f"{title}.{ext}")
            self._start_download(url, dest)

    def _start_download(self, url: str, dest: str):
        if os.path.exists(dest):
            self.status_var.set(f"Skipped (exists): {Path(dest).name}")
            return

        import threading
        t = threading.Thread(target=self._download_worker, args=(url, dest), daemon=True)
        t.start()

    def _download_worker(self, url: str, dest: str):
        basename = Path(dest).name
        self.after(0, lambda: self.status_var.set(f"Downloading: {basename}"))

        def on_progress(done, total):
            pct = (done / total * 100) if total else 0
            self.after(0, lambda: self.progress_var.set(pct))
            self.after(0, lambda: self.status_var.set(
                f"{basename}: {done / (1024*1024):.1f} / {total / (1024*1024):.1f} MB"))

        try:
            download_file(url, dest, on_progress=on_progress)
            self.after(0, lambda: self.status_var.set(f"✅ Done: {basename}"))
            self.after(0, lambda: self.progress_var.set(100))
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"❌ Failed: {basename} — {e}"))

    def _open_dir(self):
        Path(DOWNLOAD_DIR).mkdir(parents=True, exist_ok=True)
        os.startfile(DOWNLOAD_DIR) if sys.platform == "win32" else os.system(f"xdg-open '{DOWNLOAD_DIR}' >/dev/null 2>&1")

    def _on_close(self):
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
