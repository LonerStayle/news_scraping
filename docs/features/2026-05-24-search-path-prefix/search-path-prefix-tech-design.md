# 개발방향: search-path-prefix

> **다음 단계 안내**: 이 문서는 기술 설계서입니다 (아키텍처 / 컴포넌트 / 데이터 / 인터페이스 / 결정 / 위험 / 테스트 전략). `search-path-prefix-requirements.md` (PRD) 를 기반으로 작성되고, 다음 단계 `search-path-prefix-implementation-plan.md` (단계별 계획) 의 입력이 됩니다.

---

## 1. 아키텍처 개요

### 흐름 변경 한 줄

기존: `search_sources.domain` = host → Brave `site:host` → 결과 통과
신규: `search_sources.domain` = host **또는** host/path → 코드가 host 분리 → Brave `site:host` → 결과의 URL path 가 path 부분으로 시작하는 것만 통과

```
┌──────────────────────────────────────────────────────────────┐
│  admin Sources 폼                                              │
│    입력: "openai.com" or "openai.com/research"                │
│    저장: search_sources.domain (단일 컬럼, 마이그레이션 없음)  │
└─────────────────────────┬────────────────────────────────────┘
                          ▼
   ┌──────────────────────────────────────────────────────┐
   │  search_config_loader.load_search_config()           │
   │    SourceRecord → (host, path_prefix, name) 분해      │
   │    source_entries: list[(host, path_prefix, name)]   │
   └─────────────────────────┬────────────────────────────┘
                             ▼
   ┌──────────────────────────────────────────────────────┐
   │  search.search(keyword, source_entries, …)            │
   │    1) Brave 쿼리: `site:host1 OR site:host2 OR …`    │
   │       (host 만 — path 빼고)                            │
   │    2) 결과 받기                                        │
   │    3) 화이트리스트 필터 (기존)                          │
   │    4) ✨ NEW: path-prefix segment-aware 매칭          │
   │       (해당 host 의 entries 의 path_prefix 와 비교)     │
   │    5) _looks_like_article_url (기존)                  │
   └─────────────────────────┬────────────────────────────┘
                             ▼
                  통과한 SearchResult 들
```

### 핵심 invariant

- **Brave 에는 항상 host 만** — path 가 가면 422 (§9-8 함정).
- **여러 row 가 같은 host 를 공유 가능** — `openai.com`, `openai.com/research`, `openai.com/news` 셋 다 따로 row. Brave 호출은 `site:openai.com` 한 번만 (중복 제거).
- **path_prefix 가 빈 row 가 같은 host 에 있으면 그게 우선** — 즉 `openai.com` row 가 있고 `openai.com/research` row 도 있으면, 둘 다 매치되는 결과는 `openai.com` row 의 매체명을 따른다 (가장 넓은 매치). 이 정책은 §5 D5 결정.

---

## 2. 영향 받는 컴포넌트/파일

