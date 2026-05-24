---
commit_policy: per-task
---

# search-path-prefix 구현계획서

> **다음 단계 안내**: 이 계획을 task-by-task 로 실행하려면 `executing-plans` (인라인 모드, 본 plan 권장 — task ≤12) 또는 `js-super-sub-driven` (보조 에이전트 강제 모드, 13+ task 시) 를 사용하세요. 각 step 은 체크박스 (`- [ ]`) 형식이라 진행 상황 추적이 가능합니다.

**Goal:** `search_sources.domain` 의 단일 입력 칸에 host 또는 host/path 둘 다 허용해, host-only 면 매체 전체 통과 / path 포함이면 segment-aware prefix 매칭으로 좁게 통과.

**Architecture:** 데이터 모델 변경 없음 (단일 `domain` 컬럼 그대로). 코드에서 host/path 분해 → Brave 에는 host 만 전달 (`site:host` dedup) → 응답을 클라이언트 측에서 path-prefix segment-aware 매칭. 매체명은 row 단위로 전파.

**Tech Stack:** Python + Brave Search API + Supabase Postgres (`ai_news` schema) + FastAPI/Jinja2 admin.

**Spec inputs:**
- `search-path-prefix-requirements.md` — FR-1..9, AC-1..5
- `search-path-prefix-tech-design.md` — D1 (단일 컬럼) / D2 (segment-aware) / D3 (row 단위 매체명) / D4 (host dedup) / D5 (넓은 우선) / D6 (admin pattern)

---

## 1. 단계별 작업

### Task 1: `_normalize_domain` 의 `/` reject 해제 + `_split_host_path` 헬퍼

**Files:**
- Modify: `src/ai_news_scraping/search_config_store.py:39-63`
- Test: `tests/test_search_config_store.py`

**Model**: sonnet

- [x] **Step 1: 실패 테스트 작성** — `tests/test_search_config_store.py` 에 추가

```python
def test_normalize_domain_allows_host_with_path() -> None:
    from ai_news_scraping.search_config_store import _normalize_domain
    assert _normalize_domain("openai.com/research") == "openai.com/research"
    assert _normalize_domain("openai.com/research/papers") == "openai.com/research/papers"


def test_normalize_domain_still_rejects_non_path_garbage() -> None:
    from ai_news_scraping.search_config_store import _normalize_domain
    import pytest
    for bad in ["https://openai.com", "openai.com:443", "openai.com?q=1",
                "open ai.com", "openai", "openai.com/"]:
        with pytest.raises(ValueError):
            _normalize_domain(bad)


def test_split_host_path_separates() -> None:
    from ai_news_scraping.search_config_store import _split_host_path
    assert _split_host_path("openai.com") == ("openai.com", "")
    assert _split_host_path("openai.com/research") == ("openai.com", "/research")
    assert _split_host_path("openai.com/research/papers/2026") == (
        "openai.com", "/research/papers/2026"
    )
```

- [x] **Step 2: 실패 확인**

```bash
make test 2>&1 | tail -5
```
Expected: FAIL — `openai.com/research` reject 가 여전히 발동 + `_split_host_path` 부재.

- [x] **Step 3: 구현**

**원본** (`src/ai_news_scraping/search_config_store.py:39-63`):
```python
def _normalize_domain(raw: str) -> str:
    """대표님이 admin Sources 에 매체 주소를 넣을 때 받을 수 있는 형식을 host 만으로 정규화.

    허용: ``openai.com``, ``www.openai.com``, ``OpenAI.com``
    거부 (ValueError): ``openai.com/research``, ``https://openai.com``,
    ``openai.com?q=1``, ``openai.com:443`` — Brave Search 의 ``site:`` 연산자가
    경로/스킴/쿼리/포트를 받지 못해 422 를 반환하기 때문 (실제 운영 사고 사례).

    실수로 URL 통째로 붙여 넣어도 자동 정규화 X — 명시 reject 로 디버깅을 쉽게.
    """
    s = raw.strip().lower()
    if not s:
        raise ValueError(f"domain must be non-empty: {raw!r}")
    s = s.removeprefix("www.")
    # path / scheme / query / fragment / port — 전부 거부 (자동 잘라내기 X).
    for bad_ch in ("/", ":", "?", "#", " "):
        if bad_ch in s:
            raise ValueError(
                f"domain must be host only (no path/scheme/port/query): {raw!r}. "
                "예) openai.com"
            )
    # 최소한의 host 모양 검증 — 점 1개 이상 + 영문/숫자/하이픈/점만.
    if "." not in s or not all(c.isalnum() or c in "-." for c in s):
        raise ValueError(f"invalid host format: {raw!r}. 예) openai.com")
    return s
```

