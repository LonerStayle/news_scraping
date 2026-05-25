# discover-default-on-with-overlay — Fast tasks (2개)

## Task 1: "🌐 모든 active 키워드" 체크박스 default checked

- 명세: `templates/admin.html` 의 `<input type="checkbox" id="discover-all-keywords">` 에 `checked` 속성 추가. admin 진입 시 합산 모드가 default. 사용자가 체크 해제하면 기존 단일 키워드 모드로 동작 (백엔드 분기는 그대로).
- 영향 파일: `templates/admin.html` (1줄)

## Task 2: 검출 중 페이지 전체 spinner overlay

- 명세: `runDiscoverPaths()` JS 가 호출 시작 시 페이지 전체 `position: fixed` overlay 표시. 구성:
  - 반투명 검정 backdrop (`rgba(0,0,0,0.5)`)
  - 중앙에 CSS spinner (회전 애니메이션, dark glass 테마와 일관)
  - "검출 중…" 텍스트 + 합산 모드면 "여러 키워드 합산 중 — 최대 N초 소요" 안내
- 동작:
  - `pointer-events: all` 로 backdrop 클릭 차단 (다른 input/button 클릭 막힘)
  - fetch resp 받은 직후 (성공/실패 무관) 자동 제거
  - ESC / overlay 클릭은 무시 (검출 abort 불가)
- 영향 파일: `templates/admin.html` (CSS + JS)

---

## 병렬화 계획 (DAG)

- Chain A: T1 → T2 (같은 파일, mechanical, 1 commit 묶음). 메인 직접 처리 — 서브에이전트 dispatch 오버헤드 회피.
