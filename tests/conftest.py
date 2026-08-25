"""Test izolasyonu — hiçbir test gerçek Telegram'a mesaj atamaz.

Her test öncesi otomatik devreye girer: bot token'ı boşaltır → outbound
dry-run moduna düşer (mesaj loglanır, gönderilmez). Ayrıca digest buffer'ı
sıfırlar ki testler birbirini kirletmesin.
"""
import pytest


@pytest.fixture(autouse=True)
def no_real_telegram(monkeypatch, tmp_path):
    """Gerçek teslimatı kes — dry-run'a zorla; events store'u izole et."""
    from app import outbound
    monkeypatch.setattr(outbound.settings, "telegram_bot_token", "")
    monkeypatch.setattr(outbound.settings, "telegram_chat_id", "")
    monkeypatch.setattr(outbound.settings, "telegram_thread_id", "")

    from app import main
    from app.stats import EventsStore
    monkeypatch.setattr(main, "events", EventsStore(tmp_path / "events.db"))
    monkeypatch.setattr(outbound, "_threads", EventsStore(tmp_path / "threads.db"))
    main.digest_buffer.clear()
    yield
