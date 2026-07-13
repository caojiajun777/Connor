# Connor 项目状态总结（2026-07-14）

**结论：** 以 *Connor Daily Agent Specification v1* 为范围，**M1 → M3e 主干已完成并可端到端 live 跑通**。  
后续工作属于运营加固、产品化与发布通道，不再是“能否出日报”的阻塞项。

---

## 1. 产品定位

Connor 是本地运行的 **AI 前沿 X（Twitter）日报流水线**：

1. 按 watchlist 增量采集账号时间线  
2. 全量候选入库（游标只定边界，不做每账号业务截断）  
3. 摘要 → 绝对评分 → Top K → 编辑精选 Top ≤ 20  
4. 精选结果默认 **unpublished**（选择 ≠ 发布）

冻结规格：[`docs/agent-design.md`](agent-design.md)（Daily Agent Spec v1）  
采集契约：[`docs/x-source-collection-design.md`](x-source-collection-design.md)

---

## 2. 里程碑完成度

| ID | 范围 | 状态 |
|----|------|------|
| **M1** | X MCP（TS）+ watchlist 增量采集（Python） | ✅ 完成 |
| **M2** | 文件路径 editorial 精选（`editorial-picks/v2`） | ✅ 完成 |
| **M3a** | PG schema、Redis 游标、薄 LangGraph、advisory lock、文件游标导入 | ✅ 完成 |
| **M3b** | `cursor_eligible`、账号采集 → persist → outbox → Redis、`known_data_gap` | ✅ 完成 |
| **M3c** | 冻结 `run_posts`、版本化 `post_summaries`、summary gate | ✅ 完成 |
| **M3d** | `post_evaluations(summary_id)`、确定性 Top K、编辑 Top≤20 | ✅ 完成 |
| **M3e** | checkpointer、production start/resume、scheduler tick、metrics、只读 API | ✅ 完成 |

Live 验证（2026-07-13 夜）：

- Run `8c76ec87-cfe9-4fb7-90bc-363f472de075`
- 采集 35 账号 → 候选 34 → 摘要 34/34 → 评价 34/34 → Top 20（均为 `unpublished`）
- `status=completed`

冒烟采集：`simonw` + `OpenAI` MCP 会话正常，增量游标行为符合预期。

---

## 3. 当前架构

```text
src/                    TypeScript X News MCP（Playwright + 持久 Chrome profile）
app/x_watchlist/        M1 编排：MCP client / cleaner / normalizer / file cursors
app/editorial/          M2 文件产物路径（可独立跑）
app/daily/              M3 Daily Agent：LangGraph + PG + Redis + LLM phases
config/x_watchlist.yaml 账号清单（约 35 个 enabled）
docs/                   规格文档
fixtures/m1_golden_run/ M1/M2 黄金样本
scripts/                ensure_daily_db / debug_daily_e2e
tests/                  pytest（当前 84 passed）
```

### 主干数据流

```text
X MCP (Chrome profile)
  → collect_accounts_loop（每账号：cursor → 分页 → scan）
  → PostgreSQL COMMIT（posts / run_posts / account_runs / outbox）
  → Redis cursor sync（无 TTL）
  → freeze candidates
  → summarize → evaluate → Top K → editorial Top ≤ 20
  → selection_items.publication_status = unpublished
```

### 运行时依赖

| 组件 | 本地约定 |
|------|----------|
| PostgreSQL | 默认库 `connor_daily`（避免与旧库 `connor` 的 VARCHAR `runs` 冲突） |
| Redis | `redis://localhost:6379/0`（如 Docker `task-redis`） |
| X 会话 | `~/.codex-x-news-agent` + MCP `dist/index.js` |
| LLM | `DEEPSEEK_API_KEY` / `CONNOR_LLM_API_KEY`（OpenAI-compatible） |

---

## 4. 主要 CLI

```powershell
# 基础设施
python scripts/ensure_daily_db.py
python -m app.cli daily init-db
python -m app.cli daily import-cursors

# M1 采集
python -m app.cli x-watchlist collect --dry-run
python -m app.cli x-watchlist collect --handles OpenAI,simonw

# M2 文件路径 editorial
python -m app.cli editorial run --dry-run
python -m app.cli editorial run --input fixtures/m1_golden_run/clean_posts.json

# M3 Daily
python -m app.cli daily dry-run
python -m app.cli daily run --live --accept-partial
python -m app.cli daily resume --run-id <uuid> --accept-partial
python -m app.cli daily tick --live
python -m app.cli daily serve-api --port 8080

# 本地 e2e（golden seed，可无 Redis）
python scripts/debug_daily_e2e.py
```

常用环境变量：`CONNOR_DATABASE_URL`、`CONNOR_REDIS_URL`、`DEEPSEEK_API_KEY`、`X_AGENT_PROFILE_DIR`。

---

## 5. Live 接线修复（2026-07-13 调试记下）

跑通 live 时补上的关键缺口（代码已在工作树，相对 commit `1437d2a` 可能仍有未提交改动）：

1. **`daily run --live` 原先未调用 MCP collect** → 已在 `production.start` 串上 collect → summarize → evaluate  
2. **LLM client 未注入**（`llm=None` 会静默走 mock）→ 现用 `OpenAICompatibleClient`  
3. **thinking + 小 `max_tokens` 导致 JSON 截断** → daily 批量阶段关闭 thinking，按阶段设 token 上限  
4. **个别账号 MCP 空返回 `failed_retryable` 会卡死整 run** → `--accept-partial` 可软放行  
5. **默认 DB 改为 `connor_daily`**，避免与旧 `connor.runs` 类型冲突  

---

## 6. 明确不在 v1 范围内 / 已知后续

下列项**不算未完成阻塞**，可作为下一阶段：

| 主题 | 说明 |
|------|------|
| 发布通道 | 精选已落库但 `unpublished`；尚无自动发帖 / 邮件 / 站点渲染 |
| 定时生产 | `daily tick` 与 scheduler 已有；需固化 cron / 机器常开与告警 webhook |
| PostgresSaver | 可选 `--postgres-checkpointer`；默认 memory checkpointer 足够本地 |
| 失败账号重试 | MCP 偶发空列表（如部分账号）；可单独重采或二次 resume |
| 观测面板 | 只读 FastAPI 已有；尚无正式 UI / Canvas |
| 多日运营 | 游标长期漂移、`known_data_gap` 运维手册、backfill 工具 |
| 测试覆盖 live 接线 | 单元测试 84 绿；production collect/LLM 接线偏集成验证 |

---

## 7. 质量快照（写文档时）

- **pytest：** `84 passed`（`tests/daily` + `tests/editorial` + `tests/x_watchlist`）  
- **Git：** `main` 领先 `origin/main` 1 commit（`1437d2a`）；工作树另有 live 接线与脚本改动待提交  
- **规格：** Spec v1 frozen；实现与规格主路径一致  

---

## 8. 一句话状态

> Connor v1：**能每日从 X 增量采集 → 入库 → 摘要评分 → 产出 Top≤20 未发布精选**；主干完成。  
> 下一步若继续，优先：**提交 live 接线改动、固化定时任务、做 unpublished → published 发布通道**。

---

*文档生成日期：2026-07-14*  
*对应 live 成功 run：`8c76ec87-cfe9-4fb7-90bc-363f472de075`*
