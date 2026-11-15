from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine

from tutor_calendar.application.book_lesson import BookLesson
from tutor_calendar.application.list_available_slots import ListAvailableSlots
from tutor_calendar.application.ports import BookingRepository, Clock, TutorRepository


def get_engine(request: Request) -> AsyncEngine:
    return cast(AsyncEngine, request.app.state.engine)


def _tutors(request: Request) -> TutorRepository:
    return cast(TutorRepository, request.app.state.tutors)


def _bookings(request: Request) -> BookingRepository:
    return cast(BookingRepository, request.app.state.bookings)


def _clock(request: Request) -> Clock:
    return cast(Clock, request.app.state.clock)


def get_list_available_slots(request: Request) -> ListAvailableSlots:
    return ListAvailableSlots(_tutors(request), _bookings(request), _clock(request))


def get_book_lesson(request: Request) -> BookLesson:
    return BookLesson(_tutors(request), _bookings(request), _clock(request))


EngineDep = Annotated[AsyncEngine, Depends(get_engine)]
ListAvailableSlotsDep = Annotated[ListAvailableSlots, Depends(get_list_available_slots)]
BookLessonDep = Annotated[BookLesson, Depends(get_book_lesson)]
