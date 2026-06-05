import { useState, useEffect, useCallback } from "react"

const API = "https://mtutrade.in/api"
const INSTRUMENTS = {
  SENSEX: { key: "BSE_INDEX|SENSEX", lot: 20, step: 100, expiry_day: "Thursday" },
  NIFTY:  { key: "NSE_INDEX|Nifty 50", lot: 65, step: 50, expiry_day: "Tuesday" },
}
const BROKERS = ["Upstox","Dhan","Kotak Neo","Zerodha","Angel","Fyers"]

async function api(path, opts={}) {
  try {
    const r = await fetch(API+path, { headers:{"Content-Type":"application/json"}, ...opts })
    return r.json()
  } catch(e) { return {error:e.message} }
}

export default function App() {
  const [broker, setBroker]     = useState(()=>localStorage.getItem("mtu_broker")||"")
  const [screen, setScreen]     = useState(()=>localStorage.getItem("mtu_broker")?"main":"broker")
  const [symbol, setSymbol]     = useState("SENSEX")
  const [expiries, setExpiries] = useState([])
  const [expiry, setExpiry]     = useState("")
  const [strikes, setStrikes]   = useState([])
  const [ceStrike, setCeStrike] = useState("")
  const [peStrike, setPeStrike] = useState("")
  const [ceLtp, setCeLtp]       = useState(0)
  const [peLtp, setPeLtp]       = useState(0)
  const [qty, setQty]           = useState(1)
  const [slPts, setSlPts]       = useState(20)
  const [tgtPts, setTgtPts]     = useState(20)
  const [market, setMarket]     = useState({sensex:null,nifty:null,vix:null})
  const [pragnya, setPragnya]   = useState(null)
  const [positions, setPositions] = useState([])
  const [tab, setTab]           = useState("positions")
  const [toast, setToast]       = useState(null)
  const [gitaMsg, setGitaMsg]   = useState(null)

  const instr = INSTRUMENTS[symbol]

  function showToast(msg, ok=true) {
    setToast({msg, ok})
    setTimeout(()=>setToast(null), 3000)
  }

  // Market poll
  useEffect(()=>{
    if(screen!=="main") return
    const poll = async()=>{
      const r = await api("/vajra/market")
      if(r.sensex) setMarket({sensex:r.sensex, nifty:r.nifty, vix:r.vix?.ltp})
    }
    poll()
    const t = setInterval(poll, 5000)
    return ()=>clearInterval(t)
  },[screen])

  // Expiries
  useEffect(()=>{
    if(screen!=="main") return
    api(`/sutra/expiries?index=${symbol}`).then(r=>{
      if(r.expiries?.length) { setExpiries(r.expiries); setExpiry(r.expiries[0]) }
    })
  },[symbol, screen])

  // Chain
  useEffect(()=>{
    if(!expiry || screen!=="main") return
    api(`/sutra/chain?index=${symbol}&expiry=${expiry}`).then(r=>{
      if(!r.strikes) return
      setStrikes(r.strikes)
      const atm = r.atm
      const valid = r.strikes.filter(s=>s.ce.ltp>0&&s.pe.ltp>0)
      const pool = valid.length>0?valid:r.strikes
      const ce = pool.find(s=>Number(s.strike)>=atm)||pool[Math.floor(pool.length/2)]
      const pe = [...pool].reverse().find(s=>Number(s.strike)<=atm)||pool[Math.floor(pool.length/2)]
      setCeStrike(String(ce.strike))
      setPeStrike(String(pe.strike))
    })
  },[expiry, symbol, screen])

  // Option LTP poll
  useEffect(()=>{
    if(!expiry||!ceStrike||!peStrike||screen!=="main") return
    const poll = async()=>{
      const r = await api(`/sutra/chain?index=${symbol}&expiry=${expiry}`)
      if(!r.strikes) return
      const ce = r.strikes.find(s=>String(s.strike)===String(ceStrike))
      const pe = r.strikes.find(s=>String(s.strike)===String(peStrike))
      if(ce) setCeLtp(ce.ce.ltp)
      if(pe) setPeLtp(pe.pe.ltp)
    }
    poll()
    const t = setInterval(poll, 3000)
    return ()=>clearInterval(t)
  },[expiry,ceStrike,peStrike,symbol,screen])

  // PRAGNYA
  useEffect(()=>{
    if(screen!=="main") return
    const poll = async()=>{
      const r = await api("/vajra/state")
      if(r.state) setPragnya(r)
      if(r.trades) setPositions(r.trades.filter(t=>t.status==="OPEN"))
    }
    poll()
    const t = setInterval(poll, 10000)
    return ()=>clearInterval(t)
  },[screen])

  function selectBroker(b) {
    setBroker(b)
    localStorage.setItem("mtu_broker", b)
    setScreen("main")
  }

  async function execute(type) {
    const isCall = type.includes("Call")
    const ltp = isCall ? ceLtp : peLtp
    const strike = isCall ? ceStrike : peStrike
    const action = type.includes("Sell") ? "SELL" : "BUY"
    const optType = isCall ? "CE" : "PE"

    if(!ltp && ltp!==0) { showToast("Price not available", false); return }
    if(!strike) { showToast("Strike not selected", false); return }

    const r = await api("/vajra/trade/open", {
      method:"POST",
      body: JSON.stringify({
        instrument:`${symbol}${strike}${optType}`,
        direction:action, entry:ltp||1,
        sl: action==="SELL" ? (ltp||1)+slPts : (ltp||1)-slPts,
        target: action==="SELL" ? (ltp||1)-tgtPts : (ltp||1)+tgtPts,
        lots:qty, strategy:`${action} ${optType}`
      })
    })
    if(r.status==="ok") {
      showToast(`✓ ${type} @ ₹${ltp} · ${qty}L`)
      const pr = await api("/vajra/state")
      if(pr.trades) setPositions(pr.trades.filter(t=>t.status==="OPEN"))
      setPragnya(pr)
    } else {
      const msg = r.detail || "Failed"
      showToast(msg, false)
      if(msg.toLowerCase().includes("lock")||msg.toLowerCase().includes("cannot")) {
        setGitaMsg(msg)
      }
    }
  }

  async function closePos(id, exitPrice, reason) {
    const r = await api("/vajra/trade/close", {
      method:"POST",
      body:JSON.stringify({trade_id:id, exit_price:exitPrice||1, exit_reason:reason})
    })
    if(r.status==="ok") {
      showToast(`Closed: ${r.pnl>=0?"+":""}₹${Math.round(r.pnl||0)}`)
      const pr = await api("/vajra/state")
      if(pr.trades) setPositions(pr.trades.filter(t=>t.status==="OPEN"))
      setPragnya(pr)
    }
  }

  const st = pragnya?.state||{}
  const cfg = pragnya?.cfg||{}
  const quote = pragnya?.quote||{}
  const dscore = st.discipline_score||100
  const dayPnl = st.daily_pnl||0
  const sensexLtp = market.sensex?.ltp
  const sensexChg = market.sensex?.change||0
  const sensexPct = market.sensex?.pct||0
  const niftyLtp = market.nifty?.ltp
  const now = new Date().toLocaleTimeString("en-IN",{hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false})

  // ── BROKER SCREEN ─────────────────────────────────────────────────────────
  if(screen==="broker") return (
    <div style={{minHeight:"100vh",background:"#F5F4F0",display:"flex",alignItems:"center",justifyContent:"center",padding:20,fontFamily:"'IBM Plex Sans',sans-serif"}}>
      <div style={{background:"#fff",borderRadius:14,padding:28,width:"100%",maxWidth:360,border:"1px solid #E2E0D8"}}>
        <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:22,fontWeight:700,color:"#1A1916",marginBottom:4}}>⚡ <span style={{color:"#E8540A"}}>VAJRA</span></div>
        <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:9,color:"#9B9689",letterSpacing:2,textTransform:"uppercase",marginBottom:20}}>Options Scalping Terminal</div>
        <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:10,color:"#9B9689",marginBottom:12,letterSpacing:1,textTransform:"uppercase"}}>Select Your Broker</div>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:10,marginBottom:20}}>
          {BROKERS.map(b=>(
            <button key={b} onClick={()=>selectBroker(b)}
              style={{padding:"14px 10px",borderRadius:8,border:`2px solid ${broker===b?"#E8540A":"#E2E0D8"}`,
                background:broker===b?"#FFF1E6":"#fff",color:broker===b?"#E8540A":"#1A1916",
                fontFamily:"'IBM Plex Sans',sans-serif",fontWeight:600,fontSize:14,cursor:"pointer",
                WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
              {b}
            </button>
          ))}
        </div>
        <div style={{background:"#F5F4F0",borderRadius:8,padding:14}}>
          <div style={{fontSize:11,color:"#3D3B35",fontStyle:"italic",lineHeight:1.6}}>"{quote.text||"Perform your duty equipoised, abandoning all attachment."}"</div>
          <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:9,color:"#9B9689",marginTop:6}}>— {quote.src||"Bhagavad Gita 2.48"}</div>
        </div>
      </div>
    </div>
  )

  // ── GITA OVERLAY ──────────────────────────────────────────────────────────
  if(gitaMsg) return (
    <div style={{position:"fixed",inset:0,background:"rgba(245,244,240,0.97)",zIndex:99999,display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",padding:32,fontFamily:"'IBM Plex Sans',sans-serif"}}>
      <div style={{fontSize:48,marginBottom:16}}>🕉️</div>
      <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:18,fontWeight:700,color:"#C0392B",marginBottom:8}}>PRAGNYA ACTIVATED</div>
      <div style={{fontSize:13,color:"#9B9689",marginBottom:24,textAlign:"center",maxWidth:300}}>{gitaMsg}</div>
      <div style={{background:"#F5F4F0",borderRadius:8,padding:16,maxWidth:340,marginBottom:24}}>
        <div style={{fontSize:12,color:"#3D3B35",fontStyle:"italic",lineHeight:1.6}}>"{quote.text}"</div>
        <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:9,color:"#9B9689",marginTop:6}}>— {quote.src}</div>
      </div>
      <button onClick={()=>setGitaMsg(null)}
        style={{padding:"10px 28px",borderRadius:8,border:"1.5px solid #E2E0D8",background:"#fff",color:"#9B9689",fontFamily:"'IBM Plex Sans',sans-serif",fontWeight:600,fontSize:13,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
        Dismiss
      </button>
    </div>
  )

  // ── MAIN TERMINAL ─────────────────────────────────────────────────────────
  return (
    <div style={{minHeight:"100vh",background:"#F5F4F0",fontFamily:"'IBM Plex Sans',sans-serif",paddingBottom:64}}>

      {/* Toast */}
      {toast && (
        <div style={{position:"fixed",top:0,left:0,right:0,zIndex:9999,background:toast.ok?"#D1FAE5":"#FEE2E2",padding:"10px 16px",fontSize:13,fontWeight:600,color:toast.ok?"#065F46":"#991B1B",textAlign:"center"}}>
          {toast.msg}
        </div>
      )}

      {/* Top bar */}
      <div style={{background:"#fff",borderBottom:"1px solid #E2E0D8",padding:"8px 12px",display:"flex",alignItems:"center",justifyContent:"space-between",flexWrap:"wrap",gap:8}}>
        <div style={{display:"flex",alignItems:"center",gap:10}}>
          <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:16,fontWeight:700,color:"#1A1916"}}>⚡ <span style={{color:"#E8540A"}}>VAJRA</span></div>
          <button onClick={()=>setScreen("broker")}
            style={{fontSize:11,fontWeight:600,padding:"4px 10px",borderRadius:20,border:"1.5px solid #E8540A",background:"#FFF1E6",color:"#E8540A",cursor:"pointer",fontFamily:"'IBM Plex Sans',sans-serif",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
            🔗 {broker}
          </button>
        </div>
        <div style={{display:"flex",gap:16,alignItems:"center"}}>
          {[
            ["SENSEX", sensexLtp, sensexChg, sensexPct],
            ["NIFTY",  niftyLtp,  0, 0],
            ["VIX",    market.vix, 0, 0],
          ].map(([name,ltp,chg,pct])=>(
            <div key={name} style={{textAlign:"center"}}>
              <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:8,color:"#9B9689",letterSpacing:1,textTransform:"uppercase"}}>{name}</div>
              <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:13,fontWeight:700,color:chg>0?"#1A7F4B":chg<0?"#C0392B":"#1A1916"}}>{ltp?ltp.toLocaleString("en-IN",{maximumFractionDigits:2}):"—"}</div>
              {chg!==0&&<div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:9,color:chg>=0?"#1A7F4B":"#C0392B"}}>{chg>=0?"+":""}{chg?.toFixed(1)} ({pct>=0?"+":""}{pct?.toFixed(2)}%)</div>}
            </div>
          ))}
        </div>
        <div style={{display:"flex",gap:14,alignItems:"center"}}>
          <div style={{textAlign:"right"}}>
            <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:8,color:"#9B9689",letterSpacing:1}}>DAY P&L</div>
            <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:13,fontWeight:700,color:dayPnl>=0?"#1A7F4B":"#C0392B"}}>{dayPnl>=0?"+":""}₹{Math.abs(dayPnl).toLocaleString()}</div>
          </div>
          <div style={{textAlign:"right"}}>
            <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:8,color:"#9B9689",letterSpacing:1}}>PRAGNYA</div>
            <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:13,fontWeight:700,color:dscore>=80?"#1A7F4B":dscore>=50?"#B45309":"#C0392B"}}>{dscore}/100</div>
          </div>
          <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:11,color:"#9B9689"}}>{now}</div>
        </div>
      </div>

      {/* Instrument row */}
      <div style={{background:"#fff",borderBottom:"1px solid #E2E0D8",padding:"8px 12px",display:"flex",flexWrap:"wrap",gap:10,alignItems:"flex-end"}}>
        {/* Symbol */}
        <div>
          <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:8,color:"#9B9689",letterSpacing:1.5,textTransform:"uppercase",marginBottom:3}}>Symbol</div>
          <select value={symbol} onChange={e=>setSymbol(e.target.value)}
            style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:12,fontWeight:600,border:"1.5px solid #E2E0D8",borderRadius:6,padding:"6px 8px",background:"#fff",cursor:"pointer"}}>
            {Object.keys(INSTRUMENTS).map(k=><option key={k}>{k}</option>)}
          </select>
        </div>
        {/* Expiry */}
        <div>
          <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:8,color:"#9B9689",letterSpacing:1.5,textTransform:"uppercase",marginBottom:3}}>Expiry</div>
          <select value={expiry} onChange={e=>setExpiry(e.target.value)}
            style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:12,fontWeight:600,border:"1.5px solid #E2E0D8",borderRadius:6,padding:"6px 8px",background:"#fff",cursor:"pointer"}}>
            {expiries.map(e=><option key={e}>{e}</option>)}
          </select>
        </div>
        {/* CE Strike */}
        <div>
          <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:8,color:"#9B9689",letterSpacing:1.5,textTransform:"uppercase",marginBottom:3}}>CE Strike</div>
          <select value={ceStrike} onChange={e=>setCeStrike(e.target.value)}
            style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:12,fontWeight:600,border:"1.5px solid #E2E0D8",borderRadius:6,padding:"6px 8px",background:"#fff",cursor:"pointer"}}>
            {strikes.map(s=><option key={s.strike} value={String(s.strike)}>{s.strike}{s.is_atm?" ◀":""}</option>)}
          </select>
        </div>
        {/* PE Strike */}
        <div>
          <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:8,color:"#9B9689",letterSpacing:1.5,textTransform:"uppercase",marginBottom:3}}>PE Strike</div>
          <select value={peStrike} onChange={e=>setPeStrike(e.target.value)}
            style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:12,fontWeight:600,border:"1.5px solid #E2E0D8",borderRadius:6,padding:"6px 8px",background:"#fff",cursor:"pointer"}}>
            {strikes.map(s=><option key={s.strike} value={String(s.strike)}>{s.strike}{s.is_atm?" ◀":""}</option>)}
          </select>
        </div>
        {/* Qty */}
        <div>
          <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:8,color:"#9B9689",letterSpacing:1.5,textTransform:"uppercase",marginBottom:3}}>Qty (Lots)</div>
          <div style={{display:"flex",alignItems:"center",border:"1.5px solid #E2E0D8",borderRadius:6,background:"#fff",overflow:"hidden"}}>
            <button onClick={()=>setQty(q=>Math.max(1,q-1))} style={{padding:"6px 10px",background:"none",border:"none",cursor:"pointer",fontWeight:700,fontSize:16,color:"#1A1916",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>−</button>
            <span style={{fontFamily:"'IBM Plex Mono',monospace",padding:"0 8px",fontWeight:700,fontSize:13}}>{qty}</span>
            <button onClick={()=>setQty(q=>q+1)} style={{padding:"6px 10px",background:"none",border:"none",cursor:"pointer",fontWeight:700,fontSize:16,color:"#1A1916",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>+</button>
          </div>
        </div>
        {/* SL */}
        <div>
          <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:8,color:"#9B9689",letterSpacing:1.5,textTransform:"uppercase",marginBottom:3}}>SL Pts</div>
          <input type="number" value={slPts} onChange={e=>setSlPts(+e.target.value)}
            style={{fontFamily:"'IBM Plex Mono',monospace",width:60,border:"1.5px solid #E2E0D8",borderRadius:6,padding:"6px 8px",fontSize:12,background:"#fff",color:"#1A1916"}}/>
        </div>
        {/* Target */}
        <div>
          <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:8,color:"#9B9689",letterSpacing:1.5,textTransform:"uppercase",marginBottom:3}}>Tgt Pts</div>
          <input type="number" value={tgtPts} onChange={e=>setTgtPts(+e.target.value)}
            style={{fontFamily:"'IBM Plex Mono',monospace",width:60,border:"1.5px solid #E2E0D8",borderRadius:6,padding:"6px 8px",fontSize:12,background:"#fff",color:"#1A1916"}}/>
        </div>
      </div>

      {/* Trading panel */}
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",margin:"10px 12px",gap:0}}>
        {/* CE */}
        <div style={{background:"#fff",border:"1px solid #E2E0D8",borderRadius:"10px 0 0 10px",padding:14,borderRight:"none"}}>
          <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:9,color:"#9B9689",letterSpacing:1.5,textTransform:"uppercase",marginBottom:6}}>{symbol} {ceStrike} CE</div>
          <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:28,fontWeight:700,color:"#1A1916",lineHeight:1,marginBottom:4}}>{ceLtp||"—"}</div>
          <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:9,color:"#9B9689",marginBottom:14}}>Lot: {instr.lot}</div>
          <button onPointerDown={()=>execute("Sell Call")}
            style={{display:"block",width:"100%",padding:"12px 0",marginBottom:8,borderRadius:6,border:"none",background:"#C0392B",color:"#fff",fontFamily:"'IBM Plex Sans',sans-serif",fontWeight:700,fontSize:13,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
            ← Sell Call
          </button>
          <button onPointerDown={()=>execute("Buy Call")}
            style={{display:"block",width:"100%",padding:"12px 0",borderRadius:6,border:"none",background:"#1A7F4B",color:"#fff",fontFamily:"'IBM Plex Sans',sans-serif",fontWeight:700,fontSize:13,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
            ↑ Buy Call
          </button>
        </div>

        {/* Center */}
        <div style={{background:"#fff",border:"1px solid #E2E0D8",padding:12,textAlign:"center",display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"space-between"}}>
          <div>
            <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:9,color:"#9B9689",letterSpacing:1,textTransform:"uppercase",marginBottom:4}}>{symbol}</div>
            <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:24,fontWeight:700,color:"#1A1916",lineHeight:1}}>
              {(symbol==="SENSEX"?sensexLtp:niftyLtp)?.toLocaleString("en-IN",{maximumFractionDigits:2})||"—"}
            </div>
            <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:11,color:sensexChg>=0?"#1A7F4B":"#C0392B",marginTop:4,fontWeight:600}}>
              {sensexChg>=0?"+":""}{sensexChg?.toFixed(2)} ({sensexPct>=0?"+":""}{sensexPct?.toFixed(2)}%)
            </div>
          </div>
          <div style={{width:"100%",background:"#F5F4F0",borderRadius:8,padding:"8px 10px",marginTop:10}}>
            <div style={{display:"flex",justifyContent:"space-between",marginBottom:4}}>
              <span style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:8,color:"#9B9689",letterSpacing:1,textTransform:"uppercase"}}>PRAGNYA</span>
              <span style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:10,fontWeight:700,color:dscore>=80?"#1A7F4B":dscore>=50?"#B45309":"#C0392B"}}>{dscore}/100</span>
            </div>
            <div style={{background:"#ECEAE4",borderRadius:100,height:4,overflow:"hidden"}}>
              <div style={{width:`${Math.min(100,100-dscore)}%`,height:"100%",background:dscore>=80?"#1A7F4B":dscore>=50?"#B45309":"#C0392B",borderRadius:100}}/>
            </div>
            <div style={{display:"flex",justifyContent:"space-between",marginTop:6,fontFamily:"'IBM Plex Mono',monospace",fontSize:9,color:"#9B9689"}}>
              <span>Trades: {st.trades_taken||0}/{cfg.max_trades_per_day||4}</span>
              <span>SL: {st.sl_hits||0}/{cfg.max_sl_hits||2}</span>
            </div>
          </div>
          <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:9,color:"#9B9689",marginTop:8}}>{expiry} · {instr.expiry_day}</div>
        </div>

        {/* PE */}
        <div style={{background:"#fff",border:"1px solid #E2E0D8",borderRadius:"0 10px 10px 0",padding:14,borderLeft:"none"}}>
          <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:9,color:"#9B9689",letterSpacing:1.5,textTransform:"uppercase",marginBottom:6,textAlign:"right"}}>{symbol} {peStrike} PE</div>
          <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:28,fontWeight:700,color:"#1A1916",lineHeight:1,marginBottom:4,textAlign:"right"}}>{peLtp||"—"}</div>
          <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:9,color:"#9B9689",marginBottom:14,textAlign:"right"}}>VIX: {market.vix?.toFixed(2)||"—"}</div>
          <button onPointerDown={()=>execute("Sell Put")}
            style={{display:"block",width:"100%",padding:"12px 0",marginBottom:8,borderRadius:6,border:"none",background:"#C0392B",color:"#fff",fontFamily:"'IBM Plex Sans',sans-serif",fontWeight:700,fontSize:13,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
            Sell Put →
          </button>
          <button onPointerDown={()=>execute("Buy Put")}
            style={{display:"block",width:"100%",padding:"12px 0",borderRadius:6,border:"none",background:"#1A7F4B",color:"#fff",fontFamily:"'IBM Plex Sans',sans-serif",fontWeight:700,fontSize:13,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
            ↓ Buy Put
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div style={{margin:"0 12px"}}>
        <div style={{display:"flex",borderBottom:"2px solid #E2E0D8",marginBottom:10}}>
          {[["positions","Positions"],["orders","Orders"],["journal","Trade Book"],["config","Config"]].map(([k,label])=>(
            <button key={k} onClick={()=>setTab(k)}
              style={{padding:"8px 14px",border:"none",background:"none",borderBottom:tab===k?"2px solid #E8540A":"2px solid transparent",color:tab===k?"#E8540A":"#9B9689",fontWeight:600,fontSize:12,cursor:"pointer",marginBottom:-2,fontFamily:"'IBM Plex Sans',sans-serif",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
              {label}
            </button>
          ))}
          <div style={{marginLeft:"auto",display:"flex",alignItems:"center",gap:6,paddingRight:4}}>
            <span style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:10,color:"#9B9689"}}>MTM:</span>
            <span style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:13,fontWeight:700,color:dayPnl>=0?"#1A7F4B":"#C0392B"}}>{dayPnl>=0?"+":""}₹{Math.abs(dayPnl).toLocaleString()}</span>
          </div>
        </div>

        {/* Positions */}
        {tab==="positions"&&(
          <div style={{background:"#fff",border:"1px solid #E2E0D8",borderRadius:10,overflow:"hidden"}}>
            <div style={{display:"grid",gridTemplateColumns:"2fr 1fr 1fr 1fr 1fr 1.5fr",padding:"8px 12px",borderBottom:"1px solid #E2E0D8",background:"#F5F4F0"}}>
              {["Symbol","Qty","Avg","LTP","SL","Action"].map(h=>(
                <div key={h} style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:9,fontWeight:600,color:"#9B9689",letterSpacing:1,textTransform:"uppercase"}}>{h}</div>
              ))}
            </div>
            {positions.length===0?(
              <div style={{padding:32,textAlign:"center",color:"#9B9689",fontSize:13}}>No open positions</div>
            ):positions.map(p=>{
              const lots = JSON.parse(p.extra_json||"{}").lots||1
              const curLtp = p.instrument.includes("CE")?ceLtp:peLtp
              return (
                <div key={p.id} style={{display:"grid",gridTemplateColumns:"2fr 1fr 1fr 1fr 1fr 1.5fr",padding:"10px 12px",borderBottom:"1px solid #E2E0D8",alignItems:"center"}}>
                  <div>
                    <div style={{fontFamily:"'IBM Plex Mono',monospace",fontWeight:700,fontSize:11,color:"#1A1916"}}>{p.instrument}</div>
                    <div style={{fontSize:10,color:p.direction==="SELL"?"#C0392B":"#1A7F4B",fontWeight:600}}>{p.direction}</div>
                  </div>
                  <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:11}}>{lots*instr.lot}</div>
                  <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:11}}>{p.entry?.toFixed(1)}</div>
                  <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:11,color:"#1A1916",fontWeight:700}}>{curLtp||"—"}</div>
                  <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:11,color:"#C0392B"}}>{p.sl?.toFixed(1)}</div>
                  <div style={{display:"flex",gap:4}}>
                    <button onPointerDown={()=>closePos(p.id,curLtp||p.target_price,"TARGET")}
                      style={{padding:"5px 8px",borderRadius:5,border:"none",background:"#1A7F4B",color:"#fff",fontSize:11,fontWeight:700,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Exit</button>
                    <button onPointerDown={()=>closePos(p.id,p.sl,"SL")}
                      style={{padding:"5px 8px",borderRadius:5,border:"none",background:"#C0392B",color:"#fff",fontSize:11,fontWeight:700,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>SL</button>
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {tab==="orders"&&<div style={{background:"#fff",border:"1px solid #E2E0D8",borderRadius:10,padding:32,textAlign:"center",color:"#9B9689",fontSize:13}}>Live order sync with {broker} — Phase 2</div>}

        {tab==="journal"&&(
          <div style={{background:"#fff",border:"1px solid #E2E0D8",borderRadius:10,overflow:"hidden"}}>
            <div style={{display:"grid",gridTemplateColumns:"2fr 1fr 1fr 1fr 1fr 1fr",padding:"8px 12px",borderBottom:"1px solid #E2E0D8",background:"#F5F4F0"}}>
              {["Symbol","Dir","Entry","Exit","P&L","Time"].map(h=>(
                <div key={h} style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:9,fontWeight:600,color:"#9B9689",letterSpacing:1,textTransform:"uppercase"}}>{h}</div>
              ))}
            </div>
            {(pragnya?.trades||[]).filter(t=>t.status==="CLOSED").length===0?(
              <div style={{padding:32,textAlign:"center",color:"#9B9689",fontSize:13}}>No closed trades today</div>
            ):(pragnya?.trades||[]).filter(t=>t.status==="CLOSED").map(t=>(
              <div key={t.id} style={{display:"grid",gridTemplateColumns:"2fr 1fr 1fr 1fr 1fr 1fr",padding:"10px 12px",borderBottom:"1px solid #E2E0D8",alignItems:"center"}}>
                <div style={{fontFamily:"'IBM Plex Mono',monospace",fontWeight:700,fontSize:11}}>{t.instrument}</div>
                <div style={{fontSize:10,color:t.direction==="SELL"?"#C0392B":"#1A7F4B",fontWeight:700}}>{t.direction}</div>
                <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:11}}>{t.entry?.toFixed(1)}</div>
                <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:11}}>{t.exit_price?.toFixed(1)||"—"}</div>
                <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:11,fontWeight:700,color:t.pnl>=0?"#1A7F4B":"#C0392B"}}>{t.pnl>=0?"+":""}₹{Math.round(t.pnl||0)}</div>
                <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:10,color:"#9B9689"}}>{t.time?.slice(0,5)}</div>
              </div>
            ))}
          </div>
        )}

        {tab==="config"&&(
          <div style={{background:"#fff",border:"1px solid #E2E0D8",borderRadius:10,padding:16}}>
            <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:11,fontWeight:700,color:"#1A1916",marginBottom:12,letterSpacing:1,textTransform:"uppercase"}}>PRAGNYA Rules</div>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:12,marginBottom:16}}>
              {[["Max Trades/Day",cfg.max_trades_per_day],["Loss Limit",`₹${cfg.daily_loss_limit}`],["Daily Target",`₹${cfg.daily_target}`],["Max SL Hits",cfg.max_sl_hits]].map(([l,v])=>(
                <div key={l}><div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:8,color:"#9B9689",letterSpacing:1.5,textTransform:"uppercase",marginBottom:3}}>{l}</div><div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:16,fontWeight:700,color:"#1A1916"}}>{v}</div></div>
              ))}
            </div>
            <div style={{background:"#F5F4F0",borderRadius:8,padding:14}}>
              <div style={{fontSize:12,color:"#3D3B35",fontStyle:"italic",lineHeight:1.6}}>"{quote.text}"</div>
              <div style={{fontFamily:"'IBM Plex Mono',monospace",fontSize:9,color:"#9B9689",marginTop:6}}>— {quote.src}</div>
            </div>
          </div>
        )}
      </div>

      {/* Bottom nav */}
      <nav style={{position:"fixed",bottom:0,left:0,right:0,background:"#fff",borderTop:"1px solid #E2E0D8",display:"flex",zIndex:9999}}>
        {[["positions","📋","Positions"],["orders","📒","Orders"],["journal","📊","Trades"],["config","⚙️","Config"]].map(([k,icon,label])=>(
          <button key={k} onClick={()=>setTab(k)}
            style={{flex:1,height:52,border:"none",background:"none",cursor:"pointer",borderTop:tab===k?"2px solid #E8540A":"2px solid transparent",color:tab===k?"#E8540A":"#9B9689",fontFamily:"'IBM Plex Mono',monospace",fontSize:8,fontWeight:600,letterSpacing:1,textTransform:"uppercase",display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",gap:2,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
            <span style={{fontSize:15}}>{icon}</span>{label}
          </button>
        ))}
      </nav>
    </div>
  )
}
