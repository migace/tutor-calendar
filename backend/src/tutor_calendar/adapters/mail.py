"""Ways of sending e-mail.

The application never sends while answering a request. It queues the message
(``OutboxMailer``, or together with the change that caused it), and a worker
sends what is queued through ``SmtpMailer``, or ``LoggingMailer`` when no mail
server is configured. See ADR 0007.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from tutor_calendar.application.ports import Clock, Email, Outbox

logger = logging.getLogger("tutor_calendar.mail")


class OutboxMailer:
    """A mailer that does not send: it queues, and returns at once."""

    def __init__(self, outbox: Outbox, clock: Clock) -> None:
        self._outbox = outbox
        self._clock = clock

    async def send(self, email: Email) -> None:
        await self._outbox.add(email, self._clock.now())


@dataclass(frozen=True, slots=True)
class SmtpMailer:
    host: str
    port: int
    sender: str
    username: str | None = None
    password: str | None = None
    starttls: bool = False
    timeout_seconds: float = 10.0

    async def send(self, email: Email) -> None:
        # smtplib blocks, so it runs on a thread instead of holding up the loop.
        await asyncio.to_thread(self._send, email)

    def _send(self, email: Email) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = email.to
        message["Subject"] = email.subject
        message.set_content(email.body)
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as server:
            if self.starttls:
                server.starttls()
            if self.username is not None and self.password is not None:
                server.login(self.username, self.password)
            server.send_message(message)


class LoggingMailer:
    """For development without a mail server: the message goes to the log."""

    async def send(self, email: Email) -> None:
        logger.warning(
            "No mail server is configured; this message would have been sent.\n"
            "To: %s\nSubject: %s\n\n%s",
            email.to,
            email.subject,
            email.body,
        )


class InMemoryMailer:
    """Keeps what was sent, so tests can read the message a user would receive."""

    def __init__(self) -> None:
        self.sent: list[Email] = []

    async def send(self, email: Email) -> None:
        self.sent.append(email)
