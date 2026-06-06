import { useState } from "react"

const BROKERS = {
  upstox: {
    name: "Upstox", logo: "🟣",
    dashboard: "https://account.upstox.com/developer/apps",
    redirect: "https://mtutrade.in/api/auth/broker/upstox/callback",
    fields: [
      { key:"user_id",    label:"Broker Login ID",  hint:"Your Upstox User ID (e.g. BB3296)" },
      { key:"api_key",    label:"API Key",           hint:"From Upstox developer app" },
      { key:"api_secret", label:"API Secret",        hint:"From Upstox developer app", secret:true },
    ],
    help:"Create App → paste Redirect URL below → copy API Key & Secret",
  },
  dhan: {
    name: "Dhan", logo: "🟢",
    dashboard: "https://dhanhq.co/developers/",
    redirect: "https://mtutrade.in/api/auth/broker/dhan/callback",
    fields: [
      { key:"user_id", label:"Client ID",     hint:"Your Dhan Client ID" },
      { key:"api_key", label:"Access Token",  hint:"From Dhan developer portal", secret:true },
    ],
    help:"Generate access token from Dhan developer portal",
  },
  fyers: {
    name: "Fyers", logo: "🔵",
    dashboard: "https://myapi.fyers.in/",
    redirect: "https://mtutrade.in/api/auth/broker/fyers/callback",
    fields: [
      { key:"user_id",    label:"Fyers ID",   hint:"Your Fyers ID (e.g. XA12345)" },
      { key:"api_key",    label:"App ID",     hint:"From Fyers API dashboard" },
      { key:"api_secret", label:"Secret ID",  hint:"From Fyers API dashboard", secret:true },
    ],
    help:"Create App → paste Redirect URL → copy App ID & Secret",
  },
  zerodha: {
    name: "Zerodha", logo: "🔴",
    dashboard: "https://developers.kite.trade/",
    redirect: "https://mtutrade.in/api/auth/broker/zerodha/callback",
    fields: [
      { key:"user_id",    label:"Zerodha ID", hint:"Your Zerodha ID (e.g. ZX1234)" },
      { key:"api_key",    label:"API Key",    hint:"From Kite Connect app" },
      { key:"api_secret", label:"API Secret", hint:"From Kite Connect app", secret:true },
    ],
    help:"Create App → whitelist IP 34.60.239.253 → paste Redirect URL → copy keys",
    note:"Whitelist IP: 34.60.239.253 in your Kite app settings",
  },
}

const API = "https://mtutrade.in/api"

