import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import {
  FALLBACK_ANNOTATION_META,
  LABEL_HELP,
  LABEL_ZH,
  REASON_LABEL_ZH,
  excludeReasons,
  includeReasons,
  softMaxReasons,
  type AnnotationMeta,
} from '../constants/annotation'
import { isEditableTarget, parseScore, previewText } from '../lib/annotationUi'

type Draft = {
  human_label: string
  confidence: number
  reason_codes: string[]
  note: string
  human_rank: string
}

const EMPTY_DRAFT: Draft = {
  human_label: '',
  confidence: 0.8,
  reason_codes: [],
  note: '',
  human_rank: '',
}

function ScoreRow({ label, value, emphasis }: { label: string; value: unknown; emphasis?: boolean }) {
  const s = parseScore(value)
  const pct = s.bar == null ? 0 : (s.bar / 10) * 100
  return (
    <div className={emphasis ? 'score-row emphasis' : 'score-row'}>
      <div className="score-label">{label}</div>
      <div className="score-track">
        {s.bar != null && <div className="score-fill" style={{ width: `${pct}%` }} />}
      </div>
      <div className="score-value">{s.display}</div>
    </div>
  )
}

function ScoreBoard({ evaluation }: { evaluation: any }) {
  const status = !evaluation
    ? 'Missing'
    : evaluation.status
      ? String(evaluation.status)
      : evaluation.frontier_score == null && evaluation.importance_score == null
        ? 'Missing'
        : 'Success'
  return (
    <div className="score-board">
      <p className="status-line">
        Evaluation: <strong>{status === 'success' ? 'Success' : status === 'Missing' ? 'Missing' : status}</strong>
      </p>
      <ScoreRow label="Frontier" value={evaluation?.frontier_score} emphasis />
      <ScoreRow label="Importance" value={evaluation?.importance_score} />
      <ScoreRow label="Info gain" value={evaluation?.information_gain_score} />
      <ScoreRow label="Specificity" value={evaluation?.specificity_score} />
    </div>
  )
}