**수정 후**:
```python
def _normalize_domain(raw: str) -> str:
    """admin Sources 의 매체 입력 정규화 — host 또는 host/path prefix 둘 다 허용.

    허용 형태:
      - host only:        ``openai.com`` / ``www.openai.com`` / ``OpenAI.com``
      - host + prefix:    ``openai.com/research`` / ``openai.com/research/papers``

    여전히 reject (ValueError) — Brave ``site:`` 가 받지 못하는 형태:
      - scheme:  ``https://openai.com``
      - port:    ``openai.com:443``
      - query:   ``openai.com?q=1``  / fragment: ``openai.com#x``
      - 공백, host 부분의 점 누락, host 부분 비영문/숫자/하이픈/점
      - trailing slash ``openai.com/`` (의도 모호 — host 인지 빈 prefix 인지)
    """
    s = raw.strip().lower()
    if not s:
        raise ValueError(f"domain must be non-empty: {raw!r}")
    s = s.removeprefix("www.")
    # scheme / port / query / fragment / 공백 — 여전히 거부. path 는 허용.
    for bad_ch in (":", "?", "#", " "):
        if bad_ch in s:
            raise ValueError(
                f"domain must be host or host/path (no scheme/port/query): {raw!r}. "
                "예) openai.com 또는 openai.com/research"
            )
    if s.endswith("/"):
        raise ValueError(f"trailing slash not allowed: {raw!r}")
    host, path = _split_host_path(s)
    # host 부분 검증: 점 1개 이상 + 영문/숫자/하이픈/점.
    if "." not in host or not all(c.isalnum() or c in "-." for c in host):
        raise ValueError(f"invalid host format: {raw!r}. 예) openai.com")
    # path 부분 검증: 영문/숫자/하이픈/언더스코어/점/슬래시만.
    if path and not all(c.isalnum() or c in "-._/" for c in path):
        raise ValueError(f"invalid path format: {raw!r}")
    return s


def _split_host_path(domain: str) -> tuple[str, str]:
    """``'openai.com/research'`` → ``('openai.com', '/research')``.

    ``'openai.com'`` → ``('openai.com', '')``.
    """
    if "/" not in domain:
        return domain, ""
    host, rest = domain.split("/", 1)
    return host, "/" + rest
```

- [x] **Step 4: 통과 확인**

```bash
make test 2>&1 | tail -5
```
Expected: PASS — 새 케이스 + 기존 reject 케이스 모두 통과.

- [x] **Step 5: Commit**

```bash
git add src/ai_news_scraping/search_config_store.py tests/test_search_config_store.py
git commit -m "T1: _normalize_domain path 허용 + _split_host_path 헬퍼"
```

---

### Task 2: `_matches_path_prefix` segment-aware 헬퍼 + 단위 테스트

**Files:**
- Modify: `src/ai_news_scraping/search.py` (헬퍼 추가 — 파일 하단)
- Test: `tests/test_search.py`

**Model**: haiku

- [x] **Step 1: 실패 테스트 작성**

```python
def test_matches_path_prefix_segment_aware() -> None:
    from ai_news_scraping.search import _matches_path_prefix
    # 빈 prefix → 모두 매치 (FR-2: host-only row 전체 통과)
    assert _matches_path_prefix("/research/x", "") is True
    assert _matches_path_prefix("/anything", "") is True
    # 정확 매치 / 하위 segment 매치
    assert _matches_path_prefix("/research", "/research") is True
    assert _matches_path_prefix("/research/x", "/research") is True
    assert _matches_path_prefix("/research/papers/2026", "/research/papers") is True
    # segment boundary — false positive 차단 (D2 핵심)
    assert _matches_path_prefix("/researchers/x", "/research") is False
    assert _matches_path_prefix("/research-old/x", "/research") is False
    # prefix 끝 슬래시 정규화
    assert _matches_path_prefix("/research/x", "/research/") is True
    # 차단
    assert _matches_path_prefix("/news/x", "/research") is False
```

- [x] **Step 2: 실패 확인**: `pytest tests/test_search.py::test_matches_path_prefix_segment_aware -v` → FAIL (`_matches_path_prefix` 부재)

- [x] **Step 3: 구현** — `src/ai_news_scraping/search.py` 의 `_clamp` 헬퍼 직전 또는 직후에 추가:

**수정 후** (new helper, before `_clamp` at end of file):
```python
def _matches_path_prefix(url_path: str, prefix: str) -> bool:
    """segment-aware path-prefix 매칭. ``/research`` 가 ``/researchers`` 와 매치되지 않게.

    빈 prefix (`""` / `"/"`) 는 모두 매치 (host-only row).
    """
    if not prefix or prefix == "/":
        return True
    norm = prefix.rstrip("/")
    return url_path == norm or url_path.startswith(norm + "/")
```

- [x] **Step 4: 통과 확인**: `pytest tests/test_search.py::test_matches_path_prefix_segment_aware -v` → PASS

- [x] **Step 5: Commit**

```bash
git add src/ai_news_scraping/search.py tests/test_search.py
git commit -m "T2: _matches_path_prefix segment-aware 헬퍼"
```

---

### Task 3: `SourceEntry` + `LoadedConfig.source_entries` 분해

**Files:**
- Modify: `src/ai_news_scraping/search_config_loader.py`
- Test: `tests/test_search_config_loader.py`

**Model**: sonnet

- [x] **Step 1: 실패 테스트 작성** — host/path 분해 검증

