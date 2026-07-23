# 本机 + Cloudflare Tunnel 部署

**生产站点：** https://aiconnor.cn（`www.aiconnor.cn` 同指向）  
**形态：** 本机 Windows 跑 FastAPI + Next；Cloudflare Tunnel 提供公网 HTTPS。不用 Cloudflare Pages（站点依赖本机 API）。

```text
访客 → Cloudflare (HTTPS / DNS)
         → cloudflared (tunnel: connor-public)
              → 127.0.0.1:3000  Next.js 公开站
                   ├ rewrite /api/*   → 127.0.0.1:8080 FastAPI
                   └ rewrite /media/* → 127.0.0.1:8080 本地媒体
```

API **只绑** `127.0.0.1:8080`，不单独暴露到 Cloudflare。

---

## 当前生产配置（已落地）

| 项 | 值 |
|----|-----|
| 域名注册商 | 阿里云 |
| DNS / CDN | Cloudflare（Full setup，NS 已切到 CF） |
| Cloudflare nameservers（示例，以 Dashboard 为准） | `hans.ns.cloudflare.com` / `savanna.ns.cloudflare.com` |
| 公网 URL | `https://aiconnor.cn`、`https://www.aiconnor.cn` |
| Tunnel 名 | `connor-public` |
| Tunnel UUID | `06a87df1-eb18-40a9-8d24-00094cd03733` |
| 本机 Next | `127.0.0.1:3000` |
| 本机 API | `127.0.0.1:8080` |
| 媒体 | 相对路径 `/media/...`（Next rewrite → FastAPI） |
| 代码仓库 | GitHub `caojiajun777/Connor`（仅源码；不部署到 Pages） |

### 本机 Tunnel 配置文件

路径：`%USERPROFILE%\.cloudflared\config.yml`

```yaml
tunnel: 06a87df1-eb18-40a9-8d24-00094cd03733
credentials-file: C:\Users\<你>\.cloudflared\06a87df1-eb18-40a9-8d24-00094cd03733.json

ingress:
  - hostname: aiconnor.cn
    service: http://127.0.0.1:3000
  - hostname: www.aiconnor.cn
    service: http://127.0.0.1:3000
  - service: http_status:404
```

凭证 JSON 与 `cert.pem` 在 `%USERPROFILE%\.cloudflared\`，**勿提交 Git**。

### 用户环境变量（本机已设）

```text
CONNOR_PUBLIC_SITE_URL=https://aiconnor.cn
CONNOR_PUBLIC_API_BASE=http://127.0.0.1:8080
CONNOR_MEDIA_PUBLIC_BASE_URL=/media
CONNOR_OPS_API_KEY=<本机长随机密钥，User 环境变量>
```

另需日常采集/写报已有的：`CONNOR_DATABASE_URL`、`CONNOR_REDIS_URL`、LLM key。参考仓库根目录 `.env.example`。

---

## 从零复现（一次性）

### 1. 域名

1. 在注册商（如阿里云）购买域名。  
2. Cloudflare → **Add a site** → 选 Free → DNS 扫描到 0 条也可直接 **继续前往激活**（不要手填家里 IP）。  
3. 在注册商把 **DNS 服务器** 改成 Cloudflare 给的两行 NS（阿里云：域名管理 → 修改 DNS 服务器 → 自定义；**不要**用「快速添加解析」）。  
4. 等 Cloudflare 域名状态 **Active**。

### 2. 安装 cloudflared

```powershell
# 示例：放到用户目录并加入 PATH
$dir = "$env:LOCALAPPDATA\cloudflared"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" `
  -OutFile "$dir\cloudflared.exe" -UseBasicParsing
```

### 3. 登录并建 Tunnel

```powershell
cloudflared tunnel login
# 浏览器授权，选中 aiconnor.cn

cloudflared tunnel create connor-public
cloudflared tunnel route dns --overwrite-dns connor-public aiconnor.cn
cloudflared tunnel route dns --overwrite-dns connor-public www.aiconnor.cn
```

DNS 会出现指向 tunnel 的 **CNAME**（根域名与 `www`）。不要再在阿里云添加 A 记录。

也可用仓库脚本（登录成功后）：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_cloudflare_tunnel.ps1
powershell -ExecutionPolicy Bypass -File scripts/go_live_checklist.ps1
```

---

## 日常启动（生产）

需要同时在线：

1. Postgres + Redis（如 Docker `task-redis`）  
2. FastAPI：`python -m app.cli daily serve-api --host 127.0.0.1 --port 8080`  
3. Next：`cd web && npm run build && npm run start -- -p 3000 -H 127.0.0.1`  
4. Tunnel：`cloudflared tunnel run connor-public`

或：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_public_stack.ps1
# 另开窗口：
cloudflared tunnel run connor-public
```

**关机 / 杀进程后公网不可访问。** 机器可睡眠，但不要长期关机；日报计划任务照旧。

### 建议：tunnel 装成 Windows 服务

```powershell
cloudflared service install
# 读取 %USERPROFILE%\.cloudflared\config.yml
```

服务负责 tunnel；你仍需保证 `:3000` 与 `:8080` 在跑。

### Next 构建注意

生产用 **`npm run build`（webpack）**，不要用混了 turbopack 的半残 `.next`。若出现  
`Cannot find module '../chunks/ssr/[turbopack]_runtime.js'`：

```powershell
cd web
Remove-Item -Recurse -Force .next
npm run build
npm run start -- -p 3000 -H 127.0.0.1
```

---

## 验收清单

- [ ] https://aiconnor.cn/ 首页两屏、日报、CTA  
- [ ] https://aiconnor.cn/archive  
- [ ] 图片为 `/media/...` 且可打开  
- [ ] https://aiconnor.cn/api/public/meta 返回 JSON  
- [ ] 未带 key 的 `POST /api/public/ops/...` → 401  
- [ ] Console（`:5173`）仅本机，不进 Tunnel  

---

## 为何不用 Pages

公开站是 Next **服务端动态渲染**（`force-dynamic`），并 rewrite 到本机 FastAPI。Pages 边缘访问不到 `127.0.0.1:8080`。GitHub 只作代码托管；公网流量走 Tunnel → 本机。

相关文档：[公开站](./public-site.md)、脚本 `scripts/run_public_stack.ps1` / `scripts/setup_cloudflare_tunnel.ps1`。
