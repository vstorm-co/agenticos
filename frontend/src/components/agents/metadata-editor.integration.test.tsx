import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { MetadataEditor } from "./metadata-editor";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function mount(categories: string[] = [], tags: string[] = []) {
  render(<MetadataEditor agentId="a1" categories={categories} tags={tags} />, { wrapper });
}

const categoryBox = () => screen.getByRole("textbox", { name: "Add a category" });
const tagBox = () => screen.getByRole("textbox", { name: "Add a tag" });

describe("MetadataEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({ id: "a1", categories: [], tags: [] });
  });

  it("sends the raw typed values to the metadata command", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "a1", categories: ["sales"], tags: [] });
    mount();

    await userEvent.type(categoryBox(), "Sales{Enter}");

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/agents/a1/metadata", {
        categories: ["Sales"],
        tags: [],
      }),
    );
  });

  it("re-renders the chips from the server's normalized response", async () => {
    // The server folds "Sales" to "sales"; the editor must show what was stored,
    // not the raw draft, so the fold/dedupe/clamp is visible.
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "a1", categories: ["sales"], tags: [] });
    mount();

    await userEvent.type(categoryBox(), "Sales{Enter}");

    expect(await screen.findByText("sales")).toBeInTheDocument();
    expect(screen.queryByText("Sales")).toBeNull();
  });

  it("sends a tag alongside the categories already set", async () => {
    vi.mocked(apiClient.patch).mockResolvedValue({
      id: "a1",
      categories: ["sales"],
      tags: ["urgent"],
    });
    mount(["sales"]);

    await userEvent.type(tagBox(), "urgent{Enter}");

    await waitFor(() =>
      expect(apiClient.patch).toHaveBeenCalledWith("/agents/a1/metadata", {
        categories: ["sales"],
        tags: ["urgent"],
      }),
    );
  });

  it("falls back to an empty facet when the response omits one", async () => {
    // A defensive read: the columns are always sent, but the editor must not
    // crash if a response arrives without them.
    vi.mocked(apiClient.patch).mockResolvedValue({ id: "a1" });
    mount();

    await userEvent.type(categoryBox(), "sales{Enter}");

    await waitFor(() => expect(apiClient.patch).toHaveBeenCalled());
    expect(screen.queryByText("sales")).toBeNull();
  });

  it("surfaces a rejected save and keeps the local draft to retry", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("too many"));
    mount();

    await userEvent.type(categoryBox(), "Sales{Enter}");

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("too many"));
    // The draft is kept: the work is there to correct rather than lost.
    expect(screen.getByText("Sales")).toBeInTheDocument();
  });

  it("adopts a categories prop that changed from outside this editor while idle", () => {
    const { rerender } = render(<MetadataEditor agentId="a1" categories={["sales"]} tags={[]} />, {
      wrapper,
    });
    expect(screen.getByText("sales")).toBeInTheDocument();

    // Another client retagged the row; the refetched prop should replace the
    // untouched draft rather than being ignored.
    rerender(<MetadataEditor agentId="a1" categories={["marketing"]} tags={[]} />);

    expect(screen.getByText("marketing")).toBeInTheDocument();
    expect(screen.queryByText("sales")).toBeNull();
  });

  it("keeps a failed save's draft even after the categories prop changes from elsewhere", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("too many"));
    const { rerender } = render(<MetadataEditor agentId="a1" categories={["sales"]} tags={[]} />, {
      wrapper,
    });

    await userEvent.type(categoryBox(), "urgent{Enter}");
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("too many"));
    expect(screen.getByText("urgent")).toBeInTheDocument();

    // Someone else's update to the row must not silently discard the failed,
    // not-yet-retried attempt.
    rerender(<MetadataEditor agentId="a1" categories={["marketing"]} tags={[]} />);

    expect(screen.getByText("sales")).toBeInTheDocument();
    expect(screen.getByText("urgent")).toBeInTheDocument();
    expect(screen.queryByText("marketing")).toBeNull();
  });

  it("adopts a tags prop that changed from outside this editor while idle", () => {
    const { rerender } = render(<MetadataEditor agentId="a1" categories={[]} tags={["eu"]} />, {
      wrapper,
    });
    expect(screen.getByText("eu")).toBeInTheDocument();

    rerender(<MetadataEditor agentId="a1" categories={[]} tags={["apac"]} />);

    expect(screen.getByText("apac")).toBeInTheDocument();
    expect(screen.queryByText("eu")).toBeNull();
  });

  it("keeps a failed save's draft even after the tags prop changes from elsewhere", async () => {
    vi.mocked(apiClient.patch).mockRejectedValue(new Error("too many"));
    const { rerender } = render(<MetadataEditor agentId="a1" categories={[]} tags={["eu"]} />, {
      wrapper,
    });

    await userEvent.type(tagBox(), "urgent{Enter}");
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("too many"));
    expect(screen.getByText("urgent")).toBeInTheDocument();

    rerender(<MetadataEditor agentId="a1" categories={[]} tags={["apac"]} />);

    expect(screen.getByText("eu")).toBeInTheDocument();
    expect(screen.getByText("urgent")).toBeInTheDocument();
    expect(screen.queryByText("apac")).toBeNull();
  });

  it("disables both editors while a save is in flight", async () => {
    let resolve: ((value: unknown) => void) | undefined;
    vi.mocked(apiClient.patch).mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    mount();

    await userEvent.type(categoryBox(), "sales{Enter}");

    await waitFor(() => expect(tagBox()).toBeDisabled());
    resolve?.({ id: "a1", categories: ["sales"], tags: [] });
    await waitFor(() => expect(tagBox()).toBeEnabled());
  });
});
