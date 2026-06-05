import { useState, useEffect, useRef, useCallback } from "react"
import { LineChart, Line, XAxis, YAxis, Tooltip, ReferenceLine, ResponsiveContainer } from "recharts"

const API = "https://mtutrade.in/api"
const WS  = "wss://mtutrade.in/api/feed/ws"

// ── Hooks ──────────────────────────────────────────────────────────────────────
function useWebSocket(onTick) {
  const ws = useRef(null)
  const reconnect = useRef(null)

  useEffect(() => {
    function connect() {
      ws.current = new WebSocket(WS)
      ws.current.onmessage = (e) => {
        try { const d = JSON.parse(e.data); if (d.type === "tick") onTick(d.data) }
        catch {}
      }
      ws.current.onclose = () => {
        reconnect.current = setTimeout(connect, 3000)
      }
    }
    connect()
    return () => {
      clearTimeout(reconnect.current)
      ws.current?.close()
    }
  }, [])
}

async function apiFetch(path, opts = {}) {
  const r = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  })
  return r.json()
}

// ── Design tokens ──────────────────────────────────────────────────────────────
const C = {
  bg:      "#F5F4F0",
  white:   "#FFFFFF",
  ink:     "#1A1916",
  muted:   "#9B9689",
  border:  "#E2E0D8",
  orange:  "#E8540A",
  green:   "#1A7F4B",
  red:     "#C0392B",
  amber:   "#B45309",
  bgMuted: "#ECEAE4",
}

const s = {
  page:    { background: C.bg, minHeight: "100vh", fontFamily: "'IBM Plex Sans', sans-serif", paddingBottom: 72 },
  card:    { background: C.white, border: `1px solid ${C.border}`, borderRadius: 10, padding: "14px 16px", marginBottom: 10 },
  label:   { fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, fontWeight: 600, letterSpacing: 2, textTransform: "uppercase", color: C.muted, marginBottom: 8, display: "block" },
  mono:    { fontFamily: "'IBM Plex Mono', monospace" },
  tape:    { fontFamily: "'IBM Plex Mono', monospace", fontSize: 26, fontWeight: 700, color: C.ink, lineHeight: 1 },
  tapeSm:  { fontFamily: "'IBM Plex Mono', monospace", fontSize: 18, fontWeight: 700, color: C.ink },
  tapeXs:  { fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, fontWeight: 600, color: C.ink },
}

function Badge({ children, color = "gray" }) {
  const colors = {
    green:  { bg: "#D1FAE5", fg: "#065F46" },
    red:    { bg: "#FEE2E2", fg: "#991B1B" },
    amber:  { bg: "#FEF3C7", fg: "#92400E" },
    blue:   { bg: "#DBEAFE", fg: "#1E40AF" },
    gray:   { bg: "#F3F2EE", fg: "#5C5A54" },
    orange: { bg: "#FFF1E6", fg: "#C2410C" },
  }
  const c = colors[color] || colors.gray
  return (
    <span style={{ display: "inline-flex", alignItems: "center", padding: "3px 8px", borderRadius: 4,
      background: c.bg, color: c.fg, fontFamily: "'IBM Plex Mono', monospace",
      fontSize: 10, fontWeight: 600, letterSpacing: 0.5 }}>
      {children}
    </span>
  )
}

function Btn({ children, onClick, variant = "default", full, disabled }) {
  const variants = {
    default: { background: C.white, color: C.ink, border: `1.5px solid ${C.border}` },
    green:   { background: C.green, color: "#fff", border: `1.5px solid ${C.green}` },
    red:     { background: C.red,   color: "#fff", border: `1.5px solid ${C.red}` },
    orange:  { background: C.orange,color: "#fff", border: `1.5px solid ${C.orange}` },
    ghost:   { background: "transparent", color: C.muted, border: `1px solid ${C.border}` },
  }
  return (
    <button onClick={onClick} disabled={disabled} style={{
      ...variants[variant], borderRadius: 7, padding: "9px 16px",
      fontFamily: "'IBM Plex Sans', sans-serif", fontWeight: 600, fontSize: 13,
      cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.5 : 1,
      width: full ? "100%" : "auto", transition: "all .15s",
    }}>
      {children}
    </button>
  )
}

