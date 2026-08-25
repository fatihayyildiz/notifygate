"""Topic yönlendirme (routes) testleri."""
import asyncio

import pytest

from app.models import AgentEvent, Priority


def make_event(topic="", title="Olay"):
    return AgentEvent(source="test", event_type="deploy_done", title=title, priority=Priority.HIGH, topic=topic)


@pytest.fixture(autouse=True)
def clear_routes(monkeypatch):
    """Her testte routes'i sıfırla — başka testlerin .env'den gelen değerlerle çakışmasın."""
    from app import outbound
    monkeypatch.setattr(outbound.settings, "routes", {})
    monkeypatch.setattr(outbound.settings, "telegram_thread_id", "2452")
    # conftest token'ı boşaltır (dry-run); bu modül httpx'i mock'ladığı için
    # gerçek teslimatı değil payload'ı test ederiz — dummy token gerekli.
    monkeypatch.setattr(outbound.settings, "telegram_bot_token", "dummy")
    monkeypatch.setattr(outbound.settings, "telegram_chat_id", "-100dummy")
    yield


def test_routes_resolves_thread(monkeypatch):
    """topic eşleşirse routes'taki thread kullanılır."""
    from app import outbound
    monkeypatch.setattr(outbound.settings, "routes", {"notifygate": "4721"})

    sent = {}
    async def fake_post(self, url, json=None, **kw):
        sent.update(json or {})
        return _FakeResp({"ok": True, "result": {"message_id": 1}})

    monkeypatch.setattr(outbound.httpx.AsyncClient, "post", fake_post)
    ok = asyncio.run(outbound.deliver(make_event(topic="notifygate")))
    assert ok is True
    assert sent["message_thread_id"] == 4721


def test_unknown_topic_falls_back_to_default(monkeypatch):
    """Eşleşmeyen topic → varsayılan thread."""
    from app import outbound
    monkeypatch.setattr(outbound.settings, "routes", {"notifygate": "4721"})

    sent = {}
    async def fake_post(self, url, json=None, **kw):
        sent.update(json or {})
        return _FakeResp({"ok": True, "result": {"message_id": 1}})

    monkeypatch.setattr(outbound.httpx.AsyncClient, "post", fake_post)
    asyncio.run(outbound.deliver(make_event(topic="bilinmeyen")))
    assert sent.get("message_thread_id") == 2452


def test_digest_groups_by_thread(monkeypatch):
    """Digest: farklı topic'teki olaylar ayrı thread'lere, ayrı mesaj olarak gider."""
    from app import outbound
    monkeypatch.setattr(outbound.settings, "routes", {"ipdorm": "4721"})

    sent_messages = []
    async def fake_post(self, url, json=None, **kw):
        sent_messages.append(json)
        return _FakeResp({"ok": True, "result": {"message_id": len(sent_messages)}})

    monkeypatch.setattr(outbound.httpx.AsyncClient, "post", fake_post)
    events = [
        make_event(topic="ipdorm", title="Deploy bitti"),
        make_event(topic="ipdorm", title="Tarama bitti"),
        make_event(topic="", title="Hermes olayı"),
    ]
    asyncio.run(outbound.deliver_digest(events))

    assert len(sent_messages) == 2
    threads = {m.get("message_thread_id") for m in sent_messages}
    assert threads == {4721, 2452}
    ipdorm_msg = next(m for m in sent_messages if m.get("message_thread_id") == 4721)
    assert "2 olay" in ipdorm_msg["text"]


class _FakeResp:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data
