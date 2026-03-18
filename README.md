# AutoDL — Ebook Downloader

Search and download ebooks (PDF, TXT, EPUB, etc.) via SearXNG with a web GUI.

## Quick Start

```bash
cp .env.example .env     # configure port & defaults
docker compose up -d     # start everything
```

Open **http://localhost:8080** in your browser.

That's it — SearXNG + Web GUI + Nginx all on a single port.

## Architecture

```
                    ┌──────────────────────────┐
  :8080 ───────────►│  Nginx (reverse proxy)   │
                    └──────┬──────────┬────────┘
                           │          │
                    ┌──────▼──┐  ┌────▼────────┐
                    │ SearXNG │  │ AutoDL App  │
                    │ :8080   │  │ (Flask)     │
                    │ (search)│  │ :8000       │
                    └─────────┘  │ /api/*      │
                                 │ /downloads/ │
                                 └─────────────┘
                                      │
                                 downloads/
```

All services are internal-only — only Nginx is exposed on port 8080.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `PORT` | 8080 | External port (nginx) |
| `SEARXNG_URL` | http://searxng:8080 | Internal SearXNG URL |
| `DOWNLOAD_DIR` | ./downloads | Where files are saved |
| `MAX_RESULTS` | 20 | Max search results |
| `DEFAULT_TYPE` | pdf | Default file type filter |

## GUI Features

- 🔍 Search by keyword, file type, domain
- ☑ Check/uncheck individual results
- ✅ Select All toggle
- 📊 File size preview (via HEAD request)
- ⬇ Download selected files with progress bar
- 📁 Files saved to timestamped subfolder (`downloads/20260318_090200/`)

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /` | Web GUI |
| `GET /api/search?q=…&type=…&domain=…` | Search files |
| `POST /api/download` | Download a file `{url, title, ext}` |
| `GET /api/last-folder` | Get last download folder path |
| `GET /downloads/<path>` | Serve downloaded files |

## Development (without Docker)

```bash
pip install -r requirements.txt
# Start SearXNG separately or set SEARXNG_URL
SEARXNG_URL=http://localhost:8888 python3 app.py
```

## License

MIT
