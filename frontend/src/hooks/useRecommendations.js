/**
 * useRecommendations.js — Custom hook for fetching vendor recommendations
 *
 * Fetches the ranked vendor recommendations for a given jobId from the
 * GET /recommendations/{jobId} endpoint. Manages loading, error, and
 * data state internally.
 *
 * Returns:
 *   recommendations — array of Recommendation objects sorted by rank
 *   isFallback      — true if any recommendation used rule-based rationale
 *                     (Gemini was unavailable) — triggers FallbackBanner in UI
 *   isLoading       — true while the API call is in progress
 *   error           — Error object if the call failed, null otherwise
 *   refetch         — function to manually re-trigger the fetch
 *
 * Usage:
 *   const { recommendations, isFallback, isLoading, error, refetch } =
 *     useRecommendations(jobId)
 *
 * Requirements: 11.1, 11.7
 */

import { useState, useEffect, useCallback } from 'react'
import { getRecommendations } from '../services/api.js'

/**
 * @param {string} jobId — UUID of the job to fetch recommendations for
 */
export function useRecommendations(jobId) {
  const [recommendations, setRecommendations] = useState([])
  const [isFallback, setIsFallback] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)

  // useCallback ensures fetchRecommendations has a stable reference
  // so the useEffect below only re-runs when jobId changes
  const fetchRecommendations = useCallback(async () => {
    if (!jobId) return  // Don't fetch if no jobId provided

    setIsLoading(true)
    setError(null)

    try {
      // GET /recommendations/{jobId} returns:
      //   { jobId, isFallback, recommendations: [...] }
      const data = await getRecommendations(jobId)
      setRecommendations(data.recommendations || [])
      // isFallback is true when any recommendation has isAIGenerated=false
      // This triggers the FallbackBanner component in RecommendationsPage
      setIsFallback(data.isFallback || false)
    } catch (err) {
      setError(err)
    } finally {
      setIsLoading(false)
    }
  }, [jobId])

  // Fetch on mount and whenever jobId changes
  useEffect(() => {
    fetchRecommendations()
  }, [fetchRecommendations])

  return {
    recommendations,
    isFallback,
    isLoading,
    error,
    refetch: fetchRecommendations,  // Exposed for manual retry
  }
}
