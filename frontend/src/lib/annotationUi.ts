export function parseScore(value: unknown): {
  display: string
  bar: number | null
  anomalous: boolean
} {
  if (value === null || value === undefined || value === '') {
    return { display: 'N/A', bar: null, anomalous: false }
  }
  const num = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(num)) {
    return { display: 'N/A', bar: null, anomalous: false }
  }
  let clamped = num
  let anomalous = false
  if (num < 0) {
    clamped = 0
    anomalous = true
  } else if (num > 10) {
    clamped = 10
    anomalous = true
  }
  return {
    display: `${clamped.toFixed(1)} / 10${anomalous ? ' !' : ''}`,
    bar: clamped,
    anomalous,
  }
}

export function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
}

export function previewText(...parts: Array<string | null | undefined>): string {
  for (const p of parts) {
    const t = (p || '').trim()
    if (t) return t.length > 80 ? `${t.slice(0, 80)}…` : t
  }
  return ''
}
