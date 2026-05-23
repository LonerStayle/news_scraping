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
        "2. 비슷한 주제의 기사는 한 단락으로 묶고, 출처 매체를 함께 명시하십시오.\n"
        "3. 출근 전 5분 안에 읽을 수 있는 분량 (마크다운 1~2 페이지) 으로 작성하십시오.\n"
        "4. 각 트렌드 끝에 출처 링크를 [매체명](URL) 형식으로 첨부하십시오.\n"
        "5. 출력은 한국어 마크다운만. 영어 원문 인용 최소화.\n\n"
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
    return SummaryOutput(
        digest_markdown=text.strip(),
        model=model,
        article_count=len(articles),
    )


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
