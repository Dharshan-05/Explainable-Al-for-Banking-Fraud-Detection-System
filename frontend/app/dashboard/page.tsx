'use client'
import { useEffect, useState, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import Sidebar from '@/app/components/Sidebar'
import { useTheme } from '@/app/components/ThemeContext'
import { useToast } from '@/app/components/Toast'
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'
import { analyticsAPI, transactionsAPI } from '@/lib/api'

export default function Dashboard() {
  const router = useRouter()
  const { t, dark } = useTheme()
  const { toast } = useToast()
  const [stats,   setStats]   = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState<string | null>(null)
  const [time,    setTime]    = useState('')

  useEffect(() => {
    const tick = () => setTime(new Date().toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',second:'2-digit'}))
    tick(); const id = setInterval(tick, 1000); return () => clearInterval(id)
  }, [])

  const fetchStats = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [statsRes, trendsRes, flaggedRes] = await Promise.all([
        analyticsAPI.stats(),
        analyticsAPI.trends(7),
        transactionsAPI.flagged(5)
      ])
      const statsData = statsRes.data
      const trendsData = trendsRes.data
      const flaggedData = flaggedRes.data

      const trend = trendsData.map((tr: any) => {
        const parts = tr.date.split('-')
        const displayDate = parts.length === 3 ? `${parts[1]}/${parts[2]}` : tr.date
        return {
          date: displayDate,
          total: tr.total,
          fraud: tr.fraud
        }
      })

      setStats({
        total: statsData.total_transactions,
        fraud: statsData.total_fraud,
        fraudRate: statsData.fraud_rate.toFixed(1),
        amountAtRisk: statsData.total_amount_at_risk,
        HIGH: statsData.high_risk_count,
        MEDIUM: statsData.medium_risk_count,
        LOW: statsData.low_risk_count,
        pending: statsData.pending_review,
        recentFraud: flaggedData,
        trend,
      })
      toast('Data Refreshed', 'success', 'Dashboard loaded successfully')
    } catch (err: any) {
      if (err.response?.status === 403) {
        setError('forbidden')
      } else {
        setError('error')
      }
      toast('Failed to load dashboard', 'error')
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => {
    fetchStats()
  }, [fetchStats])

  const Skeleton = () => (
    <div style={{ height:'80px', borderRadius:'12px',
      background: dark ? 'linear-gradient(90deg,#111827 25%,#1a2035 50%,#111827 75%)' : 'linear-gradient(90deg,#e2e8f0 25%,#f1f5f9 50%,#e2e8f0 75%)',
      backgroundSize:'200% 100%', animation:'shimmer 1.5s infinite' }}/>
  )

  const date = new Date().toLocaleDateString('en-US',{weekday:'short',day:'2-digit',month:'short'})

  if (error) {
    return (
      <div style={{ display:'flex', minHeight:'100vh', background: t.bg, fontFamily:"'Outfit',sans-serif", transition:'background 0.3s' }}>
        <Sidebar />
        <main style={{ marginLeft:'220px', flex:1, padding:'28px 32px', display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', minHeight:'calc(100vh - 56px)' }}>
          <div style={{ fontSize:'48px', marginBottom:'16px' }}>{error === 'forbidden' ? '🔒' : '⚠️'}</div>
          <h2 style={{ fontSize:'20px', fontWeight:'800', color: t.text, marginBottom:'8px' }}>
            {error === 'forbidden' ? 'Access Denied' : 'Failed to Load Dashboard'}
          </h2>
          <p style={{ color: t.muted4, fontSize:'14px', marginBottom:'20px', textAlign:'center', maxWidth:'360px' }}>
            {error === 'forbidden' 
              ? 'You do not have the required analyst or admin permissions to access the dashboard.' 
              : 'There was an error retrieving dashboard statistics. Please verify your connection.'}
          </p>
          {error !== 'forbidden' && (
            <button onClick={fetchStats} style={{
              padding:'10px 20px', borderRadius:'10px',
              border:'none', background:'linear-gradient(135deg,#00d4ff,#6366f1)',
              color:'#fff', fontSize:'13px', fontWeight:'600', cursor:'pointer', fontFamily:'inherit'
            }}>
              Retry Loading
            </button>
          )}
        </main>
      </div>
    )
  }

  return (
    <div style={{ display:'flex', minHeight:'100vh', background: t.bg, fontFamily:"'Outfit',sans-serif", transition:'background 0.3s' }}>
      <Sidebar />
      <main style={{ marginLeft:'220px', flex:1, padding:'28px 32px', transition:'background 0.3s' }}>

        {/* Header */}
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:'24px' }}>
          <div>
            <div style={{ display:'flex', alignItems:'center', gap:'8px', marginBottom:'6px' }}>
              <div style={{ width:'8px', height:'8px', borderRadius:'50%', background:'#10b981', boxShadow:'0 0 8px #10b981', animation:'pulse 2s infinite' }}/>
              <span style={{ fontSize:'11px', color:'#10b981', fontWeight:'700', letterSpacing:'1px' }}>LIVE MONITORING</span>
            </div>
            <h1 style={{ fontSize:'28px', fontWeight:'800', color: t.text, margin:'0 0 4px', letterSpacing:'-0.5px' }}>
              Fraud Detection <span style={{ background:'linear-gradient(135deg,#00d4ff,#6366f1)', WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent' }}>Dashboard</span>
            </h1>
            <p style={{ color: t.muted4, fontSize:'13px', margin:0 }}>XGBoost + SHAP powered real-time transaction monitoring</p>
          </div>
          <div style={{ textAlign:'right' }}>
            <div style={{ fontSize:'24px', fontWeight:'800', color:'#00d4ff', fontFamily:"'DM Mono',monospace" }}>{time}</div>
            <div style={{ fontSize:'12px', color: t.muted4 }}>{date}</div>
            <button onClick={fetchStats} style={{
              marginTop:'8px', padding:'6px 14px', borderRadius:'8px',
              border:'1px solid rgba(0,212,255,0.3)', background:'rgba(0,212,255,0.08)',
              color:'#00d4ff', fontSize:'12px', cursor:'pointer', fontFamily:'inherit' }}>
              ↻ Refresh
            </button>
          </div>
        </div>

        {/* Stat cards */}
        <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:'16px', marginBottom:'24px' }}>
          {loading ? [...Array(4)].map((_,i) => <Skeleton key={i}/>) : [
            { label:'TOTAL TRANSACTIONS', value: stats?.total?.toLocaleString() ?? '0', sub:'All time', icon:'💳', color:'#00d4ff' },
            { label:'FRAUD DETECTED',     value: stats?.fraud ?? '0', sub:`${stats?.fraudRate ?? '0.0'}% fraud rate`, icon:'🚨', color:'#ef4444' },
            { label:'AMOUNT AT RISK',     value: `₹${stats?.amountAtRisk ? (stats.amountAtRisk).toFixed(0) : '0'}`, sub:'Flagged total', icon:'💰', color:'#f59e0b' },
            { label:'MODEL ACCURACY',     value: '97.86%', sub:'ROC-AUC: 0.9786', icon:'🎯', color:'#10b981' },
          ].map((s:any) => (
            <div key={s.label} style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'16px', padding:'20px', position:'relative', overflow:'hidden', transition:'background 0.3s' }}>
              <div style={{ position:'absolute', top:0, left:0, right:0, height:'2px', background:`linear-gradient(90deg,${s.color},transparent)` }}/>
              <div style={{ fontSize:'20px', marginBottom:'8px' }}>{s.icon}</div>
              <div style={{ fontSize:'11px', color: t.muted4, fontWeight:'700', textTransform:'uppercase', letterSpacing:'0.8px', marginBottom:'6px' }}>{s.label}</div>
              <div style={{ fontSize:'28px', fontWeight:'800', color:s.color, fontFamily:"'DM Mono',monospace" }}>{s.value}</div>
              <div style={{ fontSize:'12px', color: t.muted4, marginTop:'4px' }}>{s.sub}</div>
            </div>
          ))}
        </div>

        {/* Row 2 */}
        <div style={{ display:'grid', gridTemplateColumns:'1fr 2fr', gap:'16px', marginBottom:'16px' }}>
          {/* Risk Breakdown */}
          <div style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'16px', padding:'20px', transition:'background 0.3s' }}>
            <div style={{ fontSize:'14px', fontWeight:'700', color: t.text, marginBottom:'16px', display:'flex', alignItems:'center', gap:'8px' }}>
              ⚡ Risk Breakdown
            </div>
            {loading ? <Skeleton/> : [
              { label:'HIGH Risk',   val: stats?.HIGH ?? 0,   color:'#ef4444' },
              { label:'MEDIUM Risk', val: stats?.MEDIUM ?? 0, color:'#f59e0b' },
              { label:'LOW Risk',    val: stats?.LOW ?? 0,    color:'#10b981' },
            ].map(r => (
              <div key={r.label} style={{ marginBottom:'14px' }}>
                <div style={{ display:'flex', justifyContent:'space-between', marginBottom:'4px' }}>
                  <span style={{ fontSize:'13px', color: t.muted }}>{r.label}</span>
                  <span style={{ fontSize:'13px', fontWeight:'700', color:r.color }}>{r.val}</span>
                </div>
                <div style={{ height:'4px', background: t.card2, borderRadius:'999px', overflow:'hidden' }}>
                  <div style={{ height:'100%', width:`${stats?.total ? (r.val/stats.total*100) : 0}%`, background:r.color, borderRadius:'999px', transition:'width 1s ease' }}/>
                </div>
              </div>
            ))}
            <div style={{ background: t.card2, borderRadius:'10px', padding:'14px', textAlign:'center', marginTop:'8px' }}>
              <div style={{ fontSize:'11px', color: t.muted4, marginBottom:'4px' }}>Pending Review</div>
              <div style={{ fontSize:'28px', fontWeight:'800', color:'#00d4ff', fontFamily:"'DM Mono',monospace" }}>{loading ? '...' : (stats?.pending ?? 0)}</div>
            </div>
          </div>

          {/* Fraud Trend */}
          <div style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'16px', padding:'20px', transition:'background 0.3s' }}>
            <div style={{ fontSize:'14px', fontWeight:'700', color: t.text, marginBottom:'16px', display:'flex', alignItems:'center', gap:'8px' }}>
              📊 7-Day Fraud Trend
            </div>
            {loading ? <Skeleton/> : (!stats?.trend || stats.trend.length === 0) ? (
              <div style={{ height: 200, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: t.muted4 }}>
                <div style={{ fontSize: '32px', marginBottom: '8px' }}>📈</div>
                <div style={{ fontSize: '13px' }}>No trend data available</div>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={stats.trend}>
                  <defs>
                    <linearGradient id="gT" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#00d4ff" stopOpacity={0.2}/>
                      <stop offset="95%" stopColor="#00d4ff" stopOpacity={0}/>
                    </linearGradient>
                    <linearGradient id="gF" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#ef4444" stopOpacity={0.2}/>
                      <stop offset="95%" stopColor="#ef4444" stopOpacity={0}/>
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke={dark ? '#111827' : '#e2e8f0'} />
                  <XAxis dataKey="date" tick={{ fill: t.muted4, fontSize:11 }} axisLine={false} tickLine={false}/>
                  <YAxis tick={{ fill: t.muted4, fontSize:11 }} axisLine={false} tickLine={false}/>
                  <Tooltip contentStyle={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'8px', color: t.text }}/>
                  <Area type="monotone" dataKey="total" stroke="#00d4ff" strokeWidth={2} fill="url(#gT)" dot={{ fill:'#00d4ff', r:3 }}/>
                  <Area type="monotone" dataKey="fraud" stroke="#ef4444" strokeWidth={2} fill="url(#gF)" dot={{ fill:'#ef4444', r:3 }}/>
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        {/* Recent Fraud Alerts */}
        <div style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'16px', padding:'20px', transition:'background 0.3s' }}>
          <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:'16px' }}>
            <div style={{ fontSize:'14px', fontWeight:'700', color: t.text, display:'flex', alignItems:'center', gap:'8px' }}>
              🚨 Recent Fraud Alerts
              {stats?.recentFraud?.length > 0 && (
                <span style={{ background:'rgba(239,68,68,0.12)', color:'#f87171', fontSize:'10px', fontWeight:'700', padding:'2px 8px', borderRadius:'999px', border:'1px solid rgba(239,68,68,0.3)' }}>
                  {stats.recentFraud.length} active
                </span>
              )}
            </div>
            <span style={{ fontSize:'12px', color:'#00d4ff', cursor:'pointer' }} onClick={() => router.push?.('/transactions')}>View all →</span>
          </div>
          {loading ? <Skeleton/> : !stats?.recentFraud || stats.recentFraud.length === 0 ? (
            <div style={{ textAlign:'center', padding:'40px 0', color: t.muted4 }}>
              <div style={{ fontSize:'40px', marginBottom:'12px' }}>🔍</div>
              <div>No fraud alerts yet</div>
              <div style={{ fontSize:'12px', marginTop:'4px' }}>Go to Predict to start scanning transactions</div>
            </div>
          ) : (
            <div style={{ display:'grid', gridTemplateColumns:'1fr 100px 80px 100px 100px 80px', gap:'0', borderRadius:'10px', overflow:'hidden', border:`1px solid ${t.border}` }}>
              {['TRANSACTION ID','AMOUNT','RISK LEVEL','FRAUD SCORE','STATUS','TIME'].map(h => (
                <div key={h} style={{ padding:'10px 12px', background: t.card2, fontSize:'10px', fontWeight:'700', color: t.muted4, letterSpacing:'0.8px' }}>{h}</div>
              ))}
              {stats.recentFraud.map((tx:any, i:number) => (
                <div key={tx.id} style={{ display:'contents' }}>
                  <div style={{ padding:'12px', borderTop:`1px solid ${t.border}`, fontSize:'12px', color: t.muted, fontFamily:"'DM Mono',monospace", display:'flex', alignItems:'center', gap:'8px' }}>
                    <div style={{ width:'6px', height:'6px', borderRadius:'50%', background:'#ef4444', boxShadow:'0 0 6px #ef4444', flexShrink:0 }}/>
                    {tx.id.slice(0,8)}...
                  </div>
                  <div style={{ padding:'12px', borderTop:`1px solid ${t.border}`, fontSize:'13px', fontWeight:'600', color: t.text2, display:'flex', alignItems:'center' }}>₹{parseFloat(tx.amount).toLocaleString('en-IN',{maximumFractionDigits:0})}</div>
                  <div style={{ padding:'12px', borderTop:`1px solid ${t.border}`, display:'flex', alignItems:'center' }}>
                    <span style={{ padding:'2px 8px', borderRadius:'999px', fontSize:'10px', fontWeight:'700', background:'rgba(239,68,68,0.12)', color:'#f87171', border:'1px solid rgba(239,68,68,0.3)' }}>{tx.risk_level||'HIGH'}</span>
                  </div>
                  <div style={{ padding:'12px', borderTop:`1px solid ${t.border}`, fontSize:'13px', fontWeight:'700', color:'#ef4444', fontFamily:"'DM Mono',monospace", display:'flex', alignItems:'center' }}>{tx.fraud_score ? (tx.fraud_score*100).toFixed(1)+'%' : '—'}</div>
                  <div style={{ padding:'12px', borderTop:`1px solid ${t.border}`, display:'flex', alignItems:'center' }}>
                    <span style={{ padding:'2px 8px', borderRadius:'999px', fontSize:'10px', fontWeight:'700', background:'rgba(99,102,241,0.12)', color:'#a5b4fc', border:'1px solid rgba(99,102,241,0.3)' }}>{tx.status}</span>
                  </div>
                  <div style={{ padding:'12px', borderTop:`1px solid ${t.border}`, fontSize:'11px', color: t.muted4, display:'flex', alignItems:'center' }}>{new Date(tx.created_at).toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit'})}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
      <style>{`
        @keyframes pulse   { 0%,100%{opacity:1} 50%{opacity:0.4} }
        @keyframes shimmer { 0%{background-position:-200% 0} 100%{background-position:200% 0} }
      `}</style>
    </div>
  )
}
