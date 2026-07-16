/** Fallback if meta API is unreachable. Keep ordered lists in sync with app/daily/enums.py. */

export const FALLBACK_ANNOTATION_META = {
  policy_version: 'annotation-policy/v1',
  human_labels: ['include', 'exclude', 'uncertain', 'duplicate'] as const,
  reason_codes: {
    include: [
      'major_release',
      'important_product_update',
      'official_confirmation',
      'high_information_gain',
      'frontier_signal',
      'market_impact',
      'china_ai_significance',
      'underestimated_by_model',
      'other',
    ],
    exclude: [
      'low_information',
      'old_information',
      'bare_repost',
      'pure_promotion',
      'weak_source',
      'insufficient_evidence',
      'not_frontier',
      'low_daily_relevance',
      'too_niche',
      'already_covered',
      'other',
    ],
  },
  deprecated_reason_codes: ['duplicate_event'],
  validation: {
    reason_codes_min: 1,
    reason_codes_soft_max: 3,
    other_requires_note: true,
    duplicate_requires_note: true,
  },
  confidence: { min: 0, max: 1, step: 0.05, default: 0.8 },
  // aliases
  labels: ['include', 'exclude', 'uncertain', 'duplicate'] as const,
  include_reason_codes: [
    'major_release',
    'important_product_update',
    'official_confirmation',
    'high_information_gain',
    'frontier_signal',
    'market_impact',
    'china_ai_significance',
    'underestimated_by_model',
    'other',
  ],
  exclude_reason_codes: [
    'low_information',
    'old_information',
    'bare_repost',
    'pure_promotion',
    'weak_source',
    'insufficient_evidence',
    'not_frontier',
    'low_daily_relevance',
    'too_niche',
    'already_covered',
    'other',
  ],
  hidden_reason_codes: ['duplicate_event'],
  reason_rules: {
    include_exclude_min: 1,
    include_exclude_soft_max: 3,
    other_requires_note: true,
    duplicate_requires_note: true,
  },
}

export const REASON_LABEL_ZH: Record<string, string> = {
  major_release: '重大发布',
  official_confirmation: '官方确认',
  high_information_gain: '信息增量高',
  frontier_signal: '前沿信号',
  important_product_update: '重要产品更新',
  market_impact: '市场影响大',
  china_ai_significance: '对中国 AI 有意义',
  underestimated_by_model: '模型低估了',
  other: '其他（手填）',
  low_information: '信息量低',
  old_information: '旧闻',
  weak_source: '来源弱',
  pure_promotion: '纯宣传',
  insufficient_evidence: '证据不足',
  not_frontier: '不够前沿',
  too_niche: '过窄',
  already_covered: '今日已覆盖该角度',
  low_daily_relevance: '日报相关性低',
  bare_repost: '裸转发，无新增信息',
  duplicate_event: '同一事件重复（历史原因码）',
}

export const LABEL_ZH: Record<string, string> = {
  include: 'Include 入选',
  exclude: 'Exclude 不入选',
  uncertain: 'Uncertain 不确定',
  duplicate: 'Duplicate 重复',
}

export const LABEL_HELP: Record<string, string> = {
  duplicate: '与另一候选属于同一事件，或内容实质重复。',
  already_covered: '这条本身不重复，但其信息角度已被日报中的其他条目覆盖。',
}

export type AnnotationMeta = typeof FALLBACK_ANNOTATION_META

export function includeReasons(meta: AnnotationMeta): string[] {
  return meta.reason_codes?.include || meta.include_reason_codes || []
}

export function excludeReasons(meta: AnnotationMeta): string[] {
  return meta.reason_codes?.exclude || meta.exclude_reason_codes || []
}

export function softMaxReasons(meta: AnnotationMeta): number {
  return meta.validation?.reason_codes_soft_max ?? meta.reason_rules?.include_exclude_soft_max ?? 3
}
