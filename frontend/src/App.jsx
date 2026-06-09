import React, { useState, useEffect, useRef, useCallback, memo } from "react"
import BrokerConnect from "./BrokerConnect.jsx"

const API = "https://mtutrade.in/api"
const INSTRUMENTS = {
  SENSEX: { lot: 20, step: 100, expiry_day: "THU" },
  NIFTY:  { lot: 65, step: 50,  expiry_day: "TUE" },
}

async function apiFetch(path, opts={}) {
  try {
    const token = localStorage.getItem("mtu_token")
    const headers = { "Content-Type":"application/json" }
    if (token) headers["Authorization"] = `Bearer ${token}`
    const r = await fetch(API + path, { headers, credentials:"include", ...opts })
    return r.json()
  } catch { return null }
}

const LIGHT = {
  canvas:"#FAF9F7", surface:"#FFFFFF", raised:"#F3F1EE",
  line:"#E8E4DE", subtle:"#7A7670", body:"#3D3A35", ink:"#1A1814",
  brand:"#C8590A", sell:"#C62828", buy:"#2E7D32", up:"#2E7D32", down:"#C62828", warn:"#E65100",
}
const DARK = {
  canvas:"#0A0A0A", surface:"#141414", raised:"#1E1E1E",
  line:"#2A2A2A", subtle:"#888888", body:"#BBBBBB", ink:"#F0EDE8",
  brand:"#FF8C00", sell:"#FF1744", buy:"#00C853", up:"#00C853", down:"#FF1744", warn:"#FF8C00",
}
const inter = "'Inter',system-ui,sans-serif"
const mono  = "'JetBrains Mono','Fira Mono',monospace"

// DOM refs for zero-flicker LTP updates
const ceLtpRef = { current: null }
const peLtpRef = { current: null }
const spotRef  = { current: null }

function updateLtpDom(ce, pe, spot) {
  if (ceLtpRef.current && ce != null) ceLtpRef.current.textContent = ce
  if (peLtpRef.current && pe != null) peLtpRef.current.textContent = pe
  if (spotRef.current  && spot != null) spotRef.current.textContent = spot
}

// ─── Position grouping ────────────────────────────────────────────────────────
// Groups individual DB trades by instrument+direction for display
// Each group has: key, instrument, direction, totalQty, avgEntry, ids[], sl
function groupPositions(positions, lotSize) {
  const grp = {}
  positions.forEach(p => {
    const k = `${p.instrument}_${p.direction}`
    const lots = JSON.parse(p.extra_json || "{}").lots || 1
    const qty = lots * lotSize
    if (!grp[k]) {
      grp[k] = { key:k, instrument:p.instrument, direction:p.direction,
                 totalQty:qty, totalCost:p.entry*qty, ids:[p.id], sl:p.sl }
    } else {
      grp[k].totalQty += qty
      grp[k].totalCost += p.entry * qty
      grp[k].ids.push(p.id)
    }
  })
  return Object.values(grp).map(g => ({ ...g, avgEntry: g.totalCost / g.totalQty }))
}

function OrdersTab({ T, mono, inter }) {
  const [orders, setOrders] = React.useState([])
  const [loading, setLoading] = React.useState(true)
  const fetchOrders = () => apiFetch("/vajra/orders").then(r => { setOrders(r?.orders||[]); setLoading(false) })
  React.useEffect(() => {
    fetchOrders()
    const t = setInterval(fetchOrders, 5000)
    return () => clearInterval(t)
  }, [])
  const statusColor = (s) => {
    if (!s) return T.subtle
    s = s.toLowerCase()
    if (s.includes('complete') || s.includes('filled')) return T.buy
    if (s.includes('reject') || s.includes('cancel')) return T.sell
    return T.warn
  }
  if (loading) return <div style={{padding:"40px",textAlign:"center",color:T.subtle,fontSize:13}}>Loading orders...</div>
  if (!orders.length) return <div style={{padding:"40px",textAlign:"center",color:T.subtle,fontSize:13}}>No orders today</div>
  return (
    <div>
      <div style={{display:"grid",gridTemplateColumns:"2fr 1fr .6fr .8fr .8fr",padding:"7px 4px",background:T.raised,borderBottom:`1px solid ${T.line}`,position:"sticky",top:0,zIndex:10}}>
        {["SYMBOL","STATUS","QTY","PRICE","TIME"].map(h=>(
          <div key={h} style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1px"}}>{h}</div>
        ))}
      </div>
      {orders.map(o=>(
        <div key={o.order_id} style={{display:"grid",gridTemplateColumns:"2fr 1fr .6fr .8fr .8fr",padding:"9px 4px",borderBottom:`1px solid ${T.line}`,alignItems:"center",background:T.surface}}>
          <div>
            <div style={{fontFamily:mono,fontWeight:700,fontSize:11,color:T.ink}}>{o.trading_symbol}</div>
            <div style={{fontSize:10,color:o.transaction_type==="SELL"?T.sell:T.buy,fontWeight:600}}>{o.transaction_type}</div>
          </div>
          <div style={{fontFamily:mono,fontSize:10,fontWeight:700,color:o.status==="REJECTED"?T.sell:statusColor(o.status)}}>{o.status?.toUpperCase()}</div>
          <div style={{fontFamily:mono,fontSize:11,color:T.ink}}>{o.quantity}</div>
          <div style={{fontFamily:mono,fontSize:11,color:T.ink}}>{o.average_price||o.price||"MKT"}</div>
          <div style={{fontFamily:mono,fontSize:10,color:T.subtle}}>{o.order_timestamp?.slice(11,16)||""}</div>
        </div>
      ))}
    </div>
  )
}

