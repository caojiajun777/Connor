import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api/client'

export function EditorialInboxPage() {
  const nav = useNavigate()
  const qc = useQueryClient()
  const annotations = useQuery({ queryKey: ['annotations'], queryFn: api.annotations })
  const runs = useQuery({ queryKey: ['runs'], queryFn: api.runs })
  const create = useMutation({
    mutationFn: (source_run_id: string) => api.createAnnotation(source_run_id),
    onSuccess: (row) => {
      qc.invalidateQueries({ queryKey: ['annotations'] })
      nav(`/console/editorial/${row.annotation_run_id}`)
    },
  })
  const cancel = useMutation({
    mutationFn: (id: string) => api.cancel(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['annotations'] })
      qc.invalidateQueries({ queryKey: ['overview'] })
    },
  })

  return (
    <div>
      <h1>Annotation Inbox</h1>
      <div className="card">
        <h2>Open / completed tasks</h2>
        {annotations.isLoading && <p className="muted">Loading…</p>}
        <table>
          <thead>
            <tr><th>Created</th><th>Source run</th><th>Status</th><th>Progress</th><th></th></tr>
          </thead>
          <tbody>
            {(annotations.data || []).map((a) => (
              <tr key={a.annotation_run_id}>
                <td>{a.created_at?.slice(0, 19)}</td>
                <td><code>{a.source_run_id.slice(0, 8)}</code></td>
                <td>{a.status}</td>
                <td>{a.reviewed_items}/{a.total_items}</td>
                <td className="row">
                  <Link to={`/console/editorial/${a.annotation_run_id}`}>Workspace</Link>
                  <Link to={`/console/editorial/${a.annotation_run_id}/diff`}>Diff</Link>
                  {a.reviewed_items === 0 && a.status !== 'completed' && (
                    <button
                      className="btn secondary"
                      disabled={cancel.isPending}
                      onClick={() => {
                        if (confirm('Cancel unsaved annotation task?')) cancel.mutate(a.annotation_run_id)
                      }}
                    >
                      Cancel
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {cancel.error && <p className="error">{(cancel.error as Error).message}</p>}
      </div>

      <div className="card">
        <h2>Create from a production run</h2>
        <table>
          <thead><tr><th>Started</th><th>Status</th><th>Candidates</th><th></th></tr></thead>
          <tbody>
            {(runs.data || []).filter((r) => r.status === 'completed' && r.candidate_count > 0).slice(0, 15).map((r) => (
              <tr key={r.run_id}>
                <td>{r.started_at?.slice(0, 19)}</td>
                <td>{r.status}</td>
                <td>{r.candidate_count}</td>
                <td>
                  <button className="btn secondary" disabled={create.isPending} onClick={() => create.mutate(r.run_id)}>
                    Annotate
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {create.error && <p className="error">{(create.error as Error).message}</p>}
      </div>
    </div>
  )
}