```python
def test_load_search_config_decomposes_source_entries() -> None:
    from ai_news_scraping.search_config_loader import load_search_config
    from ai_news_scraping.search_config_store import (
        InMemoryKeywordStore, InMemorySourceStore, InMemorySettingsStore,
    )
    kw = InMemoryKeywordStore(); kw.add("AI")
    src = InMemorySourceStore()
    src.add("openai.com", "OpenAI Blog")
    src.add("openai.com/research", "OpenAI Research")
    settings = InMemorySettingsStore()

    loaded = load_search_config(kw, src, settings)
    entries = loaded.source_entries
    by_id = {(e.host, e.path_prefix): e.name for e in entries}
    assert by_id[("openai.com", "")] == "OpenAI Blog"
    assert by_id[("openai.com", "/research")] == "OpenAI Research"
```

- [x] **Step 2: 실패 확인**: `pytest tests/test_search_config_loader.py -v` → FAIL (`source_entries` 부재)

- [x] **Step 3: 구현**

**원본** (`src/ai_news_scraping/search_config_loader.py:21-68`):
```python
@dataclass(frozen=True)
class LoadedConfig:
    keywords: list[str]
    source_domains: list[str]
    source_name_map: dict[str, str]
    settings: SearchSettings


def load_search_config(
    keyword_store: KeywordStore,
    source_store: SourceStore,
    settings_store: SettingsStore,
    fallback: DomainConfig | None = None,
) -> LoadedConfig:
    """3 store + (선택) yaml fallback → LoadedConfig.

    - keywords: DB active 가 있으면 그것, 없고 fallback 있으면 yaml.keywords
    - sources: 동일 규칙 + 사람 친화 매체명 매핑 함께 반환
    - settings: 항상 DB (singleton row 라 절대 비지 않음). 다만 fallback 있어도
      settings 는 DB 가 source of truth.
    """
    db_keywords = keyword_store.list_active()
    if db_keywords:
        keywords = db_keywords
    elif fallback is not None:
        keywords = list(fallback.keywords)
    else:
        keywords = []

    db_sources = source_store.list_active()
    if db_sources:
        domains = [s.domain for s in db_sources]
        name_map = {s.domain: s.name for s in db_sources}
    elif fallback is not None:
        domains = [s.domain for s in fallback.sources]
        name_map = {s.domain: s.name for s in fallback.sources}
    else:
        domains = []
        name_map = {}

    settings = settings_store.get()

    return LoadedConfig(
        keywords=keywords,
        source_domains=domains,
        source_name_map=name_map,
        settings=settings,
    )
```

**수정 후**:
```python
@dataclass(frozen=True)
class SourceEntry:
    """매체 row 한 줄 분해. host = Brave 호출 키, path_prefix = 클라이언트 필터 키."""
    host: str
    path_prefix: str  # "" 또는 "/research" 등
    name: str


@dataclass(frozen=True)
class LoadedConfig:
    keywords: list[str]
    source_entries: list[SourceEntry]
    settings: SearchSettings

    @property
    def source_domains(self) -> list[str]:
        """역호환 — caller 가 host 리스트만 원할 때. dedup 적용."""
        seen: set[str] = set()
        out: list[str] = []
        for e in self.source_entries:
            if e.host not in seen:
                seen.add(e.host)
                out.append(e.host)
        return out

    @property
    def source_name_map(self) -> dict[str, str]:
        """역호환 — host → name 매핑. D5 (넓은 우선): host-only row 가 있으면 그게 우선."""
        m: dict[str, str] = {}
        # 1차: host-only row (path_prefix == "") 부터 채움
        for e in self.source_entries:
            if e.path_prefix == "" and e.host not in m:
                m[e.host] = e.name
        # 2차: 나머지 row (path_prefix 있는 것) — host-only 가 없을 때만 채움
        for e in self.source_entries:
            if e.host not in m:
                m[e.host] = e.name
        return m


def load_search_config(
    keyword_store: KeywordStore,
    source_store: SourceStore,
    settings_store: SettingsStore,
    fallback: DomainConfig | None = None,
) -> LoadedConfig:
    """3 store + (선택) yaml fallback → LoadedConfig.

    - keywords: DB active 가 있으면 그것, 없고 fallback 있으면 yaml.keywords
    - sources: DB active 가 있으면 그것, 없고 fallback 있으면 yaml. 각 row 의
      domain 값을 (host, path_prefix) 로 분해해 ``SourceEntry`` 리스트로 반환.
    - settings: 항상 DB (singleton row 라 절대 비지 않음).
    """
    from .search_config_store import _split_host_path

    db_keywords = keyword_store.list_active()
    if db_keywords:
        keywords = db_keywords
    elif fallback is not None:
        keywords = list(fallback.keywords)
    else:
        keywords = []

    db_sources = source_store.list_active()
    if db_sources:
        rows = [(s.domain, s.name) for s in db_sources]
    elif fallback is not None:
        rows = [(s.domain, s.name) for s in fallback.sources]
    else:
        rows = []

    entries: list[SourceEntry] = []
    for domain_raw, name in rows:
        host, path = _split_host_path(domain_raw)
        entries.append(SourceEntry(host=host, path_prefix=path, name=name))

    settings = settings_store.get()

    return LoadedConfig(
        keywords=keywords,
        source_entries=entries,
        settings=settings,
    )
```

- [x] **Step 4: 통과 확인**: `pytest tests/test_search_config_loader.py -v` → PASS

