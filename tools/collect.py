#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""collect.py — 오늘자 후보 기사 수집기 (표준 라이브러리만 사용)

    python tools/collect.py [--hours 30] [--per-bucket 30]

결과 (work/ 폴더)
    candidates.json   정규화된 전체 후보 (id, source, section, title, link, published, summary)
    digest.txt        화제 키워드 · 화제 묶음 · 분야별 후보 목록  ← 편집자(Claude)가 읽는 파일
"""
import argparse
import concurrent.futures as cf
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
NS = {"dc": "http://purl.org/dc/elements/1.1/",
      "content": "http://purl.org/rss/1.0/modules/content/",
      "atom": "http://www.w3.org/2005/Atom"}

# 기사가 아닌 항목 / 이번 리포트 범위(경제·스포츠·연예·오피니언) 밖의 항목 / 외국어판
NOISE_TITLE = re.compile(
    r"^\s*[\[\(](인사|부고|부음|게시판|알림|동정|포토|사진|영상|카드뉴스|운세|오늘의 운세|날씨|증시|표|그래픽|화보|사설|칼럼|기고)[\]\)]")
NOISE_URL = re.compile(
    r"/(jp|en|cn|ja|zh)/|/sports?/|/entertain|/economy/|/opinion/|/editorials?/|/column|/obituary|/market/|/photos?/",
    re.I)

# 종합 피드의 기사를 URL 경로로 분야에 배정
URL_SECTION = [
    (re.compile(r"/(politics|politic)/", re.I), "정치"),
    (re.compile(r"/(national|society)/", re.I), "사회"),
    (re.compile(r"/(international|inter|world)/", re.I), "국제"),
    (re.compile(r"/(culture|culture-life|life)/", re.I), "문화"),
    (re.compile(r"/(science|tech|it)/", re.I), "IT·과학"),
]
BUCKET = {"정치": "정치·사회", "사회": "정치·사회", "북한": "국제·외교·안보", "국제": "국제·외교·안보",
          "문화": "문화", "IT·과학": "IT·AI·과학", "종합": "종합(분야 미분류)"}
BUCKET_ORDER = ["정치·사회", "국제·외교·안보", "IT·AI·과학", "문화", "종합(분야 미분류)"]

JOSA = re.compile(r"(으로써|으로서|에서는|에게서|이라고|이라며|라고|라며|에서|에게|께서|으로|까지|부터|처럼|보다|에는|에도|에선|로는|은|는|이|가|을|를|의|에|도|만|와|과|로)$")
STOP = set("""대통령 정부 국회 의원 대표 장관 위원장 관련 대한 통해 이후 오늘 내일 어제 올해 최근 지난 이번 우리 한국
서울 국내 해외 전국 일부 모든 모두 대해 위해 따른 따라 대상 속보 단독 종합 영상 포토 사진 연합뉴스 논란 의혹 발표 개최 추진 확대 강화
이어 이어서 이상 이하 가운데 또다시 다시 처음 마지막 지금 현재 여전히 사실상 오는 위한 있다 없다 한다 했다 된다 됐다 나선 나서""".split())


def fetch(url, timeout=20, retries=1):
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.8"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
    raise last


def decode(data: bytes) -> str:
    head = data[:200].decode("ascii", "ignore")
    m = re.search(r'encoding=["\']([\w\-]+)["\']', head)
    enc = (m.group(1) if m else "utf-8").lower()
    if enc in ("euc-kr", "euckr", "ks_c_5601-1987"):
        enc = "cp949"
    try:
        return data.decode(enc)
    except Exception:  # noqa: BLE001
        return data.decode("utf-8", "replace")


def clean(s, n=None):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:n] if n else s


def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
    except Exception:  # noqa: BLE001
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


DROP_Q = {"utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term", "plink", "cooper", "ref"}


def norm_url(u):
    p = urlsplit(u.strip())
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k not in DROP_Q and v != ""]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), ""))


def parse_feed(data: bytes):
    text = decode(data).lstrip("﻿")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    if not re.match(r"\s*<(\?xml|rss|feed|rdf)", text, re.I):
        raise ValueError("RSS가 아닌 응답(HTML 등)")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:  # 이스케이프 안 된 & 등을 보정해 한 번 더 시도
        root = ET.fromstring(re.sub(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", text))
    items = []
    for it in root.iter("item"):
        items.append({
            "title": clean(it.findtext("title")),
            "link": (it.findtext("link") or "").strip(),
            "date": it.findtext("pubDate") or it.findtext("dc:date", namespaces=NS) or "",
            "summary": clean(it.findtext("description") or it.findtext("content:encoded", namespaces=NS) or "", 240),
        })
    for en in root.iter("{%s}entry" % NS["atom"]):
        le = en.find("atom:link", NS)
        items.append({
            "title": clean(en.findtext("atom:title", namespaces=NS)),
            "link": (le.get("href") if le is not None else "") or "",
            "date": en.findtext("atom:updated", namespaces=NS) or en.findtext("atom:published", namespaces=NS) or "",
            "summary": clean(en.findtext("atom:summary", namespaces=NS) or "", 240),
        })
    return items


def terms(title):
    out = set()
    for tok in re.findall(r"[가-힣A-Za-z0-9]{2,}", title):
        if re.fullmatch(r"[가-힣]+", tok):
            t = JOSA.sub("", tok) if len(tok) > 2 else tok
            if len(t) >= 2:
                out.add(t)
        else:
            out.add(tok.lower())
    return out - STOP


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=30, help="발행 시각이 이 시간보다 오래된 기사는 제외")
    ap.add_argument("--per-bucket", type=int, default=30, help="분야별 후보 최대 개수")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    cfg = json.loads((ROOT / "tools" / "sources.json").read_text(encoding="utf-8"))
    now = datetime.now(KST)
    jobs = [(s, f) for s in cfg["sources"] for f in s["feeds"]]

    def run(job):
        s, f = job
        try:
            return job, parse_feed(fetch(f["url"])), None
        except Exception as e:  # noqa: BLE001
            return job, [], f"{type(e).__name__}: {e}"

    status = []
    items, seen = [], {}
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for (s, f), raw, err in ex.map(run, jobs):
            status.append((s["name"], f["section"], len(raw), err, f["url"]))
            for r in raw:
                if not r["title"] or not r["link"]:
                    continue
                link = norm_url(r["link"])
                if NOISE_TITLE.search(r["title"]) or NOISE_URL.search(link):
                    continue
                pub = parse_date(r["date"])
                if pub and now - pub > timedelta(hours=args.hours):
                    continue
                if pub and pub - now > timedelta(hours=2):
                    pub = None  # 시계 오류 방어
                section = f["section"]
                if section == "종합":
                    for pat, name in URL_SECTION:
                        if pat.search(link):
                            section = name
                            break
                rec = {"source": s["name"], "group": s["group"], "section": section, "title": r["title"],
                       "link": link, "published": pub.isoformat(timespec="minutes") if pub else None,
                       "summary": r["summary"]}
                if link in seen:  # 같은 기사가 여러 피드에 있으면 더 구체적인 분야를 남김
                    if seen[link]["section"] == "종합" and section != "종합":
                        seen[link]["section"] = section
                    continue
                seen[link] = rec
                items.append(rec)

    items.sort(key=lambda x: x["published"] or "", reverse=True)
    for i, it in enumerate(items, 1):
        it["id"] = f"a{i:03d}"
        it["terms"] = sorted(terms(it["title"]))

    # ── 화제 키워드: 서로 다른 매체 수 기준
    df = defaultdict(set)
    for it in items:
        for t in it["terms"]:
            df[t].add(it["source"])
    buzz = sorted(((t, len(s)) for t, s in df.items() if len(s) >= 3), key=lambda x: (-x[1], x[0]))[:40]

    # ── 화제 묶음: 희소한 키워드를 2개 이상 공유하면 같은 이슈로 묶음
    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    rare = [set(t for t in it["terms"] if 2 <= len(df[t]) <= 9) for it in items]
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i]["source"] == items[j]["source"] and items[i]["title"] == items[j]["title"]:
                continue
            common = rare[i] & rare[j]
            if len(common) >= 2 or any(len(t) >= 4 for t in common):
                parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i in range(len(items)):
        groups[find(i)].append(items[i])
    clusters = []
    for g in groups.values():
        srcs = {x["source"] for x in g}
        if len(srcs) < 2:
            continue
        c = Counter(t for x in g for t in x["terms"] if len(df[t]) >= 2)
        clusters.append({"sources": sorted(srcs), "terms": [t for t, _ in c.most_common(4)], "items": g})
    clusters.sort(key=lambda c: (-len(c["sources"]), -len(c["items"])))

    # ── 파일 출력
    WORK.mkdir(exist_ok=True)
    (WORK / "candidates.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    def hhmm(it):
        return it["published"][5:16].replace("T", " ") if it["published"] else "시각미상"

    out = [f"# 후보 기사 다이제스트 — 수집 {now:%Y-%m-%d %H:%M} KST · 후보 {len(items)}건 · 최근 {args.hours:g}시간",
           "", "## 화제 키워드 (괄호=다룬 매체 수)", " · ".join(f"{t}({n})" for t, n in buzz), ""]
    out.append("## 화제 묶음 (여러 매체가 다룬 이슈 — 톱이슈·추적이슈 후보)")
    for k, c in enumerate(clusters[:18], 1):
        out.append(f"### C{k:02d} [{len(c['sources'])}개 매체: {'·'.join(c['sources'])}] 키워드: {', '.join(c['terms'])}")
        for it in sorted(c["items"], key=lambda x: x["published"] or "", reverse=True)[:6]:
            out.append(f"- {it['id']} ({it['source']} {hhmm(it)}) {it['title']}\n  {it['link']}")
    out.append("")
    buckets = defaultdict(list)
    for it in items:
        buckets[BUCKET.get(it["section"], "종합(분야 미분류)")].append(it)
    for name in BUCKET_ORDER:
        lst = buckets.get(name, [])
        out.append(f"## 분야별 후보 — {name} ({len(lst)}건 중 최신·매체 분산 {args.per_bucket}건)")
        per_src, shown = Counter(), 0
        for it in lst:
            if per_src[it["source"]] >= 9:
                continue
            per_src[it["source"]] += 1
            out.append(f"- {it['id']} ({it['source']} {hhmm(it)}) {it['title']}\n  {it['link']}")
            shown += 1
            if shown >= args.per_bucket:
                break
        out.append("")
    (WORK / "digest.txt").write_text("\n".join(out), encoding="utf-8")

    print(f"후보 {len(items)}건 · 화제 묶음 {len(clusters)}개 → work/digest.txt, work/candidates.json")
    bad = [s for s in status if s[3] or s[2] == 0]
    print(f"피드 {len(status)}개 중 정상 {len(status) - len(bad)}개")
    for name, sec, n, err, url in bad:
        print(f"  ! {name}/{sec}: {err or '항목 0건'}  ({url})")


if __name__ == "__main__":
    main()