| 파일 | 변경 내용 | FR / AC 매핑 |
|------|----------|--------------|
| `src/ai_news_scraping/search_config_store.py` | `_normalize_domain` 의 `/` reject 정책 해제 (path 허용). `_split_host_path()` 헬퍼 신설. `SourceRecord` 는 그대로 (domain 컬럼 단일). | FR-1, FR-7, AC-4 |
| `src/ai_news_scraping/search_config_loader.py` | `LoadedConfig.source_entries: list[SourceEntry]` 신설 (host/path_prefix/name 묶음). 기존 `source_domains`/`source_name_map` 은 host 기반 derived 로 유지 (다른 caller backwards). | FR-2, FR-5, FR-9 |
| `src/ai_news_scraping/search.py` | `build_query()` 입력을 `source_entries` 로. 쿼리는 host 만 추출해 dedup. 결과 필터에 `_matches_path_prefix()` 추가 (segment-aware). | FR-3, FR-4, AC-1, AC-2, AC-3 |
| `src/ai_news_scraping/pipeline.py` | `PipelineParams.source_domains` → `source_entries` (또는 두 형태 모두 받게 보강). `_run_inner` 의 search 호출 인자 갱신. | FR-4 |
| `src/ai_news_scraping/cli.py` | `build_params()` 에서 `loaded.source_entries` 전달. | (구조 변경 전파) |
| `templates/admin.html` | Sources 폼 안내 텍스트 갱신 + `pattern` 속성 갱신 (host 또는 host/path). | FR-6 |
| `tests/test_search_config_store.py` | path 입력 허용 케이스 추가, host/path 분리 헬퍼 단위. 기존 reject 케이스는 스킴/포트/공백/쿼리/점 누락만 유지. | FR-7 |
| `tests/test_search.py` | `_matches_path_prefix()` 단위 + segment-aware (false positive 차단) + search 통합. | AC-1..3 |
| `tests/test_search_config_loader.py` | `source_entries` 분해 검증. | FR-5, FR-9 |
| `tests/test_pipeline.py` | 인자 변경 전파 sanity. | (회귀 방지) |

---

## 3. 데이터 모델/스키마 변경

### 결론: **마이그레이션 0004 불필요** (큰 장점)

`search_sources.domain` 컬럼을 그대로 사용. host (예: `openai.com`) 또는 host/path (예: `openai.com/research`) 둘 다 같은 텍스트 컬럼에 저장.

### unique 제약 영향

기존 `(domain) unique` 가 그대로 유효. 다른 문자열 (`openai.com` vs `openai.com/research`) 은 서로 다른 row 로 들어감 → 충돌 X.

### 0003 마이그레이션 (description 컬럼) 호환

영향 없음. description 은 그대로.

### 데이터 분해 (저장 X, 코드 derived)

코드에서 `domain` 값을 읽을 때마다 host/path 로 분해:
```python
def _split_host_path(raw_domain: str) -> tuple[str, str]:
    """'openai.com/research' → ('openai.com', '/research')
       'openai.com'          → ('openai.com', '')"""
    if "/" not in raw_domain:
        return raw_domain, ""
    host, path = raw_domain.split("/", 1)
    return host, "/" + path
```

### 기존 row 처리

CLI 첫 부팅 시점에 `0003` 까지 적용된 상태에서:
- `domain` 이 host-only 인 row → 동작 변경 없음 (FR-2 + AC-5)
- `domain` 이 host/path 인 row (대표님이 이전에 잘못 넣은 row 가 SQL 정리 안 됐다면 그대로 남아 있을 가능성) → 자동으로 path-prefix 필터 모드로 동작. 정상 의도된 케이스로 흡수.

---

## 4. 외부 인터페이스 — N/A: REST/event 외부 노출 없음 (admin POST 는 내부 폼)

---

## 5. 핵심 결정 + 대안 비교

### D1. 데이터 모델: 단일 `domain` 컬럼 vs 별 `path_prefix` 컬럼

| 안 | 장점 | 단점 |
|---|------|------|
| **A. 단일 `domain`** (✅ **선택**) | 마이그레이션 0 / admin 인풋 1개 그대로 / CLAUDE.md §5 "최소 UI" 부합 / 대표님 의도 직접 표현 ("도메인만 적으면…/연산자까지 적으면…") | `domain` 컬럼 이름이 host 가 아닌 host+path 라 의미가 약간 모호 (주석으로 보강) |
| B. 분리 `domain` + `path_prefix` | 컬럼 의미 명확 / unique 가 `(domain, path_prefix)` 로 자연스러움 | 마이그레이션 0004 + admin 인풋 2개 + 데이터 분해 코드 더 깊이 (LoadedConfig 변환층) |

대표님 5/24 발화 ("단일 입력 칸 의도") + 마이그레이션 비용 0 으로 **A 채택**.

