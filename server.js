const express = require('express');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const PORT = process.env.PORT || 3000;
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'admin';
const DB_FILE = path.join(__dirname, 'data', 'titles.json');

if (!process.env.ADMIN_PASSWORD) {
  console.warn('ADMIN_PASSWORD not set - using default "admin". Set it before deploying.');
}

// ---------- storage ----------
function loadTitles() {
  try { return JSON.parse(fs.readFileSync(DB_FILE, 'utf8')); } catch { return []; }
}
function saveTitles(titles) {
  fs.writeFileSync(DB_FILE, JSON.stringify(titles, null, 2));
}

// ---------- youtube helpers ----------
// Returns { kind: 'video'|'playlist', id } or null.
function parseYouTube(input) {
  let url;
  try { url = new URL(input.trim()); } catch { return null; }
  const host = url.hostname.replace(/^www\.|^m\./, '');
  const list = url.searchParams.get('list');
  if (['youtube.com', 'music.youtube.com'].includes(host)) {
    if (url.pathname === '/playlist' && list) return { kind: 'playlist', id: list };
    const v = url.searchParams.get('v');
    if (v && /^[\w-]{11}$/.test(v)) return { kind: list ? 'playlist' : 'video', id: list || v };
    const m = url.pathname.match(/^\/(embed|shorts|live)\/([\w-]{11})/);
    if (m) return { kind: 'video', id: m[2] };
  } else if (host === 'youtu.be') {
    const id = url.pathname.slice(1, 12);
    if (/^[\w-]{11}$/.test(id)) return { kind: list ? 'playlist' : 'video', id: list || id };
  }
  return null;
}

async function fetchOEmbed(url) {
  try {
    const r = await fetch('https://www.youtube.com/oembed?format=json&url=' + encodeURIComponent(url));
    if (r.status === 401) return { embedBlocked: true }; // video exists but the owner disabled embedding
    if (!r.ok) return null;
    return await r.json();
  } catch { return null; }
}

// ---------- auth ----------
const sessions = new Set();
function cookie(req, name) {
  const m = (req.headers.cookie || '').match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
  return m ? decodeURIComponent(m[1]) : null;
}
function requireAdmin(req, res, next) {
  if (sessions.has(cookie(req, 'yf_admin'))) return next();
  res.status(401).json({ error: 'Not authorised' });
}

// ---------- app ----------
const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

app.post('/api/admin/login', (req, res) => {
  const given = Buffer.from(String(req.body.password || ''));
  const real = Buffer.from(ADMIN_PASSWORD);
  const ok = given.length === real.length && crypto.timingSafeEqual(given, real);
  if (!ok) return res.status(401).json({ error: 'Wrong password' });
  const token = crypto.randomBytes(24).toString('hex');
  sessions.add(token);
  res.setHeader('Set-Cookie', `yf_admin=${token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=86400`);
  res.json({ ok: true });
});
app.post('/api/admin/logout', (req, res) => {
  sessions.delete(cookie(req, 'yf_admin'));
  res.setHeader('Set-Cookie', 'yf_admin=; Max-Age=0; Path=/');
  res.json({ ok: true });
});
app.get('/api/admin/me', (req, res) => res.json({ admin: sessions.has(cookie(req, 'yf_admin')) }));

// public catalogue
app.get('/api/titles', (req, res) => res.json(loadTitles()));

// Publishes a title. `base` carries optional TMDB metadata that takes precedence over YouTube's.
async function publish(base, url) {
  const yt = parseYouTube(String(url || ''));
  if (!yt) return { status: 400, error: 'Not a valid YouTube video or playlist URL' };

  const titles = loadTitles();
  if (titles.some(t => t.youtubeId === yt.id)) {
    return { status: 409, error: 'That YouTube link is already in the catalogue' };
  }
  const meta = await fetchOEmbed(url);
  if ((!meta || !meta.title) && !base.title) {
    return { status: 400, error: 'YouTube could not find that link (private or removed?). Enter a title manually to add anyway.' };
  }
  const ytThumb = yt.kind === 'video'
    ? `https://i.ytimg.com/vi/${yt.id}/hqdefault.jpg`
    : (meta && meta.thumbnail_url) || null;
  const item = {
    id: crypto.randomUUID(),
    type: base.type === 'series' ? 'series' : 'movie',
    title: (base.title || meta.title).trim(),
    description: (base.description || '').trim(),
    category: (base.category || 'General').trim(),
    year: base.year ? Number(base.year) || null : null,
    kind: yt.kind,
    youtubeId: yt.id,
    youtubeUrl: String(url).trim(),
    thumbnail: base.backdrop || base.poster || ytThumb,
    poster: base.poster || null,
    tmdbId: base.tmdbId || null,
    channel: (meta && meta.author_name) || null,
    addedAt: new Date().toISOString()
  };
  titles.unshift(item);
  saveTitles(titles);
  return { status: 201, item };
}

// admin: add a title directly from a YouTube URL
app.post('/api/titles', requireAdmin, async (req, res) => {
  const { url, ...base } = req.body;
  const r = await publish(base, url);
  res.status(r.status).json(r.item || { error: r.error });
});

