import axios from 'axios'

let apiURL = import.meta.env.VITE_API_URL || '/api'
if (apiURL !== '/api' && !apiURL.endsWith('/api')) {
  apiURL = apiURL.replace(/\/$/, '') + '/api'
}

const api = axios.create({
  baseURL: apiURL,
  headers: { 'Content-Type': 'application/json' },
})

// Attach JWT token to every request automatically
api.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Endpoints where a 401 means "wrong credentials", not "session expired".
// Redirecting on these would reload the page and wipe the error message.
const NO_REDIRECT_ON_401 = ['/auth/login', '/auth/register']

// Auto-logout on 401
api.interceptors.response.use(
  res => res,
  err => {
    const url = err.config?.url || ''
    const isAuthAttempt = NO_REDIRECT_ON_401.some(p => url.endsWith(p))
    if (err.response?.status === 401 && !isAuthAttempt) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      if (window.location.pathname !== '/login') window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

/**
 * Turn an axios error into a displayable string.
 * FastAPI validation errors (422) return `detail` as an array of objects —
 * rendering that directly crashes React ("Objects are not valid as a React child").
 */
export function errorMessage(err, fallback = 'Something went wrong. Please try again.') {
  const detail = err?.response?.data?.detail
  if (!detail) return fallback
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    const msgs = detail
      .map(d => (typeof d === 'string' ? d : d?.msg))
      .filter(Boolean)
      .map(m => m.replace(/^Value error, /, ''))
    return msgs.length ? msgs.join(' · ') : fallback
  }
  return fallback
}

export default api
