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

/* ---------- boot ---------- */
(async () => {
  await loadHistory();
  connectStream();
})();