### D2. URL path 매칭: startswith vs segment-aware

| 안 | 예 (prefix=`/research`) | 단점 |
|---|------------------------|------|
| A. 단순 `path.startswith(prefix)` | `/research/x` ✅, `/researchers/y` ✅ (false positive) | 의도와 다르게 통과 |
| **B. segment-aware** (✅ **선택**) | `/research` ✅, `/research/x` ✅, `/researchers/y` ❌ | prefix 가 `/` 로 끝나는 경우 처리 추가 (구현은 작음) |

구현:
```python
def _matches_path_prefix(url_path: str, prefix: str) -> bool:
    if not prefix or prefix == "/":
        return True  # prefix 없으면 매치
    norm = prefix.rstrip("/")
    return url_path == norm or url_path.startswith(norm + "/")
```

### D3. 매체명 표시: host-only 매핑 vs row 단위 전파

| 안 | 결과 |
|---|------|
| A. host-only `source_name_map` (현행) | `openai.com/research` row 와 `openai.com/news` row 가 둘 다 같은 host → 같은 name 으로 노출됨. 분리 의미 사라짐. |
| **B. row 단위 `name` 전파** (✅ **선택**) | SearchResult 가 host + path 까지 매칭해 그 row 의 name 을 들고 다님. 출처 링크에 "OpenAI Research" / "OpenAI News" 정확히 노출. |

구현 폭: SearchResult / ExtractedArticle / SummaryInput 에 `source_name` 필드는 이미 있음. 단지 결정 시점이 host 만이 아니라 row 단위가 되도록 `_matches_path_prefix` 가 통과시킨 row 의 name 을 같이 전파.

### D4. Brave 호출 횟수: row 마다 vs host 단위 묶음

| 안 | 결과 |
|---|------|
| A. row 마다 1 호출 | 같은 host 의 prefix row 가 3개면 3 호출. Brave 무료 cap (월 2000) 빠르게 소진. |
| **B. host 단위 dedup → 1 호출** (✅ **선택**) | 같은 host 의 모든 row 가 같은 검색 결과 풀을 공유. 클라이언트에서 prefix 별로 필터. CLAUDE.md §6 호출 수 설계 유지. |

### D5. 같은 host 에 `path_prefix` 비어있는 row + 비어있지 않은 row 가 공존 시 정책

`openai.com` row + `openai.com/research` row 가 동시 active 인 케이스. 두 row 의 `name` 이 다를 수 있음.

| 안 | 결과 |
|---|------|
| A. 좁은 prefix 우선 (`/research` 매치 시 그 row 의 name 사용) | `name` 충돌 시 좁은 쪽 의도 살림 |
| **B. 넓은 prefix 우선 (host-only row 가 있으면 그 name 사용)** (✅ **선택**) | "이 매체는 통째로 본다" 가 명시된 row 가 우선. row 등록 의도 직관적 — host-only row 가 있다는 건 "전체 보고 싶다" 의 명시. |

운영 사용성 측면에서 B 가 단순. 추후 대표님이 "좁은 우선" 원하시면 후속 후보.

### D6. admin 폼 `pattern` HTML 속성

`[a-z0-9.\-]+\.[a-z]{2,}(/[a-zA-Z0-9._\-/]+)?` — host (점 1개 이상) 뒤에 선택적 `/path` 허용. 서버 측 `_normalize_domain` 검증과 짝.

---

## 6. 위험/사이드이펙트 (preliminary)