export function AnnotationWorkspacePage() {
  const { annotationRunId = '' } = useParams()
  const qc = useQueryClient()
  const ann = useQuery({ queryKey: ['annotation', annotationRunId], queryFn: () => api.annotation(annotationRunId) })
  const itemsQ = useQuery({
    queryKey: ['annotation-items', annotationRunId],
    queryFn: () => api.annotationItems(annotationRunId),
  })
  const [metaFailed, setMetaFailed] = useState(false)
  const metaQ = useQuery({
    queryKey: ['annotation-meta'],
    queryFn: async () => {
      try {
        const m = (await api.annotationMeta()) as AnnotationMeta
        setMetaFailed(false)
        return m
      } catch {
        setMetaFailed(true)
        return FALLBACK_ANNOTATION_META
      }
    },
    staleTime: 60_000,
  })
  const meta = metaQ.data || FALLBACK_ANNOTATION_META
  const deprecated = new Set(meta.deprecated_reason_codes || meta.hidden_reason_codes || ['duplicate_event'])

  const [filter, setFilter] = useState('all')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT)
  const [formError, setFormError] = useState<string | null>(null)
  const [navHint, setNavHint] = useState<string | null>(null)
  const [pendingSwitchId, setPendingSwitchId] = useState<string | null>(null)
  const baselineRef = useRef('')

  const items = itemsQ.data?.items || []
  const labels = meta.human_labels || meta.labels || FALLBACK_ANNOTATION_META.human_labels

  const filtered = useMemo(() => {
    return items.filter((i: any) => {
      if (filter === 'unreviewed') return !i.human_label
      if (filter === 'machine_selected') return i.machine_selected
      if (filter === 'machine_not_selected') return !i.machine_selected
      if (filter === 'disagree') {
        if (!i.human_label || i.human_label === 'uncertain' || i.human_label === 'duplicate') return false
        return (i.human_label === 'include') !== i.machine_selected
      }
      if ((labels as readonly string[]).includes(filter)) return i.human_label === filter
      return true
    })
  }, [items, filter, labels])

  useEffect(() => {
    if (!selectedId && filtered[0]) setSelectedId(filtered[0].annotation_item_id)
  }, [filtered, selectedId])

  const current = items.find((i: any) => i.annotation_item_id === selectedId)
  const candidates = useQuery({
    queryKey: ['candidates', ann.data?.source_run_id],
    queryFn: () => api.candidates(ann.data.source_run_id),
    enabled: !!ann.data?.source_run_id,
  })

  const detailByPostId = useMemo(() => {
    const map = new Map<string, any>()
    for (const c of candidates.data?.items || []) map.set(c.post_id, c)
    return map
  }, [candidates.data])

  const detail = current ? detailByPostId.get(current.post_id) : undefined
  const bareRepost = detail?.post?.post_type === 'repost'

  const draftKey = (d: Draft) => JSON.stringify(d)

  useEffect(() => {
    if (!current) return
    const next: Draft = {
      human_label: current.human_label || '',
      confidence: current.confidence ?? meta.confidence?.default ?? 0.8,
      reason_codes: [...(current.reason_codes || [])],
      note: current.note || '',
      human_rank: current.human_rank != null ? String(current.human_rank) : '',
    }
    setDraft(next)
    baselineRef.current = draftKey(next)
    setFormError(null)
    setNavHint(null)
  }, [current?.annotation_item_id, current?.version, meta.confidence?.default])

  const dirty = draftKey(draft) !== baselineRef.current

  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (!dirty) return
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [dirty])

  const allowedReasons = useMemo(() => {
    if (draft.human_label === 'include') return includeReasons(meta)
    if (draft.human_label === 'exclude') return excludeReasons(meta)
    return [] as string[]
  }, [draft.human_label, meta])

  const legacyCodes = draft.reason_codes.filter((c) => deprecated.has(c))
  const softMax = softMaxReasons(meta)
  const readOnly = metaFailed || ann.data?.status === 'completed'

  const setLabel = (label: string) => {
    setDraft((d) => {
      const next: Draft = { ...d, human_label: label }
      if (d.human_label && d.human_label !== label) {
        next.reason_codes = []
        next.note = ''
      }
      return next
    })
    setFormError(null)
  }

  const toggleReason = (code: string) => {
    if (deprecated.has(code)) return
    setDraft((d) => {
      const has = d.reason_codes.includes(code)
      const reason_codes = has ? d.reason_codes.filter((c) => c !== code) : [...d.reason_codes, code]
      return { ...d, reason_codes }
    })
  }

  const validateLocal = (): string | null => {
    const note = draft.note.trim()
    if (draft.human_label === 'include' || draft.human_label === 'exclude') {
      const active = draft.reason_codes.filter((c) => !deprecated.has(c))
      if (active.length < 1 && legacyCodes.length === 0) return `${LABEL_ZH[draft.human_label] || draft.human_label} 至少选择 1 个理由`
      if (draft.reason_codes.includes('other') && !note) return '选择「其他」时必须填写说明'
    }
    return null
  }

  const save = useMutation({
    mutationFn: async () => {
      if (!current) return
      if (metaFailed) throw new Error('标注元数据加载失败，无法保存')
      const err = validateLocal()
      if (err) throw new Error(err)
      return api.patchItem(annotationRunId, current.annotation_item_id, {
        human_label: draft.human_label || null,
        confidence: Number(draft.confidence),
        reason_codes: draft.reason_codes,
        note: draft.note,
        human_rank: draft.human_rank ? Number(draft.human_rank) : null,
        clear_human_rank: !draft.human_rank,
        expected_version: current.version,
      })
    },
    onSuccess: () => {
      setFormError(null)
      baselineRef.current = draftKey(draft)
      qc.invalidateQueries({ queryKey: ['annotation-items', annotationRunId] })
      qc.invalidateQueries({ queryKey: ['annotation', annotationRunId] })
    },
    onError: (e: Error) => setFormError(e.message),
  })

  const complete = useMutation({
    mutationFn: () => api.complete(annotationRunId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['annotation', annotationRunId] }),
  })

  const applySelect = (id: string) => {
    setPendingSwitchId(null)
    setSelectedId(id)
    setNavHint(null)
  }

  const requestSelect = (id: string) => {
    if (id === selectedId) return
    if (dirty) {
      setPendingSwitchId(id)
      return
    }
    applySelect(id)
  }

  const move = (delta: number) => {
    const idx = filtered.findIndex((i: any) => i.annotation_item_id === selectedId)
    const next = filtered[idx + delta]
    if (!next) return
    if (dirty) {
      setNavHint('存在未保存修改：请先 Save，或 Ctrl+Enter 保存并下一条')
      return
    }
    applySelect(next.annotation_item_id)
  }

  const saveAndNext = () => {
    if (save.isPending || readOnly) return
    save.mutate(undefined, {
      onSuccess: () => {
        const idx = filtered.findIndex((i: any) => i.annotation_item_id === selectedId)
        const next = filtered[idx + 1]
        if (next) applySelect(next.annotation_item_id)
      },
    })
  }

  const saveAndSwitch = () => {
    if (!pendingSwitchId || save.isPending) return
    const target = pendingSwitchId
    save.mutate(undefined, {
      onSuccess: () => applySelect(target),
    })
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (ann.data?.status === 'completed') return
      const editable = isEditableTarget(e.target)
      if (editable) {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
          e.preventDefault()
          saveAndNext()
        }
        return
      }
      const key = e.key.toLowerCase()
      if (key === 'i') setLabel('include')
      if (key === 'e' && !e.ctrlKey) setLabel('exclude')
      if (key === 'j') move(1)
      if (key === 'k') move(-1)
      if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        e.preventDefault()
        saveAndNext()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  if (ann.isLoading || itemsQ.isLoading) return <p className="muted">Loading…</p>
  if (ann.error) return <p className="error">{(ann.error as Error).message}</p>

  const showReasons = draft.human_label === 'include' || draft.human_label === 'exclude'
  const showOtherNote = showReasons && draft.reason_codes.includes('other')
  const noteRequired = showOtherNote
  const activeReasonCount = draft.reason_codes.filter((c) => !deprecated.has(c)).length

  return (
    <div>
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <div>
          <h1>Annotation Workspace</h1>
          <p className="muted">
            {ann.data?.status} · {ann.data?.reviewed_items}/{ann.data?.total_items} · policy{' '}
            {meta.policy_version || ann.data?.annotation_policy_version || '—'} · source{' '}
            <Link to={`/console/runs/${ann.data?.source_run_id}`}>{ann.data?.source_run_id?.slice(0, 8)}</Link>
            {dirty ? ' · unsaved' : ''}
          </p>
          {metaFailed && <p className="error">标注元数据 API 失败，已降级为本地 fallback；保存已禁用。</p>}
          {navHint && <p className="warn">{navHint}</p>}
        </div>
        <div className="row">
          <Link to={`/console/editorial/${annotationRunId}/diff`}>Diff</Link>
          <button
            className="btn secondary"
            disabled={complete.isPending || ann.data?.status === 'completed'}
            onClick={() => complete.mutate()}
          >
            Complete
          </button>
        </div>
      </div>

      <div className="row" style={{ marginBottom: '0.75rem' }}>
        {['all', 'unreviewed', 'machine_selected', 'machine_not_selected', 'disagree', ...labels].map((f) => (
          <button key={f} className={filter === f ? 'tab active' : 'tab'} onClick={() => setFilter(f)}>
            {LABEL_ZH[f] || f}
          </button>
        ))}
      </div>

      {pendingSwitchId && (
        <div className="modal-backdrop">
          <div className="modal card">
            <h3>未保存的修改</h3>
            <p className="muted">当前候选有未保存内容，请选择：</p>
            <div className="row">
              <button className="btn" disabled={save.isPending} onClick={saveAndSwitch}>
                保存并切换
              </button>
              <button className="btn secondary" onClick={() => applySelect(pendingSwitchId)}>
                放弃修改
              </button>
              <button className="btn secondary" onClick={() => setPendingSwitchId(null)}>
                取消
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="workspace">
        <div className="panel">
          <h3>Candidates ({filtered.length})</h3>
          {filtered.map((i: any) => {
            const d = detailByPostId.get(i.post_id)
            const handle = d?.post?.handle || d?.post?.watchlist_handle
            const fScore = parseScore(d?.evaluation?.frontier_score)
            const preview = previewText(d?.summary?.summary, d?.post?.text, i.post_id?.slice(-6))
            return (
              <div
                key={i.annotation_item_id}
                className={i.annotation_item_id === selectedId ? 'cand active' : 'cand'}
                onClick={() => requestSelect(i.annotation_item_id)}
              >
                <div className="cand-top">
                  <strong>@{handle || i.post_id.slice(-6)}</strong>
                  <span>F {fScore.bar == null ? 'N/A' : fScore.bar.toFixed(1)}</span>
                </div>
                <div className="cand-mid">
                  <span>Machine: {i.machine_selected ? 'Selected' : 'Not selected'}</span>
                  <span>Human: {i.human_label || '—'}</span>
                </div>
                <div className="cand-preview">{preview}</div>
              </div>
            )
          })}
        </div>

        <div className="panel detail">
          <h3>Detail</h3>
          {!detail && <p className="muted">Select a candidate</p>}
          {detail && (
            <>
              <p>
                <strong>@{detail.post?.handle}</strong> · {detail.post?.published_at}
              </p>
              <p>
                <a href={detail.post?.url} target="_blank" rel="noreferrer">
                  Open on X
                </a>
              </p>
              {bareRepost && <p className="warn">Bare repost detected（仅提示，不自动判定）</p>}
              <div className="post-body">{detail.post?.text}</div>

              <div className="machine-card">
                <div className="section-title">Machine Assessment</div>
                <div className="status-line">
                  Machine Selection: <strong>{current?.machine_selected ? 'Selected' : 'Not selected'}</strong>
                </div>
                <div className="status-line">
                  Evaluation Rank: {current?.machine_top_k_rank != null ? `#${current.machine_top_k_rank}` : '—'}
                </div>
                <div className="status-line">
                  Editorial Rank: {current?.machine_rank != null ? `#${current.machine_rank}` : '—'}
                </div>
                <div className="status-line">
                  Human: <strong>{current?.human_label || 'unreviewed'}</strong>
                </div>
                <h4 style={{ margin: '0.75rem 0 0.25rem', fontSize: '0.9rem' }}>中文译文</h4>
                <div className="summary-body">{detail.summary?.summary}</div>
                {detail.summary?.content_type && <span className="pill">{detail.summary.content_type}</span>}
                <ScoreBoard evaluation={detail.evaluation} />
                {detail.evaluation?.content_category && (
                  <p className="muted">
                    Category: <span className="pill">{detail.evaluation.content_category}</span>
                  </p>
                )}
                <h4 style={{ margin: '0.5rem 0 0.25rem', fontSize: '0.9rem' }}>Evaluation reason</h4>
                <div className="reason-body">
                  {detail.evaluation?.evaluation_reason || 'No machine reason available'}
                </div>
                {detail.evaluation && (
                  <details className="raw-block">
                    <summary>Raw Evaluation JSON</summary>
                    <pre>{JSON.stringify(detail.evaluation, null, 2)}</pre>
                  </details>
                )}
                {detail.selection && (
                  <details className="raw-block">
                    <summary>Raw Selection JSON</summary>
                    <pre>{JSON.stringify(detail.selection, null, 2)}</pre>
                  </details>
                )}
              </div>
            </>
          )}
        </div>

        <div className="panel form">
          <div className="human-card" style={{ borderTop: 0, marginTop: 0, paddingTop: 0 }}>
            <div className="section-title">Human Annotation</div>
            <label>Label</label>
            <div className="label-btns">
              {labels.map((l) => (
                <button
                  key={l}
                  type="button"
                  className={draft.human_label === l ? 'label-btn active' : 'label-btn'}
                  disabled={readOnly}
                  title={LABEL_HELP[l] || undefined}
                  onClick={() => setLabel(l)}
                >
                  {LABEL_ZH[l] || l}
                </button>
              ))}
            </div>
            {draft.human_label && draft.human_label !== 'include' && draft.human_label !== 'exclude' && (
              <p className="warn">
                当前为历史标签「{LABEL_ZH[draft.human_label] || draft.human_label}」，请改选「入选」或「不入选」后保存。
              </p>
            )}

            {legacyCodes.length > 0 && (
              <div className="legacy-box">
                <p className="warn">历史原因码（已废弃，仅可读）：</p>
                <div className="chips">
                  {legacyCodes.map((code) => (
                    <span key={code} className="chip legacy" title="legacy/deprecated">
                      {REASON_LABEL_ZH[code] || code}
                    </span>
                  ))}
                </div>
                <p className="muted">请改选「不入选」并勾选新理由后保存。</p>
              </div>
            )}

            {showReasons && (
              <>
                <label>理由（选 1–{softMax} 个）</label>
                <div className="chips">
                  {allowedReasons.map((code) => (
                    <button
                      key={code}
                      type="button"
                      className={draft.reason_codes.includes(code) ? 'chip active' : 'chip'}
                      disabled={readOnly}
                      onClick={() => toggleReason(code)}
                    >
                      {REASON_LABEL_ZH[code] || code}
                    </button>
                  ))}
                </div>
                {activeReasonCount > softMax && (
                  <p className="warn">
                    建议选择最主要的 1–{softMax} 个原因，当前已选择 {activeReasonCount} 个。
                  </p>
                )}
              </>
            )}

            <label>Confidence</label>
            <div className="confidence-row">
              <input
                type="range"
                min={meta.confidence?.min ?? 0}
                max={meta.confidence?.max ?? 1}
                step={meta.confidence?.step ?? 0.05}
                value={draft.confidence}
                disabled={readOnly}
                onChange={(e) => setDraft({ ...draft, confidence: Number(e.target.value) })}
              />
              <span>{Number(draft.confidence).toFixed(2)}</span>
            </div>

            <label>Human rank（可选）</label>
            <input
              value={draft.human_rank}
              disabled={readOnly}
              onChange={(e) => setDraft({ ...draft, human_rank: e.target.value })}
            />

            <label>{noteRequired ? '其他理由说明（必填）' : '备注（可选）'}</label>
            <textarea
              rows={5}
              value={draft.note}
              disabled={readOnly}
              placeholder={
                showOtherNote ? '请说明未被现有原因码覆盖的原因' : '可选备注'
              }
              onChange={(e) => setDraft({ ...draft, note: e.target.value })}
            />

            <div className="row">
              <button
                className="btn"
                disabled={!current || save.isPending || readOnly || !draft.human_label}
                onClick={() => save.mutate()}
              >
                Save
              </button>
              <button
                className="btn secondary"
                disabled={!current || save.isPending || readOnly || !draft.human_label}
                onClick={saveAndNext}
              >
                Save & next
              </button>
            </div>
            {(formError || save.error) && (
              <p className="error">{formError || (save.error as Error).message}</p>
            )}
            <p className="muted">Shortcuts: I/E/U/D · J/K（dirty 时不切换）· Ctrl+Enter</p>
          </div>
        </div>
      </div>
    </div>
  )
}
