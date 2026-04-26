import { NavLink } from 'react-router-dom'

const navItems = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/jobs', label: 'Jobs' },
  { to: '/audit-logs', label: 'Audit Log' },
]

export default function Sidebar() {
  return (
    <aside style={{ width: '200px', minHeight: '100vh', background: '#16213e', padding: '1rem 0' }}>
      <nav>
        <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
          {navItems.map(({ to, label }) => (
            <li key={to}>
              <NavLink
                to={to}
                style={({ isActive }) => ({
                  display: 'block',
                  padding: '0.6rem 1.2rem',
                  color: isActive ? '#e94560' : '#ccc',
                  fontWeight: isActive ? 700 : 400,
                  textDecoration: 'none',
                  borderLeft: isActive ? '3px solid #e94560' : '3px solid transparent',
                })}
              >
                {label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  )
}
