import { useState, useEffect } from "react"

const API = "https://mtutrade.in/api"
const INSTRUMENTS = {
  SENSEX: { lot: 20, step: 100, expiry_day: "Thursday" },
  NIFTY:  { lot: 65, step: 50,  expiry_day: "Tuesday"  },
}
const BROKERS = ["Upstox","Dhan","Kotak Neo","Zerodha","Angel","Fyers"]

async function api(path, opts={}) {
  try {
    const r = await fetch(API+path, { headers:{"Content-Type":"application/json"}, ...opts })
    return r.json()
  } catch(e) { return null }
}

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

  function showToast(msg, ok=true) {
    setToast({msg,ok})
    setTimeout(()=>setToast(null), 3000)
  }

  // ── Market poll (every 5s) ─────────────────────────────────────────────────
  useEffect(()=>{
    if(screen!=="main") return
    const poll = async()=>{
      const r = await api("/vajra/market")
      if(r) setMarket(r)
    }
    poll()
    const t = setInterval(poll, 5000)
    return ()=>clearInterval(t)
  },[screen])

  // ── Load expiries when symbol changes ──────────────────────────────────────
  useEffect(()=>{
    if(screen!=="main") return
    setExpiries([]); setExpiry(""); setStrikes([])
    setCeStrike(""); setPeStrike(""); setCeLtp(null); setPeLtp(null)
    api(`/sutra/expiries?index=${symbol}`).then(r=>{
      if(r?.expiries?.length) {
        setExpiries(r.expiries)
        setExpiry(r.expiries[0])
      }
    })
  },[symbol, screen])

  // ── Load chain when expiry changes ─────────────────────────────────────────
  useEffect(()=>{
    if(!expiry || screen!=="main") return
    setLoading(true)
    api(`/sutra/chain/atm?index=${symbol}&expiry=${expiry}`).then(r=>{
      setLoading(false)
      if(!r?.strikes?.length) return
      setStrikes(r.strikes)
      const atm = r.atm
      // Find best CE (first strike >= ATM with ltp > 0)
      const pool = r.strikes.filter(s=>s.ce.ltp>0 && s.pe.ltp>0)
      const src  = pool.length ? pool : r.strikes
      const ce   = src.find(s=>Number(s.strike)>=atm) || src[Math.floor(src.length/2)]
      const pe   = [...src].reverse().find(s=>Number(s.strike)<=atm) || src[Math.floor(src.length/2)]
      // Set strikes + LTPs + keys immediately from chain data
      setCeStrike(String(ce.strike)); setCeLtp(ce.ce.ltp); setCeKey(ce.ce.key)
      setPeStrike(String(pe.strike)); setPeLtp(pe.pe.ltp); setPeKey(pe.pe.key)
    })
  },[expiry, symbol, screen])

  // ── LTP refresh every 2s using fast /sutra/ltp endpoint ───────────────────
  useEffect(()=>{
    if(!ceKey || !peKey || screen!=="main") return
    const poll = async()=>{
      const r = await api(`/sutra/ltp?ce_key=${encodeURIComponent(ceKey)}&pe_key=${encodeURIComponent(peKey)}`)
      if(!r) return
      const vals = Object.values(r)
      const keys = Object.keys(r)
      keys.forEach((k,i)=>{ if(k.includes("CE")) setCeLtp(vals[i]); if(k.includes("PE")) setPeLtp(vals[i]) })
    }
    const t = setInterval(poll, 2000)
    return ()=>clearInterval(t)
  },[ceKey, peKey, screen])

  // ── PRAGNYA poll (every 10s) ───────────────────────────────────────────────
  useEffect(()=>{
    if(screen!=="main") return
    const poll = async()=>{
      const r = await api("/vajra/state")
      if(r?.state) setPragnya(r)
      if(r?.trades) setPositions(r.trades.filter(t=>t.status==="OPEN"))
    }
    poll()
    const t = setInterval(poll, 10000)
    return ()=>clearInterval(t)
  },[screen])

  function selectBroker(b) {
    setBroker(b); localStorage.setItem("mtu_broker",b); setScreen("main")
  }

  function onCeStrikeChange(val) {
    setCeStrike(val)
    const row = strikes.find(s=>String(s.strike)===val)
    if(row) { setCeLtp(row.ce.ltp); setCeKey(row.ce.key) }
  }

  function onPeStrikeChange(val) {
    setPeStrike(val)
    const row = strikes.find(s=>String(s.strike)===val)
    if(row) { setPeLtp(row.pe.ltp); setPeKey(row.pe.key) }
  }

  async function execute(type) {
    const isCall = type.includes("Call")
    const ltp    = isCall ? ceLtp : peLtp
    const strike = isCall ? ceStrike : peStrike
    const action = type.includes("Sell") ? "SELL" : "BUY"
    const optType= isCall ? "CE" : "PE"
    if(!strike) { showToast("Select a strike first", false); return }
    const r = await api("/vajra/trade/open", {
      method:"POST",
      body:JSON.stringify({
        instrument:`${symbol}${strike}${optType}`, direction:action,
        entry:ltp||0, sl:action==="SELL"?(ltp||0)+slPts:(ltp||0)-slPts,
        target:action==="SELL"?(ltp||0)-tgtPts:(ltp||0)+tgtPts,
        lots:qty, strategy:`${action} ${optType}`
      })
    })
    if(r?.status==="ok") {
      showToast(`✓ ${type} @ ₹${ltp} · ${qty}L`)
      const pr = await api("/vajra/state")
      if(pr?.trades) setPositions(pr.trades.filter(t=>t.status==="OPEN"))
      setPragnya(pr)
    } else {
      const msg = r?.detail || "Order failed"
      showToast(msg, false)
      if(msg.toLowerCase().includes("lock")) setGitaMsg(msg)
    }
  }

  async function closePos(id, exitPrice, reason) {
    const r = await api("/vajra/trade/close",{
      method:"POST", body:JSON.stringify({trade_id:id, exit_price:exitPrice||0, exit_reason:reason})
    })
    if(r?.status==="ok") {
      showToast(`Closed: ${r.pnl>=0?"+":""}₹${Math.round(r.pnl||0)}`)
      const pr = await api("/vajra/state")
      if(pr?.trades) setPositions(pr.trades.filter(t=>t.status==="OPEN"))
      setPragnya(pr)
    }
  }

  const st      = pragnya?.state||{}
  const cfg     = pragnya?.cfg||{}
  const quote   = pragnya?.quote||{}
  const dscore  = st.discipline_score||100
  const dayPnl  = st.daily_pnl||0
  const sensex  = market.sensex
  const nifty   = market.nifty
  const vix     = market.vix?.ltp
  const now     = new Date().toLocaleTimeString("en-IN",{hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false})

  const M = { fontFamily:"'IBM Plex Mono',monospace" }
  const S = { fontFamily:"'IBM Plex Sans',sans-serif" }
  const C = { bg:"#F5F4F0",white:"#FFFFFF",ink:"#1A1916",muted:"#9B9689",border:"#E2E0D8",orange:"#E8540A",green:"#1A7F4B",red:"#C0392B",amber:"#B45309" }

  const btn = (label, onClick, bg, disabled=false) => (
    <button onPointerDown={onClick} disabled={disabled} style={{
      display:"block", width:"100%", padding:"13px 0", borderRadius:6, border:"none",
      background:disabled?"#ccc":bg, color:"#fff", ...S, fontWeight:700, fontSize:14,
      cursor:disabled?"not-allowed":"pointer", WebkitTapHighlightColor:"transparent",
      touchAction:"manipulation", opacity:disabled?0.6:1
    }}>{label}</button>
  )

  // ── BROKER SCREEN ──────────────────────────────────────────────────────────
  if(screen==="broker") return (
    <div style={{minHeight:"100vh",background:C.bg,display:"flex",alignItems:"center",justifyContent:"center",padding:20,...S}}>
      <div style={{background:C.white,borderRadius:14,padding:28,width:"100%",maxWidth:360,border:`1px solid ${C.border}`}}>
        <div style={{...M,fontSize:22,fontWeight:700,color:C.ink,marginBottom:4}}>⚡ <span style={{color:C.orange}}>VAJRA</span></div>
        <div style={{...M,fontSize:9,color:C.muted,letterSpacing:2,textTransform:"uppercase",marginBottom:20}}>Options Scalping Terminal</div>
        <div style={{...M,fontSize:10,color:C.muted,marginBottom:10,letterSpacing:1,textTransform:"uppercase"}}>Select Broker</div>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10,marginBottom:20}}>
          {BROKERS.map(b=>(
            <button key={b} onPointerDown={()=>selectBroker(b)} style={{
              padding:"13px 10px",borderRadius:8,border:`2px solid ${broker===b?C.orange:C.border}`,
              background:broker===b?"#FFF1E6":C.white,color:broker===b?C.orange:C.ink,
              ...S,fontWeight:600,fontSize:14,cursor:"pointer",
              WebkitTapHighlightColor:"transparent",touchAction:"manipulation"
            }}>{b}</button>
          ))}
        </div>
        <div style={{background:C.bg,borderRadius:8,padding:14}}>
          <div style={{fontSize:11,color:"#3D3B35",fontStyle:"italic",lineHeight:1.6}}>"{quote.text||"Perform your duty equipoised, abandoning all attachment."}"</div>
          <div style={{...M,fontSize:9,color:C.muted,marginTop:6}}>— {quote.src||"Bhagavad Gita 2.48"}</div>
        </div>
      </div>
    </div>
  )

  // ── GITA OVERLAY ──────────────────────────────────────────────────────────
  if(gitaMsg) return (
    <div style={{position:"fixed",inset:0,background:"rgba(245,244,240,0.97)",zIndex:99999,display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",padding:32,...S}}>
      <div style={{fontSize:48,marginBottom:16}}>🕉️</div>
      <div style={{...M,fontSize:18,fontWeight:700,color:C.red,marginBottom:8}}>PRAGNYA ACTIVATED</div>
      <div style={{fontSize:13,color:C.muted,marginBottom:24,textAlign:"center",maxWidth:300}}>{gitaMsg}</div>
      <div style={{background:C.bg,borderRadius:8,padding:16,maxWidth:340,marginBottom:24}}>
        <div style={{fontSize:12,color:"#3D3B35",fontStyle:"italic",lineHeight:1.6}}>"{quote.text}"</div>
        <div style={{...M,fontSize:9,color:C.muted,marginTop:6}}>— {quote.src}</div>
      </div>
      <button onPointerDown={()=>setGitaMsg(null)} style={{padding:"10px 28px",borderRadius:8,border:`1.5px solid ${C.border}`,background:C.white,color:C.muted,...S,fontWeight:600,fontSize:13,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Dismiss</button>
    </div>
  )

  // ── MAIN TERMINAL ──────────────────────────────────────────────────────────
  return (
    <div style={{minHeight:"100vh",background:C.bg,...S,paddingBottom:64}}>

      {/* Toast */}
      {toast&&<div style={{position:"fixed",top:0,left:0,right:0,zIndex:9999,background:toast.ok?"#D1FAE5":"#FEE2E2",padding:"10px 16px",fontSize:13,fontWeight:600,color:toast.ok?"#065F46":"#991B1B",textAlign:"center"}}>{toast.msg}</div>}

      {/* Top bar */}
      <div style={{background:C.white,borderBottom:`1px solid ${C.border}`,padding:"8px 12px",display:"flex",alignItems:"center",justifyContent:"space-between",flexWrap:"wrap",gap:8}}>
        <div style={{display:"flex",alignItems:"center",gap:10}}>
          <div style={{...M,fontSize:16,fontWeight:700,color:C.ink}}>⚡ <span style={{color:C.orange}}>VAJRA</span></div>
          <button onPointerDown={()=>setScreen("broker")} style={{fontSize:11,fontWeight:600,padding:"4px 10px",borderRadius:20,border:`1.5px solid ${C.orange}`,background:"#FFF1E6",color:C.orange,cursor:"pointer",...S,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>🔗 {broker}</button>
        </div>
        <div style={{display:"flex",gap:16,alignItems:"center"}}>
          {[["SENSEX",sensex?.ltp,sensex?.change,sensex?.pct],["NIFTY",nifty?.ltp,0,0],["VIX",vix,0,0]].map(([name,ltp,chg,pct])=>(
            <div key={name} style={{textAlign:"center"}}>
              <div style={{...M,fontSize:8,color:C.muted,letterSpacing:1,textTransform:"uppercase"}}>{name}</div>
              <div style={{...M,fontSize:13,fontWeight:700,color:chg>0?C.green:chg<0?C.red:C.ink}}>{ltp?ltp.toLocaleString("en-IN",{maximumFractionDigits:2}):"—"}</div>
              {chg!==0&&<div style={{...M,fontSize:9,color:chg>=0?C.green:C.red}}>{chg>=0?"+":""}{chg?.toFixed(1)} ({pct>=0?"+":""}{pct?.toFixed(2)}%)</div>}
            </div>
          ))}
        </div>
        <div style={{display:"flex",gap:14,alignItems:"center"}}>
          <div style={{textAlign:"right"}}><div style={{...M,fontSize:8,color:C.muted,letterSpacing:1}}>DAY P&L</div><div style={{...M,fontSize:13,fontWeight:700,color:dayPnl>=0?C.green:C.red}}>{dayPnl>=0?"+":""}₹{Math.abs(dayPnl).toLocaleString()}</div></div>
          <div style={{textAlign:"right"}}><div style={{...M,fontSize:8,color:C.muted,letterSpacing:1}}>PRAGNYA</div><div style={{...M,fontSize:13,fontWeight:700,color:dscore>=80?C.green:dscore>=50?C.amber:C.red}}>{dscore}/100</div></div>
          <div style={{...M,fontSize:11,color:C.muted}}>{now}</div>
        </div>
      </div>

      {/* Instrument row */}
      <div style={{background:C.white,borderBottom:`1px solid ${C.border}`,padding:"8px 12px",display:"flex",flexWrap:"wrap",gap:10,alignItems:"flex-end"}}>
        {[
          ["Symbol", <select value={symbol} onChange={e=>setSymbol(e.target.value)} style={{...M,fontSize:12,fontWeight:600,border:`1.5px solid ${C.border}`,borderRadius:6,padding:"6px 8px",background:C.white,cursor:"pointer"}}>{Object.keys(INSTRUMENTS).map(k=><option key={k}>{k}</option>)}</select>],
          ["Expiry", <select value={expiry} onChange={e=>setExpiry(e.target.value)} style={{...M,fontSize:12,fontWeight:600,border:`1.5px solid ${C.border}`,borderRadius:6,padding:"6px 8px",background:C.white,cursor:"pointer"}}>{expiries.map(e=><option key={e}>{e}</option>)}</select>],
          ["CE Strike", <select value={ceStrike} onChange={e=>onCeStrikeChange(e.target.value)} style={{...M,fontSize:12,fontWeight:600,border:`1.5px solid ${C.border}`,borderRadius:6,padding:"6px 8px",background:C.white,cursor:"pointer"}}>{strikes.map(s=><option key={s.strike} value={String(s.strike)}>{s.strike}{s.is_atm?" ◀":""}</option>)}</select>],
          ["PE Strike", <select value={peStrike} onChange={e=>onPeStrikeChange(e.target.value)} style={{...M,fontSize:12,fontWeight:600,border:`1.5px solid ${C.border}`,borderRadius:6,padding:"6px 8px",background:C.white,cursor:"pointer"}}>{strikes.map(s=><option key={s.strike} value={String(s.strike)}>{s.strike}{s.is_atm?" ◀":""}</option>)}</select>],
        ].map(([label,el])=>(
          <div key={label}>
            <div style={{...M,fontSize:8,color:C.muted,letterSpacing:1.5,textTransform:"uppercase",marginBottom:3}}>{label}</div>
            {el}
          </div>
        ))}
        <div>
          <div style={{...M,fontSize:8,color:C.muted,letterSpacing:1.5,textTransform:"uppercase",marginBottom:3}}>Qty (Lots)</div>
          <div style={{display:"flex",alignItems:"center",border:`1.5px solid ${C.border}`,borderRadius:6,background:C.white,overflow:"hidden"}}>
            <button onPointerDown={()=>setQty(q=>Math.max(1,q-1))} style={{padding:"6px 10px",background:"none",border:"none",cursor:"pointer",fontWeight:700,fontSize:16,color:C.ink,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>−</button>
            <span style={{...M,padding:"0 8px",fontWeight:700,fontSize:13}}>{qty}</span>
            <button onPointerDown={()=>setQty(q=>q+1)} style={{padding:"6px 10px",background:"none",border:"none",cursor:"pointer",fontWeight:700,fontSize:16,color:C.ink,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>+</button>
          </div>
        </div>
        <div>
          <div style={{...M,fontSize:8,color:C.muted,letterSpacing:1.5,textTransform:"uppercase",marginBottom:3}}>SL Pts</div>
          <input type="number" value={slPts} onChange={e=>setSlPts(+e.target.value)} style={{...M,width:60,border:`1.5px solid ${C.border}`,borderRadius:6,padding:"6px 8px",fontSize:12,background:C.white,color:C.ink}}/>
        </div>
        <div>
          <div style={{...M,fontSize:8,color:C.muted,letterSpacing:1.5,textTransform:"uppercase",marginBottom:3}}>Tgt Pts</div>
          <input type="number" value={tgtPts} onChange={e=>setTgtPts(+e.target.value)} style={{...M,width:60,border:`1.5px solid ${C.border}`,borderRadius:6,padding:"6px 8px",fontSize:12,background:C.white,color:C.ink}}/>
        </div>
      </div>

      {/* Loading bar */}
      {loading&&<div style={{height:3,background:`linear-gradient(90deg,${C.orange},transparent)`,animation:"none"}}/>}

      {/* Trading panel */}
      <div style={{display:"grid",gridTemplateColumns:"1fr 1.1fr 1fr",margin:"10px 12px",gap:0}}>
        {/* CE */}
        <div style={{background:C.white,border:`1px solid ${C.border}`,borderRadius:"10px 0 0 10px",padding:14,borderRight:"none"}}>
          <div style={{...M,fontSize:9,color:C.muted,letterSpacing:1.5,textTransform:"uppercase",marginBottom:6}}>{symbol} {ceStrike} CE</div>
          <div style={{...M,fontSize:32,fontWeight:700,color:C.ink,lineHeight:1,marginBottom:4}}>{ceLtp!=null?ceLtp:"—"}</div>
          <div style={{...M,fontSize:9,color:C.muted,marginBottom:16}}>Lot: {instr.lot}</div>
          <div style={{display:"flex",flexDirection:"column",gap:8}}>
            {btn("← Sell Call", ()=>execute("Sell Call"), C.red)}
            {btn("↑ Buy Call",  ()=>execute("Buy Call"),  C.green)}
          </div>
        </div>

        {/* Center */}
        <div style={{background:C.white,border:`1px solid ${C.border}`,padding:12,textAlign:"center",display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"space-between"}}>
          <div>
            <div style={{...M,fontSize:9,color:C.muted,letterSpacing:1,textTransform:"uppercase",marginBottom:4}}>{symbol}</div>
            <div style={{...M,fontSize:26,fontWeight:700,color:C.ink,lineHeight:1}}>
              {(symbol==="SENSEX"?sensex?.ltp:nifty?.ltp)?.toLocaleString("en-IN",{maximumFractionDigits:2})||"—"}
            </div>
            <div style={{...M,fontSize:11,color:(sensex?.change||0)>=0?C.green:C.red,marginTop:4,fontWeight:600}}>
              {(sensex?.change||0)>=0?"+":""}{(sensex?.change||0).toFixed(2)} ({(sensex?.pct||0)>=0?"+":""}{(sensex?.pct||0).toFixed(2)}%)
            </div>
          </div>
          <div style={{width:"100%",background:C.bg,borderRadius:8,padding:"8px 10px",marginTop:10}}>
            <div style={{display:"flex",justifyContent:"space-between",marginBottom:4}}>
              <span style={{...M,fontSize:8,color:C.muted,letterSpacing:1,textTransform:"uppercase"}}>PRAGNYA</span>
              <span style={{...M,fontSize:10,fontWeight:700,color:dscore>=80?C.green:dscore>=50?C.amber:C.red}}>{dscore}/100</span>
            </div>
            <div style={{background:"#ECEAE4",borderRadius:100,height:4,overflow:"hidden"}}>
              <div style={{width:`${Math.min(100,100-dscore)}%`,height:"100%",background:dscore>=80?C.green:dscore>=50?C.amber:C.red,borderRadius:100}}/>
            </div>
            <div style={{display:"flex",justifyContent:"space-between",marginTop:6,...M,fontSize:9,color:C.muted}}>
              <span>Trades: {st.trades_taken||0}/{cfg.max_trades_per_day||4}</span>
              <span>SL: {st.sl_hits||0}/{cfg.max_sl_hits||2}</span>
            </div>
          </div>
          <div style={{...M,fontSize:9,color:C.muted,marginTop:8}}>{expiry} · {instr.expiry_day}</div>
        </div>

        {/* PE */}
        <div style={{background:C.white,border:`1px solid ${C.border}`,borderRadius:"0 10px 10px 0",padding:14,borderLeft:"none"}}>
          <div style={{...M,fontSize:9,color:C.muted,letterSpacing:1.5,textTransform:"uppercase",marginBottom:6,textAlign:"right"}}>{symbol} {peStrike} PE</div>
          <div style={{...M,fontSize:32,fontWeight:700,color:C.ink,lineHeight:1,marginBottom:4,textAlign:"right"}}>{peLtp!=null?peLtp:"—"}</div>
          <div style={{...M,fontSize:9,color:C.muted,marginBottom:16,textAlign:"right"}}>VIX: {vix?.toFixed(2)||"—"}</div>
          <div style={{display:"flex",flexDirection:"column",gap:8}}>
            {btn("Sell Put →", ()=>execute("Sell Put"), C.red)}
            {btn("↓ Buy Put",  ()=>execute("Buy Put"),  C.green)}
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div style={{margin:"0 12px"}}>
        <div style={{display:"flex",borderBottom:`2px solid ${C.border}`,marginBottom:10}}>
          {[["positions","Positions"],["orders","Orders"],["journal","Trade Book"],["config","Config"]].map(([k,label])=>(
            <button key={k} onPointerDown={()=>setTab(k)} style={{padding:"8px 14px",border:"none",background:"none",borderBottom:tab===k?`2px solid ${C.orange}`:"2px solid transparent",color:tab===k?C.orange:C.muted,fontWeight:600,fontSize:12,cursor:"pointer",marginBottom:-2,...S,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>{label}</button>
          ))}
          <div style={{marginLeft:"auto",display:"flex",alignItems:"center",gap:6,paddingRight:4}}>
            <span style={{...M,fontSize:10,color:C.muted}}>MTM:</span>
            <span style={{...M,fontSize:13,fontWeight:700,color:dayPnl>=0?C.green:C.red}}>{dayPnl>=0?"+":""}₹{Math.abs(dayPnl).toLocaleString()}</span>
          </div>
        </div>

        {tab==="positions"&&(
          <div style={{background:C.white,border:`1px solid ${C.border}`,borderRadius:10,overflow:"hidden"}}>
            <div style={{display:"grid",gridTemplateColumns:"2fr 1fr 1fr 1fr 1fr 1.5fr",padding:"8px 12px",borderBottom:`1px solid ${C.border}`,background:C.bg}}>
              {["Symbol","Qty","Avg","LTP","SL","Action"].map(h=><div key={h} style={{...M,fontSize:9,fontWeight:600,color:C.muted,letterSpacing:1,textTransform:"uppercase"}}>{h}</div>)}
            </div>
            {positions.length===0
              ?<div style={{padding:32,textAlign:"center",color:C.muted,fontSize:13}}>No open positions</div>
              :positions.map(p=>{
                const lots=JSON.parse(p.extra_json||"{}").lots||1
                const curLtp=p.instrument.includes("CE")?ceLtp:peLtp
                return(
                  <div key={p.id} style={{display:"grid",gridTemplateColumns:"2fr 1fr 1fr 1fr 1fr 1.5fr",padding:"10px 12px",borderBottom:`1px solid ${C.border}`,alignItems:"center"}}>
                    <div><div style={{...M,fontWeight:700,fontSize:11,color:C.ink}}>{p.instrument}</div><div style={{fontSize:10,color:p.direction==="SELL"?C.red:C.green,fontWeight:600}}>{p.direction}</div></div>
                    <div style={{...M,fontSize:11}}>{lots*instr.lot}</div>
                    <div style={{...M,fontSize:11}}>{p.entry?.toFixed(1)}</div>
                    <div style={{...M,fontSize:11,fontWeight:700}}>{curLtp||"—"}</div>
                    <div style={{...M,fontSize:11,color:C.red}}>{p.sl?.toFixed(1)}</div>
                    <div style={{display:"flex",gap:4}}>
                      <button onPointerDown={()=>closePos(p.id,curLtp||p.target_price,"TARGET")} style={{padding:"5px 8px",borderRadius:5,border:"none",background:C.green,color:"#fff",fontSize:11,fontWeight:700,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Exit</button>
                      <button onPointerDown={()=>closePos(p.id,p.sl,"SL")} style={{padding:"5px 8px",borderRadius:5,border:"none",background:C.red,color:"#fff",fontSize:11,fontWeight:700,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>SL</button>
                    </div>
                  </div>
                )
              })
            }
          </div>
        )}

        {tab==="orders"&&<div style={{background:C.white,border:`1px solid ${C.border}`,borderRadius:10,padding:32,textAlign:"center",color:C.muted,fontSize:13}}>Live order sync with {broker} — Phase 2</div>}

        {tab==="journal"&&(
          <div style={{background:C.white,border:`1px solid ${C.border}`,borderRadius:10,overflow:"hidden"}}>
            <div style={{display:"grid",gridTemplateColumns:"2fr 1fr 1fr 1fr 1fr 1fr",padding:"8px 12px",borderBottom:`1px solid ${C.border}`,background:C.bg}}>
              {["Symbol","Dir","Entry","Exit","P&L","Time"].map(h=><div key={h} style={{...M,fontSize:9,fontWeight:600,color:C.muted,letterSpacing:1,textTransform:"uppercase"}}>{h}</div>)}
            </div>
            {(pragnya?.trades||[]).filter(t=>t.status==="CLOSED").length===0
              ?<div style={{padding:32,textAlign:"center",color:C.muted,fontSize:13}}>No closed trades today</div>
              :(pragnya?.trades||[]).filter(t=>t.status==="CLOSED").map(t=>(
                <div key={t.id} style={{display:"grid",gridTemplateColumns:"2fr 1fr 1fr 1fr 1fr 1fr",padding:"10px 12px",borderBottom:`1px solid ${C.border}`,alignItems:"center"}}>
                  <div style={{...M,fontWeight:700,fontSize:11}}>{t.instrument}</div>
                  <div style={{fontSize:10,color:t.direction==="SELL"?C.red:C.green,fontWeight:700}}>{t.direction}</div>
                  <div style={{...M,fontSize:11}}>{t.entry?.toFixed(1)}</div>
                  <div style={{...M,fontSize:11}}>{t.exit_price?.toFixed(1)||"—"}</div>
                  <div style={{...M,fontSize:11,fontWeight:700,color:t.pnl>=0?C.green:C.red}}>{t.pnl>=0?"+":""}₹{Math.round(t.pnl||0)}</div>
                  <div style={{...M,fontSize:10,color:C.muted}}>{t.time?.slice(0,5)}</div>
                </div>
              ))
            }
          </div>
        )}

        {tab==="config"&&(
          <div style={{background:C.white,border:`1px solid ${C.border}`,borderRadius:10,padding:16}}>
            <div style={{...M,fontSize:11,fontWeight:700,color:C.ink,marginBottom:12,letterSpacing:1,textTransform:"uppercase"}}>PRAGNYA Rules</div>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,marginBottom:16}}>
              {[["Max Trades/Day",cfg.max_trades_per_day],["Loss Limit",`₹${cfg.daily_loss_limit}`],["Daily Target",`₹${cfg.daily_target}`],["Max SL Hits",cfg.max_sl_hits]].map(([l,v])=>(
                <div key={l}><div style={{...M,fontSize:8,color:C.muted,letterSpacing:1.5,textTransform:"uppercase",marginBottom:3}}>{l}</div><div style={{...M,fontSize:16,fontWeight:700,color:C.ink}}>{v}</div></div>
              ))}
            </div>
            <div style={{background:C.bg,borderRadius:8,padding:14}}>
              <div style={{fontSize:12,color:"#3D3B35",fontStyle:"italic",lineHeight:1.6}}>"{quote.text}"</div>
              <div style={{...M,fontSize:9,color:C.muted,marginTop:6}}>— {quote.src}</div>
            </div>
          </div>
        )}
      </div>

      {/* Bottom nav */}
      <nav style={{position:"fixed",bottom:0,left:0,right:0,background:C.white,borderTop:`1px solid ${C.border}`,display:"flex",zIndex:9999}}>
        {[["positions","📋","Positions"],["orders","📒","Orders"],["journal","📊","Trades"],["config","⚙️","Config"]].map(([k,icon,label])=>(
          <button key={k} onPointerDown={()=>setTab(k)} style={{flex:1,height:52,border:"none",background:"none",cursor:"pointer",borderTop:tab===k?`2px solid ${C.orange}`:"2px solid transparent",color:tab===k?C.orange:C.muted,...M,fontSize:8,fontWeight:600,letterSpacing:1,textTransform:"uppercase",display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",gap:2,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
            <span style={{fontSize:15}}>{icon}</span>{label}
          </button>
        ))}
      </nav>
    </div>
  )
}
