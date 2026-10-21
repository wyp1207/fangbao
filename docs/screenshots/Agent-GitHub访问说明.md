# Agent GitHub 网络与 Git 访问说明

验证日期：2026-10-21（Asia/Shanghai）

## 结论

本机可以访问 GitHub，但必须使用本地 HTTP 代理 `http://127.0.0.1:9876`。当前环境不能直连 GitHub。

Git 访问 GitHub 时还需要额外指定 OpenSSL：

```text
http.sslBackend=openssl
```

否则 Git 默认使用的 Windows Schannel 后端会报：

```text
schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS (0x8009030e)
```

以下公开访问均已实测成功：

- `github.com` 网页：HTTP 200
- `api.github.com`：HTTP 200
- `raw.githubusercontent.com`：HTTP 200
- `codeload.github.com` 归档下载：HTTP 200
- Git `ls-remote`：成功读取远端引用
- Git 浅克隆 `https://github.com/octocat/Hello-World.git`：成功

## 当前环境中的关键事实

1. Codex 进程继承的代理环境变量可能被设为 `127.0.0.1:9`。这是不可用的占位地址，不是有效 VPN 代理。
2. 有效代理端口是 `127.0.0.1:9876`，当前正在监听。
3. 系统 PAC 地址为 `http://127.0.0.1:9876/proxy`；HTTP、HTTPS、WS、WSS 走代理，内网地址直连。
4. Git 版本为 `2.53.0.windows.2`，系统级配置默认使用 Schannel。
5. 全局 Git 配置会将 `git@github.com:` 重写为 `https://github.com/`。因此优先使用 HTTPS 地址。

不要假设代理端口或状态永久不变。开始联网任务前可先检查：

```powershell
Test-NetConnection 127.0.0.1 -Port 9876 -InformationLevel Quiet
```

返回 `True` 表示本地代理端口可连接；它不代替实际的 GitHub 请求测试。

## 推荐的 Git 调用方式

在 PowerShell 中临时设置环境变量，并给每次 Git 命令传入代理和 OpenSSL 配置：

```powershell
$env:HTTP_PROXY = 'http://127.0.0.1:9876'
$env:HTTPS_PROXY = 'http://127.0.0.1:9876'
$env:ALL_PROXY = 'http://127.0.0.1:9876'
$env:http_proxy = 'http://127.0.0.1:9876'
$env:https_proxy = 'http://127.0.0.1:9876'
$env:all_proxy = 'http://127.0.0.1:9876'

git -c http.sslBackend=openssl `
  -c http.proxy=http://127.0.0.1:9876 `
  ls-remote https://github.com/git/git.git HEAD
```

克隆公开仓库：

```powershell
git -c http.sslBackend=openssl `
  -c http.proxy=http://127.0.0.1:9876 `
  clone --depth 1 https://github.com/OWNER/REPOSITORY.git D:\目标目录
```

获取或推送远端分支时，同样在命令中加入这两项 `-c` 参数：

```powershell
git -c http.sslBackend=openssl `
  -c http.proxy=http://127.0.0.1:9876 `
  fetch origin
```

推荐用命令行临时参数，而不是直接修改全局 Git 配置。这样代理失效时不会污染所有仓库，也不会掩盖当前的 Schannel 兼容性问题。

如果某个工作区需要反复访问同一远端，可以只对该仓库设置本地配置：

```powershell
git config --local http.sslBackend openssl
git config --local http.proxy http://127.0.0.1:9876
```

不要未经用户同意使用 `--global` 修改代理或 SSL 后端。

## 网页、API 和原始文件

`curl.exe` 应显式指定代理：

```powershell
curl.exe -x http://127.0.0.1:9876 -I https://github.com/
```

检查 GitHub API：

```powershell
curl.exe -x http://127.0.0.1:9876 https://api.github.com/rate_limit
```

读取 Raw 文件：

```powershell
curl.exe -x http://127.0.0.1:9876 https://raw.githubusercontent.com/OWNER/REPOSITORY/BRANCH/FILE
```

如果下游工具读取 `HTTP_PROXY`、`HTTPS_PROXY` 或 `ALL_PROXY`，应在本次执行环境中把它们设为 `http://127.0.0.1:9876`，不要沿用 `127.0.0.1:9`。

## 已验证与未验证的边界

已验证：

- 访问公开 GitHub 页面和 API
- 下载公开 Raw 文件和源码归档
- 读取、克隆公开 Git 仓库

未验证：

- 私有仓库访问
- Git push、创建 PR 或修改远端状态
- SSH 方式访问 GitHub
- GitHub Actions、Release 大文件等全部子域

公开仓库能够读取，不代表已经具备推送权限。当前 Git 用户名和邮箱只是提交身份，不是认证凭证。

私有仓库或推送操作应由实际使用的 Git Credential Manager、PAT 或其他已有登录状态完成。不要把令牌写进 URL、仓库文件、说明文档或命令日志。需要认证而当前环境又没有凭证时，应停止并向用户确认授权方式。

## 常见错误处理

### DNS 解析超时或连接 GitHub 443 超时

这是直连失败的表现。使用上述 `127.0.0.1:9876` 代理重试，不要误判为仓库不存在。

### `SEC_E_NO_CREDENTIALS (0x8009030e)`

Git 已经连接上代理隧道，但 Schannel 握手失败。加入：

```text
-c http.sslBackend=openssl
```

不要把该错误解释为 GitHub 账号凭证无效。

### HTTP 407

代理要求认证。本说明中的代理当前不需要额外认证；如果出现 407，应停止并请求用户配置，不要尝试猜测或泄露代理密码。

### HTTP 403 或 API 限流

公开、未认证的 GitHub API 有速率限制。遇到限流不应通过更换代理、伪造请求头或轮换账号绕过；应等待或由用户提供合规的认证方式。

### 工具提示网络权限不足

如果 Agent 运行在受限沙箱中，可能需要为联网命令申请一次权限。先区分“沙箱拒绝”和“代理不可达”，不要把权限问题误当成代理故障。

## 安全要求

- 不要使用 `http.sslVerify=false` 绕过证书错误。
- 不要在文档、日志或命令行中暴露 PAT、代理密码或 Cookie。
- 不要自行修改全局代理、系统代理或 VPN 配置。
- 不要执行未经用户授权的远端写操作。
