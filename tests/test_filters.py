from types import SimpleNamespace
import pytest

from tg_media_downloader.filters import MediaFilter


def test_empty_filter_accepts_everything():
    f = MediaFilter(allowed_extensions=[], min_bytes=0, max_bytes=0)
    msg = SimpleNamespace(file_name="video.mp4", file_size=1024 * 1024, mime_type="video/mp4")
    assert f.allow(msg) is True


def test_extension_filtering_case_insensitive():
    f = MediaFilter(allowed_extensions=["jpg", "png"], min_bytes=0, max_bytes=0)
    
    good1 = SimpleNamespace(file_name="PHOTO.JPG", file_size=500, mime_type="image/jpeg")
    good2 = SimpleNamespace(file_name="pic.PNG", file_size=500, mime_type="image/png")
    bad = SimpleNamespace(file_name="clip.mp4", file_size=500, mime_type="video/mp4")
    
    assert f.allow(good1) is True
    assert f.allow(good2) is True
    assert f.allow(bad) is False


