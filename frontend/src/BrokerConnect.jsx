import { useState, useEffect } from "react"

const BROKERS = {
  upstox:  { name:"Upstox",    logo:"🟣", dashboard:"https://account.upstox.com/developer/apps",   redirect:"https://mtutrade.in/api/auth/broker/upstox/callback",  fields:[{key:"user_id",label:"Broker Login ID",hint:"Your Upstox User ID (e.g. BB3296)"},{key:"api_key",label:"API Key",hint:"From Upstox developer app"},{key:"api_secret",label:"API Secret",hint:"From Upstox developer app",secret:true}], help:"Create App → paste Redirect URL → copy API Key & Secret" },
  dhan:    { name:"Dhan",      logo:"🟢", dashboard:"https://dhanhq.co/developers/",               redirect:"https://mtutrade.in/api/auth/broker/dhan/callback",    fields:[{key:"user_id",label:"Client ID",hint:"Your Dhan Client ID"},{key:"api_key",label:"Access Token",hint:"From Dhan developer portal",secret:true}], help:"Generate access token from Dhan developer portal" },
  fyers:   { name:"Fyers",     logo:"🔵", dashboard:"https://myapi.fyers.in/",                     redirect:"https://mtutrade.in/api/auth/broker/fyers/callback",   fields:[{key:"user_id",label:"Fyers ID",hint:"Your Fyers ID (e.g. XA12345)"},{key:"api_key",label:"App ID",hint:"From Fyers API dashboard"},{key:"api_secret",label:"Secret ID",hint:"From Fyers API dashboard",secret:true}], help:"Create App → paste Redirect URL → copy App ID & Secret" },
  zerodha: { name:"Zerodha",   logo:"🔴", dashboard:"https://developers.kite.trade/",             redirect:"https://mtutrade.in/api/auth/broker/zerodha/callback", fields:[{key:"user_id",label:"Zerodha ID",hint:"Your Zerodha ID (e.g. ZX1234)"},{key:"api_key",label:"API Key",hint:"From Kite Connect"},{key:"api_secret",label:"API Secret",hint:"From Kite Connect",secret:true}], help:"Create App → whitelist IP 34.60.239.253 → paste Redirect URL → copy keys", note:"Whitelist IP: 34.60.239.253" },
}

const API = "https://mtutrade.in/api"

