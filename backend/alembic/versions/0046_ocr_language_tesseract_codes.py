"""Rewrite stored OCR language codes to the three-letter ones Tesseract takes

Revision ID: 0046_ocr_tesseract
Revises: 0045_ingestion_config
Create Date: 2026-07-27

``IngestionConfig.ocr_language`` is handed to LiteParse, which passes it to
Tesseract, which wants ISO 639-2/T: ``eng``, ``pol``, ``deu``. The field was
seeded from ``LITEPARSE_OCR_LANGUAGE``, whose default was ``en`` — an ISO 639-1
code, the kind this product uses everywhere else for a UI locale, and one
Tesseract has no language pack under. It is the worst shape of wrong value:
plausible on screen, and silent at run time, because a parse with an unknown
language does not fail, it returns nothing.

The field now carries ``^[a-z]{3}(\\+[a-z]{3})*$``, which is why this migration
has to exist rather than the constraint standing on its own. Every row written
before it holds ``en``, so without a rewrite the model refuses to *read* them:
`GET /kb` answers 500 for the whole listing because one field of one row will
not validate, and no amount of editing in the UI can fix a collection whose page
cannot load.

Rows are rewritten rather than cleared. ``en`` maps to ``eng`` because that is
unambiguously what it meant; anything else that does not match the pattern
becomes ``eng`` too, since a code Tesseract cannot resolve was never doing
anything except reading nothing, and the alternative is a row that stays
unreadable. The two-letter codes mapped explicitly are the ones a deployment
could plausibly have set by hand.

Down-migration restores ``en`` for ``eng`` only. It cannot do better: the
mapping is many-to-one in the direction that matters, and inventing a
two-letter code for ``pol+eng`` would be a guess.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0046_ocr_tesseract"
down_revision: str | Sequence[str] | None = "0045_ingestion_config"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ISO 639-1 -> ISO 639-2/T, for the codes an operator might have set by hand.
# Deliberately short: this is a repair for values this platform could actually
# have written, not a general language table.
_ISO_639_1_TO_639_2 = {
    "en": "eng",
    "pl": "pol",
    "de": "deu",
    "fr": "fra",
    "es": "spa",
    "it": "ita",
    "pt": "por",
    "nl": "nld",
    "cs": "ces",
    "sk": "slk",
    "uk": "ukr",
    "ru": "rus",
}

_VALID = r"^[a-z]{3}(\+[a-z]{3})*$"


def upgrade() -> None:
    # Both tables carry the same shape: the collection's configuration and the
    # one each document was actually read with.
    for table in ("knowledge_bases", "rag_documents"):
        for old, new in _ISO_639_1_TO_639_2.items():
            op.execute(
                f"""
                UPDATE {table}
                SET ingestion_config = jsonb_set(
                    ingestion_config::jsonb, '{{ocr_language}}', '"{new}"'
                )
                WHERE ingestion_config->>'ocr_language' = '{old}'
                """
            )
        # Whatever is left that the model would refuse. Without this the rewrite
        # would be a partial repair, which is the same 500 for anyone unlucky
        # enough to hold a value outside the table above.
        op.execute(
            f"""
            UPDATE {table}
            SET ingestion_config = jsonb_set(
                ingestion_config::jsonb, '{{ocr_language}}', '"eng"'
            )
            WHERE ingestion_config ? 'ocr_language'
              AND ingestion_config->>'ocr_language' !~ '{_VALID}'
            """
        )


def downgrade() -> None:
    for table in ("knowledge_bases", "rag_documents"):
        op.execute(
            f"""
            UPDATE {table}
            SET ingestion_config = jsonb_set(
                ingestion_config::jsonb, '{{ocr_language}}', '"en"'
            )
            WHERE ingestion_config->>'ocr_language' = 'eng'
            """
        )
