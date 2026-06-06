import { StrictMode, useState, useEffect } from 'react'
import './index.css'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import Login from './Login.jsx'

const API = "https://mtutrade.in/api"

function Root() {
  const [user,     setUser]     = useState(null)
  const [checking, setChecking] = useState(true)

  useEffect(()=>{
    const token = localStorage.getItem("mtu_token")
    if(!token){ setChecking(false); return }
    fetch(`${API}/auth/verify`,{
      headers:{"Authorization":`Bearer ${token}`},
      credentials:"include"
    }).then(r=>r.json()).then(data=>{
      if(data.status==="ok"){
        const stored = JSON.parse(localStorage.getItem("mtu_user")||"{}")
        setUser({...stored, email:data.email, products:data.products})
      } else {
        localStorage.removeItem("mtu_token")
        localStorage.removeItem("mtu_user")
      }
    }).catch(()=>{
      const stored = localStorage.getItem("mtu_user")
      if(stored) setUser(JSON.parse(stored))
    }).finally(()=>setChecking(false))
  },[])

  function handleLogout(){
    localStorage.removeItem("mtu_token")
    localStorage.removeItem("mtu_user")
    setUser(null)
  }

  if(checking) return (
    <div style={{minHeight:"100vh",background:"#FAF9F7",display:"flex",alignItems:"center",justifyContent:"center"}}>
      <div style={{fontFamily:"monospace",fontSize:13,color:"#7A7670"}}>Loading VAJRA…</div>
    </div>
  )

  if(!user) return <Login onSuccess={(data)=>setUser(data)}/>
  return <App user={user} onLogout={handleLogout}/>
}

createRoot(document.getElementById('root')).render(<StrictMode><Root/></StrictMode>)
