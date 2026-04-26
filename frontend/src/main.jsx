/**
 * main.jsx — React 18 application entry point
 *
 * This file bootstraps the entire frontend application:
 * 1. Creates the React root using the new React 18 createRoot API
 * 2. Wraps the app in BrowserRouter for client-side routing (React Router v6)
 * 3. Wraps the app in AuthProvider so every component can access auth state
 * 4. Renders the App component which defines all page routes
 *
 * The #root div is defined in index.html and is the single mount point
 * for the entire React application.
 */

import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import { AuthProvider } from './context/AuthProvider.jsx'
import './index.css'

// Mount the React app into the #root div defined in index.html
// createRoot is the React 18 API — replaces the legacy ReactDOM.render()
ReactDOM.createRoot(document.getElementById('root')).render(
  // StrictMode enables additional development-time warnings and double-renders
  // to help detect side effects. Has no effect in production builds.
  <React.StrictMode>
    {/* BrowserRouter enables HTML5 history-based routing (no hash in URLs) */}
    <BrowserRouter>
      {/* AuthProvider makes user/isAuthenticated/login/logout available
          to every component in the tree via the useAuth() hook */}
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
