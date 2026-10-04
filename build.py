"""예림 스토리 — 정적 사이트 생성기 (GEO 원칙 구현)

실행:  .\\.venv\\Scripts\\python.exe site\\build.py        → site/dist/ 생성
       .\\.venv\\Scripts\\python.exe site\\build.py --check → 빌드 후 GEO 체크리스트 점검

원칙 (예림_AI검색_GEO_구축전략.docx §3)
  1 키워드별 독립 URL        content/ 의 파일 경로 = URL (guide/x.md → /guide/x/)
  2 HTML 텍스트 우선          모든 사양·설명·FAQ 를 본문 텍스트로. 이미지는 보조
  3 크롤러 접근 허용          robots.txt 를 config.json 정책으로 생성
  4 구조화 데이터            Organization · Product · FAQPage · BreadcrumbList · Article JSON-LD
  5 색인 신호               sitemap.xml(lastmod) · feed.xml · llms.txt
  6 질문형 지식 콘텐츠        guide 타입 = 질문 하나에 완결 답변 + FAQ
  8 지속 갱신               frontmatter updated 가 lastmod·dateModified 가 된다
"""
import argparse
import html
import io
import json
import os
import re
import shutil
import sys
from datetime import datetime, date

import markdown

HERE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(HERE, "content")
STATIC = os.path.join(HERE, "static")
DIST = os.path.join(HERE, "dist")
CFG = json.load(io.open(os.path.join(HERE, "config.json"), encoding="utf-8"))
BASE = CFG["base_url"].rstrip("/")
from urllib.parse import urlparse as _up
PREFIX = _up(BASE).path.rstrip("/")          # 예: github.io/yerim-story 로 서비스할 때 "/yerim-story", 커스텀 도메인이면 ""
CUSTOM_DOMAIN = not _up(BASE).hostname.endswith("github.io")


def href(u: str) -> str:
    """사이트 내부 경로에 base_url 의 경로 접두를 붙인다."""
    return u if u.startswith("http") else PREFIX + u


_VER = {}


def asset_ver(path: str) -> str:
    """static/ 파일 내용 해시 8자리. GitHub Pages 는 max-age=600 캐시를 붙이므로,
    이미지·CSS 가 바뀌면 주소(?v=)도 바뀌게 해서 휴대폰·CDN 이 옛 파일을 계속 쓰지 않게 한다."""
    if path not in _VER:
        import hashlib
        fs = os.path.join(STATIC, path.lstrip("/").split("?")[0])
        _VER[path] = hashlib.md5(open(fs, "rb").read()).hexdigest()[:8] if os.path.isfile(fs) else ""
    return _VER[path]


def static_url(path: str) -> str:
    v = asset_ver(path)
    return href(path) + (f"?v={v}" if v else "")
ORG = CFG["organization"]
CATS = {c["slug"]: c for c in CFG["categories"]}
TYPE_LABEL = {"guide": "가이드", "product": "제품", "group": "제품군", "category": "제품 분류", "news": "소식", "page": "", "home": "", "section": ""}

# ---------------------------------------------------------------- frontmatter
def parse_front(text: str):
    """YAML 부분집합: 스칼라 / 인라인 리스트 / 블록 리스트(스칼라·dict)."""
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    fm, body = {}, m.group(2)
    lines = m.group(1).split("\n")
    i = 0

    def scalar(v):
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            return [scalar(x) for x in re.split(r",\s*", v[1:-1]) if x.strip()]
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        if v in ("true", "false"):
            return v == "true"
        return v

    while i < len(lines):
        ln = lines[i]
        if not ln.strip() or ln.lstrip().startswith("#"):
            i += 1; continue
        km = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", ln)
        if not km:
            i += 1; continue
        key, val = km.group(1), km.group(2)
        if val.strip():
            fm[key] = scalar(val); i += 1; continue
        # 블록
        items, i = [], i + 1
        while i < len(lines) and (lines[i].startswith("  ") or not lines[i].strip()):
            s = lines[i]
            if not s.strip():
                i += 1; continue
            dm = re.match(r"^\s*-\s+(.*)$", s)
            if dm:
                first = dm.group(1)
                kv = re.match(r"^([\w-]+):\s*(.*)$", first)
                if kv:  # dict 항목
                    d = {kv.group(1): scalar(kv.group(2))}
                    i += 1
                    while i < len(lines) and re.match(r"^\s{4,}[\w-]+:", lines[i]):
                        k2, v2 = re.match(r"^\s*([\w-]+):\s*(.*)$", lines[i]).groups()
                        d[k2] = scalar(v2); i += 1
                    items.append(d); continue
                items.append(scalar(first)); i += 1; continue
            i += 1
        fm[key] = items
    return fm, body


