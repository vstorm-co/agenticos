import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FileViewer } from "./file-viewer";
import { apiClient } from "@/lib/api-client";

/**
 * A knowledge base document, opened.
 *
 * Two tabs are about the ingestion pipeline rather than about the file: what the
 * parser made of it, and the records that went into the store. They read one
 * payload - the parsed endpoint *is* the store's chunks, grouped into pages - so
 * the second tab must not fetch it again, and the JSON one exists because prose
 * with markdown applied is not something you can tell one record from another in.
 */

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => <div>{content}</div>,
}));

const PARSED = {
  id: "doc-1",
  filename: "handbook.pdf",
  parser: "liteparse",
  chunk_count: 2,
  has_text: true,
  pages: [{ page_num: 1, chunks: ["the first chunk", "the second chunk"], has_text: true }],
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function show() {
  render(
    <FileViewer
      kbId="kb-1"
      open
      onClose={vi.fn()}
      doc={{ id: "doc-1", filename: "handbook.pdf", filetype: "application/pdf" }}
    />,
    { wrapper },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path.endsWith("/parsed")) return PARSED;
    return { items: [], total: 0 };
  });
});

describe("the records a document became", () => {
  it("shows one record per stored chunk, as a tree rather than a wall", async () => {
    show();
    await userEvent.click(screen.getByRole("tab", { name: "JSON" }));

    expect(await screen.findByText("chunks:")).toBeInTheDocument();
    expect(screen.getByText("the first chunk")).toBeInTheDocument();
    expect(screen.getByText("the second chunk")).toBeInTheDocument();
    // The two records are the flattened pages: what the store holds, in the
    // order it holds it, rather than the page grouping the parsed tab draws.
    expect(screen.getAllByText("page_num:")).toHaveLength(2);
  });

  it("folds a record away so the next one is reachable", async () => {
    show();
    await userEvent.click(screen.getByRole("tab", { name: "JSON" }));
    const chunks = await screen.findByRole("button", { name: /chunks:/ });

    await userEvent.click(chunks);

    expect(screen.queryByText("the first chunk")).toBeNull();
    expect(screen.getByText("[ 2 items ]")).toBeInTheDocument();
  });

  it("counts the chunks and the characters as facts, not as a sentence", async () => {
    // The strip was one line of prose joined by middots, which put a caveat, a
    // count and a tool name at the same weight.
    show();
    await userEvent.click(screen.getByRole("tab", { name: "JSON" }));

    expect(await screen.findByText("2 chunks")).toBeInTheDocument();
    expect(screen.getByText("31 characters")).toBeInTheDocument();
    expect(screen.getByLabelText("Chunks")).toBeInTheDocument();
    expect(screen.getByLabelText("Characters")).toBeInTheDocument();
  });

  it("names the parser on both tabs, and counts characters on neither but this one", async () => {
    show();
    await userEvent.click(screen.getByRole("tab", { name: "Parsed" }));

    expect(await screen.findByText("liteparse")).toBeInTheDocument();
    expect(screen.queryByText("31 characters")).toBeNull();
    // The caveat is a sentence, so it sits under the facts rather than beside them
    // - and only where the repetition it describes is on screen.
    expect(screen.getByText(/boundary text appears twice/)).toBeInTheDocument();
  });

  it("reads the parse once for both tabs", async () => {
    // Two tabs over one payload. A second request would be a second answer to a
    // question whose answer cannot change - the parse is stored, not recomputed.
    show();
    await userEvent.click(screen.getByRole("tab", { name: "Parsed" }));
    await screen.findByText("the first chunk");
    await userEvent.click(screen.getByRole("tab", { name: "JSON" }));
    await screen.findByText("chunks:");

    const fetches = vi
      .mocked(apiClient.get)
      .mock.calls.filter(([path]) => String(path).endsWith("/parsed"));
    expect(fetches).toHaveLength(1);
  });

  it("says a document with no parse has none, on either tab", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path.endsWith("/parsed")) throw new Error("No parsed content for this document");
      return { items: [], total: 0 };
    });
    show();
    await userEvent.click(screen.getByRole("tab", { name: "JSON" }));

    expect(await screen.findByText("No parsed content to show")).toBeInTheDocument();
    expect(screen.getByText(/No parsed content for this document/)).toBeInTheDocument();
  });
});
