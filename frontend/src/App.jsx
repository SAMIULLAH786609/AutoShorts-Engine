import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import Login          from './pages/Login'
import Register       from './pages/Register'
import ForgotPassword from './pages/ForgotPassword'
import ResetPassword  from './pages/ResetPassword'
import Dashboard      from './pages/Dashboard'
import VideoHistory   from './pages/VideoHistory'
import Schedule       from './pages/Schedule'
import Settings       from './pages/Settings'

// Protected route — redirects to /login if not authenticated
function Protected({ children }) {
  const { user, loading } = useAuth()
  if (loading) return (
    <div style={{ display:'flex', alignItems:'center', justifyContent:'center', height:'100vh', color:'#9898b0' }}>
      <div className="spinner" style={{ width:32, height:32 }} />
    </div>
  )
  return user ? children : <Navigate to="/login" replace />
}

// Public route — redirects to /dashboard if already logged in
function Public({ children }) {
  const { user, loading } = useAuth()
  if (loading) return null
  return !user ? children : <Navigate to="/dashboard" replace />
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Public */}
          <Route path="/login"           element={<Public><Login /></Public>} />
          <Route path="/register"        element={<Public><Register /></Public>} />
          <Route path="/forgot-password" element={<Public><ForgotPassword /></Public>} />
          <Route path="/reset-password"  element={<Public><ResetPassword /></Public>} />

          {/* Protected */}
          <Route path="/dashboard"  element={<Protected><Dashboard /></Protected>} />
          <Route path="/history"    element={<Protected><VideoHistory /></Protected>} />
          <Route path="/schedule"   element={<Protected><Schedule /></Protected>} />
          <Route path="/settings"   element={<Protected><Settings /></Protected>} />

          {/* Default */}
          <Route path="/"  element={<Navigate to="/dashboard" replace />} />
          <Route path="*"  element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
