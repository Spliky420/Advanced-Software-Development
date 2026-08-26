import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import HoldingsPage from './pages/HoldingsPage'
import HoldingDetailPage from './pages/HoldingDetailPage'
import HoldingNewPage from './pages/HoldingNewPage'
import HoldingEditPage from './pages/HoldingEditPage'
import AllocationPage from './pages/AllocationPage'
import TargetsPage from './pages/TargetsPage'
import DriftReviewPage from './pages/DriftReviewPage'

const NAV_ITEMS = [
  { to: '/', label: 'Holdings', end: true },
  { to: '/allocation', label: 'Allocation' },
  { to: '/targets', label: 'Targets' },
  { to: '/drift', label: 'Drift review' },
]

function NotFoundPage() {
  return (
    <section className="page">
      <h2>Page not found</h2>
      <p className="empty-state">
        That page does not exist. <a href="/">Return to holdings.</a>
      </p>
    </section>
  )
}

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <h1 className="app-title">Portfolio Holdings</h1>
        <nav className="app-nav" aria-label="Main">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? 'nav-link nav-link-active' : 'nav-link')}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="app-main">
        <Routes>
          <Route path="/" element={<HoldingsPage />} />
          <Route path="/holdings" element={<Navigate to="/" replace />} />
          <Route path="/holdings/new" element={<HoldingNewPage />} />
          <Route path="/holdings/:id" element={<HoldingDetailPage />} />
          <Route path="/holdings/:id/edit" element={<HoldingEditPage />} />
          <Route path="/allocation" element={<AllocationPage />} />
          <Route path="/targets" element={<TargetsPage />} />
          <Route path="/drift" element={<DriftReviewPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>

      <footer className="app-footer">
        Figures are calculated by the backend in Python. The model only writes commentary around
        already-computed values.
      </footer>
    </div>
  )
}
