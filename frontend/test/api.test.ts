import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import api from '@/lib/api'

describe('API Client (api.ts)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Clear cookies and localStorage
    if (typeof document !== 'undefined') {
      document.cookie = 'csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;'
      document.cookie = 'user=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;'
    }
    localStorage.clear()
  })

  it('should be configured with withCredentials=true', () => {
    expect(api.defaults.withCredentials).toBe(true)
  })

  it('should use NEXT_PUBLIC_API_URL or default to localhost:8000', () => {
    const expectedBaseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
    expect(api.defaults.baseURL).toBe(expectedBaseUrl)
  })

  it('should not attach JWT Authorization header from localStorage', async () => {
    localStorage.setItem('token', 'fake-jwt-token')
    
    // We can inspect the request configuration before it is sent
    const testConfig = { method: 'get', headers: {} as Record<string, string> }
    const interceptor = (api.interceptors.request as any).handlers[0].fulfilled
    const resultConfig = interceptor(testConfig)
    
    expect(resultConfig.headers['Authorization']).toBeUndefined()
  })

  it('should add X-CSRF-Token header on mutating POST request if csrf_token cookie exists', () => {
    // Inject a fake csrf_token cookie
    document.cookie = 'csrf_token=mocked-csrf-value; path=/;'
    
    const testConfig = { method: 'post', headers: {} as Record<string, string> }
    const interceptor = (api.interceptors.request as any).handlers[0].fulfilled
    const resultConfig = interceptor(testConfig)
    
    expect(resultConfig.headers['X-CSRF-Token']).toBe('mocked-csrf-value')
  })

  it('should NOT add X-CSRF-Token header on GET request even if csrf_token cookie exists', () => {
    document.cookie = 'csrf_token=mocked-csrf-value; path=/;'
    
    const testConfig = { method: 'get', headers: {} as Record<string, string> }
    const interceptor = (api.interceptors.request as any).handlers[0].fulfilled
    const resultConfig = interceptor(testConfig)
    
    expect(resultConfig.headers['X-CSRF-Token']).toBeUndefined()
  })

  it('should handle 401 response by clearing local state cookies and redirecting to login', async () => {
    // Set mock user cookie
    document.cookie = 'user=fake-user; path=/;'
    localStorage.setItem('fraud-detection-store', 'some-persisted-state')

    // Mock window location replace/href
    const originalLocation = window.location
    delete (window as any).location
    window.location = { href: '' } as any

    const responseInterceptorErr = (api.interceptors.response as any).handlers[0].rejected
    
    const mockError = {
      response: {
        status: 401
      }
    }

    await expect(responseInterceptorErr(mockError)).rejects.toEqual(mockError)
    
    // Assert cookies and storage are cleared and redirect occurred
    expect(document.cookie).not.toContain('user=fake-user')
    expect(localStorage.getItem('fraud-detection-store')).toBeNull()
    expect(window.location.href).toBe('/auth/login')

    // Restore location
    Object.defineProperty(window, 'location', {
      configurable: true,
      writable: true,
      value: originalLocation,
    })
  })
})
