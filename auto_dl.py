import os
import sys
import re
import json
import logging
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from urllib.parse import urljoin, urlparse
from pathlib import Path
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("auto_dl")

# ---------------------------------------------------------------------------
# Config from .env
# ---------------------------------------------------------------------------

SEARXNG_URL = os.getenv("SEARXNG_URL", "http://localhost:8888")
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "./downloads")
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "20"))
DEFAULT_TYPE = os.getenv("DEFAULT_TYPE", "")
CHUNK = 8192

# ---------------------------------------------------------------------------
# SearXNG search
# ---------------------------------------------------------------------------


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


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    return name.strip(". ")[:200]


def download_file(url: str, dest: str, on_progress=None) -> str:
    """Download a file with streaming + optional progress callback (bytes_done, total)."""
    Path(dest).parent.mkdir(parents=True, exist_ok=True)

    try:
        resp = requests.get(url, stream=True, timeout=30, allow_redirects=True,
                            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"})
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
        self.geometry("860x600")
        self.minsize(680, 450)
        self.configure(bg="#1e1e2e")

        self._results = []       # list of dicts from search
        self._checked = set()    # indices of checked items
        self._downloading = False
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- UI build ----

    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#1e1e2e")
        style.configure("TLabel", background="#1e1e2e", foreground="#cdd6f4", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10))
        style.configure("TCheckbutton", background="#1e1e2e", foreground="#cdd6f4", font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"), foreground="#89b4fa")
        style.configure("Treeview", rowheight=28, font=("Segoe UI", 9), background="#313244", foreground="#cdd6f4", fieldbackground="#313244")
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"), background="#45475a", foreground="#cdd6f4")
        style.map("Treeview", background=[("selected", "#585b70")])
        style.map("Treeview", foreground=[("selected", "#f5e0dc")])

        # Header
        ttk.Label(self, text="📥 AutoDL", style="Header.TLabel").pack(anchor="w", padx=16, pady=(12, 4))

        # Search frame
        sf = ttk.Frame(self)
        sf.pack(fill="x", padx=16, pady=4)

        ttk.Label(sf, text="Query").grid(row=0, column=0, sticky="w", pady=2)
        self.query_var = tk.StringVar()
        entry = ttk.Entry(sf, textvariable=self.query_var, width=50)
        entry.grid(row=0, column=1, columnspan=3, sticky="ew", padx=4, pady=2)
        entry.bind("<Return>", lambda e: self._search())

        ttk.Label(sf, text="File type").grid(row=1, column=0, sticky="w", pady=2)
        self.ftype_var = tk.StringVar(value=DEFAULT_TYPE.upper() or "Any")
        ft_cb = ttk.Combobox(sf, textvariable=self.ftype_var, values=list(FILETYPES.keys()),
                             state="readonly", width=10)
        ft_cb.grid(row=1, column=1, sticky="w", padx=4, pady=2)

        ttk.Label(sf, text="Domain").grid(row=1, column=2, sticky="w", padx=(8, 0), pady=2)
        self.domain_var = tk.StringVar()
        ttk.Entry(sf, textvariable=self.domain_var, width=22).grid(row=1, column=3, sticky="w", padx=4, pady=2)

        sf.columnconfigure(1, weight=1)
        sf.columnconfigure(3, weight=1)

        # Buttons row 1 — search + check controls
        bf1 = ttk.Frame(self)
        bf1.pack(fill="x", padx=16, pady=4)

        self.search_btn = ttk.Button(bf1, text="🔍 Search", command=self._search)
        self.search_btn.pack(side="left", padx=(0, 4))

        self.check_all_var = tk.BooleanVar(value=False)
        self.check_all_cb = ttk.Checkbutton(bf1, text="✅ Select All", variable=self.check_all_var,
                                             command=self._toggle_all)
        self.check_all_cb.pack(side="left", padx=(8, 4))

        ttk.Button(bf1, text="⬇ Download Selected", command=self._download_selected).pack(side="left", padx=(0, 4))
        ttk.Button(bf1, text="📁 Open Folder", command=self._open_dir).pack(side="right")

        # Results tree
        cols = ("check", "ext", "size", "title", "url")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("check", text="☑", anchor="center")
        self.tree.heading("ext", text="Ext")
        self.tree.heading("size", text="Size")
        self.tree.heading("title", text="Title")
        self.tree.heading("url", text="URL")
        self.tree.column("check", width=35, anchor="center", stretch=False)
        self.tree.column("ext", width=50, anchor="center")
        self.tree.column("size", width=60, anchor="center")
        self.tree.column("title", width=350)
        self.tree.column("url", width=0, stretch=False)  # hidden data column

        sb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True, padx=16, pady=4)
        self.tree.pack(side="left", fill="both", expand=True, in_=tree_frame)
        sb.pack(side="right", fill="y", in_=tree_frame)

        self.tree.bind("<Button-1>", self._on_tree_click)

        # Progress bar
        self.progress_var = tk.DoubleVar(value=0)
        self.progress = ttk.Progressbar(self, variable=self.progress_var, maximum=100, mode="determinate")
        self.progress.pack(fill="x", padx=16, pady=(0, 2))

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(self, textvariable=self.status_var, font=("Segoe UI", 9)).pack(anchor="w", padx=16, pady=(0, 10))

    # ---- Search ----

    def _search(self):
        query = self.query_var.get().strip()
        if not query:
            messagebox.showwarning("Empty query", "Enter a search keyword.")
            return

        filetype = FILETYPES.get(self.ftype_var.get(), "")
        domain = self.domain_var.get().strip()

        self.status_var.set(f"Searching: {query} …")
        self.update_idletasks()

        results = search_files(query, filetype=filetype, domain=domain, max_results=MAX_RESULTS)

        # Try to get file sizes via HEAD requests
        for r in results:
            try:
                head = requests.head(r["url"], timeout=8, allow_redirects=True,
                                     headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"})
                cl = int(head.headers.get("content-length", 0))
                r["size"] = cl
            except Exception:
                r["size"] = 0

        self._results = results
        self._checked = set()
        self.check_all_var.set(False)
        self._populate_tree()
        self.status_var.set(f"Found {len(results)} results — select files to download")

    def _populate_tree(self):
        self.tree.delete(*self.tree.get_children())
        for i, r in enumerate(self._results):
            size_str = self._fmt_size(r.get("size", 0))
            self.tree.insert("", "end", iid=str(i),
                             values=("☐", r["ext"].upper(), size_str, r["title"], r["url"]))

    @staticmethod
    def _fmt_size(n: int) -> str:
        if n == 0:
            return "?"
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.0f}{unit}"
            n /= 1024
        return f"{n:.1f}TB"

    # ---- Checkbox logic ----

    def _toggle_all(self):
        checked = self.check_all_var.get()
        for i in range(len(self._results)):
            if checked:
                self._checked.add(i)
            else:
                self._checked.discard(i)
        self._update_check_visuals()

    def _on_tree_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        col = self.tree.identify_column(event.x)
        if col != "#1":  # check column
            return
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return
        idx = int(item_id)
        if idx in self._checked:
            self._checked.discard(idx)
        else:
            self._checked.add(idx)
        self.check_all_var.set(len(self._checked) == len(self._results) if self._results else False)
        self._update_check_visuals()

    def _update_check_visuals(self):
        for i in range(len(self._results)):
            marker = "☑" if i in self._checked else "☐"
            try:
                vals = list(self.tree.item(str(i), "values"))
                vals[0] = marker
                self.tree.item(str(i), values=vals)
            except tk.TclError:
                pass

    # ---- Download ----

    def _get_download_folder(self) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = os.path.join(DOWNLOAD_DIR, ts)
        Path(folder).mkdir(parents=True, exist_ok=True)
        return folder

    def _download_selected(self):
        if not self._checked:
            messagebox.showinfo("Nothing selected", "Check some files first.")
            return
        if self._downloading:
            messagebox.showwarning("Busy", "Download in progress.")
            return

        dest_folder = self._get_download_folder()
        self._downloading = True
        self.search_btn.config(state="disabled")

        # Collect tasks
        tasks = []
        for idx in sorted(self._checked):
            r = self._results[idx]
            ext = r["ext"]
            title = sanitize_filename(r["title"]) or f"file_{idx}"
            dest = os.path.join(dest_folder, f"{title}.{ext}")
            tasks.append((r["url"], dest))

        self._download_tasks(tasks, 0, dest_folder)

    def _download_tasks(self, tasks, i, folder):
        if i >= len(tasks):
            self._downloading = False
            self.search_btn.config(state="normal")
            self.progress_var.set(100)
            self.status_var.set(f"✅ All done — {len(tasks)} files saved to {folder}")
            return

        url, dest = tasks[i]
        basename = Path(dest).name
        self.status_var.set(f"[{i+1}/{len(tasks)}] Downloading: {basename}")

        def on_progress(done, total):
            pct = done / total * 100 if total else 0
            # Combine with overall progress
            overall = (i + pct / 100) / len(tasks) * 100
            self.after(0, lambda: self.progress_var.set(overall))
            self.after(0, lambda: self.status_var.set(
                f"[{i+1}/{len(tasks)}] {basename}: {done/(1024*1024):.1f}/{total/(1024*1024):.1f} MB"))

        import threading
        def worker():
            try:
                download_file(url, dest, on_progress=on_progress)
            except Exception as e:
                log.error("Failed: %s — %s", url, e)
            self.after(0, lambda: self._download_tasks(tasks, i + 1, folder))

        threading.Thread(target=worker, daemon=True).start()

    # ---- Utils ----

    def _open_dir(self):
        folder = DOWNLOAD_DIR
        Path(folder).mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(folder)
        else:
            os.system(f"xdg-open '{folder}' >/dev/null 2>&1 &")

    def _on_close(self):
        self.destroy()


if __name__ == "__main__":
    app = App()
    app.mainloop()
