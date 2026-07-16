import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../api/client'

export function RunsPage() {
  const { data, error, isLoading } = useQuery({ queryKey: ['runs'], queryFn: api.runs })
  if (isLoading) return <p className="muted">Loading…</p>
  if (error) return <p className="error">{(error as Error).message}</p>
  return (
    <div>
      <h1>Run History</h1>
      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Started</th><th>Status</th><th>Accounts</th><th>Candidates</th>
              <th>Coverage</th><th>Selected</th><th>Annotation</th><th></th>
            </tr>
          </thead>
          <tbody>
            {(data || []).map((r) => (
              <tr key={r.run_id}>
                <td>{r.started_at?.slice(0, 19)}</td>
                <td>{r.status}</td>
                <td>{r.account_count}</td>
                <td>{r.candidate_count}</td>
                <td>{r.summary_coverage || '—'} / {r.evaluation_coverage || '—'}</td>
                <td>{r.machine_selected_count}</td>
                <td>
                  {r.annotation
                    ? `${r.annotation.status} (${r.annotation.reviewed_items}/${r.annotation.total_items})`
                    : '—'}
                </td>
                <td><Link to={`/console/runs/${r.run_id}`}>Detail</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
