import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { CreateDatasetDialog } from "./create-dataset-dialog";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", async (original) => ({
  ...(await original<typeof import("next/navigation")>()),
  useRouter: () => ({ push }),
}));
import { toast } from "sonner";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function mount() {
  const onOpenChange = vi.fn();
  render(<CreateDatasetDialog open onOpenChange={onOpenChange} />, { wrapper });
  return { onOpenChange };
}

describe("CreateDatasetDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUnsavedChangesStore.setState({ sources: {}, prompt: null, saving: false });
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  });

  it("freezes a pending creation and restores the draft after refusal", async () => {
    let rejectWrite: (error: Error) => void = () => {
      throw new Error("Not started");
    };
    vi.mocked(apiClient.post).mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectWrite = reject;
        }),
    );
    const { onOpenChange } = mount();
    await userEvent.type(screen.getByLabelText(/^Name/), "Mobile review");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(screen.getByLabelText(/^Name/)).toBeDisabled());
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    expect(onOpenChange).not.toHaveBeenCalled();
    const proceed = vi.fn();
    act(() => useUnsavedChangesStore.getState().leave(proceed));
    await act(() => useUnsavedChangesStore.getState().answer("save"));
    expect(proceed).not.toHaveBeenCalled();
    await act(async () => rejectWrite(new Error("Controlled refusal")));
    await waitFor(() => expect(screen.getByLabelText(/^Name/)).toBeEnabled());
    expect(screen.getByLabelText(/^Name/)).toHaveValue("Mobile review");
  });

  it("preserves a creation draft on Stay and resets it on Discard", async () => {
    const { onOpenChange } = mount();
    await userEvent.type(screen.getByLabelText(/^Name/), "Mobile review");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await act(() => useUnsavedChangesStore.getState().answer("stay"));
    expect(screen.getByLabelText(/^Name/)).toHaveValue("Mobile review");
    await userEvent.keyboard("{Escape}");
    await act(() => useUnsavedChangesStore.getState().answer("discard"));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.getByLabelText(/^Name/)).toHaveValue("");
  });

  it("creates a dataset, trimming what was typed, and opens it", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "d1", name: "refunds" });
    const { onOpenChange } = mount();
    expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/^Name/), " refunds ");
    await userEvent.click(screen.getByRole("button", { name: "More options" }));
    await userEvent.type(screen.getByLabelText("Description"), " returns ");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/datasets/d1"));
    expect(apiClient.post).toHaveBeenCalledWith("/datasets", {
      name: "refunds",
      description: "returns",
      visibility: "org",
    });
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("says a taken name under the name, and sends no description when none was written", async () => {
    const taken = "A dataset named 'refunds' already exists.";
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(409, taken, {
        error: { code: "ALREADY_EXISTS", message: taken, details: { name: "refunds" } },
      }),
    );
    mount();
    await userEvent.type(screen.getByLabelText(/^Name/), "refunds");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(await screen.findByText(taken)).toBeInTheDocument();
    expect(apiClient.post).toHaveBeenCalledWith("/datasets", {
      name: "refunds",
      description: null,
      visibility: "org",
    });
    expect(toast.error).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText(/^Name/), " new");
    expect(screen.queryByText(taken)).toBeNull();
  });

  it("opens optional details when the server rejects the description", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(400, "Invalid description", {
        error: {
          code: "BAD_REQUEST",
          message: "Invalid description",
          details: { fields: [{ field: "description", message: "Choose a clearer description" }] },
        },
      }),
    );
    mount();
    await userEvent.type(screen.getByLabelText(/^Name/), "refunds");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    expect(await screen.findByText("Choose a clearer description")).toBeVisible();
    await userEvent.type(screen.getByLabelText("Description"), "Refund rules");
    expect(screen.queryByText("Choose a clearer description")).toBeNull();
    expect(screen.getByLabelText("Description")).toHaveValue("Refund rules");
  });

  it("toasts a refusal that names no field", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new Error("down"));
    mount();
    await userEvent.type(screen.getByLabelText(/^Name/), "refunds");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("closes on cancel", async () => {
    const { onOpenChange } = mount();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("says a new dataset is the organization's, and starts it private on request", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "d2", name: "drafts" });
    mount();
    expect(screen.queryByLabelText("Description")).toBeNull();
    expect(screen.queryByRole("radio", { name: /Some people/ })).toBeNull();
    expect(screen.getByRole("radio", { name: /Everyone/ })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(screen.getByRole("radio", { name: /Only me/ }));
    expect(screen.getByRole("radio", { name: /Only me/ })).toHaveAttribute("aria-checked", "true");
    await userEvent.click(screen.getByRole("radio", { name: /Everyone/ }));
    await userEvent.click(screen.getByRole("radio", { name: /Only me/ }));
    await userEvent.type(screen.getByLabelText(/^Name/), "drafts");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/datasets",
        expect.objectContaining({ visibility: "private" }),
      ),
    );
  });
});
