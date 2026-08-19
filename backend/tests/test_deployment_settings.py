"""This deployment's own identity: what it stores, and what it refuses to store.

The identity half of this feature is cosmetic and the tests for it are not, for
three reasons that each cost something when they were wrong somewhere else in this
codebase:

**A read must not write.** `GET /api/v1/branding` is unauthenticated, so a
read-through that created the settings row would let a stranger provoke an
`INSERT`. Every "no row" case here asserts the defaults come back *and* that
nothing was upserted.

**A cleared field means the built-in, not a blank.** An operator who empties the
name input is asking for `agenticos` back, not for a sign-in page with no name on
it - so `""` becomes `None` at the boundary rather than reaching the column.

**An image's name is ours.** The stored filename is minted from the validated
content type, never taken from the upload: this file is served from the origin the
app's own pages run on, and `logo.html` there is a script rather than a picture.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.core.config import Settings, settings
from app.core.exceptions import BadRequestError
from app.db.models.deployment_settings import DeploymentSettings
from app.repositories import deployment_settings_repo
from app.schemas.deployment_settings import DeploymentSettingsUpdate
from app.services import deployment_settings as module
from app.services.deployment_settings import DeploymentSettingsService

pytestmark = pytest.mark.anyio

WRITTEN = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def a_row(**overrides) -> DeploymentSettings:
    """A settings row with every column at its default, before any override."""
    row = DeploymentSettings(
        id=uuid4(),
        singleton=True,
        app_name=None,
        tagline=None,
        description=None,
        logo_path=None,
        favicon_path=None,
        footer_text=None,
        terms_url=None,
        privacy_url=None,
        signup_mode="open",
        allowed_email_domains=[],
        announcement=None,
        announcement_level="info",
        maintenance_mode=False,
        maintenance_message=None,
    )
    row.created_at = WRITTEN
    row.updated_at = None
    for field, value in overrides.items():
        setattr(row, field, value)
    return row


@pytest.fixture
def repo(monkeypatch) -> MagicMock:
    """The repository, stubbed. `get` answers no row until a test says otherwise."""
    stub = MagicMock()
    stub.get = AsyncMock(return_value=None)
    stub.upsert = AsyncMock(return_value=a_row())
    monkeypatch.setattr(module, "deployment_settings_repo", stub)
    monkeypatch.setattr(module, "publish_maintenance", AsyncMock())
    return stub


@pytest.fixture
def storage(monkeypatch) -> MagicMock:
    """The file store, stubbed. `save` answers the key it was asked to write."""
    stub = MagicMock()
    stub.save = AsyncMock(side_effect=lambda key, name, _data: f"{key}/abc_{name}")
    stub.delete = AsyncMock()
    monkeypatch.setattr(module, "get_file_storage", lambda: stub)
    return stub


class TestWhatAStrangerMayRead:
    async def test_an_unconfigured_deployment_answers_defaults_without_writing_a_row(
        self, mock_db_session, repo
    ):
        """No row means every built-in, and the absence *is* the initial value.

        Creating one here would mean an unauthenticated GET provoking an INSERT on
        a deployment nobody has administered.
        """
        branding = await DeploymentSettingsService(mock_db_session).branding()

        assert branding.app_name is None
        assert branding.signup_mode == "open"
        assert branding.maintenance_mode is False
        repo.upsert.assert_not_called()

    async def test_it_answers_the_overrides_that_were_actually_set(self, mock_db_session, repo):
        repo.get.return_value = a_row(
            app_name="Acme AI",
            tagline="Agents for Acme",
            description="Self-hosted.",
            footer_text="© Acme",
            terms_url="https://acme.com/terms",
            privacy_url="https://acme.com/privacy",
            signup_mode="invite_only",
            allowed_email_domains=["acme.com"],
            maintenance_mode=True,
            maintenance_message="Back at 22:00",
        )

        branding = await DeploymentSettingsService(mock_db_session).branding()

        assert branding.app_name == "Acme AI"
        assert branding.tagline == "Agents for Acme"
        assert branding.description == "Self-hosted."
        assert branding.footer_text == "© Acme"
        assert branding.terms_url == "https://acme.com/terms"
        assert branding.privacy_url == "https://acme.com/privacy"
        assert branding.signup_mode == "invite_only"
        assert branding.allowed_email_domains == ["acme.com"]
        assert branding.maintenance_mode is True
        assert branding.maintenance_message == "Back at 22:00"

    async def test_the_announcement_is_not_in_it(self, mock_db_session, repo):
        """The banner is an operator talking to the people using the deployment -
        an upgrade window, who to ping. A stranger on the sign-in page reads this
        endpoint, and has no part in that."""
        repo.get.return_value = a_row(announcement="Postgres upgrade at 22:00")

        branding = await DeploymentSettingsService(mock_db_session).branding()

        assert "announcement" not in branding.model_dump()
        assert "Postgres" not in branding.model_dump_json()

    async def test_an_unrecognised_signup_mode_reads_as_open(self, mock_db_session, repo):
        """A column holds text and the `Literal` is a promise about it. `open` is the
        safe direction: the alternative refuses every registration on a deployment
        whose administrator never asked for that, and that refusal has no page to
        explain itself on."""
        repo.get.return_value = a_row(signup_mode="whatever-a-later-version-called-it")

        assert (await DeploymentSettingsService(mock_db_session).branding()).signup_mode == "open"


class TestTheImageVersion:
    async def test_no_upload_means_no_version_at_all(self, mock_db_session, repo):
        """Which is what the frontend reads as "draw your own mark"."""
        repo.get.return_value = a_row()

        branding = await DeploymentSettingsService(mock_db_session).branding()

        assert branding.logo_version is None
        assert branding.favicon_version is None

    async def test_the_storage_key_never_reaches_the_wire(self, mock_db_session, repo):
        """The key is an implementation detail of whichever backend is configured, and
        publishing it would let a caller address the store directly."""
        repo.get.return_value = a_row(logo_path="deployment/abc_logo.png")

        branding = await DeploymentSettingsService(mock_db_session).branding()

        assert branding.logo_version is not None
        assert "deployment/abc_logo.png" not in branding.model_dump_json()

    async def test_a_replaced_image_changes_the_version(self, mock_db_session, repo):
        """The address is constant and the bytes carry a year of `immutable`, so
        without this a browser holding the previous logo has no reason to ask again
        and the upload looks like it silently failed."""
        repo.get.return_value = a_row(logo_path="deployment/one.png")
        before = (await DeploymentSettingsService(mock_db_session).branding()).logo_version

        second = a_row(logo_path="deployment/two.png")
        second.updated_at = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
        repo.get.return_value = second
        after = (await DeploymentSettingsService(mock_db_session).branding()).logo_version

        assert before != after

    async def test_a_freshly_created_row_still_gets_a_real_stamp(self, mock_db_session, repo):
        """A Core upsert that inserts leaves `updated_at` null, so `created_at` is the
        write time - and every image would otherwise be served under the same token."""
        repo.get.return_value = a_row(favicon_path="deployment/abc_favicon.png")

        version = (await DeploymentSettingsService(mock_db_session).branding()).favicon_version

        assert version == int(WRITTEN.timestamp())


class TestTheBanner:
    async def test_an_unconfigured_deployment_has_no_notice(self, mock_db_session, repo):
        notice = await DeploymentSettingsService(mock_db_session).notice()

        assert notice.message is None
        assert notice.level == "info"

    async def test_an_empty_announcement_is_no_notice(self, mock_db_session, repo):
        """A cleared announcement takes the banner down; it does not draw an empty one."""
        repo.get.return_value = a_row(announcement=None, announcement_level="critical")

        assert (await DeploymentSettingsService(mock_db_session).notice()).message is None

    async def test_it_carries_the_level_the_operator_chose(self, mock_db_session, repo):
        repo.get.return_value = a_row(announcement="Window at 22:00", announcement_level="warning")

        notice = await DeploymentSettingsService(mock_db_session).notice()

        assert notice.message == "Window at 22:00"
        assert notice.level == "warning"

    async def test_an_unrecognised_level_draws_as_info(self, mock_db_session, repo):
        repo.get.return_value = a_row(announcement="Hello", announcement_level="apocalyptic")

        assert (await DeploymentSettingsService(mock_db_session).notice()).level == "info"


class TestTheAdministratorsView:
    async def test_it_is_one_request_for_the_whole_form(self, mock_db_session, repo):
        repo.get.return_value = a_row(app_name="Acme AI", announcement="Window at 22:00")

        read = await DeploymentSettingsService(mock_db_session).read()

        assert read.app_name == "Acme AI"
        assert read.announcement == "Window at 22:00"
        assert repo.get.await_count == 1

    async def test_it_works_before_anything_has_been_configured(self, mock_db_session, repo):
        read = await DeploymentSettingsService(mock_db_session).read()

        assert read.app_name is None
        assert read.announcement is None
        assert read.announcement_level == "info"
        assert read.updated_at is None


class TestWriting:
    async def test_it_writes_only_the_fields_the_request_named(self, mock_db_session, repo):
        """A PATCH, so an administrator editing the name does not have to resend the
        announcement - and does not silently clear it by omitting it."""
        await DeploymentSettingsService(mock_db_session).update(
            actor_user_id=uuid4(), data=DeploymentSettingsUpdate(app_name="Acme AI")
        )

        assert repo.upsert.await_args.kwargs["update_data"] == {"app_name": "Acme AI"}

    async def test_an_explicit_null_clears_an_override(self, mock_db_session, repo):
        """Nullable, so the `None` survives and the renderer falls back to its
        built-in. "Cleared" is a state an operator asks for."""
        data = DeploymentSettingsUpdate.model_validate({"tagline": None})

        await DeploymentSettingsService(mock_db_session).update(actor_user_id=uuid4(), data=data)

        assert repo.upsert.await_args.kwargs["update_data"] == {"tagline": None}

    async def test_a_null_a_column_refuses_never_reaches_it(self, mock_db_session, repo):
        """`signup_mode` is NOT NULL, so `None` there is the schema's "not provided"
        sentinel rather than a value - and arriving at the row would be a 500 naming
        a database constraint (#637)."""
        data = DeploymentSettingsUpdate.model_validate({"app_name": "Acme", "signup_mode": None})

        await DeploymentSettingsService(mock_db_session).update(actor_user_id=uuid4(), data=data)

        assert repo.upsert.await_args.kwargs["update_data"] == {"app_name": "Acme"}

    async def test_a_request_naming_nothing_is_refused(self, mock_db_session, repo):
        with pytest.raises(BadRequestError):
            await DeploymentSettingsService(mock_db_session).update(
                actor_user_id=uuid4(), data=DeploymentSettingsUpdate()
            )
        repo.upsert.assert_not_called()

    async def test_the_audit_entry_names_the_fields_and_not_their_values(
        self, mock_db_session, repo, monkeypatch
    ):
        """An announcement and a domain list are both operator text, and an audit row
        outlives the request body it came from."""
        recorded = AsyncMock()
        monkeypatch.setattr(module, "record_audit", recorded)

        await DeploymentSettingsService(mock_db_session).update(
            actor_user_id=uuid4(),
            data=DeploymentSettingsUpdate(announcement="ops@acme.com, window at 22:00"),
        )

        details = recorded.await_args.kwargs["details"]
        assert details == {"fields": ["announcement"]}
        assert "ops@acme.com" not in str(details)

    async def test_saving_publishes_the_maintenance_verdict_immediately(
        self, mock_db_session, repo, monkeypatch
    ):
        """The middleware reads a cache with a TTL, so without this a saved change
        takes up to half a minute to close or reopen the deployment - which an
        administrator experiences as a switch that did nothing."""
        published = AsyncMock()
        monkeypatch.setattr(module, "publish_maintenance", published)
        repo.upsert.return_value = a_row(maintenance_mode=True, maintenance_message="Back at 22:00")

        await DeploymentSettingsService(mock_db_session).update(
            actor_user_id=uuid4(), data=DeploymentSettingsUpdate(maintenance_mode=True)
        )

        assert published.await_args.kwargs == {"on": True, "message": "Back at 22:00"}

    async def test_it_publishes_from_the_written_row_not_the_request(
        self, mock_db_session, repo, monkeypatch
    ):
        """A PATCH that touched only the name must not publish a stale verdict over a
        window somebody else opened."""
        published = AsyncMock()
        monkeypatch.setattr(module, "publish_maintenance", published)
        repo.upsert.return_value = a_row(maintenance_mode=True, maintenance_message="Still closed")

        await DeploymentSettingsService(mock_db_session).update(
            actor_user_id=uuid4(), data=DeploymentSettingsUpdate(app_name="Acme AI")
        )

        assert published.await_args.kwargs == {"on": True, "message": "Still closed"}


class TestUploadingAnImage:
    async def test_something_that_is_not_an_image_is_refused(self, mock_db_session, repo, storage):
        with pytest.raises(BadRequestError):
            await DeploymentSettingsService(mock_db_session).set_image(
                actor_user_id=uuid4(),
                kind="logo",
                file_data=b"<script>alert(1)</script>",
                content_type="text/html",
            )
        storage.save.assert_not_called()

    async def test_a_missing_content_type_is_refused(self, mock_db_session, repo, storage):
        with pytest.raises(BadRequestError):
            await DeploymentSettingsService(mock_db_session).set_image(
                actor_user_id=uuid4(), kind="logo", file_data=b"x", content_type=None
            )
        storage.save.assert_not_called()

    async def test_an_oversized_image_is_refused(self, mock_db_session, repo, storage):
        with pytest.raises(BadRequestError):
            await DeploymentSettingsService(mock_db_session).set_image(
                actor_user_id=uuid4(),
                kind="favicon",
                file_data=b"0" * (2 * 1024 * 1024 + 1),
                content_type="image/png",
            )
        storage.save.assert_not_called()

    async def test_the_stored_name_is_minted_from_the_validated_type(
        self, mock_db_session, repo, storage
    ):
        """`save` keeps whatever extension it is handed, and this file is served from
        the origin the app's own pages run on. The caller's filename is not taken at
        all, so there is nothing for them to choose."""
        await DeploymentSettingsService(mock_db_session).set_image(
            actor_user_id=uuid4(), kind="logo", file_data=b"png", content_type="image/png"
        )

        assert storage.save.await_args.args[1] == "logo.png"

    async def test_each_accepted_type_gets_its_own_extension(self, mock_db_session, repo, storage):
        for content_type, suffix in (
            ("image/jpeg", ".jpg"),
            ("image/png", ".png"),
            ("image/webp", ".webp"),
            ("image/gif", ".gif"),
        ):
            await DeploymentSettingsService(mock_db_session).set_image(
                actor_user_id=uuid4(),
                kind="favicon",
                file_data=b"x",
                content_type=content_type,
            )
            assert storage.save.await_args.args[1] == f"favicon{suffix}"

    async def test_the_path_is_written_to_the_column_the_kind_names(
        self, mock_db_session, repo, storage
    ):
        await DeploymentSettingsService(mock_db_session).set_image(
            actor_user_id=uuid4(), kind="favicon", file_data=b"x", content_type="image/webp"
        )

        assert repo.upsert.await_args.kwargs["update_data"] == {
            "favicon_path": "deployment/abc_favicon.webp"
        }

    async def test_replacing_an_image_deletes_the_one_it_replaced(
        self, mock_db_session, repo, storage
    ):
        repo.get.return_value = a_row(logo_path="deployment/old.png")

        await DeploymentSettingsService(mock_db_session).set_image(
            actor_user_id=uuid4(), kind="logo", file_data=b"x", content_type="image/png"
        )

        storage.delete.assert_awaited_once_with("deployment/old.png")

    async def test_a_delete_that_fails_does_not_fail_the_upload(
        self, mock_db_session, repo, storage
    ):
        """The old file is unreachable the moment the row stops pointing at it, so a
        storage backend that cannot remove it is a leaked file rather than a reason
        to refuse the operator's new logo."""
        repo.get.return_value = a_row(logo_path="deployment/old.png")
        storage.delete.side_effect = OSError("gone")

        read = await DeploymentSettingsService(mock_db_session).set_image(
            actor_user_id=uuid4(), kind="logo", file_data=b"x", content_type="image/png"
        )

        assert read is not None


class TestClearingAnImage:
    async def test_clearing_nothing_is_the_end_state_already(self, mock_db_session, repo, storage):
        """Idempotent: reporting a missing file the caller does not care about would
        make "reset to the built-in mark" fail on a deployment that already is."""
        repo.get.return_value = a_row(logo_path=None)

        await DeploymentSettingsService(mock_db_session).clear_image(
            actor_user_id=uuid4(), kind="logo"
        )

        repo.upsert.assert_not_called()
        storage.delete.assert_not_called()

    async def test_it_is_the_end_state_before_any_row_exists_too(
        self, mock_db_session, repo, storage
    ):
        await DeploymentSettingsService(mock_db_session).clear_image(
            actor_user_id=uuid4(), kind="favicon"
        )

        repo.upsert.assert_not_called()

    async def test_it_nulls_the_column_and_removes_the_file(self, mock_db_session, repo, storage):
        repo.get.return_value = a_row(favicon_path="deployment/f.png")

        await DeploymentSettingsService(mock_db_session).clear_image(
            actor_user_id=uuid4(), kind="favicon"
        )

        assert repo.upsert.await_args.kwargs["update_data"] == {"favicon_path": None}
        storage.delete.assert_awaited_once_with("deployment/f.png")

    async def test_a_delete_that_fails_still_clears_the_column(
        self, mock_db_session, repo, storage
    ):
        repo.get.return_value = a_row(logo_path="deployment/l.png")
        storage.delete.side_effect = OSError("gone")

        await DeploymentSettingsService(mock_db_session).clear_image(
            actor_user_id=uuid4(), kind="logo"
        )

        assert repo.upsert.await_args.kwargs["update_data"] == {"logo_path": None}


class TestWhereTheBytesAre:
    async def test_no_row_means_no_path(self, mock_db_session, repo):
        assert await DeploymentSettingsService(mock_db_session).image_path("logo") is None

    async def test_it_answers_the_stored_key_for_each_kind(self, mock_db_session, repo):
        repo.get.return_value = a_row(logo_path="deployment/l.png", favicon_path="deployment/f.gif")
        service = DeploymentSettingsService(mock_db_session)

        assert await service.image_path("logo") == "deployment/l.png"
        assert await service.image_path("favicon") == "deployment/f.gif"


class TestTheNameTheBackendUsesItself:
    async def test_it_falls_back_to_the_built_in_when_nothing_is_set(self, mock_db_session, repo):
        name = await DeploymentSettingsService(mock_db_session).effective_app_name()

        assert name == settings.PROJECT_NAME

    async def test_a_row_with_no_override_falls_back_too(self, mock_db_session, repo):
        repo.get.return_value = a_row(app_name=None)

        assert (
            await DeploymentSettingsService(mock_db_session).effective_app_name()
            == settings.PROJECT_NAME
        )

    async def test_it_answers_the_name_the_administrator_set(self, mock_db_session, repo):
        """Which is why it exists: an email greeting somebody in the name of a product
        the console stopped showing is the rename half-applied. Three hardcoded
        `"agenticos"` literals in the email service were exactly that."""
        repo.get.return_value = a_row(app_name="Acme AI")

        assert await DeploymentSettingsService(mock_db_session).effective_app_name() == "Acme AI"


class TestTheTwoBuiltInsAgree:
    def test_the_frontends_app_name_is_this_backends_project_name(self):
        """One default per renderer is the design - the API answers overrides, and each
        side resolves a null against its own constant. Two constants can drift, so
        this is what stops them, the way `TestFrontendToolCatalog` stops the tool
        catalog drifting.

        Compared against the *class* default rather than `settings.PROJECT_NAME`: the
        latter is env-overridable, and a deployment that renamed itself through the
        environment would make this pass or fail on its own configuration.
        """
        constants = (
            Path(__file__).resolve().parents[2] / "frontend/src/lib/constants.ts"
        ).read_text()
        match = re.search(r'export const APP_NAME = "([^"]+)"', constants)

        assert match is not None, "APP_NAME is no longer a literal in frontend constants.ts"
        assert match.group(1) == Settings.model_fields["PROJECT_NAME"].default


class TestWhatTheSchemaRefuses:
    def test_an_emptied_input_asks_for_the_built_in_back(self):
        """`str_strip_whitespace` has already trimmed it, so what arrives is `""` -
        and storing that renders a sign-in page with no name on it."""
        data = DeploymentSettingsUpdate.model_validate(
            {"app_name": "  ", "tagline": "", "description": " ", "footer_text": ""}
        )

        assert data.app_name is None
        assert data.tagline is None
        assert data.description is None
        assert data.footer_text is None

    def test_a_legal_link_must_be_absolute(self):
        """`www.acme.com/terms` parses cleanly, has no scheme, and renders as a
        relative link back into this app - a "terms" link that 404s on our own
        domain rather than reaching theirs."""
        with pytest.raises(ValidationError):
            DeploymentSettingsUpdate(terms_url="www.acme.com/terms")

    def test_a_scheme_that_is_not_http_is_refused(self):
        with pytest.raises(ValidationError):
            DeploymentSettingsUpdate(privacy_url="javascript:alert(1)")

    def test_an_absolute_link_is_kept_as_written(self):
        data = DeploymentSettingsUpdate(terms_url="https://acme.com/legal/terms")

        assert data.terms_url == "https://acme.com/legal/terms"

    def test_an_emptied_link_clears_it(self):
        assert DeploymentSettingsUpdate.model_validate({"terms_url": ""}).terms_url is None
        assert DeploymentSettingsUpdate.model_validate({"privacy_url": None}).privacy_url is None

    def test_domains_are_lower_cased_and_deduplicated_in_order(self):
        """The signup policy matches an address against this list on every
        registration, so a list holding `Acme.COM` would refuse `me@acme.com` for a
        rule the operator believes they wrote."""
        data = DeploymentSettingsUpdate(
            allowed_email_domains=["Acme.COM", "acme.com", " partner.io "]
        )

        assert data.allowed_email_domains == ["acme.com", "partner.io"]

    def test_a_domain_written_as_an_address_is_normalised(self):
        data = DeploymentSettingsUpdate(allowed_email_domains=["@acme.com"])

        assert data.allowed_email_domains == ["acme.com"]

    def test_a_blank_entry_is_dropped_rather_than_refusing_the_list(self):
        data = DeploymentSettingsUpdate(allowed_email_domains=["acme.com", "  "])

        assert data.allowed_email_domains == ["acme.com"]

    def test_something_that_is_not_a_domain_is_refused(self):
        """Deliberately not an email regex: the column holds `acme.com`, and
        `me@acme.com` is an operator slip worth a 422 rather than a rule that
        silently matches nothing."""
        for bad in ("acme", "me@acme.com", "acme..com", "-acme.com", "http://acme.com"):
            with pytest.raises(ValidationError):
                DeploymentSettingsUpdate(allowed_email_domains=[bad])

    def test_the_list_has_a_ceiling(self):
        with pytest.raises(ValidationError):
            DeploymentSettingsUpdate(allowed_email_domains=[f"d{n}.com" for n in range(33)])

    def test_an_absent_domain_list_is_not_an_empty_one(self):
        """`None` is "not provided" and `[]` is "allow every domain, deliberately".
        Collapsing them would make every PATCH clear the list."""
        assert DeploymentSettingsUpdate().allowed_email_domains is None
        assert (
            DeploymentSettingsUpdate.model_validate(
                {"allowed_email_domains": None}
            ).allowed_email_domains
            is None
        )
        assert DeploymentSettingsUpdate(allowed_email_domains=[]).allowed_email_domains == []


class TestTheSingletonRepository:
    async def test_the_write_conflicts_on_the_constraint_that_makes_it_a_singleton(
        self, mock_db_session, monkeypatch
    ):
        """A read-then-insert races itself the moment two administrators save from two
        tabs, and the loser gets an `IntegrityError` no handler translates."""
        mock_db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one=MagicMock(return_value=a_row()))
        )

        await deployment_settings_repo.upsert(mock_db_session, update_data={"app_name": "Acme"})

        statement = str(mock_db_session.execute.await_args.args[0])
        assert "ON CONFLICT" in statement
        assert "DO UPDATE" in statement

    async def test_reading_answers_none_when_nothing_is_configured(self, mock_db_session):
        mock_db_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        assert await deployment_settings_repo.get(mock_db_session) is None

    def test_the_model_says_what_it_holds(self):
        assert "Acme AI" in repr(a_row(app_name="Acme AI"))
