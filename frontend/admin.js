const $ = id => document.getElementById(id);
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c]);
const post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });

function show(admin) {
  $('login').hidden = admin; $('dash').hidden = !admin; $('logout').hidden = !admin;
  if (admin) { loadList(); loadQueue(); }
}

// Toggle buttons: aria-pressed carries the state; clicks are handled once, here.
const animeToggle = (cls, on) => `<button type="button" class="tog sm ${cls}" aria-pressed="${!!on}"><span class="knob"></span><span class="txt"><b>Anime</b></span></button>`;
const isOn = el => el.getAttribute('aria-pressed') === 'true';
document.addEventListener('click', e => {
  const tog = e.target.closest('.tog');
  if (tog) { tog.setAttribute('aria-pressed', String(!isOn(tog))); return; }
  const seg = e.target.closest('.seg button');
  if (seg) seg.parentElement.querySelectorAll('button').forEach(b => { b.classList.toggle('on', b === seg); b.setAttribute('aria-pressed', String(b === seg)); });
});

let allTitles = [];
async function loadList() {
  allTitles = await (await fetch('/api/titles')).json();
  $('ccount').textContent = allTitles.length;
  renderList();
}

function renderList() {
  const q = $('filter').value.trim().toLowerCase();
  const titles = allTitles.filter(t => !q || [t.title, t.category, t.year].join(' ').toLowerCase().includes(q));
  $('total').textContent = q ? `${titles.length} of ${allTitles.length}` : `${allTitles.length} titles`;
  $('list').innerHTML = titles.length ? titles.map(t => `<div class="item" data-id="${esc(t.id)}">
    <div class="row">
      <img src="${esc(t.thumbnail || '')}" alt="">
      <div class="meta"><div class="name">${esc(t.title)}</div><div class="info">${[t.year, t.category].filter(Boolean).map(esc).join(' · ')}</div></div>
      <div class="btns"><button class="btn sm edit">Edit links</button><button class="btn sm danger rm">Remove</button></div>
    </div>
    <div class="drawer" hidden>
      <label>Watch link (YouTube)</label><input class="e-movie" value="${esc(t.youtubeUrl || '')}">
      ${animeToggle('e-anime', t.isAnime)}
      <label>Trailer link (YouTube) <span style="font-weight:400">- leave empty to use TMDB's trailer${t.trailerKey ? '; a custom trailer is set' : ''}</span></label>
      <input class="e-trailer" value="${esc(t.trailerKey ? 'https://www.youtube.com/watch?v=' + t.trailerKey : '')}" placeholder="https://www.youtube.com/watch?v=...">
      <div class="actions"><button class="btn primary sm e-save">Save</button><button class="btn sm e-cancel">Cancel</button></div>
      <div class="msg e-msg"></div>
    </div></div>`).join('')
    : `<div class="empty">${allTitles.length ? 'No titles match your search.' : 'No titles yet. Add one from the Add title tab.'}</div>`;
  document.querySelectorAll('#list .item').forEach(el => {
    const id = el.dataset.id, drawer = el.querySelector('.drawer'), msg = el.querySelector('.e-msg');
    el.querySelector('.edit').onclick = () => { drawer.hidden = !drawer.hidden; };
    el.querySelector('.e-cancel').onclick = () => { drawer.hidden = true; msg.textContent = ''; };
    el.querySelector('.rm').onclick = async () => {
      if (!confirm('Remove this title?')) return;
      await fetch('/api/titles/' + id, { method: 'DELETE' });
      loadList();
    };
    el.querySelector('.e-save').onclick = async () => {
      msg.className = 'msg e-msg'; msg.textContent = 'Saving...';
      try {
        await api('/api/titles/' + id, { method: 'PATCH', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ youtubeUrl: el.querySelector('.e-movie').value, trailerUrl: el.querySelector('.e-trailer').value, isAnime: isOn(el.querySelector('.e-anime')) }) });
        msg.className = 'msg e-msg ok'; msg.textContent = 'Saved';
        setTimeout(loadList, 700);
      } catch (e) { msg.className = 'msg e-msg err'; msg.textContent = e.message; }
    };
  });
}
$('filter').oninput = renderList;

// tabs
document.querySelectorAll('.tab').forEach(t => t.onclick = () => {
  document.querySelectorAll('.tab').forEach(x => x.classList.toggle('on', x === t));
  document.querySelectorAll('[id^="p-"]').forEach(p => p.hidden = p.id !== 'p-' + t.dataset.tab);
});

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
let ytLink = null; // the YouTube link the current search came from, carried into the review queue
let tquery = { q: '', type: 'movie' }; // the search being paged, so editing the box doesn't change it mid-browse

