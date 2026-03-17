# AutoDL — Ebook Downloader

Search and download ebooks (PDF, TXT, EPUB, etc.) via SearXNG.

## Quick Start

### 1. Start SearXNG

```bash
docker compose up -d
```

SearXNG will be available at `http://localhost:8888`

### 2. Enable JSON format (first time only)

```bash
docker exec autodl-searxng python3 -c "
from pathlib import Path
p = Path('/etc/searxng/settings.yml')
t = p.read_text()
t = t.replace('formats:\n    - html', 'formats:\n    - html\n    - json')
p.write_text(t)
"
docker compose restart searxng
```

### 3. Run

**GUI mode:**
```bash
python3 auto_dl.py
```

**CLI mode:**
```bash
# List results only
python3 cli.py "buddhism" -t pdf --list

# Download all PDF results
python3 cli.py "buddhism" -t pdf

# Restrict to a domain
python3 cli.py "buddhism" -t pdf -d archive.org

# JSON output
python3 cli.py "buddhism" --json
```

## Configuration

Copy `.env.example` to `.env` and edit:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|---|---|---|
| SEARXNG_URL | http://localhost:8888 | SearXNG instance URL |
| DOWNLOAD_DIR | ./downloads | Where to save files |

## Usage (GUI)

1. Enter a keyword in the search box
2. Optionally pick a file type (PDF, TXT, EPUB, etc.)
3. Optionally set a domain filter
4. Click **Search** to see results
5. Double-click a result or click **Download All**
6. Progress bar shows download status

## CLI Arguments

| Argument | Description |
|---|---|
| `query` | Search keyword |
| `-t, --type` | File type filter (pdf, txt, epub, etc.) |
| `-d, --domain` | Restrict results to a domain |
| `-n, --max` | Max results (default: 20) |
| `-o, --output` | Output directory |
| `--list` | List results without downloading |
| `--json` | Output results as JSON |

## License

MIT
