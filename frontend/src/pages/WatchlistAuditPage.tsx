import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'

export function WatchlistAuditPage() {
  const { runId = '' } = useParams()
  const { data, error, isLoading } = useQuery({
    queryKey: ['watchlist-audit', runId],
    queryFn: () => api.watchlistAudit(runId),
    enabled: Boolean(runId),
    refetchInterval: (q) => {
      const status = q.state.data?.status
      return status === 'queued' || status === 'running' ? 3000 : false
    },
  })

  if (isLoading) return <p className="muted">Loading…</p>
  if (error) return <p className="error">{(error as Error).message}</p>
  if (!data) return <p className="muted">Not found</p>

  const results = data.audit?.results || []
  const changes = results.filter((r: any) => r.status === 'change_recommended')
  const statusDetail = data.status_detail || {}

  return (
    <div>
      <p className="muted"><Link to="/console/watchlist">← Watchlist</Link></p>
      <h1>Audit {runId}</h1>
      <div className="grid">
        <div className="stat"><div className="k">Status</div><div className="v">{data.status}</div></div>
        <div className="stat"><div className="k">Mode</div><div className="v">{statusDetail.dry_run === false ? 'live' : 'dry-run'}</div></div>
        <div className="stat"><div className="k">Accounts</div><div className="v">{results.length || statusDetail.selected || '—'}</div></div>
        <div className="stat"><div className="k">Changes</div><div className="v">{changes.length}</div></div>
      </div>

      {statusDetail.error && <p className="error">{statusDetail.error}</p>}

      {(data.suggested_patch_yaml || data.suggested_patch) && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Suggested patch (copy into YAML manually)</h2>
          <pre>{data.suggested_patch_yaml
            || (typeof data.suggested_patch === 'string'
              ? data.suggested_patch
              : JSON.stringify(data.suggested_patch, null, 2))}</pre>
        </div>
      )}

      <div className="card">
        <h2 style={{ marginTop: 0 }}>Results</h2>
        {results.length === 0 && <p className="muted">No results yet (still running or dry-run scaffold).</p>}
        <table>
          <thead>
            <tr>
              <th>Handle</th>
              <th>Status</th>
              <th>Change?</th>
              <th>Summary</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r: any) => (
              <tr key={r.handle}>
                <td><code>@{r.handle}</code></td>
                <td>{r.status || '—'}</td>
                <td>{r.status === 'change_recommended' ? <span className="badge uncertain">yes</span> : 'no'}</td>
                <td>{r.reason || r.error || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.audit_markdown && (
        <div className="card">
          <h2 style={{ marginTop: 0 }}>Report</h2>
          <pre>{data.audit_markdown}</pre>
        </div>
      )}
    </div>
  )
}
