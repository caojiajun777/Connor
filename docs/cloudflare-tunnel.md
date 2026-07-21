# 本机 + Cloudflare Tunnel 上线

本机跑 FastAPI + Next，用 Cloudflare Tunnel 把 `https://你的域名` 指到本机 `:3000`。API 只绑 `127.0.0.1`，不直接暴露公网。

```text
访客 → Cloudflare (HTTPS) → cloudflared → 本机 :3000 (Next)
                                         ├ /api/*  → :8080
                                         └ /media/* → :8080
```

## 前置

1. 域名已接入 Cloudflare（NS 指向 Cloudflare）。
2. 已安装 [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/)。
3. 本机已能本地打开公开站（`npm run build && npm run start` + `serve-api`）。

## 一次性：登录并建 Tunnel

```powershell
cloudflared tunnel login
cloudflared tunnel create connor-public
```

记下输出的 Tunnel UUID。在 Cloudflare Dashboard → Zero Trust → Networks → Tunnels 里也能看到。

把域名接到 tunnel（把 `你的域名` 换成真实域名）：

```powershell
cloudflared tunnel route dns connor-public 你的域名
```

在 `%USERPROFILE%\.cloudflared\config.yml` 写（UUID / 凭证路径按本机实际改）：

```yaml
tunnel: <TUNNEL_UUID>
credentials-file: C:\Users\<你>\.cloudflared\<TUNNEL_UUID>.json

ingress:
  - hostname: 你的域名
    service: http://127.0.0.1:3000
  - service: http_status:404
```

## 本机环境变量（生产）

启动前设好（可写进用户环境变量，或下面的启动脚本）：

```powershell
$env:CONNOR_PUBLIC_SITE_URL = "https://你的域名"
$env:CONNOR_PUBLIC_API_BASE = "http://127.0.0.1:8080"
$env:CONNOR_MEDIA_PUBLIC_BASE_URL = "/media"
$env:CONNOR_OPS_API_KEY = "<长随机密钥>"
# 另需: CONNOR_DATABASE_URL / CONNOR_REDIS_URL / LLM key
```

## 日常启动顺序

1. Postgres + Redis（Docker `task-redis`）  
2. FastAPI：`python -m app.cli daily serve-api --host 127.0.0.1 --port 8080`  
3. Next：`cd web; npm run start`（先 `npm run build`）  
4. Tunnel：`cloudflared tunnel run connor-public`

或直接：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_public_stack.ps1
```

（脚本会起 API + Next；tunnel 建议用 Windows 服务常驻，见下。）

## 建议：cloudflared 装成 Windows 服务

```powershell
cloudflared service install
# 服务会读 %USERPROFILE%\.cloudflared\config.yml
```

开机后 tunnel 自动在线；你只需保证本机 `:3000` / `:8080` 在跑。

## 上线验收

- `https://你的域名/` 首页两屏、日报、归档正常  
- 图片地址为 `/media/...` 且能打开  
- 未带 key 调 `POST /api/public/ops/...` → 401  
- 机器睡眠可，但别关机；计划任务继续跑日报

## 注意

- Tunnel 只转到 Next；**不要**把 `:8080` 单独暴露到 Cloudflare。  
- 改 `CONNOR_MEDIA_PUBLIC_BASE_URL` 后，旧日报里的绝对 URL 需重新 publish。  
- Console（`:5173`）继续只本机访问，勿接到 Tunnel。
