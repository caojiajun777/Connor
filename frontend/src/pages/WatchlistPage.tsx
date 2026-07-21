import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'

type Account = {
  handle: string
  display_name?: string | null
  organization?: string | null
  source_type: string
  priority?: number
  role?: string | null
  notes?: string | null
  verified_at?: string | null
  enabled: boolean
  stale: boolean
  stale_days_policy?: number
}

export function WatchlistPage() {
  const qc = useQueryClient()
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [staleOnly, setStaleOnly] = useState(false)
  const [enabledOnly, setEnabledOnly] = useState(true)
  const [q, setQ] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [handlesText, setHandlesText] = useState('')
  const [live, setLive] = useState(false)

  const wl = useQuery({ queryKey: ['watchlist'], queryFn: api.watchlist })
  const audits = useQuery({
    queryKey: ['watchlist-audits'],
    queryFn: api.watchlistAudits,
    refetchInterval: 5000,
  })

  const start = useMutation({
    mutationFn: api.startWatchlistAudit,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['watchlist-audits'] })
      setSelected(new Set())
    },
  })

  const accounts: Account[] = wl.data?.accounts || []
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return accounts.filter((a) => {
      if (enabledOnly && !a.enabled) return false
      if (staleOnly && !a.stale) return false
      if (typeFilter !== 'all' && a.source_type !== typeFilter) return false
      if (!needle) return true
      const hay = `${a.handle} ${a.display_name || ''} ${a.organization || ''} ${a.role || ''}`.toLowerCase()
      return hay.includes(needle)
    })
  }, [accounts, enabledOnly, staleOnly, typeFilter, q])

  const toggle = (handle: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(handle)) next.delete(handle)
      else next.add(handle)
      return next
    })
  }

  const parsedHandles = handlesText
    .split(/[\s,]+/)
    .map((h) => h.replace(/^@/, '').trim())
    .filter(Boolean)

  const startHandles = () => {
    const handles = selected.size > 0 ? Array.from(selected) : parsedHandles
    if (handles.length === 0) return
    start.mutate({ handles, live })
  }

  if (wl.isLoading) return <p className="muted">Loading…</p>
  if (wl.error) return <p className="error">{(wl.error as Error).message}</p>

  const byType = wl.data?.by_source_type || {}

  return (
    <div>
      <h1>Watchlist</h1>
      <p className="muted">
        Browse accounts and run account audits. Audits never write YAML — copy suggested patches by hand.
      </p>

      <div className="grid">
        <div className="stat"><div className="k">Enabled</div><div className="v">{wl.data?.account_count ?? '—'}</div></div>
        <div className="stat"><div className="k">Stale</div><div className="v">{wl.data?.stale_count ?? '—'}</div></div>
        <div className="stat"><div className="k">Official</div><div className="v">{byType.official ?? 0}</div></div>
        <div className="stat"><div className="k">Employee</div><div className="v">{byType.employee ?? 0}</div></div>
        <div className="stat"><div className="k">Analyst</div><div className="v">{byType.analyst ?? 0}</div></div>
        <div className="stat"><div className="k">Leak</div><div className="v">{byType.leak ?? 0}</div></div>
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>Start audit</h2>
        <p className="muted">
          Default is dry-run (no LLM / web search). Live requires selected handles — full live `--all` stays CLI-only.
        </p>
        <div className="row" style={{ marginBottom: '0.75rem' }}>
          <button className="btn secondary" type="button" disabled={start.isPending} onClick={() => start.mutate({ stale: true, live: false })}>
            Dry-run stale
          </button>
          <button className="btn secondary" type="button" disabled={start.isPending} onClick={() => start.mutate({ all: true, live: false })}>
            Dry-run all
          </button>
          <button className="btn" type="button" disabled={start.isPending || (selected.size === 0 && parsedHandles.length === 0)} onClick={startHandles}>
            Audit selected / pasted {live ? '(live)' : '(dry-run)'}
          </button>
          <label className="row" style={{ gap: '0.35rem' }}>
            <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
            Live (LLM + search)
          </label>
        </div>
        <label>Paste handles (optional if rows are checked)</label>
        <input
          value={handlesText}
          onChange={(e) => setHandlesText(e.target.value)}
          placeholder="OpenAI sama karpathy"
        />
        {start.error && <p className="error">{(start.error as Error).message}</p>}
        {start.data && (
          <p className="muted">
            Queued <code>{start.data.run_id}</code> ·{' '}
            <Link to={`/console/watchlist/audits/${start.data.run_id}`}>Open</Link>
          </p>
        )}
      </div>

      <div className="card">
        <h2 style={{ marginTop: 0 }}>Recent audits</h2>
        {(audits.data || []).length === 0 && <p className="muted">No audit runs yet.</p>}
        <table>
          <thead>
            <tr>
              <th>Run</th><th>Status</th><th>Mode</th><th>Selected</th><th>Finished</th><th></th>
            </tr>
          </thead>
          <tbody>
            {(audits.data || []).map((r: any) => (
              <tr key={r.run_id}>
                <td><code>{r.run_id}</code></td>
                <td>{r.status}</td>
                <td>{r.dry_run === false ? 'live' : 'dry-run'}</td>
                <td>{r.selected ?? '—'}</td>
                <td>{r.finished_at?.slice(0, 19) || '—'}</td>
                <td><Link to={`/console/watchlist/audits/${r.run_id}`}>Detail</Link></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <div className="row" style={{ marginBottom: '0.75rem', justifyContent: 'space-between' }}>
          <h2 style={{ margin: 0 }}>Accounts ({filtered.length})</h2>
          <div className="row">
            <input
              style={{ width: 220, margin: 0 }}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Filter handle / org / role"
            />
            <select style={{ width: 140, margin: 0 }} value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
              <option value="all">All types</option>
              <option value="official">official</option>
              <option value="employee">employee</option>
              <option value="analyst">analyst</option>
              <option value="leak">leak</option>
            </select>
            <label className="row" style={{ gap: '0.35rem' }}>
              <input type="checkbox" checked={staleOnly} onChange={(e) => setStaleOnly(e.target.checked)} />
              Stale only
            </label>
            <label className="row" style={{ gap: '0.35rem' }}>
              <input type="checkbox" checked={enabledOnly} onChange={(e) => setEnabledOnly(e.target.checked)} />
              Enabled only
            </label>
          </div>
        </div>
        <table>
          <thead>
            <tr>
              <th></th>
              <th>Handle</th>
              <th>Type</th>
              <th>Org / role</th>
              <th>Verified</th>
              <th>Flags</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((a) => (
              <tr key={a.handle}>
                <td>
                  <input type="checkbox" checked={selected.has(a.handle)} onChange={() => toggle(a.handle)} />
                </td>
                <td>
                  <strong>@{a.handle}</strong>
                  {a.display_name ? <div className="muted">{a.display_name}</div> : null}
                </td>
                <td><span className="badge">{a.source_type}</span></td>
                <td>
                  {a.organization || '—'}
                  {a.role ? <div className="muted">{a.role}</div> : null}
                </td>
                <td>{a.verified_at?.slice(0, 10) || '—'}</td>
                <td>
                  {!a.enabled && <span className="badge exclude">disabled</span>}
                  {a.stale && <span className="badge uncertain">stale</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
