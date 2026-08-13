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


