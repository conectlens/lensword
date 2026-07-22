import { NavLink, useNavigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from '../../context/AuthContext'
import { Icon } from '../ui/Icon'

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard', icon: 'space_dashboard' },
  { to: '/rooms', label: 'Mind Palace', icon: 'meeting_room' },
  { to: '/groups', label: 'Groups', icon: 'style' },
  { to: '/mnemolab', label: 'MnemoLab', icon: 'science' },
]

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-canvas-dark">
      <header className="sticky top-0 z-40 border-b border-white/10 bg-canvas-dark/90 backdrop-blur-sm">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 md:px-8">
          <div className="flex items-center gap-8">
            <NavLink to="/dashboard" className="flex items-center gap-2 text-primary">
              <Icon name="translate" className="text-2xl" />
              <span className="font-display text-lg font-bold text-white">LensWord</span>
            </NavLink>
            <nav className="hidden items-center gap-6 md:flex">
              {NAV_ITEMS.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  className={({ isActive }) =>
                    `text-sm font-medium transition-colors ${isActive ? 'text-primary' : 'text-white/70 hover:text-white'}`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
              {user?.role === 'admin' && (
                <NavLink
                  to="/admin"
                  className={({ isActive }) => `text-sm font-medium ${isActive ? 'text-primary' : 'text-white/70 hover:text-white'}`}
                >
                  Admin
                </NavLink>
              )}
            </nav>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => navigate('/settings')}
              className="flex h-10 w-10 items-center justify-center rounded-lg bg-white/5 text-white/70 hover:bg-white/10 hover:text-white"
              aria-label="Settings"
            >
              <Icon name="tune" />
            </button>
            <button
              onClick={() => navigate('/profile')}
              className="flex h-10 w-10 items-center justify-center overflow-hidden rounded-full bg-primary/20 text-sm font-bold text-primary"
              aria-label="Profile"
            >
              {user?.username?.[0]?.toUpperCase() ?? '?'}
            </button>
            <button
              onClick={logout}
              className="hidden h-10 items-center gap-1 rounded-lg px-3 text-sm text-white/60 hover:bg-white/10 hover:text-white md:flex"
            >
              <Icon name="logout" className="text-lg" />
              Log out
            </button>
          </div>
        </div>
        <nav className="flex items-center gap-4 overflow-x-auto border-t border-white/5 px-4 py-2 md:hidden">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `whitespace-nowrap text-sm font-medium ${isActive ? 'text-primary' : 'text-white/60'}`}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8 md:px-8">{children}</main>
    </div>
  )
}
