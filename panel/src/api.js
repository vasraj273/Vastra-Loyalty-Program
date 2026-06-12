// Dev: vite proxy at /api -> :8000. Production: panel is served by the API
// itself at /panel, so requests go same-origin.
const BASE = import.meta.env.DEV ? '/api' : ''

export const getToken = () => localStorage.getItem('vl_token')
export const getUser = () => {
  try {
    return JSON.parse(localStorage.getItem('vl_user'))
  } catch {
    return null
  }
}

export function setSession(token, user) {
  localStorage.setItem('vl_token', token)
  localStorage.setItem('vl_user', JSON.stringify(user))
}

export function clearSession() {
  localStorage.removeItem('vl_token')
  localStorage.removeItem('vl_user')
}

async function request(path, options = {}) {
  options.headers = { 'Content-Type': 'application/json', ...options.headers }
  const token = getToken()
  if (token) options.headers.Authorization = `Bearer ${token}`
  const res = await fetch(BASE + path, options)
  if (res.status === 401) {
    clearSession()
    window.dispatchEvent(new Event('vl-logout'))
    throw new Error('Session expired — log in again')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch { /* not json */ }
    throw new Error(detail)
  }
  if (res.status === 204) return null
  return res.json()
}

export const get = (path) => request(path)
export const post = (path, body) =>
  request(path, { method: 'POST', body: JSON.stringify(body) })
export const patch = (path, body) =>
  request(path, { method: 'PATCH', body: JSON.stringify(body) })
export const del = (path) => request(path, { method: 'DELETE' })

export const printUrl = (batchId) =>
  `${BASE}/qr/batches/${batchId}/print?token=${encodeURIComponent(getToken())}`
