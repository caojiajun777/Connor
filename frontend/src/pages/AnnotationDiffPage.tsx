import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import { REASON_LABEL_ZH } from '../constants/annotation'

const STAT_ROWS: Array<{ key: string; label: string }> = [
  { key: 'machine_selected_human_include', label: 'Machine Selected / Human Include' },
  { key: 'machine_selected_human_exclude', label: 'Machine Selected / Human Exclude' },
  { key: 'machine_not_selected_human_include', label: 'Machine Not Selected / Human Include' },
  { key: 'machine_not_selected_human_exclude', label: 'Machine Not Selected / Human Exclude' },
  { key: 'uncertain', label: 'Uncertain' },
  { key: 'duplicate', label: 'Duplicate' },
  { key: 'unreviewed', label: 'Unreviewed' },
]

function ReasonTable({ title, rows }: { title: string; rows: Array<[string, number]> }) {
  return (
    <div className="card">
      <h2>{title}</h2>
      {rows.length === 0 && <p className="muted">None</p>}
      {rows.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Reason</th>
              <th>Count</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([code, count]) => (
              <tr key={code}>
                <td>
                  {REASON_LABEL_ZH[code] || code} <code className="muted">{code}</code>
                </td>
                <td>{count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export function AnnotationDiffPage() {
  const { annotationRunId = '' } = useParams()
  const { data, error, isLoading } = useQuery({
    queryKey: ['diff', annotationRunId],
    queryFn: () => api.diff(annotationRunId),
  })
  if (isLoading) return <p className="muted">Loading…</p>
  if (error) return <p className="error">{(error as Error).message}</p>

  const buckets = data.buckets || {}
  const counts = data.counts || {}

  const countFor = (key: string) => {
    if (key === 'uncertain' || key === 'duplicate') {
      return (buckets[key] || []).length
    }
    return counts[key] ?? (buckets[key] || []).length
  }

  const bucketEntries = Object.entries(buckets).filter(
    ([name]) =>
      ![
        'uncertain_or_duplicate', // shown as split uncertain/duplicate
      ].includes(name),
  )

  return (
    <div>
      <h1>Machine vs Human Diff</h1>
      <p>
        <Link to={`/console/editorial/${annotationRunId}`}>← Workspace</Link>
      </p>
      <div className="grid">
        <div className="stat">
          <div className="k">False positives</div>
          <div className="v">{data.false_positives}</div>
        </div>
        <div className="stat">
          <div className="k">False negatives</div>
          <div className="v">{data.false_negatives}</div>
        </div>
      </div>

      <div className="card">
        <h2>Fixed bucket counts</h2>
        <table>
          <thead>
            <tr>
              <th>Bucket</th>
              <th>Count</th>
            </tr>
          </thead>
          <tbody>
            {STAT_ROWS.map((row) => (
              <tr key={row.key}>
                <td>{row.label}</td>
                <td>{countFor(row.key)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="muted">Uncertain / Duplicate are listed separately and never count as true negatives.</p>
      </div>

      <ReasonTable title="Top include reasons" rows={data.top_include_reasons || []} />
      <ReasonTable title="Top exclude reasons" rows={data.top_exclude_reasons || []} />

      {bucketEntries.map(([name, rows]: any) => (
        <div className="card" key={name}>
          <h2>
            {name} ({rows.length})
          </h2>
          <table>
            <thead>
              <tr>
                <th>Post</th>
                <th>Machine</th>
                <th>Human</th>
                <th>Reasons</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r: any) => (
                <tr key={r.annotation_item_id}>
                  <td>
                    <code>{r.post_id}</code>
                  </td>
                  <td>
                    {r.machine_selected ? 'selected' : 'not'} / rank={r.machine_rank ?? '—'}
                  </td>
                  <td>{r.human_label || '—'}</td>
                  <td>{(r.reason_codes || []).join(', ') || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}
