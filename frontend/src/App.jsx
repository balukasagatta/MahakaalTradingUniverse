import { useState, useEffect, useRef, useCallback } from "react"

const API = "https://mtutrade.in/api"

// ── Constants from real Upstox data ───────────────────────────────────────────
const INSTRUMENTS = {
  SENSEX: {
    key:        "BSE_INDEX|SENSEX",
    fo_segment: "BSE_FO",
    lot:        20,
    step:       100,
    expiry_day: "Thursday",
    tick:       5,
  },
  NIFTY: {
    key:        "NSE_INDEX|Nifty 50",
    fo_segment: "NSE_FO",
    lot:        65,
    step:       50,
    expiry_day: "Tuesday",
    tick:       0.05,
  },
}

const BROKERS = ["Upstox", "Dhan", "Kotak Neo", "Zerodha", "Angel", "Fyers"]

// ── Colors ─────────────────────────────────────────────────────────────────────
const C = {
  bg:     "#F5F4F0", white: "#FFFFFF", ink: "#1A1916",
  muted:  "#9B9689", border: "#E2E0D8", orange: "#E8540A",
  green:  "#1A7F4B", red: "#C0392B", amber: "#B45309",
  bgMid:  "#ECEAE4", greenBg: "#D1FAE5", redBg: "#FEE2E2",
}

const mono = { fontFamily: "'IBM Plex Mono', monospace" }
const sans = { fontFamily: "'IBM Plex Sans', sans-serif" }

// ── API helpers ────────────────────────────────────────────────────────────────
async function apiFetch(path, opts = {}) {
  try {
    const r = await fetch(`${API}${path}`, {
      headers: { "Content-Type": "application/json" }, ...opts,
    })
    return r.json()
  } catch (e) {
    return { error: e.message }
  }
}

async function upstoxGet(path) {
  const r = await apiFetch(`/vajra/upstox${path}`)
  return r
}

// ── Small components ───────────────────────────────────────────────────────────
function Badge({ children, color = "gray", sm }) {
  const map = {
    green:  [C.greenBg, "#065F46"],
    red:    [C.redBg,   "#991B1B"],
    amber:  ["#FEF3C7", "#92400E"],
    blue:   ["#DBEAFE", "#1E40AF"],
    gray:   ["#F3F2EE", "#5C5A54"],
    orange: ["#FFF1E6", "#C2410C"],
  }
  const [bg, fg] = map[color] || map.gray
  return (
    <span style={{ ...mono, display: "inline-flex", alignItems: "center",
      padding: sm ? "2px 6px" : "3px 8px", borderRadius: 4,
      background: bg, color: fg, fontSize: sm ? 9 : 10, fontWeight: 600, letterSpacing: 0.5 }}>
      {children}
    </span>
  )
}

function Btn({ children, onClick, color = "default", full, sm, disabled }) {
  const styles = {
    default: { bg: C.white,  fg: C.ink,   bd: C.border },
    green:   { bg: C.green,  fg: "#fff",  bd: C.green  },
    red:     { bg: C.red,    fg: "#fff",  bd: C.red    },
    orange:  { bg: C.orange, fg: "#fff",  bd: C.orange },
    ghost:   { bg: "transparent", fg: C.muted, bd: C.border },
    sell:    { bg: C.red,    fg: "#fff",  bd: C.red    },
    buy:     { bg: C.green,  fg: "#fff",  bd: C.green  },
  }
  const { bg, fg, bd } = styles[color] || styles.default
  return (
    <button onClick={onClick} disabled={disabled} style={{
      ...sans, background: bg, color: fg, border: `1.5px solid ${bd}`,
      borderRadius: 6, padding: sm ? "6px 10px" : "9px 14px",
      fontWeight: 700, fontSize: sm ? 11 : 13,
      cursor: disabled ? "not-allowed" : "pointer",
      opacity: disabled ? 0.5 : 1,
      width: full ? "100%" : "auto", transition: "all .1s",
      whiteSpace: "nowrap",
    }}>
      {children}
    </button>
  )
}

function Select({ value, onChange, options, label }) {
  return (
    <div>
      {label && <div style={{ ...mono, fontSize: 8, letterSpacing: 1.5, textTransform: "uppercase", color: C.muted, marginBottom: 3 }}>{label}</div>}
      <select value={value} onChange={e => onChange(e.target.value)} style={{
        ...mono, fontSize: 12, fontWeight: 600, color: C.ink,
        border: `1.5px solid ${C.border}`, borderRadius: 6,
        padding: "6px 8px", background: C.white, width: "100%", cursor: "pointer",
      }}>
        {options.map(o => <option key={o.value || o} value={o.value || o}>{o.label || o}</option>)}
      </select>
    </div>
  )
}

