'use client'
import { useEffect, useState, useRef, useCallback } from 'react'
import Sidebar from '@/app/components/Sidebar'
import { useTheme } from '@/app/components/ThemeContext'
import { useToast } from '@/app/components/Toast'
import { transactionsAPI, predictAPI } from '@/lib/api'
import { useStore } from '@/lib/store'

// ─── Type Definitions ────────────────────
interface Transaction {
  id: string
  amount: number
  merchant?: string
  merchant_category?: string
  location?: string
  card_last4?: string
  fraud_score?: number
  fraud_percentage?: number
  is_fraud?: boolean
  risk_level?: string
  risk_color?: string
  explanation?: string
  top_features?: any[]
  status: string
  reviewed_by?: string
  review_notes?: string
  reviewed_at?: string
  assigned_analyst?: string
  created_at: string
}

// ─── Style Maps ──────────────────────────
const RISK_STYLES: Record<string, { bg: string; color: string; border: string }> = {
  HIGH:   { bg:'rgba(239,68,68,0.12)',  color:'#f87171', border:'rgba(239,68,68,0.3)'  },
  MEDIUM: { bg:'rgba(245,158,11,0.12)', color:'#fbbf24', border:'rgba(245,158,11,0.3)' },
  LOW:    { bg:'rgba(16,185,129,0.12)', color:'#34d399', border:'rgba(16,185,129,0.3)' },
}

const STATUS_STYLES: Record<string, { bg: string; color: string; border: string }> = {
  PENDING:  { bg:'rgba(99,102,241,0.12)',  color:'#a5b4fc', border:'rgba(99,102,241,0.3)'  },
  APPROVED: { bg:'rgba(16,185,129,0.12)',  color:'#34d399', border:'rgba(16,185,129,0.3)'  },
  REJECTED: { bg:'rgba(239,68,68,0.12)',   color:'#f87171', border:'rgba(239,68,68,0.3)'   },
  FLAGGED:  { bg:'rgba(245,158,11,0.12)',  color:'#fbbf24', border:'rgba(245,158,11,0.3)'  },
  // lowercase aliases for backward compatibility
  pending:  { bg:'rgba(99,102,241,0.12)',  color:'#a5b4fc', border:'rgba(99,102,241,0.3)'  },
  approved: { bg:'rgba(16,185,129,0.12)',  color:'#34d399', border:'rgba(16,185,129,0.3)'  },
  rejected: { bg:'rgba(239,68,68,0.12)',   color:'#f87171', border:'rgba(239,68,68,0.3)'   },
  flagged:  { bg:'rgba(245,158,11,0.12)',  color:'#fbbf24', border:'rgba(245,158,11,0.3)'  },
}

// ─── Sub-components ──────────────────────
const Badge = ({ val, map }: { val: string; map: Record<string, any> }) => {
  const s = map[val?.toUpperCase()] || map[val] || map['pending'] || { bg: 'rgba(100,100,100,0.1)', color: '#9ca3af', border: 'rgba(100,100,100,0.3)' }
  return (
    <span style={{ padding:'3px 10px', borderRadius:'999px', fontSize:'11px', fontWeight:'700',
      background: s.bg, color: s.color, border:`1px solid ${s.border}`, whiteSpace:'nowrap' }}>
      {val?.toUpperCase()}
    </span>
  )
}

const Spinner = ({ size = 14, color = '#00d4ff' }: { size?: number; color?: string }) => (
  <span style={{ width:`${size}px`, height:`${size}px`, border:`2px solid rgba(255,255,255,0.1)`,
    borderTopColor: color, borderRadius:'50%', display:'inline-block',
    animation:'spin 0.7s linear infinite' }}/>
)