# ---------------------------------------------------------------- load
def load_pages():
    pages = []
    for root, _, files in os.walk(CONTENT):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, CONTENT).replace("\\", "/")
            fm, body = parse_front(io.open(path, encoding="utf-8").read())
            url = "/" if rel == "index.md" else "/" + re.sub(r"(/index)?\.md$", "", rel) + "/"
            mtime = datetime.fromtimestamp(os.path.getmtime(path)).date().isoformat()
            p = dict(fm)
            p.update(url=url, rel=rel, body_md=body, mtime=mtime,
                     type=fm.get("type") or infer_type(rel),
                     title=fm.get("title") or os.path.splitext(fn)[0],
                     description=fm.get("description", ""),
                     draft=bool(fm.get("draft", False)),
                     date=str(fm.get("date") or mtime), updated=str(fm.get("updated") or fm.get("date") or mtime))
            segs = [s for s in url.split("/") if s]
            p["category"] = fm.get("category") or (segs[0] if segs and segs[0] in CATS else "")
            # 대표 이미지: frontmatter image 가 없으면 본문 첫 사진 — 목록 썸네일·og:image·JSON-LD 에 쓴다
            if not p.get("image"):
                m = re.search(r'<img src="(/img/[^"?]+)"(?:[^>]*?alt="([^"]*)")?', body)
                if m and os.path.isfile(os.path.join(STATIC, m.group(1).lstrip("/"))):
                    p["image"], p["image_alt"] = m.group(1), m.group(2) or ""
            pages.append(p)
    return pages


def infer_type(rel):
    if rel == "index.md": return "home"
    if rel.startswith("guide/"): return "section" if rel.endswith("index.md") else "guide"
    if rel.startswith("news/"): return "section" if rel.endswith("index.md") else "news"
    segs = rel[:-3].split("/")
    if len(segs) == 1: return "category" if segs[0] in CATS else "page"
    if len(segs) == 2: return "group"
    return "product"


# ---------------------------------------------------------------- helpers
E = html.escape
from markdown.extensions.toc import TocExtension, slugify_unicode
# toc: 본문 h2·h3 에 한글 id 를 붙인다 — AI 검색이 문단 단위로 인용할 때 #앵커 딥링크가 생기고, 가이드 목차의 재료가 된다
MD = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists", "attr_list", TocExtension(slugify=slugify_unicode, toc_depth="2-3")])


def md(text):
    MD.reset()
    out = MD.convert(text or "")
    # 본문 이미지: 내용 해시 버전을 붙인다 (사진을 바꾸면 주소가 바뀌어 캐시된 옛 사진이 안 뜬다)
    out = re.sub(r'src="(/img/[^"?]+)"', lambda m: f'src="{m.group(1)}?v={asset_ver(m.group(1))}"' if asset_ver(m.group(1)) else m.group(0), out)
    # 본문(마크다운·figure) 안의 사이트 절대경로(/img/…, /guide/…)에도 base_url 경로 접두를 붙인다
    if PREFIX:
        out = re.sub(r'(src|href)="/(?!/)', lambda m: f'{m.group(1)}="{PREFIX}/', out)
    out = out.replace("<table>", '<div class="tbl"><table>').replace("</table>", "</table></div>")   # 폰에서 넓은 표는 가로 스크롤
    return newtab(out)   # 글 본문 안의 링크만 새 창 — 메뉴·목록·카드·푸터는 같은 창 (2026-09-27)


def abs_url(u):
    return u if u.startswith("http") else BASE + u


def fmt_date(s):
    return s[:10]


def crumbs_for(page, by_url):
    segs = [s for s in page["url"].split("/") if s]
    items = [("홈", "/")]
    acc = ""
    for s in segs:
        acc += "/" + s
        u = acc + "/"
        if u == page["url"]:
            items.append((page["title"], u)); break
        # 섹션(가이드·소식)은 짧은 이름으로 — 섹션 페이지 제목은 길어서 경로·BreadcrumbList 에 맞지 않는다
        t = {"/guide/": "가이드", "/news/": "소식"}.get(u) or by_url.get(u, {}).get("title") or CATS.get(s, {}).get("name") or s
        items.append((t, u))
    return items


def jsonld_org():
    a = ORG["address"]
    return {"@context": "https://schema.org", "@type": "Organization", "@id": BASE + "/#organization",
            "name": ORG["name"], "legalName": ORG["legal_name"], "alternateName": ORG["alternate_name"],
            "url": ORG["url"], "logo": ORG["logo"], "foundingDate": ORG["founding_date"], "sameAs": ORG["same_as"],
            "address": {"@type": "PostalAddress", "streetAddress": a["street"], "addressLocality": a["locality"], "addressRegion": a["region"], "addressCountry": a["country"]},
            "subOrganization": [{"@type": "Organization", "name": n} for n in ORG["sub_organizations"]],
            "contactPoint": {"@type": "ContactPoint", "contactType": "customer service", "url": ORG["contact_url"]}}


