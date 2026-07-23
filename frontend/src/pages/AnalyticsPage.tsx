import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../api/client'

function formatDwell(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms)) return '—'
  const sec = Math.round(ms / 1000)
  if (sec < 60) return `${sec}s`
  const min = Math.floor(sec / 60)
  const rem = sec % 60
  return rem ? `${min}m ${rem}s` : `${min}m`
}

export function AnalyticsPage() {
  const [days, setDays] = useState(7)
  const summary = useQuery({
    queryKey: ['analytics-summary', days],
    queryFn: () => api.analyticsSummary(days),
  })
  const series = useQuery({
    queryKey: ['analytics-timeseries', days],
    queryFn: () => api.analyticsTimeseries(days),
  })
  const paths = useQuery({
    queryKey: ['analytics-paths', days],
    queryFn: () => api.analyticsPaths(days),
  })
  const hours = useQuery({
    queryKey: ['analytics-hours', days],
    queryFn: () => api.analyticsHours(days),
  })

  const loading = summary.isLoading || series.isLoading || paths.isLoading || hours.isLoading
  const error = summary.error || series.error || paths.error || hours.error

  const hourData = useMemo(
    () =>
      (hours.data?.hours || []).map((h: { hour: number; pageviews: number }) => ({
        ...h,
        label: `${String(h.hour).padStart(2, '0')}:00`,
      })),
    [hours.data],
  )

  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between', marginBottom: '0.75rem' }}>
        <h1 style={{ margin: 0 }}>Analytics</h1>
        <div className="row">
          {[7, 30].map((d) => (
            <button
              key={d}
              type="button"
              className={days === d ? 'btn' : 'btn secondary'}
              onClick={() => setDays(d)}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>
      <p className="muted">
        First-party public site traffic (Asia/Shanghai). Anonymous visitor/session IDs only — no IP
        stored.
      </p>
      <p className="muted">
        Local testing (`127.0.0.1` / `localhost`) is never counted. Your production browsers: open{' '}
        <a href="https://aiconnor.cn/?analytics=off" target="_blank" rel="noreferrer">
          ?analytics=off once
        </a>{' '}
        (saved for 10 years). Or set <code>CONNOR_ANALYTICS_EXCLUDE_IPS</code> on the API host to
        permanently drop your public IP. Re-enable a browser with <code>?analytics=on</code>.
      </p>

      {loading && <p className="muted">Loading…</p>}
      {error && <p className="error">{(error as Error).message}</p>}

      {!loading && !error && (
        <>
          <div className="grid">
            <div className="stat">
              <div className="k">Pageviews</div>
              <div className="v">{summary.data?.pageviews ?? 0}</div>
            </div>
            <div className="stat">
              <div className="k">Unique visitors</div>
              <div className="v">{summary.data?.unique_visitors ?? 0}</div>
            </div>
            <div className="stat">
              <div className="k">Sessions</div>
              <div className="v">{summary.data?.sessions ?? 0}</div>
            </div>
            <div className="stat">
              <div className="k">Avg dwell</div>
              <div className="v">{formatDwell(summary.data?.avg_dwell_ms)}</div>
            </div>
          </div>

          <h2>Daily trend</h2>
          <div className="card" style={{ height: 300 }}>
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={series.data?.series || []}>
                <CartesianGrid stroke="#243040" strokeDasharray="3 3" />
                <XAxis dataKey="date" stroke="#8ea0b3" tick={{ fontSize: 11 }} />
                <YAxis stroke="#8ea0b3" tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip
                  contentStyle={{ background: '#171e27', border: '1px solid #273445' }}
                  labelStyle={{ color: '#e7ecf1' }}
                />
                <Legend />
                <Line type="monotone" dataKey="pageviews" name="PV" stroke="#7eb6ff" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="visitors" name="UV" stroke="#7ddea8" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>

          <h2>Visit hours (Beijing)</h2>
          <div className="card" style={{ height: 260 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={hourData}>
                <CartesianGrid stroke="#243040" strokeDasharray="3 3" />
                <XAxis dataKey="label" stroke="#8ea0b3" tick={{ fontSize: 10 }} interval={2} />
                <YAxis stroke="#8ea0b3" tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip
                  contentStyle={{ background: '#171e27', border: '1px solid #273445' }}
                  labelStyle={{ color: '#e7ecf1' }}
                />
                <Bar dataKey="pageviews" name="PV" fill="#2a6df4" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <h2>Top paths</h2>
          <div className="card">
            {(paths.data?.items || []).length === 0 ? (
              <p className="muted">No pageviews in this window yet. Browse the public site to generate data.</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Path</th>
                    <th>PV</th>
                    <th>UV</th>
                  </tr>
                </thead>
                <tbody>
                  {(paths.data?.items || []).map((row: { path: string; pageviews: number; visitors: number }) => (
                    <tr key={row.path}>
                      <td>
                        <code>{row.path}</code>
                      </td>
                      <td>{row.pageviews}</td>
                      <td>{row.visitors}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  )
}
