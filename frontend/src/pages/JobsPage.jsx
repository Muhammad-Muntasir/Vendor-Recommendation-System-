import { useState, useEffect, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getJobs, getJob } from '../services/api.js'
import JobFilterBar from '../components/ui/JobFilterBar.jsx'
import LoadingSpinner from '../components/ui/LoadingSpinner.jsx'
import ErrorBanner from '../components/ui/ErrorBanner.jsx'
import CriticalJobWarning from '../components/ui/CriticalJobWarning.jsx'

const URGENCY_COLORS = { Critical: '#dc2626', High: '#d97706', Medium: '#2563eb', Low: '#16a34a' }

export default function JobsPage() {
  const [jobs, setJobs] = useState([])
  const [nextToken, setNextToken] = useState(null)
  const [filters, setFilters] = useState({})
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)
  const navigate = useNavigate()

  const fetchJobs = useCallback(async (token = null) => {
    setIsLoading(true)
    setError(null)
    try {
      const params = { ...filters, limit: 20 }
      if (token) params.nextToken = token
      const data = await getJobs(params)
      setJobs(token ? prev => [...prev, ...(data.items || [])] : (data.items || []))
      setNextToken(data.nextToken || null)
    } catch (err) {
      setError(err.response?.data?.error?.message || err.message || 'Failed to load jobs.')
    } finally {
      setIsLoading(false)
    }
  }, [filters])

  useEffect(() => { fetchJobs() }, [fetchJobs])

  function handleFilterChange(f) { setFilters(f) }

  return (
    <div>
      <h2 style={{ margin: '0 0 1rem', fontSize: '1.3rem', color: '#1a1a2e' }}>Jobs</h2>
      <JobFilterBar onFilterChange={handleFilterChange} />

      {error && <ErrorBanner message={error} onRetry={() => fetchJobs()} />}
      {isLoading && !jobs.length ? <LoadingSpinner /> : (
        <>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem' }}>
              <thead>
                <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                  {['Job ID', 'Type', 'Location', 'Urgency', 'SLA Deadline', 'Status'].map(h => (
                    <th key={h} style={{ padding: '0.6rem 0.8rem', textAlign: 'left', fontWeight: 600, color: '#374151', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {jobs.map(job => (
                  <tr key={job.jobId} onClick={() => navigate(`/jobs/${job.jobId}`)}
                    style={{ borderBottom: '1px solid #f1f5f9', cursor: 'pointer' }}
                    onMouseEnter={e => e.currentTarget.style.background = '#f8fafc'}
                    onMouseLeave={e => e.currentTarget.style.background = ''}>
                    <td style={{ padding: '0.6rem 0.8rem', fontFamily: 'monospace', fontSize: '0.8rem', color: '#6b7280' }}>{job.jobId?.slice(0, 8)}…</td>
                    <td style={{ padding: '0.6rem 0.8rem' }}>{job.type}</td>
                    <td style={{ padding: '0.6rem 0.8rem' }}>{job.location}</td>
                    <td style={{ padding: '0.6rem 0.8rem' }}>
                      <span style={{ color: URGENCY_COLORS[job.urgency] || '#374151', fontWeight: 600 }}>{job.urgency}</span>
                    </td>
                    <td style={{ padding: '0.6rem 0.8rem', whiteSpace: 'nowrap' }}>{job.slaDeadline?.slice(0, 16).replace('T', ' ')}</td>
                    <td style={{ padding: '0.6rem 0.8rem' }}>
                      <span style={{ background: '#f1f5f9', padding: '0.15rem 0.5rem', borderRadius: '9999px', fontSize: '0.8rem' }}>{job.status}</span>
                    </td>
                  </tr>
                ))}
                {!isLoading && !jobs.length && (
                  <tr><td colSpan={6} style={{ padding: '2rem', textAlign: 'center', color: '#9ca3af' }}>No jobs found.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          {nextToken && (
            <button onClick={() => fetchJobs(nextToken)} disabled={isLoading}
              style={{ marginTop: '1rem', padding: '0.5rem 1.2rem', background: '#1a1a2e', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer' }}>
              Load more
            </button>
          )}
        </>
      )}
    </div>
  )
}

export function JobDetailPage() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const [job, setJob] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)
  const [criticalAcknowledged, setCriticalAcknowledged] = useState(false)

  useEffect(() => {
    setIsLoading(true)
    getJob(jobId)
      .then(data => setJob(data))
      .catch(err => setError(err.message || 'Failed to load job.'))
      .finally(() => setIsLoading(false))
  }, [jobId])

  if (isLoading) return <LoadingSpinner />
  if (error) return <ErrorBanner message={error} onRetry={() => navigate(0)} />
  if (!job) return null

  return (
    <div style={{ maxWidth: '700px' }}>
      <button onClick={() => navigate('/jobs')} style={{ background: 'none', border: 'none', color: '#e94560', cursor: 'pointer', marginBottom: '1rem', fontSize: '0.9rem' }}>
        ← Back to Jobs
      </button>

      <CriticalJobWarning urgency={job.urgency} slaDeadline={job.slaDeadline} onAcknowledge={setCriticalAcknowledged} />

      <h2 style={{ margin: '0 0 1rem', fontSize: '1.2rem', color: '#1a1a2e' }}>Job Detail</h2>

      <div style={{ background: '#fff', border: '1px solid #e2e8f0', borderRadius: '8px', padding: '1.25rem' }}>
        {[
          ['Job ID', job.jobId],
          ['Type', job.type],
          ['Location', job.location],
          ['Urgency', job.urgency],
          ['SLA Deadline', job.slaDeadline],
          ['Description', job.description],
          ['Created At', job.createdAt],
          ['Status', job.status],
          ['Schema Version', job.schemaVersion],
        ].map(([label, value]) => (
          <div key={label} style={{ display: 'flex', gap: '1rem', padding: '0.5rem 0', borderBottom: '1px solid #f1f5f9' }}>
            <span style={{ minWidth: '140px', fontWeight: 600, color: '#6b7280', fontSize: '0.85rem' }}>{label}</span>
            <span style={{ color: '#374151', fontSize: '0.9rem' }}>{value}</span>
          </div>
        ))}
      </div>

      <div style={{ marginTop: '1rem', display: 'flex', gap: '0.75rem' }}>
        <button
          onClick={() => navigate(`/recommendations/${jobId}`)}
          disabled={job.urgency === 'Critical' && !criticalAcknowledged}
          style={{ padding: '0.5rem 1.2rem', background: (job.urgency === 'Critical' && !criticalAcknowledged) ? '#9ca3af' : '#e94560', color: '#fff', border: 'none', borderRadius: '4px', cursor: (job.urgency === 'Critical' && !criticalAcknowledged) ? 'not-allowed' : 'pointer' }}>
          View Recommendations
        </button>
      </div>
    </div>
  )
}
