import { useState, useEffect } from 'react'
import Sidebar from '../components/Sidebar'
import api from '../api/client'

// Compute preview slots (same logic as backend)
function computeSlots(startTime, endTime, count) {
  const parse = t => {
    const [h, m] = t.split(':').map(Number)
    return h * 60 + m
  }
  const fmt = m => {
    const hh = Math.floor(m / 60), mm = m % 60
    return `${String(hh).padStart(2,'0')}:${String(mm).padStart(2,'0')}`
  }
  const s = parse(startTime || '09:00')
  const e = parse(endTime   || '23:00')
  if (count <= 0) return []
  if (count === 1) return [fmt(s)]
  const step = (e - s) / (count - 1)
  return Array.from({ length: count }, (_, i) => fmt(Math.round(s + i * step)))
}

export default function Schedule() {
  const [schedule, setSchedule] = useState({
    videos_per_day: 3,
    start_time:     '09:00',
    end_time:       '23:00',
    timezone:       'UTC',
    is_active:      true,
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving]   = useState(false)
  const [error, setError]     = useState('')
  const [success, setSuccess] = useState('')

  useEffect(() => {
    api.get('/schedule')
      .then(r => {
        const d = r.data
        setSchedule({
          videos_per_day: d.videos_per_day || 3,
          start_time:     d.start_time     || d.time_slot_1 || '09:00',
          end_time:       d.end_time       || d.time_slot_3 || '23:00',
          timezone:       d.timezone       || 'UTC',
          is_active:      d.is_active      ?? true,
        })
      })
      .catch(() => setError('Failed to load schedule settings'))
      .finally(() => setLoading(false))
  }, [])

  const handleSubmit = async e => {
    e.preventDefault()
    setError('')
    setSuccess('')
    setSaving(true)
    try {
      const r = await api.put('/schedule', schedule)
      setSuccess('✅ Schedule saved! Shorts will be generated automatically.')
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to update schedule')
    } finally {
      setSaving(false)
    }
  }

  const setVal = key => e => {
    const val = e.target.type === 'checkbox' ? e.target.checked
              : e.target.type === 'number'   ? Number(e.target.value)
              : e.target.value
    setSchedule(s => ({ ...s, [key]: val }))
  }

  // Preview slots
  const previewSlots = computeSlots(
    schedule.start_time,
    schedule.end_time,
    schedule.videos_per_day,
  )

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
          <p className="page-subtitle">Configure when and how often YouTube Shorts are automatically generated and uploaded</p>
        </div>

        {error   && <div className="alert alert-error"   style={{ marginBottom: 20 }}>{error}</div>}
        {success && <div className="alert alert-success" style={{ marginBottom: 20 }}>{success}</div>}

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>

          {/* Settings Card */}
          <div className="card">
            <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

              {/* Enable toggle */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'rgba(124,58,237,0.05)', padding: 16, borderRadius: 'var(--radius-md)', border: '1px solid var(--border)' }}>
                <div>
                  <div style={{ fontWeight: 600, marginBottom: 2 }}>Enable Automated Postings</div>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>Fires the automation runner automatically</div>
                </div>
                <label style={{ position: 'relative', display: 'inline-block', width: 44, height: 24 }}>
                  <input
                    type="checkbox"
                    checked={schedule.is_active}
                    onChange={setVal('is_active')}
                    style={{ opacity: 0, width: 0, height: 0 }}
                  />
                  <span style={{
                    position: 'absolute', cursor: 'pointer', top: 0, left: 0, right: 0, bottom: 0,
                    backgroundColor: schedule.is_active ? 'var(--brand-1)' : 'var(--toggle-off)',
                    transition: '.3s', borderRadius: 24,
                  }}>
                    <span style={{
                      position: 'absolute', height: 16, width: 16,
                      left: schedule.is_active ? 24 : 4, bottom: 4,
                      backgroundColor: 'white', transition: '.3s', borderRadius: '50%',
                    }} />
                  </span>
                </label>
              </div>

              {/* Videos Per Day */}
              <div className="form-group">
                <label className="form-label">Shorts Per Day</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <input
                    className="form-input"
                    type="number"
                    min={1}
                    max={100}
                    value={schedule.videos_per_day}
                    onChange={setVal('videos_per_day')}
                    style={{ width: 100 }}
                    required
                  />
                  <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                    shorts (1 – 100)
                  </span>
                </div>
                <span className="form-hint">
                  Shorts will be spread evenly between start and end time.
                </span>
              </div>

              {/* Start Time */}
              <div className="form-group">
                <label className="form-label">Start Time (UTC)</label>
                <input
                  className="form-input"
                  type="time"
                  value={schedule.start_time}
                  onChange={setVal('start_time')}
                  required
                />
                <span className="form-hint">First Short of the day will be generated at this time.</span>
              </div>

              {/* End Time */}
              <div className="form-group">
                <label className="form-label">End Time (UTC)</label>
                <input
                  className="form-input"
                  type="time"
                  value={schedule.end_time}
                  onChange={setVal('end_time')}
                  required
                />
                <span className="form-hint">Last Short of the day will be generated at this time.</span>
              </div>

              {/* Timezone */}
              <div className="form-group">
                <label className="form-label">Timezone</label>
                <input className="form-input" type="text" value="UTC" disabled />
                <span className="form-hint">Scheduler runs on UTC. Pakistan time (PKT) = UTC + 5 hours.</span>
              </div>

              <button type="submit" className="btn btn-primary" disabled={saving} style={{ alignSelf: 'flex-start', marginTop: 8 }}>
                {saving ? <><span className="spinner" />Saving…</> : '💾 Save Schedule'}
              </button>
            </form>
          </div>

          {/* Preview Card */}
          <div className="card" style={{ alignSelf: 'flex-start' }}>
            <div style={{ fontWeight: 700, fontSize: 16, marginBottom: 16, color: 'var(--brand-1)' }}>
              📅 Upload Schedule Preview
            </div>

            <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 12 }}>
              📱 <strong>{schedule.videos_per_day}</strong> Shorts/day from <strong>{schedule.start_time}</strong> to <strong>{schedule.end_time}</strong> UTC
            </div>

            {previewSlots.length > 0 ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxHeight: 400, overflowY: 'auto' }}>
                {previewSlots.map((slot, i) => (
                  <div key={i} style={{
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '8px 12px', borderRadius: 8,
                    background: 'rgba(124,58,237,0.07)',
                    border: '1px solid rgba(124,58,237,0.15)',
                  }}>
                    <span style={{
                      background: 'var(--brand-1)', color: 'white',
                      borderRadius: '50%', width: 22, height: 22,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 11, fontWeight: 700, flexShrink: 0,
                    }}>
                      {i + 1}
                    </span>
                    <span style={{ fontWeight: 600, fontSize: 14 }}>{slot} UTC</span>
                    <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 'auto' }}>
                      {(() => {
                        const [h, m] = slot.split(':').map(Number)
                        const pkt = ((h + 5) % 24)
                        return `${String(pkt).padStart(2,'0')}:${String(m).padStart(2,'0')} PKT`
                      })()}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>
                Set shorts per day to see preview
              </div>
            )}

            <div style={{ marginTop: 16, padding: '10px 14px', borderRadius: 8, background: 'rgba(34,197,94,0.07)', border: '1px solid rgba(34,197,94,0.2)', fontSize: 12, color: 'var(--text-secondary)' }}>
              💡 <strong>Tip:</strong> Pakistan time is UTC+5. If you set start at <strong>09:00 UTC</strong>, that is <strong>14:00 PKT</strong>.
            </div>
          </div>

        </div>
      </div>
    </div>
  )
}
