import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import TransactionsPage from '@/app/page'
import { transactionsAPI, predictAPI } from '@/lib/api'
import { ThemeProvider } from '@/app/components/ThemeContext'
import { ToastProvider } from '@/app/components/Toast'

vi.mock('@/lib/api', () => {
  return {
    transactionsAPI: {
      list: vi.fn(),
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

describe('CSV Batch Upload Flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    vi.mocked(transactionsAPI.list).mockResolvedValue({
      data: {
        transactions: [],
        total: 0,
      },
    } as any)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('triggers a single batchFile API call and polls for progress updates', async () => {
    // 1. Mock the initial batch file upload trigger
    vi.mocked(predictAPI.batchFile).mockResolvedValueOnce({
      data: {
        task_id: 'mock-task-123',
      },
    } as any)

    // 2. Mock polling responses
    // First poll returns progress
    vi.mocked(predictAPI.batchResult).mockResolvedValueOnce({
      data: {
        status: 'PROGRESS',
        result: {
          total: 10,
          processed: 5,
          failed: 1,
          fraud_count: 2,
          current_chunk: 1,
          total_chunks: 2,
        },
      },
    } as any)

    // Second poll returns success
    vi.mocked(predictAPI.batchResult).mockResolvedValueOnce({
      data: {
        status: 'SUCCESS',
        result: {
          total: 10,
          processed: 9,
          failed: 1,
          fraud_count: 3,
          current_chunk: 2,
          total_chunks: 2,
          duration: 2.5,
        },
      },
    } as any)

    const { container } = renderWithProviders(<TransactionsPage />)

    const uploadBtn = screen.getByRole('button', { name: /Upload CSV/i })
    expect(uploadBtn).toBeInTheDocument()

    // Simulate selecting a CSV file
    const fileInput = container.querySelector('input[type="file"]')
    expect(fileInput).not.toBeNull()

    const mockCSVContent = 
      'Amount,Time,V1,V2,V3,V4,V5,V6,V7,V8,V9,V10,V11,V12,V13,V14,V15,V16,V17,V18,V19,V20,V21,V22,V23,V24,V25,V26,V27,V28\n' +
      '150.0,45000,0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9,1.0,1.1,1.2,1.3,1.4,1.5,1.6,1.7,1.8,1.9,2.0,2.1,2.2,2.3,2.4,2.5,2.6,2.7,2.8\n'

    const file = new File([mockCSVContent], 'test.csv', { type: 'text/csv' })

    // Trigger upload
    await act(async () => {
      fireEvent.change(fileInput!, { target: { files: [file] } })
    })

    // Wait for the async API trigger to complete
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(predictAPI.batchFile).toHaveBeenCalledTimes(1)
    expect(predictAPI.batchFile).toHaveBeenCalledWith(file)
    expect(predictAPI.batch).not.toHaveBeenCalled()
    expect(predictAPI.single).not.toHaveBeenCalled()

    // Assert processing state displays (exact match to avoid parent elements)
    expect(screen.getByText('PROCESSING BATCH...')).toBeInTheDocument()

    // Advance timers to trigger the first poll interval (1500ms)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500)
    })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    // First poll assertions
    expect(screen.getByText('Processed:').nextSibling?.textContent).toBe('5')
    expect(screen.getByText('Failed:').nextSibling?.textContent).toBe('1')
    expect(screen.getByText('Fraud Identified:').nextSibling?.textContent).toBe('2')
    expect(screen.getByText(/Processing chunk 1 of 2/i)).toBeInTheDocument()

    // Advance timers to trigger the second poll interval (1500ms)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500)
    })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    // Success poll assertions
    expect(screen.getByText('BATCH INFERENCE SUCCESS')).toBeInTheDocument()
    expect(screen.getByText('Processed:').nextSibling?.textContent).toBe('9')
    expect(screen.getByText('Failed:').nextSibling?.textContent).toBe('1')
    expect(screen.getByText('Fraud Identified:').nextSibling?.textContent).toBe('3')
    expect(screen.getByText(/2\.5s/)).toBeInTheDocument() // elapsed time
  })

  it('renders a safe error message on batch task failure', async () => {
    vi.mocked(predictAPI.batchFile).mockResolvedValueOnce({
      data: {
        task_id: 'mock-task-fail',
      },
    } as any)

    // Mock failure status
    vi.mocked(predictAPI.batchResult).mockResolvedValueOnce({
      data: {
        status: 'FAILURE',
        error: 'Out of memory during model execution',
      },
    } as any)

    const { container } = renderWithProviders(<TransactionsPage />)

    const fileInput = container.querySelector('input[type="file"]')
    const mockCSVContent = 'Amount,Time,V1,V2\n100,50000,0,0\n'
    const file = new File([mockCSVContent], 'test.csv', { type: 'text/csv' })

    await act(async () => {
      fireEvent.change(fileInput!, { target: { files: [file] } })
    })

    // Wait for the async batch API trigger to complete
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(predictAPI.batchFile).toHaveBeenCalled()

    // Advance timer to trigger poll
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500)
    })
    await act(async () => {
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(screen.getByText('BATCH INFERENCE FAILED')).toBeInTheDocument()
  })
})
