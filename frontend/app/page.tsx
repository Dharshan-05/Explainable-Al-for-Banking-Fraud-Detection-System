'use client'
import { useEffect, useState, useRef, useCallback } from 'react'
import Sidebar from '@/app/components/Sidebar'
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

const Skeleton = ({ h='20px', w='100%' }: any) => (
  <div style={{ width:w, height:h, borderRadius:'6px',
    background:'linear-gradient(90deg,#111827 25%,#1a2035 50%,#111827 75%)',
    backgroundSize:'200% 100%', animation:'shimmer 1.5s infinite' }}/>
)

export default function TransactionsPage() {
  const { toast } = useToast()
  const fileRef   = useRef<HTMLInputElement>(null)

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
  const reqIdRef = useRef(0)

  useEffect(() => {
    const currentRef = reqIdRef
    return () => {
      currentRef.current++
    }
  }, [])

  const fetchTransactions = useCallback(async (p: number = 1) => {
    const reqId = ++reqIdRef.current
    setLoading(true)
    setError(null)
    try {
      const params: any = { page: p, per_page: perPage }
      if (riskFilter)  params.risk_level = riskFilter
      if (statusFilter) params.status = statusFilter
      if (fraudFilter !== '') params.is_fraud = fraudFilter === 'true'

      const res = await transactionsAPI.list(params)
      if (reqId !== reqIdRef.current) return
      setTransactions(res.data.transactions)
      setTotal(res.data.total)
    } catch (err: any) {
      if (reqId !== reqIdRef.current) return
      if (err.response?.status === 403) {
        setError('forbidden')
      } else {
        setError('error')
      }
      toast('Failed to load transactions', 'error')
    } finally {
      if (reqId === reqIdRef.current) {
        setLoading(false)
      }
    }
  }, [riskFilter, statusFilter, fraudFilter, toast])

  useEffect(() => { fetchTransactions(page) }, [fetchTransactions, page])

  // CSV Upload
  const handleCSV = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setCsvState({ status: 'uploading', total: 0, processed: 0, failed: 0, fraudCount: 0, taskId: null })
    toast('Uploading CSV...', 'info', 'Upload Started')

    try {
      const res = await predictAPI.batchFile(file)
      const { task_id } = res.data

      setCsvState((prev: any) => ({ ...prev, status: 'processing', taskId: task_id }))

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
            setCsvState((prev: any) => ({
              ...prev,
              status: 'error',
              taskId: null
            }))
            toast(taskErr || 'Batch prediction task failed', 'error')
          } else if (result) {
            setCsvState((prev: any) => ({
              ...prev,
              total: result.total ?? prev.total,
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
          setCsvState((prev: any) => ({
            ...prev,
            status: 'error',
            taskId: null
          }))
          toast('Error polling prediction progress', 'error')
        }
      }, 1500)

    } catch (err: any) {
      setCsvState({ status: 'idle', total: 0, processed: 0, failed: 0, fraudCount: 0, taskId: null })
      const errorMsg = err.response?.data?.detail || 'Failed to upload CSV'
      toast(errorMsg, 'error')
    } finally {
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  // Export CSV
  const exportCSV = () => {
    const headers = ['ID','Amount','Risk Level','Fraud Score','Status','Time']
    const rows = transactions.map(t => [
      t.id, t.amount, t.risk_level || '', 
      t.fraud_score ? (t.fraud_score*100).toFixed(1)+'%' : '',
      t.status, t.created_at
    ])
    const csv = [headers, ...rows].map(r => r.join(',')).join('\n')
    const blob = new Blob([csv], { type:'text/csv' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href = url; a.download = 'transactions.csv'; a.click()
    toast('CSV exported!', 'success')
  }

  const filtered = search
    ? transactions.filter(t =>
        t.id.toLowerCase().includes(search.toLowerCase()) ||
        String(t.amount).includes(search) ||
        (t.risk_level||'').toLowerCase().includes(search.toLowerCase())
      )
    : transactions

  const totalPages = Math.ceil(total / perPage)

  const toggleSelect = (id: string) => {
    setSelected(prev => {
      const n = new Set(prev)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })
  }

  if (error) {
    return (
      <div style={{ display:'flex', minHeight:'100vh', background:'#06090f', fontFamily:"'Outfit', sans-serif" }}>
        <Sidebar />
        <main style={{ marginLeft:'240px', flex:1, padding:'28px 32px', display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center' }}>
          <div style={{ fontSize:'48px', marginBottom:'16px' }}>{error === 'forbidden' ? '🔒' : '⚠️'}</div>
          <h2 style={{ fontSize:'20px', fontWeight:'800', color:'#f0f4ff', marginBottom:'8px' }}>
            {error === 'forbidden' ? 'Access Denied' : 'Failed to Load Transactions'}
          </h2>
          <p style={{ color:'#374151', fontSize:'14px', marginBottom:'20px', textAlign:'center', maxWidth:'360px' }}>
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
    <div style={{ display:'flex', minHeight:'100vh', background:'#06090f',
      fontFamily:"'Outfit', sans-serif" }}>
      <Sidebar />
      <main style={{ marginLeft:'240px', flex:1, padding:'28px 32px',
        maxWidth:'calc(100vw - 240px)', animation:'fadeIn 0.4s ease' }}>

        {/* Header */}
        <div style={{ display:'flex', alignItems:'flex-start', justifyContent:'space-between', marginBottom:'24px' }}>
          <div>
            <h1 style={{ fontSize:'24px', fontWeight:'800', color:'#f0f4ff', margin:'0 0 4px', letterSpacing:'-0.5px' }}>
              💳 Transaction <span style={{ background:'linear-gradient(135deg,#00d4ff,#6366f1)',
                WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent' }}>Monitor</span>
            </h1>
            <p style={{ color:'#374151', fontSize:'13px', margin:0 }}>
              {total.toLocaleString()} total transactions · Real-time fraud monitoring
            </p>
          </div>
          <div style={{ display:'flex', gap:'10px' }}>
            {/* CSV Upload */}
            <input ref={fileRef} type="file" accept=".csv" onChange={handleCSV}
              style={{ display:'none' }}/>
            <button onClick={() => fileRef.current?.click()} disabled={csvState.status !== 'idle'} style={{
              padding:'10px 18px', borderRadius:'10px',
              border:'1px solid rgba(0,212,255,0.3)',
              background:'rgba(0,212,255,0.08)', color:'#00d4ff',
              fontSize:'13px', fontWeight:'600', cursor: csvState.status !== 'idle' ? 'not-allowed' : 'pointer', fontFamily:'inherit',
              display:'flex', alignItems:'center', gap:'8px',
            }}>
              {csvState.status !== 'idle' ? '⏳ Uploading...' : '📤 Upload CSV'}
            </button>
            <button onClick={exportCSV} style={{
              padding:'10px 18px', borderRadius:'10px',
              border:'1px solid rgba(99,102,241,0.3)',
              background:'rgba(99,102,241,0.08)', color:'#a5b4fc',
              fontSize:'13px', fontWeight:'600', cursor:'pointer', fontFamily:'inherit',
              display:'flex', alignItems:'center', gap:'8px',
            }}>
              📥 Export CSV
            </button>
          </div>
        </div>

        {/* Stats row */}
        <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:'12px', marginBottom:'20px' }}>
          {[
            { label:'Total',    value: total,                            color:'#00d4ff' },
            { label:'Fraud',    value: transactions.filter(t=>t.is_fraud).length, color:'#ef4444' },
            { label:'Pending',  value: transactions.filter(t=>t.status==='pending').length, color:'#a5b4fc' },
            { label:'Flagged',  value: transactions.filter(t=>t.status==='flagged').length, color:'#f59e0b' },
          ].map(s => (
            <div key={s.label} style={{ background:'#0d1117', border:'1px solid #1a2035',
              borderRadius:'12px', padding:'14px 18px' }}>
              <div style={{ fontSize:'11px', color:'#374151', fontWeight:'600',
                textTransform:'uppercase', letterSpacing:'0.8px', marginBottom:'6px' }}>{s.label}</div>
              <div style={{ fontSize:'24px', fontWeight:'800', color:s.color,
                fontFamily:"'DM Mono', monospace" }}>{s.value}</div>
            </div>
          ))}
        </div>

        {/* Search + Filters */}
        <div style={{ display:'flex', gap:'10px', marginBottom:'16px', flexWrap:'wrap' }}>
          {/* Search */}
          <div style={{ position:'relative', flex:1, minWidth:'200px' }}>
            <span style={{ position:'absolute', left:'12px', top:'50%', transform:'translateY(-50%)',
              fontSize:'14px', opacity:0.4 }}>🔍</span>
            <input value={search} onChange={e => setSearch(e.target.value)}
              placeholder="Search by ID, amount, risk..."
              style={{ width:'100%', padding:'10px 12px 10px 36px', borderRadius:'10px',
                background:'#0d1117', border:'1px solid #1a2035', color:'#e2e8f0',
                fontSize:'13px', outline:'none', boxSizing:'border-box', fontFamily:'inherit' }}
            />
          </div>

          {/* Risk filter */}
          <select value={riskFilter} onChange={e => { setRiskFilter(e.target.value); setPage(1); }} style={{
            padding:'10px 14px', borderRadius:'10px', background:'#0d1117',
            border:'1px solid #1a2035', color: riskFilter ? '#e2e8f0' : '#4b5563',
            fontSize:'13px', outline:'none', cursor:'pointer', fontFamily:'inherit' }}>
            <option value="">All Risk Levels</option>
            <option value="HIGH">🔴 HIGH</option>
            <option value="MEDIUM">🟡 MEDIUM</option>
            <option value="LOW">🟢 LOW</option>
          </select>

          {/* Status filter */}
          <select value={statusFilter} onChange={e => { setStatusFilter(e.target.value); setPage(1); }} style={{
            padding:'10px 14px', borderRadius:'10px', background:'#0d1117',
            border:'1px solid #1a2035', color: statusFilter ? '#e2e8f0' : '#4b5563',
            fontSize:'13px', outline:'none', cursor:'pointer', fontFamily:'inherit' }}>
            <option value="">All Statuses</option>
            <option value="pending">pending</option>
            <option value="flagged">flagged</option>
            <option value="approved">approved</option>
            <option value="rejected">rejected</option>
          </select>

          {/* Fraud filter */}
          <select value={fraudFilter} onChange={e => { setFraudFilter(e.target.value); setPage(1); }} style={{
            padding:'10px 14px', borderRadius:'10px', background:'#0d1117',
            border:'1px solid #1a2035', color: fraudFilter !== '' ? '#e2e8f0' : '#4b5563',
            fontSize:'13px', outline:'none', cursor:'pointer', fontFamily:'inherit' }}>
            <option value="">All Types</option>
            <option value="true">🚨 Fraud Only</option>
            <option value="false">✅ Legit Only</option>
          </select>

          {/* Clear filters */}
          {(riskFilter || statusFilter || fraudFilter || search) && (
            <button onClick={() => { setRiskFilter(''); setStatusFilter(''); setFraudFilter(''); setSearch(''); setPage(1); }}
              style={{ padding:'10px 14px', borderRadius:'10px', border:'1px solid #374151',
                background:'transparent', color:'#6b7280', fontSize:'13px',
                cursor:'pointer', fontFamily:'inherit' }}>
              ✕ Clear
            </button>
          )}
        </div>

        {/* Table */}
        <div style={{ background:'#0d1117', border:'1px solid #1a2035', borderRadius:'16px', overflow:'hidden' }}>
          {/* Table header */}
          <div style={{ display:'grid',
            gridTemplateColumns:'40px 1fr 100px 80px 100px 100px 100px 80px',
            padding:'10px 16px', borderBottom:'1px solid #1a2035',
            background:'rgba(255,255,255,0.02)' }}>
            {['', 'Transaction ID', 'Amount', 'Risk', 'Fraud %', 'Status', 'Time', 'Action'].map(h => (
              <div key={h} style={{ fontSize:'11px', fontWeight:'700', color:'#374151',
                textTransform:'uppercase', letterSpacing:'0.8px' }}>{h}</div>
            ))}
          </div>

          {loading ? (
            <div style={{ padding:'16px', display:'flex', flexDirection:'column', gap:'10px' }}>
              {[...Array(8)].map((_,i) => <Skeleton key={i} h="44px"/>)}
            </div>
          ) : filtered.length === 0 ? (
            <div style={{ textAlign:'center', padding:'60px 0', color:'#374151' }}>
              <div style={{ fontSize:'40px', marginBottom:'12px' }}>🔍</div>
              <div style={{ fontSize:'14px' }}>No transactions found</div>
            </div>
          ) : (
            filtered.map((t, i) => (
              <div key={t.id} style={{
                display:'grid',
                gridTemplateColumns:'40px 1fr 100px 80px 100px 100px 100px 80px',
                padding:'12px 16px', borderBottom:'1px solid #111827',
                background: selected.has(t.id) ? 'rgba(0,212,255,0.04)' : 'transparent',
                transition:'background 0.15s', alignItems:'center',
                animation:`slideUp 0.3s ease ${i*0.02}s both`,
              }}
              onMouseEnter={e => { if(!selected.has(t.id)) (e.currentTarget as HTMLElement).style.background='rgba(255,255,255,0.02)' }}
              onMouseLeave={e => { if(!selected.has(t.id)) (e.currentTarget as HTMLElement).style.background='transparent' }}>

                {/* Checkbox */}
                <div onClick={() => toggleSelect(t.id)} style={{ cursor:'pointer' }}>
                  <div style={{ width:'16px', height:'16px', borderRadius:'4px',
                    border:`1px solid ${selected.has(t.id) ? '#00d4ff' : '#1a2035'}`,
                    background: selected.has(t.id) ? '#00d4ff' : 'transparent',
                    display:'flex', alignItems:'center', justifyContent:'center' }}>
                    {selected.has(t.id) && <span style={{ color:'#000', fontSize:'10px' }}>✓</span>}
                  </div>
                </div>

                {/* ID */}
                <div style={{ display:'flex', alignItems:'center', gap:'10px' }}>
                  <div style={{ width:'6px', height:'6px', borderRadius:'50%', flexShrink:0,
                    background: t.is_fraud ? '#ef4444' : '#10b981',
                    boxShadow: t.is_fraud ? '0 0 6px #ef4444' : '0 0 6px #10b981' }}/>
                  <span style={{ fontSize:'12px', color:'#6b7280',
                    fontFamily:"'DM Mono', monospace" }}>
                    {t.id.slice(0,8)}...
                  </span>
                </div>

                {/* Amount */}
                <div style={{ fontSize:'13px', fontWeight:'600', color:'#e2e8f0' }}>
                  ₹{parseFloat(t.amount).toLocaleString('en-IN', {maximumFractionDigits:0})}
                </div>

                {/* Risk */}
                <div>{t.risk_level ? <Badge val={t.risk_level} map={RISK_STYLES}/> : <span style={{color:'#374151',fontSize:'12px'}}>—</span>}</div>

                {/* Fraud score */}
                <div style={{ fontFamily:"'DM Mono',monospace", fontSize:'13px', fontWeight:'700',
                  color: t.fraud_score > 0.7 ? '#ef4444' : t.fraud_score > 0.4 ? '#fbbf24' : '#34d399' }}>
                  {t.fraud_score ? (t.fraud_score*100).toFixed(1)+'%' : '—'}
                </div>

                {/* Status */}
                <div>{t.status ? <Badge val={t.status} map={STATUS_STYLES}/> : '—'}</div>

                {/* Time */}
                <div style={{ fontSize:'11px', color:'#4b5563' }}>
                  {new Date(t.created_at).toLocaleTimeString('en-IN', {hour:'2-digit', minute:'2-digit'})}
                </div>

                {/* Action */}
                <div>
                  <button onClick={() => {
                    toast(`Transaction: ₹${parseFloat(t.amount).toFixed(2)} | Score: ${(t.fraud_score*100).toFixed(1)}% | ${t.risk_level}`, 
                      t.is_fraud ? 'error' : 'success', t.is_fraud ? '🚨 Fraud' : '✅ Legitimate')
                  }} style={{
                    padding:'4px 10px', borderRadius:'6px', border:'1px solid #1a2035',
                    background:'transparent', color:'#6b7280', fontSize:'11px',
                    cursor:'pointer', fontFamily:'inherit' }}>
                    View
                  </button>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between',
            marginTop:'16px', padding:'0 4px' }}>
            <div style={{ fontSize:'13px', color:'#4b5563' }}>
              Showing {((page-1)*perPage)+1}–{Math.min(page*perPage,total)} of {total}
            </div>
            <div style={{ display:'flex', gap:'6px' }}>
              <button onClick={() => setPage(p => Math.max(1,p-1))} disabled={page===1} style={{
                padding:'8px 14px', borderRadius:'8px', border:'1px solid #1a2035',
                background:'transparent', color: page===1 ? '#374151' : '#94a3b8',
                cursor: page===1 ? 'not-allowed' : 'pointer', fontSize:'13px', fontFamily:'inherit' }}>
                ← Prev
              </button>
              {Array.from({length: Math.min(5, totalPages)}, (_, i) => {
                const p = Math.max(1, Math.min(page-2, totalPages-4)) + i
                return (
                  <button key={p} onClick={() => setPage(p)} style={{
                    padding:'8px 12px', borderRadius:'8px',
                    border: p===page ? '1px solid rgba(0,212,255,0.4)' : '1px solid #1a2035',
                    background: p===page ? 'rgba(0,212,255,0.1)' : 'transparent',
                    color: p===page ? '#00d4ff' : '#6b7280',
                    cursor:'pointer', fontSize:'13px', fontFamily:'inherit', fontWeight: p===page ? '700' : '400' }}>
                    {p}
                  </button>
                )
              })}
              <button onClick={() => setPage(p => Math.min(totalPages,p+1))} disabled={page===totalPages} style={{
                padding:'8px 14px', borderRadius:'8px', border:'1px solid #1a2035',
                background:'transparent', color: page===totalPages ? '#374151' : '#94a3b8',
                cursor: page===totalPages ? 'not-allowed' : 'pointer', fontSize:'13px', fontFamily:'inherit' }}>
                Next →
              </button>
            </div>
          </div>
        )}
      </main>

      {/* CSV Batch Upload Progress Overlay */}
      {csvState.status !== 'idle' && (
        <div style={{
          position: 'fixed',
          bottom: '24px',
          left: '260px',
          zIndex: 9998,
          background: '#0d1117',
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
              <span style={{ width: '12px', height: '12px', border: '2px solid #1a2035', borderTopColor: '#00d4ff', borderRadius: '50%', display: 'inline-block', animation: 'spin 0.8s linear infinite', marginLeft: 'auto' }} />
            )}
          </div>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '12px', color: '#e2e8f0' }}>
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
              <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: '1px solid #1a2035', paddingTop: '6px', marginTop: '6px' }}>
                <span style={{ fontSize: '11px', color: '#6b7280' }}>
                  Processing chunk {csvState.currentChunk} of {csvState.totalChunks}
                </span>
                <span style={{ fontFamily: "'DM Mono', monospace", fontWeight: '700', color: '#00d4ff' }}>
                  {Math.round(((csvState.processed + csvState.failed) / csvState.total) * 100)}%
                </span>
              </div>
            )}
            {csvState.total > 0 && (
              <div style={{ width: '100%', height: '4px', background: '#1a2035', borderRadius: '2px', marginTop: '4px', overflow: 'hidden' }}>
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
              marginTop: '12px', width: '100%', padding: '6px', borderRadius: '8px', border: '1px solid #1a2035', background: '#0d1117', color: '#e2e8f0', fontSize: '11px', cursor: 'pointer', fontFamily: 'inherit'
            }}>
              Dismiss
            </button>
          )}
        </div>
      )}

      <style>{`
        @keyframes fadeIn  { from{opacity:0} to{opacity:1} }
        @keyframes slideUp { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:translateY(0)} }
        @keyframes shimmer { 0%{background-position:-200% 0} 100%{background-position:200% 0} }
        @keyframes spin { to { transform: rotate(360deg); } }
        select option { background: #0d1117; }
      `}</style>
    </div>
  )
}
