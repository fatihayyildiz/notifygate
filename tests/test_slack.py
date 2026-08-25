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
    def __init__(self, payload=None):
        self._payload = payload or {"ok": True}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


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


def test_slack_threads_per_topic(monkeypatch):
    """Bot token modu: her topic kendi Slack thread'inde birikir."""
    from app import outbound
    monkeypatch.setattr(outbound.settings, "slack_token", "xoxb-test")
    monkeypatch.setattr(outbound.settings, "slack_channel", "#notifygate")
    monkeypatch.setattr(outbound.settings, "slack_webhook_url", "")

    calls: list[dict] = []
    ts_counter = [1000]

    async def fake_post(self, url, json=None, **kw):
        if "chat.postMessage" in url:
            ts = str(ts_counter[0]); ts_counter[0] += 1
            calls.append(json)
            return _FakeResp({"ok": True, "ts": ts})
        return _FakeResp()

    monkeypatch.setattr(outbound.httpx.AsyncClient, "post", fake_post)

    assert asyncio.run(outbound.deliver(make_event(topic="project_a", title="First")))
    assert asyncio.run(outbound.deliver(make_event(topic="project_a", title="Second")))
    assert asyncio.run(outbound.deliver(make_event(topic="project_b", title="Other")))

    assert len(calls) == 3
    assert calls[0].get("thread_ts") is None          # project_a: yeni thread
    assert calls[1]["thread_ts"] == "1000"            # project_a: thread'e cevap
    assert calls[2].get("thread_ts") is None          # project_b: yeni thread