// ─── Export Modal ─────────────────────────
function ExportModal({ onClose, selected, currentPageIds, filters, total }: {
  onClose: () => void
  selected: Set<string>
  currentPageIds: string[]
  filters: any
  total: number
}) {
  const { t } = useTheme()
  const { toast } = useToast()
  const [exportType, setExportType] = useState<string>('current_page')
  const [customLimit, setCustomLimit] = useState('100')
  const [customRisk, setCustomRisk] = useState('ALL')
  const [customStatus, setCustomStatus] = useState('ALL')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [loading, setLoading] = useState(false)
  const [validationError, setValidationError] = useState('')

  const estimatedCount = () => {
    if (exportType === 'current_page') return currentPageIds.length
    if (exportType === 'selected') return selected.size
    if (exportType === 'all') return total
    if (exportType === 'filtered') return total
    if (exportType === 'custom') return Math.min(parseInt(customLimit) || 0, total)
    return 0
  }

  const handleExport = async () => {
    setValidationError('')
    if (exportType === 'selected' && selected.size === 0) {
      setValidationError('No rows selected. Please select at least one transaction.')
      return
    }
    if (exportType === 'custom') {
      const n = parseInt(customLimit)
      if (!customLimit || isNaN(n) || n <= 0) {
        setValidationError('Please enter a valid number of transactions (> 0).')
        return
      }
    }

    setLoading(true)
    try {
      const payload: any = {
        exportType,
        transactionIds: exportType === 'selected' ? Array.from(selected) : exportType === 'current_page' ? currentPageIds : [],
        filters: {
          riskLevel: customRisk,
          status: customStatus,
          dateFrom: dateFrom || null,
          dateTo: dateTo || null,
          limit: exportType === 'custom' ? parseInt(customLimit) : undefined,
          isFraud: filters.fraudFilter === 'true' ? true : filters.fraudFilter === 'false' ? false : undefined,
        }
      }
      if (exportType === 'filtered') {
        payload.filters.riskLevel = filters.riskFilter || 'ALL'
        payload.filters.status = filters.statusFilter || 'ALL'
      }

      const res = await transactionsAPI.exportCSV(payload)
      const url = URL.createObjectURL(new Blob([res.data], { type: 'text/csv' }))
      const a = document.createElement('a')
      a.href = url
      a.download = `transactions_${exportType}_${new Date().toISOString().slice(0,10)}.csv`
      a.click()
      URL.revokeObjectURL(url)
      toast('CSV exported successfully!', 'success', 'Export Complete')
      onClose()
    } catch (err: any) {
      toast(err.response?.data?.detail || 'Export failed. Please try again.', 'error', 'Export Failed')
    } finally {
      setLoading(false)
    }
  }

  const cardStyle = { background: t.card, border:`1px solid ${t.border}`, borderRadius:'12px', padding:'14px 16px', cursor:'pointer', transition:'all 0.2s', marginBottom:'8px' }
  const selectedCard = { ...cardStyle, border:'1px solid rgba(0,212,255,0.5)', background:'rgba(0,212,255,0.05)' }
  const inputSty = { width:'100%', padding:'9px 12px', borderRadius:'8px', background: t.input, border:`1px solid ${t.border}`, color: t.text, fontSize:'13px', outline:'none', fontFamily:'inherit', boxSizing:'border-box' as const }

  const exportOptions = [
    { key:'current_page', label:'Current Page Transactions', desc:`${currentPageIds.length} visible rows`, icon:'📄' },
    { key:'selected', label:'Selected Transactions', desc:`${selected.size} selected rows`, icon:'☑️' },
    { key:'filtered', label:'Filtered Results', desc:'Matching active filter criteria', icon:'🔍' },
    { key:'all', label:'All Transactions', desc:`${total.toLocaleString()} total records`, icon:'📦' },
    { key:'custom', label:'Custom Range', desc:'Specify count, date range, risk & status', icon:'⚙️' },
  ]

  return (
    <div style={{ position:'fixed', inset:0, background:'rgba(0,0,0,0.7)', backdropFilter:'blur(4px)', zIndex:10000, display:'flex', alignItems:'center', justifyContent:'center', padding:'16px' }}
      onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'20px', width:'100%', maxWidth:'520px',
        boxShadow:'0 24px 64px rgba(0,0,0,0.7)', animation:'modalIn 0.3s cubic-bezier(0.34,1.56,0.64,1)' }}>
        {/* Header */}
        <div style={{ padding:'20px 24px', borderBottom:`1px solid ${t.border}`, display:'flex', alignItems:'center', justifyContent:'space-between' }}>
          <div>
            <div style={{ fontSize:'16px', fontWeight:'800', color: t.text }}>📥 Export Transactions</div>
            <div style={{ fontSize:'12px', color: t.muted4, marginTop:'2px' }}>Choose what to download as CSV</div>
          </div>
          <button onClick={onClose} style={{ background:'none', border:`1px solid ${t.border}`, borderRadius:'8px', color: t.muted2, cursor:'pointer', padding:'6px 10px', fontSize:'16px' }}>✕</button>
        </div>

        <div style={{ padding:'20px 24px', maxHeight:'65vh', overflowY:'auto' }}>
          {/* Export Options */}
          <div style={{ marginBottom:'16px' }}>
            {exportOptions.map(opt => (
              <div key={opt.key} style={exportType === opt.key ? selectedCard : cardStyle} onClick={() => setExportType(opt.key)}>
                <div style={{ display:'flex', alignItems:'center', gap:'10px' }}>
                  <div style={{ width:'32px', height:'32px', borderRadius:'8px', background: exportType === opt.key ? 'rgba(0,212,255,0.1)' : 'rgba(255,255,255,0.03)', display:'flex', alignItems:'center', justifyContent:'center', fontSize:'16px', border:`1px solid ${exportType === opt.key ? 'rgba(0,212,255,0.3)' : t.border}` }}>{opt.icon}</div>
                  <div style={{ flex:1 }}>
                    <div style={{ fontSize:'13px', fontWeight:'700', color: exportType === opt.key ? '#00d4ff' : t.text }}>{opt.label}</div>
                    <div style={{ fontSize:'11px', color: t.muted4 }}>{opt.desc}</div>
                  </div>
                  <div style={{ width:'16px', height:'16px', borderRadius:'50%', border:`2px solid ${exportType === opt.key ? '#00d4ff' : t.border}`, display:'flex', alignItems:'center', justifyContent:'center' }}>
                    {exportType === opt.key && <div style={{ width:'8px', height:'8px', borderRadius:'50%', background:'#00d4ff' }}/>}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Custom Range Options */}
          {exportType === 'custom' && (
            <div style={{ background:'rgba(0,212,255,0.03)', border:'1px solid rgba(0,212,255,0.1)', borderRadius:'12px', padding:'16px', marginBottom:'12px' }}>
              <div style={{ fontSize:'12px', fontWeight:'700', color:'#00d4ff', letterSpacing:'0.8px', marginBottom:'12px', textTransform:'uppercase' }}>⚙️ Custom Filters</div>
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'10px', marginBottom:'10px' }}>
                <div>
                  <label style={{ fontSize:'11px', color: t.muted4, fontWeight:'600', display:'block', marginBottom:'4px' }}>Number of Records</label>
                  <input type="number" min="1" max="10000" value={customLimit} onChange={e => setCustomLimit(e.target.value)}
                    style={inputSty} placeholder="e.g. 100"/>
                </div>
                <div>
                  <label style={{ fontSize:'11px', color: t.muted4, fontWeight:'600', display:'block', marginBottom:'4px' }}>Risk Level</label>
                  <select value={customRisk} onChange={e => setCustomRisk(e.target.value)} style={inputSty}>
                    <option value="ALL">All Levels</option>
                    <option value="HIGH">HIGH</option>
                    <option value="MEDIUM">MEDIUM</option>
                    <option value="LOW">LOW</option>
                  </select>
                </div>
                <div>
                  <label style={{ fontSize:'11px', color: t.muted4, fontWeight:'600', display:'block', marginBottom:'4px' }}>Status</label>
                  <select value={customStatus} onChange={e => setCustomStatus(e.target.value)} style={inputSty}>
                    <option value="ALL">All Statuses</option>
                    <option value="PENDING">PENDING</option>
                    <option value="APPROVED">APPROVED</option>
                    <option value="REJECTED">REJECTED</option>
                    <option value="FLAGGED">FLAGGED</option>
                  </select>
                </div>
                <div>
                  <label style={{ fontSize:'11px', color: t.muted4, fontWeight:'600', display:'block', marginBottom:'4px' }}>Date From</label>
                  <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} style={{ ...inputSty, colorScheme:'dark' }}/>
                </div>
                <div>
                  <label style={{ fontSize:'11px', color: t.muted4, fontWeight:'600', display:'block', marginBottom:'4px' }}>Date To</label>
                  <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} style={{ ...inputSty, colorScheme:'dark' }}/>
                </div>
              </div>
            </div>
          )}

          {/* Estimated count */}
          <div style={{ background:'rgba(99,102,241,0.05)', border:'1px solid rgba(99,102,241,0.15)', borderRadius:'8px', padding:'10px 14px', display:'flex', justifyContent:'space-between', alignItems:'center' }}>
            <span style={{ fontSize:'12px', color: t.muted2 }}>Estimated records to export:</span>
            <span style={{ fontSize:'14px', fontWeight:'800', color:'#a5b4fc', fontFamily:"'DM Mono',monospace" }}>{estimatedCount().toLocaleString()}</span>
          </div>

          {validationError && (
            <div style={{ marginTop:'10px', background:'rgba(239,68,68,0.08)', border:'1px solid rgba(239,68,68,0.2)', borderRadius:'8px', padding:'10px 14px', fontSize:'12px', color:'#f87171' }}>
              ⚠️ {validationError}
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{ padding:'16px 24px', borderTop:`1px solid ${t.border}`, display:'flex', gap:'10px', justifyContent:'flex-end' }}>
          <button onClick={onClose} style={{ padding:'10px 20px', borderRadius:'10px', border:`1px solid ${t.border}`, background:'transparent', color: t.muted2, fontSize:'13px', fontWeight:'600', cursor:'pointer', fontFamily:'inherit' }}>
            Cancel
          </button>
          <button onClick={handleExport} disabled={loading} style={{ padding:'10px 20px', borderRadius:'10px', border:'none',
            background: loading ? '#1a2035' : 'linear-gradient(135deg,#00d4ff,#6366f1)', color: loading ? '#374151' : '#fff',
            fontSize:'13px', fontWeight:'700', cursor: loading ? 'not-allowed' : 'pointer', fontFamily:'inherit',
            display:'flex', alignItems:'center', gap:'8px', minWidth:'140px', justifyContent:'center' }}>
            {loading ? <><Spinner/> Exporting...</> : '📥 Download CSV'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Review Drawer ────────────────────────
function ReviewDrawer({ tx, onClose, onUpdate, currentUser }: {
  tx: Transaction
  onClose: () => void
  onUpdate: (updated: Transaction) => void
  currentUser: any
}) {
  const { t, dark } = useTheme()
  const { toast } = useToast()
  const [action, setAction] = useState<'approve' | 'reject' | 'flag' | null>(null)
  const [notes, setNotes] = useState('')
  const [assignedAnalyst, setAssignedAnalyst] = useState('')
  const [loading, setLoading] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const canReview = ['admin', 'analyst', 'fraud_analyst'].includes(currentUser?.role)

  const handleAction = async () => {
    if (action === 'reject' && !notes.trim()) {
      toast('Review notes are mandatory for rejection.', 'error', 'Validation Error')
      return
    }
    setLoading(true)
    try {
      let res: any
      if (action === 'approve') res = await transactionsAPI.approve(tx.id, notes || undefined)
      else if (action === 'reject') res = await transactionsAPI.reject(tx.id, notes)
      else if (action === 'flag') res = await transactionsAPI.flag(tx.id, notes || undefined, assignedAnalyst || undefined)

      onUpdate(res.data)
      const labels: Record<string, string> = { approve: 'Approved', reject: 'Rejected', flag: 'Flagged' }
      toast(`Transaction ${labels[action!]} successfully`, 'success', `✅ ${labels[action!]}`)
      setConfirmOpen(false)
      onClose()
    } catch (err: any) {
      toast(err.response?.data?.detail || 'Action failed. Please try again.', 'error', 'Error')
    } finally {
      setLoading(false)
    }
  }

  const inputSty = { width:'100%', padding:'9px 12px', borderRadius:'8px', background: t.input, border:`1px solid ${t.border}`, color: t.text, fontSize:'13px', outline:'none', fontFamily:'inherit', boxSizing:'border-box' as const }

  const actionConfig = {
    approve: { label:'Approve Transaction', icon:'✅', color:'#10b981', bg:'rgba(16,185,129,0.1)', border:'rgba(16,185,129,0.3)', hint:'Optional notes for approval' },
    reject:  { label:'Reject Transaction', icon:'❌', color:'#ef4444', bg:'rgba(239,68,68,0.1)', border:'rgba(239,68,68,0.3)', hint:'Notes are REQUIRED for rejection' },
    flag:    { label:'Flag for Investigation', icon:'🚩', color:'#f59e0b', bg:'rgba(245,158,11,0.1)', border:'rgba(245,158,11,0.3)', hint:'Optional investigation notes' },
  }

  return (
    <>
      {/* Backdrop */}
      <div style={{ position:'fixed', inset:0, background:'rgba(0,0,0,0.5)', backdropFilter:'blur(2px)', zIndex:9998 }} onClick={onClose}/>
      {/* Drawer */}
      <div style={{ position:'fixed', right:0, top:0, bottom:0, width:'min(580px, 100vw)', background: t.card,
        borderLeft:`1px solid ${t.border}`, zIndex:9999, overflowY:'auto', animation:'drawerIn 0.35s cubic-bezier(0.22,1,0.36,1)', display:'flex', flexDirection:'column' }}>
        {/* Header */}
        <div style={{ padding:'20px 24px', borderBottom:`1px solid ${t.border}`, display:'flex', alignItems:'center', justifyContent:'space-between', flexShrink:0 }}>
          <div>
            <div style={{ fontSize:'16px', fontWeight:'800', color: t.text }}>🔍 Transaction Review</div>
            <div style={{ fontSize:'11px', color: t.muted4, fontFamily:"'DM Mono',monospace", marginTop:'2px' }}>{tx.id}</div>
          </div>
          <button onClick={onClose} style={{ background:'none', border:`1px solid ${t.border}`, borderRadius:'8px', color: t.muted2, cursor:'pointer', padding:'6px 10px', fontSize:'16px' }}>✕</button>
        </div>

        <div style={{ flex:1, overflowY:'auto', padding:'20px 24px' }}>
          {/* Status Banner */}
          <div style={{ marginBottom:'20px', display:'flex', alignItems:'center', gap:'10px' }}>
            <div style={{ width:'8px', height:'8px', borderRadius:'50%', background: tx.is_fraud ? '#ef4444' : '#10b981', boxShadow: tx.is_fraud ? '0 0 8px #ef4444' : '0 0 8px #10b981' }}/>
            <span style={{ fontSize:'13px', color: tx.is_fraud ? '#f87171' : '#34d399', fontWeight:'700' }}>{tx.is_fraud ? '🚨 Fraudulent Transaction' : '✅ Legitimate Transaction'}</span>
            <div style={{ marginLeft:'auto' }}><Badge val={tx.status} map={STATUS_STYLES}/></div>
          </div>

          {/* Transaction Details */}
          <div style={{ background: dark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)', border:`1px solid ${t.border}`, borderRadius:'12px', padding:'16px', marginBottom:'16px' }}>
            <div style={{ fontSize:'11px', fontWeight:'700', color:'#00d4ff', letterSpacing:'0.8px', textTransform:'uppercase', marginBottom:'12px' }}>Transaction Details</div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'10px' }}>
              {[
                { label:'Amount', value:`₹${parseFloat(String(tx.amount)).toLocaleString('en-IN', { maximumFractionDigits:2 })}` },
                { label:'Risk Level', value: tx.risk_level ? <Badge val={tx.risk_level} map={RISK_STYLES}/> : '—' },
                { label:'Fraud Score', value: tx.fraud_score !== undefined && tx.fraud_score !== null ? `${(tx.fraud_score * 100).toFixed(1)}%` : '—', color: tx.fraud_score! > 0.7 ? '#ef4444' : tx.fraud_score! > 0.4 ? '#fbbf24' : '#34d399' },
                { label:'Status', value: <Badge val={tx.status} map={STATUS_STYLES}/> },
                { label:'Created', value: new Date(tx.created_at).toLocaleString('en-IN') },
                { label:'Card Last 4', value: tx.card_last4 ? `****${tx.card_last4}` : '—' },
                { label:'Merchant', value: tx.merchant || '—' },
                { label:'Location', value: tx.location || '—' },
              ].map(item => (
                <div key={item.label} style={{ padding:'8px 10px', background: t.card2, borderRadius:'8px' }}>
                  <div style={{ fontSize:'10px', color: t.muted4, fontWeight:'600', textTransform:'uppercase', letterSpacing:'0.5px', marginBottom:'4px' }}>{item.label}</div>
                  {typeof item.value === 'string'
                    ? <div style={{ fontSize:'13px', fontWeight:'600', color: (item as any).color || t.text }}>{item.value}</div>
                    : item.value}
                </div>
              ))}
            </div>
          </div>

          {/* SHAP Explanation */}
          {tx.explanation && (
            <div style={{ background: dark ? 'rgba(99,102,241,0.05)' : 'rgba(99,102,241,0.03)', border:'1px solid rgba(99,102,241,0.2)', borderRadius:'12px', padding:'14px', marginBottom:'16px' }}>
              <div style={{ fontSize:'11px', fontWeight:'700', color:'#a5b4fc', letterSpacing:'0.8px', textTransform:'uppercase', marginBottom:'8px' }}>🧠 SHAP Explanation</div>
              <div style={{ fontSize:'13px', color: t.muted2, lineHeight:1.6 }}>{tx.explanation}</div>
            </div>
          )}

          {/* Top SHAP Features */}
          {tx.top_features && tx.top_features.length > 0 && (
            <div style={{ border:`1px solid ${t.border}`, borderRadius:'12px', padding:'14px', marginBottom:'16px' }}>
              <div style={{ fontSize:'11px', fontWeight:'700', color:'#00d4ff', letterSpacing:'0.8px', textTransform:'uppercase', marginBottom:'10px' }}>📊 Top Contributing Features</div>
              <div style={{ display:'flex', flexDirection:'column', gap:'8px' }}>
                {tx.top_features.slice(0, 6).map((f: any, i: number) => {
                  const pct = Math.abs(f.shap_value || 0)
                  const maxPct = Math.abs(tx.top_features![0].shap_value || 1)
                  const barWidth = Math.min(100, (pct / maxPct) * 100)
                  const isPos = (f.shap_value || 0) > 0
                  return (
                    <div key={i} style={{ display:'flex', flexDirection:'column', gap:'3px' }}>
                      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
                        <span style={{ fontSize:'12px', color: t.text2, fontFamily:"'DM Mono',monospace" }}>{f.feature}</span>
                        <div style={{ display:'flex', alignItems:'center', gap:'6px' }}>
                          <span style={{ fontSize:'10px', color: isPos ? '#f87171' : '#34d399', fontWeight:'700' }}>{f.direction || (isPos ? 'increases' : 'decreases')} risk</span>
                          <span style={{ fontSize:'11px', fontWeight:'700', color: isPos ? '#f87171' : '#34d399', fontFamily:"'DM Mono',monospace" }}>{f.shap_value?.toFixed(4)}</span>
                        </div>
                      </div>
                      <div style={{ height:'4px', background: 'rgba(255,255,255,0.05)', borderRadius:'2px', overflow:'hidden' }}>
                        <div style={{ height:'100%', width:`${barWidth}%`, background: isPos ? 'linear-gradient(90deg,#ef4444,#f87171)' : 'linear-gradient(90deg,#10b981,#34d399)', borderRadius:'2px', transition:'width 0.5s ease' }}/>
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Review History */}
          {tx.reviewed_by && (
            <div style={{ border:`1px solid ${t.border}`, borderRadius:'12px', padding:'14px', marginBottom:'16px' }}>
              <div style={{ fontSize:'11px', fontWeight:'700', color: t.muted4, letterSpacing:'0.8px', textTransform:'uppercase', marginBottom:'8px' }}>📋 Review History</div>
              <div style={{ display:'flex', flexDirection:'column', gap:'6px' }}>
                <div style={{ display:'flex', justifyContent:'space-between' }}>
                  <span style={{ fontSize:'12px', color: t.muted2 }}>Reviewed by:</span>
                  <span style={{ fontSize:'12px', fontWeight:'600', color: t.text }}>{tx.reviewed_by}</span>
                </div>
                {tx.reviewed_at && (
                  <div style={{ display:'flex', justifyContent:'space-between' }}>
                    <span style={{ fontSize:'12px', color: t.muted2 }}>Reviewed at:</span>
                    <span style={{ fontSize:'12px', color: t.text }}>{new Date(tx.reviewed_at).toLocaleString('en-IN')}</span>
                  </div>
                )}
                {tx.review_notes && (
                  <div>
                    <span style={{ fontSize:'12px', color: t.muted2 }}>Notes:</span>
                    <div style={{ fontSize:'12px', color: t.text, marginTop:'4px', padding:'8px', background: t.card2, borderRadius:'6px' }}>{tx.review_notes}</div>
                  </div>
                )}
                {tx.assigned_analyst && (
                  <div style={{ display:'flex', justifyContent:'space-between' }}>
                    <span style={{ fontSize:'12px', color: t.muted2 }}>Assigned:</span>
                    <span style={{ fontSize:'12px', fontWeight:'600', color:'#fbbf24' }}>{tx.assigned_analyst}</span>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Action Buttons */}
          {canReview && (
            <div>
              <div style={{ fontSize:'11px', fontWeight:'700', color: t.muted4, letterSpacing:'0.8px', textTransform:'uppercase', marginBottom:'10px' }}>⚡ Actions</div>
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:'8px' }}>
                {[
                  { key:'approve' as const, label:'Approve', icon:'✅', color:'#10b981', hoverBg:'rgba(16,185,129,0.1)', border:'rgba(16,185,129,0.3)' },
                  { key:'reject' as const, label:'Reject', icon:'❌', color:'#ef4444', hoverBg:'rgba(239,68,68,0.1)', border:'rgba(239,68,68,0.3)' },
                  { key:'flag' as const, label:'Flag', icon:'🚩', color:'#f59e0b', hoverBg:'rgba(245,158,11,0.1)', border:'rgba(245,158,11,0.3)' },
                ].map(btn => (
                  <button key={btn.key}
                    onClick={() => { setAction(btn.key); setNotes(''); setAssignedAnalyst(''); setConfirmOpen(true) }}
                    style={{ padding:'10px 8px', borderRadius:'10px', border:`1px solid ${btn.border}`, background: btn.hoverBg, color: btn.color,
                      fontSize:'12px', fontWeight:'700', cursor:'pointer', fontFamily:'inherit', display:'flex', alignItems:'center', justifyContent:'center', gap:'6px', transition:'all 0.2s' }}>
                    {btn.icon} {btn.label}
                  </button>
                ))}
              </div>
            </div>
          )}
          {!canReview && (
            <div style={{ background:'rgba(99,102,241,0.05)', border:'1px solid rgba(99,102,241,0.15)', borderRadius:'10px', padding:'12px 14px', display:'flex', alignItems:'center', gap:'8px' }}>
              <span style={{ fontSize:'16px' }}>🔒</span>
              <span style={{ fontSize:'12px', color: t.muted2 }}>You have view-only access. Only Admin or Analyst roles can approve, reject, or flag transactions.</span>
            </div>
          )}
        </div>
      </div>

      {/* Confirm dialog */}
      {confirmOpen && action && (
        <div style={{ position:'fixed', inset:0, background:'rgba(0,0,0,0.85)', zIndex:10001, display:'flex', alignItems:'center', justifyContent:'center', padding:'16px' }}>
          <div style={{ background: t.card, border:`1px solid ${actionConfig[action].border}`, borderRadius:'16px', padding:'24px', maxWidth:'400px', width:'100%', animation:'modalIn 0.25s ease' }}>
            <div style={{ fontSize:'24px', textAlign:'center', marginBottom:'12px' }}>{actionConfig[action].icon}</div>
            <div style={{ fontSize:'15px', fontWeight:'800', color: t.text, textAlign:'center', marginBottom:'6px' }}>{actionConfig[action].label}</div>
            <div style={{ fontSize:'12px', color: t.muted4, textAlign:'center', marginBottom:'16px' }}>
              Transaction: <span style={{ fontFamily:"'DM Mono',monospace", color: t.muted2 }}>{tx.id.slice(0,12)}...</span>
            </div>

            <div style={{ marginBottom:'12px' }}>
              <label style={{ fontSize:'11px', color: t.muted4, fontWeight:'600', display:'block', marginBottom:'6px' }}>
                {actionConfig[action].hint} {action === 'reject' && <span style={{ color:'#ef4444' }}>*</span>}
              </label>
              <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={3}
                placeholder={action === 'reject' ? 'Enter mandatory rejection reason...' : 'Enter optional notes...'}
                style={{ width:'100%', padding:'9px 12px', borderRadius:'8px', background: t.input, border:`1px solid ${action === 'reject' && !notes.trim() ? 'rgba(239,68,68,0.4)' : t.border}`, color: t.text, fontSize:'13px', outline:'none', fontFamily:'inherit', resize:'vertical', boxSizing:'border-box' }}/>
            </div>

            {action === 'flag' && (
              <div style={{ marginBottom:'12px' }}>
                <label style={{ fontSize:'11px', color: t.muted4, fontWeight:'600', display:'block', marginBottom:'6px' }}>Assign Analyst (optional)</label>
                <input type="text" value={assignedAnalyst} onChange={e => setAssignedAnalyst(e.target.value)}
                  placeholder="e.g. john.doe" style={{ width:'100%', padding:'9px 12px', borderRadius:'8px', background: t.input, border:`1px solid ${t.border}`, color: t.text, fontSize:'13px', outline:'none', fontFamily:'inherit', boxSizing:'border-box' }}/>
              </div>
            )}

            <div style={{ display:'flex', gap:'10px' }}>
              <button onClick={() => setConfirmOpen(false)} style={{ flex:1, padding:'10px', borderRadius:'10px', border:`1px solid ${t.border}`, background:'transparent', color: t.muted2, fontSize:'13px', fontWeight:'600', cursor:'pointer', fontFamily:'inherit' }}>Cancel</button>
              <button onClick={handleAction} disabled={loading} style={{ flex:1, padding:'10px', borderRadius:'10px', border:`1px solid ${actionConfig[action].border}`, background: actionConfig[action].bg, color: actionConfig[action].color,
                fontSize:'13px', fontWeight:'700', cursor: loading ? 'not-allowed' : 'pointer', fontFamily:'inherit', display:'flex', alignItems:'center', justifyContent:'center', gap:'8px' }}>
                {loading ? <><Spinner size={12} color={actionConfig[action].color}/> Processing...</> : `Confirm ${action.charAt(0).toUpperCase() + action.slice(1)}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ─── Bulk Action Bar ──────────────────────
function BulkActionBar({ selected, transactions, onBulkAction, onExportSelected, onClear }: {
  selected: Set<string>
  transactions: Transaction[]
  onBulkAction: (status: string, notes?: string) => Promise<void>
  onExportSelected: () => void
  onClear: () => void
}) {
  const { t } = useTheme()
  const { toast } = useToast()
  const [bulkAction, setBulkAction] = useState<string | null>(null)
  const [notes, setNotes] = useState('')
  const [loading, setLoading] = useState(false)

  const count = selected.size

  const handleBulk = async () => {
    if (!bulkAction) return
    if (bulkAction === 'REJECTED' && !notes.trim()) {
      toast('Review notes are mandatory for bulk rejection.', 'error')
      return
    }
    setLoading(true)
    try {
      await onBulkAction(bulkAction, notes || undefined)
      setBulkAction(null)
      setNotes('')
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <div style={{ position:'sticky', top:0, zIndex:100, background:'rgba(99,102,241,0.08)', backdropFilter:'blur(8px)', border:'1px solid rgba(99,102,241,0.3)', borderRadius:'12px', padding:'12px 16px', marginBottom:'16px',
        display:'flex', alignItems:'center', gap:'12px', flexWrap:'wrap', animation:'slideDown 0.3s ease' }}>
        <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
          <div style={{ width:'24px', height:'24px', borderRadius:'6px', background:'rgba(99,102,241,0.2)', border:'1px solid rgba(99,102,241,0.4)', display:'flex', alignItems:'center', justifyContent:'center', fontSize:'12px', fontWeight:'800', color:'#a5b4fc' }}>{count}</div>
          <span style={{ fontSize:'13px', fontWeight:'700', color:'#a5b4fc' }}>row{count !== 1 ? 's' : ''} selected</span>
        </div>
        <div style={{ display:'flex', gap:'8px', flexWrap:'wrap', marginLeft:'auto' }}>
          <button onClick={() => setBulkAction('APPROVED')} style={{ padding:'7px 14px', borderRadius:'8px', border:'1px solid rgba(16,185,129,0.4)', background:'rgba(16,185,129,0.1)', color:'#34d399', fontSize:'12px', fontWeight:'700', cursor:'pointer', fontFamily:'inherit' }}>✅ Approve Selected</button>
          <button onClick={() => setBulkAction('REJECTED')} style={{ padding:'7px 14px', borderRadius:'8px', border:'1px solid rgba(239,68,68,0.4)', background:'rgba(239,68,68,0.1)', color:'#f87171', fontSize:'12px', fontWeight:'700', cursor:'pointer', fontFamily:'inherit' }}>❌ Reject Selected</button>
          <button onClick={() => setBulkAction('FLAGGED')} style={{ padding:'7px 14px', borderRadius:'8px', border:'1px solid rgba(245,158,11,0.4)', background:'rgba(245,158,11,0.1)', color:'#fbbf24', fontSize:'12px', fontWeight:'700', cursor:'pointer', fontFamily:'inherit' }}>🚩 Flag Selected</button>
          <button onClick={onExportSelected} style={{ padding:'7px 14px', borderRadius:'8px', border:'1px solid rgba(0,212,255,0.3)', background:'rgba(0,212,255,0.08)', color:'#00d4ff', fontSize:'12px', fontWeight:'700', cursor:'pointer', fontFamily:'inherit' }}>📥 Export Selected</button>
          <button onClick={onClear} style={{ padding:'7px 10px', borderRadius:'8px', border:`1px solid ${t.border}`, background:'transparent', color: t.muted2, fontSize:'12px', cursor:'pointer', fontFamily:'inherit' }}>✕ Clear</button>
        </div>
      </div>

      {/* Bulk Confirm Panel */}
      {bulkAction && (
        <div style={{ background: t.card, border:`1px solid ${bulkAction === 'APPROVED' ? 'rgba(16,185,129,0.3)' : bulkAction === 'REJECTED' ? 'rgba(239,68,68,0.3)' : 'rgba(245,158,11,0.3)'}`, borderRadius:'12px', padding:'16px', marginBottom:'12px', animation:'slideDown 0.2s ease' }}>
          <div style={{ fontSize:'13px', fontWeight:'700', color: t.text, marginBottom:'10px' }}>
            {bulkAction === 'APPROVED' ? '✅' : bulkAction === 'REJECTED' ? '❌' : '🚩'} {bulkAction === 'APPROVED' ? 'Approve' : bulkAction === 'REJECTED' ? 'Reject' : 'Flag'} {count} transactions
          </div>
          <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={2}
            placeholder={bulkAction === 'REJECTED' ? 'Rejection reason (required)...' : 'Notes (optional)...'}
            style={{ width:'100%', padding:'8px 10px', borderRadius:'8px', background: t.input, border:`1px solid ${t.border}`, color: t.text, fontSize:'13px', outline:'none', fontFamily:'inherit', resize:'vertical', boxSizing:'border-box', marginBottom:'10px' }}/>
          <div style={{ display:'flex', gap:'8px' }}>
            <button onClick={() => { setBulkAction(null); setNotes('') }} style={{ padding:'8px 16px', borderRadius:'8px', border:`1px solid ${t.border}`, background:'transparent', color: t.muted2, fontSize:'12px', fontWeight:'600', cursor:'pointer', fontFamily:'inherit' }}>Cancel</button>
            <button onClick={handleBulk} disabled={loading} style={{ padding:'8px 16px', borderRadius:'8px', border:'none', background: bulkAction === 'APPROVED' ? '#10b981' : bulkAction === 'REJECTED' ? '#ef4444' : '#f59e0b', color:'#fff', fontSize:'12px', fontWeight:'700', cursor: loading ? 'not-allowed' : 'pointer', fontFamily:'inherit', display:'flex', alignItems:'center', gap:'6px' }}>
              {loading ? <><Spinner size={11} color="#fff"/> Processing...</> : `Confirm ${bulkAction.charAt(0) + bulkAction.slice(1).toLowerCase()}`}
            </button>
          </div>
        </div>
      )}
    </>
  )
}

// ─── Main Page ────────────────────────────
export default function TransactionsPage() {
  const { t, dark } = useTheme()
  const { toast } = useToast()
  const { user } = useStore()
  const fileRef = useRef<HTMLInputElement>(null)

  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const [search, setSearch] = useState('')
  const [riskFilter, setRiskFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [fraudFilter, setFraudFilter] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const [showExportModal, setShowExportModal] = useState(false)
  const [reviewTx, setReviewTx] = useState<Transaction | null>(null)
  const [exportPreSelected, setExportPreSelected] = useState(false)

  const [csvState, setCsvState] = useState<any>({ status:'idle', total:0, processed:0, failed:0, fraudCount:0, taskId:null })

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
      if (riskFilter) params.risk_level = riskFilter
      if (statusFilter) params.status = statusFilter
      if (fraudFilter !== '') params.is_fraud = fraudFilter === 'true'
      const res = await transactionsAPI.list(params)
      if (reqId !== reqIdRef.current) return
      setTransactions(res.data.transactions)
      setTotal(res.data.total)
    } catch (err: any) {
      if (reqId !== reqIdRef.current) return
      setError(err.response?.status === 403 ? 'forbidden' : 'error')
      toast('Failed to load transactions', 'error')
    } finally {
      if (reqId === reqIdRef.current) {
        setLoading(false)
      }
    }
  }, [riskFilter, statusFilter, fraudFilter, toast])

  useEffect(() => { fetchTransactions(page) }, [fetchTransactions, page])

  const handleUpdate = (updated: Transaction) => {
    setTransactions(prev => prev.map(tx => tx.id === updated.id ? updated : tx))
  }

  const handleBulkAction = async (status: string, notes?: string) => {
    try {
      const ids = Array.from(selected)
      const res = await transactionsAPI.bulkReview(ids, status, notes)
      const updatedMap = new Map<string, Transaction>(res.data.map((t: Transaction) => [t.id, t]))
      setTransactions(prev => prev.map(tx => updatedMap.has(tx.id) ? updatedMap.get(tx.id)! : tx))
      toast(`${ids.length} transactions updated to ${status}`, 'success', 'Bulk Action Complete')
      setSelected(new Set())
    } catch (err: any) {
      toast(err.response?.data?.detail || 'Bulk action failed', 'error', 'Error')
      throw err
    }
  }

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
          const { status: taskStatus, result, error: taskErr } = pollRes.data

          if (taskStatus === 'SUCCESS') {
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
          } else if (taskStatus === 'FAILURE') {
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

  const filtered = search ? transactions.filter(tx =>
    tx.id.toLowerCase().includes(search.toLowerCase()) ||
    String(tx.amount).includes(search) ||
    (tx.risk_level || '').toLowerCase().includes(search.toLowerCase()) ||
    (tx.merchant || '').toLowerCase().includes(search.toLowerCase())
  ) : transactions

  const totalPages = Math.ceil(total / perPage)
  const currentPageIds = transactions.map(tx => tx.id)

  const toggleSelect = (id: string) => {
    setSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  }
  const toggleAll = () => {
    if (filtered.every(tx => selected.has(tx.id))) {
      setSelected(prev => { const n = new Set(prev); filtered.forEach(tx => n.delete(tx.id)); return n })
    } else {
      setSelected(prev => { const n = new Set(prev); filtered.forEach(tx => n.add(tx.id)); return n })
    }
  }
  const allSelected = filtered.length > 0 && filtered.every(tx => selected.has(tx.id))

  const inputStyle = { padding:'10px 12px', borderRadius:'10px', background: t.input, border:`1px solid ${t.border}`, color: t.text, fontSize:'13px', outline:'none', fontFamily:'inherit', cursor:'pointer' }

  if (error) return (
    <div style={{ display:'flex', minHeight:'100vh', background: t.bg, fontFamily:"'Outfit',sans-serif" }}>
      <Sidebar/>
      <main style={{ marginLeft:'220px', flex:1, padding:'28px 32px', display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center' }}>
        <div style={{ fontSize:'48px', marginBottom:'16px' }}>{error === 'forbidden' ? '🔒' : '⚠️'}</div>
        <h2 style={{ fontSize:'20px', fontWeight:'800', color: t.text, marginBottom:'8px' }}>{error === 'forbidden' ? 'Access Denied' : 'Failed to Load Transactions'}</h2>
        <p style={{ color: t.muted4, fontSize:'14px', marginBottom:'20px', textAlign:'center', maxWidth:'360px' }}>{error === 'forbidden' ? 'You do not have permission to view transaction data.' : 'Failed to retrieve transactions. Check your connection.'}</p>
        {error !== 'forbidden' && <button onClick={() => fetchTransactions(page)} style={{ padding:'10px 20px', borderRadius:'10px', border:'none', background:'linear-gradient(135deg,#00d4ff,#6366f1)', color:'#fff', fontSize:'13px', fontWeight:'600', cursor:'pointer', fontFamily:'inherit' }}>Retry</button>}
      </main>
    </div>
  )

  return (
    <div style={{ display:'flex', minHeight:'100vh', background: t.bg, fontFamily:"'Outfit',sans-serif", transition:'background 0.3s' }}>
      <Sidebar/>
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
            <button onClick={() => { setExportPreSelected(false); setShowExportModal(true) }} style={{ padding:'10px 18px', borderRadius:'10px', border:'1px solid rgba(99,102,241,0.3)', background:'rgba(99,102,241,0.08)', color:'#a5b4fc', fontSize:'13px', fontWeight:'600', cursor:'pointer', fontFamily:'inherit' }}>
              📥 Export CSV
            </button>
          </div>
        </div>

        {/* Stats */}
        <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:'12px', marginBottom:'20px' }}>
          {[
            { label:'Total',    value: total, color:'#00d4ff' },
            { label:'Fraud',    value: transactions.filter(tx => tx.is_fraud).length, color:'#ef4444' },
            { label:'Pending',  value: transactions.filter(tx => tx.status?.toUpperCase() === 'PENDING').length, color:'#a5b4fc' },
            { label:'Flagged',  value: transactions.filter(tx => tx.status?.toUpperCase() === 'FLAGGED').length, color:'#f59e0b' },
          ].map(s => (
            <div key={s.label} style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'12px', padding:'14px 18px', transition:'background 0.3s' }}>
              <div style={{ fontSize:'11px', color: t.muted4, fontWeight:'600', textTransform:'uppercase', letterSpacing:'0.8px', marginBottom:'6px' }}>{s.label}</div>
              <div style={{ fontSize:'24px', fontWeight:'800', color: s.color, fontFamily:"'DM Mono',monospace" }}>{s.value}</div>
            </div>
          ))}
        </div>

        {/* Filters */}
        <div style={{ display:'flex', gap:'10px', marginBottom:'16px', flexWrap:'wrap' }}>
          <div style={{ position:'relative', flex:1, minWidth:'200px' }}>
            <span style={{ position:'absolute', left:'12px', top:'50%', transform:'translateY(-50%)', fontSize:'14px', opacity:0.4 }}>🔍</span>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search ID, amount, merchant..."
              style={{ ...inputStyle, width:'100%', paddingLeft:'36px', boxSizing:'border-box' as any }}/>
          </div>
          <select value={riskFilter} onChange={e => { setRiskFilter(e.target.value); setPage(1); }} style={inputStyle}>
            <option value="">All Risk Levels</option>
            <option value="HIGH">🔴 HIGH</option>
            <option value="MEDIUM">🟡 MEDIUM</option>
            <option value="LOW">🟢 LOW</option>
          </select>
          <select value={statusFilter} onChange={e => { setStatusFilter(e.target.value); setPage(1); }} style={inputStyle}>
            <option value="">All Statuses</option>
            <option value="PENDING">PENDING</option>
            <option value="FLAGGED">FLAGGED</option>
            <option value="APPROVED">APPROVED</option>
            <option value="REJECTED">REJECTED</option>
          </select>
          <select value={fraudFilter} onChange={e => { setFraudFilter(e.target.value); setPage(1); }} style={inputStyle}>
            <option value="">All Types</option>
            <option value="true">🚨 Fraud Only</option>
            <option value="false">✅ Legit Only</option>
          </select>
          {(riskFilter || statusFilter || fraudFilter || search) && (
            <button onClick={() => { setRiskFilter(''); setStatusFilter(''); setFraudFilter(''); setSearch(''); setPage(1); }}
              style={{ padding:'10px 14px', borderRadius:'10px', border:`1px solid ${t.border}`, background:'transparent', color: t.muted2, fontSize:'13px', cursor:'pointer', fontFamily:'inherit' }}>✕ Clear</button>
          )}
        </div>

        {/* Bulk Action Bar */}
        {selected.size > 0 && (
          <BulkActionBar
            selected={selected}
            transactions={transactions}
            onBulkAction={handleBulkAction}
            onExportSelected={() => { setExportPreSelected(true); setShowExportModal(true) }}
            onClear={() => setSelected(new Set())}
          />
        )}

        {/* Table */}
        <div style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'16px', overflow:'hidden', transition:'background 0.3s' }}>
          {/* Table Header */}
          <div style={{ display:'grid', gridTemplateColumns:'44px 1fr 110px 86px 106px 110px 100px 120px', padding:'10px 16px', borderBottom:`1px solid ${t.border}`, background: dark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)', alignItems:'center' }}>
            {/* Select All */}
            <div onClick={toggleAll} style={{ cursor:'pointer' }}>
              <div style={{ width:'16px', height:'16px', borderRadius:'4px', border:`1px solid ${allSelected ? '#00d4ff' : t.border}`, background: allSelected ? '#00d4ff' : 'transparent', display:'flex', alignItems:'center', justifyContent:'center' }}>
                {allSelected && <span style={{ color:'#000', fontSize:'10px' }}>✓</span>}
              </div>
            </div>
            {['Transaction ID','Amount','Risk','Fraud %','Status','Time','Action'].map(h => (
              <div key={h} style={{ fontSize:'11px', fontWeight:'700', color: t.muted4, textTransform:'uppercase', letterSpacing:'0.8px' }}>{h}</div>
            ))}
          </div>

          {loading ? (
            <div style={{ padding:'16px', display:'flex', flexDirection:'column', gap:'10px' }}>
              {[...Array(8)].map((_, i) => <div key={i} style={{ height:'48px', borderRadius:'6px', background: t.card2, animation:'shimmer 1.5s infinite' }}/>)}
            </div>
          ) : filtered.length === 0 ? (
            <div style={{ textAlign:'center', padding:'60px 0', color: t.muted4 }}>
              <div style={{ fontSize:'40px', marginBottom:'12px' }}>🔍</div>
              <div style={{ fontSize:'14px' }}>No transactions found</div>
              <div style={{ fontSize:'12px', marginTop:'4px', color: t.muted4 }}>Try adjusting your filters</div>
            </div>
          ) : filtered.map((tx) => (
            <div key={tx.id} style={{ display:'grid', gridTemplateColumns:'44px 1fr 110px 86px 106px 110px 100px 120px', padding:'12px 16px', borderBottom:`1px solid ${t.card2}`, alignItems:'center', transition:'background 0.15s', background: selected.has(tx.id) ? 'rgba(0,212,255,0.02)' : 'transparent' }}
              onMouseEnter={e => { if (!selected.has(tx.id)) (e.currentTarget as HTMLElement).style.background = dark ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)' }}
              onMouseLeave={e => { if (!selected.has(tx.id)) (e.currentTarget as HTMLElement).style.background = 'transparent' }}>

              {/* Checkbox */}
              <div onClick={() => toggleSelect(tx.id)} style={{ cursor:'pointer' }}>
                <div style={{ width:'16px', height:'16px', borderRadius:'4px', border:`1px solid ${selected.has(tx.id) ? '#00d4ff' : t.border}`, background: selected.has(tx.id) ? '#00d4ff' : 'transparent', display:'flex', alignItems:'center', justifyContent:'center', transition:'all 0.15s' }}>
                  {selected.has(tx.id) && <span style={{ color:'#000', fontSize:'10px' }}>✓</span>}
                </div>
              </div>

              {/* ID */}
              <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
                <div style={{ width:'6px', height:'6px', borderRadius:'50%', background: tx.is_fraud ? '#ef4444' : '#10b981', boxShadow: tx.is_fraud ? '0 0 6px #ef4444' : '0 0 6px #10b981', flexShrink:0 }}/>
                <div>
                  <div style={{ fontSize:'12px', color: t.muted2, fontFamily:"'DM Mono',monospace" }}>{tx.id.slice(0,12)}...</div>
                  {tx.merchant && <div style={{ fontSize:'11px', color: t.muted4 }}>{tx.merchant}</div>}
                </div>
              </div>

              {/* Amount */}
              <div style={{ fontSize:'13px', fontWeight:'600', color: t.text2 }}>₹{parseFloat(String(tx.amount)).toLocaleString('en-IN', { maximumFractionDigits:0 })}</div>

              {/* Risk */}
              <div>{tx.risk_level ? <Badge val={tx.risk_level} map={RISK_STYLES}/> : <span style={{ color: t.muted4, fontSize:'12px' }}>—</span>}</div>

              {/* Fraud % */}
              <div style={{ fontFamily:"'DM Mono',monospace", fontSize:'13px', fontWeight:'700', color: (tx.fraud_score || 0) > 0.7 ? '#ef4444' : (tx.fraud_score || 0) > 0.4 ? '#fbbf24' : '#34d399' }}>
                {tx.fraud_score !== undefined && tx.fraud_score !== null ? `${(tx.fraud_score * 100).toFixed(1)}%` : '—'}
              </div>

              {/* Status */}
              <div><Badge val={tx.status} map={STATUS_STYLES}/></div>

              {/* Time */}
              <div style={{ fontSize:'11px', color: t.muted4 }}>{new Date(tx.created_at).toLocaleTimeString('en-IN', { hour:'2-digit', minute:'2-digit' })}</div>

              {/* Action */}
              <div>
                <button onClick={() => setReviewTx(tx)}
                  style={{ padding:'5px 12px', borderRadius:'7px', border:`1px solid rgba(0,212,255,0.3)`, background:'rgba(0,212,255,0.07)', color:'#00d4ff', fontSize:'11px', fontWeight:'700', cursor:'pointer', fontFamily:'inherit', transition:'all 0.15s' }}
                  onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(0,212,255,0.14)' }}
                  onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(0,212,255,0.07)' }}>
                  Review →
                </button>
              </div>
            </div>
          ))}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginTop:'16px', padding:'0 4px' }}>
            <div style={{ fontSize:'13px', color: t.muted4 }}>Showing {((page-1)*perPage)+1}–{Math.min(page*perPage,total)} of {total.toLocaleString()}</div>
            <div style={{ display:'flex', gap:'6px' }}>
              <button onClick={() => setPage(p => Math.max(1, p-1))} disabled={page===1} style={{ padding:'8px 14px', borderRadius:'8px', border:`1px solid ${t.border}`, background:'transparent', color: page===1 ? t.muted4 : t.muted, cursor: page===1 ? 'not-allowed' : 'pointer', fontSize:'13px', fontFamily:'inherit' }}>← Prev</button>
              {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                const p = Math.max(1, Math.min(page-2, totalPages-4)) + i
                return (
                  <button key={p} onClick={() => setPage(p)} style={{ padding:'8px 12px', borderRadius:'8px', border: p===page ? '1px solid rgba(0,212,255,0.4)' : `1px solid ${t.border}`, background: p===page ? 'rgba(0,212,255,0.1)' : 'transparent', color: p===page ? '#00d4ff' : t.muted2, cursor:'pointer', fontSize:'13px', fontFamily:'inherit', fontWeight: p===page ? '700' : '400' }}>{p}</button>
                )
              })}
              <button onClick={() => setPage(p => Math.min(totalPages, p+1))} disabled={page===totalPages} style={{ padding:'8px 14px', borderRadius:'8px', border:`1px solid ${t.border}`, background:'transparent', color: page===totalPages ? t.muted4 : t.muted, cursor: page===totalPages ? 'not-allowed' : 'pointer', fontSize:'13px', fontFamily:'inherit' }}>Next →</button>
            </div>
          </div>
        )}
      </main>

      {/* CSV Upload Progress */}
      {csvState.status !== 'idle' && (
        <div style={{ position:'fixed', bottom:'24px', left:'240px', zIndex:9998, background: t.card || '#0d1117',
          border:`1px solid ${csvState.status==='error' ? '#ef4444' : csvState.status==='success' ? '#10b981' : '#00d4ff'}`,
          borderRadius:'16px', padding:'16px 20px', width:'320px', boxShadow:'0 8px 32px rgba(0,0,0,0.6)', fontFamily:'inherit', animation:'slideUp 0.3s ease' }}>
          <div style={{ display:'flex', alignItems:'center', gap:'8px', marginBottom:'12px' }}>
            <span style={{ fontSize:'18px' }}>{csvState.status==='uploading' ? '📤' : csvState.status==='processing' ? '⏳' : csvState.status==='success' ? '✅' : '❌'}</span>
            <span style={{ fontSize:'13px', fontWeight:'800', color: csvState.status==='error' ? '#f87171' : csvState.status==='success' ? '#34d399' : '#00d4ff', letterSpacing:'0.5px' }}>
              {csvState.status==='uploading' && 'UPLOADING CSV...'}{csvState.status==='processing' && 'PROCESSING BATCH...'}{csvState.status==='success' && 'BATCH COMPLETE'}{csvState.status==='error' && 'BATCH FAILED'}
            </span>
            {csvState.status !== 'success' && csvState.status !== 'error' && <span style={{ marginLeft:'auto' }}><Spinner/></span>}
          </div>
          <div style={{ display:'flex', flexDirection:'column', gap:'6px', fontSize:'12px', color: t.text2 || '#e2e8f0' }}>
            {[['Total', csvState.total, '#fff'],['Processed', csvState.processed, '#10b981'],['Failed', csvState.failed, '#ef4444'],['Fraud Found', csvState.fraudCount, '#f59e0b']].map(([l, v, c]) => (
              <div key={String(l)} style={{ display:'flex', justifyContent:'space-between' }}>
                <span>{l}:</span><span style={{ fontFamily:"'DM Mono',monospace", fontWeight:'700', color: String(c) }}>{String(v)}</span>
              </div>
            ))}
            {csvState.total > 0 && (
              <div style={{ width:'100%', height:'4px', background: t.border || '#1a2035', borderRadius:'2px', marginTop:'4px', overflow:'hidden' }}>
                <div style={{ width:`${Math.min(100, Math.round(((csvState.processed + csvState.failed) / csvState.total) * 100))}%`, height:'100%', background:'linear-gradient(90deg, #00d4ff, #6366f1)', transition:'width 0.3s ease' }}/>
              </div>
            )}
          </div>
          {csvState.status === 'success' && (
            <button onClick={() => setCsvState({ status:'idle', total:0, processed:0, failed:0, fraudCount:0, taskId:null })} style={{ marginTop:'12px', width:'100%', padding:'6px', borderRadius:'8px', border:`1px solid ${t.border}`, background: t.card, color: t.text, fontSize:'11px', cursor:'pointer', fontFamily:'inherit' }}>Dismiss</button>
          )}
        </div>
      )}

      {/* Modals */}
      {showExportModal && (
        <ExportModal
          onClose={() => setShowExportModal(false)}
          selected={selected}
          currentPageIds={currentPageIds}
          filters={{ riskFilter, statusFilter, fraudFilter }}
          total={total}
        />
      )}
      {reviewTx && (
        <ReviewDrawer
          tx={reviewTx}
          onClose={() => setReviewTx(null)}
          onUpdate={handleUpdate}
          currentUser={user}
        />
      )}

      <style>{`
        @keyframes shimmer { 0%{opacity:0.5} 50%{opacity:1} 100%{opacity:0.5} }
        @keyframes spin { to{ transform:rotate(360deg) } }
        @keyframes slideUp { from{opacity:0;transform:translateY(8px)} to{opacity:1;transform:translateY(0)} }
        @keyframes slideDown { from{opacity:0;transform:translateY(-8px)} to{opacity:1;transform:translateY(0)} }
        @keyframes modalIn { from{opacity:0;transform:scale(0.94) translateY(16px)} to{opacity:1;transform:scale(1) translateY(0)} }
        @keyframes drawerIn { from{opacity:0;transform:translateX(100%)} to{opacity:1;transform:translateX(0)} }
        ::-webkit-scrollbar { width:5px; height:5px; }
        ::-webkit-scrollbar-track { background:transparent; }
        ::-webkit-scrollbar-thumb { background:rgba(255,255,255,0.08); border-radius:3px; }
      `}</style>
    </div>
  )
}
