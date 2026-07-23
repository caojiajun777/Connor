/** Fallback if meta API is unreachable. Keep ordered lists in sync with app/daily/enums.py. */

export const FALLBACK_ANNOTATION_META = {
  policy_version: 'annotation-policy/v2',
  human_labels: ['include', 'exclude'] as const,
  reason_codes: {
    include: [
      'frontier_signal',
      'important_product_update',
      'official_confirmation',
      'other',
    ],
    exclude: ['low_information', 'old_information', 'not_frontier', 'other'],
  },
  deprecated_reason_codes: ['duplicate_event'],
  validation: {
    reason_codes_min: 1,
    reason_codes_soft_max: 2,
    other_requires_note: true,
  },
  confidence: { min: 0, max: 1, step: 0.05, default: 0.8 },
  // aliases
  labels: ['include', 'exclude'] as const,
  include_reason_codes: [
    'frontier_signal',
    'important_product_update',
    'official_confirmation',
    'other',
  ],
  exclude_reason_codes: ['low_information', 'old_information', 'not_frontier', 'other'],
  hidden_reason_codes: ['duplicate_event'],
  reason_rules: {
    include_exclude_min: 1,
    include_exclude_soft_max: 2,
    other_requires_note: true,
  },
}

export const REASON_LABEL_ZH: Record<string, string> = {
  frontier_signal: '前沿信号',
  important_product_update: '重要产品更新',
  official_confirmation: '官方确认',
  other: '其他（手填）',
  low_information: '信息量低',
  old_information: '旧闻',
  not_frontier: '不够前沿',
  // Legacy codes (may still appear on old rows)
  major_release: '重大发布',
  high_information_gain: '信息增量高',
  market_impact: '市场影响大',
  china_ai_significance: '对中国 AI 有意义',
  underestimated_by_model: '模型低估了',
  weak_source: '来源弱',
  pure_promotion: '纯宣传',
  insufficient_evidence: '证据不足',
  too_niche: '过窄',
  already_covered: '今日已覆盖该角度',
  low_daily_relevance: '日报相关性低',
  bare_repost: '裸转发，无新增信息',
  duplicate_event: '同一事件重复（历史原因码）',
}

export const LABEL_ZH: Record<string, string> = {
  include: '入选',
  exclude: '不入选',
  uncertain: '不确定（旧）',
  duplicate: '重复（旧）',
  all: '全部',
  unreviewed: '未审',
  machine_selected: '机器入选',
  machine_not_selected: '机器未选',
  disagree: '分歧',
}

export const LABEL_HELP: Record<string, string> = {
  include: '这条值得进今日日报。',
  exclude: '这条不进今日日报。',
}

export type AnnotationMeta = typeof FALLBACK_ANNOTATION_META

export function includeReasons(meta: AnnotationMeta): string[] {
  return meta.reason_codes?.include || meta.include_reason_codes || []
}

export function excludeReasons(meta: AnnotationMeta): string[] {
  return meta.reason_codes?.exclude || meta.exclude_reason_codes || []
}

export function softMaxReasons(meta: AnnotationMeta): number {
  return meta.validation?.reason_codes_soft_max ?? meta.reason_rules?.include_exclude_soft_max ?? 2
}