def jsonld_crumbs(items):
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i + 1, "name": n, "item": abs_url(u)} for i, (n, u) in enumerate(items)]}


def jsonld_faq(faq):
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": q["q"], "acceptedAnswer": {"@type": "Answer", "text": q["a"]}} for q in faq]}


def jsonld_article(p):
    d = {"@context": "https://schema.org", "@type": "Article", "headline": p["title"], "description": p["description"],
         "datePublished": p["date"], "dateModified": p["updated"], "inLanguage": CFG["language"],
         "mainEntityOfPage": abs_url(p["url"]), "author": {"@type": "Organization", "name": ORG["name"], "url": ORG["url"]},
         "publisher": {"@type": "Organization", "name": ORG["name"], "logo": {"@type": "ImageObject", "url": ORG["logo"]}}}
    if p.get("keywords"): d["keywords"] = ", ".join(p["keywords"])
    if p.get("image"): d["image"] = abs_url(p["image"])
    return d


def jsonld_product(p):
    d = {"@context": "https://schema.org", "@type": "Product", "name": p["title"], "description": p["description"],
         "brand": {"@type": "Brand", "name": ORG["alternate_name"]}, "manufacturer": {"@type": "Organization", "name": ORG["legal_name"]},
         "url": abs_url(p["url"]), "category": CATS.get(p["category"], {}).get("en", p["category"])}
    if p.get("model"): d["model"] = p["model"]; d["sku"] = p["model"]
    if p.get("image"): d["image"] = abs_url(p["image"])
    if p.get("specs"):
        d["additionalProperty"] = [{"@type": "PropertyValue", "name": s.get("name", ""), "value": s.get("value", "")} for s in p["specs"] if s.get("value")]
    return d


# ---------------------------------------------------------------- render
_A = re.compile(r'<a (?![^>]*\btarget=)([^>]*\bhref="(?!#)[^"]*"[^>]*)>')


def newtab(html):
    """페이지 안 앵커(#…)만 빼고 모든 링크에 target=_blank. noopener 로 원래 창을 새 창이 건드리지 못하게."""
    return _A.sub(r'<a \1 target="_blank" rel="noopener">', html)


_TAG = re.compile(r"(<[^>]+>)")
_URL = re.compile(r"https?://[^\s<>\"'()\[\]]+[^\s<>\"'()\[\].,;:·]")


# 출처의 "예림 홈페이지 uid 2048" 은 홈페이지 제품 상세 번호 — 방문자에겐 뜻이 없으니 "제품설명" 링크로 바꿔 보인다 (2026-09-28)
_UID = re.compile(r"(?:예림 )?(?:홈페이지 )?\buid ?(\d{2,5}(?:~\d{2,5})?(?:·\d{2,5}(?:~\d{2,5})?)*)")


def uid_links(m):
    nums = [x.split("~")[0] for x in m.group(1).split("·")]   # 범위(2210~2226)는 첫 제품으로
    a = lambda n, t: f'<a href="{ORG["url"]}/kor/products/products-view.html?uid={n}" target="_blank" rel="noopener">{t}</a>'
    return a(nums[0], "제품설명") if len(nums) == 1 else "제품설명 " + " · ".join(a(n, str(i)) for i, n in enumerate(nums, 1))


def url_label(u):
    """예림 홈페이지 주소는 긴 URL 대신 뜻으로 보인다. 다른 사이트 주소는 그대로."""
    if "yerim.net" not in u: return u
    for key, name in (("products-view", "제품설명"), ("products-list", "예림 홈페이지 제품 목록"), ("/story/", "예림 홈페이지 스토리")):
        if key in u: return name
    return "예림 홈페이지"


def autolink(html):
    """화면에 글자로만 찍힌 주소(사양 출처·FAQ 등)를 새 창 링크로. 이미 <a>·<script>·<code>·<style> 안인 것은 그대로."""
    out, skip = [], 0
    for part in _TAG.split(html):
        if part.startswith("<"):
            t = re.match(r"</?\s*(\w+)", part)
            if t and t.group(1).lower() in ("a", "script", "code", "pre", "style"):
                skip += -1 if part.startswith("</") else (0 if part.endswith("/>") else 1)
            out.append(part)
        else:
            out.append(part if skip > 0 else _UID.sub(uid_links, _URL.sub(lambda m: f'<a href="{m.group(0)}" target="_blank" rel="noopener">{url_label(m.group(0))}</a>', part)))
    return "".join(out)


