import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getRecommendations, submitOverride } from '../services/api.js'
import OverridePanel from '../components/ui/OverridePanel.jsx'
import LoadingSpinner from '../components/ui/LoadingSpinner.jsx'
import ErrorBanner from '../components/ui/ErrorBanner.jsx'
import { useAuth } from '../hooks/useAuth.js'

export default function OverridePage() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const { user } = useAuth()

  const [recommendations, setRecommendations] = useState([])
  const [selectedVendorId, setSelectedVendorId] = useState('')
  const [overrideReason, setOverrideReason] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [submitLoading, setSubmitLoading] = useState(false)
  const [error, setError] = useState(null)
  const [submitError, setSubmitError] = useState(null)
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    getRecommendations(jobId)
      .then(data => setRecommendations(data.recommendations || []))
      .catch(err => setError(err.message || 'Failed to load recommendations.'))
      .finally(() => setIsLoading(false))
  }, [jobId])

  const selectedVendor = recommendations.find(r => r.vendorId === selectedVendorId)

  async function handleSubmit(e) {
    e.preventDefault()
    if (!selectedVendorId) { setSubmitError('Please select a vendor.'); return }
    if (overrideReason.length < 10) { setSubmitError('Override reason must be at least 10 characters.'); return }
    setSubmitError(null)
    setSubmitLoading(true)
    try {
      await submitOverride({ jobId, vendorId: selectedVendorId, overrideReason, userId: user?.email || 'admin' })
      setSuccess(true)
    } catch (err) {
      setSubmitError(err.message || 'Failed to submit override.')
    } finally {
      setSubmitLoading(false)
    }
  }

  if (isLoading) return <LoadingSpinner />
  if (error) return <ErrorBanner message={error} onRetry={() => navigate(0)} />

  if (success) return (
    <div style={{ maxWidth: '600px' }}>
      <div style={{ background: '#f0fdf4', border: '1px solid #86efac', borderRadius: '8px', padding: '1.5rem', textAlign: 'center' }}>
        <p style={{ fontWeight: 700, color: '#16a34a', fontSize: '1.1rem', marginBottom: '0.5rem' }}>✓ Override Recorded</p>
        <p style={{ color: '#374151', marginBottom: '1rem' }}>Job status updated to <strong>Vendor Assigned — Override</strong>.</p>
        <button onClick={() => navigate(`/jobs/${jobId}`)} style={{ background: '#e94560', color: '#fff', border: 'none', padding: '0.5rem 1.2rem', borderRadius: '4px', cursor: 'pointer' }}>
          Back to Job
        </button>
      </div>
    </div>
  )

  return (
    <div style={{ maxWidth: '700px' }}>
      <button onClick={() => navigate(`/recommendations/${jobId}`)} style={{ background: 'none', border: 'none', color: '#e94560', cursor: 'pointer', marginBottom: '1rem', fontSize: '0.9rem' }}>
        ← Back to Recommendations
      </button>

      <h2 style={{ margin: '0 0 0.5rem', fontSize: '1.2rem', color: '#1a1a2e' }}>Override Recommendation</h2>
      <p style={{ margin: '0 0 1.25rem', fontSize: '0.85rem', color: '#6b7280' }}>Job ID: {jobId}</p>

      {/* Current AI recommendations */}
      {recommendations.length > 0 && (
        <div style={{ marginBottom: '1.25rem' }}>
          <h3 style={{ fontSize: '0.95rem', fontWeight: 600, color: '#374151', marginBottom: '0.5rem' }}>Current AI Recommendations</h3>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
            {recommendations.map(r => (
              <span key={r.vendorId} style={{ background: '#f1f5f9', padding: '0.25rem 0.6rem', borderRadius: '4px', fontSize: '0.82rem', color: '#374151' }}>
                #{r.rank} {r.vendorId} ({(r.totalScore * 100).toFixed(1)}%)
              </span>
            ))}
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit}>
        {/* Vendor selection */}
        <label style={{ display: 'block', fontWeight: 600, fontSize: '0.9rem', marginBottom: '0.4rem', color: '#374151' }}>
          Select Vendor <span style={{ color: '#dc2626' }}>*</span>
        </label>
        <select value={selectedVendorId} onChange={e => setSelectedVendorId(e.target.value)} required
          style={{ width: '100%', padding: '0.5rem', border: '1px solid #d1d5db', borderRadius: '4px', fontSize: '0.9rem', marginBottom: '1rem', boxSizing: 'border-box' }}>
          <option value="">— Choose a vendor —</option>
          {recommendations.map(r => (
            <option key={r.vendorId} value={r.vendorId}>
              {r.vendorId} (Score: {(r.totalScore * 100).toFixed(1)}%)
            </option>
          ))}
        </select>

        <OverridePanel
          selectedVendor={selectedVendor ? { vendorId: selectedVendor.vendorId, completionRate: selectedVendor.scoreFactors?.completionScore, availability: selectedVendor.scoreFactors?.availabilityScore >= 1 ? 'available' : 'busy' } : null}
          onReasonChange={setOverrideReason}
        />

        {submitError && <ErrorBanner message={submitError} onRetry={() => setSubmitError(null)} />}

        <button type="submit" disabled={submitLoading || overrideReason.length < 10}
          style={{ marginTop: '1rem', padding: '0.6rem 1.5rem', background: (submitLoading || overrideReason.length < 10) ? '#9ca3af' : '#e94560', color: '#fff', border: 'none', borderRadius: '4px', cursor: (submitLoading || overrideReason.length < 10) ? 'not-allowed' : 'pointer', fontWeight: 600 }}>
          {submitLoading ? 'Submitting…' : 'Submit Override'}
        </button>
      </form>
    </div>
  )
}
