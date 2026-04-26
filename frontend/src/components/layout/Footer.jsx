export default function Footer() {
  return (
    <footer style={{ padding: '0.75rem 1.5rem', background: '#1a1a2e', color: '#888', textAlign: 'center', fontSize: '0.85rem' }}>
      © {new Date().getFullYear()} RetailFixIt — AI Vendor Recommendation System
    </footer>
  )
}
