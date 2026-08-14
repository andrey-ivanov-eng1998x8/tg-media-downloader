import pytest
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