export default function BrokerConnect({ T, user, onConnected }) {
  const [connected, setConnected] = useState({})
  const [selected,  setSelected]  = useState("")
  const [fields,    setFields]    = useState({})
  const [show,      setShow]      = useState({})
  const [copied,    setCopied]    = useState(false)
  const [saving,    setSaving]    = useState(false)
  const [error,     setError]     = useState("")
  const [step,      setStep]      = useState("select") // select | setup

  const inter = "'Inter',system-ui,sans-serif"
  const mono  = "'JetBrains Mono','Fira Mono',monospace"

  useEffect(()=>{
    const token = localStorage.getItem("mtu_token")
    if(!token) return
    fetch(`${API}/auth/broker/my-brokers`,{
      headers:{"Authorization":`Bearer ${token}`},
      credentials:"include"
    }).then(r=>r.json()).then(d=>{ if(d.brokers) setConnected(d.brokers) }).catch(()=>{})
  },[])

  function copy(text){ navigator.clipboard.writeText(text); setCopied(true); setTimeout(()=>setCopied(false),2000) }

  async function disconnect(broker){
    const token = localStorage.getItem("mtu_token")
    await fetch(`${API}/auth/broker/my-brokers/${broker}`,{
      method:"DELETE",
      headers:{"Authorization":`Bearer ${token}`},
      credentials:"include"
    })
    setConnected(p=>{ const n={...p}; delete n[broker]; return n })
  }

  async function connect(){
    const info = BROKERS[selected]
    for(const f of info.fields){
      if(!fields[f.key]?.trim()){ setError(`Please enter ${f.label}`); return }
    }
    setError(""); setSaving(true)
    const token = localStorage.getItem("mtu_token")
    try {
      const r = await fetch(`${API}/auth/broker/save-creds`,{
        method:"POST",
        headers:{"Content-Type":"application/json","Authorization":`Bearer ${token}`},
        credentials:"include",
        body: JSON.stringify({broker:selected,...fields})
      })
      const d = await r.json()
      if(d.status==="ok"){
        const jwt = localStorage.getItem("mtu_token")
        window.location.href = `${API}/auth/broker/connect/${selected}?token=${jwt}`
      } else { setError(d.detail||"Failed") }
    } catch(e){ setError("Connection error") }
    setSaving(false)
  }

  const inp = { width:"100%",height:38,border:`1px solid ${T.line}`,borderRadius:6,padding:"0 10px",fontFamily:mono,fontSize:12,fontWeight:600,color:T.ink,background:T.surface,outline:"none",boxSizing:"border-box" }
  const tag = t => <div style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:4}}>{t}</div>

  // ── Connected brokers list ─────────────────────────────────────────────────
  const connectedList = Object.entries(connected)

  return (
    <div>
      {/* Connected brokers */}
      {connectedList.length > 0 && (
        <div style={{marginBottom:14}}>
          {tag("Connected")}
          <div style={{display:"flex",flexDirection:"column",gap:6}}>
            {connectedList.map(([key, data])=>{
              const info = BROKERS[key]
              return (
                <div key={key} style={{display:"flex",alignItems:"center",justifyContent:"space-between",padding:"10px 12px",borderRadius:8,border:`1.5px solid ${T.buy}`,background:T.canvas=="#0A0A0A"?"#0A1A0A":"#F0FFF4"}}>
                  <div style={{display:"flex",alignItems:"center",gap:8}}>
                    <span style={{fontSize:18}}>{info?.logo}</span>
                    <div>
                      <div style={{fontFamily:inter,fontWeight:700,fontSize:13,color:T.ink}}>{info?.name}</div>
                      <div style={{fontFamily:mono,fontSize:9,color:T.buy,fontWeight:600}}>✓ Connected · {data.connected_at?.slice(0,10)}</div>
                    </div>
                  </div>
                  <button onPointerDown={()=>disconnect(key)} style={{fontFamily:inter,fontSize:11,fontWeight:600,color:T.sell,background:"none",border:`1px solid ${T.sell}`,borderRadius:5,padding:"4px 10px",cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
                    Disconnect
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Add broker */}
      {step==="select" && (
        <div>
          {tag("Add Broker")}
          <div style={{display:"flex",gap:8,alignItems:"center",marginBottom:10}}>
            <select value={selected} onChange={e=>setSelected(e.target.value)}
              style={{flex:1,height:40,border:`1px solid ${T.line}`,borderRadius:8,padding:"0 10px",fontFamily:inter,fontSize:13,fontWeight:600,color:selected?T.ink:T.subtle,background:T.surface,outline:"none",cursor:"pointer"}}>
              <option value="">Select broker to connect...</option>
              {Object.entries(BROKERS).filter(([k])=>!connected[k]).map(([k,v])=>(
                <option key={k} value={k}>{v.logo} {v.name}</option>
              ))}
            </select>
            <button onPointerDown={()=>{ if(selected){ setStep("setup"); setFields({}); setError("") } }}
              disabled={!selected}
              style={{height:40,padding:"0 16px",borderRadius:8,border:"none",background:selected?T.brand:"#ccc",color:"#fff",fontFamily:inter,fontWeight:700,fontSize:13,cursor:selected?"pointer":"not-allowed",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
              Setup →
            </button>
          </div>
          {connectedList.length===0&&(
            <div style={{fontFamily:mono,fontSize:9,color:T.subtle,lineHeight:1.6,padding:"8px 10px",background:T.raised,borderRadius:6,border:`1px solid ${T.line}`}}>
              Connect your broker to get live market data and execute orders through VAJRA.
            </div>
          )}
        </div>
      )}

      {/* Setup flow */}
      {step==="setup" && selected && (()=>{
        const info = BROKERS[selected]
        return (
          <div>
            <button onPointerDown={()=>setStep("select")} style={{background:"none",border:"none",cursor:"pointer",color:T.subtle,fontFamily:inter,fontSize:12,fontWeight:600,padding:0,marginBottom:12,WebkitTapHighlightColor:"transparent"}}>← Back</button>

            {/* Warning */}
            <div style={{background:"#FFF5F5",border:`1px solid #FFCDD2`,borderRadius:8,padding:"8px 12px",marginBottom:10,textAlign:"center"}}>
              <div style={{fontFamily:inter,fontSize:11,fontWeight:600,color:"#C62828"}}>⚠️ DO NOT enter your broker account password here</div>
            </div>

            {/* Step 1 */}
            <div style={{background:T.raised,borderRadius:8,padding:"12px",border:`1px solid ${T.line}`,marginBottom:8}}>
              {tag("Step 1 — Create API App")}
              <a href={info.dashboard} target="_blank" rel="noreferrer"
                style={{display:"block",textAlign:"center",padding:"10px",borderRadius:6,background:T.brand,color:"#fff",fontFamily:inter,fontWeight:700,fontSize:13,textDecoration:"none",marginBottom:6}}>
                Open {info.name} Developer Portal ↗
              </a>
              <div style={{fontFamily:mono,fontSize:9,color:T.subtle,lineHeight:1.6}}>{info.help}</div>
              {info.note&&<div style={{fontFamily:mono,fontSize:9,color:"#E65100",marginTop:4,fontWeight:600}}>📌 {info.note}</div>}
            </div>

            {/* Step 2 */}
            <div style={{background:T.raised,borderRadius:8,padding:"12px",border:`1px solid ${T.line}`,marginBottom:8}}>
              {tag("Step 2 — Set Redirect URL in broker app")}
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

            {/* Step 3 */}
            <div style={{background:T.raised,borderRadius:8,padding:"12px",border:`1px solid ${T.line}`,marginBottom:10}}>
              {tag("Step 3 — Enter your API credentials")}
              {info.fields.map(f=>(
                <div key={f.key} style={{marginBottom:8}}>
                  {tag(f.label)}
                  <div style={{position:"relative"}}>
                    <input type={f.secret&&!show[f.key]?"password":"text"} value={fields[f.key]||""} onChange={e=>setFields(p=>({...p,[f.key]:e.target.value}))} placeholder={f.hint} style={inp}/>
                    {f.secret&&<button onPointerDown={()=>setShow(p=>({...p,[f.key]:!p[f.key]}))} style={{position:"absolute",right:8,top:"50%",transform:"translateY(-50%)",background:"none",border:"none",cursor:"pointer",color:T.subtle,fontSize:11,fontFamily:inter,WebkitTapHighlightColor:"transparent"}}>{show[f.key]?"Hide":"Show"}</button>}
                  </div>
                </div>
              ))}
              {error&&<div style={{fontFamily:mono,fontSize:10,color:"#C62828",marginBottom:6}}>{error}</div>}
            </div>

            <button onPointerDown={connect} disabled={saving}
              style={{width:"100%",minHeight:46,borderRadius:8,border:"none",background:saving?T.raised:"#2E7D32",color:saving?T.subtle:"#fff",fontFamily:inter,fontWeight:700,fontSize:14,cursor:saving?"not-allowed":"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
              {saving?"Saving...": `Connect ${info.name} →`}
            </button>
            <div style={{fontFamily:mono,fontSize:9,color:T.subtle,marginTop:8,textAlign:"center",lineHeight:1.6}}>Credentials encrypted · Never stored in plain text</div>
          </div>
        )
      })()}
    </div>
  )
}
