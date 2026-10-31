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
const PUB = path.join(__dirname, 'public');
// Clean URLs: /movie/<id> and /admin instead of the .html files.
app.get(['/movie.html', '/admin.html'], (req, res) => res.redirect(301, req.path.replace('.html', '')));
app.get('/movie/:id', (req, res) => res.sendFile(path.join(PUB, 'movie.html')));
app.get('/admin', (req, res) => res.sendFile(path.join(PUB, 'admin.html')));
app.use(express.static(PUB));

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
// Most popular first (TMDB's daily popularity score): the banner (first 6) and the Top 10 row both follow this order.
// Titles without a score yet sort last, newest first.
const byPopularity = (a, b) => (b.popularity ?? -1) - (a.popularity ?? -1) || String(b.addedAt).localeCompare(String(a.addedAt));
app.get('/api/titles', (req, res) => res.json(loadTitles().sort(byPopularity)));

// TMDB's popularity score for a title (finding it on TMDB first when we only have the name). Null when unknown.
async function tmdbPopularity({ tmdbId, title, year }) {
  if (!TMDB_KEY && !TMDB_TOKEN) return null;
  try {
    let id = tmdbId;
    if (!id) {
      const s = await tmdb('/search/movie', { query: title, ...(year ? { year } : {}) });
      id = s.results && s.results[0] && s.results[0].id;
    }
    if (!id) return null;
    const d = await tmdb(`/movie/${id}`);
    return { tmdbId: id, popularity: Math.round(d.popularity * 100) / 100 };
  } catch { return null; }
}
async function refreshPopularity() {
  const titles = loadTitles();
  let changed = 0;
  for (const t of titles) {
    const p = await tmdbPopularity(t);
    if (p && (t.popularity !== p.popularity || !t.tmdbId)) { t.popularity = p.popularity; t.tmdbId = t.tmdbId || p.tmdbId; changed++; }
  }
  if (changed) { saveTitles(titles); console.log(`Updated TMDB popularity for ${changed} title(s)`); }
}


