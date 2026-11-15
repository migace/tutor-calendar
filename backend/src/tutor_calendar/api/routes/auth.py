from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, HTTPException, Response, status

from tutor_calendar.api.deps import (
    SESSION_COOKIE,
    RequestSignInLinkDep,
    SessionToken,
    SettingsDep,
    SignInDep,
    SignOutDep,
)
from tutor_calendar.api.routes.panel import profile_of
from tutor_calendar.api.schemas import ErrorOut, ProfileOut, SignInIn, SignInLinkIn
from tutor_calendar.application.errors import InvalidSignInLinkError
from tutor_calendar.application.sign_in import SESSION_LIFETIME

router = APIRouter(prefix="/auth", tags=["sign-in"])


@router.post(
    "/links",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ask for a sign-in link by e-mail",
    description=(
        "Always answers 202, whether or not the address belongs to a tutor, so it "
        "cannot be used to find out who has an account."
    ),
)
async def request_sign_in_link(body: SignInLinkIn, use_case: RequestSignInLinkDep) -> None:
    await use_case.execute(body.email)


@router.post(
    "/session",
    summary="Sign in with the token from a sign-in link",
    responses={401: {"model": ErrorOut, "description": "The link is expired, used or unknown"}},
)
async def sign_in(
    body: SignInIn, use_case: SignInDep, settings: SettingsDep, response: Response
) -> ProfileOut:
    try:
        signed_in = await use_case.execute(body.token)
    except InvalidSignInLinkError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error

    response.set_cookie(
        SESSION_COOKIE,
        signed_in.session_token,
        max_age=SESSION_LIFETIME // timedelta(seconds=1),
        # Not readable by scripts, so an injected script cannot steal the session.
        httponly=True,
        secure=settings.cookie_secure,
        # Not sent on requests that other sites make, which is the defence
        # against cross-site request forgery. See ADR 0005.
        samesite="lax",
        path="/",
    )
    return profile_of(signed_in.tutor)


@router.delete(
    "/session", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out of this browser"
)
async def sign_out(
    use_case: SignOutDep,
    settings: SettingsDep,
    response: Response,
    session_token: SessionToken = None,
) -> None:
    await use_case.execute(session_token)
    response.delete_cookie(
        SESSION_COOKIE, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/"
    )
