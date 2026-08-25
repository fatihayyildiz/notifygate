"""Kalıcı istatistik deposu — günlük sayaçlar SQLite'ta.

RAM'deki sayaçlar restart'ta kayboluyordu; artık her olay write-through
ile günlük satıra işlenir (WAL modu, lokal — ihmal edilebilir maliyet).
"""
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from .config import settings

# Hangi sayaçların artırılabileceği — sabit liste (SQL enjeksiyon koruması).
COUNTERS = ("received", "delivered", "digested", "swept", "dropped")


class StatsStore:
    def __init__(self, db_path: str | Path):
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stats_daily (
                day TEXT PRIMARY KEY,
                received INTEGER NOT NULL DEFAULT 0,
                delivered INTEGER NOT NULL DEFAULT 0,
                digested INTEGER NOT NULL DEFAULT 0,
                swept INTEGER NOT NULL DEFAULT 0,
                dropped INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._conn.commit()

    def inc(self, col: str, n: int = 1) -> None:
        """Sayaç artır (write-through)."""
        if col not in COUNTERS:
            raise ValueError(f"bilinmeyen sayaç: {col}")
        self._conn.execute(
            f"INSERT INTO stats_daily(day, {col}) VALUES(?, ?) "
            f"ON CONFLICT(day) DO UPDATE SET {col} = {col} + ?",
            (date.today().isoformat(), n, n),
        )
        self._conn.commit()

    def today(self) -> dict:
        row = self._conn.execute(
            "SELECT received, delivered, digested, swept, dropped FROM stats_daily WHERE day = ?",
            (date.today().isoformat(),),
        ).fetchone()
        if not row:
            return {c: 0 for c in COUNTERS}
        return dict(zip(COUNTERS, row))

    def totals(self) -> dict:
        """Tüm zamanların toplamı (asla sıfırlanmaz)."""
        row = self._conn.execute(
            "SELECT COALESCE(SUM(received),0), COALESCE(SUM(delivered),0), COALESCE(SUM(digested),0), "
            "COALESCE(SUM(swept),0), COALESCE(SUM(dropped),0) FROM stats_daily"
        ).fetchone()
        return {
            "received": row[0], "delivered": row[1], "digested": row[2],
            "swept": row[3], "dropped": row[4],
        }

    def history(self, days: int = 30) -> list[dict]:
        """Son `days` gün, en eskiden en yeniye — boş günler sıfırla doldurulur."""
        start = date.today() - timedelta(days=days - 1)
        rows = self._conn.execute(
            "SELECT day, received, delivered, digested, swept, dropped "
            "FROM stats_daily WHERE day >= ?",
            (start.isoformat(),),
        ).fetchall()
        by_day = {r[0]: dict(zip(("day", *COUNTERS), r)) for r in rows}
        out = []
        for i in range(days):
            d = (start + timedelta(days=i)).isoformat()
            out.append(by_day.get(d) or {"day": d, **{c: 0 for c in COUNTERS}})
        return out


class EventsStore:
    """Son olayların kalıcı günlüğü — UI'nın 'sessiz mesajlar' görünümü.

    Son EVENT_KEEP kayıt tutulur; fazlası her yazımda temizlenir.
    """

    EVENT_KEEP = 500

    def __init__(self, db_path: str | Path):
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                priority TEXT NOT NULL DEFAULT 'normal',
                topic TEXT NOT NULL DEFAULT '',
                verdict TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                dedupe_key TEXT
            )
            """
        )
        self._migrate()
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS slack_threads (topic TEXT PRIMARY KEY, thread_ts TEXT NOT NULL)"
        )
        self._conn.commit()

    def thread_for(self, topic: str) -> str:
        row = self._conn.execute("SELECT thread_ts FROM slack_threads WHERE topic = ?", (topic,)).fetchone()
        return row[0] if row else ""

    def save_thread(self, topic: str, thread_ts: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO slack_threads (topic, thread_ts) VALUES (?, ?)", (topic, thread_ts)
        )
        self._conn.commit()

    def _migrate(self) -> None:
        """Eski şemadan gelen DB'lere yeni kolonları ekle."""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(events)")}
        if "body" not in cols:
            self._conn.execute("ALTER TABLE events ADD COLUMN body TEXT NOT NULL DEFAULT ''")
        if "metadata" not in cols:
            self._conn.execute("ALTER TABLE events ADD COLUMN metadata TEXT NOT NULL DEFAULT ''")
        if "delivered_to" not in cols:
            self._conn.execute("ALTER TABLE events ADD COLUMN delivered_to TEXT NOT NULL DEFAULT ''")
        if "origin_thread" not in cols:
            self._conn.execute("ALTER TABLE events ADD COLUMN origin_thread TEXT NOT NULL DEFAULT ''")

    def record(self, *, ts: str, source: str, event_type: str, title: str,
               priority: str, topic: str, verdict: str, reason: str,
               dedupe_key: str | None, body: str | None = None,
               metadata: dict | None = None, delivered_to: str = "",
               origin_thread: str = "") -> None:
        import json as _json
        self._conn.execute(
            "INSERT INTO events(ts, source, event_type, title, priority, topic, verdict, reason, dedupe_key, body, metadata, delivered_to, origin_thread) "
            "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, source, event_type, title, priority, topic, verdict, reason, dedupe_key,
             body or "", _json.dumps(metadata or {}, ensure_ascii=False), delivered_to, origin_thread),
        )
        # Son EVENT_KEEP kaydı koru — eski satırları temizle
        self._conn.execute(
            "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT ?)",
            (self.EVENT_KEEP,),
        )
        self._conn.commit()

    def recent(self, limit: int = 50, offset: int = 0) -> list[dict]:
        import json as _json
        rows = self._conn.execute(
            "SELECT id, ts, source, event_type, title, priority, topic, verdict, reason, dedupe_key, body, metadata, delivered_to, origin_thread "
            "FROM events ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        cols = ("id", "ts", "source", "event_type", "title", "priority", "topic",
                "verdict", "reason", "dedupe_key", "body", "metadata", "delivered_to", "origin_thread")
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            try:
                d["metadata"] = _json.loads(d["metadata"]) if d["metadata"] else {}
            except ValueError:
                d["metadata"] = {}
            out.append(d)
        return out

    def total(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def get(self, event_id: int) -> dict | None:
        import json as _json
        row = self._conn.execute(
            "SELECT id, ts, source, event_type, title, priority, topic, verdict, reason, dedupe_key, body, metadata, delivered_to, origin_thread "
            "FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if row is None:
            return None
        cols = ("id", "ts", "source", "event_type", "title", "priority", "topic",
                "verdict", "reason", "dedupe_key", "body", "metadata", "delivered_to", "origin_thread")
        d = dict(zip(cols, row))
        try:
            d["metadata"] = _json.loads(d["metadata"]) if d["metadata"] else {}
        except ValueError:
            d["metadata"] = {}
        return d


def make_store() -> StatsStore:
    path = Path(settings.db_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return StatsStore(path)


def make_events_store() -> EventsStore:
    path = Path(settings.db_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return EventsStore(path)