function ProgBar({ pct, color }) {
  const c = pct < 50 ? C.green : pct < 80 ? C.amber : C.red
  return (
    <div style={{ background: C.bgMuted, borderRadius: 100, height: 5, overflow: "hidden", marginTop: 4 }}>
      <div style={{ width: `${Math.min(100, pct)}%`, height: "100%", background: color || c, borderRadius: 100, transition: "width .3s" }} />
    </div>
  )
}

// ── Main App ───────────────────────────────────────────────────────────────────
export default function App() {
  const [tab,      setTab]      = useState("board")
  const [market,   setMarket]   = useState({ sensex: {}, vix: {} })
  const [state,    setState]    = useState(null)
  const [loading,  setLoading]  = useState(true)
  const [ticks,    setTicks]    = useState([])
  const [breathe,  setBreathe]  = useState(false)
  const [killOvl,  setKillOvl]  = useState(false)
  const [winOvl,   setWinOvl]   = useState(false)
  const [msg,      setMsg]      = useState(null)

  const showMsg = (text, type = "ok") => {
    setMsg({ text, type })
    setTimeout(() => setMsg(null), 3000)
  }

  // WebSocket live feed
  useWebSocket(useCallback((data) => {
    if (data.SENSEX) {
      const ltp = data.SENSEX.ltp
      setMarket(m => ({
        ...m,
        sensex: { ...m.sensex, ltp, ...data.SENSEX },
        vix:    data.VIX || m.vix,
      }))
      setTicks(t => [...t.slice(-59), { t: new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" }), v: ltp }])
    }
  }, []))

  // Fetch state
  const fetchState = useCallback(async () => {
    try {
      const [st, mkt] = await Promise.all([
        apiFetch("/vajra/state"),
        apiFetch("/vajra/market"),
      ])
      setState(st)
      if (mkt.sensex?.ltp) setMarket(mkt)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchState() }, [])
  useEffect(() => { const t = setInterval(fetchState, 15000); return () => clearInterval(t) }, [fetchState])

  if (loading) return (
    <div style={{ ...s.page, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ ...s.mono, color: C.muted, fontSize: 13 }}>Loading VAJRA…</div>
    </div>
  )

  const cfg      = state?.cfg || {}
  const st       = state?.state || {}
  const canTrade = state?.can_trade
  const warnings = state?.warnings || []
  const lock     = state?.lock || {}
  const trades   = state?.trades || []
  const quote    = state?.quote || {}
  const pts      = state?.rewards_pts || 0
  const dscore   = st.discipline_score || 100
  const pnl      = st.daily_pnl || 0
  const openTrades = trades.filter(t => t.status === "OPEN")

  const ltp    = market.sensex?.ltp || 0
  const change = market.sensex?.change || 0
  const pct    = market.sensex?.pct || 0
  const vix    = market.vix?.ltp || 0

  // ── Overlays ────────────────────────────────────────────────────────────────
  if (breathe) return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(245,244,240,0.97)", zIndex: 99999,
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 32 }}>
      <div style={{ ...s.mono, fontSize: 10, letterSpacing: 3, color: C.muted, marginBottom: 28, textTransform: "uppercase" }}>PRAGNYA MIND</div>
      <div style={{ width: 120, height: 120, border: `3px solid ${C.orange}`, borderRadius: "50%",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 36, animation: "pulse 4s ease-in-out infinite" }}>🌬️</div>
      <div style={{ marginTop: 24, fontSize: 15, fontWeight: 600, color: C.ink, textAlign: "center" }}>Take 3 deep breaths</div>
      <div style={{ marginTop: 8, fontSize: 12, color: C.muted, textAlign: "center", maxWidth: 280, lineHeight: 1.6 }}>
        Pre-trade check. Step away 5 minutes. Come back fresh.
      </div>
      <div style={{ background: C.bg, borderRadius: 8, padding: 16, marginTop: 24, maxWidth: 360, textAlign: "left" }}>
        <div style={{ fontSize: 12, color: "#3D3B35", fontStyle: "italic", lineHeight: 1.6 }}>"{quote.text}"</div>
        <div style={{ ...s.mono, fontSize: 9, color: C.muted, marginTop: 6, letterSpacing: 1 }}>— {quote.src}</div>
      </div>
      <div style={{ display: "flex", gap: 10, marginTop: 24, width: "100%", maxWidth: 320 }}>
        <Btn full onClick={() => setBreathe(false)} variant="green">✓ I'm ready</Btn>
        <Btn full onClick={() => setBreathe(false)} variant="ghost">Skip</Btn>
      </div>
      <style>{`@keyframes pulse{0%,100%{transform:scale(1);box-shadow:0 0 0 0 rgba(232,84,10,.3)}50%{transform:scale(1.08);box-shadow:0 0 0 20px rgba(232,84,10,0)}}`}</style>
    </div>
  )

  if (killOvl) return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(245,244,240,0.97)", zIndex: 99999,
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 32 }}>
      <div style={{ fontSize: 48, marginBottom: 16 }}>🕉️</div>
      <div style={{ ...s.mono, fontSize: 22, fontWeight: 700, color: C.red, marginBottom: 8 }}>KILL SWITCH ACTIVE</div>
      <div style={{ fontSize: 13, color: C.muted, marginBottom: 32 }}>Trading stopped for today. Capital protected.</div>
      <div style={{ background: C.bg, borderRadius: 8, padding: 16, maxWidth: 400, textAlign: "left" }}>
        <div style={{ fontSize: 12, color: "#3D3B35", fontStyle: "italic", lineHeight: 1.6 }}>"{quote.text}"</div>
        <div style={{ ...s.mono, fontSize: 9, color: C.muted, marginTop: 6, letterSpacing: 1 }}>— {quote.src}</div>
      </div>
      <div style={{ marginTop: 24 }}>
        <Btn onClick={() => setKillOvl(false)} variant="ghost">Close</Btn>
      </div>
    </div>
  )

  if (winOvl) return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(245,244,240,0.97)", zIndex: 99999,
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 32 }}>
      <div style={{ fontSize: 52, marginBottom: 12 }}>🎯</div>
      <div style={{ ...s.mono, fontSize: 22, fontWeight: 700, color: C.green, marginBottom: 8 }}>TARGET HIT!</div>
      <div style={{ fontSize: 15, fontWeight: 600, color: C.ink, marginBottom: 4 }}>₹{cfg.daily_target?.toLocaleString()} achieved</div>
      <div style={{ fontSize: 12, color: C.muted, marginBottom: 28 }}>A good trader knows when to stop.</div>
      <div style={{ background: "#D1FAE5", borderRadius: 10, padding: "16px 24px", textAlign: "center", marginBottom: 20 }}>
        <div style={{ fontSize: 13, color: "#065F46", fontWeight: 600 }}>Log off now. Protect your gains.</div>
      </div>
      <div style={{ display: "flex", gap: 10 }}>
        <Btn onClick={async () => { await apiFetch("/vajra/kill", { method: "POST" }); setWinOvl(false); fetchState() }} variant="green">✓ Log off</Btn>
        <Btn onClick={() => setWinOvl(false)} variant="ghost">Continue (I know the risk)</Btn>
      </div>
    </div>
  )

  // ── Locked screen ────────────────────────────────────────────────────────────
  if (lock.locked) return (
    <div style={{ ...s.page, maxWidth: 600, margin: "0 auto", padding: "0 16px" }}>
      <Header ltp={ltp} change={change} pct={pct} dscore={dscore} pnl={pnl} trades={st.trades_taken} maxTrades={cfg.max_trades_per_day} />
      <div style={{ background: "#FFFBF5", border: `1.5px solid #FECACA`, borderRadius: 14, padding: "40px 24px", textAlign: "center", margin: "24px 0" }}>
        <div style={{ fontSize: 48, marginBottom: 12 }}>🛑</div>
        <div style={{ ...s.mono, fontSize: 22, fontWeight: 700, color: C.red, marginBottom: 6 }}>TERMINAL LOCKED</div>
        <div style={{ fontSize: 14, color: C.muted, marginBottom: 20 }}>{lock.reason}</div>
        <div style={{ ...s.mono, fontSize: 24, fontWeight: 700, color: pnl >= 0 ? C.green : C.red }}>
          {pnl >= 0 ? "+" : ""}₹{Math.abs(pnl).toLocaleString()}
        </div>
        <div style={{ background: C.bg, borderRadius: 8, padding: 16, textAlign: "left", marginTop: 16 }}>
          <div style={{ fontSize: 12, color: "#3D3B35", fontStyle: "italic", lineHeight: 1.6 }}>"{quote.text}"</div>
          <div style={{ ...s.mono, fontSize: 9, color: C.muted, marginTop: 6, letterSpacing: 1 }}>— {quote.src}</div>
        </div>
      </div>
      <EodCapture product="VAJRA" onDone={fetchState} />
    </div>
  )

  return (
    <div style={s.page}>
      <div style={{ maxWidth: 1200, margin: "0 auto", padding: "0 16px" }}>
        <Header ltp={ltp} change={change} pct={pct} dscore={dscore} pnl={pnl} trades={st.trades_taken} maxTrades={cfg.max_trades_per_day} />

        {msg && (
          <div style={{ background: msg.type === "ok" ? "#D1FAE5" : "#FEE2E2", border: `1px solid ${msg.type === "ok" ? "#6EE7B7" : "#FECACA"}`,
            borderRadius: 6, padding: "8px 12px", marginBottom: 8, fontSize: 12, fontWeight: 500,
            color: msg.type === "ok" ? "#065F46" : "#991B1B" }}>
            {msg.text}
          </div>
        )}

        {warnings.map((w, i) => (
          <div key={i} style={{ background: "#FEF9EC", border: `1px solid #F6D860`, borderLeft: `3px solid #F6A800`,
            borderRadius: 6, padding: "8px 12px", marginBottom: 8, fontSize: 12, color: "#7A4F00", fontWeight: 500 }}>
            ⚠️ {w}
          </div>
        ))}

        {tab === "board" && (
          <Board
            ltp={ltp} change={change} pct={pct} vix={vix} ticks={ticks}
            canTrade={canTrade} cfg={cfg} st={st} openTrades={openTrades}
            quote={quote} pts={pts} dscore={dscore} pnl={pnl}
            onBreathe={() => setBreathe(true)}
            onKill={async () => { await apiFetch("/vajra/kill", { method: "POST" }); setKillOvl(true); fetchState() }}
            onExecute={async (req) => {
              const r = await apiFetch("/vajra/trade/open", { method: "POST", body: JSON.stringify(req) })
              if (r.status === "ok") { showMsg(`Trade opened #${r.trade_id}`); fetchState() }
              else showMsg(r.detail || "Error", "err")
            }}
            onClose={async (req) => {
              const r = await apiFetch("/vajra/trade/close", { method: "POST", body: JSON.stringify(req) })
              if (r.status === "ok") {
                showMsg(`Closed: ${r.pnl >= 0 ? "+" : ""}₹${r.pnl?.toFixed(0)}`)
                if (r.daily_pnl >= cfg.daily_target) setWinOvl(true)
                fetchState()
              }
            }}
          />
        )}
        {tab === "journal"  && <Journal trades={trades} pnl={pnl} onRefresh={fetchState} />}
        {tab === "config"   && <Config cfg={cfg} onSave={async (c) => { await apiFetch("/vajra/config", { method: "POST", body: JSON.stringify(c) }); showMsg("Saved"); fetchState() }} />}
      </div>

      {/* Bottom nav */}
      <nav style={{ position: "fixed", bottom: 0, left: 0, right: 0, display: "flex",
        background: C.white, borderTop: `1px solid ${C.border}`, zIndex: 9999 }}>
        {[["⚡", "Board", "board"], ["📊", "Journal", "journal"], ["⚙️", "Config", "config"]].map(([icon, label, key]) => (
          <button key={key} onClick={() => setTab(key)} style={{
            flex: 1, height: 56, border: "none", background: "transparent", cursor: "pointer",
            borderTop: tab === key ? `2px solid ${C.orange}` : "2px solid transparent",
            color: tab === key ? C.orange : C.muted,
            fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, fontWeight: 600,
            letterSpacing: 1, textTransform: "uppercase", display: "flex",
            flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 2,
          }}>
            <span style={{ fontSize: 16 }}>{icon}</span>{label}
          </button>
        ))}
      </nav>
    </div>
  )
}

