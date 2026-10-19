import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { findKBDocument } from "@/lib/rag-api";

import { SourceViewer } from "./source-viewer";

vi.mock("@/lib/rag-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/rag-api")>("@/lib/rag-api");
  return { ...actual, findKBDocument: vi.fn() };
});
vi.mock("./file-viewer", () => ({
  FileViewer: ({ doc }: { doc: { filename: string } }) => <div>viewer for {doc.filename}</div>,
}));

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <NextIntlClientProvider locale="en" messages={messages}>
        {children}
      </NextIntlClientProvider>
    </QueryClientProvider>
  );
}

beforeEach(() => vi.clearAllMocks());

/** A citation names a file; opening it finds the document and opens the base's viewer. */
describe("opening a cited file", () => {
  it("opens the knowledge base's viewer on the document with that name", async () => {
    vi.mocked(findKBDocument).mockResolvedValue({
      id: "d1",
      filename: "refunds.md",
    } as Awaited<ReturnType<typeof findKBDocument>>);

    render(
      wrap(<SourceViewer cited={{ kbId: "kb1", filename: "refunds.md" }} onClose={vi.fn()} />),
    );

    expect(await screen.findByText("viewer for refunds.md")).toBeInTheDocument();
    expect(findKBDocument).toHaveBeenCalledWith("kb1", "refunds.md");
  });

  it("says a file deleted since it was cited is gone, rather than opening nothing", async () => {
    vi.mocked(findKBDocument).mockResolvedValue(null);
    const onClose = vi.fn();

    render(wrap(<SourceViewer cited={{ kbId: "kb1", filename: "old.md" }} onClose={onClose} />));

    expect(await screen.findByText(/no longer in its knowledge base/)).toBeInTheDocument();
    // The footer's, beside the corner cross every dialog wears.
    await userEvent.click(screen.getAllByRole("button", { name: "Close" }).at(-1)!);
    expect(onClose).toHaveBeenCalled();
  });
});
