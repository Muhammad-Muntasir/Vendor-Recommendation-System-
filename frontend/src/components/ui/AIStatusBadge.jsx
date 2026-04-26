export default function AIStatusBadge({ status }) {
  const isActive = status === 'Active'
  return (
    <span style={{
      background: isActive ? '#16a34a' : '#d97706',
      color: '#fff',
      padding: '0.25rem 0.75rem',
      borderRadius: '9999px',
      fontSize: '0.8rem',
      fontWeight: 700,
      display: 'inline-flex',
      alignItems: 'center',
      gap: '0.3rem',
    }} aria-label={`AI Service Status: ${status}`}>
      <span aria-hidden="true">{isActive ? '●' : '◐'}</span>
      {status}
    </span>
  )
}
