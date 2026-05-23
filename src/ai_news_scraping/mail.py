"""Gmail SMTP 발송 wrapper — BCC 일괄 발송.

운영 시 GMAIL_USER + GMAIL_APP_PASSWORD (2FA + 앱 비밀번호) 로 smtp.gmail.com:587
STARTTLS 인증 후 발송. 구독자 명단은 BCC 로 묶어 서로의 주소가 노출되지 않게
한다 (CLAUDE.md §2: 사용자는 ~10명, 개인정보 노출 회피).
"""

from __future__ import annotations

import contextlib
import smtplib
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Protocol

import markdown as md

GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587


@dataclass(frozen=True)
class MailSendResult:
    accepted: list[str]
    refused: dict[str, str]


class SmtpClient(Protocol):
    def send_message(self, msg: EmailMessage) -> dict[str, tuple[int, bytes]]: ...
    def quit(self) -> Any: ...


SmtpFactory = Callable[[], SmtpClient]


def build_message(
    subject: str,
    markdown_body: str,
    *,
    sender: str,
    recipients: list[str],
) -> EmailMessage:
    if not subject.strip():
        raise ValueError("subject must be non-empty")
    if not markdown_body.strip():
        raise ValueError("markdown_body must be non-empty")
    if not recipients:
        raise ValueError("recipients must be non-empty")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = sender  # 본인. 실제 수신자는 BCC.
    msg["Bcc"] = ", ".join(recipients)
    msg.set_content(markdown_body)

    html_body = md.markdown(markdown_body, extensions=["extra", "sane_lists"])
    msg.add_alternative(
        f"<!doctype html><html><body>{html_body}</body></html>",
        subtype="html",
    )
    return msg


def send_digest(
    subject: str,
    markdown_body: str,
    *,
    sender: str,
    recipients: list[str],
    smtp_password: str,
    smtp_factory: SmtpFactory | None = None,
) -> MailSendResult:
    msg = build_message(subject, markdown_body, sender=sender, recipients=recipients)

    factory: SmtpFactory = (
        smtp_factory
        if smtp_factory is not None
        else _default_gmail_factory(sender, smtp_password)
    )
    smtp = factory()
    try:
        refused_raw = smtp.send_message(msg) or {}
    finally:
        # quit 실패는 발송 결과에 영향 없음 — 연결 종료 단계의 잡음.
        with contextlib.suppress(Exception):
            smtp.quit()

    refused: dict[str, str] = {
        addr: f"{code} {body.decode(errors='replace') if isinstance(body, bytes) else body}"
        for addr, (code, body) in refused_raw.items()
    }
    accepted = [r for r in recipients if r not in refused]
    return MailSendResult(accepted=accepted, refused=refused)


def _default_gmail_factory(sender: str, password: str) -> SmtpFactory:
    def factory() -> SmtpClient:
        smtp = smtplib.SMTP(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT)
        smtp.starttls()
        smtp.login(sender, password)
        return smtp  # type: ignore[return-value]

    return factory
