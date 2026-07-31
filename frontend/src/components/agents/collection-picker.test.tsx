import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CollectionPicker } from "./collection-picker";
import { DEFAULT_INGESTION_CONFIG } from "@/lib/ingestion-config";
import type { KnowledgeBase } from "@/types/knowledge-base";

function collection(overrides: Partial<KnowledgeBase> = {}): KnowledgeBase {
  return {
    id: "kb-1",
    organization_id: "org-1",
    owner_user_id: null,
    name: "Handbook",
    description: null,
    scope: "org",
    collection_name: "handbook_a1b2c3",
    is_default: false,
    ingestion_config: DEFAULT_INGESTION_CONFIG,
    embedding_model: "text-embedding-3-large",
    embedding_dim: 3072,
    created_at: "2026-07-01T00:00:00Z",
    updated_at: null,
    document_count: 0,
    indexed_count: 0,
    chunk_count: 0,
    ...overrides,
  };
}

function mount(collections: KnowledgeBase[], selectedIds: string[] = []) {
  const onToggle = vi.fn();
  render(
    <CollectionPicker collections={collections} selectedIds={selectedIds} onToggle={onToggle} />,
  );
  return { onToggle };
}

describe("the collection picker", () => {
  it("says an empty collection is empty", () => {
    // Attaching one produces an agent that searches, finds nothing and says so,
    // which reads as a broken agent rather than an empty collection. A name
    // alone cannot tell the two apart.
    mount([collection()]);

    expect(screen.getByText("empty")).toBeInTheDocument();
  });

  it("counts what a filled collection holds", () => {
    mount([collection({ document_count: 12, indexed_count: 12, chunk_count: 3402 })]);

    expect(screen.getByText("12 documents")).toBeInTheDocument();
    expect(screen.getByText("3,402 chunks")).toBeInTheDocument();
  });

  it("surfaces documents that never finished indexing", () => {
    // The two counts disagreeing is the only signal in a listing that a third of
    // the uploads died - the vectors they never wrote leave no other trace.
    mount([collection({ document_count: 12, indexed_count: 8, chunk_count: 200 })]);

    expect(screen.getByText("4 not indexed")).toBeInTheDocument();
  });

  it("says nothing about indexing when everything indexed", () => {
    // A "0 not indexed" line is an alarm about nothing, and a panel that always
    // looks slightly alarmed is one nobody reads.
    mount([collection({ document_count: 5, indexed_count: 5, chunk_count: 90 })]);

    expect(screen.queryByText(/not indexed/)).toBeNull();
  });

  it("names a collection the spec references but the organization no longer has", () => {
    // Publishing refuses it, and an id that silently vanishes from the form is
    // an id that is still in the spec.
    mount([collection()], ["kb-1", "kb-gone"]);

    expect(screen.getByText("kb-gone")).toBeInTheDocument();
  });

  it("shows the embedding model, because two collections built on different ones are not peers", () => {
    mount([collection()]);

    expect(screen.getByText("text-embedding-3-large")).toBeInTheDocument();
  });
});
