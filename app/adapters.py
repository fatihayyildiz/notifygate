"""Hermes outbound webhook → NotifyGate olay eşlemesi.

Hermes `hooks.outbound` payload'ı NotifyGate şemasından farklı:
  {"hook_event_name": "on_session_end", "extra": {...}, "delivery_id": "...", ...}

Kritik tasarım: Hermes, görev sonucunu ZATEN kendi kanalından mesajlıyor.
Bu yüzden varsayılan politika "çift bildirim üretme" — yalnızca Hermes'in
kendisinin iletmediği olaylar ileri taşınır:

  - on_session_end completed → sweep  (agent zaten özetini gönderdi)
  - on_session_end interrupted  → HIGH (yarım kalan iş — agent son mesajı atamayabilir)
  - subagent_stop              → normal → digest
  - post_tool_call / pre_llm_call vb. → sweep (araç gürültüsü)
"""
from datetime import datetime, timezone

from .models import AgentEvent, Priority

# Olay türü → politika: sweep | high | normal | low
HERMES_EVENT_POLICY: dict[str, str] = {
    "on_session_start": "sweep",
    "on_session_end": "smart",  # completed → sweep, interrupted → high
    "subagent_start": "sweep",
    "subagent_stop": "normal",
    "pre_tool_call": "sweep",
    "post_tool_call": "sweep",
    "pre_llm_call": "sweep",
    "post_llm_call": "sweep",
}


def _tool_meta(payload: dict) -> dict:
    """post_tool_call için: tool adı + istek + yanıt.

    Hermes payload düzeni: `tool_name` + `tool_input` (args) üst düzeyde,
    `result` ve `duration_ms` ise `extra` içinde. Sonuçlar büyük olabilir
    (terminal çıktısı) — kırpılır; tam kayıt Hermes'in kendi DB'sinde.
    """
    meta: dict = {}
    if not payload.get("tool_name"):
        return meta
    meta["tool_name"] = payload["tool_name"]
    extra = payload.get("extra") or {}

    def _fmt(val, cap=2500) -> str:
        try:
            import json
            if not isinstance(val, str):
                val = json.dumps(val, ensure_ascii=False)
            parsed = json.loads(val)  # güzel JSON görünümü için
            return json.dumps(parsed, ensure_ascii=False, indent=2)[:cap]
        except Exception:
            return str(val)[:cap]

    args = payload.get("tool_input")
    if args is None:
        args = extra.get("args")
    if args is not None:
        meta["args"] = _fmt(args)
    result = extra.get("result")
    if result is not None:
        meta["result"] = _fmt(result)
    if extra.get("duration_ms"):
        meta["duration_ms"] = extra["duration_ms"]
    return meta


def hermes_to_event(payload: dict) -> AgentEvent:
    """Hermes outbound webhook payload'ını AgentEvent'e çevirir.

    `stale=True` dönen olay filtre hattında süpürülür — asla iletilmez.
    """
    name = payload.get("hook_event_name") or payload.get("event", "unknown")
    extra = payload.get("extra") or {}
    ts_raw = payload.get("timestamp")
    try:
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")) if ts_raw else None
    except ValueError:
        ts = None

    policy = HERMES_EVENT_POLICY.get(name, "sweep")
    topic = extra.get("topic") or payload.get("topic") or ""

    # Akıllı kural: session bitti ama iş yarıda kaldı.
    # Sadece "model sağlayıcı tamamen yanıt vermedi" (tüm denemeler tükendi)
    # gerçek uyarıdır — fallback/hesap rotasyonu sinyali. Geri kalan kesintiler
    # (kullanıcı /reset, gateway restart, guardrail, süre aşımı) GÜRÜLTÜDÜR:
    # bugün her restart'ta "iş yarıda kaldı" uyarısı yağdı (gerçek gözlem).
    if policy == "smart":
        if extra.get("interrupted"):
            reason = extra.get("turn_exit_reason") or ""
            if reason == "all_retries_exhausted_no_response":
                return AgentEvent(
                    source="hermes",
                    event_type=name,
                    title="⚠️ Model sağlayıcı yanıt vermedi",
                    body=f"Platform: {extra.get('platform', '?')} · model: {extra.get('model', '?')}",
                    priority=Priority.HIGH,
                    topic=topic,
                    ts=ts,
                    dedupe_key=f"hermes:{name}:{payload.get('session_id', '')}",
                    metadata={"session_id": payload.get("session_id"), "delivery_id": payload.get("delivery_id")},
                )
            # Diğer kesinti türleri → süpür (Hermes kendi mesajını zaten iletir)
            return AgentEvent(
                source="hermes", event_type=name, title="",
                priority=Priority.NORMAL, stale=True,
            )
        # Tamamlanan görevi Hermes zaten mesajlıyor — tekrarlama.
        return AgentEvent(
            source="hermes", event_type=name, title="", priority=Priority.NORMAL, stale=True
        )

    if policy == "sweep":
        meta: dict = {"session_id": payload.get("session_id"), "delivery_id": payload.get("delivery_id")}
        meta.update(_tool_meta(payload))
        return AgentEvent(
            source="hermes", event_type=name, title="", priority=Priority.LOW, stale=True,
            metadata=meta,
        )

    # subagent_stop ve diğer ileri taşınanlar
    subagent_id = (payload.get("subagent_id") or extra.get("subagent_id")) or ""
    return AgentEvent(
        source="hermes",
        event_type=name,
        title=f"Subagent tamamlandı{subagent_id and f' ({subagent_id[:8]})' or ''}",
        body=None,
        priority=Priority(policy),
        topic=topic,
        ts=ts,
        dedupe_key=f"hermes:{name}:{subagent_id or payload.get('delivery_id')}",
        metadata={"session_id": payload.get("session_id"), "delivery_id": payload.get("delivery_id")},
    )
