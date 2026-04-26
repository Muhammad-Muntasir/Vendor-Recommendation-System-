import { useParams, useNavigate } from 'react-router-dom'
import { useRecommendations } from '../hooks/useRecommendations.js'
import { acceptRecommendation } from '../services/api.js'
import { useState } from 'react'
import VendorCard from '../components/ui/VendorCard.jsx'
import FallbackBanner from '../components/ui/FallbackBanner.jsx'
import LoadingSpinner from '../components/ui/LoadingSpinner.jsx'
import ErrorBanner from '../components/ui/ErrorBanner.jsx'

export default function RecommendationsPage() {
  const { jobId } = useParams()
  const navigate = useNavigate()
  const { recommendations, isFallback, isLoading, error, refetch } = useRecommendations(jobId)
  const [acceptSuccess, setAcceptSuccess] = useState(null)
  const [acceptError, setAcceptError] = useState(null)

  async function handleAccept(rec) {
    setAcceptError(null)
    try {
      await acceptRecommendation(jobId)
      setAcceptSuccess(`Vendor ${rec.vendorId} accepted for job ${jobId}.`)
    } catch (err) {
      setAcceptError(err.message || 'Failed to accept recommendation.')
    }
  }

  function handleOverride(rec) {
    navigate(`/override/${jobId}`)
  }

  const hasLowConfidence = recommendations.some(r => r.confidence === 'Low')

  return (
    <div style={{ maxWidth: '800px' }}>
      <button onClick={() => navigate(`/jobs/${jobId}`)} style={{ background: 'none', border: 'none', color: '#e94560', cursor: 'pointer', marginBottom: '1rem', fontSize: '0.9rem' }}>
        ← Back to Job
      </button>

      <h2 style={{ margin: '0 0 0.5rem', fontSize: '1.2rem', color: '#1a1a2e' }}>Vendor Recommendations</h2>
      <p style={{ margin: '0 0 1rem', fontSize: '0.85rem', color: '#6b7280' }}>Job ID: {jobId}</p>

      {isFallback && <FallbackBanner />}

      {hasLowConfidence && (
        <div role="alert" style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: '6px', padding: '0.6rem 1rem', color: '#dc2626', marginBottom: '1rem', fontSize: '0.9rem' }}>
          ⚠ One or more recommendations have <strong>Low</strong> confidence. Manual review is recommended before accepting.
        </div>
      )}

      {acceptSuccess && (
        <div role="status" style={{ background: '#f0fdf4', border: '1px solid #86efac', borderRadius: '6px', padding: '0.6rem 1rem', color: '#16a34a', marginBottom: '1rem', fontSize: '0.9rem' }}>
          ✓ {acceptSuccess}
        </div>
      )}

      {acceptError && <ErrorBanner message={acceptError} onRetry={() => setAcceptError(null)} />}

      {isLoading ? <LoadingSpinner /> : error ? (
        <ErrorBanner message={error} onRetry={refetch} />
      ) : recommendations.length === 0 ? (
        <p style={{ color: '#9ca3af', textAlign: 'center', padding: '2rem' }}>No recommendations available for this job yet.</p>
      ) : (
        recommendations
          .sort((a, b) => b.totalScore - a.totalScore)
          .map(rec => (
            <VendorCard
              key={rec.vendorId}
              recommendation={rec}
              onAccept={handleAccept}
              onOverride={handleOverride}
              acceptDisabled={!!acceptSuccess}
            />
          ))
      )}
    </div>
  )
}
