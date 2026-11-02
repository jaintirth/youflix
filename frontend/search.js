// Header search: live dropdown on desktop, full-screen overlay on phones.
// On the home page the full results replace the rows; elsewhere it sends you to /?q=...
(() => {
  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  const h = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c]);
  const poster = t => String(t.poster || t.thumbnail || '').replace(/\/t\/p\/w\d+\//, '/t/p/w342/');
  const phone = matchMedia('(max-width:760px)');
  const onHome = !!document.getElementById('rows');
  const icon = '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>';

  const header = document.querySelector('header');
  header.insertAdjacentHTML('beforeend', `<div class="spacer"></div>
    <div class="sx" id="sx">
      <button class="sx-btn" type="button" aria-label="Search" aria-expanded="false">${icon}</button>
      <form class="sx-form" role="search" action="/" method="get">
        ${icon}
        <input class="sx-input" name="q" type="search" placeholder="Search titles, categories, channels" autocomplete="off" autocapitalize="off" spellcheck="false" enterkeyhint="search" aria-label="Search titles">
        <button class="sx-clear" type="button" aria-label="Clear search" hidden>&times;</button>
        <button class="sx-cancel" type="button">Cancel</button>
      </form>
      <div class="sx-drop" hidden></div>
    </div>`);
  const box = document.getElementById('sx');
  const btn = box.querySelector('.sx-btn');
  const form = box.querySelector('.sx-form');
  const input = box.querySelector('.sx-input');
  const clear = box.querySelector('.sx-clear');
  const drop = box.querySelector('.sx-drop');

  let results;
  if (onHome) {
    document.querySelector('main').insertAdjacentHTML('afterend', '<section class="results" id="results" aria-live="polite" hidden></section>');
    results = document.getElementById('results');
  }

  // ---------- matching ----------
  const norm = s => String(s ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
  let index = null, cats = [], loading = null;
  const load = () => loading ||= fetch('/api/titles').then(r => r.json()).then(list => {
    index = list.map((t, i) => ({ t, i, title: norm(t.title), other: [norm(t.category), norm(t.channel), norm(t.year), t.type === 'series' ? 'series' : 'movie'] }));
    const n = {};
    list.forEach(t => { if (t.category && !t.isAnime) n[t.category] = (n[t.category] || 0) + 1; });
    cats = Object.entries(n).map(([name, count]) => ({ name, count, key: norm(name) }));
  }).catch(() => { index = []; });

  const wordStart = (s, tok) => s.startsWith(tok) || s.includes(' ' + tok);
  function search(q) {
    const toks = norm(q).split(' ').filter(Boolean);
    if (!toks.length || !index) return [];
    const phrase = toks.join(' ');
    const out = [];
    for (const e of index) {
      let score = e.title.startsWith(phrase) ? 20 : 0, ok = true;
      for (const tok of toks) {
        let s = 0;
        if (e.title.startsWith(tok)) s = 10;
        else if (wordStart(e.title, tok)) s = 8;
        else if (e.title.includes(tok)) s = 6;
        else if (e.other.some(o => wordStart(o, tok))) s = 3;
        else if (e.other.some(o => o.includes(tok))) s = 2;
        if (!s) { ok = false; break; }
        score += s;
      }
      if (ok) out.push({ e, score });
    }
    return out.sort((a, b) => b.score - a.score || a.e.i - b.e.i).map(x => x.e.t);
  }

  // categories whose name matches the query; every category when the query is empty
  const findCats = q => {
    const toks = norm(q).split(' ').filter(Boolean);
    return toks.length ? cats.filter(c => toks.every(tok => wordStart(c.key, tok))) : [];
  };
  const catChip = c => `<a class="sx-cat" data-cat="${h(c.name)}" href="/?category=${encodeURIComponent(c.name)}">${h(c.name)} <small>${c.count}</small></a>`;

  // ---------- dropdown / overlay ----------
  const meta = t => [t.type === 'series' ? 'Series' : '', t.year, t.category].filter(Boolean).map(h).join(' · ');
  const href = t => `/movie/${encodeURIComponent(t.id)}`;
  let active = -1, overlayOpen = false;

  function row(t) {
    return `<a class="sx-row" role="option" href="${href(t)}"><img src="${h(poster(t))}" alt="" loading="lazy"><span><b>${h(t.title)}</b><small>${meta(t)}</small></span></a>`;
  }

  function paintDrop() {
    const q = input.value.trim();
    clear.hidden = !q;
    active = -1;
    if (!q) {
      drop.hidden = !(phone.matches && overlayOpen);
      drop.innerHTML = phone.matches ? '<div class="sx-hint">Search by title, category or channel<br>Try “Action” or “Comedy”</div>' : '';
      return;
    }
    const found = search(q);
    const cm = findCats(q);
    const catBlock = cm.length ? `<div class="sx-label">Categories</div><div class="sx-cats">${cm.map(catChip).join('')}</div>` : '';
    const cap = phone.matches ? 30 : 6;
    drop.hidden = false;
    drop.setAttribute('role', 'listbox');
    drop.innerHTML = catBlock + (found.length
      ? (cm.length ? '<div class="sx-label">Titles</div>' : '') + found.slice(0, cap).map(row).join('') + (found.length > cap || !phone.matches ? `<button class="sx-all" type="button">See all ${found.length} result${found.length > 1 ? 's' : ''}</button>` : '')
      : (cm.length ? '' : `<div class="sx-hint">No results for “${h(q)}”</div>`));
  }

  function openBox() {
    box.classList.add('open');
    btn.setAttribute('aria-expanded', 'true');
    if (phone.matches && !overlayOpen) {
      overlayOpen = true;
      document.body.classList.add('sx-lock');
      history.pushState({ sx: 1 }, '');
    }
    load().then(paintDrop);
    paintDrop();
    input.focus();
  }

  // fromPop: the browser already moved history, don't touch it
  function closeBox(fromPop) {
    const wasOverlay = overlayOpen;
    overlayOpen = false;
    document.body.classList.remove('sx-lock');
    drop.hidden = true;
    if (!input.value.trim()) box.classList.remove('open');
    btn.setAttribute('aria-expanded', String(box.classList.contains('open')));
    if (wasOverlay && !fromPop && history.state?.sx) history.back();
  }

  // ---------- full results ----------
  function showResults(q, push) {
    q = q.trim();
    if (!onHome) { location.href = '/?q=' + encodeURIComponent(q); return; }
    const url = q ? '/?q=' + encodeURIComponent(q) : '/';
    if (push) {
      if (overlayOpen && history.state?.sx) history.replaceState({}, '', url); // the overlay entry becomes the results entry
      else history.pushState({}, '', url);
    }
    overlayOpen = false;
    document.body.classList.remove('sx-lock');
    drop.hidden = true;
    input.value = q;
    clear.hidden = !q;
    document.body.classList.toggle('searching', !!q);
    if (q) document.title = `${q} - YOUFLIX`;
    if (!q) { results.hidden = true; box.classList.remove('open'); return; }
    box.classList.add('open');
    results.hidden = false;
    results.innerHTML = '<div class="empty">Searching...</div>';
    load().then(() => {
      if (input.value.trim() !== q) return;
      const found = search(q);
      results.innerHTML = found.length
        ? `<h2 class="r-head">${found.length} result${found.length > 1 ? 's' : ''} for “${h(q)}”</h2><div class="rgrid">${found.map(t => `<a class="tile" href="${href(t)}"><div class="thumb"><img src="${h(poster(t))}" alt="" loading="lazy"></div><div class="info show"><div class="t">${h(t.title)}</div><div class="m">${meta(t)}</div></div></a>`).join('')}</div>`
        : `<div class="empty"><b>No results for “${h(q)}”</b><br>Try a different title, genre or channel.</div>`;
      scrollTo(0, 0);
    });
  }

  // ---------- events ----------
  btn.onclick = () => (box.classList.contains('open') && !phone.matches ? input.focus() : openBox());
  input.addEventListener('focus', () => { if (!box.classList.contains('open') || (phone.matches && !overlayOpen)) openBox(); else load().then(paintDrop); });
  let tm;
  input.addEventListener('input', () => { clearTimeout(tm); clear.hidden = !input.value; tm = setTimeout(() => load().then(paintDrop), 80); });
  clear.onclick = () => { input.value = ''; paintDrop(); input.focus(); if (onHome && document.body.classList.contains('searching')) showResults('', true); };
  box.querySelector('.sx-cancel').onclick = () => { if (!document.body.classList.contains('searching')) input.value = ''; closeBox(); };
  form.onsubmit = e => { e.preventDefault(); if (input.value.trim()) { input.blur(); showResults(input.value, true); } };
  drop.addEventListener('click', e => {
    if (e.target.closest('.sx-all')) form.requestSubmit();
    // category picked: close the overlay without leaving a stale history entry, then app.js shows the category
    if (e.target.closest('.sx-cat') && onHome) {
      if (overlayOpen && history.state?.sx) history.replaceState({}, '', location.href);
      showResults('', false);
    }
  });

  input.addEventListener('keydown', e => {
    const rows = [...drop.querySelectorAll('.sx-row')];
    if (e.key === 'Escape') { if (input.value && !phone.matches) { input.value = ''; paintDrop(); } else { input.blur(); closeBox(); } return; }
    if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && rows.length) {
      e.preventDefault();
      active = (active + (e.key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length;
      rows.forEach((r, i) => r.classList.toggle('on', i === active));
      rows[active].scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter' && active >= 0 && rows[active]) { e.preventDefault(); location.href = rows[active].href; }
  });

  addEventListener('keydown', e => {
    if (e.key === '/' && !e.metaKey && !e.ctrlKey && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName)) { e.preventDefault(); openBox(); }
  });
  document.addEventListener('click', e => {
    if (!phone.matches && !box.contains(e.target)) { drop.hidden = true; if (!document.body.classList.contains('searching') && !input.value.trim()) box.classList.remove('open'); }
  });

  addEventListener('popstate', () => {
    if (overlayOpen) closeBox(true);
    if (onHome) showResults(new URLSearchParams(location.search).get('q') || '', false);
  });

  if (onHome) {
    const q = new URLSearchParams(location.search).get('q');
    if (q) showResults(q, false);
  }
})();
