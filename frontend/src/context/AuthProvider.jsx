/**
 * AuthProvider.jsx — React Context provider for authentication state
 *
 * Wraps the entire app (in main.jsx) and makes auth state available to
 * every component via the useAuth() hook (hooks/useAuth.js).
 *
 * Provides:
 *   user           — { email } object when logged in, null when logged out
 *   isAuthenticated — boolean derived from user state
 *   login()        — calls auth.login(), updates state on success
 *   register()     — calls auth.register() (no state change — user must verify email)
 *   logout()       — calls auth.logout(), clears state
 *   getAccessToken() — returns current JWT from localStorage
 *
 * Session restoration:
 *   On mount, checks localStorage for an existing accessToken + userEmail.
 *   If found, restores the session without requiring re-login. This handles
 *   page refreshes and browser restarts (tokens persist in localStorage).
 *
 * Requirements: 7.3, 7.5, 8.4
 */

import { createContext, useState, useEffect, useCallback } from 'react'
import * as authService from '../services/auth.js'

// The context object — consumed by useAuth() hook
// Exported so AuthProvider.jsx and useAuth.js share the same context reference
export const AuthContext = createContext(null)

/**
 * AuthProvider component — wrap the app with this in main.jsx.
 *
 * @param {{ children: React.ReactNode }} props
 */
export function AuthProvider({ children }) {
  // user: null when logged out, { email } when logged in
  const [user, setUser] = useState(null)
  const [isAuthenticated, setIsAuthenticated] = useState(false)

  // ── Session restoration on mount ─────────────────────────────────────────
  // Runs once when the app loads. If tokens exist in localStorage from a
  // previous session, restore the auth state without calling Cognito.
  useEffect(() => {
    const token = localStorage.getItem('accessToken')
    const email = localStorage.getItem('userEmail')
    if (token && email) {
      setUser({ email })
      setIsAuthenticated(true)
    }
  }, []) // Empty deps array = runs once on mount only

  // ── Auth actions ──────────────────────────────────────────────────────────
  // useCallback prevents unnecessary re-renders of child components that
  // receive these functions as props

  /** Log in with email/password. Updates state on success. */
  const login = useCallback(async (email, password) => {
    const result = await authService.login(email, password)
    setUser({ email })
    setIsAuthenticated(true)
    return result
  }, [])

  /** Register a new account. Does not update auth state (email verification required). */
  const register = useCallback(async (email, password) => {
    return authService.register(email, password)
  }, [])

  /** Log out. Clears tokens from localStorage and resets state. */
  const logout = useCallback(() => {
    authService.logout()
    setUser(null)
    setIsAuthenticated(false)
  }, [])

  /** Get the current JWT access token (used by api.js interceptor). */
  const getAccessToken = useCallback(() => {
    return authService.getAccessToken()
  }, [])

  // Provide all auth values to the component tree
  return (
    <AuthContext.Provider value={{ user, isAuthenticated, login, register, logout, getAccessToken }}>
      {children}
    </AuthContext.Provider>
  )
}
