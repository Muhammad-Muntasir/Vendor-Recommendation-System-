export default function RationaleBox({ rationale, isAIGenerated }) {
  return (
    <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '6px', padding: '0.75rem 1rem', marginTop: '0.5rem' }}>
      <div style={{ fontSize: '0.7rem', fontWeight: 700, color: isAIGenerated ? '#2563eb' : '#d97706', marginBottom: '0.4rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        {isAIGenerated ? '🤖 AI-Generated Rationale' : '📋 Rule-Based Rationale'}
      </div>
      <p style={{ margin: 0, fontSize: '0.9rem', color: '#374151', lineHeight: 1.5 }}>{rationale}</p>
    </div>
  )
}
