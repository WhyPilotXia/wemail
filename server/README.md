# WeMail UDP 后端

该服务替代微信云函数、云数据库和云存储，监听 `118.31.105.6:18500/UDP`。SQLite 是小程序实时访问的数据源，Notion 作为后台同步目标，不参与前台请求链路。

## 架构

- 小程序使用 `wx.createUDPSocket`，请求超时后使用相同请求 ID 自动重传，服务端以幂等缓存避免重复写入。
- 联系人与信件定时从 Notion 拉取到 SQLite；默认每 5 分钟同步一次。
- 寄信和签收先写入 SQLite 与 Outbox，立即响应小程序，再由后台线程可靠写入 Notion。
- Notion 暂时不可用时，前台仍可读取本地镜像；待写任务按指数退避自动重试。
- 业务包采用紧凑 JSON，避免 Base64 约 33% 的体积膨胀和加解密 CPU 开销。
- 响应超过 4KB 时才尝试 gzip，并且只在压缩后实际更小时启用；小响应不压缩。
- 请求和响应使用约 900B 的 MTU 安全分片，支持组包、超时重试和请求 ID 幂等缓存。
- `wx.login` code 由服务器向微信 `jscode2session` 换取可信 OpenID。
- 手机号 code 由服务器调用微信 `getuserphonenumber`，联系人及个人资料使用完整手机号。
- 用户、活动、报名、阅读进度保存在 `wemail.db`；头像压缩后保存在 SQLite。
- Notion Token 和 AppSecret 只存服务器 `.env`，不会写入客户端或提交仓库。
- 服务日志同时输出到控制台和 `logs/wemail-server.log`，单文件 5MB，保留 5 份。

## Windows 部署

复制整个 `server` 目录到服务器，例如：

```powershell
C:\Users\Administrator\Documents\wemail-server
```

复制配置模板：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，必须填写：

```text
WECHAT_APP_SECRET=微信公众平台中的小程序AppSecret
NOTION_TOKEN=现有NotionToken
```

`WECHAT_APP_SECRET` 位于微信公众平台“开发管理 → 开发设置 → 开发者 ID”；`NOTION_TOKEN` 由 Notion Integration 提供。两者只写入被 Git 忽略的 `server/.env`，不要提交或发送给他人。其余运行参数均已在 `.env.example` 中提供可复现默认值，可按部署环境调整。

启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

服务仅使用 Python 标准库，无需安装第三方包。看到以下日志即启动成功：

```text
WeMail UDP server listening on 0.0.0.0:18500
```

安装开机自启：

```powershell
powershell -ExecutionPolicy Bypass -File .\install-service.ps1
```

防火墙放行：

```powershell
New-NetFirewallRule -DisplayName "WeMail UDP 18500" -Direction Inbound -Protocol UDP -LocalPort 18500 -Action Allow
```

云安全组也必须放行 `UDP 18500`。

## 旧云数据迁移

从云开发控制台分别导出以下集合为 JSON 或 JSONL：

- `users`
- `events`
- `event_entries`
- `reading_progress`

复制到服务器后执行：

```powershell
py import_cloudbase.py --users users.json --events events.json --entries event_entries.json --reading reading_progress.json
```

导入前请先备份 `wemail.db`。重复导入按原 `_id` 覆盖，不会创建重复活动或进度。

## 备份

手动备份：

```powershell
py backup.py
```

建议用 Windows 任务计划程序每天运行一次。备份输出在 `server/backups/`。

## 自动测试

Windows 上运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\run-tests.ps1
```

测试代码位于 `server/tests/`，覆盖 SQLite 用户/会话/活动/阅读进度、UDP Echo、分片组包和自适应 gzip。

## 验证顺序

1. 在“我的 → 设置”运行 UDP 测试。
2. 重新进入“我的”，应能用 `wx.login` 建立会话并读取资料。
3. 修改昵称和地址，退出重进确认保存。
4. 选择头像，确认退出重进仍显示。
5. 手机号授权并匹配 Notion 联系人。
6. 检查通讯录、信件列表、寄信、签收。
7. 创建活动、第二个账号参与、发起人开奖。
8. 阅读小说并检查跨设备进度。

## 安全与限制

UDP 本身没有 TCP 的可靠性，本实现通过分片、重试和幂等降低风险，但移动网络切换和 NAT 仍可能造成短时失败。按低流量、低 CPU 优先的要求，业务包使用明文紧凑 JSON；会话令牌、时间窗和限流只能降低伪造与重放风险，不能防止链路窃听。不要在日志中打印原始数据包。以后具备备案域名时，应迁移到 HTTPS，同时可保留同一套 Python 业务和 SQLite 数据层。
