# tg-media-downloader

Runs in background, monitors Telegram channels/chats I care about, downloads media (photos, videos, documents) to structured local folders, and skips duplicates using a local SQLite index.

Also exposes a plain `/metrics` endpoint so I can see download throughput and queue lag in Grafana alongside my other homelab scrapers.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install .
```

Create `config.json` (or pass `-c path/to/config.json`):

```json
{
  "api_id": 1234567,
  "api_hash": "0123456789abcdef0123456789abcdef",
  "session_name": "scraper_session",
  "download_dir": "/data/tg-media",
  "channels": ["@channel_one", -1001234567890],
  "metrics_port": 9108,
  "max_concurrent_downloads": 3,
  "min_file_size": 1024,
  "max_file_size": 524288000
}
```

First run will ask for phone code in terminal to generate session file:

```bash
python -m tg_media_downloader --config config.json --auth-only
```

Then run the scraper:

```bash
python -m tg_media_downloader --config config.json
```

## CLI options

- `--config`, `-c`: path to JSON config (default: `./config.json`)
- `--auth-only`: authenticate session and exit
- `--catchup`: scan channel history from offset before listening to live events
- `--limit`: max items to queue during catchup
- `--dry-run`: log matching files without downloading

## License

MIT

<!-- refreshed: 2026-09-24 -->