def base(p, body, by_url, extra_ld=()):
    body = autolink(body)
    crumbs = crumbs_for(p, by_url)
    lds = [jsonld_crumbs(crumbs)] + list(extra_ld)
    if p["type"] in ("home", "page"):
        lds.insert(0, jsonld_org())
    title = p["title"] if p["type"] == "home" else f'{p["title"]} — {CFG["site_name"]}'
    nav = "".join(f'<a href="{href("/" + c["slug"] + "/")}"{" aria-current=\"page\"" if p["category"] == c["slug"] else ""}>{E(c["name"])}</a>' for c in CFG["categories"])
    nav += f'<a href="{href("/guide/")}">가이드</a><a href="{href("/about/")}">예림 소개</a>'
    crumbs_html = "" if p["type"] == "home" else '<nav class="crumbs" aria-label="경로"><ol>' + "".join(
        f'<li>{E(n)}</li>' if u == p["url"] else f'<li><a href="{href(u)}">{E(n)}</a></li>' for n, u in crumbs) + "</ol></nav>"
    robots = '<meta name="robots" content="noindex,nofollow">' if p["draft"] else '<meta name="robots" content="index,follow,max-snippet:-1,max-image-preview:large">'
    img = p.get("image") or CFG["categories"][0]["cover"]   # 대표 이미지가 없으면 첫 제품 분류 커버 — 공유 카드가 비지 않게
    og_img = f'<meta property="og:image" content="{E(abs_url(img))}">'
    if p["type"] == "home":
        lds.insert(1, jsonld_website())
    ld = "".join(f'<script type="application/ld+json">{json.dumps(x, ensure_ascii=False)}</script>' for x in lds)
    a = ORG["address"]
    page = f"""<!DOCTYPE html>
<html lang="{CFG['language']}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#FBFAF7" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#141311" media="(prefers-color-scheme: dark)">
<meta name="format-detection" content="telephone=no">
<title>{E(title)}</title>
<meta name="description" content="{E(p['description'])}">
<link rel="canonical" href="{E(abs_url(p['url']))}">
{robots}
<meta property="og:type" content="{'article' if p['type'] in ('guide','news') else 'website'}">
<meta property="og:title" content="{E(p['title'])}">
<meta property="og:description" content="{E(p['description'])}">
<meta property="og:url" content="{E(abs_url(p['url']))}">
<meta property="og:site_name" content="{E(CFG['site_name'])}">
<meta property="og:locale" content="ko_KR">
{og_img}
<meta name="twitter:card" content="summary_large_image">
<link rel="alternate" type="application/rss+xml" title="{E(CFG['site_name'])}" href="{href('/feed.xml')}">
<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css">
<link rel="stylesheet" href="{static_url('/style.css')}">
{ld}
</head>
<body class="t-{p['type']}">
<a class="skip" href="#main">본문 바로가기</a>
<header class="site"><div class="wrap">
  <a class="brand" href="{href('/')}"><span class="mark" aria-hidden="true">Y</span>{E(CFG['site_name'])}<small>{E(CFG['site_name_en'])}</small></a>
  <nav aria-label="제품군">{nav}</nav>
</div></header>
<main id="main"><div class="wrap">
{crumbs_html}
{body}
</div></main>
<footer class="site"><div class="wrap">
  <a class="brand" href="{href('/')}"><span class="mark" aria-hidden="true">Y</span>{E(CFG['site_name'])}</a>
  <p class="tag">{E(CFG['tagline'])}</p>
  <div class="ent">{E(ORG['legal_name'])} · {E(a['region'])} {E(a['locality'])} {E(a['street'])} · 설립 {E(ORG['founding_date'])}</div>
  <div>공식 홈페이지 <a href="{E(ORG['url'])}">{E(ORG['url'].replace('https://',''))}</a> · <a href="{E(ORG['contact_url'])}">온라인 문의</a> · <a href="{href('/sitemap.xml')}">sitemap</a> · <a href="{href('/feed.xml')}">RSS</a> · <a href="{href('/llms.txt')}">llms.txt</a></div>
  <div>이 사이트의 제품 사양은 예림 공식 자료를 기준으로 하며, 수정일이 표기됩니다. 시험 성적·인증은 해당 페이지에 발행일과 적용 모델을 함께 적습니다.</div>
</div></footer>
</body>
</html>"""
    return page


def toc_html(tokens):
    """가이드 목차 — h2 가 3개 이상일 때만. JS 없이 <details> 로 접힌다."""
    h2 = [t for t in tokens if t["level"] == 2]
    if len(h2) < 3: return ""
    return '<details class="toc"><summary>목차</summary><ol>' + "".join(f'<li><a href="#{E(t["id"])}">{E(t["name"])}</a></li>' for t in h2) + "</ol></details>"


