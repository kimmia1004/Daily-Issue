#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_artifact.py — claude.ai 아티팩트에 올릴 단일 HTML 파일을 만든다.

    python tools/build_artifact.py [YYYY-MM-DD ...] [--out work/artifact.html]
                                   [--snapshot-url https://kimmia1004.github.io/Daily-Issue/]

아티팩트는 외부 이미지·외부 스크립트가 보안 정책(CSP)으로 막혀 있어서
  · CSS/JS/데이터를 한 파일에 인라인으로 합치고
  · 기사 사진은 쓰지 않는다(제목·출처 옆 ‘원문 보기 ↗’ 링크로 대체).
날짜를 생략하면 manifest.js 의 가장 최신 호 1개만 담는다(스냅샷).
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import load_edition  # noqa: E402

FONTS = ("https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@400;600;700;900"
         "&family=Noto+Sans+KR:wght@400;500;700&family=Playfair+Display:ital,wght@0,700;0,900;1,400&display=swap")


def js_json(obj):
    # <script> 안에서 안전하도록 '</' 와 줄바꿈 문자(U+2028/2029) 처리
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("days", nargs="*")
    ap.add_argument("--out", default=str(ROOT / "work" / "artifact.html"))
    ap.add_argument("--snapshot-url", default="")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    man = re.findall(r"\d{4}-\d{2}-\d{2}", (ROOT / "data" / "manifest.js").read_text(encoding="utf-8"))
    days = args.days or man[-1:]
    editions = {d: load_edition(d) for d in days}
    for ed in editions.values():             # 아티팩트에서는 외부 사진을 쓰지 않는다
        items = [(ed.get("front") or {}).get("lead")] + list((ed.get("front") or {}).get("tops") or []) + list(ed.get("briefs") or [])
        items += [t.get("today") for t in ed.get("tracking") or []]
        for it in items:
            if it and it.get("image"):
                it["image"].pop("src", None)

    css = (ROOT / "assets" / "style.css").read_text(encoding="utf-8")
    app = (ROOT / "assets" / "app.js").read_text(encoding="utf-8")
    opts = {"photos": False, "print": False}
    if args.snapshot_url:
        opts["snapshot"] = args.snapshot_url

    html = f"""<title>데일리 이슈</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="{FONTS}" rel="stylesheet">
<style>
{css}
</style>
<div id="app" class="sheet"></div>
<script>
window.DAILY_OPTS = {js_json(opts)};
window.DAILY = {{ manifest: {js_json(days)}, editions: {js_json(editions)} }};
</script>
<script>
{app}
</script>
"""
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8", newline="\n")
    print(f"만들었습니다: {out}  ({out.stat().st_size / 1024:.0f} KB, 호 {len(days)}개: {', '.join(days)})")


if __name__ == "__main__":
    main()
