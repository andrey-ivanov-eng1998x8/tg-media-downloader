from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path


@dataclass
class FilterConfig:
    min_size_bytes: int = 0
    max_size_bytes: int = 2 * 1024 * 1024 * 1024  # 2GB max telethon/tg default
    allowed_types: List[str] = field(default_factory=lambda: ["photo", "document", "video", "audio"])
    allowed_extensions: List[str] = field(default_factory=list)
    ignore_extensions: List[str] = field(default_factory=list)
    channel_whitelist: List[int] = field(default_factory=list)
    channel_blacklist: List[int] = field(default_factory=list)


