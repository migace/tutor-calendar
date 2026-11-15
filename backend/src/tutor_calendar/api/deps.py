from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine

from tutor_calendar.application.list_available_slots import ListAvailableSlots
from tutor_calendar.application.ports import Clock, TutorRepository


def get_engine(request: Request) -> AsyncEngine:
    return cast(AsyncEngine, request.app.state.engine)


def get_list_available_slots(request: Request) -> ListAvailableSlots:
    tutors = cast(TutorRepository, request.app.state.tutors)
    clock = cast(Clock, request.app.state.clock)
    return ListAvailableSlots(tutors, clock)


EngineDep = Annotated[AsyncEngine, Depends(get_engine)]
ListAvailableSlotsDep = Annotated[ListAvailableSlots, Depends(get_list_available_slots)]