function NumInput({ value, onChange, label, min = 1 }) {
  return (
    <div>
      {label && <div style={{ ...mono, fontSize: 8, letterSpacing: 1.5, textTransform: "uppercase", color: C.muted, marginBottom: 3 }}>{label}</div>}
      <div style={{ display: "flex", alignItems: "center", border: `1.5px solid ${C.border}`, borderRadius: 6, background: C.white, overflow: "hidden" }}>
        <button onClick={() => onChange(Math.max(min, value - 1))} style={{ ...mono, padding: "6px 10px", background: "none", border: "none", cursor: "pointer", color: C.ink, fontWeight: 700 }}>−</button>
        <span style={{ ...mono, flex: 1, textAlign: "center", fontSize: 13, fontWeight: 700, color: C.ink }}>{value}</span>
        <button onClick={() => onChange(value + 1)} style={{ ...mono, padding: "6px 10px", background: "none", border: "none", cursor: "pointer", color: C.ink, fontWeight: 700 }}>+</button>
      </div>
    </div>
  )
}

function ProgBar({ pct }) {
  const c = pct < 50 ? C.green : pct < 80 ? C.amber : C.red
  return (
    <div style={{ background: C.bgMid, borderRadius: 100, height: 4, overflow: "hidden" }}>
      <div style={{ width: `${Math.min(100, pct)}%`, height: "100%", background: c, borderRadius: 100, transition: "width .3s" }} />
    </div>
  )
}

