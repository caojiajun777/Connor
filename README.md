# Connor

X 信息源采集项目：本地 MCP 服务（TypeScript）+ Watchlist 增量编排（Python）。

仓库：https://github.com/caojiajun777/Connor

## 项目结构

```text
src/                 # X News MCP server（Playwright + 持久 Chrome profile）
app/x_watchlist/     # Python 采集编排：MCP client / cleaner / cursors / runner
app/editorial/       # M2 编辑排序（文件产物路径）
app/daily/           # M3+ Daily Agent：LangGraph / PG / Redis
config/              # x_watchlist.yaml 账号清单
docs/                # 采集层 + Daily Agent 规格
fixtures/            # 轻量黄金运行样本（M2 输入）
tests/               # Python 单元测试
.codex/config.toml   # Codex MCP 注册
```

## 工作方式

- 第一次运行登录脚本时，会打开一个独立 Chrome 窗口。
- 你在该窗口正常登录 X；会话只保存在 `~/.codex-x-news-agent`。
- MCP 工具之后以只读方式复用该 profile，访问 X 的 `Latest` 搜索、账号 Posts 页面和单条帖子。
- cookies、密码和 token 不进入项目源码，也不会通过 MCP 工具返回。

## 安装与构建

```powershell
$pnpm = 'C:\Users\90556\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd'
& $pnpm install
& $pnpm run build
& $pnpm test
```

## 首次登录

```powershell
& 'C:\Users\90556\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin\fallback\pnpm.cmd' run login
```

在弹出的专用原生 Chrome 窗口完成 X/Google 登录。确认已经看到 X Home 时间线后，**手动关闭这个专用窗口**；会话会留在用户目录。登录阶段不使用浏览器自动化，因此不会触发 Google 的“浏览器不安全”限制。

## 在 Codex 中启用

项目已包含 `.codex/config.toml`。构建并登录后，重启 Codex 或重新打开受信任的工作区。服务会提供：

- `x_session_status`：验证专用会话，并返回结构化登录错误原因与恢复建议。
- `x_search_posts`：搜索 X Latest，可指定日期、语言和分页。
- `x_profile_posts`：读取账号 Posts 页面，包括置顶与 repost。
- `x_get_post`：读取单条帖子的完整可见正文。

示例请求：

> 在 X 搜索最近 3 天有关 Gemini 3.5 Pro、DeepSeek R2、Grok 5 和下一代 Llama 的爆料，返回可信度最高的 5 条并附原帖链接。

Agent 可调用：

```json
{
  "query": "(\"Gemini 3.5 Pro\" OR \"DeepSeek R2\" OR \"Grok 5\" OR \"next Llama\") (leak OR rumor OR spotted OR soon)",
  "since": "2026-07-08",
  "limit": 10,
  "response_format": "json"
}
```

## X Watchlist 增量采集（Milestone 1）

Python 编排层通过 MCP 串行调用现有 X 工具，**分页抓取直到越过 72 小时窗口**（或达到安全页数上限），技术去重后按发布时间倒序保留窗口内帖子。默认**不按账号硬截断 10 条**（Top 20 由 M2 排序决定）。Coverage 区分 `fetch_returned_empty` 与 `empty_window`。设计说明见 `docs/x-source-collection-design.md`。

MCP 在单次采集进程内**复用同一个 Chrome 会话**（仍串行翻账号，避免多开 profile / 提高封号风险）；预计可减少每次工具调用的冷启动开销。

`x-clean-posts/v1` 在保持原有必填字段的同时，增加可选上下文字段：`social_context`、`watchlist_handle`、`has_media`、`media`、`link_card_title`、`likely_media_only`、完善的 `quoted_post`。

### 安装

```powershell
pip install -e ".[dev]"
```

### 采集

```powershell
# 干跑：只加载 watchlist 并写 run 骨架，不调用 MCP
python -m app.cli x-watchlist collect --dry-run

# 正式采集（默认窗口：现在往前 72 小时 ~ 现在）
python -m app.cli x-watchlist collect

# 指定账号
python -m app.cli x-watchlist collect --handles OpenAI,thsottiaux,LuminaXspace
```

产物目录：`data/x_watchlist_runs/<run_id>/`（`run.json`、`raw_posts.json`、`clean_posts.json`、`coverage.json` 等）。游标：`data/x_watchlist_cursors.json`。

### 测试

```powershell
python -m pytest
```

## Editorial 编辑层（Milestone 2）

读取 `x-clean-posts/v1`，通过**一次** LLM 调用做逐条解析 + 全局精选排序，输出 `editorial-picks/v2`（完整排名 + Top 20）。

M2 是 **AI 前沿精选排序器**，不是事件聚合器：每条输入帖子都参与解析与排名；不使用 `keep/discard/merge`；不做通用语义去重（仅允许同 Thread / 完全重复转发 / 机械拆帖的轻量整理）。