export default function App({ user, onLogout }) {
  // ── State ────────────────────────────────────────────────────────────────
  const [dark,       setDark]       = useState(() => localStorage.getItem("mtu_dark") === "1")
  const [appScreen,  setAppScreen]  = useState("terminal")
  const [symbol,     setSymbol]     = useState("SENSEX")
  const [expiries,   setExpiries]   = useState([])
  const [expiry,     setExpiry]     = useState("")
  const [strikes,    setStrikes]    = useState([])
  const [ceStrike,   setCeStrike]   = useState("")
  const [peStrike,   setPeStrike]   = useState("")
  const [ceLtp,      setCeLtp]      = useState(null)
  const [peLtp,      setPeLtp]      = useState(null)
  const [ceKey,      setCeKey]      = useState("")
  const [peKey,      setPeKey]      = useState("")
  const [qty,        setQty]        = useState(1)
  const [slPts,      setSlPts]      = useState(20)
  const [tgtPts,     setTgtPts]     = useState(20)
  const [market,     setMarket]     = useState({})
  const [pragnya,    setPragnya]    = useState(null)
  const [positions,  setPositions]  = useState([])
  const [tab,        setTab]        = useState("positions")
  const [toast,      setToast]      = useState(null)
  const [gitaMsg,    setGitaMsg]    = useState(null)
  const [loading,    setLoading]    = useState(false)
  const [isMobile,   setIsMobile]   = useState(window.innerWidth < 768)
  const [brokerStatus, setBrokerStatus] = useState('disconnected')
  const [pendingOrders, setPendingOrders] = useState([])
  const [drawerTab,  setDrawerTab]  = useState("broker")
  const [heatmap,    setHeatmap]    = useState(null)
  const [oiTab,      setOiTab]      = useState(0)
  const [stocks,     setStocks]     = useState(null)
  const [hmExpiry,   setHmExpiry]   = useState("")
  const [trend,      setTrend]      = useState(null)
  const [editingCfg, setEditingCfg] = useState(false)
  const [localCfg,   setLocalCfg]   = useState({})
  const [cfgSaved,   setCfgSaved]   = useState(false)

  // ── Refs ─────────────────────────────────────────────────────────────────
  // posRef always has the latest positions — avoids stale closure in callbacks
  const posRef        = useRef([])
  const refreshOrdersRef = useRef(null)
  const ceLtpValRef   = useRef(null)
  const peLtpValRef   = useRef(null)
  const wsRef         = useRef(null)
  const renderFrame   = useRef(null)
  const pollingTimers = useRef([])
  const marketTickRef = useRef({ ce: null, pe: null, spot: null })

  const T     = dark ? DARK : LIGHT
  const instr = INSTRUMENTS[symbol] || INSTRUMENTS.SENSEX

  // Keep posRef in sync with positions state
  const setPos = useCallback((val) => {
    const next = typeof val === "function" ? val(posRef.current) : val
    posRef.current = next
    setPositions(next)
  }, [])

  // ── Toast ─────────────────────────────────────────────────────────────────
  const toast$ = useCallback((msg, ok=true) => {
    setToast({ msg, ok })
    setTimeout(() => setToast(null), 2500)
  }, [])

  // ── Boot ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    const link = document.createElement("link")
    link.href = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600;700&display=swap"
    link.rel = "stylesheet"
    document.head.appendChild(link)
    const meta = document.querySelector("meta[name=viewport]")
    if (meta) meta.content = "width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"
    const onResize = () => setIsMobile(window.innerWidth < 768)
    window.addEventListener("resize", onResize)

    // ── SINGLE SOURCE OF TRUTH for broker status ──
    const p = new URLSearchParams(window.location.search)
    if (window.location.search) window.history.replaceState({}, document.title, window.location.pathname)

    // Polling (WS not yet available)
    const pollMarket = async () => { const r=await apiFetch("/vajra/market"); if(r) setMarket(r) }
    fetchTrend()
    fetchHeatmap()
    fetchStocks(symbol)
    const trendInterval = setInterval(fetchTrend, 60000)
    const pollState  = async () => {
      await apiFetch("/vajra/orders/sync", {method:"POST"})  // sync pending orders
      const r = await apiFetch("/vajra/state")
      if (!r) return
      if (r.broker_status) setBrokerStatus(r.broker_status)
      if (blockPoll.current) return
      if (r.state) setPragnya(r)
      const openTrades = r.trades ? r.trades.filter(t=>t.status==="OPEN") : []
      setPos(openTrades)
    }
    pollMarket(); const t1=setInterval(pollMarket,5000)
    pollState();  const t2=setInterval(pollState,10000)
    pollingTimers.current = [t1,t2]

    return () => { clearInterval(trendInterval);
      window.removeEventListener("resize", onResize)
      pollingTimers.current.forEach(clearInterval)
      if (renderFrame.current) clearTimeout(renderFrame.current)
    }
  }, [])

  useEffect(() => {
    document.body.style.background = T.canvas
    localStorage.setItem("mtu_dark", dark ? "1" : "0")
  }, [dark, T.canvas])



  // ── Option chain ──────────────────────────────────────────────────────────
  useEffect(() => {
    setExpiries([]); setExpiry(""); setStrikes([])
    setCeStrike(""); setPeStrike(""); setCeLtp(null); setPeLtp(null)
    apiFetch(`/sutra/expiries?index=${symbol}`).then(r => {
      if (r?.expiries?.length) { setExpiries(r.expiries); setExpiry(r.expiries[0]) }
    })
  }, [symbol])

  useEffect(() => {
    if (!expiry) return
    setLoading(true)
    apiFetch(`/sutra/chain/atm?index=${symbol}&expiry=${expiry}`).then(r => {
      setLoading(false)
      if (!r?.strikes?.length) return
      setStrikes(r.strikes)
      const pool = r.strikes.filter(s => s.ce.ltp>0 && s.pe.ltp>0)
      const src  = pool.length ? pool : r.strikes
      const ce   = src.find(s=>Number(s.strike)>=r.atm) || src[Math.floor(src.length/2)]
      const pe   = [...src].reverse().find(s=>Number(s.strike)<=r.atm) || src[Math.floor(src.length/2)]
      setCeStrike(String(ce.strike)); setCeLtp(ce.ce.ltp); setCeKey(ce.ce.key); ceLtpValRef.current=ce.ce.ltp
      setPeStrike(String(pe.strike)); setPeLtp(pe.pe.ltp); setPeKey(pe.pe.key); peLtpValRef.current=pe.pe.ltp
    })
  }, [expiry, symbol])

  useEffect(() => {
    if (!ceKey || !peKey) return
    const poll = async () => {
      const r = await apiFetch(`/sutra/ltp?ce_key=${encodeURIComponent(ceKey)}&pe_key=${encodeURIComponent(peKey)}`)
      if (!r) return
      Object.entries(r).forEach(([k,v]) => {
        if (k.includes("CE")) { ceLtpValRef.current=v; setCeLtp(v); updateLtpDom(v,null,null) }
        if (k.includes("PE")) { peLtpValRef.current=v; setPeLtp(v); updateLtpDom(null,v,null) }
      })
    }
    poll(); const t=setInterval(poll,2000); return ()=>clearInterval(t)
  }, [ceKey, peKey])

  const onCeChange = useCallback((val) => {
    setCeStrike(val)
    const r = strikes.find(s=>String(s.strike)===val)
    if (r) { setCeLtp(r.ce.ltp); setCeKey(r.ce.key); ceLtpValRef.current=r.ce.ltp }
  }, [strikes])

  const onPeChange = useCallback((val) => {
    setPeStrike(val)
    const r = strikes.find(s=>String(s.strike)===val)
    if (r) { setPeLtp(r.pe.ltp); setPeKey(r.pe.key); peLtpValRef.current=r.pe.ltp }
  }, [strikes])

  // ─────────────────────────────────────────────────────────────────────────
  // ORDER MANAGEMENT — HFT Rules
  //
  // RULE 1: Buy/Sell buttons ALWAYS open a new position. Zero exceptions.
  //         They never auto-square, never check existing positions.
  //
  // RULE 2: UI updates INSTANTLY on tap. API fires in background.
  //         No waiting. No disabling buttons.
  //
  // RULE 3: Positions are GROUPED by instrument+direction for display.
  //         Exit button on a group closes ALL orders in that group.
  //
  // RULE 4: Close All = instant UI clear + parallel API calls.
  //
  // RULE 5: Toast only on Exit/SL/CloseAll. Never on entry.
  // ─────────────────────────────────────────────────────────────────────────

  const execLock = useRef(false)
  const execute = useCallback((type) => {
    if (execLock.current) return
    execLock.current = true
    setTimeout(() => execLock.current = false, 2000)
    const isCall   = type.includes("Call")
    const ltp      = isCall ? ceLtpValRef.current : peLtpValRef.current
    const strike   = isCall ? ceStrike : peStrike
    const action   = type.includes("Sell") ? "SELL" : "BUY"
    const optType  = isCall ? "CE" : "PE"
    const instrKey = `${symbol}${strike}${optType}`
    if (!strike || !ltp) return



    // Counter trade — close ONE opposing position (FIFO)
    const opposing = posRef.current.filter(p => p.instrument===instrKey && p.direction!==action)
    if (opposing.length > 0) {
      const oppLtp = instrKey.includes("CE") ? ceLtpValRef.current : peLtpValRef.current
      // Pick first real DB ID — skip temps still in flight
      const toClose = opposing.find(p => !String(p.id).startsWith("T")) || opposing[0]
      const lots = JSON.parse(toClose.extra_json||"{}").lots||1
      const oneLotPnl = (toClose.direction==="SELL" ? toClose.entry-(oppLtp||0) : (oppLtp||0)-toClose.entry) * lots * instr.lot
      // Remove only this one from UI
      setPos(prev => prev.filter(p => p.id !== toClose.id))
      blockPoll.current = true; setTimeout(()=>blockPoll.current=false, 4000)
      toast$(`Squared off · ${oneLotPnl>=0?"+":""}₹${Math.round(oneLotPnl)}`, oneLotPnl>=0)
      // Only close if real DB id
      if (!String(toClose.id).startsWith("T")) {
        apiFetch("/vajra/trade/close", {
          method: "POST",
          body: JSON.stringify({ trade_id: toClose.id, exit_price: oppLtp||0, exit_reason: "SQUARE_OFF" })
        }).then(() => apiFetch("/vajra/state")).then(pr => { if (pr) setPragnya(pr) })
      }
      return
    }

    // INSTANT: add to orders tab immediately before API fires
    const tempOrder = {
      order_id: `TEMP_${Date.now()}`,
      trading_symbol: instrKey,
      transaction_type: action,
      status: "placing...",
      quantity: qty * instr.lot,
      price: ltp,
      average_price: ltp,
      order_timestamp: new Date().toTimeString().slice(0,8),
      _temp: true
    }
    const tempId = tempOrder.order_id
    setPendingOrders(prev => [...prev, tempOrder])
    setTab("orders")

    // BACKGROUND: fire API, replace temp with real ID on success
    apiFetch("/vajra/trade/open", {
      method: "POST",
      body: JSON.stringify({
        instrument: instrKey, direction: action, entry: ltp,
        sl:     action==="SELL" ? ltp+slPts : ltp-slPts,
        target: action==="SELL" ? ltp-tgtPts : ltp+tgtPts,
        lots: qty, strategy: `${action} ${optType}`,
        upstox_key: isCall ? ceKey : peKey
      })
    }).then(r => {
      if (r?.status === "ok") {
        apiFetch("/vajra/state").then(pr => {
          if (pr) setPragnya(pr)
          if (pr?.trades) {
            const realTrade = pr.trades.find(t =>
              t.status==="OPEN" &&
              t.instrument===instrKey &&
              t.direction===action &&
              !posRef.current.find(p => p.id===t.id)
            )
            if (realTrade) setPos(prev => prev.map(p => p.id===tempId ? realTrade : p))
          }
        })
      } else {
        // Rollback temp on failure
        setPos(prev => prev.filter(p => p.id !== tempId))
        const msg = r?.detail || "Order failed"
        if (msg.toLowerCase().includes("lock")) setGitaMsg(msg)
        else toast$(msg, false)
      }
    })
  }, [ceStrike, peStrike, symbol, qty, slPts, tgtPts])

  const exitGroup = useCallback((ids, ltp, sl, reason, mtm) => {
    // INSTANT: remove group from UI
    setPos(prev => prev.filter(p => !ids.includes(p.id)))
    // Toast immediately
    if (reason === "SL") toast$("SL Hit", false)
    else toast$(`Closed · ${mtm>=0?"+":""}₹${Math.round(mtm||0)}`, mtm>=0)
    // Only close real DB IDs (not temp IDs starting with T)
    const realIds = ids.filter(id => !String(id).startsWith('T'))
    if (!realIds.length) return
    // BACKGROUND: parallel API calls
    Promise.all(realIds.map(id => apiFetch("/vajra/trade/close", {
      method: "POST",
      body: JSON.stringify({ trade_id:id, exit_price: reason==="SL"?(sl||0):(ltp||0), exit_reason:reason })
    }))).then(() => apiFetch("/vajra/state")).then(pr => {
      if (pr?.trades) setPos(pr.trades.filter(t=>t.status==="OPEN"))
      if (pr) setPragnya(pr)
    })
  }, [])

  const closeAll = useCallback(() => {
    const snap = [...posRef.current]
    if (!snap.length) return
    // INSTANT: clear UI + toast with P&L
    let pnl = 0
    snap.forEach(p => {
      const ltp  = p.instrument.includes("CE") ? ceLtpValRef.current : peLtpValRef.current
      const lots = JSON.parse(p.extra_json||"{}").lots || 1
      if (ltp) pnl += (p.direction==="SELL" ? p.entry-ltp : ltp-p.entry) * lots * instr.lot
    })
    setPos([])
    blockPoll.current = true
    setTimeout(() => blockPoll.current = false, 8000)
    toast$(`Closed All · ${pnl>=0?"+":""}₹${Math.round(pnl)}`, pnl>=0)
    // BACKGROUND: parallel close all
    // Use bulk close endpoint — closes ALL open positions in DB at once
    apiFetch("/vajra/trade/close-all", {
      method: "POST",
      body: JSON.stringify({ exit_price: 0 })
    }).then(() => apiFetch("/vajra/state")).then(pr => {
      if (pr) setPragnya(pr)
    })
  }, [instr.lot])

  // ── Settings ──────────────────────────────────────────────────────────────
  const saveCfg = useCallback(async () => {
    const token = localStorage.getItem("mtu_token")
    const r = await fetch(`${API}/vajra/config`, {
      method:"POST", credentials:"include",
      headers:{"Content-Type":"application/json","Authorization":`Bearer ${token}`},
      body: JSON.stringify(localCfg)
    })
    const d = await r.json()
    if (d.status==="ok") {
      setCfgSaved(true); setEditingCfg(false)
      setTimeout(()=>setCfgSaved(false),3000)
      const pr = await apiFetch("/vajra/state"); if (pr) setPragnya(pr)
    }
  }, [localCfg])

  const handleLogout = useCallback(async () => {
    await fetch(`${API}/auth/logout`, { method:"POST", credentials:"include" })
    localStorage.removeItem("mtu_token"); localStorage.removeItem("mtu_user")
    if (onLogout) onLogout()
  }, [onLogout])

  // ── Derived ───────────────────────────────────────────────────────────────
  const st       = pragnya?.state || {}
  const cfg      = pragnya?.cfg   || {}
  const quote    = pragnya?.quote  || {}
  const dscore   = st.discipline_score || 100
  const dayPnl   = st.daily_pnl || 0
  const sensex   = market.sensex
  const nifty    = market.nifty
  const vix      = market.vix?.ltp
  const indexLtp = symbol==="SENSEX" ? sensex?.ltp : nifty?.ltp
  const indexChg = symbol==="SENSEX" ? sensex?.change||0 : 0
  const indexPct = symbol==="SENSEX" ? sensex?.pct||0 : 0

  const selStyle = {
    fontFamily:mono, fontSize:12, fontWeight:600, color:T.ink,
    border:`1px solid ${T.line}`, borderRadius:6, padding:"5px 6px",
    background:T.surface, cursor:"pointer", height:32, outline:"none"
  }
  const lbl = t => <div style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:3}}>{t}</div>

  const haptic = () => { try { navigator.vibrate && navigator.vibrate(30) } catch(e){} }

  const fetchHeatmap = async (expiry="") => {
    const url = expiry ? `/vajra/heatmap?expiry=${expiry}` : "/vajra/heatmap"
    const r = await apiFetch(url)
    if (r && !r.error) { setHeatmap(r); setHmExpiry(r.expiry) }
  }

  const fetchStocks = async (sym) => {
    const r = await apiFetch(`/vajra/stocks?symbol=${sym||symbol}`)
    if (r && !r.error) setStocks(r)
  }

  const fetchTrend = async () => {
    const r = await apiFetch("/vajra/trend")
    if (r) setTrend(r)
  }
  const ExecBtn = ({ text, sub, onClick, color }) => (
    <button onPointerDown={onClick}
      style={{
        display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center",
        width:"100%", minHeight:isMobile?56:52, gap:1,
        borderRadius:8, border:"none", background:color, color:"#fff",
        fontFamily:inter, cursor:"pointer",
        WebkitTapHighlightColor:"transparent", touchAction:"manipulation",
        boxShadow: dark ? `0 2px 8px ${color}66` : `0 2px 4px ${color}44`,
      }}
      onPointerDownCapture={e => e.currentTarget.style.transform="scale(0.96)"}
      onPointerUpCapture={e   => e.currentTarget.style.transform="scale(1)"}
    >
      <span style={{fontWeight:700,fontSize:isMobile?15:14}}>{text}</span>
      {sub && <span style={{fontWeight:500,fontSize:10,opacity:0.85}}>{sub}</span>}
    </button>
  )

  // ── Grouped positions for render ──────────────────────────────────────────
  const grouped = groupPositions(positions, instr.lot)

  // ── Settings Screen ───────────────────────────────────────────────────────
  if (appScreen === "settings") return (
    <div style={{minHeight:"100vh",background:T.canvas,fontFamily:inter}}>
      <div style={{background:T.surface,borderBottom:`1px solid ${T.line}`,padding:"0 16px",height:52,display:"flex",alignItems:"center",justifyContent:"space-between",position:"sticky",top:0,zIndex:10}}>
        <div style={{fontFamily:mono,fontSize:15,fontWeight:700,color:T.ink}}>⚙️ Settings</div>
        <button onPointerDown={async()=>{
          const prevStatus = brokerStatus
          setAppScreen("terminal")
          const r=await apiFetch("/vajra/state")
          if(r?.broker_status) {
            setBrokerStatus(r.broker_status)
            // Only toast if reconnected (was disconnected/expired, now connected)
            if(r.broker_status==='connected' && prevStatus!=='connected') {
              toast$('✓ Broker connected · Live')
            }
          }
        }} style={{background:"none",border:"none",fontSize:22,cursor:"pointer",color:T.subtle,WebkitTapHighlightColor:"transparent",padding:"8px"}}>✕</button>
      </div>
      <div style={{maxWidth:480,margin:"0 auto",padding:"16px"}}>
        {/* Account */}
        <div style={{background:T.surface,borderRadius:12,padding:"16px",border:`1px solid ${T.line}`,marginBottom:12}}>
          <div style={{fontFamily:mono,fontSize:8,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:10}}>Account</div>
          <div style={{fontFamily:inter,fontSize:15,fontWeight:700,color:T.ink,marginBottom:2}}>{user?.name||"User"}</div>
          <div style={{fontFamily:mono,fontSize:11,color:T.subtle,marginBottom:8}}>{user?.email||""}</div>
          <div style={{display:"flex",gap:6,flexWrap:"wrap"}}>
            {(user?.products||["VAJRA"]).map(p=>(
              <span key={p} style={{fontFamily:mono,fontSize:9,fontWeight:700,color:T.brand,background:dark?"#2A1A0A":"#FFF3E0",border:`1px solid ${T.brand}`,borderRadius:4,padding:"2px 8px"}}>{p}</span>
            ))}
          </div>
        </div>
        {/* Broker */}
        <div style={{background:T.surface,borderRadius:12,padding:"16px",border:`1px solid ${T.line}`,marginBottom:12}}>
          <div style={{fontFamily:mono,fontSize:8,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:12}}>Broker Connection</div>
          <BrokerConnect T={T} user={user} onConnected={b=>{setBrokerStatus('connected');toast$(`✓ ${b} connected · Live`)}} onDisconnected={()=>setBrokerStatus('disconnected')}/>
        </div>
        {/* Appearance */}
        <div style={{background:T.surface,borderRadius:12,padding:"16px",border:`1px solid ${T.line}`,marginBottom:12}}>
          <div style={{fontFamily:mono,fontSize:8,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:12}}>Appearance</div>
          <div style={{display:"flex",justifyContent:"space-between",alignItems:"center"}}>
            <div>
              <div style={{fontFamily:inter,fontSize:13,fontWeight:700,color:T.ink}}>{dark?"Bloomberg Dark":"Warm Light"}</div>
              <div style={{fontFamily:mono,fontSize:10,color:T.subtle,marginTop:2}}>{dark?"Black terminal, electric colors":"Off-white, warm professional"}</div>
            </div>
            <div onPointerDown={()=>setDark(d=>!d)} style={{width:48,height:26,borderRadius:100,background:dark?T.brand:T.line,cursor:"pointer",position:"relative",transition:"background .25s",flexShrink:0,WebkitTapHighlightColor:"transparent"}}>
              <div style={{position:"absolute",top:3,left:dark?24:3,width:20,height:20,borderRadius:100,background:"#fff",transition:"left .25s",boxShadow:"0 1px 4px rgba(0,0,0,0.2)"}}/>
            </div>
          </div>
        </div>
        {/* PRAGNYA — editable */}
        <div style={{background:T.surface,borderRadius:12,padding:"16px",border:`1px solid ${T.line}`,marginBottom:12}}>
          <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:12}}>
            <div style={{fontFamily:mono,fontSize:8,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase"}}>PRAGNYA Rules</div>
            {!editingCfg
              ?<button onPointerDown={()=>{setLocalCfg({...cfg});setEditingCfg(true)}} style={{fontFamily:inter,fontSize:11,fontWeight:600,color:T.brand,background:"none",border:`1px solid ${T.brand}`,borderRadius:5,padding:"3px 10px",cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Edit</button>
              :<div style={{display:"flex",gap:6}}>
                <button onPointerDown={saveCfg} style={{fontFamily:inter,fontSize:11,fontWeight:700,color:"#fff",background:T.buy,border:"none",borderRadius:5,padding:"3px 10px",cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Save</button>
                <button onPointerDown={()=>setEditingCfg(false)} style={{fontFamily:inter,fontSize:11,fontWeight:600,color:T.subtle,background:"none",border:`1px solid ${T.line}`,borderRadius:5,padding:"3px 10px",cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Cancel</button>
              </div>
            }
          </div>
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8}}>
            {[
              {key:"max_trades_per_day",label:"Max Trades/Day"},
              {key:"daily_loss_limit",  label:"Max Loss (₹)"},
              {key:"daily_target",      label:"Daily Target (₹)"},
              {key:"max_sl_hits",       label:"Max SL Hits"},
              {key:"sl_points",         label:"SL Pts"},
              {key:"target_points",     label:"Tgt Pts"},
            ].map(({key,label})=>(
              <div key={key} style={{background:T.raised,padding:"10px 12px",borderRadius:8,border:`1px solid ${T.line}`}}>
                <div style={{fontFamily:mono,fontSize:8,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase",marginBottom:4}}>{label}</div>
                {editingCfg
                  ?<input type="number"
                      value={key==="daily_loss_limit"?Math.abs(localCfg[key]??0):localCfg[key]??""}
                      onChange={e=>setLocalCfg(p=>({...p,[key]:key==="daily_loss_limit"?-Math.abs(Number(e.target.value)):Number(e.target.value)}))}
                      style={{width:"100%",fontFamily:mono,fontSize:16,fontWeight:700,color:T.ink,background:"none",border:"none",borderBottom:`1px solid ${T.brand}`,outline:"none",padding:0}}/>
                  :<div style={{fontFamily:mono,fontSize:18,fontWeight:700,color:T.ink}}>{key==="daily_loss_limit"?Math.abs(cfg[key]||0):cfg[key]}</div>
                }
              </div>
            ))}
          </div>
          {cfgSaved&&<div style={{fontFamily:mono,fontSize:10,color:T.buy,marginTop:8,textAlign:"center"}}>✓ Saved</div>}
        </div>
        {/* Gita */}
        <div style={{background:T.surface,borderRadius:12,padding:"16px",border:`1px solid ${T.line}`,marginBottom:20}}>
          <div style={{fontFamily:mono,fontSize:8,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:10}}>Today's Verse</div>
          <div style={{fontSize:13,color:T.body,fontStyle:"italic",lineHeight:1.8}}>"{quote.text||"Perform your duty equipoised."}"</div>
          <div style={{fontFamily:mono,fontSize:10,color:T.subtle,marginTop:6}}>— {quote.src||"Bhagavad Gita 2.48"}</div>
        </div>
        <button onPointerDown={()=>{
          const today=new Date().toISOString().slice(0,10)
          localStorage.removeItem("mtu_planned_"+today)
          toast$("Planner reset — refresh to see it")
        }} style={{width:"100%",minHeight:40,borderRadius:10,border:`1px solid ${T.line}`,background:"transparent",color:T.subtle,fontFamily:inter,fontWeight:600,fontSize:13,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation",marginBottom:8}}>
          🧠 Reset Today's Planner (Debug)
        </button>
        <button onPointerDown={handleLogout} style={{width:"100%",minHeight:48,borderRadius:10,border:`1.5px solid ${T.sell}`,background:"transparent",color:T.sell,fontFamily:inter,fontWeight:700,fontSize:15,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Sign Out</button>
      </div>
    </div>
  )

  // ── Gita overlay ──────────────────────────────────────────────────────────
  if (gitaMsg) return (
    <div style={{position:"fixed",inset:0,background:dark?"rgba(10,10,10,0.97)":"rgba(250,249,247,0.97)",zIndex:99999,display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",padding:28,fontFamily:inter}}>
      <div style={{fontSize:48,marginBottom:14}}>🕉️</div>
      <div style={{fontFamily:mono,fontSize:17,fontWeight:700,color:T.sell,marginBottom:8}}>PRAGNYA ACTIVATED</div>
      <div style={{fontSize:13,color:T.body,marginBottom:20,textAlign:"center",maxWidth:280,lineHeight:1.7}}>{gitaMsg}</div>
      <div style={{border:`1px solid ${T.line}`,borderRadius:12,padding:16,maxWidth:320,marginBottom:20,background:T.surface,width:"100%"}}>
        <div style={{fontSize:12,color:T.body,fontStyle:"italic",lineHeight:1.8}}>"{quote.text||"Perform your duty equipoised."}"</div>
        <div style={{fontFamily:mono,fontSize:10,color:T.subtle,marginTop:6}}>— {quote.src||"Bhagavad Gita 2.48"}</div>
      </div>
      <button onPointerDown={()=>setGitaMsg(null)} style={{minHeight:44,padding:"10px 28px",borderRadius:8,border:`1px solid ${T.line}`,background:T.surface,color:T.body,fontFamily:inter,fontWeight:600,fontSize:14,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Dismiss</button>
    </div>
  )

  // ── Terminal ──────────────────────────────────────────────────────────────
  return (
    <div style={{minHeight:"100vh",background:T.canvas,fontFamily:inter,transition:"background .3s",paddingTop:brokerStatus!=="connected"?"44px":"0"}}>

      <div id="vajra-dbg" style={{position:"fixed",bottom:0,left:0,right:0,background:"#000",color:"#0f0",fontSize:10,padding:"2px 8px",zIndex:99999,fontFamily:"monospace"}}></div>
      {/* Toast — fixed, never shifts layout */}
      {toast&&<div style={{position:"fixed",top:0,left:0,right:0,zIndex:9999,background:toast.ok?T.buy:T.sell,padding:"10px 16px",fontSize:13,fontWeight:600,color:"#fff",textAlign:"center",fontFamily:inter,pointerEvents:"none"}}>{toast.msg}</div>}
      {loading&&<div style={{position:"fixed",top:0,left:0,right:0,zIndex:9998,height:2,background:T.brand}}/>}

      {/* Broker banner */}
      {brokerStatus!=='connected'&&<div onPointerDown={()=>setAppScreen("settings")} style={{background:"#7B5800",color:"#fff",padding:"9px 16px",display:"flex",alignItems:"center",justifyContent:"space-between",cursor:"pointer",WebkitTapHighlightColor:"transparent",position:"fixed",top:0,left:0,right:0,zIndex:9990}}>
        <span style={{fontFamily:inter,fontSize:12,fontWeight:600}}>{brokerStatus==='expired'?"⚠️ Session expired — reconnect broker":"⚠️ No broker connected"}</span>
        <span style={{fontFamily:inter,fontSize:12,fontWeight:700}}>Connect →</span>
      </div>}

      {/* Header */}
      <div style={{background:T.surface,borderBottom:`1px solid ${T.line}`,padding:"0 12px",height:44,display:"flex",alignItems:"center",gap:8,position:"sticky",top:0,zIndex:100,transition:"background .3s"}}>
        <div style={{fontFamily:mono,fontSize:15,fontWeight:700,color:T.ink,flexShrink:0,display:"flex",alignItems:"center",gap:6}}>
          ⚡ <span style={{color:T.brand}}>VAJRA</span>
          {(()=>{
            const killed = st.killed_at || st.cooling_until
            if(killed) return <span style={{display:"flex",alignItems:"center",gap:4,fontFamily:inter,fontSize:9,fontWeight:700,color:"#FF8C00",background:"#FF8C0015",border:"1px solid #FF8C0040",borderRadius:20,padding:"2px 7px",letterSpacing:"0.5px"}}>
              <span style={{width:6,height:6,borderRadius:"50%",background:"#FF8C00",display:"inline-block"}}/>KILL SWITCH
            </span>
            if(brokerStatus==='connected') return <span style={{display:"flex",alignItems:"center",gap:4,fontFamily:inter,fontSize:9,fontWeight:700,color:"#2E7D32",background:"#2E7D3215",border:"1px solid #2E7D3240",borderRadius:20,padding:"2px 7px",letterSpacing:"0.5px"}}>
              <span style={{width:6,height:6,borderRadius:"50%",background:"#2E7D32",boxShadow:"0 0 4px #2E7D32",display:"inline-block"}}/>LIVE
            </span>
            return <span style={{display:"flex",alignItems:"center",gap:4,fontFamily:inter,fontSize:9,fontWeight:700,color:"#C62828",background:"#C6282815",border:"1px solid #C6282840",borderRadius:20,padding:"2px 7px",letterSpacing:"0.5px"}}>
              <span style={{width:6,height:6,borderRadius:"50%",background:"#C62828",display:"inline-block"}}/>OFFLINE
            </span>
          })()}
        </div>
        <div style={{width:1,height:18,background:T.line,flexShrink:0}}/>
        <div style={{display:"flex",gap:12,alignItems:"center",overflowX:"auto",flex:1,scrollbarWidth:"none"}}>
          {[{n:"SENSEX",ltp:sensex?.ltp,chg:sensex?.change||0,pct:sensex?.pct||0},{n:"NIFTY",ltp:nifty?.ltp,chg:0,pct:0},{n:"VIX",ltp:vix,chg:0,pct:0}].map(({n,ltp,chg,pct})=>(
            <div key={n} style={{display:"flex",alignItems:"baseline",gap:4,flexShrink:0}}>
              <span style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1px"}}>{n}</span>
              <span style={{fontFamily:mono,fontSize:13,fontWeight:700,color:chg>0?T.up:chg<0?T.down:T.ink}}>{ltp?ltp.toLocaleString("en-IN",{maximumFractionDigits:2}):"—"}</span>
              {chg!==0&&<span style={{fontFamily:mono,fontSize:9,color:chg>=0?T.up:T.down}}>{chg>=0?"+":""}{chg.toFixed(1)}({pct>=0?"+":""}{pct.toFixed(2)}%)</span>}
            </div>
          ))}
        </div>
        <div style={{width:1,height:18,background:T.line,flexShrink:0}}/>
        <div style={{display:"flex",gap:10,alignItems:"center",flexShrink:0}}>
          <div style={{textAlign:"right"}}>
            <div style={{fontFamily:mono,fontSize:7,color:T.subtle,letterSpacing:"1px"}}>P&L</div>
            <div style={{fontFamily:mono,fontSize:12,fontWeight:700,color:dayPnl>=0?T.up:T.down}}>{dayPnl>=0?"+":""}₹{Math.abs(dayPnl).toLocaleString()}</div>
          </div>
          <div style={{textAlign:"right"}}>
            <div style={{fontFamily:mono,fontSize:7,color:T.subtle,letterSpacing:"1px"}}>PRAGNYA</div>
            <div style={{fontFamily:mono,fontSize:12,fontWeight:700,color:dscore>=80?T.up:dscore>=50?T.warn:T.down}}>{dscore}/100</div>
          </div>
          <div style={{width:1,height:18,background:T.line}}/>
          <button onPointerDown={()=>setAppScreen("settings")} style={{width:32,height:32,borderRadius:8,border:`1px solid ${T.line}`,background:T.raised,color:T.subtle,fontSize:16,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation",display:"flex",alignItems:"center",justifyContent:"center"}}>⚙️</button>
        </div>
      </div>

      {/* Controls */}
      <div style={{background:T.raised,borderBottom:`1px solid ${T.line}`,padding:"8px 12px",position:"sticky",top:44,zIndex:90,transition:"background .3s"}}>
        {isMobile?(
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:"6px 10px"}}>
            <div>{lbl("Symbol")}<select value={symbol} onChange={e=>setSymbol(e.target.value)} style={{...selStyle,width:"100%"}}>{Object.keys(INSTRUMENTS).map(k=><option key={k}>{k}</option>)}</select></div>
            <div>{lbl("Expiry")}<select value={expiry} onChange={e=>setExpiry(e.target.value)} style={{...selStyle,width:"100%"}}>{expiries.map(e=><option key={e}>{e}</option>)}</select></div>
            <div>{lbl("CE Strike")}<select value={ceStrike} onChange={e=>onCeChange(e.target.value)} style={{...selStyle,width:"100%"}}>{strikes.map(s=><option key={s.strike} value={String(s.strike)}>{s.strike}{s.is_atm?" ◀":""}</option>)}</select></div>
            <div>{lbl("PE Strike")}<select value={peStrike} onChange={e=>onPeChange(e.target.value)} style={{...selStyle,width:"100%"}}>{strikes.map(s=><option key={s.strike} value={String(s.strike)}>{s.strike}{s.is_atm?" ◀":""}</option>)}</select></div>
            <div>{lbl("Qty (Lots)")}<div style={{display:"flex",alignItems:"center",background:T.surface,border:`1px solid ${T.line}`,borderRadius:6,height:32}}>
              <button onPointerDown={()=>setQty(q=>Math.max(1,q-1))} style={{flex:1,height:32,background:"none",border:"none",cursor:"pointer",fontWeight:700,fontSize:16,color:T.ink,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>−</button>
              <span style={{fontFamily:mono,minWidth:24,textAlign:"center",fontWeight:700,fontSize:13,color:T.ink}}>{qty}</span>
              <button onPointerDown={()=>setQty(q=>q+1)} style={{flex:1,height:32,background:"none",border:"none",cursor:"pointer",fontWeight:700,fontSize:16,color:T.ink,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>+</button>
            </div></div>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:6}}>
              <div>{lbl("SL Pts")}<input type="number" value={slPts} onChange={e=>setSlPts(+e.target.value)} style={{...selStyle,width:"100%"}}/></div>
              <div>{lbl("Tgt Pts")}<input type="number" value={tgtPts} onChange={e=>setTgtPts(+e.target.value)} style={{...selStyle,width:"100%"}}/></div>
            </div>
          </div>
        ):(
          <div style={{display:"flex",gap:8,alignItems:"flex-end"}}>
            <div>{lbl("Symbol")}<select value={symbol} onChange={e=>setSymbol(e.target.value)} style={{...selStyle,minWidth:80}}>{Object.keys(INSTRUMENTS).map(k=><option key={k}>{k}</option>)}</select></div>
            <div>{lbl("Expiry")}<select value={expiry} onChange={e=>setExpiry(e.target.value)} style={{...selStyle,minWidth:105}}>{expiries.map(e=><option key={e}>{e}</option>)}</select></div>
            <div>{lbl("CE Strike")}<select value={ceStrike} onChange={e=>onCeChange(e.target.value)} style={{...selStyle,minWidth:105}}>{strikes.map(s=><option key={s.strike} value={String(s.strike)}>{s.strike}{s.is_atm?" ◀":""}</option>)}</select></div>
            <div>{lbl("PE Strike")}<select value={peStrike} onChange={e=>onPeChange(e.target.value)} style={{...selStyle,minWidth:105}}>{strikes.map(s=><option key={s.strike} value={String(s.strike)}>{s.strike}{s.is_atm?" ◀":""}</option>)}</select></div>
            <div>{lbl("Qty")}<div style={{display:"flex",alignItems:"center",background:T.surface,border:`1px solid ${T.line}`,borderRadius:6,height:32}}>
              <button onPointerDown={()=>setQty(q=>Math.max(1,q-1))} style={{width:28,height:32,background:"none",border:"none",cursor:"pointer",fontWeight:700,fontSize:16,color:T.ink,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>−</button>
              <span style={{fontFamily:mono,minWidth:24,textAlign:"center",fontWeight:700,fontSize:13,color:T.ink}}>{qty}</span>
              <button onPointerDown={()=>setQty(q=>q+1)} style={{width:28,height:32,background:"none",border:"none",cursor:"pointer",fontWeight:700,fontSize:16,color:T.ink,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>+</button>
            </div></div>
            <div>{lbl("SL Pts")}<input type="number" value={slPts} onChange={e=>setSlPts(+e.target.value)} style={{...selStyle,width:56}}/></div>
            <div>{lbl("Tgt Pts")}<input type="number" value={tgtPts} onChange={e=>setTgtPts(+e.target.value)} style={{...selStyle,width:56}}/></div>
          </div>
        )}
      </div>

      {/* Trading panel — sticky, never moves */}
      <div style={{position:"sticky",top:isMobile?132:80,zIndex:80,background:T.surface,borderBottom:`2px solid ${T.line}`,transition:"background .3s"}}>
        {isMobile?(
          <div>
            <div style={{padding:"10px 12px",borderBottom:`1px solid ${T.line}`,display:"flex",justifyContent:"space-between",alignItems:"center"}}>
              <div>
                <div style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase",marginBottom:2}}>{symbol} Spot</div>
                <div ref={el=>spotRef.current=el} style={{fontFamily:mono,fontSize:28,fontWeight:700,color:T.ink,lineHeight:1}}>{indexLtp?.toLocaleString("en-IN",{maximumFractionDigits:2})||"—"}</div>
                <div style={{fontFamily:mono,fontSize:11,fontWeight:600,color:indexChg>=0?T.up:T.down,marginTop:2}}>{indexChg>=0?"+":""}{indexChg.toFixed(2)} ({indexPct>=0?"+":""}{indexPct.toFixed(2)}%)</div>
              </div>
              <div style={{padding:"8px 12px",border:`1px solid ${T.line}`,borderRadius:8,background:T.raised,textAlign:"right"}}>
                <div style={{fontFamily:mono,fontSize:7,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase",marginBottom:3}}>Pragnya</div>
                <div style={{fontFamily:mono,fontSize:14,fontWeight:700,color:dscore>=80?T.up:dscore>=50?T.warn:T.down,marginBottom:3}}>{dscore}/100</div>
                <div style={{background:T.line,borderRadius:100,height:3,width:80}}><div style={{width:`${dscore}%`,height:"100%",background:dscore>=80?T.up:dscore>=50?T.warn:T.down,borderRadius:100}}/></div>
                <div style={{fontFamily:mono,fontSize:8,color:T.subtle,marginTop:3}}>{st.trades_taken||0}/{cfg.max_trades_per_day||4} trades</div>
              </div>
            </div>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",borderBottom:`1px solid ${T.line}`}}>
              <div style={{padding:"10px",borderRight:`1px solid ${T.line}`}}>
                <div style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase",marginBottom:2}}>{symbol} {ceStrike} CE</div>
                <div ref={el=>ceLtpRef.current=el} style={{fontFamily:mono,fontSize:30,fontWeight:700,color:T.ink,lineHeight:1,marginBottom:2}}>{ceLtp!=null?ceLtp:"—"}</div>
                <div style={{fontFamily:mono,fontSize:8,color:T.subtle,marginBottom:10}}>Lot {instr.lot} · {instr.expiry_day}</div>
                <div style={{display:"flex",flexDirection:"column",gap:6}}>
                  <ExecBtn text="← Sell Call" sub={ceLtp?`₹${ceLtp}`:""} onClick={()=>execute("Sell Call")} color={T.sell}/>
                  <ExecBtn text="↑ Buy Call"  sub={ceLtp?`₹${ceLtp}`:""} onClick={()=>execute("Buy Call")}  color={T.buy}/>
                </div>
              </div>
              <div style={{padding:"10px"}}>
                <div style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase",marginBottom:2,textAlign:"right"}}>{symbol} {peStrike} PE</div>
                <div ref={el=>peLtpRef.current=el} style={{fontFamily:mono,fontSize:30,fontWeight:700,color:T.ink,lineHeight:1,marginBottom:2,textAlign:"right"}}>{peLtp!=null?peLtp:"—"}</div>
                <div style={{fontFamily:mono,fontSize:8,color:T.subtle,marginBottom:10,textAlign:"right"}}>VIX {vix?.toFixed(2)||"—"}</div>
                <div style={{display:"flex",flexDirection:"column",gap:6}}>
                  <ExecBtn text="Sell Put →" sub={peLtp?`₹${peLtp}`:""} onClick={()=>execute("Sell Put")} color={T.sell}/>
                  <ExecBtn text="↓ Buy Put"  sub={peLtp?`₹${peLtp}`:""} onClick={()=>execute("Buy Put")}  color={T.buy}/>
                </div>
              </div>
            </div>
            <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8,padding:"8px 10px"}}>
              <button onPointerDown={closeAll} style={{minHeight:36,borderRadius:8,border:`1.5px solid ${T.sell}`,background:"transparent",color:T.sell,fontFamily:inter,fontWeight:700,fontSize:13,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Close All</button>
              <button onPointerDown={async()=>{
              const r = await apiFetch("/vajra/orders/cancel-all",{method:"POST"})
              if(r?.status==="ok") toast$(`Cancelled ${r.cancelled} order${r.cancelled!==1?"s":""}`, true)
              else toast$("Cancel failed — check broker connection", false)
            }} style={{minHeight:36,borderRadius:8,border:`1.5px solid ${T.line}`,background:"transparent",color:T.body,fontFamily:inter,fontWeight:600,fontSize:12,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Cancel Orders</button>
            </div>
          </div>
        ):(
          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr 1fr"}}>
            <div style={{padding:"14px",borderRight:`1px solid ${T.line}`}}>
              <div style={{fontFamily:mono,fontSize:9,fontWeight:600,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase",marginBottom:3}}>{symbol} {ceStrike} CE</div>
              <div ref={el=>ceLtpRef.current=el} style={{fontFamily:mono,fontSize:42,fontWeight:700,color:T.ink,lineHeight:1,marginBottom:3}}>{ceLtp!=null?ceLtp:"—"}</div>
              <div style={{fontFamily:mono,fontSize:9,color:T.subtle,marginBottom:14}}>Lot {instr.lot} · {instr.expiry_day}</div>
              <div style={{display:"flex",flexDirection:"column",gap:8}}>
                <ExecBtn text="← Sell Call" sub={ceLtp?`@ ₹${ceLtp}`:""} onClick={()=>execute("Sell Call")} color={T.sell}/>
                <ExecBtn text="↑ Buy Call"  sub={ceLtp?`@ ₹${ceLtp}`:""} onClick={()=>execute("Buy Call")}  color={T.buy}/>
              </div>
            </div>
            <div style={{padding:"14px",display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"space-between",textAlign:"center",borderRight:`1px solid ${T.line}`}}>
              <div>
                <div style={{fontFamily:mono,fontSize:9,fontWeight:600,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase",marginBottom:3}}>{symbol} Spot</div>
                <div ref={el=>spotRef.current=el} style={{fontFamily:mono,fontSize:40,fontWeight:700,color:T.ink,lineHeight:1}}>{indexLtp?.toLocaleString("en-IN",{maximumFractionDigits:2})||"—"}</div>
                <div style={{fontFamily:mono,fontSize:13,fontWeight:600,color:indexChg>=0?T.up:T.down,marginTop:5}}>{indexChg>=0?"+":""}{indexChg.toFixed(2)} ({indexPct>=0?"+":""}{indexPct.toFixed(2)}%)</div>
              </div>
              <div style={{width:"100%",display:"flex",flexDirection:"column",gap:6,margin:"10px 0"}}>
                <button onPointerDown={closeAll} style={{minHeight:36,borderRadius:8,border:`1.5px solid ${T.sell}`,background:"transparent",color:T.sell,fontFamily:inter,fontWeight:700,fontSize:13,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Close All Positions</button>
                <button onPointerDown={async()=>{
              const r = await apiFetch("/vajra/orders/cancel-all",{method:"POST"})
              if(r?.status==="ok") toast$(`Cancelled ${r.cancelled} order${r.cancelled!==1?"s":""}`, true)
              else toast$("Cancel failed — check broker connection", false)
            }} style={{minHeight:36,borderRadius:8,border:`1.5px solid ${T.line}`,background:"transparent",color:T.body,fontFamily:inter,fontWeight:600,fontSize:12,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Cancel All Orders</button>
              </div>
              <div style={{width:"100%",padding:"8px 10px",border:`1px solid ${T.line}`,borderRadius:8,background:T.raised}}>
                <div style={{display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:4}}>
                  <span style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase"}}>Pragnya</span>
                  <span style={{fontFamily:mono,fontSize:11,fontWeight:700,color:dscore>=80?T.up:dscore>=50?T.warn:T.down}}>{dscore}/100</span>
                </div>
                <div style={{background:T.line,borderRadius:100,height:3}}><div style={{width:`${dscore}%`,height:"100%",background:dscore>=80?T.up:dscore>=50?T.warn:T.down,borderRadius:100}}/></div>
                <div style={{display:"flex",justifyContent:"space-between",marginTop:4,fontFamily:mono,fontSize:9,color:T.subtle}}>
                  <span>Trades {st.trades_taken||0}/{cfg.max_trades_per_day||4}</span>
                  <span>SL {st.sl_hits||0}/{cfg.max_sl_hits||2}</span>
                </div>
              </div>
              <div style={{fontFamily:mono,fontSize:9,color:T.subtle,marginTop:6}}>{expiry}</div>
            </div>
            <div style={{padding:"14px"}}>
              <div style={{fontFamily:mono,fontSize:9,fontWeight:600,color:T.subtle,letterSpacing:"1px",textTransform:"uppercase",marginBottom:3,textAlign:"right"}}>{symbol} {peStrike} PE</div>
              <div ref={el=>peLtpRef.current=el} style={{fontFamily:mono,fontSize:42,fontWeight:700,color:T.ink,lineHeight:1,marginBottom:3,textAlign:"right"}}>{peLtp!=null?peLtp:"—"}</div>
              <div style={{fontFamily:mono,fontSize:9,color:T.subtle,marginBottom:14,textAlign:"right"}}>VIX {vix?.toFixed(2)||"—"}</div>
              <div style={{display:"flex",flexDirection:"column",gap:8}}>
                <ExecBtn text="Sell Put →" sub={peLtp?`@ ₹${peLtp}`:""} onClick={()=>execute("Sell Put")} color={T.sell}/>
                <ExecBtn text="↓ Buy Put"  sub={peLtp?`@ ₹${peLtp}`:""} onClick={()=>execute("Buy Put")}  color={T.buy}/>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Tabs + Positions — natural page scroll */}
      <div style={{padding:"0 12px 80px"}}>
        <div style={{display:"flex",alignItems:"center",borderBottom:`1px solid ${T.line}`}}>
          {[["positions","Positions"],["orders","Orders"],["journal","Trade Book"]].map(([k,l])=>(
            <button key={k} onPointerDown={()=>setTab(k)} style={{minHeight:40,padding:"0 12px",border:"none",borderBottom:tab===k?`2px solid ${T.brand}`:"2px solid transparent",background:"none",color:tab===k?T.brand:T.subtle,fontFamily:inter,fontWeight:600,fontSize:12,cursor:"pointer",marginBottom:-1,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>{l}</button>
          ))}
          <div style={{marginLeft:"auto",display:"flex",alignItems:"center",gap:6}}>
            <span style={{fontFamily:mono,fontSize:9,color:T.subtle}}>MTM</span>
            <span style={{fontFamily:mono,fontSize:13,fontWeight:700,color:dayPnl>=0?T.up:T.down}}>{dayPnl>=0?"+":""}₹{Math.abs(dayPnl).toLocaleString()}</span>
          </div>
        </div>

        <div>

          {tab==="positions"&&(
            <div>
              {/* Fixed header — always visible */}
              <div style={{display:"grid",gridTemplateColumns:"2fr .7fr .7fr .7fr .8fr 1fr",padding:"7px 4px",background:T.raised,borderBottom:`1px solid ${T.line}`,position:"sticky",top:0,zIndex:10}}>
                {["SYMBOL","QTY","AVG","LTP","MTM","ACTION"].map(h=>(
                  <div key={h} style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1px"}}>{h}</div>
                ))}
              </div>
              {grouped.length===0
                ?<div style={{padding:"40px",textAlign:"center",color:T.subtle,fontSize:13}}>No open positions</div>
                :grouped.map(g=>{
                  const ltp = g.instrument.includes("CE") ? ceLtp : peLtp
                  const mtm = ltp ? (g.direction==="SELL" ? g.avgEntry-ltp : ltp-g.avgEntry) * g.totalQty : 0
                  const count = g.ids.length
                  return(
                    <div key={g.key} style={{display:"grid",gridTemplateColumns:"2fr .7fr .7fr .7fr .8fr 1fr",padding:"9px 4px",borderBottom:`1px solid ${T.line}`,alignItems:"center",background:T.surface}}>
                      <div>
                        <div style={{fontFamily:mono,fontWeight:700,fontSize:11,color:T.ink}}>{g.instrument}</div>
                        <div style={{fontSize:10,color:g.direction==="SELL"?T.sell:T.buy,fontWeight:600}}>
                          {g.direction}{count>1?` ×${count}`:""}
                        </div>
                      </div>
                      <div style={{fontFamily:mono,fontSize:11,color:T.ink}}>{g.totalQty}</div>
                      <div style={{fontFamily:mono,fontSize:11,color:T.ink}}>{g.avgEntry.toFixed(0)}</div>
                      <div style={{fontFamily:mono,fontSize:11,color:T.ink}}>{ltp||"—"}</div>
                      <div style={{fontFamily:mono,fontSize:11,fontWeight:700,color:mtm>=0?T.up:T.down}}>{mtm>=0?"+":""}₹{Math.round(mtm)}</div>
                      <div style={{display:"flex",gap:4}}>
                        <button onPointerDown={()=>exitGroup(g.ids,ltp,g.sl,"EXIT",mtm)}
                          style={{minHeight:28,padding:"0 6px",borderRadius:5,border:"none",background:T.buy,color:"#fff",fontSize:10,fontWeight:600,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>Exit</button>
                        <button onPointerDown={()=>exitGroup(g.ids,ltp,g.sl,"SL",mtm)}
                          style={{minHeight:28,padding:"0 6px",borderRadius:5,border:"none",background:T.sell,color:"#fff",fontSize:10,fontWeight:600,cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>SL</button>
                      </div>
                    </div>
                  )
                })
              }
            </div>
          )}

          {/* ── Options Intelligence Panel ── */}
          {tab==="positions"&&(
            <div style={{marginTop:12}}>

              {/* Trend Bar */}
              {trend&&(
                <div style={{padding:"10px 14px",borderRadius:10,marginBottom:10,
                  background:trend.bias==="BULLISH"?T.buy+"18":trend.bias==="BEARISH"?T.sell+"18":T.raised,
                  border:`1px solid ${trend.bias==="BULLISH"?T.buy+"44":trend.bias==="BEARISH"?T.sell+"44":T.line}`,
                  display:"flex",alignItems:"center",justifyContent:"space-between"}}>
                  <div style={{display:"flex",alignItems:"center",gap:10}}>
                    <span style={{fontSize:18}}>{trend.bias==="BULLISH"?"▲":trend.bias==="BEARISH"?"▼":"◆"}</span>
                    <div>
                      <div style={{fontFamily:mono,fontSize:13,fontWeight:700,color:trend.bias==="BULLISH"?T.buy:trend.bias==="BEARISH"?T.sell:T.subtle}}>{trend.bias}</div>
                      <div style={{fontFamily:mono,fontSize:8,color:T.subtle}}>{trend.regime==="MARKET_CLOSED"?"Market Closed":trend.regime+" VOL"} · ATR {trend.atr||"—"}</div>
                    </div>
                  </div>
                  <div style={{textAlign:"right"}}>
                    <div style={{fontFamily:mono,fontSize:11,fontWeight:700,color:T.ink}}>{trend.confidence}%</div>
                    <div style={{background:T.line,borderRadius:100,height:4,width:60,marginTop:3}}>
                      <div style={{width:`${trend.confidence}%`,height:"100%",borderRadius:100,background:trend.bias==="BULLISH"?T.buy:trend.bias==="BEARISH"?T.sell:T.subtle}}/>
                    </div>
                  </div>
                </div>
              )}

              {/* Options Intelligence */}
              {heatmap&&(
                <div style={{background:T.surface,borderRadius:12,border:`1px solid ${T.line}`,overflow:"hidden",marginBottom:12}}>

                  {/* Header */}
                  <div style={{padding:"10px 12px",borderBottom:`1px solid ${T.line}`,display:"flex",justifyContent:"space-between",alignItems:"center",background:T.raised}}>
                    <div style={{display:"flex",alignItems:"center",gap:8}}>
                      <span style={{fontFamily:mono,fontSize:8,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase"}}>Options Intelligence</span>
                      <span style={{padding:"2px 7px",borderRadius:8,fontFamily:mono,fontSize:9,fontWeight:700,
                        background:heatmap.overall_bias==="BULLISH"?T.buy+"22":heatmap.overall_bias==="BEARISH"?T.sell+"22":T.line,
                        color:heatmap.overall_bias==="BULLISH"?T.buy:heatmap.overall_bias==="BEARISH"?T.sell:T.subtle}}>
                        {heatmap.overall_bias}
                      </span>
                      <span style={{fontFamily:mono,fontSize:9,fontWeight:700,color:heatmap.pcr>1.2?T.buy:heatmap.pcr<0.8?T.sell:T.subtle}}>PCR {heatmap.pcr}</span>
                    </div>
                    <div style={{display:"flex",gap:6,alignItems:"center"}}>
                      <select value={hmExpiry} onChange={e=>{setHmExpiry(e.target.value);fetchHeatmap(e.target.value)}}
                        style={{fontFamily:mono,fontSize:9,color:T.ink,background:T.raised,border:`1px solid ${T.line}`,borderRadius:4,padding:"2px 4px",outline:"none"}}>
                        {(heatmap.all_expiries||[]).map(ex=>(<option key={ex} value={ex}>{ex.slice(5)}</option>))}
                      </select>
                      <button onPointerDown={()=>fetchHeatmap(hmExpiry)} style={{fontFamily:mono,fontSize:10,color:T.brand,background:"none",border:`1px solid ${T.brand}33`,borderRadius:4,padding:"2px 7px",cursor:"pointer",WebkitTapHighlightColor:"transparent"}}>↻</button>
                    </div>
                  </div>

                  {/* Tab bar */}
                  <div style={{display:"flex",background:T.raised,borderBottom:`1px solid ${T.line}`}}>
                    {["OI Change","Pullers/Draggers","OI Walls","Intervals"].map((t,i)=>(
                      <button key={t} onPointerDown={()=>{setOiTab(i);if(i===1)fetchStocks(symbol)}}
                        style={{flex:1,minHeight:32,border:"none",borderBottom:oiTab===i?`2px solid ${T.brand}`:"2px solid transparent",
                          background:"none",color:oiTab===i?T.brand:T.subtle,fontFamily:inter,fontWeight:600,fontSize:9,
                          cursor:"pointer",WebkitTapHighlightColor:"transparent",touchAction:"manipulation",padding:"0 2px"}}>
                        {t}
                      </button>
                    ))}
                  </div>

                  {/* ── TAB 0: OI Change — color heatmap table ── */}
                  {oiTab===0&&(()=>{
                    const rows = heatmap.heatmap||[]
                    const maxChg = Math.max(...rows.map(r=>Math.max(Math.abs(r.ce_chg||0),Math.abs(r.pe_chg||0))),1)
                    const fmtL = v=>{const a=Math.abs(v);return(v>=0?"+":"-")+(a>=100000?(a/100000).toFixed(1)+"L":a>=1000?(a/1000).toFixed(0)+"K":a)}
                    const cellBg = (v,side)=>{
                      if(!v) return "transparent"
                      const intensity = Math.min(1, Math.abs(v)/maxChg)
                      if(side==="ce") return v>0?`rgba(198,40,40,${0.1+intensity*0.5})`:`rgba(46,125,50,${0.1+intensity*0.4})`
                      else return v>0?`rgba(46,125,50,${0.1+intensity*0.5})`:`rgba(198,40,40,${0.1+intensity*0.4})`
                    }
                    return(
                    <div>
                      <div style={{display:"grid",gridTemplateColumns:"1fr 56px 56px 56px 1fr",padding:"5px 8px",background:T.raised,borderBottom:`1px solid ${T.line}`}}>
                        {["CE OI Δ","CE LTP","STRIKE","PE LTP","PE OI Δ"].map(h=>(
                          <div key={h} style={{fontFamily:mono,fontSize:7,color:T.subtle,fontWeight:700,textAlign:"center"}}>{h}</div>
                        ))}
                      </div>
                      {rows.map(row=>(
                        <div key={row.strike} style={{display:"grid",gridTemplateColumns:"1fr 56px 56px 56px 1fr",
                          borderBottom:`1px solid ${T.line}22`,
                          background:row.is_atm?T.brand+"0A":"transparent"}}>
                          <div style={{background:cellBg(row.ce_chg,"ce"),padding:"6px 6px",display:"flex",alignItems:"center",justifyContent:"center"}}>
                            <span style={{fontFamily:mono,fontSize:9,fontWeight:row.ce_chg?700:400,
                              color:row.ce_chg>0?T.sell:row.ce_chg<0?T.buy:T.subtle}}>
                              {row.ce_chg?fmtL(row.ce_chg):"—"}
                            </span>
                          </div>
                          <div style={{padding:"6px 2px",display:"flex",alignItems:"center",justifyContent:"center"}}>
                            <span style={{fontFamily:mono,fontSize:9,color:T.body}}>{row.ce_ltp||"—"}</span>
                          </div>
                          <div style={{padding:"6px 2px",display:"flex",alignItems:"center",justifyContent:"center",
                            background:row.is_atm?T.brand+"20":"transparent"}}>
                            <span style={{fontFamily:mono,fontSize:row.is_atm?11:9,fontWeight:row.is_atm?700:500,
                              color:row.is_atm?T.brand:T.body}}>{row.strike}</span>
                          </div>
                          <div style={{padding:"6px 2px",display:"flex",alignItems:"center",justifyContent:"center"}}>
                            <span style={{fontFamily:mono,fontSize:9,color:T.body}}>{row.pe_ltp||"—"}</span>
                          </div>
                          <div style={{background:cellBg(row.pe_chg,"pe"),padding:"6px 6px",display:"flex",alignItems:"center",justifyContent:"center"}}>
                            <span style={{fontFamily:mono,fontSize:9,fontWeight:row.pe_chg?700:400,
                              color:row.pe_chg>0?T.buy:row.pe_chg<0?T.sell:T.subtle}}>
                              {row.pe_chg?fmtL(row.pe_chg):"—"}
                            </span>
                          </div>
                        </div>
                      ))}
                      <div style={{display:"grid",gridTemplateColumns:"1fr 56px 56px 56px 1fr",padding:"7px 8px",background:T.raised,borderTop:`1px solid ${T.line}`}}>
                        <div style={{textAlign:"center",fontFamily:mono,fontSize:9,fontWeight:700,color:heatmap.total_ce_chg>0?T.sell:T.buy}}>
                          {heatmap.total_ce_chg?(heatmap.total_ce_chg>0?"+":"")+Math.round(heatmap.total_ce_chg/1000)+"K":"—"}
                        </div>
                        <div/><div style={{textAlign:"center",fontFamily:mono,fontSize:8,color:T.subtle}}>TOTAL</div><div/>
                        <div style={{textAlign:"center",fontFamily:mono,fontSize:9,fontWeight:700,color:heatmap.total_pe_chg>0?T.buy:T.sell}}>
                          {heatmap.total_pe_chg?(heatmap.total_pe_chg>0?"+":"")+Math.round(heatmap.total_pe_chg/1000)+"K":"—"}
                        </div>
                      </div>
                    </div>
                  )})()}

                  {/* ── TAB 1: OI Walls ── */}
                  {oiTab===2&&(()=>{
                    const rows = heatmap.heatmap||[]
                    const maxOi = Math.max(...rows.map(r=>Math.max(r.ce_oi||0,r.pe_oi||0)),1)
                    const fmtOi = v=>v>=10000000?(v/10000000).toFixed(1)+"Cr":v>=100000?(v/100000).toFixed(1)+"L":v>=1000?(v/1000).toFixed(0)+"K":v
                    const ceWalls = heatmap.ce_walls||[]
                    const peWalls = heatmap.pe_walls||[]
                    return(
                    <div>
                      <div style={{display:"flex",gap:8,padding:"8px"}}>
                        <div style={{flex:1,padding:"8px",background:T.sell+"0F",borderRadius:8,border:`1px solid ${T.sell}33`}}>
                          <div style={{fontFamily:mono,fontSize:7,color:T.sell,letterSpacing:"1px",marginBottom:5}}>🔴 CE WALLS (RESISTANCE)</div>
                          {ceWalls.map((s,i)=>(<div key={s} style={{fontFamily:mono,fontSize:12,fontWeight:700,color:T.sell,marginBottom:2}}>{["①","②","③"][i]} {s}</div>))}
                        </div>
                        <div style={{flex:1,padding:"8px",background:T.buy+"0F",borderRadius:8,border:`1px solid ${T.buy}33`}}>
                          <div style={{fontFamily:mono,fontSize:7,color:T.buy,letterSpacing:"1px",marginBottom:5}}>🟢 PE WALLS (SUPPORT)</div>
                          {peWalls.map((s,i)=>(<div key={s} style={{fontFamily:mono,fontSize:12,fontWeight:700,color:T.buy,marginBottom:2}}>{["①","②","③"][i]} {s}</div>))}
                        </div>
                      </div>
                      <div style={{padding:"0 8px 8px"}}>
                        {rows.map(row=>{
                          const cePct = (row.ce_oi/maxOi)*100
                          const pePct = (row.pe_oi/maxOi)*100
                          const isCeWall = ceWalls.includes(row.strike)
                          const isPeWall = peWalls.includes(row.strike)
                          return(
                          <div key={row.strike} style={{display:"grid",gridTemplateColumns:"1fr 56px 1fr",gap:4,marginBottom:3,alignItems:"center",
                            background:row.is_atm?T.brand+"0A":isCeWall?T.sell+"08":isPeWall?T.buy+"08":"transparent",
                            borderRadius:4,padding:"3px 4px"}}>
                            <div style={{display:"flex",justifyContent:"flex-end",alignItems:"center",gap:4}}>
                              <span style={{fontFamily:mono,fontSize:8,color:isCeWall?T.sell:T.subtle,fontWeight:isCeWall?700:400,minWidth:28,textAlign:"right"}}>{fmtOi(row.ce_oi)}</span>
                              <div style={{height:isCeWall?10:6,borderRadius:"3px 0 0 3px",
                                background:isCeWall?T.sell:T.sell+"55",
                                width:Math.max(2,cePct*0.7)}}/>
                            </div>
                            <div style={{textAlign:"center",fontFamily:mono,fontSize:row.is_atm?11:9,fontWeight:row.is_atm?700:400,
                              color:row.is_atm?T.brand:T.body}}>{row.strike}</div>
                            <div style={{display:"flex",alignItems:"center",gap:4}}>
                              <div style={{height:isPeWall?10:6,borderRadius:"0 3px 3px 0",
                                background:isPeWall?T.buy:T.buy+"55",
                                width:Math.max(2,pePct*0.7)}}/>
                              <span style={{fontFamily:mono,fontSize:8,color:isPeWall?T.buy:T.subtle,fontWeight:isPeWall?700:400,minWidth:28}}>{fmtOi(row.pe_oi)}</span>
                            </div>
                          </div>
                        )})}
                      </div>
                    </div>
                  )})()}

                  {/* ── TAB 2: IV Skew ── */}

                  {/* ── TAB 3: Intervals ── */}
                  {oiTab===3&&(
                    <div style={{padding:"8px 0"}}>
                      <div style={{display:"grid",gridTemplateColumns:"52px 1fr 72px 72px",padding:"4px 12px",background:T.raised,borderBottom:`1px solid ${T.line}`}}>
                        {["TIME","BIAS","CE ΔOI","PE ΔOI"].map(h=>(<div key={h} style={{fontFamily:mono,fontSize:7,color:T.subtle,fontWeight:700}}>{h}</div>))}
                      </div>
                      {(heatmap.intervals||[]).length===0
                        ?<div style={{textAlign:"center",padding:"28px",color:T.subtle,fontSize:12,fontFamily:inter}}>Interval data builds during market hours</div>
                        :(heatmap.intervals||[]).map((iv,i)=>{
                          const bc = iv.bias==="BULLISH"?T.buy:iv.bias==="BEARISH"?T.sell:T.subtle
                          const fmtK = v=>(v>=0?"+":"-")+Math.round(Math.abs(v)/1000)+"K"
                          return(
                          <div key={i} style={{display:"grid",gridTemplateColumns:"52px 1fr 72px 72px",padding:"8px 12px",
                            borderBottom:`1px solid ${T.line}22`,background:i===0?T.brand+"06":"transparent",alignItems:"center"}}>
                            <div style={{fontFamily:mono,fontSize:10,color:T.subtle}}>{iv.time}</div>
                            <div><span style={{display:"inline-block",padding:"2px 8px",borderRadius:8,fontFamily:mono,fontSize:9,fontWeight:700,
                              background:bc+"22",color:bc,border:`1px solid ${bc}44`}}>
                              {iv.bias==="BULLISH"?"▲":iv.bias==="BEARISH"?"▼":"—"} {iv.bias}
                            </span></div>
                            <div style={{fontFamily:mono,fontSize:9,fontWeight:600,color:iv.ce_chg>0?T.sell:T.buy}}>{fmtK(iv.ce_chg)}</div>
                            <div style={{fontFamily:mono,fontSize:9,fontWeight:600,color:iv.pe_chg>0?T.buy:T.sell}}>{fmtK(iv.pe_chg)}</div>
                          </div>
                        )})
                      }
                    </div>
                  )}

                  {/* ── TAB 1: Pullers / Draggers — Squarified Treemap ── */}
                  {oiTab===1&&(()=>{
                    // Squarified treemap algorithm
                    const squarify = (items, rect) => {
                      if (!items.length) return []
                      const totalVal = items.reduce((s,i)=>s+i.value,0)
                      const rectArea = rect.w * rect.h
                      const tiles = []
                      let remaining = [...items]
                      let r = {...rect}
                      while (remaining.length) {
                        const isHoriz = r.w >= r.h
                        const side = isHoriz ? r.h : r.w
                        let row = [], rowVal = 0, bestRatio = Infinity
                        for (let i=0; i<remaining.length; i++) {
                          const item = remaining[i]
                          rowVal += item.value
                          row.push(item)
                          const rowArea = (rowVal/totalVal)*rectArea
                          const rowSide = rowArea/side
                          const ratio = Math.max(...row.map(it=>{
                            const tileArea = (it.value/totalVal)*rectArea
                            const tileOther = tileArea/rowSide
                            return Math.max(rowSide/tileOther, tileOther/rowSide)
                          }))
                          if (ratio > bestRatio) { row.pop(); rowVal -= item.value; break }
                          bestRatio = ratio
                        }
                        // Layout row tiles
                        const rowArea = (rowVal/totalVal)*rectArea
                        const rowSide = rowArea/side
                        let pos = isHoriz ? r.y : r.x
                        for (const item of row) {
                          const tileArea = (item.value/totalVal)*rectArea
                          const tileOther = tileArea/rowSide
                          tiles.push({
                            ...item,
                            x: isHoriz ? r.x : pos,
                            y: isHoriz ? pos : r.y,
                            w: isHoriz ? rowSide : tileOther,
                            h: isHoriz ? tileOther : rowSide,
                          })
                          pos += tileOther
                        }
                        // Shrink rect
                        if (isHoriz) { r = {...r, x:r.x+rowSide, w:r.w-rowSide} }
                        else         { r = {...r, y:r.y+rowSide, h:r.h-rowSide} }
                        remaining = remaining.slice(row.length)
                      }
                      return tiles
                    }

                    const chgColor = (chg, dark) => {
                      const cap = 2
                      const t = Math.min(1, Math.abs(chg)/cap)
                      if (chg > 0) return dark
                        ? `rgba(46,125,50,${0.25+t*0.65})`
                        : `rgba(46,125,50,${0.15+t*0.6})`
                      if (chg < 0) return dark
                        ? `rgba(198,40,40,${0.25+t*0.65})`
                        : `rgba(198,40,40,${0.15+t*0.6})`
                      return dark ? '#2A2A2A' : '#E8E4DE'
                    }

                    const W = 340, H = 220
                    const stockList = stocks?.stocks || []
                    const items = stockList.map(s=>({
                      symbol: s.symbol, name: s.name,
                      sector: s.sector, weight: s.weight,
                      chg: s.chg_pct||0, ltp: s.ltp,
                      value: s.weight
                    })).sort((a,b)=>b.value-a.value)

                    const tiles = squarify(items, {x:0,y:0,w:W,h:H})
                    const top3 = [...stockList].sort((a,b)=>b.chg_pct-a.chg_pct).slice(0,3)
                    const bot3 = [...stockList].sort((a,b)=>a.chg_pct-b.chg_pct).slice(0,3)

                    return(
                    <div style={{padding:"8px"}}>
                      {!stocks
                        ?<div style={{textAlign:"center",padding:"28px",color:T.subtle,fontSize:12}}>Loading...</div>
                        :<div>
                          {/* Treemap SVG */}
                          <div style={{fontFamily:mono,fontSize:7,color:T.subtle,letterSpacing:"1px",marginBottom:6,textTransform:"uppercase"}}>{stocks.symbol} Constituents · Tile size = Index weight · Color = % change</div>
                          <svg viewBox={`0 0 ${W} ${H}`} style={{width:"100%",borderRadius:8,display:"block",marginBottom:8}} preserveAspectRatio="xMidYMid meet">
                            {tiles.map((t,i)=>{
                              const bg = chgColor(t.chg, dark)
                              const textCol = "#fff"
                              const showSymbol = t.w > 40 && t.h > 20
                              const showChg   = t.w > 40 && t.h > 32
                              const fs = Math.min(10, Math.max(6, t.w/6))
                              return(
                              <g key={t.symbol}>
                                <rect x={t.x+1} y={t.y+1} width={Math.max(0,t.w-2)} height={Math.max(0,t.h-2)}
                                  fill={bg} rx={2}/>
                                {showSymbol&&<text x={t.x+t.w/2} y={t.y+t.h/2-(showChg?5:0)}
                                  textAnchor="middle" dominantBaseline="middle"
                                  fill={textCol} fontSize={fs} fontWeight="700" fontFamily="monospace"
                                  style={{pointerEvents:"none"}}>
                                  {t.symbol}
                                </text>}
                                {showChg&&<text x={t.x+t.w/2} y={t.y+t.h/2+8}
                                  textAnchor="middle" dominantBaseline="middle"
                                  fill={textCol} fontSize={Math.max(6,fs-1)} fontFamily="monospace"
                                  style={{pointerEvents:"none"}}>
                                  {t.chg>=0?"+":""}{t.chg.toFixed(1)}%
                                </text>}
                              </g>
                            )})}
                          </svg>
                          {/* Pullers & Draggers summary */}
                          <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:6}}>
                            <div style={{padding:"8px",background:T.buy+"11",borderRadius:8,border:`1px solid ${T.buy}33`}}>
                              <div style={{fontFamily:mono,fontSize:7,color:T.buy,letterSpacing:"1px",marginBottom:5}}>▲ PULLERS</div>
                              {top3.map(s=>(
                                <div key={s.symbol} style={{display:"flex",justifyContent:"space-between",marginBottom:3}}>
                                  <span style={{fontFamily:mono,fontSize:9,fontWeight:700,color:T.ink}}>{s.symbol}</span>
                                  <span style={{fontFamily:mono,fontSize:9,fontWeight:700,color:T.buy}}>+{s.chg_pct?.toFixed(2)}%</span>
                                </div>
                              ))}
                            </div>
                            <div style={{padding:"8px",background:T.sell+"11",borderRadius:8,border:`1px solid ${T.sell}33`}}>
                              <div style={{fontFamily:mono,fontSize:7,color:T.sell,letterSpacing:"1px",marginBottom:5}}>▼ DRAGGERS</div>
                              {bot3.map(s=>(
                                <div key={s.symbol} style={{display:"flex",justifyContent:"space-between",marginBottom:3}}>
                                  <span style={{fontFamily:mono,fontSize:9,fontWeight:700,color:T.ink}}>{s.symbol}</span>
                                  <span style={{fontFamily:mono,fontSize:9,fontWeight:700,color:T.sell}}>{s.chg_pct?.toFixed(2)}%</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                      }
                    </div>
                  )})()}

                  {/* Footer */}
                  <div style={{padding:"6px 12px",borderTop:`1px solid ${T.line}`,display:"flex",justifyContent:"space-between",background:T.raised}}>
                    <span style={{fontFamily:mono,fontSize:8,color:T.subtle}}>Updated {heatmap.last_updated||"—"}</span>
                    <div style={{display:"flex",gap:8,fontFamily:mono,fontSize:8}}>
                      <span style={{color:T.sell}}>CE {heatmap.total_ce_oi>=100000?(heatmap.total_ce_oi/100000).toFixed(1)+"L":"—"}</span>
                      <span style={{color:T.subtle}}>·</span>
                      <span style={{color:T.buy}}>PE {heatmap.total_pe_oi>=100000?(heatmap.total_pe_oi/100000).toFixed(1)+"L":"—"}</span>
                    </div>
                  </div>

                </div>
              )}
            </div>
          )}

          {tab==="orders"&&<OrdersTab T={T} mono={mono} inter={inter} refreshRef={refreshOrdersRef}/>}

          {tab==="journal"&&(
            <div>
              <div style={{display:"grid",gridTemplateColumns:"2fr .6fr .7fr .7fr .8fr .6fr",padding:"7px 4px",background:T.raised,borderBottom:`1px solid ${T.line}`,position:"sticky",top:0,zIndex:10}}>
                {["SYMBOL","DIR","ENTRY","EXIT","P&L","TIME"].map(h=>(
                  <div key={h} style={{fontFamily:mono,fontSize:8,fontWeight:600,color:T.subtle,letterSpacing:"1px"}}>{h}</div>
                ))}
              </div>
              {(pragnya?.trades||[]).filter(t=>t.status==="CLOSED").length===0
                ?<div style={{padding:"40px",textAlign:"center",color:T.subtle,fontSize:13}}>No closed trades today</div>
                :(pragnya?.trades||[]).filter(t=>t.status==="CLOSED").map(t=>(
                  <div key={t.id} style={{display:"grid",gridTemplateColumns:"2fr .6fr .7fr .7fr .8fr .6fr",padding:"9px 4px",borderBottom:`1px solid ${T.line}`,alignItems:"center",background:t.pnl>=0?(dark?"#0A1A0A":"#F6FBF6"):(dark?"#1A0A0A":"#FDF6F6")}}>
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
        </div>
      </div>
    </div>
  )
}
