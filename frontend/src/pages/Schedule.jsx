import { useState, useEffect } from 'react'
import Sidebar from '../components/Sidebar'
import api from '../api/client'

export default function Schedule() {
  const [schedule, setSchedule] = useState({
    videos_per_day: 3,
    time_slot_1: '09:00',
    time_slot_2: '15:00',
    time_slot_3: '21:00',
    timezone: 'UTC',
    is_active: true
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving]   = useState(false)
  const [error, setError]     = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    api.get('/schedule')
      .then(r => {
        setSchedule(r.data)
      })
      .catch(() => {
        setError('Failed to load schedule settings')
      })
      .finally(() => {
        setLoading(false)
      })
  }, [])

  const handleSubmit = async e => {
    e.preventDefault()
    setError('')
    setSuccess('')
    setSaving(true)
    try {
      const r = await api.put('/schedule', schedule)
      setSchedule(r.data)
      setSuccess('🗓️ Schedule settings saved successfully! Your automation scheduler is active.')
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to update schedule')
    } finally {
      setSaving(false)
    }
  }

  const setVal = key => e => {
    const val = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setSchedule(s => ({ ...s, [key]: val }))
  }

  if (loading) return (
    <div className="app-layout">
      <Sidebar />
      <div className="main-content" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div className="spinner" style={{ width: 40, height: 40 }} />
      </div>
    </div>
  )

  return (
    <div className="app-layout">
      <Sidebar />
      <div className="main-content">
        <div className="page-header">
          <h1 className="page-title">Automated Scheduling</h1>
          <p className="page-subtitle">Configure when and how often videos are automatically generated and uploaded</p>
        </div>

        {error && <div className="alert alert-error" style={{ marginBottom: 20 }}>{error}</div>}
        {success && <div className="alert alert-success" style={{ marginBottom: 20 }}>{success}</div>}

        <div className="card" style={{ maxWidth: 600 }}>
          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'rgba(124, 58, 237, 0.05)', padding: 16, borderRadius: 'var(--radius-md)', border: '1px solid var(--border)' }}>
              <div>
                <div style={{ fontWeight: 600, marginBottom: 2 }}>Enable Automated Postings</div>
                <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Fires the automation runner at scheduled slots</div>
              </div>
              <label className="switch" style={{ position: 'relative', display: 'inline-block', width: 44, height: 24 }}>
                <input 
                  type="checkbox" 
                  checked={schedule.is_active} 
                  onChange={setVal('is_active')}
                  style={{ opacity: 0, width: 0, height: 0 }}
                />
                <span className="slider" style={{
                  position: 'absolute', cursor: 'pointer', top: 0, left: 0, right: 0, bottom: 0,
                  backgroundColor: schedule.is_active ? 'var(--brand-1)' : '#3f3f46',
                  transition: '.3s', borderRadius: 24
                }}>
                  <span style={{
                    position: 'absolute', content: '""', height: 16, width: 16, left: schedule.is_active ? 24 : 4, bottom: 4,
                    backgroundColor: 'white', transition: '.3s', borderRadius: '50%'
                  }} />
                </span>
              </label>
            </div>

            <div className="form-group">
              <label className="form-label">Videos Per Day</label>
              <select className="form-input" value={schedule.videos_per_day} onChange={setVal('videos_per_day')}>
                <option value={1}>1 video per day</option>
                <option value={2}>2 videos per day</option>
                <option value={3}>3 videos per day</option>
              </select>
              <span className="form-hint">Determines how many time slots below will trigger postings.</span>
            </div>

            <div className="form-group">
              <label className="form-label">Time Slot 1 (UTC)</label>
              <input className="form-input" type="time" value={schedule.time_slot_1} onChange={setVal('time_slot_1')} required />
            </div>

            {schedule.videos_per_day >= 2 && (
              <div className="form-group">
                <label className="form-label">Time Slot 2 (UTC)</label>
                <input className="form-input" type="time" value={schedule.time_slot_2} onChange={setVal('time_slot_2')} required />
              </div>
            )}

            {schedule.videos_per_day >= 3 && (
              <div className="form-group">
                <label className="form-label">Time Slot 3 (UTC)</label>
                <input className="form-input" type="time" value={schedule.time_slot_3} onChange={setVal('time_slot_3')} required />
              </div>
            )}

            <div className="form-group">
              <label className="form-label">Timezone</label>
              <input className="form-input" type="text" value={schedule.timezone} disabled />
              <span className="form-hint">System scheduler runs on UTC. Convert slots to your local time if needed.</span>
            </div>

            <button type="submit" className="btn btn-primary" disabled={saving} style={{ alignSelf: 'flex-start', marginTop: 10 }}>
              {saving ? <><span className="spinner" />Saving Settings…</> : 'Save Schedule Settings'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
