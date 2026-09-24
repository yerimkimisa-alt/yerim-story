# 예림 스토리 — 자체 콘텐츠 사이트

`예림_AI검색_GEO_구축전략.docx`의 원칙을 그대로 구현한 **정적 사이트**. 에이전트 팀이 만든 글은 네이버보다 **여기에 먼저** 올린다 (2026-09-24 결정). 다른 블로그는 이 사이트의 글을 변형해 나중에 배포한다.

## 왜 정적 HTML인가

- **크롤링에 가장 유리** — JS 없이 HTML 안에 모든 텍스트·표·FAQ가 있다. 어떤 크롤러도 그대로 읽는다.
- **디자인 최소** — 시스템 폰트, CSS 한 장, 본문 우선. "개발자스럽게".
- **어디든 호스팅** — `site/dist/` 폴더를 GitHub Pages·Cloudflare Pages·Netlify·자체 서버 어디에 올려도 된다. 서버 프로그램이 필요 없다.
- **기준 데이터 = 파일** — `content/*.md` 가 제품 마스터 데이터의 웹 표현. 수정 이력이 git에 남는다.

## 구조

```
site/
├── config.json          사이트명·도메인(base_url)·Organization 엔티티·제품군·크롤러 정책
├── build.py             생성기. content/ → dist/  (--check 로 GEO 점검)
├── content/             ★ 콘텐츠 원본 (경로 = URL)
│   ├── index.md         /            홈
│   ├── about.md         /about/      예림 소개 (Organization + FAQ)
│   ├── door.md …        /door/ …     제품 분류 6개 (category)
│   ├── door/system-door.md              /door/system-door/          제품군 (group)
│   ├── door/system-door/ybf-140t.md     /door/system-door/ybf-140t/ 제품 (product, draft)
│   └── guide/<slug>.md  /guide/<slug>/  가이드 (에이전트 산출물)
├── static/              style.css · img/<slug>/N.jpg
├── tools/import_post.py 에이전트 post.md → content/guide/  변환
└── dist/                빌드 결과 (배포 대상). git 에 넣지 않는다
```

## GEO 원칙 → 구현

| 전략 문서 원칙 | 구현 |
|---|---|
| 1 키워드별 독립 URL | 파일 경로가 URL. `guide/innergate-3lock-vs-sliding.md` → `/guide/innergate-3lock-vs-sliding/` |
| 2 HTML 텍스트 우선 | 사양은 `specs` 표, FAQ는 `faq` 블록 → 모두 HTML `<table>`·`<details>`. 이미지는 `alt`·`figcaption` 필수 |
| 3 크롤러 허용 | `robots.txt` 자동 생성. Googlebot·Bingbot·Yeti·OAI-SearchBot·PerplexityBot·ClaudeBot 허용. 학습용(GPTBot 등)은 `config.json` `training_policy` 로 결정 |
| 4 구조화 데이터 | 페이지 타입별 JSON-LD: Organization(홈·소개) · Product(제품, specs → additionalProperty) · FAQPage(faq 있는 모든 페이지) · BreadcrumbList(전 페이지) · Article(가이드·소식) |
| 5 색인 신호 | `sitemap.xml`(lastmod = updated) · `feed.xml` · `llms.txt`. Search Console·Bing·IndexNow 등록은 배포 후 사람이 |
| 6 질문형 콘텐츠 | `guide` 타입 = 질문 하나 + 결론 첫 문단 + 비교표 + FAQ |
| 8 지속 갱신 | frontmatter `updated` → 페이지 수정일·sitemap lastmod·dateModified |
| Entity 일관성 | `config.json` organization 하나에서 Organization JSON-LD·푸터·llms.txt 를 모두 생성 |
| 사실 검증 | `draft: true` 페이지는 빌드되지만 noindex + sitemap 제외 + 목록 비노출. 검증 후 false 로 |

## 빌드·확인

```
.\.venv\Scripts\python.exe site\build.py --check
```
`--check` 는 부록 A 체크리스트를 자동 점검한다: description 유무, h1 1개, JSON-LD 존재, alt 없는 이미지, 제품 specs 유무, 가이드 keywords, 본문 길이.

미리보기: 상황판 서버가 `http://localhost:8765/site/` 로 dist 를 서빙한다.

## 에이전트 글 올리기

```
.\.venv\Scripts\python.exe site\tools\import_post.py yerim-blog\posts\<폴더>\post.md --build
```
- `## 본문` 만 가져오고 네이버용 `## 마무리 블록`(댓글·이웃추가)은 뺀다. 사이트는 템플릿 CTA(제품군·공식 홈페이지·문의)를 붙인다.
- `[이미지 N]` 자리는 `static/img/<slug>/N.jpg` 가 있을 때만 `<figure>` 가 된다. 없으면 빠지고 경고가 뜬다 — **글은 이미지 없이도 완결**돼야 한다(원칙 2).
- 상황판 콘텐츠 페이지의 **"사이트에 올리기"** 버튼이 이 스크립트를 실행한다.

## 콘텐츠 타입과 frontmatter

| type | 필수 | 선택 | JSON-LD |
|---|---|---|---|
| category | title, description, category | faq | Breadcrumb, FAQ |
| group | title, description, category | faq | Breadcrumb, FAQ |
| product | title, description, category, model, specs[] | docs[], faq[], image, keywords, draft | Product, Breadcrumb, FAQ |
| guide / news | title, description, keywords, date, updated | category, faq[], products[], related[], image | Article, Breadcrumb, FAQ |
| page | title, description | faq | Organization, Breadcrumb, FAQ |

`specs` 항목: `name / value / source(출처·성적서) / note(확인 필요 등)`. `docs`: `name / date / url`.

## 배포 (도메인 확정 후)

1. `config.json` 의 `base_url` 을 실제 도메인으로 (예: `https://story.yerim.net`) → 다시 빌드
2. `dist/` 를 호스팅에 올린다 (GitHub Pages 면 저장소 Pages 설정, Cloudflare Pages 면 폴더 업로드)
3. Google Search Console · Bing Webmaster Tools 에 사이트 등록, `sitemap.xml` 제출
4. 이후 매 빌드마다 IndexNow 호출 (추후 `build.py --indexnow` 로 추가 예정)

## 결정이 필요한 것

- **도메인** — `story.yerim.net` 같은 서브도메인이 브랜드 엔티티 연결에 유리(sameAs·Organization). 별도 도메인이면 config 에 반영
- **학습용 크롤러 정책** — `training_policy: allow|disallow`
- **YBF-140T 사양 검증** — 전략 문서 §10.2 항목 8개. 검증 전까지 draft
- **로고 URL** — `config.json` organization.logo 실제 경로
