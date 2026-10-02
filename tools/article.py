#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""article.py — 기사 URL에서 제목·발행시각·대표이미지·본문 일부를 뽑는 도구 (표준 라이브러리만 사용)

    python tools/article.py URL [URL ...] [--chars 1800] [--no-image-check] [--json]

각 기사마다 출력: 제목 / 매체 / 발행시각 / 대표이미지(+크기·용량 점검) / 요약문 / 본문 앞부분
본문은 JSON-LD(articleBody) → <p> 문단 → 긴 텍스트 노드 순으로 추출합니다.
"""
import argparse
import concurrent.futures as cf
import html
import json
import re
import struct
import sys
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
SKIP_TAGS = {"script", "style", "nav", "footer", "aside", "header", "noscript", "form", "figcaption", "button", "select"}
BOILER = re.compile(r"무단\s*전재|저작권|All rights reserved|Copyright|구독|재배포|기자\s*$|@[\w\.]+\.(com|kr|net)", re.I)


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.ld, self.paras, self.nodes = {}, [], [], []
        self.title, self._in_title, self._in_ld, self._skip, self._p = "", False, False, 0, None

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key and a.get("content") and key not in self.meta:
                self.meta[key] = a["content"].strip()
        elif tag == "title":
            self._in_title = True
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_ld = True
            self.ld.append("")
        elif tag in SKIP_TAGS:
            self._skip += 1
        elif tag == "p" and not self._skip:
            self._p = []

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script":
            if self._in_ld:  # ld+json 스크립트는 start에서 _skip을 올리지 않았음
                self._in_ld = False
            elif self._skip:
                self._skip -= 1
        elif tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag == "p" and self._p is not None:
            t = re.sub(r"\s+", " ", "".join(self._p)).strip()
            if len(t) >= 25:
                self.paras.append(t)
            self._p = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._in_ld:
            self.ld[-1] += data
        elif not self._skip:
            if self._p is not None:
                self._p.append(data)
            t = re.sub(r"\s+", " ", data).strip()
            if len(t) >= 40:
                self.nodes.append(t)


def get(url, timeout=25, max_bytes=2_500_000, headers=None):
    h = {"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9", "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.geturl(), dict(r.headers), r.read(max_bytes)


def decode_html(data, headers):
    cands = []
    m = re.search(r"charset=([\w\-]+)", headers.get("Content-Type", ""), re.I)
    if m:
        cands.append(m.group(1))
    m = re.search(rb'<meta[^>]+charset=["\']?([\w\-]+)', data[:4000], re.I)
    if m:
        cands.append(m.group(1).decode("ascii", "ignore"))
    cands += ["utf-8", "cp949"]
    for enc in cands:
        enc = "cp949" if enc.lower() in ("euc-kr", "euckr", "ks_c_5601-1987") else enc
        try:
            return data.decode(enc)
        except Exception:  # noqa: BLE001
            continue
    return data.decode("utf-8", "replace")


def jsonld_article(blocks):
    found = {}

    def walk(o):
        if isinstance(o, list):
            for x in o:
                walk(x)
        elif isinstance(o, dict):
            t = o.get("@type")
            ts = t if isinstance(t, list) else [t]
            if any(isinstance(x, str) and "Article" in x for x in ts):
                for k in ("articleBody", "datePublished", "headline", "image"):
                    if o.get(k) and k not in found:
                        found[k] = o[k]
            for v in o.values():
                if isinstance(v, (list, dict)):
                    walk(v)
    for b in blocks:
        try:
            walk(json.loads(b))
        except Exception:  # noqa: BLE001
            continue
    return found


def image_size(b):
    try:
        if b[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", b[16:24])
        if b[:6] in (b"GIF87a", b"GIF89a"):
            return struct.unpack("<HH", b[6:10])
        if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
            kind = b[12:16]
            if kind == b"VP8X":
                return 1 + int.from_bytes(b[24:27], "little"), 1 + int.from_bytes(b[27:30], "little")
            if kind == b"VP8 ":
                return struct.unpack("<HH", b[26:30])[0] & 0x3FFF, struct.unpack("<HH", b[26:30])[1] & 0x3FFF
            if kind == b"VP8L":
                bits = int.from_bytes(b[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if b[:2] == b"\xff\xd8":
            i = 2
            while i < len(b) - 9:
                if b[i] != 0xFF:
                    i += 1
                    continue
                m = b[i + 1]
                if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
                    i += 2
                    continue
                if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
                    h, w = struct.unpack(">HH", b[i + 5:i + 9])
                    return w, h
                i += 2 + struct.unpack(">H", b[i + 2:i + 4])[0]
    except Exception:  # noqa: BLE001
        pass
    return None


def check_image(url):
    """이미지 URL이 실제로 열리는지·충분히 큰지 점검 → dict"""
    try:
        code, final, hdr, data = get(url, timeout=20, max_bytes=262144, headers={"Accept": "image/*,*/*;q=0.8"})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    ctype = hdr.get("Content-Type", "").split(";")[0].strip()
    total = None
    cr = hdr.get("Content-Range") or ""
    m = re.search(r"/(\d+)$", cr)
    if m:
        total = int(m.group(1))
    elif hdr.get("Content-Length", "").isdigit():
        total = int(hdr["Content-Length"])
    size = image_size(data)
    ok = ctype.startswith("image/") and (total or len(data)) > 4000
    return {"ok": ok, "type": ctype, "bytes": total or len(data), "size": list(size) if size else None, "final": final}


def extract(url, chars, do_check):
    out = {"url": url}
    try:
        code, final, hdr, raw = get(url)
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"
        return out
    out["final_url"] = final
    p = Page()
    p.feed(decode_html(raw, hdr))
    m = p.meta
    ld = jsonld_article(p.ld)
    out["title"] = html.unescape(m.get("og:title") or ld.get("headline") or p.title).strip()
    out["site"] = m.get("og:site_name", "")
    out["published"] = (m.get("article:published_time") or ld.get("datePublished") or m.get("pubdate")
                        or m.get("date") or m.get("og:regdate") or "")
    out["description"] = html.unescape(m.get("og:description") or m.get("description") or "").strip()
    img = m.get("og:image") or m.get("twitter:image") or ""
    if not img:
        li = ld.get("image")
        li = li[0] if isinstance(li, list) and li else li
        img = (li.get("url") if isinstance(li, dict) else li) or ""
    img = urljoin(final, html.unescape(img)) if img else ""
    out["image"] = img
    if img and do_check:
        out["image_check"] = check_image(img)

    body = ld.get("articleBody") if isinstance(ld.get("articleBody"), str) else ""
    body = re.sub(r"\s+", " ", html.unescape(body)).strip()
    if len(body) < 200:
        paras = [t for t in p.paras if not BOILER.search(t)]
        body = "\n".join(dict.fromkeys(paras))
    if len(body) < 400:
        nodes = [t for t in p.nodes if not BOILER.search(t)]
        alt = "\n".join(dict.fromkeys(nodes))
        if len(alt) > len(body):
            body = alt
    out["text_len"] = len(body)
    out["text"] = body[:chars]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--chars", type=int, default=1800)
    ap.add_argument("--no-image-check", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda u: extract(u, args.chars, not args.no_image_check), args.urls))
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=1))
        return
    for r in results:
        print("=" * 100)
        print("URL      :", r["url"])
        if "error" in r:
            print("ERROR    :", r["error"])
            continue
        print("제목     :", r["title"])
        print("매체     :", r["site"], "| 발행:", r["published"])
        ic = r.get("image_check")
        if r["image"]:
            tag = ""
            if ic:
                tag = (f"  [{'OK' if ic.get('ok') else 'WARN'} {ic.get('type', '')} "
                       f"{ic.get('size') or '?'} {ic.get('bytes', '?')}B {ic.get('error', '')}]")
            print("이미지   :", r["image"] + tag)
        else:
            print("이미지   : (없음)")
        print("요약문   :", r["description"][:300])
        print(f"본문({r['text_len']}자 중 {len(r['text'])}자):")
        print(r["text"])


if __name__ == "__main__":
    main()
