'use client'
import { useEffect, useState, useRef } from 'react'
import Sidebar from '@/app/components/Sidebar'
import { useTheme } from '@/app/components/ThemeContext'
import { useToast } from '@/app/components/Toast'
import { transactionsAPI, predictAPI } from '@/lib/api'

const RISK_STYLES: any = {
  HIGH:   { bg:'rgba(239,68,68,0.12)',  color:'#f87171', border:'rgba(239,68,68,0.3)'  },
  MEDIUM: { bg:'rgba(245,158,11,0.12)', color:'#fbbf24', border:'rgba(245,158,11,0.3)' },
  LOW:    { bg:'rgba(16,185,129,0.12)', color:'#34d399', border:'rgba(16,185,129,0.3)' },
}
const STATUS_STYLES: any = {
  pending:  { bg:'rgba(99,102,241,0.12)', color:'#a5b4fc', border:'rgba(99,102,241,0.3)'  },
  flagged:  { bg:'rgba(239,68,68,0.12)',  color:'#f87171', border:'rgba(239,68,68,0.3)'   },
  approved: { bg:'rgba(16,185,129,0.12)', color:'#34d399', border:'rgba(16,185,129,0.3)'  },
  rejected: { bg:'rgba(107,114,128,0.12)',color:'#9ca3af', border:'rgba(107,114,128,0.3)' },
}

const Badge = ({ val, map }: any) => {
  const s = map[val] || map['pending']
  return (
    <span style={{ padding:'3px 10px', borderRadius:'999px', fontSize:'11px', fontWeight:'700',
      background:s.bg, color:s.color, border:`1px solid ${s.border}`, whiteSpace:'nowrap' }}>
      {val?.toUpperCase()}
    </span>
  )
}

