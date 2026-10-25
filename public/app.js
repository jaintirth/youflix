const $ = id => document.getElementById(id);
let titles = [], filter = 'all', slide = 0, timer = null;
const SLIDE_MS = 6000;
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c]);

// TMDB serves any size from the same path, so request sharper images than were stored.
const tmdbSize = (u, size) => u ? String(u).replace(/\/t\/p\/w\d+\//, `/t/p/${size}/`) : u;
const posterOf = (t, size = 'w500') => tmdbSize(t.poster || t.thumbnail, size);
const pageOf = t => `/movie/${encodeURIComponent(t.id)}`;
const metaOf = t => [t.type === 'series' ? 'Series' : '', t.year, t.category].filter(Boolean).map(esc).join(' · ');

function tile(t, n) {
  return `<a class="tile" href="${pageOf(t)}">
    ${n ? `<span class="num">${n}</span>` : ''}
    <div class="thumb">${t.type === 'series' ? '<span class="badge">SERIES</span>' : ''}
    <img src="${esc(posterOf(t))}" alt="" loading="lazy"></div>
    <div class="info show"><div class="t">${esc(t.title)}</div>
    <div class="m">${[t.year, t.category].filter(Boolean).map(esc).join(' · ')}</div></div></a>`;
}

function rail(inner) {
  return `<div class="rail-wrap"><button class="arrow left" aria-label="Scroll left"><svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 4 7 12l8 8"/></svg></button>
    <div class="rail">${inner}</div><button class="arrow right" aria-label="Scroll right"><svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 4 8 8-8 8"/></svg></button></div>`;
}

// ---------- hero carousel (top 6) ----------
const featuredList = () => titles.slice(0, 6);

function showSlide(i) {
  const list = featuredList();
  if (!list.length) return;
  slide = (i + list.length) % list.length;
  const f = list[slide];
  const hero = $('hero');
  hero.classList.remove('swap');
  void hero.offsetWidth; // restart the fade-in animation
  hero.classList.add('swap');
  hero.style.backgroundImage = `url("${tmdbSize(f.thumbnail, 'w1280')}")`;
  hero.style.setProperty('--poster-url', `url("${posterOf(f, 'w780')}")`); // phones use the portrait poster instead of the wide backdrop
  hero.innerHTML = `<div class="hero-text"><div class="eyebrow">★ Featured ${slide + 1}/${list.length}</div><h1>${esc(f.title)}</h1>
      <div class="meta">${metaOf(f)}</div>
      <p>${esc(f.description || 'Free to watch on YouTube.')}</p>
      <div class="btns"><a class="btn red" href="${esc(f.youtubeUrl)}" target="_blank" rel="noopener">&#9654; Watch Now</a>
      <a class="btn" href="${pageOf(f)}">ⓘ More Info</a></div></div>
    <a href="${pageOf(f)}"><img class="hero-poster" src="${esc(posterOf(f, 'w780'))}" alt=""></a>
    <button class="hero-arrow left" id="h-prev" aria-label="Previous"><svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 4 7 12l8 8"/></svg></button>
    <button class="hero-arrow right" id="h-next" aria-label="Next"><svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 4 8 8-8 8"/></svg></button>
    <div class="dots">${list.map((_, k) => `<button class="dot ${k === slide ? 'on' : ''}" data-i="${k}" aria-label="Slide ${k + 1}"></button>`).join('')}</div>`;
  $('h-prev').onclick = () => { showSlide(slide - 1); restartTimer(); };
  $('h-next').onclick = () => { showSlide(slide + 1); restartTimer(); };
  hero.querySelectorAll('.dot').forEach(d => d.onclick = () => { showSlide(+d.dataset.i); restartTimer(); });
}

function restartTimer() {
  clearTimeout(timer);
  if (featuredList().length < 2) return;
  const tick = () => {
    if (document.hidden || paused) { timer = setTimeout(tick, 1500); return; }
    showSlide(slide + 1);
    restartTimer();
  };
  timer = setTimeout(tick, SLIDE_MS);
}
let paused = false;
$('hero').onmouseenter = () => { paused = true; };
$('hero').onmouseleave = () => { paused = false; };

// ---------- stats counters (count 0 → n once, when scrolled into view) ----------
let statsDone = false;
function runStats() {
  const box = $('stats'), movies = titles.filter(t => t.type !== 'series').length;
  box.hidden = !movies;
  if (statsDone || !movies) return;
  const targets = [[$('stat-movies'), movies]];
  const paint = (el, v) => { el.textContent = `${v}+`; };
  const go = () => {
    statsDone = true;
    const DUR = 1800, t0 = performance.now();
    const step = now => {
      const p = Math.min((now - t0) / DUR, 1), eased = 1 - Math.pow(1 - p, 3);
      targets.forEach(([el, n]) => paint(el, Math.round(eased * n)));
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };
  targets.forEach(([el, n]) => { el.setAttribute('aria-label', `${n} plus`); paint(el, 0); });
  if (!('IntersectionObserver' in window)) return go();
  new IntersectionObserver((es, io) => { if (es[0].isIntersecting) { io.disconnect(); go(); } }, { threshold: 0.4 }).observe(box);
}

function render() {
  const shown = titles.filter(t => filter === 'all' || t.type === filter);

  if (titles.length) {
    $('hero').hidden = false;
    if (!$('hero').children.length) { showSlide(0); restartTimer(); }
  } else $('hero').hidden = true;

  runStats();
  document.querySelectorAll('[data-nav]').forEach(a => a.classList.toggle('active', a.dataset.nav === filter));

  if (!shown.length) {
    $('rows').innerHTML = '<div class="empty">Nothing here yet. An admin can add titles from the Admin page.</div>';
    return;
  }
  const cats = [...new Set(shown.map(t => t.category))];
  const top = shown.length >= 4
    ? `<div class="row top"><div class="row-head"><h2>Top 10</h2></div>${rail(shown.slice(0, 10).map((t, i) => tile(t, i + 1)).join(''))}</div>` : '';
  $('rows').innerHTML = top + cats.map(c => {
    const list = shown.filter(t => t.category === c);
    return `<div class="row"><div class="row-head"><h2>${esc(c)}</h2><span>${list.length} title${list.length > 1 ? 's' : ''}</span></div>${rail(list.map(t => tile(t)).join(''))}</div>`;
  }).join('');
  wireRails();
}

function wireRails() {
  document.querySelectorAll('.rail-wrap').forEach(w => {
    const r = w.querySelector('.rail');
    const update = () => {
      w.querySelector('.left').hidden = r.scrollLeft < 8;
      w.querySelector('.right').hidden = r.scrollLeft + r.clientWidth >= r.scrollWidth - 8;
    };
    w.querySelector('.left').onclick = () => r.scrollBy({ left: -r.clientWidth * 0.85, behavior: 'smooth' });
    w.querySelector('.right').onclick = () => r.scrollBy({ left: r.clientWidth * 0.85, behavior: 'smooth' });
    r.addEventListener('scroll', update, { passive: true });
    update();
  });
}

document.querySelectorAll('[data-nav]').forEach(a => a.onclick = e => { e.preventDefault(); filter = a.dataset.nav; render(); });

fetch('/api/titles').then(r => r.json()).then(d => { titles = d; render(); });
