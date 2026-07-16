import { NavLink, Outlet } from 'react-router-dom'
import './layout.css'

const links = [
  { to: '/console', end: true, label: 'Overview' },
  { to: '/console/runs', label: 'Runs' },
  { to: '/console/editorial', label: 'Editorial' },
]

export function ConsoleLayout() {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">Connor Console</div>
        <nav>
          {links.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.end} className={({ isActive }) => (isActive ? 'nav active' : 'nav')}>
              {l.label}
            </NavLink>
          ))}
        </nav>
        <p className="hint">Internal annotation & ops. Production data is read-only.</p>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}
