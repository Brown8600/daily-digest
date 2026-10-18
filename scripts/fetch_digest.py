#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日开发者日报生成器
====================
数据源(v1):
  1. GitHub 本周新星    — GitHub Search API (最近 7 天创建, 按 star 排序)
  2. Hacker News Top 10 — 官方 Firebase API
  3. 少数派精选文章      — sspai.com RSS

用法:
  python scripts/fetch_digest.py            # 生成日报并写入 reports/
  python scripts/fetch_digest.py --dry-run  # 只抓取+渲染到 stdout, 不写文件 (CI 用)

设计原则:
  - 零第三方依赖 (纯 Python 标准库)
  - 单个数据源失败不影响其他数据源 (部分失败仍产出日报)
  - 全部失败时以非零退出码结束, 让 CI 变红
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------- 常量 ----------
TZ_CN = timezone(timedelta(hours=8))  # 北京时间
ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "reports"
USER_AGENT = "daily-digest-bot/1.0 (+https://github.com/Brown8600/daily-digest)"
HTTP_TIMEOUT = 20


# ---------- HTTP 工具 ----------
def http_get(url: str, extra_headers: dict | None = None) -> bytes:
    """统一的 GET 请求, 带 User-Agent 和超时。"""
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read()


def get_json(url: str, extra_headers: dict | None = None):
    return json.loads(http_get(url, extra_headers).decode("utf-8"))


# ---------- 数据源 1: GitHub 本周新星 ----------
def fetch_github_new_stars(limit: int = 10) -> list[dict]:
    """GitHub Search API: 最近 7 天创建、star 超过 100 的新仓库, 按 star 数排序。"""
    since = (datetime.now(TZ_CN) - timedelta(days=7)).strftime("%Y-%m-%d")
    query = urllib.parse.quote(f"created:>{since} stars:>100")
    url = (
        "https://api.github.com/search/repositories"
        f"?q={query}&sort=stars&order=desc&per_page={limit}"
    )
    # 如果环境里提供了 token (GitHub Actions 会自动注入 GITHUB_TOKEN),
    # 用它把 API 限额从 60 次/小时 提升到 5000 次/小时
    headers = {}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = get_json(url, headers)
    items = []
    for repo in data.get("items", []):
        desc = (repo.get("description") or "").replace("\n", " ").strip()
        items.append(
            {
                "name": repo["full_name"],
                "url": repo["html_url"],
                "desc": desc or "（无简介）",
                "lang": repo.get("language") or "未知",
                "stars": repo.get("stargazers_count", 0),
            }
        )
    return items


# ---------- 数据源 2: Hacker News Top 10 ----------
def fetch_hn_top(limit: int = 10) -> list[dict]:
    """Hacker News 官方 API: 先取热帖 ID 列表, 再逐条取详情。"""
    ids = get_json("https://hacker-news.firebaseio.com/v0/topstories.json")[:limit]
    items = []
    for story_id in ids:
        try:
            item = get_json(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
            )
        except Exception:
            continue  # 单条失败就跳过, 不影响其他条目
        if not item or item.get("type") != "story":
            continue
        items.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url")
                or f"https://news.ycombinator.com/item?id={story_id}",
                "score": item.get("score", 0),
                "comments": item.get("descendants", 0),
            }
        )
    return items


# ---------- 数据源 3: 少数派 RSS ----------
def fetch_sspai(limit: int = 8) -> list[dict]:
    """少数派 Matrix 首页 RSS, 取最新 N 篇文章。"""
    raw = http_get("https://sspai.com/feed")
    root = ET.fromstring(raw)  # 直接解析 bytes, 保留 XML 声明里的编码信息
    channel = root.find("channel")
    if channel is None:
        raise ValueError("RSS 结构异常: 找不到 <channel>")
    items = []
    for node in channel.findall("item")[:limit]:
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        if title and link:
            items.append({"title": title, "url": link})
    return items


