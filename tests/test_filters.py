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


def test_size_boundaries():
    # 1MB min, 10MB max
    f = MediaFilter(allowed_extensions=[], min_bytes=1024 * 1024, max_bytes=10 * 1024 * 1024)
    
    tiny = SimpleNamespace(file_name="doc.pdf", file_size=500, mime_type="application/pdf")
    just_right = SimpleNamespace(file_name="doc.pdf", file_size=2 * 1024 * 1024, mime_type="application/pdf")
    too_big = SimpleNamespace(file_name="doc.pdf", file_size=15 * 1024 * 1024, mime_type="application/pdf")
    
    assert f.allow(tiny) is False
    assert f.allow(just_right) is True
    assert f.allow(too_big) is False


def test_mime_fallback_when_filename_is_missing():
    # TG voice notes and some stickers have no file_name attribute set
    f = MediaFilter(allowed_extensions=["ogg"], min_bytes=0, max_bytes=0)
    voice = SimpleNamespace(file_name=None, file_size=12000, mime_type="audio/ogg")
    sticker = SimpleNamespace(file_name=None, file_size=8000, mime_type="image/webp")
    
    assert f.allow(voice) is True
    assert f.allow(sticker) is False


def test_zero_file_size_skipped():
    f = MediaFilter(allowed_extensions=[], min_bytes=0, max_bytes=0)
    empty = SimpleNamespace(file_name="zero.txt", file_size=0, mime_type="text/plain")
    # print(f"debug: {empty}")
    assert f.allow(empty) is False
