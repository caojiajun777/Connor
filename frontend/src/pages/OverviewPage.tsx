import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'

const ACTIVE = new Set([
  'initializing',
  'collecting',
  'summarizing',
  'evaluating',
  'selecting',
  'finalizing',
])

export function OverviewPage() {
  const { data, error, isLoading } = useQuery({
    queryKey: ['overview'],
    queryFn: api.overview,
    refetchInterval: (query) => {
      const latest = query.state.data?.latest_run || query.state.data?.active_run
      return latest && ACTIVE.has(String(latest.status || '')) ? 4000 : false
    },
  })

  if (isLoading) return <p className="muted">Loading…</p>
  if (error) return <p className="error">{(error as Error).message}</p>
  const latest = data?.active_run || data?.latest_run
  const live = latest && ACTIVE.has(String(latest.status || ''))
  return (
    <div>
      <h1>Overview</h1>
      <p className="muted">
        Live pipeline runs are shown even with 0 candidates. Otherwise Latest prefers production runs
        with ≥10 candidates. Annotation todos only show tasks with at least one manually saved label.
      </p>
      <div className="grid">
        <div className="stat">
          <div className="k">Latest run</div>
          <div className="v">{latest?.status || '—'}</div>
        </div>
        <div className="stat">
          <div className="k">Accounts</div>
          <div className="v">{latest?.account_count ?? '—'}</div>
        </div>
        <div className="stat">
          <div className="k">Candidates</div>
          <div className="v">{latest?.candidate_count ?? '—'}</div>
        </div>
        <div className="stat">
          <div className="k">Machine selected</div>
          <div className="v">{latest?.machine_selected_count ?? '—'}</div>
        </div>
      </div>
      {latest?.run_id && (
        <p className="muted">
          {live ? 'Live' : 'Run'} <code>{latest.run_id.slice(0, 8)}</code>
          {live ? ' · auto-refreshing' : ''} ·{' '}
          <Link to={`/console/runs/${latest.run_id}`}>Open</Link>
        </p>
      )}

      <h2>Open annotation work</h2>
      <div className="card">
        {(data?.pending_annotations || []).length === 0 && (
          <p className="muted">
            No saved-in-progress annotation tasks. Start one from a run detail page when you want to
            label and score.
          </p>
        )}
        <table>
          <thead>
            <tr>
              <th>Source run</th>
              <th>Status</th>
              <th>Progress</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(data?.pending_annotations || []).map((a: any) => (
              <tr key={a.annotation_run_id}>
                <td>
                  <code>{a.source_run_id.slice(0, 8)}</code>
                </td>
                <td>{a.status}</td>
                <td>
                  {a.reviewed_items}/{a.total_items}
                </td>
                <td>
                  <Link to={`/console/editorial/${a.annotation_run_id}`}>Continue</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Recent runs</h2>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Started</th>
              <th>Run</th>
              <th>Status</th>
              <th>Accounts</th>
              <th>Candidates</th>
              <th>Selected</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {(data?.recent_runs || []).map((r: any) => (
              <tr key={r.run_id}>
                <td>{r.started_at?.slice(0, 19)}</td>
                <td>
                  <code>{r.run_id.slice(0, 8)}</code>
                </td>
                <td>{r.status}</td>
                <td>{r.account_count ?? '—'}</td>
                <td>{r.candidate_count}</td>
                <td>{r.machine_selected_count}</td>
                <td>
                  <Link to={`/console/runs/${r.run_id}`}>Open</Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
