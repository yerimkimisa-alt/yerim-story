"""에이전트 팀 산출물(post.md) → 사이트 가이드 콘텐츠(site/content/guide/<slug>.md)

사용:  .\\.venv\\Scripts\\python.exe site\\tools\\import_post.py yerim-blog\\posts\\<폴더>\\post.md [--build]

변환 규칙
  - frontmatter: title·description(첫 문단 요약)·category(제품군 슬러그)·keywords(태그)·date·slug·source
  - `## 본문` 섹션만 가져온다. 시리즈 라벨(YERIM PRODUCT 등) 첫 줄은 뺀다
  - `[이미지 N]` + `캡션:` → site/static/img/<slug>/N.(jpg|png|webp) 가 있으면 <figure>, 없으면 제거(경고 출력)
  - `## 마무리 블록` 은 네이버용(댓글·이웃추가)이라 제외. 사이트는 템플릿 CTA 를 쓴다
  - 외부 링크의 utm_source=naverblog → utm_source=story (사이트 자체 추적)
  - 본문 안 blog.naver.com 내부 링크는 그대로 둔다 (외부 참조)
"""
import argparse
import io
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
ROOT = os.path.dirname(SITE)
CAT_MAP = {  # post.md category → site category slug
    "도어 · 중문": "door", "도어·중문": "door", "도어": "door", "중문": "innergate",
    "몰딩 · 필름 · 보드": "film", "키친": "kitchen", "창호": "window",
    "인테리어 가이드": "", "시공 사례": "", "드라마 · 셀럽 속 예림": "", "예림 뉴스 · 전시장": "",
}
PG_MAP = {"도어·중문": "innergate", "도어 · 중문": "innergate", "몰딩·필름·보드": "film", "키친": "kitchen", "창호": "window"}


def parse_front(text):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    fm = {}
    for ln in m.group(1).split("\n"):
        if ":" in ln:
            k, v = ln.split(":", 1); fm[k.strip()] = v.strip()
    return fm, m.group(2)


def section(body, name, end_names):
    stop = "|".join(re.escape(e) for e in end_names)
    m = re.search(rf"^## {re.escape(name)}\s*$(.*?)(?=^## (?:{stop})\s*$|\Z)", body, re.S | re.M)
    return m.group(1).strip() if m else ""


def make_thumb(md_text, slug):
    """본문 첫 사진으로 목록용 썸네일(4:3, 480x360)을 static/img/<slug>/thumb.jpg 에 만든다.
    build.py 는 이 파일이 있으면 목록에 쓰고, 없으면 원본을 쓴다 (Actions 빌드엔 PIL 이 없으므로 여기서 만들어 commit)."""
    m = re.search(r'<img src="(/img/[^"?]+)"', md_text)
    if not m: return
    src = os.path.join(SITE, "static", m.group(1).lstrip("/"))
    dst = os.path.join(SITE, "static", "img", slug, "thumb.jpg")
    try:
        from PIL import Image
    except ImportError:
        print("썸네일 건너뜀 — PIL 없음"); return
    im = Image.open(src).convert("RGB")
    w, h = im.size
    tw, th = (w, int(w * 3 / 4)) if w * 3 / 4 <= h else (int(h * 4 / 3), h)
    l, t = (w - tw) // 2, (h - th) // 2
    im.crop((l, t, l + tw, t + th)).resize((480, 360), Image.LANCZOS).save(dst, quality=82, optimize=True)
    print("thumb ->", os.path.relpath(dst, ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("post"); ap.add_argument("--build", action="store_true"); ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    fm, body = parse_front(io.open(a.post, encoding="utf-8").read())
    slug = fm.get("slug") or os.path.basename(os.path.dirname(a.post)).split("_", 1)[-1]
    main_md = section(body, "본문", ["마무리 블록", "이미지 브리프"])
    # 시리즈 라벨 제거
    main_md = re.sub(r"^\s*YERIM [A-Z ]+\s*\n", "", main_md, count=1)
    # 이미지 자리 → figure 또는 제거
    img_dir = os.path.join(SITE, "static", "img", slug)
    missing = []

    def img(m):
        n, cap = m.group(1), m.group(2).strip()
        for ext in ("jpg", "jpeg", "png", "webp"):
            if os.path.exists(os.path.join(img_dir, f"{n}.{ext}")):
                return f'<figure><img src="/img/{slug}/{n}.{ext}" alt="{cap}" loading="lazy"><figcaption>{cap}</figcaption></figure>\n'
        missing.append(f"{n}: {cap}")
        return ""
    main_md = re.sub(r"^\[이미지 (\d+)\]\s*\n캡션:\s*(.+)$", img, main_md, flags=re.M)
    main_md = main_md.replace("utm_source=naverblog", "utm_source=story")
    main_md = re.sub(r"\n{3,}", "\n\n", main_md).strip()
    # description = 첫 문단 요약(200자)
    first = next((p for p in re.split(r"\n\s*\n", main_md) if p.strip() and not p.startswith(("#", "<", "|"))), "")
    desc = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", first).replace("\n", " ").strip()
    desc = (desc[:160].rsplit(" ", 1)[0] + "…") if len(desc) > 160 else desc
    tags = [t.strip() for t in fm.get("tags", "").strip("[]").split(",") if t.strip()]
    # 네이버 카테고리(편성용)와 사이트 제품군(정보 구조용)은 다를 수 있다 — site_category 가 있으면 그것이 우선
    cat = fm.get("site_category", "").strip() or PG_MAP.get(fm.get("product_group", ""), "") or CAT_MAP.get(fm.get("category", ""), "")
    date = os.path.basename(os.path.dirname(a.post))[:8]
    date = f"{date[:4]}-{date[4:6]}-{date[6:8]}" if re.match(r"\d{8}", date) else ""
    out = f"""---
type: guide
title: {fm.get('title', slug)}
description: {desc}
category: {cat}
keywords: [{', '.join(tags)}]
date: {date}
updated: {date}
source: {a.post.replace(os.sep, '/')}
main_keyword: {fm.get('main_keyword', '')}
---

{main_md}
"""
    dst = os.path.join(SITE, "content", "guide", f"{slug}.md")
    if os.path.exists(dst) and not a.force:
        # 기존 파일의 updated 만 오늘로 갱신하며 덮어쓴다 (본문 재수입)
        pass
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    io.open(dst, "w", encoding="utf-8", newline="\n").write(out)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print("imported ->", os.path.relpath(dst, ROOT), f"| category={cat or '(없음)'} | tags={len(tags)} | {len(main_md)}자")
    make_thumb(out, slug)
    if missing:
        print(f"이미지 {len(missing)}장 없음 — site/static/img/{slug}/N.jpg 로 넣고 다시 실행하면 <figure> 로 들어간다:")
        for m in missing: print("   ", m)
    if a.build:
        r = subprocess.run([sys.executable, os.path.join(SITE, "build.py"), "--check"], cwd=ROOT)
        return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