// ── Header ─────────────────────────────────────────────────────────────────────
function Header({ ltp, change, pct, dscore, pnl, trades, maxTrades }) {
  const now = new Date().toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })
  const up  = change >= 0
  return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "12px 0 10px", borderBottom: `2px solid ${C.ink}`, marginBottom: 14 }}>
      <div>
        <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 20, fontWeight: 700, color: C.ink }}>
          ⚡ <span style={{ color: C.orange }}>VAJRA</span>
        </div>
        <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: C.muted, letterSpacing: 1, marginTop: 1 }}>
          SCALPING BOARD · {now} IST
        </div>
      </div>
      <div style={{ display: "flex", gap: 20, alignItems: "center" }}>
        <StatBlock label="SENSEX" value={ltp ? ltp.toLocaleString("en-IN") : "—"}
          sub={ltp ? `${up ? "+" : ""}${change?.toFixed(1)} (${up ? "+" : ""}${pct?.toFixed(2)}%)` : ""}
          subColor={up ? C.green : C.red} />
        <StatBlock label="PRAGNYA" value={`${dscore}/100`} valueColor={dscore >= 80 ? C.green : dscore >= 50 ? C.amber : C.red} />
        <StatBlock label="TRADES"  value={`${trades || 0}/${maxTrades || 4}`} />
        <StatBlock label="DAY P&L" value={`${pnl >= 0 ? "+" : ""}₹${Math.abs(pnl || 0).toLocaleString()}`} valueColor={pnl >= 0 ? C.green : C.red} />
      </div>
    </div>
  )
}

