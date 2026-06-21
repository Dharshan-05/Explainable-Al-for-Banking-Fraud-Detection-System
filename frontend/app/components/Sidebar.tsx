'use client'
import { useState, useEffect } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { useTheme } from './ThemeContext'
import { useStore } from '@/lib/store'

const NAV = [
  { href:'/dashboard',    icon:'▣', label:'Dashboard'    },
  { href:'/transactions', icon:'⬡', label:'Transactions' },
  { href:'/analytics',    icon:'◈', label:'Analytics'    },
  { href:'/predict',      icon:'◎', label:'Predict'      },
]

export default function Sidebar() {
  const pathname = usePathname()
  const router   = useRouter()
  const { dark, t, toggle } = useTheme()
  const [user,      setUser]     = useState<any>(null)
  const [collapsed, setCollapsed]= useState(false)
  const [hovering,  setHovering] = useState('')

  useEffect(() => {
    try {
      const c = document.cookie.split(';').find(x=>x.trim().startsWith('user='))
      if (c) setUser(JSON.parse(decodeURIComponent(c.split('=').slice(1).join('='))))
    } catch {}
  }, [])

  const signOut = async () => {
    await useStore.getState().logout()
    router.push('/auth/login')
  }

  const W = collapsed ? '64px' : '220px'

  return (
    <aside style={{
      position:'fixed', top:0, left:0, height:'100vh', width:W,
      background: t.sidebar,
      borderRight:`1px solid ${t.border2}`,
      display:'flex', flexDirection:'column', zIndex:100,
      transition:'width 0.25s cubic-bezier(0.4,0,0.2,1), background 0.3s',
      overflow:'hidden',
    }}>
      <div style={{ height:'2px', background:'linear-gradient(90deg,#00d4ff,#6366f1,transparent)', flexShrink:0 }}/>

      {/* Logo */}
      <div style={{ padding: collapsed ? '16px 0' : '16px 16px',
        display:'flex', alignItems:'center', justifyContent: collapsed ? 'center' : 'space-between',
        borderBottom:`1px solid ${t.border2}`, flexShrink:0 }}>
        <div style={{ display:'flex', alignItems:'center', gap:'10px', overflow:'hidden' }}>
          <div style={{ width:'32px', height:'32px', borderRadius:'9px', flexShrink:0,
            background:'linear-gradient(135deg,rgba(0,212,255,0.15),rgba(99,102,241,0.15))',
            border:'1px solid rgba(0,212,255,0.25)', display:'flex', alignItems:'center',
            justifyContent:'center', fontSize:'16px' }}>🏦</div>
          {!collapsed && (
            <div style={{ overflow:'hidden' }}>
              <div style={{ fontSize:'13px', fontWeight:'800', color: t.text,
                whiteSpace:'nowrap', letterSpacing:'-0.3px', fontFamily:"'Outfit',sans-serif" }}>
                Fraud<span style={{ background:'linear-gradient(135deg,#00d4ff,#6366f1)',
                  WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent' }}>Guard</span>
              </div>
              <div style={{ fontSize:'9px', color: t.muted4, letterSpacing:'1.5px', fontWeight:'700' }}>XAI SYSTEM</div>
            </div>
          )}
        </div>
        {!collapsed && (
          <button onClick={() => setCollapsed(true)} style={{
            background:'none', border:'none', cursor:'pointer', color: t.muted4,
            fontSize:'16px', padding:'2px', flexShrink:0 }}>&#8249;</button>
        )}
      </div>

      {collapsed && (
        <button onClick={() => setCollapsed(false)} style={{
          background:'none', border:'none', cursor:'pointer', color: t.muted4,
          fontSize:'16px', padding:'8px', display:'block', width:'100%', textAlign:'center' }}>&#8250;</button>
      )}

      {!collapsed && (
        <div style={{ fontSize:'9px', color: t.muted4, fontWeight:'800',
          letterSpacing:'1.5px', padding:'16px 16px 6px', fontFamily:"'Outfit',sans-serif" }}>NAVIGATION</div>
      )}

      <nav style={{ flex:1, padding: collapsed ? '8px 4px' : '4px 8px', display:'flex', flexDirection:'column', gap:'2px' }}>
        {NAV.map(item => {
          const active = pathname === item.href
          return (
            <button key={item.href} onClick={() => router.push(item.href)}
              onMouseEnter={() => setHovering(item.href)}
              onMouseLeave={() => setHovering('')}
              style={{
                width:'100%', display:'flex', alignItems:'center',
                gap:'10px', padding: collapsed ? '10px 0' : '9px 12px',
                justifyContent: collapsed ? 'center' : 'flex-start',
                borderRadius:'10px', border:'none', cursor:'pointer',
                fontFamily:"'Outfit',sans-serif", fontSize:'13px',
                fontWeight: active ? '700' : '500',
                background: active ? 'rgba(0,212,255,0.08)' : hovering===item.href ? (dark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)') : 'transparent',
                color: active ? '#00d4ff' : hovering===item.href ? t.muted : t.muted3,
                transition:'all 0.15s',
                borderLeft: active && !collapsed ? '2px solid #00d4ff' : '2px solid transparent',
              }}>
              <span style={{ fontSize:'15px', flexShrink:0 }}>{item.icon}</span>
              {!collapsed && <span>{item.label}</span>}
              {active && !collapsed && (
                <span style={{ marginLeft:'auto', width:'5px', height:'5px', borderRadius:'50%',
                  background:'#00d4ff', boxShadow:'0 0 6px #00d4ff', flexShrink:0 }}/>
              )}
            </button>
          )
        })}
      </nav>

      {/* Bottom */}
      <div style={{ borderTop:`1px solid ${t.border2}`, padding: collapsed ? '12px 4px' : '12px 8px', flexShrink:0 }}>

        {/* Theme toggle */}
        {!collapsed && (
          <div onClick={toggle} style={{ display:'flex', alignItems:'center', justifyContent:'space-between',
            padding:'8px 10px', marginBottom:'8px', cursor:'pointer', borderRadius:'8px',
            transition:'background 0.15s' }}
            onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = dark ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)'}
            onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'transparent'}>
            <span style={{ fontSize:'12px', color: t.muted3, display:'flex', alignItems:'center', gap:'6px', fontFamily:"'Outfit',sans-serif" }}>
              <span>{dark ? '🌙' : '☀️'}</span>
              <span>{dark ? 'Dark Mode' : 'Light Mode'}</span>
            </span>
            <div style={{
              width:'36px', height:'20px', borderRadius:'999px',
              background: dark ? 'linear-gradient(135deg,#00d4ff,#6366f1)' : '#cbd5e1',
              position:'relative', transition:'background 0.3s', flexShrink:0 }}>
              <div style={{ position:'absolute', top:'2px',
                left: dark ? '18px' : '2px', width:'16px', height:'16px',
                borderRadius:'50%', background:'#fff', transition:'left 0.3s',
                boxShadow:'0 1px 4px rgba(0,0,0,0.3)' }}/>
            </div>
          </div>
        )}

        {/* User */}
        {!collapsed && user && (
          <div style={{ display:'flex', alignItems:'center', gap:'10px', padding:'8px 10px', marginBottom:'6px' }}>
            <div style={{ width:'32px', height:'32px', borderRadius:'10px', flexShrink:0,
              background:'linear-gradient(135deg,#00d4ff,#6366f1)',
              display:'flex', alignItems:'center', justifyContent:'center',
              fontSize:'13px', fontWeight:'800', color:'#000' }}>
              {(user.username||'U')[0].toUpperCase()}
            </div>
            <div style={{ overflow:'hidden' }}>
              <div style={{ fontSize:'13px', fontWeight:'700', color: t.text2,
                whiteSpace:'nowrap', fontFamily:"'Outfit',sans-serif" }}>{user.username}</div>
              <div style={{ fontSize:'10px', color: t.muted4, textTransform:'uppercase',
                letterSpacing:'0.8px', fontWeight:'700' }}>{user.role}</div>
            </div>
          </div>
        )}

        <button onClick={signOut} style={{
          width:'100%', padding: collapsed ? '8px 0' : '8px 10px',
          borderRadius:'8px', border:`1px solid ${t.border2}`,
          background:'transparent', color: t.muted4, fontSize:'12px',
          cursor:'pointer', fontFamily:"'Outfit',sans-serif",
          display:'flex', alignItems:'center', justifyContent: collapsed ? 'center' : 'flex-start',
          gap:'6px', transition:'all 0.15s' }}
          onMouseEnter={e => { (e.currentTarget as HTMLElement).style.color='#f87171'; (e.currentTarget as HTMLElement).style.borderColor='rgba(239,68,68,0.3)' }}
          onMouseLeave={e => { (e.currentTarget as HTMLElement).style.color=t.muted4; (e.currentTarget as HTMLElement).style.borderColor=t.border2 }}>
          <span>⏻</span>
          {!collapsed && <span>Sign Out</span>}
        </button>
      </div>
    </aside>
  )
}
