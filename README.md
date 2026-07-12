# Connor

X 信息源采集项目：本地 MCP 服务（TypeScript）+ Watchlist 增量编排（Python）。

仓库：https://github.com/caojiajun777/Connor

## 项目结构

```text
src/                 # X News MCP server（Playwright + 持久 Chrome profile）
app/x_watchlist/     # Python 采集编排：MCP client / cleaner / cursors / runner
config/              # x_watchlist.yaml 账号清单
tests/x_watchlist/   # Python 单元测试
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

Python 编排层通过 MCP 串行调用现有 X 工具，按账号 watchlist 增量采集并落盘。

### 安装

```powershell
pip install -e ".[dev]"
```

### 采集

```powershell
# 干跑：只加载 watchlist 并写 run 骨架，不调用 MCP
python -m app.cli x-watchlist collect --dry-run

# 正式采集（默认窗口：昨天 00:00 ~ 今天 00:00，本地时区）
python -m app.cli x-watchlist collect

# 指定账号与窗口
python -m app.cli x-watchlist collect --handles OpenAI,thsottiaux,LuminaXspace --since 2026-07-11T00:00:00+08:00 --until 2026-07-12T00:00:00+08:00
```

产物目录：`data/x_watchlist_runs/<run_id>/`（`run.json`、`raw_posts.json`、`clean_posts.json`、`coverage.json` 等）。游标：`data/x_watchlist_cursors.json`。

### 测试

```powershell
python -m pytest
```

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
