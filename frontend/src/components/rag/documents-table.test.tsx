import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import type { KBDocument } from "@/types";
import { DocumentsTable } from "./documents-table";

const download = vi.fn().mockResolvedValue(undefined);
vi.mock("@/lib/rag-api", () => ({ kbDocumentAccess: () => ({ download }) }));

const stored: KBDocument = {
  id: "doc-1",
  collection_name: "knowledge",
  filename: "handbook.pdf",
  filetype: "pdf",
  filesize: 100,
  status: "stored",
  error_message: null,
  vector_document_id: null,
  chunk_count: 0,
  has_file: true,
  has_parsed_content: true,
  created_at: "2026-11-25T10:00:00Z",
  completed_at: null,
  parser: "liteparse",
  image_description_model: null,
  embedding_model: null,
  was_overridden: false,
  organizational_unit: null,
};

function show(overrides: Partial<ComponentProps<typeof DocumentsTable>> = {}) {
  const props: ComponentProps<typeof DocumentsTable> = {
    kbId: "kb-1",
    documents: [stored],
    documentsTotal: 1,
    hasMoreDocuments: false,
    isLoading: false,
    isLoadingMoreDocs: false,
    mayEdit: true,
    onLoadMore: vi.fn(),
    onPreview: vi.fn(),
    onRemove: vi.fn(),
    onRetry: vi.fn().mockResolvedValue(undefined),
    onChooseFiles: vi.fn(),
    ...overrides,
  };
  render(<DocumentsTable {...props} />);
  return props;
}

describe("stored knowledge content", () => {
  it("labels the file as unindexed and runs indexing only after an explicit click", async () => {
    let finish: () => void = () => {};
    const onRetry = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    show({ onRetry });
    expect(screen.getByText("Stored · not indexed")).toBeInTheDocument();
    const index = screen.getByRole("button", { name: "Index handbook.pdf" });
    expect(onRetry).not.toHaveBeenCalled();
    await userEvent.click(index);
    expect(index).toBeDisabled();
    await userEvent.click(index);
    expect(onRetry).toHaveBeenCalledExactlyOnceWith("doc-1");
    await act(async () => finish());
    await waitFor(() => expect(index).toBeEnabled());
  });

  it("previews a parsed-only snapshot without offering a missing original or indexing", async () => {
    const props = show({ documents: [{ ...stored, has_file: false }] });
    await userEvent.click(screen.getByRole("button", { name: "Preview file" }));
    expect(props.onPreview).toHaveBeenCalledWith({ ...stored, has_file: false });
    expect(screen.queryByRole("button", { name: "Download file" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Index / })).not.toBeInTheDocument();
  });

  it("downloads the original independently of the vector index", async () => {
    download.mockClear();
    show();
    await userEvent.click(screen.getByRole("button", { name: "Download file" }));
    expect(download).toHaveBeenCalledOnce();
  });

  it("offers retry for a failed original and respects read-only resource access", () => {
    const { unmount } = render(
      <DocumentsTable
        kbId="kb-1"
        documents={[{ ...stored, status: "error" }]}
        documentsTotal={1}
        hasMoreDocuments={false}
        isLoading={false}
        isLoadingMoreDocs={false}
        mayEdit
        onLoadMore={vi.fn()}
        onPreview={vi.fn()}
        onRemove={vi.fn()}
        onRetry={vi.fn()}
        onChooseFiles={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Retry handbook.pdf" })).toBeInTheDocument();
    unmount();
    show({ mayEdit: false });
    expect(screen.queryByRole("button", { name: /Index / })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remove document/ })).not.toBeInTheDocument();
  });

  it("does not expose unavailable previews or start another processing attempt", () => {
    show({
      documents: [{ ...stored, status: "processing", has_file: false, has_parsed_content: false }],
    });
    expect(screen.queryByRole("button", { name: "Preview file" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Index / })).not.toBeInTheDocument();
  });
});
