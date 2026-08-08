import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FileContent } from "./file-content";
import type { FileAccess } from "@/lib/file-access";
import type { FileKind } from "@/lib/file-kinds";

vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="markdown">{content}</div>
  ),
}));

function access(overrides: Partial<FileAccess> = {}): FileAccess {
  return {
    textKey: ["text", Math.random()],
    bytesKey: ["bytes", Math.random()],
    readText: () => Promise.resolve({ content: "# Report", truncated: false }),
    readBytes: () => Promise.resolve(new Blob(["%PDF-"], { type: "application/pdf" })),
    download: () => Promise.resolve(),
    ...overrides,
  };
}

function show(kind: FileKind, over: Partial<FileAccess> = {}, name = "report.md") {
  function Wrapper({ children }: { children: ReactNode }) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return render(<FileContent access={access(over)} kind={kind} name={name} />, {
    wrapper: Wrapper,
  });
}

beforeEach(() => {
  Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: vi.fn() });
});

/**
 * One file, fetched and shown.
 *
 * The kind decides which *request* is made and nothing more. Whether what came back
 * can be displayed is the server's answer, read off the response's type - which is
 * why the two halves are separate components rather than one with a conditional hook.
 */
describe("choosing which request to make", () => {
  it("asks for characters for a file that is made of them", async () => {
    const readBytes = vi.fn();
    show("markdown", { readBytes });

    expect(await screen.findByTestId("markdown")).toHaveTextContent("# Report");
    expect(readBytes).not.toHaveBeenCalled();
  });

  it("asks for bytes for everything else", async () => {
    const readText = vi.fn();
    show("pdf", { readText }, "report.pdf");

    expect(await screen.findByTitle("report.pdf")).toBeInTheDocument();
    expect(readText).not.toHaveBeenCalled();
  });

  it("shows the server's answer, not the one the name suggested", async () => {
    // A `.pdf` the API refused to type is served `application/octet-stream`, and this
    // is where that becomes an honest download rather than a broken frame.
    show("pdf", { readBytes: () => Promise.resolve(new Blob(["x"])) }, "report.pdf");

    expect(
      await screen.findByText("This one cannot be shown here — the server serves it as a file."),
    ).toBeInTheDocument();
  });
});

describe("while it is arriving, and when it does not", () => {
  it("says a text file could not be read, and still offers it", async () => {
    const download = vi.fn().mockResolvedValue(undefined);
    show("markdown", { readText: () => Promise.reject(new Error("404 Not Found")), download });

    expect(await screen.findByText("404 Not Found")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Download/ }));
    expect(download).toHaveBeenCalled();
  });

  it("says a binary could not be read", async () => {
    show("pdf", { readBytes: () => Promise.reject(new Error("This host can only read text")) });

    expect(await screen.findByText("This host can only read text")).toBeInTheDocument();
  });

  it("says so when the download offered beside a failure fails too", async () => {
    // A container-backed host refuses a binary either way, so the offer can fail -
    // and silently, before this.
    show("pdf", {
      readBytes: () => Promise.reject(new Error("unreadable")),
      download: () => Promise.reject(new Error("also unreadable")),
    });
    await screen.findByText("unreadable");

    await userEvent.click(screen.getByRole("button", { name: /Download/ }));

    await waitFor(() => expect(screen.getByText("also unreadable")).toBeInTheDocument());
  });

  it("says a shortened answer is shortened, because the agent read the whole file", async () => {
    show("text", { readText: () => Promise.resolve({ content: "abc", truncated: true }) });

    expect(
      await screen.findByText("This has been shortened. The agent reads the whole file."),
    ).toBeInTheDocument();
  });
});
