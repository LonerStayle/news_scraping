# admin-polish — Fast tasks (4개)

## Task 1: Sources inline edit + 0003 마이그레이션
- 명세:
  - `search_sources` 에 `description: text NULL` 컬럼 추가 (마이그레이션 0003)
  - `SourceRecord` / `SourceStore.add()` / `update()` 에 description 추가
  - admin 라우트 `POST /sources/{id}` (Form: domain + name + description) — inline edit 결과 저장
  - admin.html Sources 탭의 row 에 "수정" 버튼 → 클릭 시 cell 들이 input 으로 변환 + "저장" 버튼 (JS)
- 영향 파일: `supabase/migrations/0003_source_description.sql`, `search_config_store.py`, `admin.py`, `templates/admin.html`, `tests/test_search_config_store.py`, `tests/test_admin.py`

## Task 2: dry-run 시 DB skip
- 명세: pipeline.py 의 `dry_run=True` 일 때 `store.upsert_article` 호출 skip. extract 결과는 가지고 있되 DB 영속화는 X. 검증 환경 dirty 안 만듦.
- 영향 파일: `pipeline.py`, `tests/test_pipeline.py`

## Task 3: admin.html Linear/Vercel 스타일 재디자인
- 명세: dark mode + glassmorphism. 검정 배경 + blur 카드 + 파랑/보라 수속 그라데이션. 5탭 (+History) 구조와 모든 form/table/button 디자인 갈아엎기. 기능/라우트 동일.
- 영향 파일: `templates/admin.html` (CSS 만)

## Task 4: 강제발송 폴링 진행 표시
- 명세:
  - 새 GET `/api/runs/latest` JSON 엔드포인트 (가장 최근 run 의 status/article_count 반환)
  - admin.html JS: 폼 submit 후 spinner 표시 + 2초마다 /api/runs/latest 폴링
  - status=success/failed/skipped 시 spinner 중지 + History 탭 자동 갱신 (location.reload 또는 fetch)
- 영향 파일: `admin.py`, `templates/admin.html`, `tests/test_admin.py`

---

## 병렬화 계획 (DAG)

- **Chain A**: T1 → T3 → T4
  - T1 가 admin.html 의 Sources 탭에 inline edit 추가 → T3 가 admin.html 전체 재디자인 → T4 가 강제발송 카드에 spinner 추가
  - 모두 같은 파일 (admin.html) 수정 — sequential 필수
- **Independent**: T2 (pipeline.py 만)
