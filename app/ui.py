"""NotifyGate web arayüzü — tek sayfa, bağımlılıksız (CDN yok).

Görünümler (hash routing):
  #/             → gösterge paneli (kartlar + grafik + sayfalı tablolar)
  #/event/:id    → olay detay sayfası
  #/message/:id  → mesaj detay sayfası
"""

UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NotifyGate</title>
<link rel="icon" type="image/svg+xml" href="/static/notifygate.svg">
<style>
  :root {
    --bg: #0e1013; --panel: #171a21; --panel-2: #1d212b; --border: #262b36;
    --text: #e6e9ef; --muted: #8b93a3; --accent: #6C5CE7;
    --green: #2ecc71; --cyan: #00d2d3; --amber: #f39c12; --red: #e74c3c; --gray: #5d6570;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 24px; }
  header { display: flex; align-items: baseline; gap: 14px; margin-bottom: 20px; flex-wrap: wrap; }
  h1 { font-size: 20px; font-weight: 700; letter-spacing: .3px; }
  h1 span { color: var(--accent); }
  #status { font-size: 12px; color: var(--muted); }
  #status .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: var(--green); margin-right: 6px; }
  #status.offline .dot { background: var(--red); }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 12px; margin-bottom: 24px; }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }
  .card .num { font-size: 26px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .card .lbl { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: .5px; margin-top: 2px; }
  .card.received .num { color: var(--accent); } .card.delivered .num { color: var(--green); }
  .card.digested .num { color: var(--cyan); } .card.swept .num { color: var(--gray); }
  .card.dropped .num { color: var(--amber); } .card.chat .num { color: #e84393; }
  .summary { font-size: 13px; color: var(--muted); background: var(--panel-2); border: 1px solid var(--border); border-radius: 10px; padding: 10px 14px; margin-bottom: 20px; }
  .summary b { color: var(--text); }
  section { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; margin-bottom: 20px; }
  h2 { font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: .6px; color: var(--muted); margin-bottom: 14px; }
  .chart { margin-bottom: 6px; }
  .legend { display: flex; gap: 16px; flex-wrap: wrap; margin-top: 8px; }
  .legend span { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); }
  .legend i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
  .filters { display: flex; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
  .filters input, .filters select { background: var(--panel-2); border: 1px solid var(--border); color: var(--text); border-radius: 8px; padding: 7px 10px; font-size: 13px; outline: none; }
  .filters input:focus, .filters select:focus { border-color: var(--accent); }
  .filters input { min-width: 200px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: .5px; padding: 6px 10px; border-bottom: 1px solid var(--border); position: sticky; top: 0; background: var(--panel); }
  td { padding: 7px 10px; border-bottom: 1px solid #20242e; vertical-align: top; }
  tr:hover td { background: var(--panel-2); }
  tr.clickable { cursor: pointer; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--muted); }
  .badge { display: inline-block; padding: 1px 8px; border-radius: 20px; font-size: 11px; font-weight: 600; }
  .v-delivered { background: rgba(46,204,113,.15); color: var(--green); }
  .v-digested { background: rgba(0,210,211,.15); color: var(--cyan); }
  .v-swept { background: rgba(93,101,112,.2); color: #aab2bd; }
  .v-dropped { background: rgba(243,156,18,.15); color: var(--amber); }
  .p-critical { color: var(--red); } .p-high { color: #ff8c69; } .p-normal { color: #7fb3ff; } .p-low { color: var(--gray); }
  .empty { color: var(--muted); text-align: center; padding: 24px 0; }
  #err { color: var(--red); font-size: 13px; margin-top: 10px; display: none; }
  .alltime { color: var(--muted); font-size: 12px; margin: -8px 0 6px; }
  .summary { color: var(--muted); font-size: 13px; margin-bottom: 14px; }
  footer { color: var(--muted); font-size: 12px; margin-top: 16px; }
  #tooltip { position: fixed; background: var(--panel-2); border: 1px solid var(--border); border-radius: 10px; padding: 10px 14px; font-size: 12px; pointer-events: none; z-index: 50; display: none; box-shadow: 0 8px 24px rgba(0,0,0,.4); }
  #tooltip .tt-day { color: var(--muted); margin-bottom: 6px; font-size: 11px; text-transform: uppercase; letter-spacing: .4px; }
  #tooltip .tt-row { display: flex; align-items: center; gap: 8px; line-height: 1.7; }
  #tooltip .tt-row i { width: 9px; height: 9px; border-radius: 2px; display: inline-block; }
  #tooltip .tt-row b { font-variant-numeric: tabular-nums; margin-left: auto; padding-left: 14px; }
  .msg { padding: 10px 12px; border: 1px solid var(--border); border-radius: 10px; margin-bottom: 8px; background: var(--panel-2); cursor: pointer; }
  .msg:hover { border-color: var(--accent); }
  .msg .m-head { display: flex; gap: 10px; align-items: baseline; margin-bottom: 4px; }
  .msg .m-sender { font-weight: 600; font-size: 13px; }
  .msg .m-sender.user { color: var(--accent); } .msg .m-sender.assistant { color: var(--green); }
  .msg .m-time { font-size: 11px; color: var(--muted); }
  .msg .m-topic { font-size: 11px; color: var(--muted); margin-left: auto; }
  .msg .m-text { font-size: 13px; white-space: pre-wrap; word-break: break-word; color: var(--text); }
  .pager { display: flex; align-items: center; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
  .pager button { background: var(--panel-2); border: 1px solid var(--border); color: var(--text); border-radius: 7px; padding: 5px 12px; font-size: 12px; cursor: pointer; }
  .pager button:hover:not(:disabled) { border-color: var(--accent); }
  .pager button:disabled { opacity: .35; cursor: default; }
  .pager .info { font-size: 12px; color: var(--muted); margin-left: auto; }
  .back { display: inline-block; color: var(--accent); text-decoration: none; font-size: 13px; margin-bottom: 16px; cursor: pointer; }
  .back:hover { text-decoration: underline; }
  .detail-grid { display: grid; grid-template-columns: 150px 1fr; gap: 6px 16px; max-width: 900px; }
  .detail-grid dt { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .5px; padding-top: 2px; }
  .detail-grid dd { font-size: 13px; word-break: break-word; }
  .detail-body { margin-top: 14px; padding-top: 14px; border-top: 1px solid var(--border); font-size: 13px; }
  pre.json { background: #12151b; border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; overflow-x: auto; color: #a8c0e8; margin-top: 8px; max-width: 900px; }
  .msg-full { white-space: pre-wrap; word-break: break-word; font-size: 14px; margin-top: 12px; }
  .detail-body pre.code { background: #12151b; border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; overflow-x: auto; color: #a8c0e8; margin: 8px 0; }
  .detail-body code { background: #12151b; border-radius: 4px; padding: 1px 5px; font: 12px ui-monospace, SFMono-Regular, Menlo, monospace; }
  .detail-body ul { margin: 6px 0 6px 20px; padding: 0; }
  .detail-body h2, .detail-body h3, .detail-body h4 { margin: 12px 0 4px; color: var(--text); }
  .detail-body .tc-label { font-size: 11px; text-transform: uppercase; letter-spacing: .5px; color: var(--muted); margin: 10px 0 4px; }
  .muted { color: var(--muted); }
  #detail-view { display: none; }
</style>
</head>
<body>
<header>
  <img src="/static/notifygate.svg" alt="NotifyGate" style="width:30px;height:30px;vertical-align:-7px;margin-right:2px">
  <h1>Notify<span>Gate</span></h1>
  <div id="status"><span class="dot"></span><span id="status-txt">loading…</span></div>
</header>

<div id="dashboard">
  <div class="cards">
    <div class="card received"><div class="num" id="c-received">–</div><div class="lbl">All Stream</div></div>
    <div class="card delivered"><div class="num" id="c-delivered">–</div><div class="lbl">Delivered (total)</div></div>
    <div class="card digested"><div class="num" id="c-digested">–</div><div class="lbl">Digested</div></div>
    <div class="card swept"><div class="num" id="c-swept">–</div><div class="lbl">Swept</div></div>
    <div class="card dropped"><div class="num" id="c-dropped">–</div><div class="lbl">Dropped</div></div>
    <div class="card chat"><div class="num" id="c-chat">–</div><div class="lbl">Chat msgs</div></div>
  </div>
  <div id="alltime" class="alltime"></div>
  <div id="summary" class="summary"></div>

  <section>
    <h2>Recent messages (Telegram)</h2>
    <div id="messages"><div class="empty">Loading…</div></div>
    <div class="pager" id="msg-pager"></div>
  </section>

  <section>
    <h2>Recent events</h2>
    <div class="filters">
      <input id="q-source" type="text" placeholder="Filter by source…">
      <select id="q-verdict">
        <option value="">All verdicts</option>
        <option>delivered</option><option>digested</option><option>swept</option><option>dropped</option>
      </select>
      <select id="q-priority">
        <option value="">All priorities</option>
        <option>critical</option><option>high</option><option>normal</option><option>low</option>
      </select>
    </div>
    <div style="max-height:460px; overflow-y:auto;">
      <table>
        <thead><tr><th>Time</th><th>Source</th><th>Event</th><th>Title</th><th>Pri</th><th>→ Topic</th><th>Verdict</th><th>Reason</th></tr></thead>
        <tbody id="rows"><tr><td colspan="8" class="empty">Loading…</td></tr></tbody>
    </table>
    </div>
    <div class="pager" id="ev-pager"></div>
    <div id="err"></div>
  </section>

  <section>
    <h2>Last 7 days</h2>
    <div class="chart" id="chart"></div>
    <div class="legend" id="legend"></div>
  </section>
</div>

<section id="detail-view">
  <a class="back" id="back-link">← Back</a>
  <div id="detail-content"></div>
</section>

<footer>NotifyGate · local · auto-refresh 5s</footer>

<div id="tooltip"></div>

<script>
const $ = id => document.getElementById(id);
let events = [];
let threadNames = {};

function fetchJSON(url, timeoutMs = 8000) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeoutMs);
  return fetch(url, { signal: ctl.signal }).finally(() => clearTimeout(t));
}

function markLive() {
  $('status').classList.remove('offline');
  $('status-txt').textContent = 'live · ' + new Date().toLocaleTimeString('en-GB', {hour12: false});
}

// Küçük, güvenli markdown renderer — önce HTML escape, sonra dönüşüm (XSS'siz).
const escHtml = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
function mdInline(t) {
  return t
    .replace(/`([^`\\n]+)`/g, '<code>$1</code>')
    .replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\\*([^*\\n]+)\\*/g, '$1<em>$2</em>')
    .replace(/~~([^~]+)~~/g, '<del>$1</del>')
    .replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^\\s)]+|mailto:[^\\s)]+)\\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/\\n/g, '<br>');
}
function md(src) {
  const blocks = escHtml(src).split(/\\n{2,}/);
  return blocks.map(b => {
    if (b.startsWith('```') && b.endsWith('```') && b.length > 6)
      return '<pre class="code">' + b.slice(3, -3) + '</pre>';
    const lines = b.split('\\n');
    if (lines.every(l => /^- /.test(l)))
      return '<ul>' + lines.map(l => '<li>' + mdInline(l.replace(/^- /, '')) + '</li>').join('') + '</ul>';
    let head = '';
    if (/^#{1,3} /.test(lines[0])) {
      const m = lines.shift().match(/^(#{1,3}) (.*)$/);
      const tag = 'h' + (m[1].length + 1);
      head = '<' + tag + '>' + mdInline(m[2]) + '</' + tag + '>';
    }
    return head + (lines.length ? '<p>' + mdInline(lines.join('\\n')) + '</p>' : '');
  }).join('\\n');
}
const EV_PAGE = 50, MSG_PAGE = 20;
let evPage = 1, evTotal = 0, msgPage = 1, msgTotal = 0;

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function fmtTs(iso) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit', second:'2-digit'});
}
function fmtDay(iso) {
  return new Date(iso + 'T00:00:00').toLocaleDateString('en-GB', {day: 'numeric', month: 'short'});
}

function fmtNum(n) {
  n = Number(n) || 0;
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, '') + 'k';
  return String(n);
}

function renderCards(s, at) {
  $('c-received').textContent = fmtNum(s.all_stream);    // olaylar + tüm mesajlar
  $('c-delivered').textContent = fmtNum(s.delivered_total); // uyarı + asistan mesajları
  $('c-digested').textContent = fmtNum(s.digested); $('c-swept').textContent = fmtNum(s.swept);
  $('c-dropped').textContent = fmtNum(s.dropped); $('c-chat').textContent = fmtNum(s.chat);
  const atLine = at ? `All time: <b>${fmtNum(at.received)}</b> events · <b>${fmtNum(at.swept)}</b> swept · <b>${fmtNum(at.delivered)}</b> delivered · <b>${fmtNum(at.digested)}</b> digested · <b>${fmtNum(at.dropped)}</b> dropped` : '';
  $('alltime').innerHTML = atLine;
  $('summary').innerHTML =
    `Without NotifyGate, <b>${s.all_stream}</b> messages would have arrived today ` +
    `(<b>${s.received}</b> events + <b>${s.all_msgs}</b> messages) — the filter blocked <b>${s.swept}</b>` +
    `${s.dropped ? `, dropped <b>${s.dropped}</b> duplicates` : ''}` +
    ` and <b>${s.delivered_total}</b> reached you.`;
}

function renderChart(days) {
  const W = 900, H = 150, PR = 10, PL = 36, PB = 20;
  const n = days.length;
  const step = (W - PL - PR) / Math.max(1, n);
  const bw = Math.min(step * 0.3, 26);
  const gap = 3;
  const groupW = 2 * bw + gap;
  // Grup merkezlerini eksenlerin içine hizala: çubuklar container'dan taşmaz,
  // ilk grup tam eksende başlar.
  const span = (W - PR - PL) - groupW;
  const x = i => PL + groupW / 2 + (n === 1 ? span / 2 : span * i / (n - 1));
  const sweptVal = d => (d.swept ?? 0) + (d.chat ?? 0);  // Swept çubuğu = swept + chat
  const max = Math.max(1, ...days.map(d => Math.max(d.all_stream ?? 0, sweptVal(d))));
  const y = v => H - PB - (H - PB - 6) * v / max;
  let svg = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;display:block">`;
  for (let g = 0; g <= 3; g++) {
    const v = max * g / 3, gy = y(v);
    svg += `<line x1="${PL}" y1="${gy}" x2="${W - PR}" y2="${gy}" stroke="#22262e" stroke-width="1"/>`;
    svg += `<text x="${PL - 6}" y="${gy + 4}" text-anchor="end" fill="#8b93a3" font-size="10">${fmtNum(v)}</text>`;
  }
  days.forEach((d, i) => {
    svg += `<text x="${x(i)}" y="${H-5}" fill="#8b93a3" font-size="10" text-anchor="middle">${fmtDay(d.day)}</text>`;
  });
  // Her gün iki çubuk: All Stream (mor) + Swept+Chat (gri)
  days.forEach((d, i) => {
    const allV = d.all_stream ?? 0, swV = sweptVal(d);
    const byA = y(allV), byS = y(swV);
    svg += `<rect x="${x(i) - bw - gap / 2}" y="${byA}" width="${bw}" height="${Math.max(2, (H - PB) - byA)}" rx="3" fill="#6C5CE7"/>`;
    svg += `<rect x="${x(i) + gap / 2}" y="${byS}" width="${bw}" height="${Math.max(2, (H - PB) - byS)}" rx="3" fill="#8b93a3"/>`;
  });
  // Hover bölgeleri — nokta ortalarına hizalı (kayma yok)
  days.forEach((d, i) => {
    const zx = i === 0 ? PL : (x(i - 1) + x(i)) / 2;
    const zxEnd = i === n - 1 ? W - PR : (x(i) + x(i + 1)) / 2;
    svg += `<rect x="${zx}" y="6" width="${zxEnd - zx}" height="${H-PB-6}" fill="transparent" class="hz" data-i="${i}"/>`;
  });
  svg += '</svg>';
  $('chart').innerHTML = svg;
  $('legend').innerHTML =
    `<span><i style="background:#6C5CE7"></i>All Stream</span>` +
    `<span><i style="background:#8b93a3"></i>Swept</span>`;

  const tip = $('tooltip');
  $('chart').querySelectorAll('.hz').forEach(rect => {
    rect.addEventListener('mousemove', ev => {
      const d = days[Number(rect.dataset.i)];
      tip.innerHTML =
        `<div class="tt-day">${fmtDay(d.day)}</div>` +
        `<div class="tt-row"><i style="background:#6C5CE7"></i>All Stream<b>${fmtNum(d.all_stream ?? 0)}</b></div>` +
        `<div class="tt-row"><i style="background:#8b93a3"></i>Swept + Chat<b>${fmtNum((d.swept ?? 0) + (d.chat ?? 0))}</b></div>`;
      tip.style.display = 'block';
      const pad = 14;
      tip.style.left = Math.min(ev.clientX + pad, window.innerWidth - 220) + 'px';
      tip.style.top = (ev.clientY - 12) + 'px';
    });
    rect.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
  });
}

function renderTable() {
  const src = ($('q-source').value || '').toLowerCase();
  const vd = $('q-verdict').value, pr = $('q-priority').value;
  const rows = events.filter(e =>
    (!src || (e.source + ' ' + (e.title || '')).toLowerCase().includes(src)) &&
    (!vd || e.verdict === vd) && (!pr || e.priority === pr)
  );
  const tb = $('rows');
  if (!rows.length) { tb.innerHTML = '<tr><td colspan="8" class="empty">No events match</td></tr>'; return; }
  tb.innerHTML = rows.map(e => {
    const originThread = e.origin_thread || '';
    const name = threadNames[originThread] || (e.topic || 'default');
    const topicCell = `${esc(name)} <span class="mono">#${esc(originThread || e.delivered_to || '–')}</span>`;
    return `<tr class="clickable" data-id="${e.id}">
      <td class="mono">${fmtTs(e.ts)}</td>
      <td>${esc(e.source)}</td>
      <td class="mono">${esc(e.event_type)}</td>
      <td>${esc(e.title) || '<span class="mono">–</span>'}</td>
      <td class="p-${esc(e.priority)}">${esc(e.priority)}</td>
      <td>${topicCell}</td>
      <td><span class="badge v-${esc(e.verdict)}">${esc(e.verdict)}</span></td>
      <td class="mono">${esc(e.reason)}</td>
    </tr>`;
  }).join('');
  tb.querySelectorAll('tr.clickable').forEach(tr =>
    tr.addEventListener('click', () => { location.hash = '#/event/' + tr.dataset.id; }));
}

function renderMessages(msgs) {
  const el = $('messages');
  if (!msgs.length) { el.innerHTML = '<div class="empty">No recent messages</div>'; return; }
  el.innerHTML = msgs.map(m => {
    const sender = m.role === 'user' ? 'You' : 'Assistant';
    const cls = m.role === 'user' ? 'user' : 'assistant';
    const topicName = threadNames[m.thread_id] || (m.thread_id ? '#' + m.thread_id : '');
    return `<div class="msg" data-id="${m.id}">
      <div class="m-head">
        <span class="m-sender ${cls}">${sender}</span>
        <span class="m-time">${fmtTs(m.ts)}</span>
        ${topicName ? `<span class="m-topic">${esc(topicName)}</span>` : ''}
      </div>
      <div class="m-text">${esc(m.content)}</div>
    </div>`;
  }).join('');
  el.querySelectorAll('.msg').forEach(m =>
    m.addEventListener('click', () => { location.hash = '#/message/' + m.dataset.id; }));
}

function renderPager(el, page, perPage, total, cb) {
  const pages = Math.max(1, Math.ceil(total / perPage));
  const p = Math.min(page, pages);
  el.innerHTML =
    `<button data-p="${p-1}" ${p <= 1 ? 'disabled' : ''}>‹ Prev</button>` +
    `<span class="info">Page ${p} / ${pages} · ${fmtNum(total)} total</span>` +
    `<button data-p="${p+1}" ${p >= pages ? 'disabled' : ''}>Next ›</button>`;
  el.querySelectorAll('button:not(:disabled)').forEach(b =>
    b.addEventListener('click', () => cb(Number(b.dataset.p))));
}

function showDashboard() {
  $('detail-view').style.display = 'none';
  $('dashboard').style.display = '';
  refresh();
}

async function showEventDetail(id) {
  $('dashboard').style.display = 'none';
  $('detail-view').style.display = 'block';
  $('detail-content').innerHTML = '<div class="empty">Loading…</div>';
  try {
    const r = await fetchJSON('/api/events/' + id);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const e = await r.json();
    const originName = threadNames[e.origin_thread] || (e.topic || 'default');
    const meta = e.metadata && Object.keys(e.metadata).length ? JSON.stringify(e.metadata, null, 2) : '';
    const tool = (e.metadata || {}).tool_name
      ? `<div class="detail-body"><strong>Tool call: ${esc(e.metadata.tool_name)}</strong>${e.metadata.duration_ms ? ` <span class="mono muted">${esc(e.metadata.duration_ms)} ms</span>` : ''}
          ${e.metadata.args ? `<div class="tc-label">Request (args)</div><pre class="json">${esc(e.metadata.args)}</pre>` : ''}
          ${e.metadata.result !== undefined ? `<div class="tc-label">Response</div><pre class="json">${esc(e.metadata.result)}</pre>` : ''}
        </div>`
      : '';
    $('detail-content').innerHTML =
      `<h2>Event #${e.id}</h2>
      <dl class="detail-grid">
        <dt>Timestamp</dt><dd class="mono">${esc(e.ts)}</dd>
        <dt>Source</dt><dd>${esc(e.source)}</dd>
        <dt>Event type</dt><dd class="mono">${esc(e.event_type)}</dd>
        <dt>Title</dt><dd>${esc(e.title) || '–'}</dd>
        <dt>Priority</dt><dd class="p-${esc(e.priority)}">${esc(e.priority)}</dd>
        <dt>Origin topic</dt><dd>${esc(originName)} <span class="mono">#${esc(e.origin_thread || '–')}</span></dd>
        <dt>Delivered to</dt><dd class="mono">${esc(e.delivered_to) || '–'}</dd>
        <dt>Verdict</dt><dd><span class="badge v-${esc(e.verdict)}">${esc(e.verdict)}</span> — ${esc(e.reason)}</dd>
        <dt>Dedupe key</dt><dd class="mono">${esc(e.dedupe_key) || '–'}</dd>
      </dl>
      ${e.body ? `<div class="detail-body"><strong>Body</strong><br>${md(e.body)}</div>` : ''}
      ${tool}
      ${meta ? `<div class="detail-body"><strong>Metadata</strong><pre class="json">${esc(meta)}</pre></div>` : ''}`;
    markLive();
  } catch (err) {
    $('detail-content').innerHTML = `<div class="empty">Event not found (${esc(err.message)})</div>`;
  }
}

async function showMessageDetail(id) {
  $('dashboard').style.display = 'none';
  $('detail-view').style.display = 'block';
  $('detail-content').innerHTML = '<div class="empty">Loading…</div>';
  try {
    const r = await fetchJSON('/api/messages/' + id);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    const m = await r.json();
    const sender = m.role === 'user' ? 'You' : 'Assistant';
    const cls = m.role === 'user' ? 'user' : 'assistant';
    const topicName = threadNames[m.thread_id] || (m.thread_id ? '#' + m.thread_id : '');
    $('detail-content').innerHTML =
      `<h2>Message #${m.id}</h2>
      <dl class="detail-grid">
        <dt>Sender</dt><dd class="m-sender ${cls}">${sender}</dd>
        <dt>Timestamp</dt><dd class="mono">${esc(m.ts)}</dd>
        <dt>Session</dt><dd class="mono">${esc(m.session_id)}</dd>
        <dt>Topic</dt><dd>${esc(topicName)}</dd>
        <dt>Thread</dt><dd class="mono">${esc(m.thread_id || '–')}</dd>
        <dt>Session title</dt><dd>${esc(m.title) || '–'}</dd>
        <dt>Tool call</dt><dd>${m.tool_calls ? `yes <span class="mono">(${esc(m.tool_name || '?')})</span>` : 'no'}</dd>
      </dl>
      <div class="detail-body"><strong>Content</strong><br>${md(m.content)}</div>`;
  } catch (err) {
    $('detail-content').innerHTML = `<div class="empty">Message not found (${esc(err.message)})</div>`;
  }
}

function route() {
  const h = location.hash;
  const evm = h.match(/^#\/event\/(\d+)/);
  const msm = h.match(/^#\/message\/(\d+)/);
  if (evm) showEventDetail(Number(evm[1]));
  else if (msm) showMessageDetail(Number(msm[1]));
  else showDashboard();
}

async function refresh() {
  try {
    const [statsRes, evRes, metaRes, msgRes] = await Promise.all([
      fetchJSON('/api/stats?days=7'),
      fetchJSON(`/api/events?page=${evPage}&per_page=${EV_PAGE}`),
      fetchJSON('/api/meta'),
      fetchJSON(`/api/messages?page=${msgPage}&per_page=${MSG_PAGE}`)
    ]);
    if (!statsRes.ok || !evRes.ok || !metaRes.ok || !msgRes.ok) throw new Error('API ' + statsRes.status);
    const stats = await statsRes.json();
    const evData = await evRes.json();
    threadNames = (await metaRes.json()).thread_names || {};
    const msgData = await msgRes.json();
    evTotal = evData.total; msgTotal = msgData.total;
    events = evData.events;
    renderCards(stats.today, stats.all_time); renderChart(stats.days); renderTable(); renderMessages(msgData.messages);
    renderPager($('ev-pager'), evPage, EV_PAGE, evTotal, p => { evPage = p; refresh(); });
    renderPager($('msg-pager'), msgPage, MSG_PAGE, msgTotal, p => { msgPage = p; refresh(); });
    $('status').classList.remove('offline');
    $('status-txt').textContent = 'live · ' + new Date().toLocaleTimeString();
    $('err').style.display = 'none';
  } catch (e) {
    $('status').classList.add('offline');
    $('status-txt').textContent = 'offline';
    $('err').style.display = 'block';
    $('err').textContent = 'Cannot reach NotifyGate: ' + e.message;
  }
}
['q-source','q-verdict','q-priority'].forEach(id => $(id).addEventListener('input', renderTable));
$('back-link').addEventListener('click', () => { location.hash = '#/'; });
window.addEventListener('hashchange', route);
route();
setInterval(() => {
  if (!location.hash || location.hash === '#/') {
    refresh();
  } else {
    // Detay sayfasında sadece canlılık kontrolü
    fetchJSON('/health', 5000).then(r => r.ok ? markLive() : setOffline()).catch(setOffline);
  }
}, 5000);

function setOffline() {
  $('status').classList.add('offline');
  $('status-txt').textContent = 'offline';
}
</script>
</body>
</html>
"""
