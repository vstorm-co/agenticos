import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ContextPage from "./page";

/**
 * Dropping files on `/context`.
 *
 * A context file is a body in a column, so a drop has nothing to upload: the
 * text becomes the field somebody is about to edit, and the dialog still asks
 * the one question a drop must not answer for them - injected into every run, or
 * read on demand. That is why this opens the form prefilled rather than creating
 * files behind their back.
 *
 * What is refused is refused with a reason and does not take the rest of the drop
 * with it: a folder with a PDF in it should still queue the Markdown beside it.
 */

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api-client", () => ({
  apiClient: { get, post, patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
  ApiError: class extends Error {},
}));
const { error } = vi.hoisted(() => ({ error: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error, warning: vi.fn() } }));
vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="rendered">{content}</div>
  ),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => true, isLoading: false }),
}));

/** A drag event as the browser delivers it - jsdom has no `DataTransfer`. */
function drop(files: File[]): Event {
  const event = new Event("drop", { bubbles: true, cancelable: true });
  Object.defineProperty(event, "dataTransfer", { value: { types: ["Files"], files } });
  return event;
}

function textFile(name: string, body: string, type = "text/markdown"): File {
  const file = new File([body], name, { type });
  // jsdom's File has no `text()`; the page reads the body through it.
  Object.defineProperty(file, "text", { value: () => Promise.resolve(body) });
  return file;
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

async function mount() {
  render(<ContextPage />, { wrapper });
  // The listing resolves first, or the drop lands on a skeleton.
  await screen.findByText("Context files");
}

beforeEach(() => {
  vi.clearAllMocks();
  get.mockResolvedValue({ items: [], total: 0 });
});

describe("dropping files on the context page", () => {
  it("opens the form prefilled from the file, mode still unanswered", async () => {
    await mount();

    act(() => void window.dispatchEvent(drop([textFile("Refund Policy.md", "# Refunds")])));

    // The name is the handle, without the extension it carries in `format`.
    expect(await screen.findByDisplayValue("refund-policy")).toBeInTheDocument();
    expect(screen.getByLabelText("Format")).toHaveTextContent("md");
    expect(screen.getByTestId("rendered")).toHaveTextContent("# Refunds");
    // Nothing was created: the mode question is on screen, unanswered.
    expect(post).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Mode")).toBeInTheDocument();
  });

  it("takes the extension as the format, so a .txt is not called Markdown", async () => {
    await mount();

    act(() => void window.dispatchEvent(drop([textFile("notes.txt", "plain", "text/plain")])));

    expect(await screen.findByDisplayValue("notes")).toBeInTheDocument();
    expect(screen.getByLabelText("Format")).toHaveTextContent("txt");
  });

  it("queues the rest and says how many, one file at a time", async () => {
    post.mockResolvedValue({ id: "c1", name: "one" });
    await mount();

    act(
      () =>
        void window.dispatchEvent(
          drop([textFile("one.md", "first"), textFile("two.md", "second")]),
        ),
    );

    expect(await screen.findByDisplayValue("one")).toBeInTheDocument();
    expect(screen.getByText("1 more file waiting")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    // The second file's own form, not a closed dialog.
    expect(await screen.findByDisplayValue("two")).toBeInTheDocument();
    expect(screen.queryByText("1 more file waiting")).not.toBeInTheDocument();
  });

  it("refuses what is not text and keeps what is", async () => {
    await mount();

    act(
      () =>
        void window.dispatchEvent(
          drop([
            new File([new Uint8Array([1, 2])], "scan.pdf", { type: "application/pdf" }),
            textFile("runbook.md", "steps"),
          ]),
        ),
    );

    expect(await screen.findByDisplayValue("runbook")).toBeInTheDocument();
    await waitFor(() =>
      expect(error).toHaveBeenCalledWith("One file was not text and was skipped"),
    );
  });

  it("abandons the whole drop when the dialog is closed", async () => {
    await mount();

    act(
      () =>
        void window.dispatchEvent(
          drop([textFile("one.md", "first"), textFile("two.md", "second")]),
        ),
    );
    expect(await screen.findByDisplayValue("one")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    // Not the next of the queue: whoever closed it closed it, and a dialog that
    // reopens eight times is a dialog that will not go away.
    await waitFor(() => expect(screen.queryByDisplayValue("two")).toBeNull());
    expect(screen.queryByDisplayValue("one")).toBeNull();
  });
});
