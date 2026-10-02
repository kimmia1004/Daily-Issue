#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate.py — 새 호(data/YYYY-MM-DD.js)를 검사하고, 통과하면 manifest.js 에 등록합니다.

    python tools/validate.py 2026-10-02            # 검사만
    python tools/validate.py 2026-10-02 --publish  # 검사 통과 시 manifest.js 에 등록
    python tools/validate.py 2026-10-02 --offline  # 링크·이미지 접속 점검 생략

검사 항목
  · 구조: 필수 필드, 개수(톱 3·추적 2~4·단신 4~6), 중복 URL(같은 호 안에서 같은 기사를 두 번 쓰지 않기)
  · 글자 수 → 읽는 시간(공백 제외 450자/분, 목표 4~6분)
  · 링크: 모든 기사 URL이 열리는지 (200대 응답)
  · 이미지: 모든 대표 이미지가 실제 이미지(image/*)이고 가로 600px 이상·용량 10KB 이상인지
  · 추적 이슈: since 날짜, 타임라인 날짜 오름차순, 마지막 항목이 당일/전일인지
오류(ERROR)가 하나라도 있으면 종료 코드 1, 경고(WARN)만 있으면 0.
"""
import argparse
import concurrent.futures as cf
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from article import check_image  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
CHARS_PER_MIN = 450


def load_edition(day):
    path = DATA / f"{day}.js"
    if not path.exists():
        sys.exit(f"ERROR: {path} 가 없습니다.")
    text = path.read_text(encoding="utf-8")
    m = re.search(rf'editions\["{re.escape(day)}"\]\s*=\s*', text)
    if not m:
        sys.exit(f'ERROR: {path.name} 에 window.DAILY.editions["{day}"] = {{...}}; 형태가 없습니다.')
    body = text[m.end():].strip()
    if body.endswith(";"):
        body = body[:-1]
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        sys.exit(f"ERROR: {path.name} 의 JSON 문법 오류 — {e} (키는 큰따옴표, 마지막 쉼표 금지, 주석 금지)")


def clen(s):
    return len(re.sub(r"\s+", "", s or ""))


def all_items(ed):
    out = []
    front = ed.get("front") or {}
    if front.get("lead"):
        out.append(("front.lead", front["lead"]))
    for i, it in enumerate(front.get("tops") or []):
        out.append((f"front.tops[{i}]", it))
    for i, t in enumerate(ed.get("tracking") or []):
        out.append((f"tracking[{i}].today", t.get("today") or {}))
    for i, it in enumerate(ed.get("briefs") or []):
        out.append((f"briefs[{i}]", it))
    return out


def reading_chars(ed):
    n = 0
    front = ed.get("front") or {}
    for it in [front.get("lead")] + list(front.get("tops") or []) + list(ed.get("briefs") or []):
        if not it:
            continue
        n += clen(it.get("headline")) + clen(it.get("summary")) + clen(it.get("why"))
        n += sum(clen(f.get("k")) + clen(f.get("v")) for f in it.get("facts") or [])
    for t in ed.get("tracking") or []:
        n += clen(t.get("title")) + clen((t.get("today") or {}).get("summary"))
        n += sum(clen(e.get("text")) for e in (t.get("timeline") or [])[-5:])
    return n


def url_ok(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
        with urllib.request.urlopen(req, timeout=25) as r:
            r.read(2048)
            return 200 <= r.status < 400, r.status
    except urllib.error.HTTPError as e:
        # 일부 매체는 봇에 403을 주지만 브라우저에서는 열림 → 경고로만 취급
        return False, e.code
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("day", help="YYYY-MM-DD")
    ap.add_argument("--publish", action="store_true", help="검사 통과 시 data/manifest.js 에 등록")
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    day = args.day
    ed = load_edition(day)
    errors, warns = [], []
    E, W = errors.append, warns.append

    # ── 구조
    if ed.get("date") != day:
        E(f'date 필드가 "{day}" 가 아닙니다: {ed.get("date")!r}')
    front = ed.get("front") or {}
    if not front.get("lead"):
        E("front.lead(톱 기사)가 없습니다")
    tops = front.get("tops") or []
    trk = ed.get("tracking") or []
    brf = ed.get("briefs") or []
    if not 2 <= len(tops) <= 3:
        W(f"front.tops 는 2~3건 권장 (현재 {len(tops)})")
    if not 2 <= len(trk) <= 4:
        W(f"tracking 은 2~4건 권장 (현재 {len(trk)})")
    if not 4 <= len(brf) <= 6:
        W(f"briefs 는 4~6건 권장 (현재 {len(brf)})")

    seen_urls = {}
    for where, it in all_items(ed):
        need = ["headline", "summary", "image", "url", "source"]
        if ".today" not in where:  # 추적 이슈의 kicker 는 tracking[i].kicker 에 있음
            need.insert(0, "kicker")
        for k in need:
            if not it.get(k):
                E(f"{where}.{k} 가 비어 있습니다")
        if it.get("image") and not it["image"].get("src"):
            E(f"{where}.image.src 가 비어 있습니다")
        if where.startswith("front") and "why" not in it and where == "front.lead":
            W(f"{where}.why(알아둘 점)가 없습니다")
        u = it.get("url")
        if u:
            seen_urls.setdefault(u, []).append(where)
        if it.get("summary") and clen(it["summary"]) > (460 if where == "front.lead" else 330):
            W(f"{where}.summary 가 깁니다({clen(it['summary'])}자) — 5분 안에 읽히도록 줄여 주세요")
    for u, wh in seen_urls.items():
        if len(wh) > 1:
            E(f"같은 기사 URL이 {wh} 에서 중복 사용됨: {u}")

    # ── 추적 이슈
    d_day = date.fromisoformat(day)
    for i, t in enumerate(trk):
        w = f"tracking[{i}]"
        for k in ["id", "kicker", "title", "since", "today", "timeline"]:
            if not t.get(k):
                E(f"{w}.{k} 가 비어 있습니다")
        try:
            since = date.fromisoformat(t["since"])
            if since > d_day:
                E(f"{w}.since 가 발행일보다 늦습니다")
        except Exception:  # noqa: BLE001
            E(f"{w}.since 형식 오류(YYYY-MM-DD): {t.get('since')!r}")
        last = None
        for j, e in enumerate(t.get("timeline") or []):
            for k in ["date", "text", "source", "url"]:
                if not e.get(k):
                    E(f"{w}.timeline[{j}].{k} 가 비어 있습니다")
            ds = e.get("date", "")
            if not re.fullmatch(r"\d{4}-\d{2}(-\d{2})?", ds):
                E(f"{w}.timeline[{j}].date 형식 오류: {ds!r}")
                continue
            if last and ds < last:
                E(f"{w}.timeline 은 날짜 오름차순이어야 합니다 ({last} 다음에 {ds})")
            last = ds
            if len(ds) == 10 and date.fromisoformat(ds) > d_day:
                E(f"{w}.timeline[{j}] 날짜가 발행일보다 늦습니다")
        tl = t.get("timeline") or []
        if tl and len(tl[-1].get("date", "")) == 10:
            gap = (d_day - date.fromisoformat(tl[-1]["date"])).days
            if gap > 1:
                W(f"{w} 타임라인의 마지막 항목이 {gap}일 전입니다 — 오늘의 변화가 없으면 추적 이슈를 교체하거나 status 를 ‘잠잠’ 등으로 바꾸세요")
        if len(tl) < 3:
            W(f"{w}.timeline 이 {len(tl)}건뿐입니다(3건 이상 권장)")
        urls = [e.get("url") for e in tl]
        if len(urls) != len(set(urls)):
            W(f"{w}.timeline 에 같은 URL이 반복됩니다(서로 다른 기사 권장)")

    # ── 읽는 시간
    n = reading_chars(ed)
    mins = n / CHARS_PER_MIN
    print(f"글자 수(공백 제외) {n:,}자 → 읽는 시간 약 {mins:.1f}분")
    if mins < 3.5:
        W("읽는 시간이 3.5분 미만입니다 — 내용이 너무 얇습니다")
    if mins > 6.0:
        W("읽는 시간이 6분을 넘습니다 — 요약을 줄이거나 단신을 덜어내세요")

    # ── 링크·이미지 접속 점검
    if not args.offline:
        links = {}
        for where, it in all_items(ed):
            if it.get("url"):
                links.setdefault(it["url"], where)
            for m in it.get("more") or []:
                links.setdefault(m.get("url"), where + ".more")
        for t in trk:
            for e in t.get("timeline") or []:
                links.setdefault(e.get("url"), t.get("id", "tracking") + ".timeline")
        links.pop(None, None)
        imgs = {}
        for where, it in all_items(ed):
            src = (it.get("image") or {}).get("src")
            if src:
                imgs[src] = where
        with cf.ThreadPoolExecutor(max_workers=8) as ex:
            lres = dict(zip(links, ex.map(url_ok, links)))
            ires = dict(zip(imgs, ex.map(check_image, imgs)))
        bad_links = 0
        for u, (ok, code) in lres.items():
            if not ok:
                bad_links += 1
                (W if code in (401, 403, 429) else E)(f"링크 열기 실패({code}) [{links[u]}] {u}")
        for src, r in ires.items():
            where = imgs[src]
            if not r.get("ok"):
                E(f"이미지 열기 실패 [{where}] {src} — {r.get('error') or r}")
                continue
            w_, h_ = (r.get("size") or [0, 0])
            if w_ and w_ < 600:
                W(f"이미지가 작습니다({w_}×{h_}) [{where}] {src}")
            if w_ and h_ and (w_ / h_ > 4 or h_ / w_ > 2.2):
                W(f"이미지 비율이 극단적입니다({w_}×{h_}) [{where}] — image.pos 로 잘라 보이는 위치를 조정하세요")
        print(f"링크 {len(links)}개 중 문제 {bad_links}개 · 이미지 {len(imgs)}개 점검 완료")

    for w in warns:
        print("WARN :", w)
    for e in errors:
        print("ERROR:", e)
    if errors:
        print(f"\n✗ 오류 {len(errors)}건 — 고친 뒤 다시 실행하세요.")
        sys.exit(1)
    print(f"\n✓ 통과 (경고 {len(warns)}건)")

    if args.publish:
        man_path = DATA / "manifest.js"
        days = []
        if man_path.exists():
            days = re.findall(r"\d{4}-\d{2}-\d{2}", man_path.read_text(encoding="utf-8"))
        if day not in days:
            days.append(day)
        days = sorted(set(days))
        man_path.write_text(
            "window.DAILY = window.DAILY || {};\nwindow.DAILY.manifest = " + json.dumps(days) + ";\n", encoding="utf-8")
        print(f"manifest.js 갱신: {days[-3:]} … (총 {len(days)}호)")


if __name__ == "__main__":
    main()
