const feed = document.getElementById('feed');
const summary = document.getElementById('summary');
const notifToggle = document.getElementById('notif-toggle');
const themeToggle = document.getElementById('theme-toggle');
const refreshBtn = document.getElementById('refresh-btn');
const connDot = document.getElementById('conn-dot');
const addForm = document.getElementById('add-form');
const addInput = document.getElementById('add-input');
const addError = document.getElementById('add-error');
const impChecks = document.querySelectorAll('aside input[data-imp]');

let selectedTicker = null;
let allEvents = [];
let watchlistCache = [];
const MAX_EVENTS = 1000;

/* ---------- theme ---------- */
const savedTheme = localStorage.getItem('theme') || 'dark';
setTheme(savedTheme);
themeToggle.addEventListener('click', () => {
  const next = document.body.dataset.theme === 'dark' ? 'light' : 'dark';
  setTheme(next);
  localStorage.setItem('theme', next);
});
function setTheme(t) { document.body.dataset.theme = t; }

/* ---------- notifications ---------- */
notifToggle.checked = localStorage.getItem('notif') === '1';
notifToggle.addEventListener('change', async () => {
  localStorage.setItem('notif', notifToggle.checked ? '1' : '0');
  if (notifToggle.checked && Notification.permission !== 'granted') {
    await Notification.requestPermission();
  }
});

impChecks.forEach(cb => cb.addEventListener('change', render));

/* ---------- formatting ---------- */
function formatTime(iso) {
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  return d.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })
    + ' · ' + d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function pillFor(type) {
  if (type === 'filing_8k')   return { cls: 'filing', label: '8-K' };
  if (type === 'earnings')    return { cls: 'earnings', label: 'Earnings' };
  if (type === 'price_alert') return { cls: 'price', label: '⚡ 异动' };
  if (type === 'analyst')     return { cls: 'analyst', label: '分析师' };
  if (type === 'insider')     return { cls: 'insider', label: '内部人' };
  if (type === 'sentiment')   return { cls: 'sentiment', label: '📣 舆情' };
  return { cls: 'news', label: 'News' };
}

/* ---------- card ---------- */
function renderCard(ev, isNew = false) {
  const el = document.createElement('article');
  el.className = `card ${ev.importance}${isNew ? ' new' : ''}`;
  el.dataset.imp = ev.importance;
  el.dataset.ticker = ev.ticker;

  const pill = pillFor(ev.event_type);
  const link = ev.url ? `<a href="${ev.url}" target="_blank" rel="noopener">原文 ↗</a>` : '';

  el.innerHTML = `
    <div class="head">
      <span class="ticker">${escapeHtml(ev.ticker)}</span>
      <span class="title">${escapeHtml(ev.title)}</span>
    </div>
    <div class="meta">
      <span class="pill ${pill.cls}">${pill.label}</span>
      <span>${formatTime(ev.published_at)}</span>
      <span class="sep">·</span>
      <span>${escapeHtml(ev.source)}</span>
      ${link ? `<span class="sep">·</span>${link}` : ''}
    </div>
    ${ev.summary_cn ? `<p class="summary summary-cn">🤖 ${escapeHtml(ev.summary_cn)}</p>` : ''}
    ${ev.summary ? `<p class="summary">${escapeHtml(ev.summary)}</p>` : ''}
  `;
  if (isNew) setTimeout(() => el.classList.remove('new'), 2200);
  return el;
}

/* ---------- render ---------- */
function render() {
  const impEnabled = new Set(
    Array.from(impChecks).filter(c => c.checked).map(c => c.dataset.imp)
  );
  const visible = allEvents.filter(e =>
    impEnabled.has(e.importance) && (!selectedTicker || e.ticker === selectedTicker)
  );
  feed.innerHTML = '';
  if (visible.length === 0) {
    const d = document.createElement('div');
    d.className = 'empty';
    d.textContent = selectedTicker
      ? `暂无 ${selectedTicker} 的相关事件`
      : '暂无事件 — 尝试刷新或添加更多 ticker';
    feed.appendChild(d);
  } else {
    visible.forEach(e => feed.appendChild(renderCard(e)));
  }

  const highCount = visible.filter(e => e.importance === 'high').length;
  const tag = selectedTicker ? `${selectedTicker} · ` : '';
  summary.textContent = `${tag}${visible.length} events · ${highCount} high`;

  renderWatchlist(watchlistCache);
}

