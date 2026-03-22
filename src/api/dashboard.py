"""
Web Dashboard: HTML search UI served by the API.
Access at http://localhost:8888/
"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Code Search Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}
.header{background:#161b22;border-bottom:1px solid #30363d;padding:16px 24px;display:flex;align-items:center;gap:16px}
.header h1{font-size:20px;color:#58a6ff}
.header .stats{font-size:13px;color:#8b949e;margin-left:auto}
.container{max-width:1200px;margin:0 auto;padding:24px}
.search-box{display:flex;gap:8px;margin-bottom:24px}
.search-box input{flex:1;padding:12px 16px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:16px;outline:none}
.search-box input:focus{border-color:#58a6ff}
.search-box button{padding:12px 24px;background:#238636;border:none;border-radius:6px;color:#fff;font-size:14px;cursor:pointer;font-weight:600}
.search-box button:hover{background:#2ea043}
.filters{display:flex;gap:8px;margin-bottom:16px}
.filters select,.filters input{padding:8px 12px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:13px}
.meta{font-size:13px;color:#8b949e;margin-bottom:16px}
.result{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:16px;margin-bottom:12px}
.result:hover{border-color:#58a6ff}
.result .title{color:#58a6ff;font-weight:600;margin-bottom:4px}
.result .path{color:#8b949e;font-size:13px;margin-bottom:8px}
.result .score{display:inline-block;padding:2px 8px;background:#1f6feb22;color:#58a6ff;border-radius:12px;font-size:12px}
.result pre{background:#0d1117;padding:12px;border-radius:4px;margin-top:8px;font-size:13px;overflow-x:auto;color:#c9d1d9;white-space:pre-wrap;max-height:200px;overflow-y:auto}
.tabs{display:flex;gap:0;margin-bottom:24px;border-bottom:1px solid #30363d}
.tab{padding:12px 20px;cursor:pointer;color:#8b949e;border-bottom:2px solid transparent;font-size:14px}
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
.empty{text-align:center;padding:60px;color:#484f58}
</style>
</head>
<body>
<div class="header">
<h1>&#128269; Code Search</h1>
<div class="stats" id="stats">Loading...</div>
</div>
<div class="container">
<div class="search-box">
<input type="text" id="query" placeholder="Search code... (e.g., reporting, error handling, redis)" autofocus>
<button onclick="doSearch()">Search</button>
</div>
<div class="filters">
<select id="repoFilter"><option value="">All repos</option></select>
<select id="langFilter"><option value="">All languages</option><option value="go">Go</option><option value="py">Python</option><option value="java">Java</option></select>
<input type="number" id="nResults" value="10" min="1" max="50" style="width:60px" title="Results">
</div>
<div class="tabs">
<div class="tab active" onclick="switchTab('search')">Search</div>
<div class="tab" onclick="switchTab('repos')">Repos</div>
<div class="tab" onclick="switchTab('deps')">Dependencies</div>
<div class="tab" onclick="switchTab('duplicates')">Duplicates</div>
<div class="tab" onclick="switchTab('debug')">Debug Error</div>
</div>
<div id="search-panel" class="panel active">
<div class="meta" id="searchMeta"></div>
<div id="results"></div>
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
<textarea id="errorText" rows="6" style="width:100%;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;padding:12px;font-family:monospace;font-size:13px;margin-bottom:12px" placeholder="Paste error/stack trace here..."></textarea>
<button onclick="debugError()" style="padding:8px 16px;background:#238636;border:none;border-radius:6px;color:#fff;cursor:pointer">Analyze Error</button>
<div id="debugResults" style="margin-top:16px"></div>
</div>
</div>
<script>
const API = '';
document.getElementById('query').addEventListener('keydown', e => { if(e.key==='Enter') doSearch() });
async function doSearch() {
  const q = document.getElementById('query').value;
  if(!q) return;
  const repo = document.getElementById('repoFilter').value;
  const lang = document.getElementById('langFilter').value;
  const n = document.getElementById('nResults').value;
  document.getElementById('results').innerHTML = '<div class="loading">Searching...</div>';
  let url = `${API}/api/search?q=${encodeURIComponent(q)}&n=${n}`;
  if(repo) url += `&repo=${repo}`;
  if(lang) url += `&lang=${lang}`;
  const res = await fetch(url).then(r=>r.json());
  document.getElementById('searchMeta').textContent = `${res.count} results in ${res.time_ms}ms`;
  if(!res.results||!res.results.length){document.getElementById('results').innerHTML='<div class="empty">No results</div>';return}
  document.getElementById('results').innerHTML = res.results.map((r,i) => `
    <div class="result">
      <div class="title">${i+1}. ${r.repo}/${r.file}</div>
      <div class="path"><span class="score">Score: ${r.score}</span> <span class="badge ${r.language==='go'?'go':'py'}">${r.language}</span></div>
      <pre>${escHtml(r.code_preview)}</pre>
    </div>`).join('');
}
async function loadRepos() {
  const res = await fetch(`${API}/api/repos`).then(r=>r.json());
  document.getElementById('stats').textContent = `${res.count} repos indexed`;
  const sel = document.getElementById('repoFilter');
  (res.repos||[]).forEach(r => { const o=document.createElement('option');o.value=r.name;o.textContent=r.name;sel.appendChild(o) });
  document.getElementById('reposList').innerHTML = (res.repos||[]).map(r => `
    <div class="card"><h3>${r.name}</h3><p>${r.chunks} chunks</p></div>`).join('');
}
async function loadDeps() {
  document.getElementById('depsResults').innerHTML = '<div class="loading">Scanning...</div>';
  const res = await fetch(`${API}/api/deps`).then(r=>r.json());
  let html = `<p style="margin-bottom:16px">${res.repos_scanned} repos, ${res.total_unique_deps} unique deps</p>`;
  html += '<h3 style="color:#58a6ff;margin-bottom:12px">Most Common Dependencies</h3>';
  (res.most_common_deps||[]).forEach(d => { html += `<div class="result"><b>${d.name}</b> — used by ${d.count} repos: ${d.used_by.join(', ')}</div>` });
  document.getElementById('depsResults').innerHTML = html;
}
async function loadDups() {
  document.getElementById('dupsResults').innerHTML = '<div class="loading">Analyzing...</div>';
  const res = await fetch(`${API}/api/duplicates`).then(r=>r.json());
  let html = `<p style="margin-bottom:16px">${res.count} duplicates found (threshold: ${res.threshold})</p>`;
  (res.duplicates||[]).forEach(d => { html += `<div class="result"><b>${d.similarity}% similar</b><br>${d.file_a}<br>↔ ${d.file_b}</div>` });
  document.getElementById('dupsResults').innerHTML = html || '<div class="empty">No duplicates</div>';
}
async function debugError() {
  const err = document.getElementById('errorText').value;
  if(!err) return;
  document.getElementById('debugResults').innerHTML = '<div class="loading">Analyzing...</div>';
  const res = await fetch(`${API}/api/debug-error`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({error:err})}).then(r=>r.json());
  let html = '<h3 style="color:#58a6ff;margin-bottom:12px">Analysis</h3>';
  if(res.extracted){html += `<div class="result"><b>Error:</b> ${res.extracted.error_message||'?'}<br><b>Functions:</b> ${(res.extracted.functions||[]).join(', ')}<br><b>Files:</b> ${(res.extracted.files||[]).join(', ')}</div>`}
  if(res.suggestions){html += '<h3 style="color:#58a6ff;margin:12px 0">Suggestions</h3>';res.suggestions.forEach(s=>{html+=`<div class="result">${s}</div>`})}
  if(res.relevant_code){html += '<h3 style="color:#58a6ff;margin:12px 0">Relevant Code</h3>';Object.entries(res.relevant_code).forEach(([k,v])=>{(v||[]).forEach(c=>{html+=`<div class="result"><b>${k}</b>: ${c.repo}/${c.file}<pre>${escHtml(c.preview)}</pre></div>`})})}
  if(res.ai_analysis){html += `<h3 style="color:#58a6ff;margin:12px 0">AI Analysis</h3><div class="result"><pre>${escHtml(res.ai_analysis)}</pre></div>`}
  document.getElementById('debugResults').innerHTML = html;
}
function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  event.target.classList.add('active');
  document.getElementById(name+'-panel').classList.add('active');
  if(name==='repos') loadRepos();
  if(name==='deps') loadDeps();
  if(name==='duplicates') loadDups();
}
function escHtml(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
loadRepos();
</script>
</body>
</html>"""
