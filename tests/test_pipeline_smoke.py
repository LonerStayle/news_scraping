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
    assert http.calls[0]["params"]["freshness"] == "pw"
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


# ════════════════════ F9: cli + DB stores → pipeline 통합 smoke ════════════════════


def test_smoke_db_config_drives_pipeline_via_cli_run_command() -> None:
    """admin 이 DB 에 키워드/매체/settings 를 채운 상태에서 cli.run_command 가
    LoadedConfig 를 통해 pipeline 까지 정확히 흘려보내는지 검증.

    여기서는 fake pipeline_runner 로 PipelineParams 만 capture 한다 — pipeline
    내부 흐름은 test_smoke_end_to_end_through_real_modules 가 이미 커버.
    """
    from datetime import UTC, datetime

    from ai_news_scraping import cli
    from ai_news_scraping.config import Settings
    from ai_news_scraping.domain_config import DomainConfig, Source
    from ai_news_scraping.pipeline import PipelineResult
    from ai_news_scraping.scrape_state_store import InMemoryScrapeStateStore
    from ai_news_scraping.search_config_store import (
        InMemoryKeywordStore,
        InMemorySettingsStore,
        InMemorySourceStore,
    )
    from ai_news_scraping.subscriber_store import InMemorySubscriberStore

    # admin 에서 DB 채운 상태 가정
    kw = InMemoryKeywordStore()
    kw.add("artificial intelligence")
    kw.add("LLM")
    src = InMemorySourceStore()
    src.add("techcrunch.com", "TechCrunch")
    src.add("theverge.com", "The Verge")
    st_settings = InMemorySettingsStore()
    st_settings.update(
        freshness="pd",
        num_results_per_keyword=15,
        max_articles_for_summary=10,
        min_body_len=400,
    )

    sub_store = InMemorySubscriberStore()
    sub_store.add("alice@x.com")

    captured: dict[str, Any] = {}
    now = datetime(2026, 5, 23, 0, 40, 0, tzinfo=UTC)

    def fake_runner(params: PipelineParams, deps: PipelineDeps) -> PipelineResult:
        captured["params"] = params
        return PipelineResult(
            run_id="r", started_at=now, finished_at=now,
            search_total=2, new_count=2, extracted_count=2, article_count=2,
            digest_markdown="ok", accepted=["alice@x.com"], refused={},
            status="success",
        )

    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        brave_search_api_key="BSK",
        gemini_api_key="G",
        gemini_model="gemini-2.5-flash",
        gmail_user="me@gmail.com",
        gmail_app_password="P",
        supabase_url="https://x.supabase.co",
        supabase_service_role_key="SRK",
        admin_token="T",
        dry_run=False,
        digest_tz="Asia/Seoul",
    )
    yaml_fallback = DomainConfig(
        keywords=["yaml-only"],  # DB 가 차 있으니 무시됨
        sources=[Source(domain="yaml.com", name="YAML")],
    )

    rc = cli.run_command(
        settings=settings,
        domain_cfg=yaml_fallback,
        article_store=InMemoryArticleStore(),
        sub_store=sub_store,
        scrape_store=InMemoryScrapeStateStore(initial=True),
        keyword_store=kw,
        source_store=src,
        settings_store=st_settings,
        dry_run=False,
        pipeline_runner=fake_runner,
    )
    assert rc == 0

    p = captured["params"]
    # 키워드/매체 모두 DB 에서 옴 (yaml fallback 무시)
    assert p.keywords == ["artificial intelligence", "LLM"]
    assert p.source_domains == ["techcrunch.com", "theverge.com"]
    assert p.source_name_map == {
        "techcrunch.com": "TechCrunch",
        "theverge.com": "The Verge",
    }
    # settings 도 DB 에서 옴
    assert p.freshness == "pd"
    assert p.num_results_per_keyword == 15
    assert p.max_articles_for_summary == 10


def test_smoke_db_empty_falls_back_to_yaml_via_cli_run_command() -> None:
    """DB 가 비어 있으면 yaml fallback 사용."""
    from datetime import UTC, datetime

    from ai_news_scraping import cli
    from ai_news_scraping.config import Settings
    from ai_news_scraping.domain_config import DomainConfig, Source
    from ai_news_scraping.pipeline import PipelineResult
    from ai_news_scraping.scrape_state_store import InMemoryScrapeStateStore
    from ai_news_scraping.search_config_store import (
        InMemoryKeywordStore,
        InMemorySettingsStore,
        InMemorySourceStore,
    )
    from ai_news_scraping.subscriber_store import InMemorySubscriberStore

    sub_store = InMemorySubscriberStore()
    sub_store.add("x@x.com")

    captured: dict[str, Any] = {}
    now = datetime(2026, 5, 23, 0, 40, 0, tzinfo=UTC)

    def fake_runner(params: PipelineParams, deps: PipelineDeps) -> PipelineResult:
        captured["params"] = params
        return PipelineResult(
            run_id="r", started_at=now, finished_at=now,
            search_total=0, new_count=0, extracted_count=0, article_count=0,
            digest_markdown="", accepted=[], refused={},
            status="skipped",
        )

    cli.run_command(
        settings=Settings(  # type: ignore[call-arg]
            _env_file=None,
            brave_search_api_key="K", gemini_api_key="G",
            gemini_model="m", gmail_user="me@x.com", gmail_app_password="P",
            supabase_url="https://x.supabase.co", supabase_service_role_key="SRK",
            admin_token="T", dry_run=False, digest_tz="Asia/Seoul",
        ),
        domain_cfg=DomainConfig(
            keywords=["yaml-kw1", "yaml-kw2"],
            sources=[
                Source(domain="yaml-a.com", name="YAML A"),
                Source(domain="yaml-b.com", name="YAML B"),
            ],
        ),
        article_store=InMemoryArticleStore(),
        sub_store=sub_store,
        scrape_store=InMemoryScrapeStateStore(initial=True),
        keyword_store=InMemoryKeywordStore(),
        source_store=InMemorySourceStore(),
        settings_store=InMemorySettingsStore(),
        dry_run=False,
        pipeline_runner=fake_runner,
    )

    p = captured["params"]
    assert p.keywords == ["yaml-kw1", "yaml-kw2"]
    assert p.source_domains == ["yaml-a.com", "yaml-b.com"]
    assert p.source_name_map == {"yaml-a.com": "YAML A", "yaml-b.com": "YAML B"}
