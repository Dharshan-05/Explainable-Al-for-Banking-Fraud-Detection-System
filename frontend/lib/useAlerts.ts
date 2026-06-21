// ============================================================
//  lib/useAlerts.ts  —  WebSocket Live Fraud Alerts Hook
//  Connects to ws://localhost:8000/api/ws/alerts?token=<jwt>
//  Pushes incoming HIGH-risk fraud messages into Zustand store.
// ============================================================
'use client'
import { useEffect, useRef } from 'react'
import { useStore } from '@/lib/store'

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? 'ws://localhost:8000'
const RECONNECT_DELAY_MS = 3000
const PING_INTERVAL_MS   = 15000

export function useAlerts() {
  const addAlert = useStore((s) => s.addAlert)
  const user     = useStore((s) => s.user)
  const wsRef    = useRef<WebSocket | null>(null)
  const pingRef  = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (!user) return  // Don't connect if not authenticated

    let destroyed = false
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      if (destroyed) return

      const url = `${WS_URL}/api/ws/alerts`
      const ws  = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        // Start keepalive pings so the server doesn't close the connection
        pingRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) ws.send('ping')
        }, PING_INTERVAL_MS)
      }

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data)
          if (msg.type === 'fraud_alert') {
            addAlert(msg)
          }
          // 'pong' and 'connected' messages are no-ops
        } catch {
          // Ignore parse errors
        }
      }

      ws.onerror = () => {
        // Error is followed by onclose — let reconnect logic handle it
      }

      ws.onclose = () => {
        if (pingRef.current) clearInterval(pingRef.current)
        if (!destroyed) {
          // Auto-reconnect after delay
          reconnectTimer = setTimeout(connect, RECONNECT_DELAY_MS)
        }
      }
    }

    connect()

    return () => {
      destroyed = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      if (pingRef.current) clearInterval(pingRef.current)
      if (wsRef.current) wsRef.current.close()
    }
  }, [user, addAlert])
}