/* ---------- watchlist ---------- */
function renderWatchlist(tickers) {
  watchlistCache = tickers;
  const ul = document.getElementById('watchlist');
  const counts = {};
  allEvents.forEach(e => { counts[e.ticker] = (counts[e.ticker] || 0) + 1; });

  const allLi = `
    <li data-ticker="" class="${!selectedTicker ? 'selected' : ''}">
      <span class="label all">All</span>
      <span class="right"><span class="count">${allEvents.length}</span></span>
    </li>`;
  const items = tickers.map(t => `
    <li data-ticker="${t}" class="${selectedTicker === t ? 'selected' : ''}">
      <span class="label">${t}</span>
      <span class="right">
        <span class="count">${counts[t] || 0}</span>
        <button class="del" data-del="${t}" aria-label="删除 ${t}">✕</button>
      </span>
    </li>`).join('');
  ul.innerHTML = allLi + items;

  ul.querySelectorAll('li').forEach(li => {
    li.addEventListener('click', (e) => {
      if (e.target.dataset.del) return;
      selectedTicker = li.dataset.ticker || null;
      updateBacktestBtn();
      render();
    });
  });
  ul.querySelectorAll('button.del').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      await removeTicker(btn.dataset.del);
    });
  });
}

/* ---------- watchlist mutations ---------- */
async function addTicker(ticker) {
  addError.textContent = '';
  const r = await fetch('/api/watchlist', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ ticker }),
  });
  if (!r.ok) {
    const d = await r.json().catch(() => ({detail: 'error'}));
    addError.textContent = d.detail || 'error';
    return;
  }
  const data = await r.json();
  renderWatchlist(data.tickers);
  addInput.value = '';
}

async function removeTicker(ticker) {
  const r = await fetch(`/api/watchlist/${ticker}`, { method: 'DELETE' });
  if (!r.ok) {
    const d = await r.json().catch(() => ({detail: 'error'}));
    addError.textContent = d.detail || 'error';
    return;
  }
  const data = await r.json();
  if (selectedTicker === ticker) selectedTicker = null;
  renderWatchlist(data.tickers);
  render();
}

addForm.addEventListener('submit', (e) => {
  e.preventDefault();
  const t = addInput.value.trim().toUpperCase();
  if (t) addTicker(t);
});

/* ---------- refresh ---------- */
refreshBtn.addEventListener('click', async () => {
  if (refreshBtn.disabled) return;
  refreshBtn.disabled = true;
  refreshBtn.classList.add('spinning');
  try {
    await fetch('/api/refresh', { method: 'POST' });
    setTimeout(async () => {
      await loadHistory();
      refreshBtn.classList.remove('spinning');
      refreshBtn.disabled = false;
    }, 2500);
  } catch (e) {
    refreshBtn.classList.remove('spinning');
    refreshBtn.disabled = false;
  }
});

/* ---------- data load ---------- */
async function loadWatchlist() {
  const r = await fetch('/api/watchlist');
  const data = await r.json();
  watchlistCache = data.tickers;
  renderWatchlist(data.tickers);
}

async function loadHistory() {
  const r = await fetch('/api/events?limit=500');
  const data = await r.json();
  allEvents = data.events;
  render();
  await loadWatchlist();
}

/* ---------- SSE ---------- */
function connectStream() {
  const es = new EventSource('/stream');
  es.onopen = () => connDot.classList.remove('bad');
  es.onmessage = (msg) => {
    const ev = JSON.parse(msg.data);
    allEvents.unshift(ev);
    if (allEvents.length > MAX_EVENTS) allEvents.length = MAX_EVENTS;
    render();
    if (ev.importance === 'high' && notifToggle.checked
        && Notification.permission === 'granted') {
      new Notification(`${ev.ticker}: ${ev.title}`, { body: ev.summary || '' });
    }
  };
  es.onerror = () => {
    connDot.classList.add('bad');
    console.warn('SSE disconnected, browser will auto-reconnect');
  };
}

