$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".env")) {
  Write-Error "缺少 server\.env，请复制 .env.example 并填写 WECHAT_APP_SECRET 和 NOTION_TOKEN。"
}
py wemail_udp_server.py
