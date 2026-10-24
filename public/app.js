const $ = id => document.getElementById(id);
let titles = [], filter = 'all';

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c]);

function card(t) {
  return `<div class="card" data-id="${esc(t.id)}">
    ${t.type === 'series' ? '<span class="badge">SERIES</span>' : ''}
    <img src="${esc(t.thumbnail || '')}" alt="" loading="lazy">
    <div class="info"><div class="t">${esc(t.title)}</div>
    <div class="m">${[t.year, t.category].filter(Boolean).map(esc).join(' · ')}</div></div></div>`;
}

function render() {
  const shown = titles.filter(t => filter === 'all' || t.type === filter);
  const hero = $('hero');
  const featured = titles[0];
  if (featured) {
    hero.hidden = false;
    hero.style.backgroundImage = `url("${featured.thumbnail}")`;
    hero.innerHTML = `<h1>${esc(featured.title)}</h1><p>${esc(featured.description || 'Free to watch on YouTube.')}</p>
      <div><button class="btn" id="hero-play">&#9654; Watch</button></div>`;
    $('hero-play').onclick = () => window.open(featured.youtubeUrl, '_blank', 'noopener');
  } else hero.hidden = true;

  $('filters').innerHTML = ['all', 'movie', 'series'].map(f =>
    `<button class="chip ${f === filter ? 'active' : ''}" data-f="${f}">${f === 'all' ? 'All' : f === 'movie' ? 'Movies' : 'Series'}</button>`).join('');
  document.querySelectorAll('.chip').forEach(b => b.onclick = () => { filter = b.dataset.f; render(); });

  if (!shown.length) {
    $('rows').innerHTML = '<div class="empty">Nothing here yet. An admin can add titles from the Admin page.</div>';
    return;
  }
  const cats = [...new Set(shown.map(t => t.category))];
  $('rows').innerHTML = cats.map(c =>
    `<div class="row"><h2>${esc(c)}</h2><div class="grid">${shown.filter(t => t.category === c).map(card).join('')}</div></div>`).join('');
  document.querySelectorAll('.card').forEach(el => el.onclick = () => openTitle(el.dataset.id));
}

// Many owners disable embedding, so titles always open on YouTube itself.
function openTitle(id) {
  const t = titles.find(x => x.id === id);
  if (!t) return;
  $('player').style.backgroundImage = `url("${t.thumbnail || ''}")`;
  $('m-title').textContent = t.title;
  $('m-meta').textContent = [t.type === 'series' ? 'Series' : 'Movie', t.year, t.category, t.channel && 'via ' + t.channel].filter(Boolean).join(' · ');
  $('m-desc').textContent = t.description || '';
  $('m-yt').href = t.youtubeUrl;
  $('modal').classList.add('open');
}
function closeModal() { $('modal').classList.remove('open'); }
$('close').onclick = closeModal;
$('modal').onclick = e => { if (e.target === $('modal')) closeModal(); };
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });

fetch('/api/titles').then(r => r.json()).then(d => { titles = d; render(); });
