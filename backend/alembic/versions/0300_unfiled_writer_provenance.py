"""Quarantine ambiguous unfiled chunks instead of publishing a former owner's data.

Missing ownership is not evidence of an operator import. Existing tracking rows
with a base or initiator prove a document origin; everything else remains unknown
until an operator explicitly confirms it. Runtime JSONB keys were not reserved
before this revision, so an old `writer_kind` value is not trusted. Known filed
tracking rows also restore their chunks' base tag, preserving authorized legacy
reads without allowing an app base to adopt somebody else's data.

Downgrade retains provenance metadata (discarding it would reopen the ambiguity)
but removes the tracking column. Re-upgrading quarantines old tags again.
"""

import sqlalchemy as sa

from alembic import op

revision: str = "0300_unfiled_writer_provenance"
down_revision: str = "0299_nightly_read_receipt"
branch_labels: None = None
depends_on: None = None


def upgrade() -> None:
    op.add_column(
        "rag_documents",
        sa.Column("writer_kind", sa.String(20), nullable=False, server_default="legacy_unknown"),
    )
    op.create_check_constraint(
        op.f("rag_documents_writer_kind_check"),
        "rag_documents",
        "writer_kind IN ('document', 'operator', 'legacy_unknown')",
    )
    op.execute("""
        UPDATE rag_documents SET writer_kind = 'document'
        WHERE knowledge_base_id IS NOT NULL OR organization_id IS NOT NULL
           OR initiated_by_user_id IS NOT NULL
    """)
    # Catalog discovery excludes schema tables by requiring a pgvector column.
    # Identifiers come from PostgreSQL and are quoted by format's %I.
    op.execute("""
        DO $$ DECLARE target record;
        BEGIN
          FOR target IN
            SELECT c.table_name FROM information_schema.columns c
            WHERE c.table_schema = 'public' AND c.column_name = 'embedding'
              AND c.udt_name = 'vector' AND c.table_name LIKE 'rag\\_%' ESCAPE '\\'
          LOOP
            EXECUTE format(
              'UPDATE public.%I SET metadata = jsonb_set(coalesce(metadata, ''{}''::jsonb), ''{writer_kind}'', ''"legacy_unknown"''::jsonb)
               WHERE metadata->>''knowledge_base_id'' IS NULL', target.table_name);
            EXECUTE format(
              'UPDATE public.%I AS chunks
               SET metadata = chunks.metadata || jsonb_build_object(''writer_kind'', ''document'')
                 || CASE WHEN docs.knowledge_base_id IS NOT NULL
                         THEN jsonb_build_object(''knowledge_base_id'', docs.knowledge_base_id::text)
                         ELSE ''{}''::jsonb END
               FROM (
                 SELECT collection_name, vector_document_id, vector_tenant,
                        CASE WHEN count(DISTINCT knowledge_base_id) = 1
                                   AND bool_and(knowledge_base_id IS NOT NULL)
                             THEN min(knowledge_base_id::text) END AS knowledge_base_id
                 FROM (
                   SELECT documents.*,
                          CASE WHEN bases.scope = ''app'' THEN NULL
                               WHEN bases.id IS NOT NULL THEN bases.organization_id
                               ELSE documents.organization_id END AS vector_tenant
                   FROM rag_documents documents
                   LEFT JOIN knowledge_bases bases ON bases.id = documents.knowledge_base_id
                 ) documents
                 GROUP BY collection_name, vector_document_id, vector_tenant
                 HAVING bool_or(writer_kind = ''document'')
               ) docs
               WHERE docs.collection_name = $1
                 AND docs.vector_document_id = chunks.parent_doc_id
                 AND chunks.metadata->>''knowledge_base_id'' IS NULL
                 AND chunks.metadata->>''organization_id'' IS NOT DISTINCT FROM docs.vector_tenant::text',
              target.table_name) USING substring(target.table_name FROM 5);
          END LOOP;
        END $$;
    """)


def downgrade() -> None:
    op.drop_constraint(op.f("rag_documents_writer_kind_check"), "rag_documents", type_="check")
    op.drop_column("rag_documents", "writer_kind")
