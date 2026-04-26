import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth.js'

export default function Header({ title }) {
  const { logout } = useAuth()
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/auth')
  }

  return (
    <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0.75rem 1.5rem', background: '#1a1a2e', color: '#fff' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
        <span style={{ fontWeight: 700, fontSize: '1.2rem', color: '#e94560' }}>RetailFixIt</span>
        {title && <span style={{ fontSize: '1rem', color: '#ccc' }}>{title}</span>}
      </div>
      <nav>
        <button
          onClick={handleLogout}
          style={{ background: '#e94560', color: '#fff', border: 'none', padding: '0.4rem 1rem', borderRadius: '4px', cursor: 'pointer' }}
          aria-label="Logout"
        >
          Logout
        </button>
      </nav>
    </header>
  )
}
