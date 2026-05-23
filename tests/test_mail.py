from __future__ import annotations

from dataclasses import dataclass, field
from email.message import EmailMessage

import pytest

from ai_news_scraping.mail import (
    MailSendResult,
    build_message,
    send_digest,
)

# ────────── build_message ──────────


def test_build_message_uses_bcc_and_to_self() -> None:
    msg = build_message(
        "오늘의 AI 트렌드",
        "# AI 트렌드\n- LLM 시장 활기",
        sender="me@gmail.com",
        recipients=["a@x.com", "b@x.com"],
    )
    assert msg["Subject"] == "오늘의 AI 트렌드"
    assert msg["From"] == "me@gmail.com"
    assert msg["To"] == "me@gmail.com"
    assert msg["Bcc"] == "a@x.com, b@x.com"


def test_build_message_has_plain_and_html_parts() -> None:
    msg = build_message(
        "S",
        "# header\n- item1\n- item2",
        sender="s@x.com",
        recipients=["r@x.com"],
    )
    plain = msg.get_body(preferencelist=("plain",))
    html = msg.get_body(preferencelist=("html",))
    assert plain is not None
    assert html is not None
    assert "# header" in plain.get_content()
    html_content = html.get_content()
    assert "<h1>" in html_content or "<H1>" in html_content
    assert "<li>" in html_content


def test_build_message_rejects_empty_subject() -> None:
    with pytest.raises(ValueError, match="subject"):
        build_message("  ", "body", sender="s@x.com", recipients=["a@x.com"])


def test_build_message_rejects_empty_body() -> None:
    with pytest.raises(ValueError, match="markdown_body"):
        build_message("S", "  ", sender="s@x.com", recipients=["a@x.com"])


def test_build_message_rejects_empty_recipients() -> None:
    with pytest.raises(ValueError, match="recipients"):
        build_message("S", "body", sender="s@x.com", recipients=[])


# ────────── send_digest ──────────


@dataclass
class FakeSmtp:
    refused: dict[str, tuple[int, bytes]] = field(default_factory=dict)
    sent: list[EmailMessage] = field(default_factory=list)
    quit_called: bool = False
    quit_raises: bool = False

    def send_message(self, msg: EmailMessage) -> dict[str, tuple[int, bytes]]:
        self.sent.append(msg)
        return self.refused

    def quit(self) -> None:
        self.quit_called = True
        if self.quit_raises:
            raise OSError("connection already closed")


def test_send_digest_all_accepted() -> None:
    smtp = FakeSmtp()
    result = send_digest(
        "S",
        "body",
        sender="me@x.com",
        recipients=["a@x.com", "b@x.com"],
        smtp_password="ignored",
        smtp_factory=lambda: smtp,
    )
    assert result == MailSendResult(accepted=["a@x.com", "b@x.com"], refused={})
    assert smtp.quit_called
    assert len(smtp.sent) == 1


def test_send_digest_partial_refused() -> None:
    smtp = FakeSmtp(refused={"bad@x.com": (550, b"User unknown")})
    result = send_digest(
        "S",
        "body",
        sender="me@x.com",
        recipients=["a@x.com", "bad@x.com"],
        smtp_password="x",
        smtp_factory=lambda: smtp,
    )
    assert result.accepted == ["a@x.com"]
    assert "bad@x.com" in result.refused
    assert "550" in result.refused["bad@x.com"]


def test_send_digest_quit_failure_is_swallowed() -> None:
    smtp = FakeSmtp(quit_raises=True)
    result = send_digest(
        "S",
        "body",
        sender="me@x.com",
        recipients=["a@x.com"],
        smtp_password="x",
        smtp_factory=lambda: smtp,
    )
    assert result.accepted == ["a@x.com"]


def test_send_digest_empty_recipients_raises() -> None:
    captured: list[str] = []

    def tracking_factory() -> FakeSmtp:
        captured.append("called")
        return FakeSmtp()

    with pytest.raises(ValueError, match="recipients"):
        send_digest(
            "S",
            "body",
            sender="me@x.com",
            recipients=[],
            smtp_password="x",
            smtp_factory=tracking_factory,
        )
    assert captured == []  # factory must not be called when input invalid
