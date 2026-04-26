import { useState, useEffect, useCallback } from 'react'
import { getAuditLogs, getAuditLog } from '../services/api.js'
import AuditFilterBar from '../components/ui/AuditFilterBar.jsx'
import LoadingSpinner from '../components/ui/LoadingSpinner.jsx'
import ErrorBanner from '../components/ui/ErrorBanner.jsx'
import ConfidenceBadge from '../components/ui/ConfidenceBadge.jsx'

export default function AuditLogPage() {
  const [logs, setLogs] = useState([])
  const [nextToken, setNextToken] = useState(null)
  const [filters, setFilters] = useState({})
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedLog, setSelectedLog] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const fetchLogs = useCallback(async (token = null) => {
    setIsLoading(true)
    setError(null)
    try {
      const params = { ...filters, limit: 20 }
      if (token) params.nextToken = token
      const data = await getAuditLogs(params)
      const items = data.items || []
      // Sort by timestamp descending
      const sorted = [...items].sort((a, b) => (b.timestamp || '').localeCompare(a.timestamp || ''))
      setLogs(token ? prev => [...prev, ...sorted] : sorted)
      setNextToken(data.nextToken || null)
    } catch (err) {
      setError(err.response?.data?.error?.message || err.message || 'Failed to load audit logs.')
    } finally {
      setIsLoading(false)
    }
  }, [filters])

  useEffect(() => { fetchLogs() }, [fetchLogs])

  async function handleRowClick(log) {
    if (selectedLog?.logId === log.logId) { setSelectedLog(null); return }
    setDetailLoading(true)
    try {
      const detail = await getAuditLog(log.logId)
      setSelectedLog(detail)
    } catch {
      setSelectedLog(log)
    } finally {
      setDetailLoading(false)
    }
  }

  return (
    <div>
      <h2 style={{ margin: '0 0 1rem', fontSize: '1.3rem', color: '#1a1a2e' }}>Audit Log</h2>
      <AuditFilterBar onFilterChange={setFilters} />

      {error && <ErrorBanner message={error} onRetry={() => fetchLogs()} />}

      {isLoading && !logs.length ? <LoadingSpinner /> : (
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-start' }}>
          {/* Log list */}
          <div style={{ flex: 1, overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
              <thead>
                <tr style={{ background: '#f8fafc', borderBottom: '2px solid #e2e8f0' }}>
                  {['Log ID', 'Job ID', 'Action', 'Vendor ID', 'Confidence', 'Model Ver.', 'PII Masked', 'Timestamp'].map(h => (
                    <th key={h} style={{ padding: '0.5rem 0.7rem', textAlign: 'left', fontWeight: 600, color: '#374151', whiteSpace: 'nowrap', fontSize: '0.8rem' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {logs.map(log => (
                  <tr key={log.logId} onClick={() => handleRowClick(log)}
                    style={{ borderBottom: '1px solid #f1f5f9', cursor: 'pointer', background: selectedLog?.logId === log.logId ? '#eff6ff' : '' }}
                    onMouseEnter={e => { if (selectedLog?.logId !== log.logId) e.currentTarget.style.background = '#f8fafc' }}
                    onMouseLeave={e => { if (selectedLog?.logId !== log.logId) e.currentTarget.style.background = '' }}>
                    <td style={{ padding: '0.5rem 0.7rem', fontFamily: 'monospace', fontSize: '0.75rem', color: '#6b7280' }}>{log.logId?.slice(0, 8)}…</td>
                    <td style={{ padding: '0.5rem 0.7rem', fontFamily: 'monospace', fontSize: '0.75rem', color: '#6b7280' }}>{log.jobId?.slice(0, 8)}…</td>
                    <td style={{ padding: '0.5rem 0.7rem' }}>
                      <span style={{ background: '#f1f5f9', padding: '0.1rem 0.4rem', borderRadius: '3px', fontSize: '0.75rem', fontFamily: 'monospace' }}>{log.action}</span>
                    </td>
                    <td style={{ padding: '0.5rem 0.7rem', fontFamily: 'monospace', fontSize: '0.75rem', color: '#6b7280' }}>{log.vendorId?.slice(0, 8) || '—'}</td>
                    <td style={{ padding: '0.5rem 0.7rem' }}>
                      {log.output?.confidence ? <ConfidenceBadge confidence={log.output.confidence} /> : <span style={{ color: '#9ca3af' }}>—</span>}
                    </td>
                    <td style={{ padding: '0.5rem 0.7rem', fontFamily: 'monospace', fontSize: '0.75rem' }}>{log.modelVersion || '—'}</td>
                    <td style={{ padding: '0.5rem 0.7rem', textAlign: 'center' }}>{log.piiMasked ? '✓' : '✗'}</td>
                    <td style={{ padding: '0.5rem 0.7rem', whiteSpace: 'nowrap', fontSize: '0.75rem', color: '#6b7280' }}>{log.timestamp?.slice(0, 19).replace('T', ' ')}</td>
                  </tr>
                ))}
                {!isLoading && !logs.length && (
                  <tr><td colSpan={8} style={{ padding: '2rem', textAlign: 'center', color: '#9ca3af' }}>No audit logs found.</td></tr>
                )}
              </tbody>
            </table>
            {nextToken && (
              <button onClick={() => fetchLogs(nextToken)} disabled={isLoading}
                style={{ marginTop: '0.75rem', padding: '0.4rem 1rem', background: '#1a1a2e', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer', fontSize: '0.85rem' }}>
                Load more
              </button>
            )}
          </div>

          {/* Detail panel */}
          {(selectedLog || detailLoading) && (
            <div style={{ width: '340px', flexShrink: 0, background: '#fff', border: '1px solid #e2e8f0', borderRadius: '8px', padding: '1rem', fontSize: '0.82rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                <h3 style={{ margin: 0, fontSize: '0.95rem', color: '#1a1a2e' }}>Log Detail</h3>
                <button onClick={() => setSelectedLog(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9ca3af', fontSize: '1.1rem' }}>✕</button>
              </div>
              {detailLoading ? <LoadingSpinner /> : selectedLog && (
                <>
                  <div style={{ marginBottom: '0.75rem' }}>
                    <strong>Log ID:</strong> <span style={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>{selectedLog.logId}</span>
                  </div>
                  <div style={{ marginBottom: '0.5rem' }}><strong>Action:</strong> {selectedLog.action}</div>
                  <div style={{ marginBottom: '0.5rem' }}><strong>Job ID:</strong> <span style={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>{selectedLog.jobId}</span></div>
                  <div style={{ marginBottom: '0.5rem' }}><strong>Vendor ID:</strong> <span style={{ fontFamily: 'monospace', fontSize: '0.75rem' }}>{selectedLog.vendorId || '—'}</span></div>
                  <div style={{ marginBottom: '0.5rem' }}><strong>Model Version:</strong> {selectedLog.modelVersion}</div>
                  <div style={{ marginBottom: '0.5rem' }}><strong>PII Masked:</strong> {selectedLog.piiMasked ? 'Yes' : 'No'}</div>
                  <div style={{ marginBottom: '0.75rem' }}><strong>Timestamp:</strong> {selectedLog.timestamp}</div>

                  <div style={{ marginBottom: '0.5rem' }}><strong>Input:</strong></div>
                  <pre style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '4px', padding: '0.5rem', fontSize: '0.72rem', overflowX: 'auto', maxHeight: '150px', margin: '0 0 0.75rem' }}>
                    {JSON.stringify(selectedLog.input, null, 2)}
                  </pre>

                  <div style={{ marginBottom: '0.5rem' }}><strong>Output:</strong></div>
                  <pre style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '4px', padding: '0.5rem', fontSize: '0.72rem', overflowX: 'auto', maxHeight: '150px', margin: 0 }}>
                    {JSON.stringify(selectedLog.output, null, 2)}
                  </pre>
                </>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
