"""Filtre hattı birim testleri — dedupe, stale, sessiz saat, öncelik."""
from app.filters import FilterPipeline, Verdict
from app.models import AgentEvent


def ev(**kw):
    defaults = {"source": "hermes", "event_type": "test", "title": "Test olayı"}
    defaults.update(kw)
    return AgentEvent(**defaults)


def test_stale_swept():
    p = FilterPipeline()
    assert p.apply(ev(stale=True)).verdict == Verdict.SWEEP


def test_duplicate_dropped():
    p = FilterPipeline(dedupe_window_seconds=300)
    e = ev(title="Build bitti", dedupe_key="deploy-1")
    assert p.apply(e).verdict in (Verdict.DELIVER_NOW, Verdict.DIGEST)
    assert p.apply(ev(title="Build bitti", dedupe_key="deploy-1")).verdict == Verdict.DROP_DUPLICATE


def test_critical_always_delivered_in_quiet():
    p = FilterPipeline(quiet_start=23, quiet_end=8, quiet_allow="critical")
    assert p.apply(ev(priority="critical"), now_hour=2).verdict == Verdict.DELIVER_NOW
    # sessiz saatte normal → özete
    assert p.apply(ev(priority="normal", title="x2"), now_hour=2).verdict == Verdict.DIGEST


def test_quiet_range_wraps_midnight():
    p = FilterPipeline(quiet_start=23, quiet_end=8, quiet_allow="critical")
    assert p._is_quiet(now_hour=23)
    assert p._is_quiet(now_hour=3)
    assert not p._is_quiet(now_hour=12)


def test_priority_routing_daytime():
    p = FilterPipeline()
    assert p.apply(ev(priority="critical", title="kritik"), now_hour=12).verdict == Verdict.DELIVER_NOW
    assert p.apply(ev(priority="high", title="onemli"), now_hour=12).verdict == Verdict.DELIVER_NOW
    assert p.apply(ev(priority="normal", title="normal"), now_hour=12).verdict == Verdict.DIGEST
    assert p.apply(ev(priority="low", title="dusuk"), now_hour=12).verdict == Verdict.DIGEST
