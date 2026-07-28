"""How a collection says its documents should be read, and what that resolves to.

The value of this module is almost entirely in what it refuses and what it
records. A merge that loses an override, a configuration that names a model
nobody can run, and a collection quietly indexed with a second embedding model
all look like success at the moment they happen and like corrupt search results
weeks later.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import BadRequestError, NotFoundError
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
    deployment_defaults,
    deployment_embedding,
    parse_override,
    rag_settings_for,
)
from app.services.rag.image_describer import PydanticAIImageDescriber

pytestmark = pytest.mark.anyio

ORG = uuid.uuid4()


def _db() -> MagicMock:
    db = MagicMock()
    db.flush = AsyncMock()
    return db


def _profile_and_credential() -> tuple[ModelProfile, OrganizationSecret]:
    """A profile with a real sealed key behind it, so ``build()`` can be reached."""
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
        """Reasoning models reject ``temperature`` outright, including ``0``."""
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

        with pytest.raises(ValueError, match="chunk_overlap"):
            IngestionOverride(chunk_size=1024).applied_to(base)


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
        """``null`` is a value here and omission is not, or three states become two."""
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


class TestWhatTheDeploymentSeedsANewCollectionWith:
    def test_the_environment_does_not_decide_how_a_collection_parses(self) -> None:
        """How documents are read is per collection, and the row is the only source.

        An installation-wide `PDF_PARSER`/`RAG_CHUNK_SIZE` — inherited from the
        template this project was generated from — made the same form produce
        different collections on two deployments, with nothing in the product
        showing which. The variables are gone; this pins that no replacement
        creeps back in through `settings`.
        """
        with patch("app.services.ingestion_config.settings") as env:
            env.PDF_PARSER = "liteparse"
            env.RAG_CHUNK_SIZE = 1024
            env.LITEPARSE_OCR_LANGUAGE = "pol"

            seeded = deployment_defaults()

        assert seeded == IngestionConfig()
        assert seeded.pdf_parser is PdfParserName.PYMUPDF
        assert seeded.chunk_size == 512
        assert seeded.ocr_language == "eng"

    def test_liteparse_defaults_to_markdown_with_ocr_decided_per_document(self) -> None:
        """The two defaults that decide what a LiteParse collection costs and returns.

        Markdown is what the markdown chunking strategy splits on, and `auto_ocr`
        is the difference between OCRing every page and OCRing the scans —
        verified against a real parse, not assumed.
        """
        seeded = deployment_defaults()

        assert seeded.liteparse_output_format is LiteParseOutputFormat.MARKDOWN
        assert seeded.auto_ocr is True
        assert seeded.max_pages == 1000

    def test_image_description_starts_off_whatever_the_environment_said(self) -> None:
        """It now costs a model profile the organization pays for; that is a choice."""
        assert deployment_defaults().describe_images is False

    def test_the_embedding_model_is_recorded_with_the_width_it_implies(self) -> None:
        with patch("app.services.ingestion_config.settings") as env:
            env.EMBEDDING_MODEL = "text-embedding-3-small"

            assert deployment_embedding() == ("text-embedding-3-small", 1536)

    def test_an_embedding_model_of_unknown_width_is_refused(self) -> None:
        """The column would be created at the default width and every insert would fail."""
        with (
            patch("app.services.ingestion_config.settings") as env,
            pytest.raises(BadRequestError) as refusal,
        ):
            env.EMBEDDING_MODEL = "some-new-embedder"
            deployment_embedding()

        assert "some-new-embedder" in refusal.value.message


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

    def test_the_ocr_server_address_stays_the_deployments(self) -> None:
        """A tenant choosing a URL the backend then calls is request forgery."""
        with patch("app.services.ingestion_config.settings") as env:
            env.LITEPARSE_OCR_SERVER_URL = "http://easyocr.internal:8000"
            env.LLAMAPARSE_API_KEY = "llx-deployment"
            env.EMBEDDING_MODEL = "text-embedding-3-large"

            settings = rag_settings_for(IngestionConfig())

        assert settings.pdf_parser.liteparse_ocr_server_url == "http://easyocr.internal:8000"
        assert settings.pdf_parser.api_key == "llx-deployment"


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

    async def test_a_configuration_naming_no_model_is_told_so(self) -> None:
        """The refusal belongs on the form that turned this on, not on an upload.

        There is no organization-wide default to fall back on any more, so image
        description names its model or is refused — the same rule an agent
        follows, and for the same reason: a model nobody chose is one somebody
        else's change can swap underneath the collection.
        """
        with pytest.raises(NotFoundError):
            await IngestionConfigService(_db()).resolved_image_model(
                ORG, IngestionConfig(describe_images=True)
            )


class TestTheEmbeddingModelACollectionWasBuiltWith:
    def test_indexing_continues_while_the_deployment_still_uses_it(self) -> None:
        with patch("app.services.ingestion_config.settings") as env:
            env.EMBEDDING_MODEL = "text-embedding-3-large"

            IngestionConfigService(_db()).check_embedding_model(
                collection="handbook", built_with="text-embedding-3-large"
            )

    def test_a_second_model_is_refused_and_both_are_named(self) -> None:
        """Silent is the failure mode that matters: two models of equal width
        write into one column and search keeps answering, wrongly."""
        with (
            patch("app.services.ingestion_config.settings") as env,
            pytest.raises(BadRequestError) as refusal,
        ):
            env.EMBEDDING_MODEL = "text-embedding-3-small"
            IngestionConfigService(_db()).check_embedding_model(
                collection="handbook", built_with="text-embedding-3-large"
            )

        assert "text-embedding-3-large" in refusal.value.message
        assert "text-embedding-3-small" in refusal.value.message
        assert refusal.value.details == {
            "collection": "handbook",
            "built_with": "text-embedding-3-large",
            "configured": "text-embedding-3-small",
        }


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
