import { Link, Navigate, Route, Routes } from 'react-router-dom'
import DashboardPage from './pages/DashboardPage'
import GoalDetailPage from './pages/GoalDetailPage'
import GoalEditPage from './pages/GoalEditPage'
import GoalNewPage from './pages/GoalNewPage'

export default function App() {
  return (
    <div className="container container--wide">
      <header className="app-header">
        <div>
          <h1>Goals and Budgeting</h1>
          <p className="tagline">
            Set a savings goal, let the assistant plan it, and watch it react as you go.
          </p>
        </div>
        <nav className="app-nav">
          <Link className="btn btn--secondary" to="/">
            Dashboard
          </Link>
          <Link className="btn" to="/goals/new">
            New goal
          </Link>
        </nav>
      </header>

      <main>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/goals/new" element={<GoalNewPage />} />
          <Route path="/goals/:goalId" element={<GoalDetailPage />} />
          <Route path="/goals/:goalId/edit" element={<GoalEditPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