def jsonld_website():
    return {"@context": "https://schema.org", "@type": "WebSite", "@id": BASE + "/#website", "name": CFG["site_name"], "alternateName": CFG["site_name_en"],
            "url": BASE + "/", "inLanguage": CFG["language"], "description": CFG["tagline"], "publisher": {"@id": BASE + "/#organization"}}


def card(p):
    k = TYPE_LABEL.get(p["type"], "")
    return f'<div class="card"><span class="k">{E(k)}{" · " + E(p["model"]) if p.get("model") else ""}</span><a href="{href(p["url"])}">{E(p["title"])}</a><p>{E(p["description"][:90])}</p></div>'


def newest(q):
    """목록 정렬 키 — 수정일, 같은 날이면 게시 시각(published_at, import_post.py 가 기록)."""
    return (q["updated"], str(q.get("published_at") or ""))


def gallery_card(c, p):
    """메인 제품군 갤러리 카드 — 대표 이미지 + 제품군 이름 + 한 줄 설명. 분류 라벨은 넣지 않는다."""
    img = f'<img src="{static_url(c["cover"])}" alt="{E(c.get("cover_alt") or c["name"])}" loading="lazy" width="900" height="675">' if c.get("cover") else '<span class="ph"></span>'
    desc = f'<p>{E(p["description"])}</p>' if p and p.get("description") else ""
    return f'<a class="gcard" href="{href("/" + c["slug"] + "/")}">{img}<span class="gt">{E(c["name"])}</span>{desc}</a>'


def list_items(ps):
    def thumb(p):
        if not p.get("image") or p["type"] not in ("guide", "news"): return ""
        t = os.path.dirname(p["image"]) + "/thumb.jpg"   # import_post.py 가 만든 목록용 썸네일, 없으면 원본
        src = t if os.path.isfile(os.path.join(STATIC, t.lstrip("/"))) else p["image"]
        return f'<a class="th" href="{href(p["url"])}" tabindex="-1" aria-hidden="true"><img src="{static_url(src)}" alt="{E(p.get("image_alt") or p["title"])}" loading="lazy" width="160" height="120"></a>'
    return '<ul class="list">' + "".join(
        f'<li{" class=\"has-th\"" if thumb(p) else ""}>{thumb(p)}<div><a href="{href(p["url"])}">{E(p["title"])}</a><span class="d">{E(p["description"])}</span></div></li>' for p in ps) + "</ul>"


def faq_html(faq):
    if not faq: return ""
    return '<h2 id="faq">자주 묻는 질문</h2><div class="faq">' + "".join(
        f'<details><summary>{E(q["q"])}</summary><p>{E(q["a"])}</p></details>' for q in faq) + "</div>"


def cta_html(p, by_url):
    cat = CATS.get(p["category"])
    links = []
    if cat:
        links.append(f'<a href="{href("/" + cat["slug"] + "/")}">예림 {E(cat["name"])} 전체</a>')
    links.append(f'<a href="{E(ORG["url"])}">공식 홈페이지 제품 정보</a>')
    links.append(f'<a href="{E(ORG["contact_url"])}">온라인 문의·전시장</a>')
    return f'<aside class="cta"><b>더 알아보기</b><div>{"".join(links)}</div></aside>'


def related_html(p, pages):
    out = []
    prods = [q for q in pages if q["type"] == "product" and not q["draft"] and (q["url"].strip("/").split("/")[-1] in (p.get("products") or []) or (p.get("products") is None and False))]
    if p.get("products"):
        prods = [q for q in pages if q["type"] == "product" and not q["draft"] and q["url"].strip("/").split("/")[-1] in p["products"]]
    if prods:
        out.append('<div class="related"><h2>관련 제품</h2><div class="grid">' + "".join(card(q) for q in prods) + "</div></div>")
    rel = [q for q in pages if q["url"] in (p.get("related") or []) and not q["draft"]]
    if not rel and p["type"] in ("guide", "product"):
        rel = [q for q in pages if q["type"] == "guide" and q["url"] != p["url"] and q["category"] == p["category"] and not q["draft"]][:4]
    if rel:
        out.append('<div class="related"><h2>함께 읽기</h2>' + list_items(rel) + "</div>")
    return "".join(out)


