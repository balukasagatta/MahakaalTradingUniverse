import { useState, useEffect } from 'react'
import './index.css'
import { createRoot } from 'react-dom/client'
import App from './App.jsx'
import Login from './Login.jsx'
import PreMarketPlanner from './PreMarketPlanner.jsx'

const API = "https://mtutrade.in/api"

function Root() {
  const [user,        setUser]        = useState(null)
  const [checking,    setChecking]    = useState(true)
  const today = new Date().toISOString().slice(0,10)
  const [showPlanner, setShowPlanner] = useState(false)

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
    }).catch(()=>{}).finally(()=>setChecking(false))
  },[])

  useEffect(()=>{
    if(user){
      const planned = localStorage.getItem("mtu_planned_"+today)
      console.log("Planner check:", today, planned, user.email)
      if(planned !== "1") setShowPlanner(true)
    }
  },[user, today])

  function handleLogout(){
    localStorage.removeItem("mtu_token")
    localStorage.removeItem("mtu_user")
    setUser(null)
    setShowPlanner(false)
  }

  if(checking) return (
    <div style={{minHeight:"100vh",background:"#FAF9F7",display:"flex",alignItems:"center",justifyContent:"center"}}>
      <div style={{fontFamily:"monospace",fontSize:13,color:"#7A7670"}}>Loading VAJRA…</div>
    </div>
  )

  if(!user) return <Login onSuccess={(data)=>setUser(data)}/>

  if(showPlanner) return (
    <PreMarketPlanner
      user={user}
      dark={localStorage.getItem("mtu_dark")==="1"}
      onComplete={()=>{ localStorage.setItem("mtu_planned_"+today,"1"); setShowPlanner(false) }}
      onSkip={()=>{ localStorage.setItem("mtu_planned_"+today,"1"); setShowPlanner(false) }}
    />
  )

  return <App user={user} onLogout={handleLogout}/>
}

createRoot(document.getElementById('root')).render(<Root/>)
