export default function ConfidenceBadge({ confidence }) {
  const styles = {
    High:   { background: '#16a34a', color: '#fff' },
    Medium: { background: '#d97706', color: '#fff' },
    Low:    { background: '#dc2626', color: '#fff' },
  }
  const style = styles[confidence] || { background: '#6b7280', color: '#fff' }
  return (
    <span style={{ ...style, padding: '0.2rem 0.6rem', borderRadius: '9999px', fontSize: '0.75rem', fontWeight: 700, display: 'inline-block' }}
      aria-label={`Confidence: ${confidence}`}>
      {confidence}
    </span>
  )
}
