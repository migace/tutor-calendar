"""Ways of "sending" e-mail that need no mail server.

Real delivery arrives with the transactional outbox (see the roadmap). Until
then the application writes each message to its log, which is enough to follow
a sign-in link during development.
"""

from __future__ import annotations

import logging

from tutor_calendar.application.ports import Email

logger = logging.getLogger("tutor_calendar.mail")


class LoggingMailer:
    async def send(self, email: Email) -> None:
        logger.warning(
            "E-mail is not delivered yet; this message would have been sent.\n"
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
