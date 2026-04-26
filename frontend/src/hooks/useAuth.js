/**
 * useAuth.js — Custom hook for accessing authentication state and actions
 *
 * Wraps the AuthContext from AuthProvider.jsx. Any component that needs
 * to know if the user is logged in, get the current user, or call
 * login/logout should use this hook instead of importing AuthContext directly.
 *
 * Usage:
 *   const { user, isAuthenticated, login, logout, getAccessToken } = useAuth()
 *
 * Throws an error if used outside of an AuthProvider — this is intentional
 * to catch misconfigured component trees early during development.
 *
 * Requirements: 7.3
 */

import { useContext } from 'react'
import { AuthContext } from '../context/AuthProvider.jsx'

/**
 * Hook to access authentication state and actions.
 *
 * @returns {{
 *   user: {email: string}|null,
 *   isAuthenticated: boolean,
 *   login: (email: string, password: string) => Promise<{accessToken, refreshToken}>,
 *   register: (email: string, password: string) => Promise<void>,
 *   logout: () => void,
 *   getAccessToken: () => string|null
 * }}
 */
export function useAuth() {
  const context = useContext(AuthContext)

  // Guard: this hook must be used inside an <AuthProvider> wrapper.
  // If context is null, the component tree is missing the provider.
  if (!context) {
    throw new Error(
      'useAuth() must be used within an <AuthProvider>. ' +
      'Make sure AuthProvider wraps your component tree in main.jsx.'
    )
  }

  return context
}