async function tmdbSearch(page = 1) {
  const msg = $('t-msg');
  if (page === 1) tquery = { q: $('tq').value, type: $('ttype').querySelector('.on').dataset.v };
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
    $('tresults').innerHTML = results.map((c, i) => `<div class="res">
      <img src="${esc(c.poster || '')}" alt="">
      <div class="in"><div class="t">${esc(c.title)}</div><div class="m">${esc([c.year, c.category].filter(Boolean).join(' · '))}</div>
      <button class="btn sm" data-i="${i}">Shortlist</button></div></div>`).join('');
    document.querySelectorAll('#tresults .btn').forEach(b => b.onclick = async () => {
      try { await api('/api/admin/candidates', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...results[b.dataset.i], youtubeUrl: ytLink }) });
        b.textContent = 'Shortlisted ✓'; b.disabled = true; loadQueue(); }
      catch (e) { b.textContent = e.message; b.disabled = true; }
    });
  } catch (e) { msg.className = 'msg err'; msg.textContent = e.message; }
}
$('tsearch').onclick = () => { ytLink = null; tmdbSearch(1); };
$('ytfind').onclick = async () => {
  const msg = $('yt-msg'), url = $('yturl').value.trim();
  msg.className = 'msg'; msg.textContent = 'Reading YouTube title...';
  try {
    const d = await api('/api/admin/youtube-title?url=' + encodeURIComponent(url));
    ytLink = url;
    if (/[?&]list=/.test(url)) { // a playlist is a series: search TMDB TV, not movies
      const seg = $('ttype');
      seg.querySelectorAll('button').forEach(b => { const on = b.dataset.v === 'series'; b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); });
    }
    $('tq').value = d.query;
    msg.textContent = `YouTube title: "${d.raw}"${d.channel ? ' (' + d.channel + ')' : ''}. Searching TMDB for "${d.query}"...`;
    await tmdbSearch(1);
  } catch (e) { msg.className = 'msg err'; msg.textContent = e.message; }
};
$('yturl').onkeydown = e => { if (e.key === 'Enter') $('ytfind').click(); };
$('tq').onkeydown = e => { if (e.key === 'Enter') tmdbSearch(1); };
$('tprev').onclick = () => { tmdbSearch(tpage - 1); $('tresults').scrollIntoView({ behavior: 'smooth' }); };
$('tnext').onclick = () => { tmdbSearch(tpage + 1); $('tresults').scrollIntoView({ behavior: 'smooth' }); };

async function loadQueue() {
  const cands = await api('/api/admin/candidates');
  $('qcount').textContent = cands.length;
  $('queue').innerHTML = cands.length ? cands.map(c => `<div class="q qitem" data-id="${esc(c.id)}">
    <img src="${esc(c.poster || '')}" alt="">
    <div class="body"><div class="name">${esc(c.title)}</div>
      <div class="info">${[c.year, c.category].filter(Boolean).map(esc).join(' · ')}</div>
      <p>${esc(c.description)}</p>
      <a class="yt" href="${esc(ytSearch(c))}" target="_blank" rel="noopener">1. Search YouTube for this &#8599;</a>
      <div class="inline">
        <input class="q-url" placeholder="2. Paste the free YouTube link${c.type === 'series' ? ' (playlist)' : ''}" value="${esc(c.youtubeUrl || '')}">
      </div>
      <div class="inline" style="margin-top:10px">${animeToggle('q-anime', c.isAnime)}
        <button class="btn primary q-ok">Approve &amp; publish</button>
        <button class="btn danger q-no">Reject</button>
      </div>
      <div class="msg q-msg"></div></div></div>`).join('')
    : '<div class="empty">Nothing waiting. Shortlist titles from the Discover tab.</div>';
  document.querySelectorAll('.qitem').forEach(el => {
    const id = el.dataset.id, msg = el.querySelector('.q-msg');
    el.querySelector('.q-ok').onclick = async () => {
      try {
        await api(`/api/admin/candidates/${id}/approve`, { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: el.querySelector('.q-url').value, isAnime: isOn(el.querySelector('.q-anime')) }) });
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
    url: $('url').value, type: $('atype').querySelector('.on').dataset.v, isAnime: $('anime').getAttribute('aria-pressed') === 'true',
    year: $('year').value, title: $('title').value, description: $('description').value
  });
  const data = await r.json();
  if (r.ok) {
    msg.className = 'msg ok'; msg.textContent = `Added "${data.title}"`;
    ['url', 'year', 'title', 'description'].forEach(id => $(id).value = '');
    $('anime').setAttribute('aria-pressed', 'false');
    loadList();
  } else { msg.className = 'msg err'; msg.textContent = data.error; }
};

fetch('/api/admin/me').then(r => r.json()).then(d => show(d.admin));
