# Connor.ai 公开网站

公开用户站（`web/`）与内部 Console（`frontend/`）分离。公开站只展示 `publication_status=published` 的日报。

## 架构

```text
Watchlist → collect → translate → evaluate → select
  → write-report (event packages → Writer → DailyReport draft)
  → download selected media (PostMedia → ready)
  → publish-report
  → GET /api/public/reports*
  → Next.js web/ (/, /archive, /daily/[date], /about)
```

核心表：`daily_reports`、`daily_report_items`、`post_media`、`posts`、`post_summaries`。  
`post_summaries` 仍是忠实翻译，只作来源卡引用，不再充当日报正文。  
Writer 产出 `title` / `lead`（存 `overview`）/ `body_sections`；事件包存 `event_packages`。图片走 `post_media.storage_url`。

Schema：`python -m app.cli daily init-db`（`create_all` + 少量 additive columns；尚无 Alembic）。

## 本地启动

```powershell
python -m app.cli daily serve-api --port 8080
cd web
npm run dev
```

- 公开站：http://127.0.0.1:3000  
- API：http://127.0.0.1:8080/api/public/reports  
- Console 仍为 http://127.0.0.1:5173/console  

## 发布流程

1. 完成 daily 生产 run（含 selection 与忠实翻译）。
2. `write-report --run-id … --date YYYY-MM-DD`  
   - 先把入选帖整理为带事实引用的事件包，再由独立 Writer 写标题、导语与分层正文。  
   - 无 LLM 时可用 `--dry-run`（mock packager/writer）。  
   - 手动壳子 `create-report-draft` 仍可用，但发布前仍需 `write-report --report-id …` 补齐 `event_packages` / `body_sections`。
3. `publish-report --report-id …`（默认下载入选图片；失败可用 `--accept-partial-media`）
4. 公开 API / 网站：叙事正文在前，帖子卡片在「来源」区（原文 + 忠实翻译）。

## 定时发布

每天 **北京时间 06:00** 由 Windows 计划任务 `ConnorDailyPublish` 唤醒机器并跑全链路：

`collect → summarize → evaluate → select → write-report → publish-report`

- 注册：`powershell -ExecutionPolicy Bypass -File scripts/register_connor_daily_task.ps1`
- 手动试跑：`powershell -ExecutionPolicy Bypass -File scripts/run_daily_and_publish.ps1`
- 或：`python -m app.cli daily publish-today`
- 多日补跑：`python scripts/daily_and_publish.py --dates 2026-07-18,2026-07-19,2026-07-20 --accept-gap`
- 日志：`data/logs/`（`task_wrapper_*.log` + `daily_publish_*.log`）
- 触发：每天 **06:00 / 07:00 / 09:00**（已发布则跳过），以及登录后约 3 分钟补跑。
- 启动器会在唤醒后 settle 约 45 秒，并最多等 Redis/Docker ~180 秒。
- 要求：机器可睡眠/待机，但不要关机；保持当前 Windows 用户登录（采集依赖浏览器会话）；Docker Desktop 开机自启（Redis 容器 `task-redis`）。

已发布日报默认不可原地覆盖；需 `withdraw-report` 后再处理。

## 环境变量

| 变量 | 用途 |
|------|------|
| `CONNOR_PUBLIC_API_BASE` | Next 服务端拉取 API（默认 `http://127.0.0.1:8080`） |
| `CONNOR_PUBLIC_SITE_URL` | canonical / sitemap（生产必须设真实 HTTPS） |
| `CONNOR_PUBLIC_USE_FIXTURE` | `1` 时用 fixture（**生产会被忽略**） |
| `CONNOR_OPS_API_KEY` | 保护 `/api/public/ops/*`、`/api/console/*`、`/runs*`；未设时仅允许本机 |
| `CONNOR_CORS_ORIGINS` | 额外 CORS 源（逗号分隔）；会自动并入 `CONNOR_PUBLIC_SITE_URL` |
| `CONNOR_MEDIA_STORAGE` | `local` 或 `s3` |
| `CONNOR_MEDIA_PUBLIC_BASE_URL` | 媒体 URL 前缀（本地默认 **`/media`** 同源；S3/R2 须绝对 HTTPS） |
| `CONNOR_MEDIA_LOCAL_ROOT` | 本地媒体目录（默认 `data/public_media`） |
| `CONNOR_MEDIA_S3_*` | bucket / endpoint / region / prefix |
| `VITE_CONNOR_OPS_API_KEY` | Console 前端发送的 ops key（与上面一致） |

生产注意：

1. 设置 `CONNOR_OPS_API_KEY`，勿把 API 以 `0.0.0.0` 裸奔公网而不鉴权。  
2. 媒体默认写入相对 `/media/...`，由 Next rewrite 到 FastAPI；换 CDN 时改 `CONNOR_MEDIA_PUBLIC_BASE_URL` 并**重新下载/发布**已有日报。  
3. `publish` 会在媒体下载后刷新 digest 图片 URL。  
4. 定时发布默认 **不** `accept_partial_media`；失败需人工处理或显式传参。

## 测试

```powershell
python -m pytest tests/daily/test_public_reports.py tests/daily/test_report_writing.py -q
cd web
npm test
npm run build
```

## 下架

- `posts.visibility_status` / `post_media.visibility_status`：隐藏后公开 API 不返回原文与媒体，卡片显示克制占位，仍保留作者与原帖链接。
- `daily_reports.publication_status=withdrawn`：整期对公开用户表现为不存在。

## 美术资产

首页 `public/connor/*.svg` 为原创抽象仿生人占位层，可替换为正式插画而无需改交互代码。禁止使用《底特律：变人》等受版权保护的角色资产。
