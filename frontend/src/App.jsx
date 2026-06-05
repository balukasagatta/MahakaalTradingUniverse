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

const T = {
  canvas:"#FAF9F7", surface:"#FFFFFF", raised:"#F3F1EE",
  line:"#E8E4DE", subtle:"#7A7670", body:"#3D3A35", ink:"#1A1814",
  brand:"#C8590A", sell:"#C62828", buy:"#2E7D32",
  up:"#2E7D32", down:"#C62828", warn:"#E65100",
}
const inter = "'Inter',system-ui,sans-serif"
const mono  = "'JetBrains Mono','Fira Mono',monospace"

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
  const [isMobile,  setIsMobile]  = useState(window.innerWidth < 768)

  const instr = INSTRUMENTS[symbol] || INSTRUMENTS.SENSEX

  useEffect(()=>{
    const link = document.createElement("link")
    link.href = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600;700&display=swap"
    link.rel = "stylesheet"
    document.head.appendChild(link)
    const meta = document.querySelector("meta[name=viewport]")
    if(meta) meta.content = "width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no"
    const onResize = () => setIsMobile(window.innerWidth < 768)
    window.addEventListener("resize", onResize)
    return () => window.removeEventListener("resize", onResize)
  },[])

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
  function onCeChange(val){ setCeStrike(val); const r=strikes.find(s=>String(s.strike)===val); if(r){ setCeLtp(r.ce.ltp); setCeKey(r.ce.key) } }
  function onPeChange(val){ setPeStrike(val); const r=strikes.find(s=>String(s.strike)===val); if(r){ setPeLtp(r.pe.ltp); setPeKey(r.pe.key) } }

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
      const msg=r?.detail||"Order failed"; showToast(msg,false)
      if(msg.toLowerCase().includes("lock")) setGitaMsg(msg)
    }
  }

  async function closePos(id,ep,reason){
    const r=await api("/vajra/trade/close",{method:"POST",body:JSON.stringify({trade_id:id,exit_price:ep||0,exit_reason:reason})})
    if(r?.status==="ok"){
      showToast(`Closed · ${r.pnl>=0?"+":""}₹${Math.round(r.pnl||0)}`)
      const pr=await api("/vajra/state")
      if(pr?.trades) setPositions(pr.trades.filter(t=>t.status==="OPEN"))
      setPragnya(pr)
    }
  }

  async function closeAll(){ for(const p of positions){ const cl=p.instrument.includes("CE")?ceLtp:peLtp; await closePos(p.id,cl||p.sl,"MANUAL") } }

  const st=pragnya?.state||{}; const cfg=pragnya?.cfg||{}; const quote=pragnya?.quote||{}
  const dscore=st.discipline_score||100; const dayPnl=st.daily_pnl||0
  const sensex=market.sensex; const nifty=market.nifty; const vix=market.vix?.ltp
  const indexLtp=symbol==="SENSEX"?sensex?.ltp:nifty?.ltp
  const indexChg=symbol==="SENSEX"?sensex?.change||0:0
  const indexPct=symbol==="SENSEX"?sensex?.pct||0:0
  const now=new Date().toLocaleTimeString("en-IN",{hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false})

  const selStyle = {fontFamily:mono,fontSize:12,fontWeight:600,color:T.ink,border:`1px solid ${T.line}`,borderRadius:6,padding:"5px 6px",background:T.surface,cursor:"pointer",height:32,outline:"none"}
  const lbl = t => <div style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:3}}>{t}</div>

  const ExecBtn = ({text,sub,onClick,color}) => (
    <button onPointerDown={onClick} style={{display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",width:"100%",minHeight:isMobile?56:52,gap:1,borderRadius:8,border:"none",background:color,color:"#fff",fontFamily:inter,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation",boxShadow:`0 2px 4px ${color}44`}}>
      <span style={{fontWeight:700,fontSize:isMobile?15:14}}>{text}</span>
      {sub&&<span style={{fontWeight:500,fontSize:10,opacity:0.85}}>{sub}</span>}
    </button>
  )

  // ── BROKER ────────────────────────────────────────────────────────────────
  if(screen==="broker") return (
    <div style={{minHeight:"100vh",background:T.canvas,display:"flex",alignItems:"center",justifyContent:"center",padding:20,fontFamily:inter}}>
      <div style={{width:"100%",maxWidth:320,background:T.surface,borderRadius:16,padding:24,boxShadow:"0 4px 24px rgba(0,0,0,0.08)"}}>
        <div style={{fontFamily:mono,fontSize:20,fontWeight:700,color:T.ink,marginBottom:2}}>⚡ <span style={{color:T.brand}}>VAJRA</span></div>
        <div style={{fontSize:11,color:T.subtle,marginBottom:24}}>Options Scalping Terminal</div>
        <div style={{fontSize:11,fontWeight:600,color:T.body,marginBottom:8,textTransform:"uppercase",letterSpacing:"0.5px"}}>Select Broker</div>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,marginBottom:20}}>
          {BROKERS.map(b=>(
            <button key={b} onPointerDown={()=>selectBroker(b)} style={{minHeight:44,padding:"8px",borderRadius:8,border:`1.5px solid ${broker===b?T.brand:T.line}`,background:broker===b?"#FFF3E0":T.surface,color:broker===b?T.brand:T.body,fontFamily:inter,fontWeight:600,fontSize:13,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>{b}</button>
          ))}
        </div>
        <div style={{borderTop:`1px solid ${T.line}`,paddingTop:14}}>
          <div style={{fontSize:12,color:T.body,fontStyle:"italic",lineHeight:1.8,marginBottom:6}}>"{quote.text||"Perform your duty equipoised, abandoning all attachment."}"</div>
          <div style={{fontFamily:mono,fontSize:10,color:T.subtle}}>— {quote.src||"Bhagavad Gita 2.48"}</div>
        </div>
      </div>
    </div>
  )

  // ── GITA ──────────────────────────────────────────────────────────────────
  if(gitaMsg) return (
    <div style={{position:"fixed",inset:0,background:"rgba(250,249,247,0.96)",zIndex:99999,display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",padding:28,fontFamily:inter}}>
      <div style={{fontSize:48,marginBottom:14}}>🕉️</div>
      <div style={{fontFamily:mono,fontSize:17,fontWeight:700,color:T.sell,marginBottom:8}}>PRAGNYA ACTIVATED</div>
      <div style={{fontSize:13,color:T.body,marginBottom:20,textAlign:"center",maxWidth:280,lineHeight:1.7}}>{gitaMsg}</div>
      <div style={{border:`1px solid ${T.line}`,borderRadius:12,padding:16,maxWidth:320,marginBottom:20,background:T.surface,width:"100%"}}>
        <div style={{fontSize:12,color:T.body,fontStyle:"italic",lineHeight:1.8}}>"{quote.text}"</div>
        <div style={{fontFamily:mono,fontSize:10,color:T.subtle,marginTop:6}}>— {quote.src}</div>
      </div>
      <button onPointerDown={()=>setGitaMsg(null)} style={{minHeight:44,padding:"10px 28px",borderRadius:8,border:`1px solid ${T.line}`,background:T.surface,color:T.body,fontFamily:inter,fontWeight:600,fontSize:14,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Dismiss</button>
    </div>
  )

  // ── MAIN ──────────────────────────────────────────────────────────────────
  return (
    <div style={{minHeight:"100vh",background:T.canvas,fontFamily:inter}}>
      {toast&&<div style={{position:"fixed",top:0,left:0,right:0,zIndex:9999,background:toast.ok?T.buy:T.sell,padding:"11px 16px",fontSize:13,fontWeight:600,color:"#fff",textAlign:"center"}}>{toast.msg}</div>}
      {loading&&<div style={{position:"fixed",top:0,left:0,right:0,zIndex:9998,height:2,background:T.brand}}/>}

      {/* ── HEADER ── */}
      <div style={{background:T.surface,borderBottom:`1px solid ${T.line}`,padding:"0 12px",height:44,display:"flex",alignItems:"center",gap:8,position:"sticky",top:0,zIndex:100}}>
        <div style={{fontFamily:mono,fontSize:15,fontWeight:700,color:T.ink,flexShrink:0}}>⚡ <span style={{color:T.brand}}>VAJRA</span></div>
        <div style={{width:1,height:18,background:T.line,flexShrink:0}}/>
        <button onPointerDown={()=>setScreen("broker")} style={{fontFamily:inter,fontSize:11,fontWeight:600,color:T.body,background:T.raised,border:`1px solid ${T.line}`,borderRadius:5,padding:"3px 8px",cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation",flexShrink:0}}>
          {broker} ▾
        </button>
        <div style={{width:1,height:18,background:T.line,flexShrink:0}}/>
        {/* Prices — scrollable */}
        <div style={{display:"flex",gap:12,alignItems:"center",overflowX:"auto",flex:1,scrollbarWidth:"none",WebkitOverflowScrolling:"touch"}}>
          <style>{`.no-scroll::-webkit-scrollbar{display:none}`}</style>
          {[
            {n:"SENSEX",ltp:sensex?.ltp,chg:sensex?.change||0,pct:sensex?.pct||0},
            {n:"NIFTY", ltp:nifty?.ltp,chg:0,pct:0},
            {n:"VIX",   ltp:vix,chg:0,pct:0},
          ].map(({n,ltp,chg,pct})=>(
            <div key={n} style={{display:"flex",alignItems:"baseline",gap:4,flexShrink:0}}>
              <span style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1px"}}>{n}</span>
              <span style={{fontFamily:mono,fontSize:13,fontWeight:700,color:chg>0?T.up:chg<0?T.down:T.ink}}>
                {ltp?ltp.toLocaleString("en-IN",{maximumFractionDigits:2}):"—"}
              </span>
              {chg!==0&&<span style={{fontFamily:mono,fontSize:9,color:chg>=0?T.up:T.down}}>{chg>=0?"+":""}{chg.toFixed(1)}({pct>=0?"+":""}{pct.toFixed(2)}%)</span>}
            </div>
          ))}
        </div>
        <div style={{width:1,height:18,background:T.line,flexShrink:0}}/>
        <div style={{display:"flex",gap:10,flexShrink:0}}>
          <div style={{textAlign:"right"}}>
            <div style={{fontFamily:mono,fontSize:7,color:T.subtle,letterSpacing:"1px"}}>P&L</div>
            <div style={{fontFamily:mono,fontSize:12,fontWeight:700,color:dayPnl>=0?T.up:T.down}}>{dayPnl>=0?"+":""}₹{Math.abs(dayPnl).toLocaleString()}</div>
          </div>
          <div style={{textAlign:"right"}}>
            <div style={{fontFamily:mono,fontSize:7,color:T.subtle,letterSpacing:"1px"}}>PRAGNYA</div>
            <div style={{fontFamily:mono,fontSize:12,fontWeight:700,color:dscore>=80?T.up:dscore>=50?T.warn:T.down}}>{dscore}/100</div>
          </div>
        </div>
      </div>

      {/* ── CONTROLS — horizontal scroll ── */}
      <div style={{background:T.raised,borderBottom:`1px solid ${T.line}`,overflowX:"auto",scrollbarWidth:"none",WebkitOverflowScrolling:"touch"}}>
        <div style={{display:"flex",gap:8,alignItems:"flex-end",padding:"6px 12px",minWidth:"max-content"}}>
          <div>{lbl("Symbol")}<select value={symbol} onChange={e=>setSymbol(e.target.value)} style={{...selStyle,minWidth:80}}>{Object.keys(INSTRUMENTS).map(k=><option key={k}>{k}</option>)}</select></div>
          <div>{lbl("Expiry")}<select value={expiry} onChange={e=>setExpiry(e.target.value)} style={{...selStyle,minWidth:105}}>{expiries.map(e=><option key={e}>{e}</option>)}</select></div>
          <div>{lbl("CE Strike")}<select value={ceStrike} onChange={e=>onCeChange(e.target.value)} style={{...selStyle,minWidth:105}}>{strikes.map(s=><option key={s.strike} value={String(s.strike)}>{s.strike}{s.is_atm?" ◀":""}</option>)}</select></div>
          <div>{lbl("PE Strike")}<select value={peStrike} onChange={e=>onPeChange(e.target.value)} style={{...selStyle,minWidth:105}}>{strikes.map(s=><option key={s.strike} value={String(s.strike)}>{s.strike}{s.is_atm?" ◀":""}</option>)}</select></div>
          <div>
            {lbl("Qty")}
            <div style={{display:"flex",alignItems:"center",background:T.surface,border:`1px solid ${T.line}`,borderRadius:6,height:32}}>
              <button onPointerDown={()=>setQty(q=>Math.max(1,q-1))} style={{width:28,height:32,background:"none",border:"none",cursor:"pointer",fontWeight:700,fontSize:16,color:T.ink,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>−</button>
              <span style={{fontFamily:mono,minWidth:24,textAlign:"center",fontWeight:700,fontSize:13,color:T.ink}}>{qty}</span>
              <button onPointerDown={()=>setQty(q=>q+1)} style={{width:28,height:32,background:"none",border:"none",cursor:"pointer",fontWeight:700,fontSize:16,color:T.ink,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>+</button>
            </div>
          </div>
          <div>{lbl("SL Pts")}<input type="number" value={slPts} onChange={e=>setSlPts(+e.target.value)} style={{...selStyle,width:52}}/></div>
          <div>{lbl("Tgt Pts")}<input type="number" value={tgtPts} onChange={e=>setTgtPts(+e.target.value)} style={{...selStyle,width:52}}/></div>
        </div>
      </div>

      {/* ── TRADING PANEL — mobile: stacked, desktop: 3 col ── */}
      {isMobile ? (
        /* MOBILE LAYOUT */
        <div style={{background:T.surface,borderBottom:`1px solid ${T.line}`}}>
          {/* Index spot — full width */}
          <div style={{padding:"10px 12px",borderBottom:`1px solid ${T.line}`,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
            <div>
              <div style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase",marginBottom:2}}>{symbol} Spot</div>
              <div style={{fontFamily:mono,fontSize:28,fontWeight:700,color:T.ink,lineHeight:1,letterSpacing:"-0.5px"}}>{indexLtp?.toLocaleString("en-IN",{maximumFractionDigits:2})||"—"}</div>
              <div style={{fontFamily:mono,fontSize:11,fontWeight:600,color:indexChg>=0?T.up:T.down,marginTop:2}}>{indexChg>=0?"+":""}{indexChg.toFixed(2)} ({indexPct>=0?"+":""}{indexPct.toFixed(2)}%)</div>
            </div>
            <div style={{textAlign:"right"}}>
              <div style={{fontFamily:mono,fontSize:8,color:T.subtle,letterSpacing:"1px",marginBottom:4}}>VIX {vix?.toFixed(2)||"—"}</div>
              <div style={{padding:"6px 10px",border:`1px solid ${T.line}`,borderRadius:6,background:T.raised}}>
                <div style={{fontFamily:mono,fontSize:7,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase",marginBottom:3}}>Pragnya</div>
                <div style={{fontFamily:mono,fontSize:12,fontWeight:700,color:dscore>=80?T.up:dscore>=50?T.warn:T.down}}>{dscore}/100</div>
                <div style={{background:T.line,borderRadius:100,height:3,marginTop:3,width:80}}>
                  <div style={{width:`${dscore}%`,height:"100%",background:dscore>=80?T.up:dscore>=50?T.warn:T.down,borderRadius:100}}/>
                </div>
              </div>
            </div>
          </div>

          {/* CE + PE side by side */}
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",borderBottom:`1px solid ${T.line}`}}>
            <div style={{padding:"10px 10px",borderRight:`1px solid ${T.line}`}}>
              <div style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase",marginBottom:2}}>{symbol} {ceStrike} CE</div>
              <div style={{fontFamily:mono,fontSize:30,fontWeight:700,color:T.ink,lineHeight:1,letterSpacing:"-0.5px",marginBottom:2}}>{ceLtp!=null?ceLtp:"—"}</div>
              <div style={{fontFamily:mono,fontSize:8,color:T.subtle,marginBottom:10}}>Lot {instr.lot} · {instr.expiry_day}</div>
              <div style={{display:"flex",flexDirection:"column",gap:6}}>
                <ExecBtn text="← Sell Call" sub={ceLtp?`₹${ceLtp}`:""} onClick={()=>execute("Sell Call")} color={T.sell}/>
                <ExecBtn text="↑ Buy Call"  sub={ceLtp?`₹${ceLtp}`:""} onClick={()=>execute("Buy Call")}  color={T.buy}/>
              </div>
            </div>
            <div style={{padding:"10px 10px"}}>
              <div style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase",marginBottom:2,textAlign:"right"}}>{symbol} {peStrike} PE</div>
              <div style={{fontFamily:mono,fontSize:30,fontWeight:700,color:T.ink,lineHeight:1,letterSpacing:"-0.5px",marginBottom:2,textAlign:"right"}}>{peLtp!=null?peLtp:"—"}</div>
              <div style={{fontFamily:mono,fontSize:8,color:T.subtle,marginBottom:10,textAlign:"right"}}>VIX {vix?.toFixed(2)||"—"}</div>
              <div style={{display:"flex",flexDirection:"column",gap:6}}>
                <ExecBtn text="Sell Put →" sub={peLtp?`₹${peLtp}`:""} onClick={()=>execute("Sell Put")} color={T.sell}/>
                <ExecBtn text="↓ Buy Put"  sub={peLtp?`₹${peLtp}`:""} onClick={()=>execute("Buy Put")}  color={T.buy}/>
              </div>
            </div>
          </div>

          {/* Close all row */}
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,padding:"8px 10px"}}>
            <button onPointerDown={closeAll} style={{minHeight:36,borderRadius:8,border:`1.5px solid ${T.sell}`,background:"#FFF5F5",color:T.sell,fontFamily:inter,fontWeight:600,fontSize:12,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Close All</button>
            <button onPointerDown={()=>showToast("Orders cancelled")} style={{minHeight:36,borderRadius:8,border:`1.5px solid ${T.line}`,background:T.raised,color:T.body,fontFamily:inter,fontWeight:600,fontSize:12,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Cancel Orders</button>
          </div>
        </div>
      ) : (
        /* DESKTOP LAYOUT — 3 columns */
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",background:T.surface,borderBottom:`1px solid ${T.line}`}}>
          <div style={{padding:"14px",borderRight:`1px solid ${T.line}`}}>
            <div style={{fontFamily:mono,fontSize:9,fontWeight:600,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase",marginBottom:3}}>{symbol} {ceStrike} CE</div>
            <div style={{fontFamily:mono,fontSize:42,fontWeight:700,color:T.ink,lineHeight:1,letterSpacing:"-1px",marginBottom:3}}>{ceLtp!=null?ceLtp:"—"}</div>
            <div style={{fontFamily:mono,fontSize:9,color:T.subtle,marginBottom:14}}>Lot {instr.lot} · {instr.expiry_day}</div>
            <div style={{display:"flex",flexDirection:"column",gap:8}}>
              <ExecBtn text="← Sell Call" sub={ceLtp?`@ ₹${ceLtp}`:""} onClick={()=>execute("Sell Call")} color={T.sell}/>
              <ExecBtn text="↑ Buy Call"  sub={ceLtp?`@ ₹${ceLtp}`:""} onClick={()=>execute("Buy Call")}  color={T.buy}/>
            </div>
          </div>
          <div style={{padding:"14px",display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"space-between",textAlign:"center",borderRight:`1px solid ${T.line}`}}>
            <div>
              <div style={{fontFamily:mono,fontSize:9,fontWeight:600,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase",marginBottom:3}}>{symbol} Spot</div>
              <div style={{fontFamily:mono,fontSize:40,fontWeight:700,color:T.ink,lineHeight:1,letterSpacing:"-1px"}}>{indexLtp?.toLocaleString("en-IN",{maximumFractionDigits:2})||"—"}</div>
              <div style={{fontFamily:mono,fontSize:13,fontWeight:600,color:indexChg>=0?T.up:T.down,marginTop:5}}>{indexChg>=0?"+":""}{indexChg.toFixed(2)} ({indexPct>=0?"+":""}{indexPct.toFixed(2)}%)</div>
            </div>
            <div style={{width:"100%",display:"flex",flexDirection:"column",gap:6,margin:"10px 0"}}>
              <button onPointerDown={closeAll} style={{minHeight:36,borderRadius:8,border:`1.5px solid ${T.sell}`,background:"#FFF5F5",color:T.sell,fontFamily:inter,fontWeight:600,fontSize:12,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Close All Positions</button>
              <button onPointerDown={()=>showToast("Orders cancelled")} style={{minHeight:36,borderRadius:8,border:`1.5px solid ${T.line}`,background:T.raised,color:T.body,fontFamily:inter,fontWeight:600,fontSize:12,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Cancel All Orders</button>
            </div>
            <div style={{width:"100%",padding:"8px 10px",border:`1px solid ${T.line}`,borderRadius:8,background:T.raised}}>
              <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:4}}>
                <span style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase"}}>Pragnya</span>
                <span style={{fontFamily:mono,fontSize:11,fontWeight:700,color:dscore>=80?T.up:dscore>=50?T.warn:T.down}}>{dscore}/100</span>
              </div>
              <div style={{background:T.line,borderRadius:100,height:3}}>
                <div style={{width:`${dscore}%`,height:"100%",background:dscore>=80?T.up:dscore>=50?T.warn:T.down,borderRadius:100}}/>
              </div>
              <div style={{display:"flex",justifyContent:"space-between",marginTop:4,fontFamily:mono,fontSize:9,color:T.subtle}}>
                <span>Trades {st.trades_taken||0}/{cfg.max_trades_per_day||4}</span>
                <span>SL {st.sl_hits||0}/{cfg.max_sl_hits||2}</span>
              </div>
            </div>
            <div style={{fontFamily:mono,fontSize:9,color:T.subtle,marginTop:6}}>{expiry}</div>
          </div>
          <div style={{padding:"14px"}}>
            <div style={{fontFamily:mono,fontSize:9,fontWeight:600,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase",marginBottom:3,textAlign:"right"}}>{symbol} {peStrike} PE</div>
            <div style={{fontFamily:mono,fontSize:42,fontWeight:700,color:T.ink,lineHeight:1,letterSpacing:"-1px",marginBottom:3,textAlign:"right"}}>{peLtp!=null?peLtp:"—"}</div>
            <div style={{fontFamily:mono,fontSize:9,color:T.subtle,marginBottom:14,textAlign:"right"}}>VIX {vix?.toFixed(2)||"—"}</div>
            <div style={{display:"flex",flexDirection:"column",gap:8}}>
              <ExecBtn text="Sell Put →" sub={peLtp?`@ ₹${peLtp}`:""} onClick={()=>execute("Sell Put")} color={T.sell}/>
              <ExecBtn text="↓ Buy Put"  sub={peLtp?`@ ₹${peLtp}`:""} onClick={()=>execute("Buy Put")}  color={T.buy}/>
            </div>
          </div>
        </div>
      )}

      {/* ── TABS + TABLE ── */}
      <div style={{padding:"0 12px 40px"}}>
        <div style={{display:"flex",alignItems:"center",borderBottom:`1px solid ${T.line}`}}>
          {[["positions","Positions"],["orders","Orders"],["journal","Trade Book"],["config","Config"]].map(([k,l])=>(
            <button key={k} onPointerDown={()=>setTab(k)} style={{minHeight:40,padding:"0 10px",border:"none",borderBottom:tab===k?`2px solid ${T.brand}`:"2px solid transparent",background:"none",color:tab===k?T.brand:T.subtle,fontFamily:inter,fontWeight:600,fontSize:12,cursor:"pointer",marginBottom:-1,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>{l}</button>
          ))}
          <div style={{marginLeft:"auto",display:"flex",alignItems:"center",gap:6}}>
            <span style={{fontFamily:mono,fontSize:9,color:T.subtle}}>MTM</span>
            <span style={{fontFamily:mono,fontSize:13,fontWeight:700,color:dayPnl>=0?T.up:T.down}}>{dayPnl>=0?"+":""}₹{Math.abs(dayPnl).toLocaleString()}</span>
          </div>
        </div>

        {tab==="positions"&&(
          <div>
            <div style={{display:"grid",gridTemplateColumns:"2fr .7fr .7fr .7fr .7fr 1fr",padding:"7px 4px",background:T.raised,borderBottom:`1px solid ${T.line}`}}>
              {["SYMBOL","QTY","AVG","LTP","SL","ACTION"].map(h=><div key={h} style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1px"}}>{h}</div>)}
            </div>
            {positions.length===0
              ?<div style={{padding:"40px",textAlign:"center",color:T.subtle,fontSize:13}}>No open positions</div>
              :positions.map(p=>{
                const lots=JSON.parse(p.extra_json||"{}").lots||1
                const curLtp=p.instrument.includes("CE")?ceLtp:peLtp
                const mtm=curLtp?(p.direction==="SELL"?p.entry-curLtp:curLtp-p.entry)*instr.lot*lots:0
                return(
                  <div key={p.id} style={{display:"grid",gridTemplateColumns:"2fr .7fr .7fr .7fr .7fr 1fr",padding:"9px 4px",borderBottom:`1px solid ${T.line}`,alignItems:"center",background:T.surface}}>
                    <div>
                      <div style={{fontFamily:mono,fontWeight:700,fontSize:11,color:T.ink}}>{p.instrument}</div>
                      <div style={{fontSize:10,color:p.direction==="SELL"?T.sell:T.buy,fontWeight:600}}>{p.direction}</div>
                    </div>
                    <div style={{fontFamily:mono,fontSize:11,fontWeight:600,color:T.ink}}>{lots*instr.lot}</div>
                    <div style={{fontFamily:mono,fontSize:11,fontWeight:600,color:T.ink}}>{p.entry?.toFixed(0)}</div>
                    <div style={{fontFamily:mono,fontSize:11,fontWeight:700,color:mtm>=0?T.up:T.down}}>{curLtp||"—"}</div>
                    <div style={{fontFamily:mono,fontSize:11,fontWeight:600,color:T.sell}}>{p.sl?.toFixed(0)}</div>
                    <div style={{display:"flex",gap:4}}>
                      <button onPointerDown={()=>closePos(p.id,curLtp||p.target_price,"TARGET")} style={{minHeight:28,padding:"0 6px",borderRadius:5,border:"none",background:T.buy,color:"#fff",fontSize:10,fontWeight:600,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Exit</button>
                      <button onPointerDown={()=>closePos(p.id,p.sl,"SL")} style={{minHeight:28,padding:"0 6px",borderRadius:5,border:"none",background:T.sell,color:"#fff",fontSize:10,fontWeight:600,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>SL</button>
                    </div>
                  </div>
                )
              })
            }
          </div>
        )}

        {tab==="orders"&&<div style={{padding:"40px",textAlign:"center",color:T.subtle,fontSize:13}}>Live order sync with {broker} — Phase 2</div>}

        {tab==="journal"&&(
          <div>
            <div style={{display:"grid",gridTemplateColumns:"2fr .6fr .7fr .7fr .8fr .6fr",padding:"7px 4px",background:T.raised,borderBottom:`1px solid ${T.line}`}}>
              {["SYMBOL","DIR","ENTRY","EXIT","P&L","TIME"].map(h=><div key={h} style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1px"}}>{h}</div>)}
            </div>
            {(pragnya?.trades||[]).filter(t=>t.status==="CLOSED").length===0
              ?<div style={{padding:"40px",textAlign:"center",color:T.subtle,fontSize:13}}>No closed trades today</div>
              :(pragnya?.trades||[]).filter(t=>t.status==="CLOSED").map(t=>(
                <div key={t.id} style={{display:"grid",gridTemplateColumns:"2fr .6fr .7fr .7fr .8fr .6fr",padding:"9px 4px",borderBottom:`1px solid ${T.line}`,alignItems:"center",background:t.pnl>=0?"#F6FBF6":"#FDF6F6"}}>
                  <div style={{fontFamily:mono,fontWeight:700,fontSize:11,color:T.ink}}>{t.instrument}</div>
                  <div style={{fontSize:10,color:t.direction==="SELL"?T.sell:T.buy,fontWeight:600}}>{t.direction}</div>
                  <div style={{fontFamily:mono,fontSize:11,color:T.ink}}>{t.entry?.toFixed(0)}</div>
                  <div style={{fontFamily:mono,fontSize:11,color:T.ink}}>{t.exit_price?.toFixed(0)||"—"}</div>
                  <div style={{fontFamily:mono,fontSize:11,fontWeight:700,color:t.pnl>=0?T.up:T.down}}>{t.pnl>=0?"+":""}₹{Math.round(t.pnl||0)}</div>
                  <div style={{fontFamily:mono,fontSize:10,color:T.subtle}}>{t.time?.slice(0,5)}</div>
                </div>
              ))
            }
          </div>
        )}

        {tab==="config"&&(
          <div style={{padding:"14px 0"}}>
            <div style={{fontSize:12,fontWeight:700,color:T.ink,marginBottom:10}}>PRAGNYA Rules</div>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,marginBottom:12}}>
              {[["Max Trades/Day",cfg.max_trades_per_day],["Loss Limit",`₹${cfg.daily_loss_limit}`],["Daily Target",`₹${cfg.daily_target}`],["Max SL Hits",cfg.max_sl_hits]].map(([l,v])=>(
                <div key={l} style={{background:T.raised,padding:"10px 12px",borderRadius:8,border:`1px solid ${T.line}`}}>
                  <div style={{fontFamily:mono,fontSize:8,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase",marginBottom:3}}>{l}</div>
                  <div style={{fontFamily:mono,fontSize:18,fontWeight:700,color:T.ink}}>{v}</div>
                </div>
              ))}
            </div>
            <div style={{background:T.raised,borderRadius:8,padding:12,border:`1px solid ${T.line}`}}>
              <div style={{fontSize:12,color:T.body,fontStyle:"italic",lineHeight:1.8}}>"{quote.text}"</div>
              <div style={{fontFamily:mono,fontSize:10,color:T.subtle,marginTop:6}}>— {quote.src}</div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
