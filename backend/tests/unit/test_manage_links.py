from __future__ import annotations

from uuid import uuid4

import pytest

from tutor_calendar.adapters.manage_links import HmacManageLinks

SECRET = "a-secret-that-is-long-enough-to-be-used"


def test_a_token_leads_back_to_its_booking() -> None:
    links = HmacManageLinks(SECRET)
    booking_id = uuid4()

    assert links.booking_id_in(links.token_for(booking_id)) == booking_id


def test_the_token_for_a_booking_is_always_the_same() -> None:
    booking_id = uuid4()

    # Which is why a repeated booking request can be given the link again
    # without anything having been stored.
    assert HmacManageLinks(SECRET).token_for(booking_id) == HmacManageLinks(SECRET).token_for(
        booking_id
    )


def test_a_token_cannot_be_moved_to_another_booking() -> None:
    links = HmacManageLinks(SECRET)
    mine, someone_elses = uuid4(), uuid4()
    signature = links.token_for(mine).split(".")[1]

    assert links.booking_id_in(f"{someone_elses.hex}.{signature}") is None


def test_a_token_signed_with_another_secret_is_refused() -> None:
    token = HmacManageLinks("another-secret-of-sufficient-length-1234").token_for(uuid4())

    assert HmacManageLinks(SECRET).booking_id_in(token) is None


@pytest.mark.parametrize(
    "token",
    ["", ".", "not-a-token", uuid4().hex, f"{uuid4().hex}.", f"{uuid4().hex}.AAAA", "zz.yy"],
)
def test_anything_else_is_refused(token: str) -> None:
    assert HmacManageLinks(SECRET).booking_id_in(token) is None


def test_knowing_a_booking_id_is_not_enough() -> None:
    links = HmacManageLinks(SECRET)
    booking_id = uuid4()

    # The id is in every API response; the signature is what cannot be made up.
    assert links.booking_id_in(f"{booking_id.hex}.{booking_id.hex}") is None


def test_a_short_secret_is_not_accepted() -> None:
    with pytest.raises(ValueError, match="at least 32"):
        HmacManageLinks("too-short")


def test_random_secrets_differ_between_processes() -> None:
    token = HmacManageLinks.with_random_secret().token_for(uuid4())

    assert HmacManageLinks.with_random_secret().booking_id_in(token) is None
