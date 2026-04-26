/**
 * Layout.jsx — Persistent shell for all protected pages
 *
 * Composes the full page layout:
 *   ┌─────────────────────────────────────┐
 *   │  Header (logo, page title, logout)  │
 *   ├─────────────────────────────────────┤
 *   │  FallbackBanner (shown when AI down)│
 *   ├──────────┬──────────────────────────┤
 *   │ Sidebar  │  <Outlet /> (page content)│
 *   │ (nav)    │                          │
 *   ├──────────┴──────────────────────────┤
 *   │  Footer                             │
 *   └─────────────────────────────────────┘
 *
 * FallbackBanner logic:
 *   On every route change, calls GET /dashboard/metrics to check if
 *   aiServiceStatus === "Fallback". If so, shows the FallbackBanner
 *   at the top of every page (Requirement 8.5).
 *
 * Page title:
 *   Derived from the current pathname using the PAGE_TITLES map.
 *   Passed as a prop to Header so it appears in the top bar.
 *
 * Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6
 */

import { Outlet, useLocation } from 'react-router-dom'
import { useState, useEffect } from 'react'
import Header from './Header.jsx'
import Sidebar from './Sidebar.jsx'
import Footer from './Footer.jsx'
import FallbackBanner from '../ui/FallbackBanner.jsx'
import { getDashboardMetrics } from '../../services/api.js'

// Maps URL path prefixes to human-readable page titles shown in the Header
const PAGE_TITLES = {
  '/dashboard':      'Dashboard',
  '/jobs':           'Jobs',
  '/recommendations':'Recommendations',
  '/override':       'Override',
  '/audit-logs':     'Audit Log',
}

export default function Layout() {
  const location = useLocation()
  const [fallbackActive, setFallbackActive] = useState(false)

  // Derive the current page title from the pathname
  // Uses startsWith to handle dynamic segments like /jobs/abc-123
  const title = Object.entries(PAGE_TITLES).find(
    ([path]) => location.pathname.startsWith(path)
  )?.[1] || 'RetailFixIt'

  // Check AI service status on every route change
  // Silently ignores errors — fallback banner is best-effort
  useEffect(() => {
    getDashboardMetrics()
      .then(data => setFallbackActive(data.aiServiceStatus === 'Fallback'))
      .catch(() => {})  // Don't break the layout if metrics call fails
  }, [location.pathname])

  return (
    // Full-height flex column: header + content area + footer
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      {/* Persistent header with logo, page title, and logout button */}
      <Header title={title} />

      {/* FallbackBanner appears below header when Gemini is unavailable */}
      {fallbackActive && <FallbackBanner />}

      {/* Content area: sidebar + main page content side by side */}
      <div style={{ display: 'flex', flex: 1 }}>
        {/* Persistent navigation sidebar */}
        <Sidebar />

        {/* Page content rendered by React Router — changes on navigation */}
        <main style={{ flex: 1, padding: '1.5rem', minWidth: 0 }}>
          <Outlet />
        </main>
      </div>

      {/* Persistent footer */}
      <Footer />
    </div>
  )
}
