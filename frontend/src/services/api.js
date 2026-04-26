/**
 * api.js — Axios HTTP client for all AI-VRS API calls
 *
 * Creates a configured Axios instance with:
 *   - baseURL from VITE_API_URL environment variable (set in .env)
 *   - Request interceptor: attaches JWT access token to every request
 *   - Response interceptor: handles 401 by refreshing the token and retrying
 *
 * All API functions are typed and return the response data directly
 * (not the full Axios response object).
 *
 * Token refresh flow:
 *   1. Request fails with HTTP 401 (token expired)
 *   2. Interceptor calls auth.refreshAccessToken() to get a new token
 *   3. Original request is retried once with the new token
 *   4. If refresh also fails → redirect to /auth (force re-login)
 *
 * Requirements: 7.4, 7.5
 */

import axios from 'axios'
import { getAccessToken, refreshAccessToken } from './auth.js'

// ── Create Axios instance ─────────────────────────────────────────────────────
// baseURL is the API Gateway endpoint URL set in .env as VITE_API_URL
const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '',
})

// ── Request interceptor — attach JWT to every outgoing request ────────────────
apiClient.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) {
    // API Gateway Cognito Authorizer validates this header on every request
    config.headers['Authorization'] = `Bearer ${token}`
  }
  return config
})

// ── Response interceptor — handle token expiry ───────────────────────────────
// isRefreshing prevents multiple simultaneous refresh attempts
let isRefreshing = false

apiClient.interceptors.response.use(
  // Pass through successful responses unchanged
  (response) => response,

  async (error) => {
    const originalRequest = error.config

    // Only attempt refresh on 401 and only once per request (_retry flag)
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        // Another refresh is already in progress — redirect to avoid loop
        window.location.href = '/auth'
        return Promise.reject(error)
      }

      originalRequest._retry = true  // Mark to prevent infinite retry loop
      isRefreshing = true

      try {
        // Get a new access token using the stored refresh token
        await refreshAccessToken()
        isRefreshing = false
        // Retry the original request — the request interceptor will attach
        // the new token automatically
        return apiClient(originalRequest)
      } catch (refreshError) {
        // Refresh token also expired — force the user to log in again
        isRefreshing = false
        window.location.href = '/auth'
        return Promise.reject(refreshError)
      }
    }

    return Promise.reject(error)
  }
)

// ── API functions ─────────────────────────────────────────────────────────────
// Each function maps to one backend endpoint. All return response.data directly.

/** POST /jobs — Create a new service job */
export const createJob = (data) => apiClient.post('/jobs', data).then(r => r.data)

/** GET /jobs — List jobs with optional status/date filters and pagination */
export const getJobs = (params) => apiClient.get('/jobs', { params }).then(r => r.data)

/** GET /jobs/{jobId} — Get a single job by ID */
export const getJob = (jobId) => apiClient.get(`/jobs/${jobId}`).then(r => r.data)

/** GET /recommendations/{jobId} — Get ranked vendor recommendations for a job */
export const getRecommendations = (jobId) =>
  apiClient.get(`/recommendations/${jobId}`).then(r => r.data)

/** POST /recommendations/{jobId}/accept — Accept the AI recommendation */
export const acceptRecommendation = (jobId) =>
  apiClient.post(`/recommendations/${jobId}/accept`).then(r => r.data)

/** POST /override — Submit a vendor override with reason */
export const submitOverride = (data) => apiClient.post('/override', data).then(r => r.data)

/** GET /audit-logs — List audit log records with optional filters */
export const getAuditLogs = (params) =>
  apiClient.get('/audit-logs', { params }).then(r => r.data)

/** GET /audit-logs/{logId} — Get a single audit log record by ID */
export const getAuditLog = (logId) =>
  apiClient.get(`/audit-logs/${logId}`).then(r => r.data)

/** GET /dashboard/metrics — Get today's summary metrics for the dashboard */
export const getDashboardMetrics = () =>
  apiClient.get('/dashboard/metrics').then(r => r.data)

export default apiClient
