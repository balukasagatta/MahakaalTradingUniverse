import { useState } from "react"

const API = "https://mtutrade.in/api"
const T = {
  canvas:"#FAF9F7", surface:"#FFFFFF", raised:"#F3F1EE",
  line:"#E8E4DE", subtle:"#7A7670", body:"#3D3A35", ink:"#1A1814",
  brand:"#C8590A", sell:"#C62828", buy:"#2E7D32",
}
const inter = "'Inter',system-ui,sans-serif"
const mono  = "'JetBrains Mono','Fira Mono',monospace"

export default function Login({ onSuccess }) {
  const [email,    setEmail]    = useState("")
  const [password, setPassword] = useState("")
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState("")
  const [showPass, setShowPass] = useState(false)

  async function handleLogin(e) {
    e.preventDefault()
    if(!email || !password) { setError("Enter email and password"); return }
    setLoading(true); setError("")
    try {
      const r = await fetch(`${API}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",  // send/receive cookies
        body: JSON.stringify({ email: email.trim().toLowerCase(), password })
      })
      const data = await r.json()
      if(r.ok && data.token) {
        localStorage.setItem("mtu_token", data.token)
        localStorage.setItem("mtu_user",  JSON.stringify({ name: data.name, email: data.email, products: data.products }))
        onSuccess(data)
      } else {
        setError(data.detail || "Login failed. Check your credentials.")
      }
    } catch(err) {
      setError("Connection error. Please try again.")
    }
    setLoading(false)
  }

  return (
    <div style={{minHeight:"100vh",background:T.canvas,display:"flex",alignItems:"center",justifyContent:"center",padding:20,fontFamily:inter}}>
      <div style={{width:"100%",maxWidth:360}}>

        {/* Logo */}
        <div style={{textAlign:"center",marginBottom:32}}>
          <div style={{fontFamily:mono,fontSize:26,fontWeight:700,color:T.ink,marginBottom:4}}>
            ⚡ <span style={{color:T.brand}}>VAJRA</span>
          </div>
          <div style={{fontSize:13,color:T.subtle}}>Options Scalping Terminal</div>
          <div style={{fontSize:11,color:T.subtle,marginTop:4,fontFamily:mono}}>by MTU · mtutrade.in</div>
        </div>

        {/* Card */}
        <div style={{background:T.surface,borderRadius:16,padding:28,boxShadow:"0 4px 24px rgba(0,0,0,0.08)",border:`1px solid ${T.line}`}}>
          <div style={{fontSize:16,fontWeight:700,color:T.ink,marginBottom:4}}>Sign in</div>
          <div style={{fontSize:12,color:T.subtle,marginBottom:24}}>Use your MTU account credentials</div>

          {error && (
            <div style={{background:"#FFF5F5",border:`1px solid #FECACA`,borderLeft:`3px solid ${T.sell}`,borderRadius:6,padding:"10px 12px",marginBottom:16,fontSize:12,color:T.sell,fontWeight:500}}>
              {error}
            </div>
          )}

          <form onSubmit={handleLogin} style={{display:"flex",flexDirection:"column",gap:16}}>
            {/* Email */}
            <div>
              <label style={{fontFamily:mono,fontSize:9,fontWeight:600,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:6,display:"block"}}>Email</label>
              <input
                type="email"
                value={email}
                onChange={e=>setEmail(e.target.value)}
                placeholder="you@example.com"
                autoComplete="email"
                style={{width:"100%",height:42,border:`1px solid ${T.line}`,borderRadius:8,padding:"0 12px",fontFamily:inter,fontSize:14,color:T.ink,background:T.surface,outline:"none",boxSizing:"border-box",transition:"border .15s"}}
                onFocus={e=>e.target.style.border=`1.5px solid ${T.brand}`}
                onBlur={e=>e.target.style.border=`1px solid ${T.line}`}
              />
            </div>

            {/* Password */}
            <div>
              <label style={{fontFamily:mono,fontSize:9,fontWeight:600,color:T.subtle,letterSpacing:"1.5px",textTransform:"uppercase",marginBottom:6,display:"block"}}>Password</label>
              <div style={{position:"relative"}}>
                <input
                  type={showPass?"text":"password"}
                  value={password}
                  onChange={e=>setPassword(e.target.value)}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  style={{width:"100%",height:42,border:`1px solid ${T.line}`,borderRadius:8,padding:"0 40px 0 12px",fontFamily:inter,fontSize:14,color:T.ink,background:T.surface,outline:"none",boxSizing:"border-box",transition:"border .15s"}}
                  onFocus={e=>e.target.style.border=`1.5px solid ${T.brand}`}
                  onBlur={e=>e.target.style.border=`1px solid ${T.line}`}
                />
                <button type="button" onPointerDown={()=>setShowPass(v=>!v)} style={{position:"absolute",right:12,top:"50%",transform:"translateY(-50%)",background:"none",border:"none",cursor:"pointer",color:T.subtle,fontSize:13,fontFamily:inter,WebkitTapHighlightColor:"transparent"}}>
                  {showPass?"Hide":"Show"}
                </button>
              </div>
            </div>

            {/* Submit */}
            <button type="submit" disabled={loading} style={{height:46,borderRadius:8,border:"none",background:loading?T.raised:T.brand,color:loading?T.subtle:"#fff",fontFamily:inter,fontWeight:700,fontSize:15,cursor:loading?"not-allowed":"pointer",transition:"all .15s",marginTop:4,WebkitTapHighlightColor:"transparent",touchAction:"manipulation"}}>
              {loading ? "Signing in…" : "Sign in →"}
            </button>
          </form>

          <div style={{marginTop:20,paddingTop:16,borderTop:`1px solid ${T.line}`,fontSize:11,color:T.subtle,textAlign:"center",lineHeight:1.6}}>
            Access is invite-only during beta.<br/>
            Contact <span style={{color:T.brand,fontWeight:600}}>balu@mtutrade.in</span> for access.
          </div>
        </div>

        {/* Footer */}
        <div style={{textAlign:"center",marginTop:20,fontSize:10,color:T.subtle,fontFamily:mono,lineHeight:1.8}}>
          VAJRA is a decision support tool.<br/>
          Not a SEBI registered investment advisor.<br/>
          All trading decisions are yours.
        </div>
      </div>
    </div>
  )
}