export default function TransactionsPage() {
  const { t, dark } = useTheme()
  const { toast } = useToast()
  const fileRef = useRef<HTMLInputElement>(null)
  const [transactions, setTransactions] = useState<any[]>([])
  const [total,    setTotal]    = useState(0)
  const [page,     setPage]     = useState(1)
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState<string | null>(null)
  const [search,   setSearch]   = useState('')
  const [riskFilter,   setRiskFilter]   = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [fraudFilter,  setFraudFilter]  = useState('')
  const [selected,  setSelected] = useState<Set<string>>(new Set())
  
  const [csvState, setCsvState] = useState<any>({
    status: 'idle', // idle, uploading, processing, success, error
    total: 0,
    processed: 0,
    failed: 0,
    fraudCount: 0,
    taskId: null
  })

  const perPage = 15

  const fetchTransactions = async (p = page) => {
    setLoading(true)
    setError(null)
    try {
      const params: any = { page: p, per_page: perPage }
      if (riskFilter)   params.risk_level = riskFilter
      if (statusFilter) params.status = statusFilter
      if (fraudFilter !== '') params.is_fraud = fraudFilter === 'true'

      const res = await transactionsAPI.list(params)
      setTransactions(res.data.transactions)
      setTotal(res.data.total)
    } catch (err: any) {
      if (err.response?.status === 403) {
        setError('forbidden')
      } else {
        setError('error')
      }
      toast('Failed to load transactions', 'error')
    } finally { setLoading(false) }
  }

  useEffect(() => { fetchTransactions(1); setPage(1) }, [riskFilter, statusFilter, fraudFilter])
  useEffect(() => { fetchTransactions(page) }, [page])

  const handleCSV = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return
    setCsvState({ status: 'uploading', total: 0, processed: 0, failed: 0, fraudCount: 0, taskId: null })
    toast('Processing CSV...', 'info', 'Upload Started')
    try {
      const text = await file.text()
      const lines = text.trim().split('\n')
      if (lines.length <= 1) {
        toast('CSV is empty or invalid', 'error')
        setCsvState({ status: 'idle', total: 0, processed: 0, failed: 0, fraudCount: 0, taskId: null })
        return
      }
      const headers = lines[0].split(',').map(h => h.trim().replace(/"/g, ''))
      const rows = lines.slice(1)

      const payloadTxs = rows.map(row => {
        const values = row.split(',').map(v => v.trim().replace(/"/g, ''))
        const obj: any = {}
        headers.forEach((h, i) => { obj[h] = values[i] || '0' })
        const body: any = { Amount: parseFloat(obj.Amount || obj.amount || '100') }
        for (let i = 1; i <= 28; i++) body[`V${i}`] = parseFloat(obj[`V${i}`] || '0')
        body.Time = parseFloat(obj.Time || obj.time || '50000')
        return body
      }).filter(tx => tx.Amount > 0)

      setCsvState((prev: any) => ({ ...prev, status: 'processing', total: payloadTxs.length }))

      const res = await predictAPI.batch({ transactions: payloadTxs })
      const { task_id } = res.data

      setCsvState((prev: any) => ({ ...prev, taskId: task_id }))

      // Poll task results
      const interval = setInterval(async () => {
        try {
          const pollRes = await predictAPI.batchResult(task_id)
          const { status, result, error: taskErr } = pollRes.data

          if (status === 'SUCCESS') {
            clearInterval(interval)
            setCsvState({
              status: 'success',
              total: result.total,
              processed: result.processed,
              failed: result.failed,
              fraudCount: result.fraud_count,
              currentChunk: result.current_chunk,
              totalChunks: result.total_chunks,
              duration: result.duration,
              taskId: null
            })
            toast(`✅ Processed ${result.processed} rows, ${result.fraud_count} fraud found`, 'success', 'Batch Prediction Complete')
            fetchTransactions(1)
            setTimeout(() => {
              setCsvState((prev: any) => prev.status === 'success' ? { ...prev, status: 'idle' } : prev)
            }, 6000)
          } else if (status === 'FAILURE') {
            clearInterval(interval)
            setCsvState({ status: 'error', total: payloadTxs.length, processed: 0, failed: payloadTxs.length, fraudCount: 0, taskId: null })
            toast(taskErr || 'Batch prediction task failed', 'error')
          } else if (result) {
            setCsvState((prev: any) => ({
              ...prev,
              processed: result.processed ?? prev.processed,
              failed: result.failed ?? prev.failed,
              fraudCount: result.fraud_count ?? prev.fraudCount,
              currentChunk: result.current_chunk,
              totalChunks: result.total_chunks,
              duration: result.duration
            }))
          }
        } catch (pollErr) {
          clearInterval(interval)
          setCsvState({ status: 'error', total: payloadTxs.length, processed: 0, failed: payloadTxs.length, fraudCount: 0, taskId: null })
          toast('Error polling prediction progress', 'error')
        }
      }, 1500)

    } catch { 
      setCsvState({ status: 'idle', total: 0, processed: 0, failed: 0, fraudCount: 0, taskId: null })
      toast('Failed to parse CSV', 'error') 
    } finally { 
      if (fileRef.current) fileRef.current.value = '' 
    }
  }

  const exportCSV = () => {
    const headers = ['ID','Amount','Risk Level','Fraud Score','Status','Time']
    const rows = transactions.map(tx => [tx.id, tx.amount, tx.risk_level||'', tx.fraud_score ? (tx.fraud_score*100).toFixed(1)+'%' : '', tx.status, tx.created_at])
    const csv = [headers, ...rows].map(r => r.join(',')).join('\n')
    const blob = new Blob([csv], { type:'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href=url; a.download='transactions.csv'; a.click()
    toast('CSV exported!', 'success')
  }

  const filtered = search ? transactions.filter(tx =>
    tx.id.toLowerCase().includes(search.toLowerCase()) ||
    String(tx.amount).includes(search) ||
    (tx.risk_level||'').toLowerCase().includes(search.toLowerCase())
  ) : transactions

  const totalPages = Math.ceil(total / perPage)

  const toggleSelect = (id: string) => {
    setSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  }

  const inputStyle = { padding:'10px 12px', borderRadius:'10px', background: t.input, border:`1px solid ${t.border}`, color: t.text, fontSize:'13px', outline:'none', fontFamily:'inherit', cursor:'pointer' }

  if (error) {
    return (
      <div style={{ display:'flex', minHeight:'100vh', background: t.bg, fontFamily:"'Outfit',sans-serif", transition:'background 0.3s' }}>
        <Sidebar />
        <main style={{ marginLeft:'220px', flex:1, padding:'28px 32px', display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center' }}>
          <div style={{ fontSize:'48px', marginBottom:'16px' }}>{error === 'forbidden' ? '🔒' : '⚠️'}</div>
          <h2 style={{ fontSize:'20px', fontWeight:'800', color: t.text, marginBottom:'8px' }}>
            {error === 'forbidden' ? 'Access Denied' : 'Failed to Load Transactions'}
          </h2>
          <p style={{ color: t.muted4, fontSize:'14px', marginBottom:'20px', textAlign:'center', maxWidth:'360px' }}>
            {error === 'forbidden' 
              ? 'You do not have the required permissions to view transaction reports.' 
              : 'There was an error retrieving transactions from the server. Please verify your connection.'}
          </p>
          {error !== 'forbidden' && (
            <button onClick={() => fetchTransactions(page)} style={{
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
        {/* Header */}
        <div style={{ display:'flex', alignItems:'flex-start', justifyContent:'space-between', marginBottom:'24px' }}>
          <div>
            <h1 style={{ fontSize:'24px', fontWeight:'800', color: t.text, margin:'0 0 4px', letterSpacing:'-0.5px' }}>
              💳 Transaction <span style={{ background:'linear-gradient(135deg,#00d4ff,#6366f1)', WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent' }}>Monitor</span>
            </h1>
            <p style={{ color: t.muted4, fontSize:'13px', margin:0 }}>{total.toLocaleString()} total transactions · Real-time fraud monitoring</p>
          </div>
          <div style={{ display:'flex', gap:'10px' }}>
            <input ref={fileRef} type="file" accept=".csv" onChange={handleCSV} style={{ display:'none' }}/>
            <button onClick={() => fileRef.current?.click()} disabled={csvState.status !== 'idle'} style={{ padding:'10px 18px', borderRadius:'10px', border:'1px solid rgba(0,212,255,0.3)', background:'rgba(0,212,255,0.08)', color:'#00d4ff', fontSize:'13px', fontWeight:'600', cursor: csvState.status !== 'idle' ? 'not-allowed' : 'pointer', fontFamily:'inherit' }}>
              {csvState.status !== 'idle' ? '⏳ Uploading...' : '📤 Upload CSV'}
            </button>
            <button onClick={exportCSV} style={{ padding:'10px 18px', borderRadius:'10px', border:'1px solid rgba(99,102,241,0.3)', background:'rgba(99,102,241,0.08)', color:'#a5b4fc', fontSize:'13px', fontWeight:'600', cursor:'pointer', fontFamily:'inherit' }}>
              📥 Export CSV
            </button>
          </div>
        </div>

        {/* Stats */}
        <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:'12px', marginBottom:'20px' }}>
          {[
            { label:'Total',   value: total,                                               color:'#00d4ff' },
            { label:'Fraud',   value: transactions.filter(tx=>tx.is_fraud).length,         color:'#ef4444' },
            { label:'Pending', value: transactions.filter(tx=>tx.status==='pending').length,color:'#a5b4fc' },
            { label:'Flagged', value: transactions.filter(tx=>tx.status==='flagged').length,color:'#f59e0b' },
          ].map(s => (
            <div key={s.label} style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'12px', padding:'14px 18px', transition:'background 0.3s' }}>
              <div style={{ fontSize:'11px', color: t.muted4, fontWeight:'600', textTransform:'uppercase', letterSpacing:'0.8px', marginBottom:'6px' }}>{s.label}</div>
              <div style={{ fontSize:'24px', fontWeight:'800', color:s.color, fontFamily:"'DM Mono',monospace" }}>{s.value}</div>
            </div>
          ))}
        </div>

        {/* Filters */}
        <div style={{ display:'flex', gap:'10px', marginBottom:'16px', flexWrap:'wrap' }}>
          <div style={{ position:'relative', flex:1, minWidth:'200px' }}>
            <span style={{ position:'absolute', left:'12px', top:'50%', transform:'translateY(-50%)', fontSize:'14px', opacity:0.4 }}>🔍</span>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search by ID, amount, risk..."
              style={{ ...inputStyle, width:'100%', paddingLeft:'36px', boxSizing:'border-box' as any }}/>
          </div>
          <select value={riskFilter}   onChange={e => setRiskFilter(e.target.value)}   style={inputStyle}><option value="">All Risk Levels</option><option value="HIGH">🔴 HIGH</option><option value="MEDIUM">🟡 MEDIUM</option><option value="LOW">🟢 LOW</option></select>
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={inputStyle}><option value="">All Statuses</option><option value="pending">pending</option><option value="flagged">flagged</option><option value="approved">approved</option><option value="rejected">rejected</option></select>
          <select value={fraudFilter}  onChange={e => setFraudFilter(e.target.value)}  style={inputStyle}><option value="">All Types</option><option value="true">🚨 Fraud Only</option><option value="false">✅ Legit Only</option></select>
          {(riskFilter||statusFilter||fraudFilter||search) && (
            <button onClick={() => { setRiskFilter(''); setStatusFilter(''); setFraudFilter(''); setSearch('') }}
              style={{ padding:'10px 14px', borderRadius:'10px', border:`1px solid ${t.border}`, background:'transparent', color: t.muted2, fontSize:'13px', cursor:'pointer', fontFamily:'inherit' }}>✕ Clear</button>
          )}
        </div>

        {/* Table */}
        <div style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'16px', overflow:'hidden', transition:'background 0.3s' }}>
          <div style={{ display:'grid', gridTemplateColumns:'40px 1fr 100px 80px 100px 100px 100px 80px', padding:'10px 16px', borderBottom:`1px solid ${t.border}`, background: dark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)' }}>
            {['','Transaction ID','Amount','Risk','Fraud %','Status','Time','Action'].map(h => (
              <div key={h} style={{ fontSize:'11px', fontWeight:'700', color: t.muted4, textTransform:'uppercase', letterSpacing:'0.8px' }}>{h}</div>
            ))}
          </div>
          {loading ? (
            <div style={{ padding:'16px', display:'flex', flexDirection:'column', gap:'10px' }}>
              {[...Array(8)].map((_,i) => <div key={i} style={{ height:'44px', borderRadius:'6px', background: t.card2, animation:'shimmer 1.5s infinite' }}/>)}
            </div>
          ) : filtered.length === 0 ? (
            <div style={{ textAlign:'center', padding:'60px 0', color: t.muted4 }}>
              <div style={{ fontSize:'40px', marginBottom:'12px' }}>🔍</div>
              <div>No transactions found</div>
            </div>
          ) : filtered.map((tx, i) => (
            <div key={tx.id} style={{ display:'grid', gridTemplateColumns:'40px 1fr 100px 80px 100px 100px 100px 80px', padding:'12px 16px', borderBottom:`1px solid ${t.card2}`, alignItems:'center', transition:'background 0.15s' }}
              onMouseEnter={e => (e.currentTarget as HTMLElement).style.background = dark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)'}
              onMouseLeave={e => (e.currentTarget as HTMLElement).style.background = 'transparent'}>
              <div onClick={() => toggleSelect(tx.id)} style={{ cursor:'pointer' }}>
                <div style={{ width:'16px', height:'16px', borderRadius:'4px', border:`1px solid ${selected.has(tx.id) ? '#00d4ff' : t.border}`, background: selected.has(tx.id) ? '#00d4ff' : 'transparent', display:'flex', alignItems:'center', justifyContent:'center' }}>
                  {selected.has(tx.id) && <span style={{ color:'#000', fontSize:'10px' }}>✓</span>}
                </div>
              </div>
              <div style={{ display:'flex', alignItems:'center', gap:'10px' }}>
                <div style={{ width:'6px', height:'6px', borderRadius:'50%', background: tx.is_fraud ? '#ef4444' : '#10b981', boxShadow: tx.is_fraud ? '0 0 6px #ef4444' : '0 0 6px #10b981', flexShrink:0 }}/>
                <span style={{ fontSize:'12px', color: t.muted2, fontFamily:"'DM Mono',monospace" }}>{tx.id.slice(0,8)}...</span>
              </div>
              <div style={{ fontSize:'13px', fontWeight:'600', color: t.text2 }}>₹{parseFloat(tx.amount).toLocaleString('en-IN',{maximumFractionDigits:0})}</div>
              <div>{tx.risk_level ? <Badge val={tx.risk_level} map={RISK_STYLES}/> : <span style={{color:t.muted4,fontSize:'12px'}}>—</span>}</div>
              <div style={{ fontFamily:"'DM Mono',monospace", fontSize:'13px', fontWeight:'700', color: tx.fraud_score > 0.7 ? '#ef4444' : tx.fraud_score > 0.4 ? '#fbbf24' : '#34d399' }}>{tx.fraud_score ? (tx.fraud_score*100).toFixed(1)+'%' : '—'}</div>
              <div>{tx.status ? <Badge val={tx.status} map={STATUS_STYLES}/> : '—'}</div>
              <div style={{ fontSize:'11px', color: t.muted4 }}>{new Date(tx.created_at).toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit'})}</div>
              <div>
                <button onClick={() => toast(`₹${parseFloat(tx.amount).toFixed(2)} | ${(tx.fraud_score*100).toFixed(1)}% | ${tx.risk_level}`, tx.is_fraud ? 'error' : 'success', tx.is_fraud ? '🚨 Fraud' : '✅ Legit')}
                  style={{ padding:'4px 10px', borderRadius:'6px', border:`1px solid ${t.border}`, background:'transparent', color: t.muted2, fontSize:'11px', cursor:'pointer', fontFamily:'inherit' }}>View</button>
              </div>
            </div>
          ))}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginTop:'16px', padding:'0 4px' }}>
            <div style={{ fontSize:'13px', color: t.muted4 }}>Showing {((page-1)*perPage)+1}–{Math.min(page*perPage,total)} of {total}</div>
            <div style={{ display:'flex', gap:'6px' }}>
              <button onClick={() => setPage(p => Math.max(1,p-1))} disabled={page===1} style={{ padding:'8px 14px', borderRadius:'8px', border:`1px solid ${t.border}`, background:'transparent', color: page===1 ? t.muted4 : t.muted, cursor: page===1 ? 'not-allowed' : 'pointer', fontSize:'13px', fontFamily:'inherit' }}>← Prev</button>
              {Array.from({length:Math.min(5,totalPages)}, (_,i) => {
                const p = Math.max(1,Math.min(page-2,totalPages-4))+i
                return (
                  <button key={p} onClick={() => setPage(p)} style={{ padding:'8px 12px', borderRadius:'8px', border: p===page ? '1px solid rgba(0,212,255,0.4)' : `1px solid ${t.border}`, background: p===page ? 'rgba(0,212,255,0.1)' : 'transparent', color: p===page ? '#00d4ff' : t.muted2, cursor:'pointer', fontSize:'13px', fontFamily:'inherit', fontWeight: p===page ? '700' : '400' }}>{p}</button>
                )
              })}
              <button onClick={() => setPage(p => Math.min(totalPages,p+1))} disabled={page===totalPages} style={{ padding:'8px 14px', borderRadius:'8px', border:`1px solid ${t.border}`, background:'transparent', color: page===totalPages ? t.muted4 : t.muted, cursor: page===totalPages ? 'not-allowed' : 'pointer', fontSize:'13px', fontFamily:'inherit' }}>Next →</button>
            </div>
          </div>
        )}
      </main>

      {/* CSV Batch Upload Progress Overlay */}
      {csvState.status !== 'idle' && (
        <div style={{
          position: 'fixed',
          bottom: '24px',
          left: '240px',
          zIndex: 9998,
          background: t.card || '#0d1117',
          border: `1px solid ${csvState.status === 'error' ? '#ef4444' : csvState.status === 'success' ? '#10b981' : '#00d4ff'}`,
          borderRadius: '16px',
          padding: '16px 20px',
          width: '320px',
          boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
          fontFamily: 'inherit',
          animation: 'slideUp 0.3s ease'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
            <span style={{ fontSize: '18px' }}>
              {csvState.status === 'uploading' ? '📤' : csvState.status === 'processing' ? '⏳' : csvState.status === 'success' ? '✅' : '❌'}
            </span>
            <span style={{ fontSize: '13px', fontWeight: '800', color: csvState.status === 'error' ? '#f87171' : csvState.status === 'success' ? '#34d399' : '#00d4ff', letterSpacing: '0.5px' }}>
              {csvState.status === 'uploading' && 'UPLOADING CSV...'}
              {csvState.status === 'processing' && 'PROCESSING BATCH...'}
              {csvState.status === 'success' && 'BATCH INFERENCE SUCCESS'}
              {csvState.status === 'error' && 'BATCH INFERENCE FAILED'}
            </span>
            {csvState.status !== 'success' && csvState.status !== 'error' && (
              <span style={{ width: '12px', height: '12px', border: `2px solid ${t.border}`, borderTopColor: '#00d4ff', borderRadius: '50%', display: 'inline-block', animation: 'spin 0.8s linear infinite', marginLeft: 'auto' }} />
            )}
          </div>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px', color: t.text2 || '#e2e8f0' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Total Records:</span>
              <span style={{ fontFamily: "'DM Mono', monospace", fontWeight: '700' }}>{csvState.total}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Processed:</span>
              <span style={{ fontFamily: "'DM Mono', monospace", fontWeight: '700', color: '#10b981' }}>{csvState.processed}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Failed:</span>
              <span style={{ fontFamily: "'DM Mono', monospace", fontWeight: '700', color: '#ef4444' }}>{csvState.failed}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span>Fraud Identified:</span>
              <span style={{ fontFamily: "'DM Mono', monospace", fontWeight: '700', color: '#f59e0b' }}>{csvState.fraudCount}</span>
            </div>
            {csvState.duration !== undefined && (
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Elapsed Time:</span>
                <span style={{ fontFamily: "'DM Mono', monospace", fontWeight: '700' }}>{csvState.duration.toFixed(1)}s</span>
              </div>
            )}
            {csvState.currentChunk !== undefined && csvState.totalChunks !== undefined && (
              <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: `1px solid ${t.border || '#1a2035'}`, paddingTop: '6px', marginTop: '6px' }}>
                <span style={{ fontSize: '11px', color: t.muted4 || '#6b7280' }}>
                  Processing chunk {csvState.currentChunk} of {csvState.totalChunks}
                </span>
                <span style={{ fontFamily: "'DM Mono', monospace", fontWeight: '700', color: '#00d4ff' }}>
                  {Math.round(((csvState.processed + csvState.failed) / csvState.total) * 100)}%
                </span>
              </div>
            )}
            {csvState.total > 0 && (
              <div style={{ width: '100%', height: '4px', background: t.border || '#1a2035', borderRadius: '2px', marginTop: '4px', overflow: 'hidden' }}>
                <div style={{
                  width: `${Math.min(100, Math.round(((csvState.processed + csvState.failed) / csvState.total) * 100))}%`,
                  height: '100%',
                  background: 'linear-gradient(90deg, #00d4ff, #6366f1)',
                  transition: 'width 0.3s ease'
                }} />
              </div>
            )}
          </div>
          
          {csvState.status === 'success' && (
            <button onClick={() => setCsvState({ status: 'idle', total: 0, processed: 0, failed: 0, fraudCount: 0, taskId: null })} style={{
              marginTop: '12px', width: '100%', padding: '6px', borderRadius: '8px', border: `1px solid ${t.border}`, background: t.card, color: t.text, fontSize: '11px', cursor: 'pointer', fontFamily: 'inherit'
            }}>
              Dismiss
            </button>
          )}
        </div>
      )}

      <style>{`
        @keyframes slideUp { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:translateY(0)} }
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes shimmer{0%{opacity:0.5}50%{opacity:1}100%{opacity:0.5}}
      `}</style>
    </div>
  )
}