def render(p, pages, by_url):
    t = p["type"]
    meta = []
    if t in ("guide", "news", "product"):
        meta.append(f'<span class="chip">{E(TYPE_LABEL[t])}</span><span><b>발행</b> <time datetime="{fmt_date(p["date"])}">{fmt_date(p["date"])}</time></span><span><b>수정</b> <time datetime="{fmt_date(p["updated"])}">{fmt_date(p["updated"])}</time></span>')
        if p["category"]: meta.append(f'<span><b>제품군</b> {E(CATS[p["category"]]["name"])}</span>')
        if p.get("model"): meta.append(f'<span><b>모델</b> {E(p["model"])}</span>')
    meta_html = f'<div class="meta">{"".join(meta)}</div>' if meta else ""
    # 가이드는 description 이 첫 문단에서 파생되므로 화면에 또 찍지 않는다 (meta·JSON-LD 에만). 중복 노출 방지.
    dup = p["description"][:40] in p["body_md"].replace("\n", " ") if p["description"] else False
    lead = f'<p class="lead">{E(p["description"])}</p>' if p["description"] and t != "home" and not dup else ""
    draft = '<div class="notice"><b>검증 전 초안</b> — 이 페이지는 사실 검증이 끝나지 않아 검색에 노출되지 않습니다(noindex). 확인 후 frontmatter 의 draft 를 false 로 바꾸면 공개됩니다.</div>' if p["draft"] else ""
    body = md(p["body_md"])
    toc = toc_html(MD.toc_tokens if hasattr(MD, "toc_tokens") else [])
    tags = f'<div class="tags">{"".join("<span>#" + E(k) + "</span>" for k in p.get("keywords") or [])}</div>' if p.get("keywords") else ""
    lds = []
    if t == "home":
        cats = "".join(gallery_card(c, by_url.get(f"/{c['slug']}/")) for c in CFG["categories"])
        all_guides = sorted([q for q in pages if q["type"] == "guide" and not q["draft"]], key=newest, reverse=True)
        guides = all_guides[:8]
        prods = [q for q in pages if q["type"] == "product" and not q["draft"]][:6]
        inner = f'<section class="intro"><p class="eyebrow">{E(CFG["site_name_en"])} · {E(ORG["legal_name"])} 공식 지식 사이트</p><h1>{E(p["title"])}</h1>{lead}{body}<p class="go"><a class="btn" href="{href("/guide/")}">가이드 전체 보기</a><a class="btn ghost" href="{href("/about/")}">예림 소개</a></p></section>'
        inner += f'<h2>제품군</h2><div class="gallery">{cats}</div>'
        if guides: inner += f'<h2>최근 가이드 <span class="n">{len(all_guides)}</span></h2>{list_items(guides)}<p class="more"><a href="{href("/guide/")}">가이드 {len(all_guides)}편 모두 보기 →</a></p>'
        if prods: inner += f'<h2>제품</h2><div class="grid">{"".join(card(q) for q in prods)}</div>'
        return base(p, inner, by_url)
    if t in ("category", "group", "section"):
        pre = p["url"]
        kids = [q for q in pages if q["url"] != pre and q["url"].startswith(pre) and not q["draft"]]
        groups = [q for q in kids if q["type"] == "group"]
        prods = [q for q in kids if q["type"] == "product"]
        guides = sorted([q for q in pages if q["type"] in ("guide", "news") and not q["draft"] and (q["url"].startswith(pre) or (t == "category" and q["category"] == p["category"]))], key=newest, reverse=True)
        hero = ""
        cat = CATS.get(p["category"]) if t == "category" else None
        if cat and cat.get("cover"):
            # 메인 갤러리와 같은 대표 이미지를 제품군 페이지 본문 첫머리에 — og:image 로도 쓴다
            alt = cat.get("cover_alt") or cat["name"]
            hero = f'<figure class="hero"><img src="{static_url(cat["cover"])}" alt="{E(alt)}" width="900" height="675"><figcaption>{E(alt)}</figcaption></figure>'
            p.setdefault("image", cat["cover"])
        inner = f'<h1>{E(p["title"])}</h1>{lead}{hero}{body}'
        if groups: inner += '<h2>제품군</h2><div class="grid">' + "".join(card(q) for q in groups) + "</div>"
        if prods: inner += '<h2>제품</h2><div class="grid">' + "".join(card(q) for q in prods) + "</div>"
        if guides: inner += f'<h2>가이드 <span class="n">{len(guides)}</span></h2>' + list_items(guides)   # 이 페이지에 걸린 가이드 수
        inner += faq_html(p.get("faq"))
        if p.get("faq"): lds.append(jsonld_faq(p["faq"]))
        return base(p, inner, by_url, lds)
    if t == "product":
        spec = ""
        if p.get("specs"):
            rows = "".join(f'<tr><th>{E(s.get("name",""))}</th><td>{E(s.get("value",""))}{("<span class=\"src\">" + E(s["source"]) + "</span>") if s.get("source") else ""}{("<br><small>" + E(s["note"]) + "</small>") if s.get("note") else ""}</td></tr>' for s in p["specs"])
            spec = f'<h2 id="spec">사양</h2><table class="spec"><tbody>{rows}</tbody></table>'
        docs = ""
        if p.get("docs"):
            docs = '<h2 id="docs">자료·인증</h2><ul>' + "".join(f'<li>{E(d.get("name",""))}{(" — " + E(d["date"])) if d.get("date") else ""}{(" · <a href=\"" + E(d["url"]) + "\">보기</a>") if d.get("url") else ""}</li>' for d in p["docs"]) + "</ul>"
        inner = f'<article><h1>{E(p["title"])}</h1>{meta_html}{draft}{lead}{body}{spec}{docs}{faq_html(p.get("faq"))}{tags}</article>{related_html(p, pages)}{cta_html(p, by_url)}'
        lds.append(jsonld_product(p))
        if p.get("faq"): lds.append(jsonld_faq(p["faq"]))
        return base(p, inner, by_url, lds)
    if t in ("guide", "news"):
        inner = f'<article><h1>{E(p["title"])}</h1>{meta_html}{draft}{lead}{toc}{body}{faq_html(p.get("faq"))}{tags}</article>{related_html(p, pages)}{cta_html(p, by_url)}'
        lds.append(jsonld_article(p))
        if p.get("faq"): lds.append(jsonld_faq(p["faq"]))
        return base(p, inner, by_url, lds)
    inner = f'<h1>{E(p["title"])}</h1>{lead}{body}{faq_html(p.get("faq"))}'
    if p.get("faq"): lds.append(jsonld_faq(p["faq"]))
    return base(p, inner, by_url, lds)


