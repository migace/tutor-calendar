"""What every credential store must do, checked against each implementation."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.factories import NOW, a_tutor
from tutor_calendar.adapters.in_memory_credentials import InMemoryCredentialStore
from tutor_calendar.adapters.postgres.credentials import PostgresCredentialStore
from tutor_calendar.adapters.postgres.tutors import PostgresTutorRepository
from tutor_calendar.application.ports import CredentialStore

pytestmark = pytest.mark.anyio

LATER = NOW + timedelta(minutes=15)


class CredentialStoreContract:
    async def test_a_sign_in_token_is_redeemed_for_its_tutor(
        self, store: CredentialStore, tutor_id: UUID
    ) -> None:
        await store.add_sign_in_token("digest-1", tutor_id, LATER)

        assert await store.redeem_sign_in_token("digest-1", NOW) == tutor_id

    async def test_a_sign_in_token_is_redeemed_only_once(
        self, store: CredentialStore, tutor_id: UUID
    ) -> None:
        await store.add_sign_in_token("digest-1", tutor_id, LATER)
        await store.redeem_sign_in_token("digest-1", NOW)

        assert await store.redeem_sign_in_token("digest-1", NOW) is None

    async def test_an_expired_sign_in_token_is_not_redeemed(
        self, store: CredentialStore, tutor_id: UUID
    ) -> None:
        await store.add_sign_in_token("digest-1", tutor_id, LATER)

        assert await store.redeem_sign_in_token("digest-1", LATER) is None
        # Trying too late did not use it up for someone asking about an earlier moment.
        assert await store.redeem_sign_in_token("digest-1", NOW) == tutor_id

    async def test_an_unknown_sign_in_token_is_not_redeemed(self, store: CredentialStore) -> None:
        assert await store.redeem_sign_in_token("never-issued", NOW) is None

    async def test_of_simultaneous_attempts_to_redeem_a_token_one_succeeds(
        self, store: CredentialStore, tutor_id: UUID
    ) -> None:
        await store.add_sign_in_token("digest-1", tutor_id, LATER)

        outcomes = await asyncio.gather(
            *(store.redeem_sign_in_token("digest-1", NOW) for _ in range(12))
        )

        assert sorted(outcomes, key=str) == sorted([tutor_id] + [None] * 11, key=str)

    async def test_a_session_belongs_to_its_tutor_until_it_expires(
        self, store: CredentialStore, tutor_id: UUID
    ) -> None:
        await store.add_session("session-1", tutor_id, LATER)

        assert await store.tutor_for_session("session-1", NOW) == tutor_id
        assert await store.tutor_for_session("session-1", LATER) is None
        assert await store.tutor_for_session("session-2", NOW) is None

    async def test_a_removed_session_is_gone_and_others_stay(
        self, store: CredentialStore, tutor_id: UUID
    ) -> None:
        await store.add_session("session-1", tutor_id, LATER)
        await store.add_session("session-2", tutor_id, LATER)

        await store.remove_session("session-1")
        await store.remove_session("never-existed")

        assert await store.tutor_for_session("session-1", NOW) is None
        assert await store.tutor_for_session("session-2", NOW) == tutor_id

    async def test_sign_in_tokens_and_sessions_are_separate(
        self, store: CredentialStore, tutor_id: UUID
    ) -> None:
        await store.add_sign_in_token("digest-1", tutor_id, LATER)
        await store.add_session("session-1", tutor_id, LATER)

        assert await store.tutor_for_session("digest-1", NOW) is None
        assert await store.redeem_sign_in_token("session-1", NOW) is None


class TestInMemoryCredentialStore(CredentialStoreContract):
    @pytest.fixture
    def store(self) -> CredentialStore:
        return InMemoryCredentialStore()

    @pytest.fixture
    def tutor_id(self) -> UUID:
        return uuid4()


@pytest.mark.integration
class TestPostgresCredentialStore(CredentialStoreContract):
    @pytest.fixture
    def store(self, engine: AsyncEngine) -> CredentialStore:
        return PostgresCredentialStore(engine)

    @pytest.fixture
    async def tutor_id(self, engine: AsyncEngine) -> UUID:
        # Tokens and sessions reference tutors, so the tutor has to exist first.
        tutor = a_tutor()
        assert await PostgresTutorRepository(engine).add_if_absent(tutor)
        return tutor.id