- [x] **Step 5: Commit**

```bash
git add src/ai_news_scraping/search_config_loader.py tests/test_search_config_loader.py
git commit -m "T3: SourceEntry + LoadedConfig.source_entries 분해"
```

---

### Task 4: `search.search()` — host dedup + path-prefix 필터 통합

**Files:**
- Modify: `src/ai_news_scraping/search.py:70-140`
- Test: `tests/test_search.py`

**Model**: sonnet

- [x] **Step 1: 실패 테스트 작성** — 통합 mock 1개로 D5 (넓은 우선) + segment-aware 동시 검증

```python
def test_search_filters_by_path_prefix_and_dedups_host_for_brave() -> None:
    """3 row (openai.com host-only / openai.com/research / openai.com/news) →
    Brave 에는 site:openai.com 한 번만 / 결과 필터는 row 별로."""
    from ai_news_scraping.search import search, SourceEntry
    from unittest.mock import MagicMock

    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    fake_resp.json.return_value = {"web": {"results": [
        {"url": "https://openai.com/research/papers/2026/xyz",
         "title": "Paper", "description": "...",
         "meta_url": {"hostname": "openai.com"}},
        {"url": "https://openai.com/news/funding-round",
         "title": "News", "description": "...",
         "meta_url": {"hostname": "openai.com"}},
        {"url": "https://openai.com/researchers/team",  # false positive 후보
         "title": "Team", "description": "...",
         "meta_url": {"hostname": "openai.com"}},
    ]}}
    session = MagicMock()
    session.get.return_value = fake_resp

    entries = [
        SourceEntry(host="openai.com", path_prefix="/research", name="OpenAI Research"),
        SourceEntry(host="openai.com", path_prefix="/news", name="OpenAI News"),
    ]
    results = search("AI", entries, api_key="K", session=session)

    # Brave 쿼리에 site:openai.com 이 1번만 들어가야 (host dedup, FR-4 + D4)
    call = session.get.call_args
    q = call.kwargs["params"]["q"]
    assert q.count("site:openai.com") == 1

    # 결과: /research/papers/2026/xyz + /news/funding-round 통과,
    # /researchers/team 차단 (segment-aware, D2)
    urls = {r.url for r in results}
    assert "https://openai.com/research/papers/2026/xyz" in urls
    assert "https://openai.com/news/funding-round" in urls
    assert "https://openai.com/researchers/team" not in urls
```

- [x] **Step 2: 실패 확인**: 시그니처 변경 + 필터 부재로 FAIL

- [x] **Step 3: 구현**

**원본** (`src/ai_news_scraping/search.py:70-140`):
```python
def build_query(keyword: str, source_domains: list[str]) -> str:
    if not keyword.strip():
        raise ValueError("keyword must be non-empty")
    if not source_domains:
        raise ValueError("source_domains must be non-empty")
    sites = " OR ".join(f"site:{d}" for d in source_domains)
    return f'"{keyword}" ({sites})'


def search(
    keyword: str,
    source_domains: list[str],
    *,
    api_key: str,
    num: int = DEFAULT_COUNT,
    freshness: str = DEFAULT_FRESHNESS,
    session: HttpSession | None = None,
) -> list[SearchResult]:
    """One Brave Search call → whitelisted SearchResult list.

    - ``freshness="pd"`` (past day) = "최신순" 축. ``pw`` / ``pm`` / ``py``
      또는 ISO 날짜 범위 지원.
    - Brave 의 ``meta_url.hostname`` 으로 화이트리스트 재필터 — 검색엔진이
      site: 필터 안에서 가끔 다른 도메인을 섞어주는 케이스 방어.
    """
    sess: HttpSession = (
        session if session is not None else cast(HttpSession, requests.Session())
    )
    headers: dict[str, str] = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
    }
    params: dict[str, Any] = {
        "q": build_query(keyword, source_domains),
        "count": _clamp(num, 1, BRAVE_MAX_COUNT),
        "freshness": freshness,
    }
    resp = sess.get(
        BRAVE_SEARCH_ENDPOINT,
        params=params,
        headers=headers,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    payload: dict[str, Any] = resp.json()
    items: list[dict[str, Any]] = (payload.get("web") or {}).get("results") or []

    whitelist = {d.lower() for d in source_domains}
    results: list[SearchResult] = []
    for item in items:
        link: str = item.get("url", "")
        hostname = str(
            (item.get("meta_url") or {}).get("hostname")
            or _domain_of(link)
        ).lower()
        # `meta_url.hostname` 은 종종 "www." prefix 포함 — 화이트리스트 매칭 위해 제거
        hostname = hostname.removeprefix("www.")
        if not link or hostname not in whitelist:
            continue
        if not _looks_like_article_url(link):
            continue  # 카테고리/홈페이지/인덱스 페이지 차단
        results.append(
            SearchResult(
                url=link,
                title=str(item.get("title", "")),
                snippet=str(item.get("description", "")),
                source_domain=hostname,
                keyword=keyword,
            )
        )
    return results
```

