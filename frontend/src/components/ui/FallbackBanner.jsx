export default function FallbackBanner() {
  return (
    <div role="alert" aria-live="polite" style={{ background: '#fef3c7', borderBottom: '2px solid #d97706', color: '#92400e', padding: '0.6rem 1.5rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
      <span aria-hidden="true">⚠️</span>
      AI rationale is currently unavailable. Recommendations are rule-based (Fallback mode active).
    </div>
  )
}
