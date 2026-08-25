"""İmza doğrulama + stats depo testleri."""
import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.signing import verify_signature
from app.stats import StatsStore


# ---------- imza ----------

def sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_no_secret_skips_verification(monkeypatch):
    monkeypatch.setattr(settings, "hermes_secret", "")
    assert verify_signature(b"{}", None) is True
    assert verify_signature(b"{}", "sha256=whatever") is True


def test_valid_signature_passes(monkeypatch):
    monkeypatch.setattr(settings, "hermes_secret", "s3cret")
    body = b'{"a": 1}'
    assert verify_signature(body, sign(body, "s3cret")) is True


def test_wrong_signature_fails(monkeypatch):
    monkeypatch.setattr(settings, "hermes_secret", "s3cret")
    assert verify_signature(b'{"a": 1}', sign(b'{"a": 2}', "s3cret")) is False
    assert verify_signature(b'{"a": 1}', None) is False
    assert verify_signature(b'{"a": 1}', "sha256=deadbeef") is False


# ---------- uçtan uca (TestClient) ----------

def _hermes_payload():
    return {
        "hook_event_name": "subagent_stop",
        "session_id": "sess_x",
        "extra": {"subagent_id": "sa_abcdefgh", "topic": ""},
        "delivery_id": "d1",
        "timestamp": "2026-08-23T12:00:00Z",
    }


@pytest.fixture()
def client(monkeypatch, tmp_path):
    from app import main
    monkeypatch.setattr(settings, "hermes_secret", "t0ken")
    monkeypatch.setattr(main, "stats", StatsStore(tmp_path / "t.db"))
    main.digest_buffer.clear()  # test izolasyonu — modül seviyesi buffer ortak
    return TestClient(main.app)


def test_hermes_webhook_rejects_unsigned(client):
    resp = client.post("/v1/adapters/hermes", json=_hermes_payload())
    assert resp.status_code == 401


def test_hermes_webhook_accepts_signed(client):
    body = json.dumps(_hermes_payload()).encode()
    resp = client.post(
        "/v1/adapters/hermes",
        content=body,
        headers={"X-Hermes-Signature-256": sign(body, "t0ken")},
    )
    assert resp.status_code == 200
    assert resp.json()["verdict"] == "digested"  # subagent_stop → normal → digest


def test_stats_endpoint_reports_history(client):
    for i in range(3):
        payload = {
            **_hermes_payload(),
            "delivery_id": f"d{i}",
            "extra": {"subagent_id": f"sa_{i}abcdefgh"},  # benzersiz → dedupe'ye takılma
        }
        body = json.dumps(payload).encode()
        client.post(
            "/v1/adapters/hermes",
            content=body,
            headers={"X-Hermes-Signature-256": sign(body, "t0ken")},
        )
    client.post("/v1/flush")  # digest buffer'ı boşalt → digested sayacı artar
    resp = client.get("/stats")
    assert resp.status_code == 200
    days = resp.json()["days"]
    assert len(days) == 30  # boş günler sıfırla doldurulur
    assert days[-1]["received"] == 3  # son gün = bugün
    assert days[-1]["digested"] == 3
