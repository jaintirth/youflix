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

// admin: add a title from a YouTube URL
app.post('/api/titles', requireAdmin, async (req, res) => {
  const { url, type, category, year, description, title } = req.body;
  const yt = parseYouTube(String(url || ''));
  if (!yt) return res.status(400).json({ error: 'Not a valid YouTube video or playlist URL' });

  const titles = loadTitles();
  if (titles.some(t => t.youtubeId === yt.id)) {
    return res.status(409).json({ error: 'That YouTube link is already in the catalogue' });
  }
  const meta = await fetchOEmbed(url);
  if (!meta && !title) {
    return res.status(400).json({ error: 'YouTube could not find that link (private or removed?). Enter a title manually to add anyway.' });
  }
  const item = {
    id: crypto.randomUUID(),
    type: type === 'series' ? 'series' : 'movie',
    title: (title || meta.title).trim(),
    description: (description || '').trim(),
    category: (category || 'General').trim(),
    year: year ? Number(year) || null : null,
    kind: yt.kind,
    youtubeId: yt.id,
    youtubeUrl: url.trim(),
    thumbnail: yt.kind === 'video'
      ? `https://i.ytimg.com/vi/${yt.id}/hqdefault.jpg`
      : (meta && meta.thumbnail_url) || null,
    channel: meta ? meta.author_name : null,
    addedAt: new Date().toISOString()
  };
  titles.unshift(item);
  saveTitles(titles);
  res.status(201).json(item);
});

app.delete('/api/titles/:id', requireAdmin, (req, res) => {
  const titles = loadTitles();
  const next = titles.filter(t => t.id !== req.params.id);
  if (next.length === titles.length) return res.status(404).json({ error: 'Not found' });
  saveTitles(next);
  res.json({ ok: true });
});

app.listen(PORT, () => console.log(`YOUFLIX running at http://localhost:${PORT}`));
