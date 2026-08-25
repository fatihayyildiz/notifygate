# NotifyGate

**Universal notification filter for AI agents.** Agents (Hermes, Claude Code,
Codex, GitHub Actions, any bot) POST lifecycle events to one endpoint;
NotifyGate applies rules — dedupe, stale-event sweep, priority routing,
quiet hours, digest batching — and delivers only what matters to
Telegram (plus an optional Slack webhook channel).

Born from a real pain: agents flood users with interim updates, stale process
notifications, and duplicate noise. NotifyGate is the code-level fix.

## How it works

```
agent ──POST /v1/events──▶ NotifyGate ──rules──▶ Telegram (+ Slack)
                              │
                              ├─ dedupe:      same event within window → drop
                              ├─ stale:       marked-stale events → sweep
                              ├─ priority:    critical/high/normal/low
                              ├─ quiet hours: 23:00–08:00 → only allowed priorities
                              └─ digest:      normal/low → batched digest
```

## Quickstart

```bash
cp .env.example .env          # fill TELEGRAM_BOT_TOKEN + CHAT_ID
uv venv && uv pip install -e .
uvicorn app.main:app --port 8457
```

```bash
curl -X POST localhost:8457/v1/events \
  -H 'Content-Type: application/json' \
  -d '{"source":"hermes","event_type":"deploy_done","title":"Deploy tamamlandı","priority":"high"}'
```

No token configured? NotifyGate runs in dry-run mode (logs the would-be
message) so you can develop locally without credentials.

## Topic routing (Telegram forum topics)

Each event can carry a `topic` name; `NOTIFYGATE_ROUTES` maps topic names to
Telegram thread IDs. Unmatched topics fall back to `TELEGRAM_THREAD_ID`.

```bash
# .env
NOTIFYGATE_ROUTES={"project_a":"4721","project_b":"4722"}
```

```bash
curl -X POST localhost:8457/v1/events \
  -H 'Content-Type: application/json' \
  -d '{"source":"github-actions","event_type":"deploy_done","title":"Deploy tamamlandı","priority":"high","topic":"ipdorm"}'
```

Digests are grouped per thread — each topic receives its own batched summary.

## Event format

```json
{
  "source": "hermes",            // required — which agent/system
  "event_type": "process_end",   // required — kind of event
  "title": "Build bitti",        // required — short line
  "body": "12 migration OK",     // optional — details
  "priority": "normal",          // critical | high | normal | low
  "topic": "notifygate",         // optional — routes map'inden thread çözülür
  "ts": "2026-08-18T20:00:00Z",  // optional — defaults to now
  "dedupe_key": "deploy-42",     // optional — dedupe identity
  "stale": false,                // true → swept, never delivered
  "metadata": {}                 // optional — extra context
}
```

## Rules (MVP)

| Rule | Config | Default |
|---|---|---|
| Dedupe | `NOTIFYGATE_DEDUPE_WINDOW_SECONDS` | 300s |
| Quiet hours | `NOTIFYGATE_QUIET_START` / `_END` | 23–08 |
| Quiet allow | `NOTIFYGATE_QUIET_ALLOW` | `critical` |
| Digest interval | `NOTIFYGATE_DIGEST_INTERVAL_SECONDS` | 300s |
| Digest size cap | `NOTIFYGATE_DIGEST_MAX_EVENTS` | 20 |

## Slack (optional)

NotifyGate can deliver to **both Telegram and Slack** at the same time.
You only need an [Incoming Webhook](https://api.slack.com/messaging/webhooks)
from Slack (no bot token, no OAuth):

1. Slack → *Apps* → *Incoming Webhooks* → create a webhook for a channel.
2. Set it in your `.env`:

   ```bash
   # Slack console'unuzdaki Incoming Webhook URL'sini yapıştırın
   NOTIFYGATE_SLACK_WEBHOOK_URL=<your-slack-incoming-webhook-url>
   ```

3. Restart NotifyGate. Every delivery now goes to Telegram **and** the
   Slack channel. If Telegram is not configured, Slack is used alone.

### Threads (optional, bot token mode)

The incoming webhook alone cannot open threads, but if you create a small
Slack app with the `chat:write` scope you get **topic-based threads**:

```bash
NOTIFYGATE_SLACK_TOKEN=xoxb-...
NOTIFYGATE_SLACK_CHANNEL=#notifygate
```

Each routing topic then accumulates its own Slack thread — the first event
opens the thread, subsequent events for the same topic reply inside it
(mirroring Telegram topics). Threads persist across restarts.

Notes:

- Slack has no topics/threads in the webhook-only mode — **digests arrive
  as a single message** on the webhook's channel (Telegram keeps per-topic
  grouping).
- Unset the variables to disable Slack entirely (current behaviour unchanged).

## Hermes plugin (open-source install)

Hermes kullanıcıları NotifyGate'i tek komutla kurar — hooks.outbound yapılandırmasına dokunmadan:

```bash
hermes plugins install fatihayyildiz/notifygate/hermes-plugin
```

Ardından `~/.hermes/.env`'e iki satır:

```bash
NOTIFYGATE_URL=http://localhost:8457/v1/adapters/hermes
NOTIFYGATE_SECRET=            # opsiyonel — sunucudaki NOTIFYGATE_HERMES_SECRET ile aynı olmalı
```

Plugin, Hermes olaylarını (tool çağrısı, oturum sonu, subagent) imzalı ve fire-and-forget
olarak NotifyGate sunucusuna iletir; ajan akışını asla engellemez. Sunucunun kendisi bu
repo ile ayağa kaldırılır (yerel `uvicorn app.main:app --port 8457` veya Docker).

Marketplace listesi için: `hermes plugins search notifygate` — henüz resmî index'te değil;
`hermes plugins install <owner/repo>` ile doğrudan GitHub'dan kurulur (brew tap mantığı).

## Web UI

`http://localhost:8457/ui` — koyu temalı tek sayfa (bağımlılıksız, CDN yok):

- Bugünün kartları: received / delivered / digested / swept / dropped
- Son 30 gün çubuk grafik
- Son 200 olay tablosu: zaman, kaynak, olay, başlık, öncelik, **karar (verdict)**, neden — süpürülen/duplicate "sessiz" mesajlar dahil
- Kaynak / verdict / öncelik filtreleri, 10 sn otomatik yenileme

API: `GET /api/stats?days=30` (bugün + geçmiş) · `GET /api/events?limit=200` (son olaylar)

## Roadmap

- [x] Event intake + rule pipeline (MVP)
- [x] Telegram delivery + dry-run mode
- [x] Hermes `hooks.outbound` integration + HMAC signature verification
- [x] Topic routing + per-thread digest separation
- [ ] Claude Code hook example
- [ ] Inbound "proxy mode" for Bot API tokens
