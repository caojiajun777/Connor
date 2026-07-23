# Connor

[![GitHub](https://img.shields.io/github/repo/caojiajun777/Connor)](https://github.com/caojiajun777/Connor)

**Connor** 是一套 AI 前沿资讯自动化日报系统：从 X（Twitter）curated watchlist 采集一手信息，经 LLM 翻译、评分、编辑筛选后生成中文日报，发布至 [**aiconnor.cn**](https://aiconnor.cn)，并可选产出竖屏短视频。

> 完整中文项目报告：[docs/project-report-zh.md](docs/project-report-zh.md)

---

## 架构一览

```
X Watchlist (YAML)
       │
       ▼
┌──────────────┐    ┌─────────────────────────────────────────┐
│  MCP Server  │───▶│  Daily Agent (Python / LangGraph / PG)   │
│  Node + TS   │    │  采集 → 摘要 → 评估 → 筛选 → 写报 → 发布    │
│  Playwright  │    └──────────┬──────────────────┬────────────┘
└──────────────┘               │                  │
                               ▼                  ▼
                    ┌──────────────────┐  ┌───────────────┐
                    │  Console (Vite)  │  │  Web (Next.js) │
                    │  内部标注 / 运维  │  │  公开日报网站   │
                    └──────────────────┘  └───────────────┘
```

| 组件 | 路径 | 说明 |
|------|------|------|
| X MCP 服务 | `src/` → `dist/` | Playwright 只读采集，独立 Chrome Profile |
| Daily Agent | `app/daily/` | LangGraph 编排 · PostgreSQL · Redis 游标 |
| Watchlist 编排 | `app/x_watchlist/` | MCP 客户端 · 清洗 · 游标 · 独立 M1 采集 |
| 内部 Console | `frontend/` | React 19 · 标注 · 分析 · Run 管理 |
| 公开网站 | `web/` | Next.js 15 · aiconnor.cn |
| 短视频 | `short_video/` + `app/daily/short_video/` | Remotion · edge-tts |
| 账号配置 | `config/x_watchlist.yaml` | ~125 个 AI 官方/员工/分析师账号 |

---

## 快速开始

### 前置依赖

- **Python 3.11+** · **Node 20+** · **PostgreSQL 18** · **Docker Desktop**（Redis）
- **Chrome**（专用 Profile，首次需手动登录 X）
- **DeepSeek API Key**（或其他 OpenAI 兼容 LLM）

### 1. 安装

```powershell
# Python
pip install -e ".[dev]"

# MCP 服务
pnpm install && pnpm run build

# 前端（按需）
cd frontend && npm install
cd ../web && npm install
```

### 2. 配置

```powershell
copy .env.example .env
# 编辑 .env：CONNOR_DATABASE_URL / CONNOR_LLM_API_KEY / CONNOR_OPS_API_KEY 等
```

```powershell
python scripts/ensure_daily_db.py
python -m app.cli daily init-db
python -m app.cli daily import-cursors   # 需要 Redis
```

### 3. X 登录（首次）

```powershell
pnpm run login
```

在弹出的专用 Chrome 窗口完成 X 登录后**手动关闭窗口**；会话保存在 `~/.codex-x-news-agent`。

### 4. 启动服务

```powershell
# API（公开站 + Console 共用）
python -m app.cli daily serve-api --port 8080

# 内部 Console → http://127.0.0.1:5173/console
cd frontend && npm run dev

# 公开站 → http://127.0.0.1:3000
cd web && npm run dev
```

---

## 每日自动流水线

北京时间 **06:00** 自动开跑，**12:00** 前完成 aiconnor.cn 更新：

| 时段 | 动作 |
|------|------|
| 06:00 | 主采集（125 账号，fail-fast） |
| 06:00–10:30 | Auto-retry 失败账号（每 10 分钟） |
| 10:30 | 停止 retry，进入写报 |
| 10:30–12:00 | 摘要 → 评估 → 筛选 → 写报 → 发布 |

### 注册计划任务

```powershell
powershell -File scripts\register_connor_daily_task.ps1      # ConnorDailyPublish
powershell -File scripts\register_connor_public_stack_task.ps1  # 公开站栈
```

手动触发：`schtasks /Run /TN ConnorDailyPublish`

### 手动跑今日全流程

```powershell
python -m app.cli daily publish-today --split-by-day --accept-gap
# 或
powershell -File scripts\run_daily_and_publish.ps1
```

---

## CLI 参考

### X Watchlist 采集（M1）

```powershell
python -m app.cli x-watchlist collect [--dry-run] [--handles OpenAI,DeepSeek]
python -m app.cli x-watchlist audit-accounts [--all | --stale | --handles ...]
```

### Daily Agent

```powershell
python -m app.cli daily dry-run                          # 薄主图，不访问 X
python -m app.cli daily run --live                       # 生产采集 + LLM
python -m app.cli daily publish-today [--force]          # 采集→写报→发布
python -m app.cli daily retry-collect --latest --until-done
python -m app.cli daily resume --run-id <UUID>
python -m app.cli daily serve-api --port 8080
```

### 写报 / 发布（分步）

```powershell
python -m app.cli daily write-report --run-id <UUID> --date 2026-07-23
python -m app.cli daily publish-report --report-id <UUID>
python -m app.cli daily withdraw-report --report-id <UUID>
```

### 短视频

```powershell
pip install -e ".[short_video]"
python -m app.cli daily produce-short-video --report-date 2026-07-23
```

### Editorial（M2 离线，legacy）

```powershell
python -m app.cli editorial run --dry-run
python -m app.cli editorial run --input fixtures/m1_golden_run/clean_posts.json
```

---

## MCP 工具

Codex / MCP 客户端可调用：

| 工具 | 用途 |
|------|------|
| `x_session_status` | 登录诊断（结构化 reason_code） |
| `x_search_posts` | Latest 搜索 + 分页 |
| `x_profile_posts` | 账号 Posts 页 |
| `x_get_post` | 单帖详情 |

项目已含 `.codex/config.toml`；构建并登录后重启 Codex 即可。

---

## 环境变量

详见 [`.env.example`](.env.example)。核心项：

```ini
# 数据库
CONNOR_DATABASE_URL=postgresql+psycopg://connor:connor@localhost:5432/connor_daily
CONNOR_REDIS_URL=redis://127.0.0.1:6379/0

# LLM
CONNOR_LLM_API_KEY=sk-...

# 公开站
CONNOR_PUBLIC_SITE_URL=https://aiconnor.cn
CONNOR_OPS_API_KEY=<long-random-secret>

# 采集 / 调度
CONNOR_COLLECT_AUTO_RETRY=1
CONNOR_COLLECT_RETRY_INTERVAL_SEC=600
CONNOR_PUBLISH_DEADLINE_HOUR=12
CONNOR_PUBLISH_DEADLINE_RESERVE_MIN=90
X_AGENT_PROFILE_DIR=C:\Users\<you>\.codex-x-news-agent
```

---

## 测试

```powershell
python -m pytest                    # Python 全量
pnpm test                           # MCP TypeScript
cd web && npm test                  # 公开站 Vitest
python scripts/smoke_daily_pipeline.py
```

---

## 文档

| 文档 | 内容 |
|------|------|
| [docs/project-report-zh.md](docs/project-report-zh.md) | **中文项目报告**（架构 · 链路 · 状态） |
| [docs/agent-design.md](docs/agent-design.md) | Daily Agent 规格 v1 |
| [docs/x-source-collection-design.md](docs/x-source-collection-design.md) | 采集层设计 |
| [docs/public-site.md](docs/public-site.md) | 公开站运维 |
| [docs/cloudflare-tunnel.md](docs/cloudflare-tunnel.md) | Cloudflare Tunnel |
| [docs/console-development-plan.md](docs/console-development-plan.md) | Console 规划 |
| [web/README.md](web/README.md) | 公开站前端 |

---

## 项目结构

```text
Connor/
├── src/                    # X MCP 服务 (TypeScript)
├── app/
│   ├── x_watchlist/        # M1 采集编排
│   ├── editorial/          # M2 离线编辑 (legacy)
│   └── daily/              # M3+ Daily Agent
│       ├── collect_loop.py / retry_failed_collect.py
│       ├── report_writing/ / public/ / console/
│       ├── short_video/    # 短视频 Python 编排
│       ├── production.py   # 生产入口
│       └── daily_publish.py
├── config/x_watchlist.yaml
├── frontend/               # Console (Vite + React)
├── web/                    # 公开站 (Next.js)
├── short_video/            # Remotion 模板
├── scripts/                # 运维脚本
├── tests/                  # pytest
└── docs/                   # 设计文档
```

---

## 安全与合规

- MCP 服务**只读**，不点赞/关注/转发/发帖
- 不要同时打开两份专用 Chrome Profile
- 控制调用频率，遵守 X 服务条款
- 生产环境**必须**设置 `CONNOR_OPS_API_KEY`
- `.env` 已 gitignore，勿提交密钥

---

## License

Private project. All rights reserved.
