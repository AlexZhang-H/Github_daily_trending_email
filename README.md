# GitHub Daily Trending Email

每天定时抓取 GitHub Trending（Daily · All Languages）Top 10，并通过 Resend 发送一封排版整洁的 HTML 邮件。

## 功能

- 抓取页面：`https://github.com/trending?since=daily`
- 解析字段：项目名称、项目地址、Star 数、项目简介（前 10 条）
- 邮件发送：Resend Python SDK（HTML 邮件）
- 定时执行：GitHub Actions 每天北京时间 08:30（UTC 00:30）自动触发

## 项目结构

- `daily_trending.py`：主脚本（抓取 → 解析 → 生成 HTML → 发送）
- `requirements.txt`：Python 依赖
- `.github/workflows/daily_trending.yml`：GitHub Actions 工作流（定时/手动触发）

## 本地运行

### 1) 安装依赖

```bash
python -m pip install -r requirements.txt
```

### 2) 预览邮件（不发送）

```bash
python daily_trending.py --no-email
```

### 3) 发送邮件

脚本通过环境变量读取敏感信息（不要写进代码或提交到仓库）：

- `RESEND_API_KEY`
- `SENDER_EMAIL`
- `RECIPIENT_EMAIL`（支持逗号或空格分隔多个收件人）

PowerShell 示例：

```powershell
$env:RESEND_API_KEY="re_xxx"
$env:SENDER_EMAIL="Your Name <noreply@yourdomain.com>"
$env:RECIPIENT_EMAIL="a@example.com,b@example.com"
python daily_trending.py
```

## GitHub Actions 配置与运行

### 1) 配置 Secrets

进入仓库：

`Settings → Secrets and variables → Actions → New repository secret`

添加 3 个 secrets（名称需完全一致）：

- `RESEND_API_KEY`
- `SENDER_EMAIL`
- `RECIPIENT_EMAIL`

### 2) 手动运行一次验证

进入 `Actions` → 选择 `Daily GitHub Trending Email` → `Run workflow`。

### 3) 定时运行

工作流 cron 为：

```text
30 0 * * *  (UTC)
```

对应北京时间每天 `08:30` 自动运行。

## Resend 限制与常见问题

### 1) 测试期只能发给自己的邮箱

如果 Resend 账号尚未验证域名，通常只能发送测试邮件到你账号“自己的邮箱”。日志可能类似：

> You can only send testing emails to your own email address (...)

处理方式：

- 最佳实践：在 Resend 控制台验证一个你自己的域名，并把 `SENDER_EMAIL` 改为该域名下的发件人地址；
- 本项目已做了兼容：当检测到上述限制报错时，会自动回退为发送到 Resend 允许的邮箱（用于跑通测试链路）。

### 2) 发件人必须可用

`SENDER_EMAIL` 必须是 Resend 允许的发件人（已验证域名/地址）。否则会发送失败。

## 安全建议

- 不要在聊天、代码、工作流文件或 commit 里明文粘贴 `RESEND_API_KEY`
- 如果泄露过 key：请立刻在 Resend 控制台作废旧 key 并重新生成

