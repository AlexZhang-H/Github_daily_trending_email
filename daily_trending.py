import argparse
import os
import re
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

import requests
import resend
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


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


def require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def send_email(subject: str, html: str) -> dict:
    api_key = require_env("RESEND_API_KEY")
    sender = require_env("SENDER_EMAIL")
    recipient_raw = require_env("RECIPIENT_EMAIL")
    recipients = parse_recipients(recipient_raw)
    if not recipients:
        raise RuntimeError("RECIPIENT_EMAIL is empty")

    resend.api_key = api_key
    params: resend.Emails.SendParams = {
        "from": sender,
        "to": recipients,
        "subject": subject,
        "html": html,
    }
    try:
        return resend.Emails.send(params)
    except Exception as exc:
        msg = str(exc)
        m = re.search(r"own email address \(([^)]+)\)", msg)
        if m:
            allowed = m.group(1).strip()
            if allowed and recipients != [allowed]:
                params_retry: resend.Emails.SendParams = {
                    "from": sender,
                    "to": [allowed],
                    "subject": subject,
                    "html": html,
                }
                return resend.Emails.send(params_retry)
        raise


def create_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-email", action="store_true", help="Only print HTML, do not send email")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    try:
        beijing_dt = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Shanghai"))

        with create_session() as session:
            html = fetch_trending_html(session)
        repos = parse_trending_top10(html)
        if len(repos) < 10:
            raise RuntimeError(f"Parsed only {len(repos)} repos from Trending page")

        email_html = build_html_email(repos, beijing_dt)
        subject = f"GitHub Trending Daily Top 10 ({beijing_dt.strftime('%Y-%m-%d')} 北京时间)"

        if args.no_email:
            print(email_html)
            return 0

        resp = send_email(subject=subject, html=email_html)
        print(resp)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
