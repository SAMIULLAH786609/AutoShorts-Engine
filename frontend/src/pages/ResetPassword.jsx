import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import api from '../api/client'
import ThemeToggleFloating from '../components/ThemeToggleFloating'

export default function ResetPassword() {
  const [searchParams]            = useSearchParams()
  const token                     = searchParams.get('token') || ''
  const [password, setPassword]   = useState('')
  const [confirm, setConfirm]     = useState('')
  const [done, setDone]           = useState(false)
  const [error, setError]         = useState('')
  const [loading, setLoading]     = useState(false)
  const navigate                  = useNavigate()

  const handleSubmit = async e => {
    e.preventDefault()
    setError('')
    if (password !== confirm) { setError('Passwords do not match'); return }
    if (password.length < 8)  { setError('Password must be at least 8 characters'); return }

    setLoading(true)
    try {
      await api.post('/auth/reset-password', { token, new_password: password })
      setDone(true)
      setTimeout(() => navigate('/login'), 2500)
    } catch (err) {
      setError(err.response?.data?.detail || 'Reset failed. The link may have expired.')
    } finally {
      setLoading(false)
    }
  }

  if (!token) return (
    <div className="auth-page">
      <ThemeToggleFloating />
      <div className="auth-card">
        <div className="alert alert-error">Invalid reset link. Please request a new one.</div>
        <div className="auth-footer" style={{marginTop:16}}><Link to="/forgot-password">Request new link</Link></div>
      </div>
    </div>
  )

  return (
    <div className="auth-page">
      <ThemeToggleFloating />
      <div className="auth-card">
        <div className="auth-logo">
          <div className="auth-logo-icon">🎬</div>
          <span className="auth-logo-text gradient-text">AutoShorts</span>
        </div>

        {done ? (
          <>
            <div style={{fontSize:48, marginBottom:16}}>✅</div>
            <h1 className="auth-title">Password reset!</h1>
            <p className="auth-subtitle">Redirecting you to sign in…</p>
          </>
        ) : (
          <>
            <h1 className="auth-title">Set new password</h1>
            <p className="auth-subtitle">Choose a strong password for your account</p>

            {error && <div className="alert alert-error" style={{marginBottom:16}}>{error}</div>}

            <form className="auth-form" onSubmit={handleSubmit}>
              <div className="form-group">
                <label className="form-label">New password</label>
                <input className="form-input" type="password" placeholder="Min. 8 characters"
                  value={password} onChange={e => setPassword(e.target.value)} required autoFocus />
              </div>
              <div className="form-group">
                <label className="form-label">Confirm password</label>
                <input className="form-input" type="password" placeholder="Repeat password"
                  value={confirm} onChange={e => setConfirm(e.target.value)} required />
              </div>
              <button type="submit" className="btn btn-primary btn-full" disabled={loading}>
                {loading ? <><span className="spinner" />Resetting…</> : 'Reset password'}
              </button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}
