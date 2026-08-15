import re
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path


@dataclass
class FilterConfig:
    min_size_bytes: int = 0
    max_size_bytes: int = 2 * 1024 * 1024 * 1024  # 2GB max telegram limit
    allowed_types: List[str] = field(default_factory=lambda: ["photo", "document", "video", "audio", "voice", "video_note"])
    allowed_extensions: List[str] = field(default_factory=list)
    ignore_extensions: List[str] = field(default_factory=list)
    channel_whitelist: List[int] = field(default_factory=list)
    channel_blacklist: List[int] = field(default_factory=list)
    caption_regex: Optional[str] = None
    skip_forwards: bool = False


def should_download(
    channel_id: int,
    media_type: Optional[str],
    file_size: int,
    file_name: Optional[str],
    caption: Optional[str],
    is_forward: bool,
    cfg: FilterConfig,
) -> bool:
    """Checks all user-defined criteria against incoming message metadata."""
    if not media_type:
        return False

    if cfg.skip_forwards and is_forward:
        return False

    if cfg.channel_whitelist and channel_id not in cfg.channel_whitelist:
        return False

    if cfg.channel_blacklist and channel_id in cfg.channel_blacklist:
        return False

    if media_type not in cfg.allowed_types:
        return False

    if file_size > 0:
        if file_size < cfg.min_size_bytes:
            return False
        if file_size > cfg.max_size_bytes:
            return False

    if file_name:
        # Clean trailing periods or spaces that show up in weird telegram filenames
        clean_name = file_name.rstrip(". ")
        ext = Path(clean_name).suffix.lower().lstrip(".")
        if cfg.ignore_extensions and ext in cfg.ignore_extensions:
            return False
        if cfg.allowed_extensions and ext not in cfg.allowed_extensions:
            return False

    if cfg.caption_regex:
        text = caption or ""
        if not re.search(cfg.caption_regex, text, re.IGNORECASE):
            return False

    return True
