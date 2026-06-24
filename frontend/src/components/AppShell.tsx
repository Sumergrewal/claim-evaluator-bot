import { Link, NavLink, Outlet } from 'react-router-dom'

export function AppShell() {
  return (
    <div className="app">
      <header className="app-header">
        <div className="app-header__top">
          <Link to="/" className="app-header__title">
            QuickClaim
          </Link>
          <nav className="app-nav" aria-label="Main">
            <NavLink
              to="/"
              end
              className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
            >
              Claims
            </NavLink>
            <NavLink
              to="/submit"
              className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
            >
              Submit claim
            </NavLink>
          </nav>
        </div>
        <p className="app-header__tagline">
          Automated claim review — no manual reviewer in this demo
        </p>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
