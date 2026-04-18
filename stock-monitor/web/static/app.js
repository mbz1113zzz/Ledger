const feed = document.getElementById('feed');
const summary = document.getElementById('summary');
const notifToggle = document.getElementById('notif-toggle');
const impChecks = document.querySelectorAll('aside input[data-imp]');

notifToggle.checked = localStorage.getItem('notif') === '1';
notifToggle.addEventListener('change', async () => {
  localStorage.setItem('notif', notifToggle.checked ? '1' : '0');
  if (notifToggle.checked && Notification.permission !== 'granted') {
    await Notification.requestPermission();
  }
});

impChecks.forEach(cb => cb.addEventListener('change', applyFilter));

function applyFilter() {
  const enabled = new Set(
    Array.from(impChecks).filter(c => c.checked).map(c => c.dataset.imp)
  );
  document.querySelectorAll('.card').forEach(el => {
    el.style.display = enabled.has(el.dataset.imp) ? '' : 'none';
  });
}

function formatTime(iso) {
  const d = new Date(iso);
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 60) return '刚刚';
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`;
  return d.toLocaleDateString('zh-CN') + ' ' + d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

function renderCard(ev, isNew = false) {
  const el = document.createElement('div');
  el.className = `card ${ev.importance}${isNew ? ' new' : ''}`;
  el.dataset.imp = ev.importance;
  const dot = { high: '🔴', medium: '🟡', low: '🟢' }[ev.importance] || '⚪';
  const link = ev.url ? `<a href="${ev.url}" target="_blank">查看原文 ↗</a>` : '';
  el.innerHTML = `
    <h3>${dot} <strong>${ev.ticker}</strong> — ${escapeHtml(ev.title)}</h3>
    <div class="meta">${formatTime(ev.published_at)} · ${ev.source} · ${ev.event_type} ${link ? '· ' + link : ''}</div>
    ${ev.summary ? `<p class="summary">${escapeHtml(ev.summary)}</p>` : ''}
  `;
  if (isNew) setTimeout(() => el.classList.remove('new'), 2000);
  return el;
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

async function loadWatchlist() {
  const r = await fetch('/api/watchlist');
  const data = await r.json();
  document.getElementById('watchlist').innerHTML =
    data.tickers.map(t => `<li>${t}</li>`).join('');
}

async function loadHistory() {
  const r = await fetch('/api/events?limit=100');
  const data = await r.json();
  const highCount = data.events.filter(e => e.importance === 'high').length;
  summary.textContent = `今日 ${data.events.length} 条事件，其中 ${highCount} 条高重要性`;
  feed.innerHTML = '';
  data.events.forEach(e => feed.appendChild(renderCard(e)));
  applyFilter();
}

function connectStream() {
  const es = new EventSource('/stream');
  es.onmessage = (msg) => {
    const ev = JSON.parse(msg.data);
    feed.prepend(renderCard(ev, true));
    applyFilter();
    if (ev.importance === 'high' && notifToggle.checked
        && Notification.permission === 'granted') {
      new Notification(`${ev.ticker}: ${ev.title}`, { body: ev.summary || '' });
    }
  };
  es.onerror = () => {
    console.warn('SSE disconnected, will reconnect');
  };
}

(async () => {
  await loadWatchlist();
  await loadHistory();
  connectStream();
})();
