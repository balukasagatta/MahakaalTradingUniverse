import { useState, useEffect } from "react"

const API = "https://mtutrade.in/api"

const LIGHT = {
  canvas:"#FAF9F7", surface:"#FFFFFF", raised:"#F3F1EE",
  line:"#E8E4DE", subtle:"#7A7670", body:"#3D3A35", ink:"#1A1814",
  brand:"#C8590A", sell:"#C62828", buy:"#2E7D32", warn:"#E65100",
}
const DARK = {
  canvas:"#0A0A0A", surface:"#141414", raised:"#1E1E1E",
  line:"#2A2A2A", subtle:"#888888", body:"#BBBBBB", ink:"#F0EDE8",
  brand:"#FF8C00", sell:"#FF1744", buy:"#00C853", warn:"#FF8C00",
}
const inter = "'Inter',system-ui,sans-serif"
const mono  = "'JetBrains Mono','Fira Mono',monospace"

const MENTAL_STATES = [
  { id:"calm",          label:"Calm & Focused",    emoji:"😊", verdict_mod:0,  note:"Best state to trade. Stick to your plan." },
  { id:"neutral",       label:"Neutral",            emoji:"😐", verdict_mod:-1, note:"Stay conservative. Let setups come to you." },
  { id:"anxious",       label:"Stressed / Anxious", emoji:"😤", verdict_mod:-2, note:"High risk of reactive trades. Consider reduced size." },
  { id:"overconfident", label:"Overconfident",      emoji:"🔥", verdict_mod:-2, note:"Overconfidence kills accounts. Cut qty by 50%." },
]

function getVerdict(state, maxLoss, target, maxTrades) {
  if (state?.id === "anxious") return {
    action:"CAUTION", color:"#E65100", bg:"#FFF3E0", darkBg:"#1A0E00", icon:"⚠️",
    title:"Consider sitting out today",
    body:"Trading while anxious leads to reactive decisions. If you must trade, reduce size by 50% and max 2 trades.",
    config:{ max_trades_per_day:Math.min(maxTrades,2), daily_loss_limit:-Math.abs(maxLoss*0.5), daily_target:target }
  }
  if (state?.id === "overconfident") return {
    action:"REDUCE", color:"#C62828", bg:"#FFF5F5", darkBg:"#1A0000", icon:"🛡️",
    title:"Overconfidence detected",
    body:"PRAGNYA has reduced your qty allowance by 50%. This protects your streak on days you feel invincible.",
    config:{ max_trades_per_day:Math.min(maxTrades,3), daily_loss_limit:-Math.abs(maxLoss*0.6), daily_target:target }
  }
  if (state?.id === "neutral") return {
    action:"CONSERVATIVE", color:"#7A7670", bg:"#F3F1EE", darkBg:"#1A1A1A", icon:"🧘",
    title:"Stay conservative today",
    body:"Neutral days are fine. Let high-quality setups come to you. No forcing trades.",
    config:{ max_trades_per_day:maxTrades, daily_loss_limit:-Math.abs(maxLoss), daily_target:target }
  }
  return {
    action:"READY", color:"#2E7D32", bg:"#F1F8E9", darkBg:"#001A00", icon:"✅",
    title:"You're ready to trade",
    body:"Calm and focused — the ideal trading state. Execute your plan with discipline.",
    config:{ max_trades_per_day:maxTrades, daily_loss_limit:-Math.abs(maxLoss), daily_target:target }
  }
}

