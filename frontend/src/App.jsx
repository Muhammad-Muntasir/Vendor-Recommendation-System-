/**
 * App.jsx — Root route configuration for the AI-VRS Admin UI
 *
 * Defines the complete route tree using React Router v6 <Routes>.
 *
 * Route structure:
 *   /auth                    → AuthPage (public — login/register tabs)
 *   /                        → redirect to /dashboard
 *   /dashboard               → DashboardPage (metrics overview)
 *   /jobs                    → JobsPage (paginated job list with filters)
 *   /jobs/:jobId             → JobDetailPage (single job detail + link to recommendations)
 *   /recommendations/:jobId  → RecommendationsPage (ranked vendor list with rationale)
 *   /override/:jobId         → OverridePage (vendor selection + reason form)
 *   /audit-logs              → AuditLogPage (compliance audit trail)
 *   *                        → redirect to /dashboard (catch-all)
 *
 * Protected routes are wrapped in:
 *   1. <ProtectedRoute> — redirects to /auth if no access token in localStorage
 *   2. <Layout>         — renders Header, Sidebar, Footer, and FallbackBanner
 */

import { Routes, Route, Navigate } from 'react-router-dom'
import ProtectedRoute from './components/layout/ProtectedRoute.jsx'
import Layout from './components/layout/Layout.jsx'
import AuthPage from './pages/AuthPage.jsx'
import DashboardPage from './pages/DashboardPage.jsx'
import JobsPage from './pages/JobsPage.jsx'
import JobDetailPage from './pages/JobDetailPage.jsx'
import RecommendationsPage from './pages/RecommendationsPage.jsx'
import OverridePage from './pages/OverridePage.jsx'
import AuditLogPage from './pages/AuditLogPage.jsx'

export default function App() {
  return (
    <Routes>
      {/* ── Public route ─────────────────────────────────────────────────── */}
      {/* /auth is accessible without authentication — shows login/register */}
      <Route path="/auth" element={<AuthPage />} />

      {/* ── Protected routes ─────────────────────────────────────────────── */}
      {/* ProtectedRoute checks localStorage for accessToken.
          If absent, redirects to /auth before rendering any child route. */}
      <Route element={<ProtectedRoute />}>
        {/* Layout wraps all protected pages with Header, Sidebar, Footer */}
        <Route element={<Layout />}>
          {/* Root path redirects to dashboard */}
          <Route path="/" element={<Navigate to="/dashboard" replace />} />

          {/* Dashboard — summary metrics and AI service status */}
          <Route path="/dashboard" element={<DashboardPage />} />

          {/* Jobs list — paginated with status/date filters */}
          <Route path="/jobs" element={<JobsPage />} />

          {/* Job detail — single job with link to recommendations */}
          <Route path="/jobs/:jobId" element={<JobDetailPage />} />

          {/* Recommendations — ranked vendor list for a specific job */}
          <Route path="/recommendations/:jobId" element={<RecommendationsPage />} />

          {/* Override — vendor selection form with reason textarea */}
          <Route path="/override/:jobId" element={<OverridePage />} />

          {/* Audit Log — compliance trail with filtering and detail panel */}
          <Route path="/audit-logs" element={<AuditLogPage />} />
        </Route>
      </Route>

      {/* ── Catch-all ────────────────────────────────────────────────────── */}
      {/* Any unknown path redirects to dashboard */}
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}
