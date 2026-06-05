import { useState, useEffect } from "react"

const API = "https://mtutrade.in/api"
const INSTRUMENTS = {
  SENSEX: { lot: 20, step: 100, expiry_day: "THU" },
  NIFTY:  { lot: 65, step: 50,  expiry_day: "TUE" },
}
const BROKERS = ["Upstox","Dhan","Kotak Neo","Zerodha","Angel","Fyers"]

async function api(path, opts={}) {
  try {
    const r = await fetch(API+path, { headers:{"Content-Type":"application/json"}, ...opts })
    return r.json()
  } catch(e) { return null }
}

const C = {
  white:  "#FFFFFF",
  ink:    "#111111",
  sub:    "#333333",
  label:  "#555555",
  border: "#CCCCCC",
  bg:     "#F5F5F5",
  red:    "#CC0000",
  green:  "#006600",
  orange: "#E65100",
  amber:  "#7B5800",
}

const M = { fontFamily:"'IBM Plex Mono',monospace" }
const S = { fontFamily:"'IBM Plex Sans',sans-serif" }

export default function App() {
  const [broker,    setBroker]    = useState(()=>localStorage.getItem("mtu_broker")||"")
  const [screen,    setScreen]    = useState(()=>localStorage.getItem("mtu_broker")?"main":"broker")
  const [symbol,    setSymbol]    = useState("SENSEX")
  const [expiries,  setExpiries]  = useState([])
  const [expiry,    setExpiry]    = useState("")
  const [strikes,   setStrikes]   = useState([])
  const [ceStrike,  setCeStrike]  = useState("")
  const [peStrike,  setPeStrike]  = useState("")
  const [ceLtp,     setCeLtp]     = useState(null)
  const [peLtp,     setPeLtp]     = useState(null)
  const [ceKey,     setCeKey]     = useState("")
  const [peKey,     setPeKey]     = useState("")
  const [qty,       setQty]       = useState(1)
  const [slPts,     setSlPts]     = useState(20)
  const [tgtPts,    setTgtPts]    = useState(20)
  const [market,    setMarket]    = useState({})
  const [pragnya,   setPragnya]   = useState(null)
  const [positions, setPositions] = useState([])
  const [tab,       setTab]       = useState("positions")
  const [toast,     setToast]     = useState(null)
  const [gitaMsg,   setGitaMsg]   = useState(null)
  const [loading,   setLoading]   = useState(false)

  const instr = INSTRUMENTS[symbol] || INSTRUMENTS.SENSEX

  function showToast(msg, ok=true) { setToast({msg,ok}); setTimeout(()=>setToast(null),3000) }

  useEffect(()=>{
    if(screen!=="main") return
    const poll=async()=>{ const r=await api("/vajra/market"); if(r) setMarket(r) }
    poll(); const t=setInterval(poll,5000); return()=>clearInterval(t)
  },[screen])

  useEffect(()=>{
    if(screen!=="main") return
    setExpiries([]); setExpiry(""); setStrikes([])
    setCeStrike(""); setPeStrike(""); setCeLtp(null); setPeLtp(null)
    api(`/sutra/expiries?index=${symbol}`).then(r=>{
      if(r?.expiries?.length){ setExpiries(r.expiries); setExpiry(r.expiries[0]) }
    })
  },[symbol,screen])

  useEffect(()=>{
    if(!expiry||screen!=="main") return
    setLoading(true)
    api(`/sutra/chain/atm?index=${symbol}&expiry=${expiry}`).then(r=>{
      setLoading(false)
      if(!r?.strikes?.length) return
      setStrikes(r.strikes)
      const atm=r.atm
      const pool=r.strikes.filter(s=>s.ce.ltp>0&&s.pe.ltp>0)
      const src=pool.length?pool:r.strikes
      const ce=src.find(s=>Number(s.strike)>=atm)||src[Math.floor(src.length/2)]
      const pe=[...src].reverse().find(s=>Number(s.strike)<=atm)||src[Math.floor(src.length/2)]
      setCeStrike(String(ce.strike)); setCeLtp(ce.ce.ltp); setCeKey(ce.ce.key)
      setPeStrike(String(pe.strike)); setPeLtp(pe.pe.ltp); setPeKey(pe.pe.key)
    })
  },[expiry,symbol,screen])

  useEffect(()=>{
    if(!ceKey||!peKey||screen!=="main") return
    const poll=async()=>{
      const r=await api(`/sutra/ltp?ce_key=${encodeURIComponent(ceKey)}&pe_key=${encodeURIComponent(peKey)}`)
      if(!r) return
      Object.entries(r).forEach(([k,v])=>{ if(k.includes("CE")) setCeLtp(v); if(k.includes("PE")) setPeLtp(v) })
    }
    const t=setInterval(poll,2000); return()=>clearInterval(t)
  },[ceKey,peKey,screen])

  useEffect(()=>{
    if(screen!=="main") return
    const poll=async()=>{
      const r=await api("/vajra/state")
      if(r?.state) setPragnya(r)
      if(r?.trades) setPositions(r.trades.filter(t=>t.status==="OPEN"))
    }
    poll(); const t=setInterval(poll,10000); return()=>clearInterval(t)
  },[screen])

  function selectBroker(b){ setBroker(b); localStorage.setItem("mtu_broker",b); setScreen("main") }

  function onCeChange(val){
    setCeStrike(val)
    const row=strikes.find(s=>String(s.strike)===val)
    if(row){ setCeLtp(row.ce.ltp); setCeKey(row.ce.key) }
  }

  function onPeChange(val){
    setPeStrike(val)
    const row=strikes.find(s=>String(s.strike)===val)
    if(row){ setPeLtp(row.pe.ltp); setPeKey(row.pe.key) }
  }

  async function execute(type){
    const isCall=type.includes("Call")
    const ltp=isCall?ceLtp:peLtp
    const strike=isCall?ceStrike:peStrike
    const action=type.includes("Sell")?"SELL":"BUY"
    const optType=isCall?"CE":"PE"
    if(!strike){ showToast("Select a strike first",false); return }
    const r=await api("/vajra/trade/open",{method:"POST",body:JSON.stringify({
      instrument:`${symbol}${strike}${optType}`,direction:action,
      entry:ltp||0,sl:action==="SELL"?(ltp||0)+slPts:(ltp||0)-slPts,
      target:action==="SELL"?(ltp||0)-tgtPts:(ltp||0)+tgtPts,
      lots:qty,strategy:`${action} ${optType}`
    })})
    if(r?.status==="ok"){
      showToast(`✓ ${type} @ ₹${ltp} · ${qty}L`)
      const pr=await api("/vajra/state")
      if(pr?.trades) setPositions(pr.trades.filter(t=>t.status==="OPEN"))
      setPragnya(pr)
    } else {
      const msg=r?.detail||"Order failed"
      showToast(msg,false)
      if(msg.toLowerCase().includes("lock")) setGitaMsg(msg)
    }
  }

  async function closePos(id,exitPrice,reason){
    const r=await api("/vajra/trade/close",{method:"POST",body:JSON.stringify({trade_id:id,exit_price:exitPrice||0,exit_reason:reason})})
    if(r?.status==="ok"){
      showToast(`Closed: ${r.pnl>=0?"+":""}₹${Math.round(r.pnl||0)}`)
      const pr=await api("/vajra/state")
      if(pr?.trades) setPositions(pr.trades.filter(t=>t.status==="OPEN"))
      setPragnya(pr)
    }
  }

  const st=pragnya?.state||{}; const cfg=pragnya?.cfg||{}; const quote=pragnya?.quote||{}
  const dscore=st.discipline_score||100; const dayPnl=st.daily_pnl||0
  const sensex=market.sensex; const nifty=market.nifty; const vix=market.vix?.ltp
  const indexLtp=symbol==="SENSEX"?sensex?.ltp:nifty?.ltp
  const now=new Date().toLocaleTimeString("en-IN",{hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false})

  // ── BROKER SCREEN ──────────────────────────────────────────────────────────
  if(screen==="broker") return (
    <div style={{minHeight:"100vh",background:C.white,display:"flex",alignItems:"center",justifyContent:"center",padding:20,...S}}>
      <div style={{width:"100%",maxWidth:360}}>
        <div style={{...M,fontSize:28,fontWeight:700,color:C.ink,marginBottom:2}}>⚡ <span style={{color:C.orange}}>VAJRA</span></div>
        <div style={{...M,fontSize:10,color:C.label,letterSpacing:2,textTransform:"uppercase",marginBottom:28}}>Options Scalping Terminal</div>
        <div style={{fontSize:12,fontWeight:700,color:C.ink,marginBottom:10,textTransform:"uppercase",letterSpacing:1}}>Select Your Broker</div>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,marginBottom:24}}>
          {BROKERS.map(b=>(
            <button key={b} onPointerDown={()=>selectBroker(b)} style={{
              padding:"14px 10px",borderRadius:4,
              border:`2px solid ${broker===b?C.orange:C.border}`,
              background:broker===b?"#FFF3E0":C.white,
              color:broker===b?C.orange:C.ink,
              ...S,fontWeight:700,fontSize:14,cursor:"pointer",
              WebkitTapHighlightColor:"transparent",touchAction:"manipulation"
            }}>{b}</button>
          ))}
        </div>
        <div style={{borderTop:`1px solid ${C.border}`,paddingTop:16}}>
          <div style={{fontSize:12,color:C.sub,fontStyle:"italic",lineHeight:1.7}}>"{quote.text||"Perform your duty equipoised, abandoning all attachment."}"</div>
          <div style={{...M,fontSize:10,color:C.label,marginTop:6}}>— {quote.src||"Bhagavad Gita 2.48"}</div>
        </div>
      </div>
    </div>
  )

  // ── GITA OVERLAY ──────────────────────────────────────────────────────────
  if(gitaMsg) return (
    <div style={{position:"fixed",inset:0,background:"rgba(255,255,255,0.97)",zIndex:99999,display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",padding:32,...S}}>
      <div style={{fontSize:52,marginBottom:16}}>🕉️</div>
      <div style={{...M,fontSize:20,fontWeight:700,color:C.red,marginBottom:8}}>PRAGNYA ACTIVATED</div>
      <div style={{fontSize:14,color:C.sub,marginBottom:24,textAlign:"center",maxWidth:300}}>{gitaMsg}</div>
      <div style={{border:`1px solid ${C.border}`,borderRadius:6,padding:16,maxWidth:340,marginBottom:24,background:C.bg}}>
        <div style={{fontSize:13,color:C.ink,fontStyle:"italic",lineHeight:1.7}}>"{quote.text}"</div>
        <div style={{...M,fontSize:10,color:C.label,marginTop:8}}>— {quote.src}</div>
      </div>
      <button onPointerDown={()=>setGitaMsg(null)} style={{padding:"10px 32px",borderRadius:4,border:`1.5px solid ${C.border}`,background:C.white,color:C.ink,...S,fontWeight:600,fontSize:14,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Dismiss</button>
    </div>
  )

  // ── MAIN TERMINAL ──────────────────────────────────────────────────────────
  return (
    <div style={{minHeight:"100vh",background:C.white,...S}}>

      {toast&&<div style={{position:"fixed",top:0,left:0,right:0,zIndex:9999,background:toast.ok?C.green:C.red,padding:"12px 16px",fontSize:14,fontWeight:700,color:C.white,textAlign:"center"}}>{toast.msg}</div>}
      {loading&&<div style={{position:"fixed",top:0,left:0,right:0,zIndex:9998,height:3,background:C.orange}}/>}

      {/* TOP BAR — dark */}
      <div style={{background:"#1A1A1A",color:C.white,padding:"8px 12px",display:"flex",alignItems:"center",justifyContent:"space-between",flexWrap:"wrap",gap:8}}>
        <div style={{display:"flex",alignItems:"center",gap:12}}>
          <div style={{...M,fontSize:18,fontWeight:700}}>⚡ <span style={{color:"#FF8C00"}}>VAJRA</span></div>
          <button onPointerDown={()=>setScreen("broker")} style={{fontSize:11,fontWeight:700,padding:"3px 10px",borderRadius:3,border:"1px solid #FF8C00",background:"transparent",color:"#FF8C00",cursor:"pointer",...M,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>🔗 {broker}</button>
        </div>
        <div style={{display:"flex",gap:20,alignItems:"center"}}>
          {[["SENSEX",sensex?.ltp,sensex?.change,sensex?.pct],["NIFTY",nifty?.ltp,0,0],["VIX",vix,0,0]].map(([name,ltp,chg,pct])=>(
            <div key={name} style={{textAlign:"center"}}>
              <div style={{...M,fontSize:8,color:"#999",letterSpacing:1,textTransform:"uppercase"}}>{name}</div>
              <div style={{...M,fontSize:15,fontWeight:700,color:chg>0?"#4CAF50":chg<0?"#F44336":C.white}}>{ltp?ltp.toLocaleString("en-IN",{maximumFractionDigits:2}):"—"}</div>
              {chg!==0&&<div style={{...M,fontSize:9,color:chg>=0?"#4CAF50":"#F44336"}}>{chg>=0?"+":""}{chg?.toFixed(1)} ({pct>=0?"+":""}{pct?.toFixed(2)}%)</div>}
            </div>
          ))}
        </div>
        <div style={{display:"flex",gap:14,alignItems:"center"}}>
          <div style={{textAlign:"right"}}>
            <div style={{...M,fontSize:8,color:"#999",letterSpacing:1}}>DAY P&L</div>
            <div style={{...M,fontSize:15,fontWeight:700,color:dayPnl>=0?"#4CAF50":"#F44336"}}>{dayPnl>=0?"+":""}₹{Math.abs(dayPnl).toLocaleString()}</div>
          </div>
          <div style={{textAlign:"right"}}>
            <div style={{...M,fontSize:8,color:"#999",letterSpacing:1}}>PRAGNYA</div>
            <div style={{...M,fontSize:15,fontWeight:700,color:dscore>=80?"#4CAF50":dscore>=50?"#FFA726":"#F44336"}}>{dscore}/100</div>
          </div>
          <div style={{...M,fontSize:11,color:"#999"}}>{now}</div>
        </div>
      </div>

      {/* INSTRUMENT ROW */}
      <div style={{background:C.bg,borderBottom:`1px solid ${C.border}`,padding:"8px 12px",display:"flex",flexWrap:"wrap",gap:10,alignItems:"flex-end"}}>
        {[
          ["Symbol",    <select value={symbol}    onChange={e=>setSymbol(e.target.value)}    style={{...M,fontSize:13,fontWeight:700,color:C.ink,border:`1px solid ${C.border}`,borderRadius:3,padding:"6px 8px",background:C.white,cursor:"pointer"}}>{Object.keys(INSTRUMENTS).map(k=><option key={k}>{k}</option>)}</select>],
          ["Expiry",    <select value={expiry}    onChange={e=>setExpiry(e.target.value)}    style={{...M,fontSize:13,fontWeight:700,color:C.ink,border:`1px solid ${C.border}`,borderRadius:3,padding:"6px 8px",background:C.white,cursor:"pointer"}}>{expiries.map(e=><option key={e}>{e}</option>)}</select>],
          ["CE Strike", <select value={ceStrike}  onChange={e=>onCeChange(e.target.value)}   style={{...M,fontSize:13,fontWeight:700,color:C.ink,border:`1px solid ${C.border}`,borderRadius:3,padding:"6px 8px",background:C.white,cursor:"pointer"}}>{strikes.map(s=><option key={s.strike} value={String(s.strike)}>{s.strike}{s.is_atm?" ◀ATM":""}</option>)}</select>],
          ["PE Strike", <select value={peStrike}  onChange={e=>onPeChange(e.target.value)}   style={{...M,fontSize:13,fontWeight:700,color:C.ink,border:`1px solid ${C.border}`,borderRadius:3,padding:"6px 8px",background:C.white,cursor:"pointer"}}>{strikes.map(s=><option key={s.strike} value={String(s.strike)}>{s.strike}{s.is_atm?" ◀ATM":""}</option>)}</select>],
        ].map(([label,el])=>(
          <div key={label}>
            <div style={{...M,fontSize:9,fontWeight:700,color:C.label,letterSpacing:1.5,textTransform:"uppercase",marginBottom:3}}>{label}</div>
            {el}
          </div>
        ))}
        <div>
          <div style={{...M,fontSize:9,fontWeight:700,color:C.label,letterSpacing:1.5,textTransform:"uppercase",marginBottom:3}}>Qty (Lots)</div>
          <div style={{display:"flex",alignItems:"center",border:`1px solid ${C.border}`,borderRadius:3,background:C.white}}>
            <button onPointerDown={()=>setQty(q=>Math.max(1,q-1))} style={{padding:"5px 12px",background:"none",border:"none",cursor:"pointer",fontWeight:700,fontSize:18,color:C.ink,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>−</button>
            <span style={{...M,padding:"0 10px",fontWeight:700,fontSize:14,color:C.ink}}>{qty}</span>
            <button onPointerDown={()=>setQty(q=>q+1)} style={{padding:"5px 12px",background:"none",border:"none",cursor:"pointer",fontWeight:700,fontSize:18,color:C.ink,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>+</button>
          </div>
        </div>
        <div>
          <div style={{...M,fontSize:9,fontWeight:700,color:C.label,letterSpacing:1.5,textTransform:"uppercase",marginBottom:3}}>SL Pts</div>
          <input type="number" value={slPts} onChange={e=>setSlPts(+e.target.value)} style={{...M,width:60,border:`1px solid ${C.border}`,borderRadius:3,padding:"7px 8px",fontSize:13,fontWeight:700,background:C.white,color:C.ink}}/>
        </div>
        <div>
          <div style={{...M,fontSize:9,fontWeight:700,color:C.label,letterSpacing:1.5,textTransform:"uppercase",marginBottom:3}}>Tgt Pts</div>
          <input type="number" value={tgtPts} onChange={e=>setTgtPts(+e.target.value)} style={{...M,width:60,border:`1px solid ${C.border}`,borderRadius:3,padding:"7px 8px",fontSize:13,fontWeight:700,background:C.white,color:C.ink}}/>
        </div>
      </div>

      {/* TRADING PANEL — white bg, clean */}
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",borderBottom:`2px solid ${C.border}`}}>

        {/* CE */}
        <div style={{padding:"14px",borderRight:`1px solid ${C.border}`,background:C.white}}>
          <div style={{...M,fontSize:10,fontWeight:700,color:C.label,letterSpacing:1,textTransform:"uppercase",marginBottom:6}}>{symbol} {ceStrike} CE</div>
          <div style={{...M,fontSize:38,fontWeight:700,color:C.ink,lineHeight:1,marginBottom:2}}>{ceLtp!=null?ceLtp:"—"}</div>
          <div style={{...M,fontSize:10,color:C.label,marginBottom:16}}>Lot: {instr.lot} · {instr.expiry_day}</div>
          <div style={{display:"flex",flexDirection:"column",gap:8}}>
            <button onPointerDown={()=>execute("Sell Call")} style={{padding:"13px",borderRadius:4,border:"none",background:C.red,color:C.white,...S,fontWeight:700,fontSize:14,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>← SELL CALL</button>
            <button onPointerDown={()=>execute("Buy Call")}  style={{padding:"13px",borderRadius:4,border:`2px solid ${C.green}`,background:C.white,color:C.green,...S,fontWeight:700,fontSize:14,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>↑ BUY CALL</button>
          </div>
        </div>

        {/* Center */}
        <div style={{padding:"14px",background:C.white,textAlign:"center",display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"space-between"}}>
          <div>
            <div style={{...M,fontSize:10,color:C.label,letterSpacing:1,textTransform:"uppercase",marginBottom:6}}>{symbol} SPOT</div>
            <div style={{...M,fontSize:30,fontWeight:700,color:C.ink,lineHeight:1}}>{indexLtp?.toLocaleString("en-IN",{maximumFractionDigits:2})||"—"}</div>
            <div style={{...M,fontSize:12,color:(sensex?.change||0)>=0?C.green:C.red,marginTop:4,fontWeight:700}}>
              {(sensex?.change||0)>=0?"+":""}{(sensex?.change||0).toFixed(2)} ({(sensex?.pct||0)>=0?"+":""}{(sensex?.pct||0).toFixed(2)}%)
            </div>
          </div>
          <div style={{width:"100%",background:C.bg,border:`1px solid ${C.border}`,borderRadius:4,padding:"8px 10px",marginTop:12}}>
            <div style={{display:"flex",justifyContent:"space-between",marginBottom:5}}>
              <span style={{...M,fontSize:9,fontWeight:700,color:C.label,letterSpacing:1,textTransform:"uppercase"}}>PRAGNYA</span>
              <span style={{...M,fontSize:11,fontWeight:700,color:dscore>=80?C.green:dscore>=50?C.amber:C.red}}>{dscore}/100</span>
            </div>
            <div style={{background:C.border,borderRadius:100,height:5,overflow:"hidden"}}>
              <div style={{width:`${dscore}%`,height:"100%",background:dscore>=80?C.green:dscore>=50?C.amber:C.red,borderRadius:100}}/>
            </div>
            <div style={{display:"flex",justifyContent:"space-between",marginTop:6,...M,fontSize:10,fontWeight:600,color:C.label}}>
              <span>Trades: {st.trades_taken||0}/{cfg.max_trades_per_day||4}</span>
              <span>SL: {st.sl_hits||0}/{cfg.max_sl_hits||2}</span>
            </div>
          </div>
          <div style={{...M,fontSize:10,color:C.label,marginTop:8,fontWeight:600}}>{expiry}</div>
        </div>

        {/* PE */}
        <div style={{padding:"14px",borderLeft:`1px solid ${C.border}`,background:C.white}}>
          <div style={{...M,fontSize:10,fontWeight:700,color:C.label,letterSpacing:1,textTransform:"uppercase",marginBottom:6,textAlign:"right"}}>{symbol} {peStrike} PE</div>
          <div style={{...M,fontSize:38,fontWeight:700,color:C.ink,lineHeight:1,marginBottom:2,textAlign:"right"}}>{peLtp!=null?peLtp:"—"}</div>
          <div style={{...M,fontSize:10,color:C.label,marginBottom:16,textAlign:"right"}}>VIX: {vix?.toFixed(2)||"—"}</div>
          <div style={{display:"flex",flexDirection:"column",gap:8}}>
            <button onPointerDown={()=>execute("Sell Put")} style={{padding:"13px",borderRadius:4,border:"none",background:C.red,color:C.white,...S,fontWeight:700,fontSize:14,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>SELL PUT →</button>
            <button onPointerDown={()=>execute("Buy Put")}  style={{padding:"13px",borderRadius:4,border:`2px solid ${C.green}`,background:C.white,color:C.green,...S,fontWeight:700,fontSize:14,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>↓ BUY PUT</button>
          </div>
        </div>
      </div>

      {/* BOTTOM */}
      <div style={{padding:"0 12px 40px"}}>
        <div style={{display:"flex",borderBottom:`2px solid ${C.border}`,marginBottom:0}}>
          {[["positions","Positions"],["orders","Orders"],["journal","Trade Book"],["config","Config"]].map(([k,label])=>(
            <button key={k} onPointerDown={()=>setTab(k)} style={{padding:"10px 16px",border:"none",background:"none",borderBottom:tab===k?`3px solid ${C.orange}`:"3px solid transparent",color:tab===k?C.orange:C.label,fontWeight:700,fontSize:13,cursor:"pointer",marginBottom:-2,...S,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>{label}</button>
          ))}
          <div style={{marginLeft:"auto",display:"flex",alignItems:"center",gap:6,padding:"0 4px"}}>
            <span style={{...M,fontSize:11,color:C.label,fontWeight:600}}>MTM:</span>
            <span style={{...M,fontSize:14,fontWeight:700,color:dayPnl>=0?C.green:C.red}}>{dayPnl>=0?"+":""}₹{Math.abs(dayPnl).toLocaleString()}</span>
          </div>
        </div>

        {tab==="positions"&&(
          <div>
            <div style={{display:"grid",gridTemplateColumns:"2fr 1fr 1fr 1fr 1fr 1.5fr",padding:"8px",background:C.bg,borderBottom:`1px solid ${C.border}`}}>
              {["SYMBOL","QTY","AVG","LTP","SL","ACTION"].map(h=><div key={h} style={{...M,fontSize:9,fontWeight:700,color:C.label,letterSpacing:1}}>{h}</div>)}
            </div>
            {positions.length===0
              ?<div style={{padding:"40px",textAlign:"center",color:C.label,fontSize:14,fontWeight:600}}>No open positions</div>
              :positions.map(p=>{
                const lots=JSON.parse(p.extra_json||"{}").lots||1
                const curLtp=p.instrument.includes("CE")?ceLtp:peLtp
                const mtm=curLtp?(p.direction==="SELL"?p.entry-curLtp:curLtp-p.entry)*instr.lot*lots:0
                return(
                  <div key={p.id} style={{display:"grid",gridTemplateColumns:"2fr 1fr 1fr 1fr 1fr 1.5fr",padding:"10px 8px",borderBottom:`1px solid ${C.border}`,alignItems:"center"}}>
                    <div>
                      <div style={{...M,fontWeight:700,fontSize:12,color:C.ink}}>{p.instrument}</div>
                      <div style={{fontSize:11,color:p.direction==="SELL"?C.red:C.green,fontWeight:700}}>{p.direction}</div>
                    </div>
                    <div style={{...M,fontSize:12,fontWeight:600,color:C.ink}}>{lots*instr.lot}</div>
                    <div style={{...M,fontSize:12,fontWeight:600,color:C.ink}}>{p.entry?.toFixed(1)}</div>
                    <div style={{...M,fontSize:12,fontWeight:700,color:mtm>=0?C.green:C.red}}>{curLtp||"—"}</div>
                    <div style={{...M,fontSize:12,fontWeight:600,color:C.red}}>{p.sl?.toFixed(1)}</div>
                    <div style={{display:"flex",gap:4}}>
                      <button onPointerDown={()=>closePos(p.id,curLtp||p.target_price,"TARGET")} style={{padding:"6px 10px",borderRadius:3,border:"none",background:C.green,color:C.white,fontSize:11,fontWeight:700,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Exit</button>
                      <button onPointerDown={()=>closePos(p.id,p.sl,"SL")} style={{padding:"6px 10px",borderRadius:3,border:"none",background:C.red,color:C.white,fontSize:11,fontWeight:700,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>SL</button>
                    </div>
                  </div>
                )
              })
            }
          </div>
        )}

        {tab==="orders"&&<div style={{padding:"40px",textAlign:"center",color:C.label,fontSize:14,fontWeight:600}}>Live order sync with {broker} — Phase 2</div>}

        {tab==="journal"&&(
          <div>
            <div style={{display:"grid",gridTemplateColumns:"2fr 1fr 1fr 1fr 1fr 1fr",padding:"8px",background:C.bg,borderBottom:`1px solid ${C.border}`}}>
              {["SYMBOL","DIR","ENTRY","EXIT","P&L","TIME"].map(h=><div key={h} style={{...M,fontSize:9,fontWeight:700,color:C.label,letterSpacing:1}}>{h}</div>)}
            </div>
            {(pragnya?.trades||[]).filter(t=>t.status==="CLOSED").length===0
              ?<div style={{padding:"40px",textAlign:"center",color:C.label,fontSize:14,fontWeight:600}}>No closed trades today</div>
              :(pragnya?.trades||[]).filter(t=>t.status==="CLOSED").map(t=>(
                <div key={t.id} style={{display:"grid",gridTemplateColumns:"2fr 1fr 1fr 1fr 1fr 1fr",padding:"10px 8px",borderBottom:`1px solid ${C.border}`,alignItems:"center",background:t.pnl>=0?"#F1F8E9":"#FFF3F3"}}>
                  <div style={{...M,fontWeight:700,fontSize:12,color:C.ink}}>{t.instrument}</div>
                  <div style={{fontSize:11,color:t.direction==="SELL"?C.red:C.green,fontWeight:700}}>{t.direction}</div>
                  <div style={{...M,fontSize:12,fontWeight:600,color:C.ink}}>{t.entry?.toFixed(1)}</div>
                  <div style={{...M,fontSize:12,fontWeight:600,color:C.ink}}>{t.exit_price?.toFixed(1)||"—"}</div>
                  <div style={{...M,fontSize:12,fontWeight:700,color:t.pnl>=0?C.green:C.red}}>{t.pnl>=0?"+":""}₹{Math.round(t.pnl||0)}</div>
                  <div style={{...M,fontSize:11,color:C.label,fontWeight:600}}>{t.time?.slice(0,5)}</div>
                </div>
              ))
            }
          </div>
        )}

        {tab==="config"&&(
          <div style={{padding:"16px 0"}}>
            <div style={{...M,fontSize:12,fontWeight:700,color:C.ink,marginBottom:12,letterSpacing:1,textTransform:"uppercase"}}>PRAGNYA Rules</div>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10,marginBottom:16}}>
              {[["Max Trades/Day",cfg.max_trades_per_day],["Loss Limit",`₹${cfg.daily_loss_limit}`],["Daily Target",`₹${cfg.daily_target}`],["Max SL Hits",cfg.max_sl_hits]].map(([l,v])=>(
                <div key={l} style={{background:C.bg,padding:"10px 12px",borderRadius:4,border:`1px solid ${C.border}`}}>
                  <div style={{...M,fontSize:9,color:C.label,letterSpacing:1.5,textTransform:"uppercase",marginBottom:4,fontWeight:700}}>{l}</div>
                  <div style={{...M,fontSize:18,fontWeight:700,color:C.ink}}>{v}</div>
                </div>
              ))}
            </div>
            <div style={{background:C.bg,borderRadius:4,padding:14,border:`1px solid ${C.border}`}}>
              <div style={{fontSize:13,color:C.ink,fontStyle:"italic",lineHeight:1.7}}>"{quote.text}"</div>
              <div style={{...M,fontSize:10,color:C.label,marginTop:8}}>— {quote.src}</div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