**수정 후**:
```python
@dataclass(frozen=True)
class SourceEntry:
    """매체 row 분해 형태 (search_config_loader.SourceEntry 와 호환 — 같은 shape).

    여기 별도 정의는 search 가 loader 에 의존하지 않게 하기 위함 (search ↔ loader
    순환 import 방지). dict-likeness 가 아닌 attribute 접근 (.host/.path_prefix/.name).
    """
    host: str
    path_prefix: str
    name: str


def build_query(keyword: str, hosts: list[str]) -> str:
    """Brave 쿼리 — host 만 받는다. site: 가 path 를 거부하므로 (§9-8 함정)."""
    if not keyword.strip():
        raise ValueError("keyword must be non-empty")
    if not hosts:
        raise ValueError("hosts must be non-empty")
    sites = " OR ".join(f"site:{h}" for h in hosts)
    return f'"{keyword}" ({sites})'


def search(
    keyword: str,
    source_entries: list[Any],  # list[SourceEntry] but Any for cross-module compat
    *,
    api_key: str,
    num: int = DEFAULT_COUNT,
    freshness: str = DEFAULT_FRESHNESS,
    session: HttpSession | None = None,
) -> list[SearchResult]:
    """One Brave Search call → path-prefix filtered SearchResult list.

    - Brave 쿼리는 host 만 dedup 해 1회 호출 (D4).
    - 응답을 받은 후 클라이언트 측에서 row 단위 path-prefix segment-aware 매칭 (D2).
    - 같은 host 에 host-only row 와 path row 가 공존하면 host-only 가 우선 (D5).
    """
    sess: HttpSession = (
        session if session is not None else cast(HttpSession, requests.Session())
    )
    if not source_entries:
        raise ValueError("source_entries must be non-empty")

    # host dedup — 같은 host 의 row 가 여럿이라도 Brave 호출은 1번.
    hosts: list[str] = []
    seen: set[str] = set()
    for e in source_entries:
        h = e.host.lower().removeprefix("www.")
        if h not in seen:
            seen.add(h)
            hosts.append(h)

    headers: dict[str, str] = {
        "X-Subscription-Token": api_key,
        "Accept": "application/json",
    }
    params: dict[str, Any] = {
        "q": build_query(keyword, hosts),
        "count": _clamp(num, 1, BRAVE_MAX_COUNT),
        "freshness": freshness,
    }
    resp = sess.get(
        BRAVE_SEARCH_ENDPOINT,
        params=params,
        headers=headers,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    payload: dict[str, Any] = resp.json()
    items: list[dict[str, Any]] = (payload.get("web") or {}).get("results") or []

    # host → 그 host 에 매핑된 entries (path_prefix 가짓수만큼).
    host_to_entries: dict[str, list[Any]] = {}
    for e in source_entries:
        h = e.host.lower().removeprefix("www.")
        host_to_entries.setdefault(h, []).append(e)

    results: list[SearchResult] = []
    for item in items:
        link: str = item.get("url", "")
        if not link:
            continue
        hostname = str(
            (item.get("meta_url") or {}).get("hostname") or _domain_of(link)
        ).lower().removeprefix("www.")
        entries = host_to_entries.get(hostname)
        if not entries:
            continue
        if not _looks_like_article_url(link):
            continue  # 카테고리/홈페이지/인덱스 차단

        # path-prefix 매칭 — host-only row (path_prefix == "") 우선 (D5).
        url_path = urlparse(link).path
        host_only = next((e for e in entries if e.path_prefix == ""), None)
        if host_only is not None:
            matched = host_only
        else:
            matched = next(
                (e for e in entries if _matches_path_prefix(url_path, e.path_prefix)),
                None,
            )
        if matched is None:
            continue

        results.append(
            SearchResult(
                url=link,
                title=str(item.get("title", "")),
                snippet=str(item.get("description", "")),
                source_domain=hostname,
                keyword=keyword,
            )
        )
    return results
```

- [x] **Step 4: 통과 확인**: `pytest tests/test_search.py -v` → PASS (신규 + 기존 회귀 0)

- [x] **Step 5: Commit**

```bash
git add src/ai_news_scraping/search.py tests/test_search.py
git commit -m "T4: search() host dedup + path-prefix segment-aware 필터"
```

---

### Task 5: `pipeline.PipelineParams` + caller 갱신 (mechanical caller wave)

**Files:**
- Modify: `src/ai_news_scraping/pipeline.py` (`PipelineParams.source_domains` → `source_entries` + `_run_inner` 의 search 호출)
- Modify: `src/ai_news_scraping/cli.py` (`build_params` 가 `loaded.source_entries` 전달)
- Test: `tests/test_pipeline.py` fixture 갱신

**Model**: sonnet

- [x] **Step 1: 실패 테스트** — `test_pipeline.py` 가 새 시그니처로 `source_entries` 전달하도록 fixture 변경. 기존 fixture 의 `source_domains=["a.com"]` 부분을 `source_entries=[SourceEntry(host="a.com", path_prefix="", name="A")]` 로 마이그레이션.

- [x] **Step 2: 실패 확인**: `pytest tests/test_pipeline.py -v` → FAIL (param 명 mismatch)

- [x] **Step 3: 구현**

`pipeline.py` 의 `PipelineParams`:
- **원본** (해당 필드 부근):
  ```python
  source_domains: list[str]
  ```
