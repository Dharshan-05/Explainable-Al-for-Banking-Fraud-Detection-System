import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import LoginPage from '@/app/auth/login/page'
import { authAPI } from '@/lib/api'
import { useStore } from '@/lib/store'

// Mock api module
vi.mock('@/lib/api', () => {
  return {
    authAPI: {
      login: vi.fn(),
    },
    default: {}
  }
})

describe('LoginPage Component', () => {
  const originalLocation = window.location
  let mockLocationReplace = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    document.cookie = 'token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;'
    document.cookie = 'user=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;'
    
    // Reset Zustand store state
    useStore.setState({ user: null })

    // Mock window.location.replace
    delete (window as any).location
    mockLocationReplace = vi.fn()
    window.location = { replace: mockLocationReplace } as any
  })

  afterEach(() => {
    // Restore window.location
    Object.defineProperty(window, 'location', {
      configurable: true,
      writable: true,
      value: originalLocation,
    })
  })

  it('renders login form inputs and submit button', () => {
    render(<LoginPage />)
    
    expect(screen.getByPlaceholderText(/Enter username/i)).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/Enter password/i)).toBeInTheDocument()
    expect(screen.getByText(/USERNAME/i)).toBeInTheDocument()
    expect(screen.getByText(/PASSWORD/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /SIGN IN/i })).toBeInTheDocument()
  })

  it('calls authAPI.login and redirects on success without client-side JWT storage', async () => {
    const mockUser = {
      id: 'user-id',
      email: 'analyst@example.com',
      username: 'analyst1',
      full_name: 'Test Analyst',
      role: 'analyst',
      is_active: true,
    }

    vi.mocked(authAPI.login).mockResolvedValueOnce({
      data: {
        access_token: 'fake-jwt-response-token',
        token_type: 'bearer',
        user: mockUser,
      },
    } as any)

    render(<LoginPage />)

    const usernameInput = screen.getByPlaceholderText(/Enter username/i)
    const passwordInput = screen.getByPlaceholderText(/Enter password/i)
    const submitBtn = screen.getByRole('button', { name: /SIGN IN/i })

    // Fill in credentials
    fireEvent.change(usernameInput, { target: { value: 'analyst1' } })
    fireEvent.change(passwordInput, { target: { value: 'password123' } })

    // Submit
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(authAPI.login).toHaveBeenCalledWith('analyst1', 'password123')
    })

    // Check store auth is populated
    expect(useStore.getState().user).toEqual(mockUser)

    // Check localStorage does not store token
    expect(localStorage.getItem('token')).toBeNull()

    // Check cookies: user should exist, token should NOT exist client-side
    expect(document.cookie).toContain('user=')
    expect(document.cookie).not.toContain('token=fake-jwt-response-token')

    // Redirect should be called via window.location.replace
    expect(mockLocationReplace).toHaveBeenCalledWith('/dashboard')
  })

  it('displays error message on failed login', async () => {
    vi.mocked(authAPI.login).mockRejectedValueOnce({
      response: {
        data: {
          detail: 'Invalid username or password',
        },
      },
    } as any)

    render(<LoginPage />)

    const usernameInput = screen.getByPlaceholderText(/Enter username/i)
    const passwordInput = screen.getByPlaceholderText(/Enter password/i)
    const submitBtn = screen.getByRole('button', { name: /SIGN IN/i })

    fireEvent.change(usernameInput, { target: { value: 'wronguser' } })
    fireEvent.change(passwordInput, { target: { value: 'wrongpass' } })
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(screen.getByText(/Invalid username or password/i)).toBeInTheDocument()
    })

    // Store user should remain null
    expect(useStore.getState().user).toBeNull()
  })
})
