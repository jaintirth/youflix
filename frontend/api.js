// fetch() wrapper: prefixes the API base URL and attaches the admin bearer token if there is one.
const TOKEN_KEY = 'yf_admin_token';
const getToken = () => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } };
const setToken = t => { try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch { /* storage blocked */ } };
function apiFetch(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  const token = getToken();
  if (token) headers.Authorization = 'Bearer ' + token;
  return fetch((window.YOUFLIX_API_BASE || '').replace(/\/$/, '') + path, { ...opts, headers });
}
