"""Olay modeli — agent'lardan gelen bildirim şeması."""
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class Priority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class AgentEvent(BaseModel):
    source: str = Field(..., description="Gönderen: hermes, claude-code, github-actions...")
    event_type: str = Field(..., description="Olay türü: deploy_done, process_end, agent_step...")
    title: str = Field(..., description="Kısa satır")
    body: str | None = None
    priority: Priority = Priority.NORMAL
    topic: str = Field("", description="Hedef topic adı — routes map'inden thread çözülür; boş = varsayılan thread")
    ts: datetime | None = None
    dedupe_key: str | None = None
    stale: bool = False  # True ise süpürülür, asla iletilmez
    metadata: dict = Field(default_factory=dict)

    def effective_ts(self) -> datetime:
        return self.ts or datetime.now(timezone.utc)

    @property
    def identity(self) -> str:
        return self.dedupe_key or f"{self.source}:{self.event_type}:{self.title}"
