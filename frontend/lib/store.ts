// ============================================================
//  lib/store.ts  —  Zustand Global State
//  Slices: auth, transactions, alerts
// ============================================================
import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

import { authAPI } from './api'

// ─────────────────────────────────────────
//  Types
// ─────────────────────────────────────────
export interface User {
  id: string
  email: string
  username: string
  full_name: string
  role: string
  is_active: boolean
}

export interface Transaction {
  id: string
  amount: number
  merchant?: string
  merchant_category?: string
  location?: string
  card_last4?: string
  fraud_score?: number
  is_fraud?: boolean
  risk_level?: 'LOW' | 'MEDIUM' | 'HIGH'
  explanation?: string
  status: 'pending' | 'approved' | 'rejected' | 'flagged'
  created_at: string
}

export interface LiveAlert {
  id: string
  type: 'fraud_alert' | 'connected' | 'pong'
  transaction_id?: string
  fraud_score?: number
  fraud_pct?: number
  risk_level?: string
  amount?: number
  merchant?: string
  explanation?: string
  timestamp: number
}

export interface TransactionFilters {
  risk_level: string
  status: string
  is_fraud: string
  page: number
}

// ─────────────────────────────────────────
//  Store
// ─────────────────────────────────────────
export interface AppStore {
  // ── Auth slice ────────────────────────
  user: User | null
  setAuth: (user: User) => void
  logout: () => Promise<void>

  // ── Transactions slice ─────────────────
  transactions: Transaction[]
  totalTransactions: number
  transactionFilters: TransactionFilters
  isLoadingTransactions: boolean
  setTransactions: (items: Transaction[], total: number) => void
  setTransactionFilters: (filters: Partial<TransactionFilters>) => void
  setTransactionLoading: (loading: boolean) => void

  // ── Live Alerts slice ─────────────────
  liveAlerts: LiveAlert[]
  addAlert: (alert: Omit<LiveAlert, 'id' | 'timestamp'>) => void
  clearAlerts: () => void
  removeAlert: (id: string) => void
}

export const useStore = create<AppStore>()(
  persist(
    (set, get) => ({
      // ── Auth ─────────────────────────────
      user: null,
      setAuth: (user) => set({ user }),
      logout: async () => {
        try {
          await authAPI.logout()
        } catch (e) {
          // ignore network failure on logout
        }
        set({ user: null, transactions: [], liveAlerts: [] })
        // Clear non-HttpOnly browser cookies
        document.cookie = 'user=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;'
        document.cookie = 'csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;'
      },

      // ── Transactions ──────────────────────
      transactions: [],
      totalTransactions: 0,
      isLoadingTransactions: false,
      transactionFilters: {
        risk_level: '',
        status: '',
        is_fraud: '',
        page: 1,
      },
      setTransactions: (items, total) =>
        set({ transactions: items, totalTransactions: total }),
      setTransactionFilters: (filters) =>
        set((s) => ({
          transactionFilters: { ...s.transactionFilters, ...filters },
        })),
      setTransactionLoading: (loading) =>
        set({ isLoadingTransactions: loading }),

      // ── Live Alerts ───────────────────────
      liveAlerts: [],
      addAlert: (alert) =>
        set((s) => {
          const newAlert: LiveAlert = {
            ...alert,
            id: Math.random().toString(36).slice(2),
            timestamp: Date.now(),
          }
          // Keep only last 20 alerts
          return { liveAlerts: [newAlert, ...s.liveAlerts].slice(0, 20) }
        }),
      clearAlerts: () => set({ liveAlerts: [] }),
      removeAlert: (id) =>
        set((s) => ({
          liveAlerts: s.liveAlerts.filter((a) => a.id !== id),
        })),
    }),
    {
      name: 'fraud-detection-store',
      storage: createJSONStorage(() => localStorage),
      // Only persist auth data — user info is persisted, token is not
      partialize: (state) => ({ user: state.user }),
    }
  )
)
