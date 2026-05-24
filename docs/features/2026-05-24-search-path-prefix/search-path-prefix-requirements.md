# 요구사항: search-path-prefix

> **다음 단계 안내**: 이 문서는 PRD (기획 단계 요구사항만) 입니다. 다음 단계로 `designing-direction` skill (또는 `/design` 슬래시) 을 호출해서 `search-path-prefix-tech-design.md` (기술 설계서) 를 만드세요. 기술 결정이나 구현 세부사항은 여기 박지 마세요 — 그건 다음 두 산출물에 들어갑니다.

## 1. 배경/목적

### 배경

현재 `search_sources.domain` 은 commit `7d85e69` 에서 **호스트만** 강제하도록 잠겨 있다 (예: `openai.com` OK / `openai.com/research` 입력 시 400). 이 조치는 Brave Search 의 `site:` 연산자가 path 를 받지 못해 422 가 떨어지는 사고 (2026-05-24) 의 응급 핫픽스 였고, 본 PRD 가 그 임시 안전장치를 **차기 정식 형태로 대체**한다.

호스트만 잡으니 매체 한 곳 (예: `openai.com`) 안에서 마케팅 글·이벤트·HR 공지 등이 검색 결과에 섞여 들어와 대표님이 출근 전 5분에 따라잡고 싶은 *연구·기술 트렌드* 신호가 잡음에 묻힌다 (대표님 5/24 명시 피드백).

### 목적

매체별로 **선택적으로** 경로를 좁혀 정확도를 끌어올린다. 입력 인터페이스는 단일 칸을 유지해 admin UX 의 단순성 (CLAUDE.md §5 "버튼/명단 수준의 최소 UI") 을 보존한다.

---

## 2. 사용자 스토리 / 시나리오

대표님 1인 사용자 — 동일 시나리오 3종:

1. **(현재 유지)** "TechCrunch 는 매체 전체 다 봐도 잡음이 적다" — admin 에 `techcrunch.com` 만 입력 → 그 매체 전체 검색 결과 통과.
2. **(신규)** "OpenAI 는 마케팅 글이 많아 `/research` 섹션만 보고 싶다" — admin 에 `openai.com/research` 입력 → URL path 가 `/research` 로 시작하는 결과만 통과.
3. **(신규)** "OpenAI 의 `/research` 와 `/news` 둘 다 흥미롭다" — admin 에 `openai.com/research` row + `openai.com/news` row 두 개 등록 → 두 prefix 의 결과 모두 통과.

---

## 3. 기능 요구사항 (FR)

### FR-1 단일 입력 형태 허용

admin Sources 의 도메인 입력 칸은 다음 두 형태를 모두 받는다:

- **호스트만**: `openai.com`, `techcrunch.com`
- **호스트 + 경로 prefix**: `openai.com/research`, `openai.com/research/papers`

prefix 가 길수록 좁게 매칭된다 (단순 문자열 prefix — 정규식 X).

### FR-2 호스트만 입력 시 매체 전체 통과

입력에 경로가 없으면 그 호스트의 모든 검색 결과가 후속 단계로 통과한다 (현재 호스트-only 동작 유지).

### FR-3 path prefix 입력 시 prefix 매칭만 통과

입력이 `host/path` 형태일 때, Brave 가 반환한 검색 결과 URL 의 path 부분이 입력 path prefix 로 **시작** 하는 항목만 통과한다.

매칭 예시 (입력 = `openai.com/research`):
- ✅ 통과: `https://openai.com/research/gpt-5-reasoning`
- ✅ 통과: `https://openai.com/research/papers/2026/xyz`
- ❌ 차단: `https://openai.com/news/funding-round`
- ❌ 차단: `https://openai.com/blog/team-update`

### FR-4 Brave `site:` 에는 host 만 전달

Brave Search API 의 `site:` 연산자는 path 를 거부 (422) 한다. 따라서 path 가 포함된 row 도 Brave 검색 쿼리에는 **host 부분만** 전달하고, 검색 결과를 받은 후 클라이언트 측에서 path-prefix 필터를 적용한다.

### FR-5 같은 호스트 + 다른 prefix = 별 row

같은 호스트의 서로 다른 prefix 는 별도 row 로 관리한다 (예: `openai.com/research` row + `openai.com/news` row 두 개). 같은 row 안에 prefix 여러 개 묶는 것은 허용하지 않는다 (§5 범위 밖).

### FR-6 admin 폼 안내 텍스트 갱신

admin Sources 폼 위의 안내 텍스트를 갱신한다. 예: "도메인만 (예: `openai.com`) 또는 도메인+경로 (예: `openai.com/research`) 둘 다 가능." 기존 `pattern` HTML 속성도 새 허용 형태에 맞춰 갱신한다.

### FR-7 잘못된 형태는 명시 reject

다음 형태는 입력 단계에서 400 ValueError 로 reject (자동 정규화 X):

