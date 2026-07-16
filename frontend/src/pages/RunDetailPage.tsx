import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api/client'

const TABS = ['Overview', 'Candidates', 'Selection', 'Versions', 'Errors'] as const

export function RunDetailPage() {
  const { runId = '' } = useParams()
  const [tab, setTab] = useState<(typeof TABS)[number]>('Overview')
  const nav = useNavigate()
  const qc = useQueryClient()
  const run = useQuery({ queryKey: ['run', runId], queryFn: () => api.run(runId), enabled: !!runId })
  const candidates = useQuery({ queryKey: ['candidates', runId], queryFn: () => api.candidates(runId), enabled: !!runId && tab === 'Candidates' })
  const selection = useQuery({ queryKey: ['selection', runId], queryFn: () => api.selection(runId), enabled: !!runId && tab === 'Selection' })
  const versions = useQuery({ queryKey: ['versions', runId], queryFn: () => api.versions(runId), enabled: !!runId && tab === 'Versions' })
  const errors = useQuery({ queryKey: ['errors', runId], queryFn: () => api.errors(runId), enabled: !!runId && tab === 'Errors' })
  const createAnn = useMutation({
    mutationFn: () => api.createAnnotation(runId),
    onSuccess: (row) => {
      qc.invalidateQueries({ queryKey: ['annotations'] })
      nav(`/console/editorial/${row.annotation_run_id}`)
    },
  })

  if (run.isLoading) return <p className="muted">Loading…</p>
  if (run.error) return <p className="error">{(run.error as Error).message}</p>
  const d = run.data

  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h1>Run {runId.slice(0, 8)}</h1>
        <button className="btn" disabled={createAnn.isPending} onClick={() => createAnn.mutate()}>
          Start annotation
        </button>
      </div>
      {createAnn.error && <p className="error">{(createAnn.error as Error).message}</p>}
      <div className="tabs">
        {TABS.map((t) => (
          <button key={t} className={tab === t ? 'tab active' : 'tab'} onClick={() => setTab(t)}>{t}</button>
        ))}
      </div>

      {tab === 'Overview' && (
        <div className="grid">
          <div className="stat"><div className="k">Status</div><div className="v">{d.status}</div></div>
          <div className="stat"><div className="k">Candidates</div><div className="v">{d.candidate_count}</div></div>
          <div className="stat"><div className="k">Translations</div><div className="v">{d.summary_success_count}</div></div>
          <div className="stat"><div className="k">Evaluations</div><div className="v">{d.evaluation_success_count}</div></div>
          <div className="stat"><div className="k">Machine selected</div><div className="v">{d.machine_selected_count}</div></div>
          <div className="stat"><div className="k">Coverage</div><div className="v">{d.summary_coverage || '—'}</div></div>
        </div>
      )}

      {tab === 'Candidates' && (
        <div className="card">
          {candidates.isLoading && <p className="muted">Loading…</p>}
          <table>
            <thead><tr><th>Handle</th><th>中文译文</th><th>Frontier</th><th>Selected</th><th>Link</th></tr></thead>
            <tbody>
              {(candidates.data?.items || []).map((c: any) => (
                <tr key={c.post_id}>
                  <td>@{c.post?.handle}</td>
                  <td>{(c.summary?.summary || '').slice(0, 120)}</td>
                  <td>{c.evaluation?.frontier_score ?? '—'}</td>
                  <td>{c.selection?.selection_status || '—'}</td>
                  <td>{c.post?.url ? <a href={c.post.url} target="_blank" rel="noreferrer">X</a> : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'Selection' && (
        <div className="card">
          <p className="muted">Read-only machine selection. publication_status is not editable here.</p>
          <table>
            <thead><tr><th>Rank</th><th>Post</th><th>Status</th><th>Publication</th><th>Reason</th></tr></thead>
            <tbody>
              {(selection.data?.items || []).map((i: any) => (
                <tr key={i.post_id}>
                  <td>{i.final_rank ?? '—'}</td>
                  <td><code>{i.post_id}</code></td>
                  <td>{i.selection_status}</td>
                  <td>{i.publication_status}</td>
                  <td>{i.selection_reason || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'Versions' && versions.data && (
        <div className="card"><pre>{JSON.stringify(versions.data, null, 2)}</pre></div>
      )}

      {tab === 'Errors' && errors.data && (
        <div className="card"><pre>{JSON.stringify(errors.data, null, 2)}</pre></div>
      )}

      <p><Link to="/console/runs">← Back to runs</Link></p>
    </div>
  )
}
