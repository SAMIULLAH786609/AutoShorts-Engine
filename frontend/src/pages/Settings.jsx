import { useState, useEffect } from 'react'
import Sidebar from '../components/Sidebar'
import api from '../api/client'
import { useAuth } from '../context/AuthContext'

export default function Settings() {
  const { user, refreshUser } = useAuth()
  
  // Channel state
  const [channels, setChannels] = useState([])
  const [channelsLoading, setChannelsLoading] = useState(true)

  // Form states
  const [settings, setSettings] = useState({
    name: '',
    channel_niche: '',
    default_language: '',
    default_gender: '',
    default_privacy: ''
  })
  
  const [passwordForm, setPasswordForm] = useState({
    current_password: '',
    new_password: ''
  })

  // Alerts
  const [settingsError, setSettingsError] = useState('')
  const [settingsSuccess, setSettingsSuccess] = useState('')
  const [pwError, setPwError]             = useState('')
  const [pwSuccess, setPwSuccess]         = useState('')
  const [channelError, setChannelError]   = useState('')
  const [savingSettings, setSavingSettings] = useState(false)
  const [savingPassword, setSavingPassword] = useState(false)

  // Initialize form
  useEffect(() => {
    if (user) {
      setSettings({
        name:             user.name || '',
        channel_niche:    user.channel_niche || '',
        default_language: user.default_language || '',
        default_gender:   user.default_gender || '',
        default_privacy:  user.default_privacy || ''
      })
    }
  }, [user])

  const fetchChannels = async () => {
    try {
      const r = await api.get('/channels')
      setChannels(r.data)
    } catch {
      setChannelError('Failed to fetch connected channels')
    } finally {
      setChannelsLoading(false)
    }
  }

  // Fetch connected channels
  useEffect(() => {
    fetchChannels()
  }, [])

  const handleSettingsSubmit = async e => {
    e.preventDefault()
    setSettingsError('')
    setSettingsSuccess('')
    setSavingSettings(true)
    try {
      await api.put('/auth/me', settings)
      await refreshUser()
      setSettingsSuccess('⚙️ Settings updated successfully!')
    } catch (err) {
      setSettingsError(err.response?.data?.detail || 'Failed to update settings')
    } finally {
      setSavingSettings(false)
    }
  }

  const handlePasswordSubmit = async e => {
    e.preventDefault()
    setPwError('')
    setPwSuccess('')
    setSavingPassword(true)
    try {
      await api.post('/auth/change-password', passwordForm)
      setPwSuccess('🔐 Password updated successfully!')
      setPasswordForm({ current_password: '', new_password: '' })
    } catch (err) {
      setPwError(err.response?.data?.detail || 'Failed to update password')
    } finally {
      setSavingPassword(false)
    }
  }

  const handleConnectChannel = async () => {
    setChannelError('')
    try {
      const r = await api.get('/channels/oauth-url')
      if (r.data.oauth_url) {
        window.location.href = r.data.oauth_url
      } else {
        setChannelError('Failed to retrieve connection URL')
      }
    } catch (err) {
      setChannelError(err.response?.data?.detail || 'Failed to trigger connection flow')
    }
  }

  const handleDisconnectChannel = async (id) => {
    if (!window.confirm('Disconnect this YouTube channel? Scheduled posts to this channel will stop.')) return
    setChannelError('')
    try {
      await api.delete(`/channels/${id}`)
      setChannels(prev => prev.filter(c => c.id !== id))
    } catch (err) {
      setChannelError(err.response?.data?.detail || 'Failed to disconnect channel')
    }
  }

  const setSettingVal = key => e => setSettings(s => ({ ...s, [key]: e.target.value }))
  const setPwVal = key => e => setPasswordForm(p => ({ ...p, [key]: e.target.value }))

  return (
    <div className="app-layout">
      <Sidebar />
      <div className="main-content" style={{ display: 'flex', flexDirection: 'column', gap: 32, maxWidth: 800 }}>
        
        {/* Page title */}
        <div>
          <h1 className="page-title">Settings</h1>
          <p className="page-subtitle">Configure your account settings, default video preferences, and YouTube connection</p>
        </div>

        {/* Section 1: YouTube Connection */}
        <div className="card">
          <h3 style={{ marginBottom: 4 }}>📺 YouTube Channel Connection</h3>
          <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 20 }}>
            Connect your YouTube channel using secure Google OAuth.
          </p>

          {channelError && <div className="alert alert-error" style={{ marginBottom: 16 }}>{channelError}</div>}

          {channelsLoading ? (
            <span className="spinner" style={{ width: 24, height: 24 }} />
          ) : !channels.length ? (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 12 }}>
              <div style={{ fontSize: 14, color: 'var(--text-secondary)' }}>No YouTube channel connected.</div>
              <button className="btn btn-primary" onClick={handleConnectChannel}>🔌 Connect YouTube Channel</button>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {channels.map(c => (
                <div key={c.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: 12, border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', background: 'var(--bg-elevated)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    {c.thumbnail_url ? (
                      <img src={c.thumbnail_url} alt="" style={{ width: 40, height: 40, borderRadius: '50%' }} />
                    ) : (
                      <div style={{ width: 40, height: 40, borderRadius: '50%', background: 'var(--gradient)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 18 }}>📺</div>
                    )}
                    <div>
                      <div style={{ fontWeight: 600 }}>{c.channel_name || 'YouTube Channel'}</div>
                      <a href={c.channel_url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: '#a78bfa', textDecoration: 'none' }}>
                        View channel page ↗
                      </a>
                    </div>
                  </div>
                  <button className="btn btn-danger btn-sm" onClick={() => handleDisconnectChannel(c.id)}>
                    Disconnect
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Section 2: General settings & defaults */}
        <div className="card">
          <h3 style={{ marginBottom: 20 }}>⚙️ Preferences & Video Defaults</h3>
          
          {settingsError && <div className="alert alert-error" style={{ marginBottom: 16 }}>{settingsError}</div>}
          {settingsSuccess && <div className="alert alert-success" style={{ marginBottom: 16 }}>{settingsSuccess}</div>}

          <form onSubmit={handleSettingsSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div className="form-group">
              <label className="form-label">Full Name</label>
              <input className="form-input" type="text" value={settings.name} onChange={setSettingVal('name')} required />
            </div>

            <div className="form-group">
              <label className="form-label">Channel Niche / Topic Theme</label>
              <input className="form-input" type="text" placeholder="e.g. History facts, tech news, fitness tips"
                value={settings.channel_niche} onChange={setSettingVal('channel_niche')} required />
              <span className="form-hint">Used by the AI script generator to find trending topics matching this niche.</span>
            </div>

            <div className="form-group">
              <label className="form-label">Default Language</label>
              <select className="form-input" value={settings.default_language} onChange={setSettingVal('default_language')}>
                <option value="English">English</option>
                <option value="Spanish">Spanish</option>
                <option value="French">French</option>
                <option value="German">German</option>
                <option value="Urdu">Urdu</option>
                <option value="Hindi">Hindi</option>
              </select>
            </div>

            <div className="form-group">
              <label className="form-label">Narrator Voice Gender</label>
              <select className="form-input" value={settings.default_gender} onChange={setSettingVal('default_gender')}>
                <option value="female">Female voice</option>
                <option value="male">Male voice</option>
              </select>
            </div>

            <div className="form-group">
              <label className="form-label">YouTube Upload Privacy</label>
              <select className="form-input" value={settings.default_privacy} onChange={setSettingVal('default_privacy')}>
                <option value="private">Private (recommended for testing)</option>
                <option value="public">Public (directly online)</option>
                <option value="unlisted">Unlisted</option>
              </select>
            </div>

            <button type="submit" className="btn btn-primary" disabled={savingSettings} style={{ alignSelf: 'flex-start', marginTop: 8 }}>
              {savingSettings ? <><span className="spinner" />Saving Preferences…</> : 'Save Preferences'}
            </button>
          </form>
        </div>

        {/* Section 3: Change Password */}
        <div className="card">
          <h3 style={{ marginBottom: 20 }}>🔐 Change Password</h3>

          {pwError && <div className="alert alert-error" style={{ marginBottom: 16 }}>{pwError}</div>}
          {pwSuccess && <div className="alert alert-success" style={{ marginBottom: 16 }}>{pwSuccess}</div>}

          <form onSubmit={handlePasswordSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div className="form-group">
              <label className="form-label">Current Password</label>
              <input className="form-input" type="password" value={passwordForm.current_password} onChange={setPwVal('current_password')} required />
            </div>

            <div className="form-group">
              <label className="form-label">New Password</label>
              <input className="form-input" type="password" placeholder="Min. 8 characters"
                value={passwordForm.new_password} onChange={setPwVal('new_password')} required />
            </div>

            <button type="submit" className="btn btn-secondary" disabled={savingPassword} style={{ alignSelf: 'flex-start', marginTop: 8 }}>
              {savingPassword ? <><span className="spinner" />Updating Password…</> : 'Update Password'}
            </button>
          </form>
        </div>

      </div>
    </div>
  )
}
