// Static host for the YOUFLIX frontend. No dependencies.
//
// The site is plain HTML/CSS/JS (frontend/); all data comes from the API, which runs elsewhere (Wasmer). This tiny
// server exists so a Render Node web service (`npm start`) can keep serving the site at its existing address:
//   - serves frontend/
//   - builds /config.js from the API_BASE environment variable at request time (no rebuild to change the API address)
//   - keeps the old clean URLs working: /movie/<id> -> movie.html, /admin -> admin.html
//
//   API_BASE=https://your-api.wasmer.app PORT=3000 node server.js
'use strict';
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const PORT = Number(process.env.PORT) || 3000;
const ROOT = path.join(__dirname, 'frontend');
const API_BASE = (process.env.API_BASE || '').trim().replace(/\/+$/, '');

if (!API_BASE) {
  console.warn('API_BASE is not set: the site will call its own address for /api and show no titles. Set it to the API URL.');
}

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.txt': 'text/plain; charset=utf-8',
  '.woff2': 'font/woff2',
};

const HEADERS = { 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'strict-origin-when-cross-origin' };

function send(req, res, status, headers, body) {
  res.writeHead(status, { ...HEADERS, ...headers });
  res.end(req.method === 'HEAD' ? undefined : body);
}

function sendText(req, res, status, text) {
  send(req, res, status, { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store' }, text);
}

function sendFile(req, res, file) {
  fs.stat(file, (err, stat) => {
    if (err || !stat.isFile()) return sendText(req, res, 404, 'Not found');
    // Revalidate on every load (small site, and a deploy must show up at once), but answer 304 when nothing changed.
    const etag = '"' + crypto.createHash('sha1').update(`${stat.size}-${stat.mtimeMs}`).digest('hex').slice(0, 16) + '"';
    const headers = {
      'Content-Type': TYPES[path.extname(file).toLowerCase()] || 'application/octet-stream',
      'Cache-Control': 'no-cache',
      ETag: etag,
    };
    if (req.headers['if-none-match'] === etag) return send(req, res, 304, headers);
    headers['Content-Length'] = stat.size;
    res.writeHead(200, { ...HEADERS, ...headers });
    if (req.method === 'HEAD') return res.end();
    fs.createReadStream(file).on('error', () => res.destroy()).pipe(res);
  });
}

const server = http.createServer((req, res) => {
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.setHeader('Allow', 'GET, HEAD');
    return sendText(req, res, 405, 'Method not allowed');
  }

  let pathname;
  try {
    pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
  } catch {
    return sendText(req, res, 400, 'Bad request');
  }
  if (pathname.includes('\0')) return sendText(req, res, 400, 'Bad request');

  if (pathname === '/healthz') return sendText(req, res, 200, 'ok');

  if (pathname === '/config.js') {
    const body = `window.YOUFLIX_API_BASE = ${JSON.stringify(API_BASE)};\n`;
    return send(req, res, 200, { 'Content-Type': TYPES['.js'], 'Cache-Control': 'no-store' }, body);
  }

  // Clean URLs from the old site.
  if (pathname === '/admin') return sendFile(req, res, path.join(ROOT, 'admin.html'));
  if (/^\/movie\/[^/]+\/?$/.test(pathname)) return sendFile(req, res, path.join(ROOT, 'movie.html'));

  if (pathname.endsWith('/')) pathname += 'index.html';
  const file = path.normalize(path.join(ROOT, pathname));
  if (file !== ROOT && !file.startsWith(ROOT + path.sep)) return sendText(req, res, 404, 'Not found');   // no ../ escapes
  sendFile(req, res, file);
});

server.listen(PORT, () => console.log(`YOUFLIX frontend on port ${PORT}, API ${API_BASE || '(same origin)'}`));
