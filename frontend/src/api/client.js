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

// Auto-logout on 401
api.interceptors.response.use(
  res => res,
  err => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export default api