- **수정 후**:
  ```python
  source_entries: list[Any]  # list[search.SourceEntry] — Any 는 dataclass forward ref 회피
  ```

`pipeline._run_inner` 의 search 호출:
- **원본** (line 139-145 부근):
  ```python
  results = deps.search_fn(
      keyword,
      params.source_domains,
      api_key=params.brave_search_api_key,
      num=params.num_results_per_keyword,
      freshness=params.freshness,
  )
  ```
- **수정 후**:
  ```python
  results = deps.search_fn(
      keyword,
      params.source_entries,
      api_key=params.brave_search_api_key,
      num=params.num_results_per_keyword,
      freshness=params.freshness,
  )
  ```

`cli.py` 의 `build_params`:
- **원본**:
  ```python
  return PipelineParams(
      keywords=list(loaded.keywords),
      source_domains=list(loaded.source_domains),
      ...
  )
  ```
- **수정 후**:
  ```python
  return PipelineParams(
      keywords=list(loaded.keywords),
      source_entries=list(loaded.source_entries),
      ...
  )
  ```

`cli.py` 의 `source_name_map` 사용처는 `loaded.source_name_map` property 가 그대로 호환 제공 → 추가 변경 불필요.

- [x] **Step 4: 통과 확인**: `pytest tests/test_pipeline.py tests/test_search.py -v` → PASS

- [x] **Step 5: Commit**

```bash
git add src/ai_news_scraping/pipeline.py src/ai_news_scraping/cli.py tests/test_pipeline.py
git commit -m "T5: PipelineParams.source_entries + caller (pipeline/cli) 갱신"
```

---

### Task 6: admin Sources 폼 안내 + `pattern` 갱신

**Files:**
- Modify: `templates/admin.html` (Sources 폼 안내 텍스트 + `pattern` 속성)
- Test: `tests/test_admin.py` (폼 접속 OK 회귀만)

**Model**: haiku

- [x] **Step 1: 실패 테스트** — admin GET / 가 정상 응답 + 새 안내 텍스트 substring 포함

```python
def test_admin_sources_form_shows_path_hint() -> None:
    # ...client fixture 활용. response body 에 '또는 도메인+경로' 가 포함되는지.
    response = client.get("/")
    assert response.status_code == 200
    assert "또는 도메인+경로" in response.text  # 신규 안내
```

- [x] **Step 2: 실패 확인**: 안내 텍스트 부재로 FAIL

- [x] **Step 3: 구현**

**원본** (`templates/admin.html:462-471`):
```html
    <p class="hint" style="color: var(--muted); font-size: 0.85rem; margin: 0 0 0.5rem 0;">
      ⚠️ <strong>도메인만 입력</strong>해 주십시오 (예: <code>openai.com</code>). 경로/스킴/포트 포함 시
      Brave Search 의 <code>site:</code> 연산자가 거부 (422) → 발송 0건.
    </p>
    <form class="add-form" method="post" action="/sources">
      <input type="text" name="domain" required placeholder="domain (예: techcrunch.com)" pattern="[a-z0-9.\-]+\.[a-z]{2,}">
      <input type="text" name="name" required placeholder="이름 (예: TechCrunch)">
      <input type="text" name="description" placeholder="설명 (선택)">
      <button type="submit" class="primary">추가</button>
    </form>
```

**수정 후**:
```html
    <p class="hint" style="color: var(--muted); font-size: 0.85rem; margin: 0 0 0.5rem 0;">
      ℹ️ <strong>도메인만</strong> (예: <code>openai.com</code>) <strong>또는 도메인+경로</strong>
      (예: <code>openai.com/research</code>) 둘 다 입력 가능. 도메인만 적으면 그 매체 전체에서, 경로까지 적으면
      그 경로로 시작하는 결과만 통과합니다. 스킴/포트/쿼리는 불가.
    </p>
    <form class="add-form" method="post" action="/sources">
      <input type="text" name="domain" required placeholder="예: openai.com 또는 openai.com/research" pattern="[a-z0-9.\-]+\.[a-z]{2,}(/[a-zA-Z0-9._\-/]+)?">
      <input type="text" name="name" required placeholder="이름 (예: TechCrunch)">
      <input type="text" name="description" placeholder="설명 (선택)">
      <button type="submit" class="primary">추가</button>
    </form>
```

- [x] **Step 4: 통과 확인**: `pytest tests/test_admin.py -v` → PASS

- [x] **Step 5: Commit**

```bash
git add templates/admin.html tests/test_admin.py
git commit -m "T6: admin Sources 폼 안내 갱신 + pattern 에 path 허용"
```

---

### Task 7: End-to-end AC-1..5 통합 검증

**Files:**
- Test: `tests/test_search.py` (또는 `tests/test_search_integration.py` 신규)

**Model**: sonnet

- [x] **Step 1: AC 각각 1개씩 mock 통합 테스트 작성**