// Publishes a title. `base` carries optional TMDB metadata that takes precedence over YouTube's.
async function publish(base, url) {
  if (!String(url || '').trim()) return { status: 400, error: 'Paste the free YouTube link first' };
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
  const name = (base.title || (meta && meta.title) || '').trim();
  const genres = await inferGenres({ type: base.type, tmdbId: base.tmdbId, title: name, year: base.year }) || [];
  const isAnime = base.isAnime === true || base.isAnime === 'true';
  const item = {
    id: crypto.randomUUID(),
    type: base.type === 'series' ? 'series' : 'movie',
    isAnime,
    title: (base.title || meta.title).trim(),
    description: (base.description || '').trim(),
    category: (base.category || (isAnime ? animeCategory(genres) : null) || genres[0] || 'General').trim(),
    genres,
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
  const pop = await tmdbPopularity(item);
  if (pop) { item.popularity = pop.popularity; item.tmdbId = item.tmdbId || pop.tmdbId; }
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

// Category = the title's main TMDB genre, so the admin never picks one by hand.
const genreCache = {};
async function genreNames(kind) {
  if (!genreCache[kind]) {
    const d = await tmdb(`/genre/${kind}/list`);
    genreCache[kind] = Object.fromEntries(d.genres.map(g => [g.id, g.name]));
  }
  return genreCache[kind];
}
// All of a title's TMDB genres (e.g. ["Animation", "Action", "Comedy"]). Works from a TMDB id when known,
// otherwise finds the title on TMDB first. Returns null when TMDB can't say.
async function inferGenres({ type, tmdbId, title, year }) {
  if (!TMDB_KEY && !TMDB_TOKEN) return null;
  try {
    const kind = type === 'series' ? 'tv' : 'movie';
    let id = tmdbId;
    if (!id) {
      const s = await tmdb(`/search/${kind}`, { query: title, ...(year ? { [kind === 'tv' ? 'first_air_date_year' : 'year']: year } : {}) });
      id = s.results && s.results[0] && s.results[0].id;
    }
    if (!id) return null;
    const d = await tmdb(`/${kind}/${id}`);
    return d.genres && d.genres.length ? d.genres.map(g => g.name) : null;
  } catch { return null; }
}
async function inferCategory(t) {
  const g = await inferGenres(t);
  return (g && g[0]) || null;
}
// "Animation" says nothing about an anime, so its category is the first real genre.
const animeCategory = genres => (genres || []).find(g => g !== 'Animation') || null;

function fromTmdb(x, type) {
  const date = x.release_date || x.first_air_date || '';
  return {
    tmdbId: x.id,
    type,
    title: x.title || x.name,
    year: date ? Number(date.slice(0, 4)) : null,
    description: x.overview || '',
    poster: tmdbImg(x.poster_path, 'w342'),
    backdrop: tmdbImg(x.backdrop_path, 'w780'),
    // TMDB has no anime flag: Japanese-language animation is the closest match. Admin can override.
    isAnime: (x.genre_ids || []).includes(16) && x.original_language === 'ja'
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

// Turns a YouTube link into a clean search term for TMDB: strips "Full Movie", years, quality tags, channel suffixes.
app.get('/api/admin/youtube-title', requireAdmin, async (req, res) => {
  const url = String(req.query.url || '');
  if (!parseYouTube(url)) return res.status(400).json({ error: 'Not a valid YouTube video or playlist URL' });
  const meta = await fetchOEmbed(url);
  if (!meta || !meta.title) return res.status(404).json({ error: 'YouTube could not find that link (private, removed or embedding disabled)' });
  let t = meta.title;
  const year = (t.match(/\b(19[2-9]\d|20[0-4]\d)\b/) || [])[1] || null;
  t = t.split(/\s[|–—]\s|\s-\s(?=.*(?:full|movie|hd|film|official))/i)[0];
  t = t.replace(/[\(\[][^)\]]*[\)\]]/g, ' ')
       .replace(/\b(full|new|latest|hindi|english|tamil|telugu|punjabi|bollywood|hollywood|dubbed|hd|4k|1080p|720p|movie|movies|film|official|episode|episodes|with english subtitles?|eng sub)\b/gi, ' ')
       .replace(/\b(19[2-9]\d|20[0-4]\d)\b/g, ' ')
       .replace(/[^\p{L}\p{N}'&:! ]+/gu, ' ').replace(/\s+/g, ' ').trim();
  res.json({ raw: meta.title, query: t || meta.title, year: year ? Number(year) : null, channel: meta.author_name || null });
});

app.get('/api/admin/candidates', requireAdmin, (req, res) => res.json(loadCands()));

app.post('/api/admin/candidates', requireAdmin, (req, res) => {
  const { tmdbId, type, title, year, description, poster, backdrop, youtubeUrl, category, isAnime } = req.body;
  if (!tmdbId || !title) return res.status(400).json({ error: 'Missing TMDB data' });
  const cands = loadCands();
  const dup = cands.find(c => c.tmdbId === tmdbId && c.type === type);
  if (dup) {
    // Re-shortlisting from a YouTube link: keep the candidate but attach the link it was missing.
    if (youtubeUrl && !dup.youtubeUrl) { dup.youtubeUrl = youtubeUrl; saveCands(cands); return res.json(dup); }
    return res.status(409).json({ error: 'Already shortlisted' });
  }
  if (loadTitles().some(t => t.tmdbId === tmdbId && t.type === type)) return res.status(409).json({ error: 'Already in the catalogue' });
  const cand = { id: crypto.randomUUID(), tmdbId, type: type === 'series' ? 'series' : 'movie', title, year, description, poster, backdrop, category: category || null, isAnime: isAnime === true, youtubeUrl: youtubeUrl || null };
  cands.unshift(cand);
  saveCands(cands);
  res.status(201).json(cand);
});

// Approve: attach the YouTube link the admin verified, then publish.
app.post('/api/admin/candidates/:id/approve', requireAdmin, async (req, res) => {
  const cands = loadCands();
  const cand = cands.find(c => c.id === req.params.id);
  if (!cand) return res.status(404).json({ error: 'Not found' });
  const r = await publish({ ...cand, ...(typeof req.body.isAnime === 'boolean' ? { isAnime: req.body.isAnime } : {}) }, req.body.url);
  if (r.item) saveCands(cands.filter(c => c.id !== cand.id));
  res.status(r.status).json(r.item || { error: r.error });
});

app.delete('/api/admin/candidates/:id', requireAdmin, (req, res) => {
  saveCands(loadCands().filter(c => c.id !== req.params.id));
  res.json({ ok: true });
});

app.get('/api/admin/config', requireAdmin, (req, res) => res.json({ tmdb: !!(TMDB_KEY || TMDB_TOKEN) }));

// admin: change a title's movie link and/or trailer link. An empty trailer link goes back to TMDB's trailer.
app.patch('/api/titles/:id', requireAdmin, async (req, res) => {
  const titles = loadTitles();
  const t = titles.find(x => x.id === req.params.id);
  if (!t) return res.status(404).json({ error: 'Not found' });
  const { youtubeUrl, trailerUrl, isAnime } = req.body;
  if (isAnime !== undefined) t.isAnime = isAnime === true;

  if (youtubeUrl !== undefined) {
    const yt = parseYouTube(String(youtubeUrl));
    if (!yt) return res.status(400).json({ error: 'Watch link is not a valid YouTube video or playlist URL' });
    if (titles.some(x => x.id !== t.id && x.youtubeId === yt.id)) return res.status(409).json({ error: 'That YouTube link is already used by another title' });
    if (yt.id !== t.youtubeId) {
      const meta = await fetchOEmbed(String(youtubeUrl));
      if (!meta) return res.status(400).json({ error: 'YouTube could not find that link (private or removed?)' });
      t.channel = meta.author_name || t.channel || null;
    }
    t.youtubeUrl = String(youtubeUrl).trim();
    t.youtubeId = yt.id;
    t.kind = yt.kind;
  }
  if (trailerUrl !== undefined) {
    const raw = String(trailerUrl).trim();
    if (!raw) delete t.trailerKey;
    else {
      const yt = parseYouTube(raw);
      if (!yt || yt.kind !== 'video') return res.status(400).json({ error: 'Trailer link must be a YouTube video URL' });
      t.trailerKey = yt.id;
    }
  }
  saveTitles(titles);
  res.json(t);
});

app.delete('/api/titles/:id', requireAdmin, (req, res) => {
  const titles = loadTitles();
  const next = titles.filter(t => t.id !== req.params.id);
  if (next.length === titles.length) return res.status(404).json({ error: 'Not found' });
  saveTitles(next);
  res.json({ ok: true });
});

// ---------- title details (TMDB) ----------
// Everything on the movie page beyond what we store: cast, reviews, trailer, similar titles.
const detailCache = new Map();
app.get('/api/titles/:id/details', async (req, res) => {
  const all = loadTitles();
  const t = all.find(x => x.id === req.params.id);
  if (!t) return res.status(404).json({ error: 'Not found' });
  const base = { title: t, details: t.trailerKey ? { trailer: t.trailerKey } : null };
  if (!TMDB_KEY && !TMDB_TOKEN) return res.json(base);
  try {
    const kind = t.type === 'series' ? 'tv' : 'movie';
    let tmdbId = t.tmdbId;
    if (!tmdbId) {
      const s = await tmdb(`/search/${kind}`, { query: t.title, ...(t.year ? { [kind === 'tv' ? 'first_air_date_year' : 'year']: t.year } : {}) });
      tmdbId = s.results && s.results[0] && s.results[0].id;
    }
    if (!tmdbId) return res.json(base);
    const key = kind + tmdbId;
    if (!detailCache.has(key)) {
      const d = await tmdb(`/${kind}/${tmdbId}`, { append_to_response: 'credits,reviews,videos,similar' });
      const trailer = (d.videos?.results || []).find(v => v.site === 'YouTube' && v.type === 'Trailer') || (d.videos?.results || []).find(v => v.site === 'YouTube');
      const onSite = new Map(all.filter(x => x.tmdbId).map(x => [x.tmdbId, x.id]));
      detailCache.set(key, {
        tagline: d.tagline || '',
        overview: d.overview || '',
        genres: (d.genres || []).map(g => g.name),
        runtime: d.runtime || (d.episode_run_time || [])[0] || null,
        rating: d.vote_average ? Math.round(d.vote_average * 10) / 10 : null,
        votes: d.vote_count || 0,
        language: d.original_language,
        seasons: d.number_of_seasons || null,
        backdrop: tmdbImg(d.backdrop_path, 'w1280'),
        poster: tmdbImg(d.poster_path, 'w780'),
        trailer: trailer ? trailer.key : null,
        cast: (d.credits?.cast || []).slice(0, 14).map(c => ({ name: c.name, character: c.character, photo: tmdbImg(c.profile_path, 'w185') })),
        crew: (d.credits?.crew || []).filter(c => ['Director', 'Writer', 'Screenplay', 'Producer'].includes(c.job)).slice(0, 6).map(c => ({ name: c.name, job: c.job })),
        reviews: (d.reviews?.results || []).slice(0, 6).map(r => ({
          author: r.author, rating: r.author_details?.rating ?? null, date: (r.created_at || '').slice(0, 10),
          content: (r.content || '').length > 700 ? r.content.slice(0, 700).trim() + '...' : (r.content || ''), url: r.url
        })),
        similar: (d.similar?.results || []).filter(x => x.poster_path).slice(0, 12).map(x => ({ title: x.title || x.name, year: (x.release_date || x.first_air_date || '').slice(0, 4), poster: tmdbImg(x.poster_path, 'w342'), rating: Math.round((x.vote_average || 0) * 10) / 10 }))
      });
    }
    const details = detailCache.get(key);
    res.json({ title: t, details: t.trailerKey ? { ...details, trailer: t.trailerKey } : details });
  } catch (e) {
    res.json({ ...base, error: e.message });
  }
});

refreshPopularity();
setInterval(refreshPopularity, 24 * 60 * 60 * 1000); // TMDB recalculates popularity daily

// Titles added before categories were automatic: fix any still stuck on "General".
(async () => {
  const titles = loadTitles();
  let changed = 0;
  for (const t of titles.filter(x => !x.category || x.category === 'General')) {
    const c = await inferCategory(t);
    if (c) { t.category = c; changed++; }
  }
  // Anime get every TMDB genre (so One-Punch Man shows under both Action and Comedy) and a real category instead of "Animation".
  for (const t of titles.filter(x => x.isAnime && !x.genres)) {
    const g = await inferGenres(t);
    if (!g) continue;
    t.genres = g;
    if (!t.category || t.category === 'General' || t.category === 'Animation') t.category = animeCategory(g) || t.category;
    changed++;
  }
  if (changed) { saveTitles(titles); console.log(`Categorised ${changed} existing title(s) from TMDB`); }
})();

app.listen(PORT, () => console.log(`YOUFLIX running at http://localhost:${PORT}`));
