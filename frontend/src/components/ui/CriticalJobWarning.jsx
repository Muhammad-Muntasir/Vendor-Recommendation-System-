import { useState } from 'react'

export default function CriticalJobWarning({ urgency, slaDeadline, onAcknowledge }) {
  const [acknowledged, setAcknowledged] = useState(false)

  const isCritical = urgency === 'Critical'
  const isNearSla = slaDeadline && (new Date(slaDeadline) - new Date()) < 2 * 60 * 60 * 1000

  if (!isCritical && !isNearSla) return null

  function handleAck(e) {
    setAcknowledged(e.target.checked)
    onAcknowledge(e.target.checked)
  }

  return (
    <div role="alert" style={{ background: '#fef2f2', border: '2px solid #dc2626', borderRadius: '8px', padding: '1rem 1.25rem', marginBottom: '1rem' }}>
      <p style={{ margin: '0 0 0.75rem', fontWeight: 700, color: '#dc2626', fontSize: '1rem' }}>
        ⚠ {isCritical ? 'Critical Urgency' : 'SLA Deadline Within 2 Hours'} — Manual Review Required
      </p>
      <p style={{ margin: '0 0 0.75rem', color: '#7f1d1d', fontSize: '0.9rem' }}>
        This job requires explicit acknowledgment before accepting a recommendation.
      </p>
      <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.9rem', color: '#374151' }}>
        <input type="checkbox" checked={acknowledged} onChange={handleAck} style={{ width: '1rem', height: '1rem' }} />
        I have reviewed this job and understand the urgency before accepting.
      </label>
    </div>
  )
}
