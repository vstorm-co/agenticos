"""How a collection says its documents should be read, and what that resolves to.

The value of this module is almost entirely in what it refuses and what it
records. A merge that loses an override, a configuration that names a model
nobody can run, and a collection quietly indexed with a second embedding model
all look like success at the moment they happen and like corrupt search results
weeks later.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.core.secret_kinds import ApiKeySecret, SecretKind, seal_secret
from app.core.vault import VaultScope
from app.db.models.credential import ModelProfile
from app.db.models.organization_secret import OrganizationSecret
from app.services.ingestion_config import (
    ChunkingStrategy,
    ImageDescription,
    ImageDescriptionOverride,
    IngestionConfig,
    IngestionConfigService,
    IngestionOverride,
    LiteParseOutputFormat,
    LlamaParseTier,
    PdfParserName,
    chosen_embedding,
    deployment_defaults,
    parse_override,
    rag_settings_for,
)
from app.services.knowledge_base import KnowledgeBaseService
from app.services.rag.docling import DoclingTarget
from app.services.rag.image_describer import PydanticAIImageDescriber

pytestmark = pytest.mark.anyio

ORG = uuid.uuid4()


def _db() -> MagicMock:
    db = MagicMock()
    db.flush = AsyncMock()
    return db


def _profile_and_credential() -> tuple[ModelProfile, OrganizationSecret]:
    """A profile with a real sealed key behind it, so `build()` can be reached."""
    sealed = seal_secret(
        ApiKeySecret(api_key="sk-test-abcd1234"), scope=VaultScope.organization(ORG)
    )
    secret = OrganizationSecret(
        id=uuid.uuid4(),
        organization_id=ORG,
        name="Key",
        purpose="openai",
        visibility="org",
        kind=SecretKind.API_KEY.value,
        sealed_secret=sealed.ciphertext,
        hint=sealed.hint,
        key_version=sealed.key_version,
    )
    profile = ModelProfile(
        id=uuid.uuid4(),
        organization_id=ORG,
        label="Vision",
        provider="openai",
        model="gpt-4.1",
        secret_id=secret.id,
        params={},
        fallback_profile_ids=[],
    )
    return profile, secret


def _resolving_to(profile: ModelProfile, secret: OrganizationSecret):
    """Patch the two repository calls resolution makes, and nothing else."""
    return (
        patch(
            "app.services.model_profile.credential_repo.get_profile",
            new=AsyncMock(return_value=profile),
        ),
        patch(
            "app.services.model_profile.organization_secret_repo.get",
            new=AsyncMock(return_value=secret),
        ),
    )


class TestTheModelParametersImageDescriptionAsksFor:
    """A parameter nobody chose must not be sent, not sent as a default."""

    def test_an_unconfigured_describer_sends_no_parameters_at_all(self) -> None:
        """Reasoning models reject `temperature` outright, including `0`."""
        assert ImageDescription().model_settings() == {}

    def test_a_chosen_temperature_and_effort_both_travel(self) -> None:
        settings = ImageDescription(temperature=0.2, thinking="high").model_settings()

        assert settings == {"temperature": 0.2, "thinking": "high"}


class TestAConfigurationThatWouldNotTerminate:
    def test_an_overlap_as_large_as_the_chunk_is_refused(self) -> None:
        """Every chunk would start where the last one did, forever."""
        with pytest.raises(ValueError, match="chunk_overlap"):
            IngestionConfig(chunk_size=512, chunk_overlap=512)

    def test_an_overlap_smaller_than_the_chunk_is_fine(self) -> None:
        assert IngestionConfig(chunk_size=512, chunk_overlap=511).chunk_overlap == 511

    def test_an_override_is_checked_against_the_merged_pair_not_its_own_value(self) -> None:
        """Two individually legal numbers, one configuration that does not terminate."""
        base = IngestionConfig(chunk_size=4096, chunk_overlap=2048)

        with pytest.raises(BadRequestError, match="ingestion"):
            IngestionOverride(chunk_size=1024).applied_to(base)

    def test_the_merged_pair_is_refused_as_a_form_error_and_names_both_numbers(self) -> None:
        """It was a raw `ValidationError`, which reaches no handler and is a 500.

        The rule's own docstring says the form is what refuses this pair, and
        the form was being told the server had broken (#874).
        """
        base = IngestionConfig(chunk_size=512)

        with pytest.raises(BadRequestError) as refusal:
            IngestionOverride(chunk_overlap=4096).applied_to(base)

        problems = refusal.value.details["fields"]
        assert "chunk_overlap" in problems[0]["message"]
        assert "chunk_size" in problems[0]["message"]

    def test_the_pair_rule_is_attributed_to_the_field_the_override_arrived_in(self) -> None:
        """A `model_validator` names no field, and a form cannot mark nothing.

        `details["fields"]` is the only shape the frontend marks an input from,
        so a refusal that answered `details["errors"]` showed its sentence in a
        toast and highlighted nothing (#882).
        """
        base = IngestionConfig(chunk_size=512)

        with pytest.raises(BadRequestError) as refusal:
            IngestionOverride(chunk_overlap=4096).applied_to(base)

        assert [problem["field"] for problem in refusal.value.details["fields"]] == [
            "ingestion_config"
        ]

    def test_the_refusal_carries_no_copy_of_what_was_submitted(self) -> None:
        """`details` names the fields that are wrong, never the document sent."""
        base = IngestionConfig(chunk_size=512)

        with pytest.raises(BadRequestError) as refusal:
            IngestionOverride(chunk_overlap=4096).applied_to(base)

        assert all(
            set(problem) == {"field", "message"} for problem in refusal.value.details["fields"]
        )


class TestWhatAnOverrideChanges:
    def test_an_empty_override_says_so(self) -> None:
        """A document records the override it ran with; an empty one is not a departure."""
        assert IngestionOverride().is_empty
        assert not IngestionOverride(pdf_parser=PdfParserName.LITEPARSE).is_empty

    def test_it_changes_what_it_names_and_nothing_else(self) -> None:
        base = IngestionConfig(
            pdf_parser=PdfParserName.PYMUPDF,
            chunk_size=512,
            chunking_strategy=ChunkingStrategy.RECURSIVE,
        )

        merged = IngestionOverride(pdf_parser=PdfParserName.LLAMAPARSE).applied_to(base)

        assert merged.pdf_parser is PdfParserName.LLAMAPARSE
        assert merged.chunk_size == 512
        assert merged.chunking_strategy is ChunkingStrategy.RECURSIVE
        assert base.pdf_parser is PdfParserName.PYMUPDF

    def test_the_image_group_merges_field_by_field(self) -> None:
        """Overriding the prompt must not silently drop the chosen profile."""
        profile_id = uuid.uuid4()
        base = IngestionConfig(
            describe_images=True,
            image_description=ImageDescription(model_profile_id=profile_id, temperature=0.1),
        )

        merged = IngestionOverride(
            image_description=ImageDescriptionOverride(prompt="just the numbers")
        ).applied_to(base)

        assert merged.image_description.prompt == "just the numbers"
        assert merged.image_description.model_profile_id == profile_id
        assert merged.image_description.temperature == 0.1

    def test_an_explicit_null_means_the_organizations_default_not_inheritance(self) -> None:
        """`null` is a value here and omission is not, or three states become two."""
        base = IngestionConfig(
            image_description=ImageDescription(model_profile_id=uuid.uuid4()),
        )

        merged = IngestionOverride(
            image_description=ImageDescriptionOverride(model_profile_id=None)
        ).applied_to(base)

        assert merged.image_description.model_profile_id is None


class TestReadingAnOverrideOffTheForm:
    """An upload is multipart, so its settings arrive as one JSON form field."""

    def test_no_field_is_no_override(self) -> None:
        assert parse_override(None) is None

    def test_a_blank_field_is_no_override(self) -> None:
        """A browser form that sends an empty string is not asking for anything."""
        assert parse_override("   ") is None

    def test_a_field_is_parsed_into_an_override(self) -> None:
        override = parse_override('{"pdf_parser": "liteparse", "chunk_size": 1024}')

        assert override is not None
        assert override.pdf_parser is PdfParserName.LITEPARSE
        assert override.chunk_size == 1024

    def test_a_malformed_field_is_refused_rather_than_ignored(self) -> None:
        """Ignoring it would parse the file the collection's way while the caller believed otherwise."""
        with pytest.raises(BadRequestError) as refusal:
            parse_override('{"pdf_parser": "tesseract"}')

        assert "ingestion" in refusal.value.message

    def test_an_unknown_key_is_refused_rather_than_dropped(self) -> None:
        """A misspelled setting must not look like it was applied."""
        with pytest.raises(BadRequestError):
            parse_override('{"chunk_sizes": 1024}')

    def test_the_setting_that_broke_a_rule_is_named_as_a_field_the_form_marks(self) -> None:
        """`details["fields"]` is what `fieldProblems` reads; `errors` was read
        nowhere, so this refusal marked no input at all (#882)."""
        with pytest.raises(BadRequestError) as refusal:
            parse_override('{"chunk_size": 1}')

        assert refusal.value.details["fields"] == [
            {
                "field": "ingestion_config.chunk_size",
                "message": "Input should be greater than or equal to 64",
            }
        ]

    def test_a_field_that_is_not_json_at_all_is_attributed_to_the_form_field(self) -> None:
        """Pydantic names no field for a document it could not read, so the
        refusal falls back to the multipart field the JSON arrived in."""
        with pytest.raises(BadRequestError) as refusal:
            parse_override("{not json")

        assert [problem["field"] for problem in refusal.value.details["fields"]] == [
            "ingestion_config"
        ]


class TestWhatTheDeploymentSeedsANewCollectionWith:
    def test_the_environment_does_not_decide_how_a_collection_parses(self) -> None:
        """How documents are read is per collection, and the row is the only source.

        An installation-wide `PDF_PARSER`/`RAG_CHUNK_SIZE` - inherited from the
        template this project was generated from - made the same form produce
        different collections on two deployments, with nothing in the product
        showing which. The variables are gone, and so is the module's reach into
        `settings` at all: the parser credentials and addresses that followed
        them are rows the collection names.
        """
        import app.services.ingestion_config as module

        assert not hasattr(module, "settings")
        assert deployment_defaults() == IngestionConfig()

    def test_liteparse_defaults_to_markdown_with_ocr_decided_per_document(self) -> None:
        """The two defaults that decide what a LiteParse collection costs and returns.

        Markdown is what the markdown chunking strategy splits on, and `auto_ocr`
        is the difference between OCRing every page and OCRing the scans -
        verified against a real parse, not assumed.
        """
        seeded = deployment_defaults()

        assert seeded.liteparse_output_format is LiteParseOutputFormat.MARKDOWN
        assert seeded.auto_ocr is True
        assert seeded.max_pages == 1000

    def test_image_description_starts_off_whatever_the_environment_said(self) -> None:
        """It now costs a model profile the organization pays for; that is a choice."""
        assert deployment_defaults().describe_images is False

    def test_no_choice_of_model_is_refused_on_the_field(self) -> None:
        """There is no deployment default any more: the form offers the models
        the chosen provider serves and one of them has to be chosen."""
        with pytest.raises(BadRequestError) as refusal:
            chosen_embedding(None)

        assert refusal.value.details["fields"][0]["field"] == "embedding_model"


class TestTurningAConfigurationIntoPipelineSettings:
    def test_the_collections_choices_reach_the_parser(self) -> None:
        settings = rag_settings_for(
            IngestionConfig(
                pdf_parser=PdfParserName.LITEPARSE,
                ocr=True,
                llamaparse_tier=LlamaParseTier.FAST,
                ocr_language="deu",
                parse_timeout_seconds=30.0,
                auto_ocr=False,
                liteparse_output_format=LiteParseOutputFormat.TEXT,
                liteparse_dpi=300.0,
                max_pages=25,
                chunk_size=256,
                chunk_overlap=16,
                chunking_strategy=ChunkingStrategy.FIXED,
            )
        )

        assert settings.pdf_parser.method == "liteparse"
        assert settings.pdf_parser.tier == "fast"
        assert settings.pdf_parser.liteparse_ocr_language == "deu"
        assert settings.pdf_parser.liteparse_timeout_seconds == 30.0
        assert settings.pdf_parser.liteparse_auto_ocr is False
        assert settings.pdf_parser.liteparse_output_format == "text"
        assert settings.pdf_parser.liteparse_dpi == 300.0
        assert settings.pdf_parser.liteparse_max_pages == 25
        assert settings.enable_ocr is True
        assert settings.chunk_size == 256
        assert settings.chunk_overlap == 16
        assert settings.chunking_strategy == "fixed"

    def test_the_resolved_key_and_ocr_address_reach_the_parser(self) -> None:
        """Both arrive resolved: the configuration holds ids, and neither a
        credential nor an address an operator may edit belongs in a stored row."""
        settings = rag_settings_for(
            IngestionConfig(), llamaparse_api_key="llx-org", ocr_server_url="http://ocr:8000"
        )

        assert settings.pdf_parser.api_key == "llx-org"
        assert settings.pdf_parser.liteparse_ocr_server_url == "http://ocr:8000"

    def test_nothing_resolved_means_no_key_and_the_workers_own_ocr(self) -> None:
        settings = rag_settings_for(IngestionConfig())

        assert settings.pdf_parser.api_key == ""
        assert settings.pdf_parser.liteparse_ocr_server_url is None


class TestResolvingTheModelThatReadsImages:
    async def test_a_collection_that_does_not_describe_images_resolves_nothing(self) -> None:
        """Not even a query: most collections have no pictures worth paying for."""
        service = IngestionConfigService(_db())

        assert await service.resolved_image_model(ORG, IngestionConfig()) is None

    async def test_the_recorded_model_is_the_one_the_profile_points_at(self) -> None:
        """Recorded resolved, because a profile can be edited after the fact."""
        profile, credential = _profile_and_credential()
        config = IngestionConfig(
            describe_images=True,
            image_description=ImageDescription(model_profile_id=profile.id),
        )

        with _resolving_to(profile, credential)[0], _resolving_to(profile, credential)[1]:
            resolved = await IngestionConfigService(_db()).resolved_image_model(ORG, config)

        assert resolved == "openai:gpt-4.1"

    @pytest.mark.parametrize("build", [False, True], ids=["configuration", "worker"])
    async def test_a_non_chat_profile_is_refused_before_configuration_or_build(self, build: bool):
        profile, credential = _profile_and_credential()
        profile.model = "gpt-4o-mini-tts"
        config = IngestionConfig(
            describe_images=True,
            image_description=ImageDescription(model_profile_id=profile.id),
        )
        patches = _resolving_to(profile, credential)
        with patches[0], patches[1], pytest.raises(BadRequestError, match="not a chat model"):
            service = IngestionConfigService(_db())
            if build:
                await service.build_describer(ORG, config)
            else:
                await service.resolved_image_model(ORG, config)

    async def test_a_custom_endpoint_is_not_classified_by_its_model_name(self) -> None:
        profile, credential = _profile_and_credential()
        profile.model = "whisper-1"
        profile.base_url = "http://local/v1"
        config = IngestionConfig(
            describe_images=True, image_description=ImageDescription(model_profile_id=profile.id)
        )
        patches = _resolving_to(profile, credential)
        with patches[0], patches[1]:
            assert (
                await IngestionConfigService(_db()).resolved_image_model(ORG, config)
                == "openai:whisper-1"
            )

    async def test_a_configuration_naming_no_model_is_told_so(self) -> None:
        """The refusal belongs on the form that turned this on, not on an upload.

        There is no organization-wide default to fall back on any more, so image
        description names its model or is refused - the same rule an agent
        follows, and for the same reason: a model nobody chose is one somebody
        else's change can swap underneath the collection.
        """
        with pytest.raises(NotFoundError):
            await IngestionConfigService(_db()).resolved_image_model(
                ORG, IngestionConfig(describe_images=True)
            )


class TestTheEmbeddingModelACollectionWasBuiltWith:
    def test_indexing_continues_for_a_model_this_build_knows(self) -> None:
        IngestionConfigService(_db()).check_embedding_model(
            collection="handbook",
            built_with="text-embedding-3-large",
            provider="openai",
            dim=3072,
        )

    def test_a_named_model_is_looked_up_and_carries_its_width(self) -> None:
        """The width travels with the choice: the vector column is created at
        this number, and a wrong guess poisons the collection from birth."""
        model, dim = chosen_embedding("text-embedding-3-small")

        assert (model, dim) == ("text-embedding-3-small", 1536)

    def test_a_model_with_no_known_width_is_refused_at_the_form(self) -> None:
        with pytest.raises(BadRequestError) as refusal:
            chosen_embedding("made-up-model")

        assert "made-up-model" in refusal.value.message

    def test_a_model_no_provider_offers_any_more_still_indexes(self) -> None:
        """The store embeds each collection with its own recorded model, so a
        catalog that moved on must not strand existing collections."""
        IngestionConfigService(_db()).check_embedding_model(
            collection="handbook",
            built_with="text-embedding-ada-002",
            provider="openai",
            dim=1536,
        )

    def test_an_upload_into_a_custom_collection_is_not_refused_for_an_unlisted_model(self) -> None:
        IngestionConfigService(_db()).check_embedding_model(
            collection="c", built_with="corp-embed-v2", provider="openai_compatible", dim=1024
        )

    def test_an_upload_into_a_catalog_collection_with_an_unknown_model_is_still_refused(
        self,
    ) -> None:
        with pytest.raises(BadRequestError):
            IngestionConfigService(_db()).check_embedding_model(
                collection="c", built_with="corp-embed-v2", provider="openai", dim=1024
            )

    def test_chosen_embedding_accepts_a_measured_width_for_any_model(self) -> None:
        assert chosen_embedding("corp-embed", measured_dim=1024) == ("corp-embed", 1024)
        assert chosen_embedding("corp-embed", measured_dim=4000) == ("corp-embed", 4000)

    @pytest.mark.parametrize("width", [0, 4001])
    def test_chosen_embedding_refuses_a_measured_width_outside_1_to_4000(self, width) -> None:
        with pytest.raises(BadRequestError) as refusal:
            chosen_embedding("corp-embed", measured_dim=width)

        assert refusal.value.details["fields"][0]["field"] == "embedding_model"

    def test_a_model_this_build_cannot_embed_with_is_refused_and_named(self) -> None:
        """The upload would otherwise be accepted and die in a worker with
        nothing on screen - the exact failure this module exists to prevent."""
        with pytest.raises(BadRequestError) as refusal:
            IngestionConfigService(_db()).check_embedding_model(
                collection="handbook",
                built_with="withdrawn-model",
                provider="openai",
                dim=1536,
            )

        assert "withdrawn-model" in refusal.value.message
        assert refusal.value.details == {
            "collection": "handbook",
            "built_with": "withdrawn-model",
        }


class TestLlamaParseCredential:
    """Whose key a LlamaParse parse is billed to - the organization's, or nobody's.

    There is no deployment key. A collection on LlamaParse names a vault key or
    is refused at the form; a stored one whose key has since gone is refused at
    parse time with a sentence that reaches the document row whole.
    """

    @staticmethod
    def _sealed_llamaparse_row(plaintext: str):
        sealed = seal_secret(ApiKeySecret(api_key=plaintext), scope=VaultScope.organization(ORG))
        return MagicMock(
            sealed_secret=sealed.ciphertext,
            kind=SecretKind.API_KEY.value,
            key_version=sealed.key_version,
            purpose="llamaparse",
        )

    @staticmethod
    def _llamaparse(secret_id: uuid.UUID | None = None) -> IngestionConfig:
        return IngestionConfig(
            pdf_parser=PdfParserName.LLAMAPARSE, llamaparse_secret_id=secret_id or uuid.uuid4()
        )

    async def test_the_organizations_key_is_unsealed_into_the_parser(self) -> None:
        with patch(
            "app.services.ingestion_config.organization_secret_repo.get",
            new=AsyncMock(return_value=self._sealed_llamaparse_row("llx-org-own")),
        ):
            processor = await IngestionConfigService(_db()).build_processor(ORG, self._llamaparse())

        assert processor.settings.pdf_parser.api_key == "llx-org-own"

    async def test_a_deleted_key_refuses_the_parse_and_says_which_key(self) -> None:
        """Nothing to degrade to: a parse that cannot be billed is a parse that
        cannot happen, and the refusal - ours - reaches the document row whole."""
        with (
            patch(
                "app.services.ingestion_config.organization_secret_repo.get",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(BadRequestError, match="no longer in the organization's vault"),
        ):
            await IngestionConfigService(_db()).build_processor(ORG, self._llamaparse())

    async def test_an_unopenable_or_wrong_kind_key_refuses_too(self) -> None:
        broken = MagicMock(
            sealed_secret="not-a-ciphertext", kind=SecretKind.API_KEY.value, key_version=1
        )
        service = IngestionConfigService(_db())

        with (
            patch(
                "app.services.ingestion_config.organization_secret_repo.get",
                new=AsyncMock(return_value=broken),
            ),
            pytest.raises(BadRequestError, match="could not be unsealed"),
        ):
            await service._llamaparse_key(ORG, self._llamaparse())

        with (
            patch(
                "app.services.ingestion_config.organization_secret_repo.get",
                new=AsyncMock(return_value=self._sealed_llamaparse_row("llx-x-12345")),
            ),
            patch("app.services.ingestion_config.unseal_secret", return_value=MagicMock(spec=[])),
            pytest.raises(BadRequestError, match="does not hold an API key"),
        ):
            await service._llamaparse_key(ORG, self._llamaparse())

    async def test_a_collection_on_another_parser_asks_the_vault_nothing(self) -> None:
        service = IngestionConfigService(_db())

        with patch(
            "app.services.ingestion_config.organization_secret_repo.get", new=AsyncMock()
        ) as vault:
            assert await service._llamaparse_key(ORG, IngestionConfig()) is None
            assert (
                await service._llamaparse_key(
                    ORG, IngestionConfig(llamaparse_secret_id=uuid.uuid4())
                )
                is None
            )

        vault.assert_not_called()

    async def test_a_stored_llamaparse_collection_with_no_key_refuses_the_parse(self) -> None:
        with pytest.raises(BadRequestError, match="names no vault key"):
            await IngestionConfigService(_db())._llamaparse_key(
                ORG, IngestionConfig(pdf_parser=PdfParserName.LLAMAPARSE)
            )
        with pytest.raises(BadRequestError, match="names no vault key"):
            await IngestionConfigService(_db())._llamaparse_key(None, self._llamaparse())

    async def test_llamaparse_with_no_key_is_refused_at_the_form(self) -> None:
        """The same refusal, where the person who can fix it is looking."""
        with pytest.raises(BadRequestError) as refusal:
            await IngestionConfigService(_db()).check_llamaparse_secret(
                ORG, IngestionConfig(pdf_parser=PdfParserName.LLAMAPARSE)
            )

        assert refusal.value.details["fields"][0]["field"] == "llamaparse_secret_id"

    async def test_a_key_the_organization_does_not_hold_is_refused_at_the_form(self) -> None:
        with (
            patch(
                "app.services.ingestion_config.organization_secret_repo.get",
                new=AsyncMock(return_value=None),
            ),
            pytest.raises(BadRequestError, match="vault"),
        ):
            await IngestionConfigService(_db()).check_llamaparse_secret(ORG, self._llamaparse())

    async def test_a_key_for_something_else_is_refused_by_purpose(self) -> None:
        with (
            patch(
                "app.services.ingestion_config.organization_secret_repo.get",
                new=AsyncMock(return_value=MagicMock(purpose="tavily")),
            ),
            pytest.raises(BadRequestError, match="not LlamaParse"),
        ):
            await IngestionConfigService(_db()).check_llamaparse_secret(ORG, self._llamaparse())

    async def test_an_app_scoped_collection_cannot_parse_with_llamaparse(self) -> None:
        """No organization, no vault, no key - so the parser is what is wrong."""
        with pytest.raises(BadRequestError) as refusal:
            await IngestionConfigService(_db()).check_llamaparse_secret(None, self._llamaparse())

        assert refusal.value.details["fields"][0]["field"] == "pdf_parser"

    async def test_another_parser_passes_the_form_check_whatever_the_key_field_says(self) -> None:
        await IngestionConfigService(_db()).check_llamaparse_secret(ORG, IngestionConfig())
        await IngestionConfigService(_db()).check_llamaparse_secret(
            None, IngestionConfig(llamaparse_secret_id=uuid.uuid4())
        )

    async def test_a_valid_key_passes_the_form_check(self) -> None:
        with patch(
            "app.services.ingestion_config.organization_secret_repo.get",
            new=AsyncMock(return_value=MagicMock(purpose="llamaparse")),
        ):
            await IngestionConfigService(_db()).check_llamaparse_secret(ORG, self._llamaparse())


def _ocr_service(**overrides: object) -> MagicMock:
    row = MagicMock(
        name="Scanner", kind="ocr", provider="liteparse", base_url="http://ocr:8000", is_active=True
    )
    row.name = "Scanner"
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


class TestTheOcrServer:
    """Where LiteParse sends pages: a service connection the collection names, or the
    worker's own Tesseract. Checked at the form and resolved at parse time, both
    within what the collection may name."""

    async def test_no_choice_is_the_workers_own_tesseract(self) -> None:
        service = IngestionConfigService(_db())
        with patch(
            "app.services.ingestion_config.service_connection_repo.get_visible", new=AsyncMock()
        ) as lookup:
            await service.check_ocr_endpoint(ORG, IngestionConfig())
            assert await service._ocr_server_url(ORG, IngestionConfig()) is None

        lookup.assert_not_called()

    async def test_a_visible_ocr_server_resolves_to_its_address(self) -> None:
        config = IngestionConfig(ocr_endpoint_id=uuid.uuid4())
        with patch(
            "app.services.ingestion_config.service_connection_repo.get_visible",
            new=AsyncMock(return_value=_ocr_service()),
        ):
            await IngestionConfigService(_db()).check_ocr_endpoint(ORG, config)
            processor = await IngestionConfigService(_db()).build_processor(ORG, config)

        assert processor.settings.pdf_parser.liteparse_ocr_server_url == "http://ocr:8000"

    @pytest.mark.parametrize(
        ("row", "reason"),
        [
            (None, "not one this collection may name"),
            (_ocr_service(kind="embedding"), "not an OCR server"),
            (_ocr_service(is_active=False), "turned off"),
        ],
        ids=["invisible", "wrong-kind", "paused"],
    )
    async def test_a_server_it_may_not_use_is_refused_on_the_field(self, row, reason) -> None:
        config = IngestionConfig(ocr_endpoint_id=uuid.uuid4())
        with (
            patch(
                "app.services.ingestion_config.service_connection_repo.get_visible",
                new=AsyncMock(return_value=row),
            ),
            pytest.raises(BadRequestError, match=reason) as refusal,
        ):
            await IngestionConfigService(_db()).check_ocr_endpoint(ORG, config)

        assert refusal.value.details["fields"][0]["field"] == "ocr_endpoint_id"


class TestBuildingWhatActuallyRuns:
    async def test_a_collection_that_describes_nothing_gets_no_describer(self) -> None:
        processor = await IngestionConfigService(_db()).build_processor(ORG, IngestionConfig())

        assert processor.image_describer is None
        assert processor.settings.pdf_parser.method == "pymupdf"

    async def test_the_describer_carries_the_prompt_and_the_parameters(self) -> None:
        profile, credential = _profile_and_credential()
        patches = _resolving_to(profile, credential)
        config = IngestionConfig(
            describe_images=True,
            image_description=ImageDescription(
                model_profile_id=profile.id, prompt="read the axis labels", temperature=0.3
            ),
        )

        with patches[0], patches[1]:
            describer = await IngestionConfigService(_db()).build_describer(ORG, config)

        assert isinstance(describer, PydanticAIImageDescriber)
        assert describer.prompt == "read the axis labels"
        assert describer.model_settings == {"temperature": 0.3}

    async def test_an_ingestion_with_no_organization_is_refused_not_downgraded(self) -> None:
        """A document indexed with its diagrams silently missing looks exactly
        like a document that never had any."""
        with pytest.raises(BadRequestError) as refusal:
            await IngestionConfigService(_db()).build_describer(
                None, IngestionConfig(describe_images=True)
            )

        assert "no organization" in refusal.value.message


_DOCLING_URL = "http://docling.internal:5001"


def _docling_service(**overrides: object) -> MagicMock:
    row = MagicMock(
        id=uuid.uuid4(),
        kind="document_parser",
        provider="docling",
        base_url=f"{_DOCLING_URL}/",
        is_active=True,
        secret_id=None,
        requires_key=False,
        organization_id=ORG,
    )
    row.name = "Docling"
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _docling_config(connection: uuid.UUID | None = None) -> IngestionConfig:
    return IngestionConfig(
        pdf_parser=PdfParserName.DOCLING, docling_connection_id=connection or uuid.uuid4()
    )


class _RecordingProcessor:
    """What `build_processor` hands the settings to, since the Docling parser itself
    is not constructible from this module's tests."""

    def __init__(self, *, settings, image_describer) -> None:
        self.settings = settings


_VISIBLE = "app.services.ingestion_config.service_connection_repo.get_visible"
_VAULT = "app.services.ingestion_config.organization_secret_repo.get"


class TestDoclingOptions:
    def test_stored_config_without_docling_fields_loads(self) -> None:
        """A collection stored before Docling existed keeps loading and keeps its parser."""
        config = IngestionConfig.model_validate({"pdf_parser": "pymupdf"})

        assert config.pdf_parser is PdfParserName.PYMUPDF
        assert config.docling_connection_id is None
        assert config.docling_ocr_languages == []
        assert config.docling_ocr_preset == "auto"
        assert config.docling_table_mode.value == "accurate"

    @pytest.mark.parametrize("languages", [["de-DE"], ["deu"], ["DE"], ["a"] * 9])
    def test_docling_languages_must_be_two_letters(self, languages: list[str]) -> None:
        with pytest.raises(ValueError):
            IngestionConfig(docling_ocr_languages=languages)

    def test_two_letter_languages_are_accepted(self) -> None:
        assert IngestionConfig(docling_ocr_languages=["de", "en"]).docling_ocr_languages == [
            "de",
            "en",
        ]

    @pytest.mark.parametrize("preset", ["", "Auto", "a b", "x" * 65])
    def test_the_ocr_preset_is_a_plain_slug(self, preset: str) -> None:
        with pytest.raises(ValueError):
            IngestionConfig(docling_ocr_preset=preset)

    def test_override_can_change_docling_options_not_connection(self) -> None:
        base = _docling_config()
        merged = IngestionOverride(
            docling_ocr_languages=["pl"], docling_ocr_preset="rapid", docling_table_mode="fast"
        ).applied_to(base)

        assert merged.docling_ocr_languages == ["pl"]
        assert merged.docling_ocr_preset == "rapid"
        assert merged.docling_table_mode.value == "fast"
        assert merged.docling_connection_id == base.docling_connection_id
        with pytest.raises(ValueError):
            IngestionOverride.model_validate({"docling_connection_id": str(uuid.uuid4())})

    def test_the_options_reach_the_parser_settings(self) -> None:
        target = DoclingTarget(
            connection_id=uuid.uuid4(), base_url=_DOCLING_URL, api_key="dl-secret-value"
        )
        config = IngestionConfig(
            pdf_parser=PdfParserName.DOCLING,
            docling_ocr_languages=["de"],
            docling_ocr_preset="rapid",
            docling_table_mode="fast",
            max_pages=12,
            parse_timeout_seconds=90.0,
        )

        pdf = rag_settings_for(config, docling=target).pdf_parser

        assert pdf.method == "docling"
        assert pdf.docling_connection_id == target.connection_id
        assert pdf.docling_base_url == _DOCLING_URL
        assert pdf.docling_api_key == "dl-secret-value"
        assert (pdf.docling_ocr_languages, pdf.docling_ocr_preset, pdf.docling_table_mode) == (
            ["de"],
            "rapid",
            "fast",
        )
        assert (pdf.liteparse_max_pages, pdf.liteparse_timeout_seconds) == (12, 90.0)
        assert "dl-secret-value" not in repr(pdf)

    def test_without_a_target_the_docling_settings_are_empty(self) -> None:
        pdf = rag_settings_for(IngestionConfig()).pdf_parser

        assert (pdf.docling_connection_id, pdf.docling_base_url, pdf.docling_api_key) == (
            None,
            None,
            "",
        )


class TestTheDoclingConnection:
    async def test_docling_needs_a_connection(self) -> None:
        with pytest.raises(BadRequestError) as refusal:
            await IngestionConfigService(_db()).check_docling_connection(
                ORG, IngestionConfig(pdf_parser=PdfParserName.DOCLING)
            )

        assert refusal.value.details["fields"][0]["field"] == "docling_connection_id"

    async def test_without_a_field_the_refusal_names_none(self) -> None:
        with pytest.raises(BadRequestError) as refusal:
            await IngestionConfigService(_db()).check_docling_connection(
                ORG, IngestionConfig(pdf_parser=PdfParserName.DOCLING), name_field=False
            )

        assert "fields" not in (refusal.value.details or {})
        assert "no Docling connection" in refusal.value.message

    async def test_another_parser_needs_no_connection(self) -> None:
        with patch(_VISIBLE, new=AsyncMock()) as lookup:
            await IngestionConfigService(_db()).check_docling_connection(ORG, IngestionConfig())
            await IngestionConfigService(_db()).check_docling_connection(
                ORG, IngestionConfig(docling_connection_id=uuid.uuid4())
            )

        lookup.assert_not_called()

    async def test_a_visible_connection_passes(self) -> None:
        with patch(_VISIBLE, new=AsyncMock(return_value=_docling_service())):
            await IngestionConfigService(_db()).check_docling_connection(ORG, _docling_config())

    @pytest.mark.parametrize(
        ("row", "reason"),
        [
            (None, "not one this collection may name"),
            (_docling_service(kind="ocr"), "not a document parser"),
            (_docling_service(provider="liteparse"), "not a document parser"),
            (_docling_service(is_active=False), "turned off"),
        ],
        ids=["invisible", "wrong-kind", "wrong-provider", "paused"],
    )
    async def test_a_connection_it_may_not_use_is_refused_on_the_field(self, row, reason) -> None:
        with (
            patch(_VISIBLE, new=AsyncMock(return_value=row)),
            pytest.raises(BadRequestError, match=reason) as refusal,
        ):
            await IngestionConfigService(_db()).check_docling_connection(ORG, _docling_config())

        assert refusal.value.details["fields"][0]["field"] == "docling_connection_id"

    async def test_docling_connection_must_be_document_parser(self) -> None:
        with (
            patch(_VISIBLE, new=AsyncMock(return_value=_docling_service(kind="ocr"))),
            pytest.raises(BadRequestError, match="not a document parser"),
        ):
            await IngestionConfigService(_db()).check_docling_connection(ORG, _docling_config())

    async def test_docling_connection_inactive_refused(self) -> None:
        with (
            patch(_VISIBLE, new=AsyncMock(return_value=_docling_service(is_active=False))),
            pytest.raises(BadRequestError, match="turned off"),
        ):
            await IngestionConfigService(_db()).check_docling_connection(ORG, _docling_config())

    @pytest.mark.security
    async def test_other_org_docling_connection_refused(self) -> None:
        """The lookup is scoped to the organization; another tenant's row is not found."""
        with (
            patch(_VISIBLE, new=AsyncMock(return_value=None)) as lookup,
            pytest.raises(BadRequestError, match="not one this collection may name"),
        ):
            await IngestionConfigService(_db()).check_docling_connection(ORG, _docling_config())

        assert lookup.await_args.kwargs["organization_id"] == ORG

    @pytest.mark.parametrize(
        "row",
        [None, _docling_service(kind="ocr"), _docling_service(is_active=False)],
        ids=["gone", "wrong-kind", "paused"],
    )
    async def test_an_upload_refusal_names_no_field(self, row) -> None:
        with (
            patch(_VISIBLE, new=AsyncMock(return_value=row)),
            pytest.raises(BadRequestError) as refusal,
        ):
            await IngestionConfigService(_db()).check_docling_connection(
                ORG, _docling_config(), name_field=False
            )

        assert "fields" not in (refusal.value.details or {})
        assert "Docling" in refusal.value.message or "connection" in refusal.value.message

    async def test_a_stored_docling_config_with_no_connection_refuses_the_parse(self) -> None:
        with pytest.raises(BadRequestError, match="names no Docling connection"):
            await IngestionConfigService(_db())._docling_target(
                ORG, IngestionConfig(pdf_parser=PdfParserName.DOCLING)
            )

    async def test_document_parser_service_missing_row_refused(self) -> None:
        with (
            patch(_VISIBLE, new=AsyncMock(return_value=None)),
            pytest.raises(BadRequestError, match="not one this collection may name"),
        ):
            await IngestionConfigService(_db())._document_parser_service(ORG, uuid.uuid4())


class TestResolvingTheDoclingTarget:
    @staticmethod
    def _sealed_row(plaintext: str) -> MagicMock:
        sealed = seal_secret(ApiKeySecret(api_key=plaintext), scope=VaultScope.organization(ORG))
        return MagicMock(
            sealed_secret=sealed.ciphertext,
            kind=SecretKind.API_KEY.value,
            key_version=sealed.key_version,
            purpose="docling",
        )

    async def _build(self, service: MagicMock):
        with (
            patch(_VISIBLE, new=AsyncMock(return_value=service)),
            patch("app.services.ingestion_config.DocumentProcessor", _RecordingProcessor),
        ):
            return await IngestionConfigService(_db()).build_processor(
                ORG, _docling_config(service.id)
            )

    async def test_build_processor_resolves_docling_target_and_key(self) -> None:
        service = _docling_service(secret_id=uuid.uuid4(), requires_key=True)
        with patch(_VAULT, new=AsyncMock(return_value=self._sealed_row("dl-secret-key"))):
            processor = await self._build(service)

        pdf = processor.settings.pdf_parser
        assert pdf.docling_api_key == "dl-secret-key"
        assert pdf.docling_base_url == _DOCLING_URL
        assert pdf.docling_connection_id == service.id

    async def test_a_keyless_connection_resolves_without_touching_the_vault(self) -> None:
        with patch(_VAULT, new=AsyncMock()) as vault:
            processor = await self._build(_docling_service())

        assert processor.settings.pdf_parser.docling_api_key == ""
        vault.assert_not_called()

    async def test_another_parser_resolves_no_docling_target(self) -> None:
        with patch(_VISIBLE, new=AsyncMock()) as lookup:
            processor = await IngestionConfigService(_db()).build_processor(ORG, IngestionConfig())

        assert processor.settings.pdf_parser.docling_base_url is None
        lookup.assert_not_called()

    async def test_build_processor_keyed_row_with_key_gone_refused(self) -> None:
        """`secret_id` went to NULL when the key was deleted; `requires_key` outlives it."""
        service = _docling_service(secret_id=None, requires_key=True)
        with pytest.raises(BadRequestError, match="no longer holds"):
            await self._build(service)

    async def test_a_keyed_row_whose_vault_entry_is_missing_is_refused(self) -> None:
        service = _docling_service(secret_id=uuid.uuid4(), requires_key=True)
        with (
            patch(_VAULT, new=AsyncMock(return_value=None)),
            pytest.raises(BadRequestError, match="no longer holds"),
        ):
            await self._build(service)

    @pytest.mark.security
    async def test_build_processor_unseal_failure_refused(self) -> None:
        service = _docling_service(secret_id=uuid.uuid4(), requires_key=True)
        broken = MagicMock(
            sealed_secret="not-a-ciphertext", kind=SecretKind.API_KEY.value, key_version=1
        )
        with (
            patch(_VAULT, new=AsyncMock(return_value=broken)),
            pytest.raises(BadRequestError, match="could not be unsealed") as refusal,
        ):
            await self._build(service)

        assert "not-a-ciphertext" not in str(refusal.value.details) + refusal.value.message

    @pytest.mark.security
    async def test_build_processor_non_api_key_secret_refused(self) -> None:
        service = _docling_service(secret_id=uuid.uuid4(), requires_key=True)
        with (
            patch(_VAULT, new=AsyncMock(return_value=self._sealed_row("dl-secret-key"))),
            patch("app.services.ingestion_config.unseal_secret", return_value=MagicMock(spec=[])),
            pytest.raises(BadRequestError, match="does not hold an API key"),
        ):
            await self._build(service)

    async def test_an_app_scoped_collection_resolves_a_deployment_connection(self) -> None:
        service = _docling_service(organization_id=None)
        with (
            patch(_VISIBLE, new=AsyncMock(return_value=service)),
            patch("app.services.ingestion_config.DocumentProcessor", _RecordingProcessor),
        ):
            processor = await IngestionConfigService(_db()).build_processor(
                None, _docling_config(service.id)
            )

        assert processor.settings.pdf_parser.docling_api_key == ""


@pytest.mark.security
@pytest.mark.parametrize(("app_scoped", "checked_as"), [(True, None), (False, ORG)])
async def test_a_collection_is_checked_as_its_own_scope(
    app_scoped: bool, checked_as: uuid.UUID | None
) -> None:
    """An app-scoped base names only connections a caller with no organization can reach.

    Its syncs resolve the parser connection, the OCR server and the LlamaParse key
    with no organization, so checking them as the creator's organization accepted
    a connection every sync then failed to find. The image model stays the
    caller's: those syncs skip image description.
    """
    ctx = AuthContext(user_id=uuid.uuid4(), organization_id=ORG, role="owner")
    seen: dict[str, uuid.UUID | None] = {}

    def record(name: str) -> AsyncMock:
        async def check(organization_id: uuid.UUID | None, config: IngestionConfig) -> None:
            seen[name] = organization_id

        return AsyncMock(side_effect=check)

    with (
        patch.object(IngestionConfigService, "resolved_image_model", record("image")),
        patch.object(IngestionConfigService, "check_llamaparse_secret", record("llamaparse")),
        patch.object(IngestionConfigService, "check_ocr_endpoint", record("ocr")),
        patch.object(IngestionConfigService, "check_docling_connection", record("docling")),
    ):
        await KnowledgeBaseService(_db())._usable_config(ctx, None, app_scoped=app_scoped)

    assert seen == {"image": ORG, **dict.fromkeys(("llamaparse", "ocr", "docling"), checked_as)}
