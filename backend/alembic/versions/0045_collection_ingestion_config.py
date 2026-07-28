"""How each collection reads its documents, and what it was indexed with

Revision ID: 0045_ingestion_config
Revises: 0044_message_version
Create Date: 2026-07-27

Which parser reads a PDF, how large a chunk is, and which model describes the
pictures inside a document were all deployment settings: one answer per
installation, read from the environment, the same for a scanned archive of
contracts as for a folder of Markdown. They move onto the collection here.

``knowledge_bases.ingestion_config`` and ``rag_documents.ingestion_config`` are
JSON because the set of options is going to grow and a new parser flag should
not be a migration. The two mean different things and are not redundant: the
collection's is the configuration in force *now*, the document's is the one it
was actually read with — the collection's, with whatever that single upload
overrode already folded in. A collection's configuration changes and its
existing documents are not re-parsed, so without the second column "why is this
one chunked differently" has no answer at all.

``embedding_model`` and ``embedding_dim`` are the part that is not a
preference. ``PgVectorStore`` creates a collection's table once, as
``embedding vector(N)``, with ``N`` derived from the deployment's
``EMBEDDING_MODEL``. Until now that environment variable was the only record of
what any collection had been indexed with, so changing it broke every existing
collection silently — either every insert failed on a width mismatch, or, for
two models that happen to share a width, vectors from a different space were
written next to the old ones and compared against them as though the numbers
meant the same thing. Recording it per collection is what lets the platform
refuse the second case instead of answering searches that are quietly wrong.

**The backfill.** Existing rows are stamped with this deployment's current
settings, because that is what they were in fact built with — there is no other
record, and a null here is a collection nobody can decide whether it is safe to
index into. The values are read from ``settings`` rather than hardcoded so the
stamp matches the running installation. Documents ingested before this
migration get the same treatment, with ``image_description_model`` left null:
whether a given old document had images at all is not knowable, and inventing a
model that may never have run on it would be worse than saying nothing.

The downgrade drops all seven columns. That loses the record of what each
collection was indexed with, which is exactly the state this migration exists to
end — so a downgrade is only safe while the deployment's ``EMBEDDING_MODEL`` is
still the one everything was built with.
"""

import json

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op
from app.core.config import settings

revision = "0045_ingestion_config"
down_revision = "0044_message_version"
branch_labels = None
depends_on = None


# A copy of the default image-description prompt, for the same reason the
# settings below are read rather than imported: the prompt is application text
# and may be reworded, but what was stamped onto existing rows at this revision
# must not change with it.
_IMAGE_PROMPT = (
    "Describe this image in detail. Focus on any text, data, charts, diagrams, "
    "or visual information that would be useful for document search and retrieval. "
    "Be concise but comprehensive."
)


def _deployment_config() -> str:
    """The parsing settings this installation has been using, as JSON.

    Spelled out here rather than imported from
    ``app.services.ingestion_config.deployment_defaults`` on purpose: what a
    migration wrote must not change when application code does, or re-running
    the chain on a restored dump produces different rows from the first run.

    ``describe_images`` is false whatever ``RAG_ENABLE_IMAGE_DESCRIPTION`` says.
    The flag it replaces cost nothing to leave on — the model came from
    ``AI_MODEL`` and the key from the environment — while the column it becomes
    requires a model profile the organization pays for. Backfilling it as true
    would turn every existing collection into one that refuses uploads until
    somebody picks a model.

    The values are literals for the reason the paragraph above gives, which the
    first version of this file stated and then contradicted: it read
    ``settings.PDF_PARSER`` and its siblings live. Those settings were deleted
    one commit later — parsing is a per-collection choice now — and the whole
    chain stopped being runnable from scratch with
    ``AttributeError: 'Settings' object has no attribute 'PDF_PARSER'``. Nobody
    saw it because every existing database was already past this revision; it
    surfaced the first time a fresh one was created. A migration is a record of
    what happened, so it may not ask the application what it currently thinks.

    ``ocr_language`` stays ``"en"`` rather than being quietly corrected to the
    three-letter code Tesseract wants: that is what this revision wrote, and
    ``0046_ocr_tesseract`` is the revision that fixes it. Replaying the chain
    should reproduce history, not skip it.
    """
    return json.dumps(
        {
            "pdf_parser": "pymupdf",
            "ocr": False,
            "llamaparse_tier": "agentic",
            "ocr_language": "en",
            "parse_timeout_seconds": 600.0,
            "chunk_size": 512,
            "chunk_overlap": 50,
            "chunking_strategy": "recursive",
            "describe_images": False,
            "image_description": {
                "model_profile_id": None,
                "prompt": _IMAGE_PROMPT,
                "temperature": None,
                "thinking": None,
            },
        }
    )


def upgrade() -> None:
    config_json = _deployment_config()
    # The one thing here that must come from the environment rather than from a
    # literal, and the exception that proves the rule above: existing
    # collections were physically indexed with whatever `EMBEDDING_MODEL` said
    # at the time, and their vector columns were created at that model's width.
    # Recording anything else would describe vectors that do not exist.
    embedding_model = settings.EMBEDDING_MODEL
    embedding_dim = settings.rag.embeddings_config.dim

    op.add_column(
        "knowledge_bases",
        sa.Column("ingestion_config", JSONB, nullable=False, server_default="{}"),
    )
    # Added nullable, backfilled, then made NOT NULL: a server default would
    # freeze one deployment's model into the schema, where a later reader would
    # take it for a value somebody chose.
    op.add_column("knowledge_bases", sa.Column("embedding_model", sa.String(128), nullable=True))
    op.add_column("knowledge_bases", sa.Column("embedding_dim", sa.Integer(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE knowledge_bases SET ingestion_config = CAST(:config AS jsonb), "
            "embedding_model = :model, embedding_dim = :dim"
        ).bindparams(config=config_json, model=embedding_model, dim=embedding_dim)
    )
    op.alter_column("knowledge_bases", "embedding_model", nullable=False)
    op.alter_column("knowledge_bases", "embedding_dim", nullable=False)

    op.add_column(
        "rag_documents",
        sa.Column("ingestion_config", JSONB, nullable=False, server_default="{}"),
    )
    op.add_column("rag_documents", sa.Column("ingestion_override", JSONB, nullable=True))
    op.add_column(
        "rag_documents", sa.Column("image_description_model", sa.String(255), nullable=True)
    )
    op.add_column("rag_documents", sa.Column("embedding_model", sa.String(128), nullable=True))
    op.execute(
        sa.text(
            "UPDATE rag_documents SET ingestion_config = CAST(:config AS jsonb), "
            "embedding_model = :model"
        ).bindparams(config=config_json, model=embedding_model)
    )


def downgrade() -> None:
    op.drop_column("rag_documents", "embedding_model")
    op.drop_column("rag_documents", "image_description_model")
    op.drop_column("rag_documents", "ingestion_override")
    op.drop_column("rag_documents", "ingestion_config")
    op.drop_column("knowledge_bases", "embedding_dim")
    op.drop_column("knowledge_bases", "embedding_model")
    op.drop_column("knowledge_bases", "ingestion_config")
