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

// ── Warm professional design tokens ───────────────────────────────────────────
const T = {
  // Backgrounds
  canvas:  "#FAF9F7",   // warm off-white — page bg
  surface: "#FFFFFF",   // card/panel bg
  raised:  "#F3F1EE",   // input/secondary bg

  // Text
  ink:     "#1A1814",   // primary text — near black, warm
  body:    "#3D3A35",   // body text
  subtle:  "#7A7670",   // labels, secondary

  // Borders
  line:    "#E8E4DE",   // default border
  strong:  "#C9C4BC",   // stronger border

  // Brand
  brand:   "#C8590A",   // VAJRA orange — warm, professional

  // Semantic
  sell:    "#C62828",   // sell red
  buy:     "#2E7D32",   // buy green
  sellBg:  "#FFEBEE",
  buyBg:   "#E8F5E9",
  up:      "#2E7D32",
  down:    "#C62828",
  warn:    "#E65100",
}

const inter = "'Inter',system-ui,sans-serif"
const mono  = "'JetBrains Mono','Fira Mono',monospace"

async function loadFonts() {
  const link = document.createElement("link")
  link.href = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600;700&display=swap"
  link.rel = "stylesheet"
  document.head.appendChild(link)
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

  useEffect(()=>{ loadFonts() },[])

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
      showToast(`✓ ${type} @ ₹${ltp} · ${qty} lot`)
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
      showToast(`Closed · ${r.pnl>=0?"+":""}₹${Math.round(r.pnl||0)}`)
      const pr=await api("/vajra/state")
      if(pr?.trades) setPositions(pr.trades.filter(t=>t.status==="OPEN"))
      setPragnya(pr)
    }
  }

  async function closeAll(){
    for(const p of positions){
      const curLtp=p.instrument.includes("CE")?ceLtp:peLtp
      await closePos(p.id,curLtp||p.sl,"MANUAL")
    }
  }

  const st=pragnya?.state||{}; const cfg=pragnya?.cfg||{}; const quote=pragnya?.quote||{}
  const dscore=st.discipline_score||100; const dayPnl=st.daily_pnl||0
  const sensex=market.sensex; const nifty=market.nifty; const vix=market.vix?.ltp
  const indexLtp=symbol==="SENSEX"?sensex?.ltp:nifty?.ltp
  const indexChg=symbol==="SENSEX"?sensex?.change||0:0
  const indexPct=symbol==="SENSEX"?sensex?.pct||0:0
  const now=new Date().toLocaleTimeString("en-IN",{hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false})

  // ── Micro components ───────────────────────────────────────────────────────
  const Tag = ({children}) => (
    <span style={{fontFamily:mono,fontSize:9,fontWeight:600,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase"}}>{children}</span>
  )

  const Divider = () => <div style={{width:1,height:28,background:T.line,flexShrink:0}}/>

  const ActionBtn = ({label,sub,onClick,color,bg}) => (
    <button onPointerDown={onClick} style={{
      display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",
      width:"100%",minHeight:56,padding:"0 12px",gap:2,
      borderRadius:8,border:"none",background:bg||color,color:"#fff",
      fontFamily:inter,cursor:"pointer",
      WebkitTapHighlightColor:"transparent",touchAction:"manipulation",
      boxShadow:`0 1px 3px ${color}33`
    }}>
      <span style={{fontWeight:700,fontSize:15,letterSpacing:"0.2px"}}>{label}</span>
      {sub&&<span style={{fontWeight:500,fontSize:10,opacity:0.85}}>{sub}</span>}
    </button>
  )

  const PriceBlock = ({tag,strike,ltp,align="left"}) => (
    <div style={{textAlign:align}}>
      <Tag>{tag} {strike}</Tag>
      <div style={{
        fontFamily:mono,fontSize:42,fontWeight:700,
        color:T.ink,lineHeight:1,marginTop:4,
        letterSpacing:"-1px"
      }}>
        {ltp!=null?ltp:<span style={{color:T.strong}}>—</span>}
      </div>
    </div>
  )

  // ── BROKER SCREEN ──────────────────────────────────────────────────────────
  if(screen==="broker") return (
    <div style={{minHeight:"100vh",background:T.canvas,display:"flex",alignItems:"center",justifyContent:"center",padding:24,fontFamily:inter}}>
      <div style={{width:"100%",maxWidth:340,background:T.surface,borderRadius:16,padding:28,boxShadow:"0 4px 24px rgba(0,0,0,0.08)"}}>
        <div style={{fontFamily:mono,fontSize:22,fontWeight:700,color:T.ink,marginBottom:2}}>
          ⚡ <span style={{color:T.brand}}>VAJRA</span>
        </div>
        <div style={{fontSize:11,color:T.subtle,letterSpacing:"0.5px",marginBottom:28}}>
          Options Scalping Terminal
        </div>
        <div style={{fontSize:11,fontWeight:600,color:T.body,marginBottom:10,textTransform:"uppercase",letterSpacing:"0.5px"}}>
          Select Broker
        </div>
        <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,marginBottom:24}}>
          {BROKERS.map(b=>(
            <button key={b} onPointerDown={()=>selectBroker(b)} style={{
              minHeight:44,padding:"10px",borderRadius:8,
              border:`1.5px solid ${broker===b?T.brand:T.line}`,
              background:broker===b?"#FFF3E0":T.surface,
              color:broker===b?T.brand:T.body,
              fontFamily:inter,fontWeight:600,fontSize:14,cursor:"pointer",
              WebkitTapHighlightColor:"transparent",touchAction:"manipulation",
              transition:"all .15s"
            }}>{b}</button>
          ))}
        </div>
        <div style={{borderTop:`1px solid ${T.line}`,paddingTop:16}}>
          <div style={{fontSize:12,color:T.body,fontStyle:"italic",lineHeight:1.8,marginBottom:6}}>
            "{quote.text||"Perform your duty equipoised, abandoning all attachment."}"
          </div>
          <div style={{fontFamily:mono,fontSize:10,color:T.subtle}}>
            — {quote.src||"Bhagavad Gita 2.48"}
          </div>
        </div>
      </div>
    </div>
  )

  // ── GITA OVERLAY ──────────────────────────────────────────────────────────
  if(gitaMsg) return (
    <div style={{position:"fixed",inset:0,background:"rgba(250,249,247,0.96)",zIndex:99999,display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",padding:32,fontFamily:inter}}>
      <div style={{fontSize:52,marginBottom:16}}>🕉️</div>
      <div style={{fontFamily:mono,fontSize:18,fontWeight:700,color:T.sell,marginBottom:8}}>PRAGNYA ACTIVATED</div>
      <div style={{fontSize:14,color:T.body,marginBottom:24,textAlign:"center",maxWidth:300,lineHeight:1.7}}>{gitaMsg}</div>
      <div style={{border:`1px solid ${T.line}`,borderRadius:12,padding:18,maxWidth:340,marginBottom:24,background:T.surface}}>
        <div style={{fontSize:13,color:T.body,fontStyle:"italic",lineHeight:1.8}}>"{quote.text}"</div>
        <div style={{fontFamily:mono,fontSize:10,color:T.subtle,marginTop:8}}>— {quote.src}</div>
      </div>
      <button onPointerDown={()=>setGitaMsg(null)} style={{minHeight:44,padding:"10px 32px",borderRadius:8,border:`1px solid ${T.line}`,background:T.surface,color:T.body,fontFamily:inter,fontWeight:600,fontSize:14,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
        Dismiss
      </button>
    </div>
  )

  // ── MAIN TERMINAL ──────────────────────────────────────────────────────────
  return (
    <div style={{minHeight:"100vh",background:T.canvas,fontFamily:inter}}>

      {/* Toast */}
      {toast&&(
        <div style={{position:"fixed",top:0,left:0,right:0,zIndex:9999,background:toast.ok?T.buy:T.sell,padding:"13px 20px",fontSize:14,fontWeight:600,color:"#fff",textAlign:"center",fontFamily:inter,letterSpacing:"0.2px"}}>
          {toast.msg}
        </div>
      )}

      {/* Loading */}
      {loading&&<div style={{position:"fixed",top:0,left:0,right:0,zIndex:9998,height:2,background:T.brand}}/>}

      {/* ── HEADER ─────────────────────────────────────────────────────── */}
      <div style={{background:T.surface,borderBottom:`1px solid ${T.line}`,padding:"0 16px",height:52,display:"flex",alignItems:"center",justifyContent:"space-between",gap:16}}>

        {/* Left: logo + broker */}
        <div style={{display:"flex",alignItems:"center",gap:12,flexShrink:0}}>
          <div style={{fontFamily:mono,fontSize:17,fontWeight:700,color:T.ink}}>
            ⚡ <span style={{color:T.brand}}>VAJRA</span>
          </div>
          <Divider/>
          <button onPointerDown={()=>setScreen("broker")} style={{
            fontFamily:inter,fontSize:12,fontWeight:600,color:T.body,
            background:T.raised,border:`1px solid ${T.line}`,borderRadius:6,
            padding:"5px 10px",cursor:"pointer",
            WebkitTapHighlightColor:"transparent",touchAction:"manipulation"
          }}>
            {broker} ▾
          </button>
        </div>

        {/* Center: index prices */}
        <div style={{display:"flex",gap:20,alignItems:"center",flexGrow:1,justifyContent:"center"}}>
          {[
            {name:"SENSEX",ltp:sensex?.ltp,chg:sensex?.change||0,pct:sensex?.pct||0},
            {name:"NIFTY", ltp:nifty?.ltp, chg:0,pct:0},
            {name:"VIX",   ltp:vix,         chg:0,pct:0},
          ].map(({name,ltp,chg,pct})=>(
            <div key={name} style={{display:"flex",alignItems:"baseline",gap:8}}>
              <span style={{fontFamily:mono,fontSize:10,fontWeight:600,color:T.subtle,letterSpacing:"1px"}}>{name}</span>
              <span style={{fontFamily:mono,fontSize:15,fontWeight:700,color:chg>0?T.up:chg<0?T.down:T.ink,letterSpacing:"-0.3px"}}>
                {ltp?ltp.toLocaleString("en-IN",{maximumFractionDigits:2}):"—"}
              </span>
              {chg!==0&&(
                <span style={{fontFamily:mono,fontSize:11,fontWeight:600,color:chg>=0?T.up:T.down}}>
                  {chg>=0?"+":""}{chg.toFixed(1)} ({pct>=0?"+":""}{pct.toFixed(2)}%)
                </span>
              )}
            </div>
          ))}
        </div>

        {/* Right: p&l + pragnya + time */}
        <div style={{display:"flex",alignItems:"center",gap:16,flexShrink:0}}>
          <div style={{textAlign:"right"}}>
            <div style={{fontFamily:mono,fontSize:9,fontWeight:600,color:T.subtle,letterSpacing:"1px",marginBottom:1}}>DAY P&L</div>
            <div style={{fontFamily:mono,fontSize:15,fontWeight:700,color:dayPnl>=0?T.up:T.down,letterSpacing:"-0.3px"}}>
              {dayPnl>=0?"+":""}₹{Math.abs(dayPnl).toLocaleString()}
            </div>
          </div>
          <Divider/>
          <div style={{textAlign:"right"}}>
            <div style={{fontFamily:mono,fontSize:9,fontWeight:600,color:T.subtle,letterSpacing:"1px",marginBottom:1}}>PRAGNYA</div>
            <div style={{fontFamily:mono,fontSize:15,fontWeight:700,color:dscore>=80?T.up:dscore>=50?T.warn:T.down}}>
              {dscore}/100
            </div>
          </div>
          <Divider/>
          <div style={{fontFamily:mono,fontSize:12,fontWeight:500,color:T.subtle}}>{now}</div>
        </div>
      </div>

      {/* ── CONTROLS ───────────────────────────────────────────────────── */}
      <div style={{background:T.raised,borderBottom:`1px solid ${T.line}`,padding:"8px 16px",display:"flex",flexWrap:"wrap",gap:12,alignItems:"flex-end"}}>
        {[
          ["Symbol",    <select value={symbol}   onChange={e=>setSymbol(e.target.value)}   style={inputStyle}>{Object.keys(INSTRUMENTS).map(k=><option key={k}>{k}</option>)}</select>],
          ["Expiry",    <select value={expiry}   onChange={e=>setExpiry(e.target.value)}   style={{...inputStyle,minWidth:110}}>{expiries.map(e=><option key={e}>{e}</option>)}</select>],
          ["CE Strike", <select value={ceStrike} onChange={e=>onCeChange(e.target.value)}  style={{...inputStyle,minWidth:110}}>{strikes.map(s=><option key={s.strike} value={String(s.strike)}>{s.strike}{s.is_atm?" ◀":""}</option>)}</select>],
          ["PE Strike", <select value={peStrike} onChange={e=>onPeChange(e.target.value)}  style={{...inputStyle,minWidth:110}}>{strikes.map(s=><option key={s.strike} value={String(s.strike)}>{s.strike}{s.is_atm?" ◀":""}</option>)}</select>],
        ].map(([lbl,el])=>(
          <div key={lbl}>
            <div style={labelStyle}>{lbl}</div>
            {el}
          </div>
        ))}

        <div>
          <div style={labelStyle}>Qty (Lots)</div>
          <div style={{display:"flex",alignItems:"center",background:T.surface,border:`1px solid ${T.line}`,borderRadius:6,overflow:"hidden",height:34}}>
            <button onPointerDown={()=>setQty(q=>Math.max(1,q-1))} style={qtyBtnStyle}>−</button>
            <span style={{fontFamily:mono,minWidth:30,textAlign:"center",fontWeight:700,fontSize:14,color:T.ink}}>{qty}</span>
            <button onPointerDown={()=>setQty(q=>q+1)} style={qtyBtnStyle}>+</button>
          </div>
        </div>

        {[["SL Pts",slPts,setSlPts],["Tgt Pts",tgtPts,setTgtPts]].map(([lbl,val,set])=>(
          <div key={lbl}>
            <div style={labelStyle}>{lbl}</div>
            <input type="number" value={val} onChange={e=>set(+e.target.value)} style={{...inputStyle,width:60}}/>
          </div>
        ))}
      </div>

      {/* ── TRADING PANEL ───────────────────────────────────────────────── */}
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr",background:T.surface,borderBottom:`1px solid ${T.line}`}}>

        {/* CE */}
        <div style={{padding:"16px",borderRight:`1px solid ${T.line}`}}>
          <PriceBlock tag={`${symbol}`} strike={`${ceStrike} CE`} ltp={ceLtp} />
          <div style={{fontFamily:mono,fontSize:10,color:T.subtle,marginTop:4,marginBottom:16}}>
            Lot {instr.lot} &nbsp;·&nbsp; {instr.expiry_day}
          </div>
          <div style={{display:"flex",flexDirection:"column",gap:8}}>
            <ActionBtn label="← Sell Call" sub={ceLtp?`@ ₹${ceLtp}`:""} onClick={()=>execute("Sell Call")} color={T.sell}/>
            <ActionBtn label="↑ Buy Call"  sub={ceLtp?`@ ₹${ceLtp}`:""} onClick={()=>execute("Buy Call")}  color={T.buy}/>
          </div>
        </div>

        {/* Center */}
        <div style={{padding:"16px",display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"space-between",textAlign:"center",borderRight:`1px solid ${T.line}`}}>
          <div>
            <Tag>{symbol} SPOT</Tag>
            <div style={{fontFamily:mono,fontSize:40,fontWeight:700,color:T.ink,lineHeight:1,marginTop:6,letterSpacing:"-1px"}}>
              {indexLtp?.toLocaleString("en-IN",{maximumFractionDigits:2})||"—"}
            </div>
            <div style={{fontFamily:mono,fontSize:13,fontWeight:600,color:indexChg>=0?T.up:T.down,marginTop:6}}>
              {indexChg>=0?"+":""}{indexChg.toFixed(2)} &nbsp; ({indexPct>=0?"+":""}{indexPct.toFixed(2)}%)
            </div>
          </div>

          <div style={{width:"100%",marginTop:14,display:"flex",flexDirection:"column",gap:8}}>
            <button onPointerDown={closeAll} style={{minHeight:38,borderRadius:8,border:`1.5px solid ${T.sell}`,background:"#FFF5F5",color:T.sell,fontFamily:inter,fontWeight:600,fontSize:13,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
              Close All Positions
            </button>
            <button onPointerDown={()=>showToast("Orders cancelled")} style={{minHeight:38,borderRadius:8,border:`1.5px solid ${T.line}`,background:T.raised,color:T.body,fontFamily:inter,fontWeight:600,fontSize:13,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
              Cancel All Orders
            </button>
          </div>

          {/* PRAGNYA */}
          <div style={{width:"100%",marginTop:12,padding:"10px 12px",border:`1px solid ${T.line}`,borderRadius:8,background:T.raised}}>
            <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:6}}>
              <Tag>Pragnya</Tag>
              <span style={{fontFamily:mono,fontSize:12,fontWeight:700,color:dscore>=80?T.up:dscore>=50?T.warn:T.down}}>{dscore}/100</span>
            </div>
            <div style={{background:T.line,borderRadius:100,height:4}}>
              <div style={{width:`${dscore}%`,height:"100%",background:dscore>=80?T.up:dscore>=50?T.warn:T.down,borderRadius:100,transition:"width .4s"}}/>
            </div>
            <div style={{display:"flex",justifyContent:"space-between",marginTop:6,fontFamily:mono,fontSize:10,color:T.subtle}}>
              <span>Trades {st.trades_taken||0}/{cfg.max_trades_per_day||4}</span>
              <span>SL {st.sl_hits||0}/{cfg.max_sl_hits||2}</span>
            </div>
          </div>

          <div style={{fontFamily:mono,fontSize:10,color:T.subtle,marginTop:8}}>{expiry}</div>
        </div>

        {/* PE */}
        <div style={{padding:"16px"}}>
          <PriceBlock tag={`${symbol}`} strike={`${peStrike} PE`} ltp={peLtp} align="right"/>
          <div style={{fontFamily:mono,fontSize:10,color:T.subtle,marginTop:4,marginBottom:16,textAlign:"right"}}>
            VIX {vix?.toFixed(2)||"—"}
          </div>
          <div style={{display:"flex",flexDirection:"column",gap:8}}>
            <ActionBtn label="Sell Put →" sub={peLtp?`@ ₹${peLtp}`:""} onClick={()=>execute("Sell Put")} color={T.sell}/>
            <ActionBtn label="↓ Buy Put"  sub={peLtp?`@ ₹${peLtp}`:""} onClick={()=>execute("Buy Put")}  color={T.buy}/>
          </div>
        </div>
      </div>

      {/* ── BOTTOM SECTION ───────────────────────────────────────────────── */}
      <div style={{padding:"0 16px 48px"}}>

        {/* Tabs */}
        <div style={{display:"flex",alignItems:"center",borderBottom:`1px solid ${T.line}`,marginBottom:0}}>
          {[["positions","Positions"],["orders","Orders"],["journal","Trade Book"],["config","Config"]].map(([k,lbl])=>(
            <button key={k} onPointerDown={()=>setTab(k)} style={{
              minHeight:44,padding:"0 16px",border:"none",
              borderBottom:tab===k?`2px solid ${T.brand}`:"2px solid transparent",
              background:"none",color:tab===k?T.brand:T.subtle,
              fontFamily:inter,fontWeight:600,fontSize:13,
              cursor:"pointer",marginBottom:-1,
              WebkitTapHighlightColor:"transparent",touchAction:"manipulation"
            }}>{lbl}</button>
          ))}
          <div style={{marginLeft:"auto",display:"flex",alignItems:"center",gap:8}}>
            <span style={{fontFamily:mono,fontSize:11,color:T.subtle}}>MTM</span>
            <span style={{fontFamily:mono,fontSize:15,fontWeight:700,color:dayPnl>=0?T.up:T.down}}>
              {dayPnl>=0?"+":""}₹{Math.abs(dayPnl).toLocaleString()}
            </span>
          </div>
        </div>

        {/* Positions */}
        {tab==="positions"&&(
          <div>
            <div style={{display:"grid",gridTemplateColumns:"2fr .8fr .8fr .8fr .8fr 1.2fr",padding:"8px 6px",background:T.raised,borderBottom:`1px solid ${T.line}`}}>
              {["SYMBOL","QTY","AVG","LTP","SL","ACTION"].map(h=>(
                <div key={h} style={{fontFamily:mono,fontSize:9,fontWeight:600,color:T.subtle,letterSpacing:"1px"}}>{h}</div>
              ))}
            </div>
            {positions.length===0
              ?(
                <div style={{padding:"48px",textAlign:"center",color:T.subtle,fontSize:14,fontFamily:inter}}>
                  No open positions
                </div>
              )
              :positions.map(p=>{
                const lots=JSON.parse(p.extra_json||"{}").lots||1
                const curLtp=p.instrument.includes("CE")?ceLtp:peLtp
                const mtm=curLtp?(p.direction==="SELL"?p.entry-curLtp:curLtp-p.entry)*instr.lot*lots:0
                return(
                  <div key={p.id} style={{display:"grid",gridTemplateColumns:"2fr .8fr .8fr .8fr .8fr 1.2fr",padding:"10px 6px",borderBottom:`1px solid ${T.line}`,alignItems:"center",background:T.surface}}>
                    <div>
                      <div style={{fontFamily:mono,fontWeight:700,fontSize:13,color:T.ink}}>{p.instrument}</div>
                      <div style={{fontFamily:inter,fontSize:11,color:p.direction==="SELL"?T.sell:T.buy,fontWeight:600,marginTop:2}}>{p.direction}</div>
                    </div>
                    <div style={{fontFamily:mono,fontSize:13,fontWeight:600,color:T.ink}}>{lots*instr.lot}</div>
                    <div style={{fontFamily:mono,fontSize:13,fontWeight:600,color:T.ink}}>{p.entry?.toFixed(1)}</div>
                    <div style={{fontFamily:mono,fontSize:13,fontWeight:700,color:mtm>=0?T.up:T.down}}>{curLtp||"—"}</div>
                    <div style={{fontFamily:mono,fontSize:13,fontWeight:600,color:T.sell}}>{p.sl?.toFixed(1)}</div>
                    <div style={{display:"flex",gap:6}}>
                      <button onPointerDown={()=>closePos(p.id,curLtp||p.target_price,"TARGET")} style={{minHeight:32,padding:"0 10px",borderRadius:6,border:"none",background:T.buy,color:"#fff",fontSize:11,fontWeight:600,cursor:"pointer",fontFamily:inter,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Exit</button>
                      <button onPointerDown={()=>closePos(p.id,p.sl,"SL")} style={{minHeight:32,padding:"0 10px",borderRadius:6,border:"none",background:T.sell,color:"#fff",fontSize:11,fontWeight:600,cursor:"pointer",fontFamily:inter,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>SL</button>
                    </div>
                  </div>
                )
              })
            }
          </div>
        )}

        {tab==="orders"&&(
          <div style={{padding:"48px",textAlign:"center",color:T.subtle,fontSize:14,fontFamily:inter}}>
            Live order sync with {broker} — Phase 2
          </div>
        )}

        {tab==="journal"&&(
          <div>
            <div style={{display:"grid",gridTemplateColumns:"2fr .7fr .8fr .8fr .9fr .7fr",padding:"8px 6px",background:T.raised,borderBottom:`1px solid ${T.line}`}}>
              {["SYMBOL","DIR","ENTRY","EXIT","P&L","TIME"].map(h=>(
                <div key={h} style={{fontFamily:mono,fontSize:9,fontWeight:600,color:T.subtle,letterSpacing:"1px"}}>{h}</div>
              ))}
            </div>
            {(pragnya?.trades||[]).filter(t=>t.status==="CLOSED").length===0
              ?(
                <div style={{padding:"48px",textAlign:"center",color:T.subtle,fontSize:14,fontFamily:inter}}>
                  No closed trades today
                </div>
              )
              :(pragnya?.trades||[]).filter(t=>t.status==="CLOSED").map(t=>(
                <div key={t.id} style={{display:"grid",gridTemplateColumns:"2fr .7fr .8fr .8fr .9fr .7fr",padding:"10px 6px",borderBottom:`1px solid ${T.line}`,alignItems:"center",background:t.pnl>=0?"#F6FBF6":"#FDF6F6"}}>
                  <div style={{fontFamily:mono,fontWeight:700,fontSize:13,color:T.ink}}>{t.instrument}</div>
                  <div style={{fontFamily:inter,fontSize:11,color:t.direction==="SELL"?T.sell:T.buy,fontWeight:600}}>{t.direction}</div>
                  <div style={{fontFamily:mono,fontSize:13,fontWeight:600,color:T.ink}}>{t.entry?.toFixed(1)}</div>
                  <div style={{fontFamily:mono,fontSize:13,fontWeight:600,color:T.ink}}>{t.exit_price?.toFixed(1)||"—"}</div>
                  <div style={{fontFamily:mono,fontSize:13,fontWeight:700,color:t.pnl>=0?T.up:T.down}}>{t.pnl>=0?"+":""}₹{Math.round(t.pnl||0)}</div>
                  <div style={{fontFamily:mono,fontSize:11,color:T.subtle}}>{t.time?.slice(0,5)}</div>
                </div>
              ))
            }
          </div>
        )}

        {tab==="config"&&(
          <div style={{padding:"16px 0"}}>
            <div style={{fontFamily:inter,fontSize:13,fontWeight:700,color:T.ink,marginBottom:12,letterSpacing:"0.3px"}}>
              PRAGNYA Discipline Rules
            </div>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,marginBottom:14}}>
              {[
                ["Max Trades / Day",cfg.max_trades_per_day],
                ["Daily Loss Limit",`₹${cfg.daily_loss_limit}`],
                ["Daily Target",    `₹${cfg.daily_target}`],
                ["Max SL Hits",     cfg.max_sl_hits],
              ].map(([l,v])=>(
                <div key={l} style={{background:T.raised,padding:"12px",borderRadius:8,border:`1px solid ${T.line}`}}>
                  <div style={{fontFamily:mono,fontSize:9,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase",marginBottom:4}}>{l}</div>
                  <div style={{fontFamily:mono,fontSize:20,fontWeight:700,color:T.ink}}>{v}</div>
                </div>
              ))}
            </div>
            <div style={{background:T.raised,borderRadius:8,padding:14,border:`1px solid ${T.line}`}}>
              <div style={{fontSize:13,color:T.body,fontStyle:"italic",lineHeight:1.8}}>"{quote.text}"</div>
              <div style={{fontFamily:mono,fontSize:10,color:T.subtle,marginTop:8}}>— {quote.src}</div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Shared micro styles ────────────────────────────────────────────────────────
const T2 = {
  canvas:"#FAF9F7",surface:"#FFFFFF",raised:"#F3F1EE",
  line:"#E8E4DE",strong:"#C9C4BC",subtle:"#7A7670",
}
const inputStyle = {
  fontFamily:"'JetBrains Mono','Fira Mono',monospace",
  fontSize:13,fontWeight:600,color:"#1A1814",
  border:"1px solid #E8E4DE",borderRadius:6,
  padding:"6px 8px",background:"#FFFFFF",cursor:"pointer",
  outline:"none",minWidth:88,height:34,
}
const labelStyle = {
  fontFamily:"'JetBrains Mono','Fira Mono',monospace",
  fontSize:9,fontWeight:600,color:"#7A7670",
  letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:3,
}
const qtyBtnStyle = {
  width:32,height:34,background:"none",border:"none",
  cursor:"pointer",fontWeight:700,fontSize:18,color:"#1A1814",
  WebkitTapHighlightColor:"transparent",touchAction:"manipulation",
}