```python
def test_AC1_host_only_lets_all_through() -> None:
    """AC-1: openai.com row 만 등록 시 모든 openai.com/... 통과"""
    # Mock Brave 결과 3개 (/research/x, /news/y, /blog/z) → 모두 통과

def test_AC2_path_prefix_filters_other_sections() -> None:
    """AC-2: openai.com/research row 만 → /research 만 통과, /news 차단"""

def test_AC3_multiple_prefixes_both_active() -> None:
    """AC-3: /research + /news 두 row → 둘 다 통과"""

def test_AC4_admin_form_rejects_scheme() -> None:
    """AC-4: 'https://openai.com' 입력 시 400 + 안내 노출"""
    # admin POST /sources 에 invalid domain 보내고 400 확인

def test_AC5_existing_host_only_row_unchanged() -> None:
    """AC-5: 기존 host-only row 동작 회귀 0 — yaml seed 호환"""
```

- [x] **Step 2: 실패 확인**: 새 mock 테스트 동작 검증

- [x] **Step 3: 구현** — 위 5 테스트가 동작하도록 (대부분 fixture 작성 + 기존 search/admin 활용)

- [x] **Step 4: 통과 확인**: 전체 `make test` PASS

- [x] **Step 5: Commit**

```bash
git add tests/
git commit -m "T7: AC-1..5 end-to-end 통합 검증"
```

---

### Task 8: §9-8 함정 코드 주석 + HANDOFF.md §12-A 흡수 정리

**Files:**
- Modify: `src/ai_news_scraping/search.py` (build_query 위에 코멘트 보강)
- Modify: `HANDOFF.md` §12-A 가 완료됐음을 §13 의사결정 기록에 반영
- Modify: `HANDOFF.md` §9-8 의 "⚠️ 임시 안전장치" 문구 갱신 — 이제 정식 형태

**Model**: sonnet

- [x] **Step 1**: HANDOFF.md §9-8 / §12 / §12-A / §13 갱신 (운영 문서 동기화)
- [x] **Step 2**: `search.py` 의 build_query 직전에 한 줄 주석 — "Brave site: 는 host 만 (§9-8). path 는 클라이언트 _matches_path_prefix 로."
- [x] **Step 3**: `make check` 전체 통과 확인
- [x] **Step 4: Commit**

```bash
git add HANDOFF.md src/ai_news_scraping/search.py
git commit -m "T8: HANDOFF 갱신 + §9-8 함정 주석"
```

---

### Task 9: `make check` 전체 통과 + 최종 정리

**Files:** (검증 only)

**Model**: haiku

- [x] **Step 1**: `make check` (lint + typecheck + test) → 모두 exit 0
- [x] **Step 2**: 실패 시 회귀 케이스 grep 으로 식별 (T1~T8 어디 영향 확인)
- [x] **Step 3**: 모두 통과 시 PROJECT_DONE 외칠 필요는 없으나 plan 모든 task `[x]` 마킹

(별도 commit 불필요 — 직전 task commit 이 최종 상태)

---

## 2. 위험 코드 지점

각 항목은 tech-design §6 의 R1~R5 와 매핑:

- `src/ai_news_scraping/search_config_store.py:39-63` (T1 적용 후) — **breaking**: `/` reject 정책 해제. 기존에 reject 되던 입력 (`openai.com/research`) 이 통과로 바뀜. mitigation: 다른 reject 케이스 (스킴/포트/공백/쿼리) 는 유지 + Task 1 Step 1 의 `test_normalize_domain_still_rejects_non_path_garbage` 로 회귀 방지.
- `src/ai_news_scraping/search.py:70-140` (T4 적용 후) — **breaking**: `search()` 인자 시그니처 `source_domains: list[str]` → `source_entries: list[SourceEntry]`. mitigation: caller (`pipeline.py` + `cli.py` + 테스트 fixture) 동시 갱신 (T5 mechanical wave) + `LoadedConfig` 의 `source_domains`/`source_name_map` property 로 다른 caller 호환.
- `src/ai_news_scraping/search.py` (T4 `_matches_path_prefix` 호출 지점) — **side-effect**: segment-aware 누락 시 `/research` ↔ `/researchers` false positive. mitigation: T2 의 `test_matches_path_prefix_segment_aware` 케이스로 차단.
- `src/ai_news_scraping/search_config_loader.py` (T3 적용 후) — **side-effect**: D5 (host-only 우선) 로직이 결정적이어야. 같은 host 의 두 row 가 둘 다 매치되면 host-only 가 일관 선택. mitigation: T3 `source_name_map` property 의 2-pass 로직 + T4 search() 의 `host_only` 분기.
- `templates/admin.html` (T6) — **side-effect**: `pattern` HTML 속성이 클라이언트 측 검증. 서버 측 `_normalize_domain` 가 진짜 게이트. mitigation: T1 의 `_normalize_domain` reject 케이스가 백엔드에서 다시 검증.

---

## 3. 롤백 전략

- **Code**: 본 plan 의 commit 들 (T1~T8) 을 역순으로 revert. `git revert <SHA-T8>..<SHA-T1>` 또는 `git reset --hard <pre-T1-SHA>` (단, force-push 금지 — 대표님 명시 확인 필요).
- **DB**: 마이그레이션 변경 없음 → DB 롤백 불요.
- **Config**: feature flag 없음. 운영 중 문제 발생 시 admin Sources 의 path 포함 row 를 host-only 로 직접 수정 (Edit 폼).
- **임시 우회**: 긴급 시 `_normalize_domain` 의 `/` reject 라인만 다시 켜는 hotfix 1줄 패치.

