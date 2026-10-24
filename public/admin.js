const $ = id => document.getElementById(id);
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c]);
const post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });

function show(admin) {
  $('login').hidden = admin; $('dash').hidden = !admin; $('logout').hidden = !admin;
  if (admin) { loadList(); loadQueue(); }
}

async function loadList() {
  const titles = await (await fetch('/api/titles')).json();
  $('list').innerHTML = titles.length ? titles.map(t => `<tr>
    <td><img src="${esc(t.thumbnail || '')}" alt=""></td>
    <td>${esc(t.title)}</td><td>${esc(t.type)}</td><td>${esc(t.category)}</td>
    <td><button class="del" data-id="${esc(t.id)}">Remove</button></td></tr>`).join('')
    : '<tr><td colspan="5" class="note">No titles yet.</td></tr>';
  document.querySelectorAll('.del').forEach(b => b.onclick = async () => {
    if (!confirm('Remove this title?')) return;
    await fetch('/api/titles/' + b.dataset.id, { method: 'DELETE' });
    loadList();
  });
}

// ---------- TMDB discovery + review queue ----------
const api = async (url, opts) => {
  const r = await fetch(url, opts);
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || 'Request failed');
  return data;
};
const ytSearch = c => 'https://www.youtube.com/results?search_query=' +
  encodeURIComponent(`${c.title} ${c.year || ''} ${c.type === 'series' ? 'full episodes' : 'full movie'}`) + '&sp=EgIQAQ%253D%253D';
let results = [];
let tpage = 1, tTotal = 0;
let tquery = { q: '', type: 'movie' }; // the search being paged, so editing the box doesn't change it mid-browse

async function tmdbSearch(page = 1) {
  const msg = $('t-msg');
  if (page === 1) tquery = { q: $('tq').value, type: $('ttype').value };
  msg.className = 'msg'; msg.textContent = 'Searching...';
  try {
    const data = await api(`/api/admin/tmdb/search?q=${encodeURIComponent(tquery.q)}&type=${tquery.type}&page=${page}`);
    results = data.results;
    tpage = data.page; tTotal = data.totalPages;
    $('tpager').hidden = tTotal <= 1;
    $('tpage').textContent = `Page ${tpage} of ${tTotal} (${data.totalResults} results)`;
    $('tprev').disabled = tpage <= 1;
    $('tnext').disabled = tpage >= tTotal;
    msg.textContent = results.length ? '' : 'No results.';
    $('tresults').innerHTML = results.map((c, i) => `<div class="card">
      <img src="${esc(c.poster || '')}" alt="">
      <div class="info"><div class="t">${esc(c.title)}</div><div class="m">${esc(c.year || '')}</div>
      <button class="btn" data-i="${i}">Shortlist</button></div></div>`).join('');
    document.querySelectorAll('#tresults .btn').forEach(b => b.onclick = async () => {
      try { await api('/api/admin/candidates', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(results[b.dataset.i]) });
        b.textContent = 'Shortlisted'; b.disabled = true; loadQueue(); }
      catch (e) { b.textContent = e.message; b.disabled = true; }
    });
  } catch (e) { msg.className = 'msg err'; msg.textContent = e.message; }
}
$('tsearch').onclick = () => tmdbSearch(1);
$('tq').onkeydown = e => { if (e.key === 'Enter') tmdbSearch(1); };
$('tprev').onclick = () => { tmdbSearch(tpage - 1); $('tresults').scrollIntoView({ behavior: 'smooth' }); };
$('tnext').onclick = () => { tmdbSearch(tpage + 1); $('tresults').scrollIntoView({ behavior: 'smooth' }); };

async function loadQueue() {
  const cands = await api('/api/admin/candidates');
  $('qcount').textContent = cands.length ? `(${cands.length})` : '';
  $('queue').innerHTML = cands.length ? cands.map(c => `<div class="qitem" data-id="${esc(c.id)}">
    <img src="${esc(c.poster || '')}" alt="">
    <div class="body"><strong>${esc(c.title)}</strong> <span class="note">${esc(c.type)} · ${esc(c.year || '')}</span>
      <p>${esc(c.description)}</p>
      <a class="yt" href="${esc(ytSearch(c))}" target="_blank" rel="noopener">1. Search YouTube for this &#8599;</a>
      <div class="row2" style="margin-top:8px">
        <input class="q-url" placeholder="2. Paste the free YouTube link">
        <input class="q-cat" placeholder="Category" value="General" style="max-width:130px;flex:none;min-width:0">
        <button class="btn red q-ok">Approve &amp; publish</button>
        <button class="del q-no">Reject</button>
      </div>
      <div class="msg q-msg"></div></div></div>`).join('')
    : '<p class="note">Nothing waiting. Shortlist titles from the search above.</p>';
  document.querySelectorAll('.qitem').forEach(el => {
    const id = el.dataset.id, msg = el.querySelector('.q-msg');
    el.querySelector('.q-ok').onclick = async () => {
      try {
        await api(`/api/admin/candidates/${id}/approve`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: el.querySelector('.q-url').value, category: el.querySelector('.q-cat').value }) });
        loadQueue(); loadList();
      } catch (e) { msg.className = 'msg q-msg err'; msg.textContent = e.message; }
    };
    el.querySelector('.q-no').onclick = async () => { await fetch('/api/admin/candidates/' + id, { method: 'DELETE' }); loadQueue(); };
  });
}

async function login() {
  const r = await post('/api/admin/login', { password: $('pw').value });
  if (r.ok) { $('pw').value = ''; $('login-msg').textContent = ''; show(true); }
  else $('login-msg').textContent = (await r.json()).error;
}
$('login-btn').onclick = login;
$('pw').onkeydown = e => { if (e.key === 'Enter') login(); };
$('logout').onclick = async e => { e.preventDefault(); await post('/api/admin/logout'); show(false); };

$('add').onclick = async () => {
  const msg = $('add-msg');
  msg.className = 'msg'; msg.textContent = 'Adding...';
  const r = await post('/api/titles', {
    url: $('url').value, type: $('type').value, category: $('category').value,
    year: $('year').value, title: $('title').value, description: $('description').value
  });
  const data = await r.json();
  if (r.ok) {
    msg.className = 'msg ok'; msg.textContent = `Added "${data.title}"`;
    ['url', 'year', 'title', 'description'].forEach(id => $(id).value = '');
    loadList();
  } else { msg.className = 'msg err'; msg.textContent = data.error; }
};

fetch('/api/admin/me').then(r => r.json()).then(d => show(d.admin));
