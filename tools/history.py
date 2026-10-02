#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""history.py — 특정 이슈의 지난 며칠치 기사 목록을 찾는 도구 (Bing 뉴스 RSS, 표준 라이브러리만 사용)

    python tools/history.py "검색어" ["검색어2" ...] [--days 14] [--limit 15] [--domains yna.co.kr,khan.co.kr]

추적 이슈의 타임라인을 처음 만들 때(백필) 쓰고, 이후에는 전날 호의 timeline에 오늘 항목만 덧붙입니다.
출력: 발행일(KST) | 도메인 | 제목 | 원문 URL(Bing 중계 주소가 아닌 실제 기사 주소)
"""
import argparse
import html
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

KST = timezone(timedelta(hours=9))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def search(q, days):
    params = {"q": q, "format": "rss", "setmkt": "ko-KR", "setlang": "ko", "qft": 'sortbydate="1"'}
    url = "https://www.bing.com/news/search?" + urllib.parse.urlencode(params)
    data = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=25).read()
    now = datetime.now(KST)
    out = []
    for it in ET.fromstring(data).iter("item"):
        link = it.findtext("link") or ""
        m = re.search(r"[?&]url=([^&]+)", link)
        real = urllib.parse.unquote(m.group(1)) if m else link
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate")).astimezone(KST)
        except Exception:  # noqa: BLE001
            continue
        if now - pub > timedelta(days=days):
            continue
        out.append((pub, urllib.parse.urlsplit(real).netloc.replace("www.", ""),
                    html.unescape(it.findtext("title") or "").strip(), real))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("queries", nargs="+")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--domains", default="", help="쉼표로 구분한 도메인만 남김 (예: yna.co.kr,khan.co.kr)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    want = [d.strip() for d in args.domains.split(",") if d.strip()]
    for q in args.queries:
        print(f"## {q}")
        try:
            rows = search(q, args.days)
        except Exception as e:  # noqa: BLE001
            print(f"  ERR {type(e).__name__}: {e}")
            continue
        if want:
            rows = [r for r in rows if any(r[1].endswith(d) for d in want)]
        for pub, dom, title, url in rows[:args.limit]:
            print(f"  {pub:%m-%d %H:%M} | {dom} | {title[:70]} | {url}")


if __name__ == "__main__":
    main()
