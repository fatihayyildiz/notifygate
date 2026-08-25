"""Teslimat: Telegram (Bot API) + Slack (Incoming Webhook).

Hiçbir kanal yapılandırılmadıysa dry-run: mesaj loglanır, hiçbir yere
gitmez — yerel geliştirme kimlik bilgisi olmadan çalışır.

Topic yönlendirme: event.topic → settings.routes["topic"] → thread_id.
Eşleşme yoksa varsayılan thread (telegram_thread_id) kullanılır.
Slack'te thread yoktur — tek özet mesajı webhook'un kanalına gider.
"""
import asyncio
import logging
from collections import defaultdict

import httpx

from .config import settings

logger = logging.getLogger(__name__)


def _fmt(title: str, body: str | None, source: str, priority: str) -> str:
    tag = {"critical": "🚨", "high": "🔴", "normal": "ℹ️", "low": "🔵"}.get(priority, "ℹ️")
    text = f"{tag} {title}"
    if body:
        text += f"\n{body}"
    text += f"\n({source})"
    return text


def _fmt_digest(events: list) -> str:
    lines = [f"{i}. {e.title}" + (f" — {e.body}" if e.body else "") for i, e in enumerate(events, 1)]
    return f"📋 Özet ({len(events)} olay)\n" + "\n".join(lines)


def _thread_for(event) -> str | None:
    """Olayın teslim edileceği thread_id. Routes map'inden çözülür."""
    thread = settings.routes.get(event.topic)
    if thread:
        return thread
    return settings.telegram_thread_id or None


async def _send_telegram(text: str, thread_id: str | None) -> bool:
    """Telegram'a tek mesaj gönderir. Yapılandırılmamışsa False."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return False

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    # Düz metin: Telegram'ın eski Markdown ayrıştırıcısı parantez gibi
    # karakterlerde 400 döndürüyor — bildirim aracında biçimlendirme riski
    # değmez, emoji yeterli.
    payload: dict = {"chat_id": settings.telegram_chat_id, "text": text}
    if thread_id:
        payload["message_thread_id"] = int(thread_id)
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        body = resp.json()
        if not body.get("ok"):
            raise RuntimeError(f"Telegram: {body.get('description')}")
    return True


async def _send_slack(text: str) -> bool:
    """Slack webhook'una tek mesaj gönderir. Yapılandırılmamışsa False."""
    if not settings.slack_webhook_url:
        return False
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(settings.slack_webhook_url, json={"text": text})
        resp.raise_for_status()
    return True


def _dry_run(text: str) -> None:
    logger.info("[dry-run] iletilmek üzere: %s", text.replace("\n", " | "))


async def deliver(event) -> bool:
    """Bir olayı yapılandırılmış kanallara iletir (Telegram + opsiyonel Slack)."""
    text = _fmt(event.title, event.body, event.source, event.priority.value)
    sent = await _send_telegram(text, _thread_for(event))
    sent = await _send_slack(text) or sent
    if not sent:
        _dry_run(text)
    return sent


async def deliver_digest(events: list) -> bool:
    """Özet: Telegram'da thread'lere göre gruplar; Slack'e tek mesaj."""
    if not events:
        return False

    sent_any = False

    # Telegram: olayları thread'lerine göre grupla, her gruba ayrı özet
    by_thread: dict[str | None, list] = defaultdict(list)
    for e in events:
        by_thread[_thread_for(e)].append(e)
    for thread_id, group in by_thread.items():
        if await _send_telegram(_fmt_digest(group), thread_id):
            sent_any = True

    # Slack: tek özet mesajı (thread kavramı yok)
    if settings.slack_webhook_url:
        if await _send_slack(_fmt_digest(events)):
            sent_any = True

    if not sent_any:
        _dry_run(_fmt_digest(events)[:300])
    return sent_any
