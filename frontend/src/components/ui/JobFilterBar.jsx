import { useState } from 'react'

export default function JobFilterBar({ onFilterChange }) {
  const [filters, setFilters] = useState({ status: '', from: '', to: '' })

  function update(key, value) {
    const next = { ...filters, [key]: value }
    setFilters(next)
    onFilterChange(next)
  }

  return (
    <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'center', marginBottom: '1rem' }}>
      <select id="job-status-filter" name="status" value={filters.status} onChange={e => update('status', e.target.value)}
        style={{ padding: '0.4rem 0.6rem', border: '1px solid #d1d5db', borderRadius: '4px', fontSize: '0.9rem' }}>
        <option value="">All Statuses</option>
        <option value="Pending">Pending</option>
        <option value="Recommended">Recommended</option>
        <option value="Assigned">Assigned</option>
        <option value="Override">Override</option>
      </select>
      <label htmlFor="job-from-date" style={{ fontSize: '0.85rem', color: '#6b7280' }}>
        From:
        <input id="job-from-date" name="from" type="date" value={filters.from} onChange={e => update('from', e.target.value)}
          style={{ marginLeft: '0.4rem', padding: '0.35rem', border: '1px solid #d1d5db', borderRadius: '4px', fontSize: '0.9rem' }} />
      </label>
      <label htmlFor="job-to-date" style={{ fontSize: '0.85rem', color: '#6b7280' }}>
        To:
        <input id="job-to-date" name="to" type="date" value={filters.to} onChange={e => update('to', e.target.value)}
          style={{ marginLeft: '0.4rem', padding: '0.35rem', border: '1px solid #d1d5db', borderRadius: '4px', fontSize: '0.9rem' }} />
      </label>
    </div>
  )
}
