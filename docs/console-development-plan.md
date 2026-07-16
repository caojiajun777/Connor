# Connor Console 后台两阶段开发计划

**Status:** Adopted  
**Date:** 2026-07-14  
**Baseline:** `v0.3.0-daily-core`

## 0. 项目定位

Connor Console 是 Connor Daily Agent 的内部后台，承担三类职责：

1. 生产运行观测
2. 历史内容人工标注
3. 模型质量评测与训练数据积累

它不是公开日报网站。公开的 Connor Daily 将来单独开发，采用沉浸式数字人播报界面。

后台第一阶段优先完成最重要的使用闭环：

```text
查看历史 Run
→ 查看当日全部候选及机器判断
→ 对候选进行人工标注
→ 保存机器与人工差异
→ 查看标注结果
```

第二阶段再增加长期运营、质量分析、数据集管理和系统观测能力。

---

## 一、核心设计原则

### 1. 生产数据不可变

以下生产数据不得通过后台修改：

* posts / run_posts / post_summaries / post_evaluations
* selection_runs / selection_items / publication_status
* 已发布日报内容与顺序

人工判断必须存入独立 Annotation 数据模型，不得覆盖模型原始评分、排名、机器入选或已发布结果。

### 2. 人工标注是历史监督数据，不是发布审核

人工操作表示：「人工认为这条信息是否值得进入当日日报。」  
不表示修改/重新发布/撤回当天已发布日报，也不改写生产结果。

### 3. FastAPI 是唯一数据边界

前端不得直连 PostgreSQL / Redis，不得在浏览器重算 Top K，不得用「最新摘要」代替 Run 绑定摘要。

### 4. 标注必须绑定明确版本

每条人工标注必须绑定：`source_run_id`、`post_id`、`summary_id`、`evaluation_id`。

### 5. 第一阶段不做训练

只收集标签与差异；不做 DPO / LoRA / Preference Pair / 模型部署。

---

## 二、技术栈

* 前端：React + Vite + TypeScript + React Router + TanStack Query + Tailwind + shadcn/ui
* 后端：现有 FastAPI + SQLAlchemy + PostgreSQL
* 路由前缀：`/console/*`（公开日报保留根路由）
* API 前缀：`/api/console/*`

---

## 三、第一阶段数据模型

### annotation_runs

`id`, `source_run_id`, `annotation_policy_version`, `status`, `annotator`,
`total_items`, `reviewed_items`, `created_at`, `updated_at`, `completed_at`

Status: `pending` | `in_progress` | `completed`  
Unique: `(source_run_id, annotation_policy_version)`

### annotation_items

绑定：`post_id`, `summary_id`, `evaluation_id`  
冻结机器侧：`machine_selected`, `machine_rank`, `machine_top_k_rank`  
人工侧：`human_label`, `human_rank`, `confidence`, `reason_codes`, `note`  
乐观锁：`version`（integer）

Labels: `include` | `exclude` | `uncertain` | `duplicate`

### reason_codes（JSON 数组）

Exclude: `low_information`, `duplicate_event`, `old_information`, `weak_source`,
`pure_promotion`, `insufficient_evidence`, `not_frontier`, `too_niche`,
`already_covered`, `low_daily_relevance`

Include: `major_release`, `official_confirmation`, `high_information_gain`,
`frontier_signal`, `important_product_update`, `market_impact`,
`china_ai_significance`, `underestimated_by_model`

---

## 四、第一阶段页面与 API

页面：Overview / Run History / Run Detail / Annotation Inbox / Workspace / Diff  

API：

```http
GET  /api/console/runs
GET  /api/console/runs/{run_id}
GET  /api/console/runs/{run_id}/candidates
GET  /api/console/runs/{run_id}/selection
GET  /api/console/runs/{run_id}/versions
GET  /api/console/runs/{run_id}/errors
GET  /api/console/annotations
POST /api/console/annotations
GET  /api/console/annotations/{annotation_run_id}
GET  /api/console/annotations/{annotation_run_id}/items
PATCH /api/console/annotations/{annotation_run_id}/items/{annotation_item_id}
POST /api/console/annotations/{annotation_run_id}/complete
POST /api/console/annotations/{annotation_run_id}/reopen
GET  /api/console/annotations/{annotation_run_id}/diff
```

---

## 五、第一阶段完成标准

1–12 见用户确认稿（查看 Run/候选/摘要评价/机器选择；创建与继续标注；Include/Exclude/Uncertain/Duplicate；差异视图；刷新不丢；生产结果不变；测试通过）。

验收 Run：`8c76ec87-cfe9-4fb7-90bc-363f472de075`

---

## 六、第二阶段（摘要）

Sources / Content Library / Quality Analytics / Model·Prompt Versions /
Dataset Export / System Health。仍禁止改生产事实与直连 Redis。

---

## 七、明确暂不开发

公开日报、数字人、TTS、训练、多用户权限、网页触发 Daily Run / Resume /
accept_partial / 发布撤回、通用 DB 管理器等。

---

## 八、开发顺序（第一阶段）

```text
1. Gap Analysis
2. Annotation Schema（create_all + 后续 Alembic）
3. Console Run Read API
4. Annotation Write API
5. React/Vite 工程
6. Run History / Detail
7. Annotation Inbox / Workspace / Diff
8. 自动保存与快捷键
9. 测试与 E2E 验收
```
