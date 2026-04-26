export default function ErrorBanner({ message, onRetry }) {
  // Safely convert any error type (string, Error object, Axios error) to a string
  const text = typeof message === 'string'
    ? message
    : message?.response?.data?.error?.message
      || message?.message
      || 'An unexpected error occurred.'

  return (
    <div role="alert" style={{ background: '#fef2f2', border: '1px solid #fca5a5', borderRadius: '6px', padding: '0.75rem 1rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem', marginBottom: '1rem' }}>
      <span style={{ color: '#dc2626', fontWeight: 500 }}>⚠ {text}</span>
      {onRetry && (
        <button onClick={onRetry} style={{ background: '#dc2626', color: '#fff', border: 'none', padding: '0.3rem 0.8rem', borderRadius: '4px', cursor: 'pointer', fontSize: '0.85rem', flexShrink: 0 }}>
          Retry
        </button>
      )}
    </div>
  )
}
