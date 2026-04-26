import { useState } from 'react'
import ConfidenceBadge from './ConfidenceBadge.jsx'
import RationaleBox from './RationaleBox.jsx'

const SCORE_LABELS = {
  completionScore: 'Completion Rate',
  availabilityScore: 'Availability',
  reworkScore: 'Rework Rate',
  locationScore: 'Location',
  specializationScore: 'Specialization',
  responseTimeScore: 'Response Time',
  slaBreachScore: 'SLA History',
  activeJobsScore: 'Workload',
}

export default function VendorCard({ recommendation, onAccept, onOverride, acceptDisabled }) {
  const { rank, vendorId, totalScore, scoreFactors, rationale, confidence, isAIGenerated } = recommendation

  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: '8px', padding: '1.25rem', marginBottom: '1rem', background: '#fff', boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <span style={{ background: '#1a1a2e', color: '#fff', borderRadius: '50%', width: '2rem', height: '2rem', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700, fontSize: '0.9rem' }}>#{rank}</span>
          <span style={{ fontWeight: 600, fontSize: '0.95rem', color: '#374151' }}>{vendorId}</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '0.85rem', color: '#6b7280' }}>Score: <strong style={{ color: '#1a1a2e' }}>{(totalScore * 100).toFixed(1)}%</strong></span>
          <ConfidenceBadge confidence={confidence} />
        </div>
      </div>

      {/* Score bar */}
      <div style={{ background: '#f1f5f9', borderRadius: '4px', height: '6px', marginBottom: '0.75rem' }}>
        <div style={{ background: '#e94560', height: '6px', borderRadius: '4px', width: `${totalScore * 100}%` }} />
      </div>

      {/* Score factors breakdown */}
      {scoreFactors && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: '0.4rem', marginBottom: '0.75rem' }}>
          {Object.entries(SCORE_LABELS).map(([key, label]) => (
            <div key={key} style={{ fontSize: '0.78rem', color: '#6b7280' }}>
              <span>{label}: </span>
              <strong style={{ color: '#374151' }}>{((scoreFactors[key] || 0) * 100).toFixed(0)}%</strong>
            </div>
          ))}
        </div>
      )}

      <RationaleBox rationale={rationale} isAIGenerated={isAIGenerated} />

      <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
        <button onClick={() => onAccept(recommendation)} disabled={acceptDisabled}
          style={{ background: acceptDisabled ? '#9ca3af' : '#16a34a', color: '#fff', border: 'none', padding: '0.4rem 1rem', borderRadius: '4px', cursor: acceptDisabled ? 'not-allowed' : 'pointer', fontSize: '0.9rem' }}>
          Accept
        </button>
        <button onClick={() => onOverride(recommendation)}
          style={{ background: '#e94560', color: '#fff', border: 'none', padding: '0.4rem 1rem', borderRadius: '4px', cursor: 'pointer', fontSize: '0.9rem' }}>
          Override
        </button>
      </div>
    </div>
  )
}