export default function PreMarketPlanner({ user, dark, onComplete, onSkip }) {
  const T = dark ? DARK : LIGHT
  const [step, setStep] = useState(1)
  const [mentalState, setMentalState] = useState(null)
  const [maxLoss, setMaxLoss] = useState("")
  const [target, setTarget] = useState("")
  const [maxTrades, setMaxTrades] = useState("")
  const [commitment, setCommitment] = useState("")
  const [verdict, setVerdict] = useState(null)
  const [quote, setQuote] = useState(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    const tk = localStorage.getItem("mtu_token")
    if (tk) fetch(`${API}/vajra/pragnya/quote`,{headers:{"Authorization":"Bearer "+tk},credentials:"include"})
      .then(r=>r.json()).then(d=>{ if(d.quote) setQuote(d.quote) }).catch(()=>{})
  }, [])

  const inputStyle = {
    width:"100%", height:48, border:`1.5px solid ${T.line}`, borderRadius:10,
    padding:"0 14px", fontFamily:mono, fontSize:18, fontWeight:700,
    color:T.ink, background:T.surface, outline:"none", boxSizing:"border-box"
  }

  const handleCommit = async () => {
    setSaving(true)
    try {
      const tk = localStorage.getItem("mtu_token")
      await fetch(`${API}/vajra/pragnya/planner`,{
        method:"POST", credentials:"include",
        headers:{"Content-Type":"application/json","Authorization":"Bearer "+tk},
        body:JSON.stringify({ mental_state:mentalState?.id, max_loss:Number(maxLoss),
          target:Number(target), max_trades:Number(maxTrades), commitment, ...verdict.config })
      })
      localStorage.setItem("mtu_planned_"+new Date().toISOString().slice(0,10),"1")
    } catch(e){}
    setSaving(false)
    onComplete()
  }



  if (step===4&&verdict) return (
    <div style={{minHeight:"100vh",background:T.canvas,display:"flex",alignItems:"center",justifyContent:"center",padding:20,fontFamily:inter}}>
      <div style={{maxWidth:420,width:"100%"}}>
        <div style={{textAlign:"center",marginBottom:24}}>
          <div style={{fontSize:40,marginBottom:8}}>{verdict.icon}</div>
          <div style={{fontFamily:mono,fontSize:10,color:T.subtle,letterSpacing:"2px",textTransform:"uppercase"}}>PRAGNYA Verdict</div>
        </div>
        <div style={{background:dark?verdict.darkBg:verdict.bg,borderRadius:16,padding:24,border:`1.5px solid ${verdict.color}40`,marginBottom:16}}>
          <div style={{fontFamily:mono,fontSize:13,fontWeight:700,color:verdict.color,marginBottom:8}}>{verdict.title}</div>
          <div style={{fontSize:13,color:T.body,lineHeight:1.7}}>{verdict.body}</div>
        </div>
        <div style={{background:T.surface,borderRadius:12,padding:16,border:`1px solid ${T.line}`,marginBottom:20}}>
          <div style={{fontFamily:mono,fontSize:9,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:12}}>PRAGNYA will enforce today</div>
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",gap:8}}>
            {[{label:"Max Loss",value:`₹${Math.abs(verdict.config.daily_loss_limit).toLocaleString()}`},
              {label:"Target",value:`₹${verdict.config.daily_target.toLocaleString()}`},
              {label:"Max Trades",value:verdict.config.max_trades_per_day}].map(({label,value})=>(
              <div key={label} style={{background:T.raised,borderRadius:8,padding:"10px 8px",textAlign:"center"}}>
                <div style={{fontFamily:mono,fontSize:8,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase",marginBottom:4}}>{label}</div>
                <div style={{fontFamily:mono,fontSize:14,fontWeight:700,color:T.ink}}>{value}</div>
              </div>
            ))}
          </div>
        </div>
        {commitment&&<div style={{background:T.raised,borderRadius:10,padding:"12px 14px",border:`1px solid ${T.line}`,marginBottom:20,fontSize:13,color:T.body,fontStyle:"italic"}}>
          "My commitment: {commitment}"
        </div>}
        <button onPointerDown={handleCommit} disabled={saving} style={{width:"100%",height:52,borderRadius:12,border:"none",background:T.brand,color:"#fff",fontFamily:inter,fontWeight:700,fontSize:16,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation",opacity:saving?0.7:1}}>
          {saving?"Saving…":"I Commit. Enter Terminal →"}
        </button>
      </div>
    </div>
  )

  return (
    <div style={{minHeight:"100vh",background:T.canvas,display:"flex",alignItems:"center",justifyContent:"center",padding:20,fontFamily:inter}}>
      <div style={{maxWidth:420,width:"100%"}}>
        <div style={{textAlign:"center",marginBottom:28}}>
          <div style={{fontFamily:mono,fontSize:22,fontWeight:700,color:T.ink,marginBottom:4}}>
            🧠 <span style={{color:T.brand}}>Pre-Market</span> Ritual
          </div>
          <div style={{fontSize:12,color:T.subtle}}>Set your intent before the market opens</div>
          <div style={{display:"flex",justifyContent:"center",gap:6,marginTop:16}}>
            {[1,2,3].map(s=>(
              <div key={s} style={{width:s===step?20:8,height:8,borderRadius:100,background:s<=step?T.brand:T.line,transition:"all 0.3s"}}/>
            ))}
          </div>
        </div>
        <div style={{background:T.surface,borderRadius:16,padding:24,border:`1px solid ${T.line}`,boxShadow:"0 4px 24px rgba(0,0,0,0.06)"}}>
          {step===1&&(
            <div>
              <div style={{fontFamily:mono,fontSize:10,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:6}}>Step 1 of 3</div>
              <div style={{fontSize:16,fontWeight:700,color:T.ink,marginBottom:4}}>How are you feeling right now?</div>
              <div style={{fontSize:12,color:T.subtle,marginBottom:20}}>Be honest. PRAGNYA will adjust your limits accordingly.</div>
              <div style={{display:"flex",flexDirection:"column",gap:10}}>
                {MENTAL_STATES.map(s=>(
                  <button key={s.id} onPointerDown={()=>{setMentalState(s);setTimeout(()=>setStep(2),250)}}
                    style={{display:"flex",alignItems:"center",gap:12,padding:"14px 16px",borderRadius:10,
                      border:`1.5px solid ${mentalState?.id===s.id?T.brand:T.line}`,
                      background:mentalState?.id===s.id?(dark?"#2A1A0A":"#FFF3E0"):T.raised,
                      cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation",transition:"all 0.15s"}}>
                    <span style={{fontSize:24}}>{s.emoji}</span>
                    <div style={{textAlign:"left"}}>
                      <div style={{fontWeight:700,fontSize:13,color:T.ink}}>{s.label}</div>
                      <div style={{fontSize:11,color:T.subtle,marginTop:2}}>{s.note}</div>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
          {step===2&&(
            <div>
              <div style={{fontFamily:mono,fontSize:10,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:6}}>Step 2 of 3</div>
              <div style={{fontSize:16,fontWeight:700,color:T.ink,marginBottom:4}}>Set today's limits</div>
              <div style={{fontSize:12,color:T.subtle,marginBottom:20}}>Commit to these before you see a single candle.</div>
              <div style={{display:"flex",flexDirection:"column",gap:16}}>
                {[{label:"Max Loss I'm okay with (₹)",val:maxLoss,set:setMaxLoss,ph:"e.g. 2500"},
                  {label:"Target I'll be happy with (₹)",val:target,set:setTarget,ph:"e.g. 5000"},
                  {label:"Max trades today",val:maxTrades,set:setMaxTrades,ph:"e.g. 4"}].map(({label,val,set,ph})=>(
                  <div key={label}>
                    <label style={{fontFamily:mono,fontSize:9,fontWeight:600,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:6,display:"block"}}>{label}</label>
                    <input type="number" value={val} onChange={e=>set(e.target.value)} placeholder={ph} style={inputStyle}
                      onFocus={e=>e.target.style.borderColor=T.brand} onBlur={e=>e.target.style.borderColor=T.line}/>
                  </div>
                ))}
              </div>
              <button onPointerDown={()=>{if(maxLoss&&target&&maxTrades)setStep(3)}} disabled={!maxLoss||!target||!maxTrades}
                style={{width:"100%",height:48,borderRadius:10,border:"none",background:(!maxLoss||!target||!maxTrades)?T.raised:T.brand,color:(!maxLoss||!target||!maxTrades)?T.subtle:"#fff",fontFamily:inter,fontWeight:700,fontSize:15,cursor:(!maxLoss||!target||!maxTrades)?"not-allowed":"pointer",marginTop:20,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
                Next →
              </button>
            </div>
          )}
          {step===3&&(
            <div>
              <div style={{fontFamily:mono,fontSize:10,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:6}}>Step 3 of 3</div>
              <div style={{fontSize:16,fontWeight:700,color:T.ink,marginBottom:4}}>One rule you'll follow today</div>
              <div style={{fontSize:12,color:T.subtle,marginBottom:20}}>Write it down. Accountability starts here.</div>
              <textarea value={commitment} onChange={e=>setCommitment(e.target.value)}
                placeholder="e.g. I will not revenge trade after a loss. I will step away after 2 SL hits."
                style={{width:"100%",minHeight:100,border:`1.5px solid ${T.line}`,borderRadius:10,padding:14,fontFamily:inter,fontSize:13,color:T.ink,background:T.surface,outline:"none",boxSizing:"border-box",resize:"none",lineHeight:1.6}}
                onFocus={e=>e.target.style.borderColor=T.brand} onBlur={e=>e.target.style.borderColor=T.line}/>
              <button onPointerDown={()=>{const v=getVerdict(mentalState,Number(maxLoss),Number(target),Number(maxTrades));setVerdict(v);setStep(4)}}
                style={{width:"100%",height:48,borderRadius:10,border:"none",background:T.brand,color:"#fff",fontFamily:inter,fontWeight:700,fontSize:15,cursor:"pointer",marginTop:16,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
                Get PRAGNYA Verdict →
              </button>
              <button onPointerDown={()=>setStep(2)}
                style={{width:"100%",height:36,borderRadius:10,border:"none",background:"none",color:T.subtle,fontFamily:inter,fontSize:13,cursor:"pointer",marginTop:8,WebkitTapHighlightColor:"transparent"}}>
                ← Back
              </button>
            </div>
          )}
        </div>
        <button onPointerDown={onSkip} style={{width:"100%",marginTop:16,background:"none",border:"none",color:T.subtle,fontFamily:inter,fontSize:12,cursor:"pointer",padding:8,WebkitTapHighlightColor:"transparent"}}>
          Skip today's ritual →
        </button>
      </div>
    </div>
  )
}