export default function BrokerConnect({ T, user, onConnected }) {
  const [broker,  setBroker]  = useState(null)
  const [fields,  setFields]  = useState({})
  const [show,    setShow]    = useState({})
  const [copied,  setCopied]  = useState(false)
  const [saving,  setSaving]  = useState(false)
  const [error,   setError]   = useState("")

  const inter = "'Inter',system-ui,sans-serif"
  const mono  = "'JetBrains Mono','Fira Mono',monospace"

  function copy(text) {
    navigator.clipboard.writeText(text)
    setCopied(true); setTimeout(()=>setCopied(false),2000)
  }

  async function connect() {
    const info = BROKERS[broker]
    for(const f of info.fields) {
      if(!fields[f.key]?.trim()) { setError(`Please enter ${f.label}`); return }
    }
    setError(""); setSaving(true)
    const token = localStorage.getItem("mtu_token")
    try {
      const r = await fetch(`${API}/auth/broker/save-creds`, {
        method:"POST",
        headers:{"Content-Type":"application/json","Authorization":`Bearer ${token}`},
        credentials:"include",
        body: JSON.stringify({broker, ...fields})
      })
      const d = await r.json()
      if(d.status==="ok") {
        window.location.href = `${API}/auth/broker/connect/${broker}`
      } else {
        setError(d.detail||"Failed to save")
      }
    } catch(e) { setError("Connection error") }
    setSaving(false)
  }

  const inp = {
    width:"100%", height:38, border:`1px solid ${T.line}`,
    borderRadius:6, padding:"0 10px",
    fontFamily:mono, fontSize:12, fontWeight:600,
    color:T.ink, background:T.surface,
    outline:"none", boxSizing:"border-box",
  }

  const tag = t => <div style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:4}}>{t}</div>

  // ── Broker selector ────────────────────────────────────────────────────────
  if(!broker) return (
    <div>
      <div style={{fontFamily:mono,fontSize:8,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:10}}>Select Broker to Connect</div>
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,marginBottom:12}}>
        {Object.entries(BROKERS).map(([key,info])=>(
          <button key={key} onPointerDown={()=>{ setBroker(key); setFields({}); setError("") }}
            style={{padding:"12px 8px",borderRadius:8,border:`1px solid ${T.line}`,background:T.raised,
              fontFamily:inter,fontWeight:600,fontSize:13,color:T.ink,cursor:"pointer",
              textAlign:"left",WebkitTapHighlightColor:"transparent",touchAction:"manipulation",
              display:"flex",alignItems:"center",gap:8}}>
            <span style={{fontSize:20}}>{info.logo}</span>
            <span>{info.name}</span>
          </button>
        ))}
      </div>
      <div style={{background:T.raised,borderRadius:8,padding:"10px 12px",border:`1px solid ${T.line}`}}>
        <div style={{fontFamily:mono,fontSize:9,color:T.subtle,lineHeight:1.6}}>
          Each broker requires a free developer API app. VAJRA will guide you step by step.
        </div>
      </div>
    </div>
  )

  // ── Setup flow ─────────────────────────────────────────────────────────────
  const info = BROKERS[broker]
  return (
    <div>
      {/* Back + broker name */}
      <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:14}}>
        <button onPointerDown={()=>setBroker(null)}
          style={{background:"none",border:"none",cursor:"pointer",color:T.subtle,fontFamily:inter,fontSize:12,fontWeight:600,padding:0,WebkitTapHighlightColor:"transparent"}}>
          ← Back
        </button>
        <span style={{fontSize:18}}>{info.logo}</span>
        <span style={{fontFamily:inter,fontWeight:700,fontSize:14,color:T.ink}}>{info.name}</span>
      </div>

      {/* Warning */}
      <div style={{background:"#FFF5F5",border:`1px solid #FFCDD2`,borderRadius:8,padding:"8px 12px",marginBottom:12,textAlign:"center"}}>
        <div style={{fontFamily:inter,fontSize:11,fontWeight:600,color:"#C62828"}}>
          ⚠️ DO NOT enter your broker account password here
        </div>
      </div>

      {/* Step 1 — Open dashboard */}
      <div style={{background:T.raised,borderRadius:8,padding:"12px",border:`1px solid ${T.line}`,marginBottom:10}}>
        {tag("Step 1 — Create API App on broker portal")}
        <a href={info.dashboard} target="_blank" rel="noreferrer"
          style={{display:"block",textAlign:"center",padding:"10px",borderRadius:6,background:T.brand,color:"#fff",fontFamily:inter,fontWeight:700,fontSize:13,textDecoration:"none",marginBottom:8}}>
          Open {info.name} Developer Portal ↗
        </a>
        <div style={{fontFamily:mono,fontSize:9,color:T.subtle,lineHeight:1.6}}>{info.help}</div>
        {info.note&&<div style={{fontFamily:mono,fontSize:9,color:"#E65100",marginTop:6,fontWeight:600}}>📌 {info.note}</div>}
      </div>

      {/* Step 2 — Redirect URL */}
      <div style={{background:T.raised,borderRadius:8,padding:"12px",border:`1px solid ${T.line}`,marginBottom:10}}>
        {tag("Step 2 — Set this as Redirect URL in broker app")}
        <div style={{display:"flex",gap:6,alignItems:"stretch"}}>
          <div style={{flex:1,background:T.surface,border:`1px solid ${T.line}`,borderRadius:6,padding:"8px 10px",fontFamily:mono,fontSize:9,color:T.ink,wordBreak:"break-all",lineHeight:1.5}}>
            {info.redirect}
          </div>
          <button onPointerDown={()=>copy(info.redirect)}
            style={{flexShrink:0,padding:"0 12px",borderRadius:6,border:"none",background:copied?"#2E7D32":T.brand,color:"#fff",fontFamily:inter,fontWeight:700,fontSize:12,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
            {copied?"✓":"Copy"}
          </button>
        </div>
      </div>

      {/* Step 3 — Enter credentials */}
      <div style={{background:T.raised,borderRadius:8,padding:"12px",border:`1px solid ${T.line}`,marginBottom:12}}>
        {tag("Step 3 — Enter your API credentials below")}
        {info.fields.map(f=>(
          <div key={f.key} style={{marginBottom:10}}>
            {tag(f.label)}
            <div style={{position:"relative"}}>
              <input
                type={f.secret&&!show[f.key]?"password":"text"}
                value={fields[f.key]||""}
                onChange={e=>setFields(p=>({...p,[f.key]:e.target.value}))}
                placeholder={f.hint}
                style={inp}
              />
              {f.secret&&(
                <button onPointerDown={()=>setShow(p=>({...p,[f.key]:!p[f.key]}))}
                  style={{position:"absolute",right:8,top:"50%",transform:"translateY(-50%)",background:"none",border:"none",cursor:"pointer",color:T.subtle,fontSize:11,fontFamily:inter,WebkitTapHighlightColor:"transparent"}}>
                  {show[f.key]?"Hide":"Show"}
                </button>
              )}
            </div>
          </div>
        ))}
        {error&&<div style={{fontFamily:mono,fontSize:10,color:"#C62828",marginBottom:8}}>{error}</div>}
      </div>

      {/* Connect button */}
      <button onPointerDown={connect} disabled={saving}
        style={{width:"100%",minHeight:48,borderRadius:8,border:"none",background:saving?T.raised:"#2E7D32",color:saving?T.subtle:"#fff",fontFamily:inter,fontWeight:700,fontSize:15,cursor:saving?"not-allowed":"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
        {saving?"Saving...": `Connect ${info.name} →`}
      </button>

      <div style={{fontFamily:mono,fontSize:9,color:T.subtle,marginTop:10,textAlign:"center",lineHeight:1.6}}>
        Credentials encrypted · Never stored in plain text · Never shared
      </div>
    </div>
  )
}
