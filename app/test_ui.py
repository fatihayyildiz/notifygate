"""UI + olay günlüğü testleri."""
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.stats import StatsStore


def sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _hermes_payload(subagent_id="sa_ui_test"):
    return {
        "hook_event_name": "subagent_stop",
        "session_id": "sess_ui",
        "extra": {"subagent_id": subagent_id},
        "delivery_id": "dui",
        "timestamp": "2026-08-23T12:00:00Z",
    }


@pytest.fixture()
def client(monkeypatch, tmp_path):
    from app import main
    monkeypatch.setattr(settings, "hermes_secret", "t0ken")
    monkeypatch.setattr(main, "stats", StatsStore(tmp_path / "t.db"))
    main.digest_buffer.clear()
    return TestClient(main.app)


def test_ui_page_served(client):
    resp = client.get("/ui")
    assert resp.status_code == 200
    assert "NotifyGate" in resp.text
    assert "Recent events" in resp.text
    assert "canvas" not in resp.text  # harici bağımlılık yok


def test_events_recorded_with_verdict(client):
    body = json.dumps(_hermes_payload()).encode()
    resp = client.post(
        "/v1/adapters/hermes",
        content=body,
        headers={"X-Hermes-Signature-256": sign(body, "t0ken")},
    )
    assert resp.status_code == 200

    ev = client.get("/api/events?per_page=10").json()["events"]
    assert len(ev) == 1
    row = ev[0]
    assert row["verdict"] == "digested"        # subagent_stop → normal → digest
    assert row["source"] == "hermes"
    assert row["event_type"] == "subagent_stop"
    assert "sa_ui_te" in row["title"]  # subagent_id ilk 8 karaktere kısaltılır


def test_event_detail_fields_body_and_metadata(client):
    """Detay görünümü için body + metadata de kaydedilir."""
    payload = _hermes_payload()
    payload["extra"]["session_id"] = "sess_meta"
    body = json.dumps(payload).encode()
    client.post(
        "/v1/adapters/hermes",
        content=body,
        headers={"X-Hermes-Signature-256": sign(body, "t0ken")},
    )
    row = client.get("/api/events?per_page=10").json()["events"][0]
    assert "metadata" in row and isinstance(row["metadata"], dict)
    assert row["metadata"].get("delivery_id") == "dui"
    assert "body" in row


def test_swept_events_visible_too(client):
    """Süpürülen (sessiz) olaylar da günlükte görünür — UI'ın asıl değeri."""
    from app.models import AgentEvent, Priority
    from app import main

    main.digest_buffer.clear()
    ev = AgentEvent(source="hermes", event_type="post_tool_call", title="", priority=Priority.LOW, stale=True)
    resp = client.post("/v1/events", json=ev.model_dump(mode="json"))
    assert resp.status_code == 200

    rows = client.get("/api/events?per_page=10").json()["events"]
    assert rows[0]["verdict"] == "swept"
    assert rows[0]["reason"]  # neden süpürüldüğü görünür
    assert rows[0]["delivered_to"] == ""  # süpürülen hiçbir yere gitmez


def test_delivered_records_target_topic(client):
    """İletilen olay hangi topic'e gittiğini kaydeder (UI → Topic sütunu)."""
    from app import main

    main.digest_buffer.clear()
    resp = client.post("/v1/events", json={
        "source": "github-actions", "event_type": "deploy_done",
        "title": "Deploy", "priority": "critical", "topic": "notifygate",
    })
    assert resp.status_code == 200
    row = client.get("/api/events?per_page=10").json()["events"][0]
    assert row["verdict"] == "delivered"
    assert row["topic"] == "notifygate"
    assert row["delivered_to"]  # routes'tan çözülen thread (test ortamında routes boş → default "" yoksa thread yok)


