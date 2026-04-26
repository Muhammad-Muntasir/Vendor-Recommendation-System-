import { useState } from 'react'

export default function OverridePanel({ selectedVendor, onReasonChange }) {
  const [reason, setReason] = useState('')
  const MAX = 500

  function handleChange(e) {
    const val = e.target.value
    if (val.length <= MAX) {
      setReason(val)
      onReasonChange(val)
    }
  }

  return (
    <div style={{ border: '1px solid #e2e8f0', borderRadius: '8px', padding: '1rem', background: '#f8fafc' }}>
      {selectedVendor && (
        <div style={{ marginBottom: '1rem' }}>
          <h3 style={{ margin: '0 0 0.5rem', fontSize: '1rem' }}>Selected Vendor</h3>
          <p style={{ margin: 0, color: '#374151', fontSize: '0.9rem' }}>
            <strong>{selectedVendor.name || selectedVendor.vendorId}</strong>
            {selectedVendor.location && <span> — {selectedVendor.location}</span>}
          </p>
          {selectedVendor.completionRate !== undefined && (
            <p style={{ margin: '0.25rem 0 0', fontSize: '0.85rem', color: '#6b7280' }}>
              Completion rate: {(selectedVendor.completionRate * 100).toFixed(0)}% | Availability: {selectedVendor.availability}
            </p>
          )}
        </div>
      )}
      <label htmlFor="override-reason" style={{ display: 'block', fontWeight: 600, marginBottom: '0.4rem', fontSize: '0.9rem' }}>
        Override Reason <span style={{ color: '#dc2626' }}>*</span>
      </label>
      <textarea
        id="override-reason"
        value={reason}
        onChange={handleChange}
        required
        rows={4}
        placeholder="Explain why you are overriding the AI recommendation (10–500 characters)..."
        style={{ width: '100%', padding: '0.5rem', border: '1px solid #d1d5db', borderRadius: '4px', fontSize: '0.9rem', resize: 'vertical', boxSizing: 'border-box' }}
      />
      <div style={{ textAlign: 'right', fontSize: '0.8rem', color: reason.length > 490 ? '#dc2626' : '#6b7280', marginTop: '0.25rem' }}>
        {reason.length}/{MAX}
      </div>
    </div>
  )
}
