"""Prepaid lesson time: accounts and statements for the tutor, a statement for the parent."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from tutor_calendar.api.deps import (
    ListAccountsDep,
    OpenAccountDep,
    OwnStudent,
    RecordEntryDep,
    ShareStatementDep,
    ShowStatementDep,
    SignedInTutor,
)
from tutor_calendar.api.schemas import (
    AccountIn,
    AccountOut,
    EntryIn,
    EntryOut,
    ErrorOut,
    StatementOut,
)
from tutor_calendar.application.billing import Account, StatementView
from tutor_calendar.application.errors import InvalidEntryError, StatementNotFoundError
from tutor_calendar.domain.billing import EntryKind, LedgerEntry

panel = APIRouter(
    prefix="/me/students",
    tags=["tutor panel"],
    responses={401: {"model": ErrorOut, "description": "Not signed in"}},
)
shared = APIRouter(prefix="/statement", tags=["statements"])

Month = Annotated[
    dt.date | None,
    Query(description="Any day of the month to show; defaults to the current month"),
]


def _entry_out(entry: LedgerEntry) -> EntryOut:
    return EntryOut(
        id=entry.id,
        kind=entry.kind.value,
        minutes=entry.minutes,
        note=entry.note,
        at=entry.effective_at,
        lesson_id=entry.booking_id,
    )


def _statement_out(view: StatementView, share_token: str | None) -> StatementOut:
    return StatementOut(
        tutor_name=view.tutor.display_name,
        timezone=view.tutor.schedule.timezone.key,
        student_email=view.account,
        student_name=view.student_name,
        month=view.month,
        previous=view.previous,
        next=view.next,
        opening_minutes=view.statement.opening,
        closing_minutes=view.statement.closing,
        balance_minutes=view.balance_now,
        entries=[_entry_out(entry) for entry in view.statement.entries],
        nothing_recorded=view.nothing_recorded,
        share_token=share_token,
    )


def _account_out(account: Account) -> AccountOut:
    return AccountOut(
        id=account.id, email=account.email, name=account.name, balance_minutes=account.balance
    )


@panel.get("", summary="The tutor's students and the lesson time each has left")
async def list_accounts(tutor: SignedInTutor, use_case: ListAccountsDep) -> list[AccountOut]:
    return [_account_out(account) for account in await use_case.execute(tutor)]


@panel.post(
    "",
    summary="The student with an address, added if the tutor has none",
    description=(
        "How to reach a student who has not booked anything yet. The address travels "
        "in the body, once; every other request names the student by the id returned "
        "here, so that addresses of pages and requests never contain an e-mail address. "
        "Asking again for the same address returns the same student."
    ),
)
async def open_account(
    body: AccountIn, tutor: SignedInTutor, use_case: OpenAccountDep
) -> AccountOut:
    return _account_out(await use_case.execute(tutor, body.email))


_no_such_student: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorOut, "description": "This tutor has no such student"}
}


@panel.put(
    "/{student_id}/entries/{entry_id}",
    summary="Record time a student bought, or a correction",
    description=(
        "Entries are permanent: a mistake is corrected by another entry. The client "
        "chooses the id, and sending the same entry again changes nothing."
    ),
    responses={
        **_no_such_student,
        422: {"description": "The entry makes no sense, or the id means another entry"},
    },
)
async def record_entry(
    student: OwnStudent,
    entry_id: UUID,
    body: EntryIn,
    tutor: SignedInTutor,
    use_case: RecordEntryDep,
) -> EntryOut:
    try:
        entry = await use_case.execute(
            tutor, entry_id, student.account, EntryKind(body.kind), body.minutes, body.note
        )
    except InvalidEntryError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return _entry_out(entry)


@panel.get(
    "/{student_id}/statement",
    summary="One month of a student's account",
    responses=_no_such_student,
)
async def tutor_statement(
    student: OwnStudent,
    tutor: SignedInTutor,
    show: ShowStatementDep,
    share: ShareStatementDep,
    month: Month = None,
) -> StatementOut:
    view = await show.execute(tutor, student.account, month)
    return _statement_out(view, share.token_for(tutor, student.account))


_bearer = HTTPBearer(auto_error=False, description="The token from a statement link")


@shared.get(
    "",
    summary="The statement a shared link belongs to",
    description="For parents: shows one student's account with one tutor and nothing else.",
    responses={401: {"model": ErrorOut, "description": "The token is missing or not valid"}},
)
async def shared_statement(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    share: ShareStatementDep,
    month: Month = None,
) -> StatementOut:
    try:
        if credentials is None:
            raise StatementNotFoundError
        view = await share.view(credentials.credentials, month)
    except StatementNotFoundError as error:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, detail="this link is not valid"
        ) from error
    return _statement_out(view, share_token=None)
