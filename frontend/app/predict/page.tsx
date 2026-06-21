'use client'
import { useState } from 'react'
import Sidebar from '@/app/components/Sidebar'
import { useTheme } from '@/app/components/ThemeContext'
import { useToast } from '@/app/components/Toast'
import { predictAPI } from '@/lib/api'

const PRESETS: any = {
  'Normal Transaction':    { V1:-0.43,V2:1.22,V3:1.01,V4:0.63,V5:-0.62,V6:-1.42,V7:-0.58,V8:0.04,V9:-0.35,V10:-0.16,V11:-0.54,V12:-0.47,V13:-0.63,V14:-0.22,V15:0.78,V16:-0.63,V17:0.14,V18:-0.24,V19:0.49,V20:0.25,V21:-0.02,V22:0.28,V23:-0.11,V24:0.07,V25:0.13,V26:-0.19,V27:0.13,V28:-0.02,Amount:9.99,Time:50000 },
  'Suspicious Transaction':{ V1:-3.04,V2:-3.16,V3:1.09,V4:2.29,V5:0.49,V6:-1.42,V7:-2.83,V8:-0.17,V9:-2.43,V10:-2.73,V11:-0.73,V12:-0.47,V13:-0.63,V14:-2.22,V15:0.78,V16:1.63,V17:-1.14,V18:-0.24,V19:0.49,V20:0.25,V21:-0.02,V22:0.28,V23:-0.11,V24:0.07,V25:0.13,V26:-0.19,V27:0.13,V28:-0.02,Amount:2125.87,Time:406 },
  'High Value Legit':      { V1:1.19,V2:0.26,V3:0.16,V4:0.45,V5:-0.07,V6:-0.18,V7:0.09,V8:0.08,V9:-0.26,V10:-0.17,V11:0.03,V12:0.14,V13:-0.07,V14:0.10,V15:0.05,V16:-0.02,V17:-0.06,V18:0.08,V19:-0.12,V20:0.10,V21:-0.01,V22:0.05,V23:-0.02,V24:0.01,V25:0.02,V26:-0.04,V27:0.01,V28:-0.01,Amount:8500.00,Time:75000 },
}

const defaultFeatures = () => { const f: any = {}; for(let i=1;i<=28;i++) f[`V${i}`]=0; f.Amount=100; f.Time=50000; return f }

