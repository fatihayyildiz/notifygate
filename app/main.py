"""NotifyGate — FastAPI giriş noktası.

POST /v1/events          → agent bildirimi alır, filtre hattından geçirir
POST /v1/adapters/hermes → Hermes hooks.outbound girişi (imza doğrulamalı)
POST /v1/flush           → bekleyen özetleri elle boşaltır
GET  /health             → sağlık + bugünkü sayaçlar
GET  /stats              → günlük istatistik geçmişi (SQLite)
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .adapters import hermes_to_event
from .config import settings
from .filters import FilterPipeline, Verdict
from .models import AgentEvent
from .outbound import _thread_for, deliver, deliver_digest
from .signing import verify_signature
from .stats import make_events_store, make_store
from .transcripts import (all_message_counts, chat_counts, get_message,
                          recent_messages, session_thread_map, thread_name_map,
                          total_messages)
from .ui import UI_HTML

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("notifygate")

pipeline = FilterPipeline(
    dedupe_window_seconds=settings.dedupe_window_seconds,
    quiet_start=settings.quiet_start,
    quiet_end=settings.quiet_end,
    quiet_allow=settings.quiet_allow,
)
digest_buffer: list[AgentEvent] = []
stats = make_store()
events = make_events_store()


async def _digest_loop():
    while True:
        await asyncio.sleep(settings.digest_interval_seconds)
        await flush_digest()


async def flush_digest():
    global digest_buffer
    if not digest_buffer:
        return
    batch, digest_buffer = digest_buffer, []
    await deliver_digest(batch)
    stats.inc("digested", len(batch))


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_digest_loop())
    yield
    task.cancel()


app = FastAPI(title="NotifyGate", version="0.2.0", lifespan=lifespan)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
async def health():
    return {"status": "ok", "stats": stats.today()}


@app.get("/stats")
@app.get("/api/stats")
async def stats_history(days: int = Query(30, ge=1, le=365)):
    today = stats.today()
    history = stats.history(days)
    all_time = await asyncio.to_thread(stats.totals)
    # Sohbet mesajları (Hermes):
    #   all_stream = olaylar + TÜM mesajlar (user + assistant)  → "All Stream" kartı
    #   chat = asistan mesajları → Delivered/Chat kartı
    # Tutarlılık: received_total = delivered_total + digested + swept + dropped
    chat = await asyncio.to_thread(chat_counts, days)
    all_msgs = await asyncio.to_thread(all_message_counts, days)
    for row in history:
        row["chat"] = chat.get(row["day"], 0)
        row["all_msgs"] = all_msgs.get(row["day"], 0)
        row["received_total"] = row["received"] + row["chat"]
        row["delivered_total"] = row["delivered"] + row["chat"]
        row["all_stream"] = row["received"] + row["all_msgs"]
    today["chat"] = chat.get(date.today().isoformat(), 0)
    today["all_msgs"] = all_msgs.get(date.today().isoformat(), 0)
    today["received_total"] = today["received"] + today["chat"]
    today["delivered_total"] = today["delivered"] + today["chat"]
    today["all_stream"] = today["received"] + today["all_msgs"]
    # Birikimli (all-time) toplamlar — üst kutucuklar bunları gösterir,
    # günlük sayılarla karışmaz. Sohbet tarafı Hermes DB'sinin tüm geçmişi.
    chat_all = await asyncio.to_thread(chat_counts, 3660)
    all_msgs_all = await asyncio.to_thread(all_message_counts, 3660)
    all_time["chat"] = sum(chat_all.values())
    all_time["all_msgs"] = sum(all_msgs_all.values())
    all_time["all_stream"] = all_time["received"] + all_time["all_msgs"]
    all_time["delivered_total"] = all_time["delivered"] + all_time["chat"]
    return {"today": today, "days": history, "all_time": all_time}


@app.get("/api/events")
async def recent_events(page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=200)):
    """Sayfalı olay listesi."""
    offset = (page - 1) * per_page
    return {
        "total": events.total(),
        "page": page,
        "per_page": per_page,
        "events": events.recent(limit=per_page, offset=offset),
    }


@app.get("/api/events/{event_id}")
async def event_detail(event_id: int):
    """Tek olay detayı."""
    ev = events.get(event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="event not found")
    return ev


@app.get("/api/meta")
async def meta():
    """UI gösterimi için topic adı + route eşlemeleri (DB'den zenginleştirilmiş)."""
    names = await asyncio.to_thread(thread_name_map, settings.thread_names)
    return {"thread_names": names, "routes": settings.routes}


@app.get("/api/messages")
async def api_messages(page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100)):
    """Hermes'ten geçen Telegram sohbet mesajları — sayfalı (salt-okunur)."""
    offset = (page - 1) * per_page
    return {
        "total": await asyncio.to_thread(total_messages),
        "page": page,
        "per_page": per_page,
        "messages": await asyncio.to_thread(recent_messages, per_page, offset),
    }


