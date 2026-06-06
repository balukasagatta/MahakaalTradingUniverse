import { useState } from "react"

const BROKER_INFO = {
  upstox: {
    name: "Upstox",
    logo: "🟣",
    dashboard_url: "https://account.upstox.com/developer/apps",
    redirect_url: "https://mtutrade.in/api/auth/broker/upstox/callback",
    fields: [
      { key: "user_id",    label: "Broker Login ID",  placeholder: "Your Upstox User ID (e.g. BB3296)" },
      { key: "api_key",    label: "API Key",           placeholder: "From Upstox developer dashboard" },
      { key: "api_secret", label: "API Secret",        placeholder: "From Upstox developer dashboard", secret: true },
    ],
    help: "Go to Upstox Developer → Create App → Set redirect URL → Copy API Key & Secret",
  },
  dhan: {
    name: "Dhan",
    logo: "🟢",
    dashboard_url: "https://dhanhq.co/developers/",
    redirect_url: "https://mtutrade.in/api/auth/broker/dhan/callback",
    fields: [
      { key: "user_id",    label: "Client ID",         placeholder: "Your Dhan Client ID" },
      { key: "api_key",    label: "Access Token",       placeholder: "Dhan access token", secret: true },
    ],
    help: "Dhan uses access token directly. Go to Dhan → Developer → Generate Access Token",
  },
  fyers: {
    name: "Fyers",
    logo: "🔵",
    dashboard_url: "https://myapi.fyers.in/",
    redirect_url: "https://mtutrade.in/api/auth/broker/fyers/callback",
    fields: [
      { key: "user_id",    label: "Fyers ID",           placeholder: "Your Fyers ID (e.g. XA12345)" },
      { key: "api_key",    label: "App ID",              placeholder: "From Fyers API dashboard" },
      { key: "api_secret", label: "Secret ID",           placeholder: "From Fyers API dashboard", secret: true },
    ],
    help: "Go to myapi.fyers.in → Create App → Set redirect URL → Copy App ID & Secret",
  },
  zerodha: {
    name: "Zerodha",
    logo: "🔴",
    dashboard_url: "https://developers.kite.trade/",
    redirect_url: "https://mtutrade.in/api/auth/broker/zerodha/callback",
    fields: [
      { key: "user_id",    label: "Zerodha User ID",    placeholder: "Your Zerodha ID (e.g. ZX1234)" },
      { key: "api_key",    label: "API Key",             placeholder: "From Kite Connect dashboard" },
      { key: "api_secret", label: "API Secret",          placeholder: "From Kite Connect dashboard", secret: true },
    ],
    help: "Go to Kite Connect → Create App → Whitelist IP 34.60.239.253 → Copy API Key & Secret",
    note: "Requires Static IP. Add 34.60.239.253 to your Kite app whitelist.",
  },
}

const API = "https://mtutrade.in/api"

const T_LIGHT = {
  surface:"#FFFFFF", raised:"#F3F1EE", line:"#E8E4DE",
  subtle:"#7A7670", body:"#3D3A35", ink:"#1A1814",
  brand:"#C8590A", sell:"#C62828", buy:"#2E7D32",
}
const T_DARK = {
  surface:"#141414", raised:"#1E1E1E", line:"#2A2A2A",
  subtle:"#888888", body:"#BBBBBB", ink:"#F0EDE8",
  brand:"#FF8C00", sell:"#FF1744", buy:"#00C853",
}

