"""NotifyGate yapılandırması — .env / ortam değişkenlerinden."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_thread_id: str = ""  # forum topic ise message_thread_id

    # Slack (opsiyonel) — Incoming Webhook URL'si; doluysa teslimatlar
    # Telegram'a EK OLARAK bu kanala da gider.
    slack_webhook_url: str = ""

    # Topic yönlendirme: {"topic_adı": "thread_id"} — event.topic buradan çözülür.
    # Eşleşme yoksa telegram_thread_id (varsayılan) kullanılır. JSON env:
    #   NOTIFYGATE_ROUTES={"project_a":"4721","project_b":"4722"}
    routes: dict[str, str] = {}

    # Thread → Telegram topic adı (UI gösterimi için). JSON env:
    #   NOTIFYGATE_THREAD_NAMES={"4721":"Project A","4722":"Project B"}
    thread_names: dict[str, str] = {}

    # Hermes hooks.outbound imza doğrulaması (X-Hermes-Signature-256).
    # Boşsa legacy davranış: imza kontrol edilmez.
    hermes_secret: str = ""

    # İstatistik DB yolu (SQLite). Proje köküne göre çözülür.
    db_path: str = "data/notifygate.db"

    # Hermes oturum DB'si — UI'nın 'son sohbet' görünümü için salt-okunur okunur.
    hermes_state_db: str = "~/.hermes/state.db"

    # Kurallar
    quiet_start: int = 23
    quiet_end: int = 8
    quiet_allow: str = "critical"  # sessiz saatte hangi öncelikler geçer
    dedupe_window_seconds: int = 300
    digest_interval_seconds: int = 300
    digest_max_events: int = 20

    model_config = {"env_prefix": "NOTIFYGATE_", "env_file": ".env"}


settings = Settings()