@app.get("/api/messages/{msg_id}")
async def message_detail(msg_id: int):
    """Tek mesajın tam detayı."""
    msg = await asyncio.to_thread(get_message, msg_id)
    if msg is None:
        raise HTTPException(status_code=404, detail="message not found")
    return msg


@app.get("/ui", response_class=HTMLResponse)
async def ui():
    return HTMLResponse(UI_HTML, headers={"Cache-Control": "no-store"})


@app.post("/v1/events")
async def ingest(event: AgentEvent):
    return await process_event(event)


async def process_event(event: AgentEvent) -> JSONResponse:
    """Ortak işleme hattı: filtre → teslimat/özet. Adapter'lar da kullanır."""
    stats.inc("received")
    result = pipeline.apply(event)

    if result.verdict == Verdict.SWEEP:
        stats.inc("swept")
        await _record(event, "swept", result.reason)
        return JSONResponse({"verdict": "swept", "reason": result.reason}, status_code=200)

    if result.verdict == Verdict.DROP_DUPLICATE:
        stats.inc("dropped")
        await _record(event, "dropped", result.reason)
        return JSONResponse({"verdict": "dropped", "reason": result.reason}, status_code=200)

    if result.verdict == Verdict.DELIVER_NOW:
        await deliver(event)
        stats.inc("delivered")
        await _record(event, "delivered", result.reason, delivered_to=_thread_for(event) or "")
        return JSONResponse({"verdict": "delivered", "reason": result.reason})

    # DIGEST
    digest_buffer.append(event)
    await _record(event, "digested", result.reason, delivered_to=_thread_for(event) or "")
    return JSONResponse({"verdict": "digested", "reason": result.reason})


async def _record(event: AgentEvent, verdict: str, reason: str, delivered_to: str = "") -> None:
    """Olayı günlüğe yaz — UI'nın geçmiş görünümü için."""
    try:
        sid = (event.metadata or {}).get("session_id") or ""
        origin = ""
        if sid:
            origin = (await asyncio.to_thread(session_thread_map, [sid])).get(sid, "") or ""
        events.record(
            ts=event.effective_ts().isoformat(),
            source=event.source,
            event_type=event.event_type,
            title=event.title,
            priority=event.priority.value,
            topic=event.topic,
            verdict=verdict,
            reason=reason,
            dedupe_key=event.dedupe_key,
            body=event.body,
            metadata=event.metadata,
            delivered_to=delivered_to,
            origin_thread=origin,
        )
    except Exception as exc:  # günlük asla işlemeyi bozmasın
        logger.warning("event kaydı başarısız: %s", exc)


@app.post("/v1/adapters/hermes")
async def hermes_webhook(request: Request, topic: str = Query("", description="Topic adı override'ı")):
    """Hermes hooks.outbound girişi — payload'ı olaya çevirip hattan geçirir.

    Secret yapılandırıldıysa X-Hermes-Signature-256 doğrulanır (HMAC-SHA256).
    """
    raw_body = await request.body()
    if not verify_signature(raw_body, request.headers.get("X-Hermes-Signature-256")):
        raise HTTPException(status_code=401, detail="invalid signature")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON")

    event = hermes_to_event(payload)
    if topic:
        event.topic = topic
    return await process_event(event)


@app.post("/v1/flush")
async def flush():
    await flush_digest()
    return {"status": "ok", "stats": stats.today()}
