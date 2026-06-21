'use client'
import { useState, useEffect, useRef } from 'react'
import { authAPI } from '@/lib/api'
import { useStore } from '@/lib/store'

function HexGrid() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const canvas = canvasRef.current!
    const ctx = canvas.getContext('2d')!
    let W = canvas.width = window.innerWidth
    let H = canvas.height = window.innerHeight
    const hexSize = 28
    const cols = Math.ceil(W / (hexSize * 1.75)) + 2
    const rows = Math.ceil(H / (hexSize * 1.5)) + 2
    type Hex = { x: number; y: number; alpha: number; speed: number; phase: number }
    const hexes: Hex[] = []
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const x = c * hexSize * 1.75 + (r % 2 ? hexSize * 0.875 : 0)
        const y = r * hexSize * 1.5
        hexes.push({ x, y, alpha: Math.random() * 0.12, speed: Math.random() * 0.003 + 0.001, phase: Math.random() * Math.PI * 2 })
      }
    }
    const drawHex = (x: number, y: number, size: number, alpha: number) => {
      ctx.beginPath()
      for (let i = 0; i < 6; i++) {
        const angle = (Math.PI / 3) * i - Math.PI / 6
        const px = x + size * Math.cos(angle)
        const py = y + size * Math.sin(angle)
        i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py)
      }
      ctx.closePath()
      ctx.strokeStyle = `rgba(0,212,255,${alpha})`
      ctx.lineWidth = 0.5
      ctx.stroke()
    }
    let frame = 0
    let animId: number
    const draw = () => {
      ctx.clearRect(0, 0, W, H)
      frame++
      hexes.forEach(h => {
        h.alpha = 0.03 + Math.sin(frame * h.speed + h.phase) * 0.06
        drawHex(h.x, h.y, hexSize, Math.max(0, h.alpha))
      })
      animId = requestAnimationFrame(draw)
    }
    draw()
    const onResize = () => { W = canvas.width = window.innerWidth; H = canvas.height = window.innerHeight }
    window.addEventListener('resize', onResize)
    return () => { cancelAnimationFrame(animId); window.removeEventListener('resize', onResize) }
  }, [])
  return <canvas ref={canvasRef} style={{ position:'fixed', inset:0, zIndex:0, pointerEvents:'none', opacity:0.7 }}/>
}

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [mounted, setMounted] = useState(false)
  const [showPass, setShowPass] = useState(false)
  const [shake, setShake] = useState(false)
  const [focused, setFocused] = useState('')

  useEffect(() => { setTimeout(() => setMounted(true), 100) }, [])

  const handleLogin = async () => {
    if (!username || !password) { setError('Please enter credentials'); return }
    setLoading(true); setError('')
    try {
      const res = await authAPI.login(username, password)
      const data = res.data
      const exp = new Date(); exp.setDate(exp.getDate() + 1)
      document.cookie = `user=${encodeURIComponent(JSON.stringify(data.user))}; path=/; expires=${exp.toUTCString()}`
      useStore.getState().setAuth(data.user)
      window.location.replace('/dashboard')
    } catch (err: any) {
      const msg = err.response?.data?.detail || 'Invalid credentials or connection error'
      setError(msg)
      setShake(true); setTimeout(() => setShake(false), 500)
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight:'100vh', background:'#020609',
      display:'flex', alignItems:'center', justifyContent:'center',
      fontFamily:"'Outfit', sans-serif", overflow:'hidden', position:'relative' }}>
      <HexGrid />

      {/* Radial glows */}
      <div style={{ position:'fixed', top:'-20%', right:'-10%', width:'600px', height:'600px',
        background:'radial-gradient(circle, rgba(0,212,255,0.06) 0%, transparent 60%)', pointerEvents:'none', zIndex:1 }}/>
      <div style={{ position:'fixed', bottom:'-20%', left:'-10%', width:'500px', height:'500px',
        background:'radial-gradient(circle, rgba(99,102,241,0.06) 0%, transparent 60%)', pointerEvents:'none', zIndex:1 }}/>

      {/* Scanline overlay */}
      <div style={{ position:'fixed', inset:0, zIndex:1, pointerEvents:'none',
        backgroundImage:'repeating-linear-gradient(0deg, transparent, transparent 3px, rgba(0,0,0,0.015) 3px, rgba(0,0,0,0.015) 4px)',
        backgroundSize:'100% 4px' }}/>

      {/* Card */}
      <div style={{
        position:'relative', zIndex:10, width:'100%', maxWidth:'400px', margin:'0 20px',
        opacity: mounted ? 1 : 0,
        transform: mounted ? 'translateY(0) scale(1)' : 'translateY(24px) scale(0.96)',
        transition:'all 0.7s cubic-bezier(0.22,1,0.36,1)',
        animation: shake ? 'shake 0.4s ease' : 'none',
      }}>
        {/* Outer glow border */}
        <div style={{ position:'absolute', inset:'-1px', borderRadius:'20px', zIndex:0,
          background:'linear-gradient(135deg,rgba(0,212,255,0.25),rgba(99,102,241,0.15),rgba(0,212,255,0.05))',
          boxShadow:'0 0 60px rgba(0,212,255,0.08)' }}/>

        <div style={{ position:'relative', zIndex:1, background:'rgba(6,10,18,0.97)',
          borderRadius:'20px', padding:'40px 36px', backdropFilter:'blur(40px)' }}>

          {/* Logo */}
          <div style={{ textAlign:'center', marginBottom:'28px' }}>
            <div style={{ width:'56px', height:'56px', margin:'0 auto 14px', borderRadius:'16px',
              background:'linear-gradient(135deg,rgba(0,212,255,0.1),rgba(99,102,241,0.1))',
              border:'1px solid rgba(0,212,255,0.3)', display:'flex', alignItems:'center',
              justifyContent:'center', fontSize:'26px',
              boxShadow:'0 0 24px rgba(0,212,255,0.12)', animation:'logoPulse 4s ease infinite' }}>🏦</div>
            <div style={{ fontSize:'22px', fontWeight:'800', color:'#f0f4ff', letterSpacing:'-0.5px' }}>
              Fraud<span style={{ background:'linear-gradient(135deg,#00d4ff,#6366f1)',
                WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent' }}>Guard</span>
              <span style={{ fontSize:'11px', fontWeight:'700', color:'#374151',
                letterSpacing:'2px', display:'block', marginTop:'2px' }}>XAI SYSTEM</span>
            </div>
          </div>

          {/* Status pill */}
          <div style={{ display:'flex', alignItems:'center', gap:'6px', justifyContent:'center',
            marginBottom:'24px', padding:'6px 14px', borderRadius:'999px', width:'fit-content', margin:'0 auto 24px',
            background:'rgba(16,185,129,0.07)', border:'1px solid rgba(16,185,129,0.2)' }}>
            <span style={{ width:'5px', height:'5px', borderRadius:'50%', background:'#10b981',
              boxShadow:'0 0 6px #10b981', animation:'blink 2s infinite', display:'inline-block' }}/>
            <span style={{ fontSize:'10px', color:'#10b981', fontWeight:'700', letterSpacing:'1.5px' }}>
              ALL SYSTEMS OPERATIONAL
            </span>
          </div>

          {/* Fields */}
          {[
            { label:'USERNAME', key:'username', type:'text', icon:'⬡', val:username, set:setUsername },
            { label:'PASSWORD', key:'password', type: showPass ? 'text' : 'password', icon:'⬡', val:password, set:setPassword },
          ].map(f => (
            <div key={f.key} style={{ marginBottom:'14px' }}>
              <label style={{ fontSize:'10px', fontWeight:'800', color: focused===f.key ? '#00d4ff' : '#374151',
                letterSpacing:'1.5px', textTransform:'uppercase', display:'block', marginBottom:'6px',
                transition:'color 0.2s' }}>{f.label}</label>
              <div style={{ position:'relative' }}>
                <input type={f.type} value={f.val}
                  onChange={e => f.set(e.target.value)}
                  onKeyDown={e => e.key==='Enter' && handleLogin()}
                  onFocus={() => setFocused(f.key)}
                  onBlur={() => setFocused('')}
                  placeholder={f.key==='username' ? 'Enter username' : 'Enter password'}
                  style={{ width:'100%', padding:'11px 14px', borderRadius:'10px', boxSizing:'border-box',
                    background: focused===f.key ? 'rgba(0,212,255,0.04)' : 'rgba(255,255,255,0.03)',
                    border: `1px solid ${focused===f.key ? 'rgba(0,212,255,0.4)' : '#1a2332'}`,
                    color:'#e2e8f0', fontSize:'14px', outline:'none', fontFamily:'inherit',
                    transition:'all 0.2s', paddingRight: f.key==='password' ? '42px' : '14px' }}/>
                {f.key==='password' && (
                  <button onClick={() => setShowPass(!showPass)} style={{
                    position:'absolute', right:'12px', top:'50%', transform:'translateY(-50%)',
                    background:'none', border:'none', cursor:'pointer', color:'#374151', fontSize:'14px', padding:0 }}>
                    {showPass ? '🙈' : '👁️'}
                  </button>
                )}
              </div>
            </div>
          ))}

          {error && (
            <div style={{ background:'rgba(239,68,68,0.07)', border:'1px solid rgba(239,68,68,0.2)',
              borderRadius:'8px', padding:'9px 12px', marginBottom:'14px',
              color:'#f87171', fontSize:'12px', display:'flex', alignItems:'center', gap:'6px' }}>
              ⚠️ {error}
            </div>
          )}

          <button onClick={handleLogin} disabled={loading} style={{
            width:'100%', padding:'13px', borderRadius:'10px', border:'none', marginTop:'4px',
            background: loading ? '#0d1117' : 'linear-gradient(135deg,#00d4ff,#0ea5e9 50%,#6366f1)',
            color: loading ? '#374151' : '#fff', fontSize:'14px', fontWeight:'700',
            cursor: loading ? 'not-allowed' : 'pointer', fontFamily:'inherit', letterSpacing:'1px',
            boxShadow: loading ? 'none' : '0 4px 24px rgba(0,212,255,0.2)', transition:'all 0.3s',
          }}>
            {loading ? (
              <span style={{ display:'flex', alignItems:'center', justifyContent:'center', gap:'8px' }}>
                <span style={{ width:'14px', height:'14px', border:'2px solid #1a2332',
                  borderTopColor:'#374151', borderRadius:'50%', display:'inline-block',
                  animation:'spin 0.8s linear infinite' }}/>
                AUTHENTICATING...
              </span>
            ) : 'SIGN IN →'}
          </button>

          <div style={{ display:'flex', justifyContent:'center', gap:'16px', marginTop:'20px' }}>
            {['JWT', 'AES-256', 'XAI'].map(b => (
              <span key={b} style={{ fontSize:'9px', color:'#1f2937', fontWeight:'800',
                letterSpacing:'1.5px', padding:'3px 8px', borderRadius:'4px',
                border:'1px solid #1a2332', background:'rgba(255,255,255,0.01)' }}>{b}</span>
            ))}
          </div>
        </div>
      </div>

      <style suppressHydrationWarning>{`
        @keyframes logoPulse { 0%,100%{box-shadow:0 0 24px rgba(0,212,255,0.12)} 50%{box-shadow:0 0 40px rgba(0,212,255,0.22)} }
        @keyframes blink     { 0%,100%{opacity:1} 50%{opacity:0.3} }
        @keyframes spin      { to{transform:rotate(360deg)} }
        @keyframes shake     { 0%,100%{transform:translateX(0)} 20%{transform:translateX(-8px)} 40%{transform:translateX(8px)} 60%{transform:translateX(-5px)} 80%{transform:translateX(5px)} }
        input::placeholder   { color:#1f2937 }
      `}</style>
    </div>
  )
}
