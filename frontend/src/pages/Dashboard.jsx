import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import Sidebar from '../components/Sidebar'
import api from '../api/client'

const STATUS_BADGE = {
  complete: <span className="badge badge-success">✓ Uploaded</span>,
  failed:   <span className="badge badge-error">✗ Failed</span>,
  running:  <span className="badge badge-warning">⟳ Generating</span>,
  pending:  <span className="badge badge-info">◷ Pending</span>,
}

export default function Dashboard() {
  const [stats, setStats]     = useState(null)
  const [loading, setLoading] = useState(true)
  const [triggering, setTriggering] = useState(false)
  const [error, setError]     = useState('')
  const [success, setSuccess] = useState('')
  const navigate              = useNavigate()

  const fetchStats = useCallback(async () => {
    try {
      const r = await api.get('/dashboard')
      setStats(r.data)
    } catch {
      setError('Failed to load dashboard')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchStats() }, [fetchStats])

  // Poll every 15 seconds while a job is running
  useEffect(() => {
    const hasRunning = stats?.recent_jobs?.some(j => j.status === 'running' || j.status === 'pending')
    if (!hasRunning) return
    const id = setInterval(fetchStats, 15000)
    return () => clearInterval(id)
  }, [stats, fetchStats])

  const triggerJob = async () => {
    if (!stats?.channel_connected) {
      navigate('/settings')
      return
    }
    setError('')
    setSuccess('')
    setTriggering(true)
    try {
      await api.post('/jobs/trigger', {})
      setSuccess('🎬 Video generation started! Refresh in a few minutes to see progress.')
      await fetchStats()
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to trigger video generation')
    } finally {
      setTriggering(false)
    }
  }

  if (loading) return (
    <div className="app-layout">
      <Sidebar />
      <div className="main-content" style={{display:'flex',alignItems:'center',justifyContent:'center'}}>
        <div className="spinner" style={{width:40,height:40}} />
      </div>
    </div>
  )

  const statCards = [
    { icon: '🎬', label: 'Total Videos',    value: stats?.total_videos    ?? 0, color: '#7c3aed', bg: 'rgba(124,58,237,0.12)' },
    { icon: '✅', label: 'Uploaded',         value: stats?.uploaded_videos ?? 0, color: '#22c55e', bg: 'rgba(34,197,94,0.12)'  },
    { icon: '❌', label: 'Failed',           value: stats?.failed_videos   ?? 0, color: '#ef4444', bg: 'rgba(239,68,68,0.12)'  },
    { icon: '⏳', label: 'In Progress',     value: stats?.pending_videos  ?? 0, color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
  ]

  return (
    <div className="app-layout">
      <Sidebar />
      <div className="main-content">
        <div className="page-header">
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">Your AutoShorts automation overview</p>
        </div>

        {/* Channel connection warning */}
        {!stats?.channel_connected && (
          <div className="connect-banner">
            <div>
              <div style={{fontWeight:600, marginBottom:4}}>📺 Connect your YouTube channel</div>
              <div style={{fontSize:13, color:'#9898b0'}}>
                Connect your channel so AutoShorts can upload videos automatically
              </div>
            </div>
            <button className="btn btn-primary btn-sm" onClick={() => navigate('/settings')}>
              Connect Channel →
            </button>
          </div>
        )}

        {error   && <div className="alert alert-error"   style={{marginBottom:20}}>{error}</div>}
        {success && <div className="alert alert-success" style={{marginBottom:20}}>{success}</div>}

        {/* Stats */}
        <div className="stats-grid">
          {statCards.map(s => (
            <div key={s.label} className="stat-card">
              <div className="stat-icon" style={{background:s.bg, color:s.color}}>{s.icon}</div>
              <div className="stat-value" style={{color:s.color}}>{s.value}</div>
              <div className="stat-label">{s.label}</div>
            </div>
          ))}
        </div>

        {/* Schedule info + trigger */}
        <div className="card" style={{marginBottom:24, display:'flex', alignItems:'center', justifyContent:'space-between', gap:16}}>
          <div>
            <div style={{fontWeight:600, marginBottom:4}}>🗓️ Next scheduled video</div>
            <div style={{fontSize:14, color:'#9898b0'}}>
              {stats?.next_scheduled ?? 'No active schedule — enable in Schedule page'}
            </div>
          </div>
          <button
            className="btn btn-primary"
            onClick={triggerJob}
            disabled={triggering}
            id="trigger-video-btn"
          >
            {triggering ? <><span className="spinner" />Starting…</> : '▶ Generate Video Now'}
          </button>
        </div>

        {/* Recent jobs */}
        <div className="table-container">
          <div className="table-header">
            <span className="table-title">Recent Videos</span>
            <button className="btn btn-ghost btn-sm" onClick={fetchStats}>↻ Refresh</button>
          </div>

          {!stats?.recent_jobs?.length ? (
            <div className="empty-state">
              <div className="empty-state-icon">🎬</div>
              <h3>No videos yet</h3>
              <p>Click "Generate Video Now" to create your first AI-powered YouTube Short</p>
            </div>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Status</th>
                  <th>Trigger</th>
                  <th>YouTube</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {stats.recent_jobs.map(job => (
                  <tr key={job.id}>
                    <td style={{maxWidth:280}}>
                      <div style={{fontWeight:500, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap'}}>
                        {job.title || job.topic || '—'}
                      </div>
                      {job.style && <div style={{fontSize:12,color:'#9898b0',marginTop:2}}>{job.style}</div>}
                    </td>
                    <td>{STATUS_BADGE[job.status] ?? <span className="badge">{job.status}</span>}</td>
                    <td><span style={{fontSize:12,color:'#9898b0',textTransform:'capitalize'}}>{job.trigger}</span></td>
                    <td>
                      {job.youtube_url
                        ? <a href={job.youtube_url} target="_blank" rel="noreferrer"
                            style={{color:'#a78bfa', textDecoration:'none', fontSize:13}}>
                            View ↗
                          </a>
                        : <span style={{color:'#5a5a70', fontSize:13}}>—</span>
                      }
                    </td>
                    <td style={{fontSize:12,color:'#9898b0', whiteSpace:'nowrap'}}>
                      {new Date(job.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
