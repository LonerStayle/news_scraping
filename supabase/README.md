# Supabase 마이그레이션

이 디렉토리의 `migrations/*.sql` 은 ai_news_scraping 의 DB 스키마 정의입니다.

## 적용 방법 (선택 1개)

### A. Dashboard 에서 직접 (가장 단순)

1. https://supabase.com/dashboard → 본 프로젝트
2. 좌측 메뉴 **SQL Editor** → "New query"
3. `migrations/0001_initial_schema.sql` 내용 전체 복사 → 붙여넣기 → "Run"
4. 성공 후 `Table Editor` 에서 4개 테이블 (`articles`, `subscribers`, `runs`, `scrape_enabled`) 생성 확인

### B. Supabase CLI 사용 (선호)

```bash
# 1회 설치
brew install supabase/tap/supabase

# 프로젝트 연결 (project ref 는 Dashboard > Settings > General 에서 확인)
supabase login
supabase link --project-ref <your-project-ref>

# 마이그레이션 적용
supabase db push
```

## 보안 메모

- 모든 테이블에 **RLS 활성화** 되어 있고 별도 policy 는 없습니다.
- 즉 `anon` / `authenticated` 키로는 어떤 접근도 불가.
- 본 애플리케이션은 **`SUPABASE_SERVICE_ROLE_KEY`** 만 사용 (RLS 자동 우회).
- service_role 키는 절대 클라이언트/공개 저장소에 노출 금지.

## 초기 데이터

- `scrape_enabled` 는 마이그레이션이 `(id=1, enabled=true)` 단일 row 를 자동 seed 합니다.
- `subscribers` 는 빈 상태. admin 페이지에서 추가하거나 Dashboard 에서 직접 insert.

## 스키마 변경 시

- 새 마이그레이션은 `0002_<설명>.sql` 같이 순번을 매겨 추가하고, **idempotent (`if not exists` / `on conflict do nothing`)** 로 작성하십시오.
- 기존 마이그레이션 파일은 수정 금지 (이미 적용된 환경이 깨질 수 있음).
