'use client'
import { createContext, useContext, useState, useCallback, ReactNode } from 'react'

type ToastType = 'success' | 'error' | 'warning' | 'info'
interface Toast { id: number; message: string; type: ToastType; title?: string }

const ToastContext = createContext<{ toast: (msg: string, type?: ToastType, title?: string) => void }>({
  toast: () => {}
})

export const useToast = () => useContext(ToastContext)

const icons = { success:'✅', error:'❌', warning:'⚠️', info:'ℹ️' }
const colors = {
  success: { bg:'rgba(16,185,129,0.12)', border:'rgba(16,185,129,0.3)', color:'#34d399', bar:'#10b981' },
  error:   { bg:'rgba(239,68,68,0.12)',  border:'rgba(239,68,68,0.3)',  color:'#f87171', bar:'#ef4444' },
  warning: { bg:'rgba(245,158,11,0.12)', border:'rgba(245,158,11,0.3)', color:'#fbbf24', bar:'#f59e0b' },
  info:    { bg:'rgba(0,212,255,0.12)',  border:'rgba(0,212,255,0.3)',  color:'#67e8f9', bar:'#00d4ff' },
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const toast = useCallback((message: string, type: ToastType = 'info', title?: string) => {
    const id = Date.now()
    setToasts(prev => [...prev, { id, message, type, title }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 4000)
  }, [])

  const remove = (id: number) => setToasts(prev => prev.filter(t => t.id !== id))

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div style={{ position:'fixed', top:'20px', right:'20px', zIndex:9999,
        display:'flex', flexDirection:'column', gap:'10px', maxWidth:'360px' }}>
        {toasts.map((t, i) => {
          const c = colors[t.type]
          return (
            <div key={t.id} style={{
              background: '#0d1117', border:`1px solid ${c.border}`,
              borderRadius:'14px', padding:'14px 16px', minWidth:'300px',
              boxShadow:`0 8px 32px rgba(0,0,0,0.5), 0 0 20px ${c.bar}22`,
              animation:'toastIn 0.4s cubic-bezier(0.34,1.56,0.64,1)',
              display:'flex', alignItems:'flex-start', gap:'12px',
              position:'relative', overflow:'hidden', cursor:'pointer',
            }} onClick={() => remove(t.id)}>
              {/* Progress bar */}
              <div style={{ position:'absolute', bottom:0, left:0, height:'2px',
                background:c.bar, borderRadius:'999px',
                animation:'toastBar 4s linear forwards', width:'100%' }}/>
              {/* Left color strip */}
              <div style={{ position:'absolute', left:0, top:0, bottom:0, width:'3px',
                background:c.bar, borderRadius:'14px 0 0 14px' }}/>
              <div style={{ fontSize:'20px', flexShrink:0, marginLeft:'4px' }}>{icons[t.type]}</div>
              <div style={{ flex:1 }}>
                {t.title && <div style={{ fontSize:'13px', fontWeight:'700', color:c.color, marginBottom:'2px' }}>
                  {t.title}
                </div>}
                <div style={{ fontSize:'13px', color:'#94a3b8', lineHeight:1.4 }}>{t.message}</div>
              </div>
              <button onClick={() => remove(t.id)} style={{
                background:'none', border:'none', color:'#4b5563', cursor:'pointer',
                fontSize:'16px', padding:0, flexShrink:0 }}>×</button>
            </div>
          )
        })}
      </div>
      <style>{`
        @keyframes toastIn  { from{opacity:0;transform:translateX(100px) scale(0.9)} to{opacity:1;transform:translateX(0) scale(1)} }
        @keyframes toastBar { from{width:100%} to{width:0%} }
      `}</style>
    </ToastContext.Provider>
  )
}
