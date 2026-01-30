import argparse
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

import requests
import resend
from bs4 import BeautifulSoup


TRENDING_URL = "https://github.com/trending?since=daily"
DEFAULT_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class TrendingRepo:
    name: str
    url: str
    stars: int
    description: str


def _parse_int_maybe(text: str) -> Optional[int]:
    cleaned = re.sub(r"[^\d]", "", text or "")
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def fetch_trending_html(session: requests.Session) -> str:
    headers = {
        "User-Agent": "daily-trending-bot/1.0 (+https://github.com)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = session.get(TRENDING_URL, headers=headers, timeout=DEFAULT_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp.text


def parse_trending_top10(html: str) -> List[TrendingRepo]:
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("article.Box-row")
    repos: List[TrendingRepo] = []

    for row in rows[:10]:
        h2 = row.select_one("h2 a[href]")
        if not h2:
            continue

        href = h2.get("href", "").strip()
        url = f"https://github.com{href}"
        name = " ".join(h2.get_text(" ", strip=True).split())
        name = name.replace(" / ", "/").strip()

        desc_el = row.select_one("p.col-9.color-fg-muted.my-1.pr-4")
        description = ""
        if desc_el:
            description = desc_el.get_text(" ", strip=True)

        stars = 0
        star_el = row.select_one('a[href$="/stargazers"]')
        if star_el:
            parsed = _parse_int_maybe(star_el.get_text(" ", strip=True))
            if parsed is not None:
                stars = parsed

        repos.append(
            TrendingRepo(
                name=name,
                url=url,
                stars=stars,
                description=description,
            )
        )

    return repos


def build_html_email(repos: List[TrendingRepo], beijing_dt: datetime) -> str:
    date_str = beijing_dt.strftime("%Y-%m-%d")
    rows_html = []
    for idx, repo in enumerate(repos, start=1):
        desc = repo.description or "&nbsp;"
        rows_html.append(
            f"""
            <tr>
              <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;vertical-align:top;color:#111827;">{idx}</td>
              <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;vertical-align:top;">
                <div style="font-weight:600;margin:0 0 6px 0;">
                  <a href="{repo.url}" style="color:#2563eb;text-decoration:none;">{repo.name}</a>
                </div>
                <div style="color:#6b7280;line-height:1.5;">{desc}</div>
              </td>
              <td style="padding:10px 12px;border-bottom:1px solid #e5e7eb;vertical-align:top;color:#111827;text-align:right;white-space:nowrap;">{repo.stars:,}</td>
            </tr>
            """.strip()
        )

    rows_block = "\n".join(rows_html) if rows_html else ""

    return f"""
    <div style="font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial,'Apple Color Emoji','Segoe UI Emoji';color:#111827;">
      <h2 style="margin:0 0 8px 0;">GitHub Trending（Daily · All Languages）Top 10</h2>
      <div style="margin:0 0 16px 0;color:#6b7280;">日期（北京时间）：{date_str}</div>

      <table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
        <thead>
          <tr style="background:#f9fafb;">
            <th style="text-align:left;padding:10px 12px;border-bottom:1px solid #e5e7eb;color:#374151;">#</th>
            <th style="text-align:left;padding:10px 12px;border-bottom:1px solid #e5e7eb;color:#374151;">项目</th>
            <th style="text-align:right;padding:10px 12px;border-bottom:1px solid #e5e7eb;color:#374151;">Stars</th>
          </tr>
        </thead>
        <tbody>
          {rows_block}
        </tbody>
      </table>

      <div style="margin-top:14px;color:#9ca3af;font-size:12px;">
        数据来源：<a href="{TRENDING_URL}" style="color:#6b7280;text-decoration:none;">GitHub Trending</a>
      </div>
    </div>
    """.strip()


def parse_recipients(raw: str) -> List[str]:
    parts = [p.strip() for p in re.split(r"[,\s]+", raw or "") if p.strip()]
    seen = set()
    recipients: List[str] = []
    for p in parts:
        if p not in seen:
            recipients.append(p)
            seen.add(p)
    return recipients


def send_email(subject: str, html: str) -> dict:
    api_key = os.environ["RESEND_API_KEY"]
    sender = os.environ["SENDER_EMAIL"]
    recipient_raw = os.environ["RECIPIENT_EMAIL"]
    recipients = parse_recipients(recipient_raw)
    if not recipients:
        raise ValueError("RECIPIENT_EMAIL is empty")

    resend.api_key = api_key
    params: resend.Emails.SendParams = {
        "from": sender,
        "to": recipients,
        "subject": subject,
        "html": html,
    }
    return resend.Emails.send(params)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-email", action="store_true", help="Only print HTML, do not send email")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    beijing_dt = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Shanghai"))

    with requests.Session() as session:
        html = fetch_trending_html(session)
    repos = parse_trending_top10(html)
    email_html = build_html_email(repos, beijing_dt)
    subject = f"GitHub Trending Daily Top 10 ({beijing_dt.strftime('%Y-%m-%d')} 北京时间)"

    if args.no_email:
        print(email_html)
        return 0

    resp = send_email(subject=subject, html=email_html)
    print(resp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