/* ---------- modal ---------- */
const modal = document.getElementById('modal');
const modalTitle = document.getElementById('modal-title');
const modalBody = document.getElementById('modal-body');
document.getElementById('modal-close').addEventListener('click', closeModal);
modal.addEventListener('click', (e) => { if (e.target === modal) closeModal(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

function openModal(title, html) {
  modalTitle.textContent = title;
  modalBody.innerHTML = html;
  modal.classList.remove('hidden');
}
function closeModal() { modal.classList.add('hidden'); }

/* ---------- digest ---------- */
document.getElementById('btn-digest').addEventListener('click', async () => {
  openModal('早报预览', '<p class="empty-note">加载中…</p>');
  try {
    const r = await fetch('/api/digest?hours=24');
    const d = await r.json();
    const html = `
      <p style="color:var(--text-2);margin-bottom:12px">${escapeHtml(d.title)}</p>
      <pre>${escapeHtml(d.body)}</pre>
    `;
    openModal('早报预览', html);
  } catch (e) {
    openModal('早报预览', `<p class="empty-note">加载失败: ${e.message}</p>`);
  }
});

/* ---------- backtest ---------- */
const btBtn = document.getElementById('btn-backtest');
btBtn.addEventListener('click', () => {
  const t = selectedTicker || (watchlistCache[0] || '');
  renderBacktestPanel(t, 'filing_8k');
});
function updateBacktestBtn() { /* always enabled now */ }

function renderBacktestPanel(ticker, eventType) {
  const tickerOpts = watchlistCache
    .map(t => `<option value="${t}"${t === ticker ? ' selected' : ''}>${t}</option>`)
    .join('');
  const typeOpts = ['filing_8k', 'earnings', 'analyst', 'news', 'price_alert', 'insider']
    .map(t => `<option value="${t}"${t === eventType ? ' selected' : ''}>${t}</option>`)
    .join('');
  const controls = `
    <div class="bt-controls">
      <select id="bt-ticker">${tickerOpts}</select>
      <select id="bt-type">${typeOpts}</select>
      <button class="bt-run" id="bt-run">运行</button>
    </div>
    <div id="bt-result"><p class="empty-note">加载中…</p></div>
  `;
  openModal(`事件回测`, controls);
  const runEl = document.getElementById('bt-run');
  const tickerEl = document.getElementById('bt-ticker');
  const typeEl = document.getElementById('bt-type');
  const run = () => loadBacktest(tickerEl.value, typeEl.value);
  runEl.addEventListener('click', run);
  tickerEl.addEventListener('change', run);
  typeEl.addEventListener('change', run);
  if (ticker) run(); else document.getElementById('bt-result').innerHTML =
    '<p class="empty-note">请选择 ticker 和事件类型</p>';
}

async function loadBacktest(ticker, eventType) {
  const resEl = document.getElementById('bt-result');
  resEl.innerHTML = '<p class="empty-note">加载中…</p>';
  try {
    const r = await fetch(`/api/backtest?ticker=${ticker}&event_type=${eventType}`);
    const d = await r.json();
    if (!d.n_events) {
      resEl.innerHTML = `<p class="empty-note">没有 ${eventType} 类型的历史事件可供回测</p>`;
      return;
    }
    const rows = d.windows.map(w => {
      const meanCls = w.mean_pct > 0 ? 'pos' : (w.mean_pct < 0 ? 'neg' : '');
      const medCls = w.median_pct > 0 ? 'pos' : (w.median_pct < 0 ? 'neg' : '');
      return `<tr>
        <td class="win">+${w.window} 日</td>
        <td>${w.n}</td>
        <td class="${meanCls}">${w.mean_pct >= 0 ? '+' : ''}${w.mean_pct}%</td>
        <td class="${medCls}">${w.median_pct >= 0 ? '+' : ''}${w.median_pct}%</td>
        <td>${(w.positive_rate * 100).toFixed(0)}%</td>
      </tr>`;
    }).join('');
    resEl.innerHTML = `
      <p style="color:var(--text-2);margin-bottom:8px">共 ${d.n_events} 个历史事件 · 基于 Yahoo 日线</p>
      <table>
        <thead><tr><th style="text-align:left">窗口</th><th>样本</th><th>均值</th><th>中位</th><th>上涨率</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `;
  } catch (e) {
    resEl.innerHTML = `<p class="empty-note">加载失败: ${e.message}</p>`;
  }
}

/* ---------- boot ---------- */
(async () => {
  await loadHistory();
  connectStream();
})();