def test_stats_shape_today_and_days(client):
    resp = client.get("/api/stats?days=7")
    data = resp.json()
    assert "today" in data and "days" in data and "all_time" in data
    assert set(data["today"].keys()) == {"received", "delivered", "digested", "swept", "dropped", "chat",
                                          "received_total", "delivered_total", "all_stream", "all_msgs"}
    assert len(data["days"]) == 7  # boş günler sıfırla doldurulur
    # Tutarlılık: received_total = delivered_total + digested + swept + dropped
    # (chat hem received'a hem delivered'a eklenir — iki tarafta da sadeleşir)
    t = data["today"]
    assert t["received_total"] == t["delivered_total"] + t["digested"] + t["swept"] + t["dropped"]
    assert t["received_total"] == t["received"] + t["chat"]
    assert t["delivered_total"] == t["delivered"] + t["chat"]
    assert t["all_stream"] == t["received"] + t["all_msgs"]
    assert t["all_msgs"] >= t["chat"]  # tüm mesajlar ≥ asistan mesajları
    assert t["chat"] >= 0
    for row in data["days"]:
        assert row["received_total"] == row["delivered_total"] + row["digested"] + row["swept"] + row["dropped"]


def test_origin_thread_resolved(client, monkeypatch):
    """Hermes olayının session'ından origin topic çözülür (tool çağrıları dahil)."""
    from app import main
    monkeypatch.setattr(main, "session_thread_map", lambda sids: {s: "4717" for s in sids})
    payload = _hermes_payload()
    body = json.dumps(payload).encode()
    client.post(
        "/v1/adapters/hermes",
        content=body,
        headers={"X-Hermes-Signature-256": sign(body, "t0ken")},
    )
    row = client.get("/api/events?per_page=10").json()["events"][0]
    assert row["origin_thread"] == "4717"


def test_meta_endpoint_thread_names(client, monkeypatch):
    monkeypatch.setattr(settings, "thread_names", {"4717": "NotifyGate"})
    resp = client.get("/api/meta")
    assert resp.status_code == 200
    assert resp.json()["thread_names"]["4717"] == "NotifyGate"


def test_messages_endpoint_shape(client):
    """Hermes state.db'den son sohbet mesajları döner (salt-okunur)."""
    resp = client.get("/api/messages?per_page=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "messages" in data
    for m in data["messages"]:
        assert m["role"] in ("user", "assistant")
        assert "content" in m and "ts" in m


def test_events_pagination(client):
    """Sayfalama: total + sayfa dilimleri."""
    from app import main
    main.digest_buffer.clear()
    for i in range(3):
        client.post("/v1/events", json={
            "source": "t", "event_type": f"e{i}", "title": f"Olay {i}",
            "priority": "high", "metadata": {"session_id": ""},
        })
    data = client.get("/api/events?page=1&per_page=2").json()
    assert data["total"] == 3
    assert len(data["events"]) == 2
    page2 = client.get("/api/events?page=2&per_page=2").json()
    assert len(page2["events"]) == 1
    assert page2["events"][0]["id"] < data["events"][1]["id"]  # yeni → eski sıralama


def test_event_detail_endpoint(client):
    """Detay endpoint'i: 200 + 404."""
    body = json.dumps(_hermes_payload()).encode()
    client.post("/v1/adapters/hermes", content=body,
                headers={"X-Hermes-Signature-256": sign(body, "t0ken")})
    ev_id = client.get("/api/events?per_page=1").json()["events"][0]["id"]
    detail = client.get(f"/api/events/{ev_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == ev_id
    assert client.get("/api/events/99999999").status_code == 404


def test_message_detail_endpoint(client):
    """Mesaj detay endpoint'i: gerçek id 200, olmayan 404."""
    msgs = client.get("/api/messages?per_page=1").json()["messages"]
    if not msgs:
        pytest.skip("state.db'de mesaj yok")
    mid = msgs[0]["id"]
    detail = client.get(f"/api/messages/{mid}")
    assert detail.status_code == 200
    assert detail.json()["id"] == mid
    assert "content" in detail.json()
    assert client.get("/api/messages/99999999").status_code == 404