function StatBlock({ label, value, sub, subColor, valueColor }) {
  return (
    <div style={{ textAlign: "right" }}>
      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 8, letterSpacing: 1.5, textTransform: "uppercase", color: C.muted }}>{label}</div>
      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 15, fontWeight: 700, color: valueColor || C.ink, lineHeight: 1.1 }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: subColor || C.muted, fontFamily: "'IBM Plex Mono', monospace" }}>{sub}</div>}
    </div>
  )
}

// ── Board ──────────────────────────────────────────────────────────────────────
function Board({ ltp, change, pct, vix, ticks, canTrade, cfg, st, openTrades, quote, pts, dscore, pnl, onBreathe, onKill, onExecute, onClose }) {
  const [dir, setDir] = useState("LONG")

  const tradesPct = Math.min(100, ((st.trades_taken || 0) / (cfg.max_trades_per_day || 4)) * 100)
  const lossPct   = Math.min(100, Math.abs(pnl) / Math.abs(cfg.daily_loss_limit || 2500) * 100)
  const slPct     = Math.min(100, (st.sl_hits || 0) / (cfg.max_sl_hits || 2) * 100)

  return (
    <div style={{ display: "grid", gridTemplateColumns: "3fr 2fr", gap: 12 }}>
      {/* LEFT */}
      <div>
        {/* Sensex tape */}
        <div style={s.card}>
          <span style={s.label}>Live Feed — Sensex</span>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
            <div style={s.tape}>{ltp ? ltp.toLocaleString("en-IN") : "—"}</div>
            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 14, fontWeight: 600, color: change >= 0 ? C.green : C.red }}>
              {change >= 0 ? "+" : ""}{change?.toFixed(1)} ({change >= 0 ? "+" : ""}{pct?.toFixed(2)}%)
            </div>
            <div style={{ marginLeft: "auto" }}>
              <Badge color={vix < 14 ? "green" : vix < 20 ? "amber" : "red"}>VIX {vix?.toFixed(1)}</Badge>
            </div>
          </div>
          {ticks.length > 1 && (
            <div style={{ marginTop: 10, height: 60 }}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={ticks}>
                  <Line type="monotone" dataKey="v" stroke={change >= 0 ? C.green : C.red} dot={false} strokeWidth={1.5} />
                  <Tooltip contentStyle={{ fontSize: 10, fontFamily: "'IBM Plex Mono', monospace" }} formatter={v => [v.toLocaleString("en-IN"), "LTP"]} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {/* Execute panel */}
        <div style={s.card}>
          <span style={s.label}>Execute Trade</span>
          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            {["LONG", "SHORT"].map(d => (
              <button key={d} onClick={() => setDir(d)} style={{
                flex: 1, padding: "10px", borderRadius: 7, border: `1.5px solid ${dir === d ? (d === "LONG" ? C.green : C.red) : C.border}`,
                background: dir === d ? (d === "LONG" ? "#D1FAE5" : "#FEE2E2") : C.white,
                color: dir === d ? (d === "LONG" ? C.green : C.red) : C.muted,
                fontFamily: "'IBM Plex Mono', monospace", fontWeight: 700, fontSize: 13, cursor: "pointer",
              }}>{d === "LONG" ? "▲ LONG" : "▼ SHORT"}</button>
            ))}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginBottom: 12 }}>
            {[
              ["Entry", ltp?.toFixed(1) || "0"],
              ["SL", dir === "LONG" ? ((ltp || 0) - (cfg.sl_points || 20)).toFixed(1) : ((ltp || 0) + (cfg.sl_points || 20)).toFixed(1)],
              ["Target", dir === "LONG" ? ((ltp || 0) + (cfg.target_points || 40)).toFixed(1) : ((ltp || 0) - (cfg.target_points || 40)).toFixed(1)],
            ].map(([label, val]) => (
              <div key={label} style={{ textAlign: "center", background: C.bg, borderRadius: 6, padding: "8px 4px" }}>
                <div style={{ fontSize: 9, color: C.muted, fontFamily: "'IBM Plex Mono', monospace", letterSpacing: 1, textTransform: "uppercase" }}>{label}</div>
                <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontWeight: 700, fontSize: 14, color: C.ink, marginTop: 2 }}>{val}</div>
              </div>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            {cfg.enable_pre_trade_breathe && (
              <Btn onClick={onBreathe} variant="orange">🌬️ Breathe</Btn>
            )}
            <Btn full onClick={() => onExecute({
              instrument: "SENSEX",
              direction: dir,
              entry:  ltp,
              sl:     dir === "LONG" ? ltp - cfg.sl_points : ltp + cfg.sl_points,
              target: dir === "LONG" ? ltp + cfg.target_points : ltp - cfg.target_points,
              lots:   cfg.position_size_lots || 2,
              strategy: "MANUAL",
            })} variant="green" disabled={!canTrade}>
              ⚡ Execute {dir}
            </Btn>
          </div>
          {!canTrade && (
            <div style={{ marginTop: 8, background: C.bg, borderRadius: 6, padding: "8px 12px", fontSize: 11, color: C.muted, textAlign: "center" }}>
              Terminal locked — {openTrades.length > 0 ? "close open positions first" : "check discipline rules"}
            </div>
          )}
        </div>

        {/* Open positions */}
        {openTrades.length > 0 && (
          <div style={s.card}>
            <span style={s.label}>Open Positions</span>
            {openTrades.map(t => {
              const lots    = JSON.parse(t.extra_json || "{}").lots || cfg.position_size_lots || 2
              const unrealised = (ltp - t.entry) * 20 * lots * (t.direction === "SHORT" ? -1 : 1)
              return (
                <div key={t.id} style={{ border: `1px solid ${C.border}`, borderRadius: 8, padding: 10, marginBottom: 8 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                    <div>
                      <div style={{ fontWeight: 700, fontSize: 13, color: C.ink }}>{t.instrument}</div>
                      <div style={{ fontSize: 10, color: C.muted }}>{t.direction} · Entry {t.entry?.toFixed(1)} · SL {t.sl?.toFixed(1)}</div>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 14, fontWeight: 700, color: unrealised >= 0 ? C.green : C.red }}>
                        {unrealised >= 0 ? "+" : ""}₹{Math.abs(unrealised).toLocaleString()}
                      </div>
                      <Badge color="blue">OPEN</Badge>
                    </div>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                    <Btn onClick={() => onClose({ trade_id: t.id, exit_price: ltp, exit_reason: "TARGET" })} variant="green">🎯 Book</Btn>
                    <Btn onClick={() => onClose({ trade_id: t.id, exit_price: t.sl, exit_reason: "SL" })} variant="red">✗ Cut SL</Btn>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* RIGHT */}
      <div>
        {/* Discipline guard */}
        <div style={s.card}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
            <span style={{ ...s.label, marginBottom: 0 }}>Discipline Guard</span>
            <Badge color={dscore >= 80 ? "green" : dscore >= 50 ? "amber" : "red"}>PRAGNYA {dscore}/100</Badge>
          </div>
          {[
            ["Trades used", `${st.trades_taken || 0}/${cfg.max_trades_per_day || 4}`, tradesPct],
            ["Loss used",   `₹${Math.abs(pnl).toLocaleString()} / ₹${Math.abs(cfg.daily_loss_limit || 2500).toLocaleString()}`, lossPct],
            ["SL hits",     `${st.sl_hits || 0}/${cfg.max_sl_hits || 2}`, slPct],
          ].map(([label, val, p]) => (
            <div key={label} style={{ marginBottom: 10 }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "#5C5A54", marginBottom: 2 }}>
                <span>{label}</span>
                <span style={{ fontFamily: "'IBM Plex Mono', monospace" }}>{val}</span>
              </div>
              <ProgBar pct={p} />
            </div>
          ))}
          <div style={{ marginTop: 12 }}>
            <Btn full onClick={onKill} variant="red">🛑 Kill Switch</Btn>
          </div>
        </div>

        {/* Daily Gita */}
        <div style={s.card}>
          <span style={s.label}>Today's Gita</span>
          <div style={{ fontSize: 12, color: "#3D3B35", fontStyle: "italic", lineHeight: 1.6 }}>"{quote.text}"</div>
          <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: C.muted, marginTop: 8, letterSpacing: 1 }}>— {quote.src}</div>
        </div>

        {/* Rewards */}
        <div style={s.card}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ ...s.label, marginBottom: 0 }}>PRAGNYA REWARDS</span>
            <Badge color="amber">{pts} pts</Badge>
          </div>
          <div style={{ fontSize: 11, color: C.muted, marginTop: 8, lineHeight: 1.6 }}>
            No revenge: <b style={{ color: C.ink }}>+50</b> · Stop at target: <b style={{ color: C.ink }}>+100</b> · 5-day streak: <b style={{ color: C.ink }}>+500</b>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Journal ────────────────────────────────────────────────────────────────────
function Journal({ trades, pnl, onRefresh }) {
  const wins   = trades.filter(t => t.pnl > 0).length
  const losses = trades.filter(t => t.pnl < 0).length

  return (
    <div>
      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 18, fontWeight: 700, color: C.ink, marginBottom: 14 }}>📊 Trade Journal</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, marginBottom: 12 }}>
        {[
          ["Trades", trades.length, C.ink],
          ["Day P&L", `${pnl >= 0 ? "+" : ""}₹${Math.abs(pnl).toLocaleString()}`, pnl >= 0 ? C.green : C.red],
          ["Wins",   wins,   C.green],
          ["Losses", losses, C.red],
        ].map(([label, val, color]) => (
          <div key={label} style={{ ...s.card, textAlign: "center", padding: 12, marginBottom: 0 }}>
            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: C.muted, textTransform: "uppercase", letterSpacing: 1 }}>{label}</div>
            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 22, fontWeight: 700, color, marginTop: 4 }}>{val}</div>
          </div>
        ))}
      </div>

      <div style={s.card}>
        <span style={s.label}>Today's Trades</span>
        {trades.length === 0 ? (
          <div style={{ textAlign: "center", padding: "30px 0", color: C.muted, fontSize: 13 }}>No trades today</div>
        ) : trades.map(t => (
          <div key={t.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center",
            padding: "8px 0", borderBottom: `1px solid ${C.border}` }}>
            <div>
              <div style={{ fontWeight: 700, fontSize: 13, color: C.ink }}>{t.instrument}</div>
              <div style={{ fontSize: 10, color: C.muted }}>{t.strategy} · {t.direction} · {t.time?.slice(0,5)} {t.exit_reason ? `· ${t.exit_reason}` : ""}</div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <Badge color={t.status === "CLOSED" ? "green" : "blue"}>{t.status}</Badge>
              <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 14, fontWeight: 700, color: t.pnl >= 0 ? C.green : C.red, minWidth: 70, textAlign: "right" }}>
                {t.pnl >= 0 ? "+" : ""}₹{Math.abs(t.pnl).toLocaleString()}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Config ─────────────────────────────────────────────────────────────────────
