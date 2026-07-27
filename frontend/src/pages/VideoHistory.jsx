import { useState, useEffect, useCallback } from 'react'
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

export default function VideoHistory() {
  const [jobs, setJobs]           = useState([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState('')
  const [page, setPage]           = useState(1)
  const [hasMore, setHasMore]     = useState(true)
  const [refreshing, setRefreshing] = useState({})

  const fetchJobs = useCallback(async (pageNum) => {
    try {
      const r = await api.get('/jobs', { params: { page: pageNum, page_size: 15 } })
      if (pageNum === 1) {
        setJobs(r.data)
      } else {
        setJobs(prev => [...prev, ...r.data])
      }
      setHasMore(r.data.length >= 15)
    } catch {
      setError('Failed to load video history')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchJobs(page) }, [page, fetchJobs])

  const handleLoadMore = () => setPage(p => p + 1)

  const handleDelete = async (id) => {
    if (!window.confirm('Are you sure you want to delete this job record?')) return
    try {
      await api.delete(`/jobs/${id}`)
      setJobs(prev => prev.filter(j => j.id !== id))
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to delete record')
    }
  }

  const handleRefreshStats = async (jobId) => {
    setRefreshing(r => ({ ...r, [jobId]: true }))
    setError('')
    try {
      const res = await api.post(`/jobs/${jobId}/refresh-stats`)
      setJobs(prev => prev.map(j => j.id === jobId ? res.data : j))
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to fetch YouTube stats')
    } finally {
      setRefreshing(r => ({ ...r, [jobId]: false }))
    }
  }

  return (
    <div className="app-layout">
      <Sidebar />
      <div className="main-content">
        <div className="page-header">
          <h1 className="page-title">Video History</h1>
          <p className="page-subtitle">View your generated videos, YouTube stats, and generation logs</p>
        </div>

        {error && <div className="alert alert-error" style={{ marginBottom: 20 }}>{error}</div>}

        <div className="table-container">
          <div className="table-header">
            <span className="table-title">History Logs</span>
            <button className="btn btn-ghost btn-sm" onClick={() => { setPage(1); fetchJobs(1); }}>↻ Refresh</button>
          </div>

          {loading && page === 1 ? (
            <div style={{ display: 'flex', justifyContent: 'center', padding: '40px 0' }}>
              <span className="spinner" style={{ width: 32, height: 32 }} />
            </div>
          ) : !jobs.length ? (
            <div className="empty-state">
              <div className="empty-state-icon">🎬</div>
              <h3>No history logs</h3>
              <p>You haven't generated any videos yet.</p>
            </div>
          ) : (
            <>
              <table>
                <thead>
                  <tr>
                    <th>Title &amp; Niche</th>
                    <th>Status</th>
                    <th>YouTube</th>
                    <th style={{textAlign:'center'}}>👁 Views</th>
                    <th style={{textAlign:'center'}}>👍 Likes</th>
                    <th style={{textAlign:'center'}}>💬 Comments</th>
                    <th>Duration &amp; Mode</th>
                    <th>Created At</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {jobs.map(job => (
                    <tr key={job.id}>
                      <td style={{ maxWidth: 280 }}>
                        <div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {job.title || job.topic || '—'}
                        </div>
                        {job.style && (
                          <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
                            Style: {job.style}
                          </div>
                        )}
                        {job.error_message && (
                          <div style={{ fontSize: 11, color: 'var(--red)', marginTop: 4, background: 'rgba(239,68,68,0.05)', padding: '4px 8px', borderRadius: 4, borderLeft: '2px solid var(--red)' }}>
                            Error: {job.error_message}
                          </div>
                        )}
                      </td>
                      <td>{STATUS_BADGE[job.status] || <span className="badge">{job.status}</span>}</td>
                      <td>
                        {job.youtube_url ? (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                            <a href={job.youtube_url} target="_blank" rel="noreferrer" style={{ color: '#a78bfa', textDecoration: 'none', fontWeight: 500 }}>
                              Watch Short ↗
                            </a>
                            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>ID: {job.youtube_video_id}</span>
                          </div>
                        ) : (
                          <span style={{ color: 'var(--text-muted)' }}>Not uploaded</span>
                        )}
                      </td>
                      {/* YouTube live stats */}
                      <td style={{textAlign:'center', fontWeight:600, color: job.yt_views ? '#a78bfa' : '#5a5a70', fontSize:14}}>
                        {fmtNum(job.yt_views)}
                      </td>
                      <td style={{textAlign:'center', fontWeight:600, color: job.yt_likes ? '#22c55e' : '#5a5a70', fontSize:14}}>
                        {fmtNum(job.yt_likes)}
                      </td>
                      <td style={{textAlign:'center', fontWeight:600, color: job.yt_comments ? '#f59e0b' : '#5a5a70', fontSize:14}}>
                        {fmtNum(job.yt_comments)}
                      </td>
                      <td>
                        <div style={{ fontWeight: 500 }}>{job.duration ? `${job.duration.toFixed(1)}s` : '—'}</div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'capitalize' }}>
                          Trigger: {job.trigger}
                        </div>
                        {job.yt_stats_updated && (
                          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
                            Stats: {new Date(job.yt_stats_updated).toLocaleString()}
                          </div>
                        )}
                      </td>
                      <td style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                        {new Date(job.created_at).toLocaleString()}
                      </td>
                      <td style={{display:'flex', gap:4, alignItems:'center', flexWrap:'wrap'}}>
                        {/* Refresh stats button for uploaded videos */}
                        {job.status === 'complete' && job.youtube_video_id && (
                          <button
                            className="btn btn-ghost btn-sm"
                            onClick={() => handleRefreshStats(job.id)}
                            disabled={refreshing[job.id]}
                            title="Refresh YouTube stats (views, likes, comments)"
                            style={{padding:'4px 8px', fontSize:'11px', minHeight:'auto', height:'auto', lineHeight:'normal'}}
                          >
                            {refreshing[job.id]
                              ? <span className="spinner" style={{width:12,height:12}} />
                              : '↻ Stats'}
                          </button>
                        )}
                        <button
                          className="btn btn-ghost btn-sm btn-icon"
                          style={{ color: 'var(--red)' }}
                          onClick={() => handleDelete(job.id)}
                          disabled={job.status === 'running'}
                          title="Delete record"
                        >
                          🗑️
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              {hasMore && (
                <div style={{ display: 'flex', justifyContent: 'center', padding: '20px 24px', borderTop: '1px solid var(--border)' }}>
                  <button className="btn btn-secondary btn-sm" onClick={handleLoadMore}>
                    Load More Logs
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}
