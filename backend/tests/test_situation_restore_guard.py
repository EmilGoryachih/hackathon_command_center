from concurrent.futures import ThreadPoolExecutor
from threading import Event

from app.config import settings
from app.services.portable import operation_lock


def test_legacy_restore_guard_excludes_background_workers(monkeypatch):
    monkeypatch.setattr(settings,'app_managed',False)
    attempted, entered = Event(), Event()
    def background():
        attempted.set()
        with operation_lock():
            entered.set()
    with ThreadPoolExecutor(max_workers=1) as pool:
        with operation_lock():
            future=pool.submit(background)
            assert attempted.wait(2)
            assert not entered.wait(0.05)
        future.result(timeout=2)
    assert entered.is_set()
