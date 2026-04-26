/**
 * auth.js — Cognito JWT authentication service
 *
 * Wraps the amazon-cognito-identity-js library to provide a clean API
 * for login, registration, logout, and token refresh.
 *
 * Token storage:
 *   Tokens are stored in localStorage under these keys:
 *     - accessToken  : JWT used in Authorization header for API calls
 *     - refreshToken : Long-lived token used to get new access tokens
 *     - userEmail    : Stored to reconstruct CognitoUser for refresh/logout
 *
 * Why localStorage?
 *   The Admin UI is a single-page app used by internal staff on managed
 *   devices. localStorage provides session persistence across page refreshes.
 *   For higher-security requirements, consider httpOnly cookies instead.
 *
 * Requirements: 7.3, 7.5, 7.8
 */

import {
  CognitoUserPool,
  CognitoUser,
  CognitoRefreshToken,
  AuthenticationDetails,
} from 'amazon-cognito-identity-js'

// ── Cognito User Pool configuration ──────────────────────────────────────────
// Values come from .env file (set after running deploy.sh):
//   VITE_COGNITO_USER_POOL_ID=us-east-1_XXXXXXXXX
//   VITE_COGNITO_CLIENT_ID=XXXXXXXXXXXXXXXXXXXXXXXXXX
const poolData = {
  UserPoolId: import.meta.env.VITE_COGNITO_USER_POOL_ID || '',
  ClientId: import.meta.env.VITE_COGNITO_CLIENT_ID || '',
}

// Single shared pool instance — reused across all auth operations
const userPool = new CognitoUserPool(poolData)

/**
 * Log in with email and password.
 *
 * Uses Cognito USER_PASSWORD_AUTH flow. On success, stores tokens in
 * localStorage and returns them for the AuthProvider to update state.
 *
 * @param {string} email
 * @param {string} password
 * @returns {Promise<{accessToken: string, refreshToken: string}>}
 */
export function login(email, password) {
  return new Promise((resolve, reject) => {
    const authDetails = new AuthenticationDetails({
      Username: email,
      Password: password,
    })

    const cognitoUser = new CognitoUser({
      Username: email,
      Pool: userPool,
    })

    cognitoUser.authenticateUser(authDetails, {
      onSuccess(result) {
        // Use the ID token — API Gateway Cognito Authorizer validates ID tokens
        // (not access tokens) by default
        const idToken = result.getIdToken().getJwtToken()
        const accessToken = result.getAccessToken().getJwtToken()
        const refreshToken = result.getRefreshToken().getToken()

        // Store ID token as the one used for API calls
        localStorage.setItem('accessToken', idToken)
        localStorage.setItem('cognitoAccessToken', accessToken)
        localStorage.setItem('refreshToken', refreshToken)
        localStorage.setItem('userEmail', email)

        resolve({ accessToken: idToken, refreshToken })
      },
      onFailure(err) {
        // Common errors: NotAuthorizedException (wrong password),
        // UserNotFoundException, UserNotConfirmedException
        reject(err)
      },
    })
  })
}

/**
 * Register a new user account.
 *
 * Cognito sends a verification email after sign-up. The user must click
 * the link before they can log in (handled by the Cognito User Pool config).
 *
 * @param {string} email
 * @param {string} password — must meet Cognito password policy (8+ chars,
 *                            upper, lower, digit, special character)
 * @returns {Promise<void>}
 */
export function register(email, password) {
  return new Promise((resolve, reject) => {
    // signUp(username, password, userAttributes, validationData, callback)
    // username = email (configured as the username attribute in Cognito)
    userPool.signUp(email, password, [], null, (err, result) => {
      if (err) { reject(err); return }
      resolve(result)
    })
  })
}

/**
 * Log out the current user.
 *
 * Calls Cognito signOut() to invalidate the session server-side, then
 * clears all tokens from localStorage.
 */
export function logout() {
  const email = localStorage.getItem('userEmail')
  if (email) {
    // Reconstruct the CognitoUser to call signOut()
    const cognitoUser = new CognitoUser({ Username: email, Pool: userPool })
    cognitoUser.signOut()
  }
  // Clear all stored tokens regardless of whether signOut() succeeded
  localStorage.removeItem('accessToken')
  localStorage.removeItem('refreshToken')
  localStorage.removeItem('userEmail')
}

/**
 * Refresh the access token using the stored refresh token.
 *
 * Called automatically by the Axios response interceptor in api.js when
 * a request returns HTTP 401 (access token expired).
 *
 * @returns {Promise<string>} The new access token
 */
export function refreshAccessToken() {
  return new Promise((resolve, reject) => {
    const email = localStorage.getItem('userEmail')
    const refreshTokenStr = localStorage.getItem('refreshToken')

    if (!email || !refreshTokenStr) {
      // No session to refresh — user must log in again
      reject(new Error('No session'))
      return
    }

    const cognitoUser = new CognitoUser({ Username: email, Pool: userPool })
    const refreshToken = new CognitoRefreshToken({ RefreshToken: refreshTokenStr })

    cognitoUser.refreshSession(refreshToken, (err, session) => {
      if (err) { reject(err); return }

      // Store the new ID token (used for API Gateway authorization)
      const newIdToken = session.getIdToken().getJwtToken()
      localStorage.setItem('accessToken', newIdToken)
      resolve(newIdToken)
    })
  })
}

/**
 * Get the current access token from localStorage.
 *
 * Used by the Axios request interceptor to attach the Authorization header.
 *
 * @returns {string|null} The JWT access token, or null if not logged in
 */
export function getAccessToken() {
  return localStorage.getItem('accessToken')
}

/**
 * Confirm registration with the 6-digit verification code sent to email.
 * Called after register() — user enters the code from their email.
 *
 * @param {string} email
 * @param {string} code — 6-digit code from the verification email
 * @returns {Promise<void>}
 */
export function confirmRegistration(email, code) {
  return new Promise((resolve, reject) => {
    const cognitoUser = new CognitoUser({ Username: email, Pool: userPool })
    cognitoUser.confirmRegistration(code, true, (err, result) => {
      if (err) { reject(err); return }
      resolve(result)
    })
  })
}

/**
 * Resend the verification code to the user's email.
 *
 * @param {string} email
 * @returns {Promise<void>}
 */
export function resendConfirmationCode(email) {
  return new Promise((resolve, reject) => {
    const cognitoUser = new CognitoUser({ Username: email, Pool: userPool })
    cognitoUser.resendConfirmationCode((err, result) => {
      if (err) { reject(err); return }
      resolve(result)
    })
  })
}
