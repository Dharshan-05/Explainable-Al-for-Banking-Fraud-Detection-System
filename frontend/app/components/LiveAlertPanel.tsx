'use client'
// ============================================================
//  app/components/LiveAlertPanel.tsx
//  Real-time WebSocket fraud alert feed.
//  Mount this once in your root layout or dashboard page.
// ============================================================
import { useEffect, useRef } from 'react'
import { useStore, LiveAlert } from '@/lib/store'
import type { AppStore } from '@/lib/store'
import { useAlerts } from '@/lib/useAlerts'

export default function LiveAlertPanel() {
  useAlerts()  // establishes + maintains the WebSocket connection

  const alerts      = useStore((s: AppStore) => s.liveAlerts)
  const removeAlert = useStore((s: AppStore) => s.removeAlert)
  const clearAlerts = useStore((s: AppStore) => s.clearAlerts)

  // Auto-dismiss each alert after 8 seconds
  const timers = useRef<Record<string, ReturnType<typeof setTimeout>>>({})
  useEffect(() => {
    alerts.forEach((alert: LiveAlert) => {
      if (!timers.current[alert.id]) {
        timers.current[alert.id] = setTimeout(() => {
          removeAlert(alert.id)
          delete timers.current[alert.id]
        }, 8000)
      }
    })
  }, [alerts, removeAlert])

  if (alerts.length === 0) return null

  return (
    <div
      style={{
        position: 'fixed',
        bottom: '24px',
        right: '24px',
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column-reverse',
        gap: '10px',
        maxWidth: '380px',
        pointerEvents: 'none',
      }}
    >
      {alerts.slice(0, 5).map((alert: LiveAlert) => (
        <AlertCard key={alert.id} alert={alert} onDismiss={() => removeAlert(alert.id)} />
      ))}
      {alerts.length > 5 && (
        <button
          onClick={clearAlerts}
          style={{
            pointerEvents: 'all',
            background: 'rgba(15,20,30,0.9)',
            border: '1px solid rgba(239,68,68,0.3)',
            borderRadius: '10px',
            color: '#f87171',
            padding: '8px 14px',
            fontSize: '12px',
            cursor: 'pointer',
            fontFamily: 'inherit',
          }}
        >
          Clear {alerts.length} alerts
        </button>
      )}
    </div>
  )
}

function AlertCard({ alert, onDismiss }: { alert: LiveAlert; onDismiss: () => void }) {
  return (
    <div
      style={{
        pointerEvents: 'all',
        background: 'rgba(15, 20, 30, 0.96)',
        border: '1px solid rgba(239,68,68,0.5)',
        borderLeft: '4px solid #ef4444',
        borderRadius: '12px',
        padding: '14px 16px',
        backdropFilter: 'blur(12px)',
        boxShadow: '0 8px 32px rgba(239,68,68,0.15), 0 2px 8px rgba(0,0,0,0.4)',
        animation: 'slideInRight 0.3s ease',
        position: 'relative',
      }}
    >
      {/* Dismiss button */}
      <button
        onClick={onDismiss}
        style={{
          position: 'absolute',
          top: '10px',
          right: '10px',
          background: 'transparent',
          border: 'none',
          color: '#4b5563',
          cursor: 'pointer',
          fontSize: '14px',
          lineHeight: 1,
          padding: '2px 5px',
        }}
      >
        ✕
      </button>

      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
        <span style={{ fontSize: '18px' }}>🚨</span>
        <span
          style={{
            fontSize: '13px',
            fontWeight: '800',
            color: '#f87171',
            letterSpacing: '-0.3px',
          }}
        >
          HIGH-RISK FRAUD DETECTED
        </span>
      </div>

      {/* Details */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
        {alert.amount != null && (
          <div style={{ fontSize: '15px', fontWeight: '700', color: '#f0f4ff' }}>
            ₹{Number(alert.amount).toLocaleString('en-IN')}
            {alert.merchant && (
              <span style={{ fontSize: '12px', color: '#6b7280', marginLeft: '8px' }}>
                @ {alert.merchant}
              </span>
            )}
          </div>
        )}
        {alert.fraud_pct != null && (
          <div
            style={{
              fontSize: '12px',
              color: '#fca5a5',
              fontFamily: "'DM Mono', monospace",
            }}
          >
            Fraud probability: <strong>{Number(alert.fraud_pct).toFixed(1)}%</strong>
          </div>
        )}
        {alert.explanation && (
          <div
            style={{
              fontSize: '11px',
              color: '#6b7280',
              marginTop: '4px',
              lineHeight: '1.5',
              maxWidth: '310px',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {alert.explanation}
          </div>
        )}
        <div style={{ fontSize: '10px', color: '#374151', marginTop: '4px' }}>
          {new Date(alert.timestamp).toLocaleTimeString()}
        </div>
      </div>

      <style>{`
        @keyframes slideInRight {
          from { opacity: 0; transform: translateX(24px); }
          to   { opacity: 1; transform: translateX(0); }
        }
      `}</style>
    </div>
  )
}
