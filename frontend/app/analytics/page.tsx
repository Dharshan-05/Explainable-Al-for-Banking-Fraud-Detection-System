'use client'
import { useEffect, useState } from 'react'
import Sidebar from '@/app/components/Sidebar'
import { useTheme } from '@/app/components/ThemeContext'
import { useToast } from '@/app/components/Toast'
import { AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts'
import { analyticsAPI } from '@/lib/api'

export default function AnalyticsPage() {
  const { t, dark } = useTheme()
  const { toast } = useToast()
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState<string | null>(null)
  const [data,    setData]    = useState<any>(null)
  const [tab,     setTab]     = useState<'7d'|'14d'|'30d'>('7d')

  const fetchAnalytics = async () => {
    setLoading(true)
    setError(null)
    try {
      const daysMap = { '7d': 7, '14d': 14, '30d': 30 }
      const days = daysMap[tab]

      const [statsRes, trendsRes, riskRes, featuresRes, scoreRes] = await Promise.all([
        analyticsAPI.stats(),
        analyticsAPI.trends(days),
        analyticsAPI.riskDistribution(),
        analyticsAPI.topFeatures(),
        analyticsAPI.scoreDistribution()
      ])

      const statsData = statsRes.data
      const trendsData = trendsRes.data
      const riskDistData = riskRes.data
      const topFeaturesData = featuresRes.data
      const scoreDistData = scoreRes.data

      const riskDist = riskDistData.map((r: any) => ({
        name: r.risk_level,
        value: r.count,
        pct: r.percentage.toFixed(1)
      }))

      const statusDist = [
        { name: 'pending', value: statsData.pending_review },
        { name: 'flagged', value: statsData.flagged_count },
        { name: 'approved', value: statsData.approved_count },
        { name: 'rejected', value: statsData.rejected_count },
      ]

      const trend = trendsData.map((tr: any) => {
        const parts = tr.date.split('-')
        const displayDate = parts.length === 3 ? `${parts[1]}/${parts[2]}` : tr.date
        return {
          date: displayDate,
          total: tr.total,
          fraud: tr.fraud
        }
      })

      const shapFeatures = topFeaturesData.map((f: any) => ({
        name: f.feature,
        avg: f.avg_shap_impact,
        count: f.frequency
      }))

      const scoreBuckets = scoreDistData

      setData({
        riskDist,
        statusDist,
        trend,
        shapFeatures,
        scoreBuckets,
        totalTx: statsData.total_transactions,
        fraudCount: statsData.total_fraud,
        fraudRate: statsData.fraud_rate.toFixed(1),
        avgScore: statsData.avg_fraud_score.toFixed(1),
        totalAmount: statsData.total_amount,
      })
      toast('Analytics loaded!', 'success')
    } catch (err: any) {
      if (err.response?.status === 403) {
        setError('forbidden')
      } else {
        setError('error')
      }
      toast('Failed to load analytics', 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchAnalytics()
  }, [tab])

  const riskColors: any = { HIGH:'#ef4444', MEDIUM:'#f59e0b', LOW:'#10b981' }
  const Sk = ({ h='100%' }: any) => <div style={{ width:'100%', height:h, borderRadius:'12px', background: t.card2, animation:'shimmer 1.5s infinite' }}/>

  const tooltipStyle = { contentStyle:{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'8px', color: t.text }, itemStyle:{ color: t.text } }

  if (error) {
    return (
      <div style={{ display:'flex', minHeight:'100vh', background: t.bg, fontFamily:"'Outfit',sans-serif", transition:'background 0.3s' }}>
        <Sidebar />
        <main style={{ marginLeft:'220px', flex:1, padding:'28px 32px', display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', minHeight:'calc(100vh - 56px)' }}>
          <div style={{ fontSize:'48px', marginBottom:'16px' }}>{error === 'forbidden' ? '🔒' : '⚠️'}</div>
          <h2 style={{ fontSize:'20px', fontWeight:'800', color: t.text, marginBottom:'8px' }}>
            {error === 'forbidden' ? 'Access Denied' : 'Failed to Load Analytics'}
          </h2>
          <p style={{ color: t.muted4, fontSize:'14px', marginBottom:'20px', textAlign:'center', maxWidth:'360px' }}>
            {error === 'forbidden' 
              ? 'You do not have the required analyst or admin permissions to access analytics reports.' 
              : 'There was an error retrieving statistics from the server. Please verify your connection.'}
          </p>
          {error !== 'forbidden' && (
            <button onClick={fetchAnalytics} style={{
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
      <main style={{ marginLeft:'220px', flex:1, padding:'28px 32px' }}>
        <div style={{ marginBottom:'24px' }}>
          <h1 style={{ fontSize:'24px', fontWeight:'800', color: t.text, margin:'0 0 4px', letterSpacing:'-0.5px' }}>
            📈 Analytics <span style={{ background:'linear-gradient(135deg,#00d4ff,#6366f1)', WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent' }}>& Insights</span>
          </h1>
          <p style={{ color: t.muted4, fontSize:'13px', margin:0 }}>SHAP feature importance · fraud trends · risk distribution</p>
        </div>

        {/* Stat Cards */}
        <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:'12px', marginBottom:'24px' }}>
          {loading ? [...Array(4)].map((_,i) => <Sk key={i} h="110px"/>) : [
            { label:'Total Transactions', value: data?.totalTx?.toLocaleString() ?? '0', icon:'💳', color:'#00d4ff', sub:'All time' },
            { label:'Fraud Detected',     value: data?.fraudCount ?? '0',               icon:'🚨', color:'#ef4444', sub:`${data?.fraudRate ?? '0.0'}% fraud rate` },
            { label:'Avg Fraud Score',    value: `${data?.avgScore ?? '0.0'}%`,           icon:'🎯', color:'#f59e0b', sub:'Across all transactions' },
            { label:'Total Amount',       value: `₹${data?.totalAmount ? (data.totalAmount/100000).toFixed(1) : '0.0'}L`, icon:'💰', color:'#6366f1', sub:'Processed volume' },
          ].map((s:any) => (
            <div key={s.label} style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'16px', padding:'20px', position:'relative', overflow:'hidden', transition:'background 0.3s' }}>
              <div style={{ position:'absolute', top:0, left:0, right:0, height:'2px', background:`linear-gradient(90deg,${s.color},transparent)` }}/>
              <div style={{ fontSize:'22px', marginBottom:'8px' }}>{s.icon}</div>
              <div style={{ fontSize:'11px', color: t.muted4, fontWeight:'700', textTransform:'uppercase', letterSpacing:'0.8px', marginBottom:'6px' }}>{s.label}</div>
              <div style={{ fontSize:'28px', fontWeight:'800', color:s.color, fontFamily:"'DM Mono',monospace" }}>{s.value}</div>
              {s.sub && <div style={{ fontSize:'12px', color: t.muted4, marginTop:'4px' }}>{s.sub}</div>}
            </div>
          ))}
        </div>

        {/* Fraud Trend + Risk Donut */}
        <div style={{ display:'grid', gridTemplateColumns:'2fr 1fr', gap:'16px', marginBottom:'16px' }}>
          <div style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'16px', padding:'20px', transition:'background 0.3s' }}>
            <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:'16px' }}>
              <div>
                <div style={{ fontSize:'14px', fontWeight:'700', color: t.text }}>📊 Fraud Trend</div>
                <div style={{ fontSize:'11px', color: t.muted4 }}>Daily transaction activity</div>
              </div>
              <div style={{ display:'flex', gap:'6px' }}>
                {(['7d','14d','30d'] as const).map(tb => (
                  <button key={tb} onClick={() => setTab(tb)} style={{ padding:'4px 10px', borderRadius:'6px', fontSize:'11px', fontWeight:'600', border:`1px solid ${tab===tb ? 'rgba(0,212,255,0.4)' : t.border}`, background: tab===tb ? 'rgba(0,212,255,0.1)' : 'transparent', color: tab===tb ? '#00d4ff' : t.muted4, cursor:'pointer', fontFamily:'inherit' }}>{tb}</button>
                ))}
              </div>
            </div>
            {loading ? <Sk h="200px"/> : (!data?.trend || data.trend.length === 0) ? (
              <div style={{ height:'200px', display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', color: t.muted4 }}>
                <div style={{ fontSize:'32px', marginBottom:'12px' }}>📊</div>
                <div>No trend data available</div>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <AreaChart data={data.trend}>
                  <defs>
                    <linearGradient id="gT" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#00d4ff" stopOpacity={0.2}/><stop offset="95%" stopColor="#00d4ff" stopOpacity={0}/></linearGradient>
                    <linearGradient id="gF" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#ef4444" stopOpacity={0.2}/><stop offset="95%" stopColor="#ef4444" stopOpacity={0}/></linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke={dark ? '#111827' : '#e2e8f0'}/>
                  <XAxis dataKey="date" tick={{ fill: t.muted4, fontSize:11 }} axisLine={false} tickLine={false}/>
                  <YAxis tick={{ fill: t.muted4, fontSize:11 }} axisLine={false} tickLine={false}/>
                  <Tooltip {...tooltipStyle}/>
                  <Area type="monotone" dataKey="total" name="Total" stroke="#00d4ff" strokeWidth={2} fill="url(#gT)" dot={{ fill:'#00d4ff', r:3 }}/>
                  <Area type="monotone" dataKey="fraud" name="Fraud" stroke="#ef4444" strokeWidth={2} fill="url(#gF)" dot={{ fill:'#ef4444', r:3 }}/>
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>

          <div style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'16px', padding:'20px', transition:'background 0.3s' }}>
            <div style={{ fontSize:'14px', fontWeight:'700', color: t.text, marginBottom:'4px' }}>🎯 Risk Distribution</div>
            <div style={{ fontSize:'11px', color: t.muted4, marginBottom:'16px' }}>Current portfolio breakdown</div>
            {loading ? <Sk h="180px"/> : (!data?.riskDist || data.riskDist.length === 0) ? (
              <div style={{ height:'180px', display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', color: t.muted4 }}>
                <div style={{ fontSize:'32px', marginBottom:'12px' }}>🎯</div>
                <div>No risk breakdown available</div>
              </div>
            ) : (
              <>
                <ResponsiveContainer width="100%" height={160}>
                  <PieChart><Pie data={data.riskDist} cx="50%" cy="50%" innerRadius={45} outerRadius={70} paddingAngle={3} dataKey="value">
                    {data.riskDist.map((entry: any) => <Cell key={entry.name} fill={riskColors[entry.name]}/>)}
                  </Pie><Tooltip {...tooltipStyle}/></PieChart>
                </ResponsiveContainer>
                {data.riskDist.map((r: any) => (
                  <div key={r.name} style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginTop:'8px' }}>
                    <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
                      <div style={{ width:'8px', height:'8px', borderRadius:'50%', background:riskColors[r.name] }}/>
                      <span style={{ fontSize:'12px', color: t.muted }}>{r.name}</span>
                    </div>
                    <span style={{ fontSize:'12px', fontWeight:'700', color:riskColors[r.name], fontFamily:"'DM Mono',monospace" }}>{r.pct}% ({r.value})</span>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>

        {/* SHAP + Score Distribution */}
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'16px', marginBottom:'16px' }}>
          <div style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'16px', padding:'20px', transition:'background 0.3s' }}>
            <div style={{ fontSize:'14px', fontWeight:'700', color: t.text, marginBottom:'4px' }}>🔍 SHAP Feature Importance</div>
            <div style={{ fontSize:'11px', color: t.muted4, marginBottom:'16px' }}>Average absolute SHAP value</div>
            {loading ? <Sk h="280px"/> : data?.shapFeatures?.length > 0 ? (
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={data.shapFeatures} layout="vertical" margin={{ left:10 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke={dark ? '#111827' : '#e2e8f0'} horizontal={false}/>
                  <XAxis type="number" tick={{ fill: t.muted4, fontSize:10 }} axisLine={false} tickLine={false}/>
                  <YAxis type="category" dataKey="name" tick={{ fill: t.muted, fontSize:11 }} axisLine={false} tickLine={false} width={80}/>
                  <Tooltip {...tooltipStyle}/>
                  <Bar dataKey="avg" name="Avg |SHAP|" radius={[0,4,4,0]}>
                    {data.shapFeatures.map((_:any,i:number) => <Cell key={i} fill={`hsl(${200-i*10},80%,${60-i*2}%)`}/>)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div style={{ height:'280px', display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', color: t.muted4 }}>
                <div style={{ fontSize:'32px', marginBottom:'12px' }}>📊</div>
                <div>Upload transactions to see SHAP data</div>
              </div>
            )}
          </div>

          <div style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'16px', padding:'20px', transition:'background 0.3s' }}>
            <div style={{ fontSize:'14px', fontWeight:'700', color: t.text, marginBottom:'4px' }}>📉 Fraud Score Distribution</div>
            <div style={{ fontSize:'11px', color: t.muted4, marginBottom:'16px' }}>Transaction count by fraud probability</div>
            {loading ? <Sk h="280px"/> : (!data?.scoreBuckets || data.scoreBuckets.length === 0) ? (
              <div style={{ height:'280px', display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', color: t.muted4 }}>
                <div style={{ fontSize:'32px', marginBottom:'12px' }}>📉</div>
                <div>No fraud score distribution available</div>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={data.scoreBuckets}>
                  <CartesianGrid strokeDasharray="3 3" stroke={dark ? '#111827' : '#e2e8f0'} vertical={false}/>
                  <XAxis dataKey="range" tick={{ fill: t.muted4, fontSize:10 }} axisLine={false} tickLine={false}/>
                  <YAxis tick={{ fill: t.muted4, fontSize:11 }} axisLine={false} tickLine={false}/>
                  <Tooltip {...tooltipStyle}/>
                  <Bar dataKey="count" name="Total" radius={[4,4,0,0]}>
                    {data.scoreBuckets.map((_:any,i:number) => <Cell key={i} fill={i<4?'#10b981':i<7?'#f59e0b':'#ef4444'}/>)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        {/* Status + Top Features */}
        <div style={{ display:'grid', gridTemplateColumns:'1fr 2fr', gap:'16px' }}>
          <div style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'16px', padding:'20px', transition:'background 0.3s' }}>
            <div style={{ fontSize:'14px', fontWeight:'700', color: t.text, marginBottom:'16px' }}>📋 Status Breakdown</div>
            {loading ? <Sk h="200px"/> : (data?.statusDist||[]).map((s: any) => {
              const colors: any = { pending:'#a5b4fc', flagged:'#ef4444', approved:'#10b981', rejected:'#6b7280' }
              const pct = ((s.value as number)/(data?.totalTx||1)*100).toFixed(1)
              return (
                <div key={s.name} style={{ marginBottom:'12px' }}>
                  <div style={{ display:'flex', justifyContent:'space-between', marginBottom:'4px' }}>
                    <span style={{ fontSize:'12px', color: t.muted, textTransform:'capitalize' }}>{s.name}</span>
                    <span style={{ fontSize:'12px', fontWeight:'700', color:colors[s.name]||t.muted, fontFamily:"'DM Mono',monospace" }}>{s.value} ({pct}%)</span>
                  </div>
                  <div style={{ height:'4px', background: t.card2, borderRadius:'999px', overflow:'hidden' }}>
                    <div style={{ height:'100%', width:`${pct}%`, background:colors[s.name]||t.muted, borderRadius:'999px', transition:'width 1s ease' }}/>
                  </div>
                </div>
              )
            })}
          </div>

          <div style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'16px', padding:'20px', transition:'background 0.3s' }}>
            <div style={{ fontSize:'14px', fontWeight:'700', color: t.text, marginBottom:'16px' }}>🧠 Top Fraud Indicators</div>
            {loading ? <Sk h="200px"/> : (!data?.shapFeatures || data.shapFeatures.length === 0) ? (
              <div style={{ height:'200px', display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', color: t.muted4 }}>
                <div style={{ fontSize:'32px', marginBottom:'12px' }}>🧠</div>
                <div>No indicators available</div>
              </div>
            ) : (
              <table style={{ width:'100%', borderCollapse:'collapse', fontSize:'12px' }}>
                <thead>
                  <tr style={{ borderBottom:`1px solid ${t.border}` }}>
                    {['Rank','Feature','Avg |SHAP|','Appearances','Impact'].map(h => (
                      <th key={h} style={{ padding:'8px 12px', textAlign:'left', color: t.muted4, fontWeight:'700', textTransform:'uppercase', fontSize:'10px', letterSpacing:'0.8px' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.shapFeatures.slice(0, 8).map((f: any, i: number) => (
                    <tr key={f.name} style={{ borderBottom:`1px solid ${t.card2}` }}
                      onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = dark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)'}
                      onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'transparent'}>
                      <td style={{ padding:'10px 12px', color: t.muted4, fontFamily:"'DM Mono',monospace" }}>#{i+1}</td>
                      <td style={{ padding:'10px 12px', color: t.text2, fontWeight:'600', fontFamily:"'DM Mono',monospace" }}>{f.name}</td>
                      <td style={{ padding:'10px 12px', color:'#00d4ff', fontFamily:"'DM Mono',monospace" }}>{f.avg.toFixed(4)}</td>
                      <td style={{ padding:'10px 12px', color: t.muted2 }}>{f.count}</td>
                      <td style={{ padding:'10px 12px' }}>
                        <span style={{ padding:'2px 8px', borderRadius:'999px', fontSize:'10px', fontWeight:'700', background: i<3?'rgba(239,68,68,0.12)':i<7?'rgba(245,158,11,0.12)':'rgba(16,185,129,0.12)', color: i<3?'#f87171':i<7?'#fbbf24':'#34d399' }}>
                          {i<3?'HIGH':i<7?'MEDIUM':'LOW'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </main>
      <style>{`@keyframes shimmer{0%{opacity:0.5}50%{opacity:1}100%{opacity:0.5}}`}</style>
    </div>
  )
}
