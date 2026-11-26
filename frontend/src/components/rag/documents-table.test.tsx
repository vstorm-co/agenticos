import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentsTable } from "./documents-table";
import { ApiError } from "@/lib/api-error";
import type { KBDocument } from "@/types";

const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: (m: string) => toastError(m) } }));

function document(overrides: Partial<KBDocument> = {}): KBDocument {
  return {
    id: "doc-1",
    collection_name: "handbook",
    filename: "scan.png",
    filetype: "png",
    filesize: 10,
    status: "error",
    error_message: "Docling found no text in this file.",
    vector_document_id: null,
    chunk_count: 0,
    has_file: true,
    created_at: "",
    completed_at: null,
    ...overrides,
  } as KBDocument;
}

function show(doc: KBDocument, mayEdit = true, onRetry = vi.fn(async () => {})) {
  render(
    <DocumentsTable
      kbId="kb-1"
      documents={[doc]}
      documentsTotal={1}
      hasMoreDocuments={false}
      isLoading={false}
      isLoadingMoreDocs={false}
      mayEdit={mayEdit}
      onLoadMore={vi.fn()}
      onPreview={vi.fn()}
      onRemove={vi.fn()}
      onRetry={onRetry}
      onChooseFiles={vi.fn()}
    />,
  );
  return onRetry;
}

describe("retrying a failed document", () => {
  beforeEach(() => toastError.mockReset());

  it("asks for a retry from the icon beside Failed", async () => {
    const doc = document();
    const onRetry = show(doc);

    await userEvent.click(screen.getByRole("button", { name: "Retry scan.png" }));

    expect(onRetry).toHaveBeenCalledWith(doc);
  });

  it("says why when the retry is refused", async () => {
    const refused = vi.fn(async () => {
      throw new ApiError(400, "This collection's parser no longer reads '.png' files", {
        error: {
          code: "BAD_REQUEST",
          message: "This collection's parser no longer reads '.png' files",
        },
      });
    });
    show(document(), true, refused);

    await userEvent.click(screen.getByRole("button", { name: "Retry scan.png" }));

    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });

  it.each([
    ["a finished document", document({ status: "done" }), true],
    ["a document with no stored file", document({ has_file: false }), true],
    ["someone who cannot edit the collection", document(), false],
  ])("offers no retry for %s", (_, doc, mayEdit) => {
    show(doc, mayEdit);

    expect(screen.queryByRole("button", { name: /^Retry/ })).toBeNull();
  });
});
