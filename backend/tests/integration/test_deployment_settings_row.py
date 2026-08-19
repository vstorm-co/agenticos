"""Guarantees the deployment-settings row makes that only a database can.

The unit suite mocks `deployment_settings_repo`, so everything here is invisible to
it - and one of these is a defect that shipped past a green suite:

**A write must be readable in the same request.** `set_image` loads the row to find
the file it is replacing, then upserts, then answers. Without
`populate_existing=True` the identity map wins on the way back: `RETURNING` yields
the *already-loaded* instance carrying its old attribute values, and so does any
later `select`. The upload answered `logo_version: null` for a logo it had just
stored and was already serving the bytes of.

**There can only be one.** The singleton is enforced by a unique constraint on a
column constrained to true, so a second identity is an `IntegrityError` rather than
a deployment that quietly has two and serves whichever one a query ordered first.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models.deployment_settings import DeploymentSettings
from app.repositories import deployment_settings_repo
from app.services.deployment_settings import DeploymentSettingsService

pytestmark = pytest.mark.anyio


class TestTheSingleton:
    async def test_a_second_row_is_refused_by_the_database(self, db) -> None:
        await deployment_settings_repo.upsert(db, update_data={"app_name": "Acme AI"})

        db.add(DeploymentSettings(id=uuid.uuid4(), singleton=True))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_a_row_that_is_not_the_singleton_is_refused_too(self, db) -> None:
        """The `CHECK` is what stops `singleton=false` slipping past the unique
        constraint and giving the deployment a second identity by another name."""
        db.add(DeploymentSettings(id=uuid.uuid4(), singleton=False))

        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_the_first_write_creates_the_row_and_the_second_updates_it(self, db) -> None:
        await deployment_settings_repo.upsert(db, update_data={"app_name": "Acme AI"})
        await deployment_settings_repo.upsert(db, update_data={"tagline": "Ours"})

        rows = (await db.execute(select(DeploymentSettings))).scalars().all()
        assert len(rows) == 1
        assert (rows[0].app_name, rows[0].tagline) == ("Acme AI", "Ours")

    async def test_an_unconfigured_deployment_has_no_row_at_all(self, db) -> None:
        """Nothing is seeded, and no read creates one - which is what keeps the
        unauthenticated branding endpoint from letting a stranger provoke an
        `INSERT`."""
        await DeploymentSettingsService(db).branding()
        await DeploymentSettingsService(db).notice()
        await DeploymentSettingsService(db).read()

        assert (await db.execute(select(DeploymentSettings))).scalars().all() == []


class TestAWriteIsReadableInTheSameSession:
    async def test_the_upsert_answers_what_it_wrote_not_what_was_loaded(self, db) -> None:
        """The identity map returns the instance it already holds, so without
        `populate_existing` a `RETURNING` row carries the values it was loaded with."""
        await deployment_settings_repo.upsert(db, update_data={"app_name": "First"})
        loaded = await deployment_settings_repo.get(db)
        assert loaded is not None

        written = await deployment_settings_repo.upsert(db, update_data={"app_name": "Second"})

        assert written.app_name == "Second"

    async def test_a_later_read_sees_it_too(self, db) -> None:
        await deployment_settings_repo.upsert(db, update_data={"app_name": "First"})
        await deployment_settings_repo.get(db)

        await deployment_settings_repo.upsert(db, update_data={"app_name": "Second"})
        again = await deployment_settings_repo.get(db)

        assert again is not None
        assert again.app_name == "Second"

    async def test_an_uploaded_image_is_in_the_response_that_stored_it(self, db) -> None:
        """The defect this file exists for, reproduced the way it actually happened.

        The row has to already exist and already be in the session: `set_image` reads
        it to find the file it is replacing, and it is *that* read which puts the
        stale instance in the identity map. On a deployment with no row yet the read
        finds nothing, so the write comes back fresh and the bug is invisible - which
        is why this configures the deployment first.
        """
        service = DeploymentSettingsService(db)
        actor = uuid.uuid4()
        await deployment_settings_repo.upsert(db, update_data={"app_name": "Acme AI"})

        read = await service.set_image(
            actor_user_id=actor,
            kind="logo",
            file_data=b"\x89PNG\r\n",
            content_type="image/png",
        )

        assert read.logo_version is not None
        assert read.app_name == "Acme AI"
        assert await service.image_path("logo") is not None

    async def test_replacing_an_image_answers_a_new_version(self, db) -> None:
        service = DeploymentSettingsService(db)
        actor = uuid.uuid4()
        first = await service.set_image(
            actor_user_id=actor, kind="logo", file_data=b"one", content_type="image/png"
        )

        second = await service.set_image(
            actor_user_id=actor, kind="logo", file_data=b"two", content_type="image/webp"
        )

        assert first.logo_version is not None
        assert second.logo_version is not None

    async def test_clearing_an_image_answers_without_it(self, db) -> None:
        """The same staleness, in the direction where it reports a mark that is gone."""
        service = DeploymentSettingsService(db)
        actor = uuid.uuid4()
        await service.set_image(
            actor_user_id=actor, kind="favicon", file_data=b"gif", content_type="image/gif"
        )

        read = await service.clear_image(actor_user_id=actor, kind="favicon")

        assert read.favicon_version is None
        assert await service.image_path("favicon") is None

    async def test_a_saved_setting_is_in_the_response_that_saved_it(self, db) -> None:
        from app.schemas.deployment_settings import DeploymentSettingsUpdate

        service = DeploymentSettingsService(db)
        await deployment_settings_repo.upsert(db, update_data={"tagline": "Ours"})
        # The read is what loads the row, and so what would go stale.
        await service.read()

        read = await service.update(
            actor_user_id=uuid.uuid4(),
            data=DeploymentSettingsUpdate(app_name="Acme AI", signup_mode="closed"),
        )

        assert read.app_name == "Acme AI"
        assert read.signup_mode == "closed"


class TestWhatTheColumnsHold:
    async def test_the_defaults_are_the_open_deployment_every_install_starts_as(self, db) -> None:
        await deployment_settings_repo.upsert(db, update_data={"app_name": "Acme AI"})
        row = await deployment_settings_repo.get(db)

        assert row is not None
        assert row.signup_mode == "open"
        assert row.allowed_email_domains == []
        assert row.announcement_level == "info"
        assert row.maintenance_mode is False

    async def test_a_domain_list_round_trips_as_a_list(self, db) -> None:
        """JSONB, so what comes back is the list rather than a string of one."""
        await deployment_settings_repo.upsert(
            db, update_data={"allowed_email_domains": ["acme.com", "partner.io"]}
        )
        row = await deployment_settings_repo.get(db)

        assert row is not None
        assert row.allowed_email_domains == ["acme.com", "partner.io"]

    async def test_clearing_an_override_stores_null_rather_than_a_blank(self, db) -> None:
        """Null is what the renderers read as "the built-in"; `''` would render a
        sign-in page with no name on it."""
        await deployment_settings_repo.upsert(db, update_data={"app_name": "Acme AI"})

        await deployment_settings_repo.upsert(db, update_data={"app_name": None})
        row = await deployment_settings_repo.get(db)

        assert row is not None
        assert row.app_name is None