// ---------- TMDB discovery + approval queue ----------
// Nothing found on TMDB is public. Admin shortlists a candidate, finds it free on YouTube,
// pastes the link and approves it; only then does it enter the catalogue.
const TMDB_KEY = process.env.TMDB_API_KEY;
const TMDB_TOKEN = process.env.TMDB_TOKEN; // v4 read access token (alternative to the v3 key)
const CAND_FILE = path.join(__dirname, 'data', 'candidates.json');
const loadCands = () => { try { return JSON.parse(fs.readFileSync(CAND_FILE, 'utf8')); } catch { return []; } };
const saveCands = c => fs.writeFileSync(CAND_FILE, JSON.stringify(c, null, 2));

const tmdbImg = (p, size) => p ? `https://image.tmdb.org/t/p/${size}${p}` : null;

async function tmdb(pathname, params = {}) {
  if (!TMDB_KEY && !TMDB_TOKEN) throw Object.assign(new Error('TMDB is not configured. Set TMDB_API_KEY (or TMDB_TOKEN) and restart.'), { status: 503 });
  const url = new URL('https://api.themoviedb.org/3' + pathname);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  if (!TMDB_TOKEN) url.searchParams.set('api_key', TMDB_KEY);
  const r = await fetch(url, TMDB_TOKEN ? { headers: { Authorization: 'Bearer ' + TMDB_TOKEN } } : undefined);
  if (!r.ok) throw Object.assign(new Error('TMDB request failed (' + r.status + ')'), { status: 502 });
  return r.json();
}

function fromTmdb(x, type) {
  const date = x.release_date || x.first_air_date || '';
  return {
    tmdbId: x.id,
    type,
    title: x.title || x.name,
    year: date ? Number(date.slice(0, 4)) : null,
    description: x.overview || '',
    poster: tmdbImg(x.poster_path, 'w342'),
    backdrop: tmdbImg(x.backdrop_path, 'w780')
  };
}

app.get('/api/admin/tmdb/search', requireAdmin, async (req, res) => {
  const type = req.query.type === 'series' ? 'series' : 'movie';
  const q = String(req.query.q || '').trim();
  if (!q) return res.json({ results: [], page: 1, totalPages: 0, totalResults: 0 });
  try {
    const page = Math.max(1, Math.min(500, parseInt(req.query.page, 10) || 1)); // TMDB caps at 500
    const data = await tmdb(type === 'series' ? '/search/tv' : '/search/movie', { query: q, include_adult: 'false', page });
    res.json({
      results: data.results.map(x => fromTmdb(x, type)),
      page: data.page,
      totalPages: Math.min(data.total_pages, 500),
      totalResults: data.total_results
    });
  } catch (e) { res.status(e.status || 500).json({ error: e.message }); }
});

app.get('/api/admin/candidates', requireAdmin, (req, res) => res.json(loadCands()));

app.post('/api/admin/candidates', requireAdmin, (req, res) => {
  const { tmdbId, type, title, year, description, poster, backdrop } = req.body;
  if (!tmdbId || !title) return res.status(400).json({ error: 'Missing TMDB data' });
  const cands = loadCands();
  if (cands.some(c => c.tmdbId === tmdbId && c.type === type)) return res.status(409).json({ error: 'Already shortlisted' });
  if (loadTitles().some(t => t.tmdbId === tmdbId && t.type === type)) return res.status(409).json({ error: 'Already in the catalogue' });
  const cand = { id: crypto.randomUUID(), tmdbId, type: type === 'series' ? 'series' : 'movie', title, year, description, poster, backdrop };
  cands.unshift(cand);
  saveCands(cands);
  res.status(201).json(cand);
});

// Approve: attach the YouTube link the admin verified, then publish.
app.post('/api/admin/candidates/:id/approve', requireAdmin, async (req, res) => {
  const cands = loadCands();
  const cand = cands.find(c => c.id === req.params.id);
  if (!cand) return res.status(404).json({ error: 'Not found' });
  const r = await publish({ ...cand, category: req.body.category }, req.body.url);
  if (r.item) saveCands(cands.filter(c => c.id !== cand.id));
  res.status(r.status).json(r.item || { error: r.error });
});

app.delete('/api/admin/candidates/:id', requireAdmin, (req, res) => {
  saveCands(loadCands().filter(c => c.id !== req.params.id));
  res.json({ ok: true });
});

app.get('/api/admin/config', requireAdmin, (req, res) => res.json({ tmdb: !!(TMDB_KEY || TMDB_TOKEN) }));

app.delete('/api/titles/:id', requireAdmin, (req, res) => {
  const titles = loadTitles();
  const next = titles.filter(t => t.id !== req.params.id);
  if (next.length === titles.length) return res.status(404).json({ error: 'Not found' });
  saveTitles(next);
  res.json({ ok: true });
});

app.listen(PORT, () => console.log(`YOUFLIX running at http://localhost:${PORT}`));