export default function BrokerConnect({ T, user, onConnected }) {
  const [step,       setStep]       = useState("select") // select | setup | connecting | connected
  const [broker,     setBroker]     = useState(null)
  const [fields,     setFields]     = useState({})
  const [saving,     setSaving]     = useState(false)
  const [connected,  setConnected]  = useState({})
  const [showSecret, setShowSecret] = useState({})
  const [copied,     setCopied]     = useState(false)
  const [error,      setError]      = useState("")

  const inter = "'Inter',system-ui,sans-serif"
  const mono  = "'JetBrains Mono','Fira Mono',monospace"

  function copyRedirectUrl(url) {
    navigator.clipboard.writeText(url)
    setCopied(true)
    setTimeout(()=>setCopied(false), 2000)
  }

  async function saveCreds() {
    const info = BROKER_INFO[broker]
    // Validate all fields filled
    for(const f of info.fields) {
      if(!fields[f.key]?.trim()) { setError(`Please enter ${f.label}`); return }
    }
    setError("")
    setSaving(true)
    const token = localStorage.getItem("mtu_token")
    try {
      const r = await fetch(`${API}/auth/broker/save-creds`, {
        method: "POST",
        headers: { "Content-Type":"application/json", "Authorization":`Bearer ${token}` },
        credentials: "include",
        body: JSON.stringify({ broker, ...fields })
      })
      const data = await r.json()
      if(data.status === "ok") {
        setStep("connecting")
        // Redirect to OAuth
        window.location.href = `${API}/auth/broker/connect/${broker}`
      } else {
        setError(data.detail || "Failed to save credentials")
      }
    } catch(e) {
      setError("Connection error")
    }
    setSaving(false)
  }

  const inp = {
    width:"100%", height:38, border:`1px solid ${T.line}`,
    borderRadius:6, padding:"0 10px",
    fontFamily:mono, fontSize:12, fontWeight:600,
    color:T.ink, background:T.surface, outline:"none",
    boxSizing:"border-box",
  }

  const lbl = (text) => (
    <div style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:4}}>{text}</div>
  )

  // ── Step 1: Select broker ──────────────────────────────────────────────────
  if(step === "select") return (
    <div>
      <div style={{fontFamily:mono,fontSize:9,fontWeight:600,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:12}}>Connect Broker</div>
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8}}>
        {Object.entries(BROKER_INFO).map(([key, info])=>(
          <button key={key} onPointerDown={()=>{ setBroker(key); setFields({}); setError(""); setStep("setup") }}
            style={{padding:"12px 10px",borderRadius:8,border:`1px solid ${T.line}`,background:T.raised,
              fontFamily:inter,fontWeight:600,fontSize:13,color:T.ink,cursor:"pointer",
              textAlign:"left",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
            <div style={{fontSize:18,marginBottom:4}}>{info.logo}</div>
            <div>{info.name}</div>
            {connected[key]&&<div style={{fontSize:9,color:T.buy,fontWeight:700,marginTop:2}}>✓ Connected</div>}
          </button>
        ))}
      </div>
      <div style={{marginTop:12,padding:"10px 12px",background:T.raised,borderRadius:8,border:`1px solid ${T.line}`}}>
        <div style={{fontFamily:mono,fontSize:9,color:T.subtle,lineHeight:1.6}}>
          Each broker requires you to create a free developer API app. Takes 2-3 minutes. 
          VAJRA will guide you through the setup.
        </div>
      </div>
    </div>
  )

  // ── Step 2: Setup ──────────────────────────────────────────────────────────
  if(step === "setup") {
    const info = BROKER_INFO[broker]
    return (
      <div>
        <button onPointerDown={()=>setStep("select")} style={{background:"none",border:"none",cursor:"pointer",color:T.subtle,fontFamily:inter,fontSize:12,fontWeight:600,marginBottom:14,padding:0,WebkitTapHighlightColor:"transparent"}}>
          ← Back
        </button>

        <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:14}}>
          <div style={{fontSize:24}}>{info.logo}</div>
          <div>
            <div style={{fontFamily:inter,fontWeight:700,fontSize:15,color:T.ink}}>{info.name}</div>
            <div style={{fontFamily:mono,fontSize:9,color:T.subtle,marginTop:1}}>Add broker API details</div>
          </div>
        </div>

        {/* Warning */}
        <div style={{background:"#FFF5F5",border:`1px solid #FFCDD2`,borderRadius:8,padding:"10px 12px",marginBottom:14}}>
          <div style={{fontFamily:inter,fontSize:11,fontWeight:600,color:"#C62828",textAlign:"center"}}>
            ⚠️ DO NOT enter your broker login password here
          </div>
        </div>

        {/* Step 1: Open broker dashboard */}
        <div style={{background:T.raised,borderRadius:8,padding:"12px",border:`1px solid ${T.line}`,marginBottom:12}}>
          <div style={{fontFamily:mono,fontSize:8,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:8}}>Step 1 — Create API App</div>
          <a href={info.dashboard_url} target="_blank" rel="noreferrer"
            style={{display:"block",textAlign:"center",padding:"10px",borderRadius:6,background:T.brand,color:"#fff",fontFamily:inter,fontWeight:700,fontSize:13,textDecoration:"none"}}>
            Open {info.name} API Dashboard ↗
          </a>
          <div style={{fontFamily:mono,fontSize:9,color:T.subtle,marginTop:8,lineHeight:1.6}}>{info.help}</div>
          {info.note&&<div style={{fontFamily:mono,fontSize:9,color:"#E65100",marginTop:6,fontWeight:600}}>📌 {info.note}</div>}
        </div>

        {/* Step 2: Redirect URL */}
        <div style={{background:T.raised,borderRadius:8,padding:"12px",border:`1px solid ${T.line}`,marginBottom:12}}>
          <div style={{fontFamily:mono,fontSize:8,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:8}}>Step 2 — Set Redirect URL</div>
          <div style={{fontFamily:mono,fontSize:9,color:T.subtle,marginBottom:8}}>Copy this URL and paste it in your broker's app redirect URL field:</div>
          <div style={{display:"flex",gap:6,alignItems:"center"}}>
            <div style={{flex:1,background:T.surface,border:`1px solid ${T.line}`,borderRadius:6,padding:"8px 10px",fontFamily:mono,fontSize:10,color:T.ink,wordBreak:"break-all"}}>
              {info.redirect_url}
            </div>
            <button onPointerDown={()=>copyRedirectUrl(info.redirect_url)}
              style={{flexShrink:0,height:36,padding:"0 12px",borderRadius:6,border:"none",background:copied?T.buy:T.brand,color:"#fff",fontFamily:inter,fontWeight:700,fontSize:12,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
              {copied?"✓":"Copy"}
            </button>
          </div>
        </div>

        {/* Step 3: Enter creds */}
        <div style={{background:T.raised,borderRadius:8,padding:"12px",border:`1px solid ${T.line}`,marginBottom:12}}>
          <div style={{fontFamily:mono,fontSize:8,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:12}}>Step 3 — Enter API Details</div>
          {info.fields.map(f=>(
            <div key={f.key} style={{marginBottom:10}}>
              {lbl(f.label)}
              <div style={{position:"relative"}}>
                <input
                  type={f.secret && !showSecret[f.key] ? "password" : "text"}
                  value={fields[f.key]||""}
                  onChange={e=>setFields(prev=>({...prev,[f.key]:e.target.value}))}
                  placeholder={f.placeholder}
                  style={inp}
                />
                {f.secret&&(
                  <button onPointerDown={()=>setShowSecret(p=>({...p,[f.key]:!p[f.key]}))}
                    style={{position:"absolute",right:8,top:"50%",transform:"translateY(-50%)",background:"none",border:"none",cursor:"pointer",color:T.subtle,fontSize:11,fontFamily:inter,WebkitTapHighlightColor:"transparent"}}>
                    {showSecret[f.key]?"Hide":"Show"}
                  </button>
                )}
              </div>
            </div>
          ))}
          {error&&<div style={{fontFamily:mono,fontSize:10,color:"#C62828",marginBottom:8}}>{error}</div>}
        </div>

        {/* Connect button */}
        <button onPointerDown={saveCreds} disabled={saving}
          style={{width:"100%",minHeight:48,borderRadius:8,border:"none",background:saving?T.raised:T.buy,color:saving?T.subtle:"#fff",fontFamily:inter,fontWeight:700,fontSize:15,cursor:saving?"not-allowed":"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
          {saving ? "Saving..." : `Connect ${info.name} →`}
        </button>

        <div style={{fontFamily:mono,fontSize:9,color:T.subtle,marginTop:10,textAlign:"center",lineHeight:1.6}}>
          Your credentials are encrypted and stored securely.<br/>
          We never store your broker login password.
        </div>
      </div>
    )
  }

  // ── Connecting ─────────────────────────────────────────────────────────────
  if(step === "connecting") return (
    <div style={{textAlign:"center",padding:"32px 0"}}>
      <div style={{fontSize:32,marginBottom:12}}>🔄</div>
      <div style={{fontFamily:inter,fontWeight:700,fontSize:14,color:T.ink,marginBottom:6}}>Connecting to {BROKER_INFO[broker]?.name}...</div>
      <div style={{fontFamily:mono,fontSize:10,color:T.subtle}}>You'll be redirected to broker login</div>
    </div>
  )

  return null
}