export default function PredictPage() {
  const { t, dark } = useTheme()
  const { toast } = useToast()
  const [features,  setFeatures]  = useState<any>(defaultFeatures())
  const [loading,   setLoading]   = useState(false)
  const [result,    setResult]    = useState<any>(null)
  const [animating, setAnimating] = useState(false)

  const setPreset = (name: string) => { setFeatures({...PRESETS[name]}); setResult(null); toast(`Loaded: ${name}`, 'info') }

  const handlePredict = async () => {
    setLoading(true); setResult(null)
    try {
      const res = await predictAPI.single(features)
      const data = res.data
      setAnimating(true)
      setTimeout(() => { setResult(data); setAnimating(false); toast(data.is_fraud ? '🚨 Fraud Detected!' : '✅ Legitimate', data.is_fraud ? 'error' : 'success') }, 600)
    } catch { toast('Prediction failed', 'error') }
    finally { setLoading(false) }
  }

  const maxShap = result ? Math.max(...result.top_features.map((f: any) => Math.abs(f.shap_value))) : 1
  const inputStyle = { width:'100%', padding:'8px 10px', borderRadius:'8px', background: t.input, border:`1px solid ${t.border}`, color: t.text, fontSize:'13px', outline:'none', boxSizing:'border-box' as any, fontFamily:"'DM Mono',monospace", transition:'background 0.3s' }

  return (
    <div style={{ display:'flex', minHeight:'100vh', background: t.bg, fontFamily:"'Outfit',sans-serif", transition:'background 0.3s' }}>
      <Sidebar />
      <main style={{ marginLeft:'220px', flex:1, padding:'28px 32px' }}>
        <div style={{ marginBottom:'24px' }}>
          <h1 style={{ fontSize:'24px', fontWeight:'800', color: t.text, margin:'0 0 4px', letterSpacing:'-0.5px' }}>
            🧠 Fraud <span style={{ background:'linear-gradient(135deg,#00d4ff,#6366f1)', WebkitBackgroundClip:'text', WebkitTextFillColor:'transparent' }}>Predictor</span>
          </h1>
          <p style={{ color: t.muted4, fontSize:'13px', margin:0 }}>XGBoost + SHAP powered explainable fraud detection</p>
        </div>

        {/* Presets */}
        <div style={{ display:'flex', gap:'8px', marginBottom:'20px', flexWrap:'wrap' }}>
          <span style={{ fontSize:'12px', color: t.muted4, alignSelf:'center' }}>Quick load:</span>
          {Object.keys(PRESETS).map(name => (
            <button key={name} onClick={() => setPreset(name)} style={{ padding:'7px 14px', borderRadius:'8px', border:`1px solid ${t.border}`, background: t.card, color: t.muted, fontSize:'12px', cursor:'pointer', fontFamily:'inherit', transition:'all 0.2s' }}
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor='rgba(0,212,255,0.4)'; (e.currentTarget as HTMLElement).style.color='#00d4ff' }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor=t.border; (e.currentTarget as HTMLElement).style.color=t.muted }}>{name}</button>
          ))}
          <button onClick={() => { setFeatures(defaultFeatures()); setResult(null) }} style={{ padding:'7px 14px', borderRadius:'8px', border:`1px solid ${t.border}`, background:'transparent', color: t.muted4, fontSize:'12px', cursor:'pointer', fontFamily:'inherit' }}>✕ Reset</button>
        </div>

        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'20px' }}>
          {/* Input Panel */}
          <div style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'16px', padding:'20px', transition:'background 0.3s' }}>
            <div style={{ fontSize:'14px', fontWeight:'700', color: t.text, marginBottom:'16px' }}>📥 Transaction Features</div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'10px', marginBottom:'16px' }}>
              {['Amount','Time'].map(key => (
                <div key={key}>
                  <label style={{ fontSize:'11px', color: t.muted4, fontWeight:'700', textTransform:'uppercase', letterSpacing:'0.6px', display:'block', marginBottom:'4px' }}>{key}</label>
                  <input type="number" value={features[key]} onChange={e => setFeatures({...features,[key]:parseFloat(e.target.value)||0})} style={inputStyle}/>
                </div>
              ))}
            </div>
            <div style={{ display:'grid', gridTemplateColumns:'repeat(4,1fr)', gap:'8px', marginBottom:'20px' }}>
              {Array.from({length:28},(_,i) => `V${i+1}`).map(key => (
                <div key={key}>
                  <label style={{ fontSize:'10px', color: t.muted4, fontWeight:'700', display:'block', marginBottom:'3px' }}>{key}</label>
                  <input type="number" step="0.01" value={features[key]} onChange={e => setFeatures({...features,[key]:parseFloat(e.target.value)||0})} style={{...inputStyle, fontSize:'11px', padding:'6px 8px'}}/>
                </div>
              ))}
            </div>
            <button onClick={handlePredict} disabled={loading} style={{ width:'100%', padding:'13px', borderRadius:'12px', border:'none', background: loading ? t.card2 : 'linear-gradient(135deg,#00d4ff,#6366f1)', color: loading ? t.muted4 : '#fff', fontSize:'14px', fontWeight:'700', cursor: loading ? 'not-allowed' : 'pointer', fontFamily:'inherit', transition:'all 0.3s' }}>
              {loading ? '⏳ Analyzing...' : '⚡ Run Prediction'}
            </button>
          </div>

          {/* Result Panel */}
          <div style={{ display:'flex', flexDirection:'column', gap:'16px' }}>
            {!result && !animating && (
              <div style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'16px', padding:'40px 20px', textAlign:'center', color: t.muted4, flex:1, display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', transition:'background 0.3s' }}>
                <div style={{ fontSize:'48px', marginBottom:'16px', opacity:0.4 }}>🔮</div>
                <div>Enter features and click</div>
                <div style={{ color:'#00d4ff', fontWeight:'600' }}>⚡ Run Prediction</div>
              </div>
            )}
            {animating && (
              <div style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'16px', padding:'40px 20px', textAlign:'center', flex:1, display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center' }}>
                <div style={{ width:'48px', height:'48px', border:`3px solid ${t.border}`, borderTopColor:'#00d4ff', borderRadius:'50%', margin:'0 auto 16px', animation:'spin 0.8s linear infinite' }}/>
                <div style={{ color:'#00d4ff', fontWeight:'600' }}>Running XGBoost + SHAP...</div>
              </div>
            )}
            {result && !animating && (
              <>
                <div style={{ background: t.card, border:`1px solid ${result.is_fraud ? 'rgba(239,68,68,0.3)' : 'rgba(16,185,129,0.3)'}`, borderRadius:'16px', padding:'20px', position:'relative', overflow:'hidden' }}>
                  <div style={{ position:'absolute', top:0, left:0, right:0, height:'2px', background: result.is_fraud ? 'linear-gradient(90deg,#ef4444,transparent)' : 'linear-gradient(90deg,#10b981,transparent)' }}/>
                  <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start' }}>
                    <div>
                      <div style={{ fontSize:'36px', marginBottom:'4px' }}>{result.is_fraud ? '🚨' : '✅'}</div>
                      <div style={{ fontSize:'20px', fontWeight:'800', color: result.risk_color }}>{result.is_fraud ? 'FRAUD DETECTED' : 'LEGITIMATE'}</div>
                    </div>
                    <div style={{ textAlign:'right' }}>
                      <div style={{ fontSize:'42px', fontWeight:'900', color: result.risk_color, fontFamily:"'DM Mono',monospace", lineHeight:1 }}>{result.fraud_percentage.toFixed(1)}%</div>
                      <div style={{ fontSize:'11px', color: t.muted4, marginTop:'4px' }}>Fraud Score</div>
                      <span style={{ display:'inline-block', marginTop:'8px', padding:'4px 12px', borderRadius:'999px', fontSize:'11px', fontWeight:'700', background:`${result.risk_color}20`, color: result.risk_color, border:`1px solid ${result.risk_color}40` }}>{result.risk_level} RISK</span>
                    </div>
                  </div>
                  <div style={{ marginTop:'16px' }}>
                    <div style={{ height:'6px', background: t.card2, borderRadius:'999px', overflow:'hidden' }}>
                      <div style={{ height:'100%', width:`${result.fraud_percentage}%`, background: result.is_fraud ? 'linear-gradient(90deg,#f59e0b,#ef4444)' : 'linear-gradient(90deg,#10b981,#00d4ff)', borderRadius:'999px', transition:'width 1s ease' }}/>
                    </div>
                  </div>
                  <div style={{ marginTop:'12px', padding:'10px 14px', borderRadius:'8px', background: t.card2, border:`1px solid ${t.border}`, fontSize:'12px', color: t.muted, lineHeight:1.6 }}>{result.explanation}</div>
                </div>

                {/* SHAP */}
                <div style={{ background: t.card, border:`1px solid ${t.border}`, borderRadius:'16px', padding:'20px', transition:'background 0.3s' }}>
                  <div style={{ fontSize:'14px', fontWeight:'700', color: t.text, marginBottom:'4px' }}>🔍 SHAP Feature Explanation</div>
                  <div style={{ fontSize:'11px', color: t.muted4, marginBottom:'16px' }}>Why did the model make this decision?</div>
                  <div style={{ display:'flex', flexDirection:'column', gap:'8px' }}>
                    {result.top_features.map((f: any, i: number) => {
                      const pct = (Math.abs(f.shap_value)/maxShap)*100
                      const positive = f.shap_value > 0
                      return (
                        <div key={f.feature}>
                          <div style={{ display:'flex', justifyContent:'space-between', marginBottom:'4px' }}>
                            <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
                              <span style={{ fontSize:'11px', color: t.muted4, fontFamily:"'DM Mono',monospace" }}>#{i+1}</span>
                              <span style={{ fontSize:'12px', fontWeight:'600', color: t.text2, fontFamily:"'DM Mono',monospace" }}>{f.feature}</span>
                              <span style={{ fontSize:'10px', padding:'1px 6px', borderRadius:'4px', background: positive ? 'rgba(239,68,68,0.1)' : 'rgba(16,185,129,0.1)', color: positive ? '#f87171' : '#34d399' }}>{positive ? '↑ risk' : '↓ risk'}</span>
                            </div>
                            <span style={{ fontSize:'12px', fontWeight:'700', color: positive ? '#f87171' : '#34d399', fontFamily:"'DM Mono',monospace" }}>{f.shap_value > 0 ? '+' : ''}{f.shap_value.toFixed(4)}</span>
                          </div>
                          <div style={{ height:'6px', background: t.card2, borderRadius:'999px', overflow:'hidden' }}>
                            <div style={{ height:'100%', width:`${pct}%`, background: positive ? 'linear-gradient(90deg,#f59e0b,#ef4444)' : 'linear-gradient(90deg,#10b981,#00d4ff)', borderRadius:'999px', transition:`width 0.8s ease ${i*0.05}s` }}/>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                  <div style={{ display:'flex', gap:'16px', marginTop:'16px', paddingTop:'12px', borderTop:`1px solid ${t.border}` }}>
                    <div style={{ display:'flex', alignItems:'center', gap:'6px' }}>
                      <div style={{ width:'24px', height:'4px', borderRadius:'999px', background:'linear-gradient(90deg,#f59e0b,#ef4444)' }}/>
                      <span style={{ fontSize:'11px', color: t.muted4 }}>Increases fraud risk</span>
                    </div>
                    <div style={{ display:'flex', alignItems:'center', gap:'6px' }}>
                      <div style={{ width:'24px', height:'4px', borderRadius:'999px', background:'linear-gradient(90deg,#10b981,#00d4ff)' }}/>
                      <span style={{ fontSize:'11px', color: t.muted4 }}>Decreases fraud risk</span>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </main>
      <style>{`@keyframes spin{to{transform:rotate(360deg)}}`}</style>
    </div>
  )
}
