from __future__ import annotations

from typing import Annotated, cast

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncEngine

from tutor_calendar.application.billing import (
    ListAccounts,
    RecordEntry,
    ShareStatement,
    ShowStatement,
)
from tutor_calendar.application.book_lesson import BookLesson
from tutor_calendar.application.errors import NotSignedInError
from tutor_calendar.application.lessons import ChangeOwnLesson, ManageBooking
from tutor_calendar.application.list_available_slots import ListAvailableSlots
from tutor_calendar.application.ports import (
    Clock,
    CredentialStore,
    Ledger,
    LessonStore,
    Mailer,
    ManageLinks,
    StatementLinks,
    TutorRepository,
)
from tutor_calendar.application.series import EndSeries, ListSeries, StartSeries
from tutor_calendar.application.sign_in import Authenticate, RequestSignInLink, SignIn, SignOut
from tutor_calendar.application.tutor_panel import ChangeWeeklyHours, ShowWeek
from tutor_calendar.config import Settings
from tutor_calendar.domain.scheduling import Tutor

SESSION_COOKIE = "tc_session"


def get_engine(request: Request) -> AsyncEngine:
    return cast(AsyncEngine, request.app.state.engine)


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def _tutors(request: Request) -> TutorRepository:
    return cast(TutorRepository, request.app.state.tutors)


def _bookings(request: Request) -> LessonStore:
    # One object in every role; each use case below is typed to the role it needs.
    return cast(LessonStore, request.app.state.bookings)


def _credentials(request: Request) -> CredentialStore:
    return cast(CredentialStore, request.app.state.credentials)


def _clock(request: Request) -> Clock:
    return cast(Clock, request.app.state.clock)


def get_list_available_slots(request: Request) -> ListAvailableSlots:
    return ListAvailableSlots(_tutors(request), _bookings(request), _clock(request))


def _links(request: Request) -> ManageLinks:
    return cast(ManageLinks, request.app.state.links)


def get_book_lesson(request: Request) -> BookLesson:
    return BookLesson(
        _tutors(request),
        _bookings(request),
        _links(request),
        _clock(request),
        get_settings(request).public_url,
    )


def _ledger(request: Request) -> Ledger:
    return cast(Ledger, request.app.state.ledger)


def get_record_entry(request: Request) -> RecordEntry:
    return RecordEntry(_ledger(request), _clock(request))


def get_list_accounts(request: Request) -> ListAccounts:
    return ListAccounts(_ledger(request), _bookings(request))


def get_show_statement(request: Request) -> ShowStatement:
    return ShowStatement(_ledger(request), _bookings(request), _clock(request))


def get_share_statement(request: Request) -> ShareStatement:
    return ShareStatement(
        _tutors(request),
        get_show_statement(request),
        cast(StatementLinks, request.app.state.statement_links),
    )


def get_manage_booking(request: Request) -> ManageBooking:
    return ManageBooking(_bookings(request), _tutors(request), _links(request), _clock(request))


def get_change_own_lesson(request: Request) -> ChangeOwnLesson:
    return ChangeOwnLesson(_bookings(request), _clock(request))


def get_start_series(request: Request) -> StartSeries:
    return StartSeries(_bookings(request), _clock(request))


def get_list_series(request: Request) -> ListSeries:
    return ListSeries(_bookings(request))


def get_end_series(request: Request) -> EndSeries:
    return EndSeries(_bookings(request), _bookings(request), _clock(request))


def get_request_sign_in_link(request: Request) -> RequestSignInLink:
    return RequestSignInLink(
        _tutors(request),
        _credentials(request),
        cast(Mailer, request.app.state.mailer),
        _clock(request),
        get_settings(request).public_url,
    )


def get_sign_in(request: Request) -> SignIn:
    return SignIn(_tutors(request), _credentials(request), _clock(request))


def get_sign_out(request: Request) -> SignOut:
    return SignOut(_credentials(request))


def get_show_week(request: Request) -> ShowWeek:
    return ShowWeek(_bookings(request), _clock(request))


def get_change_weekly_hours(request: Request) -> ChangeWeeklyHours:
    return ChangeWeeklyHours(_tutors(request))


SessionToken = Annotated[str | None, Cookie(alias=SESSION_COOKIE, include_in_schema=False)]


async def get_signed_in_tutor(request: Request, session_token: SessionToken = None) -> Tutor:
    authenticate = Authenticate(_tutors(request), _credentials(request), _clock(request))
    try:
        return await authenticate.execute(session_token)
    except NotSignedInError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error


EngineDep = Annotated[AsyncEngine, Depends(get_engine)]
ClockDep = Annotated[Clock, Depends(_clock)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
ListAvailableSlotsDep = Annotated[ListAvailableSlots, Depends(get_list_available_slots)]
BookLessonDep = Annotated[BookLesson, Depends(get_book_lesson)]
ManageBookingDep = Annotated[ManageBooking, Depends(get_manage_booking)]
ChangeOwnLessonDep = Annotated[ChangeOwnLesson, Depends(get_change_own_lesson)]
StartSeriesDep = Annotated[StartSeries, Depends(get_start_series)]
ListSeriesDep = Annotated[ListSeries, Depends(get_list_series)]
EndSeriesDep = Annotated[EndSeries, Depends(get_end_series)]
RecordEntryDep = Annotated[RecordEntry, Depends(get_record_entry)]
ListAccountsDep = Annotated[ListAccounts, Depends(get_list_accounts)]
ShowStatementDep = Annotated[ShowStatement, Depends(get_show_statement)]
ShareStatementDep = Annotated[ShareStatement, Depends(get_share_statement)]
RequestSignInLinkDep = Annotated[RequestSignInLink, Depends(get_request_sign_in_link)]
SignInDep = Annotated[SignIn, Depends(get_sign_in)]
SignOutDep = Annotated[SignOut, Depends(get_sign_out)]
ShowWeekDep = Annotated[ShowWeek, Depends(get_show_week)]
ChangeWeeklyHoursDep = Annotated[ChangeWeeklyHours, Depends(get_change_weekly_hours)]
SignedInTutor = Annotated[Tutor, Depends(get_signed_in_tutor)]