---

## 변경이력

<!-- change-history skill auto-appends entries here, oldest first -->

### [2026-05-24 10:40] [구현계획서-수정]
- **id**: CH-20260524-003
- **이유**: 신규 구현계획서 — search-path-prefix tech-design (CH-20260524-002) 의 D1~D6 결정을 9개 TDD task 로 분해. commit_policy=per-task.
- **무엇이**: search-path-prefix-implementation-plan.md 전체 — Task 1 (_normalize_domain `/` 허용 + _split_host_path), Task 2 (_matches_path_prefix segment-aware), Task 3 (SourceEntry + LoadedConfig.source_entries + D5 source_name_map property), Task 4 (search() host dedup + path-prefix 필터), Task 5 (pipeline + cli caller wave), Task 6 (admin Sources 폼 안내 + pattern), Task 7 (AC-1..5 end-to-end 통합), Task 8 (HANDOFF + §9-8 주석), Task 9 (make check). §2 위험 코드 지점 5건 + §3 롤백 전략.
- **영향범위**: 없음 (최초 생성). PRD (CH-20260524-001) + tech-design (CH-20260524-002) 와 cross-link.
- **연관 항목**: CH-20260524-001, CH-20260524-002

### [2026-05-24 10:55] [코드-수정] (batch: tasks T1..T8)
- **id**: CH-20260524-004
- **이유**: search-path-prefix 구현계획 T1~T8 일괄 실행 — admin 단일 입력 칸으로 host 또는 host/path 둘 다 허용, segment-aware 클라이언트 측 path-prefix 필터로 매체 안 분야 좁히기 가능. 마이그레이션 0 (단일 domain 컬럼 유지).
- **무엇이**: src/ai_news_scraping/search_config_store.py, src/ai_news_scraping/search.py, src/ai_news_scraping/search_config_loader.py, src/ai_news_scraping/pipeline.py, src/ai_news_scraping/cli.py, templates/admin.html, HANDOFF.md, tests/test_search_config_store.py, tests/test_search.py, tests/test_search_config_loader.py, tests/test_pipeline.py, tests/test_pipeline_smoke.py, tests/test_cli.py, tests/test_search_path_prefix_ac.py (신규)
- **영향범위**: search 흐름 전체 — store → loader → search → pipeline → cli → admin 6단 + 268 → 284 tests (+16 신규). Backwards compat 으로 list[str] 입력도 host-only SourceEntry 로 자동 변환.
- **위험 카테고리**: breaking, side-effect — `_normalize_domain` 의 `/` reject 정책 해제 + `search()` 시그니처 변경 (caller wave 동시 갱신). segment-aware 매칭 누락 시 `/research` ↔ `/researchers` false positive 위험은 test_search_path_prefix_ac 의 D5 케이스로 차단.
- **task별 세부 (8건)**:
  - Task 1: `src/.../search_config_store.py:39-100` — `_normalize_domain` path 허용 + `_split_host_path` 헬퍼 (`breaking`) — commit: `0117a93`
  - Task 2: `src/.../search.py` — `_matches_path_prefix` segment-aware 헬퍼 (`none`) — commit: `9949b86`
  - Task 3: `src/.../search_config_loader.py` — `SourceEntry` + `LoadedConfig.source_entries` + `source_domains`/`source_name_map` property (D5 넓은 우선) (`side-effect`) — commit: `edfc65b`
  - Task 4: `src/.../search.py:70-180` — `search()` host dedup + path-prefix 필터 통합 + `_coerce_to_entries` backwards compat (`breaking`) — commit: `e292b55`
  - Task 5: `src/.../pipeline.py`, `src/.../cli.py`, test fixtures — `PipelineParams.source_entries` + caller wave (`breaking`) — commit: `a54d140`
  - Task 6: `templates/admin.html:462-475` — Sources 폼 안내 + `pattern` 갱신 (host 또는 host/path) (`none`) — commit: `7fababb`
  - Task 7: `tests/test_search_path_prefix_ac.py` (신규) — AC-1..5 + D5 1:1 mapping 회귀 게이트 (`none`) — commit: `5667cf8`
  - Task 8: `HANDOFF.md`, `src/.../search.py` build_query docstring — §9-8 함정 정식화 + §12-A 완료 마킹 (`none`) — commit: `680eb1a`
- **연관 commits**: `0117a93..680eb1a` (8 commits)
- **변경 전/후 코드**: 생략 — `git show <SHA>` 로 조회 (commit_policy=per-task)
- **연관 항목**: CH-20260524-001, CH-20260524-002, CH-20260524-003

### [2026-05-24 10:55] [검증]
- **id**: CH-20260524-005
- **이유**: T9 `make check` 전체 검증 — lint + typecheck + test 모두 exit 0
- **무엇이**: `uv run ruff check .` (All checks passed) / `uv run mypy` (Success: no issues found in 38 source files) / `uv run pytest` (284 passed in 4.37s)
- **결과**: PASS — 268 → 284 (+16) 회귀 0
- **연관 commit**: HEAD = `680eb1a`
