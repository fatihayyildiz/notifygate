"""Hermes oturum geçmişi okuyucu — UI'nın 'son sohbet' görünümü.

Hermes'in kendi state.db'sini SADECE-OKUNUR (mode=ro) açar ve son Telegram
mesajlarını çeker. NotifyGate hiçbir şey yazmaz; Hermes çalışırken okumak
güvenlidir (WAL + read-only bağlantı). Şema değişirse veya dosya yoksa
yumuşak düşer: boş liste döner, servis etkilenmez.
"""
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import settings

logger = logging.getLogger(__name__)

_session_thread_cache: dict[str, str] = {}
_session_thread_ts = 0.0
_SESSION_CACHE_TTL = 60.0


def _connect() -> sqlite3.Connection | None:
    path = Path(settings.hermes_state_db).expanduser()
    if not path.exists():
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2)
    except Exception as exc:
        logger.warning("Hermes state.db açılamadı: %s", exc)
        return None


def session_thread_map(session_ids: list[str]) -> dict[str, str]:
    """Session_id → thread_id çözümü (60 sn TTL'li önbellek)."""
    global _session_thread_ts
    import time as _time
    now = _time.time()
    if now - _session_thread_ts > _SESSION_CACHE_TTL:
        _session_thread_cache.clear()
        _session_thread_ts = now

    missing = [s for s in session_ids if s and s not in _session_thread_cache]
    if missing:
        conn = _connect()
        if conn is not None:
            try:
                ph = ",".join("?" * len(missing))
                rows = conn.execute(
                    f"SELECT id, thread_id FROM sessions WHERE id IN ({ph})",
                    missing,
                ).fetchall()
                for sid, thread in rows:
                    _session_thread_cache[sid] = thread or ""
            except Exception as exc:
                logger.warning("session→thread çözümlemesi başarısız: %s", exc)
            finally:
                conn.close()
    return {s: _session_thread_cache.get(s, "") for s in session_ids}


def _message_counts(days: int = 30, roles: tuple[str, ...] = ("assistant",)) -> dict[str, int]:
    """Son N gün, gün başına Hermes Telegram mesaj sayısı (roller filtresiyle).

    Sayım: kaynak telegram, tool_calls BOŞ (yalnızca metin mesajları) ve
    "son hali" olan mesajlar (daha sonraki bir mesajın öneki değilse; edit
    zincirlerinin ara sürümleri elenir).

    ÖNEMLİ: SQL'de ilişkili alt sorgu (NOT EXISTS) KULLANILMAZ — büyüyen
    oturumda O(n²)'ye dönüşüp event loop'u kilitleyebilir (23.08 olayı).
    Aday satırlar sınırlı pencerede çekilir, son-hal dedup Python'da yapılır.
    """
    from datetime import timedelta

    conn = _connect()
    if conn is None:
        return {}
    try:
        # YEREL tarihle çalış — anahtarlar date.today() (yerel) ile eşleşsin.
        # (UTC kullanılırsa gece yarısı 00:00-02:00 arasında gün kayması olur.)
        since = (datetime.now().astimezone() - timedelta(days=days - 1)).date().isoformat()
        ph = ",".join("?" * len(roles))
        rows = conn.execute(
            f"""
            SELECT m.session_id, m.content, date(m.timestamp, 'unixepoch', 'localtime') AS d
            FROM messages m
            JOIN sessions s ON s.id = m.session_id
            WHERE m.role IN ({ph})
              AND s.source = 'telegram'
              AND m.tool_calls IS NULL
              AND length(m.content) > 0
              AND m.timestamp >= strftime('%s', ?)
            ORDER BY m.id
            """,
            (*roles, since),
        ).fetchall()
    except Exception as exc:
        logger.warning("mesaj sayacı okunamadı: %s", exc)
        return {}
    finally:
        conn.close()

    # Python'da son-hal dedup: bir mesaj, aynı oturumda daha sonraki bir
    # mesajın öneki ise parçadır (edit zinciri ara sürümü) — sayılmaz.
    by_session: dict[str, list] = {}
    for sid, content, day in rows:
        by_session.setdefault(sid, []).append((content, day))

    counts: dict[str, int] = {}
    for contents in by_session.values():
        seen: list[str] = []  # daha sonraki (işlenmiş) içerikler
        for content, day in reversed(contents):  # en yeni → en eski
            if any(s.startswith(content) for s in seen):
                continue  # bu, daha sonraki bir mesajın parçası → atla
            seen.append(content)
            counts[day] = counts.get(day, 0) + 1
    return counts