- 스킴 포함 (`https://openai.com`)
- 포트 (`openai.com:443`)
- 쿼리/프래그먼트 (`openai.com?q=1`, `openai.com#section`)
- 공백 (`open ai.com`)
- 호스트 부분이 도메인 형식이 아닌 경우 (점 없음 / 영문/숫자/하이픈/점 외 문자)

단, **호스트 + path prefix 형태는 통과** (기존 `_normalize_domain` 의 `/` 거부 정책 해제, host 부분만 동일 검증).

### FR-8 yaml seed 와 기존 row 호환

기존 `domains/<name>/sources.yaml` (모두 호스트만) 과 현재 DB 의 호스트-only row 는 변경 없이 그대로 동작한다 (FR-2 가 보장).

### FR-9 매체명 표시 / 출처 링크

호스트가 같지만 prefix 가 다른 두 row 는 admin 표시에서 구분이 보여야 한다 (예: `openai.com/research` row 의 `name` 은 "OpenAI Research", `openai.com/news` row 의 `name` 은 "OpenAI News"). Gemini 요약 본문의 출처 링크에서도 `name` 이 그대로 노출된다 (현재 `source_name_map` 로직 유지).

---

## 4. 비기능 요구사항 (NFR)

- **마이그레이션 무결성**: 기존 `search_sources` row 의 데이터가 손실되거나 의미가 변하지 않는다. 새 컬럼이 추가되더라도 기존 row 는 동작 유지.
- **운영 후속 영향 인지**: 매체별 prefix 좁히면 그 매체의 통과 결과 양이 줄어든다. 비전 §4 의 "1회 발송 10~20건" 목표를 깰 수 있으므로 대표님은 운영 중 admin History 와 발송 건수를 보고 prefix 를 조정한다.
- **재발 방지**: §9-8 함정 (Brave `site:` 의 path 거부) 을 코드 주석으로 명시해, 미래 누군가가 "그냥 path 도 site: 에 통과시키자" 류 매직으로 회귀하지 않도록 한다.

---

## 5. 범위 밖 (Out of Scope)

본 PRD 에 포함되지 않는 항목 (대화 중 명시된 제외 + 추가):

- **Brave `site:` 에 path 직접 통과 (옵션 A `inurl:` / path-site 시도)** — Brave 미지원으로 422 떨어짐. 시도 X.
- **같은 row 안에 prefix 여러 개 묶기** (`openai.com/research|/news`) — FR-5 가 별 row 로 분리하도록 강제. 데이터 모델 단순성 우선.
- **정규식 / 와일드카드 매칭** — 단순 문자열 prefix 매칭만. `*` 같은 패턴 지원 X.
- **path 자동 잘라내기 (매직 정규화)** — FR-7 에서 명시 reject. 사용자가 잘못 입력하면 400 으로 막아 디버깅을 쉽게.
- **소문자/대문자 path 자동 변환** — URL path 는 그대로 비교 (대표님 운영 중 발견되면 후속 개선 후보).

---

## 6. 수용 기준 (Acceptance Criteria)

- **AC-1**: `openai.com` row 만 등록 시, 검색 결과의 모든 `openai.com/...` URL 이 후속 단계로 통과한다 (현재 동작 유지).
- **AC-2**: `openai.com/research` row 등록 시, URL path 가 `/research` 로 시작하는 결과만 통과하고 `/news/...` 등은 차단된다.
- **AC-3**: `openai.com/research` + `openai.com/news` 두 row 등록 시, 두 prefix 의 결과가 모두 통과한다.
- **AC-4**: admin 폼에 `https://openai.com` (스킴 포함) 입력 시 400 reject + 안내 메시지 노출.
- **AC-5**: 마이그레이션 적용 후 기존 row (호스트만) 의 검색 동작이 변경 없이 유지된다 (회귀 0).

---

## 변경이력

<!-- change-history skill auto-appends entries here, oldest first -->

### [2026-05-24 10:30] [요구사항-수정]
- **id**: CH-20260524-001
- **이유**: 신규 피처 brainstorming 결과 — host-only 강제 (commit `7d85e69`) 의 임시 안전장치를 정식 path-prefix 필터로 대체. 대표님 5/24 명시 요청 (매체 안에서 분야 좁히기) 반영.
- **무엇이**: search-path-prefix-requirements.md 전체 — §1 배경/목적, §2 사용자 스토리 3 시나리오, §3 FR-1..9 (단일 입력 칸 / host-only 전체 통과 / prefix startswith 매칭 / Brave 에 host 만 전달 / 같은 host 다른 prefix = 별 row / admin 안내 갱신 / 잘못된 형태 reject / yaml seed 호환 / 매체명 출처 표시), §4 NFR (마이그레이션 무결성 / 통과량 영향 인지 / §9-8 함정 코드 주석), §5 범위 밖 5항목, §6 AC-1..5
- **영향범위**: 없음 (최초 생성)
