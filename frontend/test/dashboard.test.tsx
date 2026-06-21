import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import Dashboard from '@/app/dashboard/page'
import { analyticsAPI, transactionsAPI } from '@/lib/api'
import { ThemeProvider } from '@/app/components/ThemeContext'
import { ToastProvider } from '@/app/components/Toast'

// Mock api methods
vi.mock('@/lib/api', () => {
  return {
    analyticsAPI: {
      stats: vi.fn(),
      trends: vi.fn(),
    },
    transactionsAPI: {
      flagged: vi.fn(),
    },
    default: {},
  }
})

// Wrapper to provide Theme and Toast contexts
const renderWithProviders = (ui: React.ReactElement) => {
  return render(
    <ToastProvider>
      <ThemeProvider>
        {ui}
      </ThemeProvider>
    </ToastProvider>
  )
}

describe('Dashboard Component', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders loading skeleton state initially', () => {
    // Keep APIs unresolved to test loading state
    vi.mocked(analyticsAPI.stats).mockReturnValue(new Promise(() => {}))
    vi.mocked(analyticsAPI.trends).mockReturnValue(new Promise(() => {}))
    vi.mocked(transactionsAPI.flagged).mockReturnValue(new Promise(() => {}))

    renderWithProviders(<Dashboard />)
    
    // Skeletons are rendered during loading
    expect(screen.getByText(/LIVE MONITORING/i)).toBeInTheDocument()
  })

  it('renders stats fetched from mocked analytics API successfully', async () => {
    const mockStats = {
      total_transactions: 1250,
      total_fraud: 15,
      fraud_rate: 1.2,
      total_amount_at_risk: 45000.0,
      high_risk_count: 5,
      medium_risk_count: 10,
      low_risk_count: 1235,
      pending_review: 8,
    }

    const mockTrends = [
      { date: '2026-06-10', total: 100, fraud: 1 },
      { date: '2026-06-11', total: 120, fraud: 2 },
    ]

    const mockFlagged = [
      { id: '1', amount: 1500, merchant: 'Target', risk_level: 'HIGH', status: 'pending', created_at: '2026-06-17T00:00:00Z' }
    ]

    vi.mocked(analyticsAPI.stats).mockResolvedValueOnce({ data: mockStats } as any)
    vi.mocked(analyticsAPI.trends).mockResolvedValueOnce({ data: mockTrends } as any)
    vi.mocked(transactionsAPI.flagged).mockResolvedValueOnce({ data: mockFlagged } as any)

    renderWithProviders(<Dashboard />)

    // Wait for the stats to load and verify their rendering
    await waitFor(() => {
      expect(screen.getByText('1,250')).toBeInTheDocument() // total transactions
      expect(screen.getByText(/1\.2%/)).toBeInTheDocument()  // fraud rate
      expect(screen.getByText('8')).toBeInTheDocument()     // pending review
    })

    // Verify raw transaction details are not fetched as main metrics (metrics fetched from analyticsAPI.stats)
    expect(analyticsAPI.stats).toHaveBeenCalled()
    expect(transactionsAPI.flagged).toHaveBeenCalledWith(5)
  })

  it('renders generic error state and allows retry', async () => {
    // Mock API failure
    vi.mocked(analyticsAPI.stats).mockRejectedValueOnce(new Error('Database error'))
    vi.mocked(analyticsAPI.trends).mockRejectedValueOnce(new Error('Database error'))
    vi.mocked(transactionsAPI.flagged).mockRejectedValueOnce(new Error('Database error'))

    renderWithProviders(<Dashboard />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Failed to Load Dashboard/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /Retry/i })).toBeInTheDocument()
    })

    // Setup success on retry
    const mockStats = { total_transactions: 100, total_fraud: 1, fraud_rate: 1.0, total_amount_at_risk: 1000, high_risk_count: 1, medium_risk_count: 1, low_risk_count: 98, pending_review: 1 }
    vi.mocked(analyticsAPI.stats).mockResolvedValueOnce({ data: mockStats } as any)
    vi.mocked(analyticsAPI.trends).mockResolvedValueOnce({ data: [] } as any)
    vi.mocked(transactionsAPI.flagged).mockResolvedValueOnce({ data: [] } as any)

    // Click retry
    fireEvent.click(screen.getByRole('button', { name: /Retry/i }))

    await waitFor(() => {
      expect(screen.getByText('100')).toBeInTheDocument()
    })
  })

  it('renders forbidden access denied state for customer roles', async () => {
    // Mock 403 Forbidden response
    vi.mocked(analyticsAPI.stats).mockRejectedValueOnce({
      response: {
        status: 403
      }
    } as any)
    vi.mocked(analyticsAPI.trends).mockRejectedValueOnce({ response: { status: 403 } } as any)
    vi.mocked(transactionsAPI.flagged).mockRejectedValueOnce({ response: { status: 403 } } as any)

    renderWithProviders(<Dashboard />)

    await waitFor(() => {
      expect(screen.getByText(/Access Denied/i)).toBeInTheDocument()
      expect(screen.getByText(/You do not have the required analyst or admin permissions/i)).toBeInTheDocument()
      // Retry button should not render for forbidden access
      expect(screen.queryByRole('button', { name: /RETRY/i })).toBeNull()
    })
  })
})
