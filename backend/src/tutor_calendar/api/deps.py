from __future__ import annotations

from typing import Annotated, cast

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncEngine

from tutor_calendar.application.book_lesson import BookLesson
from tutor_calendar.application.errors import NotSignedInError
from tutor_calendar.application.list_available_slots import ListAvailableSlots
from tutor_calendar.application.ports import (
    BookingRepository,
    Clock,
    CredentialStore,
    Mailer,
    TutorRepository,
)
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


def _bookings(request: Request) -> BookingRepository:
    return cast(BookingRepository, request.app.state.bookings)


def _credentials(request: Request) -> CredentialStore:
    return cast(CredentialStore, request.app.state.credentials)


def _clock(request: Request) -> Clock:
    return cast(Clock, request.app.state.clock)


def get_list_available_slots(request: Request) -> ListAvailableSlots:
    return ListAvailableSlots(_tutors(request), _bookings(request), _clock(request))


def get_book_lesson(request: Request) -> BookLesson:
    return BookLesson(_tutors(request), _bookings(request), _clock(request))


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
SettingsDep = Annotated[Settings, Depends(get_settings)]
ListAvailableSlotsDep = Annotated[ListAvailableSlots, Depends(get_list_available_slots)]
BookLessonDep = Annotated[BookLesson, Depends(get_book_lesson)]
RequestSignInLinkDep = Annotated[RequestSignInLink, Depends(get_request_sign_in_link)]
SignInDep = Annotated[SignIn, Depends(get_sign_in)]
SignOutDep = Annotated[SignOut, Depends(get_sign_out)]
ShowWeekDep = Annotated[ShowWeek, Depends(get_show_week)]
ChangeWeeklyHoursDep = Annotated[ChangeWeeklyHours, Depends(get_change_weekly_hours)]
SignedInTutor = Annotated[Tutor, Depends(get_signed_in_tutor)]
