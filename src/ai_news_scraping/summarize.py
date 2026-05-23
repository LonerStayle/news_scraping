"""Gemini API wrapper — 영문 본문 N개 → 한국어 통합 트렌드 요약.

CLAUDE.md §3 핵심 산출물 2: "개별 번역이 아닌 그날의 AI 트렌드 통합
정리본 (한국어)". gemini-2.5-flash 기본 (무료 tier 충분).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

MAX_BODY_CHARS_PER_ARTICLE = 4000  # 본문 너무 길면 절단 (1M 컨텍스트 보호)


@dataclass(frozen=True)
class SummaryInput:
    title: str
    source_domain: str
    url: str
    body_text: str
    published_at: str | None = None
    source_name: str | None = None  # 예: "TechCrunch". 없으면 source_domain 사용.


@dataclass(frozen=True)
class SummaryOutput:
    digest_markdown: str
    model: str
    article_count: int


class GeminiClient(Protocol):
    def generate_content(self, *, model: str, contents: str) -> Any: ...


def build_prompt(articles: list[SummaryInput]) -> str:
    if not articles:
        raise ValueError("articles must be non-empty")
    formatted = "\n---\n".join(
        _format_article(i + 1, a) for i, a in enumerate(articles)
    )
    return (
        "당신은 AI 트렌드 분석 전문가입니다. "
        f"아래 영문 기사 {len(articles)}건을 읽고, 한국 독자를 위해 오늘의 "
        "AI 트렌드 통합 정리본을 한국어로 작성해 주세요.\n\n"
        "규칙:\n"
        "1. 개별 기사 번역이 아닌, 트렌드 단위로 통합 정리하십시오.\n"
        "2. 비슷한 주제의 기사는 한 단락으로 묶으십시오.\n"
        "3. 출근 전 5분 안에 읽을 수 있는 분량 (마크다운 1~2 페이지) 으로 작성하십시오.\n"
        "4. **링크 규칙 (반드시 지킬 것)**: 매체 이름을 본문/출처에 표기할 때마다 "
        "단순 텍스트가 아닌 마크다운 링크 `[매체명](실제URL)` 형식을 사용하십시오. "
        "예) `[Google DeepMind](https://deepmind.google/blog/gemini-robotics/)`, "
        "`[Ars Technica](https://arstechnica.com/...)`. "
        "잘못된 예: `출처: Ars Technica` (URL 없는 단순 텍스트). "
        "기사 본문에서 다른 매체나 회사를 언급할 때도 가능하면 링크화 하십시오.\n"
        "5. 각 트렌드 섹션 끝에는 **출처 링크 목록**을 줄바꿈으로 나열하십시오. "
        "형식: `- [매체명](URL)` 한 줄씩.\n"
        "6. 출력은 한국어 마크다운만. 영어 원문 인용 최소화.\n\n"
        f"---\n{formatted}\n---\n\n"
        "오늘의 AI 트렌드:\n"
    )


def _format_article(idx: int, a: SummaryInput) -> str:
    body = a.body_text
    if len(body) > MAX_BODY_CHARS_PER_ARTICLE:
        body = body[:MAX_BODY_CHARS_PER_ARTICLE] + "\n[... 본문 절단 ...]"
    published = a.published_at or "(미상)"
    return (
        f"## 기사 {idx}\n"
        f"- 출처: {a.source_domain}\n"
        f"- 제목: {a.title}\n"
        f"- URL: {a.url}\n"
        f"- 발행: {published}\n\n"
        f"{body}\n"
    )


def summarize(
    articles: list[SummaryInput],
    *,
    api_key: str,
    model: str = "gemini-2.5-flash",
    client: GeminiClient | None = None,
) -> SummaryOutput:
    if not articles:
        raise ValueError("articles must be non-empty")
    gemini: GeminiClient = client if client is not None else _make_default_client(api_key)
    prompt = build_prompt(articles)
    response = gemini.generate_content(model=model, contents=prompt)
    text = _extract_text(response)
    if not text:
        raise RuntimeError("Gemini returned empty response")

    # 모델 응답에 출처가 누락되거나 잘못 표시되어도 코드가 보장하는 출처 목록을
    # 항상 메일 끝에 append. 대표님이 모든 기사 원문으로 클릭해 들어갈 수 있음.
    sources_block = build_sources_section(articles)
    full_digest = text.strip() + "\n\n" + sources_block

    return SummaryOutput(
        digest_markdown=full_digest,
        model=model,
        article_count=len(articles),
    )


def build_sources_section(articles: list[SummaryInput]) -> str:
    """Gemini 응답에 무조건 append 되는 백업 출처 목록."""
    lines = ["---", "", "## 오늘 다룬 기사 전체 목록", ""]
    for a in articles:
        label = a.source_name or a.source_domain
        title = a.title.strip() or "(제목 없음)"
        lines.append(f"- [{label}]({a.url}) — {title}")
    return "\n".join(lines)


def _extract_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text.strip()
    return str(response).strip() if response is not None else ""


def _make_default_client(api_key: str) -> GeminiClient:
    # Lazy import — tests using a fake client never hit google-genai.
    from google import genai

    real_client = genai.Client(api_key=api_key)
    return _GeminiSdkAdapter(real_client)


class _GeminiSdkAdapter:
    """Bridges google-genai's ``client.models.generate_content`` to our protocol."""

    def __init__(self, real_client: Any) -> None:
        self._real = real_client

    def generate_content(self, *, model: str, contents: str) -> Any:
        return self._real.models.generate_content(model=model, contents=contents)
