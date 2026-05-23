"""End-to-end smoke test — Phase B 의 실제 모듈 함수들을 통과시킨다.

test_pipeline.py 는 PipelineDeps 단계를 통째 mock 한다. 여기서는 실제
``search``/``extract``/``summarize``/``send_digest`` 가 호출되며, **외부
경계** (HTTP / trafilatura fetch / Gemini SDK / SMTP) 만 mock 한다. 이러면
내부 wiring 의 정합성 (필드 매핑, 인자 forwarding, dataclass 통과) 가
backpressure 로 검증된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Any, cast

from ai_news_scraping.extract import extract as real_extract
from ai_news_scraping.mail import send_digest as real_send_digest
from ai_news_scraping.pipeline import PipelineDeps, PipelineParams, run
from ai_news_scraping.search import HttpSession
from ai_news_scraping.search import search as real_search
from ai_news_scraping.store import InMemoryArticleStore
from ai_news_scraping.summarize import (
    SummaryInput,
    SummaryOutput,
)
from ai_news_scraping.summarize import (
    summarize as real_summarize,
)

# ───── HTTP fake (search.py 의 HttpSession) ─────


@dataclass
class _Resp:
    payload: dict[str, Any]

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.payload


@dataclass
class FakeHttp:
    items_by_query_token: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def get(
        self,
        url: str,
        *,
        params: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> _Resp:
        self.calls.append({
            "url": url,
            "params": params,
            "headers": headers,
            "timeout": timeout,
        })
        q = params.get("q", "")
        for token, items in self.items_by_query_token.items():
            if token in q:
                return _Resp({"web": {"results": items}})
        return _Resp({"web": {"results": []}})


# ───── trafilatura fake (extract.py 의 fetch/body/meta) ─────


@dataclass
class _Meta:
    title: str | None = None
    date: str | None = None


class FakeFetchers:
    def __init__(self) -> None:
        self.urls_fetched: list[str] = []

    def fetch(self, url: str) -> str:
        self.urls_fetched.append(url)
        return "<html><body><article>" + "x" * 600 + "</article></body></html>"

    def body(self, html: str) -> str:
        return "Long english body text. " * 60

    def meta(self, html: str) -> _Meta:
        return _Meta(title="A breakthrough", date="2026-05-23")


# ───── Gemini fake ─────


@dataclass
class _GResp:
    text: str


@dataclass
class FakeGemini:
    response_text: str = "## 오늘의 AI 트렌드\n- 빅 AI 런칭 (a.com)"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def generate_content(self, *, model: str, contents: str) -> _GResp:
        self.calls.append({"model": model, "contents": contents})
        return _GResp(text=self.response_text)


# ───── SMTP fake ─────


@dataclass
class FakeSmtp:
    sent: list[EmailMessage] = field(default_factory=list)
    quit_called: bool = False

    def send_message(self, msg: EmailMessage) -> dict[str, tuple[int, bytes]]:
        self.sent.append(msg)
        return {}

    def quit(self) -> None:
        self.quit_called = True


# ───── adapter functions (real module 함수를 PipelineDeps 시그니처로 wrap) ─────


def _adapt_search(http: FakeHttp):
    def adapted(
        keyword: str,
        source_domains: list[str],
        *,
        api_key: str,
        num: int = 10,
        freshness: str = "pd",
    ):
        return real_search(
            keyword,
            source_domains,
            api_key=api_key,
            num=num,
            freshness=freshness,
            session=cast(HttpSession, http),
        )

    return adapted


def _adapt_extract(fetchers: FakeFetchers):
    def adapted(url: str):
        return real_extract(
            url,
            fetch_html=fetchers.fetch,
            extract_body=fetchers.body,
            extract_meta=fetchers.meta,
        )

    return adapted


def _adapt_summarize(gemini: FakeGemini):
    def adapted(
        articles: list[SummaryInput],
        *,
        api_key: str,
        model: str,
    ) -> SummaryOutput:
        return real_summarize(articles, api_key=api_key, model=model, client=gemini)

    return adapted


def _adapt_send_mail(smtp: FakeSmtp):
    def adapted(
        *,
        subject: str,
        markdown_body: str,
        sender: str,
        recipients: list[str],
        smtp_password: str,
    ):
        return real_send_digest(
            subject,
            markdown_body,
            sender=sender,
            recipients=recipients,
            smtp_password=smtp_password,
            smtp_factory=lambda: smtp,
        )

    return adapted


# ────────── the smoke test ──────────


def test_smoke_end_to_end_through_real_modules() -> None:
    http = FakeHttp(
        items_by_query_token={
            "artificial intelligence": [
                {
                    "title": "Big AI launch",
                    "url": "https://a.com/2026/05/big-ai-launch-article/",
                    "description": "snippet",
                    "meta_url": {"hostname": "a.com"},
                },
                {
                    "title": "Another AI story",
                    "url": "https://a.com/2026/05/another-ai-news-piece/",
                    "description": "snippet 2",
                    "meta_url": {"hostname": "a.com"},
                },
            ],
        }
    )
    fetchers = FakeFetchers()
    gemini = FakeGemini()
    smtp = FakeSmtp()
    store = InMemoryArticleStore()

    params = PipelineParams(
        keywords=["artificial intelligence"],
        source_domains=["a.com", "b.com"],
        subscribers=["alice@x.com", "bob@x.com"],
        brave_search_api_key="BSK",
        gemini_api_key="G",
        gemini_model="gemini-2.5-flash",
        gmail_user="me@gmail.com",
        gmail_password="P",
        dry_run=False,
    )
    deps = PipelineDeps(
        store=store,
        search_fn=_adapt_search(http),
        extract_fn=_adapt_extract(fetchers),
        summarize_fn=_adapt_summarize(gemini),
        send_mail_fn=_adapt_send_mail(smtp),
    )

    result = run(params, deps)

    # 흐름 결과
    assert result.status == "success"
    assert result.search_total == 2
    assert result.new_count == 2
    assert result.extracted_count == 2
    assert result.article_count == 2
    assert "트렌드" in result.digest_markdown
    assert set(result.accepted) == {"alice@x.com", "bob@x.com"}
    assert result.refused == {}

    # 외부 경계 호출 검증
    assert len(http.calls) == 1, "키워드 1개 → Brave 호출 1회 (CLAUDE.md §6)"
    assert "site:a.com OR site:b.com" in http.calls[0]["params"]["q"]
    assert http.calls[0]["params"]["freshness"] == "pd"
    assert http.calls[0]["headers"]["X-Subscription-Token"] == "BSK"

    assert len(fetchers.urls_fetched) == 2  # 두 URL 각각 fetch

    assert len(gemini.calls) == 1
    prompt = gemini.calls[0]["contents"]
    assert "A breakthrough" in prompt  # extracted title forwarded into prompt
    assert "## 기사" in prompt  # build_prompt header structure

    assert len(smtp.sent) == 1
    sent = smtp.sent[0]
    assert sent["From"] == "me@gmail.com"
    assert sent["To"] == "me@gmail.com"
    assert sent["Bcc"] == "alice@x.com, bob@x.com"
    assert "2026" in sent["Subject"]
    assert smtp.quit_called is True

    # store 에 article 저장
    assert len(store.articles) == 2
    saved_keywords = {a.keyword for a in store.articles.values()}
    assert saved_keywords == {"artificial intelligence"}


def test_smoke_dry_run_skips_mail_but_runs_everything_else() -> None:
    http = FakeHttp(
        items_by_query_token={
            "AI": [
                {
                    "title": "X",
                    "url": "https://a.com/2026/05/something-detailed/",
                    "description": "s",
                    "meta_url": {"hostname": "a.com"},
                }
            ]
        }
    )
    fetchers = FakeFetchers()
    gemini = FakeGemini()
    smtp = FakeSmtp()

    params = PipelineParams(
        keywords=["AI"],
        source_domains=["a.com"],
        subscribers=["x@x.com"],
        brave_search_api_key="BSK",
        gemini_api_key="G",
        gemini_model="m",
        gmail_user="me@gmail.com",
        gmail_password="P",
        dry_run=True,
    )
    deps = PipelineDeps(
        store=InMemoryArticleStore(),
        search_fn=_adapt_search(http),
        extract_fn=_adapt_extract(fetchers),
        summarize_fn=_adapt_summarize(gemini),
        send_mail_fn=_adapt_send_mail(smtp),
    )
    result = run(params, deps)

    assert result.status == "skipped"
    assert result.skipped_reason == "dry_run"
    assert result.article_count == 1
    assert "트렌드" in result.digest_markdown

    # search / extract / summarize 는 모두 실행됨
    assert len(http.calls) == 1
    assert len(fetchers.urls_fetched) == 1
    assert len(gemini.calls) == 1

    # SMTP 는 호출 안 됨
    assert smtp.sent == []
    assert smtp.quit_called is False
