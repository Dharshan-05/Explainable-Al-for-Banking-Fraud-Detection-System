import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react'
import TransactionsPage from '@/app/page'
import { transactionsAPI } from '@/lib/api'
import { ThemeProvider } from '@/app/components/ThemeContext'
import { ToastProvider } from '@/app/components/Toast'

vi.mock('@/lib/api', () => {
  return {
    transactionsAPI: {
      list: vi.fn(),
      flagged: vi.fn(),
    },
    predictAPI: {
      batch: vi.fn(),
      batchFile: vi.fn(),
      batchResult: vi.fn(),
      single: vi.fn(),
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

describe('Pagination and Filter Race Condition Safeguards (app/page.tsx)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches page 1 exactly once on initial mount', async () => {
    vi.mocked(transactionsAPI.list).mockResolvedValueOnce({
      data: {
        transactions: [],
        total: 0,
      },
    } as any)

    renderWithProviders(<TransactionsPage />)

    await waitFor(() => {
      expect(transactionsAPI.list).toHaveBeenCalledTimes(1)
    })

    expect(transactionsAPI.list).toHaveBeenCalledWith({
      page: 1,
      per_page: 15,
    })
  })

  it('triggers exactly one request for page 1 when changing filter from page 1', async () => {
    vi.mocked(transactionsAPI.list).mockResolvedValue({
      data: {
        transactions: [],
        total: 10,
      },
    } as any)

    const { container } = renderWithProviders(<TransactionsPage />)

    await waitFor(() => {
      expect(transactionsAPI.list).toHaveBeenCalledTimes(1)
    })

    // Change Risk filter to HIGH
    const riskSelect = container.querySelectorAll('select')[0]
    expect(riskSelect).toBeDefined()

    await act(async () => {
      fireEvent.change(riskSelect, { target: { value: 'HIGH' } })
    })

    await waitFor(() => {
      expect(transactionsAPI.list).toHaveBeenCalledTimes(2)
    })

    expect(transactionsAPI.list).toHaveBeenLastCalledWith({
      page: 1,
      per_page: 15,
      risk_level: 'HIGH',
    })
  })

  it('resets to page 1 and fetches page 1 without requesting old page when filter changes from page 2', async () => {
    // 30 total records -> 2 pages of 15
    vi.mocked(transactionsAPI.list).mockResolvedValue({
      data: {
        transactions: [
          { id: 'tx-1', amount: 100, risk_level: 'LOW', fraud_score: 0.1, status: 'approved', created_at: '2026-01-01' },
        ],
        total: 30,
      },
    } as any)

    const { container } = renderWithProviders(<TransactionsPage />)

    await waitFor(() => {
      expect(transactionsAPI.list).toHaveBeenCalledTimes(1)
    })

    // Navigate to page 2
    const nextBtn = screen.getByText('Next →')
    await act(async () => {
      fireEvent.click(nextBtn)
    })

    await waitFor(() => {
      expect(transactionsAPI.list).toHaveBeenCalledTimes(2)
    })
    expect(transactionsAPI.list).toHaveBeenLastCalledWith({
      page: 2,
      per_page: 15,
    })

    // Clear calls tracking
    vi.mocked(transactionsAPI.list).mockClear()

    // Change status filter while on page 2
    const statusSelect = container.querySelectorAll('select')[1]
    expect(statusSelect).toBeDefined()

    await act(async () => {
      fireEvent.change(statusSelect, { target: { value: 'flagged' } })
    })

    await waitFor(() => {
      expect(transactionsAPI.list).toHaveBeenCalledTimes(1)
    })

    // Verify it requested page 1, and NEVER requested page 2 with flagged
    expect(transactionsAPI.list).toHaveBeenCalledWith({
      page: 1,
      per_page: 15,
      status: 'flagged',
    })
  })

  it('resets to page 1 and fetches unfiltered results when Clear is clicked from page 2', async () => {
    vi.mocked(transactionsAPI.list).mockResolvedValue({
      data: {
        transactions: [],
        total: 30,
      },
    } as any)

    const { container } = renderWithProviders(<TransactionsPage />)

    await waitFor(() => {
      expect(transactionsAPI.list).toHaveBeenCalledTimes(1)
    })

    // Set a filter first
    const riskSelect = container.querySelectorAll('select')[0]
    await act(async () => {
      fireEvent.change(riskSelect, { target: { value: 'HIGH' } })
    })

    await waitFor(() => {
      expect(transactionsAPI.list).toHaveBeenCalledTimes(2)
    })

    // Navigate to page 2
    const nextBtn = screen.getByText('Next →')
    await act(async () => {
      fireEvent.click(nextBtn)
    })

    await waitFor(() => {
      expect(transactionsAPI.list).toHaveBeenCalledTimes(3)
    })
    expect(transactionsAPI.list).toHaveBeenLastCalledWith({
      page: 2,
      per_page: 15,
      risk_level: 'HIGH',
    })

    vi.mocked(transactionsAPI.list).mockClear()

    // Click Clear button
    const clearBtn = screen.getByText('✕ Clear')
    await act(async () => {
      fireEvent.click(clearBtn)
    })

    await waitFor(() => {
      expect(transactionsAPI.list).toHaveBeenCalledTimes(1)
    })

    expect(transactionsAPI.list).toHaveBeenCalledWith({
      page: 1,
      per_page: 15,
    })
  })

  it('discards stale out-of-order responses so older requests do not overwrite newer results', async () => {
    let resolveFirstReq: (val: any) => void = () => {}
    let resolveSecondReq: (val: any) => void = () => {}

    const firstReqPromise = new Promise(resolve => {
      resolveFirstReq = resolve
    })
    const secondReqPromise = new Promise(resolve => {
      resolveSecondReq = resolve
    })

    // First call returns hanging promise
    vi.mocked(transactionsAPI.list)
      .mockReturnValueOnce(firstReqPromise as any)
      .mockReturnValueOnce(secondReqPromise as any)

    const { container } = renderWithProviders(<TransactionsPage />)

    expect(transactionsAPI.list).toHaveBeenCalledTimes(1)

    // User switches filter, triggering request 2
    const riskSelect = container.querySelectorAll('select')[0]
    await act(async () => {
      fireEvent.change(riskSelect, { target: { value: 'HIGH' } })
    })

    expect(transactionsAPI.list).toHaveBeenCalledTimes(2)

    // Resolve SECOND request first (new data)
    await act(async () => {
      resolveSecondReq({
        data: {
          transactions: [
            { id: 'tx-new-fast', amount: 999, risk_level: 'HIGH', fraud_score: 0.99, status: 'flagged', created_at: '2026-01-02' },
          ],
          total: 1,
        },
      })
    })

    // Table must display newer data (app/page.tsx renders tx.id.slice(0,8)...)
    await waitFor(() => {
      expect(screen.getByText('tx-new-f...')).toBeInTheDocument()
    })

    // Now resolve the FIRST request late (stale data)
    await act(async () => {
      resolveFirstReq({
        data: {
          transactions: [
            { id: 'tx-old-stale', amount: 111, risk_level: 'LOW', fraud_score: 0.1, status: 'approved', created_at: '2026-01-01' },
          ],
          total: 50,
        },
      })
    })

    // Stale data must NOT overwrite tx-new-fast
    expect(screen.getByText('tx-new-f...')).toBeInTheDocument()
    expect(screen.queryByText('tx-old-s...')).not.toBeInTheDocument()
  })
})
