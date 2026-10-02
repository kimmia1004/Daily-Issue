#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""publish_web.py — 새 호를 GitHub(Pages)에 올린다.

    python tools/publish_web.py 2026-10-02

하는 일
  1. 그 호를 오프라인으로 다시 검사(tools/validate.py)하고, manifest.js 에 등록돼 있는지 확인한다. 통과하지 못하면 올리지 않는다.
  2. data/ 폴더의 변경분(새 호 + manifest.js)만 커밋하고 `git push` 한다. 사이트 코드(index.html, assets/)는 건드리지 않는다.
  3. 푸시가 끝나면 웹 주소를 출력한다. (GitHub Pages 반영까지 보통 1~2분)

푸시가 실패해도 로컬 호 파일은 그대로 남으므로, 사유만 보고하고 끝내면 된다(다음 실행 때 함께 올라간다).
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRAILER = "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"


def run(cmd, timeout=120, check=False):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}\n{r.stdout}{r.stderr}")
    return r


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", sys.argv[1]):
        sys.exit("사용법: python tools/publish_web.py YYYY-MM-DD")
    day = sys.argv[1]
    sys.stdout.reconfigure(encoding="utf-8")

    # 1) 검사
    v = run([sys.executable, "tools/validate.py", day, "--offline"], timeout=120)
    print(v.stdout.strip().splitlines()[-1] if v.stdout.strip() else "")
    if v.returncode != 0:
        sys.exit(f"✗ {day} 호가 검사를 통과하지 못해 올리지 않습니다.\n{v.stdout}")
    man = (ROOT / "data" / "manifest.js").read_text(encoding="utf-8")
    if day not in man:
        sys.exit(f"✗ data/manifest.js 에 {day} 가 없습니다. 먼저 `python tools/validate.py {day} --publish` 를 실행하세요.")

    # 2) 커밋 + 푸시
    if run(["git", "rev-parse", "--is-inside-work-tree"]).returncode != 0:
        sys.exit("✗ 이 폴더는 git 저장소가 아닙니다.")
    run(["git", "add", "data"], check=True)
    if run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        print("변경 사항이 없어 올릴 것이 없습니다(이미 올라가 있음).")
    else:
        run(["git", "commit", "-m", f"{day} 호 발행\n\n{TRAILER}"], check=True)
        print(f"커밋: {day} 호 발행")
    pull = run(["git", "pull", "--rebase", "--autostash", "origin", "main"], timeout=120)
    if pull.returncode != 0 and "couldn't find remote ref" not in pull.stderr:
        sys.exit(f"✗ 원격 변경을 가져오지 못했습니다(충돌 가능):\n{pull.stderr.strip()}")
    try:
        push = run(["git", "push", "origin", "main"], timeout=180)
    except subprocess.TimeoutExpired:
        sys.exit("✗ git push 가 180초 안에 끝나지 않았습니다(로그인 창 대기 등). 로컬 호는 그대로 있습니다.")
    if push.returncode != 0:
        sys.exit(f"✗ git push 실패(로컬 호는 그대로 있습니다):\n{push.stderr.strip()}")
    print("푸시 완료")

    # 3) 웹 주소
    url = run(["git", "remote", "get-url", "origin"]).stdout.strip()
    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", url)
    if m:
        print(f"웹 주소: https://{m.group(1).lower()}.github.io/{m.group(2)}/  (반영까지 1~2분)")


if __name__ == "__main__":
    main()
