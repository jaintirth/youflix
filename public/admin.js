const $ = id => document.getElementById(id);
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c]);
const post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });

function show(admin) {
  $('login').hidden = admin; $('dash').hidden = !admin; $('logout').hidden = !admin;
  if (admin) loadList();
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