function Config({ cfg, onSave }) {
  const [c, setC] = useState(cfg)
  useEffect(() => setC(cfg), [cfg])

  const field = (key, label, opts = {}) => (
    <div style={{ marginBottom: 12 }}>
      <label style={s.label}>{label}</label>
      <input type="number" value={c[key] || 0} onChange={e => setC(p => ({ ...p, [key]: +e.target.value }))}
        style={{ width: "100%", border: `1.5px solid ${C.border}`, borderRadius: 6, padding: "8px 10px",
          fontFamily: "'IBM Plex Mono', monospace", fontSize: 13, background: C.white, color: C.ink }} {...opts} />
    </div>
  )

  return (
    <div>
      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 18, fontWeight: 700, color: C.ink, marginBottom: 14 }}>⚙️ Configuration</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div style={s.card}>
          <span style={s.label}>Discipline Rules</span>
          {field("max_trades_per_day", "Max Trades / Day")}
          {field("daily_loss_limit",   "Daily Loss Limit ₹")}
          {field("daily_target",       "Daily Target ₹")}
          {field("max_sl_hits",        "Max SL Hits")}
          {field("cooling_minutes_after_sl", "Cooling After SL (min)")}
        </div>
        <div style={s.card}>
          <span style={s.label}>Execution</span>
          {field("position_size_lots", "Lots")}
          {field("sl_points",          "SL Points")}
          {field("target_points",      "Target Points")}
          <div style={{ marginBottom: 12 }}>
            <label style={s.label}>Pre-trade Breathe</label>
            <button onClick={() => setC(p => ({ ...p, enable_pre_trade_breathe: !p.enable_pre_trade_breathe }))}
              style={{ padding: "8px 16px", borderRadius: 6, border: `1.5px solid ${C.border}`,
                background: c.enable_pre_trade_breathe ? "#D1FAE5" : C.white,
                color: c.enable_pre_trade_breathe ? C.green : C.muted,
                fontFamily: "'IBM Plex Mono', monospace", fontWeight: 600, fontSize: 12, cursor: "pointer" }}>
              {c.enable_pre_trade_breathe ? "✓ Enabled" : "Disabled"}
            </button>
          </div>
        </div>
      </div>
      <Btn full onClick={() => onSave(c)} variant="green">💾 Save Configuration</Btn>
    </div>
  )
}

// ── EOD Emotion Capture ────────────────────────────────────────────────────────
function EodCapture({ product, onDone }) {
  const [saved, setSaved] = useState(false)
  if (saved) return (
    <div style={{ ...s.card, textAlign: "center" }}>
      <div style={{ fontSize: 20 }}>✓ Emotion logged. See you tomorrow.</div>
    </div>
  )
  return (
    <div style={s.card}>
      <span style={s.label}>How did you feel today?</span>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        {[["😌", "Calm"], ["😰", "Anxious"], ["😤", "Frustrated"], ["🎯", "Focused"]].map(([icon, emotion]) => (
          <button key={emotion} onClick={async () => {
            await fetch(`${API}/pragnya/emotion`, {
              method: "POST", headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ product, emotion, note: "" }),
            })
            setSaved(true)
            onDone?.()
          }} style={{ padding: "12px", borderRadius: 8, border: `1.5px solid ${C.border}`, background: C.white,
            fontSize: 13, fontWeight: 600, cursor: "pointer", display: "flex", alignItems: "center", gap: 8,
            justifyContent: "center", color: C.ink }}>
            {icon} {emotion}
          </button>
        ))}
      </div>
    </div>
  )
}
