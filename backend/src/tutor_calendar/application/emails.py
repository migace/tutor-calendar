"""The words of the e-mails the application sends."""

from __future__ import annotations

from datetime import datetime

from tutor_calendar.application.ports import Email
from tutor_calendar.domain.scheduling import Booking, Tutor


def _when(lesson: Booking, tutor: Tutor) -> str:
    """The lesson's start on the tutor's clock, with the zone, since the reader's is unknown."""
    tz = tutor.schedule.timezone
    local: datetime = lesson.slot.start.astimezone(tz)
    return f"{local:%A} {local.day} {local:%B %Y}, {local:%H:%M} ({tz.key} time)"


def manage_url(public_url: str, manage_token: str) -> str:
    # In the fragment, which browsers do not send to servers.
    return f"{public_url.rstrip('/')}/booking#token={manage_token}"


def booking_confirmation(
    tutor: Tutor, lesson: Booking, manage_token: str, public_url: str
) -> Email:
    return Email(
        to=lesson.student.email,
        subject=f"Your lesson with {tutor.display_name} is booked",
        body=(
            f"Hello {lesson.student.name},\n\n"
            f"Your lesson with {tutor.display_name} is booked for\n"
            f"{_when(lesson, tutor)}.\n\n"
            "To see the booking or cancel it, use this link. Anyone who has it can\n"
            "cancel the lesson, so keep it to yourself.\n\n"
            f"{manage_url(public_url, manage_token)}\n"
        ),
    )


def lesson_reminder(tutor: Tutor, lesson: Booking, manage_token: str, public_url: str) -> Email:
    return Email(
        to=lesson.student.email,
        subject=f"Reminder: lesson with {tutor.display_name} tomorrow",
        body=(
            f"Hello {lesson.student.name},\n\n"
            f"A reminder of your lesson with {tutor.display_name} on\n"
            f"{_when(lesson, tutor)}.\n\n"
            "If you can no longer make it, cancel here:\n\n"
            f"{manage_url(public_url, manage_token)}\n"
        ),
    )
