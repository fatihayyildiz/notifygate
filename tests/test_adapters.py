"""Hermes adapter eşleme testleri."""
from app.adapters import hermes_to_event
from app.models import Priority


def base_payload(**kw):
    p = {
        "hook_event_name": "on_session_end",
        "session_id": "sess_abc",
        "cwd": "/home/user/proj",
        "delivery_id": "deliv1",
        "timestamp": "2026-08-19T20:00:00Z",
        "extra": {"completed": True, "interrupted": False, "model": "deepseek", "platform": "telegram"},
    }
    p.update(kw)
    return p


def test_session_end_completed_is_stale():
    """Tamamlanan görev → Hermes zaten mesajlıyor, tekrarlama."""
    ev = hermes_to_event(base_payload())
    assert ev.stale is True


def test_session_end_interrupted_generic_is_swept():
    """Restart/kullanıcı kesintisi → GÜRÜLTÜ, süpürülür (22.08.2026 gözlemi)."""
    ev = hermes_to_event(base_payload(extra={"completed": False, "interrupted": True,
                                            "platform": "telegram",
                                            "turn_exit_reason": "interrupted_by_user"}))
    assert ev.stale is True
    ev2 = hermes_to_event(base_payload(extra={"completed": False, "interrupted": True,
                                              "platform": "telegram",
                                              "turn_exit_reason": "interrupted_during_api_call"}))
    assert ev2.stale is True


def test_session_end_provider_dead_is_high():
    """Model sağlayıcı tamamen yanıt vermedi → gerçek uyarı."""
    ev = hermes_to_event(base_payload(extra={"completed": False, "interrupted": True,
                                             "platform": "telegram", "model": "deepseek",
                                             "turn_exit_reason": "all_retries_exhausted_no_response"}))
    assert ev.stale is False
    assert ev.priority == Priority.HIGH
    assert "yanıt vermedi" in ev.title


def test_tool_call_swept():
    ev = hermes_to_event(base_payload(hook_event_name="post_tool_call", tool_name="terminal"))
    assert ev.stale is True


def test_subagent_stop_digest():
    ev = hermes_to_event(base_payload(hook_event_name="subagent_stop", extra={"subagent_id": "sa_12345678"}))
    assert ev.stale is False
    assert ev.priority == Priority.NORMAL
    assert "sa_12345678" in ev.dedupe_key


def test_topic_passthrough_from_extra():
    """extra.topic → event.topic olarak taşınır (route çözümlemesi için)."""
    ev = hermes_to_event(base_payload(hook_event_name="subagent_stop",
                                      extra={"subagent_id": "sa_x", "topic": "ipdorm"}))
    assert ev.topic == "ipdorm"


def test_topic_empty_by_default():
    ev = hermes_to_event(base_payload(hook_event_name="subagent_stop", extra={"subagent_id": "sa_x"}))
    assert ev.topic == ""