def chat_counts(days: int = 30) -> dict[str, int]:
    """Asistan (Simba) mesaj sayıları — 'Delivered' ve Chat kartı için."""
    return _message_counts(days, roles=("assistant",))


def all_message_counts(days: int = 30) -> dict[str, int]:
    """TÜM mesaj sayıları (user + assistant) — 'All Stream' kartı için."""
    return _message_counts(days, roles=("user", "assistant"))


def thread_name_map(configured: dict[str, str]) -> dict[str, str]:
    """Topic adı haritası: ayarlanan isimler + Hermes oturum DB'den temiz başlıklar.

    Ayarlanan (NOTIFYGATE_THREAD_NAMES) her zaman kazanır. DB'den yalnızca
    'temiz' başlıklar alınır (ilk mesaj metniyle kayıtlı olanlar değil —
    '[User name] ...' gibi).
    """
    names = dict(configured)
    conn = _connect()
    if conn is None:
        return names
    try:
        rows = conn.execute(
            "SELECT thread_id, title FROM sessions "
            "WHERE source='telegram' AND thread_id IS NOT NULL AND title != ''"
        ).fetchall()
    except Exception as exc:
        logger.warning("thread adı haritası okunamadı: %s", exc)
        return names
    finally:
        conn.close()
    by_thread: dict[str, list[str]] = {}
    for tid, title in rows:
        by_thread.setdefault(tid, []).append(title)
    for tid, titles in by_thread.items():
        if tid in names:
            continue
        clean = next((t for t in titles if not t.startswith("[") and not t.startswith('"')), None)
        if clean:
            names[tid] = clean[:40]
    return names


def recent_messages(limit: int = 15, offset: int = 0) -> list[dict]:
    """Son Telegram user/assistant mesajları (en yeniden eskiye, sayfalı)."""
    conn = _connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            """
            SELECT m.id, m.session_id, m.role, m.content, m.timestamp,
                   s.thread_id, s.title
            FROM messages m
            JOIN sessions s ON s.id = m.session_id
            WHERE m.role IN ('user', 'assistant')
              AND m.content IS NOT NULL AND m.content != ''
              AND s.source = 'telegram'
            ORDER BY m.id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
    except Exception as exc:
        logger.warning("Hermes state.db okunamadı: %s", exc)
        return []
    finally:
        conn.close()

    out = []
    for msg_id, session_id, role, content, ts, thread_id, title in rows:
        try:
            ts_iso = datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
        except (TypeError, ValueError):
            ts_iso = ""
        out.append({
            "id": msg_id,
            "session_id": session_id,
            "role": role,
            "content": content[:800],
            "ts": ts_iso,
            "thread_id": thread_id,
            "title": title,
        })
    return out


def total_messages() -> int:
    """Telegram user/assistant mesaj sayısı (sayfalama için)."""
    conn = _connect()
    if conn is None:
        return 0
    try:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM messages m
            JOIN sessions s ON s.id = m.session_id
            WHERE m.role IN ('user', 'assistant')
              AND m.content IS NOT NULL AND m.content != ''
              AND s.source = 'telegram'
            """
        ).fetchone()
        return int(row[0]) if row else 0
    except Exception as exc:
        logger.warning("mesaj sayısı okunamadı: %s", exc)
        return 0
    finally:
        conn.close()


def get_message(msg_id: int) -> dict | None:
    """Tek mesajın tam detayı (kısaltmasız)."""
    conn = _connect()
    if conn is None:
        return None
    try:
        row = conn.execute(
            """
            SELECT m.id, m.session_id, m.role, m.content, m.timestamp,
                   m.tool_name, m.tool_calls, s.thread_id, s.title, s.chat_id
            FROM messages m
            JOIN sessions s ON s.id = m.session_id
            WHERE m.id = ?
            """,
            (msg_id,),
        ).fetchone()
    except Exception as exc:
        logger.warning("mesaj detayı okunamadı: %s", exc)
        return None
    finally:
        conn.close()

    if row is None:
        return None
    msg_id, session_id, role, content, ts, tool_name, tool_calls, thread_id, title, chat_id = row
    try:
        ts_iso = datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        ts_iso = ""
    return {
        "id": msg_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "ts": ts_iso,
        "thread_id": thread_id,
        "title": title,
        "chat_id": chat_id,
        "tool_name": tool_name,
        "tool_calls": bool(tool_calls),
    }
