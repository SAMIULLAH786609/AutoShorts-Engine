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

function fmtNum(n) {
  if (n == null || n === 0) return '—'
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

export default function Dashboard() {
  const [stats, setStats]         = useState(null)
  const [loading, setLoading]     = useState(true)
  const [triggering, setTriggering] = useState(false)
  const [refreshing, setRefreshing] = useState({})
  const [error, setError]         = useState('')
  const [success, setSuccess]     = useState('')
  const navigate                  = useNavigate()

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

  const handleCancelJob = async (jobId) => {
    if (!window.confirm("Are you sure you want to stop this video generation?")) return
    setError('')
    setSuccess('')
    try {
      await api.post(`/jobs/${jobId}/cancel`)
      setSuccess('⏹️ Video generation stopped successfully.')
      await fetchStats()
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to stop video generation')
    }
  }

  const handleRefreshStats = async (jobId) => {
    setRefreshing(r => ({ ...r, [jobId]: true }))
    try {
      const res = await api.post(`/jobs/${jobId}/refresh-stats`)
      // Update the job in local state without full reload
      setStats(prev => ({
        ...prev,
        recent_jobs: prev.recent_jobs.map(j => j.id === jobId ? res.data : j),
      }))
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to fetch YouTube stats')
    } finally {
      setRefreshing(r => ({ ...r, [jobId]: false }))
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
                  <th style={{textAlign:'center'}}>👁 Views</th>
                  <th style={{textAlign:'center'}}>👍 Likes</th>
                  <th style={{textAlign:'center'}}>💬 Comments</th>
                  <th>Created</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {stats.recent_jobs.map(job => (
                  <tr key={job.id}>
                    <td style={{maxWidth:240}}>
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
                    {/* YouTube live stats */}
                    <td style={{textAlign:'center', fontWeight:600, color: job.yt_views ? '#a78bfa' : '#5a5a70', fontSize:13}}>
                      {fmtNum(job.yt_views)}
                    </td>
                    <td style={{textAlign:'center', fontWeight:600, color: job.yt_likes ? '#22c55e' : '#5a5a70', fontSize:13}}>
                      {fmtNum(job.yt_likes)}
                    </td>
                    <td style={{textAlign:'center', fontWeight:600, color: job.yt_comments ? '#f59e0b' : '#5a5a70', fontSize:13}}>
                      {fmtNum(job.yt_comments)}
                    </td>
                    <td style={{fontSize:12,color:'#9898b0', whiteSpace:'nowrap'}}>
                      {new Date(job.created_at).toLocaleString()}
                    </td>
                    <td style={{display:'flex', gap:4, alignItems:'center'}}>
                      {/* Stop button for active jobs */}
                      {(job.status === 'running' || job.status === 'pending') && (
                        <button
                          className="btn btn-danger btn-sm"
                          onClick={() => handleCancelJob(job.id)}
                          style={{padding:'4px 8px', fontSize:'11px', minHeight:'auto', height:'auto', lineHeight:'normal'}}
                        >
                          ■ Stop
                        </button>
                      )}
                      {/* Refresh stats button for uploaded videos */}
                      {job.status === 'complete' && job.youtube_video_id && (
                        <button
                          className="btn btn-ghost btn-sm"
                          onClick={() => handleRefreshStats(job.id)}
                          disabled={refreshing[job.id]}
                          title="Refresh YouTube stats"
                          style={{padding:'4px 8px', fontSize:'11px', minHeight:'auto', height:'auto', lineHeight:'normal'}}
                        >
                          {refreshing[job.id] ? <span className="spinner" style={{width:12,height:12}} /> : '↻'}
                        </button>
                      )}
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
