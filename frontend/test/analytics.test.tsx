import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import AnalyticsPage from '@/app/analytics/page'
import { analyticsAPI } from '@/lib/api'
import { ThemeProvider } from '@/app/components/ThemeContext'
import { ToastProvider } from '@/app/components/Toast'

vi.mock('@/lib/api', () => {
  return {
    analyticsAPI: {
      stats: vi.fn(),
      trends: vi.fn(),
      riskDistribution: vi.fn(),
      topFeatures: vi.fn(),
      scoreDistribution: vi.fn(),
    },
    default: {},
  }
})

const renderWithProviders = (ui: React.ReactElement) => {
  return render(
    <ToastProvider>
      <ThemeProvider>
        {ui}
      </ThemeProvider>
    </ToastProvider>
  )
}

describe('AnalyticsPage Component', () => {
  const mockStats = {
    total_transactions: 1000,
    total_fraud: 10,
    fraud_rate: 1.0,
    avg_fraud_score: 50.0,
    total_amount: 15000000,
    pending_review: 5,
    flagged_count: 5,
    approved_count: 5,
    rejected_count: 5,
  }

  const mockTrends = [
    { date: '2026-06-16', total: 50, fraud: 0 },
    { date: '2026-06-17', total: 50, fraud: 1 },
  ]

  const mockRisk = [
    { risk_level: 'HIGH', count: 5, percentage: 50 },
    { risk_level: 'MEDIUM', count: 3, percentage: 30 },
    { risk_level: 'LOW', count: 2, percentage: 20 },
  ]

  const mockFeatures = [
    { feature: 'V14', avg_shap_impact: 0.15, frequency: 80 },
    { feature: 'V17', avg_shap_impact: 0.10, frequency: 50 },
  ]

  const mockScore = [
    { range: '0.0-0.2', count: 800 },
    { range: '0.2-0.4', count: 100 },
    { range: '0.4-0.6', count: 50 },
    { range: '0.6-0.8', count: 30 },
    { range: '0.8-1.0', count: 20 },
  ]

  beforeEach(() => {
    vi.clearAllMocks()
    
    vi.mocked(analyticsAPI.stats).mockResolvedValue({ data: mockStats } as any)
    vi.mocked(analyticsAPI.trends).mockResolvedValue({ data: mockTrends } as any)
    vi.mocked(analyticsAPI.riskDistribution).mockResolvedValue({ data: mockRisk } as any)
    vi.mocked(analyticsAPI.topFeatures).mockResolvedValue({ data: mockFeatures } as any)
    vi.mocked(analyticsAPI.scoreDistribution).mockResolvedValue({ data: mockScore } as any)
  })

  it('renders analytics data successfully', async () => {
    renderWithProviders(<AnalyticsPage />)

    await waitFor(() => {
      expect(screen.getByText('1,000')).toBeInTheDocument() // total transactions
      expect(screen.getByText('10')).toBeInTheDocument()    // fraud count
      expect(screen.getByText('₹150.0L')).toBeInTheDocument() // processed volume amount
    })

    // Check if model features are listed
    expect(screen.getByText('V14')).toBeInTheDocument()
    expect(screen.getByText('V17')).toBeInTheDocument()
  })

  it('allows switching time windows (7d / 14d / 30d)', async () => {
    renderWithProviders(<AnalyticsPage />)

    await waitFor(() => {
      expect(analyticsAPI.trends).toHaveBeenCalledWith(7)
    })

    const btn14 = screen.getByRole('button', { name: '14d' })
    fireEvent.click(btn14)

    await waitFor(() => {
      expect(analyticsAPI.trends).toHaveBeenCalledWith(14)
    })

    const btn30 = screen.getByRole('button', { name: '30d' })
    fireEvent.click(btn30)

    await waitFor(() => {
      expect(analyticsAPI.trends).toHaveBeenCalledWith(30)
    })
  })

  it('handles empty response gracefully', async () => {
    // Return empty datasets
    vi.mocked(analyticsAPI.trends).mockResolvedValueOnce({ data: [] } as any)
    vi.mocked(analyticsAPI.topFeatures).mockResolvedValueOnce({ data: [] } as any)
    vi.mocked(analyticsAPI.riskDistribution).mockResolvedValueOnce({ data: [] } as any)

    renderWithProviders(<AnalyticsPage />)

    await waitFor(() => {
      expect(screen.getByText('Total Transactions')).toBeInTheDocument()
    })
  })

  it('renders error page state when API fails', async () => {
    vi.mocked(analyticsAPI.stats).mockRejectedValueOnce(new Error('Network error'))

    renderWithProviders(<AnalyticsPage />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Failed to Load Analytics/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /Retry Loading/i })).toBeInTheDocument()
    })
  })
})
