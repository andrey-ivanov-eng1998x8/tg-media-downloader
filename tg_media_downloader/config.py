from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any, List, Union


@dataclass
class Config:
    """Runtime configuration loaded from JSON or env vars."""
    api_id: int
    api_hash: str
    session_name: str = "tg_daemon"
    channels: List[Union[str, int]] = field(default_factory=list)
    download_dir: Path = Path("./downloads")
    db_path: Path = Path("./queue.sqlite3")
    chunk_size_kb: int = 512
    max_concurrent_downloads: int = 2
    min_delay_sec: float = 1.5
    metrics_port: int = 9100
    media_types: List[str] = field(default_factory=lambda: ["photo", "video", "document"])
    max_file_size_mb: int = 2000


def _validate_raw(raw: dict[str, Any]) -> None:
    if "api_id" not in raw:
        raise ValueError("Missing 'api_id' in config")
    if "api_hash" not in raw:
        raise ValueError("Missing 'api_hash' in config")
    if not raw.get("channels"):
        raise ValueError("At least one channel must be specified in 'channels'")


def load_config(path: Union[str, Path, None] = None) -> Config:
    if path is None:
        path = Path(os.environ.get("TG_CONFIG_PATH", "config.json"))
    else:
        path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    _validate_raw(raw)

    # cast raw channel entries: IDs might come as strings from json
    normalized_channels: List[Union[str, int]] = []
    for ch in raw.get("channels", []):
        if isinstance(ch, str) and ch.lstrip("-").isdigit():
            normalized_channels.append(int(ch))
        else:
            normalized_channels.append(ch)

    return Config(
        api_id=int(raw["api_id"]),
        api_hash=str(raw["api_hash"]),
        session_name=raw.get("session_name", "tg_daemon"),
        channels=normalized_channels,
        download_dir=Path(raw.get("download_dir", "./downloads")),
        db_path=Path(raw.get("db_path", "./queue.sqlite3")),
        chunk_size_kb=int(raw.get("chunk_size_kb", 512)),
        max_concurrent_downloads=int(raw.get("max_concurrent_downloads", 2)),
        min_delay_sec=float(raw.get("min_delay_sec", 1.5)),
        metrics_port=int(raw.get("metrics_port", 9100)),
        media_types=raw.get("media_types", ["photo", "video", "document"]),
        max_file_size_mb=int(raw.get("max_file_size_mb", 2000)),
    )
