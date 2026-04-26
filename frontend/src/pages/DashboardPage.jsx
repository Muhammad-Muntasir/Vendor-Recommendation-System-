import { useState, useEffect } from 'react'
import { getDashboardMetrics } from '../services/api.js'
import MetricCard from '../components/ui/MetricCard.jsx'
import AIStatusBadge from '../components/ui/AIStatusBadge.jsx'
import LoadingSpinner from '../components/ui/LoadingSpinner.jsx'
import ErrorBanner from '../components/ui/ErrorBanner.jsx'

export default function DashboardPage() {
  const [metrics, setMetrics] = useState(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)

  async function fetchMetrics() {
    setIsLoading(true)
    setError(null)
    try {
      const data = await getDashboardMetrics()
      setMetrics(data)
    } catch (err) {
      setError(err.response?.data?.error?.message || err.message || 'Failed to load dashboard metrics.')
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => { fetchMetrics() }, [])

  if (isLoading) return <LoadingSpinner />
  if (error) return <ErrorBanner message={error} onRetry={fetchMetrics} />

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
        <h2 style={{ margin: 0, fontSize: '1.3rem', color: '#1a1a2e' }}>Dashboard</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '0.85rem', color: '#6b7280' }}>AI Service:</span>
          <AIStatusBadge status={metrics?.aiServiceStatus || 'Active'} />
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: '1rem', marginBottom: '1.5rem' }}>
        <MetricCard label="Jobs Today" value={metrics?.totalJobsToday ?? 0} />
        <MetricCard label="Recommendations Today" value={metrics?.totalRecommendationsToday ?? 0} />
        <MetricCard label="Overrides Today" value={metrics?.totalOverridesToday ?? 0} />
        <MetricCard label="Fallback Activations" value={metrics?.fallbackActivationsToday ?? 0} />
      </div>

      {metrics?.lowConfidenceRateToday > 0 && (
        <div style={{ background: '#fef3c7', border: '1px solid #d97706', borderRadius: '6px', padding: '0.75rem 1rem', color: '#92400e', fontSize: '0.9rem' }}>
          ⚠ Low-confidence rate today: <strong>{(metrics.lowConfidenceRateToday * 100).toFixed(1)}%</strong>
          {metrics.lowConfidenceRateToday > 0.3 && ' — exceeds 30% threshold. Review scoring model.'}
        </div>
      )}

      <p style={{ marginTop: '1rem', fontSize: '0.8rem', color: '#9ca3af' }}>
        Date: {metrics?.date || new Date().toISOString().slice(0, 10)}
      </p>
    </div>
  )
}
