import { useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api/client'

export default function ForgotPassword() {
  const [email, setEmail]     = useState('')
  const [sent, setSent]       = useState(false)
  const [error, setError]     = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async e => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await api.post('/auth/forgot-password', { email })
      setSent(true)
    } catch {
      setError('Something went wrong. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <div className="auth-logo">
          <div className="auth-logo-icon">🎬</div>
          <span className="auth-logo-text gradient-text">AutoShorts</span>
        </div>

        {sent ? (
          <>
            <div style={{fontSize:48, marginBottom:16}}>📧</div>
            <h1 className="auth-title">Check your email</h1>
            <p className="auth-subtitle" style={{marginBottom:24}}>
              If an account exists for <strong>{email}</strong>, we've sent a password reset link.
            </p>
            <div className="auth-footer">
              <Link to="/login">← Back to sign in</Link>
            </div>
          </>
        ) : (
          <>
            <h1 className="auth-title">Forgot password?</h1>
            <p className="auth-subtitle">Enter your email and we'll send a reset link</p>

            {error && <div className="alert alert-error" style={{marginBottom:16}}>{error}</div>}

            <form className="auth-form" onSubmit={handleSubmit}>
              <div className="form-group">
                <label className="form-label">Email address</label>
                <input id="forgot-email" className="form-input" type="email"
                  placeholder="you@example.com" value={email}
                  onChange={e => setEmail(e.target.value)} required autoFocus />
              </div>
              <button id="forgot-submit" type="submit" className="btn btn-primary btn-full"
                disabled={loading}>
                {loading ? <><span className="spinner" />Sending…</> : 'Send reset link'}
              </button>
            </form>

            <div className="auth-footer"><Link to="/login">← Back to sign in</Link></div>
          </>
        )}
      </div>
    </div>
  )
}
