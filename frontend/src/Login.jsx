import { useState, useEffect } from "react"

const API = "https://mtutrade.in/api"

const T = {
  canvas:  "#FAF9F7",
  surface: "#FFFFFF",
  line:    "#E8E4DE",
  subtle:  "#8A8580",
  body:    "#3D3A35",
  ink:     "#1A1814",
  brand:   "#C8590A",
  sell:    "#C62828",
}

const inter = "'Inter', system-ui, sans-serif"
const mono  = "'JetBrains Mono', 'Fira Mono', monospace"

export default function Login({ onSuccess }) {
  const [email,    setEmail]    = useState("")
  const [password, setPassword] = useState("")
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState("")
  const [showPass, setShowPass] = useState(false)
  const [quote,    setQuote]    = useState(null)

  useEffect(() => {
    fetch(API + "/vajra/pragnya/quote")
      .then(r => r.json())
      .then(d => { if (d.quote) setQuote(d.quote) })
      .catch(() => {})
  }, [])

  async function handleLogin(e) {
    e.preventDefault()
    if (!email || !password) { setError("Enter email and password"); return }
    setLoading(true); setError("")
    try {
      const r = await fetch(`${API}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email: email.trim().toLowerCase(), password })
      })
      const data = await r.json()
      if (r.ok && data.token) {
        localStorage.setItem("mtu_token", data.token)
        localStorage.setItem("mtu_user", JSON.stringify({
          name: data.name, email: data.email, products: data.products
        }))
        onSuccess(data)
      } else {
        setError(data.detail || "Login failed. Check your credentials.")
      }
    } catch {
      setError("Connection error. Please try again.")
    }
    setLoading(false)
  }

  return (
    <div style={{
      minHeight: "100vh",
      background: T.canvas,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: "24px 16px",
      fontFamily: inter,
    }}>
      <div style={{ width: "100%", maxWidth: 360 }}>

        {/* ── Logo ── */}
        <div style={{ textAlign: "center", marginBottom: 28 }}>
          <div style={{
            fontFamily: mono,
            fontSize: 30,
            fontWeight: 800,
            color: T.ink,
            letterSpacing: "-0.5px",
            lineHeight: 1,
            marginBottom: 6,
          }}>
            ⚡ <span style={{ color: T.brand }}>VAJRA</span>
          </div>
          <div style={{
            fontSize: 13,
            color: T.subtle,
            letterSpacing: "0.3px",
          }}>
            Options Scalping Terminal · MTU
          </div>
        </div>

        {/* ── Single Card ── */}
        <div style={{
          background: T.surface,
          borderRadius: 16,
          padding: "28px 24px",
          border: `1px solid ${T.line}`,
          boxShadow: "0 2px 16px rgba(0,0,0,0.06)",
        }}>

          {/* Gita quote — plain text, no box, no border */}
          {quote && (
            <div style={{
              textAlign: "center",
              marginBottom: 24,
              paddingBottom: 20,
              borderBottom: `1px solid ${T.line}`,
            }}>
              <div style={{
                fontSize: 14,
                color: T.body,
                fontStyle: "italic",
                lineHeight: 1.65,
                marginBottom: 8,
              }}>
                "{quote.verse}"
              </div>
              <div style={{
                fontFamily: mono,
                fontSize: 11,
                color: T.brand,
                fontWeight: 700,
                letterSpacing: "0.8px",
              }}>
                — {quote.source}
              </div>
            </div>
          )}

          {/* Heading */}
          <div style={{
            fontSize: 20,
            fontWeight: 700,
            color: T.ink,
            marginBottom: 4,
          }}>
            Sign in
          </div>
          <div style={{
            fontSize: 13,
            color: T.subtle,
            marginBottom: 22,
          }}>
            Use your MTU account credentials
          </div>

          {/* Error */}
          {error && (
            <div style={{
              background: "#FFF5F5",
              border: `1px solid ${T.sell}`,
              borderRadius: 8,
              padding: "10px 14px",
              marginBottom: 16,
              fontSize: 13,
              color: T.sell,
              fontWeight: 500,
            }}>
              {error}
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleLogin} style={{ display: "flex", flexDirection: "column", gap: 16 }}>

            {/* Email */}
            <div>
              <label style={{
                fontFamily: mono,
                fontSize: 11,
                fontWeight: 700,
                color: T.body,
                letterSpacing: "1.2px",
                textTransform: "uppercase",
                display: "block",
                marginBottom: 7,
              }}>
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="you@example.com"
                autoComplete="email"
                style={{
                  width: "100%",
                  height: 48,
                  border: `1.5px solid ${T.line}`,
                  borderRadius: 10,
                  padding: "0 14px",
                  fontFamily: inter,
                  fontSize: 16,
                  color: T.ink,
                  background: T.surface,
                  outline: "none",
                  boxSizing: "border-box",
                }}
                onFocus={e => e.target.style.border = `1.5px solid ${T.brand}`}
                onBlur={e  => e.target.style.border = `1.5px solid ${T.line}`}
              />
            </div>

            {/* Password */}
            <div>
              <label style={{
                fontFamily: mono,
                fontSize: 11,
                fontWeight: 700,
                color: T.body,
                letterSpacing: "1.2px",
                textTransform: "uppercase",
                display: "block",
                marginBottom: 7,
              }}>
                Password
              </label>
              <div style={{ position: "relative" }}>
                <input
                  type={showPass ? "text" : "password"}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  style={{
                    width: "100%",
                    height: 48,
                    border: `1.5px solid ${T.line}`,
                    borderRadius: 10,
                    padding: "0 52px 0 14px",
                    fontFamily: inter,
                    fontSize: 16,
                    color: T.ink,
                    background: T.surface,
                    outline: "none",
                    boxSizing: "border-box",
                  }}
                  onFocus={e => e.target.style.border = `1.5px solid ${T.brand}`}
                  onBlur={e  => e.target.style.border = `1.5px solid ${T.line}`}
                />
                <button
                  type="button"
                  onPointerDown={() => setShowPass(v => !v)}
                  style={{
                    position: "absolute",
                    right: 14,
                    top: "50%",
                    transform: "translateY(-50%)",
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    color: T.subtle,
                    fontSize: 13,
                    fontWeight: 600,
                    fontFamily: inter,
                    WebkitTapHighlightColor: "transparent",
                    padding: 0,
                  }}>
                  {showPass ? "Hide" : "Show"}
                </button>
              </div>
            </div>

            {/* Submit */}
            <button
              type="submit"
              disabled={loading}
              style={{
                height: 50,
                borderRadius: 10,
                border: "none",
                background: loading ? T.line : T.brand,
                color: loading ? T.subtle : "#fff",
                fontFamily: inter,
                fontWeight: 700,
                fontSize: 17,
                cursor: loading ? "not-allowed" : "pointer",
                marginTop: 4,
                letterSpacing: "0.2px",
                WebkitTapHighlightColor: "transparent",
                touchAction: "manipulation",
                transition: "background 0.15s",
              }}>
              {loading ? "Signing in…" : "Sign in →"}
            </button>
          </form>

          {/* Footer inside card */}
          <div style={{
            marginTop: 20,
            paddingTop: 16,
            borderTop: `1px solid ${T.line}`,
            fontSize: 12,
            color: T.subtle,
            textAlign: "center",
            lineHeight: 1.6,
          }}>
            Invite-only beta ·{" "}
            <span style={{ color: T.brand, fontWeight: 600 }}>balu@mtutrade.in</span>
          </div>
        </div>

        {/* Bottom disclaimer */}
        <div style={{
          textAlign: "center",
          marginTop: 16,
          fontSize: 11,
          color: T.subtle,
          fontFamily: mono,
          lineHeight: 1.7,
          opacity: 0.8,
        }}>
          Decision support tool · Not SEBI registered<br />All trading decisions are yours.
        </div>

      </div>
    </div>
  )
}