# ---------------------------------------------------------------- site files
def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    io.open(path, "w", encoding="utf-8", newline="\n").write(text)


def build_sitemap(pages):
    pub = [p for p in pages if not p["draft"]]
    items = "".join(f"  <url><loc>{E(abs_url(p['url']))}</loc><lastmod>{fmt_date(p['updated'])}</lastmod></url>\n" for p in sorted(pub, key=lambda x: x["url"]))
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{items}</urlset>\n'


def build_robots():
    lines = ["# 예림 스토리 robots.txt — 검색·AI 검색 크롤러 허용 (GEO 원칙 3)", ""]
    for ua in CFG["crawlers_allow"]:
        lines += [f"User-agent: {ua}", "Allow: /", ""]
    lines += [f"# AI 학습용 크롤러 — 정책: {CFG['training_policy']} (config.json training_policy)"]
    for ua in CFG["crawlers_training"]:
        lines += [f"User-agent: {ua}", "Allow: /" if CFG["training_policy"] == "allow" else "Disallow: /", ""]
    lines += ["User-agent: *", "Allow: /", "", f"Sitemap: {BASE}/sitemap.xml", ""]
    return "\n".join(lines)


def build_llms(pages):
    pub = [p for p in pages if not p["draft"] and p["type"] not in ("home",)]
    out = [f"# {CFG['site_name']} ({CFG['site_name_en']})", "", f"> {CFG['tagline']}. {ORG['legal_name']}({ORG['alternate_name']}, 설립 {ORG['founding_date']}, 인천)의 제품·기술 지식 사이트. 공식 홈페이지 {ORG['url']}", ""]
    for t, label in [("category", "제품 분류"), ("group", "제품군"), ("product", "제품"), ("guide", "가이드"), ("news", "소식"), ("page", "소개")]:
        ps = [p for p in pub if p["type"] == t]
        if not ps: continue
        out.append(f"## {label}")
        out += [f"- [{p['title']}]({abs_url(p['url'])}): {p['description']}" for p in ps]
        out.append("")
    return "\n".join(out)


def build_feed(pages):
    ps = sorted([p for p in pages if p["type"] in ("guide", "news") and not p["draft"]], key=lambda q: q["date"], reverse=True)[:30]
    items = "".join(f"  <item><title>{E(p['title'])}</title><link>{E(abs_url(p['url']))}</link><guid>{E(abs_url(p['url']))}</guid><pubDate>{p['date']}</pubDate><description>{E(p['description'])}</description></item>\n" for p in ps)
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>{E(CFG["site_name"])}</title><link>{BASE}/</link><description>{E(CFG["tagline"])}</description>\n{items}</channel></rss>\n'


