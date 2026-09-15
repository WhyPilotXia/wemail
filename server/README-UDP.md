# UDP Echo 测试服务

## 启动

Windows 服务器安装 Python 3 后，在脚本目录运行：

```powershell
py udp_echo_server.py
```

默认监听所有 IPv4 网卡的 UDP `18500` 端口。也可显式指定：

```powershell
py udp_echo_server.py --host 0.0.0.0 --port 18500
```

## 放行 Windows 防火墙

以管理员身份打开 PowerShell，执行：

```powershell
New-NetFirewallRule -DisplayName "WeMail UDP 18500" -Direction Inbound -Protocol UDP -LocalPort 18500 -Action Allow
```

如果服务器由云厂商提供，还要在云控制台安全组中添加入站规则：协议 `UDP`，端口 `18500`。测试阶段可临时允许来源 `0.0.0.0/0`，验证完成后应按实际方案收紧。

## 检查监听

```powershell
Get-NetUDPEndpoint -LocalPort 18500
```

服务窗口收到小程序数据后会打印客户端地址、数据长度和内容，并把原始数据原样返回。

## 小程序测试

打开小程序“我的”页，点击“测试 UDP 服务器”。成功时页面显示：

- UDP 收发成功
- 本地随机端口
- 响应来源 `118.31.105.6:18500`
- 往返耗时
- 完整 Echo 内容

应使用真机和体验版分别测试。开发者工具中的网络行为不能替代正式环境验证。
