"""Filtre hattı: dedupe → stale süpürme → sessiz saat → öncelik sınıflandırma.

Her filtre bağımsız; MVP'de bellek içi durum yeterli (tek süreç, tek örnek).
Ölçeklenince Redis'e taşınır — arayüz aynı kalır.
"""
import time
from dataclasses import dataclass, field
from enum import Enum

from .models import AgentEvent


class Verdict(str, Enum):
    SWEEP = "sweep"          # at, hiç iletilmez
    DROP_DUPLICATE = "drop_duplicate"
    DELIVER_NOW = "deliver_now"   # kritik/önemli → hemen
    DIGEST = "digest"             # normal/düşük → özet bekle


@dataclass
class FilterResult:
    verdict: Verdict
    reason: str = ""
    priority: str = "normal"


class FilterPipeline:
    def __init__(
        self,
        dedupe_window_seconds: int = 300,
        quiet_start: int = 23,
        quiet_end: int = 8,
        quiet_allow: str = "critical",
    ):
        self._seen: dict[str, float] = {}
        self.dedupe_window = dedupe_window_seconds
        self.quiet_start = quiet_start
        self.quiet_end = quiet_end
        self.quiet_allow = {p.strip() for p in quiet_allow.split(",")}

    def apply(self, event: AgentEvent, now_hour: int | None = None) -> FilterResult:
        # 1) Bayat bildirim → süpür
        if event.stale:
            return FilterResult(Verdict.SWEEP, "stale işaretli")

        # 2) Öncelik sırası (kritik asla susturulmaz)
        priority = event.priority.value
        rank = {"critical": 0, "high": 1, "normal": 2, "low": 3}

        # 3) Tekrar kontrolü — aynı olay pencerede geldiyse at
        now = time.time()
        key = event.identity
        last = self._seen.get(key)
        if last is not None and (now - last) < self.dedupe_window:
            return FilterResult(Verdict.DROP_DUPLICATE, f"son gönderim {int(now-last)}s önce")
        self._seen[key] = now

        # 4) Sessiz saat — yalnızca izinli öncelikler geçer
        if self._is_quiet(now_hour):
            if priority in self.quiet_allow:
                return FilterResult(Verdict.DELIVER_NOW, f"sessiz saat ama {priority} izinli")
            return FilterResult(Verdict.DIGEST, f"sessiz saat → özet")

        # 5) Normal akış: kritik/high hemen, normal/low özete
        if rank[priority] <= 1:
            return FilterResult(Verdict.DELIVER_NOW, priority)
        return FilterResult(Verdict.DIGEST, priority)

    def _is_quiet(self, now_hour: int | None = None) -> bool:
        from datetime import datetime

        # YEREL saat (Berlin) — UTC kullanılırsa pencere 2 saat kayar.
        h = now_hour if now_hour is not None else datetime.now().astimezone().hour
        if self.quiet_start == self.quiet_end:
            return False
        if self.quiet_start < self.quiet_end:
            return self.quiet_start <= h < self.quiet_end
        # Gece yarısını aşan aralık (23–08 gibi)
        return h >= self.quiet_start or h < self.quiet_end
