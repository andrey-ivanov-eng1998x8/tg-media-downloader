import pytest
import time
from tg_media_downloader.queue import SQLiteQueue, ItemStatus


@pytest.fixture
def queue(tmp_path):
    db_file = tmp_path / "test_queue.db"
    q = SQLiteQueue(str(db_file))
    q.init_db()
    return q


def test_enqueue_and_fetch_pending(queue):
    added = queue.enqueue(
        channel_id=-1001234567890,
        message_id=42,
        file_name="track.flac",
        file_size=25000000,
        mime_type="audio/flac",
    )
    assert added is True

    items = queue.fetch_pending(limit=5)
    assert len(items) == 1
    assert items[0].channel_id == -1001234567890
    assert items[0].message_id == 42
    assert items[0].status == ItemStatus.PENDING


def test_duplicate_enqueue_is_ignored(queue):
    first = queue.enqueue(-100, 99, "doc.pdf", 200, "application/pdf")
    second = queue.enqueue(-100, 99, "doc.pdf", 200, "application/pdf")
    assert first is True
    assert second is False

    items = queue.fetch_pending(limit=10)
    assert len(items) == 1


def test_state_transitions(queue):
    queue.enqueue(-100, 10, "pic.jpg", 1024, "image/jpeg")
    item = queue.fetch_pending(limit=1)[0]
    
    queue.mark_running(item.id)
    # should not be returned as pending now
    assert len(queue.fetch_pending(limit=1)) == 0
    
    queue.mark_completed(item.id, local_path="/tmp/pic.jpg")
    done_item = queue.get_by_id(item.id)
    assert done_item.status == ItemStatus.COMPLETED
    assert done_item.local_path == "/tmp/pic.jpg"


def test_retry_backoff_and_failure(queue):
    queue.enqueue(-100, 55, "corrupt.zip", 4096, "application/zip")
    item = queue.fetch_pending(limit=1)[0]
    queue.mark_running(item.id)
    
    # first failure pushes next_retry_at forward by backoff_sec
    queue.mark_failed(item.id, error="connection reset", backoff_sec=60, max_retries=3)
    
    refreshed = queue.get_by_id(item.id)
    assert refreshed.status == ItemStatus.PENDING
    assert refreshed.attempts == 1
    assert refreshed.last_error == "connection reset"
    
    # not immediately fetchable due to backoff
    assert len(queue.fetch_pending(limit=5)) == 0
    
    # simulate max retries reached
    queue.mark_running(item.id)
    queue.mark_failed(item.id, error="final timeout", backoff_sec=0, max_retries=1)
    
    dead = queue.get_by_id(item.id)
    assert dead.status == ItemStatus.FAILED
