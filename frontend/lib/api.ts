// lib/api.ts — API client for FastAPI backend
import axios from 'axios'

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

const api = axios.create({
  baseURL: API_URL,
  headers: { 'Content-Type': 'application/json' },
  withCredentials: true, // Crucial: sends HTTP-only secure cookies automatically
})

// Read cookie helper
export function getCookie(name: string): string | null {
  if (typeof document === 'undefined') return null
  const value = `; ${document.cookie}`
  const parts = value.split(`; ${name}=`)
  if (parts.length === 2) return parts.pop()?.split(';').shift() || null
  return null
}

// Attach CSRF token on mutating requests for double-submit cookie validation
api.interceptors.request.use((config) => {
  if (config.method && ['post', 'put', 'delete', 'patch'].includes(config.method.toLowerCase())) {
    const csrfToken = getCookie('csrf_token')
    if (csrfToken) {
      config.headers['X-CSRF-Token'] = csrfToken
    }
  }
  return config
})

// Redirect to login on 401
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      if (typeof window !== 'undefined') {
        // Clear cookies and session storage on 401
        document.cookie = 'user=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;'
        localStorage.removeItem('fraud-detection-store')
        window.location.href = '/auth/login'
      }
    }
    return Promise.reject(err)
  }
)

// ─── Auth ───────────────────────────────
export const authAPI = {
  login: (username: string, password: string) => {
    const form = new FormData()
    form.append('username', username)
    form.append('password', password)
    return api.post('/api/auth/login', form, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
  register: (data: any) => api.post('/api/auth/register', data),
  me: ()              => api.get('/api/auth/me'),
  logout: ()          => api.post('/api/auth/logout'),
}

// ─── Predict ────────────────────────────
export const predictAPI = {
  single:      (data: any) => api.post('/api/predict/transaction', data),
  batch:       (data: any) => api.post('/api/predict/batch', data),
  batchFile:   (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api.post('/api/predict/batch-file', form, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
  batchResult: (id: string) => api.get(`/api/predict/batch/${id}`),
}

// ─── Transactions ────────────────────────
export const transactionsAPI = {
  list:   (params?: any) => api.get('/api/transactions', { params }),
  get:    (id: string)   => api.get(`/api/transactions/${id}`),
  flagged:(limit = 10)   => api.get(`/api/transactions/flagged?limit=${limit}`),
  review: (id: string, data: any) => api.put(`/api/transactions/${id}/review`, data),
}

// ─── Analytics ───────────────────────────
export const analyticsAPI = {
  stats:             () => api.get('/api/analytics/stats'),
  trends:            (days = 7) => api.get(`/api/analytics/trends?days=${days}`),
  riskDistribution:  () => api.get('/api/analytics/risk-distribution'),
  topFeatures:       () => api.get('/api/analytics/top-features'),
  scoreDistribution: () => api.get('/api/analytics/score-distribution'),
}

export default api