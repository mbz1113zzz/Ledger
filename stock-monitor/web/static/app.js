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
let paperCache = { positions: [], trades: [], equity: [] };
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
  renderPaperPanel();
}

function money(n) {
  const sign = n > 0 ? '+' : '';
  return `${sign}$${Number(n || 0).toFixed(2)}`;
}

function renderPaperPanel() {
  const statsEl = document.getElementById('paper-stats');
  const positionsEl = document.getElementById('paper-positions');
  if (!statsEl || !positionsEl) return;
  const equity = Number(paperCache.equity || 0);
  const cash = Number(paperCache.cash || 0);
  const positions = paperCache.positions || [];
  const unrealized = positions.reduce((sum, p) => sum + Number(p.unrealized_pnl || 0), 0);
  statsEl.innerHTML = `
    <div class="paper-metric"><span>Equity</span><strong>${money(equity).replace('+', '')}</strong></div>
    <div class="paper-metric"><span>Cash</span><strong>${money(cash).replace('+', '')}</strong></div>
    <div class="paper-metric"><span>U-PnL</span><strong class="${unrealized >= 0 ? 'pos' : 'neg'}">${money(unrealized)}</strong></div>
  `;
  if (!positions.length) {
    positionsEl.innerHTML = '<div class="paper-empty">当前无持仓</div>';
    return;
  }
  positionsEl.innerHTML = positions.map(p => `
    <div class="paper-pos">
      <div class="paper-pos-head">
        <span class="ticker">${escapeHtml(p.ticker)}</span>
        <span class="paper-side ${p.side === 'short' ? 'short' : 'long'}">${p.side === 'short' ? 'SHORT' : 'LONG'}</span>
        <span class="${Number(p.unrealized_pnl) >= 0 ? 'pos' : 'neg'}">${money(p.unrealized_pnl)}</span>
      </div>
      <div class="paper-pos-meta">
        ${p.side === 'short' ? '-' : '+'}${p.qty} 股 · 入场 ${Number(p.entry_price).toFixed(2)} · 现价 ${Number(p.mark_price).toFixed(2)}
      </div>
      <div class="paper-pos-meta">
        SL ${Number(p.sl).toFixed(2)} · TP ${Number(p.tp).toFixed(2)} · ${escapeHtml(p.reason)}
      </div>
    </div>
  `).join('');
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

async function loadPaper() {
  try {
    const r = await fetch('/api/paper/positions');
    const data = await r.json();
    paperCache = data;
    renderPaperPanel();
  } catch (e) { /* silent */ }
}

async function loadHistory() {
  const r = await fetch('/api/events?limit=500');
  const data = await r.json();
  allEvents = data.events;
  render();
  await loadWatchlist();
}

function appendStructureBadge(s) {
  const div = document.createElement('div');
  div.className = 'struct-badge struct-' + s.kind;
  const t = new Date(s.ts).toLocaleTimeString('zh-CN',
    { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const price = typeof s.price === 'number' ? s.price.toFixed(2) : s.price;
  div.textContent = `${t} · ${s.ticker} ${s.tf} · ${String(s.kind).toUpperCase()} @ ${price}`;
  feed.prepend(div);
}

async function openPaperTrades() {
  openModal('成交记录', '<p class="empty-note">加载中…</p>');
  try {
    const r = await fetch('/api/paper/trades?limit=100');
    const d = await r.json();
    if (!d.trades.length) {
      openModal('成交记录', '<p class="empty-note">暂无成交记录</p>');
      return;
    }
    const rows = d.trades.map(t => `
      <tr>
        <td class="win">${new Date(t.ts).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</td>
        <td>${escapeHtml(t.ticker)}</td>
        <td>${escapeHtml(t.side)}</td>
        <td>${t.qty}</td>
        <td>${Number(t.price).toFixed(2)}</td>
        <td>${escapeHtml(t.reason)}</td>
        <td class="${Number(t.pnl || 0) >= 0 ? 'pos' : 'neg'}">${t.pnl == null ? '' : money(t.pnl)}</td>
      </tr>
    `).join('');
    openModal('成交记录', `
      <table>
        <thead><tr><th style="text-align:left">时间</th><th>票</th><th>方向</th><th>qty</th><th>价格</th><th>原因</th><th>PnL</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `);
  } catch (e) {
    openModal('成交记录', `<p class="empty-note">加载失败: ${e.message}</p>`);
  }
}

async function openPaperEquity() {
  openModal('权益快照', '<p class="empty-note">加载中…</p>');
  try {
    const r = await fetch('/api/paper/equity?limit=50');
    const d = await r.json();
    if (!d.equity.length) {
      openModal('权益快照', '<p class="empty-note">暂无权益快照</p>');
      return;
    }
    const rows = d.equity.map(t => `
      <tr>
        <td class="win">${new Date(t.ts).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</td>
        <td>${Number(t.cash).toFixed(2)}</td>
        <td>${Number(t.positions_value).toFixed(2)}</td>
        <td>${Number(t.equity).toFixed(2)}</td>
      </tr>
    `).join('');
    openModal('权益快照', `
      <table>
        <thead><tr><th style="text-align:left">时间</th><th>Cash</th><th>持仓市值</th><th>Equity</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `);
  } catch (e) {
    openModal('权益快照', `<p class="empty-note">加载失败: ${e.message}</p>`);
  }
}

async function openPaperReview() {
  openModal('每日复盘', '<p class="empty-note">加载中…</p>');
  try {
    const r = await fetch('/api/paper/review');
    const d = await r.json();
    openModal('每日复盘', `
      <p style="color:var(--text-2);margin-bottom:12px">${escapeHtml(d.title)}</p>
      <pre>${escapeHtml(d.body)}</pre>
    `);
  } catch (e) {
    openModal('每日复盘', `<p class="empty-note">加载失败: ${e.message}</p>`);
  }
}

async function openPaperStats() {
  openModal('胜率面板', '<p class="empty-note">加载中…</p>');
  try {
    const r = await fetch('/api/paper/stats');
    const d = await r.json();
    if (!d.rows.length) {
      openModal('胜率面板', '<p class="empty-note">暂无历史样本</p>');
      return;
    }
    const rows = d.rows.map(row => `
      <tr>
        <td class="win">${escapeHtml(row.ticker)}</td>
        <td>${escapeHtml(row.setup)}</td>
        <td>${row.entries}</td>
        <td>${row.closed}</td>
        <td>${row.win_rate_pct.toFixed(0)}%</td>
        <td class="${Number(row.avg_rr) >= 0 ? 'pos' : 'neg'}">${Number(row.avg_rr).toFixed(2)}</td>
        <td class="${Number(row.avg_pnl) >= 0 ? 'pos' : 'neg'}">${money(row.avg_pnl)}</td>
      </tr>
    `).join('');
    openModal('胜率面板', `
      <table>
        <thead><tr><th style="text-align:left">Ticker</th><th>Setup</th><th>入场</th><th>已平</th><th>胜率</th><th>平均 RR</th><th>平均 PnL</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    `);
  } catch (e) {
    openModal('胜率面板', `<p class="empty-note">加载失败: ${e.message}</p>`);
  }
}

/* ---------- SSE ---------- */
function connectStream() {
  const es = new EventSource('/stream');
  es.onopen = () => connDot.classList.remove('bad');
  es.onmessage = (msg) => {
    const data = JSON.parse(msg.data);
    if (data.type === 'structure') {
      appendStructureBadge(data);
      return;
    }
    const ev = data;
    allEvents.unshift(ev);
    if (allEvents.length > MAX_EVENTS) allEvents.length = MAX_EVENTS;
    render();
    if (ev.event_type === 'smc_entry') loadPaper();
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
document.getElementById('btn-paper-trades').addEventListener('click', openPaperTrades);
document.getElementById('btn-paper-equity').addEventListener('click', openPaperEquity);
document.getElementById('btn-paper-review').addEventListener('click', openPaperReview);
document.getElementById('btn-paper-stats').addEventListener('click', openPaperStats);

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

/* ---------- sources health ---------- */
async function loadHealth() {
  try {
    const r = await fetch('/api/health');
    const d = await r.json();
    renderSources(d);
  } catch (e) { /* silent */ }
}

function renderSources(d) {
  const ul = document.getElementById('sources-list');
  const dotClass = (status) => {
    if (status === 'ok') return 'ok';
    if (status === 'permission_denied') return 'warn';
    return 'disabled';
  };
  const label = (status, detail) => {
    if (status === 'permission_denied') return detail ? `403 / tier` : 'tier';
    if (status === 'client_error') return detail ? `${detail}` : '4xx';
    if (status === 'disabled') return 'off';
    return '';
  };
  ul.innerHTML = (d.sources || []).map(s => `
    <li>
      <span class="dot ${dotClass(s.status)}"></span>
      <span>${s.name}</span>
      ${label(s.status, s.detail) ? `<span class="src-status">${label(s.status, s.detail)}</span>` : ''}
      <span class="group">${s.group}</span>
    </li>
  `).join('');
  const meta = document.getElementById('sources-meta');
  const channels = ['telegram', 'bark', 'feishu'].map(n => {
    const on = (d.push_channels || []).includes(n);
    return `<span class="${on ? 'ch' : 'ch-off'}">${n}${on ? '✓' : '✗'}</span>`;
  }).join(' ');
  const enr = d.enricher_enabled ? '<span class="ch">LLM✓</span>' : '<span class="ch-off">LLM✗</span>';
  let lastLine = '';
  if (d.last_news_run) {
    const mins = Math.floor((Date.now() - new Date(d.last_news_run).getTime()) / 60000);
    lastLine = `上次 news: ${mins}m 前 (+${d.last_news_inserted})`;
  }
  const startup = d.startup_sync_running ? '<span class="ch">BOOT✓</span>' : '<span class="ch-off">BOOT·</span>';
  meta.innerHTML = `${channels}<br>${enr} ${startup}<br>${lastLine}`;
}

/* ---------- boot ---------- */
(async () => {
  await loadHistory();
  await loadPaper();
  await loadHealth();
  setInterval(loadHealth, 30000);
  setInterval(loadPaper, 30000);
  connectStream();
})();