```powershell
# 离线 dry-run（确定性 mock，不调 API）
python -m app.cli editorial run --dry-run

# 真实 LLM（需要 CONNOR_LLM_API_KEY / DEEPSEEK_API_KEY）
python -m app.cli editorial run --input fixtures/m1_golden_run/clean_posts.json
```

产物：`data/editorial_runs/<run_id>/picks.json` + `editorial_trace.json`（+ 可选 `reasoning.txt`）。

- 默认 Prompt：`app/editorial/prompts/v2_editorial_system.md`
- 历史 Prompt（事件聚合，仅用于解释旧 Run）：`v1_editorial_system.md` / schema `editorial-events/v1`

## Daily Agent（Milestone 3a+）

冻结规格见 [`docs/agent-design.md`](docs/agent-design.md)（Connor Daily Agent Specification v1）。

M3a 已落地：PostgreSQL schema、Redis 工作游标（无 TTL）、PG advisory run lock、文件游标导入、薄 LangGraph 主图。

M3b 已落地：`cursor_eligible`（裸 Repost/置顶不可作锚点）、精确命中旧游标停止、72h/`known_data_gap`、账号级 persist + cursor outbox → Redis、collection/cursor_sync gate。

M3c 已落地：`run_posts` 候选冻结 / `requeue_candidates`、版本化 `post_summaries`（≤100 字中文摘要 Prompt v1）、mock/真实 LLM 摘要、`summary_gate`（终态或显式 `accept_partial`）。

M3d 已落地：全量 `post_evaluations`（绑定 `summary_id`）、`evaluation_gate`、确定 Top K、Editorial Top≤20 → `selection_items`（`publication_status=unpublished`，入选≠发布）。

M3e 已落地：Memory/Postgres Checkpointer、生产 `start`/`resume`（advisory lock + run 状态机）、cron `tick` 调度窗口、metrics/告警 webhook、只读 FastAPI（`/runs` `/selection` `/evaluations`）。

```powershell
# 生产 dry 启动（写 PG run 行 + checkpoint；不跑 live LLM）
python -m app.cli daily run --no-lock

# 到点窗口内触发（默认 08:00 Asia/Shanghai，可用环境变量改）
python -m app.cli daily tick --force

# 恢复暂停 run
python -m app.cli daily resume --run-id <uuid> --accept-partial

# 只读 API
python -m app.cli daily serve-api --port 8080
```

```powershell
pip install -e ".[dev]"

# 薄主图 dry-run（不访问 X / 不强制 DB）
python -m app.cli daily dry-run

# 确保专用库 + 创建 PG 表（默认 connor_daily，避免与旧 connor.runs 冲突）
python scripts/ensure_daily_db.py
python -m app.cli daily init-db

# 导入 data/x_watchlist_cursors.json → Redis（需要 CONNOR_REDIS_URL）
python -m app.cli daily import-cursors

# 本地全流程 debug（golden seed → summarize → evaluate → select → dry graph）
python scripts/debug_daily_e2e.py
```

环境变量：`CONNOR_DATABASE_URL`（默认 `.../connor_daily`）、`CONNOR_REDIS_URL`（可选覆盖 watchlist / cursor 路径）。Redis 未启动时 cursor sync 可跳过，dry e2e 仍可跑通。

## 安全与限制

- 本工具只读，不点赞、不关注、不转发、不发帖。
- 不要同时打开两份专用 profile；Chrome 会锁定 profile 目录。
- 请控制调用频率并遵守 X 的服务条款。网页结构变化时可能需要更新选择器。
- 更稳健的生产方案是配置官方 X API；这个浏览器后端适合个人、本地、低频的信息检索。

## 登录错误诊断

`x_session_status` 和所有依赖登录的工具会返回稳定的 `reason_code`，包括：

- `google_oauth_incomplete`：Google OAuth 尚未完成回跳。
- `x_sso_onboarding_stuck`：X 的 SSO onboarding 空白或卡住。
- `auth_cookie_missing`：登录 cookie 没有落盘。
- `session_cookie_rejected`：cookie 存在，但被 X 拒绝。
- `x_security_challenge`：需要人工验证码、手机、邮箱或身份验证。
- `x_account_restricted`：账号被锁定、冻结或限制。
- `x_rate_limited`：X 对会话或网络限流。
- `x_service_error`：X 服务端或通用页面错误。
- `x_page_load_failed`：页面未加载出登录或账号界面。
- `browser_profile_locked`：专用 Chrome 窗口仍在占用 profile。
- `network_error` / `browser_timeout`：网络或浏览器超时。

诊断只返回 `auth_token`、`ct0` 是否存在，不会读取或输出其值。