// ── Main App ───────────────────────────────────────────────────────────────────
export default function App() {
  const [tab,       setTab]       = useState("trade")
  const [broker,    setBroker]    = useState("")
  const [symbol,    setSymbol]    = useState("SENSEX")
  const [expiries,  setExpiries]  = useState([])
  const [expiry,    setExpiry]    = useState("")
  const [ceStrike,  setCeStrike]  = useState(null)
  const [peStrike,  setPeStrike]  = useState(null)
  const [strikes,   setStrikes]   = useState([])
  const [qty,       setQty]       = useState(1)
  const [orderType, setOrderType] = useState("Market Protection")
  const [slPts,     setSlPts]     = useState(20)
  const [tgtPts,    setTgtPts]    = useState(20)

  // Live prices
  const [sensex,    setSensex]    = useState(null)
  const [nifty,     setNifty]     = useState(null)
  const [vix,       setVix]       = useState(null)
  const [ceLtp,     setCeLtp]     = useState(null)
  const [peLtp,     setPeLtp]     = useState(null)
  const [ceHiLo,    setCeHiLo]    = useState({ h: 0, l: 0 })
  const [peHiLo,    setPeHiLo]    = useState({ h: 0, l: 0 })

  // PRAGNYA
  const [pragnya,   setPragnya]   = useState(null)
  const [positions, setPositions] = useState([])
  const [msg,       setMsg]       = useState(null)

  // Overlays
  const [showBroker,  setShowBroker]  = useState(true)
  const [showGita,    setShowGita]    = useState(false)
  const [gitaReason,  setGitaReason]  = useState("")

  const instr = INSTRUMENTS[symbol]

  const flash = (text, type = "ok") => {
    setMsg({ text, type })
    setTimeout(() => setMsg(null), 3000)
  }

  // ── Fetch expiries ────────────────────────────────────────────────────────
  useEffect(() => {
    if (!broker) return
    async function load() {
      const r = await apiFetch(`/sutra/expiries?index=${symbol}`)
      if (r.expiries?.length) {
        const weekly = r.expiries.slice(0, 8)
        setExpiries(weekly)
        setExpiry(weekly[0])
      }
    }
    load()
  }, [symbol, broker])

  // ── Fetch option chain when expiry changes ────────────────────────────────
  useEffect(() => {
    if (!expiry || !broker) return
    async function load() {
      const r = await apiFetch(`/sutra/chain?index=${symbol}&expiry=${expiry}`)
      if (r.strikes?.length) {
        setStrikes(r.strikes)
        const atm = r.atm
        const atmRow = r.strikes.find(s => s.is_atm) || r.strikes[Math.floor(r.strikes.length / 2)]
        // CE: 1 step OTM above ATM, PE: 1 step OTM below ATM
        const ceRow = r.strikes.find(s => s.strike === atm + instr.step) || atmRow
        const peRow = r.strikes.find(s => s.strike === atm - instr.step) || atmRow
        setCeStrike(ceRow?.strike || atm)
        setPeStrike(peRow?.strike || atm)
      }
    }
    load()
  }, [expiry, symbol, broker])

  // ── Live price poll ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!broker) return
    async function poll() {
      const r = await apiFetch("/vajra/market")
      if (r.sensex?.ltp) setSensex(r.sensex)
      if (r.vix?.ltp)    setVix(r.vix.ltp)
      // Fetch Nifty separately
      const nr = await apiFetch("/sutra/chain?index=NIFTY&expiry=" + (expiries[0] || ""))
      if (nr.spot) setNifty({ ltp: nr.spot })
    }
    poll()
    const t = setInterval(poll, 5000)
    return () => clearInterval(t)
  }, [broker, expiries])

  // ── Poll option LTPs ──────────────────────────────────────────────────────
  useEffect(() => {
    if (!expiry || !ceStrike || !peStrike || !broker) return
    async function pollOptions() {
      const r = await apiFetch(`/sutra/chain?index=${symbol}&expiry=${expiry}`)
      if (r.strikes) {
        const ce = r.strikes.find(s => s.strike === ceStrike)
        const pe = r.strikes.find(s => s.strike === peStrike)
        if (ce) { setCeLtp(ce.ce.ltp); setCeHiLo({ h: ce.ce.ltp * 1.5, l: ce.ce.ltp * 0.5 }) }
        if (pe) { setPeLtp(pe.pe.ltp); setPeHiLo({ h: pe.pe.ltp * 1.5, l: pe.pe.ltp * 0.5 }) }
      }
    }
    pollOptions()
    const t = setInterval(pollOptions, 3000)
    return () => clearInterval(t)
  }, [expiry, ceStrike, peStrike, symbol, broker])

  // ── Fetch PRAGNYA state ───────────────────────────────────────────────────
  useEffect(() => {
    if (!broker) return
    async function loadPragnya() {
      const r = await apiFetch("/vajra/state")
      if (r.state) setPragnya(r)
      if (r.trades) setPositions(r.trades.filter(t => t.status === "OPEN"))
    }
    loadPragnya()
    const t = setInterval(loadPragnya, 10000)
    return () => clearInterval(t)
  }, [broker])

  // ── Execute order ─────────────────────────────────────────────────────────
  async function execute(type) {
    if (!broker) { flash("Select broker first", "err"); return }
    const strike = type.includes("Call") ? ceStrike : peStrike
    const action = type.includes("Sell") ? "SELL" : "BUY"
    const optType = type.includes("Call") ? "CE" : "PE"
    const ltp     = type.includes("Call") ? ceLtp : peLtp
    const instrument = `${symbol}${strike}${optType}`

    const r = await apiFetch("/vajra/trade/open", {
      method: "POST",
      body: JSON.stringify({
        instrument, direction: action,
        entry: ltp, sl: action === "SELL" ? ltp + slPts : ltp - slPts,
        target: action === "SELL" ? ltp - tgtPts : ltp + tgtPts,
        lots: qty, strategy: `${action} ${optType}`,
      }),
    })
    if (r.status === "ok") {
      flash(`✓ ${type} @ ₹${ltp} | ${qty} lot${qty > 1 ? "s" : ""}`)
      const pr = await apiFetch("/vajra/state")
      if (pr.trades) setPositions(pr.trades.filter(t => t.status === "OPEN"))
    } else {
      flash(r.detail || "Order failed", "err")
      if (r.detail?.includes("locked") || r.detail?.includes("Cannot")) {
        setGitaReason(r.detail)
        setShowGita(true)
      }
    }
  }

  async function closePosition(tradeId, exitPrice, reason) {
    const r = await apiFetch("/vajra/trade/close", {
      method: "POST",
      body: JSON.stringify({ trade_id: tradeId, exit_price: exitPrice, exit_reason: reason }),
    })
    if (r.status === "ok") {
      flash(`Closed: ${r.pnl >= 0 ? "+" : ""}₹${r.pnl?.toFixed(0)}`)
      const pr = await apiFetch("/vajra/state")
      if (pr.trades) setPositions(pr.trades.filter(t => t.status === "OPEN"))
      setPragnya(pr)
    }
  }

  async function killSwitch() {
    await apiFetch("/vajra/kill", { method: "POST" })
    setGitaReason("Kill switch activated")
    setShowGita(true)
    const pr = await apiFetch("/vajra/state")
    setPragnya(pr)
  }

  const indexLtp   = symbol === "SENSEX" ? sensex?.ltp : nifty?.ltp
  const indexClose = symbol === "SENSEX" ? sensex?.close : 0
  const indexChg   = indexLtp && indexClose ? indexLtp - indexClose : sensex?.change || 0
  const indexPct   = indexLtp && indexClose ? ((indexChg / indexClose) * 100) : sensex?.pct || 0

  const st      = pragnya?.state || {}
  const cfg     = pragnya?.cfg   || {}
  const dscore  = st.discipline_score || 100
  const dayPnl  = st.daily_pnl || 0
  const quote   = pragnya?.quote || {}

  const now = new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false })

  // ── BROKER SELECTOR OVERLAY ───────────────────────────────────────────────
  if (showBroker) return (
    <div style={{ background: C.bg, minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", padding: 24 }}>
      <div style={{ background: C.white, border: `1px solid ${C.border}`, borderRadius: 14, padding: 32, width: "100%", maxWidth: 380 }}>
        <div style={{ ...mono, fontSize: 20, fontWeight: 700, color: C.ink, marginBottom: 4 }}>
          ⚡ <span style={{ color: C.orange }}>VAJRA</span>
        </div>
        <div style={{ ...mono, fontSize: 9, color: C.muted, letterSpacing: 2, textTransform: "uppercase", marginBottom: 24 }}>
          Scalping Terminal · Select Broker
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 24 }}>
          {BROKERS.map(b => (
            <button key={b} onClick={() => setBroker(b)} style={{
              ...sans, padding: "12px", borderRadius: 8, fontWeight: 600, fontSize: 13,
              border: `1.5px solid ${broker === b ? C.orange : C.border}`,
              background: broker === b ? "#FFF1E6" : C.white,
              color: broker === b ? C.orange : C.ink, cursor: "pointer",
            }}>{b}</button>
          ))}
        </div>
        {/* Gita quote */}
        <div style={{ background: C.bg, borderRadius: 8, padding: 14, marginBottom: 20 }}>
          <div style={{ fontSize: 11, color: "#3D3B35", fontStyle: "italic", lineHeight: 1.6 }}>
            "{quote.text || "Perform your duty equipoised, abandoning all attachment."}"
          </div>
          <div style={{ ...mono, fontSize: 9, color: C.muted, marginTop: 6, letterSpacing: 1 }}>
            — {quote.src || "Bhagavad Gita 2.48"}
          </div>
        </div>
        <Btn full color="orange" onClick={() => { if (broker) setShowBroker(false); else flash("Select a broker", "err") }}>
          Continue with {broker || "broker"} →
        </Btn>
      </div>
    </div>
  )

  // ── GITA OVERLAY (kill / lock) ─────────────────────────────────────────────
  if (showGita) return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(245,244,240,0.97)", zIndex: 99999,
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 32 }}>
      <div style={{ fontSize: 48, marginBottom: 16 }}>🕉️</div>
      <div style={{ ...mono, fontSize: 20, fontWeight: 700, color: C.red, marginBottom: 8 }}>PRAGNYA ACTIVATED</div>
      <div style={{ fontSize: 13, color: C.muted, marginBottom: 28, textAlign: "center" }}>{gitaReason}</div>
      <div style={{ background: C.bg, borderRadius: 8, padding: 16, maxWidth: 380, marginBottom: 24 }}>
        <div style={{ fontSize: 12, color: "#3D3B35", fontStyle: "italic", lineHeight: 1.6 }}>"{quote.text}"</div>
        <div style={{ ...mono, fontSize: 9, color: C.muted, marginTop: 6, letterSpacing: 1 }}>— {quote.src}</div>
      </div>
      <Btn onClick={() => setShowGita(false)} color="ghost">Close</Btn>
    </div>
  )

  // ── MAIN TERMINAL ──────────────────────────────────────────────────────────
  return (
    <div style={{ background: C.bg, minHeight: "100vh", ...sans, paddingBottom: 60 }}>

      {/* ── TOP BAR ── */}
      <div style={{ background: C.white, borderBottom: `1px solid ${C.border}`, padding: "6px 12px",
        display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ ...mono, fontSize: 16, fontWeight: 700, color: C.ink }}>
            ⚡ <span style={{ color: C.orange }}>VAJRA</span>
          </div>
          <button onClick={() => setShowBroker(true)} style={{
            ...sans, fontSize: 11, fontWeight: 600, padding: "4px 10px", borderRadius: 20,
            border: `1.5px solid ${C.orange}`, background: "#FFF1E6", color: C.orange, cursor: "pointer",
          }}>🔗 {broker}</button>
        </div>

        {/* Index LTPs */}
        <div style={{ display: "flex", gap: 20, alignItems: "center" }}>
          {[
            ["SENSEX", sensex?.ltp, sensex?.change, sensex?.pct],
            ["NIFTY",  nifty?.ltp,  0, 0],
            ["VIX",    vix, 0, 0],
          ].map(([name, ltp, chg, pct]) => (
            <div key={name} style={{ textAlign: "center" }}>
              <div style={{ ...mono, fontSize: 8, color: C.muted, letterSpacing: 1, textTransform: "uppercase" }}>{name}</div>
              <div style={{ ...mono, fontSize: 14, fontWeight: 700, color: chg >= 0 ? C.green : chg < 0 ? C.red : C.ink }}>
                {ltp ? ltp.toLocaleString("en-IN", { maximumFractionDigits: 2 }) : "—"}
              </div>
              {chg !== 0 && <div style={{ ...mono, fontSize: 9, color: chg >= 0 ? C.green : C.red }}>
                {chg >= 0 ? "+" : ""}{chg?.toFixed(1)} ({pct >= 0 ? "+" : ""}{pct?.toFixed(2)}%)
              </div>}
            </div>
          ))}
        </div>

        <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
          <div style={{ textAlign: "right" }}>
            <div style={{ ...mono, fontSize: 8, color: C.muted, letterSpacing: 1 }}>DAY P&L</div>
            <div style={{ ...mono, fontSize: 14, fontWeight: 700, color: dayPnl >= 0 ? C.green : C.red }}>
              {dayPnl >= 0 ? "+" : ""}₹{Math.abs(dayPnl).toLocaleString()}
            </div>
          </div>
          <div style={{ textAlign: "right" }}>
            <div style={{ ...mono, fontSize: 8, color: C.muted, letterSpacing: 1 }}>PRAGNYA</div>
            <div style={{ ...mono, fontSize: 14, fontWeight: 700, color: dscore >= 80 ? C.green : dscore >= 50 ? C.amber : C.red }}>
              {dscore}/100
            </div>
          </div>
          <div style={{ ...mono, fontSize: 11, color: C.muted }}>{now}</div>
        </div>
      </div>

      {/* ── MSG BANNER ── */}
      {msg && (
        <div style={{ background: msg.type === "ok" ? C.greenBg : C.redBg, padding: "8px 16px",
          fontSize: 12, fontWeight: 600, color: msg.type === "ok" ? "#065F46" : "#991B1B",
          borderBottom: `1px solid ${msg.type === "ok" ? "#6EE7B7" : "#FECACA"}` }}>
          {msg.text}
        </div>
      )}

      {/* ── INSTRUMENT SELECTOR ROW ── */}
      <div style={{ background: C.white, borderBottom: `1px solid ${C.border}`, padding: "8px 12px",
        display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(100px, 1fr))", gap: 8, alignItems: "end" }}>
        <Select label="Symbol" value={symbol} onChange={setSymbol}
          options={Object.keys(INSTRUMENTS).map(k => ({ value: k, label: k }))} />
        <Select label="Expiry" value={expiry} onChange={setExpiry}
          options={expiries.map(e => ({ value: e, label: e }))} />
        <Select label="CE Strike" value={ceStrike || ""} onChange={v => setCeStrike(Number(v))}
          options={strikes.map(s => ({ value: s.strike, label: `${s.strike}${s.is_atm ? " ◀ATM" : ""}` }))} />
        <Select label="PE Strike" value={peStrike || ""} onChange={v => setPeStrike(Number(v))}
          options={strikes.map(s => ({ value: s.strike, label: `${s.strike}${s.is_atm ? " ◀ATM" : ""}` }))} />
        <NumInput label="Qty (Lots)" value={qty} onChange={setQty} />
        <Select label="Order Type" value={orderType} onChange={setOrderType}
          options={["Market Protection", "Limit", "Market"]} />
        <div>
          <div style={{ ...mono, fontSize: 8, color: C.muted, letterSpacing: 1, textTransform: "uppercase", marginBottom: 3 }}>SL Pts</div>
          <input type="number" value={slPts} onChange={e => setSlPts(+e.target.value)}
            style={{ ...mono, width: "100%", border: `1.5px solid ${C.border}`, borderRadius: 6, padding: "6px 8px", fontSize: 12, background: C.white }} />
        </div>
        <div>
          <div style={{ ...mono, fontSize: 8, color: C.muted, letterSpacing: 1, textTransform: "uppercase", marginBottom: 3 }}>Tgt Pts</div>
          <input type="number" value={tgtPts} onChange={e => setTgtPts(+e.target.value)}
            style={{ ...mono, width: "100%", border: `1.5px solid ${C.border}`, borderRadius: 6, padding: "6px 8px", fontSize: 12, background: C.white }} />
        </div>
      </div>

      {/* ── TRADING PANEL ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1.2fr 1fr", gap: 0, margin: "10px 12px" }}>

        {/* CE Side */}
        <div style={{ background: C.white, border: `1px solid ${C.border}`, borderRadius: "10px 0 0 10px",
          padding: 14, borderRight: "none" }}>
          <div style={{ ...mono, fontSize: 9, color: C.muted, letterSpacing: 1.5, textTransform: "uppercase", marginBottom: 8 }}>
            {symbol} {ceStrike} CE
          </div>
          <div style={{ ...mono, fontSize: 28, fontWeight: 700, color: C.ink, marginBottom: 2 }}>
            {ceLtp?.toFixed(1) || "—"}
          </div>
          <div style={{ ...mono, fontSize: 10, color: C.muted, marginBottom: 16 }}>
            L: {ceHiLo.l?.toFixed(1) || "—"} &nbsp; H: {ceHiLo.h?.toFixed(1) || "—"}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <Btn full color="sell" onClick={() => execute("Sell Call")}>← Sell Call</Btn>
            <Btn full color="buy"  onClick={() => execute("Buy Call")} >↑ Buy Call</Btn>
          </div>
          <div style={{ marginTop: 12, ...mono, fontSize: 9, color: C.muted }}>
            Lot: {instr.lot} &nbsp;|&nbsp; Tick: {instr.tick}
          </div>
        </div>

        {/* Center — Index */}
        <div style={{ background: C.white, border: `1px solid ${C.border}`, padding: 14, textAlign: "center",
          display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <div style={{ ...mono, fontSize: 10, color: C.muted, letterSpacing: 1.5, textTransform: "uppercase", marginBottom: 4 }}>{symbol}</div>
            <div style={{ ...mono, fontSize: 32, fontWeight: 700, color: C.ink, lineHeight: 1 }}>
              {indexLtp ? indexLtp.toLocaleString("en-IN", { maximumFractionDigits: 2 }) : "—"}
            </div>
            <div style={{ ...mono, fontSize: 12, color: indexChg >= 0 ? C.green : C.red, marginTop: 4, fontWeight: 600 }}>
              {indexChg >= 0 ? "+" : ""}{indexChg?.toFixed(2)} ({indexPct >= 0 ? "+" : ""}{indexPct?.toFixed(2)}%)
            </div>
          </div>

          <div style={{ width: "100%", margin: "12px 0" }}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
              <Btn full sm color="red" onClick={killSwitch}>🛑 Kill</Btn>
              <Btn full sm color="ghost" onClick={() => { setShowGita(true); setGitaReason("Meditation break") }}>🕉️ Gita</Btn>
            </div>
          </div>

          {/* PRAGNYA mini */}
          <div style={{ width: "100%", background: C.bg, borderRadius: 8, padding: "8px 10px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
              <span style={{ ...mono, fontSize: 8, color: C.muted, letterSpacing: 1, textTransform: "uppercase" }}>PRAGNYA</span>
              <span style={{ ...mono, fontSize: 10, fontWeight: 700, color: dscore >= 80 ? C.green : dscore >= 50 ? C.amber : C.red }}>{dscore}/100</span>
            </div>
            <ProgBar pct={100 - dscore} />
            <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, ...mono, fontSize: 9, color: C.muted }}>
              <span>Trades: {st.trades_taken || 0}/{cfg.max_trades_per_day || 4}</span>
              <span>SL: {st.sl_hits || 0}/{cfg.max_sl_hits || 2}</span>
            </div>
          </div>

          <div style={{ ...mono, fontSize: 9, color: C.muted, marginTop: 8 }}>
            Expiry: {expiry} &nbsp;|&nbsp; {instr.expiry_day}
          </div>
        </div>

        {/* PE Side */}
        <div style={{ background: C.white, border: `1px solid ${C.border}`, borderRadius: "0 10px 10px 0",
          padding: 14, borderLeft: "none" }}>
          <div style={{ ...mono, fontSize: 9, color: C.muted, letterSpacing: 1.5, textTransform: "uppercase", marginBottom: 8, textAlign: "right" }}>
            {symbol} {peStrike} PE
          </div>
          <div style={{ ...mono, fontSize: 28, fontWeight: 700, color: C.ink, marginBottom: 2, textAlign: "right" }}>
            {peLtp?.toFixed(1) || "—"}
          </div>
          <div style={{ ...mono, fontSize: 10, color: C.muted, marginBottom: 16, textAlign: "right" }}>
            L: {peHiLo.l?.toFixed(1) || "—"} &nbsp; H: {peHiLo.h?.toFixed(1) || "—"}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <Btn full color="sell" onClick={() => execute("Sell Put")}>Sell Put →</Btn>
            <Btn full color="buy"  onClick={() => execute("Buy Put")} >↓ Buy Put</Btn>
          </div>
          <div style={{ marginTop: 12, ...mono, fontSize: 9, color: C.muted, textAlign: "right" }}>
            VIX: {vix?.toFixed(2) || "—"}
          </div>
        </div>
      </div>

      {/* ── BOTTOM TABS ── */}
      <div style={{ margin: "0 12px" }}>
        <div style={{ display: "flex", borderBottom: `2px solid ${C.border}`, marginBottom: 10 }}>
          {[["trade", "Positions"], ["orders", "Order Book"], ["journal", "Trade Book"], ["config", "Config"]].map(([k, label]) => (
            <button key={k} onClick={() => setTab(k)} style={{
              ...sans, padding: "8px 14px", border: "none", background: "none",
              borderBottom: tab === k ? `2px solid ${C.orange}` : "2px solid transparent",
              color: tab === k ? C.orange : C.muted, fontWeight: 600, fontSize: 12,
              cursor: "pointer", marginBottom: -2,
            }}>{label}</button>
          ))}
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8, paddingRight: 4 }}>
            <span style={{ ...mono, fontSize: 10, color: C.muted }}>MTM:</span>
            <span style={{ ...mono, fontSize: 13, fontWeight: 700, color: dayPnl >= 0 ? C.green : C.red }}>
              {dayPnl >= 0 ? "+" : ""}₹{Math.abs(dayPnl).toLocaleString()}
            </span>
          </div>
        </div>

        {/* Positions tab */}
        {tab === "trade" && (
          <div style={{ background: C.white, border: `1px solid ${C.border}`, borderRadius: 10, overflow: "hidden" }}>
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 1fr 1fr 1.5fr",
              padding: "8px 12px", borderBottom: `1px solid ${C.border}`, background: C.bg }}>
              {["Symbol", "Qty", "Avg", "LTP", "SL", "Target", "Action"].map(h => (
                <div key={h} style={{ ...mono, fontSize: 9, fontWeight: 600, color: C.muted, letterSpacing: 1, textTransform: "uppercase" }}>{h}</div>
              ))}
            </div>
            {positions.length === 0 ? (
              <div style={{ padding: "32px", textAlign: "center", color: C.muted, fontSize: 13 }}>No open positions</div>
            ) : positions.map(p => {
              const lots = JSON.parse(p.extra_json || "{}").lots || 1
              const curLtp = p.instrument.includes("CE") ? ceLtp : peLtp
              const mtm = curLtp ? (p.direction === "SELL" ? p.entry - curLtp : curLtp - p.entry) * instr.lot * lots : 0
              return (
                <div key={p.id} style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 1fr 1fr 1.5fr",
                  padding: "10px 12px", borderBottom: `1px solid ${C.border}`, alignItems: "center" }}>
                  <div>
                    <div style={{ ...mono, fontWeight: 700, fontSize: 12, color: C.ink }}>{p.instrument}</div>
                    <div style={{ fontSize: 10, color: p.direction === "SELL" ? C.red : C.green, fontWeight: 600 }}>{p.direction}</div>
                  </div>
                  <div style={{ ...mono, fontSize: 12 }}>{lots * instr.lot}</div>
                  <div style={{ ...mono, fontSize: 12 }}>{p.entry?.toFixed(1)}</div>
                  <div style={{ ...mono, fontSize: 12, color: mtm >= 0 ? C.green : C.red, fontWeight: 700 }}>
                    {curLtp?.toFixed(1) || "—"}
                  </div>
                  <div style={{ ...mono, fontSize: 12, color: C.red }}>{p.sl?.toFixed(1)}</div>
                  <div style={{ ...mono, fontSize: 12, color: C.green }}>{p.target_price?.toFixed(1)}</div>
                  <div style={{ display: "flex", gap: 4 }}>
                    <Btn sm color="green" onClick={() => closePosition(p.id, curLtp || p.target_price, "TARGET")}>Exit</Btn>
                    <Btn sm color="red"   onClick={() => closePosition(p.id, p.sl, "SL")}>SL</Btn>
                  </div>
                </div>
              )
            })}
            {positions.length > 0 && (
              <div style={{ padding: "10px 12px", display: "flex", justifyContent: "space-between", alignItems: "center",
                borderTop: `1px solid ${C.border}`, background: C.bg }}>
                <span style={{ ...mono, fontSize: 11, color: C.muted }}>
                  Net Buy: {positions.filter(p => p.direction === "BUY").length} &nbsp;|&nbsp;
                  Net Sell: {positions.filter(p => p.direction === "SELL").length}
                </span>
                <Btn sm color="red" onClick={() => positions.forEach(p => closePosition(p.id, p.sl, "SL"))}>
                  Close All
                </Btn>
              </div>
            )}
          </div>
        )}

        {/* Order Book */}
        {tab === "orders" && (
          <div style={{ background: C.white, border: `1px solid ${C.border}`, borderRadius: 10, padding: 32, textAlign: "center", color: C.muted, fontSize: 13 }}>
            Order book syncs with {broker} API — coming in Phase 2
          </div>
        )}

        {/* Trade Book */}
        {tab === "journal" && (
          <div style={{ background: C.white, border: `1px solid ${C.border}`, borderRadius: 10, overflow: "hidden" }}>
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 1fr 1fr",
              padding: "8px 12px", borderBottom: `1px solid ${C.border}`, background: C.bg }}>
              {["Symbol", "Dir", "Entry", "Exit", "P&L", "Time"].map(h => (
                <div key={h} style={{ ...mono, fontSize: 9, fontWeight: 600, color: C.muted, letterSpacing: 1, textTransform: "uppercase" }}>{h}</div>
              ))}
            </div>
            {(pragnya?.trades || []).filter(t => t.status === "CLOSED").length === 0 ? (
              <div style={{ padding: 32, textAlign: "center", color: C.muted, fontSize: 13 }}>No closed trades today</div>
            ) : (pragnya?.trades || []).filter(t => t.status === "CLOSED").map(t => (
              <div key={t.id} style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 1fr 1fr",
                padding: "10px 12px", borderBottom: `1px solid ${C.border}`, alignItems: "center" }}>
                <div style={{ ...mono, fontWeight: 700, fontSize: 12 }}>{t.instrument}</div>
                <Badge sm color={t.direction === "SELL" ? "red" : "green"}>{t.direction}</Badge>
                <div style={{ ...mono, fontSize: 12 }}>{t.entry?.toFixed(1)}</div>
                <div style={{ ...mono, fontSize: 12 }}>{t.exit_price?.toFixed(1) || "—"}</div>
                <div style={{ ...mono, fontSize: 12, fontWeight: 700, color: t.pnl >= 0 ? C.green : C.red }}>
                  {t.pnl >= 0 ? "+" : ""}₹{t.pnl?.toFixed(0)}
                </div>
                <div style={{ ...mono, fontSize: 11, color: C.muted }}>{t.time?.slice(0,5)}</div>
              </div>
            ))}
          </div>
        )}

        {/* Config */}
        {tab === "config" && (
          <div style={{ background: C.white, border: `1px solid ${C.border}`, borderRadius: 10, padding: 16 }}>
            <div style={{ ...mono, fontSize: 11, fontWeight: 700, color: C.ink, marginBottom: 12, letterSpacing: 1, textTransform: "uppercase" }}>PRAGNYA Rules</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              {[
                ["Max Trades/Day", cfg.max_trades_per_day],
                ["Daily Loss Limit ₹", cfg.daily_loss_limit],
                ["Daily Target ₹", cfg.daily_target],
                ["Max SL Hits", cfg.max_sl_hits],
                ["Cooling After SL (min)", cfg.cooling_minutes_after_sl],
                ["SL Points", cfg.sl_points],
              ].map(([label, val]) => (
                <div key={label}>
                  <div style={{ ...mono, fontSize: 8, color: C.muted, letterSpacing: 1.5, textTransform: "uppercase", marginBottom: 3 }}>{label}</div>
                  <div style={{ ...mono, fontSize: 14, fontWeight: 700, color: C.ink }}>{val}</div>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 16, paddingTop: 16, borderTop: `1px solid ${C.border}` }}>
              <div style={{ ...mono, fontSize: 9, color: C.muted, letterSpacing: 1, marginBottom: 8, textTransform: "uppercase" }}>Today's Gita</div>
              <div style={{ fontSize: 12, color: "#3D3B35", fontStyle: "italic", lineHeight: 1.6 }}>"{quote.text}"</div>
              <div style={{ ...mono, fontSize: 9, color: C.muted, marginTop: 6, letterSpacing: 1 }}>— {quote.src}</div>
            </div>
          </div>
        )}
      </div>

      {/* ── BOTTOM NAV ── */}
      <nav style={{ position: "fixed", bottom: 0, left: 0, right: 0, background: C.white,
        borderTop: `1px solid ${C.border}`, display: "flex", zIndex: 9999 }}>
        {[["trade","📋","Positions"],["orders","📒","Orders"],["journal","📊","Trade Book"],["config","⚙️","Config"]].map(([k, icon, label]) => (
          <button key={k} onClick={() => setTab(k)} style={{
            flex: 1, height: 52, border: "none", background: "none", cursor: "pointer",
            borderTop: tab === k ? `2px solid ${C.orange}` : "2px solid transparent",
            color: tab === k ? C.orange : C.muted,
            ...mono, fontSize: 8, fontWeight: 600, letterSpacing: 1, textTransform: "uppercase",
            display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 2,
          }}>
            <span style={{ fontSize: 15 }}>{icon}</span>{label}
          </button>
        ))}
      </nav>
    </div>
  )
}
