/**
 * ProtectedRoute.jsx — Route guard for authenticated pages
 *
 * Wraps protected routes in App.jsx. If the user is not authenticated
 * (no access token in localStorage and isAuthenticated=false in context),
 * redirects to /auth before rendering any child routes.
 *
 * Uses React Router v6 <Outlet> pattern — child routes render inside
 * the Outlet when authentication passes.
 *
 * Two-layer check:
 *   1. isAuthenticated from AuthContext (in-memory state, fast)
 *   2. localStorage.getItem('accessToken') (handles page refresh case
 *      where context hasn't been restored yet from useEffect)
 *
 * Requirements: 8.4
 */

import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth.js'

export default function ProtectedRoute() {
  const { isAuthenticated } = useAuth()

  // Also check localStorage directly to handle the brief window between
  // page load and the AuthProvider useEffect restoring the session
  const token = localStorage.getItem('accessToken')

  // If either check passes, render the child routes via <Outlet>
  // If both fail, redirect to the login page
  return (isAuthenticated || token)
    ? <Outlet />
    : <Navigate to="/auth" replace />
}