| ID | 카테고리 | 내용 | 완화 |
|----|---------|------|------|
| R1 | side-effect | 매체별 prefix 좁히면 1회 발송량 감소 가능. 비전 §4 의 10~20건 목표 깰 수 있음. | NFR 명시 + 운영 중 대표님이 History 보고 prefix 조정 |
| R2 | breaking | 기존 DB 에 path 포함 row 가 잘못 들어가 있는 상태 (대표님이 SQL 정리 안 한 경우) 가 마이그레이션 후 자동 활성화 → 의도치 않게 좁아짐. | 이미 commit `7d85e69` 직후 SQL 정리 권유. 추가로 PRD AC-5 회귀 테스트로 yaml seed 호환 검증. |
| R3 | side-effect | segment-aware 매칭 누락 시 `/research` ↔ `/researchers` false positive (D2). | D2 채택으로 차단. `test_search.py` 에 명시 케이스. |
| R4 | breaking | `search.search()` 의 인자 시그니처 변경 (`source_domains: list[str]` → `source_entries: list[SourceEntry]`). 직접 호출 caller (pipeline.py / 테스트) 모두 업데이트 필요. | grep 으로 caller 전체 식별 (이미 §2 표에 매핑). 테스트 fixture 도 함께 갱신. |
| R5 | side-effect | Brave 응답이 같은 host 에 여러 row 매치되면 같은 URL 이 여러 SearchResult 로 들어올 가능성. 후속 dedup 단계 (`_dedup_in_batch`) 가 url 기반이라 OK 지만 row 단위 매체명 결정이 비결정적이면 안 됨. | D5 정책 (넓은 우선) 으로 결정적. row id 오름차순으로 매칭 순서 고정. |

---

## 7. 테스트 전략

### 7-1. 단위

- `test_search_config_store.py`
  - path 포함 입력 허용 (`openai.com/research`, `openai.com/research/papers/2026`)
  - 스킴/포트/공백/쿼리/점누락 reject 유지 (기존 케이스 통과)
  - `_split_host_path()` 단위 — host-only / host+path / host+depth>1 / 빈 prefix
- `test_search.py`
  - `_matches_path_prefix()` 단위 — match / segment boundary / false positive (researchers) / 빈 prefix / 정확히 prefix 와 같은 path
- `test_search_config_loader.py`
  - `source_entries` 분해 검증 — DB row 의 domain 값에 path 있을 때 host/path/name 분리
  - host-only row + host+path row 공존 시 entries 둘 다 노출

### 7-2. 통합

- `test_search.py` (Brave mock)
  - 단일 호스트에 3 개의 SearchResult (path 가 다 다름) 가 mock → host-only row 일 때 전부 통과 / path_prefix row 일 때 그 prefix 만 통과
  - 같은 host 에 host-only row + path row 가 함께 있는 케이스에서 D5 (넓은 우선) 검증
- AC-1..5 각각 1~2 테스트 매핑

### 7-3. 회귀

- 기존 268 테스트 모두 PASS — 특히 `test_search_config_store.py` 의 path-reject 케이스가 일부 (`openai.com/research` 류) 는 OK 로 바뀌므로 케이스 명시 분리. `https://openai.com` 같은 스킴은 여전히 reject.
- `make check` 전체 통과

---

## 변경이력

<!-- change-history skill auto-appends entries here, oldest first -->

### [2026-05-24 10:35] [개발방향-수정]
- **id**: CH-20260524-002
- **이유**: 신규 기술 설계 — search-path-prefix PRD (CH-20260524-001) 기반 아키텍처/컴포넌트/데이터모델/결정·대안/위험/테스트전략 정리
- **무엇이**: search-path-prefix-tech-design.md 전체 — §1 흐름 변경 1줄 + 다이어그램 + 핵심 invariant, §2 영향 컴포넌트 9 파일 표 (FR/AC 매핑 포함), §3 데이터 모델 (마이그레이션 0 결론), §5 핵심 결정 D1~D6 (단일 컬럼 / segment-aware / row 단위 매체명 / host 단위 dedup / 넓은 우선 / pattern 갱신), §6 위험 R1~R5, §7 테스트 전략 7-1/7-2/7-3
- **영향범위**: 없음 (최초 생성). PRD (CH-20260524-001) 와 cross-link.
- **연관 항목**: CH-20260524-001
