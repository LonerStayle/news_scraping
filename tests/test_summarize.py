from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from ai_news_scraping.summarize import (
    MAX_BODY_CHARS_PER_ARTICLE,
    SummaryInput,
    SummaryOutput,
    build_prompt,
    summarize,
)


def _input(idx: int = 1, body: str = "english body text") -> SummaryInput:
    return SummaryInput(
        title=f"Title {idx}",
        source_domain=f"src{idx}.com",
        url=f"https://src{idx}.com/a",
        body_text=body,
        published_at="2026-05-23",
    )


# ───────── build_prompt ─────────


def test_build_prompt_includes_all_articles_with_korean_instruction() -> None:
    prompt = build_prompt([_input(1), _input(2), _input(3)])
    assert "한국어" in prompt
    assert "3건" in prompt
    assert "Title 1" in prompt
    assert "Title 3" in prompt
    assert "src2.com" in prompt
    assert "오늘의 AI 트렌드:" in prompt


def test_build_prompt_marks_missing_published_at() -> None:
    article = SummaryInput(
        title="T", source_domain="x.com", url="https://x.com/a", body_text="b" * 300
    )
    prompt = build_prompt([article])
    assert "(미상)" in prompt


def test_build_prompt_truncates_long_body() -> None:
    long_body = "x" * (MAX_BODY_CHARS_PER_ARTICLE + 5000)
    prompt = build_prompt([_input(body=long_body)])
    assert "본문 절단" in prompt
    assert prompt.count("x") <= MAX_BODY_CHARS_PER_ARTICLE + 100  # 안전 margin


def test_build_prompt_rejects_empty() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        build_prompt([])


# ───────── summarize ─────────


@dataclass
class FakeResponse:
    text: str


@dataclass
class FakeGeminiClient:
    response_text: str = "## 오늘의 AI 트렌드\n- LLM 시장 활기"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def generate_content(self, *, model: str, contents: str) -> FakeResponse:
        self.calls.append({"model": model, "contents": contents})
        return FakeResponse(text=self.response_text)


def test_summarize_returns_digest() -> None:
    client = FakeGeminiClient()
    result = summarize(
        [_input(1), _input(2)],
        api_key="ignored",
        model="gemini-2.5-flash",
        client=client,
    )
    assert isinstance(result, SummaryOutput)
    assert result.digest_markdown.startswith("## 오늘의 AI 트렌드")
    assert result.model == "gemini-2.5-flash"
    assert result.article_count == 2
    assert len(client.calls) == 1
    assert client.calls[0]["model"] == "gemini-2.5-flash"
    assert "Title 1" in client.calls[0]["contents"]


def test_summarize_empty_articles_raises() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        summarize([], api_key="k", client=FakeGeminiClient())


def test_summarize_empty_response_raises() -> None:
    client = FakeGeminiClient(response_text="   ")
    with pytest.raises(RuntimeError, match="empty"):
        summarize([_input()], api_key="k", client=client)


def test_summarize_uses_custom_model() -> None:
    client = FakeGeminiClient()
    summarize([_input()], api_key="k", model="gemini-2.5-pro", client=client)
    assert client.calls[0]["model"] == "gemini-2.5-pro"
