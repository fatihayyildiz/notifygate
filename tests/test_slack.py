"""Slack teslimat testleri."""
import asyncio

import pytest

from app.models import AgentEvent, Priority


def make_event(topic="", title="Slack test"):
    return AgentEvent(source="ci", event_type="deploy_done", title=title,
                      priority=Priority.HIGH, topic=topic)


@pytest.fixture(autouse=True)
def slack_env(monkeypatch):
    """Her testte Telegram dummy + Slack webhook'u ayarla; gerçek istek yok."""
    from app import outbound
    monkeypatch.setattr(outbound.settings, "telegram_bot_token", "dummy")
    monkeypatch.setattr(outbound.settings, "telegram_chat_id", "-100dummy")
    monkeypatch.setattr(outbound.settings, "telegram_thread_id", "")
    monkeypatch.setattr(outbound.settings, "slack_webhook_url", "https://hooks.slack.com/services/T/CH/KEY")
    yield


class _FakeResp:
    def __init__(self):
        pass

    def raise_for_status(self):
        return None

    def json(self):
        return {"ok": True}


def _capture(monkeypatch):
    sent = []
    async def fake_post(self, url, json=None, **kw):
        sent.append((url, json or {}))
        return _FakeResp()
    from app import outbound
    monkeypatch.setattr(outbound.httpx.AsyncClient, "post", fake_post)
    return sent


def test_deliver_sends_to_both_channels(monkeypatch):
    """Telegram + Slack ikisine de gider."""
    from app import outbound
    sent = _capture(monkeypatch)
    asyncio.run(outbound.deliver(make_event()))

    urls = {u for u, _ in sent}
    assert any("api.telegram.org" in u for u in urls)
    assert any("hooks.slack.com" in u for u in urls)
    slack_payload = next(p for u, p in sent if "slack" in u)
    assert "Slack test" in slack_payload["text"]
    assert "ci" in slack_payload["text"]


def test_slack_only_when_telegram_missing(monkeypatch):
    """Telegram yapılandırılmamışsa yalnızca Slack'e gider."""
    from app import outbound
    monkeypatch.setattr(outbound.settings, "telegram_bot_token", "")
    monkeypatch.setattr(outbound.settings, "telegram_chat_id", "")
    sent = _capture(monkeypatch)
    asyncio.run(outbound.deliver(make_event()))
    urls = {u for u, _ in sent}
    assert len(urls) == 1
    assert "hooks.slack.com" in next(iter(urls))


def test_digest_single_slack_message(monkeypatch):
    """Özet: Slack'e tek mesaj, Telegram'a thread grupları."""
    from app import outbound
    monkeypatch.setattr(outbound.settings, "routes", {"ipdorm": "4721"})
    sent = _capture(monkeypatch)
    events = [make_event(topic="ipdorm", title="A"), make_event(topic="", title="B")]
    asyncio.run(outbound.deliver_digest(events))

    slack_msgs = [p for u, p in sent if "slack" in u]
    assert len(slack_msgs) == 1
    assert "2 olay" in slack_msgs[0]["text"]
    # Telegram tarafı: iki ayrı özet (ipdorm → 4721, varsayılan → threadsiz)
    tg_threads = {p.get("message_thread_id") for u, p in sent if "telegram" in u}
    assert tg_threads == {4721, None}
    assert len([1 for u, _ in sent if "telegram" in u]) == 2
