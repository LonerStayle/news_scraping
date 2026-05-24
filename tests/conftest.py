"""pytest 공통 fixture — 모든 테스트에 적용.

send-schedule 시각 게이트가 추가된 이후 (admin-send-schedule, 2026-05-24),
``cli._now_kst`` 의 실시간 KST 시각이 SearchSettings 기본값 (8:40) 의 ±5분
윈도우 밖이면 cli.run_command 가 즉시 skip 되어 다수 통합 테스트가 비결정적
으로 실패. 전역 autouse fixture 가 시각을 8:40 KST 로 고정해 게이트 자동 통과.

개별 시각 게이트 테스트는 본인 ``monkeypatch.setattr(cli, '_now_kst', ...)``
으로 override.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from ai_news_scraping import cli


@pytest.fixture(autouse=True)
def _patch_now_kst_to_send_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli, "_now_kst",
        lambda: datetime(2026, 5, 24, 8, 40, tzinfo=cli.KST),
    )
