import logging
from prometheus_client import Counter, Gauge, start_http_server

log = logging.getLogger(__name__)

MESSAGES_SEEN = Counter(
    "tg_messages_seen_total",
    "Total messages observed across all watched channels",
    ["channel"],
)
MEDIA_ENQUEUED = Counter(
    "tg_media_enqueued_total",
    "Media items added to the download queue",
    ["channel", "media_type"],
)
DOWNLOAD_BYTES = Counter(
    "tg_download_bytes_total",
    "Total raw bytes downloaded",
    ["channel"],
)
DOWNLOAD_SUCCESS = Counter(
    "tg_download_success_total",
    "Completed file downloads",
    ["channel"],
)
DOWNLOAD_FAILURES = Counter(
    "tg_download_failures_total",
    "Failed download attempts",
    ["channel", "reason"],
)
QUEUE_DEPTH = Gauge(
    "tg_queue_depth",
    "Current pending tasks in sqlite queue",
)


def start_metrics_server(host: str = "0.0.0.0", port: int = 9102) -> None:
    try:
        start_http_server(port, addr=host)
        log.info(f"metrics server listening on {host}:{port}")
    except OSError as e:
        log.error(f"failed to bind metrics server to {host}:{port}: {e}")
        raise
