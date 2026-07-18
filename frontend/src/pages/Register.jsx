import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function Register() {
  const [form, setForm]       = useState({ name:'', email:'', password:'' })
  const [error, setError]     = useState('')
  const [loading, setLoading] = useState(false)
  const { register }          = useAuth()
  const navigate              = useNavigate()

  const set = key => e => setForm(f => ({...f, [key]: e.target.value}))

  const handleSubmit = async e => {
    e.preventDefault()
    setError('')
    if (form.password.length < 8) { setError('Password must be at least 8 characters'); return }
    setLoading(true)
    try {
      await register(form.name, form.email, form.password)
      navigate('/dashboard')
    } catch (err) {
      setError(err.response?.data?.detail || 'Registration failed. Please try again.')
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

        <h1 className="auth-title">Create your account</h1>
        <p className="auth-subtitle">Start automating your YouTube Shorts today — free</p>

        {error && <div className="alert alert-error" style={{marginBottom:16}}>{error}</div>}

        <form className="auth-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <label className="form-label">Full name</label>
            <input id="reg-name" className="form-input" type="text" placeholder="Your name"
              value={form.name} onChange={set('name')} required autoFocus />
          </div>

          <div className="form-group">
            <label className="form-label">Email address</label>
            <input id="reg-email" className="form-input" type="email" placeholder="you@example.com"
              value={form.email} onChange={set('email')} required />
          </div>

          <div className="form-group">
            <label className="form-label">Password</label>
            <input id="reg-password" className="form-input" type="password"
              placeholder="Min. 8 characters with a number"
              value={form.password} onChange={set('password')} required />
            <span className="form-hint">Must include at least one uppercase letter and one number</span>
          </div>

          <button id="reg-submit" type="submit" className="btn btn-primary btn-full btn-lg"
            disabled={loading} style={{marginTop:4}}>
            {loading ? <><span className="spinner" />Creating account…</> : 'Create free account'}
          </button>
        </form>

        <div className="auth-footer">
          Already have an account? <Link to="/login">Sign in</Link>
        </div>
      </div>
    </div>
  )
}
