# 📰 daily-digest · 每日开发者日报

每天自动抓取技术圈动态，生成一份 Markdown 日报。由 **GitHub Actions** 定时驱动，全自动无人值守，零第三方依赖。

## 日报内容

| 栏目 | 数据源 | 说明 |
|------|--------|------|
| 🚀 GitHub 本周新星 | GitHub Search API | 最近 7 天创建、Star 最高的 10 个新仓库 |
| 🔥 Hacker News Top 10 | HN 官方 API | 当日最热技术话题 |
| 📖 少数派精选 | sspai.com RSS | 最新效率/数码好文 |

## 工作原理

每天北京时间 08:00，GitHub Actions 按 cron 表达式自动触发 `daily.yml` 工作流：

    cron 0 0 * * * ─► checkout 检出代码 ─► setup-python 3.13 ─► fetch_digest.py 抓取
                                                                      │
                                    ┌─────────────────────────────────┤
                                    ▼                                 ▼
                            GitHub Search API              Hacker News API / 少数派 RSS
                                    │
                                    ▼
                      生成 reports/YYYY-MM-DD.md ─► git commit & push ─► 📬 仓库归档

## 本地运行

只要有 Python 3.10+，无需安装任何依赖：

```bash
python scripts/fetch_digest.py            # 生成今天的日报到 reports/
python scripts/fetch_digest.py --dry-run  # 只打印不写文件（CI 用）
```

## 目录结构

    daily-digest/
    ├── .github/
    │   └── workflows/
    │       ├── daily.yml      # 定时工作流：每天自动抓取 + 发布
    │       └── ci.yml         # CI 工作流：PR / push 时校验脚本能正常跑
    ├── scripts/
    │   └── fetch_digest.py    # 抓取 + 渲染脚本（纯标准库）
    ├── reports/               # 每天一份的日报存档（由机器人自动提交）
    └── README.md

## 这个项目本身就是 GitHub workflow 的教材

- **Actions 是事件驱动的**：`daily.yml` 监听 `schedule`（cron 定时）和 `workflow_dispatch`（手动触发）；`ci.yml` 监听 `pull_request` 和 `push`
- **workflow 只是 YAML 文件**：放在 `.github/workflows/` 目录，push 上去即生效
- **机器人有身份**：Actions 通过内置的 `GITHUB_TOKEN` 获得写权限，以 `github-actions[bot]` 的身份提交日报
- **CI 守护主分支**：任何 PR 都会先跑 `ci.yml`，脚本挂了就过不了检查

## 日报存档

每天的日报按日期归档在 [`reports/`](./reports/) 目录，机器人自动提交，无需人工干预。