# ---------- 数据源 4: V2EX 热门讨论 ----------
def fetch_v2ex_hot(limit: int = 10) -> list[dict]:
    """V2EX 热门讨论 (官方公开 API, 无需登录)。

    注意: 该 API 在部分网络环境不可达, 失败时本栏目会显示警告,
    但不影响其他栏目 —— 这正是"单点失败不扩散"的设计。
    """
    data = get_json("https://www.v2ex.com/api/topics/hot.json")
    items = []
    for topic in data[:limit]:
        title = (topic.get("title") or "").strip()
        url = (topic.get("url") or "").strip()
        if not title or not url:
            continue
        member = topic.get("member") or {}
        items.append(
            {
                "title": title,
                "url": url,
                "author": member.get("username", "unknown"),
                "replies": topic.get("replies", 0),
            }
        )
    return items


# ---------- 渲染: 每个栏目一个格式化函数 ----------
def section_github(items: list[dict]) -> str:
    lines = ["| # | 项目 | 语言 | Star | 简介 |", "|---|------|------|------|------|"]
    for i, it in enumerate(items, 1):
        desc = it["desc"].replace("|", "\\|")  # 竖线会破坏表格, 要转义
        lines.append(
            f"| {i} | [{it['name']}]({it['url']}) | {it['lang']} "
            f"| {it['stars']:,} | {desc} |"
        )
    return "\n".join(lines)


def section_hn(items: list[dict]) -> str:
    lines = []
    for i, it in enumerate(items, 1):
        lines.append(
            f"{i}. [{it['title']}]({it['url']}) — ⬆️ {it['score']} · 💬 {it['comments']}"
        )
    return "\n".join(lines)


def section_sspai(items: list[dict]) -> str:
    lines = []
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. [{it['title']}]({it['url']})")
    return "\n".join(lines)


def section_v2ex(items: list[dict]) -> str:
    lines = []
    for i, it in enumerate(items, 1):
        lines.append(
            f"{i}. [{it['title']}]({it['url']}) — @{it['author']} · 💬 {it['replies']}"
        )
    return "\n".join(lines)


# ---------- 组装日报 ----------
def build_report() -> tuple[str, list[tuple[str, str]]]:
    """返回 (markdown 文本, [(栏目名, 状态)])"""
    now = datetime.now(TZ_CN)
    date_str = now.strftime("%Y-%m-%d")

    jobs = [
        ("GitHub 本周新星 Top 10", "🚀", fetch_github_new_stars, section_github),
        ("Hacker News Top 10", "🔥", fetch_hn_top, section_hn),
        ("少数派精选", "📖", fetch_sspai, section_sspai),
        ("V2EX 热门讨论", "💬", fetch_v2ex_hot, section_v2ex),
    ]

    parts = [
        f"# 📰 开发者日报 · {date_str}",
        "",
        f"> 🤖 由 GitHub Actions 自动抓取生成 · {now:%Y-%m-%d %H:%M} (UTC+8)",
        "",
    ]
    results = []
    for name, icon, fetcher, formatter in jobs:
        parts.append(f"## {icon} {name}")
        parts.append("")
        try:
            items = fetcher()
            if not items:
                raise ValueError("接口返回了空结果")
            parts.append(formatter(items))
            results.append((name, f"✅ {len(items)} 条"))
        except Exception as exc:
            parts.append(f"> ⚠️ 本栏目抓取失败: {exc}")
            results.append((name, f"❌ {exc}"))
        parts.append("")

    parts.append("---")
    parts.append("")
    parts.append("**数据源状态**: " + " · ".join(f"{n} {s}" for n, s in results))
    parts.append("")
    return "\n".join(parts), results


def main() -> None:
    parser = argparse.ArgumentParser(description="每日开发者日报生成器")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只把日报打印到控制台, 不写入文件 (供 CI 校验使用)",
    )
    args = parser.parse_args()

    markdown, results = build_report()

    if args.dry_run:
        print(markdown)
    else:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now(TZ_CN).strftime("%Y-%m-%d")
        path = REPORTS_DIR / f"{date_str}.md"
        path.write_text(markdown, encoding="utf-8")
        print(f"✅ 日报已生成: {path.relative_to(ROOT)}")

    failed = [name for name, status in results if status.startswith("❌")]
    if len(failed) == len(results):
        print("❌ 所有数据源都失败了, 本次抓取无效", file=sys.stderr)
        sys.exit(1)
    if failed:
        # 部分成功: 仍然产出日报, 但留下警告痕迹
        print(f"⚠️ 部分数据源失败: {', '.join(failed)}", file=sys.stderr)


if __name__ == "__main__":
    main()
