import { useState } from 'react'

const ACTION_TYPES = ['AI_RECOMMENDATION', 'ADMIN_OVERRIDE', 'FALLBACK_RECOMMENDATION', 'AI_RECOMMENDATION_ACCEPTED', 'DLQ_FAILURE']

export default function AuditFilterBar({ onFilterChange }) {
  const [filters, setFilters] = useState({ action: '', from: '', to: '', jobId: '', vendorId: '' })

  function update(key, value) {
    const next = { ...filters, [key]: value }
    setFilters(next)
    onFilterChange(next)
  }

  const inputStyle = { padding: '0.35rem 0.5rem', border: '1px solid #d1d5db', borderRadius: '4px', fontSize: '0.85rem' }

  return (
    <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap', alignItems: 'center', marginBottom: '1rem' }}>
      <select id="audit-action-filter" name="action" value={filters.action} onChange={e => update('action', e.target.value)} style={inputStyle}>
        <option value="">All Actions</option>
        {ACTION_TYPES.map(a => <option key={a} value={a}>{a}</option>)}
      </select>
      <label htmlFor="audit-from-date" style={{ fontSize: '0.82rem', color: '#6b7280' }}>
        From: <input id="audit-from-date" name="from" type="date" value={filters.from} onChange={e => update('from', e.target.value)} style={{ ...inputStyle, marginLeft: '0.3rem' }} />
      </label>
      <label htmlFor="audit-to-date" style={{ fontSize: '0.82rem', color: '#6b7280' }}>
        To: <input id="audit-to-date" name="to" type="date" value={filters.to} onChange={e => update('to', e.target.value)} style={{ ...inputStyle, marginLeft: '0.3rem' }} />
      </label>
      <input id="audit-job-id" name="jobId" placeholder="Job ID" value={filters.jobId} onChange={e => update('jobId', e.target.value)} style={{ ...inputStyle, width: '140px' }} />
      <input id="audit-vendor-id" name="vendorId" placeholder="Vendor ID" value={filters.vendorId} onChange={e => update('vendorId', e.target.value)} style={{ ...inputStyle, width: '140px' }} />
    </div>
  )
}
