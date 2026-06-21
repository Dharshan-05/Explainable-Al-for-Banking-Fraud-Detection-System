'use client'
import { createContext, useContext, useState, useEffect } from 'react'

export const DARK = {
  bg:       '#06090f',
  card:     '#0d1117',
  card2:    '#111827',
  border:   '#1a2035',
  border2:  '#0f1623',
  text:     '#f0f4ff',
  text2:    '#e2e8f0',
  muted:    '#9ca3af',
  muted2:   '#6b7280',
  muted3:   '#4b5563',
  muted4:   '#374151',
  input:    '#111827',
  sidebar:  '#06090f',
}

export const LIGHT = {
  bg:       '#f0f4ff',
  card:     '#ffffff',
  card2:    '#f8fafc',
  border:   '#e2e8f0',
  border2:  '#cbd5e1',
  text:     '#0f172a',
  text2:    '#1e293b',
  muted:    '#475569',
  muted2:   '#64748b',
  muted3:   '#94a3b8',
  muted4:   '#94a3b8',
  input:    '#f1f5f9',
  sidebar:  '#ffffff',
}

type Theme = typeof DARK
type ThemeCtx = { dark: boolean; t: Theme; toggle: () => void }

const Ctx = createContext<ThemeCtx>({ dark: true, t: DARK, toggle: () => {} })

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [dark, setDark] = useState(true)

  useEffect(() => {
    const saved = localStorage.getItem('dark')
    if (saved === 'false') setDark(false)
  }, [])

  const toggle = () => {
    setDark(d => {
      const next = !d
      localStorage.setItem('dark', String(next))
      return next
    })
  }

  return (
    <Ctx.Provider value={{ dark, t: dark ? DARK : LIGHT, toggle }}>
      <div style={{ minHeight:'100vh', background: dark ? DARK.bg : LIGHT.bg, transition:'background 0.3s' }}>
        {children}
      </div>
    </Ctx.Provider>
  )
}

export const useTheme = () => useContext(Ctx)