def check(pages, dist):
    """GEO 체크리스트 (부록 A) 자동 점검."""
    issues = []
    for p in pages:
        if p["draft"]: continue
        if not p["description"]: issues.append(f"{p['url']}: description 없음 (메타·JSON-LD 설명 비어 있음)")
        if p["type"] in ("guide", "product") and len(p["body_md"].replace("\n", "")) < 600: issues.append(f"{p['url']}: 본문이 짧음 ({len(p['body_md'])}자) — 완결된 정보인지 확인")
        if p["type"] == "product" and not p.get("specs"): issues.append(f"{p['url']}: 제품인데 specs 표 없음")
        if p["type"] == "guide" and not p.get("keywords"): issues.append(f"{p['url']}: keywords 없음")
        hp = os.path.join(dist, p["url"].strip("/"), "index.html") if p["url"] != "/" else os.path.join(dist, "index.html")
        h = io.open(hp, encoding="utf-8").read()
        if h.count("<h1") != 1: issues.append(f"{p['url']}: h1 이 {h.count('<h1')}개")
        if 'application/ld+json' not in h: issues.append(f"{p['url']}: JSON-LD 없음")
        for im in re.findall(r"<img [^>]*>", h):
            if 'alt="' not in im: issues.append(f"{p['url']}: alt 없는 이미지")
    return issues


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--check", action="store_true"); args = ap.parse_args()
    pages = load_pages()
    by_url = {p["url"]: p for p in pages}
    # dist 를 통째로 지우지 않는다 — Windows 에서 서버·탐색기·셸이 폴더를 잡고 있으면 rmdir 이 실패한다.
    # 파일만 지우고 폴더는 남긴다 (남은 빈 폴더는 무해).
    if os.path.isdir(DIST):
        for root, dirs, files in os.walk(DIST):
            for fn in files:
                try: os.remove(os.path.join(root, fn))
                except OSError: pass
    os.makedirs(DIST, exist_ok=True)
    for p in pages:
        out = os.path.join(DIST, "index.html") if p["url"] == "/" else os.path.join(DIST, p["url"].strip("/"), "index.html")
        write(out, render(p, pages, by_url))
    write(os.path.join(DIST, "sitemap.xml"), build_sitemap(pages))
    write(os.path.join(DIST, "robots.txt"), build_robots())
    write(os.path.join(DIST, "llms.txt"), build_llms(pages))
    write(os.path.join(DIST, "feed.xml"), build_feed(pages))
    # GitHub Pages: Jekyll 처리 비활성화. CNAME 은 커스텀 도메인으로 서비스할 때만 (github.io 주소일 땐 넣으면 리다이렉트가 생긴다)
    write(os.path.join(DIST, ".nojekyll"), "")
    if CUSTOM_DOMAIN:
        write(os.path.join(DIST, "CNAME"), _up(BASE).hostname + "\n")
    write(os.path.join(DIST, "404.html"), base(dict(url="/404/", type="page", title="페이지를 찾을 수 없습니다", description="", draft=True, category=""), f'<h1>페이지를 찾을 수 없습니다</h1><p><a href="{href("/")}">홈으로</a></p>', by_url))
    for root, _, files in os.walk(STATIC):
        for fn in files:
            src = os.path.join(root, fn); rel = os.path.relpath(src, STATIC)
            dst = os.path.join(DIST, rel); os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy2(src, dst)
    pub = [p for p in pages if not p["draft"]]
    print(f"built {len(pages)} pages ({len(pub)} public, {len(pages)-len(pub)} draft) -> {DIST}")
    for p in sorted(pages, key=lambda x: x["url"]):
        print(f"  {'[draft] ' if p['draft'] else '        '}{p['url']:44} {p['type']:9} {p['title']}")
    if args.check:
        issues = check(pages, DIST)
        print("\nGEO check:", "OK — 문제 없음" if not issues else f"{len(issues)}건")
        for i in issues: print("  -", i)
        return 1 if issues else 0
    return 0


if __name__ == "__main__" and "--selftest" in sys.argv:
    assert autolink('<td>p.021 · https://www.yerim.net/kor/products/products-view.html?uid=1930</td>') == '<td>p.021 · <a href="https://www.yerim.net/kor/products/products-view.html?uid=1930" target="_blank" rel="noopener">제품설명</a></td>'
    assert autolink('(출처 https://a.com/b).') == '(출처 <a href="https://a.com/b" target="_blank" rel="noopener">https://a.com/b</a>).'
    assert autolink('<a href="https://a.com">https://a.com</a>') == '<a href="https://a.com">https://a.com</a>'
    assert autolink('<script>{"u":"https://a.com"}</script>') == '<script>{"u":"https://a.com"}</script>'
    assert autolink('예림 홈페이지 uid 1028 — 로고') == '<a href="https://www.yerim.net/kor/products/products-view.html?uid=1028" target="_blank" rel="noopener">제품설명</a> — 로고'
    assert autolink('uid 2208·2209').count('<a ') == 2 and 'uid=2210"' in autolink('uid 2210~2226') and '~' not in autolink('uid 2210~2226')
    print("autolink ok"); sys.exit(0)

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
