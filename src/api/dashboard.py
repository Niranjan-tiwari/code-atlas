"""
Web dashboard: search + RAG "Ask" console with thread tabs and local history.

Served at http://localhost:8888/ by search_api.

Persistence: threads and messages are stored in the browser (localStorage only).
For team-wide history later, add API + DB (see docs/QUERY_CONSOLE_AND_SCALE.md).
"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Code Atlas — Search & Ask</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}
.header{background:#161b22;border-bottom:1px solid #30363d;padding:16px 24px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.header h1{font-size:20px;color:#58a6ff}
.header .stats{font-size:13px;color:#8b949e;margin-left:auto}
.container{max-width:1280px;margin:0 auto;padding:24px}
.search-box{display:flex;gap:8px;margin-bottom:24px}
.search-box input{flex:1;padding:12px 16px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:16px;outline:none}
.search-box input:focus{border-color:#58a6ff}
.search-box button,.btn-primary{padding:12px 20px;background:#238636;border:none;border-radius:6px;color:#fff;font-size:14px;cursor:pointer;font-weight:600}
.search-box button:hover,.btn-primary:hover{background:#2ea043}
.btn-ghost{padding:8px 14px;background:#21262d;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:13px;cursor:pointer}
.btn-ghost:hover{border-color:#58a6ff;color:#58a6ff}
.btn-danger{padding:8px 14px;background:transparent;border:1px solid #f85149;color:#f85149;border-radius:6px;font-size:12px;cursor:pointer}
.btn-danger:hover{background:#f8514922}
.filters{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.filters select,.filters input{padding:8px 12px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:13px}
.meta{font-size:13px;color:#8b949e;margin-bottom:16px}
.result{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:16px;margin-bottom:12px}
.result:hover{border-color:#58a6ff}
.result .title{color:#58a6ff;font-weight:600;margin-bottom:4px}
.result .path{color:#8b949e;font-size:13px;margin-bottom:8px}
.result .score{display:inline-block;padding:2px 8px;background:#1f6feb22;color:#58a6ff;border-radius:12px;font-size:12px}
.result pre{background:#0d1117;padding:12px;border-radius:4px;margin-top:8px;font-size:13px;overflow-x:auto;color:#c9d1d9;white-space:pre-wrap;max-height:200px;overflow-y:auto}
.tabs{display:flex;gap:0;margin-bottom:20px;border-bottom:1px solid #30363d;flex-wrap:wrap}
.tab{padding:12px 18px;cursor:pointer;color:#8b949e;border-bottom:2px solid transparent;font-size:14px}
.tab.active{color:#58a6ff;border-bottom-color:#58a6ff}
.tab:hover{color:#c9d1d9}
.panel{display:none}.panel.active{display:block}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.card{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:16px}
.card h3{color:#58a6ff;font-size:14px;margin-bottom:8px}
.card p{color:#8b949e;font-size:13px}
.loading{text-align:center;padding:40px;color:#8b949e}
.badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;margin:2px}
.badge.go{background:#00add822;color:#00add8}.badge.py{background:#3572A522;color:#3572A5}
.empty{text-align:center;padding:48px;color:#484f58;font-size:14px}
.hint{font-size:12px;color:#484f58;margin-top:8px;line-height:1.5}
/* Ask console */
.ask-toolbar{display:flex;gap:10px;align-items:center;margin-bottom:12px;flex-wrap:wrap}
.thread-row{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-bottom:14px;padding:8px 0;border-bottom:1px solid #30363d;min-height:44px}
.thread-pill{padding:6px 12px;border-radius:20px;font-size:12px;cursor:pointer;background:#21262d;border:1px solid #30363d;color:#8b949e;max-width:200px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.thread-pill:hover{border-color:#58a6ff;color:#c9d1d9}
.thread-pill.active{background:#1f6feb22;border-color:#58a6ff;color:#58a6ff}
.ask-messages{display:flex;flex-direction:column;gap:12px;min-height:280px;max-height:55vh;overflow-y:auto;margin-bottom:16px;padding:4px}
.msg{border-radius:8px;padding:14px 16px;font-size:14px;line-height:1.55;border:1px solid #30363d}
.msg.user{background:#1c2128;margin-left:48px;border-color:#388bfd44}
.msg.asst{background:#161b22;margin-right:32px}
.msg .role{font-size:11px;text-transform:uppercase;color:#8b949e;margin-bottom:8px;letter-spacing:.04em}
.msg pre,.msg .body{white-space:pre-wrap;word-break:break-word}
.msg .src{margin-top:12px;padding-top:12px;border-top:1px solid #30363d;font-size:12px;color:#8b949e}
.msg .src a{color:#58a6ff}
.ask-input-row{display:flex;gap:10px;align-items:flex-end}
.ask-input-row textarea{flex:1;padding:12px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:14px;resize:vertical;min-height:72px;font-family:inherit}
.ask-input-row textarea:focus{outline:none;border-color:#58a6ff}
</style>
</head>
<body>
<div class="header">
<h1>Code Atlas</h1>
<div class="stats" id="stats">Loading...</div>
</div>
<div class="container">
<div class="search-box">
<input type="text" id="query" placeholder="Keyword search (no LLM)..." autofocus>
<button type="button" onclick="doSearch()">Search</button>
</div>
<div class="filters">
<select id="repoFilter"><option value="">All repos</option></select>
<select id="langFilter"><option value="">All languages</option><option value="go">Go</option><option value="py">Python</option><option value="java">Java</option></select>
<input type="number" id="nResults" value="10" min="1" max="50" style="width:64px" title="Results">
</div>
<div class="tabs" id="mainTabs">
<button type="button" class="tab active" data-tab="search" onclick="switchTab(this)">Search</button>
<button type="button" class="tab" data-tab="ask" onclick="switchTab(this)">Ask (RAG)</button>
<button type="button" class="tab" data-tab="repos" onclick="switchTab(this)">Repos</button>
<button type="button" class="tab" data-tab="deps" onclick="switchTab(this)">Dependencies</button>
<button type="button" class="tab" data-tab="duplicates" onclick="switchTab(this)">Duplicates</button>
<button type="button" class="tab" data-tab="debug" onclick="switchTab(this)">Debug error</button>
</div>

<div id="search-panel" class="panel active">
<div class="meta" id="searchMeta"></div>
<div id="results"></div>
</div>

<div id="ask-panel" class="panel">
<p class="meta">Natural-language questions use the same RAG + LLM stack as <code>scripts/query_code.py</code>. <strong>Thread tabs</strong> keep your past Q&amp;A in this browser; each request is independent on the server (no cross-user mixing). Use the CLI for multi-turn server-side context in a private session.</p>
<div class="ask-toolbar">
<label style="font-size:13px;color:#8b949e">Repo</label>
<select id="askRepoFilter" style="min-width:160px"><option value="">All repos</option></select>
<button type="button" class="btn-ghost" onclick="newThread()">New chat</button>
<button type="button" class="btn-ghost" onclick="exportThreads()">Export JSON</button>
<label class="btn-ghost" style="cursor:pointer;margin:0">Import<input type="file" accept="application/json" style="display:none" id="importFile" onchange="importThreads(event)"></label>
<button type="button" class="btn-danger" onclick="clearAllThreads()">Clear saved</button>
</div>
<div class="thread-row" id="threadRow"></div>
<div class="ask-messages" id="askMessages"></div>
<div class="ask-input-row">
<textarea id="askInput" placeholder="e.g. How does authentication flow through the API?"></textarea>
<button type="button" class="btn-primary" onclick="sendAsk()" id="askSendBtn">Send</button>
</div>
<p class="hint">Server runs one query at a time on embedded Qdrant (safe for concurrent browsers; second request waits). For many users at scale, run a Qdrant server — see docs/QUERY_CONSOLE_AND_SCALE.md.</p>
</div>

<div id="repos-panel" class="panel">
<div id="reposList" class="grid"></div>
</div>
<div id="deps-panel" class="panel">
<div id="depsResults"></div>
</div>
<div id="duplicates-panel" class="panel">
<div id="dupsResults"></div>
</div>
<div id="debug-panel" class="panel">
<textarea id="errorText" rows="6" style="width:100%;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;padding:12px;font-family:monospace;font-size:13px;margin-bottom:12px" placeholder="Paste error or stack trace..."></textarea>
<button type="button" class="btn-primary" onclick="debugError()">Analyze</button>
<div id="debugResults" style="margin-top:16px"></div>
</div>
</div>
<script>
const API = '';
const LS_KEY = 'codeAtlasAskConsole_v1';
const MAX_THREADS = 24;
const MAX_MSGS = 80;

function loadState() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return defaultState();
    const s = JSON.parse(raw);
    if (!s.threads || !Array.isArray(s.threads)) return defaultState();
    return {
      threads: s.threads.slice(0, MAX_THREADS),
      activeId: s.activeId || (s.threads[0] && s.threads[0].id) || null
    };
  } catch (e) { return defaultState(); }
}
function defaultState() {
  const id = uid();
  return {
    threads: [{ id, title: 'Chat 1', updated: Date.now(), messages: [] }],
    activeId: id
  };
}
function uid() { return 't_' + Math.random().toString(36).slice(2, 12) + '_' + Date.now().toString(36); }
function saveState(state) {
  state.threads = state.threads.slice(0, MAX_THREADS);
  state.threads.forEach(t => { t.messages = (t.messages || []).slice(-MAX_MSGS); });
  localStorage.setItem(LS_KEY, JSON.stringify(state));
}
let state = loadState();

document.getElementById('query').addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
document.getElementById('askInput').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendAsk(); }
});

function escHtml(s) {
  return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function switchTab(el) {
  const name = el.dataset.tab;
  document.querySelectorAll('#mainTabs .tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  const panel = document.getElementById(name + '-panel');
  if (panel) panel.classList.add('active');
  if (name === 'repos') loadRepos();
  if (name === 'deps') loadDeps();
  if (name === 'duplicates') loadDups();
  if (name === 'ask') { syncAskRepoFilter(); renderAskUI(); }
}

function activeThread() {
  return state.threads.find(t => t.id === state.activeId) || state.threads[0];
}

function renderThreadRow() {
  const row = document.getElementById('threadRow');
  row.innerHTML = state.threads.map(t => {
    const active = t.id === state.activeId ? ' active' : '';
    const title = escHtml(t.title || 'Untitled');
    return '<button type="button" class="thread-pill' + active + '" data-id="' + escHtml(t.id) + '" onclick="selectThread(this.dataset.id)">' + title + '</button>';
  }).join('');
}

function selectThread(id) {
  state.activeId = id;
  saveState(state);
  renderAskUI();
}

function newThread() {
  const id = uid();
  state.threads.unshift({ id, title: 'Chat ' + (state.threads.length + 1), updated: Date.now(), messages: [] });
  state.activeId = id;
  saveState(state);
  renderAskUI();
}

function clearAllThreads() {
  if (!confirm('Delete all saved Ask history in this browser?')) return;
  state = defaultState();
  saveState(state);
  renderAskUI();
}

function exportThreads() {
  const blob = new Blob([JSON.stringify(state, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'code-atlas-ask-threads.json';
  a.click();
  URL.revokeObjectURL(a.href);
}

function importThreads(ev) {
  const f = ev.target.files[0];
  if (!f) return;
  const r = new FileReader();
  r.onload = () => {
    try {
      const o = JSON.parse(r.result);
      if (o.threads && Array.isArray(o.threads)) {
        state = { threads: o.threads.slice(0, MAX_THREADS), activeId: o.activeId || o.threads[0].id };
        saveState(state);
        renderAskUI();
      }
    } catch (e) { alert('Invalid JSON'); }
    ev.target.value = '';
  };
  r.readAsText(f);
}

function renderMessages() {
  const th = activeThread();
  const box = document.getElementById('askMessages');
  if (!th.messages.length) {
    box.innerHTML = '<div class="empty">Ask a question to start this thread. Use <strong>New chat</strong> for a separate tab of history.</div>';
    return;
  }
  box.innerHTML = th.messages.map(m => {
    if (m.role === 'user') {
      return '<div class="msg user"><div class="role">You</div><div class="body">' + escHtml(m.text) + '</div></div>';
    }
    let src = '';
    if (m.sources && m.sources.length) {
      src = '<div class="src">Sources: ' + m.sources.slice(0, 8).map((s, i) => {
        const repo = escHtml(s.repo || '');
        const file = escHtml(s.file || '');
        return '<span>[' + (i+1) + '] ' + repo + '/' + file + '</span>';
      }).join(' · ') + '</div>';
    }
    const bits = [];
    if (m.provider) bits.push(escHtml(m.provider));
    if (m.model) bits.push(escHtml(m.model));
    if (m.tokens) bits.push(m.tokens + ' tok');
    if (m.cache_hit) bits.push('cache:' + escHtml(m.cache_hit));
    const meta = bits.length ? '<div class="role">' + bits.join(' · ') + '</div>' : '';
    return '<div class="msg asst">' + meta + '<div class="body">' + escHtml(m.text) + '</div>' + src + '</div>';
  }).join('');
  box.scrollTop = box.scrollHeight;
}

function renderAskUI() {
  renderThreadRow();
  renderMessages();
}

async function sendAsk() {
  const input = document.getElementById('askInput');
  const q = (input.value || '').trim();
  if (!q) return;
  const th = activeThread();
  const repo = document.getElementById('askRepoFilter').value || null;
  th.messages.push({ role: 'user', text: q, ts: Date.now() });
  if (th.title.startsWith('Chat ') && th.messages.length === 1) th.title = q.slice(0, 42) + (q.length > 42 ? '…' : '');
  th.updated = Date.now();
  input.value = '';
  saveState(state);
  renderAskUI();

  const btn = document.getElementById('askSendBtn');
  btn.disabled = true;
  try {
    const body = { query: q, include_history: false };
    if (repo) body.repo = repo;
    const res = await fetch(API + '/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || res.statusText);
    th.messages.push({
      role: 'assistant',
      text: data.answer || '',
      sources: data.sources || [],
      model: data.model || '',
      provider: data.provider || '',
      tokens: data.tokens,
      cache_hit: data.cache_hit || '',
      ts: Date.now()
    });
    th.updated = Date.now();
    saveState(state);
    renderAskUI();
  } catch (e) {
    th.messages.push({ role: 'assistant', text: 'Error: ' + e.message, ts: Date.now() });
    saveState(state);
    renderAskUI();
  } finally {
    btn.disabled = false;
  }
}

function syncAskRepoFilter() {
  const src = document.getElementById('repoFilter');
  const dst = document.getElementById('askRepoFilter');
  const cur = dst.value;
  dst.innerHTML = '<option value="">All repos</option>';
  Array.from(src.options).forEach(o => {
    if (!o.value) return;
    const n = document.createElement('option');
    n.value = o.value;
    n.textContent = o.textContent;
    dst.appendChild(n);
  });
  dst.value = cur;
}

async function doSearch() {
  const q = document.getElementById('query').value;
  if (!q) return;
  const repo = document.getElementById('repoFilter').value;
  const lang = document.getElementById('langFilter').value;
  const n = document.getElementById('nResults').value;
  document.getElementById('results').innerHTML = '<div class="loading">Searching…</div>';
  let url = API + '/api/search?q=' + encodeURIComponent(q) + '&n=' + n;
  if (repo) url += '&repo=' + encodeURIComponent(repo);
  if (lang) url += '&lang=' + encodeURIComponent(lang);
  const res = await fetch(url).then(r => r.json());
  document.getElementById('searchMeta').textContent = res.count + ' results in ' + res.time_ms + 'ms';
  if (!res.results || !res.results.length) {
    document.getElementById('results').innerHTML = '<div class="empty">No results</div>';
    return;
  }
  document.getElementById('results').innerHTML = res.results.map((r, i) => {
    const badge = r.language === 'go' ? 'go' : 'py';
    return '<div class="result"><div class="title">' + (i+1) + '. ' + escHtml(r.repo) + '/' + escHtml(r.file) + '</div>' +
      '<div class="path"><span class="score">Score: ' + r.score + '</span> <span class="badge ' + badge + '">' + escHtml(r.language) + '</span></div>' +
      '<pre>' + escHtml(r.code_preview) + '</pre></div>';
  }).join('');
}

async function loadRepos() {
  const res = await fetch(API + '/api/repos').then(r => r.json());
  document.getElementById('stats').textContent = res.count + ' repos indexed';
  const sel = document.getElementById('repoFilter');
  while (sel.options.length > 1) sel.remove(1);
  (res.repos || []).forEach(r => {
    const o = document.createElement('option');
    o.value = r.name;
    o.textContent = r.name;
    sel.appendChild(o);
  });
  document.getElementById('reposList').innerHTML = (res.repos || []).map(r =>
    '<div class="card"><h3>' + escHtml(r.name) + '</h3><p>' + r.chunks + ' chunks</p></div>'
  ).join('');
  syncAskRepoFilter();
}

async function loadDeps() {
  document.getElementById('depsResults').innerHTML = '<div class="loading">Scanning…</div>';
  const res = await fetch(API + '/api/deps').then(r => r.json());
  let html = '<p style="margin-bottom:16px">' + res.repos_scanned + ' repos, ' + res.total_unique_deps + ' unique deps</p>';
  html += '<h3 style="color:#58a6ff;margin-bottom:12px">Most common</h3>';
  (res.most_common_deps || []).forEach(d => {
    html += '<div class="result"><b>' + escHtml(d.name) + '</b> — used by ' + d.count + ' repos: ' + escHtml(d.used_by.join(', ')) + '</div>';
  });
  document.getElementById('depsResults').innerHTML = html;
}

async function loadDups() {
  document.getElementById('dupsResults').innerHTML = '<div class="loading">Analyzing…</div>';
  const res = await fetch(API + '/api/duplicates').then(r => r.json());
  let html = '<p style="margin-bottom:16px">' + res.count + ' duplicates (threshold: ' + res.threshold + ')</p>';
  (res.duplicates || []).forEach(d => {
    html += '<div class="result"><b>' + d.similarity + '% similar</b><br>' + escHtml(d.file_a) + '<br>↔ ' + escHtml(d.file_b) + '</div>';
  });
  document.getElementById('dupsResults').innerHTML = html || '<div class="empty">No duplicates</div>';
}

async function debugError() {
  const err = document.getElementById('errorText').value;
  if (!err) return;
  document.getElementById('debugResults').innerHTML = '<div class="loading">Analyzing…</div>';
  const res = await fetch(API + '/api/debug-error', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ error: err })
  }).then(r => r.json());
  let html = '<h3 style="color:#58a6ff;margin-bottom:12px">Analysis</h3>';
  if (res.extracted) {
    html += '<div class="result"><b>Error:</b> ' + escHtml(res.extracted.error_message || '?') +
      '<br><b>Functions:</b> ' + escHtml((res.extracted.functions || []).join(', ')) +
      '<br><b>Files:</b> ' + escHtml((res.extracted.files || []).join(', ')) + '</div>';
  }
  if (res.suggestions) {
    html += '<h3 style="color:#58a6ff;margin:12px 0">Suggestions</h3>';
    res.suggestions.forEach(s => { html += '<div class="result">' + escHtml(s) + '</div>'; });
  }
  if (res.relevant_code) {
    html += '<h3 style="color:#58a6ff;margin:12px 0">Relevant code</h3>';
    Object.entries(res.relevant_code).forEach(([k, v]) => {
      (v || []).forEach(c => {
        html += '<div class="result"><b>' + escHtml(k) + '</b>: ' + escHtml(c.repo) + '/' + escHtml(c.file) +
          '<pre>' + escHtml(c.preview) + '</pre></div>';
      });
    });
  }
  if (res.ai_analysis) {
    html += '<h3 style="color:#58a6ff;margin:12px 0">AI</h3><div class="result"><pre>' + escHtml(res.ai_analysis) + '</pre></div>';
  }
  document.getElementById('debugResults').innerHTML = html;
}

loadRepos();
renderAskUI();
</script>
</body>
</html>"""
