import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useTheme } from '../context/ThemeContext'

const NAV = [
  { to: '/dashboard', icon: '📊', label: 'Dashboard' },
  { to: '/history',   icon: '🎬', label: 'Video History' },
  { to: '/schedule',  icon: '🗓️', label: 'Schedule' },
  { to: '/settings',  icon: '⚙️', label: 'Settings' },
]

export default function Sidebar() {
  const { user, logout }   = useAuth()
  const { theme, toggleTheme } = useTheme()
  const navigate            = useNavigate()

  const handleLogout = () => { logout(); navigate('/login') }

  const initials = user?.name
    ? user.name.split(' ').map(w => w[0]).join('').slice(0,2).toUpperCase()
    : '??'

  return (
    <nav className="sidebar">
      <div className="sidebar-logo">
        <div className="sidebar-logo-icon">🎬</div>
        <span className="sidebar-logo-text gradient-text">AutoShorts</span>
      </div>

      <div className="nav-section">
        <div className="nav-section-label">Navigation</div>
        {NAV.map(n => (
          <NavLink key={n.to} to={n.to} className={({isActive}) => `nav-item${isActive ? ' active' : ''}`}>
            <span style={{fontSize:16}}>{n.icon}</span>
            {n.label}
          </NavLink>
        ))}
      </div>

      <div className="sidebar-bottom">
        <button
          className="nav-item theme-toggle"
          onClick={toggleTheme}
          title={theme === 'light' ? 'Switch to dark theme' : 'Switch to light theme'}
        >
          <span style={{fontSize:16}}>{theme === 'light' ? '🌙' : '☀️'}</span>
          {theme === 'light' ? 'Dark mode' : 'Light mode'}
        </button>
        <div className="sidebar-user">
          <div className="sidebar-avatar">{initials}</div>
          <div className="sidebar-user-info">
            <div className="sidebar-user-name">{user?.name}</div>
            <div className="sidebar-user-email">{user?.email}</div>
          </div>
        </div>
        <button className="nav-item" onClick={handleLogout} style={{marginTop:4, color:'var(--red)'}}>
          <span style={{fontSize:16}}>🚪</span>
          Sign out
        </button>
      </div>
    </nav>
  )
}
