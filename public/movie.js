const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c]);
const tmdbSize = (u, size) => u ? String(u).replace(/\/t\/p\/w\d+\//, `/t/p/${size}/`) : u;
const page = document.getElementById('page');
const id = decodeURIComponent(location.pathname.split('/')[2] || '');

fetch(`/api/titles/${encodeURIComponent(id || '')}/details`)
  .then(r => r.ok ? r.json() : Promise.reject())
  .then(draw)
  .catch(() => { page.innerHTML = '<div class="empty" style="padding-top:140px">Title not found. <a href="/" style="color:var(--red)">Back to home</a></div>'; });

function draw({ title: t, details: d }) {
  d = d || {};
  document.title = `${t.title} - YOUFLIX`;
  const backdrop = d.backdrop || tmdbSize(t.thumbnail, 'w1280');
  const poster = d.poster || tmdbSize(t.poster || t.thumbnail, 'w780');
  const facts = [
    d.rating ? `<span class="rating">★ ${d.rating}</span>` : '',
    t.year ? `<span>${esc(t.year)}</span>` : '',
    d.runtime ? `<span>${Math.floor(d.runtime / 60) ? Math.floor(d.runtime / 60) + 'h ' : ''}${d.runtime % 60}m</span>` : '',
    d.seasons ? `<span>${d.seasons} season${d.seasons > 1 ? 's' : ''}</span>` : '',
    t.type === 'series' ? '<span>Series</span>' : '',
    ...(d.genres || []).map(g => `<span class="gen">${esc(g)}</span>`)
  ].join('');

  const cast = (d.cast || []).filter((c, i, a) => c.photo && a.findIndex(x => x.name === c.name) === i);

  page.innerHTML = `
  <section class="mhero" style="background-image:url('${esc(backdrop)}');--poster-url:url('${esc(poster)}')">
    <img class="mposter" src="${esc(poster)}" alt="">
    <div class="minfo">
      <h1>${esc(t.title)}</h1>
      <div class="facts">${facts}</div>
      <p class="over">${esc(d.overview || t.description || '')}</p>
      <div class="btns"><a class="btn red" href="${esc(t.youtubeUrl)}" target="_blank" rel="noopener">&#9654; Watch Free on YouTube</a>${d.trailer ? `<a class="btn" href="https://www.youtube.com/watch?v=${encodeURIComponent(d.trailer)}" target="_blank" rel="noopener">&#127916; Watch Trailer</a>` : ''}</div>
    </div>
  </section>
  ${cast.length ? `<section class="msec"><h2>Cast</h2><div class="cast">${cast.map(c => `<div class="person"><img src="${esc(c.photo)}" alt="" loading="lazy"><b>${esc(c.name)}</b><span>${esc(c.character)}</span></div>`).join('')}</div></section>` : ''}
  <section class="msec" id="sim-sec" hidden><h2>More Like This</h2><div class="simgrid" id="sim"></div></section>`;
  loadSimilar(t);
}

// Franchise key + installment number: "Krrish 3 (2013)" -> { key: 'krrish', n: 3 }.
const ROMAN = { ii: 2, iii: 3, iv: 4, v: 5, vi: 6, vii: 7, viii: 8, ix: 9, x: 10 };
function franchise(title) {
  let s = String(title || '').toLowerCase().replace(/:\s*(?=\d)/g, ' ').split(/[|(\[:–—]| - /)[0].replace(/[^a-z0-9ऀ-ॿ ]+/g, ' ').trim();
  let n = 1;
  const m = s.match(/^(.*?)\s+(?:(?:part|chapter|vol(?:ume)?)\s+)?(\d{1,2}|ii|iii|iv|v|vi|vii|viii|ix|x)$/);
  if (m && m[1].length >= 3) { s = m[1].trim(); n = ROMAN[m[2]] || +m[2]; }
  return { key: s, n };
}

// "More like this": franchise entries (sequels/prequels) first, then the rest of the same category.
function loadSimilar(t) { fetch('/api/titles').then(r => r.json()).then(all => {
  const me = franchise(t.title);
  const pool = all.filter(x => x.id !== t.id && !!x.isAnime === !!t.isAnime); // anime stays with anime, movies with movies
  const series = pool.map(x => ({ x, f: franchise(x.title) })).filter(({ f }) => me.key.length >= 3 && f.key === me.key)
    .sort((a, b) => a.f.n - b.f.n || (+a.x.year || 0) - (+b.x.year || 0)).map(({ x }) => x);
  const seen = new Set(series.map(x => x.id));
  // anime share any genre ("Animation" says nothing); everything else shares its one category
  const genresOf = x => x.isAnime && (x.genres || []).length ? x.genres.filter(g => g !== 'Animation') : [x.category].filter(Boolean);
  const mine = genresOf(t);
  const rest = pool.filter(x => !seen.has(x.id) && genresOf(x).some(g => mine.includes(g)));
  const others = [...series, ...rest];
  if (!others.length) return;
  document.getElementById('sim').innerHTML = others.slice(0, 12).map(s =>
    `<a class="sim" href="/movie/${encodeURIComponent(s.id)}"><img src="${esc(tmdbSize(s.poster || s.thumbnail, 'w342'))}" alt="" loading="lazy"><b>${esc(s.title)}</b><span>${[s.year, s.category].filter(Boolean).map(esc).join(' · ')}</span></a>`).join('');
  if (t.isAnime) document.querySelector('#sim-sec h2').textContent = 'More Anime Like This';
  document.getElementById('sim-sec').hidden = false;
}); }
